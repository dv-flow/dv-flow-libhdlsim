#****************************************************************************
#* test_prof.py
#*
#* Simulator profiling: the mode vocabulary and prof.json record (prof.py),
#* the summary and its stats, the per-backend report parsers against captured
#* fixtures, and the SimProfArgs type. Real simulator runs live further down
#* and skip when the simulator isn't installed.
#****************************************************************************
import asyncio
import json
import os

import pytest

from dv_flow.libhdlsim import prof, sim_stats

DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "prof")


def _read(name):
    with open(os.path.join(DATA, name)) as fp:
        return fp.read()


#---------------------------------------------------------------------------
# Modes and the prof.json record
#---------------------------------------------------------------------------

def test_resolve_mode():
    assert prof.resolve_mode() == "none"
    assert prof.resolve_mode("none", "none") == "none"
    assert prof.resolve_mode("none", "time", "time") == "time"
    assert prof.resolve_mode("mem", "none") == "mem"


def test_resolve_mode_conflict():
    with pytest.raises(ValueError, match="'time' and 'mem'"):
        prof.resolve_mode("time", "mem")


def test_resolve_mode_unknown():
    with pytest.raises(ValueError, match="none, time, mem"):
        prof.resolve_mode("cpu")


def test_prof_json_roundtrip(tmpdir):
    prof.write_prof_json(str(tmpdir), "time")
    assert prof.read_prof_json(str(tmpdir)) == {"mode": "time"}
    prof.remove_prof_json(str(tmpdir))
    assert prof.read_prof_json(str(tmpdir)) is None


def test_prof_json_deep(tmpdir):
    """A deep profiler alone records mode `none`; the record still counts."""
    prof.write_prof_json(str(tmpdir), "none", {"xprof": True})
    assert prof.read_prof_json(str(tmpdir)) == {"mode": "none",
                                                "deep": {"xprof": True}}
    prof.write_prof_json(str(tmpdir), "time", {})
    assert prof.read_prof_json(str(tmpdir)) == {"mode": "time"}


def test_prof_json_unreadable(tmpdir):
    tmpdir.join(prof.PROF_FILE).write("{not json")
    assert prof.read_prof_json(str(tmpdir)) is None
    tmpdir.join(prof.PROF_FILE).write('{"mode": "none"}')
    assert prof.read_prof_json(str(tmpdir)) is None


#---------------------------------------------------------------------------
# The summary and its stats
#---------------------------------------------------------------------------

def test_make_summary_drops_zero_and_sorts():
    s = prof.make_summary("time", "vcs", {"hdl": 10.0, "tb": 0.001, "bogus": 5},
                          [{"name": "a", "pct": 1.0}, {"name": "b", "pct": 9.0}])
    assert s["categories"] == {"hdl": 10.0}
    assert [t["name"] for t in s["top"]] == ["b", "a"]
    assert "mem_peak_mb" not in s


def test_make_summary_top_is_capped():
    top = [{"name": str(i), "pct": float(i)} for i in range(50)]
    s = prof.make_summary("time", "vcs", {}, top)
    assert len(s["top"]) == prof.TOP_N and s["top"][0]["name"] == "49"


def test_summary_stats_time():
    s = prof.make_summary("time", "xcm", {"solver": 50.0, "hdl": 25.0}, [])
    assert prof.summary_stats(s, 4.0) == {
        "prof_solver_pct": 50.0, "prof_solver_s": 2.0,
        "prof_hdl_pct": 25.0, "prof_hdl_s": 1.0}
    # Without a CPU time there are no seconds
    assert prof.summary_stats(s) == {"prof_solver_pct": 50.0, "prof_hdl_pct": 25.0}


def test_summary_stats_mem():
    s = prof.make_summary("mem", "xcm", {"kernel": 90.0}, [], 104.94)
    assert prof.summary_stats(s, 4.0) == {
        "prof_kernel_pct": 90.0, "prof_mem_peak_mb": 104.9}


