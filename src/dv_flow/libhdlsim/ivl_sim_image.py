#****************************************************************************
#* ivl_sim_image.py
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
from dv_flow.mgr import TaskData
from dv_flow.libhdlsim.vl_sim_image_builder import VlSimImageBuilder
from dv_flow.libhdlsim.vl_sim_data import VlSimImageData

class SimImageBuilder(VlSimImageBuilder):

    def getRefTime(self, rundir):
        if os.path.isfile(os.path.join(rundir, 'simv.vpp')):
            print("Returning timestamp")
            return os.path.getmtime(os.path.join(rundir, 'simv.vpp'))
        else:
            raise Exception("simv file (%s) does not exist" % os.path.join(rundir, 'simv.vpp'))
    
    async def build(self, input, data : VlSimImageData):
        status = 0
        cmd = ['iverilog', '-o', 'simv.vpp', '-g2012']

        for incdir in data.incdirs:
            cmd.extend(['-I', incdir])

        for define in data.defines:
            cmd.extend(['-D', define])

        cmd.extend(data.args)
        cmd.extend(data.compargs)
        cmd.extend(data.elabargs)

        cmd.extend(data.files)

        for top in data.top:
            cmd.extend(['-s', top])

        status |= await self.runner.exec(cmd, logfile="iverilog.log")

        return status

async def SimImage(ctxt, input):
    return await SimImageBuilder(ctxt).run(ctxt, input)
