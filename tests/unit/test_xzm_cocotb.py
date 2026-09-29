#****************************************************************************
#* test_xzm_cocotb.py
#*
#* A cocotb test through hdlsim.xzm SimImage/SimRun. xezim isn't a
#* cocotb-known simulator: cocotb's Icarus VPI library works because it
#* exports vlog_startup_routines, which is all xezim calls. The entrypoint
#* attribute cocotb flows attach is ignored with a Warning.
#*
#* cocotb is found through `cocotb-config` on PATH (it can live in a
#* different Python environment from the one running this test).
#****************************************************************************
import asyncio
import os
import shutil
import subprocess
import pytest
from dv_flow.mgr import TaskListenerLog, TaskSetRunner, PackageLoader
from dv_flow.mgr.task_data import SeverityE
from dv_flow.mgr.task_graph_builder import TaskGraphBuilder

DATA_DIR = os.path.join(os.path.dirname(__file__), "data", "xzm", "cocotb")
COCOTB_CONFIG = shutil.which("cocotb-config")

pytestmark = [
    pytest.mark.skipif(shutil.which("xezim") is None, reason="xezim not available"),
    pytest.mark.skipif(COCOTB_CONFIG is None, reason="cocotb-config not on PATH"),
]


def _cfg(*args):
    return subprocess.check_output([COCOTB_CONFIG] + list(args), text=True).strip()


def test_cocotb_via_vpi(tmpdir, monkeypatch):
    lib = _cfg("--lib-name-path", "vpi", "icarus")
    entry = _cfg("--lib-entry", "vpi", "icarus")

    # cocotb's own environment; the flow passes the process env to the run.
    monkeypatch.setenv("GPI_USERS", "%s;%s" % (_cfg("--libpython"),
                                               _cfg("--pygpi-entry-point")))
    monkeypatch.setenv("PYGPI_PYTHON_BIN", _cfg("--python-bin"))
    monkeypatch.setenv("COCOTB_TEST_MODULES", "xzm_cocotb_tests")
    monkeypatch.setenv("COCOTB_TOPLEVEL", "xzm_cocotb_dut")
    monkeypatch.setenv("TOPLEVEL_LANG", "verilog")
    monkeypatch.setenv("PYTHONPATH", DATA_DIR)

    rundir = os.path.join(str(tmpdir), "rundir")
    runner = TaskSetRunner(rundir)
    builder = TaskGraphBuilder(
        PackageLoader().load_rgy(["std", "hdlsim.xzm"]), rundir)
    runner.builder = builder
    tasks = {}
    runner.add_listener(
        lambda t, r: tasks.__setitem__(t.name, t) if r == "leave" else None)
    runner.add_listener(TaskListenerLog().event)

    src = builder.mkTaskNode("std.FileSet", name="src", type="systemVerilogSource",
                             base=DATA_DIR, include="xzm_cocotb_dut.sv")
    vpi = builder.mkTaskNode("std.FileSet", name="vpi", type="verilogVPI",
                             base=os.path.dirname(lib),
                             include=os.path.basename(lib),
                             attributes=["entrypoint=%s" % entry])
    img = builder.mkTaskNode("hdlsim.xzm.SimImage", name="sim_img",
                             needs=[src, vpi], top=["xzm_cocotb_dut"])
    run = builder.mkTaskNode("hdlsim.xzm.SimRun", name="sim_run", needs=[img])

    asyncio.run(runner.run([run]))
    assert runner.status == 0

    with open(os.path.join(rundir, "sim_run", "sim.log")) as fp:
        log = fp.read()
    assert "TESTS=1 PASS=1 FAIL=0" in log, log[-2000:]

    warns = [m for m in tasks["sim_run"].result.markers
             if m.severity == SeverityE.Warning]
    assert any("entrypoint" in m.msg for m in warns)
