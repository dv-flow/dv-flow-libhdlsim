#****************************************************************************
#* test_pli.py
#*
#* PLI 1.0 libraries (hdlsim.SimPLI -> verilogPLI FileSets) and how each
#* backend loads them. Only Verilator and Icarus may be installed, so the
#* vcs/xcm/mti/ivl command lines are checked with exec stubbed out; the live
#* tests run where a simulator is on PATH.
#****************************************************************************
import asyncio
import os
import shutil
import subprocess
import time
import types
import pytest
from dv_flow.mgr import FileSet, TaskListenerLog, TaskSetRunner, PackageLoader
from dv_flow.mgr.task_data import SeverityE
from dv_flow.mgr.task_graph_builder import TaskGraphBuilder
from dv_flow.mgr.task_run_ctxt import TaskRunCtxt
from svdep import TaskBuildFileCollection
from dv_flow.libhdlsim.sim_pli import SimPLI
from dv_flow.libhdlsim.vl_sim_data import (
    PliLib, VlSimImageData, VlSimRunData, pli_add, pli_from_fileset)
from dv_flow.libhdlsim.vl_sim_image_builder import check_sim_image_uptodate
from dv_flow.libhdlsim import (
    ivl_sim_image, ivl_sim_run, mti_sim_image, mti_sim_run,
    vcs_sim_image, vcs_sim_run, xcm_sim_image, xcm_sim_run)
from .sims import get_available_sims

DATA_DIR = os.path.join(os.path.dirname(__file__), "data", "pli")


def _touch(path, content="\n"):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fp:
        fp.write(content)
    return path


def _errors(markers):
    return [m for m in markers if m.severity == SeverityE.Error]


def _warnings(markers):
    return [m for m in markers if m.severity == SeverityE.Warning]


#----------------------------------------------------------------------------
# SimPLI pytask
#----------------------------------------------------------------------------

def _simpli(tmpdir, inputs=(), memento=None, **params):
    p = dict(lib="", tab="", boot="", interface="pli1", access=True)
    p.update(params)
    inp = types.SimpleNamespace(
        name="pli", srcdir=str(tmpdir), rundir=str(tmpdir),
        params=types.SimpleNamespace(**p), inputs=list(inputs),
        memento=memento)
    return asyncio.run(SimPLI(None, inp))


def test_simpli_pli1(tmpdir):
    lib = _touch(os.path.join(tmpdir, "lib", "libfoo.so"))
    tab = _touch(os.path.join(tmpdir, "foo.tab"))
    res = _simpli(tmpdir, lib="lib/libfoo.so", tab="foo.tab", boot="foo_boot")
    assert res.status == 0, res.markers
    assert len(res.output) == 1
    fs = res.output[0]
    assert fs.filetype == "verilogPLI"
    assert fs.basedir == os.path.dirname(lib)
    assert fs.files == ["libfoo.so"]
    assert fs.attributes == ["boot=foo_boot", "tab=%s" % tab, "access=1"]
    assert res.markers == []


def test_simpli_absolute_and_no_access(tmpdir):
    lib = _touch(os.path.join(tmpdir, "libfoo.so"))
    res = _simpli("/nonexistent", lib=lib, boot="b", access=False)
    assert res.status == 0
    assert res.output[0].attributes == ["boot=b", "access=0"]


def test_simpli_vpi(tmpdir):
    lib = _touch(os.path.join(tmpdir, "libvpi.so"))
    res = _simpli(tmpdir, lib="libvpi.so", interface="vpi", boot="my_boot")
    assert res.status == 0
    fs = res.output[0]
    assert fs.filetype == "verilogVPI"
    assert fs.attributes == ["entrypoint=my_boot"]

    res = _simpli(tmpdir, lib="libvpi.so", interface="vpi")
    assert res.output[0].attributes == []


def test_simpli_sharedlib_inputs(tmpdir):
    _touch(os.path.join(tmpdir, "a", "liba.so"))
    _touch(os.path.join(tmpdir, "b", "libb.so"))
    inputs = [
        FileSet(filetype="sharedLib", basedir=os.path.join(tmpdir, "a"), files=["liba.so"]),
        FileSet(filetype="sharedLib", basedir=os.path.join(tmpdir, "b"), files=["libb.so"]),
    ]
    res = _simpli(tmpdir, inputs=inputs, boot="boot")
    assert res.status == 0, res.markers
    assert [fs.files[0] for fs in res.output] == ["liba.so", "libb.so"]
    assert all(fs.filetype == "verilogPLI" for fs in res.output)


