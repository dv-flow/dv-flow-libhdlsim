"""SimLibUVM (xzm): UVM location and the `dpi` param.

Driven directly against fixture trees, so these run without xezim installed.
"""
import asyncio
import os
from types import SimpleNamespace

from dv_flow.libhdlsim import xzm_tool
from dv_flow.libhdlsim.xzm_sim_lib_uvm import SimLibUVM


class FakeCtxt:
    def __init__(self, env):
        self.env = env
        self.markers = []

    def add_marker(self, marker):
        self.markers.append(marker)


def _mk_prefix(tmpdir, with_uvm=True):
    prefix = os.path.join(str(tmpdir), "xezim")
    os.makedirs(os.path.join(prefix, "bin"))
    if with_uvm:
        os.makedirs(os.path.join(prefix, "share", "uvm", "src"))
    return prefix


def _run(env, dpi="auto"):
    ctxt = FakeCtxt(env)
    inp = SimpleNamespace(params=SimpleNamespace(dpi=dpi))
    return ctxt, asyncio.run(SimLibUVM(ctxt, inp))


def test_bundled_uvm(tmpdir, monkeypatch):
    prefix = _mk_prefix(tmpdir)
    monkeypatch.setattr(xzm_tool, "xezim_prefix", lambda env=None: prefix)
    ctxt, res = _run({})
    assert res.status == 0
    assert len(res.output) == 1
    fs = res.output[0]
    assert fs.filetype == "systemVerilogSource"
    assert fs.basedir == os.path.join(prefix, "share", "uvm")
    assert fs.files == ["src/uvm_pkg.sv"]
    assert fs.incdirs == ["src"]
    # UVM's DPI layer is built into xezim: nothing to compile, no UVM_NO_DPI.
    assert "UVM_NO_DPI" not in fs.defines
    assert ctxt.markers == []


def test_uvm_home_wins(tmpdir, monkeypatch):
    prefix = _mk_prefix(tmpdir)
    monkeypatch.setattr(xzm_tool, "xezim_prefix", lambda env=None: prefix)
    ctxt, res = _run({"UVM_HOME": "/opt/uvm"})
    assert res.status == 0
    assert res.output[0].basedir == "/opt/uvm"


def test_dpi_true_same_as_auto(tmpdir, monkeypatch):
    prefix = _mk_prefix(tmpdir)
    monkeypatch.setattr(xzm_tool, "xezim_prefix", lambda env=None: prefix)
    _, res = _run({}, dpi="true")
    assert res.status == 0
    assert "UVM_NO_DPI" not in res.output[0].defines


def test_dpi_false_defines_uvm_no_dpi(tmpdir, monkeypatch):
    prefix = _mk_prefix(tmpdir)
    monkeypatch.setattr(xzm_tool, "xezim_prefix", lambda env=None: prefix)
    ctxt, res = _run({}, dpi=False)
    assert res.status == 0
    assert "UVM_NO_DPI" in res.output[0].defines
    assert ctxt.markers == []


def test_invalid_dpi_value_errors(tmpdir, monkeypatch):
    monkeypatch.setattr(xzm_tool, "xezim_prefix", lambda env=None: _mk_prefix(tmpdir))
    ctxt, res = _run({}, dpi="maybe")
    assert res.status == 1
    assert "invalid dpi" in ctxt.markers[0].msg


def test_no_xezim_errors(monkeypatch):
    monkeypatch.setattr(xzm_tool, "xezim_prefix", lambda env=None: None)
    ctxt, res = _run({})
    assert res.status == 1
    assert res.output == []
    assert len(ctxt.markers) == 1
    assert "UVM not found" in ctxt.markers[0].msg


def test_prefix_without_uvm_errors(tmpdir, monkeypatch):
    prefix = _mk_prefix(tmpdir, with_uvm=False)
    monkeypatch.setattr(xzm_tool, "xezim_prefix", lambda env=None: prefix)
    ctxt, res = _run({})
    assert res.status == 1
    assert "UVM not found" in ctxt.markers[0].msg


def test_real_prefix_layout():
    """The installed xezim, when present, has the layout SimLibUVM expects."""
    import pytest
    prefix = xzm_tool.xezim_prefix()
    if prefix is None:
        pytest.skip("xezim not on PATH")
    assert os.path.isfile(os.path.join(prefix, "share", "uvm", "src", "uvm_pkg.sv"))
    assert os.path.isfile(os.path.join(prefix, "include", "svdpi.h"))
    assert xzm_tool.xezim_version().startswith("xezim version ")
