import os
import asyncio
import json
from typing import List
from dv_flow.libhdlsim.vl_sim_image_builder import VlSimImageBuilder
from dv_flow.mgr.task_data import TaskMarker, TaskMarkerLoc

class SimImageBuilder(VlSimImageBuilder):

    def getRefTime(self, rundir):
        if os.path.isfile(os.path.join(rundir, 'simv')):
            return os.path.getmtime(os.path.join(rundir, 'simv'))
        else:
            raise Exception("simv file (%s) does not exist" % os.path.join(rundir, 'simv'))
    
    async def build(self, input, files : List[str], incdirs : List[str], libs : List[str]):
        # Create the library map
        with open(os.path.join(input.rundir, 'synopsys_sim.setup'), 'w') as fp:
            for lib in libs:
                fp.write("%s: %s\n" % (os.path.basename(lib), lib))

        cmd = ['vcs', '-full64']

        if len(files):
            cmd.append('-sverilog')

            for incdir in incdirs:
                cmd.append('+incdir+%s' % incdir)

        if len(libs):
            cmd.extend(['-liblist', "+".join(os.path.basename(l) for l in libs)])


        cmd.extend(files)

        if len(input.params.top):
            cmd.extend(['-top', "+".join(input.params.top)])

            self._log.debug("VCS command: %s" % str(cmd))

        fp = open(os.path.join(input.rundir, 'build.log'), "w")
        fp.write("Command: %s" % str(cmd))
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=input.rundir,
            stdout=fp,
            stderr=asyncio.subprocess.STDOUT)

        await proc.wait()
        fp.close()

        if proc.returncode != 0:
            self.markers.append(
                TaskMarker(
                    severity="error", 
                    msg="vcs command failed"))
        
        return proc.returncode

async def SimImage(runner, input):
    builder = SimImageBuilder()
    return await builder.run(runner, input)