@pytest.mark.parametrize("case,params,msg", [
    ("no_lib",       dict(),                                        "no library"),
    ("missing_lib",  dict(lib="nope.so", boot="b"),                 "does not exist"),
    ("missing_tab",  dict(lib="libfoo.so", tab="nope.tab"),         "does not exist"),
    ("bad_iface",    dict(lib="libfoo.so", boot="b", interface="x"), "interface"),
    ("vpi_with_tab", dict(lib="libfoo.so", tab="foo.tab", interface="vpi"), "does not apply"),
])
def test_simpli_errors(tmpdir, case, params, msg):
    _touch(os.path.join(tmpdir, "libfoo.so"))
    _touch(os.path.join(tmpdir, "foo.tab"))
    res = _simpli(tmpdir, **params)
    assert res.status == 1
    assert res.output == []
    errs = _errors(res.markers)
    assert any(msg in m.msg for m in errs), errs


def test_simpli_lib_and_sharedlib_is_error(tmpdir):
    _touch(os.path.join(tmpdir, "libfoo.so"))
    inputs = [FileSet(filetype="sharedLib", basedir=str(tmpdir), files=["libfoo.so"])]
    res = _simpli(tmpdir, inputs=inputs, lib="libfoo.so", boot="b")
    assert res.status == 1
    assert any("one or the other" in m.msg for m in _errors(res.markers))


def test_simpli_tab_with_two_libs_is_error(tmpdir):
    _touch(os.path.join(tmpdir, "liba.so"))
    _touch(os.path.join(tmpdir, "libb.so"))
    _touch(os.path.join(tmpdir, "foo.tab"))
    inputs = [FileSet(filetype="sharedLib", basedir=str(tmpdir), files=["liba.so", "libb.so"])]
    res = _simpli(tmpdir, inputs=inputs, tab="foo.tab")
    assert res.status == 1
    assert any("2 libraries" in m.msg for m in _errors(res.markers))


def test_simpli_no_boot_no_tab_warns(tmpdir):
    _touch(os.path.join(tmpdir, "libfoo.so"))
    res = _simpli(tmpdir, lib="libfoo.so")
    assert res.status == 0
    assert any("only Questa" in m.msg for m in _warnings(res.markers))


def test_simpli_changed_tracks_mtime(tmpdir):
    lib = _touch(os.path.join(tmpdir, "libfoo.so"))
    res = _simpli(tmpdir, lib="libfoo.so", boot="b")
    assert res.changed
    res = _simpli(tmpdir, memento=res.memento, lib="libfoo.so", boot="b")
    assert not res.changed
    os.utime(lib, (time.time() + 10, time.time() + 10))
    res = _simpli(tmpdir, memento=res.memento, lib="libfoo.so", boot="b")
    assert res.changed


#----------------------------------------------------------------------------
# The verilogPLI wire format
#----------------------------------------------------------------------------

def test_pli_from_fileset_roundtrip():
    lib = PliLib(path="/l/libfoo.so", boot="b", tab="/t/foo.tab", access=False)
    fs = FileSet(filetype="verilogPLI", basedir="/l", files=["libfoo.so"],
                 attributes=lib.attributes())
    assert pli_from_fileset(fs) == [lib]


def test_pli_from_fileset_defaults_and_relative_tab():
    fs = FileSet(filetype="verilogPLI", basedir="/l", files=["libfoo.so"],
                 attributes=["tab=foo.tab"])
    assert pli_from_fileset(fs) == [
        PliLib(path="/l/libfoo.so", boot=None, tab="/l/foo.tab", access=True)]


def test_pli_add_dedupes_in_order():
    a = PliLib("/a.so", boot="x")
    b = PliLib("/b.so", tab="/b.tab")
    libs = []
    pli_add(libs, [a, b])
    pli_add(libs, [PliLib("/a.so", boot="x", access=False), PliLib("/c.so")])
    assert [l.path for l in libs] == ["/a.so", "/b.so", "/c.so"]


def _fs_pli(basedir, attrs):
    return FileSet(filetype="verilogPLI", basedir=basedir,
                   files=["libfoo.so"], attributes=attrs)


