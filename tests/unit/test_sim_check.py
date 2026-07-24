
# Unit test for the SimUVMCheck / SimCheck pytasks (P1.4). No simulator: we
# hand-build a SimRunResult whose simLog artifact points at a committed fixture
# log, then drive the pytask with a minimal TaskRunCtxt (the TaskGraphBuilder
# supplies mkDataItem) and assert the emitted TestResult verdict.

import os
import types
import asyncio
import pytest
from dv_flow.mgr import PackageLoader, FileSet
from dv_flow.mgr.task_graph_builder import TaskGraphBuilder
from dv_flow.mgr.task_run_ctxt import TaskRunCtxt
from dv_flow.mgr.task_data import SeverityE
from dv_flow.libhdlsim.sim_check import SimUVMCheck, SimCheck, SimSuiteReport

LOGDIR = os.path.join(os.path.dirname(__file__), "data/uvm_logs")


def _mk(tmpdir):
    loader = PackageLoader().load_rgy(["std", "hdlsim"])
    b = TaskGraphBuilder(loader, str(tmpdir))
    ctxt = TaskRunCtxt(runner=b, ctxt=None, rundir=str(tmpdir))
    return b, ctxt


def _run_result(b, logname, status=0):
    log = FileSet(filetype="simLog", basedir=LOGDIR, files=[logname],
                  attributes=["role=log"])
    return b.mkDataItem("hdlsim.SimRunResult",
                        status=status, sim="vlt", mode="test",
                        walltime_s=0.04, artifacts=[log])


def _input(result, name="case0", testname="wb_dma_sw_copy_test", rundir="/tmp"):
    return types.SimpleNamespace(
        inputs=[result],
        params=types.SimpleNamespace(name=name, testname=testname),
        rundir=rundir,
        name=name)


def _errors(ctxt):
    return [m for m in ctxt._markers if m.severity == SeverityE.Error]


def test_uvmcheck_pass(tmpdir):
    b, ctxt = _mk(tmpdir)
    res = _run_result(b, "pass_sw_copy.log")
    out = asyncio.run(SimUVMCheck(ctxt, _input(res)))
    assert out.status == 0
    tr = out.output[0]
    assert tr.type == "hdlsim.TestResult"
    assert tr.passed is True
    assert tr.status == "pass"
    assert tr.errors == 0
    assert tr.name == "case0"
    assert tr.testname == "wb_dma_sw_copy_test"
    # artifacts forwarded
    assert any(fs.filetype == "simLog" for fs in tr.artifacts)
    assert _errors(ctxt) == []


def test_uvmcheck_fail_is_verdict_not_error_marker(tmpdir):
    b, ctxt = _mk(tmpdir)
    res = _run_result(b, "fail_uvm_error.log", status=0)
    out = asyncio.run(SimUVMCheck(ctxt, _input(res, testname="wb_dma_err_test")))
    # Verdict-as-data: failing test does NOT fail the task...
    assert out.status == 0
    tr = out.output[0]
    assert tr.passed is False
    assert tr.status == "fail"
    assert tr.errors == 3
    # ...and emits NO Error marker (which would drop the cell from a suite's
    # aggregation). The verdict lives in the TestResult; the gate is the report.
    assert _errors(ctxt) == []


def test_uvmcheck_missing_log_is_infra_error(tmpdir):
    b, ctxt = _mk(tmpdir)
    # SimRunResult with an artifact pointing at a nonexistent file, and a rundir
    # that has no sim.log -> the check cannot find a log -> task fails (status 1).
    log = FileSet(filetype="simLog", basedir=str(tmpdir), files=["nope.log"])
    res = b.mkDataItem("hdlsim.SimRunResult", status=0, sim="vlt", mode="test",
                       artifacts=[log])
    out = asyncio.run(SimUVMCheck(ctxt, _input(res, rundir=str(tmpdir))))
    assert out.status == 1
    assert len(_errors(ctxt)) == 1


def test_uvmcheck_no_result_input(tmpdir):
    b, ctxt = _mk(tmpdir)
    inp = types.SimpleNamespace(
        inputs=[], params=types.SimpleNamespace(name="c", testname="t"),
        rundir=str(tmpdir), name="c")
    out = asyncio.run(SimUVMCheck(ctxt, inp))
    assert out.status == 1


def test_generic_simcheck_uses_exit_code(tmpdir):
    b, ctxt = _mk(tmpdir)
    # Generic base: verdict is the exit code, not the log contents.
    res = _run_result(b, "pass_sw_copy.log", status=7)
    out = asyncio.run(SimCheck(ctxt, _input(res)))
    tr = out.output[0]
    assert tr.passed is False
    assert tr.run_status == 7
    assert out.status == 0


def test_uvmcheck_falls_back_to_rundir_log(tmpdir):
    # No simLog artifact, but sim.log sits in the shared rundir -> found.
    b, ctxt = _mk(tmpdir)
    import shutil
    shutil.copy(os.path.join(LOGDIR, "pass_sw_copy.log"),
                os.path.join(str(tmpdir), "sim.log"))
    res = b.mkDataItem("hdlsim.SimRunResult", status=0, sim="vlt",
                       mode="test", artifacts=[])
    out = asyncio.run(SimUVMCheck(ctxt, _input(res, rundir=str(tmpdir))))
    assert out.status == 0
    assert out.output[0].passed is True


def _input_uvm(result, name="c", testname="t", rundir="/tmp"):
    return types.SimpleNamespace(
        inputs=[result],
        params=types.SimpleNamespace(name=name, testname=testname, uvm=True),
        rundir=rundir, name=name)


def test_simcheck_dispatches_to_uvm_when_uvm_true(tmpdir):
    # SimCheck with uvm=True must use the UVM log parser (a clean exit code but
    # UVM_ERROR>0 in the log -> fail), NOT the exit code.
    b, ctxt = _mk(tmpdir)
    res = _run_result(b, "fail_uvm_error.log", status=0)  # exit 0, but 3 errors
    out = asyncio.run(SimCheck(ctxt, _input_uvm(res)))
    tr = out.output[0]
    assert tr.passed is False        # exit-code path would have said pass
    assert tr.status == "fail"
    assert tr.errors == 3


# ---- SimSuiteReport ------------------------------------------------------

def _tr(b, name, passed, status):
    tr = b.mkDataItem("hdlsim.TestResult", passed=passed, status=status)
    tr.name = name
    return tr


def test_suite_report_all_pass(tmpdir):
    b, ctxt = _mk(tmpdir)
    inp = types.SimpleNamespace(inputs=[
        _tr(b, "a", True, "pass"), _tr(b, "b", True, "pass")])
    out = asyncio.run(SimSuiteReport(ctxt, inp))
    assert out.status == 0
    sr = out.output[0]
    assert (sr.total, sr.passed, sr.failed, sr.errored) == (2, 2, 0, 0)


def test_suite_report_gates_on_failure(tmpdir):
    b, ctxt = _mk(tmpdir)
    inp = types.SimpleNamespace(inputs=[
        _tr(b, "a", True, "pass"),
        _tr(b, "b", False, "fail"),
        _tr(b, "c", False, "timeout")])
    out = asyncio.run(SimSuiteReport(ctxt, inp))
    # Nonzero gate iff any case did not pass.
    assert out.status == 1
    sr = out.output[0]
    assert (sr.total, sr.passed, sr.failed, sr.errored) == (3, 1, 1, 1)
    # every case is still present in the roll-up
    assert len(sr.results) == 3
