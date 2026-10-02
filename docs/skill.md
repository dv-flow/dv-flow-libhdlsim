---
name: hdl-simulation
description: Configure and run HDL simulations with various simulators using the hdlsim DFM package. Use when working with SimImage, SimRun, SimLib, or simulator-specific tasks.
---

# HDL Simulation Package (hdlsim)

The hdlsim package provides tasks for compiling and running HDL simulations
with various commercial and open-source simulators. It defines abstract
tasks (SimImage, SimRun, SimLib, etc.) that each simulator package implements.

## Supported Simulators

| Package | Simulator | License |
|---------|-----------|---------|
| `hdlsim.vlt` | Verilator | Open Source |
| `hdlsim.vcs` | Synopsys VCS | Commercial |
| `hdlsim.xcm` | Cadence Xcelium | Commercial |
| `hdlsim.mti` | Siemens Questa | Commercial |
| `hdlsim.ivl` | Icarus Verilog | Open Source |
| `hdlsim.xsm` | AMD Xilinx XSim | Commercial |
| `hdlsim.xzm` | xezim | Open Source |

## Quick Start

```yaml
package:
  name: my_sim

  imports:
    - name: hdlsim.vlt   # Or hdlsim.vcs, hdlsim.xsm, hdlsim.mti, hdlsim.xzm
      as: sim

  tasks:
    - name: rtl
      uses: std.FileSet
      with:
        type: systemVerilogSource
        include: "src/**/*.sv"

    - root: build
      uses: sim.SimImage
      needs: [rtl]
      with:
        top: [my_top]

    - root: run
      uses: sim.SimRun
      needs: [build]
```

Run:

```bash
dfm run build          # Compile
dfm run run            # Compile + simulate
dfm run run -c vcs     # Use VCS config (see multi-simulator below)
```

## Core Tasks

### SimImage

Compiles HDL sources into a simulation executable.

| Parameter | Type | Description |
|-----------|------|-------------|
| `top` | list | Top-level module name(s) |
| `args` | list | Additional compiler/elaborator arguments |
| `compargs` | list | Compilation-specific arguments |
| `elabargs` | list | Elaboration-specific arguments |
| `trace` | bool | Enable waveform tracing |
| `timing` | bool | Enable timing simulation (default: true) |
| `dpilibs` | list | DPI libraries to link |
| `vpilibs` | list | VPI libraries to link |
| `incdirs` | list | Include directories |
| `defines` | list | Preprocessor defines |
| `suppress_warnings` | list | Warning codes to suppress from markers |
| `cov` | str | Coverage level: none (default), func, code, full |

Consumes: systemVerilogSource, verilogSource, verilogIncDir,
systemVerilogInclude, simLib, cSource, cppSource, systemVerilogDPI,
verilogVPI, verilogPLI, SimCompileArgs, SimElabArgs, SimCovArgs, SuppressWarnings

### SimRun

Executes a compiled simulation.

| Parameter | Type | Description |
|-----------|------|-------------|
| `args` | list | Runtime arguments |
| `plusargs` | list | Simulation plusargs (e.g., UVM_TESTNAME=test) |
| `dpilibs` | list | DPI libraries to load at runtime |
| `vpilibs` | list | VPI libraries to load at runtime |
| `trace` | bool | Enable runtime tracing |
| `valgrind` | bool | Run under valgrind |

Consumes: simDir, systemVerilogDPI, verilogVPI, verilogPLI, simRunData, SimRunArgs

SimRun has `uptodate: false` -- it always re-executes.

### SimLib

Creates a pre-compiled simulation library. Useful for large designs with
shared libraries to improve compilation time.

| Parameter | Type | Description |
|-----------|------|-------------|
| `libname` | str | Name of the library |
| `args` | list | Additional compiler arguments |
| `incdirs` | list | Include directories |
| `defines` | list | Preprocessor defines |
| `propagate_incdirs` | bool | Propagate include dirs to consumers (default: true) |
| `suppress_warnings` | list | Warning codes to suppress from markers |

### SimPLI

Attaches an already-built PLI 1.0 shared library (and, optionally, its
VCS-format `.tab` file) to a simulation. It compiles nothing. Put it in
SimImage's `needs`, not SimRun's.

