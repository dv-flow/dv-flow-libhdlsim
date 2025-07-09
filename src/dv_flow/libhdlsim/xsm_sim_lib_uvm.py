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
from typing import List
from dv_flow.mgr import TaskDataResult, FileSet, TaskRunCtxt
from dv_flow.mgr.task_data import TaskMarker, TaskMarkerLoc

_log = logging.getLogger("SimLibUVM")

async def SimLibUVM(ctxt : TaskRunCtxt, input):
    ex_memento = input.memento
    status = 0
    markers = []
    changed = False

    return TaskDataResult(
        memento=(ex_memento if status == 0 else None),
        changed=changed,
        output=[
            ctxt.mkDataItem(
                type="hdlsim.SimElabArgs",
                args=["-L", "uvm"]
            ),
            ctxt.mkDataItem(
                type="hdlsim.SimCompileArgs",
                args=["-L", "uvm"]
            )
        ],
        status=status,
        markers=markers)

