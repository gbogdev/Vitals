import json
import os
import sys

import pytest

from vitals.analysis import export_entries
from vitals.config import load_config, save_config
from vitals.logparse import MAX_LINE, LogParser


def entries(lines):
    return list(LogParser(default_year=2024).parse_lines(lines))


def test_csv_formula_injection_neutralized():
    e = entries(["2024-03-01 10:00:00 ERROR a: =HYPERLINK(\"http://x\")"])
    row = export_entries(e, "csv").splitlines()[1]
    assert "'=HYPERLINK" in row
    j = json.loads(export_entries(e, "json"))
    assert j[0]["message"].startswith("=")  # JSON keeps data unmodified


def test_long_line_truncated():
    e = entries(["2024-03-01 10:00:00 INFO a: " + "x" * 50_000])
    assert len(e[0].message) <= MAX_LINE


def test_bad_config_values_fall_back(tmp_path):
    p = tmp_path / "c.json"
    p.write_text(json.dumps({"refresh_s": "fast", "history_samples": -5, "resource_rules": [{"metric": "nope"}],
                             "log_rule": {"min_level": "LOUD"}, "parse_rules": [{"no": "pattern"}]}))
    c = load_config(p)
    assert c["refresh_s"] == 2.0 and c["history_samples"] == 10
    assert c["resource_rules"][0]["metric"] == "cpu" and c["log_rule"]["min_level"] == "ERROR"
    assert "pattern" in c["parse_rules"][0]


def test_non_object_and_corrupt_config(tmp_path):
    p = tmp_path / "c.json"
    p.write_text("[1,2]")
    assert load_config(p)["refresh_s"] == 2.0
    p.write_text("{not json")
    assert load_config(p)["refresh_s"] == 2.0


def test_save_config_roundtrip_atomic(tmp_path):
    p = tmp_path / "sub" / "c.json"
    c = load_config(tmp_path / "missing.json")
    c["refresh_s"] = 5
    save_config(c, p)
    assert load_config(p)["refresh_s"] == 5 and not list(p.parent.glob("*.tmp"))


def test_ui_load_filter_context_close(tmp_path, monkeypatch):
    """End to end: load -> filter in worker thread -> context picks the right duplicate -> clean shutdown."""
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    monkeypatch.setenv("VITALS_CONFIG", str(tmp_path / "cfg.json"))
    from PySide6.QtWidgets import QApplication
    from vitals.ui.main_window import MainWindow

    app = QApplication.instance() or QApplication(sys.argv)
    log = tmp_path / "a.log"
    # two identical-looking ERROR entries; selecting the second must show the second as the focus line
    log.write_text("\n".join(["2024-03-01 10:00:00 ERROR a: boom"] * 2 + ["2024-03-01 10:00:01 INFO a: ok"]))
    w = MainWindow()
    w.on_loaded(list(LogParser().parse_file(str(log))), False)
    w.filt.wait(5000)
    app.processEvents()
    assert len(w.filtered) == 3
    w.level_cbs["INFO"].setChecked(False)
    w.refilter()
    w.filt.wait(5000)
    app.processEvents()
    assert len(w.filtered) == 2
    w.log_table.selectRow(1)
    app.processEvents()
    assert w.ctx.toPlainText().splitlines()[1].startswith(">>")
    w.close()
    assert not w.sampler.isRunning()


def test_context_correct_after_user_sorts_table(tmp_path, monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    monkeypatch.setenv("VITALS_CONFIG", str(tmp_path / "cfg.json"))
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication
    from vitals.ui.main_window import MainWindow

    app = QApplication.instance() or QApplication(sys.argv)
    lines = [f"2024-03-01 10:00:0{i} INFO a: msg{i}" for i in range(5)]
    w = MainWindow()
    w.on_loaded(list(LogParser().parse_lines(lines)), False)
    w.filt.wait(5000)
    app.processEvents()
    w.log_table.sortByColumn(0, Qt.DescendingOrder)
    w.log_table.selectRow(0)  # top row is now line 5
    app.processEvents()
    assert "msg4" in [l for l in w.ctx.toPlainText().splitlines() if l.startswith(">>")][0]
    w.close()


def test_bom_file_first_line_parsed(tmp_path):
    p = tmp_path / "bom.log"
    p.write_bytes(b"\xef\xbb\xbf2024-03-01 10:00:00 ERROR a: first\n2024-03-01 10:00:01 INFO a: second\n")
    e = list(LogParser().parse_file(str(p)))
    assert len(e) == 2 and e[0].level == "ERROR" and e[0].message == "first"


def test_unrecognised_level_entries_visible_when_all_levels_ticked(tmp_path, monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    monkeypatch.setenv("VITALS_CONFIG", str(tmp_path / "cfg.json"))
    from PySide6.QtWidgets import QApplication
    from vitals.ui.main_window import MainWindow

    app = QApplication.instance() or QApplication(sys.argv)
    w = MainWindow()
    w.on_loaded(list(LogParser().parse_lines(["no timestamp here", "2024-03-01 10:00:01 INFO a: ok"])), False)
    w.filt.wait(5000)
    app.processEvents()
    assert len(w.filtered) == 2
    w.close()
