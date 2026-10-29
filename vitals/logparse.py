"""Incremental log parsing driven by configurable regex rules."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Iterator, Optional

# Each rule: regex with named groups (timestamp, level, source, message) and an optional strptime format.
DEFAULT_RULES = [
    {"name": "iso", "ts_format": "%Y-%m-%d %H:%M:%S",
     "pattern": r"^(?P<timestamp>\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2})(?:[.,]\d+)?(?:Z|[+-]\d{2}:?\d{2})?\s+"
                r"\[?(?P<level>[A-Za-z]+)\]?\s+(?:\[?(?P<source>[\w.\-/]+)(?:\]\s*[:\-]?|\s*:)\s*)?(?P<message>.*)$"},
    {"name": "syslog", "ts_format": "%b %d %H:%M:%S",
     "pattern": r"^(?P<timestamp>[A-Z][a-z]{2}\s+\d{1,2}\s\d{2}:\d{2}:\d{2})\s+\S+\s+"
                r"(?P<source>[\w.\-/]+)(?:\[\d+\])?:\s*(?P<message>.*)$"},
]

MAX_LINE = 10_000  # chars kept per line; bounds memory on pathological files
LEVELS = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
_ALIASES = {"TRACE": "DEBUG", "DBG": "DEBUG", "NOTICE": "INFO", "WARN": "WARNING",
            "ERR": "ERROR", "SEVERE": "ERROR", "FATAL": "CRITICAL", "CRIT": "CRITICAL"}
_LEVEL_IN_MSG = re.compile(r"\b(DEBUG|INFO|WARN(?:ING)?|ERROR|CRITICAL|FATAL)\b")


def normalize_level(raw: Optional[str]) -> Optional[str]:
    if not raw:
        return None
    r = raw.upper()
    r = _ALIASES.get(r, r)
    return r if r in LEVELS else None


@dataclass
class LogEntry:
    lineno: int
    timestamp: Optional[datetime]
    level: Optional[str]
    source: str
    message: str
    continuation: list = field(default_factory=list)  # e.g. stack trace lines

    @property
    def full_text(self) -> str:
        return "\n".join([self.message, *self.continuation])


class LogParser:
    def __init__(self, rules: Optional[list] = None, default_year: Optional[int] = None):
        self.rules = [(r, re.compile(r["pattern"]), r.get("ts_format")) for r in (rules or DEFAULT_RULES)]
        self.default_year = default_year or datetime.now().year

    def _ts(self, text: str, fmt: Optional[str]) -> Optional[datetime]:
        if not text or not fmt:
            return None
        text = " ".join(text.replace("T", " ").split())
        fmt = " ".join(fmt.replace("T", " ").split())
        try:
            if "%Y" not in fmt:
                return datetime.strptime(f"{self.default_year} {text}", f"%Y {fmt}")
            return datetime.strptime(text, fmt)
        except ValueError:
            return None

    def parse_line(self, line: str, lineno: int) -> Optional[LogEntry]:
        for _, rx, fmt in self.rules:
            m = rx.match(line)
            if not m:
                continue
            g = m.groupdict()
            level = normalize_level(g.get("level"))
            msg = g.get("message") or ""
            if level is None:
                mm = _LEVEL_IN_MSG.search(msg)
                level = normalize_level(mm.group(1)) if mm else None
            return LogEntry(lineno, self._ts(g.get("timestamp") or "", fmt), level,
                            g.get("source") or "", msg)
        return None

    def parse_lines(self, lines, max_entries: int = 500_000) -> Iterator[LogEntry]:
        """Stream entries one at a time. Unmatched lines attach to the previous entry as
        continuations. Stops after max_entries."""
        cur, n = None, 0
        for i, raw in enumerate(lines, 1):
            line = raw.rstrip("\r\n")[:MAX_LINE]
            if not line.strip():
                continue
            e = self.parse_line(line, i)
            if e:
                if cur:
                    yield cur
                    n += 1
                    if n >= max_entries:
                        return
                cur = e
            elif cur:
                if len(cur.continuation) < 200:
                    cur.continuation.append(line)
            else:
                cur = LogEntry(i, None, None, "", line)
        if cur:
            yield cur

    def parse_file(self, path: str, max_entries: int = 500_000, encoding: str = "utf-8-sig") -> Iterator[LogEntry]:
        with open(path, "r", encoding=encoding, errors="replace") as f:
            yield from self.parse_lines(f, max_entries)
