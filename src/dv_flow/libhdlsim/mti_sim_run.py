#****************************************************************************
#* mti_sim_run.py
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
import asyncio
import json
import os
from typing import Dict, List, Tuple
from dv_flow.mgr import TaskDataResult, FileSet
from dv_flow.mgr.task_data import TaskMarker, SeverityE
from dv_flow.libhdlsim import cov, prof, sim_stats
from dv_flow.libhdlsim.vl_sim_runner import VLSimRunner
from dv_flow.libhdlsim.sim_uvm_case import uvm_case_task
from dv_flow.libhdlsim.vl_sim_data import VlSimRunData

# Coverage level -> (kinds, vopt +cover= items). Covergroups and cover
# directives are recorded without +cover; it adds code coverage.
MTI_COV = {
    "func": (["covergroup", "user"], None),
    "code": (["covergroup", "user", "line", "branch", "expr"], "sbce"),
    "full": (["covergroup", "user", "line", "branch", "expr",
              "toggle", "fsm_state", "fsm_arc"], "sbceft"),
}

# The run's coverage database, saved by vsim at exit
COV_DB = "cov.ucdb"

# Profiling mode -> (vsim flag, visualizer profile kind). The default
# sampling rate is too coarse for a short test, hence perf=high.
MTI_PROF = {"time": ("-fprofile+perf=high", "perf"),
            "mem": ("-fprofile+mem", "mem")}

# vsim writes the profile database (a .fdb) under PROF_DB in the rundir;
# visualizer turns it into PROF_REPORT after the run.
PROF_DB = "fprofile"
PROF_REPORT = "prof_report.txt"

class SimRunner(VLSimRunner):
    sim_name = "mti"

    def check_pli(self, data : VlSimRunData) -> int:
        # Questa binds PLI 1.0 systfs through the library's veriusertfs or
        # init_usertfs(), or a -tab file. It has no lib:boot form.
        for lib in data.plilibs:
            if lib.boot and not lib.tab:
                self.markers.append(TaskMarker(
                    severity=SeverityE.Warning,
                    msg="Questa ignores `boot` (%s) for PLI 1.0; library %s must "
                        "export veriusertfs or init_usertfs" % (lib.boot, lib.path)))
        return 0

    async def runsim(self, data : VlSimRunData):
        status = 0

        do = "run -a; quit -f"
        cov_on = data.cov is not None and data.cov.get("level") in MTI_COV
        if cov_on:
            # -onexit: saved however the run ends ($finish, an error, ...)
            do = "coverage save -onexit %s; %s" % (
                os.path.join(self.rundir, COV_DB), do)

        cmd = [
            'vsim',
            '-batch',
            '-do',
            do,
            "simv_opt",
            "-work",
            os.path.join(data.imgdir, 'work')
        ]

        if cov_on:
            cmd.append('-coverage')

        # End-of-run time/memory report, parsed by parse_sim_stats. Left to
        # the user when they pass their own -stats/-nostats.
        if not any(a.startswith(("-stats", "-nostats")) for a in data.args):
            cmd.append('-stats=perf,time')

        if data.prof is not None and data.prof.get("mode", "none") != "none":
            cmd.append(MTI_PROF[data.prof["mode"]][0])

        if data.valgrind:
            cmd.extend(["-valgrind", "--tool=memcheck"])

        if data.full64:
            cmd.append('-64')

        for pli_path, entrypoint in data.vpilibs:
            if entrypoint:
                cmd.extend(['-pli', f'{pli_path}:{entrypoint}'])
            else:
                cmd.extend(['-pli', pli_path])

        for lib in data.plilibs:
            cmd.extend(['-pli', lib.path])
            if lib.tab:
                cmd.extend(['-tab', lib.tab])

        for dpi in data.dpilibs:
            dpi_libdir = os.path.dirname(dpi)
            dpi_file = os.path.basename(dpi)
            if dpi_file.rfind('.') > 0:
                dpi_file = dpi_file[:dpi_file.rfind('.')]
            cmd.extend(['-sv_lib', os.path.join(dpi_libdir, dpi_file)])

        for plusarg in data.plusargs:
            cmd.append("+%s" % plusarg)
        for arg in data.args:
            cmd.append(arg)

        status |= await self.exec_sim(cmd, logfile="sim.log")
        
        return status

    def parse_sim_stats(self, logfile):
        return sim_stats.parse_mti_log_stats(sim_stats.read_log_ends(logfile))

    def parse_cov_summary(self, rundir, cov_info):
        db = os.path.join(rundir, COV_DB)
        if not os.path.isfile(db):
            return {}
        vcover = self._which("vcover", sibling_of="vsim")
        if vcover is None:
            self._log.debug("vcover not found; no coverage summary")
            return {}
        out = self._run_report([vcover, "report", "-summary", db])
        if out is None:
            return {}
        return cov.parse_mti_cov_summary(out, cov_info.get("kinds"))

    def parse_prof_summary(self, rundir, prof_info):
        mode = prof_info.get("mode")
        if mode not in MTI_PROF or not os.path.isdir(os.path.join(rundir, PROF_DB)):
            return None
        visualizer = self._which("visualizer", sibling_of="vsim")
        if visualizer is None:
            self.markers.append(TaskMarker(
                severity=SeverityE.Warning,
                msg="visualizer not found; no profile report or summary"))
            return None
        # Reports the newest database under PROF_DB, with the optimizer's
        # (from the image) when vopt also profiled
        out = self._run_report([
            visualizer, "-fbatch",
            "-fprofile+%s+dir=%s+report=%s" % (
                MTI_PROF[mode][1], PROF_DB, PROF_REPORT)])
        report = os.path.join(rundir, PROF_REPORT)
        if out is None or not os.path.isfile(report):
            self.markers.append(TaskMarker(
                severity=SeverityE.Warning,
                msg="visualizer failed to report the profile; see %s" % (
                    os.path.join(rundir, "visualizer.log"))))
            return None
        with open(report, "r", errors="replace") as fp:
            return prof.parse_mti_report(fp.read(), mode)

    def _artifact_spec(self) -> Dict[str, Tuple]:
        spec = super()._artifact_spec()
        spec["simCovDb"] = ([COV_DB], "cov", ["format=%s" % cov.FORMAT_QUESTA_UCDB])
        spec["simProfDb"] = ([PROF_DB], "prof", ["format=%s" % prof.FORMAT_QUESTA_FDB])
        spec["simProfReport"] = ([PROF_REPORT], "prof-report")
        return spec

async def SimRun(runner, input) -> TaskDataResult:
    return await SimRunner().run(runner, input)

SimUVMCase = uvm_case_task(SimRunner)
