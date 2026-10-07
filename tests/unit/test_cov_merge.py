#****************************************************************************
#* test_cov_merge.py
#*
#* SimCovMerge: finding the databases in a merge's inputs (cov_merge.py), the
#* error and skip paths, a Verilator merge of captured databases, and real
#* two-run merges that skip when the simulator isn't installed.
#****************************************************************************
import asyncio
import json
import os
import shutil
import subprocess
import types

import pytest

from dv_flow.mgr import FileSet
from dv_flow.mgr.task_data import SeverityE
from dv_flow.libhdlsim import cov, cov_merge
from .sims import get_available_sims

DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "cov")

ALL_SIMS = get_available_sims()


def _db(basedir, name, fmt):
    return FileSet(filetype="simCovDb", basedir=basedir, files=[name],
                   attributes=["role=cov", "format=%s" % fmt])


def _item(type, **kw):
    return types.SimpleNamespace(type=type, **kw)


#---------------------------------------------------------------------------
# Finding the databases
#---------------------------------------------------------------------------

def test_collect_from_every_input_kind():
    log = FileSet(filetype="simLog", basedir="/r/a", files=["sim.log"])
    inputs = [
        _item("hdlsim.SimRunResult", artifacts=[log, _db("/r/a", "cov.ucdb", "questa-ucdb")]),
        _item("hdlsim.TestResult", artifacts=[_db("/r/b", "cov.ucdb", "questa-ucdb")]),
        # A SuiteResult's results may have crossed a serialization boundary
        _item("hdlsim.SuiteResult", results=[
            {"type": "hdlsim.TestResult", "artifacts": [
                {"filetype": "simCovDb", "basedir": "/r/c", "files": ["cov.ucdb"],
                 "attributes": ["role=cov", "format=questa-ucdb"]}]}]),
        # A bare FileSet, eg an earlier merge's output
        _db("/m", "cov.ucdb", "questa-ucdb"),
        # Not a coverage input at all
        _item("hdlsim.SimCovArgs", level="code"),
    ]
    assert cov_merge.collect_cov_dbs(inputs) == [
        ("/r/a/cov.ucdb", "questa-ucdb"),
        ("/r/b/cov.ucdb", "questa-ucdb"),
        ("/r/c/cov.ucdb", "questa-ucdb"),
        ("/m/cov.ucdb", "questa-ucdb"),
    ]


def test_collect_dedups_and_keeps_format():
    # A TestResult forwards its SimRunResult's artifacts: the same database
    # reached twice is merged once.
    db = _db("/r/a", "cov.vdb", "vcs-vdb")
    inputs = [_item("hdlsim.SimRunResult", artifacts=[db]),
              _item("hdlsim.TestResult", artifacts=[db]),
              _db("/r/b", "coverage.dat", "vlt-dat"),
              FileSet(filetype="simCovDb", basedir="/r/c", files=["x.db"])]
    assert cov_merge.collect_cov_dbs(inputs) == [
        ("/r/a/cov.vdb", "vcs-vdb"),
        ("/r/b/coverage.dat", "vlt-dat"),
        ("/r/c/x.db", ""),
    ]


#---------------------------------------------------------------------------
# The merge task, driven directly with a stand-in task context
#---------------------------------------------------------------------------

class _Ctxt(object):
    """Enough of TaskRunCtxt for CovMerger: exec runs the command for real."""

    def __init__(self, rundir):
        self.rundir = rundir
        self.env = dict(os.environ)
        self.lines = []

    async def exec(self, cmd, logfile=None, **kw):
        with open(os.path.join(self.rundir, logfile or "cmd.log"), "w") as fp:
            return subprocess.call(cmd, cwd=self.rundir, stdout=fp,
                                   stderr=subprocess.STDOUT)

    def info(self, msg):
        self.lines.append(msg)

    def mkDataItem(self, type, **kw):
        return types.SimpleNamespace(type=type, **kw)


def _merge(merger_cls, tmpdir, inputs):
    rundir = str(tmpdir.mkdir("merge"))
    ctxt = _Ctxt(rundir)
    inp = types.SimpleNamespace(name="merge", rundir=rundir, inputs=inputs)
    return asyncio.run(merger_cls(ctxt).run(inp)), ctxt


