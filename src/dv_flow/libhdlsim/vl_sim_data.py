import dataclasses as dc
from typing import List

@dc.dataclass
class VlSimImageData(object):
    files : List[str] = dc.field(default_factory=list)
    incdirs : List[str] = dc.field(default_factory=list)
    defines : List[str] = dc.field(default_factory=list)
    libs : List[str] = dc.field(default_factory=list)
    dpi : List[str] = dc.field(default_factory=list)
    vpi : List[str] = dc.field(default_factory=list)
    top : List[str] = dc.field(default_factory=list)

@dc.dataclass
class VlSimRunData(object):
    imgdir : str = None
    args : List[str] = dc.field(default_factory=list)
    plusargs : List[str] = dc.field(default_factory=list)
    dpilibs : List[str] = dc.field(default_factory=list)
    vpilibs : List[str] = dc.field(default_factory=list)
    dumpwaves : bool = dc.field(default=False)

