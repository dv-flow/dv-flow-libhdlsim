#****************************************************************************
#* cov.py
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
"""Coverage collection: the level vocabulary, the image's ``cov.json`` record,
and the per-backend summary parsers.

A coverage *level* is requested through ``hdlsim.SimCovArgs`` (or SimImage's
``cov`` parameter). Levels are cumulative -- each includes everything below it:

* ``none`` -- collect nothing (the default)
* ``func`` -- functional coverage: covergroups and ``cover property``
* ``code`` -- adds line/statement, branch and (where supported) expression
* ``full`` -- adds toggle and (where supported) FSM

SimImage resolves the level and records it, with the *kinds* the backend
enabled for it, in ``cov.json`` in the image directory. SimRun reads that
record back, so a run always follows its image.

Kinds use the ``verilator_coverage --report summary`` vocabulary
(:data:`KINDS`); a backend maps its own names onto these (xezim's
``statement`` is ``line``, VCS's ``COND`` is ``expr``).

This module imports nothing from dv-flow, so it unit-tests standalone.
"""

import json
import logging
import os
import re
from typing import Any, Dict, Iterable, List, Optional

_log = logging.getLogger("cov")

LEVELS = ("none", "func", "code", "full")

KINDS = ("line", "branch", "expr", "toggle", "fsm_state", "fsm_arc",
         "covergroup", "user")

# The per-image coverage record, written by SimImage and read by SimRun.
COV_FILE = "cov.json"

# `format=` attribute values on the simCovDb artifact. A downstream decoder
# (merge, report) dispatches on these, never on the file name.
FORMAT_VLT_DAT = "vlt-dat"          # Verilator coverage.dat
FORMAT_XEZIM_JSON = "xezim-json"    # xezim xezim_cov.json
FORMAT_VCS_VDB = "vcs-vdb"          # VCS <name>.vdb directory
FORMAT_QUESTA_UCDB = "questa-ucdb"  # Questa .ucdb file
FORMAT_XCELIUM_UCD = "xcelium-ucd"  # Xcelium cov_work directory (.ucm + .ucd)


def level_rank(name : str) -> int:
    """Position of `name` in :data:`LEVELS`. ValueError on an unknown level."""
    try:
        return LEVELS.index(name)
    except ValueError:
        raise ValueError("Unknown coverage level '%s' (valid: %s)" % (
            name, ", ".join(LEVELS))) from None


def max_level(*names : str) -> str:
    """The highest of `names` (each validated). 'none' when given none."""
    best = "none"
    for n in names:
        if level_rank(n) > level_rank(best):
            best = n
    return best


def write_cov_json(imgdir : str, level : str, kinds : List[str]) -> str:
    """Write the image's coverage record; return its path."""
    path = os.path.join(imgdir, COV_FILE)
    with open(path, "w") as fp:
        json.dump({"level": level, "kinds": list(kinds)}, fp, indent=2)
        fp.write("\n")
    return path


def read_cov_json(imgdir : str) -> Optional[Dict[str, Any]]:
    """The image's coverage record ``{level, kinds}``, or None when the image
    was built without coverage (no file) or the file is unreadable."""
    path = os.path.join(imgdir or "", COV_FILE)
    if not os.path.isfile(path):
        return None
    try:
        with open(path, "r") as fp:
            data = json.load(fp)
    except Exception as e:
        _log.debug("could not read %s: %s", path, e)
        return None
    if not isinstance(data, dict) or data.get("level", "none") == "none":
        return None
    data.setdefault("kinds", [])
    return data


def db_test_name(rundir : str) -> str:
    """The test name a run records in its database (VCS ``-cm_name``,
    Xcelium ``-covtest``): the run directory's name, reduced to characters
    every tool accepts. A merge tells runs apart by this name."""
    name = re.sub(r'[^A-Za-z0-9_]', '_', os.path.basename((rundir or "").rstrip("/")))
    return name or "test"


def remove_cov_json(imgdir : str) -> None:
    """Delete a record left by an earlier build (so the image never carries a
    stale level)."""
    path = os.path.join(imgdir or "", COV_FILE)
    if os.path.isfile(path):
        os.unlink(path)


#***************************************************************************
#* Summary stats: `cov_<kind>_{pct,covered,total}`
#***************************************************************************

def _kind_stats(kind : str, covered : int, total : int) -> Dict[str, Any]:
    return {
        "cov_%s_pct" % kind: round(100.0 * covered / total, 2),
        "cov_%s_covered" % kind: covered,
        "cov_%s_total" % kind: total,
    }


def _keep(kind : str, total : int, kinds : Optional[Iterable[str]]) -> bool:
    # A kind with nothing to cover (0/0) reports nothing rather than a false
    # 0%; a kind the level didn't ask for is dropped even if the tool printed it.
    if total <= 0:
        return False
    return kinds is None or kind in kinds


_VLT_LINE_RE = re.compile(
    r'^\s*(\w+)\s*:\s*[0-9.]+%\s*\(\s*(\d+)\s*/\s*(\d+)\s*\)\s*$')


