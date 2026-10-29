#****************************************************************************
#* sim_diag.py
#*
#* Copyright 2023-2026 Matthew Ballance and Contributors
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
"""Simulator runtime diagnostics: assertion failures, `$error`/`$fatal`
reports and tool errors, recognized in a simulation log.

A UVM report summary only counts what went through the UVM report server. An
SVA failure, an HDL `$error` or a simulator error is printed by the simulator
itself, so a run can fail assertions and still end with `UVM_ERROR : 0` (and,
on some simulators, exit 0). The Check tasks feed every log line through a
`DiagScanner` so that evidence is not lost.

Recognized headers (each anchored at line start; there is deliberately no bare
"error"/"failed" substring match):

=========  ============================================================
VCS        ``"f.sv", 31: top.u.A: started at 100ps failed at 100ps``
           (default SVA failure; the ``Offending`` line is continuation)
VCS        ``Error: "f.sv", 31: top.u.A: at time 100 ps`` (and
           ``Fatal:`` / ``Warning:``); message on the following line(s)
VCS        ``Error-[CODE] ...`` / ``Warning-[CODE] ...`` tool messages
Xcelium    ``xmsim: *E,ASRTST (f.sv,33): (time 105 NS) Assertion top.u.A
           has failed``; any ``<tool>: *E,<CODE>`` / ``*F,<CODE>`` /
           ``*W,<CODE>`` for xmsim, xmvlog, xmelab, xmvhdl, xrun (and the
           older nc* / irun names); location ``(path,line)`` or
           ``(path,line|col)``
Verilator  ``[15] %Error: f.sv:2: Assertion failed in top.u.A: msg``,
           ``%Fatal: ...``, ``%Warning: ...``
Icarus     ``ERROR: f.sv:3: msg`` / ``FATAL:`` / ``WARNING:``, with a
           ``Time: 1  Scope: top`` continuation
Questa     ``# ** Error: msg`` / ``** Fatal:`` / ``** Warning:``, with a
           ``Time: 2 ns  Scope: top File: f.sv Line: 6`` continuation
=========  ============================================================

Each recognized message becomes one `Diag` (severity, category, code,
location, hierarchy, time, message). `category` is ``assertion`` (an
assertion failure), ``check`` (an HDL severity task such as `$error`) or
``tool`` (a simulator-reported error). A VCS SVA failure and the `$error`
action it runs are one event when their hierarchy and time agree.

Verilator and Icarus report an assertion's action and a plain `$error` the
same way, so on those simulators the split between ``assertion`` and
``check`` is what the simulator itself says.

Like `uvm_log_parser`, this module imports no dv-flow machinery.
"""

import dataclasses as dc
import re
from typing import Any, Callable, Dict, List, Optional, Tuple

SEVERITIES = ("error", "fatal", "warning")
CATEGORIES = ("assertion", "check", "tool")

# Most continuation lines to attach to a diagnostic, and the most diagnostics
# a scanner keeps as a sample. Counts are exact; only the sample is bounded.
CONT_MAX = 3
SAMPLE_MAX = 10
MSG_MAX = 240


@dc.dataclass
class Diag(object):
    severity : str                  # error | fatal | warning
    category : str                  # assertion | check | tool
    code : str = ""
    file : str = ""
    line : int = -1
    hier : str = ""
    time : str = ""                 # as printed
    time_fs : Optional[int] = None  # normalized, for comparison
    message : str = ""
    log_line : int = 0              # 1-based line in the log
    fmt : str = ""                  # which header recognized it

    def to_dict(self) -> Dict[str, Any]:
        d = {"severity": self.severity, "category": self.category,
             "message": self.message, "log_line": self.log_line}
        for k in ("code", "file", "hier", "time"):
            v = getattr(self, k)
            if v:
                d[k] = v
        if self.line >= 0:
            d["line"] = self.line
        return d

    def summary(self) -> str:
        """One line for a console or report message."""
        loc = ("%s:%d" % (self.file, self.line)) if self.file and self.line >= 0 \
            else self.file
        parts = [self.severity]
        if self.code:
            parts.append(self.code)
        head = "[%s]" % ",".join(parts)
        what = self.hier or loc
        text = " ".join(p for p in (head, what, self.message) if p)
        if self.time:
            text += " @ %s" % self.time
        if loc and self.hier:
            text += " (%s)" % loc
        return text


