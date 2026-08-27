
import os
import logging
import shlex
import shutil
from typing import List, Optional, Tuple

_log = logging.getLogger("libhdlsim.util")


def merge_tokenize(input : List[str]) -> List[str]:
    merged = []
    if type(input) == str:
        merged.extend(shlex.split(str(input)))
    else:
        for elem in input:
            merged.extend(shlex.split(elem))
    return merged


def xcelium_install_cds_lib() -> Optional[str]:
    """Return the path to the Xcelium install-default cds.lib, or None.

    Locates the install default by resolving `which xmvlog` and walking up the
    directory tree looking for `<tools>/xcelium/files/cds.lib` (or the legacy
    `<tools>/inca/files/cds.lib`). This is robust to the various ways xmvlog
    lands on PATH (`tools/bin`, `tools.lnx86/bin`, `.../bin/64bit`, symlinks).
    The default cds.lib provides the std/IEEE/std package library mappings.
    """
    xmvlog = shutil.which('xmvlog')
    if xmvlog is None:
        return None
    d = os.path.dirname(os.path.realpath(xmvlog))
    for _ in range(6):
        for rel in (("xcelium", "files", "cds.lib"), ("inca", "files", "cds.lib")):
            cand = os.path.join(d, *rel)
            if os.path.isfile(cand):
                return cand
        parent = os.path.dirname(d)
        if parent == d:
            break
        d = parent
    return None


def xcelium_cds_lib(defines : List[Tuple[str, str]]) -> str:
    """Build cds.lib content: SOFTINCLUDE the install default, then DEFINEs.

    `defines` is an ordered list of (logical_name, physical_path) pairs.
    """
    lines = []
    install = xcelium_install_cds_lib()
    if install is not None:
        lines.append("SOFTINCLUDE %s" % install)
    else:
        _log.warning("Xcelium install-default cds.lib not found; "
                     "std/IEEE package resolution may fail")
    for logical, path in defines:
        lines.append("DEFINE %s %s" % (logical, path))
    return "\n".join(lines) + "\n"

