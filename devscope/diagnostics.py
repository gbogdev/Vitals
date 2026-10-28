"""Threshold rules. These are plain configurable comparisons, not predictive models.

An Alert means a rule condition was met by measured data. It is not a confirmed fault.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

DEFAULT_RESOURCE_RULES = [
    {"metric": "cpu", "label": "CPU", "threshold": 90.0, "duration_s": 30.0},
    {"metric": "mem_percent", "label": "Memory", "threshold": 90.0, "duration_s": 30.0},
    {"metric": "disk_percent", "label": "Disk usage", "threshold": 90.0, "duration_s": 0.0},
]
DEFAULT_LOG_RULE = {"min_level": "ERROR", "min_count": 5}


@dataclass
class Alert:
    kind: str                 # "resource" | "log"
    title: str
    detail: str
    basis: str = "measured"   # these rules only use measured values; no estimates
    status: str = "alert"     # condition met, cause not confirmed


def check_resource_rules(samples: list, rules: Optional[list] = None) -> list:
    """Alert when the most recent samples have all exceeded threshold for >= duration_s.
    A missing value breaks the run (unknown is not treated as high)."""
    alerts = []
    for r in rules or DEFAULT_RESOURCE_RULES:
        m, thr, dur = r["metric"], r["threshold"], r.get("duration_s", 0.0)
        run = []
        for s in reversed(samples):
            v = getattr(s, m, None)
            if v is None or v < thr:
                break
            run.append(s)
        if not run:
            continue
        span = run[0].ts - run[-1].ts
        if span >= dur:
            peak = max(getattr(s, m) for s in run)
            alerts.append(Alert("resource", f"{r.get('label', m)} above {thr:g}%",
                                f"Measured >= {thr:g}% for {span:.0f}s across {len(run)} samples "
                                f"(peak {peak:.1f}%). Rule requires {dur:g}s. Alert, not a confirmed fault."))
    return alerts


def check_log_rules(groups: list, rule: Optional[dict] = None) -> list:
    """groups: output of analysis.group_recurring."""
    rule = rule or DEFAULT_LOG_RULE
    return [Alert("log", f"Recurring {g.level}: {g.count}x",
                  f"{g.key[:200]} (first {g.first or 'n/a'}, last {g.last or 'n/a'}). "
                  f"Rule: >= {rule['min_count']} occurrences. Recurrence alone does not establish a cause.")
            for g in groups if g.count >= rule["min_count"]]
