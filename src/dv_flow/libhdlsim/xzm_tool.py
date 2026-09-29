#****************************************************************************
#* xzm_tool.py
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
"""Locating the xezim installation the xzm tasks use."""
import os
import shutil
import subprocess
from typing import Dict, Optional

# `xezim -V` per executable path. The version is checked on every uptodate
# check, so don't spawn a process each time.
_version_cache : Dict[str, str] = {}


def xezim_exe(env : Optional[Dict[str, str]] = None) -> Optional[str]:
    """Absolute path of the `xezim` on PATH (the task env's PATH, if given)."""
    path = env.get("PATH") if env is not None else None
    return shutil.which("xezim", path=path)


def xezim_prefix(env : Optional[Dict[str, str]] = None) -> Optional[str]:
    """Installation prefix: the directory holding bin/xezim, include/ and
    share/uvm. None if xezim is not on PATH."""
    exe = xezim_exe(env)
    if exe is None:
        return None
    return os.path.dirname(os.path.dirname(os.path.realpath(exe)))


def xezim_version(env : Optional[Dict[str, str]] = None) -> Optional[str]:
    """Version and build of the xezim on PATH, eg
    'xezim version 0.11.0; git 6558a1e6 (2026-09-26T20:11:53-07:00)'.

    The git line is included: a rebuild with elaboration fixes keeps the
    artifact format (and so loads an old artifact silently) but changes it.
    """
    exe = xezim_exe(env)
    if exe is None:
        return None
    exe = os.path.realpath(exe)
    if exe not in _version_cache:
        try:
            out = subprocess.run([exe, "-V"], capture_output=True, text=True,
                                 timeout=60).stdout
        except Exception:
            return None
        lines = [l.strip() for l in out.splitlines() if l.strip()]
        _version_cache[exe] = "; ".join(lines[:2])
    return _version_cache[exe]
