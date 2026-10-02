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
from typing import List
from dv_flow.mgr import TaskDataResult, FileSet
from dv_flow.mgr.task_data import TaskMarker, SeverityE
from dv_flow.libhdlsim.vl_sim_runner import VLSimRunner
from dv_flow.libhdlsim.sim_uvm_case import uvm_case_task
from dv_flow.libhdlsim.vl_sim_data import VlSimRunData

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

        cmd = [
            'vsim',
            '-batch',
            '-do',
            "run -a; quit -f",
            "simv_opt",
            "-work",
            os.path.join(data.imgdir, 'work')
        ]

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

async def SimRun(runner, input) -> TaskDataResult:
    return await SimRunner().run(runner, input)

SimUVMCase = uvm_case_task(SimRunner)
