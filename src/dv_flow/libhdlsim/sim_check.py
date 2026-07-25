#****************************************************************************
#* sim_check.py
#*
#* Copyright 2023-2025 Matthew Ballance and Contributors
#*
#* Licensed under the Apache License, Version 2.0 (the "License"); you may
#* not use this file except in compliance with the License.
#* You may obtain a copy of the License at:
#*
#*   http://www.apache.org/licenses/LICENSE-2.0
#*
#* Unless required by applicable law or agreed to in writing, software
#* distributed under the License is distributed on an "AS IS" BASIS,
#* WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#* See the License for the specific language governing permissions and
#* limitations under the License.
#*
#****************************************************************************
"""Check pytasks: turn a SimRunResult into an interpreted TestResult verdict.

`SimCheck`    -- generic base: verdict from the simulator exit code.
`SimUVMCheck` -- UVM specialization: the exit code is NOT the verdict (a UVM
                 `$finish` exits 0 with UVM_ERROR>0), so it parses the UVM log
                 (`uvm_log_parser.parse_uvm_log`) for the authoritative verdict.

Both run with `rundir: inherit`, so `input.rundir` is the SAME directory the
SimRun wrote its `sim.log` into. The verdict travels as *data* (a TestResult):
on a non-pass the task emits an Error marker for visibility but still returns
status 0, so one failing case does not abort a suite -- the suite's
SimSuiteReport is the CI gate. Only an infrastructure failure (no SimRunResult
input, or a missing sim log) fails the task itself.
"""

import json
import os
from dv_flow.mgr import FileSet, TaskDataResult
from dv_flow.libhdlsim import sim_stats
from dv_flow.libhdlsim.uvm_log_parser import parse_uvm_log


def _maps(result):
    """(stats, runinfo) copied off a SimRunResult, tolerating an older producer
    that carries neither."""
    def _m(name):
        v = getattr(result, name, None)
        return dict(v) if isinstance(v, dict) else {}
    return _m("stats"), _m("runinfo")


def _artifact_fields(a):
    """(filetype, basedir, files) tolerating a FileSet object OR a dict (the
    latter can occur if an artifact crossed a serialization boundary)."""
    if isinstance(a, dict):
        return a.get("filetype"), a.get("basedir"), list(a.get("files") or [])
    return (getattr(a, "filetype", None),
            getattr(a, "basedir", None),
            list(getattr(a, "files", None) or []))


def _as_fileset(a):
    """Normalize an artifact back to a FileSet for the TestResult output."""
    if isinstance(a, FileSet):
        return a
    ft, bd, files = _artifact_fields(a)
    kwargs = dict(filetype=ft, basedir=bd, files=files)
    attrs = a.get("attributes") if isinstance(a, dict) else getattr(a, "attributes", None)
    if attrs:
        kwargs["attributes"] = list(attrs)
    return FileSet(**kwargs)


def _severity_stats(parsed):
    """UVM severity tallies as `stats` keys, so a suite can total them the same
    way it totals every other metric."""
    return {k: parsed[k] for k in ("errors", "warnings", "fatals", "infos")
            if k in parsed}


def _find_result(inputs):
    for it in inputs:
        if getattr(it, "type", None) == "hdlsim.SimRunResult":
            return it
    return None


def _artifacts(result):
    return getattr(result, "artifacts", None) or []


def _locate_log(result, rundir):
    """Path to the sim log: prefer the SimRunResult's simLog artifact, fall
    back to `<shared rundir>/sim.log` (run + check share the rundir). Only
    returns a path that actually exists on disk."""
    for a in _artifacts(result):
        ft, bd, files = _artifact_fields(a)
        if ft == "simLog" and files:
            cand = os.path.join(bd or rundir, files[0])
            if os.path.isfile(cand):
                return cand
    cand = os.path.join(rundir, "sim.log")
    return cand if os.path.isfile(cand) else None


def _case_name(input):
    """A distinct, human-traceable case name. Prefers the `name` param; when
    that is empty (e.g. a matrix cell whose deferred `${{ name }}` does not
    resolve at runtime) falls back to the per-instance rundir basename, which
    is guaranteed distinct per case. This distinctness matters: the report
    gathers TestResults keyed by (src, seq), so two cases with the same name/src
    would be deduped to one (get_in_params)."""
    nm = getattr(input.params, "name", "")
    if nm:
        return nm
    rd = getattr(input, "rundir", "") or ""
    if rd:
        return os.path.basename(rd.rstrip("/"))
    return getattr(input, "name", "")


