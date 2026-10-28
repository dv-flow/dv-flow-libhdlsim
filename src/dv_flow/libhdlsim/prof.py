#****************************************************************************
#* prof.py
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
"""Simulator profiling: the mode vocabulary, the image's ``prof.json``
record, the normalized run summary, and the per-backend report parsers.

A profiling *mode* is requested through ``hdlsim.SimProfArgs`` (or SimImage's
``prof`` parameter), and works the same on every simulator that supports it:

* ``none`` -- no profiling (the default)
* ``time`` -- where the CPU time goes
* ``mem``  -- where the memory goes

Unlike coverage levels, modes are not cumulative: the tools say to profile
time and memory in separate runs, since each skews the other.

A *deep* profiler is one simulator's own tool (Xcelium's xProf, say). Each is
requested through that simulator's typed args (``hdlsim.XcmProfArgs``) or a
param of its SimImage, so a backend honors only its own and the others ignore
them. A deep profiler's output is kept for the vendor's tools; it does not
feed the summary below.

SimImage records the mode, and any deep profilers, in ``prof.json`` in the
image directory (``{"mode": "time", "deep": {"xprof": true}}``) and SimRun
reads it back, so a run always follows its image. After the run the backend
condenses its profiler's report into ``prof_summary.json`` in the rundir::

    {"mode": "time", "sim": "vcs",
     "categories": {"solver": 65.3, "hdl": 8.3, ...},
     "top": [{"scope": "module", "name": "top", "pct": 10.4,
              "instances": 17}, ...]}

``categories`` are percentages of the profiled total, using
:data:`CATEGORIES`; a category is present only where the tool reports it.
A ``mem`` summary also carries ``mem_peak_mb``, the peak as the tool defines
it (VCS: the whole process image, libraries included; Xcelium: physical;
Questa: the process size, VSZ).

This module imports nothing from dv-flow, so it unit-tests standalone.
"""

import json
import logging
import os
import re
from typing import Any, Dict, List, Optional

_log = logging.getLogger("prof")

MODES = ("none", "time", "mem")

# hdl    -- design code: modules, always/initial blocks, continuous assigns
# tb     -- testbench code: classes, packages, programs
# solver -- randomize() and the constraint solver
# pli    -- user C code: DPI, PLI, VPI
# assert -- assertion evaluation
# cov    -- functional coverage sampling
# kernel -- the simulator itself: scheduler, startup, licensing, UI
# other  -- reported by the tool but not mapped onto the above
CATEGORIES = ("hdl", "tb", "solver", "pli", "assert", "cov", "kernel", "other")

# The per-image profiling record, written by SimImage and read by SimRun.
PROF_FILE = "prof.json"
# The run's normalized profile summary.
SUMMARY_FILE = "prof_summary.json"

# How many `top` entries a summary keeps.
TOP_N = 20

# `format=` attribute values on the simProfDb artifact.
FORMAT_VCS_SIMPROFILE = "vcs-simprofile"     # VCS simprofile_dir
FORMAT_XCELIUM_XMPROF = "xcelium-xmprof"     # Xcelium xmprof.out
FORMAT_XCELIUM_XMPROFMEM = "xcelium-xmprofmem"  # Xcelium xmprofmem.json
FORMAT_QUESTA_FDB = "questa-fdb"             # Questa fprofile .fdb
FORMAT_VLT_GMON = "vlt-gmon"                 # Verilator gmon.out
FORMAT_XCELIUM_XPROF = "xcelium-xprof"       # Xcelium xProf -prof_work dir


def check_mode(name : str) -> str:
    """`name` if it is a valid mode; ValueError otherwise."""
    if name not in MODES:
        raise ValueError("Unknown profiling mode '%s' (valid: %s)" % (
            name, ", ".join(MODES)))
    return name


def resolve_mode(*names : str) -> str:
    """The one mode requested across `names` ('none' entries ignored).
    ValueError on an unknown mode, or on two different non-`none` modes."""
    mode = "none"
    for n in names:
        if check_mode(n) == "none" or n == mode:
            continue
        if mode != "none":
            raise ValueError(
                "Conflicting profiling modes '%s' and '%s': profile time and "
                "memory in separate images" % (mode, n))
        mode = n
    return mode


