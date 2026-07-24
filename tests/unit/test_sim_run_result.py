
# Unit test: the SimRunResult / TestResult / SuiteResult DataItem types
# construct via mkDataItem and round-trip through model_dump(mode='json'),
# including embedded FileSet lists in `artifacts` / `results` (P1.1).

import json
from dv_flow.mgr import PackageLoader
from dv_flow.mgr.task_graph_builder import TaskGraphBuilder
from dv_flow.mgr.fileset import FileSet


def _builder(tmpdir):
    markers = []
    loader = PackageLoader(
        marker_listeners=[lambda m: markers.append(m)]).load_rgy(["std", "hdlsim"])
    return TaskGraphBuilder(loader, str(tmpdir)), markers


def test_types_load_clean(tmpdir):
    b, markers = _builder(tmpdir)
    for t in ("hdlsim.SimRunResult", "hdlsim.TestResult", "hdlsim.SuiteResult"):
        it = b.mkDataItem(t)
        assert it is not None
    assert markers == []


def test_sim_run_result_roundtrip(tmpdir):
    b, _ = _builder(tmpdir)
    log = FileSet(filetype="simLog", basedir=str(tmpdir),
                  files=["sim.log"], attributes=["role=log"])
    trace = FileSet(filetype="simTrace", basedir=str(tmpdir),
                    files=["dump.vcd"], attributes=["role=trace"])
    srr = b.mkDataItem("hdlsim.SimRunResult",
                       status=3, sim="vlt", mode="test",
                       walltime_s=1.25, artifacts=[log, trace])
    d = json.loads(json.dumps(srr.model_dump(mode="json")))
    assert d["type"] == "hdlsim.SimRunResult"
    assert d["status"] == 3
    assert d["mode"] == "test"
    assert d["walltime_s"] == 1.25
    assert len(d["artifacts"]) == 2
    assert d["artifacts"][0]["filetype"] == "simLog"
    assert d["artifacts"][0]["files"] == ["sim.log"]


def test_test_result_roundtrip(tmpdir):
    b, _ = _builder(tmpdir)
    log = FileSet(filetype="simLog", basedir=str(tmpdir), files=["sim.log"])
    tr = b.mkDataItem("hdlsim.TestResult",
                      name="wb-arb", testname="wb_dma_arb_test", sim="vlt",
                      status="pass", passed=True, run_status=0,
                      errors=0, warnings=61, fatals=0, seed=1,
                      walltime_s=0.04, artifacts=[log])
    d = json.loads(json.dumps(tr.model_dump(mode="json")))
    assert d["passed"] is True
    assert d["testname"] == "wb_dma_arb_test"
    assert d["warnings"] == 61
    assert d["artifacts"][0]["filetype"] == "simLog"


def test_suite_result_roundtrip(tmpdir):
    b, _ = _builder(tmpdir)
    tr = b.mkDataItem("hdlsim.TestResult", name="c0", passed=False,
                      status="fail", errors=2)
    sr = b.mkDataItem("hdlsim.SuiteResult",
                      total=3, passed=2, failed=1, errored=0, results=[tr])
    d = json.loads(json.dumps(sr.model_dump(mode="json")))
    assert d["total"] == 3
    assert d["failed"] == 1
    assert len(d["results"]) == 1
    assert d["results"][0]["status"] == "fail"