async def SimUVMCheck(ctxt, input) -> TaskDataResult:
    result = _find_result(input.inputs)
    if result is None:
        ctxt.error("SimUVMCheck: no SimRunResult input")
        return TaskDataResult(status=1)

    run_status = getattr(result, "status", 0)
    sim = getattr(result, "sim", "")
    walltime = getattr(result, "walltime_s", 0.0)
    name = _case_name(input)
    testname = getattr(input.params, "testname", "")

    log_path = _locate_log(result, input.rundir)
    if log_path is None:
        # A missing log is an infrastructure failure, not a test verdict.
        ctxt.error("SimUVMCheck: sim log not found (rundir=%s)" % input.rundir)
        return TaskDataResult(status=1)

    parsed = parse_uvm_log(log_path)
    passed = parsed["passed"]

    stats, runinfo = _maps(result)
    stats.update(_severity_stats(parsed))

    # NOTE: `name` is reserved by mkDataItem (the item node-name); set fields
    # after construction.
    tr = ctxt.mkDataItem(
        "hdlsim.TestResult",
        testname=testname, sim=sim,
        status=parsed["status"], passed=passed, run_status=run_status,
        errors=parsed["errors"], warnings=parsed["warnings"],
        fatals=parsed["fatals"], seed=int(runinfo.get("seed", 0) or 0),
        walltime_s=walltime, stats=stats, runinfo=runinfo,
        artifacts=[_as_fileset(a) for a in _artifacts(result)])
    tr.name = name
    # Distinct identity so a suite's per-case TestResults are not deduped by
    # (src, seq) when gathered by the report (get_in_params dedups on that key).
    tr.src = name

    if not passed:
        # Verdict-as-data: a normal fail is reported via `info`, NOT an error
        # marker. An Error marker would mark this (compound) cell failed and its
        # TestResult would be dropped from a suite's matrix aggregation; the
        # gate is SimSuiteReport. (Infra failures above DO error.)
        ctxt.info("Test '%s' (%s) %s: UVM_ERROR=%d UVM_FATAL=%d (exit=%d)" % (
            name, testname, parsed["status"],
            parsed["errors"], parsed["fatals"], run_status))

    # Verdict-as-data: task status is 0 so a suite keeps running.
    return TaskDataResult(status=0, output=[tr])


async def SimCheck(ctxt, input) -> TaskDataResult:
    # Dispatch on the `uvm` param so a single check task serves both flavors:
    # SimUVMCase sets `uvm: true` (a plain uses-chain param override, which
    # works) rather than overriding the check SUBTASK (a compound-subtask
    # override across a uses boundary does not compose -- see
    # dv-flow-mgr/docs/proposals/list_manipulation.md P2b).
    if getattr(input.params, "uvm", False):
        return await SimUVMCheck(ctxt, input)

    result = _find_result(input.inputs)
    if result is None:
        ctxt.error("SimCheck: no SimRunResult input")
        return TaskDataResult(status=1)

    run_status = getattr(result, "status", 0)
    name = _case_name(input)
    passed = (run_status == 0)
    status = "pass" if passed else "fail"

    stats, runinfo = _maps(result)

    tr = ctxt.mkDataItem(
        "hdlsim.TestResult",
        testname=getattr(input.params, "testname", ""),
        sim=getattr(result, "sim", ""), status=status, passed=passed,
        run_status=run_status, walltime_s=getattr(result, "walltime_s", 0.0),
        seed=int(runinfo.get("seed", 0) or 0), stats=stats, runinfo=runinfo,
        artifacts=[_as_fileset(a) for a in _artifacts(result)])
    tr.name = name  # `name` is reserved by mkDataItem; set it after construction
    tr.src = name   # distinct per case (see _case_name) -> no report dedup

    if not passed:
        # Verdict-as-data (see SimUVMCheck): report via info, not an error
        # marker, so the cell's output survives suite aggregation.
        ctxt.info("Sim '%s' exited with status %d" % (name, run_status))

    return TaskDataResult(status=0, output=[tr])


def _find_results(inputs):
    return [it for it in inputs
            if getattr(it, "type", None) == "hdlsim.TestResult"]


