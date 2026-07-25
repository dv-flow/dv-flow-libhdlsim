#****************************************************************************
#* xsm_sim_run.py
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
from dv_flow.mgr import TaskDataInput, TaskDataResult, FileSet
from dv_flow.libhdlsim.vl_sim_runner import VLSimRunner
from dv_flow.libhdlsim.vl_sim_data import VlSimRunData

class SimRunner(VLSimRunner):
    sim_name = "xsm"


    async def runsim(self, data : VlSimRunData):
        status = 0

        cmd = [
            'xsim',
            '--xsimdir',
            os.path.join(data.imgdir, "xsim.dir"),
            'simv.snap',
            '--runall'
        ]

        cmd.extend(data.args)

        if len(data.vpilibs):
            raise Exception("VPI libraries not supported by xsim")

        for plusarg in data.plusargs:
            cmd.extend(["--testplusarg",  plusarg])

        # xsim loads DPI shared libraries at runtime via LD_LIBRARY_PATH.
        env = dict(os.environ)
        if data.dpilibs:
            extra_dirs = ":".join(os.path.dirname(lib) for lib in data.dpilibs)
            existing = env.get("LD_LIBRARY_PATH", "")
            env["LD_LIBRARY_PATH"] = (extra_dirs + ":" + existing) if existing else extra_dirs

        status |= await self.exec_sim(cmd, logfile="sim.log", env=env)

        return status
    
async def SimRun(runner, input : TaskDataInput) -> TaskDataResult:
    return await SimRunner().run(runner, input)