def test_stat_keys_declared():
    for c in prof.CATEGORIES:
        assert sim_stats.STAT_KEYS["prof_%s_pct" % c][1] == "none"
        assert sim_stats.STAT_KEYS["prof_%s_s" % c][1] == "sum"
    assert sim_stats.STAT_KEYS["prof_mem_peak_mb"][1] == "max"
    assert "prof" in sim_stats.INFO_KEYS


def test_aggregate_prof():
    agg = sim_stats.aggregate([
        {"prof_solver_pct": 60.0, "prof_solver_s": 3.0},
        {"prof_solver_pct": 20.0, "prof_solver_s": 1.0},
    ])
    assert agg["prof_solver_s"] == 4.0
    assert "prof_solver_pct" not in agg


#---------------------------------------------------------------------------
# VCS profileReport.json (fixtures: VCS Y-2026.03, prof_top-like design)
#---------------------------------------------------------------------------

def test_parse_vcs_time():
    s = prof.parse_vcs_profile(json.loads(_read("vcs_time.json")), "time")
    c = s["categories"]
    assert s["mode"] == "time" and s["sim"] == "vcs"
    # CONSTRAINT; VERILOG split into Module / Package / coverage
    assert c == {"solver": 65.28, "hdl": 8.31, "tb": 6.23, "cov": 4.75,
                 "pli": 0.3, "kernel": 15.13}
    assert sum(c.values()) == pytest.approx(100.0, abs=0.05)
    assert s["top"][0] == {"scope": "module", "name": "top", "pct": 10.39,
                           "instances": 17}
    # _global_ is $unit
    assert [t["name"] for t in s["top"]] == ["top", "$unit", "cnt"]


def test_parse_vcs_mem():
    s = prof.parse_vcs_profile(json.loads(_read("vcs_mem.json")), "mem")
    assert s["mem_peak_mb"] == 439.0
    assert s["categories"]["kernel"] > 99
    assert s["top"][0]["name"] == "$unit" and s["top"][0]["bytes"] == 286814


def test_parse_vcs_wrong_mode():
    # A time report has no memory section
    assert prof.parse_vcs_profile(json.loads(_read("vcs_time.json")), "mem") is None
    assert prof.parse_vcs_profile([], "time") is None


#---------------------------------------------------------------------------
# Xcelium xmprof.out / xmprofmem.* (fixtures: Xcelium 26.03-s005)
#---------------------------------------------------------------------------

def test_parse_xcm_time():
    s = prof.parse_xcm_xmprof(_read("xcm_xmprof.out"))
    c = s["categories"]
    # Technology-wise: Randomization 250, TB/SV 146, Miscellaneous 88,
    # RTL/Design 31, Analysis 4 (of 519). Outside engine (65) moves from
    # Miscellaneous to pli; Assertions (21) from RTL/Design to assert.
    assert c["solver"] == round(100 * 250 / 519, 2)
    assert c["tb"] == round(100 * 146 / 519, 2)
    assert c["pli"] == round(100 * 65 / 519, 2)
    assert c["kernel"] == round(100 * 23 / 519, 2)
    assert c["assert"] == round(100 * 21 / 519, 2)
    assert c["hdl"] == round(100 * 10 / 519, 2)
    assert c["other"] == round(100 * 4 / 519, 2)
    assert s["top"] == [
        {"scope": "module", "name": "$unit", "pct": 23.7, "instances": 1},
        {"scope": "module", "name": "top", "pct": 8.3, "instances": 1},
        {"scope": "module", "name": "cnt", "pct": 1.0, "instances": 16}]


def test_parse_xcm_time_garbage():
    assert prof.parse_xcm_xmprof("") is None
    assert prof.parse_xcm_xmprof("xmsim: nothing here\n") is None


def test_parse_xcm_mem():
    s = prof.parse_xcm_xmprofmem(_read("xcm_xmprofmem.json"),
                                 _read("xcm_xmprofmem.out"))
    # Peak `current physical memory` over the samples, in KB
    assert s["mem_peak_mb"] == round(107428 / 1024.0, 1)
    assert s["categories"] == {}
    assert [(t["name"], t["bytes"]) for t in s["top"]] == [
        ("top", 49618), ("$unit", 31012), ("cnt", 10760)]


