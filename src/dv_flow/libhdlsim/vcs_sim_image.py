#****************************************************************************
#* vcs_sim_image.py
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
from typing import List
from dv_flow.libhdlsim.vl_sim_image_builder import VlSimImageBuilder
from dv_flow.libhdlsim.vl_sim_data import VlSimImageData

class SimImageBuilder(VlSimImageBuilder):

    def getRefTime(self, rundir):
        if os.path.isfile(os.path.join(rundir, 'simv')):
            return os.path.getmtime(os.path.join(rundir, 'simv'))
        else:
            raise Exception("simv file (%s) does not exist" % os.path.join(rundir, 'simv'))
    
    async def build(self, input, data : VlSimImageData):

        status = 0

        if len(data.files):
            data.libs.append(os.path.join(input.rundir, 'work'))

        # Create the library map
        self.runner.create("synopsys_sim.setup", 
                           "\n".join(("%s: %s" % (os.path.basename(lib), lib)) for lib in data.libs))

        # If source is provided, then compile that to a 'work' library
        if len(data.files):
            self._log.debug("Building source files: %s" % str(data.files))

            cmd = ['vlogan', '-full64', '-sverilog', '-work', 'work']

            for incdir in data.incdirs:
                cmd.append('+incdir+%s' % incdir)
            for define in data.defines:
                cmd.append('+define+%s' % define)

            cmd.extend(data.args)
            cmd.extend(data.compargs)

            cmd.extend(data.files)

            status |= await self.runner.exec(cmd, logfile="vlogan.log")

            self.parseLog(os.path.join(input.rundir, 'vlogan.log'))

        if status == 0:
            cmd = ['vcs', '-full64', '-partcomp', '-fastpartcomp=j4']
            cmd.extend(data.args)
            cmd.extend(data.elabargs)

            if len(data.vpi):
                cmd.extend(["+vpi", "-debug_access"])

                for lib in data.vpi:
                    cmd.extend(["-load", lib])

            if len(data.dpi):
                raise Exception("DPI not yet supported") 

            cmd.extend(self.input.params.args)

            cmd.extend(data.csource)

            # Seems that VCS behaves better with the list in the setup file
#            if len(libs):
#                cmd.extend(['-liblist', "+".join(os.path.basename(l) for l in libs)])

            if len(input.params.top):
                cmd.extend(['-top', "+".join(input.params.top)])

                self._log.debug("VCS command: %s" % str(cmd))

            status |= await self.runner.exec(cmd, logfile="vcs.log")

            # Pull in error/warning markers
            self.parseLog(os.path.join(input.rundir, 'vcs.log'))

        return status

async def SimImage(runner, input):
    builder = SimImageBuilder(runner)
    return await builder.run(runner, input)

