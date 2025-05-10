#****************************************************************************
#* vcs_sim_lib.py
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
import json
import shutil
from pathlib import Path
from typing import List
from dv_flow.libhdlsim.vl_sim_lib_builder import VlSimLibBuilder
from dv_flow.libhdlsim.vl_sim_data import VlSimImageData
from dv_flow.mgr.task_data import TaskMarker, TaskMarkerLoc

class SimLibBuilder(VlSimLibBuilder):

    def getRefTime(self, rundir):
        if os.path.isfile(os.path.join(rundir, 'simlib.d')):
            return os.path.getmtime(os.path.join(rundir, 'simlib.d'))
        else:
            raise Exception("simv file (%s) does not exist" % os.path.join(rundir, 'simlib.d'))
    
    async def build(self, input, data : VlSimImageData):

        status = 0

        if not os.path.isdir(os.path.join(input.rundir, input.params.libname)):
            os.makedirs(os.path.join(input.rundir, input.params.libname), exist_ok=True)

        # Create a library map
        data.libs.insert(0, os.path.join(input.rundir, input.params.libname))
        self.runner.create("synopsys_sim.setup", 
                           "\n".join(("%s: %s\n" % (os.path.basename(lib), lib)) for lib in data.libs))
        cmd = ['vlogan', '-full64', '-sverilog', '-work', input.params.libname]

        for incdir in data.incdirs:
            cmd.append('+incdir+%s' % incdir)
        for define in data.defines:
            cmd.append('+define+%s' % define)

        cmd.extend(data.args)
        cmd.extend(data.compargs)

        cmd.extend(data.files)


        status |= await self.runner.exec(cmd, logfile="vlogan.log")

        # Pull in error/warning markers
        self.parseLog(os.path.join(input.rundir, 'vlogan.log'))

        if not status:
            Path(os.path.join(input.rundir, 'simlib.d')).touch()

        return status

async def SimLib(runner, input):
    builder = SimLibBuilder(runner)
    return await builder.run(runner, input)

