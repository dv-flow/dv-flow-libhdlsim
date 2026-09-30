.. DV Flow LibHDLSim documentation master file, created by
   sphinx-quickstart on Thu May  8 14:09:09 2025.
   You can adapt this file completely to your liking, but it should at least
   contain the root `toctree` directive.
#################
DV Flow LibHDLSim
#################

LibHDLSim is a DV-Flow library that provides tasks for working with HDL simulators.
The library defines a set of tasks for compiling, elaborating, and running 
HDL simulators, as well as specific implementations for a variety of simulators.

.. contents::
    :depth: 2


Task: SimLib
============
The SimLib task compiles HDL source into a pre-compiled library. If a specific
toolchain does not support the notion of a pre-compiled library, the task
propagates the input sources

Example
-------

... code-block:: yaml

    package:
      name: lib_example

      tasks:
        - name: inc
          uses: std.FileSet
          with:
            type: verilogIncDir
            include: "include"

        - name: rtl
          uses: std.FileSet
          with:
            type: systemVerilogSource
            include: "*.sv"

        - name: lib
          uses: hdlsim.vlt.SimLib
          with:
            libname: work
          needs: [rtl, inc]

        - name: sim-image
          uses: hdlsim.vlt.SimImage
          with:
            top: [top]
          needs: [lib]

Consumes
--------

* simLib 
* systemVerilogSource 
* verilogIncDir 
* verilogSource 
* hdlsim.SimCompileArgs
* hdlsim.SuppressWarnings


Produces
--------

* simLib 

Parameters
----------

* **libname** - [Optional] Specifies the logical name of the library.
* **incdirs** - [Optional] List of extra include directories
* **defines** - [Optional] List of extra defines
* **suppress_warnings** - [Optional] List of warning codes to suppress from becoming markers (e.g., TFIPC, vlog-2623)

Task: SimLibUVM
===============
Most simulators have a built-in mechanism for enabling UVM support. This task
shall implement that mechanism and output appropriate data to support 
downstream compilation and elaboration tasks.

Task: SimLibDPI
============
The SimLibDPI task compiles a set of provided C/C++ sources and object files
into a SystemVerilog DPI library using simulator-specific include directories

Example
-------

Consumes
--------

* cSource
* cppSource


Produces
--------

* systemVerilogDPI

Parameters
----------

* **libname** - [Optional] Specifies the base name of the library
* **incdirs** - [Optional] List of extra include directories
* **defines** - [Optional] List of extra defines

Task: SimLibVPI
============
The SimLibVPI task compiles a set of provided C/C++ sources and object files
into a Verilog VPI library using simulator-specific include directories

Example
-------

Consumes
--------

* cSource
* cppSource


Produces
--------

* verilogVPI

Parameters
----------

* **libname** - [Optional] Specifies the base name of the library
* **incdirs** - [Optional] List of extra include directories
* **defines** - [Optional] List of extra defines

Task: SimImage
==============
The SimImage task elaborates HDL source and/or precompiled libraries into
an executable simulation image

Example
-------

Consumes
--------

* cSource
* cppSource
* simLib 
* systemVerilogSource 
* verilogIncDir 
* verilogSource 
* systemVerilogDPI 
* verilogVPI 
* hdlsim.SimCompileArgs
* hdlsim.SimElabArgs
* hdlsim.SimCovArgs
* hdlsim.SuppressWarnings


Produces
--------

* simDir 

Parameters
----------

* **top** - [Required] List of top module names
* **args** - [Optional] List of extra arguments to pass to the compilation and elaboration commands
* **compargs** - [Optional] List of extra arguments to pass to the compilation commands
* **elabargs** - [Optional] List of extra arguments to pass to the elaboration command
* **vpilibs** - [Optional] List of VPI library paths to specify to the elaboration command
* **dpilibs** - [Optional] List of DPI library paths to specify to the elaboration command
* **incdirs** - [Optional] List of extra include directories
* **defines** - [Optional] List of extra defines
* **suppress_warnings** - [Optional] List of warning codes to suppress from becoming markers (e.g., TFIPC, vlog-2623)
* **cov** - [Optional] Coverage level: ``none`` (default), ``func``, ``code`` or ``full``.
  The image is built at the highest of this and every consumed ``hdlsim.SimCovArgs``.
  See `Coverage`_.

Task: SimRun
============
The SimRun task executes an elaborated simulation image.

Example
-------

Consumes
--------

