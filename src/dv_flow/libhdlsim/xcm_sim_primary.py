#****************************************************************************
#* xcm_sim_primary.py
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
import logging
from pathlib import Path
from typing import ClassVar, Tuple
from dv_flow.mgr import FileSet, TaskDataResult
from dv_flow.libhdlsim.vl_sim_image_builder import VlSimImageBuilder
from dv_flow.libhdlsim.vl_sim_data import VlSimImageData
from .util import merge_tokenize, xcelium_cds_lib


class SimPrimaryBuilder(VlSimImageBuilder):
    """Pre-elaborates a stable subsystem into an Xcelium *primary snapshot* (MSIE).

    This implements the "primary partition" side of Xcelium Multi-Snapshot
    Incremental Elaboration (Type C, pre-elaborated artifact). A stable module
    (DUT/IP) is compiled into its own logical library and elaborated *once* with
    ``xmelab <lib>.<top> -mkprimsnap`` to produce a non-simulatable ``PRM``
    design unit. A downstream ``SimImage`` then binds it via
    ``xmelab <tb_top> -primsnap <top>`` **without re-elaborating** it.

    Output is a ``simPrimary`` FileSet:
      - ``basedir`` = this task's rundir
      - ``files``   = [<libname>]  (the physical library dir, relative to basedir)
      - ``attributes`` = ["primtop=<top>", ...]  (primary cell names to bind)

    The consumer adds ``DEFINE <libname> <rundir>/<libname>`` to its cds.lib so
    the elaborator (and, via SimRun's cds.lib symlink, the simulator) can resolve
    the primary. Mirrors the cds.lib mechanics of the xcm SimLib/SimImage flow.
    """

    _log : ClassVar = logging.getLogger("SimPrimaryBuilder[xcm]")

    def getRefTime(self, rundir):
        # Defensive only: no custom uptodate: is wired (we rely on xmvlog/xmelab
        # -update). primsnap.d is touched on a successful primary build.
        p = os.path.join(rundir, 'primsnap.d')
        if os.path.isfile(p):
            return os.path.getmtime(p)
        raise Exception("primsnap.d file (%s) does not exist" % p)

    async def build(self, input, data : VlSimImageData) -> Tuple[int, bool]:
        status = 0
        changed = False

        rundir = input.rundir
        libname = input.params.libname
        if libname is None or libname == "":
            libname = input.name.replace(".", "_")

        # Physical library directory. MUST equal os.path.join(basedir, file) so a
        # downstream consumer reconstructs the same path (basedir=rundir,
        # file=libname), matching _gatherSvSources for the simPrimary filetype.
        libdir = os.path.join(rundir, libname)
        os.makedirs(libdir, exist_ok=True)

        # cds.lib: install default (std/IEEE), this primary's library, plus any
        # upstream precompiled libraries this subsystem compiles/elaborates
        # against.
        defines = [(libname, libdir)]
        seen = {libname}
        for lib in data.libs:
            logical = os.path.basename(lib)
            if logical in seen:
                continue
            seen.add(logical)
            defines.append((logical, lib))

        self.ctxt.create("cds.lib", xcelium_cds_lib(defines))

        # Compile the stable sources into the primary's library.
        if len(data.files):
            cmd = ['xmvlog', '-sv', '-64bit', '-update', '-work', libname]
            for incdir in data.incdirs:
                if incdir.strip() != "":
                    cmd.extend(['-incdir', incdir])
            for define in data.defines:
                cmd.extend(['-define', define])
            cmd.extend(data.args)
            cmd.extend(data.compargs)
            cmd.extend(data.files)

            status |= await self.ctxt.exec(cmd, logfile="xmvlog.log")

        # Pre-elaborate each requested top as a primary snapshot. A primary is
        # not simulatable on its own; it is bound into a SimImage later.
        if not status:
            for top in input.params.top:
                cmd = ['xmelab', '-64bit', '%s.%s' % (libname, top), '-mkprimsnap']
                cmd.extend(data.args)
                cmd.extend(data.elabargs)
                status |= await self.ctxt.exec(cmd, logfile="xmelab_%s.log" % top)
                if status:
                    break

        if not status:
            Path(os.path.join(rundir, 'primsnap.d')).touch()
            changed = True

        return (status, changed)

    async def run(self, ctxt, input) -> TaskDataResult:
        # Gather sources like SimImage, but emit a simPrimary FileSet rather than
        # a simDir (a primary is a reusable artifact, not a runnable image).
        self.ctxt = ctxt
        self.input = input

        data = VlSimImageData()
        data.top.extend(input.params.top)
        data.args.extend(merge_tokenize(input.params.args))
        data.compargs.extend(merge_tokenize(input.params.compargs))
        data.elabargs.extend(merge_tokenize(input.params.elabargs))
        data.incdirs.extend(merge_tokenize(input.params.incdirs))
        data.defines.extend(merge_tokenize(input.params.defines))

        self._gatherSvSources(data, input)

        self.suppress = list(merge_tokenize(input.params.suppress_warnings)) if hasattr(input.params, 'suppress_warnings') else []
        for fs in input.inputs:
            if fs.type == "hdlsim.SuppressWarnings":
                self.suppress.extend(fs.codes)

        status, changed = await self.build(input, data)

        libname = input.params.libname
        if libname is None or libname == "":
            libname = input.name.replace(".", "_")

        if status == 0:
            self.output.append(FileSet(
                src=input.name,
                filetype="simPrimary",
                basedir=input.rundir,
                files=[libname],
                attributes=["primtop=%s" % t for t in input.params.top]))

        return TaskDataResult(
            memento=None,
            status=status,
            output=self.output,
            changed=changed,
            markers=self.markers)


async def SimPrimary(ctxt, input) -> TaskDataResult:
    builder = SimPrimaryBuilder(ctxt)
    return await builder.run(ctxt, input)
