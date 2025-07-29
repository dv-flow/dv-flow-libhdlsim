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
from typing import Any, ClassVar, List, Tuple
from dv_flow.libhdlsim.log_parser import LogParser
from dv_flow.libhdlsim.vl_sim_data import VlSimImageData

from svdep import FileCollection, TaskCheckUpToDate, TaskBuildFileCollection

@dc.dataclass
class VlSimImageBuilder(object):
    runner : TaskRunCtxt
    input : Any = dc.field(default=None)
    markers : List = dc.field(default_factory=list)
    output : List = dc.field(default_factory=list)

    _log : ClassVar = logging.getLogger("VlSimImage")

    def getRefTime(self, rundir):
        raise NotImplementedError()

    async def build(self, input, data : VlSimImageData):
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

        self.input = input
        data = VlSimImageData()
        data.top.extend(input.params.top)
        data.args.extend(input.params.args)
        data.compargs.extend(input.params.compargs)
        data.elabargs.extend(input.params.elabargs)
        data.incdirs.extend(input.params.incdirs)
        data.defines.extend(input.params.defines)
        data.vpi.extend(input.params.vpilibs)
        data.dpi.extend(input.params.dpilibs)
        data.trace = input.params.trace
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
        if in_changed:
            memento = VlTaskSimImageMemento()

            # First, create dependency information
            try:
                info = TaskBuildFileCollection(data.files, data.incdirs).build()
                memento.svdeps = info.to_dict()
            except Exception as e:
                self._log.error("Failed to build file collection: %s" % str(e))
                self.markers.append(TaskMarker(
                    severity="error",
                    msg="Dependency-checking failed: %s" % str(e)))
                status = 1

            if status == 0:
                status = await self.build(input, data) 
        else:
            memento = VlTaskSimImageMemento(**memento)

        self.output.append(FileSet(
                src=input.name, 
                filetype="simDir", 
                basedir=input.rundir))

        return TaskDataResult(
            memento=memento if status == 0 else None,
            status=status,
            output=self.output,
            changed=in_changed,
            markers=self.markers
        )
    
    def _gatherSvSources(self, data : VlSimImageData, input):
        # input must represent dependencies for all tasks related to filesets
        # references must support transitivity

        for fs in input.inputs:
            if fs.type == "std.FileSet":
                self._log.debug("fs.filetype=%s fs.basedir=%s" % (fs.filetype, fs.basedir))
                data.defines.extend(fs.defines)

                if fs.filetype == "cSource" or fs.filetype == "cppSource":
                    for file in fs.files:
                        path = os.path.join(fs.basedir, file)
                        self._log.debug("path: basedir=%s fullpath=%s" % (fs.basedir, path))
                        data.csource.append(path)
                elif fs.filetype == "verilogIncDir":
                    if len(fs.basedir.strip()) > 0:
                        data.incdirs.append(fs.basedir)
                elif fs.filetype == "simLib":
                    if len(fs.files) > 0:
                        for file in fs.files:
                            path = os.path.join(fs.basedir, file)
                            self._log.debug("path: basedir=%s fullpath=%s" % (fs.basedir, path))
                            if len(path.strip()) > 0:
                                data.libs.append(path)
                    else:
                        data.libs.append(fs.basedir)
                    data.incdirs.extend([os.path.join(fs.basedir, i) for i in fs.incdirs])
                elif fs.filetype == "systemVerilogDPI":
                    for file in fs.files:
                        path = os.path.join(fs.basedir, file)
                        self._log.debug("path: basedir=%s fullpath=%s" % (fs.basedir, path))
                        data.dpi.append(path)
                elif fs.filetype == "verilogVPI":
                    for file in fs.files:
                        path = os.path.join(fs.basedir, file)
                        self._log.debug("path: basedir=%s fullpath=%s" % (fs.basedir, path))
                        data.vpi.append(path)
                else:
                    for file in fs.files:
                        path = os.path.join(fs.basedir, file)
                        self._log.debug("path: basedir=%s fullpath=%s" % (fs.basedir, path))
                        dir = os.path.dirname(path)
                        data.files.append(path)
                    data.incdirs.extend([os.path.join(fs.basedir, i) for i in fs.incdirs])
            elif fs.type == "hdlsim.SimCompileArgs":
                data.compargs.extend(fs.args)
                for inc in fs.incdirs:
                    if len(inc.strip()) > 0:
                        data.incdirs.append(inc)
                data.defines.extend(fs.defines)
            elif fs.type == "hdlsim.SimElabArgs":
                self._log.debug("fs.type=%s" % fs.type)
                data.elabargs.extend(fs.args)
                data.vpi.extend(fs.vpilibs)
                data.dpi.extend(fs.dpilibs)


class VlTaskSimImageMemento(BaseModel):
    svdeps : dict = pdc.Field(default_factory=dict)

