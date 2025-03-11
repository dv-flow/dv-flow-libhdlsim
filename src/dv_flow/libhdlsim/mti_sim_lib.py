import os
import asyncio
from typing import List
from dv_flow.mgr import Task, TaskData
from dv_flow.libhdlsim.vl_sim_lib_builder import VlSimLibBuilder

class SimLibBuilder(VlSimLibBuilder):

    def getRefTime(self, rundir):
        if os.path.isfile(os.path.join(rundir, 'simv_opt.d')):
            return os.path.getmtime(os.path.join(rundir, 'simv_opt.d'))
        else:
            raise Exception("simv_opt.d file (%s) does not exist" % os.path.join(rundir, 'simv_opt.d'))
    
    async def build(self, input, files : List[str], incdirs : List[str], libs : List[str]):
        cmd = []

        libname = input.params.libname
        if not os.path.isdir(os.path.join(input.rundir, libname)):
            cmd = ['vlib', libname]
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

        cmd = ['vlog', '-sv', '-work', libname]

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
        
        return proc.returncode

async def SimLib(runner, input):
    builder = SimLibBuilder()
    return await builder.run(runner, input)