def write_prof_json(imgdir : str, mode : str,
                    deep : Optional[Dict[str, Any]] = None) -> str:
    """Write the image's profiling record; return its path. `deep` holds the
    deep profilers enabled, by switch name; omitted when empty."""
    path = os.path.join(imgdir, PROF_FILE)
    data : Dict[str, Any] = {"mode": mode}
    if deep:
        data["deep"] = dict(deep)
    with open(path, "w") as fp:
        json.dump(data, fp, indent=2)
        fp.write("\n")
    return path


def read_prof_json(imgdir : str) -> Optional[Dict[str, Any]]:
    """The image's profiling record ``{mode[, deep]}``, or None when the
    image was built without profiling (no file) or the file is unreadable.
    The mode may be `none` when only a deep profiler is enabled."""
    path = os.path.join(imgdir or "", PROF_FILE)
    if not os.path.isfile(path):
        return None
    try:
        with open(path, "r") as fp:
            data = json.load(fp)
    except Exception as e:
        _log.debug("could not read %s: %s", path, e)
        return None
    if not isinstance(data, dict) or data.get("mode", "none") not in MODES:
        return None
    if data.get("mode", "none") == "none" and not data.get("deep"):
        return None
    return data


def remove_prof_json(imgdir : str) -> None:
    """Delete a record left by an earlier build."""
    path = os.path.join(imgdir or "", PROF_FILE)
    if os.path.isfile(path):
        os.unlink(path)


#***************************************************************************
#* The normalized summary
#***************************************************************************

def make_summary(mode : str, sim : str, categories : Dict[str, float],
                 top : List[Dict[str, Any]],
                 mem_peak_mb : Optional[float] = None) -> Dict[str, Any]:
    """Assemble a summary. Categories at 0 are dropped; `top` is sorted
    largest first and cut to :data:`TOP_N`."""
    cats = {}
    for c in CATEGORIES:
        v = round(categories.get(c, 0.0), 2)
        if v > 0:
            cats[c] = v
    key = "pct" if any("pct" in t for t in top) else "bytes"
    top = sorted(top, key=lambda t: t.get(key, 0), reverse=True)[:TOP_N]
    summary = {"mode": mode, "sim": sim, "categories": cats, "top": top}
    if mem_peak_mb is not None:
        summary["mem_peak_mb"] = round(mem_peak_mb, 1)
    return summary


def write_summary(rundir : str, summary : Dict[str, Any]) -> str:
    path = os.path.join(rundir, SUMMARY_FILE)
    with open(path, "w") as fp:
        json.dump(summary, fp, indent=2)
        fp.write("\n")
    return path


def read_summary(path : str) -> Optional[Dict[str, Any]]:
    """A summary written by :func:`write_summary`, or None."""
    try:
        with open(path, "r") as fp:
            data = json.load(fp)
    except Exception as e:
        _log.debug("could not read %s: %s", path, e)
        return None
    return data if isinstance(data, dict) else None


def summary_stats(summary : Dict[str, Any],
                  cpu_s : Optional[float] = None) -> Dict[str, Any]:
    """The `stats` keys for a summary: ``prof_<cat>_pct`` for each category,
    ``prof_<cat>_s`` (the share of `cpu_s`) for a time profile when `cpu_s`
    is known, and ``prof_mem_peak_mb``."""
    stats : Dict[str, Any] = {}
    time_mode = summary.get("mode") == "time"
    for cat, pct in (summary.get("categories") or {}).items():
        stats["prof_%s_pct" % cat] = pct
        if time_mode and cpu_s:
            stats["prof_%s_s" % cat] = round(cpu_s * pct / 100.0, 3)
    if summary.get("mem_peak_mb") is not None:
        stats["prof_mem_peak_mb"] = summary["mem_peak_mb"]
    return stats


#***************************************************************************
#* VCS: profileReport.json (`simv -simprofile time|mem`)
#***************************************************************************

# Summary View component -> category. Names not listed fall to `other`.
_VCS_CATS = {
    "CONSTRAINT": "solver",
    "VERILOG": "hdl",
    "PLI/DPI/DirectC": "pli",   # time view
    "PLI/DPI": "pli",           # memory view
    "KERNEL": "kernel",
    "UCLI": "kernel",
    "HSIM": "kernel",
    "Anonymous": "kernel",
    "SNPS Memory Pool": "kernel",
    "Library/Executable": "kernel",
    "Profiling": "kernel",
}

