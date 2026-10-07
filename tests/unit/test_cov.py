#****************************************************************************
#* test_cov.py
#*
#* Coverage collection: the level vocabulary and cov.json record (cov.py), the
#* per-backend summary parsers against captured fixtures, and the SimCovArgs
#* type. Real simulator runs live further down and skip when the simulator
#* isn't installed.
#****************************************************************************
import json
import os
import shutil

import pytest

from dv_flow.libhdlsim import cov

DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "cov")


def _fixture(name):
    return os.path.join(DATA, name)


def _kinds_in(stats):
    return set(k[len("cov_"):].rsplit("_", 1)[0] for k in stats)


#---------------------------------------------------------------------------
# Levels
#---------------------------------------------------------------------------

def test_level_rank_order():
    assert [cov.level_rank(l) for l in ("none", "func", "code", "full")] == [0, 1, 2, 3]


def test_level_rank_unknown():
    with pytest.raises(ValueError) as ei:
        cov.level_rank("medium")
    msg = str(ei.value)
    assert "medium" in msg
    assert "none, func, code, full" in msg


def test_max_level():
    assert cov.max_level() == "none"
    assert cov.max_level("func", "code") == "code"
    assert cov.max_level("full", "none", "func") == "full"
    with pytest.raises(ValueError):
        cov.max_level("func", "bogus")


#---------------------------------------------------------------------------
# cov.json
#---------------------------------------------------------------------------

def test_cov_json_roundtrip(tmpdir):
    d = str(tmpdir)
    cov.write_cov_json(d, "code", ["line", "branch"])
    assert cov.read_cov_json(d) == {"level": "code", "kinds": ["line", "branch"]}
    cov.remove_cov_json(d)
    assert cov.read_cov_json(d) is None


def test_cov_json_missing(tmpdir):
    assert cov.read_cov_json(str(tmpdir)) is None
    cov.remove_cov_json(str(tmpdir))    # no file: not an error


def test_cov_json_unreadable(tmpdir):
    with open(os.path.join(str(tmpdir), cov.COV_FILE), "w") as fp:
        fp.write("{not json")
    assert cov.read_cov_json(str(tmpdir)) is None


#---------------------------------------------------------------------------
# Verilator summary parser (fixtures: verilator_coverage 5.052)
#---------------------------------------------------------------------------

def _vlt(level, kinds=None):
    with open(_fixture("vlt_summary_%s.txt" % level)) as fp:
        return cov.parse_vlt_cov_summary(fp.read(), kinds)


def test_vlt_summary_func():
    s = _vlt("func")
    assert s["cov_covergroup_covered"] == 3 and s["cov_covergroup_total"] == 4
    assert s["cov_covergroup_pct"] == 75.0
    assert s["cov_user_pct"] == 100.0
    # 0/0 kinds report nothing rather than a false 0%
    assert not any(k.startswith("cov_line_") for k in s)
    assert not any(k.startswith("cov_toggle_") for k in s)


def test_vlt_summary_code():
    s = _vlt("code")
    # counts are space-padded in this output: "( 6/12)"
    assert (s["cov_branch_covered"], s["cov_branch_total"]) == (6, 12)
    assert (s["cov_line_covered"], s["cov_line_total"]) == (11, 30)
    assert s["cov_expr_pct"] == round(100.0 * 5 / 11, 2)
    assert "cov_toggle_pct" not in s


def test_vlt_summary_full():
    s = _vlt("full")
    assert (s["cov_toggle_covered"], s["cov_toggle_total"]) == (13, 14)
    assert s["cov_fsm_state_pct"] == 100.0
    assert "cov_fsm_arc_pct" not in s       # 0/0 on this design


def test_vlt_summary_kinds_filter():
    s = _vlt("full", kinds=["covergroup", "user"])
    assert set(k.split("_")[1] for k in s) == {"covergroup", "user"}


def test_vlt_summary_garbage():
    assert cov.parse_vlt_cov_summary("") == {}
    assert cov.parse_vlt_cov_summary("%Error: Can't read coverage file") == {}
    assert cov.parse_vlt_cov_summary("  bogus : 10.0% (1/10)") == {}


#---------------------------------------------------------------------------
# xezim JSON parser (fixtures: xezim 0.11.0)
#---------------------------------------------------------------------------

def _xzm(level, kinds=None):
    with open(_fixture("xzm_%s.json" % level)) as fp:
        return cov.parse_xzm_cov_summary(json.load(fp), kinds)


def test_xzm_summary_func():
    # Functional only: xezim lists hit bins but not unhit ones, so there is
    # no percentage to report.
    assert _xzm("func") == {}


