#****************************************************************************
#* vcs_sim_image.py
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
import asyncio
import json
from typing import List
from dv_flow.libhdlsim.vl_sim_image_builder import (
    VlSimImageBuilder, VlTaskSimImageMemento, check_sim_image_uptodate)
from dv_flow.libhdlsim.vl_sim_data import VlSimImageData
from dv_flow.mgr import FileSet
from dv_flow.mgr.task_data import TaskMarker, SeverityE
from svdep import TaskBuildFileCollection
from .vcs_log_parser import VcsLogParser

class SimImageBuilder(VlSimImageBuilder):

    def check_pli(self, data : VlSimImageData) -> int:
        # VCS PLI 1.0 is table-driven: it does not scan for veriusertfs, and
        # has no boot-routine form.
        status = 0
        for lib in data.pli:
            if not lib.tab:
                self.markers.append(TaskMarker(
                    severity=SeverityE.Error,
                    msg="VCS needs a `tab` file to load PLI 1.0 library %s" % lib.path))
                status = 1
            elif lib.boot:
                self.markers.append(TaskMarker(
                    severity=SeverityE.Warning,
                    msg="VCS ignores `boot` (%s) for PLI 1.0 library %s; the "
                        "`tab` file names its functions" % (lib.boot, lib.path)))
        return status

    def getRefTime(self, rundir):
        if os.path.isfile(os.path.join(rundir, 'simv')):
            return os.path.getmtime(os.path.join(rundir, 'simv'))
        else:
            raise Exception("simv file (%s) does not exist" % os.path.join(rundir, 'simv'))
    
    async def build(self, input, data : VlSimImageData):

        status = 0
        changed = False

        if len(data.files):
            data.libs.append(os.path.join(input.rundir, 'work'))

        # Create the library map
        self.ctxt.create("synopsys_sim.setup", 
                           "\n".join(("%s: %s" % (os.path.basename(lib), lib)) for lib in data.libs))

        # If source is provided, then compile that to a 'work' library
        if len(data.files):
            self._log.debug("Building source files: %s" % str(data.files))

            cmd = ['vlogan', '-full64', '-incr_vlogan', '-work', 'work']

            if data.sysv:
                cmd.append("-sverilog")

            for incdir in data.incdirs:
                cmd.append('+incdir+%s' % incdir)
            for define in data.defines:
                cmd.append('+define+%s' % define)

            cmd.extend(data.args)
            cmd.extend(data.compargs)

            cmd.extend(data.files)

            with open(os.path.join(input.rundir, 'vlogan.f'), 'w') as fh:
                for elem in cmd[1:]:
                    fh.write("%s\n" % elem)

            def file_parsed():
                nonlocal changed
                changed = True

            status |= await self.ctxt.exec(
                cmd, 
                logfile="vlogan.log",
                logfilter=VcsLogParser(
                    notify=lambda m: self.ctxt.add_marker(m),
                    notify_parsing=file_parsed,
                    suppress=self.suppress).line)

            self.parseLog(os.path.join(input.rundir, 'vlogan.log'))

        if status == 0:
            cmd = ['vcs', '-full64']
            
            if input.params.partcomp:
                cmd.append('-partcomp')
                if input.params.fastpartcomp > 0:
                    cmd.append('-fastpartcomp=j%d' % input.params.fastpartcomp)
            cmd.extend(data.args)
            cmd.extend(data.elabargs)

            if len(data.vpi):
                cmd.extend(["+vpi", "-debug_access"])

                for lib_path, entrypoint in data.vpi:
                    if entrypoint:
                        cmd.extend(["-load", f"{lib_path}:{entrypoint}"])
                    else:
                        cmd.extend(["-load", lib_path])

            # PLI 1.0: link each library into simv with its table, and give
            # simv an rpath so the .so is found at run time.
            # TODO: unverified on VCS (no VCS on the development host).
            if len(data.pli):
                if any(l.access for l in data.pli) and "-debug_access" not in cmd:
                    cmd.append("-debug_access")
                rpaths = []
                for lib in data.pli:
                    cmd.extend(["-P", lib.tab, lib.path])
                    libdir = os.path.dirname(lib.path)
                    if libdir not in rpaths:
                        rpaths.append(libdir)
                for libdir in rpaths:
                    cmd.extend(["-LDFLAGS", "-Wl,-rpath,%s" % libdir])

            if len(data.dpi):
                for dpi in data.dpi:
                    self.output.append(FileSet(
                        basedir=os.path.dirname(dpi),
                        files=[os.path.basename(dpi)],
                        filetype="systemVerilogDPI"
                    ))

            cmd.extend(self.input.params.args)

            cmd.extend(data.csource)

            # Seems that VCS behaves better with the list in the setup file
#            if len(libs):
#                cmd.extend(['-liblist', "+".join(os.path.basename(l) for l in libs)])

            if len(input.params.top):
                cmd.extend(['-top', "+".join(input.params.top)])

                self._log.debug("VCS command: %s" % str(cmd))

            status |= await self.ctxt.exec(
                cmd, 
                logfile="vcs.log")

            # Pull in error/warning markers
            self.parseLog(os.path.join(input.rundir, 'vcs.log'))

        if status == 0:
            # Record the svdep collection (SV roots + include graph) so that
            # check_uptodate can detect edits to `include'd files that are not
            # named directly in any FileSet glob.
            try:
                info = TaskBuildFileCollection(data.files, data.incdirs).build()
                self.memento = VlTaskSimImageMemento(svdeps=info.to_dict())
            except Exception as e:
                self._log.warning("Failed to build svdep collection: %s" % e)

        return (status,changed)

async def check_uptodate(ctxt) -> bool:
    ref_path = os.path.join(ctxt.rundir, 'simv')
    return await check_sim_image_uptodate(ctxt, ref_path)

async def SimImage(ctxt, input):
    builder = SimImageBuilder(ctxt)
    return await builder.run(ctxt, input)

