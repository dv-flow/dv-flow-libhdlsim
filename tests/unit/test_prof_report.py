#****************************************************************************
#* test_prof_report.py
#*
#* SimProfReport: finding the run summaries in its inputs (prof_report.py),
#* the time and mem roll-ups on synthetic summaries, the task's error and
#* warning paths, and a real suite of profiled runs that skips when no
#* profiling simulator is installed.
#****************************************************************************
import asyncio
import json
import os
import types

import pytest

from dv_flow.mgr import FileSet, PackageLoader, TaskGraphBuilder, TaskSetRunner
from dv_flow.mgr.task_data import SeverityE
from dv_flow.libhdlsim import prof, prof_report
from .sims import get_available_sims

DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "prof")


def _summary(rundir, mode, sim, categories, top=(), mem_peak_mb=None):
    os.makedirs(rundir, exist_ok=True)
    prof.write_summary(rundir, prof.make_summary(
        mode, sim, categories, list(top), mem_peak_mb))
    return FileSet(filetype="simProfSummary", basedir=rundir,
                   files=[prof.SUMMARY_FILE], attributes=["role=prof-summary"])


def _item(type, **kw):
    return types.SimpleNamespace(type=type, **kw)


def _run(type, rundir, summary=None, cpu=None, name=None, sim="vcs"):
    arts = [FileSet(filetype="simLog", basedir=rundir, files=["sim.log"])]
    if summary is not None:
        arts.append(summary)
    kw = dict(artifacts=arts, sim=sim, runinfo={"rundir": rundir,
                                                "case_name": os.path.basename(rundir)},
              stats={} if cpu is None else {"cpu_total_s": cpu})
    if name is not None:
        kw["name"] = name
    return _item(type, **kw)


#---------------------------------------------------------------------------
# Finding the summaries
#---------------------------------------------------------------------------

def test_collect_from_every_input_kind(tmpdir):
    d = str(tmpdir)
    a = _summary(os.path.join(d, "a"), "time", "vcs", {"hdl": 100})
    b = _summary(os.path.join(d, "b"), "time", "xcm", {"tb": 100})
    c = _summary(os.path.join(d, "c"), "time", "mti", {"hdl": 100})
    inputs = [
        _run("hdlsim.SimRunResult", os.path.join(d, "a"), a, cpu=1.0),
        _run("hdlsim.TestResult", os.path.join(d, "b"), b, cpu=2.0, name="case_b"),
        # A SuiteResult's results may have crossed a serialization boundary
        _item("hdlsim.SuiteResult", results=[
            {"type": "hdlsim.TestResult", "name": "case_c",
             "stats": {"sim_cpu_s": 3.0},
             "artifacts": [{"filetype": "simProfSummary", "basedir": c.basedir,
                            "files": c.files}]}]),
        # Not a run at all
        _item("hdlsim.SimProfArgs", mode="time"),
    ]
    runs, unprofiled = prof_report.collect_runs(inputs)
    assert unprofiled == 0
    assert [(r["name"], r["sim"], r["cpu_s"]) for r in runs] == [
        ("a", "vcs", 1.0), ("case_b", "xcm", 2.0), ("case_c", "mti", 3.0)]


def test_collect_dedups_and_counts_unprofiled(tmpdir):
    # A TestResult forwards its SimRunResult's artifacts: the same summary
    # reached twice is read once.
    d = str(tmpdir)
    a = _summary(os.path.join(d, "a"), "time", "vcs", {"hdl": 100})
    bad = os.path.join(d, "bad")
    os.makedirs(bad)
    with open(os.path.join(bad, prof.SUMMARY_FILE), "w") as fp:
        fp.write("not json")
    inputs = [
        _run("hdlsim.SimRunResult", os.path.join(d, "a"), a, cpu=1.0),
        _run("hdlsim.TestResult", os.path.join(d, "a"), a, cpu=1.0, name="a"),
        _run("hdlsim.SimRunResult", os.path.join(d, "plain")),
        _run("hdlsim.TestResult", os.path.join(d, "plain"), name="plain"),
        _run("hdlsim.SimRunResult", bad, FileSet(
            filetype="simProfSummary", basedir=bad, files=[prof.SUMMARY_FILE])),
    ]
    runs, unprofiled = prof_report.collect_runs(inputs)
    assert [r["name"] for r in runs] == ["a"]
    # `plain` (twice, one rundir) and the unreadable summary
    assert unprofiled == 2


#---------------------------------------------------------------------------
# The roll-up
#---------------------------------------------------------------------------