* simDir 
* systemVerilogDPI
* verilogVPI
* hdlsim.SimRunArgs
* simRunData -- Files to copy to the run directory


Produces
--------

* simRunDir 


Parameters
----------

* **args** - [Optional] List of simulation run command arguments
* **plusargs** - [Optional] List of extra include directories

Type: SimCompileArgs
====================
The SimCompileArgs type can be used to provide dataflow compilation arguments.

Parameters
----------

* **args** - [Optional] List of extra arguments to pass to the compilation command
* **incdirs** - [Optional] List of include directories
* **defines** - [Optional] List of defines


Type: SimElabArgs
=================
The SimElabArgs type can be used to provide dataflow elaboration arguments.

Parameters
----------

* **args** - [Optional] List of extra arguments to pass to the compilation command
* **dpilibs** - [Optional] List of DPI libraries
* **vpilibs** - [Optional] List of VPI libraries


Type: SimRunArgs
================
The SimRunArgs type can be used to provide dataflow run arguments.

Parameters
----------

* **args** - [Optional] List of extra arguments to pass to the simulation run
* **plusargs** - [Optional] List of plusargs to pass to the simulation run
* **dpilibs** - [Optional] List of DPI libraries
* **vpilibs** - [Optional] List of VPI libraries


Type: SimCovArgs
================
The SimCovArgs type requests coverage collection from SimImage (and, through
the image, SimRun). See `Coverage`_.

Parameters
----------

* **level** - [Optional] ``none``, ``func``, ``code`` or ``full``. Defaults to
  the package variable ``hdlsim.cov`` (itself ``none``), so a bare
  ``uses: hdlsim.SimCovArgs`` follows ``-D hdlsim.cov=<level>``.



Type: SuppressWarnings
======================
The SuppressWarnings type carries a list of warning codes to suppress as
markers.  Connect to SimImage or SimLib via ``needs`` or ``feeds`` to
suppress specific simulator warnings project-wide.

Example
-------

Direct parameter on SimImage:

.. code-block:: yaml

    - name: build
      uses: sim.SimImage
      needs: [rtl, tb]
      with:
        top: [tb_top]
        suppress_warnings: [TFIPC, MAXX]

Shared suppression dataset (reusable across tasks):

.. code-block:: yaml

    - name: suppress
      uses: hdlsim.SuppressWarnings
      with:
        codes: [TFIPC, MAXX]

    - name: build
      uses: sim.SimImage
      needs: [rtl, tb, suppress]
      with:
        top: [tb_top]

Via feeds in a config (no modification to the build task):

.. code-block:: yaml

    configs:
      - name: suppress_warnings
        tasks:
          - name: suppress
            uses: hdlsim.SuppressWarnings
            with:
              codes: [TFIPC, MAXX]
            feeds: [my_project.build]

Parameters
----------

* **codes** - List of warning codes to suppress (e.g., TFIPC, vlog-2623, PINCONNECTS)


Coverage
========

SimImage can build a coverage-instrumented image, and SimRun then collects
coverage as it runs. Coverage is off by default. Ask for it with a *level*.
Each level includes the ones below it.

.. list-table::
   :header-rows: 1

   * - Level
     - Collects
   * - ``none``
     - Nothing (the default)
   * - ``func``
     - Functional coverage: covergroups and ``cover property``
   * - ``code``
     - Adds line (statement) and branch coverage, plus expression coverage where the simulator has it
   * - ``full``
     - Adds toggle coverage, plus FSM coverage where the simulator has it

What each simulator collects at each level:

.. list-table::
   :header-rows: 1

   * - Level
     - vlt (Verilator)
     - xzm (xezim)
   * - ``func``
     - ``--coverage-user``: covergroups, ``cover property``
     - covergroups, ``cover property``
   * - ``code``
     - adds ``--coverage-line --coverage-expr``: line, branch, expression
     - adds ``--code-coverage=stmt,branch``: statement, branch
   * - ``full``
     - adds ``--coverage-toggle --coverage-fsm``: toggle, FSM state and arc
     - adds ``toggle`` to ``--code-coverage``

The other simulators don't support coverage yet. Asking them for a level gives
one warning, and the image is built without coverage.

Asking for coverage
-------------------

There are three ways, and the image uses the highest level any of them asks for:

* From the command line, for a flow that wires a bare ``hdlsim.SimCovArgs``
  into SimImage:

  .. code-block:: yaml

      - name: cov
        uses: hdlsim.SimCovArgs       # level follows hdlsim.cov
      - name: build
        uses: hdlsim.SimImage
        needs: [rtl, tb, cov]
        with: { top: [tb_top] }

  .. code-block:: bash

      dfm run build -D hdlsim.cov=code

* A holder that fixes the level: ``uses: hdlsim.SimCovArgs`` with
  ``with: { level: code }``.
* SimImage's ``cov`` parameter: ``with: { top: [tb_top], cov: full }``.

An unknown level is an error that lists the valid ones. Changing the level
rebuilds the image. SimRun has no coverage parameter: a run collects what its
image was built for.

Where the results go
--------------------

* **The database.** It is a ``simCovDb`` FileSet in ``SimRunResult.artifacts``
  (and from there in ``TestResult``/``SuiteResult``), with attributes
  ``role=cov`` and ``format=<id>``:

  - ``format=vlt-dat``: Verilator ``coverage.dat``
  - ``format=xezim-json``: xezim ``xezim_cov.json``

  A tool that reads the database should choose its decoder by ``format=``, not
  by file name. The database is inside the result items; it is not a separate
  output of SimRun.
* **Summary stats.** ``SimRunResult.stats`` gets ``cov_<kind>_pct``,
  ``cov_<kind>_covered`` and ``cov_<kind>_total`` for each kind the level
  measured. The kinds are ``line``, ``branch``, ``expr``, ``toggle``,
  ``fsm_state``, ``fsm_arc``, ``covergroup`` and ``user``; xezim's statement
  coverage is reported as ``line``. A kind with nothing to cover (0 of 0)
  is left out.
* **Provenance.** ``SimRunResult.runinfo.cov`` is ``{level, kinds}``. It is
  absent at ``none``.
* **Suites.** ``SimSuiteReport`` rolls ``cov_<kind>_pct`` up as
  ``cov_<kind>_pct_max``: the best single case. That is **not** merged
  coverage, and hit counts are not summed. Per-case percentages and the level
  appear in ``junit.xml`` properties and ``ctrf.json`` ``extra``, and the
  printed summary gets a ``coverage`` line.

Merging databases across runs and producing coverage reports are not
provided yet.

Limitations
-----------

* **Verilator: ``get_coverage()`` returns 0.** Bins are recorded correctly in
  ``coverage.dat``, but ``cg.get_coverage()`` and ``get_inst_coverage()`` are
  not implemented, so a testbench that prints coverage from a ``final`` block
  reports 0 on Verilator.
* **Verilator instruments the whole design, UVM included.** It has no module
  or instance selector, so at ``code`` and ``full`` the UVM library's code is
  counted too, and the line and branch percentages mostly measure UVM.
* **xezim reports no functional percentage.** Its database lists the bins
  that were hit but not the ones that weren't, so ``func`` gives a database
  and no ``cov_*`` stats. Code-coverage totals are reported.
* **xezim at ``none`` writes no database.** xezim normally writes
  ``xezim_cov.json`` whenever the design has a covergroup. SimRun now sends it
  to ``/dev/null`` unless a level is set.
* **xezim ``--code-coverage`` in ``args`` wins.** If the run's ``args``
  already ask for code coverage (``--code-coverage``, ``-coverage`` or
  ``+cover``), SimRun doesn't add its own flag. Stats still report only the
  kinds the level covers.
* **Cost.** Toggle instrumentation (``full``) grows with the number of
  signals, so it can slow the build and the run of a large design noticeably.
  Use ``code`` for routine regressions.
* **cocotb with Verilator works.** cocotb's Verilator main writes
  ``coverage.dat`` at exit.


Simulator Support
================= 

Tasks that support specific simulators are implemented in simulator-specific packages.
The tasks defined in these packages implement the same interface as the generic tasks.
For example, the full name of the `VCS` SimImage task is `hdlsim.vcs.SimImage`.

* **ivl** - Icarus Verilog
* **mti** - Siemens Questa Sim
* **vcs** - Synopsys VCS
* **vlt** - Verilator
* **xcm** - Cadence Xcelium
* **xsm** - AMD Xilinx Vivado (XSim)
* **xzm** - xezim

`SimUVMCase` (run one UVM test and emit a TestResult) is provided by every
UVM-capable package: vlt, vcs, mti, xcm, xsm and xzm. They share one
implementation; Icarus Verilog has no UVM support.

.. note::
    All trademarks are the property of their respective owners





Feature support matrix
=======================

