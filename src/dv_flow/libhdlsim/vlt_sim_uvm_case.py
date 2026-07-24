#****************************************************************************
#* vlt_sim_uvm_case.py
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
"""Verilator `SimUVMCase`: run one UVM test AND check its verdict in a single
leaf task.

Reuses the Verilator `SimRunner` (`VLSimRunner`) for the run -- so image
handling, DPI/VPI, artifact collection, and the `mode: test` marker handling all
come for free -- then parses the UVM report summary and emits a `TestResult`.
Being a single leaf task (not a compound) it is safe to instantiate many times
in one flow, unlike the compound form whose subtask node names collide.
"""

import os
from dv_flow.mgr import TaskDataResult
from dv_flow.libhdlsim.vlt_sim_run import SimRunner
from dv_flow.libhdlsim import uvm_log_parser
from dv_flow.libhdlsim.sim_check import _as_fileset, _artifacts


class UVMCaseRunner(SimRunner):
    """`SimRunner` (Verilator) that composes +UVM_TESTNAME, forces test mode,
    runs, then interprets the UVM log into a TestResult."""

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
        sim = getattr(srr, "sim", "") if srr is not None else ""
        walltime = getattr(srr, "walltime_s", 0.0) if srr is not None else 0.0
        artifacts = _artifacts(srr) if srr is not None else []

        # The run wrote sim.log into this task's rundir (set by the base run).
        log_path = os.path.join(self.rundir, "sim.log")
        parsed = uvm_log_parser.parse_uvm_log(log_path)

        name = getattr(input.params, "name", "") or testname or input.name

        tr = ctxt.mkDataItem(
            "hdlsim.TestResult",
            testname=testname, sim=sim, status=parsed["status"],
            passed=parsed["passed"], run_status=run_status,
            errors=parsed["errors"], warnings=parsed["warnings"],
            fatals=parsed["fatals"], seed=0, walltime_s=walltime,
            artifacts=[_as_fileset(a) for a in artifacts])
        tr.name = name
        tr.src = name  # distinct per case -> no dedup when a report gathers cases

        if not parsed["passed"]:
            # Verdict-as-data: report a fail via info, not an Error marker.
            ctxt.info("Test '%s' (%s) %s: UVM_ERROR=%d UVM_FATAL=%d (exit=%d)" % (
                name, testname, parsed["status"],
                parsed["errors"], parsed["fatals"], run_status))

        # Base infra markers (e.g. missing image) are preserved; the base run
        # already stripped the "Command failed" marker in test mode.
        return TaskDataResult(status=0, markers=base.markers, output=[tr])


async def SimUVMCase(runner, input) -> TaskDataResult:
    return await UVMCaseRunner().run(runner, input)
