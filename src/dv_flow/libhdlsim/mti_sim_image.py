import os
from typing import List
from dv_flow.mgr import Task, TaskData
from dv_flow.libhdlsim.vl_sim_image_builder import VlSimImage

class SimImage(VlSimImage):

    def getRefTime(self):
        if os.path.isfile(os.path.join(self.rundir, 'simv_opt.d')):
            print("Returning timestamp")
            return os.path.getmtime(os.path.join(self.rundir, 'simv_opt.d'))
        else:
            raise Exception("simv_opt.d file (%s) does not exist" % os.path.join(self.rundir, 'simv_opt.d'))
    
    async def build(self, files : List[str], incdirs : List[str]):
        cmd = []

        if not os.path.isdir(os.path.join(self.rundir, 'work')):
            cmd = ['vlib', 'work']
            proc = await self.session.exec(*cmd,
                                        cwd=self.rundir)
            await proc.wait()

            if proc.returncode != 0:
                raise Exception("vlib failed (%d)" % proc.returncode)

        cmd = ['vlog', '-sv']

        for incdir in incdirs:
            cmd.append('+incdir+%s' % incdir)

        cmd.extend(files)

        print("self.basedir=%s" % self.rundir)
        proc = await self.session.exec(*cmd,
                                    cwd=self.rundir)
        await proc.wait()

        if proc.returncode != 0:
            raise Exception("vlog failed (%d)" % proc.returncode)

        # Now, run vopt
        cmd = ['vopt', '-o', 'simv_opt']
        for top in self.params.top:
            cmd.append(top)

        proc = await self.session.exec(*cmd,
                                    cwd=self.rundir)
        await proc.wait()

        if proc.returncode != 0:
            raise Exception("vopt failed (%d)" % proc.returncode)

