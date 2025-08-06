
import dataclasses as dc
from typing import Callable
from .log_parser import LogParser

@dc.dataclass
class XsmLogParser(LogParser):
    notify_analyze : Callable = None
    changed : bool = False

    def line(self, l : str):
        if not self.changed and "Analyzing " in l:
            self.changed = True
            if self.notify_analyze is not None:
                self.notify_analyze()
        else:
            super().line(l)
