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
import shutil
from typing import List
from dv_flow.mgr import Task, TaskData, FileSet
from dv_flow.libhdlsim.vl_sim_image_builder import VlSimImage

class SimRun(Task):

    async def run(self, input : TaskData) -> TaskData:
        vl_fileset = input.getFileSets("simDir")

        build_dir = vl_fileset[0].basedir

        # First  things first: link in the library
        os.symlink(
            src=os.path.join(build_dir, "xcelium.d"),
            dst=self.rundir)

        cmd = ['xmsim', '-64bit', 'simv:snap' ]

        fp = open(os.path.join(self.rundir, 'sim.log'), "w")
        proc = await self.session.create_subprocess(*cmd,
                                                    cwd=self.rundir,
                                                    stdout=fp)

        await proc.wait()

        fp.close()

        if proc.returncode != 0:
            raise Exception("xmsim failed (%d)" % proc.returncode)

        output = TaskData()
        output.addFileSet(FileSet(src=self.name, type="simRunDir", basedir=self.rundir))

        return output
    pass
