
# Unit tests for the pure UVM-log verdict parser (P1.3).
# No simulator and no dv-flow machinery required.

import os
import pytest
from dv_flow.libhdlsim.uvm_log_parser import parse_uvm_log, parse_sim_log

DATA = os.path.join(os.path.dirname(__file__), "data/uvm_logs")


def _log(name):
    return os.path.join(DATA, name)


def test_pass_summary():
    r = parse_uvm_log(_log("pass_sw_copy.log"))
    assert r["saw_summary"] is True
    assert r["passed"] is True
    assert r["status"] == "pass"
    assert r["errors"] == 0
    assert r["fatals"] == 0
    assert r["saw_finish"] is True
    # A real, small log is read whole (fits in the tail window) -- fine; the
    # tail-only guarantee is exercised by test_tail_only below.


def test_fail_summary():
    r = parse_uvm_log(_log("fail_uvm_error.log"))
    assert r["saw_summary"] is True
    assert r["passed"] is False
    assert r["status"] == "fail"
    assert r["errors"] == 3
    assert r["fatals"] == 0


def test_no_summary_crash():
    r = parse_uvm_log(_log("crash_no_summary.log"))
    assert r["saw_summary"] is False
    assert r["scanned_whole_file"] is True
    assert r["passed"] is False
    assert r["status"] == "error"


def test_no_finish_timeout():
    r = parse_uvm_log(_log("timeout_no_finish.log"))
    assert r["saw_summary"] is False
    assert r["saw_finish"] is False
    assert r["passed"] is False
    assert r["status"] == "timeout"


def test_no_false_error():
    # Clean PASS log that contains 'err_test', 'error', and '0 errors' text:
    # the anchored parse must NOT be fooled into a fail.
    r = parse_uvm_log(_log("pass_tricky_substrings.log"))
    assert r["passed"] is True
    assert r["status"] == "pass"
    assert r["errors"] == 0


_CLEAN_SUMMARY = (
    "UVM_INFO @ 9: uvm_test_top [RESULT] ** TEST PASSED **\n"
    "--- UVM Report Summary ---\n\n"
    "** Report counts by severity\n"
    "UVM_INFO :   10\n"
    "UVM_WARNING :    0\n"
    "UVM_ERROR :    0\n"
    "UVM_FATAL :    0\n"
    "- uvm_root.svh:585: Verilog $finish\n"
)

DIAGDIR = os.path.join(os.path.dirname(__file__), "data", "diag")


def _diag(name):
    with open(os.path.join(DIAGDIR, name)) as fp:
        return fp.read()


def _uvm_log(tmp_path, body, summary=_CLEAN_SUMMARY):
    p = tmp_path / "sim.log"
    p.write_text("UVM_INFO @ 0: reporter [RNTST] Running test t...\n" + body + summary)
    return str(p)


def test_failure_early_in_a_large_log(tmp_path):
    """An assertion failure far before the last 64 KiB, then a clean summary:
    the whole log is scanned, so the case does not pass."""
    p = tmp_path / "big.log"
    filler = ("UVM_INFO @ 0: reporter [NOISE] "
              "the word error and err_test appear here harmlessly\n") * 200000
    p.write_text(_diag("vcs_sva_default.log") + filler + _CLEAN_SUMMARY)
    assert p.stat().st_size > 5 * 1024 * 1024

    r = parse_uvm_log(str(p))
    assert r["saw_summary"] is True
    assert r["scanned_whole_file"] is True
    assert r["errors"] == 0                # the UVM summary is still clean...
    assert r["sim_errors"] == 2            # ...but the simulator said otherwise
    assert r["assertion_failures"] == 2
    assert r["passed"] is False
    assert r["status"] == "fail"


def test_large_clean_log_passes(tmp_path):
    p = tmp_path / "big.log"
    filler = ("UVM_INFO @ 0: reporter [NOISE] "
              "the word error and err_test appear here harmlessly\n") * 200000
    p.write_text(filler + _CLEAN_SUMMARY)
    r = parse_uvm_log(str(p))
    assert r["passed"] is True and r["status"] == "pass"
    assert r["sim_errors"] == 0 and r["diagnostics"] == []


