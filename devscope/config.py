"""Local JSON settings: refresh interval, rules, parsing rules. Stored under the user's profile."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Optional

from .diagnostics import DEFAULT_LOG_RULE, DEFAULT_RESOURCE_RULES
from .logparse import DEFAULT_RULES, LEVELS
from .monitor import METRICS


def default_config() -> dict:
    return {"refresh_s": 2.0, "history_samples": 3600, "max_log_entries": 500_000,
            "resource_rules": DEFAULT_RESOURCE_RULES, "log_rule": DEFAULT_LOG_RULE, "parse_rules": DEFAULT_RULES}


def config_path() -> Path:
    env = os.environ.get("DEVSCOPE_CONFIG")
    return Path(env) if env else Path(os.environ.get("APPDATA", Path.home())) / "DevScope" / "config.json"


def load_config(path: Optional[Path] = None) -> dict:
    cfg = default_config()
    try:
        user = json.loads((path or config_path()).read_text(encoding="utf-8"))
        if isinstance(user, dict):
            cfg.update(user)
    except (OSError, ValueError):
        pass  # missing or invalid file: defaults
    return _sanitize(cfg)


def _num(v, lo, hi, default):
    ok = isinstance(v, (int, float)) and not isinstance(v, bool)
    return min(max(v, lo), hi) if ok else default


def _sanitize(cfg: dict) -> dict:
    """Replace malformed values with defaults so a hand-edited file cannot crash the app."""
    d = default_config()
    cfg["refresh_s"] = _num(cfg["refresh_s"], 0.5, 60, d["refresh_s"])
    cfg["history_samples"] = int(_num(cfg["history_samples"], 10, 100_000, d["history_samples"]))
    cfg["max_log_entries"] = int(_num(cfg["max_log_entries"], 1000, 5_000_000, d["max_log_entries"]))
    rr = cfg["resource_rules"]
    ok = isinstance(rr, list) and all(
        isinstance(r, dict) and r.get("metric") in METRICS
        and _num(r.get("threshold"), 0, 1e12, None) is not None
        and _num(r.get("duration_s", 0), 0, 1e9, None) is not None for r in rr)
    cfg["resource_rules"] = rr if ok else d["resource_rules"]
    lr = cfg["log_rule"]
    ok = isinstance(lr, dict) and lr.get("min_level") in LEVELS and _num(lr.get("min_count"), 1, 1e9, None) is not None
    cfg["log_rule"] = lr if ok else d["log_rule"]
    pr = cfg["parse_rules"]
    ok = isinstance(pr, list) and pr and all(isinstance(r, dict) and isinstance(r.get("pattern"), str) for r in pr)
    cfg["parse_rules"] = pr if ok else d["parse_rules"]
    return cfg


def save_config(cfg: dict, path: Optional[Path] = None) -> None:
    p = path or config_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    os.replace(tmp, p)  # atomic: a crash mid-write cannot leave a truncated config