#---------------------------------------------------------------------------
# Time normalization
#---------------------------------------------------------------------------

_FS = {"s": 10**15, "ms": 10**12, "us": 10**9, "ns": 10**6, "ps": 10**3, "fs": 1}
_TIME_RE = re.compile(r'^\s*([0-9]*\.?[0-9]+)\s*([munpf]?s)\s*$', re.I)


def time_fs(text : str) -> Optional[int]:
    """'105000ps', '105000 ps', '105 NS' -> femtoseconds; None if unitless or
    unparseable (a bare number has no unit to compare on)."""
    m = _TIME_RE.match(text or "")
    if m is None:
        return None
    return int(round(float(m.group(1)) * _FS[m.group(2).lower()]))


#---------------------------------------------------------------------------
# Headers
#---------------------------------------------------------------------------

# Cheap reject: the first characters every header can start with. Most lines
# of a large log (UVM_INFO, $display output) fail this and cost one match.
_PREFILTER = re.compile(
    r'^(?:#\s*)?(?:"|Error|Fatal|Warning|Lint-|ERROR|FATAL|WARNING|%|\[|\*\*'
    r'|xm|nc|xrun|irun)')

_VCS_SVA = re.compile(
    r'^"(?P<file>[^"]+)", (?P<line>\d+): (?P<hier>\S+): '
    r'started at (?P<start>\S+(?: ?[munpf]?s)?) failed at (?P<time>\d+(?:\.\d+)? ?[munpf]?s)\b')
_VCS_SEV = re.compile(
    r'^(?P<sev>Error|Fatal|Warning): "(?P<file>[^"]+)", (?P<line>\d+): '
    r'(?P<hier>\S+?):? at time (?P<time>\d+(?:\.\d+)? ?[munpf]?s)\b\s*(?P<msg>.*)$')
_VCS_TOOL = re.compile(r'^(?P<sev>Error|Warning|Lint)-\[(?P<code>[^\]]+)\]\s*(?P<msg>.*)$')
_VCS_LOC = re.compile(r'^(?P<file>\S+), (?P<line>\d+)\s*$')
# VCS Error-[SE] location: '"<path>", <line>: token is '<tok>'', where the
# line number may start the next line
_VCS_SE_LOC = re.compile(r'"([^"]+)",\s*(\d+):\s*token is (\'[^\']*\')')
# Continuation lines kept for an Error-[SE] body
VCS_SE_MAX = 16

_XCM = re.compile(
    r'^(?P<tool>xm(?:sim|vlog|elab|vhdl)|nc(?:sim|vlog|elab|vhdl)|xrun|irun)'
    r'(?:\(64\))?: \*(?P<sev>[EFW]),(?P<code>\w+)'
    r'(?: \((?P<file>[^,()]+),(?P<line>\d+)(?:\|\d+)?\))?:?\s*(?P<msg>.*)$')
_XCM_TIME = re.compile(r'\(time (?P<time>\d+(?:\.\d+)? ?[A-Za-z]+)\)\.?')
_XCM_ASRT = re.compile(r'Assertion (?P<hier>\S+) has failed')

_VLT = re.compile(
    r'^(?:\[(?P<time>[^\]]+)\]\s+)?%(?P<sev>Error|Fatal|Warning)(?:-(?P<code>\w+))?:'
    r'\s*(?P<rest>.*)$')
_VLT_LOC = re.compile(r'^(?P<file>[^:\s]+):(?P<line>\d+):(?:\d+:)?\s*(?P<rest>.*)$')
_VLT_ASRT = re.compile(r'^Assertion failed in (?P<hier>\S+?):\s*(?P<msg>.*)$')

_IVL = re.compile(
    r'^(?P<sev>ERROR|FATAL|WARNING): (?P<file>[^:\s\[]+):(?P<line>\d+):\s*(?P<msg>.*)$')
_IVL_CONT = re.compile(r'^\s+Time: (?P<time>\S+)\s+Scope: (?P<hier>\S+)')

_MTI = re.compile(
    r'^(?:#\s*)?\*\* (?P<sev>Error|Fatal|Warning)(?: \(suppressible\))?:'
    r'\s*(?:\((?P<code>[\w-]+)\)\s*)?(?P<msg>.*)$')
