#****************************************************************************
#* test_flags_select.py
#*
#* Per-sim opt/debug flag selection. The abstract hdlsim.SimCompArgsOpt /
#* SimCompArgsDbg / SimElabArgs{Opt,Dbg} / SimRunArgs{Opt,Dbg} tasks reuse the
#* backend_select elaborator: they read the resolved `sim` and rebind `uses` to
#* the concrete per-sim flag emitter `hdlsim.<sim>.<Family>`, which produces the
#* matching hdlsim.Sim*Args DataItem. Selection drives which concrete emitter is
#* bound; `sim` itself is consumed by selection and never appears on the emitted
#* item. See flow.dv and backend_select.py.
#*
#* These assert on graph construction only, so they run without a simulator.
#****************************************************************************
import os
import pytest
from dv_flow.mgr import PackageLoader, TaskGraphBuilder


def _builder(tmpdir, flow):
    d = str(tmpdir)
    with open(os.path.join(d, "flow.dv"), "w") as f:
        f.write(flow)
    loader = PackageLoader()
    pkg = loader.load(os.path.join(d, "flow.dv"))
    return TaskGraphBuilder(root_pkg=pkg, rundir=os.path.join(d, "rundir"),
                            loader=loader)


def _find(node, frag):
    if frag in node.name:
        return node
    for t in getattr(node, "tasks", []):
        r = _find(t, frag)
        if r is not None:
            return r
    return None


def _bound_type(node):
    """Name of the concrete flag task the built emitter node `uses` -- the
    observable of selection (both opt/dbg emit the same DataItem type)."""
    td = getattr(node, "taskdef", None)
    uses = getattr(td, "uses", None)
    return getattr(uses, "name", None)


# A compound `region` selects the simulator for its subtree via `set:`.
_FLOW = '''
package:
  name: foo
  imports:
    - name: hdlsim
  tasks:
  - name: region
    set:
    - hdlsim.sim: "{sim}"
    body:
    - name: flags
      uses: hdlsim.{fam}
'''


# --- selection: sim=vlt rebinds each family to its concrete emitter ----------

@pytest.mark.parametrize("fam", [
    "SimCompArgsOpt", "SimCompArgsDbg",
    "SimElabArgsOpt", "SimElabArgsDbg",
    "SimRunArgsOpt",  "SimRunArgsDbg",
])
def test_set_selects_vlt_flags(tmpdir, fam):
    builder = _builder(tmpdir, _FLOW.format(sim="vlt", fam=fam))
    region = builder.mkTaskNode("foo.region")
    flags = _find(region, ".flags")
    assert flags is not None
    assert _bound_type(flags) == "hdlsim.vlt.%s" % fam


# --- opt vs dbg are distinct families (debug config swaps one for the other) -

def test_opt_and_dbg_select_distinct_concretes(tmpdir):
    opt = _find(_builder(tmpdir, _FLOW.format(sim="vlt", fam="SimCompArgsOpt"))
                .mkTaskNode("foo.region"), ".flags")
    dbg = _find(_builder(tmpdir, _FLOW.format(sim="vlt", fam="SimCompArgsDbg"))
                .mkTaskNode("foo.region"), ".flags")
    assert _bound_type(opt) == "hdlsim.vlt.SimCompArgsOpt"
    assert _bound_type(dbg) == "hdlsim.vlt.SimCompArgsDbg"


# --- `sim` drives selection only: it is not forwarded onto the emitted item --

def test_sim_not_forwarded_to_emitted_item(tmpdir):
    builder = _builder(tmpdir, _FLOW.format(sim="vlt", fam="SimCompArgsOpt"))
    flags = _find(builder.mkTaskNode("foo.region"), ".flags")
    # Rebind (paramT=None) rebuilds params off the concrete SimCompileArgs
    # chain, which has no `sim` field -- but does carry the forwarded options.
    assert not hasattr(flags.params, "sim")
    assert hasattr(flags.params, "args")


# --- another backend selects its own concrete emitter ------------------------

def test_set_selects_mti_flags(tmpdir):
    builder = _builder(tmpdir, _FLOW.format(sim="mti", fam="SimElabArgsDbg"))
    flags = _find(builder.mkTaskNode("foo.region"), ".flags")
    assert _bound_type(flags) == "hdlsim.mti.SimElabArgsDbg"


# --- no sim selected -> the backend_select "No simulator" diagnostic ---------

def test_no_sim_selected_errors(tmpdir):
    flow = '''
package:
  name: foo
  imports:
    - name: hdlsim
  tasks:
  - name: flags
    uses: hdlsim.SimCompArgsOpt
'''
    builder = _builder(tmpdir, flow)
    with pytest.raises(Exception) as ei:
        builder.mkTaskNode("foo.flags")
    msg = str(ei.value)
    assert "No simulator selected" in msg
    assert "hdlsim.sim" in msg


# --- unknown sim -> "Unknown simulator" with a suggestion --------------------

def test_unknown_sim_errors(tmpdir):
    builder = _builder(tmpdir, _FLOW.format(sim="vltx", fam="SimCompArgsOpt"))
    with pytest.raises(Exception) as ei:
        builder.mkTaskNode("foo.region")
    msg = str(ei.value)
    assert "Unknown simulator 'vltx'" in msg
    assert "vlt" in msg


# --- explicit concrete form passes through (no selection, no sim needed) ------

def test_explicit_concrete_passthrough(tmpdir):
    flow = '''
package:
  name: foo
  imports:
    - name: hdlsim.vlt
  tasks:
  - name: flags
    uses: hdlsim.vlt.SimCompArgsOpt
'''
    builder = _builder(tmpdir, flow)
    # No `sim` anywhere, but the explicit concrete usage must not error.
    flags = builder.mkTaskNode("foo.flags")
    assert _bound_type(flags) == "hdlsim.vlt.SimCompArgsOpt"