| Parameter | Type | Description |
|-----------|------|-------------|
| `lib` | str | Shared library path (relative to the flow). Empty: use consumed `sharedLib` FileSets |
| `tab` | str | PLI 1.0 table file (VCS `.tab` format) |
| `boot` | str | Boot routine: returns the `s_tfcell` table (PLI 1.0), or the VPI startup routine |
| `interface` | str | `pli1` (default) or `vpi` (emits a `verilogVPI` FileSet) |
| `access` | bool | Grant design visibility to the library (default: true) |

```yaml
- name: novas
  uses: hdlsim.SimPLI
  with:
    lib: /tools/verdi/share/PLI/VCS/LINUX64/libnovas.so
    tab: /tools/verdi/share/PLI/VCS/LINUX64/novas.tab
- name: build
  uses: hdlsim.SimImage
  needs: [rtl, tb, novas]
```

| sim | PLI 1.0 needs | Flags |
|-----|---------------|-------|
| xcm | `boot` or `tab` | `xmelab -loadpli1 lib:boot`; `xmsim -loadpli1 lib:boot [-plimapfile tab]` |
| mti | nothing (veriusertfs), or `tab` | `vsim -pli lib [-tab tab]` |
| vcs | `tab` | `vcs -P tab lib` (linked into simv) |
| ivl | `boot`, no `tab` | `vvp -mcadpli ... -cadpli=lib:boot` |
| vlt, xsm, xzm | not supported | Error marker |

### SimLibUVM

Provides UVM library support for the target simulator. Each simulator
package implements this with the appropriate UVM paths and settings.

```yaml
tasks:
  - name: uvm
    uses: sim.SimLibUVM

  - name: build
    uses: sim.SimImage
    needs: [rtl, uvm, tb]
    with:
      top: [tb_top]
```

### SimLibDPI

Compiles C/C++ sources into a DPI library.

### SimLibVPI

Compiles C/C++ sources into a VPI library.

## Data Types

### SimCompileArgs

Additional compilation arguments injected via dataflow. Use when adding
compile flags from configs or separate tasks.

| Parameter | Type | Description |
|-----------|------|-------------|
| `args` | list | Compiler arguments |
| `incdirs` | list | Include directories |
| `defines` | list | Preprocessor defines |

### SimElabArgs

Additional elaboration arguments. Separates elaboration-phase flags from
compilation-phase flags.

| Parameter | Type | Description |
|-----------|------|-------------|
| `args` | list | Elaboration arguments |
| `dpilibs` | list | DPI libraries to link |
| `vpilibs` | list | VPI libraries to link |

### SimRunArgs

Additional runtime arguments for SimRun.

| Parameter | Type | Description |
|-----------|------|-------------|
| `args` | list | Runtime arguments |
| `plusargs` | list | Simulation plusargs |
| `dpilibs` | list | DPI libraries to load |
| `vpilibs` | list | VPI libraries to load |

### SimCovArgs

Requests coverage collection. SimImage builds at the highest level among its
`cov` param and every SimCovArgs it consumes; SimRun follows the image.

| Parameter | Type | Description |
|-----------|------|-------------|
| `level` | str | none, func, code or full (cumulative). Defaults to `${{ hdlsim.cov }}` |

### SuppressWarnings

Carries a list of warning codes to suppress as markers. Connect to
SimImage or SimLib via `needs` or `feeds`.

| Parameter | Type | Description |
|-----------|------|-------------|
| `codes` | list | Warning codes to suppress (e.g., TFIPC, vlog-2623) |

#### Direct usage

```yaml
- name: build
  uses: sim.SimImage
  needs: [rtl, tb]
  with:
    top: [tb_top]
    suppress_warnings: [TFIPC, MAXX]
```

#### Shared dataset

```yaml
- name: suppress
  uses: hdlsim.SuppressWarnings
  with:
    codes: [TFIPC, MAXX]

- name: build
  uses: sim.SimImage
  needs: [rtl, tb, suppress]
  with:
    top: [tb_top]
```

#### Via feeds in a config

```yaml
configs:
  - name: suppress_noisy
    tasks:
      - name: suppress
        uses: hdlsim.SuppressWarnings
        with:
          codes: [TFIPC, MAXX]
        feeds: [my_project.build]
```

## Using feeds in Configs

The `feeds` field injects data into a task without modifying its
definition. This is the recommended way to add simulator arguments from
configs.

