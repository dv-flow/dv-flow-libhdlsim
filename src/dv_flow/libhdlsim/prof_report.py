#****************************************************************************
#* prof_report.py
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
"""SimProfReport: roll the profiles of a set of runs into one report.

Profiles don't merge the way coverage databases do; the regression question
is which tests and which modules use the most. So the report is
simulator-neutral: it reads each run's ``prof_summary.json`` (the
`simProfSummary` artifact of SimRunResult / TestResult items and of the
TestResults inside a SuiteResult) and writes, per profiling mode:

* ``time``: the tests ranked by CPU time; the category totals, in CPU
  seconds (each run's category share of its CPU time, summed); the top
  modules, weighted the same way.
* ``mem``: the tests ranked by peak memory; the mean category shares; the
  top modules by their largest footprint in any run.

A run's CPU time is its `cpu_total_s` stat (host-measured), else
`sim_cpu_s`. A time-profiled run with neither is listed but left out of the
weighted totals.

Each run's summary keeps only its top :data:`prof.TOP_N` modules, so a
module's roll-up is a lower bound.
"""
import json
import os
from typing import Any, Dict, List, Optional, Tuple
from dv_flow.mgr import FileSet, TaskDataResult
from dv_flow.mgr.task_data import TaskMarker, SeverityE
from dv_flow.libhdlsim import prof

REPORT_TXT = "prof_report.txt"
REPORT_JSON = "prof_report.json"

# How many tests the text report lists per mode (the JSON has them all).
TESTS_N = 20


def _get(obj : Any, name : str, default=None):
    # Items may arrive as objects or, past a serialization boundary, dicts
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def _results_of(item) -> List[Any]:
    """The per-run results in one input item."""
    t = _get(item, "type")
    if t in ("hdlsim.SimRunResult", "hdlsim.TestResult"):
        return [item]
    if t == "hdlsim.SuiteResult":
        return list(_get(item, "results") or [])
    return []


def _summary_path(result) -> Optional[str]:
    for a in _get(result, "artifacts") or []:
        if _get(a, "filetype") != "simProfSummary":
            continue
        for f in _get(a, "files") or []:
            return os.path.join(_get(a, "basedir") or "", f)
    return None


def _run_name(result) -> str:
    runinfo = _get(result, "runinfo") or {}
    name = (_get(result, "name") or runinfo.get("case_name")
            or runinfo.get("testname"))
    if not name and runinfo.get("rundir"):
        name = os.path.basename(runinfo["rundir"].rstrip("/"))
    return name or "?"


def _cpu_s(result) -> Optional[float]:
    stats = _get(result, "stats") or {}
    for k in ("cpu_total_s", "sim_cpu_s"):
        v = stats.get(k)
        if isinstance(v, (int, float)) and v > 0:
            return float(v)
    return None


def collect_runs(inputs) -> Tuple[List[Dict[str, Any]], int]:
    """(runs, unprofiled): one entry per profiled run in `inputs`, in input
    order, each once (a TestResult forwards its SimRunResult's artifacts);
    and the number of runs that carry no profile summary.

    A run is ``{name, sim, cpu_s, summary}``; `cpu_s` may be None."""
    runs = []
    seen = set()
    unprofiled = set()
    for item in inputs:
        for r in _results_of(item):
            path = _summary_path(r)
            if path is None:
                key = (_get(r, "runinfo") or {}).get("rundir") or id(r)
                unprofiled.add(key)
                continue
            if path in seen:
                continue
            seen.add(path)
            summary = prof.read_summary(path)
            if summary is None:
                unprofiled.add(path)
                continue
            runs.append(dict(
                name=_run_name(r),
                sim=summary.get("sim") or _get(r, "sim") or "",
                cpu_s=_cpu_s(r),
                summary=summary))
    return runs, len(unprofiled)


def _ordered_cats(cats : Dict[str, Any]) -> Dict[str, Any]:
    return {c: cats[c] for c in prof.CATEGORIES if c in cats}