def _r(name, mode, cats, cpu=None, top=(), peak=None, sim="vcs"):
    return dict(name=name, sim=sim, cpu_s=cpu,
                summary=prof.make_summary(mode, sim, cats, list(top), peak))


def test_time_weights_by_cpu():
    runs = [
        _r("short", "time", {"hdl": 50, "solver": 50}, cpu=2.0,
           top=[{"scope": "module", "name": "fifo", "pct": 50}]),
        _r("long", "time", {"hdl": 10, "solver": 90}, cpu=8.0,
           top=[{"scope": "module", "name": "fifo", "pct": 10},
                {"scope": "module", "name": "arb", "pct": 5}]),
        _r("nocpu", "time", {"tb": 100}),
    ]
    t = prof_report.build_report(runs)["time"]
    assert t["runs"] == 3 and t["weighted"] == 2 and t["cpu_s"] == 10.0
    # hdl: 1.0 + 0.8; solver: 1.0 + 7.2; `nocpu` adds nothing
    assert t["categories"] == {"hdl": {"s": 1.8, "pct": 18.0},
                               "solver": {"s": 8.2, "pct": 82.0}}
    assert [x["name"] for x in t["tests"]] == ["long", "short", "nocpu"]
    assert t["tests"][2]["cpu_s"] is None
    assert t["top"] == [
        {"scope": "module", "name": "fifo", "s": 1.8, "pct": 18.0, "runs": 2},
        {"scope": "module", "name": "arb", "s": 0.4, "pct": 4.0, "runs": 1}]


def test_time_keeps_scope_apart():
    # A Verilator file and a module of the same name are different things
    runs = [_r("a", "time", {"hdl": 100}, cpu=1.0, sim="vlt",
               top=[{"scope": "file", "name": "top", "pct": 100}]),
            _r("b", "time", {"hdl": 100}, cpu=1.0,
               top=[{"scope": "module", "name": "top", "pct": 100}])]
    top = prof_report.build_report(runs)["time"]["top"]
    assert sorted((m["scope"], m["runs"]) for m in top) == [
        ("file", 1), ("module", 1)]


def test_mem_takes_mean_and_max():
    runs = [
        _r("small", "mem", {"hdl": 20, "kernel": 80}, peak=100.0,
           top=[{"scope": "module", "name": "ram", "bytes": 1 << 20}]),
        _r("big", "mem", {"hdl": 60, "kernel": 40}, peak=300.0,
           top=[{"scope": "module", "name": "ram", "bytes": 3 << 20}]),
    ]
    m = prof_report.build_report(runs)["mem"]
    assert m["runs"] == 2 and m["mem_peak_mb_max"] == 300.0
    assert m["categories"] == {"hdl": {"pct": 40.0}, "kernel": {"pct": 60.0}}
    assert [x["name"] for x in m["tests"]] == ["big", "small"]
    assert m["top"] == [{"scope": "module", "name": "ram",
                         "bytes": 3 << 20, "runs": 2}]


def test_modes_report_apart():
    runs = [_r("t", "time", {"hdl": 100}, cpu=1.0),
            _r("m", "mem", {"hdl": 100}, peak=10.0)]
    rep = prof_report.build_report(runs, unprofiled=3)
    assert rep["runs"] == 2 and rep["unprofiled"] == 3
    assert rep["time"]["runs"] == 1 and rep["mem"]["runs"] == 1
    assert "mem" not in prof_report.build_report(runs[:1])

    text = prof_report.render_text(rep)
    assert text.startswith("Profile report: 2 run(s) (1 time, 1 mem); "
                           "3 run(s) without a profile\n")
    assert "== time: 1 run(s), 1.00 CPU s ==" in text
    assert "== mem: 1 run(s), peak 10.0 MB ==" in text
    # Neither run has a module list
    assert text.count("  (none)\n") == 2


def test_text_caps_tests():
    runs = [_r("t%02d" % i, "time", {"hdl": 100}, cpu=float(i + 1))
            for i in range(prof_report.TESTS_N + 5)]
    rep = prof_report.build_report(runs)
    text = prof_report.render_text(rep)
    assert "... 5 more (see prof_report.json)" in text
    assert len(rep["time"]["tests"]) == prof_report.TESTS_N + 5


#---------------------------------------------------------------------------
# The task, driven directly with a stand-in task context
#---------------------------------------------------------------------------

class _Ctxt(object):

    def __init__(self):
        self.lines = []

    def info(self, msg):
        self.lines.append(msg)

    def mkDataItem(self, type, **kw):
        return types.SimpleNamespace(type=type, **kw)


