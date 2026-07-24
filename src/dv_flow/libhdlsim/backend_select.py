#****************************************************************************
#* backend_select.py
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
"""Simulator backend selection (Feature C).

The abstract `hdlsim.SimImage` / `SimRun` / ... tasks carry a `sim` parameter
(defaulted by an ordinary reference `${{ hdlsim.sim }}` to the `hdlsim.sim`
package variable) and declare an `elaborate:` clause pointing at the `elaborate`
function below. It reads the resolved `sim` and rebinds the task's `uses` to the
concrete simulator backend (`hdlsim.<sim>.SimImage`, ...), so a single
`-D hdlsim.sim=vlt` (or a subtree `set: [{ hdlsim.sim: vlt }]` override) selects
the simulator for a whole subtree while the flow author writes only the generic
`uses: hdlsim.SimImage`. The binding is declared on each abstract task in
`flow.dv` (`elaborate: dv_flow.libhdlsim.backend_select:elaborate`) and applies
along the `uses` chain.

The explicit form (`uses: hdlsim.vlt.SimImage`) still works: when a concrete
backend already appears in the task's `uses` chain, the elaborator passes the
build straight through. See docs/proposals/task_elaboration_impl_plan.md §C.
"""
import dataclasses as dc
import difflib


# All simulator sub-package leaf ids. Used to recognize an explicit concrete
# task (`hdlsim.<sim>.<Family>`) structurally, independent of whether that
# sim/family pair appears in the selection registry below.
SIMS = ("vlt", "vcs", "mti", "xsm", "xcm", "ivl")


# Single source of truth: task family -> {sim: concrete task type name}.
SIM_BACKENDS = {
    "SimImage": {
        "vlt": "hdlsim.vlt.SimImage",
        "vcs": "hdlsim.vcs.SimImage",
        "mti": "hdlsim.mti.SimImage",
        "xsm": "hdlsim.xsm.SimImage",
        "xcm": "hdlsim.xcm.SimImage",
        "ivl": "hdlsim.ivl.SimImage",
    },
    "SimRun": {
        "vlt": "hdlsim.vlt.SimRun",
        "vcs": "hdlsim.vcs.SimRun",
        "mti": "hdlsim.mti.SimRun",
        "xsm": "hdlsim.xsm.SimRun",
        "xcm": "hdlsim.xcm.SimRun",
        "ivl": "hdlsim.ivl.SimRun",
    },
    "SimLib": {
        "vlt": "hdlsim.vlt.SimLib",
        "vcs": "hdlsim.vcs.SimLib",
        "mti": "hdlsim.mti.SimLib",
        "xsm": "hdlsim.xsm.SimLib",
    },
    "SimLibUVM": {
        "vlt": "hdlsim.vlt.SimLibUVM",
        "vcs": "hdlsim.vcs.SimLibUVM",
        "mti": "hdlsim.mti.SimLibUVM",
        "xsm": "hdlsim.xsm.SimLibUVM",
    },
    # SimUVMCase = run-a-UVM-test-and-check in one leaf task (compact,
    # multi-instantiable). Verilator-first; other backends are a follow-up.
    "SimUVMCase": {
        "vlt": "hdlsim.vlt.SimUVMCase",
    },
}


# Per-sim opt/debug flag families. Structurally identical to the sim-task
# families above -- the same `elaborate` reads `sim` and rebinds `uses` to
# `hdlsim.<sim>.<Family>` -- but these concrete backends are pure DataItem
# emitters (`uses: hdlsim.Sim*Args`) carrying that simulator's default flag set
# for the mode. The abstract task declares only `sim`; args/incdirs/defines are
# inherited from the base Sim*Args type, so the concrete emitter's flags flow
# through and `sim` (selection-only) never appears in the emitted DataItem.
for _fam in ("SimCompArgsOpt", "SimCompArgsDbg",
             "SimElabArgsOpt", "SimElabArgsDbg",
             "SimRunArgsOpt", "SimRunArgsDbg"):
    SIM_BACKENDS[_fam] = {s: "hdlsim.%s.%s" % (s, _fam) for s in SIMS}
del _fam