def _time_section(runs : List[Dict[str, Any]]) -> Dict[str, Any]:
    cat_s : Dict[str, float] = {}
    mods : Dict[Tuple[str, str], Dict[str, Any]] = {}
    total = 0.0
    weighted = 0
    for r in runs:
        cpu = r["cpu_s"]
        if cpu is None:
            continue
        weighted += 1
        total += cpu
        for c, pct in (r["summary"].get("categories") or {}).items():
            cat_s[c] = cat_s.get(c, 0.0) + cpu * pct / 100.0
        for t in r["summary"].get("top") or []:
            if "pct" not in t:
                continue
            key = (t.get("scope", "module"), t.get("name", ""))
            m = mods.setdefault(key, {"scope": key[0], "name": key[1],
                                      "s": 0.0, "runs": 0})
            m["s"] += cpu * t["pct"] / 100.0
            m["runs"] += 1

    def _pct(s):
        return round(100.0 * s / total, 2) if total else 0.0

    tests = sorted(runs, key=lambda r: (r["cpu_s"] is None, -(r["cpu_s"] or 0)))
    top = sorted(mods.values(), key=lambda m: m["s"], reverse=True)[:prof.TOP_N]
    return {
        "runs": len(runs),
        "weighted": weighted,
        "cpu_s": round(total, 3),
        "categories": _ordered_cats({
            c: {"s": round(s, 3), "pct": _pct(s)} for c, s in cat_s.items()}),
        "tests": [{"name": r["name"], "sim": r["sim"], "cpu_s": r["cpu_s"],
                   "categories": dict(r["summary"].get("categories") or {})}
                  for r in tests],
        "top": [dict(m, s=round(m["s"], 3), pct=_pct(m["s"])) for m in top],
    }


def _mem_section(runs : List[Dict[str, Any]]) -> Dict[str, Any]:
    cat_sum : Dict[str, float] = {}
    mods : Dict[Tuple[str, str], Dict[str, Any]] = {}
    for r in runs:
        for c, pct in (r["summary"].get("categories") or {}).items():
            cat_sum[c] = cat_sum.get(c, 0.0) + pct
        for t in r["summary"].get("top") or []:
            if "bytes" not in t:
                continue
            key = (t.get("scope", "module"), t.get("name", ""))
            m = mods.setdefault(key, {"scope": key[0], "name": key[1],
                                      "bytes": 0, "runs": 0})
            m["bytes"] = max(m["bytes"], int(t["bytes"]))
            m["runs"] += 1

    peaks = [r["summary"]["mem_peak_mb"] for r in runs
             if r["summary"].get("mem_peak_mb") is not None]
    tests = sorted(runs, key=lambda r: -(r["summary"].get("mem_peak_mb") or 0))
    section = {
        "runs": len(runs),
        "categories": _ordered_cats({
            c: {"pct": round(s / len(runs), 2)} for c, s in cat_sum.items()}),
        "tests": [{"name": r["name"], "sim": r["sim"],
                   "mem_peak_mb": r["summary"].get("mem_peak_mb"),
                   "categories": dict(r["summary"].get("categories") or {})}
                  for r in tests],
        "top": sorted(mods.values(), key=lambda m: m["bytes"],
                      reverse=True)[:prof.TOP_N],
    }
    if peaks:
        section["mem_peak_mb_max"] = max(peaks)
    return section


def build_report(runs : List[Dict[str, Any]], unprofiled : int = 0) -> Dict[str, Any]:
    """The report document: ``{runs, unprofiled, time?, mem?}``, a section
    per mode that any run was profiled in."""
    report : Dict[str, Any] = {"runs": len(runs), "unprofiled": unprofiled}
    for mode, fn in (("time", _time_section), ("mem", _mem_section)):
        sel = [r for r in runs if r["summary"].get("mode") == mode]
        if sel:
            report[mode] = fn(sel)
    return report


def _top_cat(cats : Dict[str, float]) -> str:
    if not cats:
        return "-"
    c = max(cats, key=lambda k: cats[k])
    return "%s %.1f%%" % (c, cats[c])


def _mb(nbytes : int) -> float:
    return nbytes / float(1 << 20)


