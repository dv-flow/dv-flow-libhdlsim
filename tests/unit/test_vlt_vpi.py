import os
import pytest
import shutil
import asyncio
from types import SimpleNamespace
from dv_flow.mgr import TaskListenerLog, TaskSetRunner, PackageLoader
from dv_flow.mgr.task_graph_builder import TaskGraphBuilder
import dv_flow.libhdlsim as libhdlsim
from dv_flow.libhdlsim.vl_sim_data import VlSimImageData
from dv_flow.libhdlsim.vl_sim_image_builder import VlSimImageBuilder

have_verilator = shutil.which("verilator") is not None


def _mk_builder(tmpdir):
    def marker_listener(marker):
        if getattr(marker, "severity", None) in ("error", "Error"):
            raise Exception(f"Unexpected marker: {marker}")

    return TaskGraphBuilder(
        PackageLoader(marker_listeners=[marker_listener]).load_rgy(['std', 'hdlsim.vlt']),
        os.path.join(tmpdir, 'rundir'))


@pytest.mark.skipif(not have_verilator, reason="verilator not present")
def test_vpi_without_custom_main(tmpdir):
    """--vpi must be usable without a verilatorMain.

    C code that calls VPI (eg the UVM DPI layer) needs Verilator's VPI
    runtime, but not a custom C++ main. Only *linking an external VPI
    library* requires a main. This test covers the first case, which
    used to raise "VPI in VLT requires a verilatorMain".
    """
    data_dir = os.path.join(os.path.dirname(__file__), "data/vlt_vpi")
    runner = TaskSetRunner(os.path.join(tmpdir, 'rundir'))
    builder = _mk_builder(tmpdir)
    runner.builder = builder

    top = builder.mkTaskNode(
        'std.FileSet',
        name="top",
        type="systemVerilogSource",
        base=data_dir,
        include="top.sv")

    probe = builder.mkTaskNode(
        'std.FileSet',
        name="probe",
        type="cppSource",
        base=data_dir,
        include="vpi_probe.cc")

    sim_img = builder.mkTaskNode(
        'hdlsim.vlt.SimImage',
        name="sim_img",
        top=["top"],
        vpi=True,
        needs=[top, probe])

    sim_run = builder.mkTaskNode(
        'hdlsim.vlt.SimRun',
        name="sim_run",
        needs=[sim_img])

    runner.add_listener(TaskListenerLog().event)
    asyncio.run(runner.run(sim_run))

    assert runner.status == 0

    build_f = os.path.join(tmpdir, 'rundir', 'sim_img', 'build.f')
    with open(build_f) as fp:
        args = fp.read().split()
    assert '--vpi' in args
    # public_flat_rw was not requested and no VPI library is linked, so the
    # optimization-inhibiting flag must not be pulled in as a side effect.
    assert '--public-flat-rw' not in args


@pytest.mark.skipif(not have_verilator, reason="verilator not present")
def test_public_flat_rw_opt_in(tmpdir):
    """--public-flat-rw is requested independently of --vpi."""
    data_dir = os.path.join(os.path.dirname(__file__), "data/vlt_vpi")
    runner = TaskSetRunner(os.path.join(tmpdir, 'rundir'))
    builder = _mk_builder(tmpdir)
    runner.builder = builder

    top = builder.mkTaskNode(
        'std.FileSet',
        name="top",
        type="systemVerilogSource",
        base=data_dir,
        include="top.sv")

    probe = builder.mkTaskNode(
        'std.FileSet',
        name="probe",
        type="cppSource",
        base=data_dir,
        include="vpi_probe.cc")

    sim_img = builder.mkTaskNode(
        'hdlsim.vlt.SimImage',
        name="sim_img",
        top=["top"],
        vpi=True,
        public_flat_rw=True,
        needs=[top, probe])

    runner.add_listener(TaskListenerLog().event)
    asyncio.run(runner.run(sim_img))

    assert runner.status == 0

    build_f = os.path.join(tmpdir, 'rundir', 'sim_img', 'build.f')
    with open(build_f) as fp:
        args = fp.read().split()
    assert '--vpi' in args
    assert '--public-flat-rw' in args


@pytest.mark.parametrize("vpi,public_flat_rw", [
    (False, False),
    (True, False),
    (False, True),
    (True, True),
])
def test_simcompileargs_requests_vpi(tmpdir, vpi, public_flat_rw):
    """A library declares its VPI need via SimCompileArgs.

    This is the channel SimLibUVM uses, so it does not have to
    string-inject --vpi through `args`. No simulator required.
    """
    builder = _mk_builder(tmpdir)
    item = builder.mkDataItem(
        "hdlsim.SimCompileArgs",
        vpi=vpi,
        public_flat_rw=public_flat_rw)

    data = VlSimImageData()
    inputs = SimpleNamespace(inputs=[item])
    VlSimImageBuilder._gatherSvSources(
        VlSimImageBuilder(ctxt=None), data, inputs)

    assert data.vpi_enable is vpi
    assert data.public_flat_rw is public_flat_rw
