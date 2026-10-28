#****************************************************************************
#* sim_uvm_case.py
#*
#* Copyright 2023-2025 Matthew Ballance and Contributors
#*
#* Licensed under the Apache License, Version 2.0 (the "License"); you may
#* not use this file except in compliance with the License.
#* You may obtain a copy of the License at:
#*
#*   http://www.apache.org/licenses/LICENSE-2.0
#*
#* Unless required by applicable law or agreed to in writing, software
#* distributed under the License is distributed on an "AS IS" BASIS,
#* WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#* See the License for the specific language governing permissions and
#* limitations under the License.
#*
#****************************************************************************
"""`SimUVMCase`, shared by every UVM-capable backend: run one UVM test AND
check its verdict in a single leaf task.

Reuses the backend's `SimRunner` (a `VLSimRunner`) for the run -- so image
handling, DPI/VPI, artifact collection, and the `mode: test` marker handling all
come for free -- then parses the UVM report summary and emits a `TestResult`.
Being a single leaf task (not a compound) it is safe to instantiate many times
in one flow, unlike the compound form whose subtask node names collide.

A backend enables it with one line in its `*_sim_run.py`:

    SimUVMCase = uvm_case_task(SimRunner)
"""

import os
from dv_flow.mgr import TaskDataResult
from dv_flow.libhdlsim import uvm_log_parser
from dv_flow.libhdlsim.sim_check import fail_reason, mk_test_result


class UVMCaseMixin:
    """Composes +UVM_TESTNAME, forces test mode, runs, then interprets the UVM
    log into a TestResult. Mix in ahead of a `VLSimRunner` subclass; the
    runner supplies the simulator."""

    async def run(self, ctxt, input) -> TaskDataResult:
        testname = getattr(input.params, "testname", "") or ""

        # Compose the run: prepend +UVM_TESTNAME and force test mode so a failing
        # test rides as data (never aborts a suite). The base run copies
        # input.params.plusargs, so mutating it here is local to this task run.
        if testname:
            input.params.plusargs = (
                ["UVM_TESTNAME=%s" % testname] + list(input.params.plusargs))
        input.params.mode = "test"

        base = await super().run(ctxt, input)

        srr = None
        for o in base.output:
            if getattr(o, "type", None) == "hdlsim.SimRunResult":
                srr = o
                break
        run_status = getattr(srr, "status", 1) if srr is not None else 1

        # The run wrote its log into this task's rundir (set by the base run),
        # under whatever name the backend passed to exec_sim.
        logfile = self._runinfo.get("logfile", "sim.log")
        log_path = os.path.join(self.rundir, logfile)
        parsed = uvm_log_parser.parse_uvm_log(log_path, run_status=run_status)

        name = getattr(input.params, "name", "") or testname or input.name

        # Same TestResult as the split SimRun+SimCheck path.
        tr = mk_test_result(ctxt, parsed, srr, name, testname)
        tr.run_status = run_status

        if not parsed["passed"]:
            # Verdict-as-data: report a fail via info, not an Error marker.
            ctxt.info("Test '%s' (%s) %s: %s" % (
                name, testname, parsed["status"], fail_reason(parsed, run_status)))

        # Base infra markers (e.g. missing image) are preserved; the base run
        # already stripped the "Command failed" marker in test mode.
        return TaskDataResult(status=0, markers=base.markers, output=[tr])


def uvm_case_class(runner_cls):
    """The UVM-case runner class for a backend's `SimRunner` class."""
    return type("%sUVMCaseRunner" % runner_cls.sim_name.capitalize(),
                (UVMCaseMixin, runner_cls), {})


def uvm_case_task(runner_cls):
    """Build a SimUVMCase pytask for a backend's `SimRunner` class."""
    case_cls = uvm_case_class(runner_cls)

    async def SimUVMCase(runner, input) -> TaskDataResult:
        return await case_cls().run(runner, input)
    SimUVMCase.case_cls = case_cls
    return SimUVMCase
