
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

def mkdefine(sim, define):
    if sim in ("vcs", "mti", "vlt", "xcm"):
        return ["+define+%s" % define]
    elif sim in ("ivl",):
        return ["-D", define]
    elif sim in ("xsm",):
        return ["-d", define]
    else:
        raise Exception("Unknown simulator %s" % sim)

@pytest.mark.parametrize("sim", get_available_sims())
def test_define_fs(tmpdir, request, sim):

    data_dir = os.path.join(os.path.dirname(__file__), "data/defines")
    runner = TaskSetRunner(os.path.join(tmpdir, 'rundir'))

    def marker_listener(marker):
        raise Exception("marker")

    builder = TaskGraphBuilder(
        PackageLoader(marker_listeners=[marker_listener]).load_rgy(['std', 'hdlsim.%s' % sim]),
        os.path.join(tmpdir, 'rundir'))

    top = builder.mkTaskNode(
        'std.FileSet',
        name="top",  
        type="systemVerilogSource", 
        base=os.path.join(data_dir),
        include="top_mod1.v",
        defines=["SPECIAL_DEFINE"])

    sim_img = builder.mkTaskNode(
        'hdlsim.%s.SimImage' % sim,
        name="sim_img",
        needs=[top],
        top=["top_mod1"])

    sim_run = builder.mkTaskNode(
        'hdlsim.%s.SimRun' % sim, 
        name="sim_run",
        needs=[sim_img])

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
    
        assert sim_log.find("SPECIAL_DEFINE is defined") != -1

@pytest.mark.parametrize("sim", get_available_sims())
def test_define_simimg_compargs(tmpdir, request, sim):

    data_dir = os.path.join(os.path.dirname(__file__), "data/defines")
    runner = TaskSetRunner(os.path.join(tmpdir, 'rundir'))

    def marker_listener(marker):
        raise Exception("marker")

    builder = TaskGraphBuilder(
        PackageLoader(marker_listeners=[marker_listener]).load_rgy(['std', 'hdlsim.%s' % sim]),
        os.path.join(tmpdir, 'rundir'))

    top = builder.mkTaskNode(
        'std.FileSet',
        name="top",  
        type="systemVerilogSource", 
        base=os.path.join(data_dir),
        include="top_mod1.v")

    args = []
    args.extend(mkdefine(sim, "SPECIAL_DEFINE"))
    sim_img = builder.mkTaskNode(
        'hdlsim.%s.SimImage' % sim,
        name="sim_img",
        needs=[top],
        top=["top_mod1"],
        compargs=args)
    
    sim_run = builder.mkTaskNode(
        'hdlsim.%s.SimRun' % sim, 
        name="sim_run",
        needs=[sim_img])

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
    
        assert sim_log.find("SPECIAL_DEFINE is defined") != -1

@pytest.mark.parametrize("sim", get_available_sims())
def test_define_dataitem_compargs(tmpdir, request, sim):

    data_dir = os.path.join(os.path.dirname(__file__), "data/defines")
    runner = TaskSetRunner(os.path.join(tmpdir, 'rundir'))

    def marker_listener(marker):
        raise Exception("marker")

    builder = TaskGraphBuilder(
        PackageLoader(marker_listeners=[marker_listener]).load_rgy(['std', 'hdlsim.%s' % sim]),
        os.path.join(tmpdir, 'rundir'))

    top = builder.mkTaskNode(
        'std.FileSet',
        name="top",  
        type="systemVerilogSource", 
        base=os.path.join(data_dir),
        include="top_mod1.v")

    args = []
    args.extend(mkdefine(sim, "SPECIAL_DEFINE"))
    comp_args = builder.mkTaskNode(
        'hdlsim.SimCompileArgs',
        name="comp_args",
        compargs=args)
    sim_img = builder.mkTaskNode(
        'hdlsim.%s.SimImage' % sim,
        name="sim_img",
        needs=[top, comp_args],
        top=["top_mod1"],
        compargs=args)
    
    sim_run = builder.mkTaskNode(
        'hdlsim.%s.SimRun' % sim, 
        name="sim_run",
        needs=[sim_img])

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
    
        assert sim_log.find("SPECIAL_DEFINE is defined") != -1
