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
def test_simple_1(tmpdir, request,sim):
    data_dir = os.path.join(os.path.dirname(__file__), "data/test_markers")

    def marker_listener(marker):
        raise Exception("marker")

    def run(status):
        runner = TaskSetRunner(os.path.join(tmpdir, 'rundir'))
        builder = TaskGraphBuilder(
            PackageLoader(marker_listeners=[marker_listener]).load_rgy(['std', 'hdlsim.%s' % sim]),
            os.path.join(tmpdir, 'rundir'))

        top_v = builder.mkTaskNode(
            'std.FileSet', name="top_v",  
            type="systemVerilogSource", base=data_dir, include="*.sv")

        sim_img = builder.mkTaskNode(
            'hdlsim.%s.SimImage' % sim, 
            name="sim_img", 
            needs=[top_v], 
            top=["top"])

        sim_run = builder.mkTaskNode(
            'hdlsim.%s.SimRun' % sim, name="sim_run", 
            needs=[sim_img])

        def listener(task, reason):
            if reason == "leave":
                status.append((task, reason, task.result.markers))

        runner.add_listener(listener)
        task_o = asyncio.run(runner.run(sim_run))

        return (runner.status, task_o)

    status = []
    status_1, out_1 = run(status)

    assert status_1 != 0
    assert len(status[-1][2]) != 0

    print("status[-1][2]: %s" % str(status [-1][2]))
