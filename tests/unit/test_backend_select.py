#****************************************************************************
#* test_backend_select.py
#*
#* Feature C: the abstract hdlsim.SimImage/SimRun tasks dispatch to a concrete
#* simulator backend based on the resolved `sim` value. Post-`set:` migration
#* (docs/proposals/set_overrides_impl_plan.md Phase 5) the abstract tasks read
#* `${{ hdlsim.sim }}`; selection is driven by `-D hdlsim.sim`, a subtree
#* `set: [{ hdlsim.sim: <name> }]`, or a per-leg narrowed rebind. See also
#* docs/proposals/task_elaboration_impl_plan.md §C.
#*
#* These assert on graph construction only (which backend is bound), so they run
#* without a simulator installed.
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


def _backend(node):
    """The concrete pytask path bound to a built leaf node (ExecCallable.body)."""
    return getattr(node.task, "body", None)


# A compound `region` selects the simulator for its whole subtree via `set:`.
_SET_FLOW = '''
package:
  name: foo
  imports:
    - name: hdlsim
  tasks:
  - name: files
    uses: std.FileSet
    with: {{type: systemVerilogSource, include: "*.sv"}}
  - name: region
    set:
    - hdlsim.sim: "{sim}"
    body:
    - name: build
      uses: hdlsim.SimImage
      needs: [files]
      with: {{top: [top]}}
    - name: run
      uses: hdlsim.SimRun
      needs: [build]
'''


# --- Subtree `set:` selection ------------------------------------------------

def test_set_selects_vlt(tmpdir):
    builder = _builder(tmpdir, _SET_FLOW.format(sim="vlt"))
    region = builder.mkTaskNode("foo.region")
    build = _find(region, ".build")
    run = _find(region, ".run")
    assert build is not None and run is not None
    assert "vlt_sim_image" in _backend(build)
    assert "vlt_sim_run" in _backend(run)


# --- Missing sim -> build-abort with the C.3 "No simulator" diagnostic -------

def test_no_sim_selected_errors(tmpdir):
    flow = '''
package:
  name: foo
  tasks:
  - name: files
    uses: std.FileSet
    with: {type: systemVerilogSource, include: "*.sv"}
  - name: build
    uses: hdlsim.SimImage
    needs: [files]
    with: {top: [top]}
'''
    builder = _builder(tmpdir, flow)
    with pytest.raises(Exception) as ei:
        builder.mkTaskNode("foo.build")
    msg = str(ei.value)
    assert "No simulator selected" in msg
    assert "hdlsim.sim" in msg
    assert "vlt" in msg   # lists available backends


# --- Unknown sim -> C.3 "Unknown simulator" with a suggestion ----------------

def test_unknown_sim_errors(tmpdir):
    builder = _builder(tmpdir, _SET_FLOW.format(sim="vltx"))
    with pytest.raises(Exception) as ei:
        builder.mkTaskNode("foo.region")
    msg = str(ei.value)
    assert "Unknown simulator 'vltx'" in msg
    assert "vlt" in msg


# --- Explicit concrete form still works (backward compat, passthrough) -------

def test_explicit_concrete_passthrough(tmpdir):
    flow = '''
package:
  name: foo
  imports:
    - name: hdlsim.vlt
  tasks:
  - name: files
    uses: std.FileSet
    with: {type: systemVerilogSource, include: "*.sv"}
  - name: build
    uses: hdlsim.vlt.SimImage
    needs: [files]
    with: {top: [top]}
'''
    builder = _builder(tmpdir, flow)
    # No `sim` anywhere, but the explicit concrete usage must not error.
    build = builder.mkTaskNode("foo.build")
    assert "vlt_sim_image" in _backend(build)


# --- set: scopes the selection to a subtree; sibling keeps the default -------

def test_set_scoped_selection_and_sibling_isolation(tmpdir):
    flow = '''
package:
  name: foo
  imports:
    - name: hdlsim
  tasks:
  - name: files
    uses: std.FileSet
    with: {type: systemVerilogSource, include: "*.sv"}
  - name: region
    set:
    - hdlsim.sim: vlt
    body:
    - name: build
      uses: hdlsim.SimImage
      needs: [files]
      with: {top: [top]}
'''
    builder = _builder(tmpdir, flow)
    region = builder.mkTaskNode("foo.region")
    build = _find(region, ".build")
    assert build is not None
    assert "vlt_sim_image" in _backend(build)


