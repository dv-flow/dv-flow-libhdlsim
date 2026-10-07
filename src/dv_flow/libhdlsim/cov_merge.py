#****************************************************************************
#* cov_merge.py
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
"""SimCovMerge: merge the coverage databases of a set of runs into one.

The databases are found in the task's inputs: the `simCovDb` artifacts of
SimRunResult / TestResult items, of the TestResults inside a SuiteResult, and
bare `simCovDb` FileSets (eg an earlier merge's output, so merges compose).
Only databases of the backend's `format=` are merged; any other is skipped
with a warning.

One merge command over every database (single-threaded). The merged database
has the same name and format as a run's, so the backend's run-time summary
(parse_cov_summary) gives its `cov_*` stats.
"""
import os
import shutil
from typing import Any, List, Tuple, Type
from dv_flow.mgr import FileSet, TaskDataResult
from dv_flow.mgr.task_data import TaskMarker, SeverityE
from dv_flow.libhdlsim import cov
from dv_flow.libhdlsim.vl_sim_runner import VLSimRunner


def _get(obj : Any, name : str, default=None):
    # Items may arrive as objects or, past a serialization boundary, dicts
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def _artifacts_of(item) -> List[Any]:
    """The artifacts of one input item that could hold coverage databases."""
    t = _get(item, "type")
    if t in ("hdlsim.SimRunResult", "hdlsim.TestResult"):
        return list(_get(item, "artifacts") or [])
    if t == "hdlsim.SuiteResult":
        arts = []
        for r in _get(item, "results") or []:
            arts.extend(_get(r, "artifacts") or [])
        return arts
    if _get(item, "filetype") == "simCovDb":
        return [item]
    return []


def collect_cov_dbs(inputs) -> List[Tuple[str, str]]:
    """(path, format) of every coverage database in `inputs`, in input order,
    each path once."""
    dbs = []
    seen = set()
    for item in inputs:
        for a in _artifacts_of(item):
            if _get(a, "filetype") != "simCovDb":
                continue
            fmt = ""
            for attr in _get(a, "attributes") or []:
                if attr.startswith("format="):
                    fmt = attr[len("format="):]
            for f in _get(a, "files") or []:
                path = os.path.join(_get(a, "basedir") or "", f)
                if path not in seen:
                    seen.add(path)
                    dbs.append((path, fmt))
    return dbs


