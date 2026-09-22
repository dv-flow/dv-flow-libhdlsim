
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


def test_suite_report_fails_when_no_tests_ran(tmpdir):
    """Zero failures out of zero tests satisfies every other check, so without
    an explicit guard a mistyped selector, an empty suite, or a miswired
    `needs:` all present as a GREEN run -- the one outcome a test gate must
    never produce quietly."""
    b, ctxt = _mk(tmpdir)
    out = asyncio.run(SimSuiteReport(ctxt, types.SimpleNamespace(inputs=[])))
    assert out.status == 1
    assert out.output[0].total == 0


def test_suite_report_writes_junit(tmpdir):
    b, ctxt = _mk(tmpdir)
    rundir = str(tmpdir)
    inp = types.SimpleNamespace(
        inputs=[_tr(b, "ok", True, "pass"),
                _tr(b, "bad", False, "fail"),
                _tr(b, "dead", False, "timeout")],
        params=types.SimpleNamespace(junit=True),
        rundir=rundir, name="suite")
    out = asyncio.run(SimSuiteReport(ctxt, inp))

    path = os.path.join(rundir, "junit.xml")
    assert os.path.exists(path)
    with open(path) as f:
        xml = f.read()
    # Well-formed, and the failure/error distinction CI UIs draw is preserved.
    import xml.etree.ElementTree as ET
    root = ET.fromstring(xml)
    assert root.get("tests") == "3"
    assert root.get("failures") == "1"
    assert root.get("errors") == "1"
    names = sorted(tc.get("name") for tc in root.findall("testcase"))
    assert names == ["bad", "dead", "ok"]
    assert any(a.filetype == "junitXml" for a in out.output
               if hasattr(a, "filetype"))


def test_junit_can_be_turned_off(tmpdir):
    b, ctxt = _mk(tmpdir)
    inp = types.SimpleNamespace(
        inputs=[_tr(b, "ok", True, "pass")],
        params=types.SimpleNamespace(junit=False),
        rundir=str(tmpdir), name="suite")
    asyncio.run(SimSuiteReport(ctxt, inp))
    assert not os.path.exists(os.path.join(str(tmpdir), "junit.xml"))


def test_a_junit_write_failure_does_not_change_the_verdict(tmpdir):
    """A report-format problem is not a test result."""
    b, ctxt = _mk(tmpdir)
    inp = types.SimpleNamespace(
        inputs=[_tr(b, "ok", True, "pass")],
        params=types.SimpleNamespace(junit=True),
        rundir=os.path.join(str(tmpdir), "does", "not", "exist"), name="suite")
    out = asyncio.run(SimSuiteReport(ctxt, inp))
    assert out.status == 0


# ---- stats / runinfo forwarding + suite roll-up --------------------------

_STATS = {"walltime_s": 1.5, "cpu_total_s": 1.4, "maxrss_mb": 300.0,
          "simtime": "608us", "simtime_s": 608e-6}
_RUNINFO = {"sim": "vlt", "seed": 4242, "seed_source": "+verilator+seed",
            "plusargs": ["UVM_TESTNAME=t"], "finish_reason": "$finish",
            "host": "h1"}


def _run_result_stats(b, logname, status=0):
    log = FileSet(filetype="simLog", basedir=LOGDIR, files=[logname],
                  attributes=["role=log"])
    return b.mkDataItem("hdlsim.SimRunResult",
                        status=status, sim="vlt", mode="test", walltime_s=1.5,
                        stats=dict(_STATS), runinfo=dict(_RUNINFO),
                        artifacts=[log])


def test_uvmcheck_forwards_stats_and_runinfo(tmpdir):
    b, ctxt = _mk(tmpdir)
    out = asyncio.run(SimUVMCheck(ctxt, _input(_run_result_stats(b, "pass_sw_copy.log"))))
    tr = out.output[0]
    assert tr.stats["maxrss_mb"] == 300.0
    assert tr.stats["simtime"] == "608us"
    # The check tier ADDS the log-derived severity tallies to the map...
    assert tr.stats["errors"] == 0 and "warnings" in tr.stats
    # ...and promotes the seed, which the run recorded from its arguments.
    assert tr.runinfo["seed"] == 4242
    assert tr.seed == 4242


