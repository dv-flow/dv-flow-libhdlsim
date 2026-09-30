#****************************************************************************
#* sim_stats.py
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
"""Per-run simulation statistics and metadata: the vocabulary + the collectors.

A SimRun emits two sparse maps alongside its verdict:

* ``stats``   -- *measurements* (how long, how much memory, how much simulated
                 time). Keys are drawn from :data:`STAT_KEYS`.
* ``runinfo`` -- *provenance* (which simulator, which seed, which plusargs,
                 which host). Keys are drawn from :data:`INFO_KEYS`.

**Sparse is the contract**: a key is present only when it was actually
measured. There is no "unknown" sentinel -- a backend that cannot report peak
memory simply omits ``maxrss_mb``, and a report renders that cell blank rather
than a misleading 0.

Three collection tiers, in decreasing portability:

1. *Host process* (:func:`wrap_host_stats` / :func:`parse_host_stats`) -- CPU
   time, peak RSS, I/O and context switches, obtained by running the simulator
   under GNU ``/usr/bin/time``. Simulator-agnostic: every backend gets it for
   free, when a GNU ``time`` exists (probed once; silently skipped otherwise).
2. *Simulator-reported* -- simulated time, the simulator's own wall/CPU/memory
   accounting, thread count, finish reason. Parsed per backend by the
   ``VLSimRunner.parse_sim_stats`` hook; only Verilator implements it today.
   Coverage totals (``cov_<kind>_pct/_covered/_total``) are tier 2 as well:
   the ``VLSimRunner.parse_cov_summary`` hook, run only when the image was
   built with coverage (see :mod:`cov`).
3. *Testbench-reported* (:func:`read_tb_stats`) -- an optional ``tb_stats.json``
   the testbench itself may drop in the rundir (cycle counts, transaction
   counts, custom counters). Merged when present, ignored when not.

This module imports nothing from dv-flow, so it unit-tests standalone.
"""

import getpass
import json
import logging
import os
import re
import shutil
import socket
import subprocess
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from . import cov as _cov

_log = logging.getLogger("sim_stats")

# Filenames written into / read from the run directory.
HOST_STATS_FILE = "sim.time"    # raw GNU-time output (intermediate)
STATS_FILE = "sim_stats.json"   # the merged stats+runinfo record
TB_STATS_FILE = "tb_stats.json" # optional testbench-written counters


#***************************************************************************
#* The vocabulary: which keys mean what, and how a suite aggregates them.
#*
#* `agg` drives SimSuiteReport's roll-up:
#*   sum  -- total across cases (time, work done)
#*   max  -- worst case across cases (memory, per-case duration outliers)
#*   none -- per-case only; meaningless to combine
#***************************************************************************

# key -> (unit, agg, doc)
STAT_KEYS : Dict[str, Tuple[str, str, str]] = {
    # -- host process (tier 1: portable) ------------------------------------
    "walltime_s":    ("s",   "sum", "Wall-clock seconds for the simulator process"),
    "cpu_user_s":    ("s",   "sum", "User CPU seconds"),
    "cpu_sys_s":     ("s",   "sum", "System CPU seconds"),
    "cpu_total_s":   ("s",   "sum", "User+system CPU seconds"),
    "cpu_pct":       ("%",   "max", "CPU utilization (cpu_total_s/walltime_s*100)"),
    "maxrss_mb":     ("MB",  "max", "Peak resident set size of the simulator process"),
    "io_read_mb":    ("MB",  "sum", "Filesystem input"),
    "io_write_mb":   ("MB",  "sum", "Filesystem output"),
    "ctx_vol":       ("",    "sum", "Voluntary context switches"),
    "ctx_invol":     ("",    "sum", "Involuntary context switches"),

    # -- simulator-reported (tier 2: backend-dependent) ---------------------
    "simtime":       ("",    "none", "Simulated time as the simulator printed it (eg '608us')"),
    "simtime_s":     ("s",   "sum",  "Simulated time in seconds, derived from `simtime`"),
    "sim_walltime_s":("s",   "sum",  "Wall seconds inside the simulation loop (excludes startup)"),
    "sim_cpu_s":     ("s",   "sum",  "CPU seconds as reported by the simulator itself"),
    "sim_mem_mb":    ("MB",  "max",  "Peak memory as reported by the simulator itself"),
    "threads":       ("",    "max",  "Simulator thread count"),
    "sim_speed_s_per_s": ("", "none", "Simulated seconds per wall second (simtime_s/walltime_s)"),

    # -- log-derived tallies (filled by the Check tasks) --------------------
    "errors":        ("",    "sum", "UVM_ERROR count"),
    "warnings":      ("",    "sum", "UVM_WARNING count"),
    "fatals":        ("",    "sum", "UVM_FATAL count"),
    "infos":         ("",    "sum", "UVM_INFO count"),

    # -- testbench-reported (tier 3: opt-in convention) ---------------------
    "cycles":        ("",    "sum", "Clock cycles simulated (testbench-reported)"),
    "transactions":  ("",    "sum", "Transactions driven/observed (testbench-reported)"),
}