class CovMerger(object):
    """Base for a backend's merge. A backend sets `format`, `db_name` (the
    name its runs give the database, so the merged one reads the same way)
    and `runner` (its SimRunner, for parse_cov_summary), and implements
    merge_cmd()."""

    format : str = ""
    db_name : str = ""
    runner : Type[VLSimRunner] = VLSimRunner

    def __init__(self, ctxt):
        self.ctxt = ctxt
        self.markers = []

    def merge_cmd(self, runner : VLSimRunner, out : str,
                  dbs : List[str]) -> List[str]:
        raise NotImplementedError()

    async def run(self, input) -> TaskDataResult:
        found = collect_cov_dbs(input.inputs)
        dbs = [p for p, fmt in found if fmt == self.format]
        skipped = sorted(set(fmt or "unknown" for _, fmt in found
                             if fmt != self.format))
        if skipped:
            self.markers.append(TaskMarker(
                severity=SeverityE.Warning,
                msg="Skipped %d coverage database(s) of format %s; this "
                    "merge reads format=%s" % (
                        len(found) - len(dbs), ", ".join(skipped), self.format)))
        if not dbs:
            self.markers.append(TaskMarker(
                severity=SeverityE.Error,
                msg="No format=%s coverage databases in the inputs. Were the "
                    "runs' images built with a coverage level?" % self.format))
            return TaskDataResult(status=1, markers=self.markers)

        runner = self.runner(ctxt=self.ctxt, rundir=input.rundir)
        out = os.path.join(input.rundir, self.db_name)
        # Never report a database left by an earlier merge in this rundir
        if os.path.isdir(out) and not os.path.islink(out):
            shutil.rmtree(out)
        elif os.path.lexists(out):
            os.unlink(out)

        cmd = self.merge_cmd(runner, out, dbs)
        if cmd is None:
            return TaskDataResult(status=1, markers=self.markers)
        status = await self.ctxt.exec(cmd, logfile="merge.log")
        if status != 0 or not os.path.exists(out):
            if status == 0:
                self.markers.append(TaskMarker(
                    severity=SeverityE.Error,
                    msg="%s wrote no %s" % (os.path.basename(cmd[0]), self.db_name)))
            return TaskDataResult(status=status or 1, markers=self.markers)

        try:
            stats = runner.parse_cov_summary(input.rundir, {"kinds": None}) or {}
        except Exception as e:
            runner._log.debug("merged coverage summary failed: %s", e)
            stats = {}
        self._report(len(dbs), stats)

        return TaskDataResult(
            status=0,
            markers=self.markers,
            output=[
                FileSet(src=input.name, filetype="simCovDb",
                        basedir=input.rundir, files=[self.db_name],
                        attributes=["role=cov", "format=%s" % self.format]),
                self.ctxt.mkDataItem(
                    "hdlsim.SimCovMergeResult",
                    sim=runner.sim_name,
                    format=self.format,
                    inputs=list(dbs),
                    stats=dict(stats)),
            ])

    def _report(self, n : int, stats : dict):
        pcts = ["%s=%.2f%%" % (k, stats["cov_%s_pct" % k]) for k in cov.KINDS
                if "cov_%s_pct" % k in stats]
        self.ctxt.info("merged %d coverage database(s)%s" % (
            n, (": " + "  ".join(pcts)) if pcts else ""))

    def _tool(self, runner : VLSimRunner, exe : str, sibling_of : str) -> str:
        path = runner._which(exe, sibling_of=sibling_of)
        if path is None:
            self.markers.append(TaskMarker(
                severity=SeverityE.Error,
                msg="%s not found on PATH; it is needed to merge format=%s "
                    "coverage databases" % (exe, self.format)))
        return path


class VltCovMerger(CovMerger):
    format = cov.FORMAT_VLT_DAT
    db_name = "coverage.dat"

    def __init__(self, ctxt):
        super().__init__(ctxt)
        from dv_flow.libhdlsim.vlt_sim_run import SimRunner
        self.runner = SimRunner

    def merge_cmd(self, runner, out, dbs):
        exe = self._tool(runner, "verilator_coverage", "verilator")
        return None if exe is None else [exe, "-write", out] + dbs


class VcsCovMerger(CovMerger):
    format = cov.FORMAT_VCS_VDB

    def __init__(self, ctxt):
        super().__init__(ctxt)
        from dv_flow.libhdlsim.vcs_sim_run import SimRunner, COV_DB
        self.runner = SimRunner
        self.db_name = COV_DB

    def merge_cmd(self, runner, out, dbs):
        exe = self._tool(runner, "urg", "vcs")
        if exe is None:
            return None
        cmd = [exe, "-full64"]
        for db in dbs:
            cmd.extend(["-dir", db])
        return cmd + ["-dbname", out, "-noreport"]


class MtiCovMerger(CovMerger):
    format = cov.FORMAT_QUESTA_UCDB

    def __init__(self, ctxt):
        super().__init__(ctxt)
        from dv_flow.libhdlsim.mti_sim_run import SimRunner, COV_DB
        self.runner = SimRunner
        self.db_name = COV_DB

    def merge_cmd(self, runner, out, dbs):
        exe = self._tool(runner, "vcover", "vsim")
        return None if exe is None else [exe, "merge", "-out", out] + dbs


async def VltSimCovMerge(ctxt, input) -> TaskDataResult:
    return await VltCovMerger(ctxt).run(input)


async def VcsSimCovMerge(ctxt, input) -> TaskDataResult:
    return await VcsCovMerger(ctxt).run(input)


async def MtiSimCovMerge(ctxt, input) -> TaskDataResult:
    return await MtiCovMerger(ctxt).run(input)
