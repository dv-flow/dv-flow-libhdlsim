#****************************************************************************
#* xcm_sim_lib_uvm.py
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
import logging
import shutil
from dv_flow.mgr import TaskDataResult, FileSet, TaskRunCtxt
from dv_flow.mgr.task_data import SeverityE
from .util import xcelium_cds_lib
from .vl_sim_data import PliLib

_log = logging.getLogger("xcm.SimLibUVM")

# Logical library the UVM packages are compiled into
UVM_LIBNAME = "uvm"


def xcelium_uvm_home(uvmhome: str):
    """Resolve `uvmhome` to a UVM installation directory, or None.

    Accepts an absolute path, or the name of a UVM bundled with Xcelium under
    `<tools>/methodology/UVM` (eg CDNS-1.2, CDNS-IEEE) -- the same values
    `xrun -uvmhome` takes.
    """
    if os.path.isabs(uvmhome):
        return uvmhome if os.path.isdir(uvmhome) else None
    xmvlog = shutil.which('xmvlog')
    if xmvlog is None:
        return None
    # Walk up from xmvlog to <tools>/methodology/UVM/<uvmhome>. xmvlog may
    # resolve to tools/bin, tools.lnx86/inca/bin, ... (see util.py)
    d = os.path.dirname(os.path.realpath(xmvlog))
    for _ in range(6):
        cand = os.path.join(d, "methodology", "UVM", uvmhome)
        if os.path.isdir(cand):
            return cand
        parent = os.path.dirname(d)
        if parent == d:
            break
        d = parent
    return None


async def SimLibUVM(ctxt: TaskRunCtxt, input):
    """Pre-compiles the Xcelium-bundled UVM into a logical library.

    Mirrors what `xrun -uvm` does internally, split across the multi-step
    flow: uvm_pkg + cdns_uvm_pkg are compiled once (xmvlog) into library
    `uvm`; the consuming SimImage gets the library (cds.lib DEFINE), the UVM
    include directories, the PLI library (a verilogPLI FileSet), and the UVM
    PLI/DPI libraries (forwarded to SimRun as -sv_lib). Without libuvmdpi the
    run fails with *F,NOLWSV on uvm_hdl_*.
    """
    uvmhome = input.params.uvmhome
    uvm_home = xcelium_uvm_home(uvmhome)
    if uvm_home is None:
        ctxt.error("SimLibUVM: UVM installation '%s' not found (xmvlog on PATH?)" % uvmhome)
        return TaskDataResult(status=1, changed=False, output=[])
    _log.debug("Using UVM from %s", uvm_home)

    src = os.path.join(uvm_home, "sv", "src")
    additions = os.path.join(uvm_home, "additions", "sv")
    libdir64 = os.path.join(additions, "lib", "64bit")
    uvm_pkg = os.path.join(src, "uvm_pkg.sv")
    cdns_uvm_pkg = os.path.join(additions, "cdns_uvm_pkg.sv")

    if not os.path.isfile(uvm_pkg):
        ctxt.error("SimLibUVM: %s is not a UVM installation (no sv/src/uvm_pkg.sv)" % uvm_home)
        return TaskDataResult(status=1, changed=False, output=[])

    # Cadence additions (recording, messaging, Tcl) are present in the CDNS-*
    # bundles; a plain Accellera UVM_HOME has only uvm_pkg.
    has_additions = os.path.isfile(cdns_uvm_pkg)

    # Bundled PLI/DPI layer. Without it (eg an Accellera UVM given by path)
    # UVM is built with UVM_NO_DPI, as the other DPI-less flows do.
    dpilibs = [f for f in ("libuvmpli.so", "libuvmdpi.so")
               if os.path.isfile(os.path.join(libdir64, f))]
    defines = []
    if "libuvmdpi.so" not in dpilibs:
        ctxt.marker(
            "SimLibUVM: no prebuilt UVM DPI in %s; compiling with UVM_NO_DPI" % uvm_home,
            SeverityE.Warning)
        defines.append("UVM_NO_DPI")

    status = 0
    changed = False
    memento = {"uvm_home": uvm_home, "defines": defines}
    ex_memento = input.memento
    marker = os.path.join(input.rundir, "libuvm.d")

    if not os.path.isfile(marker) or ex_memento != memento:
        libdir = os.path.join(input.rundir, UVM_LIBNAME)
        os.makedirs(libdir, exist_ok=True)
        ctxt.create("cds.lib", xcelium_cds_lib([(UVM_LIBNAME, libdir)]))

        cmd = ['xmvlog', '-sv', '-64bit', '-update', '-work', UVM_LIBNAME,
               '-incdir', src]
        if has_additions:
            cmd.extend(['-incdir', additions, '-define', 'USE_PARAMETERIZED_WRAPPER'])
        for define in defines:
            cmd.extend(['-define', define])
        cmd.append(uvm_pkg)
        if has_additions:
            cmd.append(cdns_uvm_pkg)

        status |= await ctxt.exec(cmd, logfile="xmvlog.log")

        if not status:
            with open(marker, "w") as fp:
                fp.write("\n")
        changed = True

    if status:
        return TaskDataResult(status=status, changed=changed, output=[])

    incdirs = [src] + ([additions] if has_additions else [])
    output = [
        FileSet(
            basedir=input.rundir,
            files=[UVM_LIBNAME],
            filetype="simLib"),
        ctxt.mkDataItem(
            type="hdlsim.SimCompileArgs",
            incdirs=incdirs,
            defines=defines),
    ]

    # The PLI library goes out as a verilogPLI FileSet, as SimPLI would emit
    # it: SimImage loads it at elaboration (-loadpli1 lib:uvm_pli_boot, which
    # records the systfs in the snapshot) and forwards it to SimRun, which
    # loads it again in xmsim. `access` is off: UVM's PLI needs no design
    # visibility, and -access +rwc would cost performance. Both libraries are
    # also loaded with -sv_lib at run time.
    if "libuvmpli.so" in dpilibs:
        output.append(FileSet(
            basedir=libdir64,
            files=["libuvmpli.so"],
            filetype="verilogPLI",
            attributes=PliLib(
                path=os.path.join(libdir64, "libuvmpli.so"),
                boot="uvm_pli_boot",
                access=False).attributes()))
    if len(dpilibs):
        output.append(FileSet(
            basedir=libdir64,
            files=dpilibs,
            filetype="systemVerilogDPI"))

    return TaskDataResult(
        status=0,
        changed=changed,
        memento=memento,
        output=output)
