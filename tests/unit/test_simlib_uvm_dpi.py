"""SimLibUVM (vlt) DPI selection.

These run with no simulator installed: they drive the task function directly
against fixture UVM trees, so the logic is protected on every CI run.
"""
import asyncio
import os
import pytest
from types import SimpleNamespace

from dv_flow.libhdlsim.vlt_sim_lib_uvm import SimLibUVM


class FakeCtxt:
    """Minimal TaskRunCtxt stand-in: env, markers and mkDataItem."""

    def __init__(self, env):
        self.env = env
        self.markers = []

    def add_marker(self, marker):
        self.markers.append(marker)

    def mkDataItem(self, type, **kwargs):
        return SimpleNamespace(type=type, **kwargs)


def _mk_uvm(tmpdir, with_backend):
    """Build a fixture UVM tree, optionally carrying the Verilator backend."""
    uvm_home = os.path.join(str(tmpdir), "uvm")
    dpi = os.path.join(uvm_home, "src", "dpi")
    os.makedirs(dpi)
    open(os.path.join(uvm_home, "src", "uvm_pkg.sv"), "w").close()
    open(os.path.join(dpi, "uvm_dpi.cc"), "w").close()
    # Stock Accellera ships these; none of them is a Verilator backend.
    for f in ("uvm_hdl_vcs.c", "uvm_hdl_questa.c", "uvm_hdl_xcelium.c"):
        open(os.path.join(dpi, f), "w").close()
    if with_backend:
        open(os.path.join(dpi, "uvm_hdl_verilator.c"), "w").close()
    return uvm_home


def _run(uvm_home, dpi="auto"):
    ctxt = FakeCtxt({"UVM_HOME": uvm_home})
    input = SimpleNamespace(params=SimpleNamespace(dpi=dpi))
    result = asyncio.run(SimLibUVM(ctxt, input))
    return ctxt, result


def _sv_fileset(result):
    for o in result.output:
        if getattr(o, "filetype", None) == "systemVerilogSource":
            return o
    return None


def _by_filetype(result, filetype):
    return [o for o in result.output if getattr(o, "filetype", None) == filetype]


def test_dpi_used_when_backend_present(tmpdir):
    uvm_home = _mk_uvm(tmpdir, with_backend=True)
    ctxt, result = _run(uvm_home)

    assert result.status == 0

    # UVM_NO_DPI must NOT be forwarded -- that is the whole point.
    sv = _sv_fileset(result)
    assert sv is not None
    assert "UVM_NO_DPI" not in sv.defines

    # uvm_dpi.cc is handed to the image build...
    cpp = _by_filetype(result, "cppSource")
    assert len(cpp) == 1
    assert cpp[0].files == ["uvm_dpi.cc"]

    # ...along with a declared need for the VPI runtime.
    args = [o for o in result.output
            if getattr(o, "type", None) == "hdlsim.SimCompileArgs"]
    assert len(args) == 1
    assert args[0].vpi is True

    # public_flat_rw is NOT requested: it inhibits optimization design-wide
    # and most UVM testbenches never use register backdoor access.
    assert getattr(args[0], "public_flat_rw", False) is False

    assert ctxt.markers == []


def test_fallback_when_backend_missing(tmpdir):
    uvm_home = _mk_uvm(tmpdir, with_backend=False)
    ctxt, result = _run(uvm_home)

    assert result.status == 0

    sv = _sv_fileset(result)
    assert sv is not None
    assert "UVM_NO_DPI" in sv.defines

    assert _by_filetype(result, "cppSource") == []
    assert not [o for o in result.output
                if getattr(o, "type", None) == "hdlsim.SimCompileArgs"]

    # The degradation must be visible, not silent.
    assert len(ctxt.markers) == 1
    assert str(ctxt.markers[0].severity).lower().endswith("warning")
    assert "UVM_NO_DPI" in ctxt.markers[0].msg


def test_dpi_true_errors_when_backend_missing(tmpdir):
    uvm_home = _mk_uvm(tmpdir, with_backend=False)
    ctxt, result = _run(uvm_home, dpi="true")

    assert result.status == 1
    assert result.output == []
    assert len(ctxt.markers) == 1
    assert str(ctxt.markers[0].severity).lower().endswith("error")


def test_dpi_false_forces_no_dpi(tmpdir):
    """Escape hatch: force the fallback even where the backend exists."""
    uvm_home = _mk_uvm(tmpdir, with_backend=True)
    ctxt, result = _run(uvm_home, dpi="false")

    assert result.status == 0
    sv = _sv_fileset(result)
    assert "UVM_NO_DPI" in sv.defines
    assert _by_filetype(result, "cppSource") == []
    # Explicitly asked for, so no warning.
    assert ctxt.markers == []


def test_dpi_true_uses_dpi_when_available(tmpdir):
    uvm_home = _mk_uvm(tmpdir, with_backend=True)
    ctxt, result = _run(uvm_home, dpi="true")

    assert result.status == 0
    assert "UVM_NO_DPI" not in _sv_fileset(result).defines
    assert len(_by_filetype(result, "cppSource")) == 1


def test_invalid_dpi_value_errors(tmpdir):
    uvm_home = _mk_uvm(tmpdir, with_backend=True)
    ctxt, result = _run(uvm_home, dpi="maybe")

    assert result.status == 1
    assert len(ctxt.markers) == 1
    assert "invalid dpi" in ctxt.markers[0].msg


def test_dpi_cc_missing_is_not_capable(tmpdir):
    """The backend alone is not enough; uvm_dpi.cc must be there too."""
    uvm_home = _mk_uvm(tmpdir, with_backend=True)
    os.remove(os.path.join(uvm_home, "src", "dpi", "uvm_dpi.cc"))
    ctxt, result = _run(uvm_home)

    assert result.status == 0
    assert "UVM_NO_DPI" in _sv_fileset(result).defines
