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


Produces
--------

* simLib 

Parameters
----------

* **libname** - [Optional] Specifies the logical name of the library.
* **incdirs** - [Optional] List of extra include directories
* **defines** - [Optional] List of extra defines

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

.. note::
    All trademarks are the property of their respective owners





Feature support matrix
=======================

The following summarizes supported features by simulator package, based on the current implementation.

ivl (Icarus Verilog)
--------------------
- DPI: Not supported (SimRun errors if dpilibs provided)
- VPI: Not supported
- Trace: Not exposed
- Valgrind: Not exposed
- Incremental compile: Yes (file-dependency cache/memento)
- Special parameters: None

vlt (Verilator)
---------------
- DPI: Supported (link prebuilt libraries via -LDFLAGS, and/or compile C sources)
- VPI: Not supported
- Trace: Supported (SimImage --trace; SimRun adds +verilator+debug when trace=true)
- Valgrind: Not exposed
- Incremental compile: Yes (tool reports "Nothing to be done" to skip)
- Special parameters: None

mti (Siemens Questa/ModelSim)
-----------------------------
- DPI: Supported (compile C sources via vlog; runtime -sv_lib)
- VPI: Supported (runtime -pli)
- Trace: Not currently exposed by tasks
- Valgrind: Supported (-valgrind --tool=memcheck)
- Incremental compile: Yes (vlog -incr; detected via log parsing)
- Special parameters: None

vcs (Synopsys VCS)
------------------
- DPI: Not supported by SimImage (building); runtime load of prebuilt libs via -sv_lib supported in SimRun
- VPI: Supported (+vpi/-debug_access and -load <lib>)
- Trace: Not currently exposed by tasks
- Valgrind: Not exposed
- Incremental compile: Yes (vlogan -incr_vlogan; detected via log parsing)
- Special parameters: partcomp (bool), fastpartcomp (int)

xsm (AMD Xilinx XSIM)
---------------------
- DPI: Supported (xelab --sv_root/--sv_lib)
- VPI: Not supported
- Trace: Not currently exposed by tasks
- Valgrind: Not exposed
- Incremental compile: Yes (xvlog --incr; detected via log parsing)
- Special parameters: plusargs passed via --testplusarg at runtime

xcm (Cadence Xcelium)
---------------------
- Status: Experimental/incomplete in this repository; functionality may be outdated
- DPI/VPI/Trace/Valgrind/Incremental: TBD
- Special parameters: TBD
