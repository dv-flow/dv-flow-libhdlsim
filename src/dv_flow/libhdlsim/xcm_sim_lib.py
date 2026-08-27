#****************************************************************************
#* xcm_sim_lib.py
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
from pathlib import Path
from dv_flow.libhdlsim.vl_sim_lib_builder import VlSimLibBuilder
from dv_flow.libhdlsim.vl_sim_data import VlSimImageData
from .util import xcelium_cds_lib


class SimLibBuilder(VlSimLibBuilder):
    """Compiles HDL sources into an Xcelium logical library (via ``xmvlog -work``).

    The library is a plain "compiled-source" logical library (Library.Cell:View
    model). It is referenced downstream by adding its ``DEFINE`` to the
    consumer's ``cds.lib``; the elaborator (``xmelab``) then resolves module/UDP
    instances across all defined libraries via default binding. This mirrors the
    VCS (``synopsys_sim.setup``) and Questa (``vopt -L``) library flows.
    """

    def getRefTime(self, rundir):
        # Defensive only: no custom uptodate: is wired (we rely on `xmvlog -update`)
        if os.path.isfile(os.path.join(rundir, 'simlib.d')):
            return os.path.getmtime(os.path.join(rundir, 'simlib.d'))
        else:
            raise Exception("simlib.d file (%s) does not exist" % os.path.join(rundir, 'simlib.d'))

    async def build(self, input, data : VlSimImageData):
        status = 0
        changed = False

        rundir = input.rundir
        libname = input.params.libname

        # Physical library directory. This MUST equal os.path.join(basedir, file)
        # so that _gatherSvSources in downstream consumers reconstructs the same
        # path (basedir=rundir, file=libname).
        libdir = os.path.join(rundir, libname)
        os.makedirs(libdir, exist_ok=True)

        # Assemble the cds.lib: pull in the install default (std/IEEE/std pkgs),
        # define this library, and make any upstream precompiled libraries
        # visible so this library can compile/elaborate against them.
        defines = [(libname, libdir)]
        seen = {libname}
        for lib in data.libs:
            logical = os.path.basename(lib)
            if logical in seen:
                continue
            seen.add(logical)
            defines.append((logical, lib))

        self.runner.create("cds.lib", xcelium_cds_lib(defines))

        cmd = ['xmvlog', '-sv', '-64bit', '-update', '-work', libname]

        for incdir in data.incdirs:
            if incdir.strip() != "":
                cmd.extend(['-incdir', incdir])
        for define in data.defines:
            cmd.extend(['-define', define])

        cmd.extend(data.args)
        cmd.extend(data.compargs)
        cmd.extend(data.files)

        status |= await self.runner.exec(cmd, logfile="xmvlog.log")

        if not status:
            Path(os.path.join(rundir, 'simlib.d')).touch()
            # No reliable per-file "compiled" banner from xmvlog; report changed
            # on any successful (re)compile. `xmvlog -update` keeps this cheap.
            changed = True

        return (status, changed)


async def SimLib(runner, input):
    builder = SimLibBuilder(runner)
    return await builder.run(runner, input)