_MTI_CONT = re.compile(
    r'^(?:#\s*)?\s+Time: (?P<time>\d+(?:\.\d+)? ?[munpf]?s)'
    r'(?:\s+Started: \d+(?:\.\d+)? ?[munpf]?s)?'
    r'(?:\s+Iteration: \d+)?(?:\s+(?:Process|Instance): \S+)?'
    r'(?:\s+Scope: (?P<hier>\S+))?'
    r'(?:\s+File: (?P<file>\S+))?(?:\s+Line: (?P<line>\d+))?')

# A continuation never starts with one of these: they begin the next record
# (a UVM report, the summary, the simulator's own end-of-run lines).
_CONT_STOP = re.compile(
    r'^(?:(?:#\s*)?(?:UVM_|---|\*\* Report|\$finish|\$stop|- |V C S|xm\w+:|nc\w+:'
    r'|Simulation complete)|Time:\s+\d)')

_SEV = {"E": "error", "F": "fatal", "W": "warning",
        "Error": "error", "Fatal": "fatal", "Warning": "warning",
        "ERROR": "error", "FATAL": "fatal", "WARNING": "warning"}

# Xcelium codes for the HDL severity tasks ($error, $fatal, $warning, $info)
_XCM_CHECK_CODES = ("ERRSEV", "FATSEV", "WARSEV")


def _int(s) -> int:
    try:
        return int(s)
    except (TypeError, ValueError):
        return -1


def _clip(s : str) -> str:
    s = s.strip()
    return s if len(s) <= MSG_MAX else s[:MSG_MAX - 3] + "..."


def vcs_se(lines : List[str]) -> Tuple[str, int, str]:
    """(file, line, message) of a VCS Error-[SE] from its stripped body lines;
    file is "" and line -1 when no location is found. Shared by `DiagScanner`
    and `LogParser` so the two agree.

    Body:
      Following verilog source has syntax error :
      [<explanation>]
      "<path>", <line>: token is '<tok>'   (or '"<path>",' / '<line>: ...')
      [<echoed source line>]
      [<caret line>]
      [<explanation>]"""
    lines = [s for s in lines
             if not s.startswith("Following verilog source has syntax error")]
    file, line, token = "", -1, ""
    loc_end = -1
    for i in range(len(lines)):
        # Join with the next line to accept the split location
        m = _VCS_SE_LOC.search(" ".join(lines[i:i+2]))
        if m is not None and lines[i].startswith('"'):
            file, line, token = m.group(1), int(m.group(2)), m.group(3)
            loc_end = i if "token is" in lines[i] else i+1
            break
    if loc_end != -1:
        # The line after the location echoes the source
        explain = lines[:i] + lines[loc_end+2:]
    else:
        explain = lines
    explain = [s for s in explain if s.strip("^ ") != ""]
    msg = "Syntax error"
    if token != "":
        msg += ": token is %s" % token
    if len(explain) > 0:
        msg += " " + " ".join(explain)
    return file, line, msg


