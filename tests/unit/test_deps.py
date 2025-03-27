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
def test_simple_1(tmpdir, request,sim):

    data_dir = os.path.join(os.path.dirname(__file__), "data")
    rgy = PkgRgy()
    rgy._discover_plugins()


    def run(status):
        runner = TaskSetRunner(os.path.join(tmpdir, 'rundir'))
        builder = TaskGraphBuilder(
            None, 
            os.path.join(tmpdir, 'rundir'),
            pkg_rgy=rgy)

        fileset_t = builder.getTaskCtor('std.FileSet')

        top_v = builder.mkTaskNode(
            'std.FileSet', name="top_v",  
            type="systeVerilogSource", base=data_dir, include="*.v")

        sim_img = builder.mkTaskNode(
            'hdlsim.%s.SimImage' % sim, name="sim_img", needs=[top_v], 
            top=["top"])

        sim_run = builder.mkTaskNode(
            'hdlsim.%s.SimRun' % sim, name="sim_run", needs=[sim_img])

        def listener(task, reason):
            if reason == "leave":
                status.append((task, reason))

        runner.add_listener(listener)
        return asyncio.run(runner.run(sim_run))

    status = []
    out_1 = run(status)
    # for s in status:
    #     print("status: %s %s" % (s[0].name, s[0].output.changed))
    assert status[-2][0].output.changed == True
    status.clear()
    out_2 = run(status)
    # for s in status:
    #     print("status: %s %s" % (s[0].name, s[0].output.changed))
    assert status[-2][0].output.changed == False

