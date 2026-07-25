
# Tests for the SimRun `mode` param + SimRunResult output (P1.2).
#
#  mode: run  (default) -- a nonzero simulator exit FAILS the task.
#  mode: test           -- a nonzero simulator exit does NOT fail the task;
#                          the exit code rides in the emitted SimRunResult and
#                          a downstream Check task decides the verdict.
#
# Both modes emit a SimRunResult carrying `status`, `sim`, `mode`, and the
# collected artifact FileSets (at least a `simLog`).

import json
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


@pytest.mark.skipif(not HAVE_VLT, reason="verilator not available")
def test_simrun_emits_stats_and_runinfo(tmpdir):
    """End-to-end: a real Verilator run must publish the three collection tiers
    it can reach -- host process, simulator report, and provenance -- plus the
    durable sim_stats.json record."""
    runner, sim_run = _build_fail_run(tmpdir, "test")
    out_l = asyncio.run(runner.run([sim_run]))
    result = _find_result(out_l)
    assert result is not None

    stats, runinfo = result.stats, result.runinfo

    # Tier 1 (host process): always available, whatever the simulator prints.
    assert stats["walltime_s"] > 0
    assert "cpu_total_s" in stats and "maxrss_mb" in stats

    # Tier 2 (Verilator's own end-of-run report). $fatal exits before $finish,
    # so only assert what a report-bearing run must have; simtime rides along
    # when the summary was printed.
    if "simtime" in stats:
        assert stats["simtime_s"] > 0
        assert runinfo["sim_version"].startswith("Verilator")

    # Provenance: enough to re-run this case by hand.
    assert runinfo["sim"] == "vlt"
    assert runinfo["mode"] == "test"
    assert runinfo["cmd"][0].endswith("simv")
    assert runinfo["exit_code"] == result.status
    assert runinfo["start_time"] and runinfo["end_time"]
    # No seed was applied -> the key is ABSENT rather than a fabricated 0.
    assert "seed" not in runinfo

    # The durable record, and its artifact FileSet.
    stats_fs = [fs for fs in result.artifacts if fs.filetype == "simStats"]
    assert len(stats_fs) == 1
    path = os.path.join(stats_fs[0].basedir, stats_fs[0].files[0])
    with open(path) as fp:
        doc = json.load(fp)
    assert doc["stats"]["walltime_s"] == stats["walltime_s"]
    assert doc["runinfo"]["sim"] == "vlt"
