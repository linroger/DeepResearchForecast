r"""日历时间线纯工具（Calendar-Temporal Simulation，temporal_sim_spec §2）。

把预测问题文本解析成判定日（horizon），再把 ``(as_of, horizon]`` 区间按
日/周/半月/月/季度/半年的自然日历网格切分成模拟回合，供
``simulation_config_generator`` 生成 ``temporal_config``。

设计约束（与 dates.py / actors.py 一致）：

* 纯模块：无 LLM、无 I/O、不 import OASIS；LLM 兜底在调用方实现。
* 唯一日期解析器：``utils/dates.parse_as_of``（宽松、永不抛异常）。
* 正则 CJK 安全：中文没有词边界，禁用 ``\b``，一律用 ``(?<!\d)…(?!\d)``、
  ``(?<![A-Za-z])`` 这类显式环视。
* ``extract_horizon`` 永不抛异常；解析不出返回 ``None``。
"""

from __future__ import annotations

import calendar
import math
import re
from bisect import bisect_left
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any, List, Optional, Tuple

from .dates import parse_as_of  # 同包相对导入，匹配代码库约定

# ---------------------------------------------------------------------------
# 常量（spec §2.3 pinned）
# ---------------------------------------------------------------------------

#: 单位表（细→粗），名义天数用于回合数估算与残段合并阈值
NOMINAL: List[Tuple[str, float]] = [
    ("day", 1.0),
    ("week", 7.0),
    ("half_month", 15.22),
    ("month", 30.44),
    ("quarter", 91.31),
    ("half_year", 182.62),
]
NOMINAL_DAYS = dict(NOMINAL)
UNIT_ORDER = [name for name, _ in NOMINAL]

TARGET_MIN = 8    # 少于 8 轮信息量不足 → 触发细化
TARGET_IDEAL = 16  # 理想回合数（argmin |rounds-16|）

#: horizon 距 as_of 的最大月数（30 年），超出视为噪声年份
_HORIZON_MAX_MONTHS = 360


# ---------------------------------------------------------------------------
# 数据类（spec §2.1）
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class HorizonResult:
    horizon_date: str      # ISO YYYY-MM-DD
    source: str            # "explicit_date"|"anchored_period"|"relative"|"bare_year"|"question_spec"|"llm"|"default"
    matched_text: str      # 命中的原文片段，question_spec/llm/default 为 ""
    defaulted: bool
    confidence: float      # 确定性层 1.0；question_spec 0.9；llm 0.7；default 0.3


@dataclass(frozen=True)
class RoundPeriod:
    round: int             # 0-based
    period_start: str      # ISO，含当日
    period_end: str        # ISO，含当日
    label: str             # "2027-Q3"/"2026-W29"/"2027-03"/"2027-H2"/"2027-03-15"/"2027-03-H2"；stride>1: "起~止"


