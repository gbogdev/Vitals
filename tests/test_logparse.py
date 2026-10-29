from datetime import datetime

from vitals.logparse import LogParser, normalize_level

LINES = [
    "2024-03-01 10:00:00,123 INFO [app.db] connected to 10.0.0.1",
    "2024-03-01 10:00:05 ERROR [app.db] query failed id=42",
    "Traceback (most recent call last):",
    '  File "x.py", line 1',
    "2024-03-01T10:00:09Z WARN app.net: slow response",
    "Mar  1 10:01:00 host sshd[123]: Failed password for root",
]


def parse(lines, **kw):
    return list(LogParser(default_year=2024).parse_lines(lines, **kw))


def test_fields_and_levels():
    e = parse(LINES)
    assert [x.level for x in e] == ["INFO", "ERROR", "WARNING", None]
    assert e[0].source == "app.db" and e[0].timestamp == datetime(2024, 3, 1, 10, 0, 0)
    assert e[2].source == "app.net"


def test_continuation_lines_attach():
    e = parse(LINES)
    assert len(e[1].continuation) == 2 and "Traceback" in e[1].full_text


def test_syslog_default_year():
    e = parse(LINES)[3]
    assert e.timestamp == datetime(2024, 3, 1, 10, 1, 0) and e.source == "sshd"


def test_unparsed_leading_line_kept():
    e = parse(["garbage", "2024-03-01 10:00:00 INFO a: b"])
    assert len(e) == 2 and e[0].level is None


def test_max_entries_caps():
    lines = [f"2024-03-01 10:00:{i:02d} INFO a: m{i}" for i in range(10)]
    assert len(parse(lines, max_entries=3)) == 3


def test_custom_rule():
    rules = [{"name": "c", "pattern": r"^(?P<level>[EWI])\|(?P<source>\w+)\|(?P<message>.*)$"}]
    e = list(LogParser(rules).parse_lines(["E|core|boom"]))
    assert e[0].source == "core" and e[0].message == "boom" and e[0].level is None  # 'E' not a level name


def test_normalize_level():
    assert normalize_level("fatal") == "CRITICAL" and normalize_level("zzz") is None


def test_parse_file(tmp_path):
    p = tmp_path / "a.log"
    p.write_text("\n".join(LINES), encoding="utf-8")
    assert len(list(LogParser(default_year=2024).parse_file(str(p)))) == 4
