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


Task: SimImage
==============
The SimImage task elaborates HDL source and/or precompiled libraries into
an executable simulation image

Example
-------

Consumes
--------

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


