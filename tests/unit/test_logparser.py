import pytest
from dv_flow.libhdlsim.log_parser import LogParser
from dv_flow.mgr import SeverityE

def test_parse_vlt_style():
    markers = []

    def notify(marker):
        nonlocal markers
        markers.append(marker)

    input = """
%Warning-WIDTHTRUNC: /home/mballance/projects/zuspec/zuspec-sv/src/include/zsp/sv/zsp_sv/zsp_sv.sv:51:9: Logical operator IF expects 1 bit on the If, but If's VARREF 'count' generates 32 bits.

: ... note: In instance 'top'
   51 |         if (count) begin
      |         ^~
"""

    parser = LogParser(notify=notify)
    for l in input.splitlines():
        parser.line(l)

    assert len(markers) == 1
    assert markers[0].severity == SeverityE.Warning
    assert markers[0].msg == "[WIDTHTRUNC] Logical operator IF expects 1 bit on the If, but If's VARREF 'count' generates 32 bits."
    assert markers[0].loc is not None
    assert markers[0].loc.line == 51
    assert markers[0].loc.pos == 9
    assert markers[0].loc.path == "/home/mballance/projects/zuspec/zuspec-sv/src/include/zsp/sv/zsp_sv/zsp_sv.sv"

    input = """
%Error: /home/mballance/projects/dv-flow/dv-flow-libhdlsim/tests/unit/data/test_markers/err_syn.sv:4:4: syntax error, unexpected ';', expecting IDENTIFIER or '(' or randomize
    4 | abc;
      |    ^
%Error: Cannot continue
"""

def test_parse_mti_style1():
    markers = []

    def notify(marker):
        nonlocal markers
        markers.append(marker)

    input = """
** Error: (vlog-13069) inh.sv(3): near "X": syntax error, unexpected IDENTIFIER.
** Error: inh.sv(3): Error in class extension specification.
"""

    parser = LogParser(notify=notify)
    for l in input.splitlines():
        parser.line(l)

    assert len(markers) == 2
    assert markers[0].severity == SeverityE.Error
    assert markers[0].msg == '[vlog-13069] near "X": syntax error, unexpected IDENTIFIER.'
    assert markers[0].loc is not None
    assert markers[0].loc.line == 3
    assert markers[0].loc.pos == -1
    assert markers[0].loc.path == "inh.sv"
    assert markers[1].severity == SeverityE.Error
    assert markers[1].msg == 'Error in class extension specification.'
    assert markers[1].loc is not None
    assert markers[1].loc.line == 3
    assert markers[1].loc.pos == -1
    assert markers[1].loc.path == "inh.sv"

def test_parse_mti_style2():
    markers = []

    def notify(marker):
        nonlocal markers
        markers.append(marker)

    input = """
** Error (suppressible): inh.sv(5): (vlog-7027) The name ('xyz') was not found in the current scope.  Please verify the spelling of the name 'xyz'.
"""

    parser = LogParser(notify=notify)
    for l in input.splitlines():
        parser.line(l)

    assert len(markers) == 1
    assert markers[0].severity == SeverityE.Error
    assert markers[0].msg == "[vlog-7027] The name ('xyz') was not found in the current scope.  Please verify the spelling of the name 'xyz'."
    assert markers[0].loc is not None
    assert markers[0].loc.line == 5
    assert markers[0].loc.pos == -1
    assert markers[0].loc.path == "inh.sv"

def test_parse_vcs_style():
    markers = []

    def notify(marker):
        nonlocal markers
        markers.append(marker)

    input = """
Warning-[TMR] Text macro redefined
/foo/bar/baz.v, 17
  Text macro (ABC) is redefined. The last definition will
  override previous ones.
  Location of previous definition:
  /abc/def/ghi.v,
  16.
  Previous value: -DEF


Follow-up line
"""

    parser = LogParser(notify=notify)
    for l in input.splitlines():
        parser.line(l)

    assert len(markers) == 1
    assert markers[0].severity == SeverityE.Warning
    assert markers[0].msg == "[TMR] Text macro redefined Text macro (ABC) is redefined. The last definition will override previous ones. Location of previous definition: /abc/def/ghi.v, 16. Previous value: -DEF"
    assert markers[0].loc is not None
    assert markers[0].loc.line == 17
    assert markers[0].loc.pos == -1
    assert markers[0].loc.path == "/foo/bar/baz.v"

