#****************************************************************************
#* uvm_log_parser.py
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
"""Pure-function simulation-log verdict parser.

`parse_uvm_log(path)` returns the pass/fail verdict for a UVM run, and
`parse_sim_log(path)` the verdict for a generic (non-UVM) run, WITHOUT
importing any dv-flow machinery, so they unit-test standalone (like
`log_parser.py`).

Both make ONE streaming pass over the whole log. A tail-only read cannot
certify that the earlier part of the run was clean: an assertion failure an
hour into a run is not in the last 64 KiB. Memory stays bounded -- counts, the
summary region and a capped sample of diagnostics -- whatever the log size.

* UVM report summary -- the severity tallies after the last
  ``--- UVM Report Summary ---``::

      ** Report counts by severity
      UVM_INFO :    9
      UVM_WARNING :   61
      UVM_ERROR :    0
      UVM_FATAL :    0

  are the authoritative UVM counts (``errors``/``warnings``/``fatals``); the
  individual ``UVM_ERROR`` lines are counted only when there is no summary.
  An explicit ``** TEST FAILED **`` forces a fail.

* Simulator diagnostics -- assertion failures, HDL `$error`/`$fatal` and
  simulator errors (`sim_diag`), counted separately as ``sim_errors``,
  ``sim_fatals`` and ``assertion_failures`` (a subset of the first two). The
  UVM report server never sees these, so a clean summary does not mean they
  did not happen.

Verdict (UVM):

=====================================================  ===============
Evidence                                               status
=====================================================  ===============
summary, UVM clean, no sim errors/fatals, exit 0        pass
summary, UVM error/fatal or TEST FAILED                 fail
summary, any sim error/fatal                            fail
summary, all clean but nonzero exit                     error
no summary, crash (segfault, core dump, tool error)     error
no summary, HDL/assertion `$fatal`                      fail
no summary, no `$finish`                                timeout
no summary, finished, UVM or sim errors                 fail
no summary, finished, nothing else                      error
=====================================================  ===============

Verdict (generic): fail on any sim error/fatal or a nonzero exit; else pass.

There is deliberately NO bare ``"error"`` substring match -- that would flag
benign text like ``err_test`` or ``0 errors``.
"""

import os
import re
from dv_flow.libhdlsim import sim_diag

# Severity tally lines: "UVM_ERROR :    0" (Questa prefixes its transcript
# with '# ')
_SEV_RE = re.compile(r'^(?:#\s*)?\s*UVM_(INFO|WARNING|ERROR|FATAL)\s*:\s*(\d+)', re.M)

_SUMMARY_MARKER = "--- UVM Report Summary ---"
# Lines kept after the summary marker: the severity block is at its top, and a
# per-id count list can follow; nothing past this is needed for the verdict.
_SUMMARY_LINES = 400

# Crash / abort signatures. Assertion and `$error`-style reports are not
# crashes; `sim_diag` recognizes those.
_CRASH_SIGNATURES = (
    "segmentation fault",
    "Segmentation fault",
    "core dumped",
)

# Verilog completion markers (any one means the run reached the end).
_FINISH_SIGNATURES = ("$finish", "Verilog $finish")

# A UVM report line, for the no-summary count: "UVM_ERROR @ 10: ..."
_UVM_LINE_RE = re.compile(r'^(?:#\s*)?\s*(UVM_ERROR|UVM_FATAL|UVM_WARNING)\b(?!\s*:\s*\d)')


def _parse_summary(region):
    """Parse the severity tallies + explicit verdict from the summary region.
    Returns a dict of counts and the explicit verdict ('pass'/'fail'/None)."""
    counts = {"INFO": 0, "WARNING": 0, "ERROR": 0, "FATAL": 0}
    for m in _SEV_RE.finditer(region):
        counts[m.group(1)] = int(m.group(2))

    verdict = None
    if "** TEST PASSED **" in region:
        verdict = "pass"
    if "** TEST FAILED **" in region:
        # An explicit FAILED always wins over a stray PASSED echo.
        verdict = "fail"

    return counts, verdict


def _empty_result():
    return {
        "status": "error",
        "passed": False,
        "errors": 0,
        "warnings": 0,
        "fatals": 0,
        "infos": 0,
        "sim_errors": 0,
        "sim_fatals": 0,
        "assertion_failures": 0,
        "diagnostics": [],
        "first_failure": "",
        "saw_summary": False,
        "saw_finish": False,
        "crash": False,
        "scanned_whole_file": False,
    }


