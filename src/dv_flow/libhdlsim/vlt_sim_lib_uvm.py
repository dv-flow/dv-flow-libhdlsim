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
import os
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
      plus, when the UVM installation carries a Verilator DPI backend, the
      DPI sources and a request for Verilator's VPI runtime.

    UVM_NO_DPI is emitted *only* as a fallback, when the DPI sources cannot
    be located. It downgrades uvm_re_match to glob-only matching and disables
    register backdoor access, so it is a last resort rather than the default.
    """
    status = 0
    changed = False

    def add_marker(severity, msg):
        # Report through ctxt rather than TaskDataResult.markers: doing both
        # records the marker twice. ctxt is the path the log parsers use.
        ctxt.add_marker(TaskMarker(severity=severity, msg=msg))

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
            add_marker(SeverityE.Error,
                "UVM not found: set $UVM_HOME or install UVM with Verilator")
            return TaskDataResult(status=1, changed=False, output=[])

    # Is a Verilator-capable DPI layer present? uvm_hdl_verilator.c is the
    # thing that actually makes uvm_dpi.cc link -- stock Accellera UVM has
    # backends only for VCS/Questa/Xcelium and #errors otherwise. Probing for
    # it (rather than for a marker file) means a hand-assembled $UVM_HOME that
    # carries the backend works too.
    dpi_dir = os.path.join(str(uvm_home), "src", "dpi")
    dpi_cc = os.path.join(dpi_dir, "uvm_dpi.cc")
    dpi_backend = os.path.join(dpi_dir, "uvm_hdl_verilator.c")
    dpi_capable = os.path.isfile(dpi_cc) and os.path.isfile(dpi_backend)

    dpi_mode = getattr(input.params, "dpi", "auto")
    if isinstance(dpi_mode, bool):
        dpi_mode = "true" if dpi_mode else "false"
    dpi_mode = str(dpi_mode).lower()

    if dpi_mode not in ("auto", "true", "false"):
        add_marker(SeverityE.Error,
            "SimLibUVM: invalid dpi=%s (expected auto, true or false)" % dpi_mode)
        return TaskDataResult(status=1, changed=False, output=[])

    if dpi_mode == "false":
        use_dpi = False
    elif dpi_mode == "true":
        if not dpi_capable:
            add_marker(SeverityE.Error,
                ("SimLibUVM: dpi=true, but %s has no Verilator DPI backend "
                     "(missing %s). Install a verilator-bin that ships the UVM "
                     "DPI overlay, or set dpi=auto/false."
                     % (uvm_home, dpi_backend)))
            return TaskDataResult(status=1, changed=False, output=[])
        use_dpi = True
    else:
        use_dpi = dpi_capable

    output = []

    if use_dpi:
        _log.info("Using UVM DPI layer from %s", dpi_dir)
        output.append(FileSet(
            filetype="systemVerilogSource",
            basedir=str(uvm_home),
            files=["src/uvm_pkg.sv"],
            incdirs=["src"]))
        # uvm_dpi.cc is the single translation unit that pulls in uvm_common.c,
        # uvm_regex.cc, uvm_hdl.c and uvm_svcmd_dpi.c.
        output.append(FileSet(
            filetype="cppSource",
            basedir=dpi_dir,
            files=["uvm_dpi.cc"]))
        # Declare the VPI need rather than string-injecting --vpi: uvm_hdl.c
        # (via uvm_hdl_verilator.c) and uvm_svcmd_dpi.c both call into VPI.
        # public_flat_rw is deliberately NOT requested -- it inhibits
        # optimization design-wide, and most UVM testbenches never use
        # register backdoor access. Users who do need it set public_flat_rw
        # on SimImage, or mark signals /*verilator public*/.
        output.append(ctxt.mkDataItem("hdlsim.SimCompileArgs", vpi=True))
    else:
        if dpi_mode == "auto":
            add_marker(SeverityE.Warning,
                ("SimLibUVM: no Verilator UVM DPI backend found in %s; "
                     "falling back to UVM_NO_DPI. uvm_re_match degrades to "
                     "glob-only matching (real regexes will not match) and "
                     "register backdoor access is unavailable." % dpi_dir))
        output.append(FileSet(
            filetype="systemVerilogSource",
            basedir=str(uvm_home),
            files=["src/uvm_pkg.sv"],
            incdirs=["src"],
            defines=["UVM_NO_DPI"]))

    return TaskDataResult(
        status=status,
        changed=changed,
        output=output
    )