# VERILOG's sub-components that belong elsewhere. Class code compiled in
# $unit or a package reports as `Package`.
_VCS_VERILOG_SUB = {
    "Module": "hdl",
    "Package": "tb",
    "Functional Coverage": "cov",
    "Function Coverage Kernel": "cov",
}


def _vcs_categories(entries : List[Dict[str, Any]]) -> Dict[str, float]:
    cats : Dict[str, float] = {}
    for ent in entries or []:
        name = ent.get("Component", "")
        pct = float(ent.get("Percentage", 0.0) or 0.0)
        cat = _VCS_CATS.get(name, "other")
        if name == "VERILOG":
            # Split by sub-component; what they don't account for stays hdl
            rest = pct
            for sub in ent.get("SubContent") or []:
                sub_pct = float(sub.get("Percentage", 0.0) or 0.0)
                sub_cat = _VCS_VERILOG_SUB.get(sub.get("Component", ""), cat)
                cats[sub_cat] = cats.get(sub_cat, 0.0) + sub_pct
                rest -= sub_pct
            if rest > 0.005:
                cats[cat] = cats.get(cat, 0.0) + rest
        else:
            cats[cat] = cats.get(cat, 0.0) + pct
    return cats


def _vcs_module(name : str) -> str:
    # VCS reports $unit (and class code compiled there) as _global_
    return "$unit" if name == "_global_" else name


def parse_vcs_profile(obj : Any, mode : str) -> Optional[Dict[str, Any]]:
    """Summary of a parsed ``profileReport.json``: categories from the
    Summary View, `top` from the Module View. None when the report has no
    section for `mode`."""
    if not isinstance(obj, dict):
        return None
    if mode == "time":
        sect = obj.get("Time")
        if not isinstance(sect, dict):
            return None
        cats = _vcs_categories((sect.get("Summary") or {}).get("EntryContent"))
        top = []
        for m in (sect.get("Module") or {}).get("EntryContent") or []:
            top.append({"scope": "module", "name": _vcs_module(m.get("Module", "")),
                        "pct": round(float(m.get("%TotalTime", 0.0)), 2),
                        "instances": int(m.get("#Instances", 0))})
        return make_summary(mode, "vcs", cats, top)
    if mode == "mem":
        sect = obj.get("Memory")
        if not isinstance(sect, dict):
            return None
        summ = sect.get("Summary") or {}
        cats = _vcs_categories(summ.get("EntryContent"))
        peak = None
        total = (summ.get("TOTAL") or {}).get("Memory")
        if isinstance(total, (int, float)):
            peak = total / (1024.0 * 1024.0)
        top = []
        for m in (sect.get("Module") or {}).get("EntryContent") or []:
            top.append({"scope": "module", "name": _vcs_module(m.get("Module", "")),
                        "bytes": int(m.get("Memory", 0)),
                        "instances": int(m.get("#Instances", 0))})
        return make_summary(mode, "vcs", cats, top, peak)
    return None


#***************************************************************************
#* Xcelium: xmprof.out (`xmsim -profile`), xmprofmem.* (`xmsim -memdetail`)
#***************************************************************************

# Technology-wise Summary row -> category
_XCM_TECH = {
    "Randomization": "solver",
    "TB/SV": "tb",
    "RTL/Design": "hdl",
    "Miscellaneous": "kernel",
}

# Stream Type rows carved out of a Technology bucket: (category, from).
# Outside engine (user C code) is counted in Miscellaneous and assertions in
# RTL/Design.
_XCM_STREAM = {
    "Outside engine": ("pli", "kernel"),
    "Assertions": ("assert", "hdl"),
}

_XCM_HITS_RE = re.compile(r'^\s*[0-9.]+\s+(\d+)\s+(?:\[\s*(\d*)\]\s+)?(.+?)\s*$')
_XCM_MODULE_RE = re.compile(r'^\S+?\.([^.:\s]+):(\w+)')


