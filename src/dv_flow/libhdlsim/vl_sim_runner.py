#****************************************************************************
#* vl_sim_runner.py
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
import json
import logging
import shutil
import dataclasses as dc
from dv_flow.mgr import FileSet, TaskDataResult, TaskRunCtxt
from dv_flow.mgr.task_data import TaskMarker, SeverityE
from typing import ClassVar, List, Tuple
from dv_flow.libhdlsim.log_parser import LogParser
from dv_flow.libhdlsim.vl_sim_data import VlSimRunData

from svdep import FileCollection, TaskCheckUpToDate, TaskBuildFileCollection
from dv_flow.libhdlsim.vl_sim_image_builder import VlTaskSimImageMemento

@dc.dataclass
class VLSimRunner(object):
    markers : List[TaskMarker] = dc.field(default_factory=list)
    rundir : str = dc.field(default="")
    ctxt : TaskRunCtxt = dc.field(default=None)

    async def run(self, ctxt, input) -> TaskDataResult:
        status = 0

        self.ctxt = ctxt
        self.rundir = input.rundir
        data = VlSimRunData()

        data.plusargs = input.params.plusargs.copy()
        data.args = input.params.args.copy()
        data.trace = input.params.trace
        data.dpilibs.extend(input.params.dpilibs)
        data.vpilibs.extend(input.params.vpilibs)

        sim_data = []

        for inp in input.inputs:
            if inp.type == "std.FileSet":
                if inp.filetype == "simDir":
                    if data.imgdir:
                        self.markers.append(TaskMarker(
                            severity=SeverityE.Error,
                            msg="Multiple simDir inputs"))
                        status = 1
                        break
                    else:
                        data.imgdir = inp.basedir
                elif inp.filetype == "systemVerilogDPI":
                    for f in inp.files:
                        data.dpilibs.append(os.path.join(inp.basedir, f))
                elif inp.filetype == "verilogVPI":
                    for f in inp.files:
                        data.vpilibs.append(os.path.join(inp.basedir, f))
                elif inp.filetype == "simRunData":
                    sim_data.append(inp)
            elif inp.type == "hdlsim.SimRunArgs":
                if inp.args:
                    data.args.extend(inp.args)
                if inp.plusargs:
                    data.plusargs.extend(inp.plusargs)
                if inp.vpilibs:
                    data.vpilibs.extend(inp.vpilibs)
                if inp.dpilibs:
                    data.dpilibs.extend(inp.dpilibs)


        if data.imgdir is None:
            self.markers.append(TaskMarker(
                severity=SeverityE.Error,
                msg="No simDir input"))
            status = 1

        # Handle simRunData inputs
        self.copy_sim_data(sim_data)


        if not status:
            status |= await self.runsim(data)

        return TaskDataResult(
            status=status,
            markers=self.markers,
            output=[FileSet(
                src=input.name, 
                filetype="simRunDir", 
                basedir=input.rundir)]
        )

    async def runsim(self, data : VlSimRunData):
        self.markers.append(TaskMarker(
            severity=SeverityE.Error,
            msg="No runsim implemenetation"))
        return 1
    
    def copy_sim_data(self, sim_data : List[FileSet]):
        for ds in sim_data:
            for f in ds.files:
                src_f = os.path.join(ds.basedir, f)
                dst_f = os.path.join(self.rundir, f)
                dst_d = os.path.dirname(dst_f)
                if not os.path.exists(dst_d):
                    os.makedirs(dst_d)
                shutil.copy2(src_f, dst_f)
                logging.info(f"Copied {src_f} to {dst_f}")
    