def match_header(l : str) -> Optional[Diag]:
    """The `Diag` a log line starts, or None. Continuation lines are not
    headers; `DiagScanner` attaches them."""
    if not _PREFILTER.match(l):
        return None

    m = _VCS_SVA.match(l)
    if m:
        return Diag("error", "assertion", file=m.group("file"),
                    line=_int(m.group("line")), hier=m.group("hier"),
                    time=m.group("time"), time_fs=time_fs(m.group("time")),
                    fmt="vcs-sva")
    m = _VCS_SEV.match(l)
    if m:
        return Diag(_SEV[m.group("sev")], "check", file=m.group("file"),
                    line=_int(m.group("line")), hier=m.group("hier"),
                    time=m.group("time"), time_fs=time_fs(m.group("time")),
                    message=_clip(m.group("msg")), fmt="vcs-sev")
    m = _VCS_TOOL.match(l)
    if m:
        if m.group("sev") == "Lint":
            # Lint-[CODE]: a warning; the next line holds 'path, line'
            return Diag("warning", "tool", code=m.group("code"),
                        message=_clip(m.group("msg")), fmt="vcs-lint")
        return Diag(_SEV[m.group("sev")], "tool", code=m.group("code"),
                    message=_clip(m.group("msg")), fmt="vcs-tool")

    m = _XCM.match(l)
    if m:
        code = m.group("code")
        msg = m.group("msg")
        d = Diag(_SEV[m.group("sev")], "tool", code=code,
                 file=m.group("file") or "", line=_int(m.group("line")),
                 fmt="xcm")
        t = _XCM_TIME.search(msg)
        if t:
            d.time = t.group("time")
            d.time_fs = time_fs(d.time)
            msg = (msg[:t.start()] + msg[t.end():]).strip()
        a = _XCM_ASRT.search(msg)
        if code == "ASRTST" or a:
            d.category = "assertion"
            if a:
                d.hier = a.group("hier")
        elif code in _XCM_CHECK_CODES:
            d.category = "check"
        d.message = _clip(msg)
        return d

    m = _VLT.match(l)
    if m:
        d = Diag(_SEV[m.group("sev")], "tool", code=m.group("code") or "",
                 fmt="vlt")
        if m.group("time"):
            d.time = m.group("time")
            d.time_fs = time_fs(d.time)
        rest = m.group("rest")
        loc = _VLT_LOC.match(rest)
        if loc:
            d.file, d.line, rest = loc.group("file"), _int(loc.group("line")), loc.group("rest")
        if rest.startswith("Verilog $stop"):
            # The consequence of the error before it (or a plain $stop); the
            # process status already carries it.
            return None
        a = _VLT_ASRT.match(rest)
        if a:
            d.category = "assertion"
            d.hier = a.group("hier")
            rest = a.group("msg")
        elif d.time:
            # A runtime %Warning from $warning: '<scope>: <msg>'
            sc = rest.split(": ", 1)
            if len(sc) == 2 and " " not in sc[0]:
                d.category, d.hier, rest = "check", sc[0], sc[1]
        d.message = _clip(rest)
        return d

    m = _IVL.match(l)
    if m:
        return Diag(_SEV[m.group("sev")], "check", file=m.group("file"),
                    line=_int(m.group("line")), message=_clip(m.group("msg")),
                    fmt="ivl")

    m = _MTI.match(l)
    if m:
        msg = m.group("msg")
        cat = "assertion" if msg.startswith("Assertion error") else \
            ("tool" if m.group("code") else "check")
        return Diag(_SEV[m.group("sev")], cat, code=m.group("code") or "",
                    message=_clip(msg), fmt="mti")

    return None


#---------------------------------------------------------------------------
# Scanner
#---------------------------------------------------------------------------

