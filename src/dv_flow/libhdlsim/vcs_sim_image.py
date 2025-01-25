import os
from typing import List
from dv_flow.mgr import Task, TaskData
from dv_flow.libhdlsim.vl_sim_image import VlSimImage

class SimImage(VlSimImage):

    def getRefTime(self):
        if os.path.isfile(os.path.join(self.rundir, 'simv')):
            print("Returning timestamp")
            return os.path.getmtime(os.path.join(self.rundir, 'simv'))
        else:
            raise Exception("simv file (%s) does not exist" % os.path.join(self.rundir, 'obj_dir/simv'))
    
    async def build(self, files : List[str], incdirs : List[str]):
        cmd = ['vcs', '-sverilog']

        for incdir in incdirs:
            cmd.append('+incdir+%s' % incdir)

        cmd.extend(files)

        if len(self.params.top):
            cmd.extend(['-top', "+".join(self.params.top)])

        print("self.basedir=%s" % self.rundir)
        proc = await self.session.create_subprocess(*cmd,
                                                        cwd=self.rundir)
        await proc.wait()

        if proc.returncode != 0:
            raise Exception("VCS failed (%d)" % proc.returncode)