def test_xzm_summary_code():
    s = _xzm("code")
    assert (s["cov_line_covered"], s["cov_line_total"]) == (12, 12)   # statement
    assert (s["cov_branch_covered"], s["cov_branch_total"]) == (8, 9)
    assert "cov_toggle_pct" not in s


def test_xzm_summary_full():
    s = _xzm("full")
    assert (s["cov_toggle_covered"], s["cov_toggle_total"]) == (13, 78)
    assert s["cov_toggle_pct"] == round(100.0 * 13 / 78, 2)


def test_xzm_summary_kinds_filter():
    assert set(_xzm("full", kinds=["line"])) == {
        "cov_line_pct", "cov_line_covered", "cov_line_total"}


def test_xzm_summary_garbage():
    assert cov.parse_xzm_cov_summary(None) == {}
    assert cov.parse_xzm_cov_summary({"code_coverage": {"statement": {}}}) == {}


#---------------------------------------------------------------------------
# VCS urg dashboard parser (fixtures: urg Y-2026.03, `-show ratios`)
#---------------------------------------------------------------------------

def _vcs(name, kinds=None):
    with open(_fixture("vcs_dashboard_%s.txt" % name)) as fp:
        return cov.parse_vcs_cov_summary(fp.read(), kinds)


def test_vcs_summary_full():
    s = _vcs("full")
    assert (s["cov_line_covered"], s["cov_line_total"]) == (16, 18)
    assert (s["cov_expr_covered"], s["cov_expr_total"]) == (7, 7)        # COND
    assert (s["cov_branch_covered"], s["cov_branch_total"]) == (7, 9)
    assert (s["cov_toggle_covered"], s["cov_toggle_total"]) == (13, 14)
    assert (s["cov_user_covered"], s["cov_user_total"]) == (1, 1)        # ASSERT
    assert (s["cov_covergroup_covered"], s["cov_covergroup_total"]) == (3, 4)
    # The percentage is recomputed from the ratio, not taken from the text
    assert s["cov_toggle_pct"] == round(100.0 * 13 / 14, 2)
    # FSM is `-- 0/0` on this design
    assert not any(k.startswith("cov_fsm") for k in s)


def test_vcs_summary_fsm():
    # One FSM column, counting transitions; COND is `-- 0/0`
    s = _vcs("fsm")
    assert (s["cov_fsm_arc_covered"], s["cov_fsm_arc_total"]) == (3, 4)
    assert "cov_fsm_state_pct" not in s
    assert "cov_expr_pct" not in s
    assert "cov_covergroup_pct" not in s       # no GROUP column


def test_vcs_summary_kinds_filter():
    assert set(_vcs("full", kinds=["covergroup", "user"])) == {
        "cov_covergroup_pct", "cov_covergroup_covered", "cov_covergroup_total",
        "cov_user_pct", "cov_user_covered", "cov_user_total"}


def test_vcs_summary_garbage():
    assert cov.parse_vcs_cov_summary("") == {}
    assert cov.parse_vcs_cov_summary(None) == {}
    # Without -show ratios there are no counts to report
    assert cov.parse_vcs_cov_summary(
        "Total Coverage Summary\nSCORE  LINE   GROUP\n 80.00  88.89  75.00\n") == {}
    # A truncated table
    assert cov.parse_vcs_cov_summary("Total Coverage Summary\nSCORE LINE\n") == {}


#---------------------------------------------------------------------------
# Questa vcover parser (fixtures: vcover 2026.1 `report -summary`)
#---------------------------------------------------------------------------

def _mti(name, kinds=None):
    with open(_fixture("mti_summary_%s.txt" % name)) as fp:
        return cov.parse_mti_cov_summary(fp.read(), kinds)


def test_mti_summary_full():
    s = _mti("full")
    assert (s["cov_line_covered"], s["cov_line_total"]) == (14, 16)      # Statements
    assert (s["cov_branch_covered"], s["cov_branch_total"]) == (9, 11)
    assert (s["cov_expr_covered"], s["cov_expr_total"]) == (4, 4)        # Conditions
    assert (s["cov_toggle_covered"], s["cov_toggle_total"]) == (13, 14)
    assert (s["cov_user_covered"], s["cov_user_total"]) == (1, 1)        # Directives
    # Covergroup Bins, not the `na` Covergroups row
    assert (s["cov_covergroup_covered"], s["cov_covergroup_total"]) == (3, 4)


def test_mti_summary_fsm():
    s = _mti("fsm")
    assert (s["cov_fsm_state_covered"], s["cov_fsm_state_total"]) == (3, 3)
    assert (s["cov_fsm_arc_covered"], s["cov_fsm_arc_total"]) == (3, 4)


