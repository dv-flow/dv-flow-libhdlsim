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

Task: SimPLI
============
The SimPLI task attaches an already-built PLI 1.0 shared library (and,
optionally, its VCS-format ``.tab`` table file) to a simulation. It compiles
nothing and runs no tool: it checks the files exist and describes them as a
``verilogPLI`` FileSet, which each simulator maps to its own flags.

Attach SimPLI to SimImage, not SimRun. Simulators that load PLI at run time
get it forwarded from the image, as with VPI.

With ``interface: vpi`` it emits an ordinary ``verilogVPI`` FileSet instead
(``boot`` becomes its ``entrypoint=``), so one task attaches either kind of
library.

Example
-------

.. code-block:: yaml

    - name: novas
      uses: hdlsim.SimPLI
      with:
        lib: /tools/verdi/share/PLI/VCS/LINUX64/libnovas.so
        tab: /tools/verdi/share/PLI/VCS/LINUX64/novas.tab

    - name: build
      uses: hdlsim.SimImage
      needs: [rtl, tb, novas]

Consumes
--------

* sharedLib -- used as the library when ``lib`` is empty (one FileSet each)

Produces
--------

* verilogPLI (``interface: pli1``), with attributes ``boot=``, ``tab=`` and ``access=``
* verilogVPI (``interface: vpi``)

Parameters
----------

* **lib** - Path to the shared library, relative to the flow's directory
* **tab** - [Optional] PLI 1.0 table file (VCS ``.tab`` format)
* **boot** - [Optional] Boot routine. PLI 1.0: returns the ``s_tfcell`` table.
  VPI: the startup routine.
* **interface** - ``pli1`` (default) or ``vpi``
* **access** - [Optional] Grant the design the visibility a PLI library needs
  (default true; costs simulation performance)

Simulator support
-----------------

==============  =====================  ==========================================================
sim             PLI 1.0 needs          Flags
==============  =====================  ==========================================================
xcm             ``boot`` or ``tab``    ``xmelab -loadpli1 lib:boot`` (and ``-access +rwc``);
                                       ``xmsim -loadpli1 lib:boot [-plimapfile tab]``
mti             nothing, or ``tab``    ``vsim -pli lib [-tab tab]``; ``vopt +acc``. Questa finds
                                       the systfs through ``veriusertfs``/``init_usertfs`` and
                                       ignores ``boot`` (with a warning).
vcs             ``tab``                ``vcs -P tab lib -LDFLAGS -Wl,-rpath,<dir>`` (and
                                       ``-debug_access``); linked into simv. Unverified.
ivl             ``boot``, no ``tab``   ``vvp -mcadpli simv.vpp -cadpli=lib:boot``. Needs an
                                       Icarus built with cadpli. Unverified.
vlt, xsm, xzm   not supported          SimImage reports an Error
==============  =====================  ==========================================================

A library or table rebuilt in place makes the image rebuild.

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
* verilogPLI -- see `Task: SimPLI`_
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
* verilogPLI -- normally forwarded by SimImage; see `Task: SimPLI`_
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

   * - Simulator
     - ``func``
     - ``code`` adds
     - ``full`` adds
   * - vlt (Verilator)
     - ``--coverage-user``: covergroups, ``cover property``
     - ``--coverage-line --coverage-expr``: line, branch, expression
     - ``--coverage-toggle --coverage-fsm``: toggle, FSM state and arc
   * - xzm (xezim)
     - covergroups, ``cover property``
     - ``--code-coverage=stmt,branch``: statement, branch
     - ``toggle`` in ``--code-coverage``
   * - vcs (VCS)
     - ``-cm assert``: covergroups (always recorded), ``cover property``
     - ``-cm line+cond+branch+assert``: line, condition, branch
     - ``+tgl+fsm``: toggle, FSM
   * - mti (Questa)
     - covergroups, cover directives (no ``+cover``)
     - vopt ``+cover=sbce``: statement, branch, condition, expression
     - ``+cover=sbceft``: toggle, FSM state and transition
   * - xcm (Xcelium)
     - xmelab ``-coverage u``: covergroups, ``cover property``
     - ``-coverage b:e:u``: block, expression
     - ``-coverage b:e:f:t:u``: toggle, FSM

The flags go to the elaborator (vcs, vopt, xmelab). VCS also gets the same
``-cm`` at run time, and Questa runs with ``vsim -coverage``.

