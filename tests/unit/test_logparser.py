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
    # TODO: need some enhancements here
#    assert markers[0].msg.startswith("Following verilog source has syntax error : Token 'uvmf_transaction_base' should be a valid type. Please check whether it is misspelled, not visible/valid in the current context, or not properly imported/exported.")
#    assert markers[0].msg == "Token 'uvmf_transaction_base' should be a valid type. Please check whether it is misspelled, not visible/valid in the current context, or not properly imported/exported."
#    assert markers[0].loc is not None
#    assert markers[0].loc.line == 23
#    assert markers[0].loc.pos == -1
#    assert markers[0].loc.path == "/foo/bar/baz/uart_transaction.svh"

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

