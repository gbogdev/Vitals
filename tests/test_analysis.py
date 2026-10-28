from datetime import datetime

import pytest

from devscope.analysis import (LogFilter, apply_filter, context, export_entries,
                               group_recurring, normalize_message)
from devscope.logparse import LogParser

LINES = [
    "2024-03-01 10:00:00 INFO a.x: started",
    "2024-03-01 10:00:01 ERROR a.db: timeout after 30s on conn 101",
    "2024-03-01 10:00:02 ERROR a.db: timeout after 45s on conn 102",
    "2024-03-01 10:00:03 WARNING a.net: retry",
    "2024-03-01 10:00:04 ERROR a.net: refused",
]
E = list(LogParser().parse_lines(LINES))


def test_filter_text_level_source():
    assert len(apply_filter(E, LogFilter(text="TIMEOUT"))) == 2
    assert len(apply_filter(E, LogFilter(text="TIMEOUT", case_sensitive=True))) == 0
    assert len(apply_filter(E, LogFilter(levels={"ERROR"}))) == 3
    assert len(apply_filter(E, LogFilter(source="net"))) == 2
    assert len(apply_filter(E, LogFilter(text=r"conn \d+$", regex=True))) == 2


def test_filter_time_range():
    f = LogFilter(start=datetime(2024, 3, 1, 10, 0, 2), end=datetime(2024, 3, 1, 10, 0, 3))
    assert [e.lineno for e in apply_filter(E, f)] == [3, 4]


def test_bad_regex_raises():
    import re
    with pytest.raises(re.error):
        apply_filter(E, LogFilter(text="(", regex=True))


def test_grouping_normalizes_numbers():
    g = group_recurring(E)
    assert g[0].count == 2 and g[0].key == "timeout after <n>s on conn <n>"
    assert len(g) == 2
    assert group_recurring(E, min_count=2)[0].count == 2 and len(group_recurring(E, min_count=2)) == 1


def test_normalize_message():
    assert normalize_message("id 3f2b8c1e-aaaa-bbbb-cccc-1234567890ab at 0xDEAD v1.2.3") == "id <uuid> at <hex> v<n>"


def test_context_bounds():
    assert len(context(E, 0, 2, 2)) == 3
    assert len(context(E, 2, 1, 1)) == 3
    assert context(E, 4, 1, 5) == E[3:]


def test_export_formats():
    assert export_entries(E[:1], "csv").splitlines()[0] == "line,timestamp,level,source,message"
    assert '"level": "ERROR"' in export_entries(E[1:2], "json")
    assert "refused" in export_entries(E[4:], "text")
    with pytest.raises(ValueError):
        export_entries(E, "xml")
