#****************************************************************************
#* xzm_log_parser.py
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
import re
import dataclasses as dc
from dv_flow.mgr.task_data import SeverityE
from dv_flow.libhdlsim.log_parser import LogParser


@dc.dataclass
class XzmLogParser(LogParser):
    """Markers from xezim compile output (as of 0.11.0):

        file.sv:4:3: error: expected Semicolon, found KwEnd 'end'
        [xezim][warning] port width mismatch: ... (connection at file.sv:7:12); ...
        Simulation error: top module 'x' not found; ...
        Error: file 'x.sv' not found
        Warning: unknown flag '--y' (ignored)

    A diagnostic's continuation lines (caret excerpt, `N | ...` source lines,
    indented detail) are ignored, so each diagnostic yields one marker.

    xezim diagnostics carry no codes, so `suppress` cannot target them.
    """

    # gcc style. The path may itself contain ':' (rare), so anchor on the
    # ':<line>:<col>: <kind>:' that follows it.
    _RE_GCC = re.compile(
        r'^(?P<path>\S.*?):(?P<line>\d+):(?P<pos>\d+):\s*'
        r'(?P<kind>error|fatal|warning):\s*(?P<msg>.*)$')
    _RE_TAG = re.compile(r'^\[xezim\]\[(?P<kind>error|fatal|warning)\]\s*(?P<msg>.*)$')
    # First '... at <path>:<line>:<col>' in a tagged message
    _RE_AT = re.compile(r'\bat\s+(?P<path>[^\s:()]+):(?P<line>\d+):(?P<pos>\d+)')
    _RE_PLAIN = re.compile(
        r'^(?P<kind>Simulation error|Error|error|Warning)(?P<sep>:?)\s+(?P<msg>.*)$')

    def _line(self, l):
        s = l.rstrip("\r\n")

        m = self._RE_GCC.match(s)
        if m is not None:
            self._set(m.group("kind"), m.group("msg"),
                      "%s:%s:%s" % (m.group("path"), m.group("line"), m.group("pos")))
            return

        m = self._RE_TAG.match(s)
        if m is not None:
            at = self._RE_AT.search(m.group("msg"))
            path = ("%s:%s:%s" % (at.group("path"), at.group("line"), at.group("pos"))
                    if at is not None else "")
            self._set(m.group("kind"), m.group("msg"), path)
            return

        m = self._RE_PLAIN.match(s)
        if m is not None:
            # 'Error: <msg>', or 'Error loading ...' where the kind is part of
            # the sentence
            self._set(m.group("kind"), m.group("msg") if m.group("sep") else s, "")
            return

        # Continuation lines start with whitespace; nothing else to do for
        # them. Anything else gets the generic formats.
        if s[:1] in (" ", "\t"):
            return
        super()._line(l)

    def _set(self, kind, msg, path):
        self._kind = (SeverityE.Warning if kind.lower() == "warning"
                      else SeverityE.Error)
        self._message = msg.strip()
        self._path = path
        self.emit_marker()
