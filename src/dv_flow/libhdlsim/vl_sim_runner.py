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
from typing import ClassVar, Dict, List, Optional, Tuple
from dv_flow.libhdlsim.log_parser import LogParser
from dv_flow.libhdlsim.vl_sim_data import VlSimRunData
from dv_flow.libhdlsim import cov, sim_stats

from svdep import FileCollection, TaskCheckUpToDate, TaskBuildFileCollection
from dv_flow.libhdlsim.vl_sim_image_builder import VlTaskSimImageMemento
from .util import merge_tokenize

@dc.dataclass
class VLSimRunner(object):
    markers : List[TaskMarker] = dc.field(default_factory=list)
    rundir : str = dc.field(default="")
    ctxt : TaskRunCtxt = dc.field(default=None)
    _walltime : float = dc.field(default=0.0)
    # Sparse measurement/provenance maps for the run (see sim_stats).
    _stats : Dict[str, object] = dc.field(default_factory=dict)
    _runinfo : Dict[str, object] = dc.field(default_factory=dict)
    _log : ClassVar = logging.getLogger("VLSimRunner")
    # Backend identity, set by each concrete runner. Used when the `sim` param
    # is unresolved ("unset" is what backend_select leaves when the run task was
    # bound to a concrete per-sim task rather than selected by the `sim` var),
    # so a result always says which simulator actually produced it.
    sim_name : ClassVar[str] = ""

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

        # The run follows its image: the coverage level (and kinds) the image
        # was built with, or None when it was built without coverage.
        if data.imgdir:
            data.cov = cov.read_cov_json(data.imgdir)

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
            # A coverage database left by an earlier run in this rundir must
            # not be reported as this run's (eg a rerun at `none`).
            self._remove_cov_db()
            self._runinfo["start_time"] = sim_stats.utcnow()
            t0 = time.monotonic()
            rc = await self.runsim(data)
            self._walltime = time.monotonic() - t0
            self._runinfo["end_time"] = sim_stats.utcnow()

        self._collect_stats(input, data, rc)

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
            sim=self._sim_id(input),
            mode=mode,
            walltime_s=self._walltime,
            stats=dict(self._stats),
            runinfo=dict(self._runinfo),
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

    def _sim_id(self, input) -> str:
        """Which simulator produced this result: the resolved `sim` param when
        it names one, else the concrete runner's own identity. `unset` is what
        the param holds when the task was bound directly to a per-sim task
        instead of being selected through the `sim` variable -- reporting that
        verbatim would leave every such result unattributed."""
        sim = getattr(input.params, "sim", "") or ""
        if sim and sim != "unset":
            return sim
        return self.sim_name or sim

    async def exec_sim(self, cmd : List[str], logfile : str = "sim.log", **kwargs):
        """Run the simulator command with host-process instrumentation.

        Backends call this INSTEAD of `ctxt.exec` for the simulation itself, so
        CPU time / peak RSS come for free on every backend regardless of what
        the simulator chooses to print. The command is wrapped in GNU `time`
        when one is available (probed once) and run unchanged otherwise -- the
        wrapper propagates the child's exit status, so the caller's status
        handling is unaffected either way.
        """
        self._runinfo["cmd"] = list(cmd)
        self._runinfo["logfile"] = logfile
        wrapped = sim_stats.wrap_host_stats(
            cmd, os.path.join(self.rundir, sim_stats.HOST_STATS_FILE))
        return await self.ctxt.exec(wrapped, logfile=logfile, **kwargs)

    def parse_sim_stats(self, logfile : str) -> Dict[str, object]:
        """Backend hook: stats/provenance the SIMULATOR reported in its log.

        Return a flat dict; keys in `sim_stats.STAT_KEYS` are routed to `stats`
        and keys in `INFO_KEYS` to `runinfo`. The base returns nothing -- a
        backend whose simulator prints no end-of-run report contributes only
        the host-process tier, and the corresponding keys stay absent (they are
        never faked with a 0).

        Implemented for Verilator (`vlt_sim_run.SimRunner`). vcs / mti / xcm /
        xsm / ivl are candidates: each prints some subset (CPU time, data
        structure size, `$finish` time), but the patterns need validating
        against real logs from those tools before being relied on.
        """
        return {}

    def parse_cov_summary(self, rundir : str, cov_info : dict) -> Dict[str, object]:
        """Backend hook: coverage totals for this run, as `stats` keys
        `cov_<kind>_pct/_covered/_total` (see sim_stats.STAT_KEYS).

        Called only when the image was built with coverage; `cov_info` is its
        record ({level, kinds}), so a backend reports only the kinds that
        level enabled. Best-effort like parse_sim_stats: return {} when the
        database is missing or unreadable. The base returns {}.
        """
        return {}

    def _collect_stats(self, input, data : VlSimRunData, rc : int):
        """Assemble the run's `stats` + `runinfo` maps and persist them.

        Best-effort throughout: a failure to measure something drops the key,
        and can never change the run's verdict.
        """
        try:
            self._stats.update(sim_stats.parse_host_stats(
                os.path.join(self.rundir, sim_stats.HOST_STATS_FILE)))

            # Task-level wallclock is authoritative (always available, and it
            # spans exactly what the task timed); it supersedes GNU time's.
            self._stats["walltime_s"] = round(self._walltime, 3)

            logfile = self._runinfo.get("logfile", "sim.log")
            parsed = {}
            try:
                parsed = self.parse_sim_stats(
                    os.path.join(self.rundir, logfile)) or {}
            except Exception as e:
                self._log.debug("sim stats parse failed: %s", e)
            for k, v in parsed.items():
                if k in sim_stats.INFO_KEYS:
                    self._runinfo[k] = v
                else:
                    self._stats[k] = v

            if data.cov is not None:
                try:
                    self._stats.update(self.parse_cov_summary(
                        self.rundir, data.cov) or {})
                except Exception as e:
                    self._log.debug("coverage summary failed: %s", e)

            self._stats.update(sim_stats.read_tb_stats(self.rundir))
            sim_stats.finalize(self._stats)

            seed, seed_src = sim_stats.extract_seed(data.args, data.plusargs)

            self._runinfo.update(sim_stats.host_info())
            self._runinfo.update(dict(
                case_name=(getattr(input.params, "name", "")
                           or os.path.basename((input.rundir or "").rstrip("/"))),
                testname=getattr(input.params, "testname", ""),
                sim=self._sim_id(input),
                mode=getattr(input.params, "mode", "run"),
                args=list(data.args),
                plusargs=list(data.plusargs),
                dpilibs=list(data.dpilibs),
                vpilibs=[v[0] for v in data.vpilibs],
                imgdir=data.imgdir or "",
                rundir=self.rundir,
                trace=bool(data.trace),
                valgrind=bool(data.valgrind),
                exit_code=rc))
            if seed is not None:
                self._runinfo["seed"] = seed
                self._runinfo["seed_source"] = seed_src
            if data.cov is not None:
                self._runinfo["cov"] = dict(data.cov)

            sim_stats.write_stats_json(self.rundir, self._stats, self._runinfo)
        except Exception as e:
            self._log.debug("stats collection failed: %s", e)

    def _artifact_spec(self) -> Dict[str, Tuple]:
        """Map artifact filetype -> (glob patterns, role[, extra attributes]).

        The FileSet gets `role=<role>` first, then any extra attributes. This
        base spec is the Verilator layout (sim.log, VCD/FST traces,
        coverage.dat). Other backends override to name their own files.

        `simCovDb` carries `format=<id>` (cov.FORMAT_*): the database's
        format, which a downstream merge/report task dispatches on rather than
        on the file name. It is present only when the run wrote a database,
        which happens only when the image was built with coverage.
        """
        return {
            "simLog":   (["sim.log"],                   "log"),
            "simStats": ([sim_stats.STATS_FILE],        "stats"),
            "simTrace": (["*.vcd", "*.fst", "waves.*"], "trace"),
            "simCovDb": (["coverage.dat"],              "cov",
                         ["format=%s" % cov.FORMAT_VLT_DAT]),
        }

    def _glob_rundir(self, globs : List[str]) -> List[str]:
        files = []
        for g in globs:
            files.extend(glob.glob(os.path.join(self.rundir, g)))
        return sorted(set(f for f in files if os.path.isfile(f)))

    def _remove_cov_db(self):
        spec = self._artifact_spec().get("simCovDb")
        if spec is None:
            return
        for f in self._glob_rundir(spec[0]):
            try:
                os.unlink(f)
            except OSError as e:
                self._log.debug("could not remove stale %s: %s", f, e)

    def _collect_artifacts(self) -> List[FileSet]:
        """Glob the rundir per `_artifact_spec()`, emitting a FileSet only for
        filetypes whose files actually exist (so trace/coverage stay absent
        unless produced)."""
        out = []
        for ftype, spec in self._artifact_spec().items():
            globs, role = spec[0], spec[1]
            extra = list(spec[2]) if len(spec) > 2 else []
            files = self._glob_rundir(globs)
            if files:
                out.append(FileSet(
                    filetype=ftype,
                    basedir=self.rundir,
                    files=[os.path.relpath(f, self.rundir) for f in files],
                    attributes=["role=%s" % role] + extra))
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
    