@dc.dataclass
class DiagScanner(object):
    """Feed it a log one line at a time; it groups continuation lines, merges
    a VCS assertion with its `$error` action, and keeps exact counts plus a
    bounded sample. Call `close()` at EOF to flush the last diagnostic.

    `notify`, when set, is called once per completed event."""
    notify : Optional[Callable[[Diag], None]] = None
    sample_max : int = SAMPLE_MAX
    errors : int = 0
    fatals : int = 0
    warnings : int = 0
    lint : int = 0              # VCS Lint-[CODE] warnings (not in `warnings`)
    assertions : int = 0
    tool_failures : int = 0     # errors/fatals the simulator raised itself
    hdl_fatals : int = 0        # $fatal / fatal assertions (not tool)
    sample : List[Diag] = dc.field(default_factory=list)
    _pending : Optional[Diag] = None
    _cont : int = 0
    _held : Optional[Diag] = None   # a VCS assertion awaiting its $error action
    _se : List[str] = dc.field(default_factory=list)  # body of a VCS Error-[SE]
    _lineno : int = 0

    def line(self, l : str):
        self._lineno += 1
        l = l.rstrip("\r\n")
        d = match_header(l)
        if d is not None:
            d.log_line = self._lineno
            self._flush()
            h = self._held
            self._held = None
            if h is not None and self._merges(h, d):
                # The $error action of the assertion just reported: one event.
                # Keep the assertion's location; take the action's message.
                h.fmt = "vcs-sva+action"
                h.message = d.message
                self._pending = h
                self._cont = 0
                return
            if h is not None:
                self._commit(h)
            self._pending = d
            self._cont = 0
            return

        p = self._pending
        if p is not None and not self._accepts(p, l):
            self._flush()
            p = None
        if p is None:
            if self._held is not None and l.strip() != "":
                # Something else came between: the action isn't adjacent.
                self._commit(self._held)
                self._held = None
            return
        self._cont += 1
        self._continue(p, l)

    def close(self):
        self._flush()
        if self._held is not None:
            self._commit(self._held)
            self._held = None

    @property
    def failed(self) -> bool:
        return (self.errors + self.fatals) > 0

    def first(self) -> Optional[Diag]:
        return self.sample[0] if self.sample else None

    #-----------------------------------------------------------------------

    @staticmethod
    def _merges(h : Diag, d : Diag) -> bool:
        return (d.fmt == "vcs-sev" and d.severity in ("error", "fatal")
                and h.hier == d.hier
                and h.time_fs is not None and h.time_fs == d.time_fs)

    def _accepts(self, p : Diag, l : str) -> bool:
        """Whether `l` continues the pending diagnostic. Each format says what
        its continuation looks like; a line that isn't one ends the record."""
        if self._is_se(p):
            # The syntax-error body is longer; it ends at a blank line
            return l.strip() != "" and self._cont < VCS_SE_MAX
        if l.strip() == "" or self._cont >= CONT_MAX or _CONT_STOP.match(l):
            return False
        if p.fmt == "vlt":
            return False                          # always one line
        if p.fmt == "ivl":
            return _IVL_CONT.match(l) is not None
        if p.fmt == "mti":
            return _MTI_CONT.match(l) is not None
        if p.fmt == "vcs-sva":
            return l[:1] in (" ", "\t")            # the indented 'Offending'
        return True                               # vcs-sev, vcs-tool, vcs-lint, xcm

    @staticmethod
    def _is_se(p : Diag) -> bool:
        return p.fmt == "vcs-tool" and p.code == "SE"

    def _continue(self, p : Diag, l : str):
        if self._is_se(p):
            self._se.append(l.strip())
            return
        if p.fmt == "ivl":
            m = _IVL_CONT.match(l)
            if m:
                p.time, p.hier = m.group("time"), m.group("hier")
                return
        elif p.fmt == "mti":
            m = _MTI_CONT.match(l)
            if m:
                p.time = m.group("time")
                p.time_fs = time_fs(p.time)
                p.hier = m.group("hier") or p.hier
                p.file = m.group("file") or p.file
                if m.group("line"):
                    p.line = _int(m.group("line"))
                return
        elif p.fmt == "xcm" and p.category == "check" and not p.hier and self._cont == 1:
            # ERRSEV/FATSEV: the scope, then the message
            p.hier = l.strip()
            return
        elif p.fmt == "vcs-lint" and self._cont == 1:
            m = _VCS_LOC.match(l.strip())
            if m:
                p.file, p.line = m.group("file"), _int(m.group("line"))
                return
        elif p.fmt == "vcs-sva" and l.lstrip().startswith("Offending"):
            if not p.message:
                p.message = _clip(l)
            return

        text = l.strip()
        if text.startswith("#"):
            text = text[1:].strip()
        if text:
            p.message = _clip(text if not p.message else "%s %s" % (p.message, text))

    def _flush(self):
        p = self._pending
        if p is None:
            return
        self._pending = None
        self._cont = 0
        if self._is_se(p):
            file, line, msg = vcs_se(self._se)
            if file:
                p.file, p.line = file, line
            p.message = _clip(msg)
        self._se = []
        if p.fmt == "vcs-sva":
            self._held = p
        else:
            self._commit(p)

    def _commit(self, p : Diag):
        if p.severity == "warning":
            if p.fmt == "vcs-lint":
                self.lint += 1
            else:
                self.warnings += 1
        else:
            if p.severity == "fatal":
                self.fatals += 1
            else:
                self.errors += 1
            if p.category == "assertion":
                self.assertions += 1
            if p.category == "tool":
                self.tool_failures += 1
            elif p.severity == "fatal":
                self.hdl_fatals += 1
            if len(self.sample) < self.sample_max:
                self.sample.append(p)
        if self.notify is not None:
            self.notify(p)


def scan_lines(lines, sample_max : int = SAMPLE_MAX) -> DiagScanner:
    s = DiagScanner(sample_max=sample_max)
    for l in lines:
        s.line(l)
    s.close()
    return s