def render_text(report : Dict[str, Any]) -> str:
    out = []
    modes = ", ".join("%d %s" % (report[m]["runs"], m)
                      for m in ("time", "mem") if m in report)
    out.append("Profile report: %d run(s) (%s)%s" % (
        report["runs"], modes or "none",
        "; %d run(s) without a profile" % report["unprofiled"]
        if report["unprofiled"] else ""))

    t = report.get("time")
    if t is not None:
        out.append("")
        out.append("== time: %d run(s), %.2f CPU s ==" % (t["runs"], t["cpu_s"]))
        if t["weighted"] < t["runs"]:
            out.append("(%d run(s) have no measured CPU time and are left out "
                       "of the totals)" % (t["runs"] - t["weighted"]))
        out.append("")
        out.append("Categories (CPU seconds summed over runs)")
        for c, v in t["categories"].items():
            out.append("  %-7s %10.2f s  %6.2f%%" % (c, v["s"], v["pct"]))
        if not t["categories"]:
            out.append("  (none)")
        out.append("")
        out.append("Tests by CPU time")
        out.append("  %10s  %-16s %-4s %s" % ("cpu_s", "top category", "sim", "test"))
        for r in t["tests"][:TESTS_N]:
            out.append("  %10s  %-16s %-4s %s" % (
                "-" if r["cpu_s"] is None else "%.2f" % r["cpu_s"],
                _top_cat(r["categories"]), r["sim"], r["name"]))
        if len(t["tests"]) > TESTS_N:
            out.append("  ... %d more (see %s)" % (len(t["tests"]) - TESTS_N,
                                                   REPORT_JSON))
        out.append("")
        out.append("Top modules (CPU seconds summed over runs; a lower bound)")
        out.append("  %10s  %7s  %4s  %-6s %s" % ("cpu_s", "share", "runs",
                                                  "scope", "name"))
        for m in t["top"]:
            out.append("  %10.2f  %6.2f%%  %4d  %-6s %s" % (
                m["s"], m["pct"], m["runs"], m["scope"], m["name"]))
        if not t["top"]:
            out.append("  (none)")

    mm = report.get("mem")
    if mm is not None:
        out.append("")
        peak = mm.get("mem_peak_mb_max")
        out.append("== mem: %d run(s)%s ==" % (
            mm["runs"], ", peak %.1f MB" % peak if peak is not None else ""))
        out.append("")
        out.append("Categories (mean share over runs)")
        for c, v in mm["categories"].items():
            out.append("  %-7s %6.2f%%" % (c, v["pct"]))
        if not mm["categories"]:
            out.append("  (none)")
        out.append("")
        out.append("Tests by peak memory")
        out.append("  %10s  %-16s %-4s %s" % ("peak_mb", "top category", "sim", "test"))
        for r in mm["tests"][:TESTS_N]:
            out.append("  %10s  %-16s %-4s %s" % (
                "-" if r["mem_peak_mb"] is None else "%.1f" % r["mem_peak_mb"],
                _top_cat(r["categories"]), r["sim"], r["name"]))
        if len(mm["tests"]) > TESTS_N:
            out.append("  ... %d more (see %s)" % (len(mm["tests"]) - TESTS_N,
                                                   REPORT_JSON))
        out.append("")
        out.append("Top modules (largest footprint in any run)")
        out.append("  %10s  %4s  %-6s %s" % ("MB", "runs", "scope", "name"))
        for m in mm["top"]:
            out.append("  %10.2f  %4d  %-6s %s" % (
                _mb(m["bytes"]), m["runs"], m["scope"], m["name"]))
        if not mm["top"]:
            out.append("  (none)")
    return "\n".join(out) + "\n"


async def SimProfReport(ctxt, input) -> TaskDataResult:
    markers = []
    runs, unprofiled = collect_runs(input.inputs)
    if not runs:
        markers.append(TaskMarker(
            severity=SeverityE.Error,
            msg="No profile summaries in the inputs%s. Were the runs' images "
                "built with a profiling mode?" % (
                    " (%d run(s) without one)" % unprofiled if unprofiled else "")))
        return TaskDataResult(status=1, markers=markers)

    report = build_report(runs, unprofiled)
    t = report.get("time")
    if t is not None and t["weighted"] < t["runs"]:
        markers.append(TaskMarker(
            severity=SeverityE.Warning,
            msg="%d time-profiled run(s) have no measured CPU time; they are "
                "left out of the weighted totals" % (t["runs"] - t["weighted"])))

    text = render_text(report)
    with open(os.path.join(input.rundir, REPORT_TXT), "w") as fp:
        fp.write(text)
    with open(os.path.join(input.rundir, REPORT_JSON), "w") as fp:
        json.dump(report, fp, indent=2)
        fp.write("\n")
    for line in text.splitlines()[:1]:
        ctxt.info(line)

    return TaskDataResult(
        status=0,
        markers=markers,
        output=[
            FileSet(src=input.name, filetype="simProfReport",
                    basedir=input.rundir, files=[REPORT_TXT, REPORT_JSON],
                    attributes=["role=prof-report"]),
            ctxt.mkDataItem(
                "hdlsim.SimProfReportResult",
                runs=report["runs"],
                unprofiled=report["unprofiled"],
                time=dict(report.get("time") or {}),
                mem=dict(report.get("mem") or {})),
        ])