def test_gather_pli_not_as_hdl_source():
    b = xcm_sim_image.SimImageBuilder(ctxt=None)
    data = VlSimImageData()
    inp = types.SimpleNamespace(inputs=[
        _fs_pli("/l", ["boot=b"]), _fs_pli("/l", ["boot=b"])])
    b._gatherSvSources(data, inp)
    assert data.files == []
    assert data.pli == [PliLib("/l/libfoo.so", boot="b")]


def test_vcs_run_rejects_pli(tmpdir):
    imgdir = os.path.join(tmpdir, "img")
    os.makedirs(imgdir)
    seen = {}

    class Runner(vcs_sim_run.SimRunner):
        async def runsim(self, data):
            seen["plilibs"] = list(data.plilibs)
            return 0

    b, ctxt = _mk_ctxt(tmpdir)
    inp = types.SimpleNamespace(
        name="run", rundir=str(tmpdir),
        params=types.SimpleNamespace(plusargs=[], args=[], trace=False,
                                     dpilibs=[], vpilibs=[], valgrind=False),
        inputs=[FileSet(filetype="simDir", basedir=imgdir),
                _fs_pli("/l", ["tab=/l/foo.tab"])])
    res = asyncio.run(Runner().run(ctxt, inp))
    # VCS links PLI into simv: a library reaching SimRun is an Error, and the
    # simulator is not started.
    assert res.status != 0
    assert "plilibs" not in seen
    assert any("attached to SimImage" in m.msg for m in _errors(res.markers))


def _mk_ctxt(tmpdir):
    loader = PackageLoader().load_rgy(["std", "hdlsim"])
    b = TaskGraphBuilder(loader, str(tmpdir))
    return b, TaskRunCtxt(runner=b, ctxt=None, rundir=str(tmpdir))


#----------------------------------------------------------------------------
# Up-to-date check: a newer library or table forces a rebuild
#----------------------------------------------------------------------------

def test_uptodate_sees_newer_pli(tmpdir):
    sv = _touch(os.path.join(tmpdir, "top.sv"), "module top; endmodule\n")
    lib = _touch(os.path.join(tmpdir, "libfoo.so"))
    tab = _touch(os.path.join(tmpdir, "foo.tab"))
    ref = _touch(os.path.join(tmpdir, "simv"))
    old = time.time() - 100
    for p in (sv, lib, tab):
        os.utime(p, (old, old))

    svdeps = TaskBuildFileCollection([sv], []).build().to_dict()
    ctxt = types.SimpleNamespace(
        memento={"svdeps": svdeps},
        inputs=[FileSet(filetype="systemVerilogSource", basedir=str(tmpdir), files=["top.sv"]),
                FileSet(filetype="verilogPLI", basedir=str(tmpdir), files=["libfoo.so"],
                        attributes=["tab=foo.tab"])])
    assert asyncio.run(check_sim_image_uptodate(ctxt, ref)) is True

    new = time.time() + 100
    os.utime(tab, (new, new))
    assert asyncio.run(check_sim_image_uptodate(ctxt, ref)) is False
    os.utime(tab, (old, old))
    os.utime(lib, (new, new))
    assert asyncio.run(check_sim_image_uptodate(ctxt, ref)) is False


#----------------------------------------------------------------------------
# Command lines (exec stubbed)
#----------------------------------------------------------------------------

class FakeCtxt:
    """Records each command instead of running it; creates its log file."""

    def __init__(self, rundir):
        self.rundir = str(rundir)
        self.cmds = []
        self._markers = []

    async def exec(self, cmd, logfile=None, logfilter=None, **kw):
        self.cmds.append(list(cmd))
        if logfile:
            _touch(os.path.join(self.rundir, logfile), "")
        return 0

    def create(self, name, content):
        _touch(os.path.join(self.rundir, name), content)

    def add_marker(self, m):
        self._markers.append(m)

    def cmd(self, exe):
        for c in self.cmds:
            if c and c[0] == exe:
                return c
        raise AssertionError("no %s command in %s" % (exe, self.cmds))


def _image_input(rundir, **params):
    p = dict(top=["top"], args=[], partcomp=False, fastpartcomp=0, full64=True)
    p.update(params)
    return types.SimpleNamespace(rundir=str(rundir), inputs=[],
                                 params=types.SimpleNamespace(**p))


