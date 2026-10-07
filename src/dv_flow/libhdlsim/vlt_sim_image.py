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
from dv_flow.libhdlsim.vl_sim_data import VlSimImageData, c_flags
from dv_flow.mgr.task_data import TaskMarker, TaskMarkerLoc
from svdep import TaskBuildFileCollection
from .vlt_log_parser import VltLogParser

# Coverage level -> (kinds recorded, Verilator flags). Cumulative. Covergroups
# are recorded whenever any --coverage-* flag is on; `cover property` counts as
# `user`. --coverage-line also records branch points.
_COV_LEVELS = {
    "none": ([], []),
    "func": (["covergroup", "user"],
             ["--coverage-user"]),
    "code": (["covergroup", "user", "line", "branch", "expr"],
             ["--coverage-user", "--coverage-line", "--coverage-expr"]),
    "full": (["covergroup", "user", "line", "branch", "expr",
              "toggle", "fsm_state", "fsm_arc"],
             ["--coverage-user", "--coverage-line", "--coverage-expr",
              "--coverage-toggle", "--coverage-fsm"]),
}

class SimImageBuilder(VlSimImageBuilder):

    _log : ClassVar = logging.getLogger("SimImageBuilder[vlt]")

    def cov_kinds(self, level):
        return list(_COV_LEVELS[level][0])

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

        # Coverage instrumentation (the run writes coverage.dat at exit).
        # Ahead of the user's args, so raw flags there still come last.
        cmd.extend(_COV_LEVELS[data.cov_level][1])

        # Three separable concerns, historically conflated:
        #
        #  1. --vpi -- enables Verilator's VPI runtime. Required by anything
        #     that calls VPI from C: a cocotb main, or the UVM DPI layer
        #     (uvm_hdl_verilator.c and uvm_svcmd_dpi.c both make VPI calls,
        #     and uvm_dpi.cc compiles them into one translation unit). This
        #     works fine with the generated --main; upstream Verilator's own
        #     UVM tests use --binary --vpi with no custom main.
        #
        #  2. --public-flat-rw -- signal visibility. Only needed to reach
        #     signals that aren't otherwise marked public, and it inhibits
        #     optimization across the design, so it is not implied by --vpi.
        #
        #  3. Linking an external VPI shared library (data.vpi). This is the
        #     only part that needs a custom main, because the generated main
        #     does not bootstrap a separately-supplied VPI module.
        vpi_enable = data.vpi_enable or len(data.vpi) > 0
        public_flat_rw = data.public_flat_rw or len(data.vpi) > 0

        if len(data.vpi) > 0 and not custom_main:
            raise Exception("Linking a VPI library in VLT requires a verilatorMain (eg cocotb)")

        if vpi_enable:
            cmd.append('--vpi')
        if public_flat_rw:
            cmd.append('--public-flat-rw')

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
        for flag in c_flags(data):
            cmd.extend(['-CFLAGS', flag])
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

        # make.log, not build.log: build.log keeps Verilator's own output
        # (its warnings), which a downstream check reads.
        status |= await self.ctxt.exec(
            make_cmd,
            cwd=input.rundir,
            env=env,
            logfile="make.log")

        self.parseLog(os.path.join(input.rundir, 'make.log'))

        if status:
            return (status, changed)

        try:
            info = TaskBuildFileCollection(data.files, data.incdirs).build()
            # This scan runs against the SAME search path the compile just
            # used, so an unresolved include here is a real hole: the file is
            # compiled in but absent from the dependency graph, and editing it
            # will not mark the image out-of-date.
            if info.unresolved:
                self._log.warning(
                    "Dependency scan could not resolve %s -- changes to %s will not trigger a rebuild" % (
                        ", ".join(info.unresolved),
                        "them" if len(info.unresolved) > 1 else "it"))
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
