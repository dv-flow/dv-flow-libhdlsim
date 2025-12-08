#****************************************************************************
#* vlt_sim_lib_uvm.py
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
import logging
import shutil
from pathlib import Path
from typing import List
from dv_flow.mgr import TaskDataResult, FileSet, TaskRunCtxt
from dv_flow.mgr.task_data import TaskMarker, SeverityE

_log = logging.getLogger("vlt.SimLibUVM")

async def SimLibUVM(ctxt: TaskRunCtxt, input):
    """
    - Check $UVM_HOME first
    - Then check for UVM in Verilator's share directory
    - Forward a FileSet with:
        files:   [src/uvm_pkg.sv]
        incdirs: [src]
        defines: [UVM_NO_DPI]
    """
    status = 0
    changed = False
    markers: List[TaskMarker] = []

    if "UVM_HOME" in ctxt.env.keys():
        uvm_home = ctxt.env["UVM_HOME"]
        _log.info("Using UVM from $UVM_HOME: %s", uvm_home)
    else:
        # Try to find UVM in Verilator's share directory
        uvm_home = None
        verilator_bin = shutil.which("verilator")
        if verilator_bin is not None:
            verilator_bin_dir = Path(verilator_bin).resolve().parent
            # Check both possible locations: share/uvm and share/verilator/uvm
            for uvm_subpath in ["share/uvm", "share/verilator/uvm"]:
                verilator_share_uvm = verilator_bin_dir.parent / uvm_subpath
                if verilator_share_uvm.is_dir():
                    uvm_home = verilator_share_uvm
                    _log.info("Using UVM from Verilator share: %s", uvm_home)
                    break

        if uvm_home is None:
            markers.append(TaskMarker(
                severity=SeverityE.Error,
                msg="UVM not found: set $UVM_HOME or install UVM with Verilator"
            ))
            return TaskDataResult(status=1, changed=False, output=[], markers=markers)

    # Forward UVM fileset with required incdir and define
    fs = FileSet(
        filetype="systemVerilogSource",
        basedir=str(uvm_home),
        files=["src/uvm_pkg.sv"],
        incdirs=["src"],
        defines=["UVM_NO_DPI"]
    )

    return TaskDataResult(
        status=status,
        changed=changed,
        output=[fs],
        markers=markers
    )