def test_mti_summary_conditions_and_expressions_sum():
    text = ("    Conditions                       4         3         1         1    75.00%\n"
            "    Expressions                      6         6         0         1   100.00%\n"
            "    Assertions                       2         2         0         1   100.00%\n")
    s = cov.parse_mti_cov_summary(text)
    assert (s["cov_expr_covered"], s["cov_expr_total"]) == (9, 10)
    assert _kinds_in(s) == {"expr"}      # Assertions has no kind


def test_mti_summary_kinds_filter():
    assert _kinds_in(_mti("full", kinds=["line", "toggle"])) == {"line", "toggle"}


def test_mti_summary_garbage():
    assert cov.parse_mti_cov_summary("") == {}
    assert cov.parse_mti_cov_summary("** Error: (vcover-1234) Cannot open file") == {}


def test_db_test_name():
    assert cov.db_test_name("/r/t.sim-run") == "t_sim_run"
    assert cov.db_test_name("/r/case_3/") == "case_3"
    assert cov.db_test_name("") == "test"


#---------------------------------------------------------------------------
# The SimCovArgs type and the package `cov` var
#---------------------------------------------------------------------------

_FLOW = '''
package:
  name: foo
  imports:
    - name: hdlsim
  tasks:
  - name: bare
    uses: hdlsim.SimCovArgs
  - name: holder
    uses: hdlsim.SimCovArgs
    with: { level: code }
  - name: show
    pytask: cov_probe.show
    needs: [{task}]
    uptodate: false
'''

_PROBE = '''
import json, os
from dv_flow.mgr import TaskDataResult
async def show(ctxt, input):
    levels = [i.level for i in input.inputs if getattr(i, "type", None) == "hdlsim.SimCovArgs"]
    with open(os.path.join(os.environ["COV_PROBE_OUT"]), "w") as fp:
        json.dump(levels, fp)
    return TaskDataResult()
'''


def _cov_items(tmpdir, task, defines=()):
    """Run `task` through the dfm CLI and return the `level` of each
    SimCovArgs item it outputs. A subprocess, because dfm caches a loaded
    package per process, so an in-process `-D` would see an earlier load."""
    import subprocess, sys
    d = str(tmpdir)
    with open(os.path.join(d, "flow.dv"), "w") as f:
        f.write(_FLOW.replace("{task}", task))
    with open(os.path.join(d, "cov_probe.py"), "w") as f:
        f.write(_PROBE)
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(
        [d] + ([env["PYTHONPATH"]] if env.get("PYTHONPATH") else []))
    env["COV_PROBE_OUT"] = os.path.join(d, "levels.json")
    cmd = [sys.executable, "-m", "dv_flow.mgr", "run"]
    for dfn in defines:
        cmd += ["-D", dfn]
    subprocess.check_call(cmd + ["show"], cwd=d, env=env,
                          stdout=subprocess.DEVNULL)
    with open(env["COV_PROBE_OUT"]) as fp:
        return json.load(fp)


def test_simcovargs_defaults_to_none(tmpdir):
    assert _cov_items(tmpdir, "bare") == ["none"]


def test_simcovargs_holder(tmpdir):
    assert _cov_items(tmpdir, "holder") == ["code"]


def test_simcovargs_follows_package_var(tmpdir):
    # `-D hdlsim.cov=code`: a bare SimCovArgs follows it; a holder keeps its own
    assert _cov_items(tmpdir, "bare", ["hdlsim.cov=code"]) == ["code"]
    assert _cov_items(tmpdir.mkdir("h"), "holder", ["hdlsim.cov=full"]) == ["code"]


#---------------------------------------------------------------------------
# Real builds and runs
#---------------------------------------------------------------------------

import asyncio
from dv_flow.mgr import TaskSetRunner, PackageLoader
from dv_flow.mgr.task_data import SeverityE
from dv_flow.mgr.task_graph_builder import TaskGraphBuilder
from .sims import get_available_sims

ALL_SIMS = get_available_sims()


