from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QDoubleSpinBox, QFileDialog, QFrame, QGridLayout, QHBoxLayout,
                               QHeaderView, QLabel, QLineEdit, QListWidget, QMainWindow, QMenu, QMessageBox,
                               QPlainTextEdit, QPushButton, QSplitter, QStackedWidget, QTableWidget,
                               QTableWidgetItem, QTabWidget, QToolButton, QVBoxLayout, QWidget)

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
        self.setWindowTitle("Vitals")
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

        root = QWidget()
        self.setCentralWidget(root)
        outer = QHBoxLayout(root)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        side = QWidget()
        side.setObjectName("sidebar")
        side.setFixedWidth(190)
        sv = QVBoxLayout(side)
        sv.setContentsMargins(12, 16, 12, 12)
        brand = QLabel("Vitals")
        brand.setObjectName("brand")
        sv.addWidget(brand)
        self.nav = QListWidget()
        self.nav.setObjectName("nav")
        self.stack = QStackedWidget()
        pages = [("System", "Live resource usage", self._build_monitor()),
                 ("Processes", "Top processes by CPU", self._build_processes()),
                 ("Logs", "Search, filter and group log entries", self._build_logs()),
                 ("Diagnostics", "Rule matches on measured data", self._build_diag())]
        for name, sub, body in pages:
            self.nav.addItem(name)
            self.stack.addWidget(self._page(name, sub, body))
        self.nav.currentRowChanged.connect(self.stack.setCurrentIndex)
        self.nav.setCurrentRow(0)
        sv.addWidget(self.nav, 1)
        foot = QLabel("Local only. Nothing is uploaded.")
        foot.setProperty("muted", True)
        foot.setWordWrap(True)
        sv.addWidget(foot)
        outer.addWidget(side)
        outer.addWidget(self.stack, 1)
        self.status = self.statusBar()
        self.status.showMessage("Collecting... all data stays on this machine.")

        self.sampler = SamplerThread(self.cfg["refresh_s"])
        self.sampler.sampled.connect(self.on_sample)
        self.sampler.start()

    def _page(self, title, subtitle, body, actions=None):
        """Standard page: heading + muted subtitle (+ optional action row) above the body."""
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(24, 18, 24, 12)
        v.setSpacing(12)
        head = QHBoxLayout()
        col = QVBoxLayout()
        col.setSpacing(0)
        h = QLabel(title)
        h.setObjectName("pageTitle")
        s = QLabel(subtitle)
        s.setProperty("muted", True)
        col.addWidget(h)
        col.addWidget(s)
        head.addLayout(col, 1)
        for a in getattr(body, "page_actions", []):
            head.addWidget(a)
        v.addLayout(head)
        v.addWidget(body, 1)
        return w

    # ---- System page
    def _build_monitor(self):
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(12)
        lbl = QLabel("Refresh every")
        lbl.setProperty("muted", True)
        self.interval = QDoubleSpinBox()
        self.interval.setRange(0.5, 60)
        self.interval.setSuffix(" s")
        self.interval.setValue(self.cfg["refresh_s"])
        self.interval.valueChanged.connect(self.on_interval)
        c = QPushButton("Clear history")
        c.clicked.connect(self.history.clear)
        b = QPushButton("Export report")
        b.setProperty("primary", True)
        b.clicked.connect(self.export_report)
        w.page_actions = [lbl, self.interval, c, b]
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
        v.setContentsMargins(0, 0, 0, 0)
        self.proc_table = table(["PID", "Name", "CPU %", "Memory (RSS)"])
        self.proc_table.horizontalHeader().setSortIndicator(2, Qt.DescendingOrder)
        note = QLabel("CPU % is per core and can exceed 100 on multi-core systems. n/a = access denied.")
        note.setProperty("muted", True)
        v.addWidget(self.proc_table)
        v.addWidget(note)
        return w

    # ---- Logs tab
    def _build_logs(self):
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(10)
        ob = QPushButton("Open log")
        ob.setProperty("primary", True)
        ob.clicked.connect(self.open_log)
        eb = QToolButton()
        eb.setText("Export filtered")
        eb.setPopupMode(QToolButton.InstantPopup)
        menu = QMenu(eb)
        for fmt, label in (("csv", "CSV"), ("json", "JSON"), ("text", "Text")):
            menu.addAction(label, lambda f=fmt: self.export_logs(f))
        eb.setMenu(menu)
        w.page_actions = [eb, ob]

        card = QFrame()
        card.setObjectName("tile")
        cv = QVBoxLayout(card)
        cv.setContentsMargins(12, 10, 12, 10)
        cv.setSpacing(8)
        r1 = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search message text")
        self.search.returnPressed.connect(self.refilter)
        r1.addWidget(self.search, 1)
        self.source = QLineEdit()
        self.source.setPlaceholderText("Source contains")
        self.source.setMaximumWidth(160)
        self.source.returnPressed.connect(self.refilter)
        r1.addWidget(self.source)
        self.regex_cb = QCheckBox("Regex")
        self.case_cb = QCheckBox("Match case")
        r1.addWidget(self.regex_cb)
        r1.addWidget(self.case_cb)
        cv.addLayout(r1)
        r2 = QHBoxLayout()
        self.level_cbs = {}
        for lv in LEVELS:
            cb = QCheckBox(lv.capitalize())
            cb.setChecked(True)
            self.level_cbs[lv] = cb
            r2.addWidget(cb)
        r2.addStretch()
        self.start = QLineEdit()
        self.start.setPlaceholderText("From date")
        self.end = QLineEdit()
        self.end.setPlaceholderText("To date")
        for e in (self.start, self.end):
            e.setMaximumWidth(150)
            e.setToolTip("YYYY-MM-DD or YYYY-MM-DD HH:MM[:SS]")
            e.returnPressed.connect(self.refilter)
            r2.addWidget(e)
        ab = QPushButton("Apply filters")
        ab.clicked.connect(self.refilter)
        r2.addWidget(ab)
        cv.addLayout(r2)
        v.addWidget(card)

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
        v.setContentsMargins(0, 0, 0, 0)
        self.alert_summary = QLabel("No alerts.")
        self.alert_summary.setObjectName("badge")
        note = QLabel("An alert means a configured threshold rule matched measured data. It is not a confirmed "
                      "fault. Rules are set in the config file.")
        note.setProperty("muted", True)
        note.setWordWrap(True)
        self.alert_table = table(["Type", "Basis", "Alert", "Detail"])
        v.addWidget(self.alert_summary, 0, Qt.AlignLeft)
        v.addWidget(note)
        v.addWidget(self.alert_table, 1)
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
        n = len(alerts)
        self.alert_summary.setText(f"{n} alert{'s' if n != 1 else ''} (rule matches)" if n else "No alerts")
        self.alert_summary.setProperty("active", bool(n))
        self.alert_summary.style().unpolish(self.alert_summary)
        self.alert_summary.style().polish(self.alert_summary)
        item = self.nav.item(3)
        if item:
            item.setText(f"Diagnostics ({n})" if n else "Diagnostics")

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

    def _levels(self):
        """None (no level filter) when every box is ticked, so entries without a recognised level stay visible."""
        picked = {k for k, c in self.level_cbs.items() if c.isChecked()}
        return None if len(picked) == len(self.level_cbs) else picked

    def refilter(self):
        try:
            f = analysis.LogFilter(
                self.search.text(), self.regex_cb.isChecked(), self.case_cb.isChecked(),
                self._levels(), self.source.text(),
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
        path, _ = QFileDialog.getSaveFileName(self, "Export report", "vitals-report.txt", "Text (*.txt);;JSON (*.json)")
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
