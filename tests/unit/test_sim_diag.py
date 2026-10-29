# Unit tests for sim_diag: simulator runtime diagnostics (assertion failures,
# $error/$fatal, simulator errors) recognized in a simulation log. No
# simulator; fixtures in data/diag (see its README).

import os
import pytest
from dv_flow.libhdlsim import sim_diag

DIAGDIR = os.path.join(os.path.dirname(__file__), "data", "diag")


def _scan(name):
    with open(os.path.join(DIAGDIR, name)) as fp:
        return sim_diag.scan_lines(fp)


def _counts(s):
    return (s.errors, s.fatals, s.warnings, s.assertions)


def test_time_fs():
    assert sim_diag.time_fs("105000ps") == sim_diag.time_fs("105000 ps")
    assert sim_diag.time_fs("105 NS") == sim_diag.time_fs("105000ps")
    assert sim_diag.time_fs("125 ns") == 125 * 10**6
    assert sim_diag.time_fs("15") is None


def test_vcs_default_sva_without_error_line():
    """A default SVA failure prints no 'Error:' line; it is still an error."""
    s = _scan("vcs_sva_default.log")
    assert _counts(s) == (2, 0, 0, 2)
    d = s.first()
    assert (d.severity, d.category) == ("error", "assertion")
    assert (d.file, d.line) == ("checker.sv", 31)
    assert d.hier == "tb_top.dut.u_chk.REQ_KNOWN"
    assert d.time == "105000ps"
    assert d.message.startswith("Offending")


def test_vcs_sva_and_its_action_are_one_event():
    s = _scan("vcs_sva_action.log")
    # REQ_KNOWN@105 (+action), GNT_ONEHOT@105, unrelated $error@105,
    # REQ_KNOWN@125 (+action, time printed in another unit), $fatal@130
    assert (s.errors, s.fatals) == (4, 1)
    assert s.assertions == 3
    req, gnt, chk, req2, fat = s.sample
    assert req.hier.endswith("REQ_KNOWN") and req.message == "REQ_KNOWN_FAIL"
    assert (req.file, req.line) == ("checker.sv", 31)
    # Same time, different assertion: not merged
    assert gnt.hier.endswith("GNT_ONEHOT") and gnt.category == "assertion"
    # Same time, unrelated $error: not merged into the assertion before it
    assert chk.category == "check" and chk.message == "CHECKER_ERROR unrelated diagnostic"
    # Repeated failure at another time: its own event, merged with its action
    assert req2.time == "125000ps" and req2.message == "REQ_KNOWN_FAIL"
    assert (fat.severity, fat.category) == ("fatal", "check")


def test_xcm_asrtst_with_and_without_action():
    s = _scan("xcm_asrtst.log")
    assert _counts(s) == (3, 0, 1, 3)
    a, b, c = s.sample
    assert (a.code, a.file, a.line, a.time) == ("ASRTST", "checker.sv", 33, "105 NS")
    assert a.hier == "tb_top.dut.u_chk.REQ_KNOWN"
    assert "REQ_KNOWN_FAIL" in a.message
    assert b.time == "115 NS" and c.hier.endswith("GNT_ONEHOT")


def test_xcm_errsev_and_fatsev_independent():
    s = _scan("xcm_sevtasks.log")
    assert _counts(s) == (1, 1, 0, 0)
    e, f = s.sample
    assert (e.severity, e.category, e.code) == ("error", "check", "ERRSEV")
    assert e.hier == "tb_top.u_chk" and e.message == "CHECKER_ERROR diagnostic"
    assert (f.severity, f.code, f.message) == ("fatal", "FATSEV", "CHECKER_FATAL diagnostic")


@pytest.mark.parametrize("line,code,file,line_no", [
    ("xmvlog: *E,EXPSMC (t.sv,5|12): expecting a semicolon (';').", "EXPSMC", "t.sv", 5),
    ("xmelab: *E,CUVMUR (./t.sv,9): instance of module/UDP 'x' is unresolved.", "CUVMUR", "./t.sv", 9),
    ("xrun: *E,ELBERR: Error during elaboration (status 1), exiting.", "ELBERR", "", -1),
    ("xmsim(64): *F,INTERR: INTERNAL ERROR", "INTERR", "", -1),
])
def test_xcm_tool_envelope(line, code, file, line_no):
    d = sim_diag.match_header(line)
    assert d is not None and d.category == "tool"
    assert (d.code, d.file, d.line) == (code, file, line_no)