def test_parse_vcs_lint():
    markers = []

    def notify(marker):
        nonlocal markers
        markers.append(marker)

    input = """
Lint-[WMIA-L] Width mismatch in assignment
/a/b/top.sv, 42
  Width of LHS is 4, RHS is 8.


Follow-up line
"""

    parser = LogParser(notify=notify)
    for l in input.splitlines():
        parser.line(l)
    parser.close()

    assert len(markers) == 1
    assert markers[0].severity == SeverityE.Warning
    assert markers[0].msg == "[WMIA-L] Width mismatch in assignment Width of LHS is 4, RHS is 8."
    assert markers[0].loc is not None
    assert markers[0].loc.path == "/a/b/top.sv"
    assert markers[0].loc.line == 42

_VCS_LINT_LOG = """
Lint-[WMIA-L] Width mismatch in assignment
/a/b/top.sv, 42
  Width of LHS is 4, RHS is 8.


Lint-[PCWM-L] Port connection width mismatch
/a/b/top.sv, 50
  Port width mismatch.


"""

def _parse_lint(**kwargs):
    markers = []
    parser = LogParser(notify=lambda m: markers.append(m), **kwargs)
    for l in _VCS_LINT_LOG.splitlines():
        parser.line(l)
    parser.close()
    return markers

def test_parse_vcs_lint_escalate_listed_code():
    markers = _parse_lint(lint_as_error=["WMIA-L"])
    assert [m.severity for m in markers] == [SeverityE.Error, SeverityE.Warning]
    assert markers[0].msg.startswith("[WMIA-L]")
    assert markers[0].loc.path == "/a/b/top.sv"
    assert markers[0].loc.line == 42

def test_parse_vcs_lint_escalate_all():
    markers = _parse_lint(lint_as_error=True)
    assert [m.severity for m in markers] == [SeverityE.Error, SeverityE.Error]

def test_parse_vcs_lint_suppress_wins_over_escalation():
    markers = _parse_lint(suppress=["WMIA-L"], lint_as_error=True)
    assert len(markers) == 1
    assert markers[0].msg.startswith("[PCWM-L]")
    assert markers[0].severity == SeverityE.Error

def test_parse_vcs_lint_escalation_ignores_warnings():
    input = """
Warning-[WMIA-L] Not a lint message
/a/b/top.sv, 7
  Same code, Warning- kind.


"""
    markers = []
    parser = LogParser(notify=lambda m: markers.append(m), lint_as_error=True)
    for l in input.splitlines():
        parser.line(l)
    parser.close()
    assert len(markers) == 1
    assert markers[0].severity == SeverityE.Warning

def test_resolve_lint_as_error():
    from dv_flow.libhdlsim.log_parser import resolve_lint_as_error
    assert resolve_lint_as_error(None) == []
    assert resolve_lint_as_error([]) == []
    assert resolve_lint_as_error(True) is True
    assert resolve_lint_as_error(["all"]) is True
    assert resolve_lint_as_error("WMIA-L, PCWM-L") == ["WMIA-L", "PCWM-L"]

def test_parse_vcs_style_2():
    markers = []

    def notify(marker):
        nonlocal markers
        markers.append(marker)

    input = """
Error-[SV-LCM-PND] Package not defined
/proj/foo/bar/baz/beef_pkg_hdl.sv, 27
neat_pkg, "neat_pkg::"
  Package scope resolution failed. Token 'neat_pkg' is not a package.
  Originating module 'bar_pkg'.
  Move package definition before the use of the package.

"""

    parser = LogParser(notify=notify)
    for l in input.splitlines():
        parser.line(l)
    parser.close()

    assert len(markers) == 1
    assert markers[0].severity == SeverityE.Error
    assert markers[0].msg == "[SV-LCM-PND] Package not defined neat_pkg, \"neat_pkg::\" Package scope resolution failed. Token 'neat_pkg' is not a package. Originating module 'bar_pkg'. Move package definition before the use of the package."
    assert markers[0].loc is not None
    assert markers[0].loc.line == 27
    assert markers[0].loc.pos == -1
    assert markers[0].loc.path == "/proj/foo/bar/baz/beef_pkg_hdl.sv"

