import dataclasses as dc
from typing import Callable
from .log_parser import LogParser

@dc.dataclass
class MtiLogParser(LogParser):
    notify_comp : Callable = None
    notified : bool = False

    def line(self, l):
        if not self.notified and "-- Compiling " in l:
            if self.notify_comp is not None:
                self.notify_comp()
            self.notified = True
        else:
            super().line(l)


