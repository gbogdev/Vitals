"""Background threads. Both stop cooperatively; callers must call stop() then wait()."""
from __future__ import annotations

import threading

from PySide6.QtCore import QThread, Signal

from ..analysis import apply_filter
from ..logparse import LogParser
from ..monitor import Collector


class SamplerThread(QThread):
    sampled = Signal(object)

    def __init__(self, interval_s: float, parent=None):
        super().__init__(parent)
        self._interval = interval_s
        self._stop = threading.Event()

    def set_interval(self, s: float):
        self._interval = max(0.5, s)

    def stop(self):
        self._stop.set()

    def run(self):
        c = Collector()
        while not self._stop.is_set():
            self.sampled.emit(c.sample())
            self._stop.wait(self._interval)


class LogLoadThread(QThread):
    progress = Signal(int)
    finished_ok = Signal(list, bool)   # entries, truncated
    failed = Signal(str)

    def __init__(self, path: str, rules: list, max_entries: int, parent=None):
        super().__init__(parent)
        self.path, self.rules, self.max_entries = path, rules, max_entries
        self._stop = threading.Event()

    def stop(self):
        self._stop.set()

    def run(self):
        try:
            entries = []
            for e in LogParser(self.rules).parse_file(self.path, self.max_entries):
                if self._stop.is_set():
                    return
                entries.append(e)
                if len(entries) % 5000 == 0:
                    self.progress.emit(len(entries))
            self.finished_ok.emit(entries, len(entries) >= self.max_entries)
        except Exception as ex:  # report any I/O or rule error to the UI
            self.failed.emit(f"{type(ex).__name__}: {ex}")


class FilterThread(QThread):
    done = Signal(list)
    failed = Signal(str)

    def __init__(self, entries: list, flt, parent=None):
        super().__init__(parent)
        self.entries, self.flt = entries, flt

    def run(self):
        try:
            self.done.emit(apply_filter(self.entries, self.flt))
        except Exception as ex:  # e.g. invalid regex
            self.failed.emit(f"{type(ex).__name__}: {ex}")
