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
      DPI sources: without the register backdoor and without Verilator's VPI
      runtime by default, or all of it with --vpi when backdoor is set.

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

    backdoor = getattr(input.params, "backdoor", False)
    if isinstance(backdoor, str):
        backdoor = backdoor.lower() in ("1", "true", "yes")

    output = []

    if use_dpi and not backdoor:
        # The UVM DPI layer without Verilator's VPI runtime (no --vpi). Only
        # two things in it call VPI: the uvm_hdl_* register backdoor (left
        # out: UVM_HDL_NO_DPI) and the command-line reader, which needs just
        # vpi_get_vlog_info(). A generated wrapper supplies that one function
        # from the Verilated context, the same way verilated_vpi.cpp does,
        # so UVM keeps real regex matching and +UVM_* plusargs.
        #
        # Building without --vpi matters: with it, Verilator's main runs every
        # vlog_startup_routines it can see, including those of DPI libraries
        # that also support VPI-only simulators (pyhdl-if, for one), and
        # Verilator implements only part of VPI.
        _log.info("Using UVM DPI layer (no VPI) from %s", dpi_dir)
        wrapper = os.path.join(input.rundir, "uvm_dpi_novpi.cc")
        text = _NOVPI_WRAPPER
        if not os.path.isfile(wrapper) or open(wrapper).read() != text:
            with open(wrapper, "w") as fp:
                fp.write(text)
            changed = True
        output.append(FileSet(
            filetype="systemVerilogSource",
            basedir=str(uvm_home),
            files=["src/uvm_pkg.sv"],
            incdirs=["src"],
            defines=["UVM_HDL_NO_DPI"]))
        output.append(FileSet(
            filetype="cppSource",
            basedir=input.rundir,
            files=["uvm_dpi_novpi.cc"],
            incdirs=[dpi_dir]))
    elif use_dpi:
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


# UVM's DPI layer minus the register backdoor, for a build without --vpi.
# Mirrors uvm_dpi.cc, leaving out uvm_hdl.c, and defines the one VPI routine
# uvm_svcmd_dpi.c uses.
_NOVPI_WRAPPER = """\
// Generated by dv-flow-libhdlsim (vlt.SimLibUVM). Do not edit.
#include "verilated.h"
// argc/argv are reachable only through Verilator's internal header, which
// verilated_vpi.cpp includes under this guard to implement the same routine.
#define VERILATOR_VERILATED_VPI_CPP_
#include "verilated_imp.h"
#include "vpi_user.h"

extern "C" PLI_INT32 vpi_get_vlog_info(p_vpi_vlog_info vlog_info_p) {
    const auto argc_argv = Verilated::threadContextp()->impp()->argc_argv();
    vlog_info_p->argc = argc_argv.first;
    vlog_info_p->argv = argc_argv.second;
    vlog_info_p->product = const_cast<PLI_BYTE8*>(Verilated::productName());
    vlog_info_p->version = const_cast<PLI_BYTE8*>(Verilated::productVersion());
    return 1;
}

extern "C" {
#include <stdlib.h>
#include "uvm_dpi.h"

int uvm_re_match(const char * re, const char *str);
const char * uvm_glob_to_re(const char *glob);
void push_data(int lvl,char *entry, int cmd);
void walk_level(int lvl, int argc, char**argv,int cmd);
const char *uvm_dpi_get_next_arg_c (int init);
extern char* uvm_dpi_get_tool_name_c ();
extern char* uvm_dpi_get_tool_version_c ();
extern regex_t* uvm_dpi_regcomp (char* pattern);
extern int uvm_dpi_regexec (regex_t* re, char* str);
extern void uvm_dpi_regfree (regex_t* re);

#include "uvm_common.c"
#include "uvm_regex.cc"
#include "uvm_svcmd_dpi.c"
}
"""

