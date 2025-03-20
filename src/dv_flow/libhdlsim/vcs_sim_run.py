#****************************************************************************
#* vcs_sim_run.py
#*
#* Copyright 2023-2025 Matthew Ballance and Contributors
#*
#* Licensed under the Apache License, Version 2.0 (the "License"); you may 
#* not use this file except in compliance with the License.  
#* You may obtain a copy of the License at:
#*  
#*   http://www.apache.org/licenses/LICENSE-2.0
#*  
#* Unless required by applicable law or agreed to in writing, software 
#* distributed under the License is distributed on an "AS IS" BASIS, 
#* WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.  
#* See the License for the specific language governing permissions and 
#* limitations under the License.
#*
#* Created on:
#*     Author: 
#*
#****************************************************************************
import asyncio
import json
import os
from typing import List
from dv_flow.mgr import Task, TaskDataResult, FileSet

async def SimRun(runner, input) -> TaskDataResult:
    vl_fileset = json.loads(input.params.simdir)

    build_dir = vl_fileset["basedir"]

    cmd = [
        os.path.join(build_dir, 'simv'),
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
                basedir=input.rundir)],
    )