def test_no_databases_is_an_error(tmpdir):
    res, _ = _merge(cov_merge.VcsCovMerger, tmpdir,
                    [_item("hdlsim.SimRunResult", artifacts=[])])
    assert res.status == 1
    errs = [m for m in res.markers if m.severity == SeverityE.Error]
    assert len(errs) == 1 and "format=vcs-vdb" in errs[0].msg


def test_only_other_formats_warns_then_errors(tmpdir):
    res, _ = _merge(cov_merge.MtiCovMerger, tmpdir,
                    [_db("/r/a", "coverage.dat", "vlt-dat"),
                     _db("/r/b", "coverage.dat", "vlt-dat")])
    assert res.status == 1
    warns = [m for m in res.markers if m.severity == SeverityE.Warning]
    assert len(warns) == 1
    assert "Skipped 2" in warns[0].msg and "vlt-dat" in warns[0].msg


def _vlt_points(path):
    """(points, points hit) in a Verilator coverage.dat"""
    counts = []
    with open(path) as fp:
        for line in fp:
            if line.startswith("C "):
                counts.append(int(line.rsplit(None, 1)[1]))
    return len(counts), sum(1 for c in counts if c > 0)


def _runnable(exe):
    """`exe` is on PATH and can be exec'd (not, eg, a script without #!)."""
    path = shutil.which(exe)
    if path is None:
        return False
    try:
        subprocess.run([path, "--version"], stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL, timeout=60)
    except OSError:
        return False
    return True


@pytest.mark.skipif(not _runnable("verilator_coverage"),
                    reason="no runnable verilator_coverage")
def test_vlt_merge_fixtures(tmpdir):
    """Two captured runs (+mode=1, +mode=2) each miss the branch the other
    hits; their merge hits every point. A database of another format is
    skipped with a warning."""
    src = tmpdir.mkdir("runs")
    for mode in (1, 2):
        d = src.mkdir("m%d" % mode)
        shutil.copy(os.path.join(DATA, "vlt_merge_mode%d.dat" % mode),
                    os.path.join(str(d), "coverage.dat"))
    inputs = [_item("hdlsim.SimRunResult",
                    artifacts=[_db(str(src.join("m%d" % m)), "coverage.dat", "vlt-dat")])
              for m in (1, 2)]
    inputs.append(_db("/elsewhere", "cov.vdb", "vcs-vdb"))
    res, ctxt = _merge(cov_merge.VltCovMerger, tmpdir, inputs)
    assert res.status == 0, res.markers
    assert [m.severity for m in res.markers] == [SeverityE.Warning]

    fs, mr = res.output
    assert fs.filetype == "simCovDb" and fs.files == ["coverage.dat"]
    assert fs.attributes == ["role=cov", "format=vlt-dat"]
    assert mr.type == "hdlsim.SimCovMergeResult"
    assert mr.format == "vlt-dat" and len(mr.inputs) == 2

    for m in (1, 2):
        assert _vlt_points(os.path.join(DATA, "vlt_merge_mode%d.dat" % m)) == (6, 5)
    assert _vlt_points(os.path.join(fs.basedir, "coverage.dat")) == (6, 6)
    assert ctxt.lines and ctxt.lines[0].startswith("merged 2 coverage database(s)")


#---------------------------------------------------------------------------
# Real runs: two runs of merge_top that cover different branches, merged
#---------------------------------------------------------------------------

from dv_flow.mgr import TaskSetRunner, PackageLoader
from dv_flow.mgr.task_graph_builder import TaskGraphBuilder

MERGE_SIMS = [s for s in ("vlt", "vcs", "mti") if s in ALL_SIMS]

_REPORTER = {"vlt": "verilator_coverage", "vcs": "urg", "mti": "vcover"}

_FORMAT = {"vlt": "vlt-dat", "vcs": "vcs-vdb", "mti": "questa-ucdb"}


