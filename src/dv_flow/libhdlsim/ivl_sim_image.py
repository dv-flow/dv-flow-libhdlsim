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
import shutil
from typing import List
from dv_flow.mgr import TaskData, TaskMarker
from dv_flow.libhdlsim.vl_sim_image_builder import VlSimImageBuilder, VlTaskSimImageMemento
from dv_flow.libhdlsim.vl_sim_data import VlSimImageData
from svdep import FileCollection, TaskCheckUpToDate, TaskBuildFileCollection

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

        ex_memento = input.memento
        in_changed = (ex_memento is None or input.changed)

        self._log.debug("in_changed: %s ; ex_memento: %s input.changed: %s" % (
            in_changed, str(ex_memento), input.changed))

        memento = ex_memento
        
        if not in_changed:
            try:
                ref_mtime = self.getRefTime(input.rundir)
                info = FileCollection.from_dict(ex_memento["svdeps"])
                in_changed = not TaskCheckUpToDate(data.files, data.incdirs).check(info, ref_mtime)
            except Exception as e:
                self._log.warning("Unexpected output-directory format (%s). Rebuilding" % str(e))
                shutil.rmtree(input.rundir)
                os.makedirs(input.rundir)
                in_changed = True

        self._log.debug("in_changed=%s" % in_changed)
        if in_changed:
            self.memento = VlTaskSimImageMemento()

            # First, create dependency information
            try:
                info = TaskBuildFileCollection(data.files, data.incdirs).build()
                self.memento.svdeps = info.to_dict()
            except Exception as e:
                self._log.error("Failed to build file collection: %s" % str(e))
                self.markers.append(TaskMarker(
                    severity="error",
                    msg="Dependency-checking failed: %s" % str(e)))
                status = 1

            if status == 0:
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

                print("Compiling", flush=True)
                status |= await self.ctxt.exec(cmd, logfile="iverilog.log")
                in_changed = True
        else:
            self.memento = VlTaskSimImageMemento(**memento)


        return (status, in_changed)

async def SimImage(ctxt, input):
    return await SimImageBuilder(ctxt).run(ctxt, input)
