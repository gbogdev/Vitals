"""Local JSON settings: refresh interval, rules, parsing rules. Stored under the user's profile."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Optional

from .diagnostics import DEFAULT_LOG_RULE, DEFAULT_RESOURCE_RULES
from .logparse import DEFAULT_RULES


def default_config() -> dict:
    return {"refresh_s": 2.0, "history_samples": 3600, "max_log_entries": 500_000,
            "resource_rules": DEFAULT_RESOURCE_RULES, "log_rule": DEFAULT_LOG_RULE, "parse_rules": DEFAULT_RULES}


def config_path() -> Path:
    env = os.environ.get("DEVSCOPE_CONFIG")
    return Path(env) if env else Path(os.environ.get("APPDATA", Path.home())) / "DevScope" / "config.json"


def load_config(path: Optional[Path] = None) -> dict:
    cfg = default_config()
    try:
        cfg.update(json.loads((path or config_path()).read_text(encoding="utf-8")))
    except (OSError, ValueError):
        pass  # missing or invalid file: defaults
    return cfg


def save_config(cfg: dict, path: Optional[Path] = None) -> None:
    p = path or config_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
