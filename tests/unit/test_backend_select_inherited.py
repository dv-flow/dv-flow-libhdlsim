#****************************************************************************
#* test_backend_select_inherited.py
#*
#* Backend selection when the abstract hdlsim task is reached through the
#* project's own tasks (`image uses base uses hdlsim.SimImage`).
#*
#* The elaborator fires on `image`, but the configuration lives on `base`. It
#* used to specialize by replacing `image.uses` -- splicing `base` out of the
#* chain, so `base`'s `with:` and `needs:` vanished after `sim` had already been
#* read from them. The right backend was chosen and then built with no top, no
#* defines and no sources. These tests pin the three ways to reach a backend to
#* the same result, and cover the neighbors of that fix: implementation
#* borrowing, selection mechanisms, other families, and the inheritable
#* attributes the project may itself declare.
#*
#* Graph construction only; no simulator is needed.
#****************************************************************************
import os
import pytest
from dv_flow.mgr import PackageLoader, TaskGraphBuilder
from dv_flow.libhdlsim.backend_select import SIM_BACKENDS


SIMS = sorted(SIM_BACKENDS["SimImage"].keys())
INHERITABLE = ("uptodate", "rundir", "passthrough", "consumes", "produces")

_HEADER = '''
package:
  name: probe
  imports:
  - name: hdlsim
  tasks:
  - name: sources
    uses: std.FileSet
    with: {type: systemVerilogSource, include: "*.sv"}
  - name: more_sources
    uses: std.FileSet
    with: {type: systemVerilogSource, include: "*.svh"}
'''


def _builder(tmpdir, tasks, rundir=None):
    d = str(tmpdir)
    with open(os.path.join(d, "flow.dv"), "w") as f:
        f.write(_HEADER + tasks)
    loader = PackageLoader()
    pkg = loader.load(os.path.join(d, "flow.dv"))
    return TaskGraphBuilder(root_pkg=pkg,
                            rundir=rundir or os.path.join(d, "rundir"),
                            loader=loader)


def _body(node):
    return getattr(node.task, "body", None) or ""


def _needs(node):
    return sorted(n.name for n, _ in node.needs)


# --- The reported bug: three spellings, one result ----------------------------

_CASES = {
    # with: on the leaf, generic family
    "direct_generic": '''
  - name: image
    uses: hdlsim.SimImage
    needs: [sources]
    with: {{sim: {sim}, top: [sentinel_top], defines: [SENTINEL]}}
''',
    # project task names the backend
    "inherited_concrete": '''
  - name: base
    uses: hdlsim.{sim}.SimImage
    with: {{top: [sentinel_top], defines: [SENTINEL]}}
  - name: image
    needs: [sources]
    uses: base
''',
    # project task uses the generic family -- the failing case
    "inherited_generic": '''
  - name: base
    uses: hdlsim.SimImage
    with: {{sim: {sim}, top: [sentinel_top], defines: [SENTINEL]}}
  - name: image
    needs: [sources]
    uses: base
''',
}


@pytest.mark.parametrize("sim", SIMS)
@pytest.mark.parametrize("case", sorted(_CASES))
def test_three_spellings_agree(tmpdir, case, sim):
    b = _builder(tmpdir, _CASES[case].format(sim=sim))
    node = b.mkTaskNode("probe.image")
    assert "%s_sim_image" % sim in _body(node)
    assert node.params.top == ["sentinel_top"]
    assert node.params.defines == ["SENTINEL"]
    assert _needs(node) == ["probe.sources"]
    # `sim` is selection-only: nothing sets it when the backend is named.
    assert node.params.sim == ("unset" if case == "inherited_concrete" else sim)


def test_inherited_generic_no_stray_base_node(tmpdir):
    """Specializing `image` must not build `probe.base` as a side effect (the
    implementation used to be borrowed from the base by name)."""
    b = _builder(tmpdir, _CASES["inherited_generic"].format(sim="vlt"))
    b.mkTaskNode("probe.image")
    assert "probe.base" not in b._task_node_m


# --- needs ------------------------------------------------------------------

def test_needs_on_intermediate_survive(tmpdir):
    b = _builder(tmpdir, '''
  - name: base
    uses: hdlsim.SimImage
    needs: [sources]
    with: {sim: vlt, top: [t]}
  - name: image
    uses: base
    needs: [more_sources]
''')
    node = b.mkTaskNode("probe.image")
    assert "vlt_sim_image" in _body(node)
    assert _needs(node) == ["probe.more_sources", "probe.sources"]