@pytest.mark.xfail(strict=True, reason="SE parsing")
def test_parse_vcs_style_3():
    markers = []

    def notify(marker):
        nonlocal markers
        markers.append(marker)

    input = """
Error-[SE] Syntax error
  Following verilog source has syntax error :
    Token 'uvmf_transaction_base' should be a valid type. Please check 
  whether it is misspelled, not visible/valid in the current context, or not 
  properly imported/exported.
  "/foo/bar/baz/uart_transaction.svh",
  23: token is ';' 
  class uart_transaction  extends uvmf_transaction_base;


"""

    parser = LogParser(notify=notify)
    for l in input.splitlines():
        parser.line(l)
    parser.close()

    assert len(markers) == 1
    assert markers[0].severity == SeverityE.Error
    assert markers[0].msg.startswith("[SE]")
    assert "token is ';'" in markers[0].msg
    assert "Token 'uvmf_transaction_base' should be a valid type. Please check whether it is misspelled, not visible/valid in the current context, or not properly imported/exported." in markers[0].msg
    assert "Following verilog source" not in markers[0].msg
    assert markers[0].loc is not None
    assert markers[0].loc.line == 23
    assert markers[0].loc.pos == -1
    assert markers[0].loc.path == "/foo/bar/baz/uart_transaction.svh"

def _parse_vcs(text):
    markers = []
    parser = LogParser(notify=lambda m: markers.append(m))
    for l in text.splitlines():
        parser.line(l)
    parser.close()
    return markers

def _assert_se(marker, path, line, token):
    assert marker.severity == SeverityE.Error
    assert marker.loc is not None
    assert marker.loc.path == path
    assert marker.loc.line == line
    assert marker.msg.startswith("[SE]")
    assert ("token is '%s'" % token) in marker.msg
    assert "Following verilog source" not in marker.msg
    assert "^" not in marker.msg

@pytest.mark.xfail(strict=True, reason="SE parsing")
def test_parse_vcs_se_excerpt():
    markers = _parse_vcs("""
Error-[SE] Syntax error
  Following verilog source has syntax error :
  "se_only.sv", 3: token is 'initial'
    initial a = 1;
           ^

1 error
""")
    assert len(markers) == 1
    _assert_se(markers[0], "se_only.sv", 3, "initial")
    assert "a = 1" not in markers[0].msg

@pytest.mark.xfail(strict=True, reason="SE parsing")
def test_parse_vcs_se_explanation_after():
    markers = _parse_vcs("""
Error-[SE] Syntax error
  Following verilog source has syntax error :
  "se_two.sv", 3: token is 'logic'
    logic b
         ^
  SystemVerilog  keyword 'logic' is not expected to be used in this context.

""")
    assert len(markers) == 1
    _assert_se(markers[0], "se_two.sv", 3, "logic")
    assert "keyword 'logic' is not expected to be used in this context." in markers[0].msg

@pytest.mark.xfail(strict=True, reason="SE parsing")
def test_parse_vcs_se_split_loc():
    path = "/proj/workarea/projectx/nice-dv-assertions/.scratch/syntax-error/se_only.sv"
    markers = _parse_vcs("""
Error-[SE] Syntax error
  Following verilog source has syntax error :
  "%s",
  3: token is 'initial'
    initial a = 1;
           ^

""" % path)
    assert len(markers) == 1
    _assert_se(markers[0], path, 3, "initial")
    assert path not in markers[0].msg

@pytest.mark.xfail(strict=True, reason="SE parsing")
def test_parse_vcs_se_no_excerpt():
    markers = _parse_vcs("""
Error-[SE] Syntax error
  Following verilog source has syntax error :
  "se_late.sv", 3: token is 'endmodule'

1 error
CPU time: .414 seconds to compile
""")
    assert len(markers) == 1
    _assert_se(markers[0], "se_late.sv", 3, "endmodule")
    assert "1 error" not in markers[0].msg
    assert "CPU time" not in markers[0].msg

