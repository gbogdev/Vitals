from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QDoubleSpinBox, QFileDialog, QGridLayout, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
                               QMainWindow, QMessageBox, QPlainTextEdit, QPushButton, QSplitter, QTableWidget,
                               QTableWidgetItem, QTabWidget, QVBoxLayout, QWidget)

import re
from bisect import bisect_left

from .. import analysis
from ..config import load_config, save_config
from ..diagnostics import check_log_rules, check_resource_rules
from ..logparse import LEVELS
from ..monitor import History
from ..report import build_report, log_summary, report_json, report_text
from .widgets import LineChart, StatTile
from .workers import FilterThread, LogLoadThread, SamplerThread


def human(n):
    if n is None:
        return "n/a"
    n = float(n)
    for u in ("B", "KB", "MB", "GB", "TB"):
        if abs(n) < 1024:
            return f"{n:.1f} {u}"
        n /= 1024
    return f"{n:.1f} PB"


def table(headers):
    t = QTableWidget(0, len(headers))
    t.setHorizontalHeaderLabels(headers)
    t.setEditTriggers(QTableWidget.NoEditTriggers)
    t.setSelectionBehavior(QTableWidget.SelectRows)
    t.setAlternatingRowColors(True)
    t.verticalHeader().setVisible(False)
    h = t.horizontalHeader()
    h.setStretchLastSection(True)
    h.setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
    h.setSectionResizeMode(QHeaderView.ResizeToContents)
    h.setSortIndicator(0, Qt.AscendingOrder)
    return t


