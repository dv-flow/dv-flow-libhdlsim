import os
import asyncio
import json
import logging
import shutil
import pathlib
from typing import List
from dv_flow.mgr import TaskDataResult, FileSet, TaskRunCtxt
from dv_flow.mgr.task_data import TaskMarker, TaskMarkerLoc

async def SimLibUVM(ctxt, input):
    xvlog = shutil.which('xvlog')
    if xvlog is None:
        raise Exception("xvlog not found in PATH")
    vivado_dir = os.path.dirname(os.path.dirname(xvlog))
    return TaskDataResult(
        status=0,
        output=[
            ctxt.mkDataItem("hdlsim.SimCompileArgs", 
                            args=["--lib", "uvm"],
                            incdirs=[os.path.join(vivado_dir, "data/system_verilog/uvm_1.2")]),
            ctxt.mkDataItem("hdlsim.SimElabArgs", args=["--lib", "uvm"])
        ]
    )
