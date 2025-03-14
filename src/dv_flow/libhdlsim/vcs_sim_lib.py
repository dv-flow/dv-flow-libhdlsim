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
from dv_flow.mgr.task_data import TaskMarker, TaskMarkerLoc

class SimLibBuilder(VlSimLibBuilder):

    def getRefTime(self, rundir):
        if os.path.isfile(os.path.join(rundir, 'simlib.d')):
            return os.path.getmtime(os.path.join(rundir, 'simlib.d'))
        else:
            raise Exception("simv file (%s) does not exist" % os.path.join(rundir, 'simlib.d'))
    
    async def build(self, input, files : List[str], incdirs : List[str], libs : List[str]):

        if not os.path.isdir(os.path.join(input.rundir, input.params.libname)):
            os.makedirs(os.path.join(input.rundir, input.params.libname), exist_ok=True)

        # Create a library map
        with open(os.path.join(input.rundir, 'synopsys_sim.setup'), 'w') as fp:
            fp.write("%s: %s\n" % (
                input.params.libname, 
                os.path.join(input.rundir, input.params.libname)))

            for lib in libs:
                fp.write("%s: %s\n" % (os.path.basename(lib), lib))

        cmd = ['vlogan', '-full64', '-sverilog', '-work', input.params.libname]

        if len(libs):
            cmd.extend(['-liblist', "+".join(os.path.basename(l) for l in libs)])

        for incdir in incdirs:
            cmd.append('+incdir+%s' % incdir)

        cmd.extend(files)

        self._log.debug("Running vlogan: %s", " ".join(cmd))

        fp = open(os.path.join(input.rundir, 'build.log'), "w")
        fp.write("Command: %s" % str(cmd))
        fp.flush()
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=input.rundir,
            stdout=fp,
            stderr=asyncio.subprocess.STDOUT)

        await proc.wait()
        fp.close()

        # Pull in error/warning markers
        self.parseLog(os.path.join(input.rundir, 'build.log'))

        if proc.returncode != 0:
            self.markers.append(
                TaskMarker(
                    severity="error", 
                    msg="vlogan command failed"))
        else:
            Path(os.path.join(input.rundir, 'simlib.d')).touch()

        return proc.returncode

async def SimLib(runner, input):
    builder = SimLibBuilder()
    return await builder.run(runner, input)

