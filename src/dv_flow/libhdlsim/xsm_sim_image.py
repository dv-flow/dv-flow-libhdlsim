#****************************************************************************
#* xsm_sim_image.py
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

        cmd = ['xvlog', '--sv']

        for incdir in data.incdirs:
            if len(incdir.strip()) > 0:
                cmd.extend(['-i', incdir])

        for define in data.defines:
            cmd.extend(['-d', define])

        cmd.extend(data.args)
        cmd.extend(data.compargs)

        cmd.extend(data.files)
        cmd.extend(data.csource)

        status |= await self.runner.exec(cmd, logfile="xvlog.log")

        self.parseLog(os.path.join(input.rundir, "xvlog.log"))

        # Now, run xelab
        if not status:
            cmd = ['xelab', '--snapshot', 'simv.snap']
            for top in data.top:
                cmd.append(top)

            cmd.extend(data.args)
            cmd.extend(data.elabargs)

            if len(data.dpi) > 0:
                for dpi in data.dpi:
                    dpi = os.path.splitext(dpi)[0]  # Remove file extension
                    cmd.extend([
                        '--sv_root', os.path.dirname(dpi), 
                        '--sv_lib', os.path.basename(dpi)])

            if len(data.vpi) > 0:
                raise Exception("VPI not supported in xsim")

            status |= await self.runner.exec(cmd, logfile="xelab.log")

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
    return await SimImageBuilder(runner).run(runner, input)