def _xcm_sections(text : str) -> Dict[str, List[str]]:
    """Body lines of each dashed-rule-delimited table, keyed by its title."""
    sects : Dict[str, List[str]] = {}
    lines = (text or "").splitlines()
    i = 0
    while i < len(lines):
        if lines[i].startswith("-----") and i + 2 < len(lines) \
                and lines[i + 2].startswith("-----"):
            title = re.sub(r'\s*\(.*$', '', lines[i + 1].strip())
            body = []
            j = i + 3
            while j < len(lines) and lines[j].strip() \
                    and not lines[j].startswith("-----"):
                body.append(lines[j])
                j += 1
            sects[title] = body
            i = j
        else:
            i += 1
    return sects


def _xcm_hits(body : List[str]) -> List[tuple]:
    rows = []
    for line in body:
        m = _XCM_HITS_RE.match(line)
        if m is None or line.lstrip().startswith("%"):
            continue
        rows.append((int(m.group(1)), m.group(2), m.group(3)))
    return rows


def parse_xcm_xmprof(text : str) -> Optional[Dict[str, Any]]:
    """Summary of an ``xmprof.out``: categories from the Technology-wise and
    Stream Type tables, `top` from Most Active Modules. None when the file
    has no Technology-wise table."""
    sects = _xcm_sections(text)
    tech = _xcm_hits(sects.get("Technology-wise Summary Counts", []))
    if not tech:
        return None
    total = sum(h for h, _, _ in tech)
    if total <= 0:
        return None
    hits : Dict[str, int] = {}
    for h, _, name in tech:
        cat = _XCM_TECH.get(name, "other")
        hits[cat] = hits.get(cat, 0) + h
    for h, _, name in _xcm_hits(sects.get("Stream Type Summary Counts", [])):
        if name not in _XCM_STREAM:
            continue
        cat, src = _XCM_STREAM[name]
        h = min(h, hits.get(src, 0))
        hits[src] = hits.get(src, 0) - h
        hits[cat] = hits.get(cat, 0) + h
    cats = {c: 100.0 * h / total for c, h in hits.items()}

    top = []
    for line in sects.get("Most Active Modules", []):
        m = _XCM_HITS_RE.match(line)
        if m is None or line.lstrip().startswith("%"):
            continue
        pct = float(line.split()[0])
        name = m.group(3)
        mm = _XCM_MODULE_RE.match(name)
        if mm is not None:
            name = "$unit" if mm.group(2) == "compilation_unit" else mm.group(1)
            if name.startswith("$unit_"):
                name = "$unit"
        top.append({"scope": "module", "name": name, "pct": pct,
                    "instances": int(m.group(2) or 0)})
    return make_summary("time", "xcm", cats, top)


def _json_stream(text : str) -> List[Any]:
    """Each JSON value in `text`. xmprofmem.json is a sequence of objects,
    one per sample, rather than one document."""
    dec = json.JSONDecoder()
    out = []
    i, n = 0, len(text or "")
    while i < n:
        while i < n and text[i].isspace():
            i += 1
        if i >= n:
            break
        try:
            obj, i = dec.raw_decode(text, i)
        except ValueError:
            break
        out.append(obj)
    return out


_XCM_DU_RE = re.compile(r'^\s(\S+:\S+)\s+([\d,]+)\s+[\d,]+\s')


def parse_xcm_xmprofmem(json_text : str,
                        out_text : str = "") -> Optional[Dict[str, Any]]:
    """Summary of an ``-memdetail`` run: the peak physical memory over the
    samples in ``xmprofmem.json`` (KB), and `top` from the design-unit table
    of ``xmprofmem.out``. None when there are no samples."""
    peak_kb = None
    for obj in _json_stream(json_text):
        if not isinstance(obj, dict):
            continue
        for sample in obj.values():
            dyn = sample.get("Dynamic") if isinstance(sample, dict) else None
            if not isinstance(dyn, dict):
                continue
            try:
                kb = float(dyn["current physical memory"])
            except (KeyError, TypeError, ValueError):
                continue
            peak_kb = kb if peak_kb is None else max(peak_kb, kb)
    if peak_kb is None:
        return None

    top = []
    for line in (out_text or "").splitlines():
        if line.strip().startswith("Hierarchy_name"):
            break       # past the design-unit table
        m = _XCM_DU_RE.match(line)
        if m is None:
            continue
        mm = _XCM_MODULE_RE.match(m.group(1))
        name = m.group(1)
        if mm is not None:
            name = "$unit" if mm.group(2) == "compilation_unit" else mm.group(1)
        top.append({"scope": "module", "name": name,
                    "bytes": int(m.group(2).replace(",", ""))})
    return make_summary("mem", "xcm", {}, top, peak_kb / 1024.0)


