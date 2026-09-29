
# Integration tests for the leaf SimUVMCase (run + UVM verdict in one task),
# run for every available UVM-capable simulator. Uses a tiny module that prints
# a UVM report summary (no real UVM build) so the run + parse path is exercised
# end to end. Also checks that TWO SimUVMCase instances both produce their
# TestResult (the whole point of the leaf form -- distinct node names, no
# compound multi-instance collision).

import os
import asyncio
import pytest
from dv_flow.mgr import TaskListenerLog, TaskSetRunner, PackageLoader
from dv_flow.mgr.task_graph_builder import TaskGraphBuilder

from .sims import get_available_sims

DATA_DIR = os.path.join(os.path.dirname(__file__), "data/simrun")
SIMS = get_available_sims(uvm=True)


def _mk(tmpdir, sim):
    rundir = os.path.join(tmpdir, "rundir")
    runner = TaskSetRunner(rundir)
    builder = TaskGraphBuilder(
        PackageLoader().load_rgy(["std", "hdlsim", "hdlsim.%s" % sim]), rundir)
    runner.builder = builder
    runner.add_listener(TaskListenerLog().event)
    return runner, builder


def _image(builder, sim):
    src = builder.mkTaskNode("std.FileSet", name="src",
                             type="systemVerilogSource", base=DATA_DIR,
                             include="simrun_uvm.sv")
    return builder.mkTaskNode("hdlsim.%s.SimImage" % sim, name="img",
                              needs=[src], top=["simrun_uvm"])


def _find(out_l, type_):
    out = []
    for o in out_l or []:
        for it in o.output:
            if getattr(it, "type", None) == type_:
                out.append(it)
    return out


@pytest.mark.parametrize("sim", SIMS)
def test_uvmcase_pass(tmpdir, sim):
    runner, b = _mk(tmpdir, sim)
    img = _image(b, sim)
    case = b.mkTaskNode("hdlsim.%s.SimUVMCase" % sim, name="arb", needs=[img],
                        testname="wb_dma_arb_test", plusargs=["CMP_BY_CHANNEL"])
    out_l = asyncio.run(runner.run([case]))
    assert runner.status == 0
    trs = _find(out_l, "hdlsim.TestResult")
    assert len(trs) == 1
    tr = trs[0]
    assert tr.passed is True
    assert tr.testname == "wb_dma_arb_test"
    assert tr.name == "wb_dma_arb_test"  # `name` defaults to testname
    assert tr.errors == 0
    # +UVM_TESTNAME was composed onto the run, and a simLog artifact is attached.
    assert any(fs.filetype == "simLog" for fs in tr.artifacts)


@pytest.mark.parametrize("sim", SIMS)
def test_uvmcase_fail_is_verdict_not_task_failure(tmpdir, sim):
    runner, b = _mk(tmpdir, sim)
    img = _image(b, sim)
    case = b.mkTaskNode("hdlsim.%s.SimUVMCase" % sim, name="err", needs=[img],
                        testname="wb_dma_err_test", plusargs=["fail"])
    out_l = asyncio.run(runner.run([case]))
    # Verdict-as-data: a failing UVM test does NOT fail the task.
    assert runner.status == 0
    tr = _find(out_l, "hdlsim.TestResult")[0]
    assert tr.passed is False
    assert tr.status == "fail"
    assert tr.errors == 2


# xsm: concurrent runs from one image race. xsim regenerates
# xsim.dir/simv.snap/xsim_script.tcl inside the shared image on every run, so
# one run can pick up the other's plusargs.
_TWO_CASE_SIMS = [
    pytest.param(s, marks=pytest.mark.xfail(
        strict=True, reason="xsm: concurrent runs share xsim_script.tcl"))
    if s == "xsm" else s for s in SIMS]


@pytest.mark.parametrize("sim", _TWO_CASE_SIMS)
def test_two_uvmcases_both_report(tmpdir, sim):
    # The leaf form's raison d'etre: two instances both produce a TestResult
    # (a repeated compound would drop one to node-name collision).
    runner, b = _mk(tmpdir, sim)
    img = _image(b, sim)
    ok = b.mkTaskNode("hdlsim.%s.SimUVMCase" % sim, name="ok", needs=[img],
                      testname="wb_dma_sw_copy_test")
    bad = b.mkTaskNode("hdlsim.%s.SimUVMCase" % sim, name="bad", needs=[img],
                       testname="wb_dma_err_test", plusargs=["fail"])
    out_l = asyncio.run(runner.run([ok, bad]))
    trs = _find(out_l, "hdlsim.TestResult")
    # name defaults to testname -> two distinct TestResults, both present.
    by_name = {tr.name: tr for tr in trs}
    assert set(by_name) == {"wb_dma_sw_copy_test", "wb_dma_err_test"}
    assert by_name["wb_dma_sw_copy_test"].passed is True
    assert by_name["wb_dma_err_test"].passed is False