def test_parse_xcm_mem_without_report():
    s = prof.parse_xcm_xmprofmem(_read("xcm_xmprofmem.json"))
    assert s["mem_peak_mb"] > 0 and s["top"] == []
    assert prof.parse_xcm_xmprofmem("") is None


def test_parse_mti_time():
    s = prof.parse_mti_report(_read("mti_time_report.txt"), "time")
    assert s["sim"] == "mti"
    # Performance/Summary; Questa's `SV` row holds RTL and class code alike
    assert s["categories"] == {"hdl": 34.48, "solver": 25.86, "cov": 20.69,
                               "kernel": 10.34, "pli": 8.62}
    # <AdvanceTime> and friends are the kernel, not design units
    assert s["top"] == [{"scope": "module", "name": "top", "pct": 89.66,
                         "instances": 1}]


def test_parse_mti_mem():
    s = prof.parse_mti_report(_read("mti_mem_report.txt"), "mem")
    assert s["mem_peak_mb"] == 710.4
    c = s["categories"]
    assert c["other"] == 76.91      # Non-Kernel
    assert c["kernel"] == 22.84     # Kernel + Reserved
    assert c["assert"] == 0.13 and c["solver"] == 0.06
    assert sum(c.values()) == pytest.approx(100.0, abs=0.5)
    # Design units only: not the library or Module/Package grouping rows
    assert [t["name"] for t in s["top"]] == ["prof_top", "std"]
    assert s["top"][0]["bytes"] == int(0.78 * 1024 * 1024)


def test_parse_mti_wrong_mode():
    assert prof.parse_mti_report(_read("mti_time_report.txt"), "mem") is None
    assert prof.parse_mti_report(_read("mti_mem_report.txt"), "time") is None
    assert prof.parse_mti_report("", "time") is None


def test_parse_vlt():
    s = prof.parse_vlt_profcfunc(_read("vlt_profcfunc.txt"))
    assert s["sim"] == "vlt" and s["mode"] == "time"
    assert s["categories"] == {"hdl": 65.22, "kernel": 22.81, "other": 8.69,
                               "cov": 3.26}
    # Verilator attributes blocks to source files
    assert s["top"] == [{"scope": "file", "name": "rtl", "pct": 19.57}]


def test_parse_vlt_cxx_split():
    """Plain C++ splits by name: the randomizer, coverage, the rest of the
    runtime, and anything else."""
    rows = [
        (50.0, "C++", "VlRandomizer::next(VlRNG&)"),
        (20.0, "C++", "bool VlRandomizer::parseSolution(std::iostream&)"),
        (10.0, "C++", "VlCoverpointT<1u>::incrementBin(unsigned int)"),
        (10.0, "C++", "VlDelayScheduler::resume()"),
        (5.0, "C++", "std::deque<unsigned int>::push_back(unsigned int const&)"),
        (5.0, "VCommon", "Vtop___024root___eval(Vtop___024root*)"),
    ]
    text = "".join("%6.2f %9.2f %8.2f %10d   %-4s  %-9s %s\n" % (
        pct, 0.0, 0.0, 1, "-" if k == "C++" else "Vtop", k, n)
        for pct, k, n in rows)
    s = prof.parse_vlt_profcfunc(text)
    assert s["categories"] == {"solver": 70.0, "cov": 10.0, "kernel": 10.0,
                               "other": 5.0, "hdl": 5.0}
    assert s["top"] == []
    assert prof.parse_vlt_profcfunc("Overall summary by type:\n") is None


#---------------------------------------------------------------------------
# The SimProfArgs type and the package `prof` var
#---------------------------------------------------------------------------

_FLOW = '''
package:
  name: foo
  imports:
    - name: hdlsim
  tasks:
  - name: bare
    uses: hdlsim.SimProfArgs
  - name: holder
    uses: hdlsim.SimProfArgs
    with: { mode: mem }
  - name: show
    pytask: prof_probe.show
    needs: [{task}]
    uptodate: false
'''

_PROBE = '''
import json, os
from dv_flow.mgr import TaskDataResult
async def show(ctxt, input):
    modes = [i.mode for i in input.inputs if getattr(i, "type", None) == "hdlsim.SimProfArgs"]
    with open(os.path.join(os.environ["PROF_PROBE_OUT"]), "w") as fp:
        json.dump(modes, fp)
    return TaskDataResult()
'''