class CovRun(object):
    """One SimImage + SimRun of a test design, and what came out.

    The flow is written as a flow.dv (as a user would), because a DataItem
    task built with mkTaskNode ignores its field values.

    cov_param   -- SimImage `cov`
    cov_items   -- one `uses: hdlsim.SimCovArgs` holder per level
    img_with / run_with -- extra `with:` for SimImage / SimRun
    extra_tasks -- more task dicts, each wired into SimImage's needs
    """

    def __init__(self, tmpdir, sim, cov_param=None, cov_items=(), top="cov_top",
                 img_with=None, run_with=None, extra_tasks=(), rundir="rundir"):
        d = str(tmpdir)
        self.rundir = os.path.join(d, rundir)
        tasks = [{"name": "src", "uses": "std.FileSet",
                  "with": {"type": "systemVerilogSource", "base": DATA,
                           "include": "%s.sv" % top}}]
        needs = ["src"]
        for i, lvl in enumerate(cov_items):
            tasks.append({"name": "covargs%d" % i, "uses": "hdlsim.SimCovArgs",
                          "with": {"level": lvl}})
            needs.append("covargs%d" % i)
        for t in extra_tasks:
            tasks.append(t)
            needs.append(t["name"])
        img_with = dict(img_with or {}, top=[top])
        if cov_param is not None:
            img_with["cov"] = cov_param
        tasks.append({"name": "sim_img", "uses": "hdlsim.%s.SimImage" % sim,
                      "needs": needs, "with": img_with})
        tasks.append({"name": "sim_run", "uses": "hdlsim.%s.SimRun" % sim,
                      "needs": ["sim_img"],
                      "with": dict(run_with or {}, sim=sim)})
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

    @property
    def imgdir(self):
        return self._task_dir("sim_img")

    @property
    def rundir_run(self):
        return self._task_dir("sim_run")

    def _task_dir(self, name):
        for cand in (name, "t." + name):
            p = os.path.join(self.rundir, cand)
            if os.path.isdir(p):
                return p
        raise AssertionError("no rundir for %s under %s: %s" % (
            name, self.rundir, os.listdir(self.rundir)))

    def cov_json(self):
        return cov.read_cov_json(self.imgdir)

    def artifacts(self, filetype):
        return [a for a in self.result.artifacts if a.filetype == filetype]

    def cov_stats(self):
        return {k: v for k, v in self.result.stats.items() if k.startswith("cov_")}


@pytest.mark.parametrize("sim", ALL_SIMS)
def test_none_is_unchanged(tmpdir, sim):
    """The default (no request) collects nothing and reports nothing: no
    cov.json, no runinfo.cov, no simCovDb, no cov_* stats, no warning."""
    r = CovRun(tmpdir, sim, top="plain_top")
    assert r.status == 0
    assert r.result is not None
    assert not os.path.exists(os.path.join(r.imgdir, cov.COV_FILE))
    assert "cov" not in r.result.runinfo
    assert r.artifacts("simCovDb") == []
    assert r.cov_stats() == {}
    assert r.task_markers("sim_img", SeverityE.Warning) == []


@pytest.mark.skipif("ivl" not in ALL_SIMS, reason="iverilog not installed")
def test_unsupported_backend_warns(tmpdir):
    """A backend without coverage support warns once and builds as `none`."""
    r = CovRun(tmpdir, "ivl", cov_param="code", top="plain_top")
    assert r.status == 0
    warns = r.task_markers("sim_img", SeverityE.Warning)
    cov_warns = [w for w in warns if "coverage" in w.msg]
    assert len(cov_warns) == 1
    assert "ivl" in cov_warns[0].msg and "code" in cov_warns[0].msg
    assert r.cov_json() is None
    assert "cov" not in r.result.runinfo


@pytest.mark.parametrize("sim", ALL_SIMS[:1])
def test_unknown_level_errors(tmpdir, sim):
    r = CovRun(tmpdir, sim, cov_items=["medium"], top="plain_top")
    assert r.status != 0
    errs = r.task_markers("sim_img", SeverityE.Error)
    assert any("medium" in e.msg and "none, func, code, full" in e.msg
               for e in errs), errs


#---------------------------------------------------------------------------
# Verilator
#---------------------------------------------------------------------------

needs_vlt = pytest.mark.skipif("vlt" not in ALL_SIMS, reason="verilator not installed")


@needs_vlt
def test_vlt_func(tmpdir):
    r = CovRun(tmpdir, "vlt", cov_param="func")
    assert r.status == 0
    assert r.cov_json() == {"level": "func", "kinds": ["covergroup", "user"]}
    assert r.result.runinfo["cov"]["level"] == "func"
    dbs = r.artifacts("simCovDb")
    assert len(dbs) == 1
    assert dbs[0].files == ["coverage.dat"]
    assert dbs[0].attributes == ["role=cov", "format=vlt-dat"]
    s = r.cov_stats()
    assert _kinds_in(s) == {"covergroup", "user"}
    assert (s["cov_covergroup_covered"], s["cov_covergroup_total"]) == (3, 4)
    with open(os.path.join(dbs[0].basedir, "coverage.dat")) as fp:
        assert "hit_high" in fp.read()
    assert r.task_markers("sim_img", SeverityE.Warning) == []


@needs_vlt
def test_vlt_code(tmpdir):
    r = CovRun(tmpdir, "vlt", cov_param="code")
    assert r.status == 0
    s = r.cov_stats()
    assert _kinds_in(s) == {"covergroup", "user", "line", "branch", "expr"}
    assert 0 < s["cov_line_pct"] <= 100