def parse_vlt_cov_summary(text : str,
                          kinds : Optional[Iterable[str]] = None) -> Dict[str, Any]:
    """Parse ``verilator_coverage --report summary`` output into stats keys.

    Verilator prints every kind, with ``0.0% (0/0)`` for kinds that were not
    instrumented; those are dropped. Lines that don't parse are skipped.
    The percentage is recomputed from the counts, not taken from the text.
    """
    stats : Dict[str, Any] = {}
    for line in (text or "").splitlines():
        m = _VLT_LINE_RE.match(line)
        if m is None:
            continue
        kind, covered, total = m.group(1), int(m.group(2)), int(m.group(3))
        if kind not in KINDS or not _keep(kind, total, kinds):
            continue
        stats.update(_kind_stats(kind, covered, total))
    return stats


# xezim code_coverage kind -> KINDS name
_XZM_KINDS = {"statement": "line", "branch": "branch", "toggle": "toggle"}


def parse_xzm_cov_summary(obj : Any,
                          kinds : Optional[Iterable[str]] = None) -> Dict[str, Any]:
    """Code-coverage totals from a parsed ``xezim_cov.json``.

    Only ``code_coverage`` yields numbers: xezim lists hit covergroup bins but
    not unhit ones, so no functional percentage can be derived.
    """
    stats : Dict[str, Any] = {}
    cc = obj.get("code_coverage") if isinstance(obj, dict) else None
    if not isinstance(cc, dict):
        return stats
    for src, kind in _XZM_KINDS.items():
        ent = cc.get(src)
        if not isinstance(ent, dict):
            continue
        try:
            covered, total = int(ent["covered"]), int(ent["total"])
        except (KeyError, TypeError, ValueError):
            continue
        if _keep(kind, total, kinds):
            stats.update(_kind_stats(kind, covered, total))
    return stats


# urg dashboard column -> KINDS name. VCS's one FSM column counts transitions.
_VCS_KINDS = {"LINE": "line", "COND": "expr", "BRANCH": "branch",
              "TOGGLE": "toggle", "FSM": "fsm_arc", "ASSERT": "user",
              "GROUP": "covergroup"}

_RATIO_RE = re.compile(r'^(\d+)/(\d+)$')


def parse_vcs_cov_summary(text : str,
                          kinds : Optional[Iterable[str]] = None) -> Dict[str, Any]:
    """Parse the ``Total Coverage Summary`` table of the ``dashboard.txt``
    that ``urg -format text -show ratios`` writes.

    With ``-show ratios`` each column after SCORE is a percentage (or ``--``)
    followed by ``covered/total``. Only the ratios are used.
    """
    stats : Dict[str, Any] = {}
    lines = (text or "").splitlines()
    for i, line in enumerate(lines):
        if line.strip() != "Total Coverage Summary":
            continue
        if i + 2 >= len(lines):
            break
        cols = lines[i + 1].split()
        vals = lines[i + 2].split()
        if not cols or cols[0] != "SCORE":
            break
        # SCORE is one token; every other column is two (pct, ratio)
        for j, col in enumerate(cols[1:]):
            k = 2 + 2 * j
            if k >= len(vals):
                break
            m = _RATIO_RE.match(vals[k])
            kind = _VCS_KINDS.get(col)
            if m is None or kind is None:
                continue
            covered, total = int(m.group(1)), int(m.group(2))
            if _keep(kind, total, kinds):
                stats.update(_kind_stats(kind, covered, total))
        break
    return stats


# vcover row -> KINDS name. Conditions and Expressions both count as expr.
_MTI_KINDS = {"Statements": "line", "Branches": "branch",
              "Conditions": "expr", "Expressions": "expr",
              "Toggles": "toggle", "FSM States": "fsm_state",
              "FSM Transitions": "fsm_arc", "Covergroup Bins": "covergroup",
              "Directives": "user"}

_MTI_ROW_RE = re.compile(
    r'^\s*([A-Za-z][A-Za-z /]*?)\s+(\d+)\s+(\d+)\s+(\d+)\s+\d+\s+[0-9.]+%\s*$')


def parse_mti_cov_summary(text : str,
                          kinds : Optional[Iterable[str]] = None) -> Dict[str, Any]:
    """Parse ``vcover report -summary`` output (Bins / Hits rows).

    Rows with ``na`` counts (eg ``Covergroups``) and rows without a
    :data:`KINDS` mapping (eg ``Assertions``) are skipped.
    """
    counts : Dict[str, List[int]] = {}
    for line in (text or "").splitlines():
        m = _MTI_ROW_RE.match(line)
        if m is None:
            continue
        kind = _MTI_KINDS.get(m.group(1))
        if kind is None:
            continue
        c = counts.setdefault(kind, [0, 0])
        c[0] += int(m.group(3))
        c[1] += int(m.group(2))
    stats : Dict[str, Any] = {}
    for kind, (covered, total) in counts.items():
        if _keep(kind, total, kinds):
            stats.update(_kind_stats(kind, covered, total))
    return stats
