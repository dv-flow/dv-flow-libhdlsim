#****************************************************************************
#* vl_sim_image_builder.py
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
import pydantic.dataclasses as pdc
from toposort import toposort
from dv_flow.mgr import FileSet, TaskDataResult, TaskMarker, TaskRunCtxt
from typing import ClassVar, List, Tuple
from dv_flow.libhdlsim.log_parser import LogParser

from svdep import FileCollection, TaskCheckUpToDate, TaskBuildFileCollection

@dc.dataclass
class VlSimImageBuilder(object):
    runner : TaskRunCtxt
    markers : List = dc.field(default_factory=list)

    _log : ClassVar = logging.getLogger("VlSimImage")

    def getRefTime(self, rundir):
        raise NotImplementedError()

    async def build(self, files : List[str], incdirs : List[str]):
        raise NotImplementedError()

    def parseLog(self, log):
        parser = LogParser(notify=lambda m: self.markers.append(m))
        with open(log, "r") as fp:
            for line in fp.readlines():
                parser.line(line)

    async def run(self, runner, input) -> TaskDataResult:
        for f in os.listdir(input.rundir):
            self._log.debug("sub-elem: %s" % f)
        status = 0
        ex_memento = input.memento
        in_changed = (ex_memento is None or input.changed)

        self._log.debug("in_changed: %s ; ex_memento: %s input.changed: %s" % (
            in_changed, str(ex_memento), input.changed))

        files = []
        incdirs = []
        libs = []
        memento = ex_memento

        self._gatherSvSources(files, incdirs, libs, input)

        self._log.debug("files: %s in_changed=%s" % (str(files), in_changed))

        if not in_changed:
            try:
                ref_mtime = self.getRefTime(input.rundir)
                info = FileCollection.from_dict(ex_memento["svdeps"])
                in_changed = not TaskCheckUpToDate(files, incdirs).check(info, ref_mtime)
            except Exception as e:
                self._log.warning("Unexpected output-directory format (%s). Rebuilding" % str(e))
                shutil.rmtree(input.rundir)
                os.makedirs(input.rundir)
                in_changed = True

        self._log.debug("in_changed=%s" % in_changed)
        if in_changed:
            memento = VlTaskSimImageMemento()

            # First, create dependency information
            try:
                info = TaskBuildFileCollection(files, incdirs).build()
                memento.svdeps = info.to_dict()
            except Exception as e:
                self._log.error("Failed to build file collection: %s" % str(e))
                self.markers.append(TaskMarker(
                    severity="error",
                    msg="Dependency-checking failed: %s" % str(e)))
                status = 1

            if status == 0:
                status = await self.build(input, files, incdirs, libs) 
        else:
            memento = VlTaskSimImageMemento(**memento)

        return TaskDataResult(
            memento=memento if status == 0 else None,
            status=status,
            output=[FileSet(
                src=input.name, 
                filetype="simDir", 
                basedir=input.rundir)],
            changed=in_changed,
            markers=self.markers
        )
    
    def _gatherSvSources(self, files, incdirs, libs, input):
        # input must represent dependencies for all tasks related to filesets
        # references must support transitivity

        for fs in input.inputs:
            self._log.debug("fs.filetype=%s fs.basedir=%s" % (fs.filetype, fs.basedir))
            if fs.filetype == "verilogIncDir":
                incdirs.append(fs.basedir)
            elif fs.filetype == "simLib":
                if len(fs.files) > 0:
                    for file in fs.files:
                        path = os.path.join(fs.basedir, file)
                        self._log.debug("path: basedir=%s fullpath=%s" % (fs.basedir, path))
                        libs.append(path)
                else:
                    libs.append(fs.basedir)
                incdirs.extend([os.path.join(fs.basedir, i) for i in fs.incdirs])
            else:
                for file in fs.files:
                    path = os.path.join(fs.basedir, file)
                    self._log.debug("path: basedir=%s fullpath=%s" % (fs.basedir, path))
                    dir = os.path.dirname(path)
                    if dir not in incdirs:
                        incdirs.append(dir)
                    files.append(path)
                incdirs.extend([os.path.join(fs.basedir, i) for i in fs.incdirs])


class VlTaskSimImageMemento(BaseModel):
    svdeps : dict = pdc.Field(default_factory=dict)

