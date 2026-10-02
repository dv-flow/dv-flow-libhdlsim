#****************************************************************************
#* ivl_sim_run.py
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
from dv_flow.mgr import TaskData, FileSet
from dv_flow.mgr.task_data import TaskMarker, SeverityE
from dv_flow.libhdlsim.vl_sim_runner import VLSimRunner
from dv_flow.libhdlsim.vl_sim_data import PliLib, VlSimRunData

def check_ivl_pli(libs : List[PliLib], markers : List[TaskMarker]) -> int:
    """Icarus hosts PLI 1.0 through its cadpli VPI module, which calls the
    library's boot routine for the s_tfcell table. It has no .tab support."""
    status = 0
    for lib in libs:
        if lib.tab:
            markers.append(TaskMarker(
                severity=SeverityE.Error,
                msg="Icarus does not support PLI 1.0 `tab` files (%s)" % lib.tab))
            status = 1
        if not lib.boot:
            markers.append(TaskMarker(
                severity=SeverityE.Error,
                msg="Icarus needs a `boot` routine to load PLI 1.0 library %s" % lib.path))
            status = 1
    return status

def ivl_module_dir():
    """Icarus' default VPI module directory (<prefix>/lib/ivl), or None."""
    vvp = shutil.which("vvp")
    if vvp is None:
        return None
    libdir = os.path.join(os.path.dirname(os.path.dirname(os.path.realpath(vvp))), "lib", "ivl")
    return libdir if os.path.isdir(libdir) else None

class SimRunner(VLSimRunner):
    sim_name = "ivl"

    def check_pli(self, data : VlSimRunData) -> int:
        status = check_ivl_pli(data.plilibs, self.markers)
        if len(data.plilibs):
            # cadpli is optional in an Icarus build. Without it vvp would only
            # warn and run with the systfs undefined.
            libdir = ivl_module_dir()
            if libdir is not None and \
                    os.path.isfile(os.path.join(libdir, "system.vpi")) and \
                    not any(os.path.isfile(os.path.join(libdir, "cadpli" + ext))
                            for ext in (".vpl", ".vpi")):
                self.markers.append(TaskMarker(
                    severity=SeverityE.Error,
                    msg="This Icarus install has no cadpli module (%s), which "
                        "PLI 1.0 libraries need" % libdir))
                status = 1
        return status


    async def runsim(self, data : VlSimRunData) -> TaskData:
        status = 0

        cmd = ['vvp']

        # Load VPI libraries (eg cocotb's GPI library) ahead of the image.
        # Icarus loads a VPI module via '-M <dir> -m <module>', where <module>
        # is the library name without its directory or extension (Icarus
        # appends '.vpl'). The optional entrypoint is not used by Icarus.
        seen_dirs = set()
        for vpilib, _entrypoint in data.vpilibs:
            libdir = os.path.dirname(vpilib)
            module = os.path.basename(vpilib)
            for ext in (".vpl", ".vpi", ".so"):
                if module.endswith(ext):
                    module = module[:-len(ext)]
                    break
            if libdir and libdir not in seen_dirs:
                cmd.extend(['-M', libdir])
                seen_dirs.add(libdir)
            cmd.extend(['-m', module])

        # PLI 1.0 libraries are hosted by the cadpli module, which takes each
        # library as a `-cadpli=<lib>:<boot>` extended argument.
        # TODO: unverified (cadpli is not in the development host's Icarus).
        if len(data.plilibs):
            cmd.append('-mcadpli')

        if len(data.dpilibs):
            raise Exception("Icarus Verilog does not support DPI libraries")

        cmd.append(os.path.join(data.imgdir, 'simv.vpp'))

        for lib in data.plilibs:
            cmd.append('-cadpli=%s:%s' % (lib.path, lib.boot))

        for plusarg in data.plusargs:
            cmd.append("+%s" % plusarg)

        cmd.extend(data.args)

        status |= await self.exec_sim(cmd, logfile="sim.log")

        return status

async def SimRun(runner, input) -> TaskData:
    return await SimRunner().run(runner, input)