def _task(tmpdir, inputs):
    rundir = str(tmpdir.mkdir("report"))
    inp = types.SimpleNamespace(name="report", rundir=rundir, inputs=inputs)
    ctxt = _Ctxt()
    return asyncio.run(prof_report.SimProfReport(ctxt, inp)), ctxt


def test_no_summaries_is_an_error(tmpdir):
    res, _ = _task(tmpdir, [_run("hdlsim.SimRunResult", "/r/a")])
    assert res.status == 1
    errs = [m for m in res.markers if m.severity == SeverityE.Error]
    assert len(errs) == 1 and "1 run(s) without one" in errs[0].msg


def test_task_outputs(tmpdir):
    d = str(tmpdir)
    a = _summary(os.path.join(d, "a"), "time", "vcs", {"hdl": 100},
                 top=[{"scope": "module", "name": "fifo", "pct": 100}])
    b = _summary(os.path.join(d, "b"), "time", "vcs", {"solver": 100})
    res, ctxt = _task(tmpdir, [
        _run("hdlsim.SimRunResult", os.path.join(d, "a"), a, cpu=1.0),
        _run("hdlsim.SimRunResult", os.path.join(d, "b"), b)])
    assert res.status == 0
    warns = [m for m in res.markers if m.severity == SeverityE.Warning]
    assert len(warns) == 1 and "1 time-profiled run(s)" in warns[0].msg

    fs, item = res.output
    assert fs.filetype == "simProfReport" and fs.attributes == ["role=prof-report"]
    assert fs.files == [prof_report.REPORT_TXT, prof_report.REPORT_JSON]
    with open(os.path.join(fs.basedir, prof_report.REPORT_JSON)) as fp:
        doc = json.load(fp)
    assert item.type == "hdlsim.SimProfReportResult"
    assert item.runs == 2 and item.unprofiled == 0
    assert item.time == doc["time"] and item.mem == {}
    assert doc["time"]["top"][0]["name"] == "fifo"
    assert ctxt.lines == ["Profile report: 2 run(s) (2 time)"]


#---------------------------------------------------------------------------
# A real suite: two profiled cases, checked, reported, profiled
#---------------------------------------------------------------------------

PROF_SIMS = get_available_sims(only=("vcs", "xcm", "mti"))


def _run_suite(tmpdir, sim):
    d = str(tmpdir)
    tasks = [
        {"name": "src", "uses": "std.FileSet",
         "with": {"type": "systemVerilogSource", "base": DATA,
                  "include": "prof_top.sv"}},
        {"name": "img", "uses": "hdlsim.%s.SimImage" % sim, "needs": ["src"],
         "with": {"top": ["prof_top"], "prof": "time"}},
    ]
    for i in (1, 2):
        tasks.append({"name": "run%d" % i, "uses": "hdlsim.%s.SimRun" % sim,
                      "needs": ["img"], "with": {"mode": "test", "sim": sim}})
        tasks.append({"name": "chk%d" % i, "uses": "hdlsim.SimCheck",
                      "needs": ["run%d" % i]})
    tasks.append({"name": "regress", "uses": "hdlsim.SimSuiteReport",
                  "needs": ["chk1", "chk2"]})
    tasks.append({"name": "profile", "uses": "hdlsim.SimProfReport",
                  "needs": ["regress"]})
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
    asyncio.run(runner.run([builder.mkTaskNode("t.profile")]))
    return runner.status, outputs, markers


@pytest.mark.parametrize("sim", PROF_SIMS[:1])
def test_suite_profile(tmpdir, sim):
    status, outputs, markers = _run_suite(tmpdir, sim)
    assert status == 0, markers
    items = outputs["profile"]
    fs = [i for i in items if getattr(i, "filetype", None) == "simProfReport"]
    res = [i for i in items
           if getattr(i, "type", None) == "hdlsim.SimProfReportResult"]
    assert len(fs) == 1 and len(res) == 1, items
    for f in fs[0].files:
        assert os.path.isfile(os.path.join(fs[0].basedir, f))

    t = res[0].time
    assert res[0].runs == 2 and res[0].unprofiled == 0 and res[0].mem == {}
    assert t["weighted"] == 2 and t["cpu_s"] > 0
    assert sorted(x["name"] for x in t["tests"]) == ["t.chk1", "t.chk2"]
    assert t["categories"] and t["top"]
    assert abs(sum(c["pct"] for c in t["categories"].values()) - 100.0) < 0.5