# -- coverage summary (tier 2: parse_cov_summary) ---------------------------
# Per kind: the percentage rolls up as the best single run (`_pct_max`) -- a
# mean of per-run percentages is not a merged figure, and summing per-run hit
# counts is not a merge either, so `_covered`/`_total` stay per-case.
for _k in _cov.KINDS:
    STAT_KEYS["cov_%s_pct" % _k] = ("%", "max", "%s coverage percentage" % _k)
    STAT_KEYS["cov_%s_covered" % _k] = ("", "none", "%s coverage points hit" % _k)
    STAT_KEYS["cov_%s_total" % _k] = ("", "none", "%s coverage points" % _k)
del _k

# key -> doc. Provenance: what was run, how, and where.
INFO_KEYS : Dict[str, str] = {
    "case_name":    "Case name recorded for this run",
    "testname":     "Test identity (eg UVM_TESTNAME)",
    "sim":          "Simulator backend (vlt/vcs/mti/xcm/xsm/ivl/xzm)",
    "sim_version":  "Simulator version string, when the log reports one",
    "mode":         "SimRun mode ('run' or 'test')",
    "seed":         "Random seed applied to the run",
    "seed_source":  "Which argument the seed was taken from",
    "cmd":          "Full simulator command line (argv list)",
    "args":         "Runtime arguments passed to the simulator",
    "plusargs":     "Plusargs applied to the run",
    "dpilibs":      "DPI libraries loaded",
    "vpilibs":      "VPI libraries loaded",
    "imgdir":       "Simulation image directory the run used",
    "rundir":       "Directory the run executed in",
    "logfile":      "Simulation log file, relative to rundir",
    "trace":        "Whether waveform tracing was requested",
    "valgrind":     "Whether the run was executed under valgrind",
    "cov":          "Coverage level and kinds collected ({level, kinds}); absent at none",
    "finish_reason":"How the run ended ($finish / $stop / end / signal)",
    "exit_code":    "Simulator process exit code",
    "host":         "Host the run executed on",
    "user":         "User the run executed as",
    "nproc":        "CPU count of the host",
    "start_time":   "Run start, ISO-8601 UTC",
    "end_time":     "Run end, ISO-8601 UTC",
}