@dataclass
class SimulationTimeline:
    schema_version: int            # = 1
    mode: str                      # "calendar"
    as_of_date: str
    horizon_date: str
    horizon_source: str
    horizon_text: str
    horizon_defaulted: bool
    unit: str                      # day|week|half_month|month|quarter|half_year
    unit_stride: int               # ≥1；仅超长 horizon 才 >1
    n_rounds: int                  # 恒等于 len(round_dates) —— 唯一权威
    round_dates: List[RoundPeriod]
    span_days: int
    target_max_rounds: int
    round_cap_coarsened: Optional[dict] = None   # {"from_unit","to_unit","cap"} | None
    beyond_horizon_events: List[dict] = field(default_factory=list)  # 由配置生成器填充
    warnings: List[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# 日期小工具（纯 datetime.date 算术，非字符串解析）
# ---------------------------------------------------------------------------


def _to_date(value: Any) -> Optional[date]:
    """任意输入 → ``date``；字符串走 parse_as_of（唯一解析器）；失败返回 None。"""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    parsed = parse_as_of(value)
    return parsed.date() if parsed else None


def _add_months(d: date, months: int) -> date:
    """真日历月加法：日号溢出时钳到目标月末（绝不 N×30）。"""
    total = d.month - 1 + months
    y = d.year + total // 12
    m = total % 12 + 1
    day = min(d.day, calendar.monthrange(y, m)[1])
    return date(y, m, day)


def _month_end(y: int, m: int) -> Optional[date]:
    if not 1 <= m <= 12:
        return None
    return date(y, m, calendar.monthrange(y, m)[1])


_QUARTER_END = {1: (3, 31), 2: (6, 30), 3: (9, 30), 4: (12, 31)}


def _quarter_end(y: int, q: int) -> Optional[date]:
    if q not in _QUARTER_END:
        return None
    m, day = _QUARTER_END[q]
    return date(y, m, day)


# ---------------------------------------------------------------------------
# horizon 抽取（spec §2.2）：四个确定性层，首个命中层内取最先出现的合法候选
# ---------------------------------------------------------------------------

# 中文数字（相对时长用）：支持 一~九、两、十、及「十」组合（十二/二十/二十三）
_CN_NUM = {"一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5,
           "六": 6, "七": 7, "八": 8, "九": 9}
_CN_QUARTER = {"一": 1, "二": 2, "三": 3, "四": 4, "1": 1, "2": 2, "3": 3, "4": 4}
_MONTH_BY_ABBR = {"jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
                  "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12}


def _cn_to_int(s: str) -> Optional[int]:
    s = s.strip()
    if s.isdigit():
        try:
            return int(s)
        except ValueError:
            return None
    if "十" in s:
        head, _, tail = s.partition("十")
        if head and head not in _CN_NUM:
            return None
        if tail and tail not in _CN_NUM:
            return None
        return (_CN_NUM[head] if head else 1) * 10 + (_CN_NUM[tail] if tail else 0)
    if len(s) == 1 and s in _CN_NUM:
        return _CN_NUM[s]
    return None


# --- 第 1 层：explicit_date ---
_TIER1 = [
    re.compile(r"(?<!\d)20\d{2}[-/.]\d{1,2}[-/.]\d{1,2}(?!\d)"),
    re.compile(r"(?<!\d)20\d{2}\s*年\s*\d{1,2}\s*月\s*\d{1,2}\s*日"),
]

# --- 第 2 层：anchored_period —— (正则, handler(match)->Optional[date]) ---


def _h_dec31(m: re.Match) -> Optional[date]:
    return date(int(m.group(1)), 12, 31)


def _h_jun30(m: re.Match) -> Optional[date]:
    return date(int(m.group(1)), 6, 30)


def _h_quarter_qy(m: re.Match) -> Optional[date]:   # Q3 2027
    return _quarter_end(int(m.group(2)), int(m.group(1)))


def _h_quarter_yq(m: re.Match) -> Optional[date]:   # 2027Q3 / 2027年Q3
    return _quarter_end(int(m.group(1)), int(m.group(2)))


def _h_quarter_cjk(m: re.Match) -> Optional[date]:  # 2028年第三季度
    q = _CN_QUARTER.get(m.group(2))
    return _quarter_end(int(m.group(1)), q) if q else None


def _h_half_hy(m: re.Match) -> Optional[date]:      # H2 2027
    y = int(m.group(2))
    return date(y, 6, 30) if m.group(1) == "1" else date(y, 12, 31)


def _h_half_yh(m: re.Match) -> Optional[date]:      # 2027年H1
    y = int(m.group(1))
    return date(y, 6, 30) if m.group(2) == "1" else date(y, 12, 31)


def _h_half_cjk(m: re.Match) -> Optional[date]:     # 2028年上半年/下半年
    y = int(m.group(1))
    return date(y, 6, 30) if m.group(2) == "上半年" else date(y, 12, 31)


def _h_month_en(m: re.Match) -> Optional[date]:     # March 2027 / Feb 2028
    mon = _MONTH_BY_ABBR.get(m.group(1)[:3].lower())
    return _month_end(int(m.group(2)), mon) if mon else None


def _h_month_cjk(m: re.Match) -> Optional[date]:    # 2027年11月（(?!\d) 挡掉「…月15日」前缀）
    return _month_end(int(m.group(1)), int(m.group(2)))


_TIER2 = [
    (re.compile(r"(?<![A-Za-z])(?:by\s+end\s+of|end\s+of|late)\s*(20\d{2})(?!\d)", re.IGNORECASE), _h_dec31),
    (re.compile(r"(?<!\d)(20\d{2})\s*年底"), _h_dec31),
    (re.compile(r"(?<![A-Za-z])mid[- ]?(20\d{2})(?!\d)", re.IGNORECASE), _h_jun30),
    (re.compile(r"(?<!\d)(20\d{2})\s*年中"), _h_jun30),
    (re.compile(r"(?<![A-Za-z0-9])Q([1-4])\s*(?:of\s+)?(20\d{2})(?!\d)", re.IGNORECASE), _h_quarter_qy),
    (re.compile(r"(?<!\d)(20\d{2})\s*年?\s*Q([1-4])(?!\d)", re.IGNORECASE), _h_quarter_yq),
    (re.compile(r"(?<!\d)(20\d{2})\s*年\s*第\s*([一二三四1-4])\s*季度"), _h_quarter_cjk),
    (re.compile(r"(?<![A-Za-z0-9])H([12])\s*(?:of\s+)?(20\d{2})(?!\d)", re.IGNORECASE), _h_half_hy),
    (re.compile(r"(?<!\d)(20\d{2})\s*年?\s*H([12])(?!\d)", re.IGNORECASE), _h_half_yh),
    (re.compile(r"(?<!\d)(20\d{2})\s*年?\s*(上半年|下半年)"), _h_half_cjk),
    (re.compile(
        r"(?<![A-Za-z])(Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|June?|July?"
        r"|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)"
        r"\.?,?\s*(?:of\s+)?(20\d{2})(?!\d)", re.IGNORECASE), _h_month_en),
    (re.compile(r"(?<!\d)(20\d{2})\s*年\s*(\d{1,2})\s*月(?!\d)"), _h_month_cjk),
]

# --- 第 3 层：relative（单位备选顺序照 spec 原文：个月 必须先于 月） ---
_TIER3 = re.compile(
    r"(?<![A-Za-z])(?:in|within|next|over\s+the\s+next|未来|今后|接下来)\s*"
    r"(\d{1,4}|[一二两三四五六七八九十]+)\s*"
    r"(days?|weeks?|months?|quarters?|years?|天|日|周|星期|个月|月|季度|年)(?![A-Za-z])",
    re.IGNORECASE,
)

# --- 第 4 层：bare_year ---
_TIER4 = re.compile(r"(?<!\d)(20\d{2})(?!\d)")


def _relative_target(as_of: date, n: int, unit_text: str) -> Optional[date]:
    """as_of + N 单位（真日历算术；月/年加法钳日号，绝不 N×30）。"""
    if n <= 0:
        return None
    u = unit_text.lower()
    if u.startswith("day") or u in ("天", "日"):
        return as_of + timedelta(days=n)
    if u.startswith("week") or u in ("周", "星期"):
        return as_of + timedelta(weeks=n)
    if u.startswith("month") or u in ("个月", "月"):
        return _add_months(as_of, n)
    if u.startswith("quarter") or u == "季度":
        return _add_months(as_of, 3 * n)
    if u.startswith("year") or u == "年":
        return _add_months(as_of, 12 * n)
    return None


def extract_horizon(text: str, as_of: date) -> Optional[HorizonResult]:
    """确定性四层抽取判定日；无合法候选返回 ``None``；永不抛异常。

    输入 text 约定为 ``prompt + "\\n" + central_question``：层内按出现位置取最先
    的合法候选（prompt 在前 → prompt 命中优先）。候选 ``≤ as_of`` 或
    ``> as_of + 30y`` 一律跳过继续扫描。LLM 兜底在调用方，不在本函数。
    """
    try:
        if text is None:
            return None
        if not isinstance(text, str):
            text = str(text)
        if not text.strip():
            return None
        as_of_d = _to_date(as_of)
        if as_of_d is None:
            return None
        limit = _add_months(as_of_d, _HORIZON_MAX_MONTHS)

        def _ok(d: Optional[date]) -> bool:
            return d is not None and as_of_d < d <= limit

        # 第 1 层：explicit_date（唯一走 parse_as_of 的字符串解析）
        hits: List[Tuple[int, int, re.Match]] = []
        for idx, rx in enumerate(_TIER1):
            hits.extend((m.start(), idx, m) for m in rx.finditer(text))
        for _, _, m in sorted(hits, key=lambda t: (t[0], t[1])):
            parsed = parse_as_of(m.group(0))
            d = parsed.date() if parsed else None
            if d is not None and _ok(d):
                return HorizonResult(d.isoformat(), "explicit_date", m.group(0), False, 1.0)

        # 第 2 层：anchored_period
        hits = []
        for idx, (rx, _) in enumerate(_TIER2):
            hits.extend((m.start(), idx, m) for m in rx.finditer(text))
        for _, idx, m in sorted(hits, key=lambda t: (t[0], t[1])):
            try:
                d = _TIER2[idx][1](m)
            except (ValueError, OverflowError):
                d = None
            if d is not None and _ok(d):
                return HorizonResult(d.isoformat(), "anchored_period", m.group(0), False, 1.0)

        # 第 3 层：relative
        for m in _TIER3.finditer(text):
            n = _cn_to_int(m.group(1))
            if n is None:
                continue
            try:
                d = _relative_target(as_of_d, n, m.group(2))
            except (ValueError, OverflowError):
                d = None
            if d is not None and _ok(d):
                return HorizonResult(d.isoformat(), "relative", m.group(0), False, 1.0)

        # 第 4 层：bare_year —— 收全部年份，过滤到 [as_of.year, as_of.year+30]，取最大
        best: Optional[Tuple[date, str]] = None
        for m in _TIER4.finditer(text):
            y = int(m.group(1))
            if not as_of_d.year <= y <= as_of_d.year + 30:
                continue
            d = date(y, 12, 31)
            if _ok(d) and (best is None or d > best[0]):
                best = (d, m.group(1))
        if best:
            return HorizonResult(best[0].isoformat(), "bare_year", best[1], False, 1.0)
        return None
    except Exception:  # noqa: BLE001 — 契约：永不抛异常
        return None


def default_horizon(as_of: date, months: int = 12) -> HorizonResult:
    """降级默认判定日：as_of + months（真日历加法）。"""
    as_of_d = _to_date(as_of)
    if as_of_d is None:
        raise ValueError(f"default_horizon: as_of 不可解析: {as_of!r}")
    d = _add_months(as_of_d, months)
    return HorizonResult(d.isoformat(), "default", "", True, 0.3)


# ---------------------------------------------------------------------------
# 单位选择（spec §2.3）：ideal-target 选择 + 防锯齿细化 + 超长 stride
# ---------------------------------------------------------------------------


def select_calendar_unit(span_days: int, target_max: int, hard_max: int = 48) -> Tuple[str, int]:
    """返回 ``(unit, stride)``。

    1) 在 ``rounds ≤ target_max`` 的单位里优先取 ``rounds ≥ 8`` 且最接近 16 的
       （并列取更细单位）；2) 全部 < 8 轮（短跨度/间隙区）→ 取最细可容纳单位并
       在 ``hard_max`` 内逐级细化（防锯齿）；3) 连 half_year 都放不下（约 >18 年）
       → half_year + stride，保全覆盖不截断。
    """
    span_days = max(int(span_days), 1)
    target_max = max(int(target_max), 1)
    rounds = {name: math.ceil(span_days / days) for name, days in NOMINAL}

    fits = [name for name in UNIT_ORDER if rounds[name] <= target_max]
    candidates = [name for name in fits if rounds[name] >= TARGET_MIN]
    if candidates:
        best = candidates[0]  # 细→粗；严格更优才替换 → 并列取更细单位
        best_diff = abs(rounds[best] - TARGET_IDEAL)
        for name in candidates[1:]:
            diff = abs(rounds[name] - TARGET_IDEAL)
            if diff < best_diff:
                best, best_diff = name, diff
        return best, 1
    if fits:
        i = UNIT_ORDER.index(fits[0])  # fits 保持细→粗顺序，[0] 即最细可容纳
        while i > 0 and rounds[UNIT_ORDER[i - 1]] <= hard_max:
            i -= 1  # 防锯齿细化：在硬上限内尽量用更细单位
        return UNIT_ORDER[i], 1
    # fits 为空：half_year 也超 target_max（约 >18 年）→ stride 保全覆盖
    k = math.ceil(rounds["half_year"] / target_max)
    return "half_year", k


# ---------------------------------------------------------------------------
# 回合区间划分（spec §2.4）：自然网格对齐 + 首尾残段合并
# ---------------------------------------------------------------------------


def _next_grid(d: date, unit: str) -> date:
    """严格大于 d 的下一个自然网格起点。"""
    if unit == "day":
        return d + timedelta(days=1)
    if unit == "week":  # ISO 周一
        return d + timedelta(days=7 - d.weekday())
    if unit == "half_month":  # 每月 1 日与 16 日
        if d.day < 16:
            return date(d.year, d.month, 16)
        return date(d.year + (d.month == 12), d.month % 12 + 1, 1)
    if unit == "month":
        return date(d.year + (d.month == 12), d.month % 12 + 1, 1)
    if unit == "quarter":  # 1/4/7/10 月 1 日
        m = ((d.month - 1) // 3) * 3 + 4
        return date(d.year + 1, 1, 1) if m > 12 else date(d.year, m, 1)
    if unit == "half_year":  # 1/7 月 1 日
        return date(d.year, 7, 1) if d < date(d.year, 7, 1) else date(d.year + 1, 1, 1)
    raise ValueError(f"unknown calendar unit: {unit}")


def _slot_label(d: date, unit: str) -> str:
    """d 所在网格槽位的标签。"""
    if unit == "day":
        return d.isoformat()
    if unit == "week":
        iso = d.isocalendar()
        return f"{iso[0]}-W{iso[1]:02d}"
    if unit == "half_month":
        return f"{d.year}-{d.month:02d}-H{1 if d.day <= 15 else 2}"
    if unit == "month":
        return f"{d.year}-{d.month:02d}"
    if unit == "quarter":
        return f"{d.year}-Q{(d.month - 1) // 3 + 1}"
    if unit == "half_year":
        return f"{d.year}-H{1 if d.month <= 6 else 2}"
    raise ValueError(f"unknown calendar unit: {unit}")


def _period_label(start: date, end: date, unit: str, stride: int) -> str:
    a = _slot_label(start, unit)
    if stride <= 1:
        return a
    b = _slot_label(end, unit)
    return a if a == b else f"{a}~{b}"


def build_round_periods(as_of: date, horizon: date, unit: str, stride: int = 1) -> List[RoundPeriod]:
    """把 ``(as_of, horizon]`` 按 unit 网格划分为闭区间回合，无缝无重叠。

    首回合从 ``as_of + 1d`` 起、末回合恰好止于 ``horizon``；首尾可为残段，
    中间回合是完整单位。stride=k 时每 k 个网格边界保留一个。残段合并：
    首段 < unit_days/3 → 并入第二段；末段 < unit_days/4 → 并入前一段；
    合并若会导致 0 回合则跳过。纯 date 算术，天然处理闰年。
    """
    as_of_d = _to_date(as_of)
    horizon_d = _to_date(horizon)
    if as_of_d is None or horizon_d is None:
        return []
    stride = max(int(stride), 1)
    start = as_of_d + timedelta(days=1)
    if horizon_d < start:
        return []

    # 收集 (start, horizon] 内的网格边界（新回合起点）
    bounds: List[date] = []
    g = _next_grid(start, unit)
    while g <= horizon_d:
        bounds.append(g)
        g = _next_grid(g, unit)
    if stride > 1:
        bounds = bounds[::stride]

    starts = [start] + bounds
    ends = [b - timedelta(days=1) for b in bounds] + [horizon_d]
    periods: List[Tuple[date, date]] = list(zip(starts, ends))

    # 残段合并（阈值按名义天数 × stride）
    eff_days = NOMINAL_DAYS[unit] * stride
    if len(periods) >= 2:
        first_len = (periods[0][1] - periods[0][0]).days + 1
        if first_len < eff_days / 3.0:
            periods = [(periods[0][0], periods[1][1])] + periods[2:]
    if len(periods) >= 2:
        last_len = (periods[-1][1] - periods[-1][0]).days + 1
        if last_len < eff_days / 4.0:
            periods = periods[:-2] + [(periods[-2][0], horizon_d)]

    return [
        RoundPeriod(i, s.isoformat(), e.isoformat(), _period_label(s, e, unit, stride))
        for i, (s, e) in enumerate(periods)
    ]


# ---------------------------------------------------------------------------
# 日期 → 回合（spec §2.5）
# ---------------------------------------------------------------------------


def _field(item: Any, name: str) -> Any:
    return item.get(name) if isinstance(item, dict) else getattr(item, name)


def round_for_date(d: date, round_dates: List[RoundPeriod]) -> Optional[int]:
    """按 ``period_end`` 二分定位 d 所在回合；早于首回合或晚于 horizon 返回 None。

    兼容 RoundPeriod 与 JSON dict 两种行元素（config 回读场景）。
    """
    if not round_dates:
        return None
    dd = _to_date(d)
    if dd is None:
        return None
    ends: List[date] = []
    for rp in round_dates:
        e = _to_date(_field(rp, "period_end"))
        if e is None:  # 行元素损坏 → 保守返回 None，不猜测
            return None
        ends.append(e)
    first_start = _to_date(_field(round_dates[0], "period_start"))
    if first_start is None or dd < first_start or dd > ends[-1]:
        return None
    return bisect_left(ends, dd)


# ---------------------------------------------------------------------------
# 时间线组装（spec §2.5）
# ---------------------------------------------------------------------------


def build_timeline(as_of: date, horizon: HorizonResult, target_max: int,
                   reference_max: int = 36, hard_max: int = 48) -> SimulationTimeline:
    """组装完整 SimulationTimeline。

    * span ≤ 0（horizon 不晚于 as_of 或不可解析）→ 换用 12 个月默认判定日，
      记 warning ``horizon_invalid_defaulted``。
    * ``target_max < reference_max`` 时在两档各跑一次单位选择，单位不同即记
      ``round_cap_coarsened``（显式回合上限只粗化粒度、绝不截断覆盖）。
    * ``n_rounds`` 一律以实际边界 ``len(round_dates)`` 重算（选择期估算仅参考）。
    """
    as_of_d = _to_date(as_of)
    if as_of_d is None:
        raise ValueError(f"build_timeline: as_of 不可解析: {as_of!r}")
    warnings: List[str] = []

    h_date = _to_date(horizon.horizon_date)
    if h_date is None or (h_date - as_of_d).days <= 0:
        horizon = default_horizon(as_of_d)
        h_date = _add_months(as_of_d, 12)
        warnings.append("horizon_invalid_defaulted")
    elif horizon.defaulted:
        warnings.append("horizon_defaulted_12_months")
    span_days = (h_date - as_of_d).days

    unit, stride = select_calendar_unit(span_days, target_max, hard_max)
    round_cap_coarsened: Optional[dict] = None
    if target_max < reference_max:
        ref_unit, _ref_stride = select_calendar_unit(span_days, reference_max, hard_max)
        if ref_unit != unit:
            round_cap_coarsened = {"from_unit": ref_unit, "to_unit": unit, "cap": target_max}
            warnings.append("round_cap_coarsened")
    if stride > 1:
        warnings.append("horizon_capped_stride")

    round_dates = build_round_periods(as_of_d, h_date, unit, stride)
    return SimulationTimeline(
        schema_version=1,
        mode="calendar",
        as_of_date=as_of_d.isoformat(),
        horizon_date=h_date.isoformat(),
        horizon_source=horizon.source,
        horizon_text=horizon.matched_text,
        horizon_defaulted=horizon.defaulted,
        unit=unit,
        unit_stride=stride,
        n_rounds=len(round_dates),
        round_dates=round_dates,
        span_days=span_days,
        target_max_rounds=target_max,
        round_cap_coarsened=round_cap_coarsened,
        beyond_horizon_events=[],
        warnings=warnings,
    )
