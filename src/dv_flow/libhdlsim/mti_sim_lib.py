#****************************************************************************
#* mti_sim_lib.py
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
import asyncio
from typing import List
from dv_flow.mgr import TaskData
from dv_flow.libhdlsim.vl_sim_lib_builder import VlSimLibBuilder
from dv_flow.libhdlsim.vl_sim_data import VlSimImageData

class SimLibBuilder(VlSimLibBuilder):

    def getRefTime(self, rundir):
        if os.path.isfile(os.path.join(rundir, 'simv_opt.d')):
            return os.path.getmtime(os.path.join(rundir, 'simv_opt.d'))
        else:
            raise Exception("simv_opt.d file (%s) does not exist" % os.path.join(rundir, 'simv_opt.d'))
    
    async def build(self, input, data : VlSimImageData):
        cmd = []

        status = 0

        libname = input.params.libname
        if not os.path.isdir(os.path.join(input.rundir, libname)):
            cmd = ['vlib', libname]

            status |= await self.runner.exec(cmd, logfile="vlib.log")

        if not status:
            cmd = ['vlog', '-sv', '-work', libname]

            for incdir in data.incdirs:
                cmd.append('+incdir+%s' % incdir)
            for define in data.defines:
                cmd.append('+define+%s' % define)

            cmd.extend(data.args)
            cmd.extend(data.compargs)

            cmd.extend(data.files)

            status |= await self.runner.exec(cmd, logfile="build.log")
        
        return status

async def SimLib(runner, input):
    builder = SimLibBuilder(runner)
    return await builder.run(runner, input)
