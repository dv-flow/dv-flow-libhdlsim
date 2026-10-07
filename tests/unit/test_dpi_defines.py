import os
import pytest
import asyncio
from dv_flow.mgr import FileSet, TaskListenerLog, TaskSetRunner, PackageLoader
from dv_flow.mgr.task_graph_builder import TaskGraphBuilder
from dv_flow.libhdlsim.vl_sim_data import VlSimImageData, c_flags
from dv_flow.libhdlsim.vl_sim_image_builder import VlSimImageBuilder
from .sims import get_available_sims

SIMS = get_available_sims(exclude=("ivl", "xsm"))


class _Input(object):
    def __init__(self, inputs):
        self.inputs = inputs


def test_csource_defines_are_c_only():
    """A cSource FileSet's defines/incdirs go to the C compile, not SV"""
    data = VlSimImageData()
    builder = VlSimImageBuilder(ctxt=None)
    builder._gatherSvSources(data, _Input([
        FileSet(filetype="systemVerilogSource", basedir="/sv",
                files=["top.sv"], defines=["SV_DEF"]),
        FileSet(filetype="cSource", basedir="/c",
                files=["a.c"], defines=["C_DEF", "C_VAL=1"],
                incdirs=["inc"]),
    ]))

    assert data.defines == ["SV_DEF"]
    assert data.incdirs == []
    assert data.cdefines == ["C_DEF", "C_VAL=1"]
    assert data.cincdirs == ["/c/inc"]
    assert data.csource == ["/c/a.c"]
    assert c_flags(data) == ["-DC_DEF", "-DC_VAL=1", "-I/c/inc"]


@pytest.mark.parametrize("sim", SIMS)
def test_dpi_src_defines(tmpdir, sim):
    data_dir = os.path.join(os.path.dirname(__file__), "data/dpi_defines")
    runner = TaskSetRunner(os.path.join(tmpdir, 'rundir'))

    def marker_listener(marker):
        raise Exception("marker")

    builder = TaskGraphBuilder(
        PackageLoader(marker_listeners=[marker_listener]).load_rgy(['std', 'hdlsim.%s' % sim]),
        os.path.join(tmpdir, 'rundir'))
    runner.builder = builder

    top = builder.mkTaskNode(
        'std.FileSet',
        name="top",
        type="systemVerilogSource",
        base=data_dir,
        include="smoke.sv")

    # smoke.c fails to compile unless both defines and the incdir arrive
    top_c = builder.mkTaskNode(
        'std.FileSet',
        name="top_c",
        type="cSource",
        base=data_dir,
        include="smoke.c",
        incdirs=["inc"],
        defines=["DPI_C_DEFINE", "DPI_C_VALUE=42"])

    sim_img = builder.mkTaskNode(
        'hdlsim.%s.SimImage' % sim,
        name="sim_img",
        needs=[top, top_c],
        top=["smoke"])

    sim_run = builder.mkTaskNode(
        'hdlsim.%s.SimRun' % sim,
        name="sim_run",
        needs=[sim_img])

    runner.add_listener(TaskListenerLog().event)
    out_l = asyncio.run(runner.run([sim_run]))

    assert runner.status == 0

    rundir_fs = None
    for out in out_l:
        for fs in out.output:
            if fs.type == 'std.FileSet' and fs.filetype == "simRunDir":
                rundir_fs = fs
    assert rundir_fs is not None

    with open(os.path.join(rundir_fs.basedir, "sim.log"), "r") as f:
        sim_log = f.read()

    assert "RES: dpi_cfg.h included" in sim_log
    assert "RES: dpi_func" in sim_log
    assert "leaked into SV" not in sim_log