def _build(mod, tmpdir, libs):
    ctxt = FakeCtxt(tmpdir)
    builder = mod.SimImageBuilder(ctxt=ctxt)
    inp = _image_input(tmpdir)
    builder.input = inp
    data = VlSimImageData(pli=list(libs))
    status = builder.check_pli(data)
    if status == 0:
        status, _ = asyncio.run(builder.build(inp, data))
    return status, ctxt, builder.markers


def _runsim(mod, tmpdir, libs, check=True):
    imgdir = os.path.join(tmpdir, "img")
    os.makedirs(os.path.join(imgdir, "xcelium.d"), exist_ok=True)
    runner = mod.SimRunner()
    runner.rundir = os.path.join(tmpdir, "run")
    os.makedirs(runner.rundir, exist_ok=True)
    cmds = []

    async def exec_sim(cmd, logfile="sim.log", **kw):
        cmds.append(list(cmd))
        return 0
    runner.exec_sim = exec_sim
    data = VlSimRunData(imgdir=imgdir, plilibs=list(libs))
    status = runner.check_pli(data) if check else 0
    if status == 0:
        status = asyncio.run(runner.runsim(data))
    return status, (cmds[0] if cmds else None), runner.markers


BOOT = PliLib("/l/libboot.so", boot="my_boot")
TAB = PliLib("/l/libtab.so", tab="/l/hello.tab", access=False)
BARE = PliLib("/l/libbare.so")


# -- xcm ---------------------------------------------------------------------

def test_xcm_image_cmd(tmpdir):
    status, ctxt, markers = _build(xcm_sim_image, tmpdir, [BOOT, TAB])
    assert status == 0, markers
    elab = ctxt.cmd("xmelab")
    # Only the library with a boot routine loads at elab: xmelab rejects
    # -plimapfile.
    assert "-loadpli1" in elab
    assert elab[elab.index("-loadpli1") + 1] == "/l/libboot.so:my_boot"
    assert elab.count("-loadpli1") == 1
    assert "-plimapfile" not in elab
    assert elab.count("-access") == 1 and "+rwc" in elab


def test_xcm_image_no_access(tmpdir):
    status, ctxt, _ = _build(xcm_sim_image, tmpdir, [TAB])
    assert status == 0
    elab = ctxt.cmd("xmelab")
    assert "-access" not in elab
    assert "-loadpli1" not in elab


def test_xcm_run_cmd(tmpdir):
    status, cmd, _ = _runsim(xcm_sim_run, tmpdir, [BOOT, TAB])
    assert status == 0
    i = cmd.index("-loadpli1")
    assert cmd[i:i + 2] == ["-loadpli1", "/l/libboot.so:my_boot"]
    j = cmd.index("-loadpli1", i + 1)
    assert cmd[j:j + 4] == ["-loadpli1", "/l/libtab.so:", "-plimapfile", "/l/hello.tab"]


def test_xcm_needs_boot_or_tab(tmpdir):
    status, ctxt, markers = _build(xcm_sim_image, tmpdir, [BARE])
    assert status == 1
    assert ctxt.cmds == []
    assert any("boot" in m.msg for m in _errors(markers))
    status, cmd, markers = _runsim(xcm_sim_run, tmpdir, [BARE])
    assert status == 1 and cmd is None


# -- mti ---------------------------------------------------------------------

def test_mti_image_cmd(tmpdir):
    status, ctxt, markers = _build(mti_sim_image, tmpdir, [BOOT, TAB, BARE])
    assert status == 0, markers
    assert "+acc" in ctxt.cmd("vopt")

    status, ctxt, _ = _build(mti_sim_image, tmpdir, [TAB])
    assert "+acc" not in ctxt.cmd("vopt")


def test_mti_run_cmd(tmpdir):
    status, cmd, markers = _runsim(mti_sim_run, tmpdir, [BOOT, TAB, BARE])
    assert status == 0
    i = cmd.index("-pli")
    assert cmd[i:i + 8] == [
        "-pli", "/l/libboot.so",
        "-pli", "/l/libtab.so", "-tab", "/l/hello.tab",
        "-pli", "/l/libbare.so"]
    # boot without tab is ignored by Questa: say so.
    warns = _warnings(markers)
    assert len(warns) == 1 and "libboot.so" in warns[0].msg


# -- vcs ---------------------------------------------------------------------

