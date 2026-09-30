#****************************************************************************
# Unit tests for the per-run statistics/metadata layer (sim_stats.py) and the
# Verilator simulation-report parser.
#
# sim_stats imports no dv-flow machinery, so everything here is a pure-function
# test over strings and temp files -- no simulator required.
#****************************************************************************
import json
import os

import pytest

from dv_flow.libhdlsim import sim_stats as ss
from dv_flow.libhdlsim.vlt_sim_run import SimRunner as VltSimRunner


#---------------------------------------------------------------------------
# Time-with-unit round trip
#---------------------------------------------------------------------------

@pytest.mark.parametrize("text,expect", [
    ("608us",   608e-6),
    ("1.5 ms",  1.5e-3),
    ("915ns",   915e-9),
    ("3s",      3.0),
    ("10 US",   10e-6),
    ("1fs",     1e-15),
])
def test_parse_time_str(text, expect):
    assert ss.parse_time_str(text) == pytest.approx(expect)


@pytest.mark.parametrize("text", ["", "bogus", "12", "12x", None, "us"])
def test_parse_time_str_rejects(text):
    assert ss.parse_time_str(text) is None


@pytest.mark.parametrize("secs,expect", [
    (0.0, "0s"), (2e-6, "2us"), (1.25e-3, "1.25ms"), (3.4, "3.4s"),
])
def test_format_time_s(secs, expect):
    assert ss.format_time_s(secs) == expect


#---------------------------------------------------------------------------
# Seed extraction -- reproduction depends on capturing this correctly
#---------------------------------------------------------------------------

@pytest.mark.parametrize("args,plusargs,seed", [
    (["-sv_seed", "1234"],   [],                       1234),
    (["-sv_seed=99"],        [],                       99),
    (["-svseed 7"],          [],                       7),
    ([],                     ["verilator+seed+77"],    77),
    ([],                     ["ntb_random_seed=42"],   42),
    ([],                     ["UVM_TESTNAME=x"],       None),
    ([],                     [],                       None),
])
def test_extract_seed(args, plusargs, seed):
    got, src = ss.extract_seed(args, plusargs)
    assert got == seed
    # A seed is always attributed to the argument it came from.
    assert (src != "") == (seed is not None)


#---------------------------------------------------------------------------
# Tier 1: host-process stats
#---------------------------------------------------------------------------

def test_wrap_host_stats_is_transparent_or_absent(tmpdir):
    cmd = ["/bin/echo", "hello"]
    wrapped = ss.wrap_host_stats(cmd, os.path.join(str(tmpdir), "sim.time"))
    # Either GNU time is present (cmd is a suffix of the wrapper) or it is not
    # (cmd is returned untouched). Never a partially-applied wrapper.
    assert wrapped[-len(cmd):] == cmd


@pytest.mark.skipif(ss._gnu_time() is None, reason="no GNU time available")
def test_host_stats_end_to_end(tmpdir):
    import subprocess
    statfile = os.path.join(str(tmpdir), "sim.time")
    cmd = ss.wrap_host_stats(["/bin/sh", "-c", "exit 3"], statfile)
    rc = subprocess.run(cmd, stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL).returncode
    # The wrapper must pass the child's exit status through untouched, or a
    # run's verdict would change just by being measured.
    assert rc == 3

    stats = ss.parse_host_stats(statfile)
    assert "cpu_total_s" in stats and "maxrss_mb" in stats
    assert stats["maxrss_mb"] > 0
    assert stats["cpu_total_s"] == pytest.approx(
        stats["cpu_user_s"] + stats["cpu_sys_s"], abs=1e-6)


def test_parse_host_stats_missing_file_is_empty(tmpdir):
    assert ss.parse_host_stats(os.path.join(str(tmpdir), "nope")) == {}


def test_parse_host_stats_tolerates_preamble(tmpdir):
    # GNU time prepends eg a signal notice; the record line must still be found.
    p = os.path.join(str(tmpdir), "sim.time")
    with open(p, "w") as fp:
        fp.write("Command terminated by signal 11\n")
        fp.write("hoststats walltime_s=1.50 cpu_user_s=1.00 cpu_sys_s=0.25 "
                 "maxrss_kb=204800 exit=0 ctx_vol=3 ctx_invol=4 io_in=0 io_out=8\n")
    s = ss.parse_host_stats(p)
    assert s["walltime_s"] == 1.5
    assert s["cpu_total_s"] == 1.25
    assert s["maxrss_mb"] == 200.0
    assert s["cpu_pct"] == pytest.approx(83.3, abs=0.1)
    assert s["ctx_vol"] == 3


#---------------------------------------------------------------------------
# Tier 3 + derived + persistence
#---------------------------------------------------------------------------

def test_read_tb_stats(tmpdir):
    with open(os.path.join(str(tmpdir), ss.TB_STATS_FILE), "w") as fp:
        json.dump({"cycles": 1200, "transactions": 40,
                   "nested": {"dropped": 1}}, fp)
    s = ss.read_tb_stats(str(tmpdir))
    assert s == {"cycles": 1200, "transactions": 40}


def test_read_tb_stats_absent(tmpdir):
    assert ss.read_tb_stats(str(tmpdir)) == {}


def test_finalize_derives_simtime_and_speed():
    s = ss.finalize({"simtime": "608us", "walltime_s": 5.28})
    assert s["simtime_s"] == pytest.approx(608e-6)
    assert s["sim_speed_s_per_s"] == pytest.approx(608e-6 / 5.28, rel=1e-3)


