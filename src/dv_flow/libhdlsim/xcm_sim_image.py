#****************************************************************************
#* xcm_sim_image.py
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
from typing import List
from dv_flow.mgr import Task, TaskData
from dv_flow.libhdlsim.vl_sim_image_builder import VlSimImage

class SimImage(VlSimImage):

    def getRefTime(self):
        if os.path.isfile(os.path.join(self.rundir, 'simv_opt.d')):
            print("Returning timestamp")
            return os.path.getmtime(os.path.join(self.rundir, 'simv_opt.d'))
        else:
            raise Exception("simv_opt.d file (%s) does not exist" % os.path.join(self.rundir, 'simv_opt.d'))
    
    async def build(self, files : List[str], incdirs : List[str]):
        cmd = []

        cmd = ['xmvlog', '-sv', '-64bit']

        for incdir in incdirs:
            cmd.extend(['-incdir', incdir])

        cmd.extend(files)

        print("self.basedir=%s" % self.rundir)
        proc = await self.session.create_subprocess(*cmd,
                                                        cwd=self.rundir)
        await proc.wait()

        if proc.returncode != 0:
            raise Exception("xmvlog failed (%d)" % proc.returncode)

        # Now, run vopt
        cmd = ['xmelab', '-64bit', '-snap', 'simv:snap']
        for top in self.params.top:
            cmd.append(top)

        proc = await self.session.create_subprocess(*cmd,
                                                        cwd=self.rundir)
        await proc.wait()

        if proc.returncode != 0:
            raise Exception("xmelab failed (%d)" % proc.returncode)

