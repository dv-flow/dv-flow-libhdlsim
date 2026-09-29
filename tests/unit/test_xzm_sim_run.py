#****************************************************************************
#* test_xzm_sim_run.py
#*
#* xzm (xezim) behavior that the shared parametrized tests don't cover:
#* --error-exit, --max-time, tracing, seeds, VPI, the image manifest, and
#* UVM with the bundled library.
#****************************************************************************
import asyncio
import json
import os
import shutil
import subprocess
import time
import pytest
from dv_flow.mgr import TaskListenerLog, TaskSetRunner, PackageLoader
from dv_flow.mgr.task_data import SeverityE
from dv_flow.mgr.task_graph_builder import TaskGraphBuilder
from dv_flow.libhdlsim import xzm_tool

DATA_DIR = os.path.join(os.path.dirname(__file__), "data", "xzm")
pytestmark = pytest.mark.skipif(shutil.which("xezim") is None,
                                reason="xezim not available")


class Flow:
    """One image + one run (or UVM case) of an xzm design."""

    def __init__(self, tmpdir):
        self.tmpdir = str(tmpdir)
        self.rundir = os.path.join(self.tmpdir, "rundir")
        self.runner = TaskSetRunner(self.rundir)
        self.builder = TaskGraphBuilder(
            PackageLoader().load_rgy(["std", "hdlsim", "hdlsim.xzm"]),
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

    def src(self, include, base=DATA_DIR, name="src"):
        return self.node("std.FileSet", name=name, type="systemVerilogSource",
                         base=base, include=include)

    def image(self, needs, top, **kw):
        return self.node("hdlsim.xzm.SimImage", name="sim_img", needs=needs,
                         top=[top], **kw)

    def run(self, *nodes):
        self.out = asyncio.run(self.runner.run(list(nodes)))
        return self.runner.status

    def result(self, type_="hdlsim.SimRunResult"):
        for out in self.out or []:
            for it in out.output:
                if getattr(it, "type", None) == type_:
                    return it
        return None

    def markers(self, name, severity=None):
        t = self.tasks.get(name)
        ms = list(t.result.markers) if t is not None and t.result else []
        return [m for m in ms if severity is None or m.severity == severity]


def _simple(tmpdir, sv, top, **run_kw):
    f = Flow(tmpdir)
    img = f.image([f.src(sv)], top)
    run = f.node("hdlsim.xzm.SimRun", name="sim_run", needs=[img], **run_kw)
    status = f.run(run)
    return f, status


# --- --error-exit ------------------------------------------------------------

def test_error_fails_run(tmpdir):
    f, status = _simple(tmpdir, "xzm_error.sv", "xzm_error")
    assert status != 0
    with open(os.path.join(f.rundir, "sim_run", "sim.log")) as fp:
        # --error-exit doesn't stop the run at the $error
        assert "xzm_error: after error" in fp.read()


def test_error_is_verdict_in_test_mode(tmpdir):
    f, status = _simple(tmpdir, "xzm_error.sv", "xzm_error", mode="test")
    assert status == 0
    assert f.result().status != 0


def test_warning_passes(tmpdir):
    f, status = _simple(tmpdir, "xzm_warning.sv", "xzm_warning")
    assert status == 0
    assert f.result().status == 0


def test_run_command(tmpdir):
    f, status = _simple(tmpdir, "xzm_seed.sv", "xzm_seed")
    assert status == 0
    cmd = f.result().runinfo["cmd"]
    assert "--error-exit" in cmd
    assert cmd[cmd.index("--max-time") + 1] == "1000000s"
    assert "--report-stats=json" in cmd
    assert cmd[cmd.index("xezim") + 1].endswith("simv.xzb")


# --- --max-time --------------------------------------------------------------

def test_max_time_fails_run_mode(tmpdir):
    f, status = _simple(tmpdir, "xzm_hang.sv", "xzm_hang",
                        args=["--max-time", "10ns"])
    assert status != 0
    errs = f.markers("sim_run", SeverityE.Error)
    assert any("--max-time" in m.msg for m in errs), errs


def test_max_time_is_verdict_in_test_mode(tmpdir):
    f, status = _simple(tmpdir, "xzm_hang.sv", "xzm_hang",
                        args=["--max-time", "10ns"], mode="test")
    assert status == 0
    res = f.result()
    assert res.status != 0
    assert res.runinfo["finish_reason"] == "max_time"
    assert f.markers("sim_run", SeverityE.Error) == []


def test_user_max_time_replaces_default(tmpdir):
    f, status = _simple(tmpdir, "xzm_hang.sv", "xzm_hang",
                        args=["--max-time", "10ns"], mode="test")
    cmd = f.result().runinfo["cmd"]
    assert cmd.count("--max-time") == 1
    assert "1000000s" not in cmd


# --- tracing -----------------------------------------------------------------

def _traces(res):
    return [os.path.join(fs.basedir, p)
            for fs in res.artifacts if fs.filetype == "simTrace"
            for p in fs.files]


def test_trace_fst_from_simrun(tmpdir):
    f, status = _simple(tmpdir, "xzm_trace.sv", "xzm_trace", trace=True)
    assert status == 0
    fst = os.path.join(f.rundir, "sim_run", "sim.fst")
    assert os.path.isfile(fst)
    assert fst in _traces(f.result())


def test_trace_fmt_from_debug_elab_args(tmpdir):
    # The debug elab preset records the format in the image manifest; the run
    # needs no trace flag of its own.
    f = Flow(tmpdir)
    dbg = f.node("hdlsim.xzm.SimElabArgsDbg", name="dbg", trace_fmt="vcd")
    img = f.image([f.src("xzm_trace.sv"), dbg], "xzm_trace")
    run = f.node("hdlsim.xzm.SimRun", name="sim_run", needs=[img])
    assert f.run(run) == 0
    with open(os.path.join(f.rundir, "sim_img", "xezim_image.json")) as fp:
        assert json.load(fp)["trace_fmt"] == "vcd"
    assert "--wave" in f.result().runinfo["cmd"]
    vcd = os.path.join(f.rundir, "sim_run", "xzm_trace.vcd")
    assert os.path.isfile(vcd)
    assert vcd in _traces(f.result())


def test_no_trace_by_default(tmpdir):
    f, status = _simple(tmpdir, "xzm_trace.sv", "xzm_trace")
    assert status == 0
    assert _traces(f.result()) == []


# --- stats and seed ------------------------------------------------------------

def test_stats_and_default_seed(tmpdir):
    f, status = _simple(tmpdir, "xzm_seed.sv", "xzm_seed")
    assert status == 0
    res = f.result()
    assert res.runinfo["sim_version"].startswith("xezim ")
    assert res.runinfo["finish_reason"] == "$finish"
    assert res.runinfo["seed"] == 1
    assert res.runinfo["seed_source"] == "default"
    assert "simtime" in res.stats


def test_explicit_seed(tmpdir):
    f, status = _simple(tmpdir, "xzm_seed.sv", "xzm_seed", plusargs=["seed=7"])
    assert status == 0
    assert f.result().runinfo["seed"] == 7
    assert f.result().runinfo["seed_source"] == "+seed"


# --- image -------------------------------------------------------------------

def test_parse_error_marker(tmpdir):
    f = Flow(tmpdir)
    base = os.path.join(DATA_DIR, "parse_error")
    img = f.image([f.src("xzm_parse_error.sv", base=base)], "xzm_parse_error")
    assert f.run(img) != 0
    # Besides the generic "Command failed", the parser's located marker
    located = [m for m in f.markers("sim_img", SeverityE.Error) if m.loc]
    assert len(located) == 1, f.markers("sim_img")
    assert located[0].msg == "expected Semicolon, found KwEnd 'end'"
    assert os.path.basename(located[0].loc.path) == "xzm_parse_error.sv"
    assert located[0].loc.line == 4


def test_manifest(tmpdir):
    f, status = _simple(tmpdir, "xzm_seed.sv", "xzm_seed")
    assert status == 0
    with open(os.path.join(f.rundir, "sim_img", "xezim_image.json")) as fp:
        m = json.load(fp)
    assert m["artifact"] == "simv.xzb"
    assert m["version"] == xzm_tool.xezim_version()
    assert m["trace_fmt"] == "none"
    assert m["dpi"] == []


def test_rebuild_when_xezim_version_changes(tmpdir):
    def build():
        f = Flow(tmpdir)
        img = f.image([f.src("xzm_seed.sv")], "xzm_seed")
        assert f.run(img) == 0
        return f.tasks["sim_img"].output.changed

    assert build() is True
    time.sleep(1)
    assert build() is False  # nothing changed: up to date

    manifest = os.path.join(str(tmpdir), "rundir", "sim_img", "xezim_image.json")
    with open(manifest) as fp:
        m = json.load(fp)
    m["version"] = "xezim version 0.0.1; git 00000000"
    with open(manifest, "w") as fp:
        json.dump(m, fp)

    assert build() is True


# --- VPI ---------------------------------------------------------------------

def _vpi_lib(tmpdir):
    inc = os.path.join(xzm_tool.xezim_prefix(), "include")
    lib = os.path.join(str(tmpdir), "libxzm_vpi.so")
    subprocess.check_call(["cc", "-shared", "-fPIC", "-I", inc,
                           os.path.join(DATA_DIR, "xzm_vpi.c"), "-o", lib])
    return lib


@pytest.mark.parametrize("entrypoint", [None, "my_vpi_init"])
def test_vpi_lib(tmpdir, entrypoint):
    lib = _vpi_lib(tmpdir)
    f = Flow(tmpdir)
    vpi = f.node("std.FileSet", name="vpi", type="verilogVPI",
                 base=os.path.dirname(lib), include=os.path.basename(lib),
                 attributes=["entrypoint=%s" % entrypoint] if entrypoint else [])
    img = f.image([f.src("xzm_vpi.sv"), vpi], "xzm_vpi")
    run = f.node("hdlsim.xzm.SimRun", name="sim_run", needs=[img])
    assert f.run(run) == 0
    with open(os.path.join(f.rundir, "sim_run", "sim.log")) as fp:
        assert "xzm_vpi: startup routine ran" in fp.read()
    warns = f.markers("sim_run", SeverityE.Warning)
    if entrypoint:
        assert any("entrypoint" in m.msg for m in warns), warns
    else:
        assert warns == []


# --- UVM (bundled library) ------------------------------------------------------

def _uvm_case(tmpdir, testname, **kw):
    f = Flow(tmpdir)
    uvm = f.node("hdlsim.xzm.SimLibUVM", name="uvm")
    tb = f.src("xzm_uvm_tb.sv", base=os.path.join(DATA_DIR, "uvm"), name="tb")
    img = f.image([uvm, tb], "xzm_uvm_tb")
    case = f.node("hdlsim.xzm.SimUVMCase", name="case", needs=[img],
                  testname=testname, **kw)
    status = f.run(case)
    return f, status, f.result("hdlsim.TestResult")


def test_uvm_pass(tmpdir):
    f, status, tr = _uvm_case(tmpdir, "pass_test")
    assert status == 0
    assert tr is not None
    assert tr.passed is True
    assert tr.sim == "xzm"


def test_uvm_max_time_is_failed_case(tmpdir):
    f, status, tr = _uvm_case(tmpdir, "hang_test", args=["--max-time", "1us"])
    assert status == 0  # verdict-as-data
    assert tr.passed is False
    assert tr.run_status != 0
    assert tr.runinfo["finish_reason"] == "max_time"
