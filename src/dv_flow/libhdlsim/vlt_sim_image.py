import os
import logging
from typing import ClassVar, List
from dv_flow.mgr import Task, TaskData
from dv_flow.libhdlsim.vl_sim_image import VlSimImage

class SimImage(VlSimImage):

    _log : ClassVar = logging.getLogger("SimImage[vlt]")

    def getRefTime(self):
        if os.path.isfile(os.path.join(self.rundir, 'obj_dir/simv')):
            print("Returning timestamp")
            return os.path.getmtime(os.path.join(self.rundir, 'obj_dir/simv'))
        else:
            raise Exception("simv file (%s) does not exist" % os.path.join(self.rundir, 'obj_dir/simv'))
    
    async def build(self, files : List[str], incdirs : List[str]):
        cmd = ['verilator', '--binary', '-o', 'simv']

        for incdir in incdirs:
            cmd.append('+incdir+%s' % incdir)

        cmd.extend(files)

        for top in self.params.top:
            cmd.extend(['--top-module', top])

        print("self.basedir=%s" % self.rundir)
        proc = await self.session.create_subprocess(*cmd,
                                                        cwd=self.rundir)
        await proc.wait()

        if proc.returncode != 0:
            raise Exception("Verilator failed (%d)" % proc.returncode)

