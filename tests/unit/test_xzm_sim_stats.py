#****************************************************************************
#* test_xzm_sim_stats.py
#*
#* xzm SimRunner's log-derived stats, against xezim 0.11.0 run output
#* (data/xzm_logs/run_*.log). No simulator needed.
#****************************************************************************
import os
from dv_flow.libhdlsim import sim_stats
from dv_flow.libhdlsim.xzm_sim_run import SimRunner

LOGS = os.path.join(os.path.dirname(__file__), "data", "xzm_logs")


def _stats(name):
    return SimRunner().parse_sim_stats(os.path.join(LOGS, name))


def test_report_stats_line():
    s = _stats("run_finish.log")
    assert s["simtime"] == "10ns"
    assert s["sim_walltime_s"] == 0.001
    assert s["sim_cpu_s"] == 0.002
    assert s["sim_mem_mb"] == round(22264 / 1024.0, 3)
    assert s["sim_version"] == "xezim 0.11.0 (git 6558a1e6)"
    assert s["finish_reason"] == "$finish"
    # simtime derives simtime_s like every other backend
    assert sim_stats.finalize(dict(s))["simtime_s"] == 10e-9


def test_keys_route_to_stats_and_runinfo():
    s = _stats("run_finish.log")
    for k in ("simtime", "sim_walltime_s", "sim_cpu_s", "sim_mem_mb"):
        assert k in sim_stats.STAT_KEYS
    for k in ("sim_version", "finish_reason", "seed", "seed_source"):
        assert k in sim_stats.INFO_KEYS


def test_max_time_finish_reason():
    s = _stats("run_max_time.log")
    assert s["finish_reason"] == "max_time"
    assert s["simtime"] == "100ns"


def test_hang_report_detected():
    r = SimRunner()
    assert r._hang_report(os.path.join(LOGS, "run_max_time.log")) == \
        "(100 ticks) without $finish"
    assert r._hang_report(os.path.join(LOGS, "run_finish.log")) is None


def test_missing_stats_line():
    s = _stats("run_no_stats.log")
    assert "simtime" not in s
    assert "sim_version" not in s
    assert s["finish_reason"] == "$finish"


def test_default_seed():
    s = _stats("run_finish.log")
    assert s["seed"] == 1
    assert s["seed_source"] == "default"


def test_missing_log():
    assert SimRunner().parse_sim_stats(os.path.join(LOGS, "nope.log")) == {}
