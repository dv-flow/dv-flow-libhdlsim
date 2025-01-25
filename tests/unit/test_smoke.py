import os
import pytest
import shutil
import asyncio
import sys
from dv_flow.mgr import TaskSpec
from dv_flow.mgr.pkg_rgy import PkgRgy
from dv_flow.mgr.task_graph_runner_local import TaskGraphRunnerLocal
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
def test_simple(tmpdir, request,sim):

    data_dir = os.path.join(os.path.dirname(__file__), "data")
    runner = TaskGraphRunnerLocal(os.path.join(tmpdir, 'rundir'))
    rgy = PkgRgy()
    rgy._discover_plugins()
    # rgy.registerPackage('hdlsim', 
    #                         os.path.join(hdlsim_path, "flow.dv"))
    # rgy.registerPackage('hdlsim.%s' % sim, 
    #                         os.path.join(hdlsim_path, "%s_flow.dv" % sim))

    builder = TaskGraphBuilder(
        None, 
        os.path.join(tmpdir, 'rundir'),
        pkg_rgy=rgy)

    hdlsim_path = os.path.dirname(
        os.path.abspath(libhdlsim.__file__))
    
    fileset_t = builder.getTaskCtor(TaskSpec('std.FileSet'))
    fileset_params = fileset_t.param_ctor()
    fileset_params.type = "systemVerilogSource"
    fileset_params.base = data_dir
    fileset_params.include = "*.v"

    top_v = fileset_t.task_ctor(
        name="top_v",
        session=runner,
        params=fileset_params,
        rundir=os.path.join(tmpdir, "rundir", "top_v"),
        srcdir=fileset_t.srcdir
    )
    
    sim_img_t = builder.getTaskCtor(TaskSpec('hdlsim.%s.SimImage' % sim))
    print("sim=%s sim_img_t.src=%s %s" % (sim, sim_img_t.srcdir, str(type(sim_img_t))))
    sim_img_params = sim_img_t.mkParams()
    sim_img_params.top.append('top')
    sim_img = sim_img_t.task_ctor(
        name="sim_img",
        session=runner,
        params=sim_img_params,
        rundir=os.path.join(tmpdir, "rundir", "sim_img"),
        srcdir=sim_img_t.srcdir,
        depends=[top_v]
    )
    print("sim: %s sim_img: %s" % (sim, str(type(sim_img))))

    sim_run_t = builder.getTaskCtor(TaskSpec('hdlsim.%s.SimRun' % sim))
    print("sim=%s sim_run_t.src=%s" % (sim, sim_run_t.srcdir))
    sim_run = sim_run_t.task_ctor(
        name="sim_run",
        session=runner,
        params=sim_run_t.mkParams(),
        rundir=os.path.join(tmpdir, "rundir", "sim_run"),
        srcdir=sim_run_t.srcdir,
        depends=[sim_img])

    out = asyncio.run(runner.run(sim_run))

    print("out: %s" % str(out))

    rundir_fs = out.getFileSets("simRunDir")

    assert len(rundir_fs) == 1
    assert rundir_fs[0].src == "sim_run"

    assert os.path.isfile(os.path.join(rundir_fs[0].basedir, "sim.log"))
    with open(os.path.join(rundir_fs[0].basedir, "sim.log"), "r") as f:
        sim_log = f.read()
    
    assert sim_log.find("Hello World!") != -1
    
    pass

@pytest.mark.parametrize("sim", get_available_sims())
def test_import_alias(tmpdir,sim):

    data_dir = os.path.join(os.path.dirname(__file__), "data")
    rgy = PkgRgy()
    rgy._discover_plugins()
    # rgy.registerPackage('hdlsim', 
    #                         os.path.join(hdlsim_path, "flow.dv"))
    # rgy.registerPackage('hdlsim.%s' % sim, 
    #                         os.path.join(hdlsim_path, "%s_flow.dv" % sim))

    flow_dv = """
package:
    name: foo

    imports:

"""
    flow_dv += "    - name: hdlsim.%s" % sim + "\n"
    flow_dv += "      as: hdlsim\n"

    flow_dv += """
    tasks:
    - name: files
      uses: std.FileSet
      with:
        type: systemVerilogSource
        include: "*.sv"
    - name: build
      uses: hdlsim.SimImage
      with:
        top: [top]
      needs: [files]
    - name: run
      uses: hdlsim.SimRun
      needs: [build]
"""

    with open(os.path.join(tmpdir, "flow.dv"), "w") as fp:
        fp.write(flow_dv)

    with open(os.path.join(tmpdir, "top.sv"), "w") as fp:
        fp.write("""
module top;
  initial begin
    $display("Hello World");
    $finish;
  end
endmodule
        """)

    pkg_def = loadProjPkgDef(os.path.join(tmpdir))

    builder = TaskGraphBuilder(
        pkg_def, 
        os.path.join(tmpdir, 'rundir'),
        pkg_rgy=rgy)

    runner = TaskGraphRunnerLocal(os.path.join(tmpdir, 'rundir'))
    
    run_t = builder.mkTaskGraph("foo.run")

    # hdlsim_path = os.path.dirname(
    #     os.path.abspath(libhdlsim.__file__))
    
    # fileset_t = builder.getTaskCtor(TaskSpec('std.FileSet'))
    # fileset_params = fileset_t.param_ctor()
    # fileset_params.type = "systemVerilogSource"
    # fileset_params.base = data_dir
    # fileset_params.include = "*.v"

    # top_v = fileset_t.task_ctor(
    #     name="top_v",
    #     session=runner,
    #     params=fileset_params,
    #     rundir=os.path.join(tmpdir, "rundir", "top_v"),
    #     srcdir=fileset_t.srcdir
    # )
    
    # sim_img_t = builder.getTaskCtor(TaskSpec('hdlsim.%s.SimImage' % sim))
    # print("sim=%s sim_img_t.src=%s %s" % (sim, sim_img_t.srcdir, str(type(sim_img_t))))
    # sim_img_params = sim_img_t.mkParams()
    # sim_img_params.top.append('top')
    # sim_img = sim_img_t.task_ctor(
    #     name="sim_img",
    #     session=runner,
    #     params=sim_img_params,
    #     rundir=os.path.join(tmpdir, "rundir", "sim_img"),
    #     srcdir=sim_img_t.srcdir,
    #     depends=[top_v]
    # )
    # print("sim: %s sim_img: %s" % (sim, str(type(sim_img))))

    # sim_run_t = builder.getTaskCtor(TaskSpec('hdlsim.%s.SimRun' % sim))
    # print("sim=%s sim_run_t.src=%s" % (sim, sim_run_t.srcdir))
    # sim_run = sim_run_t.task_ctor(
    #     name="sim_run",
    #     session=runner,
    #     params=sim_run_t.mkParams(),
    #     rundir=os.path.join(tmpdir, "rundir", "sim_run"),
    #     srcdir=sim_run_t.srcdir,
    #     depends=[sim_img])

    # out = asyncio.run(runner.run(sim_run))

    # print("out: %s" % str(out))

    # rundir_fs = out.getFileSets("simRunDir")

    # assert len(rundir_fs) == 1
    # assert rundir_fs[0].src == "sim_run"

    # assert os.path.isfile(os.path.join(rundir_fs[0].basedir, "sim.log"))
    # with open(os.path.join(rundir_fs[0].basedir, "sim.log"), "r") as f:
    #     sim_log = f.read()
    
    # assert sim_log.find("Hello World!") != -1
    
    # pass
