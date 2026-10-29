#****************************************************************************
#* log_parser.py
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
#* Created on:
#*     Author: 
#*
#****************************************************************************
import os
import re
import dataclasses as dc
import enum
import logging
from typing import Callable, ClassVar, List, Optional, Union
from dv_flow.mgr.task_data import TaskMarker, TaskMarkerLoc, SeverityE
from dv_flow.libhdlsim import sim_diag

def resolve_lint_as_error(value) -> Union[bool, List[str]]:
    """Normalize the `lint_as_error` task param.

    Returns True (escalate all lint), or a list of lint codes to escalate.
    A bool is kept; "all" or "*" in the list means all codes.
    """
    if value is None or value is False:
        return []
    if value is True:
        return True
    codes = []
    for elem in ([value] if isinstance(value, str) else value):
        codes.extend(str(elem).replace(",", " ").split())
    if any(c.lower() in ("all", "*", "true") for c in codes):
        return True
    return codes

class ParseState(enum.Enum):
    Init = enum.auto()
    MultiLineStyle1 = enum.auto()

@dc.dataclass
class LogParser(object):
    notify : Optional[Callable[[TaskMarker], None]] = dc.field(default=None)
    suppress : List[str] = dc.field(default_factory=list)
    # Escalate VCS Lint- messages to errors: True for all, or a list of codes
    lint_as_error : Union[bool, List[str]] = dc.field(default=False)
    _state : ParseState = dc.field(default=ParseState.Init)
    _message : str = dc.field(default="")
    _kind : Optional[SeverityE] = dc.field(default=None)
    _code : str = dc.field(default="")
    _lint : bool = dc.field(default=False)
    _path : str = dc.field(default="")
    _log : ClassVar = logging.getLogger("LogParser")
    _tmp : str = dc.field(default="")
    # Stripped continuation lines of the current VCS message
    _lines : List[str] = dc.field(default_factory=list)
    _count : int = 0

    # VCS Error-[SE] location: '"<path>", <line>: token is '<tok>'', where
    # the line number may start the next line
    _se_loc_re : ClassVar = re.compile(r'"([^"]+)",\s*(\d+):\s*token is (\'[^\']*\')')

    def line(self, l):
        try:
            self._line(l)
        except Exception as e:
            self._log.error("Error parsing line: %s" % l)
            self._log.exception(e)

            # Reset so we get a clean try
            self._state = ParseState.Init
            self._message = ""
            self._kind = None
            self._path = ""
            self._lint = False
            self._tmp = ""
            self._lines = []

    def close(self):
        # Process an empty lines to flush any accumulated messages
        self._line("")

    def _line(self, l):
        self._log.debug("line: %s" % l)
        if self._state == ParseState.Init:
            if l.startswith("Error-") or l.startswith("Warning-") or l.startswith("Lint-"):
                # VCS-style message:
                # <Kind>-[<Code>] <Short Desc>  (Kind: Error, Warning, Lint)
                # <Path>
                #   <Indented Description Lines>
                #   ...
                # 1-2 Blank line delimiter 
                #
                l = l.strip()
                # Each message starts fresh: nothing carries over from the last
                self._tmp = ""
                self._lines = []
                self._path = ""
                self._message = ""
                self._code = ""
                # Lint- messages are reported as warnings
                self._kind = SeverityE.Error if l.startswith("Error") else SeverityE.Warning
                self._lint = l.startswith("Lint-")

                # Extract code from [CODE] bracket
                ob = l.find("[")
                cb = l.find("]", ob) if ob != -1 else -1
                if ob != -1 and cb != -1:
                    self._code = l[ob+1:cb]

                if l.find("Syntax error") == -1:
                    self._tmp = l

                self._count = 0
                self._state = ParseState.MultiLineStyle1
            elif l.startswith("%Error") or l.startswith("%Warning"):
                # Verilator-style message:
                # %<Kind>-<Code>: <Path>:<Line>:<Pos>: <Short Desc>
                # %Kind: <Path>|<verilator>: <Short Desc>
                # %Kind: <Short Desc>
                #   <Indented Description Lines> (Ignore)
                self._log.debug("Verilator-style message")
                self._kind = SeverityE.Warning if l.startswith("%Warning") else SeverityE.Error
                c1_idx = l.find(":")
                # Extract code from between '-' and ':' (e.g. %Warning-PINCONNECTS:)
                dash_idx = l.find("-")
                if 0 < dash_idx < c1_idx:
                    self._code = l[dash_idx+1:c1_idx]
                s2_idx = l.find(" ", c1_idx+2)
                self._log.debug("c1_idx=%d s2_idx=%d" % (c1_idx, s2_idx))
                if s2_idx != -1 and l[s2_idx-1] == ':':
                    # s2 is after the path
                    path_or_exe = l[c1_idx+1:s2_idx-1].strip()
                    self._log.debug("path_or_exe: %s" % path_or_exe)

                    c2_idx = l.find(":")

                    if c2_idx != -1:
                        # Have a location specification
                        self._path = path_or_exe
                    self._message = l[s2_idx:].strip()
                else:
                    self._message = l[c1_idx+1:].strip()

                self.emit_marker()
            elif l.startswith("** Error") or l.startswith("** Warning"):
                # Questa-style message:
                # ** <Kind>: (<Code>) <Path>(<Line>): <Short Desc>
                # ** <Kind> (suppressible): <Path>(<Line>): (<Code>) <Short Desc>
                self._kind = SeverityE.Warning if l.startswith("** Warning") else SeverityE.Error
                c1_idx = l.find(":")
                if l[c1_idx-1] == ")":
                    # Style-2 message
                    # ** <Kind> (suppressible): <Path>(<Line>): (<Code>) <Short Desc>
                    c2_idx = l.find(":", c1_idx+1)
                    path = l[c1_idx+1:c2_idx].strip()
                    p1_idx = path.find("(")
                    line = path[p1_idx+1:-1]
                    self._path = "%s:%s" % (path[:p1_idx].strip(), line)
                    # Extract code from (CODE) after second colon
                    code_open = l.find('(', c2_idx+1)
                    code_close = l.find(')', code_open+1) if code_open != -1 else -1
                    if code_open != -1 and code_close != -1:
                        self._code = l[code_open+1:code_close]
                    c3_idx = code_close if code_close != -1 else c2_idx
                    self._message = l[c3_idx+1:].strip()
                else:
                    # Style-1 message
                    # ** <Kind>: [(<Code>)] <Path>(<Line>): <Short Desc>
                    if l[c1_idx+2] == '(':
                        # Optional code is present
                        p2_idx = l.find(")", c1_idx+2) # End of (<Code>)
                        self._code = l[c1_idx+3:p2_idx]
                        self._log.debug("Extracted code: %s" % self._code)
                    else:
                        p2_idx = c1_idx+1
                        self._log.debug("No optional code")
                    c2_idx = l.find(":", p2_idx)

                    if c2_idx == -1:
                        # Header-only line (eg include-chain prefix). Defer to '** at ' continuation.
                        return

                    path = l[p2_idx+1:c2_idx].strip()
                    p3_idx = path.find("(")
                    line = path[p3_idx+1:-1]
                    self._path = "%s:%s" % (path[:p3_idx].strip(), line)
                    self._message = l[c2_idx+1:].strip()
                self.emit_marker()
            elif l.startswith("** at "):
                # Questa include-chain continuation line with actual location and message
                self._log.debug("Questa-style 'at' continuation")
                # Default to Error if prior kind not set
                self._kind = self._kind if self._kind is not None else SeverityE.Error
                s = l[len("** at "):].strip()
                c_idx = s.find(":")
                if c_idx != -1:
                    path_part = s[:c_idx].strip()
                    msg_part = s[c_idx+1:].strip()
                    # Extract and strip leading (vlog-XXXX) code
                    if msg_part.startswith("("):
                        rpar = msg_part.find(")")
                        if rpar != -1:
                            self._code = msg_part[1:rpar]
                            msg_part = msg_part[rpar+1:].strip()
                    # Parse path(line[:pos])
                    p_open = path_part.rfind("(")
                    p_close = path_part.rfind(")")
                    line = -1
                    pos = -1
                    if p_open != -1 and p_close == len(path_part)-1:
                        linepos = path_part[p_open+1:p_close]
                        if "," in linepos:
                            a, b = [t.strip() for t in linepos.split(",", 1)]
                            try:
                                line = int(a)
                                pos = int(b)
                            except Exception:
                                pass
                        elif ":" in linepos:
                            a, b = [t.strip() for t in linepos.split(":", 1)]
                            try:
                                line = int(a)
                                pos = int(b)
                            except Exception:
                                pass
                        else:
                            try:
                                line = int(linepos)
                            except Exception:
                                pass
                        path0 = path_part[:p_open].strip()
                        self._path = f"{path0}:{line}" if line != -1 else path0
                    else:
                        self._path = path_part
                    self._message = msg_part
                    self.emit_marker()
            elif l.startswith("ERROR:") or l.startswith("WARNING:"):
                self._kind = SeverityE.Warning if l.startswith("WARNING:") else SeverityE.Error
                last_open = l.rfind('[')
                first_colon = l.find(':')

                if last_open != -1 and first_colon != -1:
                    self._message = l[first_colon+1:last_open].strip()
                    self._path = l[last_open+1:].strip()
                    if self._path.endswith(']'):
                        # Remove trailing ']'
                        self._path = self._path[:-1].strip()
                    # Extract code from [CODE] at end of line
                    last_close = l.rfind(']')
                    if last_open != -1 and last_close != -1:
                        self._code = l[last_open+1:last_close].strip()
                    self.emit_marker()
            else:
                # Formats recognized by the runtime scanner (sim_diag) and not
                # above -- Xcelium's '<tool>: *E,<CODE> (path,line): msg' --
                # come from its table, so the two cannot drift apart.
                d = sim_diag.match_header(l.rstrip("\r\n"))
                if d is not None and d.fmt == "xcm":
                    self._kind = SeverityE.Warning if d.severity == "warning" else SeverityE.Error
                    self._code = d.code
                    if d.file:
                        self._path = "%s:%d" % (d.file, d.line) if d.line >= 0 else d.file
                    self._message = d.message
                    self.emit_marker()
        elif self._state == ParseState.MultiLineStyle1:
            # VCS-style message:
            # <Kind>-<Code> <Short Desc>
            # <Path>
            #   <Indented Description Lines>

            self._count += 1

            if (self._code == "SE" and l.strip() != "" and self._count <= 16
                    and not l.startswith(("Error-", "Warning-", "Lint-"))):
                # Syntax error: location and text come from the whole body
                self._lines.append(l.strip())
            elif self._count == 1:
                # First line after the title. If a file path is provided,
                # then it should be here
                c_idx = l.find(",")
                if c_idx != -1:
                    # May have a path
                    path = l[:c_idx].strip()
                    # Unindented '<file>, <line>' is a location even when the
                    # file is relative and absent here (eg 'top.sv, 2')
                    rel_loc = (l[:1] not in (" ", "\t") and path != ""
                               and " " not in path
                               and l[c_idx+1:].strip().isdigit())
                    if rel_loc or os.path.exists(path) or path.find("/") != -1:
                        self._path = "%s:%s" % (path, l[c_idx+1:].strip())
                if self._path == "":
                    # No path
                    self._tmp += (" " + l.strip())
            elif (l.strip() == "" or self._count > 16
                    or l.startswith(("Error-", "Warning-", "Lint-"))
                    or (self._lint and self._count > 1
                        and l[:1] not in (" ", "\t"))):
                # End: blank line, too long, the next message's header, or
                # (Lint- only) an unindented plain line. Error-/Warning-
                # descriptions may have unindented continuation lines.
                reparse = l.strip() != "" and self._count <= 16
                line = self._tmp.strip()
                sq_idx = line.find("]")
                if sq_idx != -1:
                    self._message = line[sq_idx+1:].strip()
                else:
                    self._message = line
                if self._code == "SE":
                    self._se_message()

                self.emit_marker()
                self._tmp = ""
                self._lines = []
                self._state = ParseState.Init
                self._count = 0
                if reparse:
                    self._line(l)
            else:
                # Continue adding to the accumulated message
                self._tmp += (" " + l.strip())
        pass

    def _se_message(self):
        # VCS syntax error body:
        #   Following verilog source has syntax error :
        #   [<explanation>]
        #   "<path>", <line>: token is '<tok>'   (or '"<path>",' / '<line>: ...')
        #   [<echoed source line>]
        #   [<caret line>]
        #   [<explanation>]
        lines = [s for s in self._lines
                 if not s.startswith("Following verilog source has syntax error")]
        token = ""
        loc_end = -1
        for i in range(len(lines)):
            # Join with the next line to accept the split location
            m = self._se_loc_re.search(" ".join(lines[i:i+2]))
            if m is not None and lines[i].startswith('"'):
                self._path = "%s:%s" % (m.group(1), m.group(2))
                token = m.group(3)
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
        self._message = msg

    def emit_marker(self):
        loc : Optional[TaskMarkerLoc] = None
        
        if self._path != "":
            elems = self._path.split(":")
            self._log.debug("Path elems: %s (%d)" % (elems, len(elems)))
            line=-1
            pos=-1
            if len(elems) > 1:
                self._log.debug("elems[1]: %s" % elems[1])
                try:
                    line = int(elems[1])
                except Exception as e:
                    pass
            if len(elems) > 2:
                try:
                    pos = int(elems[2])
                except Exception as e:
                    pass
            loc = TaskMarkerLoc(path=elems[0], line=line, pos=pos)

        sev = self._kind if self._kind is not None else SeverityE.Error

        # Suppress warnings (not errors) whose code is in the suppress list
        code = self._code
        if code and sev == SeverityE.Warning and code in self.suppress:
            self._code = ""
            self._lint = False
            self._kind = None
            self._message = ""
            self._path = ""
            return

        # Opt-in escalation of lint messages (applied after suppression)
        if self._lint and sev == SeverityE.Warning:
            lae = self.lint_as_error
            if lae is True or (isinstance(lae, (list, tuple, set)) and code in lae):
                sev = SeverityE.Error

        # Prepend [CODE] to message so users can identify the code to suppress
        msg = ("[%s] %s" % (code, self._message)).strip() if code else self._message
        self._log.debug("Message: %s" % msg)

        if loc is not None:
            marker = TaskMarker(
                severity=sev,
                msg=msg,
                loc=loc)
        else:
            marker = TaskMarker(
                severity=sev,
                msg=msg)

        self._code = ""
        self._lint = False
        self._kind = None
        self._message = ""
        self._path = ""
        if self.notify is not None:
            self.notify(marker)

    pass