def _prof_items(tmpdir, task, defines=()):
    """Run `task` through the dfm CLI and return the `mode` of each
    SimProfArgs item it outputs (a subprocess: see test_cov._cov_items)."""
    import subprocess, sys
    d = str(tmpdir)
    with open(os.path.join(d, "flow.dv"), "w") as f:
        f.write(_FLOW.replace("{task}", task))
    with open(os.path.join(d, "prof_probe.py"), "w") as f:
        f.write(_PROBE)
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(
        [d] + ([env["PYTHONPATH"]] if env.get("PYTHONPATH") else []))
    env["PROF_PROBE_OUT"] = os.path.join(d, "modes.json")
    cmd = [sys.executable, "-m", "dv_flow.mgr", "run"]
    for dfn in defines:
        cmd += ["-D", dfn]
    subprocess.check_call(cmd + ["show"], cwd=d, env=env,
                          stdout=subprocess.DEVNULL)
    with open(env["PROF_PROBE_OUT"]) as fp:
        return json.load(fp)


def test_simprofargs_defaults_to_none(tmpdir):
    assert _prof_items(tmpdir, "bare") == ["none"]


def test_simprofargs_holder(tmpdir):
    assert _prof_items(tmpdir, "holder") == ["mem"]


def test_simprofargs_follows_package_var(tmpdir):
    assert _prof_items(tmpdir, "bare", ["hdlsim.prof=time"]) == ["time"]
    assert _prof_items(tmpdir.mkdir("h"), "holder", ["hdlsim.prof=time"]) == ["mem"]


#---------------------------------------------------------------------------
# Real builds and runs
#---------------------------------------------------------------------------

from dv_flow.mgr import TaskSetRunner, PackageLoader
from dv_flow.mgr.task_data import SeverityE
from dv_flow.mgr.task_graph_builder import TaskGraphBuilder
from .sims import get_available_sims

ALL_SIMS = get_available_sims()
PROF_SIMS = get_available_sims(only=("vcs", "xcm"))
COV_DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "cov")


class ProfRun(object):
    """One SimImage + SimRun of a test design, and what came out.

    prof_param -- SimImage `prof`
    prof_items -- one `uses: hdlsim.SimProfArgs` holder per mode
    img_with   -- more SimImage params
    items      -- more holders the image needs, as (uses, with)
    """

    def __init__(self, tmpdir, sim, prof_param=None, prof_items=(),
                 top="prof_top", base=DATA, img_with=None, items=()):
        d = str(tmpdir)
        self.rundir = os.path.join(d, "rundir")
        tasks = [{"name": "src", "uses": "std.FileSet",
                  "with": {"type": "systemVerilogSource", "base": base,
                           "include": "%s.sv" % top}}]
        needs = ["src"]
        for i, mode in enumerate(prof_items):
            tasks.append({"name": "profargs%d" % i, "uses": "hdlsim.SimProfArgs",
                          "with": {"mode": mode}})
            needs.append("profargs%d" % i)
        for i, (uses, with_) in enumerate(items):
            tasks.append({"name": "item%d" % i, "uses": uses, "with": with_})
            needs.append("item%d" % i)
        img_with = dict(img_with or {}, top=[top])
        if prof_param is not None:
            img_with["prof"] = prof_param
        tasks.append({"name": "sim_img", "uses": "hdlsim.%s.SimImage" % sim,
                      "needs": needs, "with": img_with})
        tasks.append({"name": "sim_run", "uses": "hdlsim.%s.SimRun" % sim,
                      "needs": ["sim_img"], "with": {"sim": sim}})
        flow = {"package": {"name": "t", "imports": [{"name": "hdlsim"}],
                            "tasks": tasks}}
        with open(os.path.join(d, "flow.dv"), "w") as fp:
            json.dump(flow, fp, indent=1)     # JSON is YAML

        loader = PackageLoader()
        pkg = loader.load(os.path.join(d, "flow.dv"))
        builder = TaskGraphBuilder(root_pkg=pkg, rundir=self.rundir, loader=loader)
        runner = TaskSetRunner(self.rundir)
        runner.builder = builder
        sim_run = builder.mkTaskNode("t.sim_run")

        self.markers = {}

        def listener(task, reason):
            if reason == "leave" and task.result is not None:
                self.markers.setdefault(task.name, []).extend(task.result.markers)

        runner.add_listener(listener)
        out_l = asyncio.run(runner.run([sim_run]))
        self.status = runner.status
        self.result = None
        for out in (out_l or []):
            for item in out.output:
                if getattr(item, "type", None) == "hdlsim.SimRunResult":
                    self.result = item

    def task_markers(self, frag, severity):
        return [m for name, ms in self.markers.items() if frag in name
                for m in ms if m.severity == severity]

    def _task_dir(self, name):
        for cand in (name, "t." + name):
            p = os.path.join(self.rundir, cand)
            if os.path.isdir(p):
                return p
        raise AssertionError("no rundir for %s under %s" % (name, self.rundir))

    @property
    def imgdir(self):
        return self._task_dir("sim_img")

    def artifacts(self, filetype):
        return [a for a in self.result.artifacts if a.filetype == filetype]

    def prof_stats(self):
        return {k: v for k, v in self.result.stats.items() if k.startswith("prof_")}

    def summary(self):
        fs = self.artifacts("simProfSummary")
        assert len(fs) == 1, self.result.artifacts
        return prof.read_summary(os.path.join(fs[0].basedir, fs[0].files[0]))


