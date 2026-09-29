#****************************************************************************
#* sims.py
#*
#* The one list of simulators the tests know about. Parametrized tests call
#* get_available_sims() so a new backend is added here once, not in every
#* test module.
#****************************************************************************
import shutil

# Executable probed on PATH -> hdlsim sim id
SIM_EXES = {
    "iverilog": "ivl",
    "verilator": "vlt",
    "vcs": "vcs",
    "vsim": "mti",
    "xsim": "xsm",
    "xmvlog": "xcm",
}

# Sims whose backend provides SimLibUVM/SimUVMCase
UVM_SIMS = ("vlt", "vcs", "mti", "xcm", "xsm", "xzm")


def get_available_sims(only=None, exclude=(), uvm=False):
    """Sim ids whose executable is on PATH.

    only    -- restrict to these ids
    exclude -- drop these ids (e.g. a feature a backend doesn't support)
    uvm     -- restrict to UVM-capable ids
    """
    sims = []
    for exe, sim in SIM_EXES.items():
        if only is not None and sim not in only:
            continue
        if sim in exclude:
            continue
        if uvm and sim not in UVM_SIMS:
            continue
        if shutil.which(exe) is not None:
            sims.append(sim)
    return sims
