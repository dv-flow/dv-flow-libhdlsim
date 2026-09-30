#****************************************************************************
#* xzm_sim_run.py
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
import json
import os
import re
from typing import Dict, List, Tuple
from dv_flow.mgr import TaskDataResult
from dv_flow.mgr.task_data import TaskMarker, SeverityE
from dv_flow.libhdlsim import cov
from dv_flow.libhdlsim.vl_sim_runner import VLSimRunner
from dv_flow.libhdlsim.vl_sim_data import VlSimRunData
from dv_flow.libhdlsim.sim_uvm_case import uvm_case_task
from dv_flow.libhdlsim.xzm_sim_image import ARTIFACT, read_manifest

# Effectively unbounded. xezim's own default (100ms) ends a run silently with
# exit 0, where every other backend runs until $finish.
DEFAULT_MAX_TIME = "1000000s"

# xezim's default seed when no +seed is given
DEFAULT_SEED = 1

# The coverage database xezim writes (XEZIM_COV_DB), in the run directory
COV_DB = "xezim_cov.json"

# Code-coverage kinds per level (--code-coverage=<kinds>); none below `code`
_CODE_COV = {"code": "stmt,branch", "full": "stmt,branch,toggle"}


def _user_code_cov(args):
    """True when the user's run args already request code coverage (any of
    xezim's spellings); theirs is then left alone."""
    for a in args:
        if a == "--code-coverage" or a.startswith("--code-coverage="):
            return True
        if a == "-coverage" or a == "+cover" or a.startswith("+cover="):
            return True
    return False


