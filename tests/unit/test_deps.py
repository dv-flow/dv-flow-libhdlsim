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
def test_svh_incdirs_rebuild(tmpdir, request, sim):
    """Regression: SimImage must be rebuilt when a .svh file that is `include-d
    from a systemVerilogSource file changes, even when the .svh lives only in
    the FileSet's incdirs (i.e. it is not listed in a separate
    systemVerilogInclude node).

    Expected: second run after touching the .svh → sim_img output.changed==True
    Bug:      sim_img output.changed==False  (stale binary is silently reused)
    """
    src_dir = os.path.join(str(tmpdir), "src")
    inc_dir = os.path.join(src_dir, "inc")
    os.makedirs(inc_dir)

    sv_path  = os.path.join(src_dir, "top.sv")
    svh_path = os.path.join(inc_dir, "msg.svh")

    with open(sv_path, "w") as f:
        f.write('`include "msg.svh"\n'
                'module top;\n'
                '  initial begin\n'
                '    `MSG_DISPLAY\n'
                '    $finish;\n'
                '  end\n'
                'endmodule\n')

    with open(svh_path, "w") as f:
        f.write('`define MSG_DISPLAY $display("Hello World!");\n')

    def run():
        status = []
        runner = TaskSetRunner(os.path.join(str(tmpdir), "rundir"))

        # Provide the builder so runner.mkDataItem() works: this allows the
        # uptodate path to restore outputs and return changed=False (the
        # behaviour seen in a real CLI invocation).
        builder = TaskGraphBuilder(
            PackageLoader().load_rgy(["std", "hdlsim.%s" % sim]),
            os.path.join(str(tmpdir), "rundir"))
        runner.builder = builder

        top_v = builder.mkTaskNode(
            "std.FileSet",
            name="top_v",
            type="systemVerilogSource",
            base=src_dir,
            include="top.sv",
            incdirs=[inc_dir])

        sim_img = builder.mkTaskNode(
            "hdlsim.%s.SimImage" % sim,
            name="sim_img",
            needs=[top_v],
            top=["top"])

        sim_run = builder.mkTaskNode(
            "hdlsim.%s.SimRun" % sim,
            name="sim_run",
            needs=[sim_img])

        def listener(task, reason):
            if reason == "leave":
                status.append(task)

        runner.add_listener(listener)
        asyncio.run(runner.run([sim_run]))
        assert runner.status == 0
        return status

    # First run always builds
    status = run()
    sim_img_task = next(t for t in status if t.name == "sim_img")
    assert sim_img_task.output.changed == True

    time.sleep(2)

    # Modify only the .svh — the explicit .sv is untouched
    with open(svh_path, "w") as f:
        f.write('`define MSG_DISPLAY $display("Goodbye World!");\n')

    # Second run: SimImage should detect the changed .svh and rebuild.
    # Bug: output.changed is False because .svh files in incdirs are not tracked.
    status = run()
    sim_img_task = next(t for t in status if t.name == "sim_img")
    assert sim_img_task.output.changed == True, (
        "SimImage was not rebuilt after .svh in incdirs changed")


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
        runner.builder = builder

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
