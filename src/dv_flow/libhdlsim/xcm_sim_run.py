#****************************************************************************
#* xcm_sim_run.py
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
import shutil
from typing import Dict, List, Tuple
from dv_flow.mgr.task_data import TaskMarker, SeverityE
from dv_flow.libhdlsim import cov, prof, sim_stats
from dv_flow.libhdlsim.vl_sim_runner import VLSimRunner
from dv_flow.libhdlsim.vl_sim_data import PliLib
from dv_flow.libhdlsim.sim_uvm_case import uvm_case_task

def check_xcm_pli(libs : List[PliLib], markers : List[TaskMarker]) -> int:
    """Xcelium finds a PLI 1.0 library's systfs through its boot routine
    (-loadpli1 lib:boot) or a table (-plimapfile). A bare `-loadpli1 lib`
    does not fall back to veriusertfs, so a library with neither can't load."""
    status = 0
    for lib in libs:
        if not lib.boot and not lib.tab:
            markers.append(TaskMarker(
                severity=SeverityE.Error,
                msg="Xcelium needs a `boot` routine or a `tab` file to load "
                    "PLI 1.0 library %s" % lib.path))
            status = 1
    return status

def xcm_pli_args(libs : List[PliLib], sim : bool) -> List[str]:
    """-loadpli1 (and, at run time, -plimapfile) for each library. At
    elaboration only libraries with a boot routine are loaded: xmelab rejects
    -plimapfile, so a table-only library is bound at run time (xmelab warns
    *W,MISSYST for its systfs, which is harmless)."""
    args = []
    for lib in libs:
        if sim:
            args.extend(['-loadpli1', "%s:%s" % (lib.path, lib.boot or "")])
            if lib.tab:
                args.extend(['-plimapfile', lib.tab])
        elif lib.boot:
            args.extend(['-loadpli1', "%s:%s" % (lib.path, lib.boot)])
    return args

# Coverage level -> (kinds, xmelab -coverage). u = functional (covergroups,
# cover property); b = block (reported as line); e = expression; f = FSM;
# t = toggle.
XCM_COV = {
    "func": (["covergroup", "user"], "u"),
    "code": (["covergroup", "user", "line", "expr"], "b:e:u"),
    "full": (["covergroup", "user", "line", "expr",
              "toggle", "fsm_state", "fsm_arc"], "b:e:f:t:u"),
}

# Profiling mode -> xmsim flag. Both are runtime-only.
XCM_PROF = {"time": "-profile", "mem": "-memdetail"}

# xProf's database root (xmsim -prof_work). xmsim writes the run's database to
# prof_cpu_<n> under it, with a `prof_cpu` link to the latest.
XPROF_WORK = "xprof"
# The batch reports made from it: xprof `summary -<view>` -> file
XPROF_REPORTS = (("category", "xprof_category.txt"),
                 ("type", "xprof_type.txt"),
                 ("inst", "xprof_inst.txt"))

# The run's coverage work directory: xmsim writes the model (.ucm) and this
# run's data (.ucd) there, so it stands alone.
COV_DB = "cov_work"

