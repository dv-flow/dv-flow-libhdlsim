
import asyncio
import json
import os
from typing import List
from dv_flow.mgr import TaskDataResult, FileSet
from dv_flow.libhdlsim.vl_sim_image_builder import VlSimImageBuilder

async def SimRun(runner, input) -> TaskDataResult:
    vl_fileset = json.loads(input.params.simdir)
    
    build_dir = vl_fileset["basedir"]

    cmd = [
        os.path.join(build_dir, 'obj_dir/simv'),
    ]

    fp = open(os.path.join(input.rundir, 'sim.log'), "w")
    proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=input.rundir,
            stdout=fp)

    await proc.wait()

    fp.close()

    return TaskDataResult(
        output=[FileSet(
                src=input.name, 
                filetype="simRunDir", 
                basedir=input.rundir)],
    )