The following summarizes supported features by simulator package, based on the current implementation.

ivl (Icarus Verilog)
--------------------
- Coverage: Not supported (a requested level gives a warning)
- DPI: Not supported (SimRun errors if dpilibs provided)
- VPI: Not supported
- Trace: Not exposed
- Valgrind: Not exposed
- Incremental compile: Yes (file-dependency cache/memento)
- Special parameters: None

vlt (Verilator)
---------------
- Coverage: ``func``, ``code``, ``full`` (build-time ``--coverage-*`` flags; ``coverage.dat``, summarized with ``verilator_coverage``). See `Coverage`_.
- DPI: Supported (link prebuilt libraries via -LDFLAGS, and/or compile C sources)
- VPI: Not supported
- Trace: Supported (SimImage --trace; SimRun adds +verilator+debug when trace=true)
- Valgrind: Not exposed
- Incremental compile: Yes (tool reports "Nothing to be done" to skip)
- Special parameters: None

mti (Siemens Questa/ModelSim)
-----------------------------
- Coverage: Not supported yet (a requested level gives a warning)
- DPI: Supported (compile C sources via vlog; runtime -sv_lib)
- VPI: Supported (runtime -pli)
- Trace: Not currently exposed by tasks
- Valgrind: Supported (-valgrind --tool=memcheck)
- Incremental compile: Yes (vlog -incr; detected via log parsing)
- Special parameters: None

vcs (Synopsys VCS)
------------------
- Coverage: Not supported yet (a requested level gives a warning)
- DPI: Not supported by SimImage (building); runtime load of prebuilt libs via -sv_lib supported in SimRun
- VPI: Supported (+vpi/-debug_access and -load <lib>)
- Trace: Not currently exposed by tasks
- Valgrind: Not exposed
- Incremental compile: Yes (vlogan -incr_vlogan; detected via log parsing)
- Special parameters: partcomp (bool), fastpartcomp (int)

xsm (AMD Xilinx XSIM)
---------------------
- Coverage: Not supported yet (a requested level gives a warning)
- DPI: Supported (xelab --sv_root/--sv_lib)
- VPI: Not supported
- Trace: Not currently exposed by tasks
- Valgrind: Not exposed
- Incremental compile: Yes (xvlog --incr; detected via log parsing)
- Special parameters: plusargs passed via --testplusarg at runtime

xcm (Cadence Xcelium)
---------------------
- Coverage: Not supported yet (a requested level gives a warning)
- Status: Experimental/incomplete in this repository; functionality may be outdated
- DPI/VPI/Trace/Valgrind/Incremental: TBD
- Special parameters: TBD

xzm (xezim)
-----------
- Coverage: ``func``, ``code``, ``full`` (run-time; ``xezim_cov.json``). No functional percentage. See `Coverage`_.
- DPI: Supported. C/C++ sources given to SimImage are compiled into a shared
  library (`libxzm_dpi.so`, needs `cc`/`c++`); it and prebuilt libraries are
  loaded at run time with --dpi-lib. A design that `export`s SV functions to
  C also needs `cc` on PATH at run time.
- VPI: Supported at run time (--vpi-lib). Only `vlog_startup_routines` is
  run; an `entrypoint=` attribute is ignored with a warning. cocotb 2.x works
  this way with its Icarus VPI library.
- Trace: Supported at run time. `trace: true`, or the debug elab preset's
  `trace_fmt`, gives FST (`sim.fst`) by default, or with `trace_fmt: vcd`
  the testbench's own `$dumpfile`/`$dumpvars`.
- Valgrind: Supported (the run is wrapped in valgrind --tool=memcheck)
- Incremental compile: Yes (file-dependency cache/memento). The image is
  also rebuilt when a different xezim build is on PATH.
- UVM: SimLibUVM provides the UVM bundled with xezim (or `$UVM_HOME`). UVM's
  DPI layer is built into xezim, so nothing is compiled for it.
- Special behavior:

  - `--error-exit` is always passed, so a `$error` fails the run.
  - `--max-time 1000000s` is passed unless `args` sets `--max-time`
    (xezim's own default is 100ms). Reaching it without `$finish` is a
    failed run: an Error in `mode: run`, a nonzero status in `mode: test`,
    and `runinfo.finish_reason` is `max_time`.
  - xezim diagnostics have no warning codes, so `suppress_warnings` cannot
    target them.
  - SimImage's `timing`, `vpi` and `public_flat_rw` have no effect.
