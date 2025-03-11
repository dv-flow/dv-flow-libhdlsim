import os
import json
import logging
import shutil
import dataclasses as dc
from pydantic import BaseModel
from toposort import toposort
from dv_flow.mgr import FileSet, TaskDataResult
from dv_flow.mgr.task_data import TaskMarker, TaskMarkerLoc
from typing import ClassVar, List, Tuple

from svdep import FileCollection, TaskCheckUpToDate, TaskBuildFileCollection
from dv_flow.libhdlsim.vl_sim_image_builder import VlTaskSimImageMemento

@dc.dataclass
class VlSimLibBuilder(object):
    markers : List = dc.field(default_factory=list)

    _log : ClassVar = logging.getLogger("VlSimLib")

    def getRefTime(self, rundir):
        raise NotImplementedError()

    async def build(self, files : List[str], incdirs : List[str]):
        raise NotImplementedError()

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
        status = 0
        if in_changed:
            memento = VlTaskSimImageMemento()

            # First, create dependency information
            info = TaskBuildFileCollection(files, incdirs).build()
            memento.svdeps = info.to_dict()

            status = await self.build(input, files, incdirs, libs) 
        else:
            memento = VlTaskSimImageMemento(**memento)

        self._log.debug("%s status: %d" % (input.name, status))

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
    
    def _gatherSvSources(self, files, incdirs, libs, input):
        # input must represent dependencies for all tasks related to filesets
        # references must support transitivity

        try:
            vl_filesets = json.loads(input.params.sources)
        except Exception as e:
            self._log.error("Failed to parse JSON: %s (%s)" % (input.params.sources, str(e)))
            raise e
        self._log.debug("vl_filesets: %s" % str(vl_filesets))

        for fs_j in vl_filesets:
            fs = FileSet(**fs_j)
            self._log.debug("fs.basedir=%s" % fs.basedir)
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


