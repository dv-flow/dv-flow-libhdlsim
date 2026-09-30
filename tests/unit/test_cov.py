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

import pytest

from dv_flow.libhdlsim import cov

DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "cov")


def _fixture(name):
    return os.path.join(DATA, name)


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


@pytest.mark.parametrize("sim", get_available_sims(exclude=("xzm",)))
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