@pytest.mark.parametrize("sim", ALL_SIMS)
def test_none_is_unchanged(tmpdir, sim):
    """The default collects nothing: no prof.json, no runinfo.prof, no
    profiling artifacts, no prof_* stats, no warning."""
    r = ProfRun(tmpdir, sim, top="plain_top", base=COV_DATA)
    assert r.status == 0
    assert not os.path.exists(os.path.join(r.imgdir, prof.PROF_FILE))
    assert "prof" not in r.result.runinfo
    for ft in ("simProfDb", "simProfReport", "simProfSummary"):
        assert r.artifacts(ft) == []
    assert r.prof_stats() == {}
    assert r.task_markers("sim_img", SeverityE.Warning) == []


@pytest.mark.parametrize("sim,mode",
    [(s, "time") for s in get_available_sims(exclude=("vcs", "xcm", "mti", "vlt"))]
    + [(s, "mem") for s in get_available_sims(exclude=("vcs", "xcm", "mti"))])
def test_unsupported_backend_warns(tmpdir, sim, mode):
    r = ProfRun(tmpdir, sim, prof_param=mode, top="plain_top", base=COV_DATA)
    assert r.status == 0
    warns = r.task_markers("sim_img", SeverityE.Warning)
    assert any("'%s' profiling" % mode in w.msg for w in warns), warns
    assert not os.path.exists(os.path.join(r.imgdir, prof.PROF_FILE))
    assert "prof" not in r.result.runinfo


@pytest.mark.parametrize("sim", ALL_SIMS[:1])
def test_conflicting_modes_error(tmpdir, sim):
    r = ProfRun(tmpdir, sim, prof_param="time", prof_items=["mem"],
                top="plain_top", base=COV_DATA)
    assert r.status != 0
    errs = r.task_markers("sim_img", SeverityE.Error)
    assert any("Conflicting profiling modes" in e.msg for e in errs), errs


@pytest.mark.parametrize("sim", ALL_SIMS[:1])
def test_unknown_mode_errors(tmpdir, sim):
    r = ProfRun(tmpdir, sim, prof_items=["cpu"], top="plain_top", base=COV_DATA)
    assert r.status != 0
    errs = r.task_markers("sim_img", SeverityE.Error)
    assert any("'cpu'" in e.msg for e in errs), errs


