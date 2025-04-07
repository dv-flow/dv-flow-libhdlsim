#****************************************************************************
#* vcs_sim_run.py
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
from dv_flow.libhdlsim.log_parser import LogParser
from dv_flow.libhdlsim.vl_sim_runner import VLSimRunner

class SimRunner(VLSimRunner):

    async def runsim(self, imgdir, dpi, vpi):

        cmd = [
            os.path.join(imgdir, 'simv'),
        ]

        for lib in dpi:
            cmd.append("-sv_lib")
            cmd.append(lib.splitext()[0])

        cmd.extend(self.args)

        cmd.extend(["+%s" % p for p in self.plusargs])

        fp = open(os.path.join(self.rundir, 'sim.log'), "w")
        fp.write("Command: %s\n" % str(cmd))
        fp.flush()

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=self.rundir,
            stdout=fp,
            stderr=asyncio.subprocess.STDOUT)

        status = await proc.wait()

        fp.close()

        return status

async def SimRun(runner, input) -> TaskDataResult:
    return await SimRunner().run(runner, input)
