#****************************************************************************
#* vlt_sim_image.py
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
import os
import logging
from typing import ClassVar
from dv_flow.mgr import TaskDataResult, TaskRunCtxt
from dv_flow.libhdlsim.vl_sim_image_builder import VlSimImageBuilder, VlTaskSimImageMemento, check_sim_image_uptodate
from dv_flow.libhdlsim.vl_sim_data import VlSimImageData
from dv_flow.mgr.task_data import TaskMarker, TaskMarkerLoc
from svdep import TaskBuildFileCollection
from .vlt_log_parser import VltLogParser

class SimImageBuilder(VlSimImageBuilder):

    _log : ClassVar = logging.getLogger("SimImageBuilder[vlt]")

    def getRefTime(self, rundir):
        if os.path.isfile(os.path.join(rundir, 'obj_dir/simv')):
            return os.path.getmtime(os.path.join(rundir, 'obj_dir/simv'))
        else:
            raise Exception("simv file (%s) does not exist" % os.path.join(rundir, 'obj_dir/simv'))

    async def build(self, input, data : VlSimImageData):
        status = 0
        changed = True

        # Phase 1: verilator elaboration and C++ generation only (no link).
        # DPI lib flags are intentionally omitted here; they are injected via
        # VM_USER_LDLIBS in the explicit make phase below so that the DPI
        # object file (V<top>__Dpi.o) can be listed as a direct link object
        # before the shared library, without relying on -Wl,-u workarounds.
        cmd = ['verilator', '--cc', '--exe', '--main', '-o', 'simv', '-Wno-fatal']

        if data.timing:
            cmd.append('--timing')

        cmd.extend(['-j', '0'])

        for incdir in data.incdirs:
            cmd.append('+incdir+%s' % incdir)
        for define in data.defines:
            cmd.append('+define+%s' % define)

        if data.trace:
            cmd.append('--trace')

        if len(data.vpi) > 0:
            raise Exception("VPI not supported in VLT")

        cmd.extend(data.args)
        cmd.extend(data.compargs)
        cmd.extend(data.elabargs)

        cmd.extend(data.files)
        cmd.extend(data.csource)

        for top in input.params.top:
            cmd.extend(['--top-module', top])

        # Phase 2: make command — deferred until after verilator runs so we can
        # inspect obj_dir for the generated V<top>__Dpi.cpp.
        top_module = input.params.top[0] if input.params.top else 'top'
        mk_file = 'V%s.mk' % top_module

        with open(os.path.join(input.rundir, "build.f"), "w") as fp:
            for elem in cmd[1:]:
                fp.write("%s\n" % elem)

        def no_changes():
            nonlocal changed
            changed = False

        status |= await self.ctxt.exec(
            cmd,
            logfile="build.log",
            logfilter=VltLogParser(
                notify=lambda m: self.ctxt.add_marker(m),
                no_changes=no_changes,
                suppress=self.suppress
            ).line)

        self.parseLog(os.path.join(input.rundir, 'build.log'))

        if status:
            return (status, changed)

        make_cmd = ['make', '-C', 'obj_dir', '-f', mk_file, '-j']

        if data.dpi:
            # V<top>__Dpi.o is a standalone file only when Verilator uses
            # parallel builds (VM_PARALLEL_BUILDS=1 in *_classes.mk).  For
            # small designs VM_PARALLEL_BUILDS=0, meaning all generated .cpp
            # files are merged into __ALL.cpp/__ALL.o; there is no separate
            # __Dpi.o to list.  Read the generated classes.mk to decide.
            classes_mk = os.path.join(input.rundir, 'obj_dir', 'V%s_classes.mk' % top_module)
            parallel_builds = False
            if os.path.isfile(classes_mk):
                with open(classes_mk) as f:
                    for line in f:
                        if line.strip().startswith('VM_PARALLEL_BUILDS'):
                            parallel_builds = '1' in line
                            break

            user_ldlibs = []
            if parallel_builds:
                # Explicitly list V<top>__Dpi.o as a direct link object so it
                # is unconditionally included (not subject to archive
                # dead-stripping).  It must come before -l<lib> so the DPI
                # export stubs it defines are known to the linker when the
                # shared library's undefined refs are checked, eliminating the
                # need for -Wl,-u or --allow-shlib-undefined.
                user_ldlibs.append('V%s__Dpi.o' % top_module)
            # When VM_PARALLEL_BUILDS=0 the DPI stubs are compiled into
            # __ALL.o (always linked), so no explicit listing is needed.
            for dpi in data.dpi:
                dpi_dir = os.path.dirname(dpi)
                lib = os.path.splitext(os.path.basename(dpi))[0]
                if lib.startswith('lib'):
                    lib = lib[3:]
                user_ldlibs.extend([
                    '-L%s' % dpi_dir,
                    '-Wl,-rpath,%s' % dpi_dir,
                    '-l%s' % lib,
                ])
            # --export-dynamic is still needed so that Python extensions
            # loaded at runtime can resolve symbols back into the binary.
            user_ldlibs.append('-Wl,--export-dynamic')
            make_cmd.append('VM_USER_LDLIBS=%s' % ' '.join(user_ldlibs))

        with open(os.path.join(input.rundir, "build.f"), "a") as fp:
            fp.write("\n# make phase:\n")
            for elem in make_cmd:
                fp.write("%s\n" % elem)

        status |= await self.ctxt.exec(
            make_cmd,
            cwd=input.rundir,
            logfile="build.log")

        self.parseLog(os.path.join(input.rundir, 'build.log'))

        if status:
            return (status, changed)

        try:
            info = TaskBuildFileCollection(data.files, data.incdirs).build()
            self.memento = VlTaskSimImageMemento(svdeps=info.to_dict())
        except Exception as e:
            self._log.warning("Failed to build svdep collection: %s" % e)

        return (status, changed)

async def check_uptodate(ctxt) -> bool:
    ref_path = os.path.join(ctxt.rundir, 'obj_dir', 'simv')
    return await check_sim_image_uptodate(ctxt, ref_path)

async def SimImage(ctxt, input) -> TaskDataResult:
    builder = SimImageBuilder(ctxt)
    return await builder.run(ctxt, input)
