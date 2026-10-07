#****************************************************************************
#* mti_sim_run.py
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
#* Created on:
#*     Author: 
#*
#****************************************************************************
import asyncio
import json
import os
from typing import Dict, List, Tuple
from dv_flow.mgr import TaskDataResult, FileSet
from dv_flow.mgr.task_data import TaskMarker, SeverityE
from dv_flow.libhdlsim import cov
from dv_flow.libhdlsim.vl_sim_runner import VLSimRunner
from dv_flow.libhdlsim.sim_uvm_case import uvm_case_task
from dv_flow.libhdlsim.vl_sim_data import VlSimRunData

# Coverage level -> (kinds, vopt +cover= items). Covergroups and cover
# directives are recorded without +cover; it adds code coverage.
MTI_COV = {
    "func": (["covergroup", "user"], None),
    "code": (["covergroup", "user", "line", "branch", "expr"], "sbce"),
    "full": (["covergroup", "user", "line", "branch", "expr",
              "toggle", "fsm_state", "fsm_arc"], "sbceft"),
}

# The run's coverage database, saved by vsim at exit
COV_DB = "cov.ucdb"

class SimRunner(VLSimRunner):
    sim_name = "mti"

    def check_pli(self, data : VlSimRunData) -> int:
        # Questa binds PLI 1.0 systfs through the library's veriusertfs or
        # init_usertfs(), or a -tab file. It has no lib:boot form.
        for lib in data.plilibs:
            if lib.boot and not lib.tab:
                self.markers.append(TaskMarker(
                    severity=SeverityE.Warning,
                    msg="Questa ignores `boot` (%s) for PLI 1.0; library %s must "
                        "export veriusertfs or init_usertfs" % (lib.boot, lib.path)))
        return 0

    async def runsim(self, data : VlSimRunData):
        status = 0

        do = "run -a; quit -f"
        cov_on = data.cov is not None and data.cov.get("level") in MTI_COV
        if cov_on:
            # -onexit: saved however the run ends ($finish, an error, ...)
            do = "coverage save -onexit %s; %s" % (
                os.path.join(self.rundir, COV_DB), do)

        cmd = [
            'vsim',
            '-batch',
            '-do',
            do,
            "simv_opt",
            "-work",
            os.path.join(data.imgdir, 'work')
        ]

        if cov_on:
            cmd.append('-coverage')

        if data.valgrind:
            cmd.extend(["-valgrind", "--tool=memcheck"])

        if data.full64:
            cmd.append('-64')

        for pli_path, entrypoint in data.vpilibs:
            if entrypoint:
                cmd.extend(['-pli', f'{pli_path}:{entrypoint}'])
            else:
                cmd.extend(['-pli', pli_path])

        for lib in data.plilibs:
            cmd.extend(['-pli', lib.path])
            if lib.tab:
                cmd.extend(['-tab', lib.tab])

        for dpi in data.dpilibs:
            dpi_libdir = os.path.dirname(dpi)
            dpi_file = os.path.basename(dpi)
            if dpi_file.rfind('.') > 0:
                dpi_file = dpi_file[:dpi_file.rfind('.')]
            cmd.extend(['-sv_lib', os.path.join(dpi_libdir, dpi_file)])

        for plusarg in data.plusargs:
            cmd.append("+%s" % plusarg)
        for arg in data.args:
            cmd.append(arg)

        status |= await self.exec_sim(cmd, logfile="sim.log")
        
        return status

    def parse_cov_summary(self, rundir, cov_info):
        db = os.path.join(rundir, COV_DB)
        if not os.path.isfile(db):
            return {}
        vcover = self._which("vcover", sibling_of="vsim")
        if vcover is None:
            self._log.debug("vcover not found; no coverage summary")
            return {}
        out = self._run_report([vcover, "report", "-summary", db])
        if out is None:
            return {}
        return cov.parse_mti_cov_summary(out, cov_info.get("kinds"))

    def _artifact_spec(self) -> Dict[str, Tuple]:
        spec = super()._artifact_spec()
        spec["simCovDb"] = ([COV_DB], "cov", ["format=%s" % cov.FORMAT_QUESTA_UCDB])
        return spec

async def SimRun(runner, input) -> TaskDataResult:
    return await SimRunner().run(runner, input)

SimUVMCase = uvm_case_task(SimRunner)
