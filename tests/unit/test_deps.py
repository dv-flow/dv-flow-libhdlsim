import os
import pytest
import shutil
import asyncio
import sys
import time
from dv_flow.mgr import TaskListenerLog, TaskSetRunner, TaskSpec, ExtRgy, PackageLoader
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

    def run(status):
        runner = TaskSetRunner(os.path.join(tmpdir, 'rundir'))

        def marker_listener(marker):
            raise Exception("marker")

        builder = TaskGraphBuilder(
            PackageLoader(marker_listeners=[marker_listener]).load_rgy(['std', 'hdlsim.%s' % sim]),
            os.path.join(tmpdir, 'rundir'))

        top_v = builder.mkTaskNode(
            'std.FileSet', name="top_v",  
            type="systemVerilogSource", base=data_dir, include="*.v")

        sim_img = builder.mkTaskNode(
            'hdlsim.%s.SimImage' % sim, name="sim_img", needs=[top_v], 
            top=["top"])

        sim_run = builder.mkTaskNode(
            'hdlsim.%s.SimRun' % sim, name="sim_run", needs=[sim_img])

        def listener(task, reason):
            if reason == "leave":
                status.append((task, reason))

        runner.add_listener(listener)
        ret = asyncio.run(runner.run(sim_run))
        assert runner.status == 0
        return ret

    status = []
    out_1 = run(status)
    # for s in status:
    #     print("status: %s %s" % (s[0].name, s[0].output.changed))
    assert status[-2][0].output.changed == True
    status.clear()

    time.sleep(2)

    out_2 = run(status)
    # for s in status:
    #     print("status: %s %s" % (s[0].name, s[0].output.changed))
    assert status[-2][0].output.changed == False
