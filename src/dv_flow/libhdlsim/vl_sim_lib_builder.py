#****************************************************************************
#* vl_sim_lib_builder.py
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
from dv_flow.mgr import FileSet, TaskDataResult, TaskRunCtxt
from dv_flow.mgr.task_data import TaskMarker, TaskMarkerLoc, SeverityE
from typing import ClassVar, List, Tuple
from dv_flow.libhdlsim.log_parser import LogParser
from dv_flow.libhdlsim.vl_sim_data import VlSimImageData

from svdep import FileCollection, TaskCheckUpToDate, TaskBuildFileCollection
from dv_flow.libhdlsim.vl_sim_image_builder import VlTaskSimImageMemento

@dc.dataclass
class VlSimLibBuilder(object):
    runner : TaskRunCtxt
    markers : List = dc.field(default_factory=list)

    _log : ClassVar = logging.getLogger("VlSimLib")

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
        self.markers.clear()
        
        for f in os.listdir(input.rundir):
            self._log.debug("sub-elem: %s" % f)
        ex_memento = input.memento
        in_changed = (ex_memento is None or input.changed)

        if input.params.libname is None or input.params.libname == "":
            input.params.libname = input.name.replace(".", "_")

        self._log.debug("in_changed: %s ; ex_memento: %s input.changed: %s" % (
            in_changed, str(ex_memento), input.changed))

        data = VlSimImageData()
        data.compargs.extend(input.params.args)
        data.incdirs.extend(input.params.incdirs)
        data.defines.extend(input.params.defines)
        memento = ex_memento

        self._gatherSvSources(data, input)

        self._log.debug("files: %s in_changed=%s" % (str(data.files), in_changed))

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
        status = 0
        if in_changed:
            memento = VlTaskSimImageMemento()

            # First, create dependency information
            info = TaskBuildFileCollection(data.files, data.incdirs).build()
            memento.svdeps = info.to_dict()

            status = await self.build(input, data) 
        else:
            memento = VlTaskSimImageMemento(**memento)

        self._log.debug("%s status: %d" % (input.name, status))

        for m in self.markers:
            if m.severity == "error":
                m.severity = SeverityE.Error
            elif m.severity == "warn":
                m.severity = SeverityE.Warning
            elif m.severity == "info":
                m.severity = SeverityE.Info

        return TaskDataResult(
            memento=memento if status == 0 else None,
            output=[FileSet(
                src=input.name, 
                filetype="simLib", 
                basedir=input.rundir,
                files=[input.params.libname])],
            changed=in_changed,
            markers=self.markers,
            status=status
        )
    
    def _gatherSvSources(self, data : VlSimImageData, input):
        # input must represent dependencies for all tasks related to filesets
        # references must support transitivity

        for fs in input.inputs:
            if fs.type == "std.FileSet":
                self._log.debug("fs.basedir=%s" % fs.basedir)
                data.defines.extend(fs.defines)
                if fs.filetype == "verilogIncDir":
                    data.incdirs.append(fs.basedir)
                elif fs.filetype == "simLib":
                    if len(fs.files) > 0:
                        for file in fs.files:
                            path = os.path.join(fs.basedir, file)
                            self._log.debug("path: basedir=%s fullpath=%s" % (fs.basedir, path))
                            data.libs.append(path)
                    else:
                        data.libs.append(fs.basedir)
                    data.incdirs.extend([os.path.join(fs.basedir, i) for i in fs.incdirs])
                else:
                    for file in fs.files:
                        path = os.path.join(fs.basedir, file)
                        self._log.debug("path: basedir=%s fullpath=%s" % (fs.basedir, path))
                        dir = os.path.dirname(path)
                        data.files.append(path)
                    data.incdirs.extend([os.path.join(fs.basedir, i) for i in fs.incdirs])
            elif fs.type == "hdlsim.SimCompileArgs":
                data.compargs.extend(fs.args)
                data.incdirs.extend(fs.incdirs)
                data.defines.extend(fs.defines)


