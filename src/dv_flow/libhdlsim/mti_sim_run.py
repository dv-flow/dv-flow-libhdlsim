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
from dv_flow.libhdlsim.vl_sim_runner import VLSimRunner
from dv_flow.libhdlsim.vl_sim_data import VlSimRunData

class SimRunner(VLSimRunner):
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

        for pli in data.vpilibs:
            cmd.extend(['-pli', pli])
        
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

        status |= await self.ctxt.exec(cmd, logfile="sim.log")
        
        return status

async def SimRun(runner, input) -> TaskDataResult:
    return await SimRunner().run(runner, input)