def utcnow() -> str:
    """ISO-8601 UTC timestamp, second resolution."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


#***************************************************************************
#* Time-with-unit parsing
#***************************************************************************

_UNIT_S = {
    "s": 1.0, "ms": 1e-3, "us": 1e-6, "ns": 1e-9,
    "ps": 1e-12, "fs": 1e-15, "as": 1e-18,
}

_TIME_RE = re.compile(r'^\s*([0-9]*\.?[0-9]+)\s*([munpfa]?s)\s*$', re.I)


def parse_time_str(s : str) -> Optional[float]:
    """'608us' / '1.5 ms' / '3s' -> seconds. None if it doesn't parse.

    NOTE for callers comparing runs: a simulator's printed simulated time is
    only as precise as it chose to print. Verilator scales to 1..1000 and
    formats with %0.0f, so 1.4ms prints as '1ms' -- fine for trend/report
    purposes, not a substitute for a testbench-reported cycle count.
    """
    if s is None:
        return None
    m = _TIME_RE.match(str(s))
    if m is None:
        return None
    mult = _UNIT_S.get(m.group(2).lower())
    if mult is None:
        return None
    return float(m.group(1)) * mult


def format_time_s(seconds : float) -> str:
    """Seconds -> a compact engineering string ('2us', '1.25ms', '3.4s').

    The inverse of :func:`parse_time_str`, used for reporting: a suite's total
    simulated time is meaningless rendered as '0.00s'.
    """
    try:
        v = float(seconds)
    except (TypeError, ValueError):
        return ""
    if v == 0:
        return "0s"
    neg = "-" if v < 0 else ""
    v = abs(v)
    for unit, mult in (("s", 1.0), ("ms", 1e-3), ("us", 1e-6),
                       ("ns", 1e-9), ("ps", 1e-12), ("fs", 1e-15)):
        if v >= mult:
            scaled = v / mult
            txt = ("%.3g" % scaled)
            return "%s%s%s" % (neg, txt, unit)
    return "%s%.3gas" % (neg, v / 1e-18)


#***************************************************************************
#* Tier 1: host-process stats via GNU time
#***************************************************************************

# One key=value pair per field, so parsing needs no positional assumptions.
# %e wall, %U user, %S sys, %M maxrss(KB), %x exit, %w/%c ctx switches,
# %I/%O filesystem in/out blocks.
_TIME_FMT = ("hoststats walltime_s=%e cpu_user_s=%U cpu_sys_s=%S maxrss_kb=%M "
             "exit=%x ctx_vol=%w ctx_invol=%c io_in=%I io_out=%O")

_TIME_EXE : Optional[str] = None
_TIME_PROBED = False


def _gnu_time() -> Optional[str]:
    """Path to a GNU ``time`` that accepts ``-f``/``-o``, or None.

    Probed once per process: a BSD ``time`` rejects ``-f`` and would refuse to
    run the command at all, so we must not blindly prepend it.
    """
    global _TIME_EXE, _TIME_PROBED
    if _TIME_PROBED:
        return _TIME_EXE
    _TIME_PROBED = True
    for cand in ("/usr/bin/time", shutil.which("time")):
        if not cand or not os.path.isfile(cand):
            continue
        try:
            p = subprocess.run([cand, "-f", "probe=%e", "-o", os.devnull, "true"],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                               timeout=10)
            if p.returncode == 0:
                _TIME_EXE = cand
                break
        except Exception:
            continue
    if _TIME_EXE is None:
        _log.debug("no GNU time found; host CPU/memory stats disabled")
    return _TIME_EXE


def wrap_host_stats(cmd : List[str], statfile : str) -> List[str]:
    """Prefix `cmd` with GNU time writing `statfile`, or return it unchanged.

    GNU time propagates the child's exit status, so wrapping is transparent to
    the caller's pass/fail handling.
    """
    exe = _gnu_time()
    if exe is None:
        return cmd
    return [exe, "-f", _TIME_FMT, "-o", statfile] + list(cmd)


def parse_host_stats(path : str) -> Dict[str, Any]:
    """Parse the GNU-time output file into `stats` keys. {} if unusable."""
    if not path or not os.path.isfile(path):
        return {}
    line = None
    try:
        with open(path, "r", errors="replace") as fp:
            for l in fp:
                # GNU time may prepend eg "Command terminated by signal 11".
                if l.startswith("hoststats "):
                    line = l
    except Exception as e:
        _log.debug("could not read host stats %s: %s", path, e)
        return {}
    if line is None:
        return {}

    raw = {}
    for tok in line.split()[1:]:
        if "=" in tok:
            k, v = tok.split("=", 1)
            raw[k] = v

    def _f(key):
        try:
            return float(raw[key])
        except (KeyError, ValueError):
            return None

    stats : Dict[str, Any] = {}
    for k in ("walltime_s", "cpu_user_s", "cpu_sys_s"):
        v = _f(k)
        if v is not None:
            stats[k] = v
    if "cpu_user_s" in stats and "cpu_sys_s" in stats:
        stats["cpu_total_s"] = round(stats["cpu_user_s"] + stats["cpu_sys_s"], 3)
        wall = stats.get("walltime_s")
        if wall:
            stats["cpu_pct"] = round(100.0 * stats["cpu_total_s"] / wall, 1)
    mem = _f("maxrss_kb")
    if mem is not None:
        stats["maxrss_mb"] = round(mem / 1024.0, 1)
    for src, dst in (("io_in", "io_read_mb"), ("io_out", "io_write_mb")):
        v = _f(src)
        if v:  # 0 blocks == nothing read/written; drop the noise
            # GNU time counts 512-byte filesystem blocks.
            stats[dst] = round(v * 512 / (1024.0 * 1024.0), 2)
    for src, dst in (("ctx_vol", "ctx_vol"), ("ctx_invol", "ctx_invol")):
        v = _f(src)
        if v is not None:
            stats[dst] = int(v)
    return stats


#***************************************************************************
#* Tier 3: testbench-reported counters
#***************************************************************************

def read_tb_stats(rundir : str) -> Dict[str, Any]:
    """Read the optional `tb_stats.json` a testbench may write in its rundir.

    Convention (not a requirement): a flat JSON object of counters, eg
    ``{"cycles": 120400, "transactions": 512}``. Non-scalar values are dropped;
    everything else is merged into `stats` as-is, so a testbench can publish
    custom counters without any change here.
    """
    path = os.path.join(rundir or "", TB_STATS_FILE)
    if not os.path.isfile(path):
        return {}
    try:
        with open(path, "r") as fp:
            data = json.load(fp)
    except Exception as e:
        _log.debug("could not read %s: %s", path, e)
        return {}
    if not isinstance(data, dict):
        return {}
    return {k: v for k, v in data.items() if isinstance(v, (int, float, str))}


#***************************************************************************
#* Seed extraction
#***************************************************************************

# Per-simulator seed spellings, tried against both args and plusargs.
# (pattern, source-label). Patterns match with or without a leading +/-.
_SEED_PATTERNS = (
    (re.compile(r'^\+?verilator\+seed\+(\d+)$', re.I),      "+verilator+seed"),
    (re.compile(r'^\+?ntb_random_seed=(\d+)$', re.I),       "+ntb_random_seed"),
    (re.compile(r'^-?-?sv_?seed[= ]?(\d+)$', re.I),         "-sv_seed"),
    (re.compile(r'^-?-?svseed[= ]?(\d+)$', re.I),           "-svseed"),
    (re.compile(r'^\+?seed[=+](\d+)$', re.I),               "+seed"),
    (re.compile(r'^\+?UVM_SEED=(\d+)$', re.I),              "+UVM_SEED"),
)


def extract_seed(args : List[str], plusargs : List[str]) -> Tuple[Optional[int], str]:
    """Best-effort (seed, source) from the run's arguments.

    Handles both the `-sv_seed 1234` (two-token) and `-sv_seed=1234` spellings.
    Returns (None, "") when no seed was explicitly applied -- which is the
    common case, and is reported as such rather than as a fabricated 0.
    """
    toks : List[str] = []
    for t in list(args or []) + ["+%s" % p for p in (plusargs or [])]:
        toks.extend(str(t).split())

    for i, tok in enumerate(toks):
        for pat, label in _SEED_PATTERNS:
            m = pat.match(tok)
            if m:
                try:
                    return int(m.group(1)), label
                except ValueError:
                    pass
        # two-token form: '-sv_seed 1234'
        if tok.lower().lstrip("-") in ("sv_seed", "svseed") and i + 1 < len(toks):
            try:
                return int(toks[i + 1]), "-" + tok.lstrip("-")
            except ValueError:
                pass
    return None, ""


#***************************************************************************
#* Assembly + persistence
#***************************************************************************

def host_info() -> Dict[str, Any]:
    """Host/user/CPU-count provenance. Never raises."""
    info : Dict[str, Any] = {}
    try:
        info["host"] = socket.gethostname()
    except Exception:
        pass
    try:
        info["user"] = getpass.getuser()
    except Exception:
        pass
    try:
        info["nproc"] = os.cpu_count() or 0
    except Exception:
        pass
    return info


def finalize(stats : Dict[str, Any]) -> Dict[str, Any]:
    """Fill in the derived keys that need the whole picture.

    `simtime_s` from `simtime`, and `sim_speed_s_per_s` from the two times --
    each only when its inputs are present, keeping the map sparse.
    """
    if "simtime" in stats and "simtime_s" not in stats:
        v = parse_time_str(stats["simtime"])
        if v is not None:
            stats["simtime_s"] = v
    wall = stats.get("walltime_s")
    if stats.get("simtime_s") is not None and wall:
        stats["sim_speed_s_per_s"] = float("%.6g" % (stats["simtime_s"] / wall))
    return stats


def write_stats_json(rundir : str, stats : Dict[str, Any],
                     runinfo : Dict[str, Any]) -> Optional[str]:
    """Write `sim_stats.json` into the rundir; return its path (None on error).

    The file is the durable, tool-neutral record of the run -- readable without
    dv-flow, which is what makes after-the-fact triage and external dashboards
    possible.
    """
    if not rundir:
        return None
    path = os.path.join(rundir, STATS_FILE)
    try:
        with open(path, "w") as fp:
            json.dump({"stats": stats, "runinfo": runinfo}, fp,
                      indent=2, sort_keys=True, default=str)
            fp.write("\n")
    except Exception as e:
        # Statistics must never change a run's verdict.
        _log.debug("could not write %s: %s", path, e)
        return None
    return path


#***************************************************************************
#* Suite-level aggregation
#***************************************************************************

def aggregate(stats_list : List[Dict[str, Any]]) -> Dict[str, Any]:
    """Roll up per-case `stats` maps per each key's `agg` rule.

    Emits `<key>` for sum keys, `<key>_max` for max keys, plus `<key>_mean` for
    summed durations (a mean is what tells you whether one outlier or the whole
    suite got slower). Keys no case reported stay absent.
    """
    def _r(v):
        # Significant-digit rounding, NOT round(v, 3): simulated time is
        # routinely 1e-6 s, and fixed decimals would report every sub-ms suite
        # as having simulated 0 seconds.
        if isinstance(v, float):
            return float("%.6g" % v)
        return v

    out : Dict[str, Any] = {}
    for key, (_unit, agg, _doc) in STAT_KEYS.items():
        vals = []
        for s in stats_list:
            v = (s or {}).get(key)
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                vals.append(v)
        if not vals:
            continue
        if agg == "sum":
            total = sum(vals)
            out[key] = _r(total)
            out["%s_max" % key] = _r(max(vals))
            out["%s_mean" % key] = _r(total / len(vals))
        elif agg == "max":
            out["%s_max" % key] = _r(max(vals))
    return out
