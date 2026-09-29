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
from typing import List
from dv_flow.libhdlsim.vl_sim_runner import VLSimRunner
from dv_flow.libhdlsim.sim_uvm_case import uvm_case_task

class SimRunner(VLSimRunner):
    sim_name = "xcm"


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

async def SimRun(runner, input):
    return await SimRunner().run(runner, input)

SimUVMCase = uvm_case_task(SimRunner)