def test_finalize_keeps_map_sparse():
    # No simtime reported -> no derived keys invented.
    s = ss.finalize({"walltime_s": 1.0})
    assert "simtime_s" not in s and "sim_speed_s_per_s" not in s


def test_write_stats_json(tmpdir):
    p = ss.write_stats_json(str(tmpdir), {"walltime_s": 1.0}, {"sim": "vlt"})
    assert p is not None and os.path.basename(p) == ss.STATS_FILE
    with open(p) as fp:
        doc = json.load(fp)
    assert doc["stats"]["walltime_s"] == 1.0
    assert doc["runinfo"]["sim"] == "vlt"


#---------------------------------------------------------------------------
# Suite aggregation
#---------------------------------------------------------------------------

def test_aggregate():
    agg = ss.aggregate([
        {"walltime_s": 1.0, "maxrss_mb": 100, "errors": 0},
        {"walltime_s": 3.0, "maxrss_mb": 250, "errors": 2, "simtime_s": 1e-3},
    ])
    assert agg["walltime_s"] == 4.0            # sum
    assert agg["walltime_s_max"] == 3.0
    assert agg["walltime_s_mean"] == 2.0
    assert agg["maxrss_mb_max"] == 250         # max-only key: no sum/mean
    assert "maxrss_mb" not in agg
    assert agg["errors"] == 2
    assert agg["simtime_s"] == 1e-3            # only one case reported it


def test_aggregate_ignores_unmeasured_keys():
    # A key no case reported must be absent, not 0 -- absent means "not
    # measured here", and a 0 would read as a real measurement.
    agg = ss.aggregate([{"walltime_s": 1.0}, {}])
    assert "maxrss_mb_max" not in agg and "simtime_s" not in agg


def test_aggregate_empty():
    assert ss.aggregate([]) == {}


def test_cov_keys_declared():
    # Every coverage kind has a max-rolled percentage and per-case counts.
    for k in ("line", "branch", "toggle", "covergroup", "user"):
        assert ss.STAT_KEYS["cov_%s_pct" % k][1] == "max"
        assert ss.STAT_KEYS["cov_%s_covered" % k][1] == "none"
        assert ss.STAT_KEYS["cov_%s_total" % k][1] == "none"
    assert "cov" in ss.INFO_KEYS


def test_aggregate_cov():
    # The percentage rolls up as the best run; hit counts are not summed
    # (summing per-run hits is not a merge).
    agg = ss.aggregate([
        {"cov_line_pct": 40.0, "cov_line_covered": 4, "cov_line_total": 10},
        {"cov_line_pct": 70.0, "cov_line_covered": 7, "cov_line_total": 10},
    ])
    assert agg["cov_line_pct_max"] == 70.0
    assert "cov_line_pct" not in agg and "cov_line_pct_mean" not in agg
    assert "cov_line_covered" not in agg and "cov_line_total" not in agg


#---------------------------------------------------------------------------
# Tier 2: Verilator simulation-report parsing
#---------------------------------------------------------------------------

_VLT_TAIL = """UVM_INFO ... [TEST_DONE] finishing
- t.sv:8: Verilog $finish
- S i m u l a t i o n   R e p o r t: Verilator 5.049 devel
- Verilator: $finish at 608us; walltime 5.280 s; speed 115.202 us/s
- Verilator: cpu 5.276 s on 4 threads; allocated 396 MB
"""


def _write_log(tmpdir, text):
    p = os.path.join(str(tmpdir), "sim.log")
    with open(p, "w") as fp:
        fp.write(text)
    return p


def test_vlt_parse_sim_stats(tmpdir):
    s = VltSimRunner().parse_sim_stats(_write_log(tmpdir, _VLT_TAIL))
    assert s["sim_version"] == "Verilator 5.049 devel"
    assert s["finish_reason"] == "$finish"
    assert s["simtime"] == "608us"
    assert s["sim_walltime_s"] == 5.280
    assert s["sim_cpu_s"] == 5.276
    assert s["threads"] == 4
    assert s["sim_mem_mb"] == 396.0


def test_vlt_parse_sim_stats_stop(tmpdir):
    s = VltSimRunner().parse_sim_stats(_write_log(
        tmpdir, "- Verilator: $stop at 12ns; walltime 0.100 s; speed 1.000 ns/s\n"))
    assert s["finish_reason"] == "$stop"
    assert s["simtime"] == "12ns"


def test_vlt_parse_sim_stats_no_report(tmpdir):
    # +verilator+quiet, or an image built with a custom main that never calls
    # statsPrintSummary: report nothing rather than guessing.
    assert VltSimRunner().parse_sim_stats(
        _write_log(tmpdir, "UVM_INFO nothing to see here\n")) == {}


def test_vlt_parse_sim_stats_missing_log(tmpdir):
    assert VltSimRunner().parse_sim_stats(
        os.path.join(str(tmpdir), "absent.log")) == {}


def test_vlt_parse_sim_stats_finds_report_in_long_log(tmpdir):
    # The parser reads only the tail; the summary is always last.
    s = VltSimRunner().parse_sim_stats(
        _write_log(tmpdir, ("UVM_INFO filler line\n" * 20000) + _VLT_TAIL))
    assert s["simtime"] == "608us"


def test_aggregate_preserves_small_magnitudes():
    # Simulated time is routinely microseconds: fixed-decimal rounding would
    # report a whole suite as having simulated 0 seconds.
    agg = ss.aggregate([{"simtime_s": 2e-6}, {"simtime_s": 5e-6}])
    assert agg["simtime_s"] == pytest.approx(7e-6)
    assert agg["simtime_s_max"] == pytest.approx(5e-6)
