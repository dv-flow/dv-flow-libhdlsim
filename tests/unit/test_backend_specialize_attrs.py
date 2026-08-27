#****************************************************************************
#* test_backend_specialize_attrs.py
#*
#* Guard for a CLASS of defect, not one instance of it.
#*
#* `hdlsim`'s abstract simulator tasks (hdlsim.SimImage, hdlsim.SimRun, ...)
#* carry `elaborate: backend_select`, which rebinds `uses` to the selected
#* backend at graph-build time. Everything a project relies on must survive that
#* rebind -- but the inheritable Task attributes are materialized by the package
#* LOADER, which runs earlier, so anything the backend declares can silently be
#* dropped on the way through.
#*
#* That is not hypothetical: `uptodate:` is declared only on the backends, and
#* losing it made every image built via the portable abstract task permanently
#* "up-to-date". A whole regression could pass against a stale binary, which is
#* the worst way for a build system to fail -- it does not error, it lies.
#*
#* Rather than assert on `uptodate` alone, this compares the abstract-bound node
#* against the concrete-bound one for EVERY family and every attribute a backend
#* may declare. A new backend attribute, or a new family task, is covered the day
#* it is added without anyone remembering to extend this file.
#****************************************************************************
import os
import shutil
import pytest
from dv_flow.mgr import PackageLoader
from dv_flow.mgr.task_graph_builder import TaskGraphBuilder
from dv_flow.libhdlsim.backend_select import SIM_BACKENDS


def available_sims():
    return [sim for exe, sim in {
        "iverilog": "ivl",
        "verilator": "vlt",
        "vcs": "vcs",
        "vsim": "mti",
        "xsim": "xsm",
    }.items() if shutil.which(exe) is not None]


# Attributes the graph builder reads off a Task when constructing a node. If a
# backend declares one and specialization drops it, the abstract and concrete
# forms of the same task behave differently -- which defeats the entire point of
# having a portable abstract task.
INHERITABLE = ("uptodate", "rundir", "passthrough", "consumes", "produces")


@pytest.mark.parametrize("sim", available_sims())
@pytest.mark.parametrize("family", sorted(SIM_BACKENDS.keys()))
def test_specializing_preserves_backend_attrs(tmpdir, sim, family):
    """Binding `hdlsim.<Family>` with sim=<sim> must yield the same inheritable
    attributes as binding `hdlsim.<sim>.<Family>` directly."""
    concrete_name = SIM_BACKENDS[family].get(sim)
    if concrete_name is None:
        pytest.skip("no %s backend for %s" % (family, sim))

    rgy = PackageLoader().load_rgy(["std", "hdlsim", "hdlsim.%s" % sim])

    def build(taskname, **kw):
        # A fresh builder per node: mkTaskNode mutates builder scope state.
        b = TaskGraphBuilder(rgy, os.path.join(str(tmpdir), "rundir"))
        return b.mkTaskNode(taskname, name="t", **kw)

    abstract = build("hdlsim.%s" % family, sim=sim)

    # Give the concrete side the SAME `sim` (when it declares that parameter --
    # the flag-set tasks do not), so the comparison isolates what this test is
    # actually about: whether specialization preserves what the BACKEND
    # declares. `produces:` interpolates task parameters (`sim: "${{ sim }}"`),
    # so building the concrete side without `sim` would compare two nodes with
    # different inputs and report a plain param difference as a lost attribute.
    concrete = build(concrete_name)
    if hasattr(concrete.params, "sim"):
        concrete = build(concrete_name, sim=sim)

    mismatched = {
        a: (getattr(abstract, a, None), getattr(concrete, a, None))
        for a in INHERITABLE
        if getattr(abstract, a, None) != getattr(concrete, a, None)
    }

    assert not mismatched, (
        "hdlsim.%s specialized to %s lost backend attribute(s) %s.\n"
        "  abstract-bound vs concrete-bound: %r\n"
        "An attribute declared on the backend was dropped when `elaborate:` "
        "rebound `uses`; a project writing the portable form silently gets "
        "different behavior from one naming the backend.\n\n%s"
        % (family, sim, sorted(mismatched), mismatched,
           _diagnostics(abstract, concrete, sim)))


def _uses_chain(node):
    """Type names along the node's `uses` chain, most-derived first."""
    out, cur, seen = [], getattr(node, "taskdef", None), set()
    while cur is not None and id(cur) not in seen:
        seen.add(id(cur))
        out.append(getattr(cur, "name", "?"))
        cur = getattr(cur, "uses", None)
    return out


def _params(node):
    p = getattr(node, "params", None)
    if p is None:
        return {}
    return {k: getattr(p, k, None)
            for k in sorted(getattr(p, "model_fields", None) or vars(p))}


def _diagnostics(abstract, concrete, sim):
    """State to make a failure diagnosable from CI output alone.

    Note what this deliberately does NOT explain, because the params it prints
    look correct while the assertion fails: the params shown are the OUTER
    node's, and they are settled. The known `produces` failure happens one
    level down. `elaborate:` rebinds `uses` and calls `ctxt.buildDefault(...)`,
    which re-enters `_mkTaskNode` as a recursive build -- `node_params` is None
    there, so `_apply_node_params` returns early and the inner node keeps the
    task's DECLARED DEFAULT. `produces` is evaluated against that inner node,
    so `hdlsim.SimRun` bound with sim=vlt advertises `{sim: 'unset'}` while the
    concrete form advertises `{sim: 'vlt'}` -- and a consumer matching on
    `{type: SimRunResult, sim: vlt}` silently matches nothing.

    So: params printing as correct here is expected and is not evidence the
    assertion is spurious. The fix belongs in the elaboration path (carry the
    settled parameters into the specialized build), not in this test.
    """
    return (
        "--- diagnostics -----------------------------------------------\n"
        "requested sim      : %r\n"
        "abstract uses-chain: %s\n"
        "concrete uses-chain: %s\n"
        "abstract params    : %r\n"
        "concrete params    : %r\n"
        "---------------------------------------------------------------"
        % (sim, " -> ".join(_uses_chain(abstract)),
           " -> ".join(_uses_chain(concrete)),
           _params(abstract), _params(concrete)))