# --- selection precedence and implementation borrowing -------------------------

@pytest.mark.parametrize("base_sim,leaf_sim", [("xcm", "vlt"), ("vlt", "xcm")])
def test_leaf_overrides_intermediate_sim(tmpdir, base_sim, leaf_sim):
    """Leaf `with: {sim}` beats the intermediate's. The BODY must follow the
    leaf too: a body borrowed from `base` by name would be base's backend."""
    b = _builder(tmpdir, '''
  - name: base
    uses: hdlsim.SimImage
    with: {sim: %s, top: [t], defines: [D]}
  - name: image
    uses: base
    with: {sim: %s}
''' % (base_sim, leaf_sim))
    node = b.mkTaskNode("probe.image")
    assert "%s_sim_image" % leaf_sim in _body(node)
    assert node.params.sim == leaf_sim
    assert node.params.top == ["t"] and node.params.defines == ["D"]


def test_shared_intermediate_two_sims(tmpdir):
    """One `base`, two consumers selecting different sims. Each gets its own
    backend, and `base` itself is left as declared."""
    b = _builder(tmpdir, '''
  - name: base
    uses: hdlsim.SimImage
    needs: [sources]
    with: {top: [t]}
  - name: img_vlt
    uses: base
    with: {sim: vlt}
  - name: img_xcm
    uses: base
    with: {sim: xcm}
''')
    base = b.lookupTask("probe.base")
    abstract = base.uses
    v = b.mkTaskNode("probe.img_vlt")
    x = b.mkTaskNode("probe.img_xcm")
    assert "vlt_sim_image" in _body(v) and "xcm_sim_image" in _body(x)
    assert v.params.top == x.params.top == ["t"]
    assert _needs(v) == _needs(x) == ["probe.sources"]
    assert base.uses is abstract


def test_dash_D_selects_through_intermediate(tmpdir):
    b = _builder(tmpdir, '''
  - name: base
    uses: hdlsim.SimImage
    with: {top: [sentinel_top], defines: [SENTINEL]}
  - name: image
    uses: base
    needs: [sources]
''')
    # Simulate `-D hdlsim.sim=xcm` (see test_backend_select.test_dash_D_hdlsim_sim)
    b._pkg_params_m["hdlsim"].sim = "xcm"
    node = b.mkTaskNode("probe.image")
    assert "xcm_sim_image" in _body(node)
    assert node.params.top == ["sentinel_top"]
    assert node.params.defines == ["SENTINEL"]


def test_set_selects_through_intermediate(tmpdir):
    b = _builder(tmpdir, '''
  - name: base
    uses: hdlsim.SimImage
    needs: [sources]
    with: {top: [sentinel_top], defines: [SENTINEL]}
  - name: region
    set:
    - hdlsim.sim: "vlt"
    body:
    - name: image
      uses: base
''')
    region = b.mkTaskNode("probe.region")
    image = [t for t in region.tasks if t.name.endswith(".image")]
    assert len(image) == 1
    image = image[0]
    assert "vlt_sim_image" in _body(image)
    assert image.params.top == ["sentinel_top"]
    assert image.params.defines == ["SENTINEL"]
    assert "probe.sources" in _needs(image)     # plus the region's input


def test_project_task_named_like_family(tmpdir):
    """A project task whose leaf name is a family name must not be mistaken for
    the family link (it does not carry the `elaborate:` clause)."""
    b = _builder(tmpdir, '''
  - name: SimImage
    uses: hdlsim.SimImage
    needs: [sources]
    with: {sim: vlt, top: [t]}
''')
    node = b.mkTaskNode("probe.SimImage")
    assert "vlt_sim_image" in _body(node)
    assert node.params.top == ["t"]


# --- other families -----------------------------------------------------------

def test_simrun_through_intermediate(tmpdir):
    b = _builder(tmpdir, '''
  - name: image
    uses: hdlsim.SimImage
    needs: [sources]
    with: {sim: vlt, top: [t]}
  - name: run_base
    uses: hdlsim.SimRun
    needs: [image]
    with: {sim: vlt, plusargs: [SENTINEL_ARG]}
  - name: run
    uses: run_base
''')
    node = b.mkTaskNode("probe.run")
    assert "vlt_sim_run" in _body(node)
    assert node.params.plusargs == ["SENTINEL_ARG"]
    assert _needs(node) == ["probe.image"]


