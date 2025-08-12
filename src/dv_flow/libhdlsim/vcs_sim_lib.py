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
from .vcs_log_parser import VcsLogParser

class SimLibBuilder(VlSimLibBuilder):

    def getRefTime(self, rundir):
        if os.path.isfile(os.path.join(rundir, 'simlib.d')):
            return os.path.getmtime(os.path.join(rundir, 'simlib.d'))
        else:
            raise Exception("simv file (%s) does not exist" % os.path.join(rundir, 'simlib.d'))
    
    async def build(self, input, data : VlSimImageData):

        status = 0
        changed = False

        rundir = input.rundir
        libname = input.params.libname

        if not os.path.isdir(os.path.join(rundir, libname)):
            os.makedirs(os.path.join(rundir, libname), exist_ok=True)

        # Create a library map
        data.libs.insert(0, os.path.join(rundir, libname))
        self.runner.create("synopsys_sim.setup", 
                           "\n".join(("%s: %s\n" % (os.path.basename(lib), lib)) for lib in data.libs))
        cmd = ['vlogan', '-full64', '-sverilog', '-incr_vlogan',
               '-work', libname]

        for incdir in data.incdirs:
            cmd.append('+incdir+%s' % incdir)
        for define in data.defines:
            cmd.append('+define+%s' % define)

        cmd.extend(data.args)
        cmd.extend(data.compargs)
        cmd.extend(data.files)

        def notify_parsing():
            nonlocal changed
            changed = True

        status |= await self.runner.exec(
            cmd, 
            logfile="vlogan.log",
            logfilter=VcsLogParser(
                notify=lambda m: self.ctxt.add_marker(m),
                notify_parsing=notify_parsing
            ).line)

        if not status:
            Path(os.path.join(rundir, 'simlib.d')).touch()

        return (status, changed)

async def SimLib(runner, input):
    builder = SimLibBuilder(runner)
    return await builder.run(runner, input)
