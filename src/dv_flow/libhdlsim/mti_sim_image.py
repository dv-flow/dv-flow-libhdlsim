import os
import asyncio
from typing import List
from dv_flow.mgr import Task, TaskData
from dv_flow.libhdlsim.vl_sim_image_builder import VlSimImageBuilder

class SimImageBuilder(VlSimImageBuilder):

    def getRefTime(self):
        if os.path.isfile(os.path.join(self.rundir, 'simv_opt.d')):
            return os.path.getmtime(os.path.join(self.rundir, 'simv_opt.d'))
        else:
            raise Exception("simv_opt.d file (%s) does not exist" % os.path.join(self.rundir, 'simv_opt.d'))
    
    async def build(self, input, files : List[str], incdirs : List[str], libs : List[str]):
        cmd = []

        if not os.path.isdir(os.path.join(input.rundir, 'work')):
            cmd = ['vlib', 'work']
            fp = open(os.path.join(input.rundir, "vlib.log"), "w")
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                cwd=input.rundir,
                stdout=fp,
                stderr=asyncio.subprocess.STDOUT)
            fp.close()

            await proc.wait()

            if proc.returncode != 0:
                raise Exception("vlib failed (%d)" % proc.returncode)

        if len(files) > 0:
            cmd = ['vlog', '-sv']

            for incdir in incdirs:
                cmd.append('+incdir+%s' % incdir)

            cmd.extend(files)

            fp = open(os.path.join(input.rundir, "build.log"), "w")
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                cwd=input.rundir,
                stdout=fp,
                stderr=asyncio.subprocess.STDOUT)

            await proc.wait()
            fp.close()

            if proc.returncode != 0:
                raise Exception("vlog failed (%d)" % proc.returncode)

        # Now, run vopt
        cmd = ['vopt', '-o', 'simv_opt']
        for top in input.params.top:
            cmd.append(top)

        # Add in libraries
        for lib in libs:
            cmd.extend([
                '-Ldir', os.path.dirname(lib),
                '-L', os.path.basename(lib)])
            
        self._log.debug("vopt cmd: %s" % str(cmd))

        fp = open(os.path.join(input.rundir, "elab.log"), "w")
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=input.rundir,
            stdout=fp,
            stderr=asyncio.subprocess.STDOUT)
        await proc.wait()
        fp.close()

        if proc.returncode != 0:
            raise Exception("vopt failed (%d)" % proc.returncode)

async def SimImage(runner, input):
    builder = SimImageBuilder()
    return await builder.run(runner, input)