async def SimSuiteReport(ctxt, input) -> TaskDataResult:
    """Aggregate a suite's TestResults into a SuiteResult and gate CI.

    Consumes every TestResult produced by the suite's cases (a matrix task's
    output aggregates all body cells), rolls up pass/fail/error counts, prints a
    summary, and -- crucially -- sets the task status NONZERO iff any case did
    not pass. That status is the suite's CI gate.
    """
    results = _find_results(input.inputs)
    total = len(results)
    passed = sum(1 for r in results if getattr(r, "passed", False))
    errored = sum(1 for r in results
                  if not getattr(r, "passed", False)
                  and getattr(r, "status", "") in ("error", "timeout"))
    failed = total - passed - errored

    agg = sim_stats.aggregate([_case_stats(r) for r in results])

    sr = ctxt.mkDataItem(
        "hdlsim.SuiteResult",
        total=total, passed=passed, failed=failed, errored=errored,
        results=list(results), stats=agg)

    # Human-readable summary line + per-failure detail.
    ctxt.info("Suite: %d/%d passed (%d failed, %d errored)" % (
        passed, total, failed, errored))
    _report_stats(ctxt, results, agg)
    for r in results:
        if not getattr(r, "passed", False):
            ctxt.error("  %-24s %-8s errors=%d fatals=%d (%s)" % (
                getattr(r, "name", "?"),
                getattr(r, "status", "?"),
                getattr(r, "errors", 0),
                getattr(r, "fatals", 0),
                getattr(r, "testname", "")))

    status = 0 if (failed == 0 and errored == 0) else 1

    # A suite that ran NO cases must not report success. Zero failures out of
    # zero tests satisfies every other check here, so without this a mistyped
    # selector, an empty suite, or a miswired `needs:` all present as a green
    # run -- the one outcome a test gate must never produce quietly.
    if total == 0:
        ctxt.error(
            "no tests ran: the suite produced no TestResult. Check the "
            "selection, and that this task's needs actually emit test results.")
        status = 1

    output = [sr]
    if total and getattr(input, "rundir", None):
        rep = _write_report_json(ctxt, input, results, agg,
                                 dict(total=total, passed=passed,
                                      failed=failed, errored=errored))
        if rep is not None:
            output.append(rep)
    # Read defensively: the report is also driven directly from unit tests with
    # a minimal stand-in input, and a missing `params`/`rundir` there must not
    # look like a suite failure.
    want_junit = getattr(getattr(input, "params", None), "junit", True)
    if want_junit and total and getattr(input, "rundir", None):
        junit = _write_junit(ctxt, input, results)
        if junit is not None:
            output.append(junit)

    return TaskDataResult(status=status, output=output)


def _case_stats(r):
    """A case's `stats` map, falling back to the one metric every result has
    (walltime) for a TestResult produced before stats existed."""
    s = getattr(r, "stats", None)
    if isinstance(s, dict) and s:
        return dict(s)
    wall = getattr(r, "walltime_s", None)
    return {"walltime_s": wall} if isinstance(wall, (int, float)) else {}


def _fmt(v):
    return ("%.2f" % v) if isinstance(v, float) else str(v)


def _report_stats(ctxt, results, agg):
    """Print the suite's resource summary plus the slowest cases.

    The slowest-case list is the part people act on: a suite's total runtime is
    usually a handful of outliers, and naming them is what turns a number into
    a next step.
    """
    if not agg:
        return

    def _line(label, fields):
        """fields: (display-label, key, formatter) -- emitted only if present."""
        parts = ["%s=%s" % (lbl, fn(agg[k])) for lbl, k, fn in fields if k in agg]
        if parts:
            ctxt.info("  %-9s %s" % (label, "  ".join(parts)))

    _secs = lambda v: "%ss" % _fmt(v)
    _mb = lambda v: "%sMB" % _fmt(v)

    _line("walltime", [("total", "walltime_s", _secs),
                       ("mean", "walltime_s_mean", _secs),
                       ("max", "walltime_s_max", _secs)])
    _line("cpu", [("total", "cpu_total_s", _secs),
                  ("max", "cpu_total_s_max", _secs)])
    _line("memory", [("peak-rss", "maxrss_mb_max", _mb),
                     ("sim-peak", "sim_mem_mb_max", _mb)])
    _line("simtime", [("total", "simtime_s", sim_stats.format_time_s),
                      ("max", "simtime_s_max", sim_stats.format_time_s)])
    _line("severity", [("errors", "errors", _fmt),
                       ("warnings", "warnings", _fmt),
                       ("fatals", "fatals", _fmt)])

    ranked = sorted(
        ((getattr(r, "walltime_s", 0.0) or 0.0, getattr(r, "name", "?"))
         for r in results), reverse=True)
    if len(ranked) > 1 and ranked[0][0] > 0:
        ctxt.info("  slowest   %s" % ", ".join(
            "%s (%.2fs)" % (nm, wt) for wt, nm in ranked[:3]))


