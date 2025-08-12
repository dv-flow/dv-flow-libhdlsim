import dataclasses as dc
from typing import Callable
from .log_parser import LogParser

@dc.dataclass
class VcsLogParser(LogParser):
    notify_parsing : Callable = dc.field(default=None)
    notified : bool = False

    def line(self, l):

        if not self.notified and ("Parsing " in l or "recompiling" in l):
            if self.notify_parsing is not None:
                self.notify_parsing()
            self.notified = True
        else:
            super().line(l)
