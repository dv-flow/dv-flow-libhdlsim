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
import dataclasses as dc
import enum
import logging
from typing import Callable, ClassVar
from dv_flow.mgr.task_data import TaskMarker, TaskMarkerLoc

class ParseState(enum.Enum):
    Init = enum.auto()
    MultiLineStyle1 = enum.auto()

@dc.dataclass
class LogParser(object):
    notify : Callable = dc.field(default=None)
    _state : ParseState = dc.field(default=ParseState.Init)
    _message : str = dc.field(default="")
    _kind : str = dc.field(default="")
    _path : str = dc.field(default="")
    _log : ClassVar = logging.getLogger("LogParser")
    _tmp : str = dc.field(default="")
    _count : int = 0

    def line(self, l):
        try:
            self._line(l)
        except Exception as e:
            self._log.error("Error parsing line: %s" % l)
            self._log.exception(e)

            # Reset so we get a clean try
            self._state = ParseState.Init
            self._message = ""
            self._kind = ""
            self._path = ""

    def close(self):
        # Process an empty lines to flush any accumulated messages
        self._line("")

    def _line(self, l):
        self._log.debug("line: %s" % l)
        if self._state == ParseState.Init:
            if l.startswith("Error-") or l.startswith("Warning-"):
                # VCS-style message:
                # <Kind>-[<Code>] <Short Desc>
                # <Path>
                #   <Indented Description Lines>
                #   ...
                # 1-2 Blank line delimiter 
                #
                self._tmp = l.strip()
                self._count = 0
                self._state = ParseState.MultiLineStyle1
            elif l.startswith("%Error") or l.startswith("%Warning"):
                # Verilator-style message:
                # %<Kind>-<Code>: <Path>:<Line>:<Pos>: <Short Desc>
                # %Kind: <Path>|<verilator>: <Short Desc>
                # %Kind: <Short Desc>
                #   <Indented Description Lines> (Ignore)
                self._log.debug("Verilator-style message")
                self._kind = "warning" if l.startswith("%Warning") else "error"
                c1_idx = l.find(":")
                s2_idx = l.find(" ", c1_idx+2)
                if s2_idx == -1 and l[s2_idx-1] == ':':
                    # s2 is after the path (if present)
                    path_or_exe = l[c1_idx+1:s2_idx-1].strip()
                    self._log.debug("path_or_exe: %s" % path_or_exe)
                    c2_idx = path_or_exe.find(":")

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
                self._kind = "warning" if l.startswith("** Warning") else "error"
                c1_idx = l.find(":")
                if l[c1_idx-1] == ")":
                    # Style-2 message
                    # ** <Kind> (suppressible): <Path>(<Line>): (<Code>) <Short Desc>
                    c2_idx = l.find(":", c1_idx+1)
                    path = l[c1_idx+1:c2_idx].strip()
                    p1_idx = path.find("(")
                    line = path[p1_idx+1:-1]
                    self._path = "%s:%s" % (path[:p1_idx].strip(), line)
                    c3_idx = l.find(')', c2_idx+1)
                    self._message = l[c3_idx+1:].strip()
                else:
                    # Style-1 message
                    # ** <Kind>: [(<Code>)] <Path>(<Line>): <Short Desc>
                    if l[c1_idx+2] == '(':
                        # Optional code is present
                        p2_idx = l.find(")", c1_idx+2) # End of (<Code>)
                        self._log.debug("Skipping optional code")
                    else:
                        p2_idx = c1_idx+1
                        self._log.debug("No optional code")
                    c2_idx = l.find(":", p2_idx)

                    path = l[p2_idx+1:c2_idx].strip()
                    p3_idx = path.find("(")
                    line = path[p3_idx+1:-1]
                    self._path = "%s:%s" % (path[:p3_idx].strip(), line)
                    self._message = l[c2_idx+1:].strip()
                self.emit_marker()

            else:
                # Ignore
                pass
        elif self._state == ParseState.MultiLineStyle1:
            # VCS-style message:
            # <Kind>-<Code> <Short Desc>
            # <Path>
            #   <Indented Description Lines>

            self._count += 1
            if l.strip() == "" or self._count > 16:
                line = self._tmp.strip()
                self._kind = "warning" if line.startswith("Warning") else "error"
                if "-[SE]" in line:
                    # Syntax error
                    se_idx = line.find("Syntax error")
                    co_idx = line.find(':', se_idx) # First part is generic
                    qu_idx = line.find('"', se_idx)
                    qe_idx = line.find('"', qu_idx+1)
                    cm_idx = line.find(',', qe_idx)
                    ce_idx = line.find(':', cm_idx)
                    self._message = line[co_idx+1:qu_idx].strip()
                    self._path = line[qu_idx+1:qe_idx].strip()
                    self._path += (":" + line[cm_idx+1:ce_idx].strip())
                elif "-NS" in line:
                    # Name space error
                    sb_idx = line.find(']')
                    self._message = line[sb_idx:].strip()
                else:
                    # Semantic error
                    # First, find comma
                    ls_idx = line.find(' ')
                    co_idx = line.find(',')
                    sp_idx = line.rfind(" ", 0, co_idx)
                    ns_idx = line.find(" ", co_idx+2)

                    self._message = line[ls_idx+1:sp_idx] + " " + line[ns_idx:].strip()
                    self._path = line[sp_idx+1:co_idx].strip()
                    self._path += (":" + line[co_idx+1:ns_idx].strip())

                self.emit_marker()
                self._state = ParseState.Init
                self._count = 0
            else:
                self._tmp += (" " + l.strip())
        pass

    def emit_marker(self):
        loc : TaskMarkerLoc = None
        
        if self._path != "":
            elems = self._path.split(":")
            self._log.debug("Path elems: %s (%d)" % (elems, len(elems)))
            line=-1
            pos=-1
            if len(elems) > 1:
                self._log.debug("elems[1]: %s" % elems[1])
                line = int(elems[1])
            if len(elems) > 2:
                pos = int(elems[2])
            loc = TaskMarkerLoc(path=elems[0], line=line, pos=pos)
        self._log.debug("Message: %s" % self._message)

        if loc is not None:
            marker = TaskMarker(
                severity=self._kind,
                msg=self._message,
                loc=loc)
        else:
            marker = TaskMarker(
                severity=self._kind,
                msg=self._message)

        self._kind = ""
        self._message = ""
        self._path = ""
        if self.notify is not None:
            self.notify(marker)

    pass
