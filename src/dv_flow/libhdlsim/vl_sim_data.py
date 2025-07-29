import dataclasses as dc
from typing import List

@dc.dataclass
class VlSimImageData(object):
    files : List[str] = dc.field(default_factory=list)
    incdirs : List[str] = dc.field(default_factory=list)
    defines : List[str] = dc.field(default_factory=list)
    args : List[str] = dc.field(default_factory=list)
    compargs : List[str] = dc.field(default_factory=list)
    elabargs : List[str] = dc.field(default_factory=list)
    libs : List[str] = dc.field(default_factory=list)
    dpi : List[str] = dc.field(default_factory=list)
    vpi : List[str] = dc.field(default_factory=list)
    csource : List[str] = dc.field(default_factory=list)
    cincdirs : List[str] = dc.field(default_factory=list)
    top : List[str] = dc.field(default_factory=list)
    trace : bool = dc.field(default=False)

@dc.dataclass
class VlSimRunData(object):
    imgdir : str = ""
    args : List[str] = dc.field(default_factory=list)
    plusargs : List[str] = dc.field(default_factory=list)
    dpilibs : List[str] = dc.field(default_factory=list)
    vpilibs : List[str] = dc.field(default_factory=list)
    trace : bool = dc.field(default=False)