class SimRunner(VLSimRunner):
    sim_name = "xzm"

    _mode = "run"

    async def run(self, ctxt, input) -> TaskDataResult:
        # runsim needs the mode to decide how to report reaching --max-time
        self._mode = getattr(input.params, "mode", "run")
        return await super().run(ctxt, input)

    async def runsim(self, data : VlSimRunData):
        status = 0

        manifest = read_manifest(data.imgdir)

        cmd = []

        if data.valgrind:
            cmd.extend(['valgrind', '--tool=memcheck'])

        cmd.append('xezim')
        cmd.append(os.path.join(data.imgdir, manifest.get("artifact", ARTIFACT)))

        # Without --error-exit a $error leaves the exit status 0, and a
        # failing test would be reported as passing.
        cmd.append('--error-exit')

        if not any(a == '--max-time' or a.startswith('--max-time=') for a in data.args):
            cmd.extend(['--max-time', DEFAULT_MAX_TIME])

        # One JSON line on stderr at the end of the run; see parse_sim_stats
        cmd.append('--report-stats=json')

        for lib in data.dpilibs:
            cmd.extend(['--dpi-lib', lib])

        for lib, entrypoint in data.vpilibs:
            if entrypoint:
                # xezim runs only vlog_startup_routines. cocotb's GPI library
                # exports that too, so loading it still works.
                self.ctxt.add_marker(TaskMarker(
                    severity=SeverityE.Warning,
                    msg="xezim ignores VPI entrypoint '%s' for %s; only "
                        "vlog_startup_routines is run" % (entrypoint, lib)))
            cmd.extend(['--vpi-lib', lib])

        trace_fmt = manifest.get("trace_fmt", "none")
        if data.trace and trace_fmt == "none":
            trace_fmt = "fst"
        if trace_fmt == "fst":
            cmd.extend(['--fst', 'sim.fst'])
        elif trace_fmt == "vcd":
            # Waveform support on; the testbench's $dumpfile/$dumpvars decide
            # what is written.
            cmd.append('--wave')

        # Coverage follows the image's cov.json. xezim writes functional
        # coverage whenever the design has any, so at `none` the database is
        # sent to /dev/null rather than left in the rundir.
        env = dict(self.ctxt.env) if self.ctxt.env is not None else dict(os.environ)
        if data.cov is None:
            env["XEZIM_COV_DB"] = os.devnull
        else:
            env["XEZIM_COV_DB"] = os.path.join(self.rundir, COV_DB)
            kinds = _CODE_COV.get(data.cov.get("level"))
            if kinds is not None and not _user_code_cov(data.args):
                cmd.append("--code-coverage=%s" % kinds)

        cmd.extend(data.args)

        for p in data.plusargs:
            cmd.append("+%s" % p)

        status |= await self.exec_sim(cmd, logfile="sim.log", env=env)

        # Reaching --max-time without $finish exits 0. It's a failed run.
        hang = self._hang_report(os.path.join(self.rundir, "sim.log"))
        if hang is not None:
            status |= 1
            if self._mode != "test":
                self.markers.append(TaskMarker(
                    severity=SeverityE.Error,
                    msg="simulation reached --max-time without $finish (%s)" % hang))

        return status

    # `[xezim][hang-report] simulation reached --max-time (100 ticks) without $finish`
    _RE_HANG = re.compile(r'^\[xezim\]\[hang-report\]\s*simulation reached --max-time\s*(.*)$')
    # `Simulation finished at time 10 ($finish called)`; without the
    # parenthetical when the run stopped at --max-time.
    _RE_FINISH = re.compile(r'^Simulation finished at time\s+(\d+)\s*(\(\$finish called\))?')

    def _hang_report(self, logfile):
        """The hang-report detail if the run hit --max-time, else None."""
        for l in self._tail(logfile).splitlines():
            m = self._RE_HANG.match(l)
            if m is not None:
                return m.group(1).strip()
        return None

    @staticmethod
    def _tail(logfile, size=16384):
        # The end-of-run lines are the last thing printed; scan the tail rather
        # than the whole log (a UVM log can be very large).
        try:
            with open(logfile, "r", errors="replace") as fp:
                try:
                    fp.seek(max(0, os.path.getsize(logfile) - size))
                except Exception:
                    pass
                return fp.read()
        except Exception:
            return ""

    def parse_sim_stats(self, logfile):
        stats = {}
        if not os.path.isfile(logfile):
            return stats

        # No seed is echoed; without +seed xezim uses 1. The base replaces
        # this with the +seed value when one was given.
        stats["seed"] = DEFAULT_SEED
        stats["seed_source"] = "default"

        for l in self._tail(logfile).splitlines():
            if l.startswith('{"schema_version"'):
                try:
                    rpt = json.loads(l)
                except ValueError:
                    continue
                if "sim_time_ns" in rpt:
                    stats["simtime"] = "%sns" % rpt["sim_time_ns"]
                if "wall_ms" in rpt:
                    stats["sim_walltime_s"] = rpt["wall_ms"] / 1000.0
                if "cpu_user_ms" in rpt or "cpu_sys_ms" in rpt:
                    stats["sim_cpu_s"] = (rpt.get("cpu_user_ms", 0)
                                          + rpt.get("cpu_sys_ms", 0)) / 1000.0
                if "peak_rss_kb" in rpt:
                    stats["sim_mem_mb"] = round(rpt["peak_rss_kb"] / 1024.0, 3)
                if "version" in rpt:
                    stats["sim_version"] = "xezim %s" % rpt["version"]
                    if rpt.get("git_rev"):
                        stats["sim_version"] += " (git %s)" % rpt["git_rev"]
                continue
            if self._RE_HANG.match(l):
                stats["finish_reason"] = "max_time"
                continue
            m = self._RE_FINISH.match(l)
            if m is not None and m.group(2) and stats.get("finish_reason") != "max_time":
                stats["finish_reason"] = "$finish"

        return stats

    def parse_cov_summary(self, rundir, cov_info):
        path = os.path.join(rundir, COV_DB)
        if not os.path.isfile(path):
            return {}
        with open(path, "r") as fp:
            obj = json.load(fp)
        return cov.parse_xzm_cov_summary(obj, cov_info.get("kinds"))

    def _artifact_spec(self) -> Dict[str, Tuple]:
        spec = super()._artifact_spec()
        spec["simTrace"] = (["sim.fst", "*.vcd", "*.fst"], "trace")
        spec["simCovDb"] = ([COV_DB], "cov",
                            ["format=%s" % cov.FORMAT_XEZIM_JSON])
        return spec


async def SimRun(runner, input) -> TaskDataResult:
    return await SimRunner().run(runner, input)

SimUVMCase = uvm_case_task(SimRunner)
