#****************************************************************************
#* ivl_sim_run.py
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
import os
from typing import List
from dv_flow.mgr import TaskData, FileSet
from dv_flow.libhdlsim.vl_sim_runner import VLSimRunner
from dv_flow.libhdlsim.vl_sim_data import VlSimRunData

class SimRunner(VLSimRunner):

    async def runsim(self, data : VlSimRunData) -> TaskData:
        status = 0

        cmd = [
            'vvp',
            os.path.join(data.imgdir, 'simv.vpp'),
        ]

        if len(data.vpilibs):
            raise Exception("VPI libraries not supported yet")
        
        if len(data.dpilibs):
            raise Exception("Icarus Verilog does not support DPI libraries")

        for plusarg in data.plusargs:
            cmd.append("+%s" % plusarg)

        cmd.extend(data.args)

        status |= await self.ctxt.exec(cmd, logfile="sim.log")

        return status

async def SimRun(runner, input) -> TaskData:
    return await SimRunner().run(runner, input)

