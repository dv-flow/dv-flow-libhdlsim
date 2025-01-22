import os
import shutil
import pydantic.dataclasses as dc
from pydantic import BaseModel
from toposort import toposort
from dv_flow.mgr import FileSet, Task, TaskData, TaskMemento
from typing import List, Tuple

from svdep import FileCollection, TaskCheckUpToDate, TaskBuildFileCollection

class VlSimImage(Task):

    def getRefTime(self):
        raise NotImplementedError()

    async def build(self, files : List[str], incdirs : List[str]):
        raise NotImplementedError()

    async def run(self, input : TaskData) -> TaskData:
        for f in os.listdir(self.rundir):
            print("sub-elem: %s" % f)
        ex_memento = self.getMemento(VlTaskSimImageMemento)
        in_changed = (ex_memento is None or input.changed)

        print("in_changed: %s ; ex_memento: %s input.changed: %s" % (
            in_changed, str(ex_memento), input.changed))

        files = []
        incdirs = []
        memento = ex_memento

        self._gatherSvSources(files, incdirs, input)

        print("files: %s in_changed=%s" % (str(files), in_changed))

        if not in_changed:
            try:
                ref_mtime = self.getRefTime()
                info = FileCollection.from_dict(ex_memento.svdeps)
                in_changed = not TaskCheckUpToDate(files, incdirs).check(info, ref_mtime)
            except Exception as e:
                print("Unexpected output-directory format (%s). Rebuilding" % str(e))
                shutil.rmtree(self.rundir)
                os.makedirs(self.rundir)
                in_changed = True

        print("in_changed=%s" % in_changed)
        if in_changed:
            memento = VlTaskSimImageMemento()

            # First, create dependency information
            info = TaskBuildFileCollection(files, incdirs).build()
            memento.svdeps = info.to_dict()

            await self.build(files, incdirs) 

        output = TaskData()
        output.addFileSet(FileSet(src=self.name, type="simDir", basedir=self.rundir))
        output.changed = in_changed

        self.setMemento(memento)
        return output
    
    def _gatherSvSources(self, files, incdirs, input):
        # input must represent dependencies for all tasks related to filesets
        # references must support transitivity

        vl_filesets = input.getFileSets(("verilogSource", "systemVerilogSource"))
        print("vl_filesets: %s" % str(vl_filesets))
        fs_tasks = [fs.src for fs in vl_filesets]

        for fs in vl_filesets:
            print("fs.basedir=%s" % fs.basedir)
            for file in fs.files:
                path = os.path.join(fs.basedir, file)
                print("path: basedir=%s fullpath=%s" % (fs.basedir, path))
                dir = os.path.dirname(path)
                if dir not in incdirs:
                    incdirs.append(dir)
                files.append(path)

        # Want dependencies just for the filesets
        # - key is the task associated with a filelist
        # - deps is the dep-set of the on the incoming
        #
        # -> Send output set of dependencies
        # - Task -> deps map
        #     "task" : ["dep1", "dep2", ...],
        #     "task2" : 
        # - All tasks are represented in the map
        # -> Assume projects will often flatten before exporting

        # Sort the deps
        order = list(toposort(input.deps))

        print("order: %s" % str(order))


class VlTaskSimImageParams(BaseModel):
    debug : bool = False
    top : List[str] = dc.Field(default_factory=list)

class VlTaskSimImageMemento(TaskMemento):
    svdeps : dict = dc.Field(default_factory=dict)

