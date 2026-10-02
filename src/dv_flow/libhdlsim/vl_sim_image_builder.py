#****************************************************************************
#* vl_sim_image_builder.py
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
import json
import logging
import shutil
import dataclasses as dc
from pydantic import BaseModel
import pydantic.dataclasses as pdc
from toposort import toposort
from dv_flow.mgr import FileSet, TaskDataResult, TaskMarker, TaskRunCtxt
from typing import Any, ClassVar, List, Optional, Tuple
from dv_flow.mgr.task_data import SeverityE
from dv_flow.libhdlsim import cov
from dv_flow.libhdlsim.log_parser import LogParser
from dv_flow.libhdlsim.vl_sim_data import VlSimImageData, pli_add, pli_from_fileset
from svdep import FileCollection, TaskCheckUpToDate

from .util import merge_tokenize

_log = logging.getLogger("vl_sim_image_builder")

async def check_sim_image_uptodate(ctxt, ref_path: str) -> bool:
    """Shared svdep-based uptodate check for all SimImage variants.

    Returns True (task is up-to-date, skip build) or False (rebuild needed).
    Called as a custom uptodate: callable from each simulator's flow definition.

    ctxt  -- UpToDateCtxt provided by the framework
    ref_path -- absolute path to the output binary / sentinel file
    """
    memento = ctxt.memento
    if not memento or not memento.get("svdeps"):
        _log.debug("check_sim_image_uptodate: no svdeps in memento, rebuilding")
        return False

    if not os.path.isfile(ref_path):
        _log.debug("check_sim_image_uptodate: ref file missing (%s), rebuilding" % ref_path)
        return False

    try:
        ref_mtime = os.path.getmtime(ref_path)
    except OSError:
        return False

    # Gather SV source files and include dirs from task inputs (mirrors _gatherSvSources)
    files = []
    incdirs = []
    for fs in ctxt.inputs:
        if getattr(fs, "type", None) != "std.FileSet":
            continue
        ft = getattr(fs, "filetype", "")

        # A PLI library (and its table) is linked into the image on VCS and
        # read by xmelab on Xcelium, so one newer than the image forces a
        # rebuild. svdep tracks only HDL sources.
        if ft == "verilogPLI":
            for lib in pli_from_fileset(fs):
                for path in (lib.path, lib.tab):
                    try:
                        if path and os.path.getmtime(path) > ref_mtime:
                            _log.debug("check_sim_image_uptodate: %s is newer than the image" % path)
                            return False
                    except OSError:
                        return False
            continue
        basedir = getattr(fs, "basedir", "")
        fs_incdirs = getattr(fs, "incdirs", [])
        fs_files   = getattr(fs, "files", [])

        if ft in ("systemVerilogSource", "verilogSource"):
            files.extend(os.path.join(basedir, f) for f in fs_files)
            # incdirs embedded in the FileSet (from incdirs= param)
            incdirs.extend(os.path.join(basedir, d) for d in fs_incdirs)
        elif ft == "verilogIncDir":
            if basedir.strip():
                incdirs.append(basedir)
        elif ft in ("verilogInclude", "systemVerilogInclude"):
            # basedir is the include dir itself when no explicit incdirs
            if fs_incdirs:
                incdirs.extend(os.path.join(basedir, d) for d in fs_incdirs)
            elif basedir.strip():
                incdirs.append(basedir)

    try:
        info = FileCollection.from_dict(memento["svdeps"])
        uptodate = TaskCheckUpToDate(files, incdirs).check(info, ref_mtime)
        _log.debug("check_sim_image_uptodate: %s" % ("uptodate" if uptodate else "rebuild needed"))
        return uptodate
    except Exception as e:
        _log.debug("check_sim_image_uptodate: svdep check failed (%s), rebuilding" % e)
        return False

