"""Diagnostic report generation (local files only)."""
from __future__ import annotations

import json
import platform
from datetime import datetime
from typing import Optional

from .monitor import METRICS, summarize

_UNITS = {"cpu": "%", "mem_percent": "%", "disk_percent": "%", "net_sent_bps": " B/s", "net_recv_bps": " B/s"}


def build_report(samples: list, alerts: list, log_summary: Optional[dict] = None,
                 now: Optional[datetime] = None) -> dict:
    now = now or datetime.now()
    return {
        "generated": now.isoformat(timespec="seconds"),
        "host": {"os": platform.platform(), "python": platform.python_version()},
        "samples": len(samples),
        "period": {"start": samples[0].ts, "end": samples[-1].ts} if samples else None,
        "metrics_measured": summarize(samples),
        "alerts": [a.__dict__ for a in alerts],
        "logs": log_summary,
        "notes": ["Metric values are measured; none are estimated.",
                  "Alerts mean a configured threshold rule matched; they are not confirmed faults.",
                  "Unavailable readings are excluded from aggregates and counted."],
    }


def report_json(report: dict) -> str:
    return json.dumps(report, indent=2, default=str)


def _fmt(v, unit):
    return "n/a" if v is None else f"{v:.1f}{unit}"


def report_text(report: dict) -> str:
    L = [f"DevScope diagnostic report - {report['generated']}",
         f"Host: {report['host']['os']} (Python {report['host']['python']})",
         f"Samples: {report['samples']}", "", "Measured metrics (min / avg / max):"]
    for m in METRICS:
        a = report["metrics_measured"][m]
        u = _UNITS[m]
        L.append(f"  {m:<14} {_fmt(a['min'], u)} / {_fmt(a['avg'], u)} / {_fmt(a['max'], u)}"
                 f"  ({a['count']} readings, {a['missing']} unavailable)")
    L += ["", f"Alerts ({len(report['alerts'])}) - rule matches, not confirmed faults:"]
    L += [f"  [{a['kind']}] {a['title']}: {a['detail']}" for a in report["alerts"]] or ["  none"]
    if report.get("logs"):
        lg = report["logs"]
        L += ["", f"Logs: {lg.get('entries', 0)} entries; by level: {lg.get('by_level', {})}"]
        for g in lg.get("top_groups", []):
            L.append(f"  {g['count']}x [{g['level']}] {g['key'][:120]}")
    L += ["", *report["notes"]]
    return "\n".join(L) + "\n"


def log_summary(entries: list, groups: list, top: int = 10) -> dict:
    by: dict = {}
    for e in entries:
        k = e.level or "UNKNOWN"
        by[k] = by.get(k, 0) + 1
    return {"entries": len(entries), "by_level": by,
            "top_groups": [{"count": g.count, "level": g.level, "key": g.key} for g in groups[:top]]}
