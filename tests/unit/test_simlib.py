
import os
import pytest
import shutil
import asyncio
import sys
from dv_flow.mgr import TaskListenerLog, TaskSetRunner, TaskSpec, PackageLoader
from dv_flow.mgr.task_graph_builder import TaskGraphBuilder
from dv_flow.mgr.util import loadProjPkgDef
import dv_flow.libhdlsim as libhdlsim

sims = None

def get_available_sims():
    global sims

    sims = []
    for sim_exe,sim in {
        "iverilog": "ivl",
        "verilator": "vlt",
        "vcs": "vcs",
        "vsim": "mti",
        "xsim": "xsm",
    }.items():
        if shutil.which(sim_exe) is not None:
            sims.append(sim)
    return sims

@pytest.mark.parametrize("sim", get_available_sims())
def test_mod1_top(tmpdir, request, sim):

    data_dir = os.path.join(os.path.dirname(__file__), "data", "simlib")
    runner = TaskSetRunner(os.path.join(tmpdir, 'rundir'))

    def marker_listener(marker):
        raise Exception("marker")

    builder = TaskGraphBuilder(
        PackageLoader(marker_listeners=[marker_listener]).load_rgy(['std', 'hdlsim.%s' % sim]),
        os.path.join(tmpdir, 'rundir'))
    
    mod1 = builder.mkTaskNode(
        "std.FileSet",
        name="mod1",
        type="systemVerilogSource",
        base=os.path.join(data_dir, "mod1"),
        include="*.sv")
    mod1_lib = builder.mkTaskNode(
        "hdlsim.%s.SimLib" % sim,
        name="mod1_lib",
        needs=[mod1])
    
    mod1_top = builder.mkTaskNode(
        "std.FileSet",
        name="mod1_top",
        type="systemVerilogSource",
        base=os.path.join(data_dir, "mod1_top"),
        include="*.sv")

    sim_img = builder.mkTaskNode(
        "hdlsim.%s.SimImage" % sim,
        name="sim_img",
        top=["mod1_top"],
        needs=[mod1_lib, mod1_top])
    
    sim_run = builder.mkTaskNode(
        "hdlsim.%s.SimRun" % sim,
        name="sim_run",
        needs=[sim_img])

    runner.add_listener(TaskListenerLog().event)
    out = asyncio.run(runner.run(sim_run))

    assert runner.status == 0
