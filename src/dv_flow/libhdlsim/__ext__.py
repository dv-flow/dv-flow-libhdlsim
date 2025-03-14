#****************************************************************************
#* __ext__.py
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

def dvfm_packages():
    hdlsim_dir = os.path.dirname(os.path.abspath(__file__))

    return {
        'hdlsim': os.path.join(hdlsim_dir, "flow.dv"),
        'hdlsim.ivl': os.path.join(hdlsim_dir, "ivl_flow.dv"),
        'hdlsim.mti': os.path.join(hdlsim_dir, "mti_flow.dv"),
        'hdlsim.vcs': os.path.join(hdlsim_dir, "vcs_flow.dv"),
        'hdlsim.vlt': os.path.join(hdlsim_dir, "vlt_flow.dv"),
        'hdlsim.xcm': os.path.join(hdlsim_dir, "xcm_flow.dv"),
        'hdlsim.xsm': os.path.join(hdlsim_dir, "xsm_flow.dv"),
    }