# --- inheritable attributes ---------------------------------------------------

@pytest.mark.parametrize("sim", ["vlt", "xcm"])
@pytest.mark.parametrize("family", sorted(SIM_BACKENDS.keys()))
def test_specialize_attrs_through_intermediate(tmpdir, sim, family):
    """Reached through a project task, the abstract family yields the same
    inheritable attributes as naming the backend directly."""
    concrete_name = SIM_BACKENDS[family].get(sim)
    if concrete_name is None:
        pytest.skip("no %s backend for %s" % (family, sim))
    tasks = '''
  - name: mid
    uses: hdlsim.%s
  - name: leaf
    uses: mid
''' % family

    def build(taskname, select=None, **kw):
        # A fresh builder per node (mkTaskNode mutates builder scope state),
        # all sharing one rundir so the resolved node rundirs compare equal.
        sub = tmpdir.mkdir(taskname.replace(".", "_") + "_%d" % len(kw))
        b = _builder(sub, tasks, rundir=os.path.join(str(tmpdir), "rundir"))
        if select is not None:
            b._pkg_params_m["hdlsim"].sim = select     # == -D hdlsim.sim=<sim>
        return b.mkTaskNode(taskname, name="t", **kw)

    # Select with the package variable, as a project would: the flag-set
    # families' rebound chain deliberately has no `sim` field to pass a kwarg to.
    abstract = build("probe.leaf", select=sim)
    concrete = build(concrete_name)
    if hasattr(concrete.params, "sim"):
        concrete = build(concrete_name, sim=sim)
    mismatched = {a: (getattr(abstract, a, None), getattr(concrete, a, None))
                  for a in INHERITABLE
                  if getattr(abstract, a, None) != getattr(concrete, a, None)}
    assert not mismatched


_UPTODATE_FALSE = {
    "direct": '''
  - name: image
    uses: hdlsim.SimImage
    uptodate: false
    with: {sim: vlt, top: [t]}
''',
    "concrete": '''
  - name: image
    uses: hdlsim.vlt.SimImage
    uptodate: false
    with: {top: [t]}
''',
    "on_intermediate": '''
  - name: base
    uses: hdlsim.SimImage
    uptodate: false
    with: {sim: vlt, top: [t]}
  - name: image
    uses: base
''',
}


@pytest.mark.parametrize("case", sorted(_UPTODATE_FALSE))
def test_project_uptodate_beats_backend(tmpdir, case):
    """A project's own `uptodate:` is nearer than the backend's. The generic
    form used to overwrite it with the backend's checker, unlike the explicit
    form -- so `uptodate: false` (always rebuild) was silently ignored."""
    node = _builder(tmpdir, _UPTODATE_FALSE[case]).mkTaskNode("probe.image")
    assert node.uptodate is False
    assert "vlt_sim_image" in _body(node)


def test_backend_uptodate_through_intermediate(tmpdir):
    """With no project value, the backend's `uptodate:` still applies."""
    b = _builder(tmpdir, '''
  - name: base
    uses: hdlsim.SimImage
    with: {sim: vlt, top: [t]}
  - name: image
    uses: base
''')
    direct = _builder(tmpdir.mkdir("d"), '''
  - name: image
    uses: hdlsim.vlt.SimImage
    with: {top: [t]}
''')
    assert b.mkTaskNode("probe.image").uptodate == \
        direct.mkTaskNode("probe.image").uptodate is not None


@pytest.mark.parametrize("via_base", [False, True])
def test_project_passthrough_beats_backend(tmpdir, via_base):
    """vlt's SimLib is `passthrough: all`; a project that says otherwise wins,
    with or without a task in between."""
    tasks = '''
  - name: base
    uses: hdlsim.SimLib
    passthrough: none
    with: {sim: vlt}
  - name: lib
    uses: base
''' if via_base else '''
  - name: lib
    uses: hdlsim.SimLib
    passthrough: none
    with: {sim: vlt}
'''
    node = _builder(tmpdir, tasks).mkTaskNode("probe.lib")
    assert str(node.passthrough).endswith(".No")


def test_backend_passthrough_through_intermediate(tmpdir):
    b = _builder(tmpdir, '''
  - name: base
    uses: hdlsim.SimLib
    with: {sim: vlt}
  - name: lib
    uses: base
''')
    assert str(b.mkTaskNode("probe.lib").passthrough).endswith(".All")
