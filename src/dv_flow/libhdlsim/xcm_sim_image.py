#****************************************************************************
#* xcm_sim_image.py
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
from typing import List, Tuple
from dv_flow.libhdlsim.vl_sim_image_builder import VlSimImageBuilder, VlTaskSimImageMemento, check_sim_image_uptodate
from dv_flow.libhdlsim.vl_sim_data import VlSimImageData
from dv_flow.mgr import FileSet
from svdep import TaskBuildFileCollection
from .util import xcelium_cds_lib
from .xcm_sim_run import check_xcm_pli, xcm_pli_args

class SimImageBuilder(VlSimImageBuilder):

    # Xcelium loads VPI at run time (xmsim -loadvpi), so forward to SimRun.
    forward_vpi = True
    # PLI 1.0 is loaded at elaboration (registers the systfs) and again at
    # run time (a table-only library can only be bound by xmsim).
    forward_pli = True

    def check_pli(self, data : VlSimImageData) -> int:
        return check_xcm_pli(data.pli, self.markers)

    def getRefTime(self, rundir):
        if os.path.isfile(os.path.join(rundir, 'simv_opt.d')):
            return os.path.getmtime(os.path.join(rundir, 'simv_opt.d'))
        else:
            raise Exception("simv_opt.d file (%s) does not exist" % os.path.join(rundir, 'simv_opt.d'))

    async def build(self, input, data : VlSimImageData) -> Tuple[int,bool]:
        cmd = []
        status = 0
        changed = False

        # Assemble the cds.lib: install default (std/IEEE), the local work
        # library (kept under xcelium.d so xcm_sim_run.py's xcelium.d symlink
        # resolves the snapshot), plus each consumed precompiled simLib. The
        # elaborator resolves cross-library instances via default binding.
        # The worklib physical directory must exist or Xcelium rejects the
        # cds.lib DEFINE (*W,DLCPTH -> *F,WRKBAD).
        worklib = os.path.join(input.rundir, "xcelium.d", "worklib")
        os.makedirs(worklib, exist_ok=True)
        defines = [("worklib", worklib)]
        seen = {"worklib"}
        for lib in data.libs:
            logical = os.path.basename(lib)
            if logical in seen:
                continue
            seen.add(logical)
            defines.append((logical, lib))

        # MSIE: make each consumed primary snapshot's library visible so the
        # elaborator can bind it (-primsnap) and the simulator can resolve it at
        # runtime (SimRun symlinks this cds.lib).
        for lib in data.primaries:
            logical = os.path.basename(lib)
            if logical in seen:
                continue
            seen.add(logical)
            defines.append((logical, lib))

        self.ctxt.create("cds.lib", xcelium_cds_lib(defines))

        # Compile local sources into worklib (skip when all sources come from
        # precompiled libraries).
        if len(data.files):
            cmd = ['xmvlog', '-sv', '-64bit', '-update', '-work', 'worklib']

            for incdir in data.incdirs:
                cmd.extend(['-incdir', incdir])

            for define in data.defines:
                cmd.extend(['-define', define])

            cmd.extend(data.args)
            cmd.extend(data.compargs)

            cmd.extend(data.files)

            status |= await self.ctxt.exec(
                cmd,
                logfile="xmvlog.log")

        # Now, run elaboration
        if not status:
            cmd = ['xmelab', '-64bit', '-snap', 'simv:snap']

            # VPI libraries (eg cocotb) require read/write/connectivity access
            # to be granted at elaboration; the lib itself is loaded at run time
            # via 'xmsim -loadvpi' (see xcm_sim_run).
            # PLI 1.0 libraries that ask for `access` need the same.
            if len(data.vpi) or any(l.access for l in data.pli):
                cmd.extend(['-access', '+rwc'])

            cmd.extend(xcm_pli_args(data.pli, sim=False))

            for top in input.params.top:
                cmd.append(top)

            # MSIE: bind each consumed primary snapshot by cell name. The
            # elaborator binds the pre-elaborated PRM instead of re-elaborating
            # the subsystem's contents.
            for primtop in data.primtops:
                cmd.extend(['-primsnap', primtop])

            cmd.extend(data.args)
            cmd.extend(data.elabargs)

            status |= await self.ctxt.exec(cmd, logfile="xmelab.log")

        # Compile C/C++ DPI sources into a shared library
        if not status and len(data.csource) > 0:
            dpi_lib = os.path.join(input.rundir, 'libdpi.so')
            cmd = ['gcc', '-shared', '-fPIC', '-m64', '-o', dpi_lib]

            # Locate the Xcelium DPI header directory (svdpi.h)
            xmvlog_path = shutil.which('xmvlog')
            if xmvlog_path:
                tools_root = os.path.dirname(os.path.dirname(xmvlog_path))
                for candidate in [
                    os.path.join(tools_root, 'include'),
                    os.path.join(tools_root, 'inca', 'include'),
                ]:
                    if os.path.isfile(os.path.join(candidate, 'svdpi.h')):
                        cmd.extend(['-I', candidate])
                        break

            cmd.extend(data.csource)
            status |= await self.ctxt.exec(cmd, logfile="gcc_dpi.log")

            if not status:
                self.output.append(FileSet(
                    basedir=input.rundir,
                    files=['libdpi.so'],
                    filetype="systemVerilogDPI"
                ))

        if not status:
            with open(os.path.join(input.rundir, 'simv_opt.d'), "w") as fp:
                fp.write("\n")
            try:
                info = TaskBuildFileCollection(data.files, data.incdirs).build()
                self.memento = VlTaskSimImageMemento(svdeps=info.to_dict())
            except Exception as e:
                self._log.warning("Failed to build svdep collection: %s" % e)

        if len(data.dpi):
            for dpi in data.dpi:
                self.output.append(FileSet(
                    basedir=os.path.dirname(dpi),
                    files=[os.path.basename(dpi)],
                    filetype="systemVerilogDPI"
                ))

        return (status, True)

async def check_uptodate(ctxt) -> bool:
    ref_path = os.path.join(ctxt.rundir, 'simv_opt.d')
    return await check_sim_image_uptodate(ctxt, ref_path)

async def SimImage(ctxt, input):
  builder = SimImageBuilder(ctxt)
  return await builder.run(ctxt, input)