_VCS_TMR = """
Warning-[TMR] Text macro redefined
macro_then_se.sv, 2
  Text macro (W) is redefined. The last definition will override previous
  ones.
  Location of previous definition: macro_then_se.sv, 1.
  Previous value: 4

"""

_VCS_SE_F = """
Error-[SE] Syntax error
  Following verilog source has syntax error :
  "macro_then_se.sv", 5: token is 'initial'
    initial a = 1;
           ^

"""

_VCS_TMR_MSG = "[TMR] Text macro redefined Text macro (W) is redefined. The last definition will override previous ones. Location of previous definition: macro_then_se.sv, 1. Previous value: 4"

@pytest.mark.xfail(strict=True, reason="SE parsing")
def test_parse_vcs_se_after_warning():
    markers = _parse_vcs(_VCS_TMR + _VCS_SE_F + "1 warning\n1 error\n")
    assert len(markers) == 2
    assert markers[0].severity == SeverityE.Warning
    assert markers[0].msg == _VCS_TMR_MSG
    assert markers[0].loc.path == "macro_then_se.sv"
    assert markers[0].loc.line == 2
    _assert_se(markers[1], "macro_then_se.sv", 5, "initial")
    assert "Text macro" not in markers[1].msg

@pytest.mark.xfail(strict=True, reason="SE parsing")
def test_parse_vcs_warning_after_se():
    markers = _parse_vcs(_VCS_SE_F + _VCS_TMR + "1 warning\n1 error\n")
    assert len(markers) == 2
    assert markers[0].severity == SeverityE.Error
    assert markers[1].severity == SeverityE.Warning
    assert markers[1].msg == _VCS_TMR_MSG
    assert "syntax error" not in markers[1].msg
    assert markers[1].loc.path == "macro_then_se.sv"
    assert markers[1].loc.line == 2

@pytest.mark.xfail(strict=True, reason="SE parsing")
def test_parse_vcs_two_se():
    markers = _parse_vcs("""
Error-[SE] Syntax error
  Following verilog source has syntax error :
  "se_only.sv", 3: token is 'initial'
    initial a = 1;
           ^

Error-[SE] Syntax error
  Following verilog source has syntax error :
  "se_late.sv", 7: token is 'endmodule'

2 errors
""")
    assert len(markers) == 2
    _assert_se(markers[0], "se_only.sv", 3, "initial")
    _assert_se(markers[1], "se_late.sv", 7, "endmodule")
    assert "endmodule" not in markers[0].msg
    assert "initial" not in markers[1].msg

def test_parse_vcs_style_4():
    markers = []

    def notify(marker):
        nonlocal markers
        markers.append(marker)

    input = """
Warning-[TFIPC] Too few instance port connections
/a/b/c/d/hdl_top.sv, 75
hdl_top, "uart_if sio_bus( .clock (clk),  .reset (rst));"
  The above instance has fewer port connections than the module definition.
  Please use '+lint=TFIPC-L' to print out detailed information of unconnected
  ports.


"""

    parser = LogParser(notify=notify)
    for l in input.splitlines():
        parser.line(l)
    parser.close()

    assert len(markers) == 1
    assert markers[0].severity == SeverityE.Warning
    assert markers[0].msg == "[TFIPC] Too few instance port connections hdl_top, \"uart_if sio_bus( .clock (clk),  .reset (rst));\" The above instance has fewer port connections than the module definition. Please use '+lint=TFIPC-L' to print out detailed information of unconnected ports."
    assert markers[0].loc is not None
    assert markers[0].loc.line == 75
    assert markers[0].loc.pos == -1
    assert markers[0].loc.path == "/a/b/c/d/hdl_top.sv"