#***************************************************************************
#* Questa: the visualizer text report (`vsim -fprofile+perf|mem`, then
#* `visualizer -fbatch -fprofile+perf|mem+report=<file>`)
#***************************************************************************

# Performance/Summary row -> category. Questa reports RTL and class code
# together as `SV`, so a Questa `hdl` includes testbench code.
_MTI_PERF = {
    "SV": "hdl",
    "Verilog": "hdl",
    "VHDL": "hdl",
    "Solver": "solver",
    "C code": "pli",
    "Assertions": "assert",
    "Coverage": "cov",
    "Kernel": "kernel",
}

# Memory Overview: the process rows, then the rows under HDL
_MTI_MEM = {
    "Kernel": "kernel",
    "Reserved": "kernel",
    "Non-Kernel": "other",
}
_MTI_MEM_HDL = {
    "Assertions": "assert",
    "Solver": "solver",
    "Covergroups": "cov",
    "Classes": "tb",
    "Queues": "tb",
    "Strings": "tb",
    "Dynamic Arrays": "tb",
    "Associative Arrays": "tb",
}

_MTI_TABLE_RE = re.compile(r"^=== '/(.+?) \(.*\)' Report$")


def _mti_tables(text : str) -> Dict[str, List[List[str]]]:
    """Rows of each report table, keyed by its path (eg
    ``Performance/Summary``). A row's cells are stripped, except the first
    keeps its indentation (two spaces per tree level)."""
    tables : Dict[str, List[List[str]]] = {}
    lines = (text or "").splitlines()
    i = 0
    while i < len(lines):
        m = _MTI_TABLE_RE.match(lines[i])
        if m is None:
            i += 1
            continue
        # Title, rule, column header, rule, then rows to a blank line
        j = i + 1
        while j < len(lines) and not lines[j].startswith("---"):
            j += 1
        rows = []
        j += 1
        while j < len(lines) and lines[j].strip():
            cells = lines[j].split("|")
            rows.append([cells[0].rstrip()] + [c.strip() for c in cells[1:]])
            j += 1
        tables[m.group(1)] = rows
        i = j
    return tables


def _mti_num(cell : str) -> float:
    """A report number: '12.5%', ' 0.78', or '<0.01' (as 0)."""
    cell = cell.strip().rstrip("%")
    if not cell or cell.startswith("<"):
        return 0.0
    try:
        return float(cell)
    except ValueError:
        return 0.0


def _mti_depth(cell : str) -> int:
    return (len(cell) - len(cell.lstrip())) // 2


