#****************************************************************************
#* vcs_sim_lib_uvm.py
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
import os
import asyncio
import json
import logging
import shutil
import pathlib
from typing import List
from dv_flow.mgr import TaskDataResult, FileSet, TaskRunCtxt
from dv_flow.mgr.task_data import TaskMarker, TaskMarkerLoc

_log = logging.getLogger("SimLibUVM")

async def SimLibUVM(ctxt : TaskRunCtxt, input):
    ex_memento = input.memento
    status = 0
    markers = []

    which_vlogan = shutil.which('vlogan')
    if which_vlogan is None:
        raise Exception("vlogan not found in PATH")

    vcs_home = os.path.dirname(os.path.dirname(which_vlogan))
    changed = False

    # Determine whether we're up-to-date
    if not os.path.isfile(os.path.join(input.rundir, 'libuvm.d')):

        with open(os.path.join(input.rundir, 'synopsys_sim.setup'), 'w') as fp:
            fp.write("uvm: %s\n" % os.path.join(input.rundir, 'uvm'))
        

        cmd = ['vlogan', '-full64', '-sverilog', '-work', 'uvm', '-ntb_opts', 'uvm-1.2']

        _log.debug("Running vlogan: %s", " ".join(cmd))

        fp = open(os.path.join(input.rundir, 'build.log'), "w")
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=input.rundir,
            stdout=fp,
            stderr=asyncio.subprocess.STDOUT)

        await proc.wait()
        fp.close()

        if proc.returncode != 0:
            markers.append(
                TaskMarker(
                    severity="error", 
                    msg="vlogan(UVM) command failed"))
            status = 1

        changed = True

    return TaskDataResult(
        memento=(ex_memento if status == 0 else None),
        changed=changed,
        output=[
            FileSet(
                basedir=os.path.join(vcs_home, "etc/uvm-1.2"),
                filetype="verilogIncDir"),
            FileSet(
                basedir=os.path.join(input.rundir, "uvm"),
                filetype="simLib"),
            ctxt.mkDataItem(
                type="hdlsim.SimElabArgs",
                args=["-ntb_opts", "uvm-1.2"]
            )
        ],
        status=status,
        markers=markers)