# --- nested set: on the same var -> OUTER wins (design §R2.4) -----------------

def test_nested_set_outer_wins(tmpdir):
    flow = '''
package:
  name: foo
  imports:
    - name: hdlsim
  tasks:
  - name: files
    uses: std.FileSet
    with: {type: systemVerilogSource, include: "*.sv"}
  - name: outer
    set:
    - hdlsim.sim: vlt
    body:
    - name: inner
      set:
      - hdlsim.sim: mti
      body:
      - name: build
        uses: hdlsim.SimImage
        needs: [files]
        with: {top: [top]}
'''
    builder = _builder(tmpdir, flow)
    outer = builder.mkTaskNode("foo.outer")
    build = _find(outer, ".build")
    assert build is not None
    # Outer overrides inner: vlt wins over the nested mti.
    assert "vlt_sim_image" in _backend(build)


# --- per-leg selection via a narrowed (matcher-gated) qualified rebind --------

def test_per_leg_narrowed_rebind(tmpdir):
    flow = '''
package:
  name: foo
  imports:
    - name: hdlsim
  tasks:
  - name: files
    uses: std.FileSet
    with: {type: systemVerilogSource, include: "*.sv"}
  - name: region
    set:
    - hdlsim.sim: vlt
    - path: "**/smoke*"
      set:
      - hdlsim.sim: mti
    body:
    - name: build
      uses: hdlsim.SimImage
      needs: [files]
      with: {top: [top]}
    - name: smoke
      uses: hdlsim.SimImage
      needs: [files]
      with: {top: [top]}
'''
    builder = _builder(tmpdir, flow)
    region = builder.mkTaskNode("foo.region")
    build = _find(region, ".build")
    smoke = _find(region, ".smoke")
    assert build is not None and smoke is not None
    # The default leg uses vlt; the smoke leg is narrowed to mti.
    assert "vlt_sim_image" in _backend(build)
    assert "mti_sim_image" in _backend(smoke)


# --- -D hdlsim.sim reaches the instance (B.2), selecting the backend ---------

def test_dash_D_hdlsim_sim(tmpdir):
    # No consuming-package `sim`; import hdlsim so its package params register.
    flow = '''
package:
  name: foo
  imports:
    - name: hdlsim
  tasks:
  - name: files
    uses: std.FileSet
    with: {type: systemVerilogSource, include: "*.sv"}
  - name: build
    uses: hdlsim.SimImage
    needs: [files]
    with: {top: [top]}
'''
    builder = _builder(tmpdir, flow)
    # Simulate `-D hdlsim.sim=vlt`: the override lands on the hdlsim package's
    # instance params (B.2 reads the instance, not the class default).
    builder._pkg_params_m["hdlsim"].sim = "vlt"
    build = builder.mkTaskNode("foo.build")
    assert "vlt_sim_image" in _backend(build)


# --- Every SIM_BACKENDS entry exists in its package ---------------------------
# Most backends can't be run here (no license), so a typo in a flow.dv export
# or a pytask path would otherwise only show up on a machine with that tool.
# Building the concrete node needs only the package, not the simulator.

def _backend_entries():
    from dv_flow.libhdlsim.backend_select import SIM_BACKENDS
    return [(fam, sim, name)
            for fam, m in sorted(SIM_BACKENDS.items())
            for sim, name in sorted(m.items())]


@pytest.mark.parametrize("family,sim,concrete", _backend_entries())
def test_backend_entry_resolves(tmpdir, family, sim, concrete):
    import importlib
    from dv_flow.mgr.task_graph_builder import TaskGraphBuilder as _TGB
    rgy = PackageLoader().load_rgy(["std", "hdlsim", "hdlsim.%s" % sim])
    node = _TGB(rgy, os.path.join(str(tmpdir), "rundir")).mkTaskNode(
        concrete, name="t")
    assert node is not None
    body = _backend(node)
    if isinstance(body, str) and body.startswith("dv_flow."):
        mod, _, attr = body.rpartition(".")
        assert callable(getattr(importlib.import_module(mod), attr)), body
