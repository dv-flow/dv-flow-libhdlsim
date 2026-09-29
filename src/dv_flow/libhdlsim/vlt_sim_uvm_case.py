#****************************************************************************
#* vlt_sim_uvm_case.py
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
#****************************************************************************
"""Verilator `SimUVMCase`. The case logic is shared by every UVM-capable
backend (see `sim_uvm_case`); this module keeps the pytask path that
`vlt_flow.dv` names.
"""

from dv_flow.libhdlsim.vlt_sim_run import SimRunner
from dv_flow.libhdlsim.sim_uvm_case import uvm_case_task

SimUVMCase = uvm_case_task(SimRunner)
UVMCaseRunner = SimUVMCase.case_cls