def _family_of(task):
    """The abstract family (``SimImage`` / ``SimRun`` / ...) this task derives
    from, found by walking its `uses` chain most-derived first; ``None`` if the
    task is not a simulator task. Because the ``elaborate:`` clause is declared on
    each abstract family type, the family is simply the nearest chain type whose
    leaf name is a known family."""
    cur = task
    seen = set()
    while cur is not None and id(cur) not in seen:
        seen.add(id(cur))
        leaf = (getattr(cur, 'name', '') or '').rsplit('.', 1)[-1]
        if leaf in SIM_BACKENDS:
            return leaf
        cur = getattr(cur, 'uses', None)
    return None


def _chain_is_concrete(task, family):
    """True if a concrete backend already appears in the task's own type or its
    `uses` chain -- the user selected a simulator explicitly (e.g.
    `uses: hdlsim.vlt.SimImage`), so we build as-is. Recognized structurally as
    any `hdlsim.<sim>.<family>`.

    Matching is on the trailing `<sim>.<family>` LEAF, not the fully-qualified
    name: under a `uses:`-based package-inheritance chain the concrete backend
    is re-exposed under alias-qualified names (e.g. `<pkg>.hdlsim.<sim>.<family>`
    or a subtree-scoped name), so a full-name match would miss it -- and, since
    the concrete backend `uses:` the abstract type (which carries this
    `elaborate:` clause), missing it re-fires the elaborator forever. `_family_of`
    already matches on the leaf for the same reason."""
    cur = task
    seen = set()
    while cur is not None and id(cur) not in seen:
        seen.add(id(cur))
        nm = getattr(cur, 'name', None)
        if nm:
            parts = nm.split('.')
            # trailing two segments are `<sim>.<family>`
            if len(parts) >= 2 and parts[-1] == family and parts[-2] in SIMS:
                return True
        cur = getattr(cur, 'uses', None)
    return False


def elaborate(ctxt, task, name):
    """`elaborate:` clause for the abstract hdlsim sim tasks: read the resolved
    `sim` and rebind `uses` to the concrete simulator backend. Declared on each
    abstract family task in ``flow.dv`` as
    ``elaborate: dv_flow.libhdlsim.backend_select:elaborate`` and bound along the
    `uses` chain, so any task using an abstract family inherits it."""
    family = _family_of(task)
    if family is None:
        # Not a simulator task (shouldn't happen given the binding) -> default.
        return ctxt.buildDefault(task, name)
    backends = SIM_BACKENDS[family]

    # Explicit concrete usage (hdlsim.vlt.SimImage) -> build unchanged.
    if _chain_is_concrete(task, family):
        return ctxt.buildDefault(task, name)

    sim = ctxt.resolveParam(task, 'sim', 'unset')
    avail = ", ".join(sorted(backends.keys()))

    if sim is None or sim == 'unset' or sim == '':
        msg = ("No simulator selected for '%s'. Set it with "
               "`-D hdlsim.sim=<name>`, a subtree "
               "`set: [{ hdlsim.sim: <name> }]` override, or "
               "`with: { sim: <name> }`. Available: %s." % (name, avail))
        ctxt.error(msg)
        raise Exception(msg)

    if sim not in backends:
        hint = ""
        near = difflib.get_close_matches(sim, list(backends.keys()), n=1)
        if near:
            hint = " Did you mean '%s'?" % near[0]
        msg = ("Unknown simulator '%s' for '%s'. Available: %s.%s"
               % (sim, name, avail, hint))
        ctxt.error(msg)
        raise Exception(msg)

    backend_name = backends[sim]
    concrete = ctxt.getTask(backend_name)
    if concrete is None:
        msg = ("Simulator '%s' selected for '%s', but its backend task '%s' "
               "is not available. Ensure the '%s' package is importable."
               % (sim, name, backend_name, backend_name.rsplit('.', 1)[0]))
        ctxt.error(msg)
        raise Exception(msg)

    # Rebind `uses` to the concrete backend and build the standard interior.
    # paramT is reset so it rebuilds against the new (concrete) uses chain;
    # the re-entrancy guard keeps this from re-firing the elaborator.
    variant = dc.replace(task, uses=concrete, paramT=None)
    return ctxt.buildDefault(variant, name)