def test_parse_mti_include_chain_anonymized():
    markers = []

    def notify(m):
        nonlocal markers
        markers.append(m)

    input = """
** Error: ** while parsing file included at /p/q/r/pyhdl_uvm.sv(13)
** at /p/q/r/pyhdl_uvm_object_rgy.svh(70): (vlog-2730) Undefined variable: 'wrapper'.
"""
    parser = LogParser(notify=notify)
    for l in input.splitlines():
        parser.line(l)

    assert len(markers) == 1
    assert markers[0].severity == SeverityE.Error
    assert markers[0].msg == "[vlog-2730] Undefined variable: 'wrapper'."
    assert markers[0].loc is not None
    assert markers[0].loc.line == 70
    assert markers[0].loc.pos == -1
    assert markers[0].loc.path == "/p/q/r/pyhdl_uvm_object_rgy.svh"


# ── Warning suppression tests ──────────────────────────────────────────────────

def test_suppress_vcs_warning_by_code():
    """Suppressed VCS warning should not produce a marker."""
    markers = []
    parser = LogParser(notify=lambda m: markers.append(m), suppress=["TFIPC"])

    input = """
Warning-[TFIPC] Too few instance port connections
/a/b/c/d/hdl_top.sv, 75
hdl_top, "uart_if sio_bus( .clock (clk),  .reset (rst));"
  The above instance has fewer port connections than the module definition.

"""
    for l in input.splitlines():
        parser.line(l)
    parser.close()

    assert len(markers) == 0


def test_suppress_vcs_warning_does_not_suppress_other():
    """Only the matching code is suppressed; other warnings still produce markers."""
    markers = []
    parser = LogParser(notify=lambda m: markers.append(m), suppress=["TFIPC"])

    input = """
Warning-[TMR] Text macro redefined
/foo/bar/baz.v, 17
  Text macro (ABC) is redefined.

Warning-[TFIPC] Too few instance port connections
/a/b/c/d/hdl_top.sv, 75
hdl_top, "uart_if sio_bus();"
  The above instance has fewer port connections.

"""
    for l in input.splitlines():
        parser.line(l)
    parser.close()

    assert len(markers) == 1
    assert markers[0].msg.startswith("[TMR]")


def test_suppress_does_not_suppress_errors():
    """Suppressed code must not suppress errors, only warnings."""
    markers = []
    parser = LogParser(notify=lambda m: markers.append(m), suppress=["SV-LCM-PND"])

    input = """
Error-[SV-LCM-PND] Package not defined
/proj/foo/bar/baz/beef_pkg_hdl.sv, 27
neat_pkg, "neat_pkg::"
  Package scope resolution failed.

"""
    for l in input.splitlines():
        parser.line(l)
    parser.close()

    assert len(markers) == 1
    assert markers[0].severity == SeverityE.Error
    assert markers[0].msg.startswith("[SV-LCM-PND]")


def test_suppress_verilator_warning_by_code():
    """Suppressed Verilator warning should not produce a marker."""
    markers = []
    parser = LogParser(notify=lambda m: markers.append(m), suppress=["WIDTHTRUNC"])

    input = """\
%Warning-WIDTHTRUNC: /some/file.sv:51:9: Logical operator IF expects 1 bit.
"""
    for l in input.splitlines():
        parser.line(l)

    assert len(markers) == 0


def test_suppress_questa_style1_warning_by_code():
    """Suppressed Questa style-1 warning should not produce a marker."""
    markers = []
    parser = LogParser(notify=lambda m: markers.append(m), suppress=["vlog-13069"])

    input = """
** Warning: (vlog-13069) inh.sv(3): near "X": syntax error, unexpected IDENTIFIER.
"""
    for l in input.splitlines():
        parser.line(l)

    assert len(markers) == 0


def test_suppress_questa_style2_warning_by_code():
    """Suppressed Questa style-2 warning should not produce a marker."""
    markers = []
    parser = LogParser(notify=lambda m: markers.append(m), suppress=["vlog-7027"])

    input = """
** Warning (suppressible): inh.sv(5): (vlog-7027) The name ('xyz') was not found in the current scope.
"""
    for l in input.splitlines():
        parser.line(l)

    assert len(markers) == 0


def test_suppress_multiple_codes():
    """Multiple codes can be suppressed simultaneously."""
    markers = []
    parser = LogParser(notify=lambda m: markers.append(m), suppress=["TFIPC", "TMR"])

    input = """
Warning-[TFIPC] Too few instance port connections
/a/b/c/d/hdl_top.sv, 75
hdl_top, "uart_if sio_bus();"
  The above instance has fewer port connections.

Warning-[TMR] Text macro redefined
/foo/bar/baz.v, 17
  Text macro (ABC) is redefined.

"""
    for l in input.splitlines():
        parser.line(l)
    parser.close()

    assert len(markers) == 0