ivl and xsm don't support coverage yet. Asking them for a level gives one
warning, and the image is built without it.

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
  - ``format=vcs-vdb``: VCS ``cov.vdb`` (a directory)
  - ``format=questa-ucdb``: Questa ``cov.ucdb``
  - ``format=xcelium-ucd``: Xcelium ``cov_work`` (a directory holding the
    model ``.ucm`` and the run's ``.ucd``)

  Each run's database stands alone: it holds the design data a report or a
  merge needs as well as that run's hits. VCS and Xcelium record the run under
  the name of its run directory (``-cm_name`` / ``-covtest``), so runs
  stay distinct when merged.

  A tool that reads the database should choose its decoder by ``format=``, not
  by file name. The database is inside the result items; it is not a separate
  output of SimRun.
* **Summary stats.** ``SimRunResult.stats`` gets ``cov_<kind>_pct``,
  ``cov_<kind>_covered`` and ``cov_<kind>_total`` for each kind the level
  measured. The kinds are ``line``, ``branch``, ``expr``, ``toggle``,
  ``fsm_state``, ``fsm_arc``, ``covergroup`` and ``user``. Simulators name
  these differently. xezim's and Questa's statement coverage is reported as
  ``line``. VCS's condition coverage and Questa's condition and expression
  coverage are reported as ``expr``. VCS reports a single FSM figure, which
  counts transitions, so it is reported as ``fsm_arc``. ``user`` is
  ``cover property`` (Questa: cover directives). A kind with nothing to cover
  (0 of 0) is left out.

  The totals come from each simulator's report utility, run on the database
  after the simulation: ``verilator_coverage``, ``urg`` (VCS) or ``vcover``
  (Questa). It must be on ``PATH``. If it isn't, or if it fails, the run
  still gives its database but no ``cov_*`` stats. Xcelium gives no
  ``cov_*`` stats yet (see Limitations).
* **Provenance.** ``SimRunResult.runinfo.cov`` is ``{level, kinds}``. It is
  absent at ``none``.
* **Suites.** ``SimSuiteReport`` rolls ``cov_<kind>_pct`` up as
  ``cov_<kind>_pct_max``: the best single case. That is **not** merged
  coverage, and hit counts are not summed (for that, see `Merging`_).
  Per-case percentages and the level appear in ``junit.xml`` properties and
  ``ctrf.json`` ``extra``, and the printed summary gets a ``coverage`` line.

Merging
-------

``SimCovMerge`` merges the databases of the runs it needs into one, using the
simulator's own merge utility:

.. list-table::
   :header-rows: 1

   * - Simulator
     - Merge command
     - Merged database
   * - vlt
     - ``verilator_coverage -write``
     - ``coverage.dat``
   * - vcs
     - ``urg -dir ... -dbname``
     - ``cov.vdb``
   * - mti
     - ``vcover merge``
     - ``cov.ucdb``

It finds the databases in the ``simCovDb`` artifacts of its ``SimRunResult``,
``TestResult`` and ``SuiteResult`` inputs, and in bare ``simCovDb`` FileSets.
So it can follow the runs, the checks, or a ``SimSuiteReport``:

.. code-block:: yaml

    - name: regress
      uses: hdlsim.SimSuiteReport
      needs: [case1, case2, case3]
    - name: cov-merge
      uses: hdlsim.SimCovMerge      # or hdlsim.vcs.SimCovMerge
      needs: [regress]

Only databases of the backend's ``format=`` are merged. Any other is skipped
with a warning, and finding none at all is an error. A database reached
through two inputs (a run and the check that forwards its artifacts) is
merged once.

The outputs are:

* the merged database, as a ``simCovDb`` FileSet with the same ``format=``.
  It is an input like any other, so one merge can feed another;
* a ``SimCovMergeResult`` with ``sim``, ``format``, ``inputs`` (the merged
  paths) and ``stats``: the merged ``cov_<kind>_*`` totals, from the same
  report utility a run uses. ``stats`` is empty when that utility isn't on
  ``PATH``.

The merge runs one command over every database, in a single task. Xcelium and
xezim have no ``SimCovMerge`` yet. The merge doesn't produce detailed
coverage reports.

Limitations
-----------

* **Verilator: ``get_coverage()`` returns 0.** Bins are recorded correctly in
  ``coverage.dat``, but ``cg.get_coverage()`` and ``get_inst_coverage()`` are
  not implemented, so a testbench that prints coverage from a ``final`` block
  reports 0 on Verilator.
* **UVM is counted too.** No exclusions are applied, so at ``code`` and
  ``full`` the UVM library's code is instrumented along with the design, on
  every simulator, and the line and branch percentages mostly measure UVM.
  Verilator has no module or instance selector; on xezim, a raw
  ``--code-coverage-scope <instance>`` in the run's ``args`` narrows it.
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
* **Xcelium reports no percentages yet.** Its totals come from IMC, which
  SimRun doesn't run yet. A run gives the ``cov_work`` database and
  ``runinfo.cov``, but no ``cov_*`` stats. Its kinds name block coverage as
  ``line``, and branch coverage is not enabled.
* **VCS copies the image's database into each run.** The run's ``cov.vdb``
  starts as a copy of the image's ``simv.vdb``, without any test data, and
  simv adds the run's hits to it. On a large design this copy takes disk
  space in every run directory.
* **Your own coverage flags.** SimImage and SimRun add their flags whatever
  ``args``, ``elabargs`` or run ``args`` already contain. To collect a
  different set of metrics, leave the level at ``none`` and pass the
  simulator's own flags (``-cm``, ``+cover``, ``-coverage``) yourself. You
  then get no ``simCovDb`` or ``cov_*`` stats.
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
- PLI 1.0: Through cadpli (``boot`` required, no ``tab``). Unverified.
- Trace: Not exposed
- Valgrind: Not exposed
- Incremental compile: Yes (file-dependency cache/memento)
- Special parameters: None

vlt (Verilator)
---------------
- Coverage: ``func``, ``code``, ``full`` (build-time ``--coverage-*`` flags; ``coverage.dat``, summarized with ``verilator_coverage``). See `Coverage`_.
- DPI: Supported (link prebuilt libraries via -LDFLAGS, and/or compile C sources)
- VPI: Not supported
- PLI 1.0: Not supported
- Trace: Supported (SimImage --trace; SimRun adds +verilator+debug when trace=true)
- Valgrind: Not exposed
- Incremental compile: Yes (tool reports "Nothing to be done" to skip)
- Special parameters: None

mti (Siemens Questa/ModelSim)
-----------------------------
- Coverage: ``func``, ``code``, ``full`` (vopt ``+cover``; ``cov.ucdb``, summarized with ``vcover``). See `Coverage`_.
- DPI: Supported (compile C sources via vlog; runtime -sv_lib)
- VPI: Supported (runtime -pli)
- PLI 1.0: Supported (runtime -pli, -tab)
- Trace: Not currently exposed by tasks
- Valgrind: Supported (-valgrind --tool=memcheck)
- Incremental compile: Yes (vlog -incr; detected via log parsing)
- Special parameters: None

vcs (Synopsys VCS)
------------------
- Coverage: ``func``, ``code``, ``full`` (``-cm`` at build and run; ``cov.vdb``, summarized with ``urg``). See `Coverage`_.
- DPI: Not supported by SimImage (building); runtime load of prebuilt libs via -sv_lib supported in SimRun
- VPI: Supported (+vpi/-debug_access and -load <lib>)
- PLI 1.0: Supported (-P <tab> <lib>, linked into simv; ``tab`` required). Unverified.
- Trace: Not currently exposed by tasks
- Valgrind: Not exposed
- Incremental compile: Yes (vlogan -incr_vlogan; detected via log parsing)
- Special parameters: partcomp (bool), fastpartcomp (int)

xsm (AMD Xilinx XSIM)
---------------------
- Coverage: Not supported yet (a requested level gives a warning)
- DPI: Supported (xelab --sv_root/--sv_lib)
- VPI: Not supported
- PLI 1.0: Not supported
- Trace: Not currently exposed by tasks
- Valgrind: Not exposed
- Incremental compile: Yes (xvlog --incr; detected via log parsing)
- Special parameters: plusargs passed via --testplusarg at runtime

xcm (Cadence Xcelium)
---------------------
- Coverage: ``func``, ``code``, ``full`` (xmelab ``-coverage``; ``cov_work``). Database only, no ``cov_*`` stats yet. See `Coverage`_.
- Status: Experimental/incomplete in this repository; functionality may be outdated
- PLI 1.0: Supported (xmelab/xmsim -loadpli1, xmsim -plimapfile; ``boot`` or ``tab`` required)
- DPI/VPI/Trace/Valgrind/Incremental: TBD
- UVM: SimLibUVM compiles the UVM bundled with Xcelium (``uvmhome``,
  default ``CDNS-1.2``, or an absolute path) once into the logical library
  ``uvm``. The UVM PLI library is passed on as a ``verilogPLI`` FileSet
  (loaded with ``-loadpli1`` at elaboration and run time), and the UVM
  PLI/DPI libraries with ``-sv_lib`` at run time. A UVM without the
  prebuilt DPI library is built
  with ``UVM_NO_DPI``.
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
- PLI 1.0: Not supported
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
