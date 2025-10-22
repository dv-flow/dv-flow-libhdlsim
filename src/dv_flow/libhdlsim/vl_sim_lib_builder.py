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
from dv_flow.mgr import FileSet, TaskDataResult, TaskRunCtxt
from dv_flow.mgr.task_data import TaskMarker, TaskMarkerLoc, SeverityE
from typing import Any, ClassVar, List, Tuple
from dv_flow.libhdlsim.log_parser import LogParser
from dv_flow.libhdlsim.vl_sim_data import VlSimImageData

from svdep import FileCollection, TaskCheckUpToDate, TaskBuildFileCollection
from dv_flow.libhdlsim.vl_sim_image_builder import VlTaskSimImageMemento
from .util import merge_tokenize

@dc.dataclass
class VlSimLibBuilder(object):
    runner : TaskRunCtxt
    markers : List = dc.field(default_factory=list)
    memento : Any = dc.field(default=None)
    ctxt : TaskRunCtxt = None

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
        self.ctxt = runner

        for f in os.listdir(input.rundir):
            self._log.debug("sub-elem: %s" % f)

        if input.params.libname is None or input.params.libname == "":
            input.params.libname = input.name.replace(".", "_")

        data = VlSimImageData()
        data.compargs.extend(merge_tokenize(input.params.args))
        data.incdirs.extend(input.params.incdirs)
        data.defines.extend(merge_tokenize(input.params.defines))

        self._gatherSvSources(data, input)

        self._log.debug("files: %s" % str(data.files))

        status, in_changed = await self.build(input, data)

        for m in self.markers:
            if m.severity == "error":
                m.severity = SeverityE.Error
            elif m.severity == "warn":
                m.severity = SeverityE.Warning
            elif m.severity == "info":
                m.severity = SeverityE.Info

        return TaskDataResult(
            memento=self.memento if status == 0 else None,
            output=[FileSet(
                src=input.name, 
                filetype="simLib", 
                basedir=input.rundir,
                files=[input.params.libname],
                incdirs=(data.incdirs if input.params.propagate_incdirs else []))],
            changed=in_changed,
            markers=self.markers,
            status=status
        )
    
    def _gatherSvSources(self, data : VlSimImageData, input):
        # input must represent dependencies for all tasks related to filesets
        # references must support transitivity

        for fs in input.inputs:
            self._processDataset(data, fs)

    def _processDataset(self, data : VlSimImageData, fs):
        if fs.type == "std.FileSet":
            self._log.debug("fs.basedir=%s" % fs.basedir)
            data.defines.extend(fs.defines)
            if fs.filetype == "verilogIncDir":
                data.incdirs.append(fs.basedir)
            elif fs.filetype in ("verilogInclude", "systemVerilogInclude"):
                data.incdirs.extend([os.path.join(fs.basedir, i) for i in fs.incdirs])
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
                data.sysv |= (fs.filetype == "systemVerilogSource")
                for file in fs.files:
                    path = os.path.join(fs.basedir, file)
                    self._log.debug("path: basedir=%s fullpath=%s" % (fs.basedir, path))
                    dir = os.path.dirname(path)
                    data.files.append(path)
                data.incdirs.extend([os.path.join(fs.basedir, i) for i in fs.incdirs])
        elif fs.type == "hdlsim.SimCompileArgs":
            data.compargs.extend(merge_tokenize(fs.args))
            data.incdirs.extend(fs.incdirs)
            data.defines.extend(fs.defines)
        pass
