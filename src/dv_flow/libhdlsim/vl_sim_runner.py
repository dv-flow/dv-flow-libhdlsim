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
from pydantic import BaseModel
from toposort import toposort
from dv_flow.mgr import FileSet, TaskDataResult
from dv_flow.mgr.task_data import TaskMarker, TaskMarkerLoc, SeverityE
from typing import ClassVar, List, Tuple
from dv_flow.libhdlsim.log_parser import LogParser

from svdep import FileCollection, TaskCheckUpToDate, TaskBuildFileCollection
from dv_flow.libhdlsim.vl_sim_image_builder import VlTaskSimImageMemento

@dc.dataclass
class VLSimRunner(object):
    markers : List[TaskMarker] = dc.field(default_factory=list)
    args : List[str] = dc.field(default_factory=list)
    plusargs : List[str] = dc.field(default_factory=list)
    dpilibs : List[str] = dc.field(default_factory=list)
    vpilibs : List[str] = dc.field(default_factory=list)
    dumpwaves : bool = dc.field(default=False)
    rundir : str = dc.field(default=None)

    async def run(self, runner, input) -> TaskDataResult:
        imgdir = None
        dpi = []
        vpi = []
        status = 0

        self.rundir = input.rundir

        self.plusargs = input.params.plusargs.copy()
        self.args = input.params.args.copy()

        for inp in input.inputs:
            if inp.filetype == "simDir":
                if imgdir:
                    self.markers.append(TaskMarker(
                        severity=SeverityE.Error,
                        msg="Multiple simDir inputs"))
                    status = 1
                    break
                else:
                    imgdir = inp.basedir
            elif inp.filetype == "systemVerilogDPI":
                for f in inp.files:
                    dpi.append(os.path.join(inp.basedir, f))
            elif inp.filetype == "verilogVPI":
                for f in inp.files:
                    vpi.append(os.path.join(inp.basedir, f))
        
        if imgdir is None:
            self.markers.append(TaskMarker(
                severity=SeverityE.Error,
                msg="No simDir input"))
            status = 1

        if status == 0:
            status = await self.runsim(imgdir, dpi, vpi)

        return TaskDataResult(
            status=status,
            markers=self.markers,
            output=[FileSet(
                src=input.name, 
                filetype="simRunDir", 
                basedir=input.rundir)]
        )

    async def runsim(self, imgdir, args, plusargs, dpilibs, vpilibs):
        self.markers.append(TaskMarker(
            severity=SeverityE.Error,
            msg="No runsim implemenetation"))
        return 1
    