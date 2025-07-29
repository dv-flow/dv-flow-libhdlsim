#****************************************************************************
#* xsm_sim_lib_uvm.py
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