def _check_time(r, sim, db_format):
    assert r.status == 0, r.markers
    assert prof.read_prof_json(r.imgdir) == {"mode": "time"}
    assert r.result.runinfo["prof"] == {"mode": "time"}
    s = r.summary()
    assert s["mode"] == "time" and s["sim"] == sim
    # The design spends its time solving constraints
    assert s["categories"]["solver"] > 10
    assert sum(s["categories"].values()) == pytest.approx(100.0, abs=0.5)
    assert any(t["name"] == "prof_top" for t in s["top"]), s["top"]
    st = r.prof_stats()
    assert st["prof_solver_pct"] == s["categories"]["solver"]
    assert st["prof_solver_s"] > 0
    db = r.artifacts("simProfDb")
    assert len(db) == 1 and "format=%s" % db_format in db[0].attributes
    assert len(r.artifacts("simProfReport")) == 1


def _check_mem(r, sim, db_format):
    assert r.status == 0, r.markers
    assert r.result.runinfo["prof"] == {"mode": "mem"}
    s = r.summary()
    assert s["mode"] == "mem" and s["mem_peak_mb"] > 0
    assert r.prof_stats()["prof_mem_peak_mb"] == s["mem_peak_mb"]
    assert not any(k.endswith("_s") for k in r.prof_stats())
    db = r.artifacts("simProfDb")
    assert len(db) == 1 and "format=%s" % db_format in db[0].attributes


needs_vcs = pytest.mark.skipif("vcs" not in ALL_SIMS, reason="vcs not installed")
needs_xcm = pytest.mark.skipif("xcm" not in ALL_SIMS, reason="xcelium not installed")
needs_mti = pytest.mark.skipif("mti" not in ALL_SIMS, reason="questa not installed")
needs_vlt = pytest.mark.skipif("vlt" not in ALL_SIMS, reason="verilator not installed")


@needs_vcs
def test_vcs_time(tmpdir):
    _check_time(ProfRun(tmpdir, "vcs", prof_param="time"), "vcs",
                prof.FORMAT_VCS_SIMPROFILE)


@needs_vcs
def test_vcs_mem_from_item(tmpdir):
    _check_mem(ProfRun(tmpdir, "vcs", prof_items=["mem"]), "vcs",
               prof.FORMAT_VCS_SIMPROFILE)


@pytest.mark.parametrize("sim", get_available_sims(only=("vcs", "vlt")))
def test_mode_change_rebuilds_clean(tmpdir, sim):
    """time -> none in the same rundir: the image drops its record and the
    run leaves no profile behind. Both backends rebuild from scratch."""
    r = ProfRun(tmpdir, sim, prof_param="time")
    assert r.status == 0
    r = ProfRun(tmpdir, sim, prof_param="none")
    assert r.status == 0
    assert prof.read_prof_json(r.imgdir) is None
    assert "prof" not in r.result.runinfo
    assert r.artifacts("simProfDb") == [] and r.artifacts("simProfSummary") == []


@needs_xcm
def test_xcm_time(tmpdir):
    _check_time(ProfRun(tmpdir, "xcm", prof_param="time"), "xcm",
                prof.FORMAT_XCELIUM_XMPROF)


@needs_xcm
def test_xcm_mem(tmpdir):
    r = ProfRun(tmpdir, "xcm", prof_param="mem")
    _check_mem(r, "xcm", prof.FORMAT_XCELIUM_XMPROFMEM)
    assert any(t["name"] == "prof_top" for t in r.summary()["top"])


@needs_mti
def test_mti_time(tmpdir):
    r = ProfRun(tmpdir, "mti", prof_param="time")
    _check_time(r, "mti", prof.FORMAT_QUESTA_FDB)
    # vopt profiled too: its database sits in the image
    assert os.path.isdir(os.path.join(r.imgdir, "fprofile"))


@needs_mti
def test_mti_mem(tmpdir):
    r = ProfRun(tmpdir, "mti", prof_items=["mem"])
    _check_mem(r, "mti", prof.FORMAT_QUESTA_FDB)
    assert len(r.artifacts("simProfReport")) == 1
    assert any(t["name"] == "prof_top" for t in r.summary()["top"])