def test_vcs_image_cmd(tmpdir):
    lib2 = PliLib("/l/libtab2.so", tab="/l/two.tab", access=False)
    status, ctxt, markers = _build(vcs_sim_image, tmpdir, [TAB, lib2])
    assert status == 0, markers
    vcs = ctxt.cmd("vcs")
    i = vcs.index("-P")
    assert vcs[i:i + 3] == ["-P", "/l/hello.tab", "/l/libtab.so"]
    j = vcs.index("-P", i + 1)
    assert vcs[j:j + 3] == ["-P", "/l/two.tab", "/l/libtab2.so"]
    # One rpath per directory.
    assert vcs.count("-Wl,-rpath,/l") == 1
    assert "-debug_access" not in vcs

    status, ctxt, _ = _build(vcs_sim_image, tmpdir,
                             [PliLib("/l/libtab.so", tab="/l/hello.tab")])
    assert "-debug_access" in ctxt.cmd("vcs")


def test_vcs_needs_tab(tmpdir):
    status, ctxt, markers = _build(vcs_sim_image, tmpdir, [BOOT])
    assert status == 1
    assert ctxt.cmds == []
    assert any("tab" in m.msg for m in _errors(markers))


def test_vcs_boot_ignored_warning(tmpdir):
    lib = PliLib("/l/libtab.so", boot="b", tab="/l/hello.tab")
    status, _, markers = _build(vcs_sim_image, tmpdir, [lib])
    assert status == 0
    assert any("ignores `boot`" in m.msg for m in _warnings(markers))


# -- ivl ---------------------------------------------------------------------

def test_ivl_run_cmd(tmpdir):
    lib2 = PliLib("/m/libtwo.so", boot="two_boot")
    status, cmd, _ = _runsim(ivl_sim_run, tmpdir, [BOOT, lib2], check=False)
    assert status == 0
    img = cmd.index(os.path.join(tmpdir, "img", "simv.vpp"))
    assert cmd.index("-mcadpli") < img
    assert cmd.count("-mcadpli") == 1
    assert cmd[img + 1:img + 3] == [
        "-cadpli=/l/libboot.so:my_boot", "-cadpli=/m/libtwo.so:two_boot"]


@pytest.mark.parametrize("lib,msg", [
    (TAB, "tab"),
    (BARE, "boot"),
])
def test_ivl_rejects(tmpdir, lib, msg):
    markers = []
    assert ivl_sim_run.check_ivl_pli([lib], markers) == 1
    assert any(msg in m.msg for m in _errors(markers))


#----------------------------------------------------------------------------
# Live: through the flow graph
#----------------------------------------------------------------------------

class Flow:

    def __init__(self, tmpdir, sim):
        self.sim = sim
        self.rundir = os.path.join(str(tmpdir), "rundir")
        self.runner = TaskSetRunner(self.rundir)
        self.builder = TaskGraphBuilder(
            PackageLoader().load_rgy(["std", "hdlsim", "hdlsim.%s" % sim]),
            self.rundir)
        self.runner.builder = self.builder
        self.tasks = {}

        def listener(task, reason):
            if reason == "leave":
                self.tasks[task.name] = task
        self.runner.add_listener(listener)
        self.runner.add_listener(TaskListenerLog().event)

    def node(self, *args, **kw):
        return self.builder.mkTaskNode(*args, **kw)

    def run(self, *nodes):
        self.out = asyncio.run(self.runner.run(list(nodes)))
        return self.runner.status

    def markers(self, name, severity=None):
        t = self.tasks.get(name)
        ms = list(t.result.markers) if t is not None and t.result else []
        return [m for m in ms if severity is None or m.severity == severity]

    def output(self, name):
        t = self.tasks.get(name)
        return list(t.result.output) if t is not None and t.result else []

    def log(self, name):
        with open(os.path.join(self.rundir, name, "sim.log")) as fp:
            return fp.read()


@pytest.mark.parametrize("sim", get_available_sims(only=("vlt", "xsm", "xzm")))
def test_unsupported_sim_is_error(tmpdir, sim):
    lib = _touch(os.path.join(tmpdir, "libfoo.so"))
    f = Flow(tmpdir, sim)
    src = f.node("std.FileSet", name="src", type="systemVerilogSource",
                 base=DATA_DIR, include="top_pli1.sv")
    pli = f.node("hdlsim.SimPLI", name="pli", lib=lib, boot="pli1_boot")
    img = f.node("hdlsim.%s.SimImage" % sim, name="sim_img",
                 needs=[src, pli], top=["top"])
    assert f.run(img) != 0
    errs = f.markers("sim_img", SeverityE.Error)
    assert any("does not support PLI 1.0" in m.msg for m in errs), errs


