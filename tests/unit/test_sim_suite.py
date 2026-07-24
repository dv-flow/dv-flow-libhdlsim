
# Integration test for a suite: two SimUVMCase cases (one intentional fail)
# feeding SimSuiteReport. Verifies the suite TOLERATES a failing case (both run
# and are reported) yet GATES on it (report task status nonzero). Verilator-
# guarded. This mirrors the tests/uvm/flow.yaml pattern: one SimUVMCase per
# scenario + one SimSuiteReport gate.

import os
import shutil
import asyncio
import pytest
from dv_flow.mgr import TaskListenerLog, TaskSetRunner, PackageLoader
from dv_flow.mgr.task_graph_builder import TaskGraphBuilder

HAVE_VLT = shutil.which("verilator") is not None
DATA_DIR = os.path.join(os.path.dirname(__file__), "data/simrun")
pytestmark = pytest.mark.skipif(not HAVE_VLT, reason="verilator not available")


def _mk(tmpdir):
    rundir = os.path.join(tmpdir, "rundir")
    runner = TaskSetRunner(rundir)
    builder = TaskGraphBuilder(
        PackageLoader().load_rgy(["std", "hdlsim", "hdlsim.vlt"]), rundir)
    runner.builder = builder
    runner.add_listener(TaskListenerLog().event)
    return runner, builder


def test_suite_tolerates_and_gates(tmpdir):
    runner, b = _mk(tmpdir)
    src = b.mkTaskNode("std.FileSet", name="src", type="systemVerilogSource",
                       base=DATA_DIR, include="simrun_uvm.sv")
    img = b.mkTaskNode("hdlsim.vlt.SimImage", name="img", needs=[src],
                       top=["simrun_uvm"])
    ok = b.mkTaskNode("hdlsim.vlt.SimUVMCase", name="ok", needs=[img],
                      testname="wb_dma_sw_copy_test")
    bad = b.mkTaskNode("hdlsim.vlt.SimUVMCase", name="bad", needs=[img],
                       testname="wb_dma_err_test", plusargs=["fail"])
    report = b.mkTaskNode("hdlsim.SimSuiteReport", name="report", needs=[ok, bad])

    asyncio.run(runner.run([report]))

    # The report gates: nonzero status iff any case failed.
    assert runner.status != 0

    sr = next(it for it in report.output.output
              if getattr(it, "type", None) == "hdlsim.SuiteResult")
    assert sr.total == 2
    assert sr.passed == 1
    assert sr.failed == 1
    assert len(sr.results) == 2
    # both cases present (distinct leaf tasks -> no compound collision)
    names = sorted(r.name for r in sr.results)
    assert names == ["wb_dma_err_test", "wb_dma_sw_copy_test"]
    bad_tr = next(r for r in sr.results if r.name == "wb_dma_err_test")
    assert bad_tr.passed is False


# A matrix over (testname, plusargs) pairs -> one SimUVMCase per cell -> report.
# This is the most compact suite form (tests/uvm/flow.yaml uses it) and exercises
# runtime matrix aggregation of leaf-cell TestResults into the report.
# Concrete vlt tasks + top-level matrix (mirrors tests/uvm/flow.yaml). A matrix
# nested in a `set:` region cannot resolve `this.case`, so selection is via the
# concrete `hdlsim.vlt.*` tasks instead.
_MATRIX_FLOW = """\
package:
  name: tmx
  imports:
    - name: hdlsim
  tasks:
  - name: src
    uses: std.FileSet
    with: {{type: systemVerilogSource, base: "{data}", include: "simrun_uvm.sv"}}
  - name: img
    uses: hdlsim.vlt.SimImage
    needs: [src]
    with: {{top: [simrun_uvm]}}
  - name: cases
    strategy:
      matrix:
        case:
        - {{ testname: wb_dma_sw_copy_test, plusargs: [] }}
        - {{ testname: wb_dma_err_test,     plusargs: [fail] }}
    body:
    - name: "${{{{ this.case.testname }}}}"
      uses: hdlsim.vlt.SimUVMCase
      needs: [img]
      with:
        testname: "${{{{ this.case.testname }}}}"
        plusargs: "${{{{ this.case.plusargs }}}}"
  - name: report
    uses: hdlsim.SimSuiteReport
    needs: [cases]
"""


def test_matrix_suite_tolerates_and_gates(tmpdir):
    d = str(tmpdir)
    with open(os.path.join(d, "flow.dv"), "w") as f:
        f.write(_MATRIX_FLOW.format(data=DATA_DIR))
    loader = PackageLoader()
    pkg = loader.load(os.path.join(d, "flow.dv"))
    rundir = os.path.join(d, "rundir")
    builder = TaskGraphBuilder(root_pkg=pkg, rundir=rundir, loader=loader)
    runner = TaskSetRunner(rundir)
    runner.builder = builder
    runner.add_listener(TaskListenerLog().event)

    report = builder.mkTaskNode("tmx.report")
    asyncio.run(runner.run([report]))
    assert runner.status != 0  # gate fires on the failing case

    sr = next(it for it in report.output.output
              if getattr(it, "type", None) == "hdlsim.SuiteResult")
    assert (sr.total, sr.passed, sr.failed) == (2, 1, 1)
    assert sorted(r.name for r in sr.results) == \
        ["wb_dma_err_test", "wb_dma_sw_copy_test"]
