#****************************************************************************
#* vl_sim_runner.py
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
import glob
import json
import logging
import shutil
import time
import dataclasses as dc
from dv_flow.mgr import FileSet, TaskDataResult, TaskRunCtxt
from dv_flow.mgr.task_data import TaskMarker, SeverityE
from typing import ClassVar, Dict, List, Tuple
from dv_flow.libhdlsim.log_parser import LogParser
from dv_flow.libhdlsim.vl_sim_data import VlSimRunData

from svdep import FileCollection, TaskCheckUpToDate, TaskBuildFileCollection
from dv_flow.libhdlsim.vl_sim_image_builder import VlTaskSimImageMemento
from .util import merge_tokenize

@dc.dataclass
class VLSimRunner(object):
    markers : List[TaskMarker] = dc.field(default_factory=list)
    rundir : str = dc.field(default="")
    ctxt : TaskRunCtxt = dc.field(default=None)
    _walltime : float = dc.field(default=0.0)

    async def run(self, ctxt, input) -> TaskDataResult:
        status = 0

        self.ctxt = ctxt
        self.rundir = input.rundir
        data = VlSimRunData()

        data.plusargs = input.params.plusargs.copy()
        data.args = merge_tokenize(input.params.args)
        data.trace = input.params.trace
        data.dpilibs.extend(input.params.dpilibs)
        # Convert vpilibs from params (strings) to tuples (path, None)
        data.vpilibs.extend([(vpi, None) for vpi in input.params.vpilibs])
        data.valgrind = input.params.valgrind

        if getattr(input.params, 'full64', True):
            data.full64 = True

        sim_data = []

        for inp in input.inputs:
            if inp.type == "std.FileSet":
                if inp.filetype == "simDir":
                    if data.imgdir:
                        self.markers.append(TaskMarker(
                            severity=SeverityE.Error,
                            msg="Multiple simDir inputs"))
                        status = 1
                        break
                    else:
                        data.imgdir = inp.basedir
                elif inp.filetype == "systemVerilogDPI":
                    for f in inp.files:
                        data.dpilibs.append(os.path.join(inp.basedir, f))
                elif inp.filetype == "verilogVPI":
                    # Extract entrypoint from attributes if present
                    entrypoint = None
                    for attr in inp.attributes:
                        if attr.startswith("entrypoint="):
                            entrypoint = attr.split("=", 1)[1]
                            break
                    
                    for f in inp.files:
                        data.vpilibs.append((os.path.join(inp.basedir, f), entrypoint))
                elif inp.filetype == "simRunData":
                    sim_data.append(inp)
            elif inp.type == "hdlsim.SimRunArgs":
                if inp.args:
                    data.args.extend(merge_tokenize(inp.args))
                if inp.plusargs:
                    data.plusargs.extend(merge_tokenize(inp.plusargs))
                if inp.vpilibs:
                    # Convert vpilibs from SimRunArgs (strings) to tuples (path, None)
                    data.vpilibs.extend([(vpi, None) for vpi in inp.vpilibs])
                if inp.dpilibs:
                    data.dpilibs.extend(inp.dpilibs)


        if data.imgdir is None:
            self.markers.append(TaskMarker(
                severity=SeverityE.Error,
                msg="No simDir input"))
            status = 1

        # Handle simRunData inputs
        self.copy_sim_data(sim_data)

        # `mode` gates how a nonzero simulator exit is treated:
        #   run  (default): a nonzero exit fails the task (build-and-run).
        #   test          : the exit code rides in SimRunResult and NEVER fails
        #                    the task -- a downstream Check task decides the
        #                    verdict, so one failing case can't abort a suite.
        # A setup/config error (missing simDir, ...) fails the task in ANY mode:
        # it is an infrastructure failure, not a test outcome.
        mode = getattr(input.params, "mode", "run")

        rc = 0
        if not status:
            t0 = time.monotonic()
            rc = await self.runsim(data)
            self._walltime = time.monotonic() - t0

        task_status = status
        if mode != "test":
            task_status |= rc
        else:
            # In test mode a nonzero simulator exit is the VERDICT (carried in
            # SimRunResult), not a task failure. `ctxt.exec` auto-adds a
            # "Command failed" ERROR marker on nonzero exit; left in place it
            # marks this (compound) cell failed and its TestResult gets dropped
            # from a suite's matrix aggregation. Drop that marker here -- a
            # failing test in test mode emits no error marker of its own.
            if self.ctxt is not None:
                self.ctxt._markers = [
                    m for m in self.ctxt._markers
                    if not (m.severity == SeverityE.Error
                            and str(m.msg).startswith("Command failed"))]

        artifacts = self._collect_artifacts()

        result = self.ctxt.mkDataItem(
            "hdlsim.SimRunResult",
            status=(status | rc),
            sim=getattr(input.params, "sim", ""),
            mode=mode,
            walltime_s=self._walltime,
            artifacts=artifacts)

        return TaskDataResult(
            status=task_status,
            markers=self.markers,
            # SimRunResult carries the verdict-as-data + artifacts. The
            # legacy simRunDir FileSet is retained for one release as a soft
            # landing for consumers that located sim.log by rundir (no
            # functional flow relies on it; unit tests still do).
            output=[
                result,
                FileSet(
                    src=input.name,
                    filetype="simRunDir",
                    basedir=input.rundir),
            ]
        )

    async def runsim(self, data : VlSimRunData):
        self.markers.append(TaskMarker(
            severity=SeverityE.Error,
            msg="No runsim implemenetation"))
        return 1

    def _artifact_spec(self) -> Dict[str, Tuple[List[str], str]]:
        """Map artifact filetype -> (glob patterns, role attribute).

        This base spec is the Verilator layout (sim.log, VCD/FST traces). Other
        backends override to name their own log/trace files. `simCovDb` is a
        reserved slot: its precise glob emits nothing until a coverage database
        is actually produced (coverage support is a labeled follow-up), so the
        FileSet schema does not change when coverage lands.
        """
        return {
            "simLog":   (["sim.log"],                   "log"),
            "simTrace": (["*.vcd", "*.fst", "waves.*"], "trace"),
            "simCovDb": (["coverage.dat"],              "cov"),
        }

    def _collect_artifacts(self) -> List[FileSet]:
        """Glob the rundir per `_artifact_spec()`, emitting a FileSet only for
        filetypes whose files actually exist (so trace/coverage stay absent
        unless produced)."""
        out = []
        for ftype, (globs, role) in self._artifact_spec().items():
            files = []
            for g in globs:
                files.extend(glob.glob(os.path.join(self.rundir, g)))
            files = sorted(set(f for f in files if os.path.isfile(f)))
            if files:
                out.append(FileSet(
                    filetype=ftype,
                    basedir=self.rundir,
                    files=[os.path.relpath(f, self.rundir) for f in files],
                    attributes=["role=%s" % role]))
        return out

    def copy_sim_data(self, sim_data : List[FileSet]):
        for ds in sim_data:
            for f in ds.files:
                src_f = os.path.join(ds.basedir, f)
                dst_f = os.path.join(self.rundir, f)
                dst_d = os.path.dirname(dst_f)
                if not os.path.exists(dst_d):
                    os.makedirs(dst_d)
                shutil.copy2(src_f, dst_f)
                logging.info(f"Copied {src_f} to {dst_f}")
    