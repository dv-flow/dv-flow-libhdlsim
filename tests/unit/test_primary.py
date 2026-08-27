
import os
import pytest
import shutil
import asyncio
from dv_flow.mgr import TaskListenerLog, TaskSetRunner, PackageLoader
from dv_flow.mgr.task_graph_builder import TaskGraphBuilder
import dv_flow.libhdlsim as libhdlsim


def has_xcm():
    """MSIE (primary snapshots) is an Xcelium-only capability."""
    return shutil.which("xmvlog") is not None


@pytest.mark.skipif(not has_xcm(), reason="Xcelium (xmvlog) not available")
def test_primary_snapshot(tmpdir):
    """Xcelium MSIE Type-C: pre-elaborate a stable module into a primary
    snapshot, then bind it into a testbench SimImage without recompiling it.

    Graph:
        mod1 (FileSet)  -> mod1_prim (SimPrimary, top=mod1)
        mod1_top (FileSet, instantiates mod1) +
        mod1_prim       -> sim_img (SimImage, top=mod1_top, -primsnap mod1)
                        -> sim_run (SimRun)
    """
    data_dir = os.path.join(os.path.dirname(__file__), "data", "simlib")
    rundir = os.path.join(tmpdir, "rundir")
    runner = TaskSetRunner(rundir)

    def marker_listener(marker):
        raise Exception("marker: %s" % str(marker))

    builder = TaskGraphBuilder(
        PackageLoader(marker_listeners=[marker_listener]).load_rgy(['std', 'hdlsim.xcm']),
        rundir)
    runner.builder = builder

    # Stable subsystem -> primary snapshot
    mod1 = builder.mkTaskNode(
        "std.FileSet",
        name="mod1",
        type="systemVerilogSource",
        base=os.path.join(data_dir, "mod1"),
        include="*.sv")
    mod1_prim = builder.mkTaskNode(
        "hdlsim.xcm.SimPrimary",
        name="mod1_prim",
        top=["mod1"],
        needs=[mod1])

    # Testbench top instantiates mod1 but is NOT compiled with mod1's sources;
    # the primary binds at elaboration.
    mod1_top = builder.mkTaskNode(
        "std.FileSet",
        name="mod1_top",
        type="systemVerilogSource",
        base=os.path.join(data_dir, "mod1_top"),
        include="*.sv")

    sim_img = builder.mkTaskNode(
        "hdlsim.xcm.SimImage",
        name="sim_img",
        top=["mod1_top"],
        needs=[mod1_prim, mod1_top])

    sim_run = builder.mkTaskNode(
        "hdlsim.xcm.SimRun",
        name="sim_run",
        needs=[sim_img])

    runner.add_listener(TaskListenerLog().event)
    out_l = asyncio.run(runner.run([sim_run]))

    assert runner.status == 0

    # Confirm the simulation actually ran with the bound primary.
    sim_log = None
    for out in out_l:
        for fs in out.output:
            if fs.type == 'std.FileSet' and fs.filetype == "simRunDir":
                log_path = os.path.join(fs.basedir, "sim.log")
                assert os.path.isfile(log_path)
                with open(log_path) as f:
                    sim_log = f.read()

    assert sim_log is not None
    assert sim_log.find("Hello World!") != -1
