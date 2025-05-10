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
from dv_flow.libhdlsim.vl_sim_data import VlSimImageData

class SimImage(VlSimImage):

    def getRefTime(self, rundir):
        if os.path.isfile(os.path.join(rundir, 'simv_opt.d')):
            return os.path.getmtime(os.path.join(rundir, 'simv_opt.d'))
        else:
            raise Exception("simv_opt.d file (%s) does not exist" % os.path.join(rundir, 'simv_opt.d'))
    
    async def build(self, data : VlSimImageData):
        cmd = []
        status = 0

        cmd = ['xmvlog', '-sv', '-64bit']

        for incdir in data.incdirs:
            cmd.extend(['-incdir', incdir])
        
        for define in data.defines:
            cmd.extend(['-define', define])

        cmd.extend(data.args)
        cmd.extend(data.compargs)

        cmd.extend(data.files)

        status |= await self.runnner.exec(cmd, logfile="xmvlog.log")

        # Now, run vopt
        if not status:
            cmd = ['xmelab', '-64bit', '-snap', 'simv:snap']
            for top in self.params.top:
                cmd.append(top)

            cmd.extend(data.args)
            cmd.extend(data.elabargs)

            status |= await self.runner.exec(cmd, logfile="xmelab.log")

        return status
