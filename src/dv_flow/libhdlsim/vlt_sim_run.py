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
import re
from typing import List
from dv_flow.mgr import TaskDataResult, FileSet
from dv_flow.libhdlsim.vl_sim_runner import VLSimRunner
from dv_flow.libhdlsim.vl_sim_data import VlSimRunData

class SimRunner(VLSimRunner):
    sim_name = "vlt"


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

        status |= await self.exec_sim(cmd, logfile="sim.log")

        return status

    # Verilator's end-of-run summary (VerilatedContext::statsPrintSummary,
    # emitted by the generated --main), eg:
    #
    #   - S i m u l a t i o n   R e p o r t: Verilator 5.049 devel
    #   - Verilator: $finish at 608us; walltime 5.280 s; speed 115.202 us/s
    #   - Verilator: cpu 5.276 s on 1 threads; allocated 396 MB
    #
    # Absent when the run used `+verilator+quiet`, or when the image was built
    # with a custom C++ main (eg cocotb's) that does not call
    # statsPrintSummary() -- in which case these keys are simply not reported.
    _RE_VERSION = re.compile(r'^-\s*S i m u l a t i o n\s+R e p o r t:\s*(.+?)\s*$')
    _RE_FINISH = re.compile(
        r'^-\s*Verilator:\s*(\$finish|\$stop|end)\s+at\s+(\S+?);'
        r'\s*walltime\s+([0-9.]+)\s*s;\s*speed\s+(.+?)/s\s*$')
    _RE_CPU = re.compile(
        r'^-\s*Verilator:\s*cpu\s+([0-9.]+)\s*s\s+on\s+(\d+)\s+threads;'
        r'\s*allocated\s+([0-9.]+)\s*MB\s*$')

    def parse_sim_stats(self, logfile):
        stats = {}
        if not os.path.isfile(logfile):
            return stats

        # The summary is the last thing printed; scan the tail rather than the
        # whole log (a UVM log can be very large).
        try:
            with open(logfile, "r", errors="replace") as fp:
                try:
                    fp.seek(max(0, os.path.getsize(logfile) - 8192))
                except Exception:
                    pass
                tail = fp.read()
        except Exception:
            return stats

        for l in tail.splitlines():
            m = self._RE_VERSION.match(l)
            if m:
                stats["sim_version"] = m.group(1)
                continue
            m = self._RE_FINISH.match(l)
            if m:
                stats["finish_reason"] = m.group(1)
                # Printed with %0.0f scaled to 1..1000, so '608us' is exact to
                # the printed digit only. sim_stats.finalize derives simtime_s.
                stats["simtime"] = m.group(2)
                stats["sim_walltime_s"] = float(m.group(3))
                continue
            m = self._RE_CPU.match(l)
            if m:
                stats["sim_cpu_s"] = float(m.group(1))
                stats["threads"] = int(m.group(2))
                stats["sim_mem_mb"] = float(m.group(3))

        return stats


async def SimRun(runner, input) -> TaskDataResult:
    return await SimRunner().run(runner, input)

