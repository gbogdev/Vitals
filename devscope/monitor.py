"""System metric collection and bounded history. Values that cannot be read are None."""
from __future__ import annotations

import os
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Deque, Iterable, Optional

import psutil


@dataclass
class ProcInfo:
    pid: int
    name: str
    cpu: Optional[float]
    rss: Optional[int]


@dataclass
class Sample:
    ts: float
    cpu: Optional[float] = None          # percent, measured
    mem_percent: Optional[float] = None
    mem_used: Optional[int] = None
    mem_total: Optional[int] = None
    disk_percent: Optional[float] = None
    disk_used: Optional[int] = None
    disk_total: Optional[int] = None
    net_sent_bps: Optional[float] = None  # bytes/s, derived from counter deltas
    net_recv_bps: Optional[float] = None
    procs: list = field(default_factory=list)
    errors: list = field(default_factory=list)


def _safe(errors: list, label: str, fn):
    try:
        return fn()
    except (psutil.Error, OSError, NotImplementedError, AttributeError) as e:
        errors.append(f"{label}: {type(e).__name__}")
        return None


class Collector:
    """Stateful: network rates and per-process CPU need the previous reading."""

    def __init__(self, disk_path: Optional[str] = None, top_n: int = 200):
        self.disk_path = disk_path or os.path.abspath(os.sep)
        self.top_n = top_n
        self._prev_net = None
        self._procs: dict = {}
        psutil.cpu_percent(None)

    def sample(self) -> Sample:
        s = Sample(ts=time.time())
        e = s.errors
        s.cpu = _safe(e, "cpu", lambda: psutil.cpu_percent(None))
        vm = _safe(e, "memory", psutil.virtual_memory)
        if vm:
            s.mem_percent, s.mem_used, s.mem_total = vm.percent, vm.used, vm.total
        du = _safe(e, "disk", lambda: psutil.disk_usage(self.disk_path))
        if du:
            s.disk_percent, s.disk_used, s.disk_total = du.percent, du.used, du.total
        net = _safe(e, "network", psutil.net_io_counters)
        now = time.monotonic()
        if net:
            if self._prev_net:
                t0, sent0, recv0 = self._prev_net
                dt = now - t0
                if dt > 0:
                    s.net_sent_bps = max(0.0, (net.bytes_sent - sent0) / dt)
                    s.net_recv_bps = max(0.0, (net.bytes_recv - recv0) / dt)
            self._prev_net = (now, net.bytes_sent, net.bytes_recv)
        s.procs = self._processes(e)
        return s

    def _processes(self, errors: list) -> list:
        out, seen, denied = [], set(), 0
        try:
            procs = list(psutil.process_iter())
        except (psutil.Error, OSError) as ex:
            errors.append(f"processes: {type(ex).__name__}")
            return out
        for p in procs:
            pid = p.pid
            seen.add(pid)
            p = self._procs.setdefault(pid, p)  # reuse object so cpu_percent has a baseline
            try:
                with p.oneshot():
                    name = p.name()
                    cpu = p.cpu_percent(None)
                    try:
                        rss = p.memory_info().rss
                    except (psutil.AccessDenied, OSError):
                        rss = None
                        denied += 1
                out.append(ProcInfo(pid, name, cpu, rss))
            except psutil.NoSuchProcess:
                self._procs.pop(pid, None)
            except (psutil.AccessDenied, OSError):
                denied += 1
                out.append(ProcInfo(pid, "(access denied)", None, None))
        for pid in set(self._procs) - seen:
            del self._procs[pid]
        if denied:
            errors.append(f"processes: {denied} not fully readable (permissions)")
        out.sort(key=lambda x: (x.cpu or 0.0, x.rss or 0), reverse=True)
        return out[: self.top_n]


class History:
    """Bounded sample store; oldest samples are dropped (no unbounded growth)."""

    def __init__(self, max_samples: int = 3600):
        self._d: Deque[Sample] = deque(maxlen=max_samples)

    def add(self, s: Sample) -> None:
        self._d.append(s)

    def __len__(self):
        return len(self._d)

    def samples(self) -> list:
        return list(self._d)

    def series(self, metric: str) -> list:
        return [getattr(s, metric) for s in self._d]

    def clear(self):
        self._d.clear()


def aggregate(values: Iterable[Optional[float]]) -> dict:
    """min/avg/max over available values; missing (None) values are excluded and counted."""
    vals = list(values)
    ok = [v for v in vals if v is not None]
    if not ok:
        return {"count": 0, "missing": len(vals), "min": None, "avg": None, "max": None}
    return {"count": len(ok), "missing": len(vals) - len(ok),
            "min": min(ok), "avg": sum(ok) / len(ok), "max": max(ok)}


METRICS = ("cpu", "mem_percent", "disk_percent", "net_sent_bps", "net_recv_bps")


def summarize(samples: list) -> dict:
    return {m: aggregate(getattr(s, m) for s in samples) for m in METRICS}
