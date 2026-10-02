# Xcelium (hdlsim.xcm) SimLib / SimLibUVM: UVM pre-compiled into its own
# logical library, a testbench importing it across libraries, and the UVM
# PLI/DPI layer reaching elaboration and run. The DUT comes from a separate
# SimLib, so the image compiles only the testbench.

import os
import json
import shutil
import asyncio
import pytest
from types import SimpleNamespace
from dv_flow.mgr import TaskListenerLog, TaskSetRunner, PackageLoader
from dv_flow.mgr.task_graph_builder import TaskGraphBuilder

from dv_flow.libhdlsim.xcm_sim_lib_uvm import SimLibUVM

DATA_DIR = os.path.join(os.path.dirname(__file__), "data", "xcm_uvm")

needs_xcm = pytest.mark.skipif(
    shutil.which("xmvlog") is None, reason="Xcelium (xmvlog) not available")


def _find(out_l, filetype=None, type_=None):
    out = []
    for o in out_l or []:
        for it in o.output:
            if type_ is not None and getattr(it, "type", None) == type_:
                out.append(it)
            elif filetype is not None and getattr(it, "filetype", None) == filetype:
                out.append(it)
    return out


def _mk(tmpdir):
    rundir = os.path.join(str(tmpdir), "rundir")
    runner = TaskSetRunner(rundir)

    def marker_listener(marker):
        raise Exception("marker: %s" % str(marker))

    builder = TaskGraphBuilder(
        PackageLoader(marker_listeners=[marker_listener]).load_rgy(
            ["std", "hdlsim", "hdlsim.xcm"]),
        rundir)
    runner.builder = builder
    runner.add_listener(TaskListenerLog().event)
    return runner, builder


def _flow(b, prefix="hdlsim.xcm"):
    rtl = b.mkTaskNode("std.FileSet", name="rtl", type="systemVerilogSource",
                       base=os.path.join(DATA_DIR, "rtl"), include="*.sv")
    rtl_lib = b.mkTaskNode("%s.SimLib" % prefix, name="rtl_lib",
                           libname="rtl_lib", needs=[rtl])
    uvm = b.mkTaskNode("%s.SimLibUVM" % prefix, name="uvm")
    tb = b.mkTaskNode("std.FileSet", name="tb", type="systemVerilogSource",
                      base=os.path.join(DATA_DIR, "tb"), include="*.sv")
    # Backdoor (uvm_hdl_read) needs read access to the DUT signals.
    img = b.mkTaskNode("hdlsim.xcm.SimImage", name="img", top=["uvm_tb"],
                       elabargs=["-access", "+r"],
                       needs=[rtl_lib, uvm, tb])
    case = b.mkTaskNode("hdlsim.xcm.SimUVMCase", name="case", needs=[img],
                        testname="backdoor_test")
    return case


def _check_pass(runner, out_l):
    assert runner.status == 0
    trs = _find(out_l, type_="hdlsim.TestResult")
    assert len(trs) == 1
    tr = trs[0]
    assert tr.passed is True, tr
    assert tr.errors == 0
    sim_log = [fs for fs in tr.artifacts if fs.filetype == "simLog"][0]
    with open(os.path.join(sim_log.basedir, sim_log.files[0])) as fp:
        log = fp.read()
    # The backdoor read went through the UVM DPI library.
    assert "count=5a" in log


@needs_xcm
def test_uvm_lib_build_and_run(tmpdir):
    runner, b = _mk(tmpdir)
    out_l = asyncio.run(runner.run([_flow(b)]))
    _check_pass(runner, out_l)

    # UVM and the DUT live in their own libraries: the image compiles only
    # the testbench.
    rundir = os.path.join(str(tmpdir), "rundir")
    with open(os.path.join(rundir, "img", "img.exec_data.json")) as fp:
        cmds = [c["cmd"] for c in json.load(fp)["commands"]]
    xmvlog = [c for c in cmds if c[0] == "xmvlog"][0]
    assert [a for a in xmvlog if a.endswith(".sv")] == [
        os.path.join(DATA_DIR, "tb", "uvm_tb.sv")]
    xmelab = [c for c in cmds if c[0] == "xmelab"][0]
    assert "-loadpli1" in xmelab


@needs_xcm
def test_uvm_lib_uptodate(tmpdir):
    runner, b = _mk(tmpdir)
    asyncio.run(runner.run([_flow(b)]))
    assert runner.status == 0
    log = os.path.join(str(tmpdir), "rundir", "uvm", "xmvlog.log")
    mtime = os.path.getmtime(log)

    # A second run in the same rundir does not recompile UVM.
    runner, b = _mk(tmpdir)
    out_l = asyncio.run(runner.run([_flow(b)]))
    _check_pass(runner, out_l)
    assert os.path.getmtime(log) == mtime