@pytest.mark.parametrize("fixture,run_status", [
    ("vcs_sva_default.log", 0),     # VCS exits 0
    ("vcs_sva_action.log", 0),
    ("xcm_asrtst.log", 1),          # Xcelium exits 1
    ("xcm_sevtasks.log", 1),
    ("vlt_error_limit.log", 0),     # Verilator with +verilator+error+limit
])
def test_clean_summary_does_not_mask_sim_diagnostics(tmp_path, fixture, run_status):
    r = parse_uvm_log(_uvm_log(tmp_path, _diag(fixture)), run_status=run_status)
    assert r["saw_summary"] is True and r["errors"] == 0 and r["fatals"] == 0
    assert r["sim_errors"] + r["sim_fatals"] > 0
    assert r["passed"] is False
    assert r["status"] == "fail"
    assert r["first_failure"]
    assert r["diagnostics"][0]["severity"] in ("error", "fatal")


def test_clean_summary_with_nonzero_exit_is_error(tmp_path):
    r = parse_uvm_log(_uvm_log(tmp_path, ""), run_status=3)
    assert r["passed"] is False
    assert r["status"] == "error"
    # ...and still a pass when the exit is clean (or unknown)
    assert parse_uvm_log(_uvm_log(tmp_path, ""), run_status=0)["passed"] is True
    assert parse_uvm_log(_uvm_log(tmp_path, ""))["passed"] is True


def test_warnings_do_not_fail_a_clean_run(tmp_path):
    r = parse_uvm_log(_uvm_log(tmp_path, _diag("warnings_only.log")), run_status=0)
    assert r["passed"] is True
    assert r["sim_errors"] == 0 and r["sim_fatals"] == 0


def test_uvm_counts_come_from_the_summary_only():
    """The UVM_ERROR report lines are not added to the summary's tally."""
    r = parse_uvm_log(_log("fail_uvm_error.log"))
    assert r["errors"] == 3
    assert r["sim_errors"] == 0


def test_no_summary_hdl_fatal_is_a_fail(tmp_path):
    """A checker's $fatal ends the run before the UVM summary: a test failure,
    not a crash or a timeout."""
    r = parse_uvm_log(_uvm_log(tmp_path, _diag("xcm_sevtasks.log"), summary=""))
    assert r["saw_summary"] is False
    assert r["status"] == "fail"
    assert r["sim_fatals"] == 1


def test_no_summary_tool_fatal_is_an_error(tmp_path):
    r = parse_uvm_log(_uvm_log(
        tmp_path, "xmsim: *F,INTERR: INTERNAL ERROR\n", summary=""))
    assert r["status"] == "error"


def test_questa_transcript_prefix(tmp_path):
    """Questa prefixes its transcript with '# ', summary included."""
    summary = "".join("# " + l + "\n" for l in _CLEAN_SUMMARY.splitlines())
    r = parse_uvm_log(_uvm_log(tmp_path, "", summary=summary.replace(
        "UVM_ERROR :    0", "UVM_ERROR :    2")))
    assert r["saw_summary"] is True
    assert r["errors"] == 2
    assert r["status"] == "fail"


#---------------------------------------------------------------------------
# Generic (non-UVM) verdict
#---------------------------------------------------------------------------

def _plain(tmp_path, body):
    p = tmp_path / "sim.log"
    p.write_text(body)
    return str(p)


@pytest.mark.parametrize("fixture", [
    "vcs_sva_default.log", "vcs_sva_action.log", "xcm_asrtst.log",
    "xcm_sevtasks.log", "vlt_error_limit.log", "ivl_errors.log",
    "ivl_fatal.log", "mti_errors.log"])
def test_generic_exit_zero_with_errors_fails(tmp_path, fixture):
    r = parse_sim_log(_plain(tmp_path, _diag(fixture)), run_status=0)
    assert r["passed"] is False and r["status"] == "fail"
    assert r["errors"] == 0                 # no UVM tallies for a generic run


def test_generic_clean_and_warnings_pass(tmp_path):
    assert parse_sim_log(_plain(tmp_path, "hello\n$finish\n"))["passed"] is True
    assert parse_sim_log(_plain(tmp_path, _diag("warnings_only.log")))["passed"] is True


def test_generic_nonzero_exit_fails(tmp_path):
    r = parse_sim_log(_plain(tmp_path, "hello\n"), run_status=2)
    assert r["passed"] is False and r["status"] == "fail"


def test_generic_missing_log(tmp_path):
    r = parse_sim_log(str(tmp_path / "nope.log"))
    assert r["passed"] is False and r["status"] == "error"


def test_missing_file():
    r = parse_uvm_log(_log("does_not_exist.log"))
    assert r["passed"] is False
    assert r["status"] == "error"
