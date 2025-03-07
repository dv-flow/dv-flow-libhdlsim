import os
import asyncio
import json
import shutil
from pathlib import Path
from typing import List
from dv_flow.libhdlsim.vl_sim_lib_builder import VlSimLibBuilder

class SimLibBuilder(VlSimLibBuilder):

    def getRefTime(self, rundir):
        if os.path.isfile(os.path.join(rundir, 'simlib.d')):
            return os.path.getmtime(os.path.join(rundir, 'simlib.d'))
        else:
            raise Exception("simv file (%s) does not exist" % os.path.join(rundir, 'simlib.d'))
    
    async def build(self, input, files : List[str], incdirs : List[str], libs : List[str]):

        if not os.path.isdir(os.path.join(input.rundir, input.params.libname)):
            os.makedirs(os.path.join(input.rundir, input.params.libname), exist_ok=True)

        # Create a library map
        with open(os.path.join(input.rundir, 'synopsys_sim.setup'), 'w') as fp:
            fp.write("%s: %s\n" % (
                input.params.libname, 
                os.path.join(input.rundir, input.params.libname)))

            for lib in libs:
                fp.write("%s: %s\n" % (os.path.basename(lib), lib))

        cmd = ['vlogan', '-full64', '-sverilog', '-work', input.params.libname]

        if len(libs):
            cmd.extend(['-liblist', "+".join(os.path.basename(l) for l in libs)])

        for incdir in incdirs:
            cmd.append('+incdir+%s' % incdir)

        cmd.extend(files)

        self._log.debug("Running vlogan: %s", " ".join(cmd))

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
        else:
            Path(os.path.join(input.rundir, 'simlib.d')).touch()

async def SimLib(runner, input):
    builder = SimLibBuilder()
    return await builder.run(runner, input)