```yaml
package:
  name: my_project

  tasks:
    - root: build
      uses: sim.SimImage
      needs: [rtl, tb]
      with:
        top: [tb_top]

    - root: run
      uses: sim.SimRun
      needs: [build]

  configs:
    - name: debug
      tasks:
        # Compilation-phase flags
        - name: debug_compile_args
          uses: hdlsim.SimCompileArgs
          with:
            args: ["-debug_access+all"]
          feeds: [my_project.build]

        # Elaboration-phase flags
        - name: debug_elab_args
          uses: hdlsim.SimElabArgs
          with:
            args: ["-debug_access+all"]
          feeds: [my_project.build]

        # Runtime flags
        - name: debug_run_args
          uses: hdlsim.SimRunArgs
          with:
            args: ["-gui"]
          feeds: [my_project.run]

        # Copy data files to the test rundir at runtime
        - name: debug_scripts
          uses: std.FileSet
          with:
            type: simRunData
            include: "dump.tcl"
          feeds: [my_project.run]
```

Usage: `dfm run run -c debug`

Key points:
- `SimCompileArgs` for compilation-phase flags
- `SimElabArgs` for elaboration-phase flags
- `SimRunArgs` for runtime flags
- `std.FileSet` with `type: simRunData` to copy files into the test rundir
- Feed targets use fully-qualified names (`package.task`)

## Collecting Coverage

Levels are cumulative: `func` = covergroups and `cover property`; `code` adds
line/statement, branch (and expression on Verilator); `full` adds toggle (and
FSM on Verilator). Supported on `vlt` and `xzm`; other simulators warn and
build without coverage.

Wire a bare `SimCovArgs` into the image and pick the level on the command line:

```yaml
tasks:
  - name: cov
    uses: hdlsim.SimCovArgs      # level follows hdlsim.cov (default none)
  - name: build
    uses: hdlsim.SimImage
    needs: [rtl, tb, cov]
    with: { top: [tb_top] }
```

```bash
dfm run tests -D hdlsim.sim=vlt -D hdlsim.cov=code
```

Or fix the level in a holder (`with: { level: code }`), or on SimImage
(`with: { cov: code }`).

Results:
- `SimRunResult.artifacts` has a `simCovDb` FileSet with `role=cov` and
  `format=vlt-dat` (Verilator `coverage.dat`) or `format=xezim-json`
  (`xezim_cov.json`). Choose a decoder by `format=`.
- `stats` has `cov_<kind>_pct/_covered/_total` for each kind measured;
  `runinfo.cov` is `{level, kinds}`.
- `SimSuiteReport` gives `cov_<kind>_pct_max` (best case, not merged).
- xezim reports no functional percentage (database only). On Verilator,
  `cg.get_coverage()` returns 0.
- UVM is instrumented along with the design on both simulators, so `code`
  percentages on a UVM bench mostly measure UVM. On xezim, run `args:
  [--code-coverage-scope, <dut-instance>]` narrows it.

## Selecting a Simulator (abstract tasks)

Write the generic tasks `uses: hdlsim.SimImage` / `hdlsim.SimRun` (no simulator
in the name) and pick the backend separately. The abstract tasks read
`${{ hdlsim.sim }}`, so selection is:

```bash
dfm run run -D hdlsim.sim=vlt          # whole build runs on Verilator
```

or, over a subtree, with a `set:` block:

```yaml
- name: regression
  set:
  - hdlsim.sim: vlt                     # this subtree runs on Verilator
  - path: "**/smoke*"                   # ... except the smoke leg
    set:
    - hdlsim.sim: mti                   # ... which runs on Questa
  body:
  - name: build
    uses: hdlsim.SimImage
    needs: [files]
    with: {top: [top]}
  - name: run
    uses: hdlsim.SimRun
    needs: [build]
```

If no simulator is selected, the build aborts with a diagnostic listing the
available backends. The explicit concrete form (`uses: hdlsim.vlt.SimImage`)
always works and bypasses selection. See the dv-flow-manager
*Scoped Variables and Overrides* guide for the full `set:` model.

## Multi-Simulator Support

Use package parameters and alias imports to select the simulator at build
time:

