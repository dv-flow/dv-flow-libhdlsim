#****************************************************************************
#* vlt_sim_image.py
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
import os
import logging
from typing import ClassVar, List
from dv_flow.mgr import TaskDataResult, TaskRunCtxt
from dv_flow.libhdlsim.vl_sim_image_builder import VlSimImageBuilder
from dv_flow.libhdlsim.vl_sim_data import VlSimImageData
from dv_flow.mgr.task_data import TaskMarker, TaskMarkerLoc

class SimImageBuilder(VlSimImageBuilder):

    _log : ClassVar = logging.getLogger("SimImageBuilder[vlt]")

    def getRefTime(self, rundir):
        if os.path.isfile(os.path.join(rundir, 'obj_dir/simv')):
            return os.path.getmtime(os.path.join(rundir, 'obj_dir/simv'))
        else:
            raise Exception("simv file (%s) does not exist" % os.path.join(rundir, 'obj_dir/simv'))

    async def build(self, input, data : VlSimImageData):
        status = 0
        cmd = ['verilator', '--binary', '-o', 'simv', '-Wno-fatal']

        cmd.extend(['-j', '0'])

        for incdir in data.incdirs:
            cmd.append('+incdir+%s' % incdir)
        for define in data.defines:
            cmd.append('+define+%s' % define)

        if data.trace:
            cmd.append('--trace')

        for dpi in data.dpi:
            dir = os.path.dirname(dpi)
            lib = os.path.splitext(os.path.basename(dpi))[0]

            if lib.startswith('lib'):
                lib = lib[3:]

            cmd.append('-LDFLAGS')
            cmd.append('-L%s' % dir)
            cmd.append('-LDFLAGS')
            cmd.append('-l%s' % lib)
            cmd.append('-LDFLAGS')
            cmd.append('-Wl,-rpath,%s' % dir)

        if len(data.dpi):
            cmd.extend(["-LDFLAGS", "-Wl,--export-dynamic"])

        if len(data.vpi) > 0:
            raise Exception("VPI not supported in VLT")

        cmd.extend(data.args)
        cmd.extend(data.compargs)
        cmd.extend(data.elabargs)

        cmd.extend(data.files)

        cmd.extend(data.csource)

        for top in input.params.top:
            cmd.extend(['--top-module', top])

        status |= await self.runner.exec(cmd, logfile="build.log")

        # Parse the log for warnings and error
        self.parseLog(os.path.join(input.rundir, 'build.log'))

        return status

async def SimImage(runner, input) -> TaskDataResult:
    builder = SimImageBuilder(runner)
    return await builder.run(runner, input)

