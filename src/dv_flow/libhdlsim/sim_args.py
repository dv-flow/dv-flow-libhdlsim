
import pydantic.dataclasses as pdc
from pydantic import BaseModel
from typing import List

class SimArgs(BaseModel):
    type : str = "hdlsim.SimArgs"
    src : str = ""
    seq : int = -1
    args : List[str] = pdc.Field(default_factory=list)
    plusargs : List[str] = pdc.Field(default_factory=list)

