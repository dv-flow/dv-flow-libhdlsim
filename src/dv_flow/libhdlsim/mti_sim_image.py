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
from dv_flow.mgr import Task, TaskData
from dv_flow.libhdlsim.vl_sim_image_builder import VlSimImageBuilder

class SimImageBuilder(VlSimImageBuilder):

    def getRefTime(self, rundir):
        if os.path.isfile(os.path.join(rundir, 'simv_opt.d')):
            return os.path.getmtime(os.path.join(rundir, 'simv_opt.d'))
        else:
            raise Exception("simv_opt.d file (%s) does not exist" % os.path.join(rundir, 'simv_opt.d'))
    
    async def build(self, input, files : List[str], incdirs : List[str], libs : List[str]):
        cmd = []

        if not os.path.isdir(os.path.join(input.rundir, 'work')):
            cmd = ['vlib', 'work']
            fp = open(os.path.join(input.rundir, "vlib.log"), "w")
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                cwd=input.rundir,
                stdout=fp,
                stderr=asyncio.subprocess.STDOUT)
            fp.close()

            await proc.wait()

            if proc.returncode != 0:
                raise Exception("vlib failed (%d)" % proc.returncode)

        if len(files) > 0:
            cmd = ['vlog', '-sv']

            for incdir in incdirs:
                cmd.append('+incdir+%s' % incdir)

            cmd.extend(files)

            fp = open(os.path.join(input.rundir, "build.log"), "w")
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                cwd=input.rundir,
                stdout=fp,
                stderr=asyncio.subprocess.STDOUT)

            await proc.wait()
            fp.close()

            if proc.returncode != 0:
                raise Exception("vlog failed (%d)" % proc.returncode)

        # Now, run vopt
        cmd = ['vopt', '-o', 'simv_opt']
        for top in input.params.top:
            cmd.append(top)

        # Add in libraries
        for lib in libs:
            cmd.extend([
                '-Ldir', os.path.dirname(lib),
                '-L', os.path.basename(lib)])
            
        self._log.debug("vopt cmd: %s" % str(cmd))

        fp = open(os.path.join(input.rundir, "elab.log"), "w")
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=input.rundir,
            stdout=fp,
            stderr=asyncio.subprocess.STDOUT)
        await proc.wait()
        fp.close()


        if proc.returncode != 0:
            raise Exception("vopt failed (%d)" % proc.returncode)
        else:
            with open(os.path.join(input.rundir, 'simv_opt.d'), "w") as fp:
                fp.write("\n")

        return proc.returncode

async def SimImage(runner, input):
    builder = SimImageBuilder()
    return await builder.run(runner, input)
