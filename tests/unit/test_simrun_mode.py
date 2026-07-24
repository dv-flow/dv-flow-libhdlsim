
# Tests for the SimRun `mode` param + SimRunResult output (P1.2).
#
#  mode: run  (default) -- a nonzero simulator exit FAILS the task.
#  mode: test           -- a nonzero simulator exit does NOT fail the task;
#                          the exit code rides in the emitted SimRunResult and
#                          a downstream Check task decides the verdict.
#
# Both modes emit a SimRunResult carrying `status`, `sim`, `mode`, and the
# collected artifact FileSets (at least a `simLog`).

import os
import shutil
import asyncio
import pytest
from dv_flow.mgr import TaskListenerLog, TaskSetRunner, PackageLoader
from dv_flow.mgr.task_graph_builder import TaskGraphBuilder

HAVE_VLT = shutil.which("verilator") is not None
DATA_DIR = os.path.join(os.path.dirname(__file__), "data/simrun")


def _build_fail_run(tmpdir, mode):
    """Build an image from a $fatal testbench and a SimRun node in `mode`.

    Returns (runner, sim_run_node). Marker listener does NOT raise here (unlike
    test_simrun.py) because the failing sim legitimately emits error markers.
    """
    rundir = os.path.join(tmpdir, "rundir")
    runner = TaskSetRunner(rundir)
    builder = TaskGraphBuilder(
        PackageLoader().load_rgy(["std", "hdlsim.vlt"]), rundir)
    runner.builder = builder

    top = builder.mkTaskNode(
        "std.FileSet", name="top",
        type="systemVerilogSource", base=DATA_DIR, include="simrun_fail.sv")
    sim_img = builder.mkTaskNode(
        "hdlsim.vlt.SimImage", name="sim_img", needs=[top], top=["simrun_fail"])
    sim_run = builder.mkTaskNode(
        "hdlsim.vlt.SimRun", name="sim_run", needs=[sim_img], mode=mode,
        sim="vlt")

    runner.add_listener(TaskListenerLog().event)
    return runner, sim_run


def _find_result(out_l):
    for out in out_l:
        for item in out.output:
            if getattr(item, "type", None) == "hdlsim.SimRunResult":
                return item
    return None


@pytest.mark.skipif(not HAVE_VLT, reason="verilator not available")
def test_mode_test_tolerates_nonzero_exit(tmpdir):
    runner, sim_run = _build_fail_run(tmpdir, "test")
    out_l = asyncio.run(runner.run([sim_run]))

    # The failing sim must NOT fail the task in test mode.
    assert runner.status == 0

    result = _find_result(out_l)
    assert result is not None, "SimRun did not emit a SimRunResult"
    assert result.mode == "test"
    assert result.sim == "vlt"  # threaded from the sim param
    # $fatal -> nonzero exit carried as data, not as task failure.
    assert result.status != 0

    # A simLog artifact must be present and readable.
    logs = [fs for fs in result.artifacts if fs.filetype == "simLog"]
    assert len(logs) == 1
    log_fs = logs[0]
    log_path = os.path.join(log_fs.basedir, log_fs.files[0])
    assert os.path.isfile(log_path)
    with open(log_path) as f:
        assert "simrun_fail: about to fatal" in f.read()


@pytest.mark.skipif(not HAVE_VLT, reason="verilator not available")
def test_mode_run_fails_on_nonzero_exit(tmpdir):
    runner, sim_run = _build_fail_run(tmpdir, "run")
    # run() returns None when a requested task fails, so we assert on status.
    asyncio.run(runner.run([sim_run]))

    # Default run mode: a nonzero simulator exit fails the task.
    assert runner.status != 0
