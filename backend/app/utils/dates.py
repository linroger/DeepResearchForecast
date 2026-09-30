"""宽松日期解析工具（EXECPLAN T2.3 的基础设施）。

研究档案里的日期来自 LLM 抽取，格式不固定（ISO、斜杠、中文「年月日」、仅年月、
仅年份……）。本模块把这些都解析成 **UTC tz-aware** ``datetime``，供：

* Graphiti 边的 ``valid_at`` 双时态打点（T2.2 / T2.3）。
* ``actors.events_to_schedule`` 把 key_events 映射到模拟轮次（T1.3 / T3.8）。

``date_period`` 另给出同一日期按其精度覆盖的日历区间（日/月/年），供回测把粗粒度来源日
与钉日比较（TIME-7）。

设计原则与 actors.py 一致：**永不抛异常**，无法解析一律返回 ``None``。
"""

from __future__ import annotations

import calendar
import re
from datetime import date, datetime, timezone
from typing import Optional

# 「YYYY 年 MM 月 DD 日」/「YYYY 年 MM 月」中文格式
_CJK_YMD = re.compile(r"(\d{4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日?")
_CJK_YM = re.compile(r"(\d{4})\s*年\s*(\d{1,2})\s*月")
# 数字分隔格式 YYYY-MM-DD / YYYY/MM/DD / YYYY.MM.DD（也容忍 YYYY-M-D）
_NUM_YMD = re.compile(r"(\d{4})[\-/\.](\d{1,2})[\-/\.](\d{1,2})")
_NUM_YM = re.compile(r"(\d{4})[\-/\.](\d{1,2})")
_YEAR = re.compile(r"\b(\d{4})\b")
# date_period 的精度，从细到粗。
_PRECISIONS = ("day", "month", "year")


def _make(y: int, m: int, d: int) -> Optional[datetime]:
    try:
        return datetime(y, m, d, tzinfo=timezone.utc)
    except ValueError:
        # 容错日期溢出（如 2 月 30 日）：退回到当月 1 日
        try:
            return datetime(y, m, 1, tzinfo=timezone.utc)
        except ValueError:
            return None


def parse_as_of(value: Optional[object]) -> Optional[datetime]:
    """把宽松日期字符串解析为 UTC tz-aware ``datetime``；失败返回 ``None``。

    支持：``datetime``/``date`` 透传、``YYYY-MM-DD``、``YYYY/MM/DD``、``YYYY.MM.DD``、
    ``YYYY年MM月DD日``、``YYYY-MM``/``YYYY年MM月``（→ 当月 1 日）、纯 ``YYYY``（→ 1 月 1 日）。
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day, tzinfo=timezone.utc)
    s = str(value).strip()
    if not s:
        return None

    m = _CJK_YMD.search(s)
    if m:
        return _make(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    m = _NUM_YMD.search(s)
    if m:
        return _make(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    m = _CJK_YM.search(s)
    if m:
        return _make(int(m.group(1)), int(m.group(2)), 1)
    m = _NUM_YM.search(s)
    if m:
        return _make(int(m.group(1)), int(m.group(2)), 1)
    m = _YEAR.search(s)
    if m:
        return _make(int(m.group(1)), 1, 1)
    return None


def date_period(value: Optional[object], precision: Optional[object] = None) -> Optional[tuple[date, date]]:
    """The calendar period ``(first day, last day)`` of the date :func:`parse_as_of`
    reads from ``value`` (in UTC), or ``None`` when it reads none.

    The period follows the date's own precision: a full date (or a ``datetime`` /
    ``date``) is one day, a year-month (``YYYY-MM`` / ``YYYY年MM月``, or a full date
    whose day does not exist in its month, which parse_as_of reads as the month's
    first day) is that month, and a bare ``YYYY`` is that year.  ``precision`` (a
    declared ``'day'`` / ``'month'`` / ``'year'``, such as a sources.json
    ``date_precision``) can only widen the period: the coarser of the two is used, so
    a coarse date is never read as a single day.  Any other ``precision`` is ignored.
    Never raises.
    """
    start = parse_as_of(value)
    if start is None:
        return None
    day = start.astimezone(timezone.utc).date()
    if isinstance(value, (datetime, date)):
        own = "day"
    else:
        text = str(value).strip()
        full = _CJK_YMD.search(text) or _NUM_YMD.search(text)
        if full:
            own = "day" if day.day == int(full.group(3)) else "month"
        elif _CJK_YM.search(text) or _NUM_YM.search(text):
            own = "month"
        else:
            own = "year"
    rank = _PRECISIONS.index(own)
    if isinstance(precision, str) and precision in _PRECISIONS:
        rank = max(rank, _PRECISIONS.index(precision))
    if rank == 0:
        return day, day
    if rank == 1:
        return day.replace(day=1), day.replace(day=calendar.monthrange(day.year, day.month)[1])
    return date(day.year, 1, 1), date(day.year, 12, 31)
