import os
from typing import List
from dv_flow.mgr import Task, TaskData
from dv_flow.libhdlsim.vl_sim_image_builder import VlSimImage

class SimImage(VlSimImage):

    def getRefTime(self):
        if os.path.isfile(os.path.join(self.rundir, 'simv.vpp')):
            print("Returning timestamp")
            return os.path.getmtime(os.path.join(self.rundir, 'simv.vpp'))
        else:
            raise Exception("simv file (%s) does not exist" % os.path.join(self.rundir, 'simv.vpp'))
    
    async def build(self, files : List[str], incdirs : List[str]):
        cmd = ['iverilog', '-o', 'simv.vpp', '-g2012']

        for incdir in incdirs:
            cmd.extend(['-I', incdir])

        cmd.extend(files)

        for top in self.params.top:
            cmd.extend(['-s', top])

        print("self.basedir=%s" % self.rundir)
        proc = await self.session.create_subprocess(*cmd,
                                                        cwd=self.rundir)
        await proc.wait()

        if proc.returncode != 0:
            raise Exception("iverilog failed (%d)" % proc.returncode)