class SimRunner(VLSimRunner):
    sim_name = "xcm"

    def check_pli(self, data):
        return check_xcm_pli(data.plilibs, self.markers)


    async def runsim(self, data):
        status = 0
        # First  things first: link in the library
        if not os.path.islink(os.path.join(self.rundir, "xcelium.d")):
            os.symlink(
                src=os.path.join(data.imgdir, "xcelium.d"),
                dst=os.path.join(self.rundir, "xcelium.d"))

        # Reuse the image's cds.lib so xmsim can resolve every library the
        # snapshot references at runtime (worklib + any precompiled simLibs,
        # via absolute-path DEFINEs). Without it: *E,DLOALB / *F,NOSIMU.
        img_cds_lib = os.path.join(data.imgdir, "cds.lib")
        run_cds_lib = os.path.join(self.rundir, "cds.lib")
        if os.path.isfile(img_cds_lib) and not os.path.exists(run_cds_lib):
            os.symlink(src=img_cds_lib, dst=run_cds_lib)

        cmd = ['xmsim', '-64bit', 'simv:snap']

        # End-of-run CPU/memory report, parsed by parse_sim_stats
        if '-perfstat' not in data.args:
            cmd.append('-perfstat')

        # Load VPI libraries (eg cocotb's GPI library). Xcelium requires the
        # bootstrap entrypoint to be named explicitly when the library is not
        # 'libvpi.so'; cocotb uses 'vlog_startup_routines_bootstrap'.
        for vpi_path, entrypoint in data.vpilibs:
            ep = entrypoint if entrypoint else "vlog_startup_routines_bootstrap"
            cmd.extend(['-loadvpi', "%s:%s" % (vpi_path, ep)])

        # PLI 1.0 libraries. Those with a boot routine are also recorded in
        # the snapshot by xmelab; loading them again here is harmless.
        cmd.extend(xcm_pli_args(data.plilibs, sim=True))

        for dpi in data.dpilibs:
            dpi_libdir = os.path.dirname(dpi)
            dpi_file = os.path.basename(dpi)
            if dpi_file.rfind('.') > 0:
                dpi_file = dpi_file[:dpi_file.rfind('.')]
            cmd.extend(['-sv_lib', os.path.join(dpi_libdir, dpi_file)])

        if data.cov is not None and data.cov.get("level") in XCM_COV:
            cmd.extend(['-covworkdir', os.path.join(self.rundir, COV_DB),
                        '-covscope', 'scope',
                        '-covtest', cov.db_test_name(self.rundir),
                        '-covoverwrite'])

        # Drop any xProf output of an earlier run, whatever this run profiles
        self._remove_xprof()
        xprof = _xprof(data.prof)

        # The profile (xmprof.out, xmprofmem.*) lands in the rundir. An xProf
        # snapshot ignores -profile, and xProf's own summary stands in for
        # xmprof.out (see parse_prof_summary).
        if xprof:
            cmd.extend(['-prof_work', os.path.join(self.rundir, XPROF_WORK)])
        elif data.prof is not None and data.prof.get("mode", "none") != "none":
            cmd.append(XCM_PROF[data.prof["mode"]])

        for plusarg in data.plusargs:
            cmd.append("+%s" % plusarg)
        for arg in data.args:
            cmd.append(arg)

        status |= await self.exec_sim(cmd, logfile="sim.log")

        # A failing test still writes its database, so report it regardless
        if xprof:
            self._xprof_reports()

        return status

    def _xprof_db(self):
        """The run's xProf database (prof_cpu/prof_db), or None."""
        path = os.path.join(self.rundir, XPROF_WORK, "prof_cpu", "prof_db")
        return os.path.realpath(path) if os.path.isdir(path) else None

    def _remove_xprof(self):
        path = os.path.join(self.rundir, XPROF_WORK)
        if os.path.isdir(path):
            shutil.rmtree(path, ignore_errors=True)
        for _, fname in XPROF_REPORTS:
            fpath = os.path.join(self.rundir, fname)
            if os.path.isfile(fpath):
                os.unlink(fpath)

    def _xprof_reports(self):
        """Write the XPROF_REPORTS with `xprof -batch`. Best-effort: a
        missing database or a failed report leaves the files absent."""
        db = self._xprof_db()
        tool = self._which("xprof", sibling_of="xmsim")
        if db is None or tool is None:
            self._log.debug("no xProf report: db=%s xprof=%s", db, tool)
            return
        script = os.path.join(self.rundir, "xprof_report.tcl")
        with open(script, "w") as fp:
            for view, fname in XPROF_REPORTS:
                fp.write("summary -%s -out %s -overwrite\n" % (
                    view, os.path.join(self.rundir, fname)))
            fp.write("exit\n")
        # -load names the database up front; a `load` command in the script
        # works too, but xprof first tries (and complains about) the default
        self._run_report([tool, "-batch", "-nocopyright", "-load", db,
                          "-input", script, "-log", "xprof.log"])

    def parse_sim_stats(self, logfile):
        return sim_stats.parse_xcm_log_stats(sim_stats.read_log_ends(logfile))

    # No parse_cov_summary: Xcelium's totals come from IMC, which isn't
    # supported yet. The run still yields its database.

    def parse_prof_summary(self, rundir, prof_info):
        mode = prof_info.get("mode")
        if mode == "time":
            path = os.path.join(rundir, "xmprof.out")
            if _xprof(prof_info):
                # Same tables as xmprof.out
                path = os.path.join(rundir, XPROF_WORK, "prof_cpu",
                                    ".xmprof_summary.out")
            if not os.path.isfile(path):
                return None
            with open(path, "r", errors="replace") as fp:
                return prof.parse_xcm_xmprof(fp.read())
        if mode == "mem":
            path = os.path.join(rundir, "xmprofmem.json")
            if not os.path.isfile(path):
                return None
            with open(path, "r", errors="replace") as fp:
                json_text = fp.read()
            out_text = ""
            out = os.path.join(rundir, "xmprofmem.out")
            if os.path.isfile(out):
                with open(out, "r", errors="replace") as fp:
                    out_text = fp.read()
            return prof.parse_xcm_xmprofmem(json_text, out_text)
        return None

    def _artifact_spec(self) -> Dict[str, Tuple]:
        spec = super()._artifact_spec()
        spec["simCovDb"] = ([COV_DB], "cov", ["format=%s" % cov.FORMAT_XCELIUM_UCD])
        # xmprof.out is both the profile data and the report, so a time
        # profile lists it in each. xProf's database is the -prof_work
        # directory, which xprof loads and xprof_merge combines (its raw_data).
        mode = (self._prof or {}).get("mode")
        if _xprof(self._prof):
            spec["simProfDb"] = ([XPROF_WORK], "prof",
                                 ["format=%s" % prof.FORMAT_XCELIUM_XPROF])
            spec["simProfReport"] = ([f for _, f in XPROF_REPORTS],
                                     "prof-report")
        elif mode == "mem":
            spec["simProfDb"] = (["xmprofmem.json"], "prof",
                                 ["format=%s" % prof.FORMAT_XCELIUM_XMPROFMEM])
            spec["simProfReport"] = (["xmprofmem.out"], "prof-report")
        elif mode == "time":
            spec["simProfDb"] = (["xmprof.out"], "prof",
                                 ["format=%s" % prof.FORMAT_XCELIUM_XMPROF])
            spec["simProfReport"] = (["xmprof.out"], "prof-report")
        else:
            # Not profiling: name every file, so a stale one is removed
            spec["simProfDb"] = (["xmprof.out", "xmprofmem.json"], "prof")
            spec["simProfReport"] = (["xmprofmem.out"], "prof-report")
        return spec

def _xprof(prof_info) -> bool:
    """Whether the image's profiling record enables xProf."""
    return bool(((prof_info or {}).get("deep") or {}).get("xprof"))

async def SimRun(runner, input):
    return await SimRunner().run(runner, input)

SimUVMCase = uvm_case_task(SimRunner)
