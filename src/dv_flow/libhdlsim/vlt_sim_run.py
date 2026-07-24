#****************************************************************************
#* vlt_sim_run.py
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
import json
import os
from typing import List
from dv_flow.mgr import TaskDataResult, FileSet
from dv_flow.libhdlsim.vl_sim_runner import VLSimRunner
from dv_flow.libhdlsim.vl_sim_data import VlSimRunData

class SimRunner(VLSimRunner):

    async def runsim(self, data : VlSimRunData):
        status = 0

        cmd = []

#        cmd.extend(['valgrind', '--tool=memcheck'])

        cmd.append(os.path.join(data.imgdir, 'obj_dir/simv'))

#        cmd.extend(['-CFLAGS', '-g'])

        cmd.extend(data.args)

        for p in data.plusargs:
            cmd.append("+%s" % p)

        if len(data.dpilibs):
            raise Exception("DPI libraries not supported yet")

        if len(data.vpilibs):
            raise Exception("VPI libraries not supported yet")

        # `trace: true` on the run requests waveform dumping. Pass the project
        # `+trace` plusarg the testbench tests via `$test$plusargs("trace")` to
        # open its dump (`$dumpfile`/`$dumpvars`) -- the same plusarg
        # SimRunArgsDbg emits. (Previously this passed `+verilator+debug`, which
        # only enables Verilator's internal runtime debug logging, not tracing.)
        # The image must have been built with `--trace` (see SimElabArgsDbg);
        # avoid double-adding `+trace` if it already arrived via plusargs.
        if data.trace and "trace" not in data.plusargs:
            cmd.append("+trace")

        status |= await self.ctxt.exec(cmd, logfile="sim.log")

        return status


async def SimRun(runner, input) -> TaskDataResult:
    return await SimRunner().run(runner, input)

