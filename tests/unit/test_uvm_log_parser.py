
# Unit tests for the pure UVM-log verdict parser (P1.3).
# No simulator and no dv-flow machinery required.

import os
import pytest
from dv_flow.libhdlsim.uvm_log_parser import parse_uvm_log

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


def test_tail_only(tmp_path):
    # A large synthetic log with the summary in the last ~1 KB. With a small
    # tail window the parser must find the verdict WITHOUT scanning the whole
    # file (scanned_whole_file stays False).
    p = tmp_path / "big.log"
    filler = ("UVM_INFO @ 0: reporter [NOISE] "
              "the word error and err_test appear here harmlessly\n") * 200000
    summary = (
        "UVM_INFO @ 9: uvm_test_top [RESULT] ** TEST PASSED **\n"
        "--- UVM Report Summary ---\n\n"
        "** Report counts by severity\n"
        "UVM_INFO :   10\n"
        "UVM_WARNING :    0\n"
        "UVM_ERROR :    0\n"
        "UVM_FATAL :    0\n"
        "- uvm_root.svh:585: Verilog $finish\n"
    )
    p.write_text(filler + summary)
    assert p.stat().st_size > 5 * 1024 * 1024  # comfortably exceeds tail window

    r = parse_uvm_log(str(p), tail_bytes=8192)
    assert r["saw_summary"] is True
    assert r["scanned_whole_file"] is False  # fast path only touched the tail
    assert r["passed"] is True
    assert r["status"] == "pass"


def test_missing_file():
    r = parse_uvm_log(_log("does_not_exist.log"))
    assert r["passed"] is False
    assert r["status"] == "error"
