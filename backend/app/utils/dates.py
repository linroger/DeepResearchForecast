"""宽松日期解析工具（EXECPLAN T2.3 的基础设施）。

研究档案里的日期来自 LLM 抽取，格式不固定（ISO、斜杠、中文「年月日」、仅年月、
仅年份……）。本模块把这些都解析成 **UTC tz-aware** ``datetime``，供：

* Graphiti 边的 ``valid_at`` 双时态打点（T2.2 / T2.3）。
* ``actors.events_to_schedule`` 把 key_events 映射到模拟轮次（T1.3 / T3.8）。

设计原则与 actors.py 一致：**永不抛异常**，无法解析一律返回 ``None``。
"""

from __future__ import annotations

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

# Shared discovery and parsing grammar: the calendar planner must recognize the
# same complete named dates as this parser, rather than falling through to a
# baseline month/year elsewhere in the question.
_MONTH_NAMES = (r"Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|June?|July?"
                r"|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?")
_MONTH_NUMBER = {name: i for i, name in enumerate(
    ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"), 1)}
ENGLISH_DATE_PATTERNS = (
    re.compile(rf"(?<![A-Za-z])(?P<month>{_MONTH_NAMES})\.?\s+"
               r"(?P<day>\d{1,2})(?:st|nd|rd|th)?(?:,\s*|\s+)(?P<year>20\d{2})(?!\d)", re.I),
    re.compile(rf"(?<!\d)(?P<day>\d{{1,2}})(?:st|nd|rd|th)?\s+"
               rf"(?P<month>{_MONTH_NAMES})\.?(?:,\s*|\s+)(?P<year>20\d{{2}})(?!\d)", re.I),
)


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
    ``YYYY年MM月DD日``、``December 31, 2027``/``31 December 2027``、
    ``YYYY-MM``/``YYYY年MM月``（→ 当月 1 日）、纯 ``YYYY``（→ 1 月 1 日）。
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
    for pattern in ENGLISH_DATE_PATTERNS:
        m = pattern.search(s)
        if m:
            try:
                return datetime(int(m["year"]), _MONTH_NUMBER[m["month"][:3].lower()],
                                int(m["day"]), tzinfo=timezone.utc)
            except ValueError:
                # A complete but impossible named date is not a year-only date.
                return None
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