@needs_vlt
def test_vlt_full(tmpdir):
    r = CovRun(tmpdir, "vlt", cov_param="full")
    assert r.status == 0
    s = r.cov_stats()
    assert "cov_toggle_pct" in s and "cov_fsm_state_pct" in s
    assert r.cov_json()["kinds"][-3:] == ["toggle", "fsm_state", "fsm_arc"]


@needs_vlt
def test_vlt_level_from_item(tmpdir):
    """A SimCovArgs holder sets the level; with the param too, highest wins."""
    r = CovRun(tmpdir, "vlt", cov_items=["code"])
    assert r.cov_json()["level"] == "code"
    r = CovRun(tmpdir.mkdir("b"), "vlt", cov_param="func", cov_items=["code", "none"])
    assert r.cov_json()["level"] == "code"
    r = CovRun(tmpdir.mkdir("c"), "vlt", cov_param="full", cov_items=["func"])
    assert r.cov_json()["level"] == "full"


@needs_vlt
def test_vlt_level_from_define(tmpdir):
    """`-D hdlsim.cov=code` reaches a bare `uses: hdlsim.SimCovArgs` in a real
    build (CLI subprocess: see _cov_items)."""
    import subprocess, sys
    d = str(tmpdir)
    flow = {"package": {"name": "t", "imports": [{"name": "hdlsim"}], "tasks": [
        {"name": "src", "uses": "std.FileSet",
         "with": {"type": "systemVerilogSource", "base": DATA,
                  "include": "cov_top.sv"}},
        {"name": "covargs", "uses": "hdlsim.SimCovArgs"},
        {"name": "sim_img", "uses": "hdlsim.vlt.SimImage",
         "needs": ["src", "covargs"], "with": {"top": ["cov_top"]}},
    ]}}
    with open(os.path.join(d, "flow.dv"), "w") as fp:
        json.dump(flow, fp)
    subprocess.check_call([sys.executable, "-m", "dv_flow.mgr", "run",
                           "-D", "hdlsim.cov=code", "sim_img"],
                          cwd=d, stdout=subprocess.DEVNULL)
    recs = [cov.read_cov_json(os.path.join(d, "rundir", n))
            for n in os.listdir(os.path.join(d, "rundir"))]
    assert {"level": "code",
            "kinds": ["covergroup", "user", "line", "branch", "expr"]} in recs


@needs_vlt
def test_vlt_rebuild_on_level_change(tmpdir):
    """Same rundir: func -> code rebuilds and re-records; -> none rebuilds
    and removes the record."""
    r = CovRun(tmpdir, "vlt", cov_param="func")
    simv = os.path.join(r.imgdir, "obj_dir", "simv")
    t_func = os.path.getmtime(simv)
    assert r.cov_json()["level"] == "func"

    r = CovRun(tmpdir, "vlt", cov_param="code")
    assert r.status == 0
    assert r.cov_json()["level"] == "code"
    t_code = os.path.getmtime(simv)
    assert t_code > t_func
    assert "cov_line_pct" in r.cov_stats()

    r = CovRun(tmpdir, "vlt", cov_param="none")
    assert r.status == 0
    assert r.cov_json() is None
    assert os.path.getmtime(simv) > t_code
    # ... and the rerun in the same rundir drops the previous coverage.dat
    assert r.artifacts("simCovDb") == []
    assert not os.path.exists(os.path.join(r.rundir_run, "coverage.dat"))
    assert "cov" not in r.result.runinfo
    assert r.cov_stats() == {}


@needs_vlt
def test_vlt_with_dbg_preset(tmpdir):
    """Coverage combines with the debug (FST trace) preset."""
    r = CovRun(tmpdir, "vlt", cov_param="code",
               extra_tasks=[{"name": "dbg", "uses": "hdlsim.vlt.SimElabArgsDbg"}],
               run_with={"trace": True})
    assert r.status == 0
    assert "--trace-fst" in open(os.path.join(r.imgdir, "build.f")).read().split()
    assert len(r.artifacts("simTrace")) == 1
    assert len(r.artifacts("simCovDb")) == 1
    assert "cov_line_pct" in r.cov_stats()


#---------------------------------------------------------------------------
# xezim
#---------------------------------------------------------------------------

needs_xzm = pytest.mark.skipif("xzm" not in ALL_SIMS, reason="xezim not installed")


@needs_xzm
def test_xzm_none_writes_no_db(tmpdir):
    """At `none`, the design's covergroup is NOT written out (XEZIM_COV_DB is
    /dev/null) -- a deliberate change from xezim's default."""
    r = CovRun(tmpdir, "xzm")
    assert r.status == 0
    assert not os.path.exists(os.path.join(r.rundir_run, "xezim_cov.json"))
    assert r.artifacts("simCovDb") == []
    assert "cov" not in r.result.runinfo
    assert r.cov_stats() == {}
    assert "--code-coverage" not in " ".join(r.result.runinfo["cmd"])