def test_code_prefix_in_marker_msg_vcs():
    """VCS warning marker message includes [CODE] prefix."""
    markers = []
    parser = LogParser(notify=lambda m: markers.append(m))

    input = """
Warning-[TFIPC] Too few instance port connections
/a/b/c/d/hdl_top.sv, 75
hdl_top, "uart_if sio_bus();"
  The above instance has fewer port connections.

"""
    for l in input.splitlines():
        parser.line(l)
    parser.close()

    assert len(markers) == 1
    assert markers[0].msg.startswith("[TFIPC]")


def test_code_prefix_in_marker_msg_verilator():
    """Verilator warning marker message includes [CODE] prefix."""
    markers = []
    parser = LogParser(notify=lambda m: markers.append(m))

    input = """\
%Warning-WIDTHTRUNC: /some/file.sv:51:9: Logical operator IF expects 1 bit.
"""
    for l in input.splitlines():
        parser.line(l)

    assert len(markers) == 1
    assert markers[0].msg.startswith("[WIDTHTRUNC]")



def test_xcelium_envelope_markers():
    """Xcelium '<tool>: *E,<CODE>' messages come from sim_diag's table."""
    markers = []
    p = LogParser(notify=lambda m: markers.append(m), suppress=["NOCOND"])
    for l in ["xmvlog: *E,EXPSMC (t.sv,5|12): expecting a semicolon (';').",
              "xmsim: *W,NOCOND (t.sv,12|4): Condition is never evaluated.",
              "xmsim: *W,XPWDIS: X-propagation is disabled."]:
        p.line(l)
    p.close()
    assert [m.severity for m in markers] == [SeverityE.Error, SeverityE.Warning]
    assert markers[0].msg.startswith("[EXPSMC]")
    assert (markers[0].loc.path, markers[0].loc.line) == ("t.sv", 5)
    assert markers[1].msg.startswith("[XPWDIS]")


def test_suppress_never_hides_an_xcelium_error():
    markers = []
    p = LogParser(notify=lambda m: markers.append(m), suppress=["ASRTST"])
    p.line("xmsim: *E,ASRTST (c.sv,33): (time 105 NS) Assertion t.A has failed")
    p.close()
    assert len(markers) == 1 and markers[0].severity == SeverityE.Error


import pytest

_LINT_BLOCK = ["Lint-[WMIA-L] Width mismatch in assignment",
               "/a/b/top.sv, 42",
               "  Width of LHS is 4, RHS is 8."]

@pytest.mark.parametrize("gap", [[], [""]])
@pytest.mark.parametrize("follow,sev", [
    (["Warning-[TFIPC] Too few port connections", "/a/b/top.sv, 60", "  More text."],
     SeverityE.Warning),
    (["Error-[IND] Identifier not declared", "/a/b/top.sv, 70", "  More text."],
     SeverityE.Error),
])
def test_parse_vcs_lint_followed_by_message(gap, follow, sev):
    markers = []
    parser = LogParser(notify=lambda m: markers.append(m))
    for l in _LINT_BLOCK + gap + follow + ["", ""]:
        parser.line(l)
    parser.close()

    assert len(markers) == 2
    assert markers[0].severity == SeverityE.Warning
    assert markers[0].msg == "[WMIA-L] Width mismatch in assignment Width of LHS is 4, RHS is 8."
    assert markers[0].loc.line == 42
    assert markers[1].severity == sev
    assert markers[1].loc.line in (60, 70)


@pytest.mark.parametrize("gap", [[], [""]])
def test_parse_vcs_lint_does_not_swallow_plain_line(gap):
    markers = []
    parser = LogParser(notify=lambda m: markers.append(m))
    for l in _LINT_BLOCK + gap + ["Simulation complete", ""]:
        parser.line(l)
    parser.close()

    assert len(markers) == 1
    assert "Simulation complete" not in markers[0].msg
