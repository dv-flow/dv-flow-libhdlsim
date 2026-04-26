import asyncio
import os
import logging
from typing import ClassVar, List
from dv_flow.mgr import FileSet, TaskDataResult, TaskRunCtxt
from dv_flow.libhdlsim.vl_sim_image_builder import VlSimImageBuilder, VlTaskSimImageMemento
from dv_flow.libhdlsim.vl_sim_data import VlSimImageData
from .vlt_log_parser import VltLogParser
from .util import merge_tokenize


class ProtectLibBuilder(VlSimImageBuilder):
    """Builds a Verilator --protect-lib DPI shared library + SV wrapper.

    Produces two output filesets that a downstream VCS SimImage can consume:
      - systemVerilogSource: the generated SV DPI wrapper
      - systemVerilogDPI:    the shared library (.so)
    """

    _log: ClassVar = logging.getLogger("ProtectLibBuilder[vlt]")

    def getRefTime(self, rundir):
        raise NotImplementedError()

    async def build(self, input, data: VlSimImageData):
        status = 0
        changed = True

        top = input.params.top[0] if input.params.top else "top"
        libname = getattr(input.params, 'libname', '') or top
        jobs = getattr(input.params, 'jobs', 0) or 0

        obj_dir = os.path.join(input.rundir, f"obj_dir_{libname}")

        # Step 1: Run Verilator with --protect-lib
        cmd = ['verilator', '-cc',
               '--protect-lib', libname,
               '-Mdir', obj_dir,
               '-Wno-fatal']

        if data.timing:
            cmd.append('--timing')

        if jobs:
            cmd.extend(['-j', str(jobs)])
        else:
            cmd.extend(['-j', '0'])

        for incdir in data.incdirs:
            cmd.append(f'+incdir+{incdir}')
        for define in data.defines:
            cmd.append(f'+define+{define}')

        cmd.extend(data.args)
        cmd.extend(data.compargs)
        cmd.extend(data.files)

        for t in input.params.top:
            cmd.extend(['--top-module', t])

        with open(os.path.join(input.rundir, "verilator.f"), "w") as fp:
            for elem in cmd[1:]:
                fp.write(f"{elem}\n")

        status |= await self.ctxt.exec(
            cmd,
            logfile="verilator.log",
            logfilter=VltLogParser(
                notify=lambda m: self.ctxt.add_marker(m),
                no_changes=lambda: None,
                suppress=self.suppress
            ).line)

        self.parseLog(os.path.join(input.rundir, 'verilator.log'))

        # Step 2: Compile the C++ library (produces .a and .so)
        if status == 0:
            mk = f"V{top}.mk"
            make_cmd = ['make', '-C', obj_dir, '-f', mk,
                        '-j', str(jobs if jobs else 4)]
            status |= await self.ctxt.exec(make_cmd, logfile="make.log")

        # Step 3: Emit output filesets
        if status == 0:
            # SV wrapper -- consumed as systemVerilogSource by VCS vlogan
            self.output.append(FileSet(
                src=input.name,
                filetype="systemVerilogSource",
                basedir=obj_dir,
                files=[f"{libname}.sv"]
            ))
            # Shared library -- consumed as systemVerilogDPI by VCS vcs
            self.output.append(FileSet(
                src=input.name,
                filetype="systemVerilogDPI",
                basedir=obj_dir,
                files=[f"lib{libname}.so"]
            ))

        return (status, changed)

    async def run(self, ctxt, input) -> TaskDataResult:
        """Override base run() to skip the simDir output fileset."""
        self.input = input
        data = VlSimImageData()
        data.top.extend(input.params.top)
        data.args.extend(merge_tokenize(input.params.args))
        data.compargs.extend(merge_tokenize(input.params.compargs))
        data.elabargs.extend(merge_tokenize(input.params.elabargs))
        data.incdirs.extend(merge_tokenize(input.params.incdirs))
        data.defines.extend(merge_tokenize(input.params.defines))
        data.trace = input.params.trace
        data.timing = input.params.timing if hasattr(input.params, 'timing') else True

        self._gatherSvSources(data, input)

        # Assemble suppress list
        self.suppress = list(merge_tokenize(input.params.suppress_warnings)) if hasattr(input.params, 'suppress_warnings') else []
        for fs in input.inputs:
            if fs.type == "hdlsim.SuppressWarnings":
                self.suppress.extend(fs.codes)

        status, in_changed = await self.build(input, data)

        # Do NOT emit simDir -- this is a library, not a simulation image
        return TaskDataResult(
            memento=None,
            status=status,
            output=self.output,
            changed=in_changed,
            markers=self.markers
        )


async def ProtectLib(ctxt, input) -> TaskDataResult:
    builder = ProtectLibBuilder(ctxt)
    return await builder.run(ctxt, input)