def test_generic_simcheck_forwards_stats_and_runinfo(tmpdir):
    b, ctxt = _mk(tmpdir)
    out = asyncio.run(SimCheck(ctxt, _input(_run_result_stats(b, "pass_sw_copy.log"))))
    tr = out.output[0]
    assert tr.stats["cpu_total_s"] == 1.4
    assert tr.runinfo["finish_reason"] == "$finish"
    assert tr.seed == 4242


def test_check_tolerates_a_result_without_stats(tmpdir):
    # A SimRunResult from a producer that never set stats/runinfo must still
    # check cleanly -- the maps are simply empty.
    b, ctxt = _mk(tmpdir)
    out = asyncio.run(SimUVMCheck(ctxt, _input(_run_result(b, "pass_sw_copy.log"))))
    tr = out.output[0]
    assert tr.runinfo == {} and tr.seed == 0
    assert tr.stats["errors"] == 0     # tallies are always added
    assert tr.passed is True


def _tr_stats(b, name, passed, status, stats, runinfo=None):
    tr = b.mkDataItem("hdlsim.TestResult", passed=passed, status=status,
                      walltime_s=stats.get("walltime_s", 0.0),
                      stats=dict(stats), runinfo=dict(runinfo or {}))
    tr.name = name
    return tr


def test_suite_report_aggregates_stats(tmpdir):
    b, ctxt = _mk(tmpdir)
    inp = types.SimpleNamespace(
        inputs=[_tr_stats(b, "a", True, "pass",
                          {"walltime_s": 1.0, "maxrss_mb": 100.0, "errors": 0}),
                _tr_stats(b, "b", True, "pass",
                          {"walltime_s": 3.0, "maxrss_mb": 250.0, "errors": 0,
                           "simtime_s": 1e-3})],
        params=types.SimpleNamespace(junit=True), rundir=str(tmpdir), name="suite")
    out = asyncio.run(SimSuiteReport(ctxt, inp))
    sr = out.output[0]
    assert sr.stats["walltime_s"] == 4.0
    assert sr.stats["walltime_s_max"] == 3.0
    assert sr.stats["maxrss_mb_max"] == 250.0
    # Peak memory is a max, never a sum -- summing it would report a number no
    # machine ever had to supply.
    assert "maxrss_mb" not in sr.stats


def test_suite_report_writes_report_json(tmpdir):
    b, ctxt = _mk(tmpdir)
    inp = types.SimpleNamespace(
        inputs=[_tr_stats(b, "a", True, "pass", _STATS, _RUNINFO),
                _tr_stats(b, "b", False, "fail", {"walltime_s": 2.0})],
        params=types.SimpleNamespace(junit=True), rundir=str(tmpdir), name="suite")
    out = asyncio.run(SimSuiteReport(ctxt, inp))

    import json
    with open(os.path.join(str(tmpdir), "report.json")) as fp:
        doc = json.load(fp)
    assert doc["counts"] == {"total": 2, "passed": 1, "failed": 1, "errored": 0}
    assert doc["stats"]["walltime_s"] == 3.5
    cases = {c["name"]: c for c in doc["cases"]}
    assert cases["a"]["runinfo"]["seed"] == 4242
    assert cases["a"]["stats"]["simtime"] == "608us"
    assert cases["b"]["passed"] is False
    assert any(getattr(a, "filetype", "") == "simReportJson" for a in out.output)


def test_junit_carries_seed_and_metrics_as_properties(tmpdir):
    b, ctxt = _mk(tmpdir)
    inp = types.SimpleNamespace(
        inputs=[_tr_stats(b, "a", True, "pass", _STATS, _RUNINFO)],
        params=types.SimpleNamespace(junit=True), rundir=str(tmpdir), name="suite")
    asyncio.run(SimSuiteReport(ctxt, inp))
    import xml.etree.ElementTree as ET
    root = ET.parse(os.path.join(str(tmpdir), "junit.xml")).getroot()
    props = {p.get("name"): p.get("value")
             for p in root.iter("property")}
    # The reproduction handles must survive into the CI test view.
    assert props["seed"] == "4242"
    assert props["sim"] == "vlt"
    assert props["simtime"] == "608us"


