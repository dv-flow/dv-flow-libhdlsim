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
import tarfile
import logging
from pathlib import Path
from typing import List
from dv_flow.mgr import TaskDataResult, FileSet, TaskRunCtxt
from dv_flow.mgr.task_data import TaskMarker, SeverityE

_log = logging.getLogger("vlt.SimLibUVM")

async def SimLibUVM(ctxt: TaskRunCtxt, input):
    """
    - Locate the UVM source archive in this package's share/ directory
      (prefers .tar.gz; falls back to .tar.bz2)
    - Extract into the task run directory (creates src/ there)
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
    else:
        # Locate archive relative to this file
        share_dir = Path(__file__).resolve().parent / "share"
        candidates = [share_dir / "uvm_src.tar.gz", share_dir / "uvm_src.tar.bz2"]
        archive = next((p for p in candidates if p.is_file()), None)

        if archive is None:
            markers.append(TaskMarker(
                severity=SeverityE.Error,
                msg=f"UVM source archive not found in {share_dir} (expected uvm_src.tar.gz or uvm_src.tar.bz2)"
            ))
            return TaskDataResult(status=1, changed=False, output=[], markers=markers)

        rundir = Path(input.rundir)
        dst_src = rundir / "src"
        uvm_pkg = dst_src / "uvm_pkg.sv"

        # Extract when needed
        if input.changed or not uvm_pkg.exists():
            try:
                rundir.mkdir(parents=True, exist_ok=True)
                with tarfile.open(archive, mode="r:*") as tf:
                    tf.extractall(path=rundir)
                changed = True
                _log.debug("Extracted %s into %s", archive, rundir)
            except Exception as e:
                markers.append(TaskMarker(
                    severity=SeverityE.Error,
                    msg=f"Failed to extract {archive}: {e}"
                ))
                return TaskDataResult(status=1, changed=False, output=[], markers=markers)
        uvm_home = rundir

    # Forward UVM fileset with required incdir and define
    fs = FileSet(
        filetype="systemVerilogSource",
        basedir=uvm_home,
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
