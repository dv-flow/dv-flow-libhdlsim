import os
import asyncio
import json
from typing import List
from dv_flow.libhdlsim.vl_sim_lib_builder import VlSimLibBuilder

class SimLibBuilder(VlSimLibBuilder):

    def getRefTime(self):
        if os.path.isfile(os.path.join(self.rundir, 'simv')):
            return os.path.getmtime(os.path.join(self.rundir, 'simv'))
        else:
            raise Exception("simv file (%s) does not exist" % os.path.join(self.rundir, 'obj_dir/simv'))
    
    async def build(self, input, files : List[str], incdirs : List[str], libs : List[str]):

        if not os.path.isdir(os.path.join(input.rundir, input.params.libname)):
            os.makedirs(os.path.join(input.rundir, input.params.libname), exist_ok=True)

        # Create a library map
        with open(os.path.join(input.rundir, 'synopsys_sim.setup'), 'w') as fp:
            fp.write("%s: %s\n" % (
                input.params.libname, 
                os.path.join(input.rundir, input.params.libname)))

        cmd = ['vlogan', '-full64', '-sverilog', '-work', input.params.libname]

        for incdir in incdirs:
            cmd.append('+incdir+%s' % incdir)

        cmd.extend(files)

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

async def SimLib(runner, input):
    builder = SimLibBuilder()
    return await builder.run(runner, input)