def test_report_json_write_failure_does_not_change_the_verdict(tmpdir):
    b, ctxt = _mk(tmpdir)
    inp = types.SimpleNamespace(
        inputs=[_tr_stats(b, "a", True, "pass", _STATS)],
        params=types.SimpleNamespace(junit=False),
        rundir=os.path.join(str(tmpdir), "nope"), name="suite")
    out = asyncio.run(SimSuiteReport(ctxt, inp))
    assert out.status == 0


# ---- CTRF ----------------------------------------------------------------

def _ctrf(tmpdir):
    import json
    with open(os.path.join(str(tmpdir), "ctrf.json")) as fp:
        return json.load(fp)


def test_suite_report_writes_ctrf(tmpdir):
    b, ctxt = _mk(tmpdir)
    inp = types.SimpleNamespace(
        inputs=[_tr(b, "ok", True, "pass"),
                _tr(b, "bad", False, "fail"),
                _tr(b, "dead", False, "timeout")],
        params=types.SimpleNamespace(junit=True, ctrf=True),
        rundir=str(tmpdir), name="suite")
    out = asyncio.run(SimSuiteReport(ctxt, inp))

    doc = _ctrf(tmpdir)
    assert doc["reportFormat"] == "CTRF"
    summary = doc["results"]["summary"]
    assert (summary["tests"], summary["passed"], summary["failed"]) == (3, 1, 2)
    assert summary["start"] <= summary["stop"]
    tests = {t["name"]: t for t in doc["results"]["tests"]}
    # CTRF has one `failed`; the fail/timeout distinction survives in rawStatus.
    assert tests["bad"]["status"] == "failed" and tests["bad"]["rawStatus"] == "fail"
    assert tests["dead"]["status"] == "failed" and tests["dead"]["rawStatus"] == "timeout"
    assert tests["ok"]["status"] == "passed"
    assert any(getattr(a, "filetype", "") == "ctrfJson" for a in out.output)


def test_ctrf_carries_seed_and_metrics(tmpdir):
    b, ctxt = _mk(tmpdir)
    runinfo = dict(_RUNINFO, start_time="2026-09-22T20:00:27+00:00",
                   end_time="2026-09-22T20:00:29+00:00")
    inp = types.SimpleNamespace(
        inputs=[_tr_stats(b, "a", False, "fail", _STATS, runinfo)],
        params=types.SimpleNamespace(junit=False, ctrf=True),
        rundir=str(tmpdir), name="suite")
    asyncio.run(SimSuiteReport(ctxt, inp))

    doc = _ctrf(tmpdir)
    t = doc["results"]["tests"][0]
    # The reproduction handles are in the message a CI view shows unexpanded...
    assert "seed=4242" in t["message"] and "sim=vlt" in t["message"]
    # ...and in `extra` for anything that reads the file.
    assert t["extra"]["seed"] == 4242
    assert t["extra"]["simtime"] == "608us"
    assert t["duration"] == 1500
    summary = doc["results"]["summary"]
    assert summary["stop"] - summary["start"] == 2000


def test_ctrf_can_be_turned_off(tmpdir):
    b, ctxt = _mk(tmpdir)
    inp = types.SimpleNamespace(
        inputs=[_tr(b, "ok", True, "pass")],
        params=types.SimpleNamespace(junit=False, ctrf=False),
        rundir=str(tmpdir), name="suite")
    asyncio.run(SimSuiteReport(ctxt, inp))
    assert not os.path.exists(os.path.join(str(tmpdir), "ctrf.json"))


def test_a_ctrf_write_failure_does_not_change_the_verdict(tmpdir):
    b, ctxt = _mk(tmpdir)
    inp = types.SimpleNamespace(
        inputs=[_tr(b, "ok", True, "pass")],
        params=types.SimpleNamespace(junit=False, ctrf=True),
        rundir=os.path.join(str(tmpdir), "does", "not", "exist"), name="suite")
    out = asyncio.run(SimSuiteReport(ctxt, inp))
    assert out.status == 0