@dc.dataclass
class VlSimImageBuilder(object):
    ctxt : TaskRunCtxt
    input : Any = dc.field(default=None)
    markers : List = dc.field(default_factory=list)
    output : List = dc.field(default_factory=list)
    memento : Any = dc.field(default=None)
    suppress : List = dc.field(default_factory=list)
    # Coverage levels requested by consumed SimCovArgs items (validated and
    # combined with the `cov` param in run()).
    cov_requests : List[str] = dc.field(default_factory=list)

    _log : ClassVar = logging.getLogger("VlSimImage")

    # When True, VPI libraries consumed by this SimImage are forwarded to
    # downstream consumers (eg SimRun) instead of being baked into the image.
    # Simulators that load VPI at run time (Icarus, Questa/ModelSim, Xcelium)
    # set this so that the flow graph is identical across simulators: the user
    # always attaches VPI libraries to SimImage, never directly to SimRun.
    forward_vpi : ClassVar[bool] = False

    # Same as forward_vpi, for PLI 1.0 libraries (verilogPLI). Set by
    # simulators that load PLI at run time (Icarus, Questa, Xcelium).
    forward_pli : ClassVar[bool] = False

    def check_pli(self, data : VlSimImageData) -> int:
        """Backend hook, called once after inputs are gathered: validate
        data.pli for this simulator. Returns a nonzero status (with an Error
        marker) to skip the build.

        The base rejects any PLI library. Backends that load PLI 1.0 override.
        """
        if len(data.pli):
            self.markers.append(TaskMarker(
                severity=SeverityE.Error,
                msg="%s does not support PLI 1.0 libraries (%s)" % (
                    self._sim_label(), ", ".join(l.path for l in data.pli))))
            return 1
        return 0

    def getRefTime(self, rundir):
        raise NotImplementedError()

    def cov_kinds(self, level : str) -> Optional[List[str]]:
        """Backend hook: the coverage kinds (cov.KINDS) this backend enables
        at `level`, or None when it doesn't support coverage.

        The base returns None: SimImage then warns once and builds as if
        `none`. A backend that supports coverage returns [] at 'none' and maps
        `data.cov_level` to its own flags in build().
        """
        return None

    def _resolve_cov(self, input, data : VlSimImageData) -> int:
        """Set data.cov_level to the highest of the `cov` param and every
        consumed SimCovArgs. Returns a nonzero status on an unknown level."""
        requested = [getattr(input.params, "cov", "none") or "none"]
        requested.extend(self.cov_requests)
        try:
            level = cov.max_level(*requested)
        except ValueError as e:
            self.markers.append(TaskMarker(
                severity=SeverityE.Error, msg=str(e)))
            return 1
        if level != "none" and self.cov_kinds(level) is None:
            self.markers.append(TaskMarker(
                severity=SeverityE.Warning,
                msg="%s does not support coverage yet (requested '%s'); "
                    "building without it" % (self._sim_label(), level)))
            level = "none"
        data.cov_level = level
        return 0

    def _sim_label(self) -> str:
        sim = getattr(getattr(self.input, "params", None), "sim", "") or ""
        if sim and sim != "unset":
            return sim
        mod = type(self).__module__.rsplit(".", 1)[-1]
        return mod.split("_", 1)[0]

    async def build(self, input, data : VlSimImageData) -> Tuple[int,bool]:
        raise NotImplementedError()

    def parseLog(self, log):
        parser = LogParser(notify=lambda m: self.markers.append(m), suppress=self.suppress)
        with open(log, "r") as fp:
            for line in fp.readlines():
                parser.line(line)

    async def run(self, ctxt, input) -> TaskDataResult:
        for f in os.listdir(input.rundir):
            self._log.debug("sub-elem: %s" % f)
        status = 0

        self.input = input
        data = VlSimImageData()
        data.top.extend(input.params.top)
        data.args.extend(merge_tokenize(input.params.args))
        data.compargs.extend(merge_tokenize(input.params.compargs))
        data.elabargs.extend(merge_tokenize(input.params.elabargs))
        data.incdirs.extend(merge_tokenize(input.params.incdirs))
        data.defines.extend(merge_tokenize(input.params.defines))
        # Convert vpilibs from params (strings) to tuples (path, None)
        data.vpi.extend([(vpi, None) for vpi in input.params.vpilibs])
        data.dpi.extend(input.params.dpilibs)
        # Optional params: not every simulator's SimImage declares these
        data.vpi_enable = bool(getattr(input.params, "vpi", False))
        data.public_flat_rw = bool(getattr(input.params, "public_flat_rw", False))
        data.trace = input.params.trace
        data.timing = input.params.timing if hasattr(input.params, 'timing') else True

        self._gatherSvSources(data, input)

        self._log.debug("files: %s" % str(data.files))

        if self.check_pli(data) != 0:
            return TaskDataResult(status=1, markers=self.markers)

        if self._resolve_cov(input, data) != 0:
            return TaskDataResult(status=1, markers=self.markers)

        # Assemble suppress list from task params and connected SuppressWarnings datasets
        self.suppress = list(merge_tokenize(input.params.suppress_warnings)) if hasattr(input.params, 'suppress_warnings') else []
        for fs in input.inputs:
            if fs.type == "hdlsim.SuppressWarnings":
                self.suppress.extend(fs.codes)

        # The image must never carry a stale coverage record: drop any left by
        # an earlier build, and write the current one only once this build
        # succeeds.
        cov.remove_cov_json(input.rundir)

        status,in_changed = await self.build(input, data)

        if status == 0 and data.cov_level != "none":
            cov.write_cov_json(input.rundir, data.cov_level,
                               self.cov_kinds(data.cov_level) or [])


        self.output.append(FileSet(
                src=input.name,
                filetype="simDir",
                basedir=input.rundir))

        # Forward run-time environment (std.Env) to consumers (eg SimRun) so a
        # single upstream config task can attach to SimImage alone and still have
        # its environment reach the run.
        for fs in input.inputs:
            if getattr(fs, "type", None) == "std.Env":
                self.output.append(fs)

        # Forward VPI libraries to run-time consumers for simulators that load
        # VPI at run time (see forward_vpi). This keeps the user-facing flow
        # graph consistent: VPI libraries attach to SimImage for every simulator.
        if self.forward_vpi:
            for vpi_path, entrypoint in data.vpi:
                attrs = ["entrypoint=%s" % entrypoint] if entrypoint else []
                self.output.append(FileSet(
                    src=input.name,
                    filetype="verilogVPI",
                    basedir=os.path.dirname(vpi_path),
                    files=[os.path.basename(vpi_path)],
                    attributes=attrs))

        if self.forward_pli:
            for lib in data.pli:
                self.output.append(FileSet(
                    src=input.name,
                    filetype="verilogPLI",
                    basedir=os.path.dirname(lib.path),
                    files=[os.path.basename(lib.path)],
                    attributes=lib.attributes()))

        return TaskDataResult(
            memento=self.memento if status == 0 else None,
            status=status,
            output=self.output,
            changed=in_changed,
            markers=self.markers
        )
    
    def _gatherSvSources(self, data : VlSimImageData, input):
        # input must represent dependencies for all tasks related to filesets
        # references must support transitivity

        for fs in input.inputs:
            self._log.debug("Processing dataset of type %s from task %s" % (
                fs.type,
                fs.src
            ))
            if fs.type == "std.FileSet":
                self._log.debug("fs.filetype=%s fs.basedir=%s" % (fs.filetype, fs.basedir))
                data.defines.extend(fs.defines)

                if fs.filetype == "cSource" or fs.filetype == "cppSource":
                    for file in fs.files:
                        path = os.path.join(fs.basedir, file)
                        self._log.debug("path: basedir=%s fullpath=%s" % (fs.basedir, path))
                        data.csource.append(path)
                elif fs.filetype == "verilogIncDir":
                    if len(fs.basedir.strip()) > 0:
                        data.incdirs.append(fs.basedir)
                elif fs.filetype in ("verilogInclude", "systemVerilogInclude"):
                    self._addIncDirs(data, fs.basedir, fs.incdirs)
                elif fs.filetype == "simLib":
                    if len(fs.files) > 0:
                        for file in fs.files:
                            path = os.path.join(fs.basedir, file)
                            self._log.debug("path: basedir=%s fullpath=%s" % (fs.basedir, path))
                            if len(path.strip()) > 0:
                                data.libs.append(path)
                    else:
                        data.libs.append(fs.basedir)
                    self._addIncDirs(data, fs.basedir, fs.incdirs)
                elif fs.filetype == "verilatorMain":
                    # A user/tool-supplied C++ main (eg cocotb's verilator.cpp).
                    # Recorded separately so the Verilator SimImage can build in
                    # --exe mode with this main instead of generating one.
                    for file in fs.files:
                        data.verilator_main = os.path.join(fs.basedir, file)
                elif fs.filetype == "simPrimary":
                    # Xcelium MSIE primary snapshot (Type C). The physical
                    # library dir(s) carry the primary; the primary cell names
                    # ride along as `primtop=<name>` attributes.
                    if len(fs.files) > 0:
                        for file in fs.files:
                            path = os.path.join(fs.basedir, file)
                            if len(path.strip()) > 0:
                                data.primaries.append(path)
                    else:
                        data.primaries.append(fs.basedir)
                    for attr in fs.attributes:
                        if attr.startswith("primtop="):
                            data.primtops.append(attr.split("=", 1)[1])
                    self._addIncDirs(data, fs.basedir, fs.incdirs)
                elif fs.filetype == "systemVerilogDPI":
                    for file in fs.files:
                        path = os.path.join(fs.basedir, file)
                        self._log.debug("path: basedir=%s fullpath=%s" % (fs.basedir, path))
                        data.dpi.append(path)
                elif fs.filetype == "verilogVPI":
                    # Extract entrypoint from attributes if present
                    entrypoint = None
                    for attr in fs.attributes:
                        if attr.startswith("entrypoint="):
                            entrypoint = attr.split("=", 1)[1]
                            break
                    
                    for file in fs.files:
                        path = os.path.join(fs.basedir, file)
                        self._log.debug("path: basedir=%s fullpath=%s entrypoint=%s" % (fs.basedir, path, entrypoint))
                        data.vpi.append((path, entrypoint))
                elif fs.filetype == "verilogPLI":
                    pli_add(data.pli, pli_from_fileset(fs))
                else:
                    data.sysv |= (fs.filetype == "systemVerilogSource")
                    for file in fs.files:
                        path = os.path.join(fs.basedir, file)
                        self._log.debug("path: basedir=%s fullpath=%s" % (fs.basedir, path))
                        dir = os.path.dirname(path)
                        data.files.append(path)
                    self._addIncDirs(data, fs.basedir, fs.incdirs)
            elif fs.type == "hdlsim.SimCompileArgs":
                data.compargs.extend(merge_tokenize(fs.args))
                for inc in fs.incdirs:
                    if len(inc.strip()) > 0:
                        data.incdirs.append(inc)
                data.defines.extend(fs.defines)
                # A library (eg UVM's DPI layer) declares that it calls VPI
                # from C, rather than string-injecting --vpi via args.
                if getattr(fs, "vpi", False):
                    data.vpi_enable = True
                if getattr(fs, "public_flat_rw", False):
                    data.public_flat_rw = True
            elif fs.type == "hdlsim.SimElabArgs":
                self._log.debug("fs.type=%s" % fs.type)
                data.elabargs.extend(merge_tokenize(fs.args))
                # A trace-enabled elab-args preset (eg SimElabArgsDbg) selects
                # the waveform format here; "none" leaves it off.
                _tf = getattr(fs, 'trace_fmt', 'none')
                if _tf and _tf != 'none':
                    data.trace_fmt = _tf
                # Convert vpilibs from SimElabArgs (strings) to tuples (path, None)
                data.vpi.extend([(vpi, None) for vpi in fs.vpilibs])
                data.dpi.extend(fs.dpilibs)
            elif fs.type == "hdlsim.SimCovArgs":
                self.cov_requests.append(getattr(fs, "level", "none") or "none")

    def _addIncDirs(self, data, basedir, incdirs):
        self._log.debug("_addIncDirs base=%s incdirs=%s" % (basedir, incdirs))
        data.incdirs.extend([os.path.join(basedir, i) for i in incdirs])
        self._log.debug("data.incdirs: %s" % data.incdirs)


class VlTaskSimImageMemento(BaseModel):
    svdeps : dict = pdc.Field(default_factory=dict)