@needs_xzm
def test_xzm_func(tmpdir):
    r = CovRun(tmpdir, "xzm", cov_param="func")
    assert r.status == 0
    dbs = r.artifacts("simCovDb")
    assert len(dbs) == 1
    assert dbs[0].files == ["xezim_cov.json"]
    assert dbs[0].attributes == ["role=cov", "format=xezim-json"]
    with open(os.path.join(dbs[0].basedir, "xezim_cov.json")) as fp:
        db = json.load(fp)
    assert db["covergroups"][0]["name"] == "cg"
    assert "code_coverage" not in db
    # xezim gives no functional percentage
    assert r.cov_stats() == {}
    assert r.result.runinfo["cov"] == {"level": "func", "kinds": ["covergroup", "user"]}
    assert r.task_markers("sim_img", SeverityE.Warning) == []


@needs_xzm
def test_xzm_code(tmpdir):
    r = CovRun(tmpdir, "xzm", cov_param="code")
    assert r.status == 0
    s = r.cov_stats()
    assert _kinds_in(s) == {"line", "branch"}
    assert 0 < s["cov_line_pct"] <= 100
    assert "--code-coverage=stmt,branch" in r.result.runinfo["cmd"]


@needs_xzm
def test_xzm_full(tmpdir):
    r = CovRun(tmpdir, "xzm", cov_param="full")
    assert r.status == 0
    assert _kinds_in(r.cov_stats()) == {"line", "branch", "toggle"}


@needs_xzm
def test_xzm_user_code_coverage_wins(tmpdir):
    """A --code-coverage in the user's run args replaces ours."""
    r = CovRun(tmpdir, "xzm", cov_param="code",
               run_with={"args": ["--code-coverage=toggle"]})
    assert r.status == 0
    cmd = r.result.runinfo["cmd"]
    assert [a for a in cmd if a.startswith("--code-coverage")] == ["--code-coverage=toggle"]
    # Only kinds the level asked for are reported, and toggle isn't one at `code`
    assert r.cov_stats() == {}


@needs_xzm
def test_xzm_level_change(tmpdir):
    """Same rundir: code -> func; the run follows the new cov.json."""
    r = CovRun(tmpdir, "xzm", cov_param="code")
    assert "cov_line_pct" in r.cov_stats()
    r = CovRun(tmpdir, "xzm", cov_param="func")
    assert r.status == 0
    assert r.cov_json()["level"] == "func"
    assert r.cov_stats() == {}
    assert not any(a.startswith("--code-coverage") for a in r.result.runinfo["cmd"])
    r = CovRun(tmpdir, "xzm")
    assert r.cov_json() is None
    assert r.artifacts("simCovDb") == []


#---------------------------------------------------------------------------
# VCS, Questa, Xcelium
#---------------------------------------------------------------------------

needs_vcs = pytest.mark.skipif("vcs" not in ALL_SIMS, reason="vcs not installed")
needs_mti = pytest.mark.skipif("mti" not in ALL_SIMS, reason="questa not installed")
needs_xcm = pytest.mark.skipif("xcm" not in ALL_SIMS, reason="xcelium not installed")

# sim -> (database name, format=)
_COMMERCIAL_DB = {
    "vcs": ("cov.vdb", "vcs-vdb"),
    "mti": ("cov.ucdb", "questa-ucdb"),
    "xcm": ("cov_work", "xcelium-ucd"),
}

# Kinds each level reports on cov_top. VCS finds no FSM in it, and Questa's
# FSM extraction doesn't either (see the fsm fixtures for those rows).
_COMMERCIAL_KINDS = {
    "func": {"covergroup", "user"},
    "code": {"covergroup", "user", "line", "branch", "expr"},
    "full": {"covergroup", "user", "line", "branch", "expr", "toggle"},
}

_REPORTER = {"vcs": "urg", "mti": "vcover"}

# Backends whose run reports cov_* stats (they need their report utility)
STATS_SIMS = [s for s in ("vcs", "mti")
              if s in ALL_SIMS and shutil.which(_REPORTER[s]) is not None]
DB_SIMS = [s for s in ("vcs", "mti", "xcm") if s in ALL_SIMS]


def _check_db(r, sim):
    name, fmt = _COMMERCIAL_DB[sim]
    dbs = r.artifacts("simCovDb")
    assert len(dbs) == 1, r.result.artifacts
    assert dbs[0].files == [name]
    assert dbs[0].attributes == ["role=cov", "format=%s" % fmt]
    assert os.path.exists(os.path.join(dbs[0].basedir, name))
    return os.path.join(dbs[0].basedir, name)


