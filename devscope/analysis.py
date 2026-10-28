"""Filtering, grouping and context lookup over parsed log entries."""
from __future__ import annotations

import csv
import io
import json
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from .logparse import LEVELS, LogEntry


@dataclass
class LogFilter:
    text: str = ""
    regex: bool = False
    case_sensitive: bool = False
    levels: Optional[set] = None       # None = any
    source: str = ""                   # substring match
    start: Optional[datetime] = None
    end: Optional[datetime] = None


def apply_filter(entries: list, f: LogFilter) -> list:
    rx = None
    if f.text:
        flags = 0 if f.case_sensitive else re.IGNORECASE
        rx = re.compile(f.text if f.regex else re.escape(f.text), flags)  # re.error propagates to caller
    src = f.source.lower()
    out = []
    for e in entries:
        if f.levels is not None and (e.level or "") not in f.levels:
            continue
        if src and src not in e.source.lower():
            continue
        if f.start or f.end:
            if e.timestamp is None:
                continue
            if (f.start and e.timestamp < f.start) or (f.end and e.timestamp > f.end):
                continue
        if rx and not rx.search(e.full_text):
            continue
        out.append(e)
    return out


_NORM = [
    (re.compile(r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b"), "<uuid>"),
    (re.compile(r"0x[0-9a-fA-F]+"), "<hex>"),
    (re.compile(r"\d+(?:\.\d+)*"), "<n>"),
]


def normalize_message(msg: str) -> str:
    for rx, rep in _NORM:
        msg = rx.sub(rep, msg)
    return msg.strip()


@dataclass
class Group:
    key: str
    level: Optional[str]
    count: int
    first: Optional[datetime]
    last: Optional[datetime]
    example: LogEntry


def group_recurring(entries: list, min_level: str = "ERROR", min_count: int = 1) -> list:
    """Group entries at or above min_level by normalized message. Sorted by count desc."""
    floor = LEVELS.index(min_level)
    groups: dict = {}
    for e in entries:
        if e.level is None or LEVELS.index(e.level) < floor:
            continue
        k = (e.level, e.source, normalize_message(e.message))
        g = groups.get(k)
        if g is None:
            groups[k] = Group(k[2], e.level, 1, e.timestamp, e.timestamp, e)
        else:
            g.count += 1
            if e.timestamp:
                g.first = min(g.first, e.timestamp) if g.first else e.timestamp
                g.last = max(g.last, e.timestamp) if g.last else e.timestamp
    return sorted((g for g in groups.values() if g.count >= min_count), key=lambda g: -g.count)


def context(entries: list, index: int, before: int = 5, after: int = 5) -> list:
    """Entries surrounding entries[index] in the full (unfiltered) list."""
    return entries[max(0, index - before): index + after + 1]


def _row(e: LogEntry) -> list:
    return [e.lineno, e.timestamp.isoformat(sep=" ") if e.timestamp else "", e.level or "", e.source, e.full_text]


def _csv_safe(v):
    """Neutralize spreadsheet formula injection (cell text starting with = + - @ tab CR)."""
    return "'" + v if isinstance(v, str) and v[:1] in ("=", "+", "-", "@", "\t", "\r") else v


def export_entries(entries: list, fmt: str) -> str:
    if fmt == "csv":
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["line", "timestamp", "level", "source", "message"])
        w.writerows([_csv_safe(c) for c in _row(e)] for e in entries)
        return buf.getvalue()
    if fmt == "json":
        keys = ["line", "timestamp", "level", "source", "message"]
        return json.dumps([dict(zip(keys, _row(e))) for e in entries], indent=2)
    if fmt == "text":
        return "".join(f"{e.timestamp or ''} {e.level or ''} {e.source} {e.full_text}\n" for e in entries)
    raise ValueError(f"unknown format: {fmt}")
