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
from dv_flow.libhdlsim import cov
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

        for plusarg in data.plusargs:
            cmd.append("+%s" % plusarg)
        for arg in data.args:
            cmd.append(arg)

        status |= await self.exec_sim(cmd, logfile="sim.log")

        return status

    # No parse_cov_summary: Xcelium's totals come from IMC, which isn't
    # supported yet. The run still yields its database.

    def _artifact_spec(self) -> Dict[str, Tuple]:
        spec = super()._artifact_spec()
        spec["simCovDb"] = ([COV_DB], "cov", ["format=%s" % cov.FORMAT_XCELIUM_UCD])
        return spec

async def SimRun(runner, input):
    return await SimRunner().run(runner, input)

SimUVMCase = uvm_case_task(SimRunner)
