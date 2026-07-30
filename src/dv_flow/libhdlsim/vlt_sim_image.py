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
import glob
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

        # When a verilatorMain data item is supplied (eg cocotb's verilator.cpp),
        # build in --exe mode with that main instead of letting Verilator generate
        # one (--main). The supplier is responsible for matching the Verilator
        # --prefix (passed via compargs) to whatever the main #includes.
        custom_main = data.verilator_main is not None

        # The 'verilator' wrapper errors if VERILATOR_ROOT is set to a path that
        # disagrees with its own self-location; drop it for the custom-main build.
        env = None
        if custom_main and 'VERILATOR_ROOT' in self.ctxt.env:
            env = dict(self.ctxt.env)
            env.pop('VERILATOR_ROOT')

        # Phase 1: verilator elaboration and C++ generation only (no link).
        # DPI lib flags are intentionally omitted here; they are injected via
        # VM_USER_LDLIBS in the explicit make phase below so that the DPI
        # object file (V<top>__Dpi.o) can be listed as a direct link object
        # before the shared library, without relying on -Wl,-u workarounds.
        cmd = ['verilator', '--cc', '--exe', '-o', 'simv', '-Wno-fatal']
        if not custom_main:
            cmd.append('--main')

        if data.timing:
            cmd.append('--timing')

        cmd.extend(['-j', '0'])

        for incdir in data.incdirs:
            cmd.append('+incdir+%s' % incdir)
        for define in data.defines:
            cmd.append('+define+%s' % define)

        # Waveform tracing. Format (and enable) come from `trace_fmt`
        # (none|fst|vcd), set by a trace-enabled elab-args preset. The legacy
        # `trace: true` SimImage bool also enables tracing, defaulting to fst.
        trace_fmt = getattr(data, 'trace_fmt', 'none')
        if (not trace_fmt or trace_fmt == 'none') and data.trace:
            trace_fmt = 'fst'
        if trace_fmt == 'fst':
            cmd.append('--trace-fst')
        elif trace_fmt == 'vcd':
            cmd.append('--trace')

        if len(data.vpi) > 0:
            if not custom_main:
                raise Exception("VPI in VLT requires a verilatorMain (eg cocotb)")
            # Generic VPI: expose signals and link the VPI shared library(ies).
            cmd.extend(['--vpi', '--public-flat-rw'])
            for lib_path, _entrypoint in data.vpi:
                lib_dir = os.path.dirname(lib_path)
                lib = os.path.splitext(os.path.basename(lib_path))[0]
                if lib.startswith('lib'):
                    lib = lib[3:]
                cmd.extend(['-LDFLAGS', '-L%s' % lib_dir,
                            '-LDFLAGS', '-l%s' % lib,
                            '-LDFLAGS', '-Wl,-rpath,%s' % lib_dir])

        cmd.extend(data.args)
        cmd.extend(data.compargs)
        cmd.extend(data.elabargs)

        cmd.extend(data.files)
        cmd.extend(data.csource)
        if custom_main:
            cmd.append(data.verilator_main)

        for top in input.params.top:
            cmd.extend(['--top-module', top])

        top_module = input.params.top[0] if input.params.top else 'top'

        with open(os.path.join(input.rundir, "build.f"), "w") as fp:
            for elem in cmd[1:]:
                fp.write("%s\n" % elem)

        def no_changes():
            nonlocal changed
            changed = False

        status |= await self.ctxt.exec(
            cmd,
            env=env,
            logfile="build.log",
            logfilter=VltLogParser(
                notify=lambda m: self.ctxt.add_marker(m),
                no_changes=no_changes,
                suppress=self.suppress
            ).line)

        self.parseLog(os.path.join(input.rundir, 'build.log'))

        if status:
            return (status, changed)

        # Phase 2: make. With a custom --prefix (eg cocotb's Vtop) the makefile
        # name is not derivable from the top module, so discover it: there is a
        # single V<prefix>.mk alongside V<prefix>_classes.mk.
        if custom_main:
            mks = [f for f in glob.glob(os.path.join(input.rundir, 'obj_dir', '*.mk'))
                   if not f.endswith('_classes.mk')]
            if not mks:
                raise Exception("No generated Verilator makefile found in obj_dir")
            mk_file = os.path.basename(mks[0])
        else:
            mk_file = 'V%s.mk' % top_module

        # `-j <n>`, not a bare `-j`: bare means UNLIMITED, so several image
        # builds running at once spawn unbounded g++ and the OOM killer takes
        # cc1plus. `ctxt.cores` is this task's budget -- the batch allocation
        # under a scheduler, the `-j` budget locally.
        make_cmd = ['make', '-C', 'obj_dir', '-f', mk_file,
                    '-j', str(getattr(self.ctxt, 'cores', 1) or 1)]

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
            env=env,
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
