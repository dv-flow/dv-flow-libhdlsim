
import os
from typing import List
from dv_flow.mgr import Task, TaskData, FileSet
from dv_flow.libhdlsim.vl_sim_image_builder import VlSimImage

class SimRun(Task):

    async def run(self, input : TaskData) -> TaskData:
        vl_fileset = input.getFileSets("simDir")

        if len(vl_fileset) == 0:
            raise Exception("No simDir fileset provided")

        build_dir = vl_fileset[0].basedir

        cmd = [
            'vvp',
            os.path.join(build_dir, 'simv.vpp'),
        ]

        fp = open(os.path.join(self.rundir, 'sim.log'), "w")
        proc = await self.session.create_subprocess(*cmd,
                                                    cwd=self.rundir,
                                                    stdout=fp)

        await proc.wait()

        fp.close()

        output = TaskData()
        output.addFileSet(FileSet(src=self.name, type="simRunDir", basedir=self.rundir))

        return output
    pass
