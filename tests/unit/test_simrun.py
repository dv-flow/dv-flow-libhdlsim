
import os
import pytest
import shutil
import asyncio
import sys
from dv_flow.mgr import TaskListenerLog, TaskSetRunner
from dv_flow.mgr.pkg_rgy import PkgRgy
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
def test_plusarg(tmpdir, request, sim):

    data_dir = os.path.join(os.path.dirname(__file__), "data/simrun")
    runner = TaskSetRunner(os.path.join(tmpdir, 'rundir'))
    rgy = PkgRgy()
    rgy._discover_plugins()

    builder = TaskGraphBuilder(
        None, 
        os.path.join(tmpdir, 'rundir'),
        pkg_rgy=rgy)

    top = builder.mkTaskNode(
        task_t="std.FileSet",
        name="top",  
        type="systemVerilogSource", 
        base=os.path.join(data_dir), include="simrun_plusarg.sv")

    sim_img = builder.mkTaskNode(
        task_t='hdlsim.%s.SimImage' % sim,
        name="sim_img", needs=[top], top=["simrun_plusarg"])

    sim_run = builder.mkTaskNode(
        'hdlsim.%s.SimRun' % sim, 
        name="sim_run",
        needs=[sim_img],
        plusargs=["myarg=you"])

    runner.add_listener(TaskListenerLog().event)
    out_l = asyncio.run(runner.run([sim_run]))

    assert runner.status == 0

    for out in out_l:
        rundir_fs = None
        for fs in out.output:
            if fs.type == 'std.FileSet' and fs.filetype == "simRunDir":
                rundir_fs = fs

        assert rundir_fs is not None
        assert rundir_fs.src in ("sim_run",)

        assert os.path.isfile(os.path.join(rundir_fs.basedir, "sim.log"))
        with open(os.path.join(rundir_fs.basedir, "sim.log"), "r") as f:
            sim_log = f.read()
    
        assert sim_log.find("Hello World: you") != -1
