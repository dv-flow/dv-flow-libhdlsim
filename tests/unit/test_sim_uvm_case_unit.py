#****************************************************************************
#* test_sim_uvm_case_unit.py
#*
#* The shared SimUVMCase pieces without a simulator: the class uvm_case_task
#* builds, and where the mixin looks for the run log.
#****************************************************************************
import os
import shutil
import asyncio
import types
from dv_flow.mgr import TaskDataResult
from dv_flow.libhdlsim.vl_sim_runner import VLSimRunner
from dv_flow.libhdlsim.sim_uvm_case import UVMCaseMixin, uvm_case_task
from dv_flow.libhdlsim.vlt_sim_run import SimRunner as VltRunner

UVM_LOGS = os.path.join(os.path.dirname(__file__), "data", "uvm_logs")


def test_case_class_mro():
    task = uvm_case_task(VltRunner)
    cls = task.case_cls
    assert cls.__mro__[:3] == (cls, UVMCaseMixin, VltRunner)
    assert issubclass(cls, VLSimRunner)
    assert cls.sim_name == "vlt"
    assert cls.__name__ == "VltUVMCaseRunner"


class _Ctxt:
    def __init__(self):
        self.infos = []

    def mkDataItem(self, type_, **kw):
        return types.SimpleNamespace(type=type_, **kw)

    def info(self, msg):
        self.infos.append(msg)


class _FakeRunner(VLSimRunner):
    """Stands in for a backend whose run log is not named sim.log."""
    sim_name = "fake"
    logname = "custom_run.log"
    src_log = "pass_sw_copy.log"

    async def run(self, ctxt, input):
        self.rundir = input.rundir
        self._runinfo["logfile"] = self.logname
        shutil.copy(os.path.join(UVM_LOGS, self.src_log),
                    os.path.join(self.rundir, self.logname))
        srr = types.SimpleNamespace(type="hdlsim.SimRunResult", status=0,
                                    sim=self.sim_name, walltime_s=0.0,
                                    artifacts=[], stats={}, runinfo={})
        return TaskDataResult(status=0, markers=[], output=[srr])


def _input(tmpdir):
    params = types.SimpleNamespace(testname="t", plusargs=[], mode="run",
                                   name="")
    return types.SimpleNamespace(params=params, rundir=str(tmpdir), name="c")


def test_mixin_reads_logfile_from_runinfo(tmpdir):
    task = uvm_case_task(_FakeRunner)
    res = asyncio.run(task(_Ctxt(), _input(tmpdir)))
    tr = res.output[0]
    assert tr.passed is True
    assert tr.sim == "fake"


def test_mixin_parses_named_log_not_sim_log(tmpdir):
    # A failing sim.log alongside a passing custom log: the verdict must come
    # from the log the runner named.
    class _Runner(_FakeRunner):
        src_log = "fail_uvm_error.log"
    shutil.copy(os.path.join(UVM_LOGS, "pass_sw_copy.log"),
                os.path.join(str(tmpdir), "sim.log"))
    task = uvm_case_task(_Runner)
    res = asyncio.run(task(_Ctxt(), _input(tmpdir)))
    assert res.output[0].passed is False


def test_mixin_composes_testname_and_test_mode(tmpdir):
    inp = _input(tmpdir)
    inp.params.plusargs = ["X=1"]
    asyncio.run(uvm_case_task(_FakeRunner)(_Ctxt(), inp))
    assert inp.params.plusargs == ["UVM_TESTNAME=t", "X=1"]
    assert inp.params.mode == "test"