def _run_flow(tmpdir, sim, merge_uses, suite=False):
    """Build merge_top at `code`, run it with +mode=1 and +mode=2, and merge.
    With `suite`, the runs go through SimCheck + SimSuiteReport and the merge
    reads the SuiteResult. Returns (status, {task: output items})."""
    d = str(tmpdir)
    tasks = [
        {"name": "src", "uses": "std.FileSet",
         "with": {"type": "systemVerilogSource", "base": DATA,
                  "include": "merge_top.sv"}},
        {"name": "img", "uses": "hdlsim.%s.SimImage" % sim, "needs": ["src"],
         "with": {"top": ["merge_top"], "cov": "code", "timing": False}},
    ]
    merge_needs = []
    for m in (1, 2):
        run = {"name": "run%d" % m, "uses": "hdlsim.%s.SimRun" % sim,
               "needs": ["img"], "with": {"plusargs": ["mode=%d" % m], "sim": sim}}
        if suite:
            run["with"]["mode"] = "test"
            tasks.append(run)
            tasks.append({"name": "chk%d" % m, "uses": "hdlsim.SimCheck",
                          "needs": ["run%d" % m]})
        else:
            tasks.append(run)
            merge_needs.append("run%d" % m)
    if suite:
        tasks.append({"name": "report", "uses": "hdlsim.SimSuiteReport",
                      "needs": ["chk1", "chk2"]})
        merge_needs = ["report"]
    merge = {"name": "merge", "uses": merge_uses, "needs": merge_needs}
    if merge_uses == "hdlsim.SimCovMerge":
        merge["with"] = {"sim": sim}
    tasks.append(merge)
    with open(os.path.join(d, "flow.dv"), "w") as fp:
        json.dump({"package": {"name": "t", "imports": [{"name": "hdlsim"}],
                               "tasks": tasks}}, fp, indent=1)

    loader = PackageLoader()
    pkg = loader.load(os.path.join(d, "flow.dv"))
    rundir = os.path.join(d, "rundir")
    builder = TaskGraphBuilder(root_pkg=pkg, rundir=rundir, loader=loader)
    runner = TaskSetRunner(rundir)
    runner.builder = builder
    outputs, markers = {}, []

    def listener(task, reason):
        if reason == "leave" and task.result is not None:
            outputs[task.name.rsplit(".", 1)[-1]] = list(task.result.output or [])
            markers.extend(task.result.markers)

    runner.add_listener(listener)
    asyncio.run(runner.run([builder.mkTaskNode("t.merge")]))
    return runner.status, outputs, markers


def _merge_out(outputs):
    items = outputs["merge"]
    dbs = [i for i in items if getattr(i, "filetype", None) == "simCovDb"]
    res = [i for i in items if getattr(i, "type", None) == "hdlsim.SimCovMergeResult"]
    assert len(dbs) == 1 and len(res) == 1, items
    return dbs[0], res[0]


@pytest.mark.parametrize("sim", MERGE_SIMS)
def test_merge_two_runs(tmpdir, sim):
    status, outputs, markers = _run_flow(tmpdir, sim, "hdlsim.%s.SimCovMerge" % sim)
    assert status == 0, markers
    db, res = _merge_out(outputs)
    assert db.attributes == ["role=cov", "format=%s" % _FORMAT[sim]]
    assert os.path.exists(os.path.join(db.basedir, db.files[0]))
    assert res.sim == sim and res.format == _FORMAT[sim]
    assert len(res.inputs) == 2 and len(set(res.inputs)) == 2

    if shutil.which(_REPORTER[sim]) is None:
        return
    runs = [next(i for i in outputs["run%d" % m]
                 if getattr(i, "type", None) == "hdlsim.SimRunResult")
            for m in (1, 2)]
    # Branch, not line: Verilator counts the if/else bodies as branch points
    # only, so each run's line coverage is already complete there.
    per_run = [r.stats["cov_branch_covered"] for r in runs]
    total = runs[0].stats["cov_branch_total"]
    assert runs[1].stats["cov_branch_total"] == total
    # Each run misses the branch the other takes; the merge has both
    assert all(c < total for c in per_run)
    assert res.stats["cov_branch_total"] == total
    assert res.stats["cov_branch_covered"] > max(per_run)


@pytest.mark.parametrize("sim", MERGE_SIMS[:1])
def test_merge_abstract_dispatch(tmpdir, sim):
    """`uses: hdlsim.SimCovMerge` + `sim` selects the backend's merge."""
    status, outputs, markers = _run_flow(tmpdir, sim, "hdlsim.SimCovMerge")
    assert status == 0, markers
    assert _merge_out(outputs)[1].sim == sim


@pytest.mark.parametrize("sim", MERGE_SIMS)
def test_merge_from_suite(tmpdir, sim):
    """The merge reads the databases inside a SuiteResult's TestResults."""
    status, outputs, markers = _run_flow(tmpdir, sim,
                                         "hdlsim.%s.SimCovMerge" % sim, suite=True)
    assert status == 0, markers
    _, res = _merge_out(outputs)
    assert len(res.inputs) == 2