@needs_xcm
def test_generic_tasks_select_xcm(tmpdir):
    """hdlsim.SimLib / hdlsim.SimLibUVM dispatch to the xcm backends."""
    d = str(tmpdir)
    with open(os.path.join(d, "flow.dv"), "w") as f:
        f.write('''
package:
  name: foo
  imports:
    - name: hdlsim
    - name: hdlsim.xcm
  tasks:
  - name: region
    set:
    - hdlsim.sim: xcm
    body:
    - name: rtl
      uses: std.FileSet
      with: {type: systemVerilogSource, base: "%s/rtl", include: "*.sv"}
    - name: rtl_lib
      uses: hdlsim.SimLib
      needs: [rtl]
      with: {libname: rtl_lib}
    - name: uvm
      uses: hdlsim.SimLibUVM
    - name: tb
      uses: std.FileSet
      with: {type: systemVerilogSource, base: "%s/tb", include: "*.sv"}
    - name: img
      uses: hdlsim.SimImage
      needs: [rtl_lib, uvm, tb]
      with: {top: [uvm_tb], elabargs: [-access, +r]}
    - name: case
      uses: hdlsim.SimUVMCase
      needs: [img]
      with: {testname: backdoor_test}
''' % (DATA_DIR, DATA_DIR))
    loader = PackageLoader()
    pkg = loader.load(os.path.join(d, "flow.dv"))
    rundir = os.path.join(d, "rundir")
    builder = TaskGraphBuilder(root_pkg=pkg, rundir=rundir, loader=loader)
    runner = TaskSetRunner(rundir, builder=builder)
    runner.add_listener(TaskListenerLog().event)
    region = builder.mkTaskNode("foo.region")
    out_l = asyncio.run(runner.run([region]))
    _check_pass(runner, out_l)


class _FakeCtxt:
    def __init__(self):
        self.env = {}
        self.markers = []

    def error(self, msg, loc=None):
        self.markers.append(msg)


def test_unknown_uvmhome_errors(tmpdir):
    ctxt = _FakeCtxt()
    input = SimpleNamespace(
        params=SimpleNamespace(uvmhome=os.path.join(str(tmpdir), "no_uvm")),
        rundir=str(tmpdir), memento=None)
    result = asyncio.run(SimLibUVM(ctxt, input))
    assert result.status == 1
    assert len(ctxt.markers) == 1
    assert "not found" in ctxt.markers[0]


class _RecCtxt(_FakeCtxt):
    """Records commands instead of running them."""

    def __init__(self, rundir):
        super().__init__()
        self.rundir = rundir
        self.cmds = []

    def marker(self, msg, severity=None, loc=None):
        self.markers.append(msg)

    def create(self, name, content):
        with open(os.path.join(self.rundir, name), "w") as fp:
            fp.write(content)

    async def exec(self, cmd, logfile=None, **kw):
        self.cmds.append(list(cmd))
        return 0

    def mkDataItem(self, type, **kw):
        return SimpleNamespace(type=type, **kw)


def test_uvm_pli_is_verilogPLI(tmpdir):
    """The UVM PLI library goes out as a verilogPLI FileSet, which the xcm
    backend loads with -loadpli1 at elaboration and at run time."""
    from dv_flow.libhdlsim.vl_sim_data import pli_from_fileset
    from dv_flow.libhdlsim.xcm_sim_run import xcm_pli_args

    # A fake absolute uvmhome with the Cadence additions and both libraries
    uvm_home = os.path.join(str(tmpdir), "CDNS-1.2")
    libdir64 = os.path.join(uvm_home, "additions", "sv", "lib", "64bit")
    os.makedirs(os.path.join(uvm_home, "sv", "src"))
    os.makedirs(libdir64)
    for f in (os.path.join(uvm_home, "sv", "src", "uvm_pkg.sv"),
              os.path.join(uvm_home, "additions", "sv", "cdns_uvm_pkg.sv"),
              os.path.join(libdir64, "libuvmpli.so"),
              os.path.join(libdir64, "libuvmdpi.so")):
        open(f, "w").close()

    rundir = os.path.join(str(tmpdir), "rundir")
    os.makedirs(rundir)
    ctxt = _RecCtxt(rundir)
    input = SimpleNamespace(
        params=SimpleNamespace(uvmhome=uvm_home), rundir=rundir, memento=None)
    result = asyncio.run(SimLibUVM(ctxt, input))
    assert result.status == 0
    assert ctxt.markers == []

    # No hand-built -loadpli1 elaboration argument any more
    assert not [o for o in result.output
                if getattr(o, "type", None) == "hdlsim.SimElabArgs"]

    pli = [o for o in result.output if getattr(o, "filetype", None) == "verilogPLI"]
    assert len(pli) == 1
    libs = pli_from_fileset(pli[0])
    lib_path = os.path.join(libdir64, "libuvmpli.so")
    assert [(l.path, l.boot, l.tab, l.access) for l in libs] == [
        (lib_path, "uvm_pli_boot", None, False)]
    assert xcm_pli_args(libs, sim=False) == [
        "-loadpli1", "%s:uvm_pli_boot" % lib_path]
    assert xcm_pli_args(libs, sim=True) == [
        "-loadpli1", "%s:uvm_pli_boot" % lib_path]

    # Both libraries are still loaded with -sv_lib at run time
    dpi = [o for o in result.output
           if getattr(o, "filetype", None) == "systemVerilogDPI"]
    assert len(dpi) == 1
    assert dpi[0].files == ["libuvmpli.so", "libuvmdpi.so"]
