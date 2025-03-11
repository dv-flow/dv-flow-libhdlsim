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
                sp_idx = l.find(" ")
                self._kind = "warn" if l.startswith("Warning") else "error"
                self._message = l[sp_idx+1:].strip()
                self._state = ParseState.MultiLineStyle1
            elif l.startswith("%Error") or l.startswith("%Warning"):
                # Verilator-style message:
                # %<Kind>-<Code>: <Path>:<Line>:<Pos>: <Short Desc>
                # %Kind: <Path>|<verilator>: <Short Desc>
                # %Kind: <Short Desc>
                #   <Indented Description Lines> (Ignore)
                self._log.debug("Verilator-style message")
                self._kind = "warn" if l.startswith("%Warning") else "error"
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
                self._kind = "warn" if l.startswith("** Warning") else "error"
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

            c_idx = l.find(',')
            if c_idx != -1:
                self._log.debug("Found comma (and lineno): %s" % l)
                path = l[:c_idx].strip()
                line = l[c_idx+1:].strip()
                self._path = "%s:%s" % (path, line)
            else:
                self._log.debug("No comma (and lineno): %s" % l)
                self._path = l.strip()

            self.emit_marker()
            self._state = ParseState.Init
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