```yaml
package:
  name: my_project

  with:
    simulator:
      type: str
      value: vlt

  imports:
    - name: hdlsim.${{ simulator }}
      as: sim

  configs:
    - name: verilator
      with:
        simulator:
          value: vlt
    - name: vcs
      with:
        simulator:
          value: vcs
    - name: questa
      with:
        simulator:
          value: mti
```

Usage:

```bash
dfm run build -c vcs
dfm run build -c questa
```

## Build Reuse with --base-rundir

For regression workflows, build once and reuse compiled artifacts:

```bash
# Build phase
dfm run build

# Test phase (no recompilation)
dfm run test_smoke --base-rundir /path/to/build/rundir
dfm run test_full  --base-rundir /path/to/build/rundir
```

## Real-World UVM Example

A multi-fragment UVM testbench structure showing proper dependency chains.

### Directory Structure

```
project/
  flow.dv                    # Root package
  src/rtl/
    flow.dv                  # RTL fragment
    *.sv
  verification_ip/
    pkg_a/
      flow.dv                # VIP package A fragment
      hdl/*.sv
      hvl/*.sv
    pkg_b/
      flow.dv                # VIP package B fragment
      hdl/*.sv
      hvl/*.sv
  tb/
    flow.dv                  # TB fragment
    env/flow.dv              # Environment fragment
    sequences/flow.dv        # Sequences fragment
    tests/flow.dv            # Tests fragment
    hdl_top.sv
    hvl_top.sv
```

### Root Package (flow.dv)

```yaml
package:
  name: my_project

  imports:
    - name: hdlsim.vlt
      as: sim

  fragments:
    - src/rtl/flow.dv
    - verification_ip/pkg_a/flow.dv
    - verification_ip/pkg_b/flow.dv
    - tb/flow.dv

  configs:
    - name: vcs
      imports:
        - name: hdlsim.vcs
          as: sim
    - name: debug
      tasks:
        - name: debug_compile
          uses: hdlsim.SimCompileArgs
          with:
            args: ["-debug_access+all"]
          feeds: [my_project.build]
```

### RTL Fragment (src/rtl/flow.dv)

```yaml
fragment:
  tasks:
    - name: rtl
      uses: std.FileSet
      with:
        type: systemVerilogSource
        include: "*.sv"
```

### VIP Fragment (verification_ip/pkg_a/flow.dv)

```yaml
fragment:
  tasks:
    - name: pkg_a_hdl
      uses: std.FileSet
      with:
        type: systemVerilogSource
        base: hdl
        include: "*.sv"

    - name: pkg_a_hvl
      uses: std.FileSet
      needs: [pkg_a_hdl]
      with:
        type: systemVerilogSource
        base: hvl
        include: "*.sv"
```

### Testbench Fragment (tb/flow.dv)

```yaml
fragment:
  fragments:
    - env/flow.dv
    - sequences/flow.dv
    - tests/flow.dv

  tasks:
    - name: uvm
      uses: sim.SimLibUVM

    - name: hdl_top
      uses: std.FileSet
      needs: [pkg_a_hdl, pkg_b_hdl]
      with:
        type: systemVerilogSource
        include: "hdl_top.sv"

    - name: hvl_top
      uses: std.FileSet
      needs: [env, sequences]
      with:
        type: systemVerilogSource
        include: "hvl_top.sv"

    - root: build
      uses: sim.SimImage
      needs: [hdl_top, hvl_top, rtl, uvm]
      with:
        top: [hdl_top, hvl_top]

    - root: run
      uses: sim.SimRun
      needs: [build]
      with:
        plusargs: [UVM_TESTNAME=base_test]
```

### Test Fragment (tb/tests/flow.dv)

```yaml
fragment:
  tasks:
    - name: tests
      uses: std.FileSet
      needs: [env, sequences]
      with:
        type: systemVerilogSource
        include: "*.sv"

    - root: test_smoke
      uses: sim.SimRun
      needs: [build]
      with:
        plusargs: [UVM_TESTNAME=smoke_test]

    - root: test_full
      uses: sim.SimRun
      needs: [build]
      with:
        plusargs: [UVM_TESTNAME=full_test]
```

### Running

```bash
dfm run build                   # Compile
dfm run run                     # Run base test
dfm run test_smoke              # Run smoke test
dfm run test_full -c debug      # Run full test with debug
dfm run build -c vcs            # Compile with VCS
dfm graph build -o flow.dot     # Visualize dependency graph
```
