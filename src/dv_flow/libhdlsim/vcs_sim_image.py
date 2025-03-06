import os
import asyncio
import json
from typing import List
from dv_flow.libhdlsim.vl_sim_image_builder import VlSimImageBuilder

class SimImageBuilder(VlSimImageBuilder):

    def getRefTime(self):
        if os.path.isfile(os.path.join(self.rundir, 'simv')):
            return os.path.getmtime(os.path.join(self.rundir, 'simv'))
        else:
            raise Exception("simv file (%s) does not exist" % os.path.join(self.rundir, 'obj_dir/simv'))
    
    async def build(self, input, files : List[str], incdirs : List[str]):
        cmd = ['vcs', '-sverilog']

        for incdir in incdirs:
            cmd.append('+incdir+%s' % incdir)

        cmd.extend(files)

        if len(input.params.top):
            cmd.extend(['-top', "+".join(input.params.top)])

        fp = open(os.path.join(input.rundir, 'build.log'), "w")
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=input.rundir,
            stdout=fp,
            stderr=asyncio.subprocess.STDOUT)

        await proc.wait()
        fp.close()

        if proc.returncode != 0:
            raise Exception("VCS failed (%d)" % proc.returncode)

async def SimImage(runner, input):
    builder = SimImageBuilder()
    return await builder.run(runner, input)

