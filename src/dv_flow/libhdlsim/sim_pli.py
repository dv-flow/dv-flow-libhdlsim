#****************************************************************************
#* sim_pli.py
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
"""SimPLI: attach a pre-built PLI 1.0 (or VPI) shared library to a simulation.

The task builds nothing and runs no tool. It validates the library (and its
optional `.tab` table) and describes it as a FileSet that SimImage consumes:

  interface: pli1 -> filetype `verilogPLI`, attributes `boot=`, `tab=`, `access=`
  interface: vpi  -> filetype `verilogVPI`, attribute `entrypoint=` (the
                     existing VPI plumbing, unchanged)

Each simulator backend maps a `verilogPLI` FileSet to its own flags (see
PliLib in vl_sim_data and each backend's check_pli).
"""
import os
from typing import List
from dv_flow.mgr import FileSet, TaskDataResult
from dv_flow.mgr.task_data import TaskMarker, SeverityE
from dv_flow.libhdlsim.vl_sim_data import PliLib

INTERFACES = ("pli1", "vpi")


def _abspath(srcdir, path):
    path = os.path.expandvars(os.path.expanduser(path.strip()))
    if not os.path.isabs(path):
        path = os.path.join(srcdir or "", path)
    return os.path.normpath(path)


def _mtime(path):
    try:
        return os.path.getmtime(path)
    except OSError:
        return None


async def SimPLI(ctxt, input) -> TaskDataResult:
    params = input.params
    markers : List[TaskMarker] = []

    def error(msg):
        markers.append(TaskMarker(severity=SeverityE.Error, msg=msg))

    interface = (getattr(params, "interface", "pli1") or "pli1").strip()
    lib_p = (getattr(params, "lib", "") or "").strip()
    tab_p = (getattr(params, "tab", "") or "").strip()
    boot = (getattr(params, "boot", "") or "").strip() or None
    access = bool(getattr(params, "access", True))

    if interface not in INTERFACES:
        error("SimPLI: interface '%s' is not one of %s" % (
            interface, ", ".join(INTERFACES)))

    # The library: the `lib` param, or every consumed sharedLib FileSet.
    shared = []
    for fs in input.inputs:
        if getattr(fs, "type", None) == "std.FileSet" and \
                getattr(fs, "filetype", None) == "sharedLib":
            shared.extend(os.path.join(fs.basedir, f) for f in fs.files)

    libs = []
    if lib_p:
        if shared:
            error("SimPLI: both `lib` (%s) and sharedLib inputs (%s) supply a "
                  "library; give one or the other" % (lib_p, ", ".join(shared)))
        libs.append(_abspath(input.srcdir, lib_p))
    else:
        libs.extend(os.path.normpath(os.path.abspath(p)) for p in shared)
        if not libs:
            error("SimPLI: no library: set `lib` or consume a sharedLib FileSet")

    for lib in libs:
        if not os.path.isfile(lib):
            error("SimPLI: library %s does not exist" % lib)

    tab = None
    if tab_p:
        tab = _abspath(input.srcdir, tab_p)
        if interface == "vpi":
            error("SimPLI: `tab` is a PLI 1.0 table; it does not apply to "
                  "interface: vpi")
        elif not os.path.isfile(tab):
            error("SimPLI: table file %s does not exist" % tab)
        elif len(libs) > 1:
            error("SimPLI: `tab` names functions in one library, but %d "
                  "libraries were supplied" % len(libs))

    if interface == "pli1" and not boot and not tab:
        # Valid on Questa (the library exports veriusertfs/init_usertfs), but
        # nothing else can find the table. The backend raises the hard error.
        markers.append(TaskMarker(
            severity=SeverityE.Warning,
            msg="SimPLI: neither `boot` nor `tab` is set; only Questa can load "
                "this library (via veriusertfs or init_usertfs)"))

    if any(m.severity == SeverityE.Error for m in markers):
        return TaskDataResult(status=1, markers=markers)

    output = []
    for lib in libs:
        if interface == "vpi":
            output.append(FileSet(
                src=input.name,
                filetype="verilogVPI",
                basedir=os.path.dirname(lib),
                files=[os.path.basename(lib)],
                attributes=(["entrypoint=%s" % boot] if boot else [])))
        else:
            output.append(FileSet(
                src=input.name,
                filetype="verilogPLI",
                basedir=os.path.dirname(lib),
                files=[os.path.basename(lib)],
                attributes=PliLib(path=lib, boot=boot, tab=tab,
                                  access=access).attributes()))

    # The FileSets carry paths only, so report a change when a library or the
    # table is replaced in place. Consumers (SimImage) rebuild on it.
    memento = {"files": [[p, _mtime(p)] for p in libs + ([tab] if tab else [])]}
    changed = (input.memento is None or
               dict(input.memento).get("files") != memento["files"])

    return TaskDataResult(
        status=0,
        changed=changed,
        output=output,
        memento=memento,
        markers=markers)