def test_verilator_error_limit_exit_zero():
    """Real Verilator output with +verilator+error+limit: the run exits 0."""
    s = _scan("vlt_error_limit.log")
    assert _counts(s) == (5, 0, 1, 5)
    d = s.first()
    assert (d.file, d.line, d.time) == ("chk.sv", 2, "15")
    assert d.hier == "top.u_chk.REQ_GNT" and d.message == "'assert' failed."
    # The '-Info: ... $stop ignored' line is not glued onto the message
    assert all("Info" not in x.message for x in s.sample)


def test_verilator_fatal_and_stop():
    s = _scan("vlt_fatal.log")
    # '%Error: ... Verilog $stop' is the $fatal's consequence, not a second event
    assert (s.errors, s.fatals) == (0, 1)
    assert s.first().message == "CHECKER_FATAL diagnostic"


def test_icarus():
    s = _scan("ivl_errors.log")
    assert _counts(s) == (3, 0, 1, 0)
    a = s.first()
    assert (a.file, a.line, a.time, a.hier, a.message) == ("imm.sv", 3, "1", "top", "IMM_FAIL a=0")
    assert "$finish" not in s.sample[-1].message
    f = _scan("ivl_fatal.log")
    assert (f.errors, f.fatals) == (0, 1)


def test_questa():
    s = _scan("mti_errors.log")
    assert _counts(s) == (2, 1, 1, 1)
    e, a, f = s.sample
    assert (e.category, e.hier, e.file, e.line, e.time) == (
        "check", "tb_top.u_chk", "checker.sv", 6, "2 ns")
    assert (a.category, a.hier, a.line) == ("assertion", "tb_top.u_chk.REQ_KNOWN", 31)
    assert f.severity == "fatal"


def test_warnings_and_benign_text_are_not_failures():
    s = _scan("warnings_only.log")
    assert (s.errors, s.fatals) == (0, 0)
    assert s.warnings == 5
    assert s.sample == []


def test_vcs_lint_is_a_warning_with_location():
    got = []
    s = sim_diag.DiagScanner(notify=got.append)
    for l in ['Lint-[WMIA-L] Width mismatch in assignment',
              '/a/b/top.sv, 42',
              '  Width of LHS is 4, RHS is 8.',
              '',
              'Follow-up line']:
        s.line(l)
    s.close()
    assert (s.errors, s.fatals) == (0, 0)
    assert len(got) == 1
    d = got[0]
    assert (d.severity, d.code, d.fmt) == ("warning", "WMIA-L", "vcs-lint")
    assert (d.file, d.line) == ("/a/b/top.sv", 42)
    assert d.message == "Width mismatch in assignment Width of LHS is 4, RHS is 8."


def test_eof_without_blank_line_flushes():
    s = sim_diag.scan_lines(['xmsim: *E,ERRSEV (c.sv,5): (time 1 NS).', 'tb', 'LAST'])
    assert s.errors == 1 and s.first().message == "LAST"
    s = sim_diag.scan_lines(['"c.sv", 3: t.A: started at 1ps failed at 1ps'])
    assert s.errors == 1 and s.assertions == 1


def test_unknown_continuation_does_not_hide_the_error():
    s = sim_diag.scan_lines([
        'Error: "c.sv", 3: t.u: at time 10 ps',
        'line one', 'line two', 'line three', 'line four', 'line five'])
    assert s.errors == 1
    assert "line four" not in s.first().message


def test_sample_is_bounded_counts_are_not():
    lines = ['"c.sv", 3: t.A: started at %dps failed at %dps' % (i, i) for i in range(50)]
    s = sim_diag.scan_lines(lines, sample_max=4)
    assert s.errors == 50 and s.assertions == 50
    assert len(s.sample) == 4


def test_diag_to_dict():
    s = _scan("xcm_asrtst.log")
    d = s.first().to_dict()
    assert d["severity"] == "error" and d["category"] == "assertion"
    assert d["code"] == "ASRTST" and d["line"] == 33 and d["log_line"] == 2
