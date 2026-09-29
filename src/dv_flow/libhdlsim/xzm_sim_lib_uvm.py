#****************************************************************************
#* xzm_sim_lib_uvm.py
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
#****************************************************************************
import logging
import os
from dv_flow.mgr import TaskDataResult, FileSet, TaskRunCtxt
from dv_flow.mgr.task_data import TaskMarker, SeverityE
from dv_flow.libhdlsim import xzm_tool

_log = logging.getLogger("xzm.SimLibUVM")

async def SimLibUVM(ctxt: TaskRunCtxt, input):
    """
    - Check $UVM_HOME first
    - Then the UVM that ships with xezim (<prefix>/share/uvm)
    - Forward a FileSet with:
        files:   [src/uvm_pkg.sv]
        incdirs: [src]

    xezim implements UVM's DPI layer (regex matching, command-line
    processing, uvm_hdl_* backdoor) internally, so no DPI sources are
    forwarded and UVM_NO_DPI is not needed. `dpi: false` still defines
    UVM_NO_DPI, to reproduce a DPI-less simulator's behavior; `auto` and
    `true` are the same thing here.
    """
    def add_marker(severity, msg):
        ctxt.add_marker(TaskMarker(severity=severity, msg=msg))

    dpi_mode = getattr(input.params, "dpi", "auto")
    if isinstance(dpi_mode, bool):
        dpi_mode = "true" if dpi_mode else "false"
    dpi_mode = str(dpi_mode).lower()

    if dpi_mode not in ("auto", "true", "false"):
        add_marker(SeverityE.Error,
            "SimLibUVM: invalid dpi=%s (expected auto, true or false)" % dpi_mode)
        return TaskDataResult(status=1, changed=False, output=[])

    if "UVM_HOME" in ctxt.env.keys():
        uvm_home = ctxt.env["UVM_HOME"]
        _log.info("Using UVM from $UVM_HOME: %s", uvm_home)
    else:
        uvm_home = None
        prefix = xzm_tool.xezim_prefix(ctxt.env)
        if prefix is not None and os.path.isdir(os.path.join(prefix, "share", "uvm")):
            uvm_home = os.path.join(prefix, "share", "uvm")
            _log.info("Using UVM from xezim share: %s", uvm_home)

        if uvm_home is None:
            add_marker(SeverityE.Error,
                "UVM not found: set $UVM_HOME or use a xezim installation "
                "that ships share/uvm")
            return TaskDataResult(status=1, changed=False, output=[])

    fs = FileSet(
        filetype="systemVerilogSource",
        basedir=str(uvm_home),
        files=["src/uvm_pkg.sv"],
        incdirs=["src"])
    if dpi_mode == "false":
        fs.defines = ["UVM_NO_DPI"]

    return TaskDataResult(status=0, changed=False, output=[fs])