@pytest.mark.skipif(shutil.which("iverilog") is None, reason="Icarus not available")
def test_ivl_forwards_pli(tmpdir):
    lib = _touch(os.path.join(tmpdir, "libfoo.so"))
    f = Flow(tmpdir, "ivl")
    src = f.node("std.FileSet", name="src", type="systemVerilogSource",
                 base=DATA_DIR, include="top_pli1.sv")
    pli = f.node("hdlsim.SimPLI", name="pli", lib=lib, boot="pli1_boot")
    img = f.node("hdlsim.ivl.SimImage", name="sim_img",
                 needs=[src, pli], top=["top"])
    assert f.run(img) == 0
    fwd = [o for o in f.output("sim_img")
           if getattr(o, "filetype", None) == "verilogPLI"]
    assert len(fwd) == 1
    assert pli_from_fileset(fwd[0]) == [PliLib(lib, boot="pli1_boot")]


@pytest.mark.skipif(shutil.which("iverilog") is None, reason="Icarus not available")
def test_ivl_run_without_cadpli_is_error(tmpdir):
    libdir = ivl_sim_run.ivl_module_dir()
    if libdir is None or any(os.path.isfile(os.path.join(libdir, "cadpli" + e))
                             for e in (".vpl", ".vpi")):
        pytest.skip("this Icarus has cadpli")
    lib = _touch(os.path.join(tmpdir, "libfoo.so"))
    f = Flow(tmpdir, "ivl")
    src = f.node("std.FileSet", name="src", type="systemVerilogSource",
                 base=DATA_DIR, include="top_pli1.sv")
    pli = f.node("hdlsim.SimPLI", name="pli", lib=lib, boot="pli1_boot")
    img = f.node("hdlsim.ivl.SimImage", name="sim_img",
                 needs=[src, pli], top=["top"])
    run = f.node("hdlsim.ivl.SimRun", name="sim_run", needs=[img])
    assert f.run(run) != 0
    errs = f.markers("sim_run", SeverityE.Error)
    assert any("cadpli" in m.msg for m in errs), errs


def _sim_include(sim):
    """The directory holding the simulator's veriuser.h."""
    if sim == "xcm":
        root = os.path.dirname(os.path.dirname(shutil.which("xmvlog")))
        cands = [os.path.join(root, "include"), os.path.join(root, "inca", "include")]
    else:
        root = os.path.dirname(os.path.dirname(shutil.which("vsim")))
        cands = [os.path.join(root, "include"), os.path.join(root, "..", "include")]
    for c in cands:
        if os.path.isfile(os.path.join(c, "veriuser.h")):
            return c
    pytest.skip("veriuser.h not found for %s" % sim)


def _cc_lib(tmpdir, sim, src):
    lib = os.path.join(str(tmpdir), "lib%s.so" % os.path.splitext(src)[0])
    subprocess.check_call(["gcc", "-shared", "-fPIC", "-I", _sim_include(sim),
                           os.path.join(DATA_DIR, src), "-o", lib])
    return lib


@pytest.mark.parametrize("sim", get_available_sims(only=("xcm", "mti")))
@pytest.mark.parametrize("kind", ["boot", "tab"])
def test_pli_hello(tmpdir, sim, kind):
    f = Flow(tmpdir, sim)
    if kind == "boot":
        lib = _cc_lib(tmpdir, sim, "pli1.c")
        top = "top_pli1.sv"
        pli = f.node("hdlsim.SimPLI", name="pli", lib=lib, boot="pli1_boot")
        expect = "hello from $hello_pli1"
    else:
        lib = _cc_lib(tmpdir, sim, "tabonly.c")
        top = "top_tab.sv"
        pli = f.node("hdlsim.SimPLI", name="pli", lib=lib,
                     tab=os.path.join(DATA_DIR, "hello.tab"))
        expect = "hello from $hello_tab"
    src = f.node("std.FileSet", name="src", type="systemVerilogSource",
                 base=DATA_DIR, include=top)
    img = f.node("hdlsim.%s.SimImage" % sim, name="sim_img",
                 needs=[src, pli], top=["top"])
    run = f.node("hdlsim.%s.SimRun" % sim, name="sim_run", needs=[img])
    assert f.run(run) == 0
    # Questa exits 0 on an undefined systf, so the log is the verdict.
    assert expect in f.log("sim_run")
