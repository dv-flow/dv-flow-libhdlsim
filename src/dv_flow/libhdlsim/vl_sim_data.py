import os
import dataclasses as dc
from typing import List, Optional, Tuple

@dc.dataclass
class PliLib(object):
    """A pre-built PLI 1.0 (TF/ACC) library, as carried by a `verilogPLI`
    FileSet (see SimPLI). `boot` is the routine returning the s_tfcell table;
    `tab` is a VCS-format table file; `access` asks for design visibility."""
    path : str
    boot : Optional[str] = None
    tab : Optional[str] = None
    access : bool = True

    def key(self):
        return (self.path, self.boot, self.tab)

    def attributes(self) -> List[str]:
        attrs = []
        if self.boot:
            attrs.append("boot=%s" % self.boot)
        if self.tab:
            attrs.append("tab=%s" % self.tab)
        attrs.append("access=%d" % (1 if self.access else 0))
        return attrs

def pli_from_fileset(fs) -> List[PliLib]:
    """One PliLib per file of a `verilogPLI` FileSet, from its `boot=`,
    `tab=` and `access=` attributes. A relative `tab=` is taken against the
    FileSet basedir."""
    boot = None
    tab = None
    access = True
    for attr in (getattr(fs, "attributes", None) or []):
        key, sep, val = attr.partition("=")
        if not sep:
            continue
        if key == "boot":
            boot = val or None
        elif key == "tab":
            tab = val or None
        elif key == "access":
            access = val.strip().lower() not in ("0", "false", "no", "off", "")
    if tab and not os.path.isabs(tab):
        tab = os.path.join(fs.basedir, tab)
    return [PliLib(path=os.path.join(fs.basedir, f), boot=boot, tab=tab, access=access)
            for f in fs.files]

def pli_add(libs : List[PliLib], new : List[PliLib]):
    """Append `new` to `libs` in order, dropping any (path, boot, tab) already
    present. A diamond in the flow graph can deliver one library twice."""
    seen = set(l.key() for l in libs)
    for lib in new:
        if lib.key() not in seen:
            seen.add(lib.key())
            libs.append(lib)

@dc.dataclass
class VlSimImageData(object):
    sysv : bool = dc.field(default=False)
    files : List[str] = dc.field(default_factory=list)
    incdirs : List[str] = dc.field(default_factory=list)
    defines : List[str] = dc.field(default_factory=list)
    args : List[str] = dc.field(default_factory=list)
    compargs : List[str] = dc.field(default_factory=list)
    elabargs : List[str] = dc.field(default_factory=list)
    libs : List[str] = dc.field(default_factory=list)
    # Xcelium MSIE: consumed primary snapshots (Type C). `primaries` holds the
    # physical library directories carrying each primary snapshot (added as
    # cds.lib DEFINEs); `primtops` holds the primary cell/top names to bind via
    # `xmelab -primsnap <name>`.
    primaries : List[str] = dc.field(default_factory=list)
    primtops : List[str] = dc.field(default_factory=list)
    dpi : List[str] = dc.field(default_factory=list)
    vpi : List[Tuple[str, Optional[str]]] = dc.field(default_factory=list)
    # PLI 1.0 libraries (verilogPLI FileSets), in load order.
    pli : List[PliLib] = dc.field(default_factory=list)
    # Request the simulator's VPI runtime without necessarily linking an
    # external VPI library. Anything that calls VPI from C needs this -- a
    # cocotb main, or the UVM DPI layer (uvm_hdl_verilator.c, uvm_svcmd_dpi.c).
    vpi_enable : bool = dc.field(default=False)
    # Request flat public read/write access to all signals. Needed to reach
    # arbitrary signals through VPI, but it inhibits optimization, so it is
    # requested explicitly rather than implied by vpi_enable.
    public_flat_rw : bool = dc.field(default=False)
    csource : List[str] = dc.field(default_factory=list)
    cincdirs : List[str] = dc.field(default_factory=list)
    # Path to a user/tool-supplied C++ "main" (eg cocotb's verilator.cpp). When
    # set, the Verilator SimImage builds with this main instead of --main.
    verilator_main : Optional[str] = dc.field(default=None)
    top : List[str] = dc.field(default_factory=list)
    trace : bool = dc.field(default=False)
    # Waveform format, and the trace enable: "none" (off), "fst" (default
    # format when tracing) or "vcd". Selects Verilator's --trace-fst vs
    # --trace at build time. Set from the elab-args `trace_fmt` param.
    trace_fmt : str = dc.field(default="none")
    timing : bool = dc.field(default=True)
    full64 : bool = dc.field(default=True)
    # Coverage level (cov.LEVELS): the highest of SimImage's `cov` param and
    # every consumed SimCovArgs. Recorded in <imgdir>/cov.json for the run.
    cov_level : str = dc.field(default="none")

@dc.dataclass
class VlSimRunData(object):
    imgdir : str = ""
    args : List[str] = dc.field(default_factory=list)
    plusargs : List[str] = dc.field(default_factory=list)
    dpilibs : List[str] = dc.field(default_factory=list)
    vpilibs : List[Tuple[str, Optional[str]]] = dc.field(default_factory=list)
    plilibs : List[PliLib] = dc.field(default_factory=list)
    trace : bool = dc.field(default=False)
    full64 : bool = dc.field(default=True)
    valgrind : bool = dc.field(default=False)
    # The image's coverage record ({level, kinds}, from cov.json); None when
    # the image was built without coverage.
    cov : Optional[dict] = dc.field(default=None)

