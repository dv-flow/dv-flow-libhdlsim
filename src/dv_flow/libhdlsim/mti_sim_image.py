#****************************************************************************
#* mti_sim_image.py
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
from dv_flow.libhdlsim.vl_sim_image_builder import VlSimImageBuilder
from dv_flow.libhdlsim.vl_sim_data import VlSimImageData
from dv_flow.mgr import FileSet

class SimImageBuilder(VlSimImageBuilder):

    def getRefTime(self, rundir):
        if os.path.isfile(os.path.join(rundir, 'simv_opt.d')):
            return os.path.getmtime(os.path.join(rundir, 'simv_opt.d'))
        else:
            raise Exception("simv_opt.d file (%s) does not exist" % os.path.join(rundir, 'simv_opt.d'))
    
    async def build(self, input, data : VlSimImageData):
        cmd = []
        status = 0

        if not os.path.isdir(os.path.join(input.rundir, 'work')):
            cmd = ['vlib', 'work']
            status |= await self.runner.exec(cmd, logfile="vlib.log")

        if not status and (len(data.files) > 0 or len(data.csource) > 0):
            # Now, run vlog
            cmd = ['vlog', '-sv']

            for incdir in data.incdirs:
                cmd.append('+incdir+%s' % incdir)
            for define in data.defines:
                cmd.append('+define+%s' % define)

            cmd.extend(data.args)
            cmd.extend(data.compargs)

            cmd.extend(data.files)

            cmd.extend(data.csource)

            status |= await self.runner.exec(cmd, logfile="build.log")

        # Now, run vopt
        if not status:
            cmd = ['vopt', '-o', 'simv_opt']
            for top in input.params.top:
                cmd.append(top)

            cmd.extend(data.args)
            cmd.extend(data.elabargs)

            # Add in libraries
            for lib in data.libs:
                cmd.extend([
                    '-Ldir', os.path.dirname(lib),
                    '-L', os.path.basename(lib)])
            
            self._log.debug("vopt cmd: %s" % str(cmd))

            status |= await self.runner.exec(cmd, logfile="vopt.log")

        if not status:
            with open(os.path.join(input.rundir, 'simv_opt.d'), "w") as fp:
                fp.write("\n")

        if len(data.dpi):
            for dpi in data.dpi:
                self.output.append(FileSet(
                    basedir=os.path.dirname(dpi),
                    files=[os.path.basename(dpi)],
                    filetype="systemVerilogDPI"
                ))

        return status

async def SimImage(runner, input):
    builder = SimImageBuilder(runner)
    return await builder.run(runner, input)