def parse_mti_report(text : str, mode : str) -> Optional[Dict[str, Any]]:
    """Summary of a visualizer text report. A time profile takes its
    categories from Performance/Summary and `top` from Performance/Design
    Unit; a memory profile takes them from Memory/Memory Overview (shares of
    the process size) and Memory/Design Unit Memory, and its peak is the
    peak process size (VSZ). None when the report lacks those tables."""
    tables = _mti_tables(text)
    if mode == "time":
        rows = tables.get("Performance/Summary")
        if not rows:
            return None
        cats : Dict[str, float] = {}
        for row in rows:
            if len(row) < 2:
                continue
            cat = _MTI_PERF.get(row[0].strip(), "other")
            cats[cat] = cats.get(cat, 0.0) + _mti_num(row[1])
        top = []
        for row in tables.get("Performance/Design Unit", []):
            # <AdvanceTime>, <NoContext>, ...: the kernel, not a design unit
            if len(row) < 5 or row[0].strip().startswith("<"):
                continue
            top.append({"scope": "module", "name": row[0].strip(),
                        "pct": _mti_num(row[3]),
                        "instances": int(_mti_num(row[4]))})
        return make_summary("time", "mti", cats, top)
    if mode == "mem":
        rows = tables.get("Memory/Memory Overview")
        if not rows:
            return None
        cats = {}
        peak = None
        hdl_pct = 0.0
        hdl_split = 0.0
        for row in rows:
            name = row[0].strip()
            pct = _mti_num(row[2]) if len(row) > 2 else 0.0
            depth = _mti_depth(row[0])
            if depth == 0:
                if name == "Peak Process Memory (VSZ)" and len(row) > 1:
                    peak = _mti_num(row[1])
            elif depth == 1:
                if name == "HDL":
                    hdl_pct = pct
                else:
                    cat = _MTI_MEM.get(name, "other")
                    cats[cat] = cats.get(cat, 0.0) + pct
            elif depth == 2:
                cat = _MTI_MEM_HDL.get(name, "hdl")
                cats[cat] = cats.get(cat, 0.0) + pct
                hdl_split += pct
        # What the HDL rows don't break down stays hdl
        if hdl_pct > hdl_split:
            cats["hdl"] = cats.get("hdl", 0.0) + hdl_pct - hdl_split
        top = []
        for row in tables.get("Memory/Design Unit Memory", []):
            # Design-unit rows name their language; library rows say Library
            if len(row) < 5 or row[3] in ("", "Library"):
                continue
            nbytes = int(_mti_num(row[1]) * 1024 * 1024)
            if nbytes > 0:
                top.append({"scope": "module", "name": row[0].strip(),
                            "bytes": nbytes, "instances": int(_mti_num(row[4]))})
        return make_summary("mem", "mti", cats, top, peak)
    return None


#***************************************************************************
#* Verilator: verilator_profcfunc's report on gprof's (`--prof-cfuncs`)
#***************************************************************************

# A function row: % time, cumulative s, self s, calls, design, type, name
_VLT_FUNC_RE = re.compile(
    r'^\s*([\d.]+)\s+[\d.]+\s+[\d.]+\s+\d+\s+\S+\s+'
    r'(VBlock|VCommon|VLib|Prof|C\+\+)\s+(.*?)\s*$')
_VLT_BLOCK_RE = re.compile(r'^(\S+):\d+$')
# Verilated runtime code reported as plain C++
_VLT_SOLVER_RE = re.compile(r'^(?:\S+\s+)?(?:VlRandom|VlSolver)')
_VLT_COV_RE = re.compile(r'^(?:\S+\s+)?VlCover')
_VLT_KERNEL_RE = re.compile(r'^(?:\S+\s+)?(?:Vl|Verilated)')


def parse_vlt_profcfunc(text : str) -> Optional[Dict[str, Any]]:
    """Summary of a ``verilator_profcfunc`` report. Verilog blocks and
    Verilated design code are `hdl`, the Verilated library `kernel`; plain
    C++ is split by name into the randomizer (`solver`), coverage (`cov`),
    the rest of the runtime (`kernel`) and anything else (`other`, which
    includes DPI code and the C++ library). `top` is per source file, as
    Verilator attributes blocks to files, not modules. None when the report
    has no function rows."""
    cats : Dict[str, float] = {}
    files : Dict[str, float] = {}
    seen = False
    for line in (text or "").splitlines():
        m = _VLT_FUNC_RE.match(line)
        if m is None:
            continue
        seen = True
        pct, kind, name = float(m.group(1)), m.group(2), m.group(3)
        if kind == "VBlock":
            cat = "hdl"
            bm = _VLT_BLOCK_RE.match(name)
            if bm is not None:
                files[bm.group(1)] = files.get(bm.group(1), 0.0) + pct
        elif kind == "VCommon":
            cat = "hdl"
        elif kind in ("VLib", "Prof"):
            cat = "kernel"
        elif _VLT_SOLVER_RE.match(name):
            cat = "solver"
        elif _VLT_COV_RE.match(name):
            cat = "cov"
        elif _VLT_KERNEL_RE.match(name):
            cat = "kernel"
        else:
            cat = "other"
        cats[cat] = cats.get(cat, 0.0) + pct
    if not seen:
        return None
    top = [{"scope": "file", "name": f, "pct": round(p, 2)}
           for f, p in files.items() if round(p, 2) > 0]
    return make_summary("time", "vlt", cats, top)
