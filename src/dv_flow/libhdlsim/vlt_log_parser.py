import dataclasses as dc
from typing import Callable
from .log_parser import LogParser

@dc.dataclass
class VltLogParser(LogParser):
    no_changes : Callable = None

    def line(self, l):
        if "Nothing to be done" in l:
            if self.no_changes is not None:
                self.no_changes()
        else:
            super().line(l)
