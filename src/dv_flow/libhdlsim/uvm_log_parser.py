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
"""Pure-function UVM simulation-log verdict parser.

`parse_uvm_log(path)` returns the pass/fail verdict for a UVM run WITHOUT
importing any dv-flow machinery, so it unit-tests standalone (like
`log_parser.py`).

Design (see docs/sim_case_suite_design.md):

* Fast path -- read only the TAIL of the log and look for the UVM report
  summary block::

      --- UVM Report Summary ---

      ** Report counts by severity
      UVM_INFO :    9
      UVM_WARNING :   61
      UVM_ERROR :    0
      UVM_FATAL :    0

  The verdict is `errors == 0 and fatals == 0` (an explicit
  ``** TEST FAILED **`` forces a fail). The exit code is NOT the verdict: a UVM
  ``$finish`` exits 0 even with ``UVM_ERROR > 0``.

* Fallback -- only when the summary block is absent from the tail (crash / hang
  before the report server ran) do we stream the WHOLE file, matching *anchored*
  patterns (``UVM_ERROR``/``UVM_FATAL`` at line start, ``%Error``/``Error-[``,
  ``Assertion failed``, ``segmentation fault``, missing ``$finish``). There is
  deliberately NO bare ``"error"`` substring match -- that would flag benign
  text like ``err_test`` or ``0 errors``.
"""

import os
import re

# Severity tally lines: "UVM_ERROR :    0"
_SEV_RE = re.compile(r'^\s*UVM_(INFO|WARNING|ERROR|FATAL)\s*:\s*(\d+)', re.M)

_SUMMARY_MARKER = "--- UVM Report Summary ---"

# Crash / abort signatures used only in the fallback whole-file scan.
_CRASH_SIGNATURES = (
    "%Error",
    "Error-[",
    "Assertion failed",
    "segmentation fault",
    "Segmentation fault",
    "core dumped",
    "Fatal:",
)

# Verilog completion markers (any one means the run reached the end).
_FINISH_SIGNATURES = ("$finish", "Verilog $finish")


def _read_tail(path, tail_bytes):
    """Return (text, scanned_whole_file). Reads at most `tail_bytes` from the
    end of the file, discarding a leading partial line when truncated."""
    size = os.path.getsize(path)
    with open(path, "rb") as f:
        if size > tail_bytes:
            f.seek(size - tail_bytes)
            f.readline()  # drop the partial first line
            return f.read().decode("utf-8", errors="replace"), False
        return f.read().decode("utf-8", errors="replace"), True


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
        "saw_summary": False,
        "saw_finish": False,
        "scanned_whole_file": False,
    }


def parse_uvm_log(path, tail_bytes=65536):
    """Parse a UVM simulation log and return a verdict dict.

    Keys: ``status`` ("pass"/"fail"/"error"/"timeout"), ``passed`` (bool),
    ``errors``/``warnings``/``fatals``/``infos`` (int), ``saw_summary`` (bool),
    ``saw_finish`` (bool), ``scanned_whole_file`` (bool -- True only when the
    fallback whole-file scan ran, i.e. the fast tail path missed).
    """
    res = _empty_result()

    if not os.path.isfile(path):
        res["status"] = "error"
        return res

    tail, whole = _read_tail(path, tail_bytes)

    # ---- Fast path: summary block present in the tail --------------------
    idx = tail.find(_SUMMARY_MARKER)
    if idx != -1:
        counts, verdict = _parse_summary(tail[idx:])
        res["saw_summary"] = True
        res["scanned_whole_file"] = whole
        res["infos"] = counts["INFO"]
        res["warnings"] = counts["WARNING"]
        res["errors"] = counts["ERROR"]
        res["fatals"] = counts["FATAL"]
        res["saw_finish"] = any(s in tail for s in _FINISH_SIGNATURES)

        passed = counts["ERROR"] == 0 and counts["FATAL"] == 0
        if verdict == "fail":
            passed = False
        res["passed"] = passed
        res["status"] = "pass" if passed else "fail"
        return res

    # ---- Fallback: no summary in tail -> stream the whole file -----------
    # Something aborted before the report server ran. Use anchored patterns
    # only; never a bare "error" substring.
    res["scanned_whole_file"] = True
    errors = fatals = warnings = 0
    saw_finish = False
    crash = False

    with open(path, "r", errors="replace") as f:
        for line in f:
            s = line.lstrip()
            if s.startswith("UVM_ERROR"):
                errors += 1
            elif s.startswith("UVM_FATAL"):
                fatals += 1
            elif s.startswith("UVM_WARNING"):
                warnings += 1
            if not crash and any(sig in line for sig in _CRASH_SIGNATURES):
                crash = True
            if not saw_finish and any(sig in line for sig in _FINISH_SIGNATURES):
                saw_finish = True

    res["errors"] = errors
    res["fatals"] = fatals
    res["warnings"] = warnings
    res["saw_finish"] = saw_finish
    res["passed"] = False  # no clean summary is never a pass

    if crash:
        res["status"] = "error"
    elif not saw_finish:
        res["status"] = "timeout"
    elif errors or fatals:
        res["status"] = "fail"
    else:
        # Finished cleanly but produced no summary -- not a recognizable UVM
        # run; treat as an error rather than silently passing.
        res["status"] = "error"

    return res