@pytest.mark.parametrize("sim", DB_SIMS)
@pytest.mark.parametrize("level", ["func", "code", "full"])
def test_commercial_db(tmpdir, sim, level):
    """Every level yields one database, of the backend's format, and records
    the level in cov.json and runinfo."""
    r = CovRun(tmpdir, sim, cov_param=level)
    assert r.status == 0
    assert r.cov_json()["level"] == level
    assert r.result.runinfo["cov"] == r.cov_json()
    _check_db(r, sim)
    assert r.task_markers("sim_img", SeverityE.Warning) == []


@pytest.mark.parametrize("sim", STATS_SIMS)
@pytest.mark.parametrize("level", ["func", "code", "full"])
def test_commercial_stats(tmpdir, sim, level):
    r = CovRun(tmpdir, sim, cov_param=level)
    assert r.status == 0
    s = r.cov_stats()
    assert _kinds_in(s) == _COMMERCIAL_KINDS[level]
    # The covergroup has one hit and one unhit bin per coverpoint
    assert (s["cov_covergroup_covered"], s["cov_covergroup_total"]) == (3, 4)
    assert (s["cov_user_covered"], s["cov_user_total"]) == (1, 1)
    if level != "func":
        assert 0 < s["cov_line_pct"] < 100
    if level == "full":
        assert (s["cov_toggle_covered"], s["cov_toggle_total"]) == (13, 14)


@pytest.mark.parametrize("sim", DB_SIMS)
def test_commercial_level_from_item(tmpdir, sim):
    """A SimCovArgs holder sets the level; with the param too, highest wins."""
    r = CovRun(tmpdir, sim, cov_param="func", cov_items=["code", "none"])
    assert r.status == 0
    assert r.cov_json()["level"] == "code"


@pytest.mark.parametrize("sim", DB_SIMS)
def test_commercial_level_change(tmpdir, sim):
    """Same rundir: code -> func -> none. Each rebuild re-records the level,
    and the run drops the database the previous run left."""
    r = CovRun(tmpdir, sim, cov_param="code")
    assert r.status == 0
    _check_db(r, sim)

    r = CovRun(tmpdir, sim, cov_param="func")
    assert r.status == 0
    assert r.cov_json()["level"] == "func"
    _check_db(r, sim)
    if sim in STATS_SIMS:
        assert _kinds_in(r.cov_stats()) == {"covergroup", "user"}

    r = CovRun(tmpdir, sim, cov_param="none")
    assert r.status == 0
    assert r.cov_json() is None
    assert r.artifacts("simCovDb") == []
    assert not os.path.exists(os.path.join(r.rundir_run, _COMMERCIAL_DB[sim][0]))
    assert "cov" not in r.result.runinfo
    assert r.cov_stats() == {}


@needs_vcs
def test_vcs_db_stands_alone(tmpdir):
    """The run's cov.vdb carries the design shape copied from the image,
    and the run writes its test data there, not into the image's simv.vdb."""
    r = CovRun(tmpdir, "vcs", cov_param="code")
    assert r.status == 0
    db = _check_db(r, "vcs")
    testdata = os.path.join(db, "snps", "coverage", "db", "testdata")
    name = cov.db_test_name(r.rundir_run)
    assert os.listdir(testdata) == [name]
    assert not os.path.exists(os.path.join(
        r.imgdir, "simv.vdb", "snps", "coverage", "db", "testdata"))
    cmd = r.result.runinfo["cmd"]
    assert cmd[cmd.index("-cm") + 1] == "line+cond+branch+assert"
    assert cmd[cmd.index("-cm_name") + 1] == name


@needs_mti
def test_mti_func_has_no_code_coverage(tmpdir):
    """At func, vopt gets no +cover (covergroups and directives need none)."""
    r = CovRun(tmpdir, "mti", cov_param="func")
    assert r.status == 0
    with open(os.path.join(r.imgdir, "vopt.log")) as fp:
        assert "+cover" not in fp.read()
    r = CovRun(tmpdir.mkdir("b"), "mti", cov_param="full")
    assert r.status == 0
    with open(os.path.join(r.imgdir, "vopt.log")) as fp:
        assert "+cover=sbceft" in fp.read()


@needs_xcm
def test_xcm_db_stands_alone(tmpdir):
    """xmsim writes the model (.ucm) and this run's data (.ucd) to the run's
    cov_work. Xcelium reports no cov_* stats yet."""
    r = CovRun(tmpdir, "xcm", cov_param="full")
    assert r.status == 0
    db = _check_db(r, "xcm")
    scope = os.path.join(db, "scope")
    assert any(f.endswith(".ucm") for f in os.listdir(scope))
    assert any(f.endswith(".ucd") for f in os.listdir(
        os.path.join(scope, cov.db_test_name(r.rundir_run))))
    assert r.cov_stats() == {}
    assert r.cov_json()["kinds"] == ["covergroup", "user", "line", "expr",
                                     "toggle", "fsm_state", "fsm_arc"]


