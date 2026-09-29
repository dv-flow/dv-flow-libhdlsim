#****************************************************************************
#* test_xzm_log_parser.py
#*
#* XzmLogParser against xezim 0.11.0 compile output (data/xzm_logs/, captured
#* from the real tool). No simulator needed.
#****************************************************************************
import os
from dv_flow.mgr.task_data import SeverityE
from dv_flow.libhdlsim.xzm_log_parser import XzmLogParser

LOGS = os.path.join(os.path.dirname(__file__), "data", "xzm_logs")


def _parse_lines(lines, suppress=()):
    markers = []
    p = XzmLogParser(notify=markers.append, suppress=list(suppress))
    for l in lines:
        p.line(l)
    p.close()
    return markers


def _parse(name, suppress=()):
    with open(os.path.join(LOGS, name)) as fp:
        return _parse_lines(fp.readlines(), suppress)


def test_parse_error_located():
    m = _parse("parse_error.log")
    assert len(m) == 1  # caret/excerpt lines add nothing
    assert m[0].severity == SeverityE.Error
    assert m[0].msg == "expected Semicolon, found KwEnd 'end'"
    assert (m[0].loc.path, m[0].loc.line, m[0].loc.pos) == ("perr.sv", 4, 3)


def test_undeclared_identifier_located():
    m = _parse("undeclared.log")
    assert len(m) == 1
    assert m[0].severity == SeverityE.Error
    assert (m[0].loc.path, m[0].loc.line) == ("undecl.sv", 3)


def test_gcc_style_warning():
    # Parse warnings use the same renderer as parse errors, with 'warning'.
    m = _parse_lines(["a/b.sv:12:7: warning: something odd\n",
                      "   12 |   foo;\n", "      |   ^\n"])
    assert len(m) == 1
    assert m[0].severity == SeverityE.Warning
    assert (m[0].loc.path, m[0].loc.line, m[0].loc.pos) == ("a/b.sv", 12, 7)


def test_tagged_warnings_with_and_without_location():
    m = _parse("elab_warnings.log")
    # Two [xezim][warning] lines; the indented detail line adds nothing.
    assert len(m) == 2
    assert all(x.severity == SeverityE.Warning for x in m)
    implicit, width = m
    assert implicit.msg.startswith("implicit 1-bit net")
    assert implicit.loc is None
    assert width.msg.startswith("port width mismatch")
    assert (width.loc.path, width.loc.line, width.loc.pos) == ("pw.sv", 7, 12)


def test_simulation_error_bad_top():
    m = _parse("bad_top.log")
    assert len(m) == 1
    assert m[0].severity == SeverityE.Error
    assert m[0].msg.startswith("top module 'nope' not found")
    assert m[0].loc is None


def test_plain_error_line():
    m = _parse("missing_file.log")
    assert len(m) == 1
    assert m[0].severity == SeverityE.Error
    assert m[0].msg == "file 'nofile.sv' not found"


def test_error_sentence_keeps_whole_line():
    m = _parse_lines(["Error loading compiled artifact 'x.xzb': deserialize: bad\n"])
    assert len(m) == 1
    assert m[0].msg.startswith("Error loading compiled artifact")


def test_tagged_error():
    m = _parse_lines(["[xezim][error] something failed (at t.sv:3:1)\n"])
    assert len(m) == 1
    assert m[0].severity == SeverityE.Error
    assert (m[0].loc.path, m[0].loc.line) == ("t.sv", 3)


def test_suppress_has_no_effect():
    # xezim diagnostics carry no codes, so a suppress list can't match them.
    # (Deferred: flip this when xezim or this parser grows warning codes.)
    m = _parse("elab_warnings.log", suppress=["implicit", "WIDTH", "port"])
    assert len(m) == 2


def test_status_lines_ignored():
    m = _parse_lines(["Parsed 1 file(s): 1 descriptions, 1 errors, 0 warnings\n",
                      "Elaboration successful\n",
                      "Wrote compiled artifact to simv.xzb\n"])
    assert m == []
