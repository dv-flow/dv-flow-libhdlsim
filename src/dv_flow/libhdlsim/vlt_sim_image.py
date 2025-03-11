import asyncio
import os
import logging
from typing import ClassVar, List
from dv_flow.mgr import TaskDataResult
from dv_flow.libhdlsim.vl_sim_image_builder import VlSimImageBuilder
from dv_flow.mgr.task_data import TaskMarker, TaskMarkerLoc

class SimImageBuilder(VlSimImageBuilder):

    _log : ClassVar = logging.getLogger("SimImageBuilder[vlt]")

    def getRefTime(self, rundir):
        if os.path.isfile(os.path.join(rundir, 'obj_dir/simv')):
            return os.path.getmtime(os.path.join(rundir, 'obj_dir/simv'))
        else:
            raise Exception("simv file (%s) does not exist" % os.path.join(rundir, 'obj_dir/simv'))

    async def build(self, input, files : List[str], incdirs : List[str], libs : List[str]):
        cmd = ['verilator', '--binary', '-o', 'simv']

        for incdir in incdirs:
            cmd.append('+incdir+%s' % incdir)

        cmd.extend(files)

        for top in input.params.top:
            cmd.extend(['--top-module', top])

        fp = open(os.path.join(input.rundir, 'build.log'), "w")
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=input.rundir,
            stdout=fp,
            stderr=asyncio.subprocess.STDOUT)

        await proc.wait()
        fp.close()

        self._log.debug("proc.returncode: %d" % proc.returncode)

        # Parse the log for warnings and error
        self.parseLog(os.path.join(input.rundir, 'build.log'))

        if proc.returncode != 0:
            self.markers.append(
                TaskMarker(
                    severity="error", 
                    msg="verilator command failed"))
        else:
            pass

        return proc.returncode

async def SimImage(runner, input) -> TaskDataResult:
    builder = SimImageBuilder()
    return await builder.run(runner, input)