def fill(t, rows):
    t.setSortingEnabled(False)
    t.setUpdatesEnabled(False)
    t.setRowCount(len(rows))
    for r, row in enumerate(rows):
        for c, v in enumerate(row):
            it = QTableWidgetItem()
            it.setData(Qt.DisplayRole, v)
            t.setItem(r, c, it)
    t.setUpdatesEnabled(True)
    t.setSortingEnabled(True)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("DevScope")
        self.resize(1100, 700)
        self.cfg = load_config()
        self.history = History(self.cfg["history_samples"])
        self.entries: list = []
        self.filtered: list = []
        self.groups: list = []
        self.loader = None
        self.filt = None
        self._refilter_pending = False
        self.all_groups: list = []
        self.alerts: list = []

        tabs = QTabWidget()
        self.setCentralWidget(tabs)
        tabs.addTab(self._build_monitor(), "System")
        tabs.addTab(self._build_processes(), "Processes")
        tabs.addTab(self._build_logs(), "Logs")
        tabs.addTab(self._build_diag(), "Diagnostics")
        self.status = self.statusBar()
        self.status.showMessage("Collecting... all data stays on this machine.")

        self.sampler = SamplerThread(self.cfg["refresh_s"])
        self.sampler.sampled.connect(self.on_sample)
        self.sampler.start()

    # ---- System tab
    def _build_monitor(self):
        w = QWidget()
        v = QVBoxLayout(w)
        bar = QHBoxLayout()
        bar.addWidget(QLabel("Refresh (s):"))
        self.interval = QDoubleSpinBox()
        self.interval.setRange(0.5, 60)
        self.interval.setValue(self.cfg["refresh_s"])
        self.interval.valueChanged.connect(self.on_interval)
        bar.addWidget(self.interval)
        b = QPushButton("Export report...")
        b.clicked.connect(self.export_report)
        bar.addWidget(b)
        c = QPushButton("Clear history")
        c.clicked.connect(self.history.clear)
        bar.addWidget(c)
        bar.addStretch()
        v.addLayout(bar)
        self.tiles = {k: StatTile(t) for k, t in
                      (("cpu", "CPU"), ("mem", "Memory"), ("disk", "Disk"), ("net", "Network"))}
        row = QHBoxLayout()
        for t in self.tiles.values():
            row.addWidget(t)
        v.addLayout(row)
        self.charts = {
            "cpu": LineChart("CPU"), "mem_percent": LineChart("Memory"),
            "net_recv_bps": LineChart("Network down", " B/s", None, "#6aa58a"),
            "net_sent_bps": LineChart("Network up", " B/s", None, "#b99a63"),
        }
        grid = QGridLayout()
        for i, ch in enumerate(self.charts.values()):
            grid.addWidget(ch, i // 2, i % 2)
        v.addLayout(grid, 1)
        self.sys_info = QLabel("")
        self.sys_info.setProperty("muted", True)
        v.addWidget(self.sys_info)
        return w

    def _build_processes(self):
        w = QWidget()
        v = QVBoxLayout(w)
        self.proc_table = table(["PID", "Name", "CPU %", "Memory (RSS)"])
        self.proc_table.horizontalHeader().setSortIndicator(2, Qt.DescendingOrder)
        v.addWidget(QLabel("Top processes by CPU (CPU % is per-core; n/a = access denied)"))
        v.addWidget(self.proc_table)
        return w

    # ---- Logs tab
    def _build_logs(self):
        w = QWidget()
        v = QVBoxLayout(w)
        r1 = QHBoxLayout()
        ob = QPushButton("Open log...")
        ob.clicked.connect(self.open_log)
        r1.addWidget(ob)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search message text")
        self.search.returnPressed.connect(self.refilter)
        r1.addWidget(self.search, 1)
        self.regex_cb = QCheckBox("Regex")
        self.case_cb = QCheckBox("Match case")
        r1.addWidget(self.regex_cb)
        r1.addWidget(self.case_cb)
        self.source = QLineEdit()
        self.source.setPlaceholderText("Source contains")
        self.source.setMaximumWidth(150)
        self.source.returnPressed.connect(self.refilter)
        r1.addWidget(self.source)
        v.addLayout(r1)
        r2 = QHBoxLayout()
        self.level_cbs = {}
        for lv in LEVELS:
            cb = QCheckBox(lv)
            cb.setChecked(True)
            self.level_cbs[lv] = cb
            r2.addWidget(cb)
        self.start = QLineEdit()
        self.start.setPlaceholderText("From YYYY-MM-DD[ HH:MM:SS]")
        self.end = QLineEdit()
        self.end.setPlaceholderText("To YYYY-MM-DD[ HH:MM:SS]")
        r2.addWidget(self.start)
        r2.addWidget(self.end)
        ab = QPushButton("Apply")
        ab.clicked.connect(self.refilter)
        r2.addWidget(ab)
        for fmt in ("csv", "json", "text"):
            b = QPushButton(f"Export {fmt}")
            b.clicked.connect(lambda _=False, f=fmt: self.export_logs(f))
            r2.addWidget(b)
        v.addLayout(r2)

        split = QSplitter(Qt.Vertical)
        self.log_table = table(["Line", "Time", "Level", "Source", "Message"])
        self.log_table.itemSelectionChanged.connect(self.show_context)
        split.addWidget(self.log_table)
        bottom = QTabWidget()
        self.ctx = QPlainTextEdit()
        self.ctx.setReadOnly(True)
        bottom.addTab(self.ctx, "Context (5 before / after)")
        self.group_table = table(["Count", "Level", "First", "Last", "Message pattern"])
        bottom.addTab(self.group_table, "Recurring errors")
        split.addWidget(bottom)
        split.setSizes([400, 200])
        v.addWidget(split)
        return w

    def _build_diag(self):
        w = QWidget()
        v = QVBoxLayout(w)
        v.addWidget(QLabel("Alerts: a configured threshold rule matched measured data. "
                           "An alert is not a confirmed fault. Rules are in the config file."))
        self.alert_table = table(["Type", "Basis", "Alert", "Detail"])
        v.addWidget(self.alert_table)
        return w

    # ---- slots
    def on_interval(self, val):
        self.cfg["refresh_s"] = val
        self.sampler.set_interval(val)
        try:
            save_config(self.cfg)
        except OSError:
            pass

    def on_sample(self, s):
        self.history.add(s)
        for k, ch in self.charts.items():
            ch.set_values(self.history.series(k))
        pct = lambda v: "n/a" if v is None else f"{v:.1f}%"
        self.tiles["cpu"].set(pct(s.cpu), "measured")
        self.tiles["mem"].set(pct(s.mem_percent), f"{human(s.mem_used)} / {human(s.mem_total)}")
        self.tiles["disk"].set(pct(s.disk_percent), f"{human(s.disk_used)} / {human(s.disk_total)}")
        self.tiles["net"].set(f"↓ {human(s.net_recv_bps)}/s", f"↑ {human(s.net_sent_bps)}/s")
        self.sys_info.setText(f"Samples kept: {len(self.history)} (oldest are dropped at the configured limit). "
                              "All values are measured.")
        if s.errors:
            self.status.showMessage("Unavailable: " + "; ".join(s.errors[:3]))
        rows = [(p.pid, p.name, "n/a" if p.cpu is None else round(p.cpu, 1), "n/a" if p.rss is None else human(p.rss))
                for p in s.procs[:100]]
        fill(self.proc_table, rows)
        self.refresh_alerts()

    def refresh_alerts(self):
        alerts = check_resource_rules(self.history.samples(), self.cfg["resource_rules"])
        alerts += check_log_rules(self.all_groups, self.cfg["log_rule"])
        self.alerts = alerts
        fill(self.alert_table, [(a.kind, a.basis, a.title, a.detail) for a in alerts])

    def open_log(self):
        path, _ = QFileDialog.getOpenFileName(self, "Open log", "", "Logs (*.log *.txt *.out);;All files (*)")
        if not path:
            return
        if self.loader and self.loader.isRunning():
            self.loader.stop()
            self.loader.wait()
        self.loader = LogLoadThread(path, self.cfg["parse_rules"], self.cfg["max_log_entries"])
        self.loader.progress.connect(lambda n: self.status.showMessage(f"Parsing... {n} entries"))
        self.loader.finished_ok.connect(self.on_loaded)
        self.loader.failed.connect(lambda m: QMessageBox.warning(self, "Log error", m))
        self.status.showMessage("Parsing...")
        self.loader.start()

    def on_loaded(self, entries, truncated):
        self.entries = entries
        self.all_groups = analysis.group_recurring(entries, self.cfg["log_rule"]["min_level"])
        msg = f"Loaded {len(entries)} entries"
        if truncated:
            msg += f" (stopped at limit {self.cfg['max_log_entries']})"
        self.status.showMessage(msg)
        self.refilter()

    def _parse_dt(self, text):
        text = text.strip()
        if not text:
            return None
        for f in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
            try:
                return datetime.strptime(text, f)
            except ValueError:
                pass
        raise ValueError(f"Bad date: {text}")

    def refilter(self):
        try:
            f = analysis.LogFilter(
                self.search.text(), self.regex_cb.isChecked(), self.case_cb.isChecked(),
                {k for k, c in self.level_cbs.items() if c.isChecked()}, self.source.text(),
                self._parse_dt(self.start.text()), self._parse_dt(self.end.text()))
            if f.text and f.regex:
                re.compile(f.text)  # fail fast on syntax errors before starting the worker
        except (ValueError, re.error) as ex:
            QMessageBox.warning(self, "Filter", str(ex))
            return
        if self.filt and self.filt.isRunning():
            self._refilter_pending = True  # rerun with the latest inputs when the current run ends
            return
        self.status.showMessage("Filtering...")
        self.filt = FilterThread(self.entries, f)
        self.filt.done.connect(self.on_filtered)
        self.filt.failed.connect(lambda m: QMessageBox.warning(self, "Filter", m))
        self.filt.finished.connect(self._filter_finished)
        self.filt.start()

    def _filter_finished(self):
        if self._refilter_pending:
            self._refilter_pending = False
            self.refilter()

    def on_filtered(self, filtered):
        self.filtered = filtered
        shown = self.filtered[:20000]  # keep table responsive; export uses the full filtered list
        fill(self.log_table, [(e.lineno, str(e.timestamp or ""), e.level or "", e.source, e.message) for e in shown])
        self.groups = analysis.group_recurring(self.filtered, self.cfg["log_rule"]["min_level"])
        fill(self.group_table, [(g.count, g.level, str(g.first or ""), str(g.last or ""), g.key) for g in self.groups])
        extra = f" (showing first {len(shown)})" if len(shown) < len(self.filtered) else ""
        self.status.showMessage(f"{len(self.filtered)} of {len(self.entries)} entries match{extra}")
        self.refresh_alerts()

    def show_context(self):
        rows = self.log_table.selectionModel().selectedRows()
        if not rows or not self.entries:
            return
        # The table may be user-sorted, so identify the entry by its line number, not its row.
        lineno = self.log_table.item(rows[0].row(), 0).data(Qt.DisplayRole)
        idx = bisect_left(self.entries, lineno, key=lambda x: x.lineno)  # entries are in file order
        if idx >= len(self.entries) or self.entries[idx].lineno != lineno:
            return
        e = self.entries[idx]
        lines = []
        for x in analysis.context(self.entries, idx):
            mark = ">>" if x is e else "  "
            lines.append(f"{mark} {x.lineno}: {x.timestamp or ''} {x.level or ''} {x.source} {x.full_text}")
        self.ctx.setPlainText("\n".join(lines))

    def export_logs(self, fmt):
        if not self.filtered:
            QMessageBox.information(self, "Export", "No filtered entries to export.")
            return
        path, _ = QFileDialog.getSaveFileName(self, "Export", f"filtered.{ 'txt' if fmt == 'text' else fmt}")
        if path:
            with open(path, "w", encoding="utf-8", newline="") as fh:
                fh.write(analysis.export_entries(self.filtered, fmt))

    def export_report(self):
        path, _ = QFileDialog.getSaveFileName(self, "Export report", "devscope-report.txt", "Text (*.txt);;JSON (*.json)")
        if not path:
            return
        summ = log_summary(self.filtered or self.entries, self.groups) if self.entries else None
        rep = build_report(self.history.samples(), getattr(self, "alerts", []), summ)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(report_json(rep) if path.endswith(".json") else report_text(rep))

    def closeEvent(self, ev):
        self.sampler.stop()
        self.sampler.wait(5000)
        if self.loader and self.loader.isRunning():
            self.loader.stop()
            self.loader.wait(5000)
        if self.filt and self.filt.isRunning():
            self.filt.wait(5000)
        super().closeEvent(ev)