#---------------------------------------------------------------------------
# Suite roll-up
#---------------------------------------------------------------------------

_SUITE_FORMAT = {"vlt": "vlt-dat", "vcs": "vcs-vdb", "mti": "questa-ucdb"}


@pytest.mark.parametrize("sim", [s for s in ALL_SIMS if s == "vlt"] + STATS_SIMS)
def test_suite_rollup(tmpdir, sim):
    """Two cases on one `code` image -> SimSuiteReport: each TestResult keeps
    its own cov_* stats and simCovDb; the SuiteResult rolls up the best
    percentage; junit.xml / ctrf.json carry the level and percentages."""
    d = str(tmpdir)
    tasks = [
        {"name": "src", "uses": "std.FileSet",
         "with": {"type": "systemVerilogSource", "base": DATA,
                  "include": "cov_top.sv"}},
        {"name": "covargs", "uses": "hdlsim.SimCovArgs", "with": {"level": "code"}},
        {"name": "img", "uses": "hdlsim.%s.SimImage" % sim, "needs": ["src", "covargs"],
         "with": {"top": ["cov_top"]}},
    ]
    for c in ("c0", "c1"):
        tasks.append({"name": "run_" + c, "uses": "hdlsim.%s.SimRun" % sim,
                      "needs": ["img"], "with": {"mode": "test", "sim": sim}})
        tasks.append({"name": c, "uses": "hdlsim.SimCheck",
                      "needs": ["run_" + c]})
    tasks.append({"name": "report", "uses": "hdlsim.SimSuiteReport",
                  "needs": ["c0", "c1"]})
    with open(os.path.join(d, "flow.dv"), "w") as fp:
        json.dump({"package": {"name": "t", "imports": [{"name": "hdlsim"}],
                               "tasks": tasks}}, fp)

    loader = PackageLoader()
    pkg = loader.load(os.path.join(d, "flow.dv"))
    rundir = os.path.join(d, "rundir")
    builder = TaskGraphBuilder(root_pkg=pkg, rundir=rundir, loader=loader)
    runner = TaskSetRunner(rundir)
    runner.builder = builder
    report = builder.mkTaskNode("t.report")
    asyncio.run(runner.run([report]))
    assert runner.status == 0

    sr = next(it for it in report.output.output
              if getattr(it, "type", None) == "hdlsim.SuiteResult")
    assert sr.total == 2 and sr.passed == 2
    assert sr.stats["cov_line_pct_max"] > 0
    assert "cov_line_covered" not in sr.stats
    dbs = []
    for tr in sr.results:
        assert tr.stats["cov_line_pct"] > 0
        assert tr.runinfo["cov"]["level"] == "code"
        for a in tr.artifacts:
            a = a if isinstance(a, dict) else a.model_dump()
            if a["filetype"] == "simCovDb":
                assert "format=%s" % _SUITE_FORMAT[sim] in a["attributes"]
                dbs.append(os.path.join(a["basedir"], a["files"][0]))
    assert len(dbs) == 2 and len(set(dbs)) == 2
    assert all(os.path.exists(p) for p in dbs)

    rdir = next(os.path.join(rundir, n) for n in os.listdir(rundir)
                if n.endswith("report"))
    junit = open(os.path.join(rdir, "junit.xml")).read()
    assert '<property name="cov_level" value="code"/>' in junit
    assert 'name="cov_line_pct"' in junit
    with open(os.path.join(rdir, "ctrf.json")) as fp:
        ctrf = json.load(fp)
    extra = ctrf["results"]["tests"][0]["extra"]
    assert extra["cov_level"] == "code" and extra["cov_line_pct"] > 0


def test_suite_summary_coverage_line():
    """SimSuiteReport's printed summary gains a coverage line (best case per
    kind), and only for kinds some case reported."""
    from dv_flow.libhdlsim import sim_check

    class _Ctxt(object):
        def __init__(self):
            self.lines = []

        def info(self, msg):
            self.lines.append(msg)

    ctxt = _Ctxt()
    from dv_flow.libhdlsim import sim_stats
    agg = sim_stats.aggregate([
        {"cov_line_pct": 40.0, "cov_branch_pct": 25.5},
        {"cov_line_pct": 70.0}])
    sim_check._report_stats(ctxt, [], agg)
    cov_lines = [l for l in ctxt.lines if l.strip().startswith("coverage")]
    assert cov_lines == ["  coverage  line=70.00%  branch=25.50%"]
