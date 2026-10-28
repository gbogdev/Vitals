import json
from datetime import datetime

from devscope.analysis import group_recurring
from devscope.diagnostics import check_log_rules, check_resource_rules
from devscope.logparse import LogParser
from devscope.monitor import Collector, History, Sample, aggregate, summarize
from devscope.report import build_report, log_summary, report_json, report_text


def mk(vals, key="cpu", step=10.0):
    return [Sample(ts=i * step, **{key: v}) for i, v in enumerate(vals)]


def test_aggregate_ignores_none():
    a = aggregate([10, None, 30])
    assert (a["min"], a["avg"], a["max"], a["count"], a["missing"]) == (10, 20, 30, 2, 1)
    assert aggregate([None])["avg"] is None


def test_summarize_missing_metric():
    s = summarize(mk([50, 70]))
    assert s["cpu"]["avg"] == 60 and s["mem_percent"]["count"] == 0


def test_history_bounded():
    h = History(max_samples=5)
    for s in mk(range(20)):
        h.add(s)
    assert len(h) == 5 and h.series("cpu") == [15, 16, 17, 18, 19]


RULE = [{"metric": "cpu", "label": "CPU", "threshold": 90, "duration_s": 30}]


def test_sustained_alert_fires():
    assert len(check_resource_rules(mk([10, 95, 95, 95, 95]), RULE)) == 1  # 30s span


def test_short_spike_no_alert():
    assert check_resource_rules(mk([10, 95, 95, 10]), RULE) == []
    assert check_resource_rules(mk([95, 95, 95, 95, 10]), RULE) == []  # latest is below


def test_missing_value_breaks_run():
    assert check_resource_rules(mk([95, 95, None, 95, 95]), RULE) == []


def test_alert_wording_is_not_fault():
    a = check_resource_rules(mk([95] * 5), RULE)[0]
    assert a.status == "alert" and a.basis == "measured" and "not a confirmed fault" in a.detail


LOG = [f"2024-03-01 10:00:0{i} ERROR a: fail {i}" for i in range(6)] + ["2024-03-01 10:00:09 ERROR b: once"]


def test_log_rule():
    g = group_recurring(list(LogParser().parse_lines(LOG)))
    al = check_log_rules(g, {"min_level": "ERROR", "min_count": 5})
    assert len(al) == 1 and "6x" in al[0].title


def test_report_contents():
    entries = list(LogParser().parse_lines(LOG))
    groups = group_recurring(entries)
    alerts = check_log_rules(groups, {"min_level": "ERROR", "min_count": 5})
    r = build_report(mk([10, 20, None]), alerts, log_summary(entries, groups), now=datetime(2024, 1, 1))
    assert r["generated"] == "2024-01-01T00:00:00" and r["samples"] == 3
    assert json.loads(report_json(r))["metrics_measured"]["cpu"]["avg"] == 15
    t = report_text(r)
    assert "not confirmed faults" in t and "1 unavailable" in t and "6x" in t


def test_report_empty():
    r = build_report([], [])
    assert r["period"] is None and "none" in report_text(r)


def test_collector_live_sample():
    c = Collector()
    c.sample()
    s = c.sample()
    assert s.ts > 0 and (s.cpu is None or 0 <= s.cpu <= 100) and isinstance(s.errors, list)