def _write_report_json(ctxt, input, results, agg, counts):
    """Write `report.json`: the machine-readable suite record.

    Everything the run knew -- verdict, metrics, provenance -- in one file per
    suite, so an external dashboard or a trend job never has to re-parse logs.
    """
    path = os.path.join(input.rundir, "report.json")
    doc = {
        "suite": getattr(input, "name", ""),
        "timestamp": sim_stats.utcnow(),
        "counts": counts,
        "stats": agg,
        "cases": [{
            "name": getattr(r, "name", ""),
            "testname": getattr(r, "testname", ""),
            "sim": getattr(r, "sim", ""),
            "status": getattr(r, "status", ""),
            "passed": bool(getattr(r, "passed", False)),
            "run_status": getattr(r, "run_status", 0),
            "stats": _case_stats(r),
            "runinfo": (dict(getattr(r, "runinfo", None))
                        if isinstance(getattr(r, "runinfo", None), dict) else {}),
        } for r in results],
    }
    try:
        with open(path, "w") as fp:
            json.dump(doc, fp, indent=2, sort_keys=True, default=str)
            fp.write("\n")
    except Exception as e:
        # A report-format failure must not change the suite's verdict.
        ctxt.info("could not write report.json: %s" % e)
        return None
    return FileSet(src=input.name, filetype="simReportJson",
                   basedir=input.rundir, files=["report.json"])


def _xml_escape(text):
    return (str(text).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


_JUNIT_PROP_STATS = ("simtime", "cpu_total_s", "maxrss_mb", "sim_speed_s_per_s")
_JUNIT_PROP_INFO = ("sim", "sim_version", "seed", "host", "start_time",
                    "finish_reason")


def _junit_props(r):
    """(name, value) pairs for a case's <properties> block: the reproduction
    handles (sim, seed, host) and the headline metrics, when present."""
    stats = _case_stats(r)
    runinfo = getattr(r, "runinfo", None)
    runinfo = runinfo if isinstance(runinfo, dict) else {}
    props = [(k, runinfo[k]) for k in _JUNIT_PROP_INFO if runinfo.get(k) not in (None, "")]
    props += [(k, stats[k]) for k in _JUNIT_PROP_STATS if stats.get(k) is not None]
    return props


def _write_junit(ctxt, input, results):
    """Render the suite as `junit.xml` and return it as a FileSet.

    JUnit is the one report format CI systems read natively, so this is what
    turns a suite into a GitHub/GitLab test view. Failures are reported as
    `<failure>` and inconclusive runs as `<error>`, which is the distinction
    those UIs already draw.
    """
    path = os.path.join(input.rundir, "junit.xml")
    failures = sum(1 for r in results if not getattr(r, "passed", False)
                   and str(getattr(r, "status", "")) not in ("error", "timeout"))
    errors = sum(1 for r in results if not getattr(r, "passed", False)
                 and str(getattr(r, "status", "")) in ("error", "timeout"))
    try:
        with open(path, "w") as fp:
            fp.write('<?xml version="1.0" encoding="UTF-8"?>\n')
            fp.write('<testsuite name="%s" tests="%d" failures="%d" errors="%d">\n' % (
                _xml_escape(input.name), len(results), failures, errors))
            for r in results:
                name = _xml_escape(getattr(r, "name", "") or
                                   getattr(r, "testname", "") or "?")
                fp.write('  <testcase name="%s" classname="%s" time="%s">' % (
                    name, _xml_escape(getattr(r, "testname", "") or name),
                    _xml_escape(getattr(r, "walltime_s", 0) or 0)))
                # Per-case metrics/provenance as JUnit <properties>: the one
                # slot the format offers for tool-specific data, so seed and
                # resource use survive into the CI test view.
                props = _junit_props(r)
                if props:
                    fp.write('\n    <properties>\n')
                    for k, v in props:
                        fp.write('      <property name="%s" value="%s"/>\n' % (
                            _xml_escape(k), _xml_escape(v)))
                    fp.write('    </properties>\n  ')
                if not getattr(r, "passed", False):
                    kind = ("error"
                            if str(getattr(r, "status", "")) in ("error", "timeout")
                            else "failure")
                    fp.write('\n    <%s message="%s: errors=%d fatals=%d"/>\n  ' % (
                        kind, _xml_escape(getattr(r, "status", "?")),
                        getattr(r, "errors", 0), getattr(r, "fatals", 0)))
                fp.write('</testcase>\n')
            fp.write('</testsuite>\n')
    except Exception as e:
        # A report-format failure must not change the suite's verdict.
        ctxt.info("could not write junit.xml: %s" % e)
        return None

    return FileSet(src=input.name, filetype="junitXml",
                   basedir=input.rundir, files=["junit.xml"])
