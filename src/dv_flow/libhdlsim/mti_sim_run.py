
import asyncio
import json
import os
from typing import List
from dv_flow.mgr import Task, TaskDataResult, FileSet

async def SimRun(runner, input) -> TaskDataResult:
    vl_fileset = json.loads(input.params.simdir)

    build_dir = vl_fileset["basedir"]

    cmd = [
        'vsim',
        '-batch',
        '-do',
        "run -a; quit -f",
        "simv_opt",
        "-work",
        os.path.join(build_dir, 'work')
    ]

    fp = open(os.path.join(input.rundir, 'sim.log'), "w")
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        cwd=input.rundir,
        stdout=fp,
        stderr=asyncio.subprocess.STDOUT)

    await proc.wait()
    fp.close()

    return TaskDataResult(
        output=[FileSet(
                src=input.name, 
                filetype="simRunDir", 
                basedir=input.rundir,
                status=0)],
    )
