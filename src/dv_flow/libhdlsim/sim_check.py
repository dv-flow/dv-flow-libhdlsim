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

import os
from dv_flow.mgr import FileSet, TaskDataResult
from dv_flow.libhdlsim.uvm_log_parser import parse_uvm_log


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

    # NOTE: `name` is reserved by mkDataItem (the item node-name); set fields
    # after construction.
    tr = ctxt.mkDataItem(
        "hdlsim.TestResult",
        testname=testname, sim=sim,
        status=parsed["status"], passed=passed, run_status=run_status,
        errors=parsed["errors"], warnings=parsed["warnings"],
        fatals=parsed["fatals"], seed=0, walltime_s=walltime,
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

    tr = ctxt.mkDataItem(
        "hdlsim.TestResult",
        testname=getattr(input.params, "testname", ""),
        sim=getattr(result, "sim", ""), status=status, passed=passed,
        run_status=run_status, walltime_s=getattr(result, "walltime_s", 0.0),
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

    sr = ctxt.mkDataItem(
        "hdlsim.SuiteResult",
        total=total, passed=passed, failed=failed, errored=errored,
        results=list(results))

    # Human-readable summary line + per-failure detail.
    ctxt.info("Suite: %d/%d passed (%d failed, %d errored)" % (
        passed, total, failed, errored))
    for r in results:
        if not getattr(r, "passed", False):
            ctxt.error("  %-24s %-8s errors=%d fatals=%d (%s)" % (
                getattr(r, "name", "?"),
                getattr(r, "status", "?"),
                getattr(r, "errors", 0),
                getattr(r, "fatals", 0),
                getattr(r, "testname", "")))

    status = 0 if (failed == 0 and errored == 0) else 1
    return TaskDataResult(status=status, output=[sr])