def _scan(path):
    """One pass over the log: the diagnostics, the last summary region, the
    per-line UVM counts, and the finish/crash evidence."""
    diag = sim_diag.DiagScanner()
    summary = None          # lines after the last summary marker
    uvm = {"UVM_ERROR": 0, "UVM_FATAL": 0, "UVM_WARNING": 0}
    saw_finish = crash = False

    with open(path, "r", errors="replace") as f:
        for line in f:
            diag.line(line)
            if summary is not None and len(summary) < _SUMMARY_LINES:
                summary.append(line)
            if _SUMMARY_MARKER in line:
                summary = [line]
                continue
            m = _UVM_LINE_RE.match(line)
            if m:
                uvm[m.group(1)] += 1
            if not crash and any(sig in line for sig in _CRASH_SIGNATURES):
                crash = True
            if not saw_finish and any(sig in line for sig in _FINISH_SIGNATURES):
                saw_finish = True
    diag.close()
    return diag, summary, uvm, saw_finish, crash


def _fill_diag(res, diag):
    res["sim_errors"] = diag.errors
    res["sim_fatals"] = diag.fatals
    res["assertion_failures"] = diag.assertions
    res["diagnostics"] = [d.to_dict() for d in diag.sample]
    first = diag.first()
    res["first_failure"] = first.summary() if first is not None else ""


def parse_uvm_log(path, run_status=None):
    """Parse a UVM simulation log and return a verdict dict.

    Keys: ``status`` ("pass"/"fail"/"error"/"timeout"), ``passed`` (bool),
    ``errors``/``warnings``/``fatals``/``infos`` (int, UVM tallies),
    ``sim_errors``/``sim_fatals``/``assertion_failures`` (int, simulator
    diagnostics), ``diagnostics`` (a capped sample, as dicts),
    ``first_failure`` (one line, or ""), ``saw_summary``, ``saw_finish``,
    ``crash`` and ``scanned_whole_file`` (bool).

    `run_status` is the simulator's exit code when known: a nonzero exit with
    an otherwise clean log is not a pass.
    """
    res = _empty_result()

    if not os.path.isfile(path):
        res["status"] = "error"
        return res

    diag, summary, uvm, saw_finish, crash = _scan(path)
    res["scanned_whole_file"] = True
    res["saw_finish"] = saw_finish
    res["crash"] = crash
    _fill_diag(res, diag)

    if summary is not None:
        counts, verdict = _parse_summary("".join(summary))
        res["saw_summary"] = True
        res["infos"] = counts["INFO"]
        res["warnings"] = counts["WARNING"]
        res["errors"] = counts["ERROR"]
        res["fatals"] = counts["FATAL"]

        uvm_failed = counts["ERROR"] > 0 or counts["FATAL"] > 0 or verdict == "fail"
        if uvm_failed or diag.failed:
            res["status"] = "fail"
        elif run_status:
            res["status"] = "error"
        else:
            res["status"] = "pass"
        res["passed"] = res["status"] == "pass"
        return res

    # ---- No summary: something ended the run before the report server ran.
    res["errors"] = uvm["UVM_ERROR"]
    res["fatals"] = uvm["UVM_FATAL"]
    res["warnings"] = uvm["UVM_WARNING"]
    res["passed"] = False  # no clean summary is never a pass

    if crash or diag.tool_failures:
        res["status"] = "error"
    elif diag.hdl_fatals:
        # A checker's $fatal ended the run: a test failure, not a crash
        res["status"] = "fail"
    elif not saw_finish:
        res["status"] = "timeout"
    elif res["errors"] or res["fatals"] or diag.failed:
        res["status"] = "fail"
    else:
        # Finished cleanly but produced no summary -- not a recognizable UVM
        # run; treat as an error rather than silently passing.
        res["status"] = "error"

    return res


def parse_sim_log(path, run_status=0):
    """Verdict for a generic (non-UVM) run: the exit code AND the log.

    A simulator can report failed assertions and still exit 0, so a zero exit
    alone is not a pass. Returns the same keys as `parse_uvm_log` (the UVM
    tallies stay 0). A missing log is ``status: "error"``.
    """
    res = _empty_result()
    if not os.path.isfile(path):
        return res

    diag, _summary, _uvm, saw_finish, crash = _scan(path)
    res["scanned_whole_file"] = True
    res["saw_finish"] = saw_finish
    res["crash"] = crash
    _fill_diag(res, diag)

    res["status"] = "fail" if (diag.failed or run_status) else "pass"
    res["passed"] = res["status"] == "pass"
    return res
