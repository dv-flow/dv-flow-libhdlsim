import os
import asyncio
import json
import logging
import shutil
from typing import List
from dv_flow.mgr import TaskDataResult, FileSet

_log = logging.getLogger("SimLibUVM")

async def SimLibUVM(runner, input):
    ex_memento = input.memento

    # TODO: determine whether we're up-to-date

    with open(os.path.join(input.rundir, 'synopsys_sim.setup'), 'w') as fp:
        fp.write("uvm: %s\n" % os.path.join(input.rundir, 'uvm'))
        
    which_vlogan = shutil.which('vlogan')
    if which_vlogan is None:
        raise Exception("vlogan not found in PATH")

    vcs_home = os.path.dirname(os.path.dirname(which_vlogan))

    cmd = ['vlogan', '-full64', '-sverilog', '-work', 'uvm', '-ntb_opts', 'uvm-1.2']

    _log.debug("Running vlogan: %s", " ".join(cmd))

    fp = open(os.path.join(input.rundir, 'build.log'), "w")
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        cwd=input.rundir,
        stdout=fp,
        stderr=asyncio.subprocess.STDOUT)

    await proc.wait()
    fp.close()

    if proc.returncode != 0:
        raise Exception("VCS failed (%d)" % proc.returncode)

    return TaskDataResult(
        memento=ex_memento,
        changed=True,
        output=[
            FileSet(
                basedir=os.path.join(vcs_home, "etc/uvm-1.2"),
                filetype="verilogIncDir"),
            FileSet(
                basedir=os.path.join(input.rundir, "uvm"),
                filetype="simLib")
        ])