@needs_vlt
def test_vlt_time(tmpdir):
    """gprof samples only the simulator binary, and Verilator's constraint
    solver runs in a child process, so the categories aren't checked."""
    r = ProfRun(tmpdir, "vlt", prof_param="time")
    assert r.status == 0, r.markers
    assert r.result.runinfo["prof"] == {"mode": "time"}
    s = r.summary()
    assert s["mode"] == "time" and s["sim"] == "vlt"
    assert sum(s["categories"].values()) == pytest.approx(100.0, abs=0.5)
    db = r.artifacts("simProfDb")
    assert len(db) == 1 and "format=%s" % prof.FORMAT_VLT_GMON in db[0].attributes
    assert sorted(r.artifacts("simProfReport")[0].files) == \
        ["gprof.out", "prof_report.txt"]


#---------------------------------------------------------------------------
# Deep profilers
#---------------------------------------------------------------------------

XPROF = {"mode": "none", "deep": {"xprof": True}}
XPROF_ITEM = ("hdlsim.XcmProfArgs", {"xprof": True})


def _check_xprof(r):
    """xProf's database and its three reports came out."""
    db = r.artifacts("simProfDb")
    assert len(db) == 1 and "format=%s" % prof.FORMAT_XCELIUM_XPROF in db[0].attributes
    assert db[0].files == ["xprof"]
    assert os.path.isdir(os.path.join(db[0].basedir, "xprof", "prof_cpu", "prof_db"))
    rpt = r.artifacts("simProfReport")
    assert len(rpt) == 1
    assert sorted(rpt[0].files) == ["xprof_category.txt", "xprof_inst.txt",
                                    "xprof_type.txt"]
    with open(os.path.join(rpt[0].basedir, "xprof_type.txt")) as fp:
        assert "worklib.prof_top" in fp.read()


@needs_xcm
def test_xcm_xprof(tmpdir):
    """xProf alone: its outputs, but no summary and no prof_* stats."""
    r = ProfRun(tmpdir, "xcm", img_with={"xprof": True})
    assert r.status == 0, r.markers
    assert prof.read_prof_json(r.imgdir) == XPROF
    assert r.result.runinfo["prof"] == XPROF
    _check_xprof(r)
    assert r.artifacts("simProfSummary") == []
    assert r.prof_stats() == {}

    # Dropped again in the same rundir: no xProf output left behind
    r = ProfRun(tmpdir, "xcm", top="plain_top", base=COV_DATA)
    assert r.status == 0, r.markers
    assert "prof" not in r.result.runinfo
    assert r.artifacts("simProfDb") == [] and r.artifacts("simProfReport") == []
    assert not os.path.exists(os.path.join(r.result.artifacts[0].basedir, "xprof"))


@needs_xcm
def test_xcm_xprof_with_time(tmpdir):
    """Requested by the typed args, with `time`: xProf's summary feeds the
    usual prof_summary.json and stats."""
    r = ProfRun(tmpdir, "xcm", prof_param="time", items=[XPROF_ITEM])
    assert r.status == 0, r.markers
    assert r.result.runinfo["prof"] == {"mode": "time", "deep": {"xprof": True}}
    _check_xprof(r)
    s = r.summary()
    assert s["mode"] == "time" and s["categories"]["solver"] > 10
    assert r.prof_stats()["prof_solver_pct"] == s["categories"]["solver"]


@needs_xcm
def test_xcm_xprof_with_mem_errors(tmpdir):
    r = ProfRun(tmpdir, "xcm", prof_param="mem", items=[XPROF_ITEM],
                top="plain_top", base=COV_DATA)
    assert r.status != 0
    errs = r.task_markers("sim_img", SeverityE.Error)
    assert any("xProf and 'mem'" in e.msg for e in errs), errs


@pytest.mark.parametrize("sim", get_available_sims(only=("vcs", "mti")))
def test_other_sims_ignore_xcm_args(tmpdir, sim):
    """Another simulator's image consumes XcmProfArgs without a word."""
    r = ProfRun(tmpdir, sim, items=[XPROF_ITEM], top="plain_top", base=COV_DATA)
    assert r.status == 0, r.markers
    assert not os.path.exists(os.path.join(r.imgdir, prof.PROF_FILE))
    assert "prof" not in r.result.runinfo
    assert r.task_markers("sim_img", SeverityE.Warning) == []
