#!/usr/bin/env python3
"""data-visuals 捆绑渲染器 —— 官方统计序列（datasets.json）→ 确定性图表。

输入（全部位于 --dir 运行目录内）：

    data/datasets.json   {"schema_version": 1, "series": [{series, slug, provider, title,
                          title_zh, units, frequency, seasonal_adjustment, transform,
                          projection_from, file, kiqs, source_id, ...}]}
    data/<slug>.json     Series.to_dict()：{series, provider, provider_name, title, title_zh,
                          units, frequency, seasonal_adjustment, observations:[{date,value,flag}],
                          source_url, retrieved_at, transform, projection_from, notes, ...}

输出（全部落在 <dir>/charts/ 下 + <dir>/charts.json 清单）：

    charts/data_<slug>.png           单序列图（matplotlib Agg，固定画幅，dpi 200，字节确定）
    charts/data_<slug>.html          同图交互版（plotly 可导入时；plotly.js 内联、自包含）
    charts/data_compare_<slug>.png   同单位+同频率、仅地域不同的序列叠加对比（≤ 2 张，每张 ≤ 6 线）

图表语法（与 SKILL.md / design.md §8 一致）：
  * 每条序列一条线，原生日期轴；缺测（None）断线，绝不插值。
  * 最新观测点加标记 + 按单位格式化的数值标签；projection_from 之后的预测段画虚线 +
    浅色阴影带，图例标注 projection。
  * y 轴标签 = 单位（折行）；标题 = 序列标题（--lang zh 且有 title_zh 时用中文）；
    页脚 "Source: <provider_name> · <native id> · retrieved <YYYY-MM-DD>"。
  * 视觉主题复制自 report_visualizer（WAVE9 色板/画布/网格/字体栈），与研究端
    forecast-visuals 渲染器一致。

清单约定：charts.json 是 JSON 列表；本渲染器只拥有 id 以 ``data_`` 开头的条目，
在 ``charts.json.lock`` 跨进程锁内“读旧 → 删本渲染器旧条目 → 按顺序追加本次条目 →
原子整写”，其它生产者（forecast-visuals 的 timeline/quant_metrics 等）的条目按原顺序保留。
清单 title/caption 在词边界处不含数字（报告审计把图注里的数字当未引用的数值断言）。

stdout 恰好输出一行 JSON 摘要：{"charts": [ids], "skipped": [{series, reason}],
"dropped": [{series, reason}]}（非零退出时另含 "error"）。诊断日志走 stderr。
本脚本只写 <dir> 之内：charts/ 子目录、charts.json 及其 .lock。

Exit codes: 0 = 至少写出一张图；2 = 无可用数据（清单缺失/损坏/为空或全部序列不合格）；
3 = matplotlib 不可用。
"""

from __future__ import annotations

import argparse
from contextlib import contextmanager
import datetime as dt
import html as html_lib
import json
import logging
import math
import os
import re
import sys
import tempfile
import textwrap
from pathlib import Path

try:
    import fcntl  # POSIX deployment: serialize cross-process manifest updates.
except ImportError:  # pragma: no cover - Windows remains atomic last-writer-wins.
    fcntl = None  # type: ignore

# ---------------------------------------------------------------------------
# 图形库探测：PNG 只走 matplotlib（字节确定、无需 Chrome/kaleido）；plotly 只负责
# 可选的交互 HTML 孪生图。matplotlib 缺失 → exit 3。
# ---------------------------------------------------------------------------
try:
    import matplotlib
    matplotlib.use("Agg")  # 无头环境
    import matplotlib.dates as mdates  # type: ignore
    import matplotlib.pyplot as plt  # type: ignore
    from matplotlib import font_manager, ft2font  # type: ignore
    from matplotlib.legend_handler import HandlerTuple  # type: ignore
    from matplotlib.lines import Line2D  # type: ignore
    from matplotlib.patches import Patch  # type: ignore
    from matplotlib.ticker import FuncFormatter, MaxNLocator  # type: ignore
    _HAS_MPL = True
except Exception:  # noqa: BLE001 — 导入失败即降级
    plt = None  # type: ignore
    _HAS_MPL = False

try:
    import plotly.graph_objects as go  # type: ignore
    _HAS_PLOTLY = True
except Exception:  # noqa: BLE001
    go = None  # type: ignore
    _HAS_PLOTLY = False

# ---------------------------------------------------------------------------
# WAVE9-THEME — the subset of the report-stage theme this renderer draws with.
# SOURCE OF TRUTH: backend/app/services/report_visualizer.py（“WAVE9 统一图表
# 风格” 常量块 _VIZ_FONT/_PALETTE/_SURFACE/_GRID/_AXIS/_INK/_INK_2 与
# _apply_layout）；forecast-visuals/scripts/render.py 持有同一块的逐字副本。
# 本脚本由 _charts_python() 解释器独立运行、不可 import backend 包，只能复制。
# SYNC OBLIGATION: report_visualizer.py 的这些主题常量一旦变更，必须同步改这里，
# 并重跑 runtime_skill_sync.py 让 deer-flow/skills/public 的部署副本保持字节一致。
# ---------------------------------------------------------------------------
_VIZ_FONT = ('system-ui, -apple-system, "Segoe UI", "Helvetica Neue", Arial, '
             '"PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", "Noto Sans CJK SC", '
             'sans-serif')
_PALETTE = ["#2a78d6", "#1baf7a", "#eda100", "#008300",
            "#4a3aa7", "#e34948", "#e87ba4", "#eb6834"]
_SURFACE = "#fcfcfb"
_GRID = "#e1e0d9"
_AXIS = "#c3c2b7"
_INK = "#0b0b0b"
_INK_2 = "#52514e"

# WAVE9 图例约定：顶部右侧横排（与 report_visualizer 各构建器一致）。
_WAVE9_LEGEND = {"orientation": "h", "yanchor": "bottom", "y": 1.02,
                 "xanchor": "right", "x": 1}

# matplotlib 拉丁字体优先级（逐台机器确定：首个已安装者）；DejaVu Sans 随 matplotlib
# 自带，保证任何部署都有可用字体。CJK 字体族与 report_visualizer._CJK_FONT_FAMILIES 一致。
_LATIN_FONT_FAMILIES = ("Arial", "Liberation Sans", "DejaVu Sans")
_CJK_FONT_FAMILIES = (
    "Noto Sans CJK SC", "Noto Sans CJK TC", "Noto Sans CJK JP",
    "Source Han Sans SC", "Source Han Sans CN", "Microsoft YaHei", "SimHei",
    "PingFang SC", "PingFang HK", "Hiragino Sans GB", "Hiragino Sans",
    "Arial Unicode MS", "WenQuanYi Zen Hei", "Malgun Gothic",
)

# 预测段阴影带：中性暖灰（与网格同色系），不占用分类色槽，读作“非观测区间”。
_BAND_COLOR = _GRID
_BAND_ALPHA = 0.5

# ---------------------------------------------------------------------------
# 清单与输出契约（design.md §8）
# ---------------------------------------------------------------------------
_OWNED_PREFIX = "data_"
_SOURCE_DATA = "data/datasets.json"
_DATA_CLASS = "official_statistics"
_DEFAULT_MAX = 8
_MAX_COMPARE_CHARTS = 2
_MAX_COMPARE_LINES = 6
_MIN_POINTS = 2              # 少于两个数值观测 = 一个统计数，不是图
_MAX_POINTS = 2400           # 每条线最多绘制的最新观测数（data_sources 默认已截到 240）
_FIG_SIZE = (8.0, 4.5)       # 英寸；dpi 200 → 1600×900 像素，固定画幅
_DPI = 200
_PAD_IN = 0.14               # 画布外边距（英寸）
_GAP_IN = 0.10               # 标题区/页脚与绘图装饰之间的留白（英寸）
_SAFE_NAME_RE = re.compile(r"^[A-Za-z0-9._-]+$")
_SLUG_RE = re.compile(r"^[a-z0-9_]{1,60}$")
_PROJECTION_FLAGS = {"projection", "projected", "forecast"}
_STATUS_STYLE = {"observed": ("-", "solid", "o"), "projection": ("--", "dash", "o"),
                 "unknown": (":", "dot", "x"), "preliminary": (":", "dot", "^"),
                 "estimate": ("-.", "dashdot", "s")}

_FREQ_LABELS = {
    "en": {"D": "Daily", "W": "Weekly", "M": "Monthly", "Q": "Quarterly", "A": "Annual"},
    "zh": {"D": "日度", "W": "周度", "M": "月度", "Q": "季度", "A": "年度"},
}
_SA_LABELS = {
    "en": {"SA": "Seasonally adjusted", "NSA": "Not seasonally adjusted",
           "SAAR": "Seasonally adjusted annual rate"},
    "zh": {"SA": "季节调整", "NSA": "未季调", "SAAR": "季调年率"},
}
_TRANSFORM_LABELS = {
    "en": {"yoy": "year-over-year change", "pct": "period-over-period change"},
    "zh": {"yoy": "同比变化", "pct": "环比变化"},
}
# 图内固定文案（图像内文字不受报告数字审计约束，但仍保持简短）。
_CHROME = {
    "en": {"observed": "Observed", "projection": "Projection", "source": "Source",
           "retrieved": "retrieved", "latest": "latest", "unknown": "Unknown status",
           "preliminary": "Preliminary", "estimate": "Estimate"},
    "zh": {"observed": "实际值", "projection": "预测", "source": "来源",
           "retrieved": "获取于", "latest": "最新", "unknown": "状态未知",
           "preliminary": "初步值", "estimate": "估计值"},
}
_MONTHS_EN = ("Jan", "Feb", "Mar", "Apr", "May", "Jun",
              "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
# 清单 caption 用的数据商简称（不含数字；未知数据商回退 provider_name）。
_PROVIDER_SHORT = {
    "en": {"fred": "FRED", "bls": "the U.S. Bureau of Labor Statistics",
           "bis": "the BIS", "imf": "the IMF", "wb": "World Bank Data360",
           "usgov": "U.S. government open data"},
    "zh": {"fred": "FRED", "bls": "美国劳工统计局", "bis": "国际清算银行",
           "imf": "国际货币基金组织", "wb": "世界银行 Data360", "usgov": "美国政府开放数据"},
}

# 标题地域识别（对比图分组用）：经济体名称 → 规范显示名。按长度降序匹配，
# 仅在两条序列标题去掉唯一地域后完全一致时才判定“只差地域”。
_GEO_NAMES = (
    "United States", "U.S.", "Euro Area", "Euro area", "European Union", "China",
    "Japan", "Germany", "France", "Italy", "Spain", "Netherlands", "Belgium", "Austria",
    "Ireland", "Portugal", "Greece", "Finland", "United Kingdom", "Switzerland", "Sweden",
    "Norway", "Denmark", "Poland", "Czech Republic", "Czechia", "Hungary", "Romania",
    "Canada", "Mexico", "Brazil", "Argentina", "Chile", "Colombia", "Peru", "India",
    "Indonesia", "Korea", "South Korea", "Republic of Korea", "Australia", "New Zealand",
    "Russia", "Russian Federation", "Turkey", "Turkiye", "Türkiye", "Saudi Arabia",
    "South Africa", "Israel", "Thailand", "Malaysia", "Philippines", "Singapore",
    "Hong Kong SAR", "Hong Kong", "Taiwan", "Vietnam", "Viet Nam", "Egypt", "Nigeria",
    "World", "Advanced Economies", "Emerging Markets", "Emerging Market Economies",
    "Emerging and Developing Economies", "OECD",
)
_GEO_RE = re.compile(
    "|".join(
        rf"(?<![A-Za-z]){re.escape(name)}(?![A-Za-z])"
        for name in sorted(set(_GEO_NAMES), key=lambda n: (-len(n), n))
    ),
    re.IGNORECASE,
)
_ISO3_RE = re.compile(r"^[A-Z]{3}$")
_BIS_AREA_RE = re.compile(r"^[A-Z0-9]{2}$")


def _log(msg: str) -> None:
    print(f"[render_data] {msg}", file=sys.stderr)


def _read_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeDecodeError):
        return None


def _publish(tmp: str, path: Path) -> None:
    """Atomically move a finished temp file into place with ordinary file permissions
    (mkstemp creates 0600, which would hide charts from a web server or a copy step)."""
    mask = os.umask(0)
    os.umask(mask)
    os.chmod(tmp, 0o666 & ~mask)
    os.replace(tmp, path)


def _atomic_write(path: Path, text: str) -> None:
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=path.name, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        _publish(tmp, path)
    finally:
        if os.path.exists(tmp):
            try:
                os.unlink(tmp)
            except OSError:
                pass


def _is_within(path: Path, root: Path) -> bool:
    """True when the resolved *path* lies inside the resolved *root* (symlinks followed)."""
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except (OSError, ValueError, RuntimeError):
        return False


# ---------------------------------------------------------------------------
# 解析：日期 / 数值 / 文本
# ---------------------------------------------------------------------------
_DATE_RE = re.compile(r"^\s*(\d{4})(?:-(\d{1,2})(?:-(\d{1,2}))?)?")
_QUARTER_RE = re.compile(r"^\s*(\d{4})\s*-?\s*Q([1-4])\b", re.IGNORECASE)


def _parse_date(value) -> dt.date | None:
    """ISO 'YYYY-MM-DD'（可带时间）/ 'YYYY-MM' / 'YYYY' / 'YYYY-Qn' → 期初日期；无效 → None。"""
    raw = str(value or "").strip()
    if not raw:
        return None
    quarter = _QUARTER_RE.match(raw)
    try:
        if quarter:
            return dt.date(int(quarter.group(1)), 3 * int(quarter.group(2)) - 2, 1)
        match = _DATE_RE.match(raw)
        if not match:
            return None
        year = int(match.group(1))
        month = int(match.group(2) or 1)
        day = int(match.group(3) or 1)
        if year < 1:
            return None
        return dt.date(year, month, day)
    except ValueError:
        return None


def _parse_value(value) -> float | None:
    """有限数值 → float；None/布尔/NaN/inf/非数字串 → None（缺测，绝不补值）。"""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        number = float(value)
    elif isinstance(value, str):
        text = value.strip().replace(",", "")
        if not text:
            return None
        try:
            number = float(text)
        except ValueError:
            return None
    else:
        return None
    return number if math.isfinite(number) else None


def _clean_text(value, limit: int = 240) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _cjk_codepoints(text) -> frozenset:
    """CJK/日文/韩文码位集合（与 report_visualizer._cjk_codepoints 同一判定）。"""
    points = set()
    for char in str(text or ""):
        value = ord(char)
        if (0x2E80 <= value <= 0x303F or 0x3040 <= value <= 0x30FF
                or 0x3100 <= value <= 0x312F or 0x31A0 <= value <= 0x31EF
                or 0x3200 <= value <= 0x33FF or 0x3400 <= value <= 0x4DBF
                or 0x4E00 <= value <= 0x9FFF or 0xAC00 <= value <= 0xD7AF
                or 0xF900 <= value <= 0xFAFF or 0xFF00 <= value <= 0xFFEF
                or 0x20000 <= value <= 0x2EBEF or 0x30000 <= value <= 0x323AF):
            points.add(value)
    return frozenset(points)


# ---------------------------------------------------------------------------
# 数字中性化（清单 title/caption）：报告审计 _NUMBER_RE 把 '\d+%'、'\b\d{2,}\b'、
# '\d{4}年' 视为数值断言。期限词里的小整数改写为数词（10-Year → Ten-Year，
# 10年期 → 十年期），其余不贴在拉丁字母后的数字串整体移除（M2、G20 保留）。
# ---------------------------------------------------------------------------
_EN_ONES = ("", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine",
            "Ten", "Eleven", "Twelve", "Thirteen", "Fourteen", "Fifteen", "Sixteen",
            "Seventeen", "Eighteen", "Nineteen")
_EN_TENS = ("", "", "Twenty", "Thirty", "Forty", "Fifty", "Sixty", "Seventy", "Eighty", "Ninety")
_ZH_DIGITS = "零一二三四五六七八九"


def _en_number_word(n: int) -> str:
    if n < 20:
        return _EN_ONES[n]
    tens, ones = divmod(n, 10)
    return _EN_TENS[tens] + (f"-{_EN_ONES[ones].lower()}" if ones else "")


def _zh_number_word(n: int) -> str:
    if n < 10:
        return _ZH_DIGITS[n]
    tens, ones = divmod(n, 10)
    head = "十" if tens == 1 else _ZH_DIGITS[tens] + "十"
    return head + (_ZH_DIGITS[ones] if ones else "")


_EN_TERM_RE = re.compile(r"(?<![A-Za-z0-9.])(\d{1,2})(?=[- ](?:year|month|week|day)s?\b)",
                         re.IGNORECASE)
_ZH_TERM_RE = re.compile(r"(?<![0-9.])(\d{1,2})(?=(?:年期|个月|月期|年|周|天|日))")
_DIGIT_RUN_RE = re.compile(r"(?<![A-Za-z0-9])\d+(?:[.,:/=–-]\d+)*\s*(?:%|年|月|日|季度)?")
_AUDIT_NUMBER_RE = re.compile(r"\d+%|\b\d{2,}\b|\d{4}年")
_CJK_SPACE_RE = re.compile(r"(?<=[\u3000-\u9fff\uff00-\uffef]) +| +(?=[\u3000-\u9fff\uff00-\uffef])")


def _term_word(match, words) -> str:
    number = int(match.group(1))
    return words(number) if number > 0 else match.group(1)


def _digit_free(text) -> str:
    """Return *text* with no digits at word boundaries (see block comment above)."""
    out = str(text or "")
    out = _EN_TERM_RE.sub(lambda m: _term_word(m, _en_number_word), out)
    out = _ZH_TERM_RE.sub(lambda m: _term_word(m, _zh_number_word), out)
    out = _DIGIT_RUN_RE.sub(" ", out)
    out = re.sub(r"[(（\[]\s*[)）\]]", " ", out)            # 移除数字后留下的空括号
    out = re.sub(r"\s+([,.;:，。；：)）])", r"\1", out)
    out = re.sub(r"([(（])\s+", r"\1", out)
    out = re.sub(r"\s+", " ", out).strip()
    out = _CJK_SPACE_RE.sub("", out)                          # 中文里移除数字留下的空格
    out = re.sub(r"^[\s,.;:=·/–—-]+|[\s,;:=·/–—-]+$", "", out)
    return out.strip()


def _is_digit_free(text: str) -> bool:
    return not _AUDIT_NUMBER_RE.search(text) and not re.search(r"\b\d", text)


# ---------------------------------------------------------------------------
# 数值格式（标签/刻度）：百分比带 %；带规模词的货币/计数换算到绝对量再用 K/M/B/T；
# 巨大数值只在标签里用后缀，绝不改动数据。
# ---------------------------------------------------------------------------
_SCALE_WORDS = (("trillions of", 1e12), ("billions of", 1e9), ("millions of", 1e6),
                ("thousands of", 1e3))
_CURRENCY_SYMBOLS = (
    (re.compile(r"\b(?:u\.?s\.?\s+)?dollars?\b|\busd\b|\bus\$", re.IGNORECASE), "$"),
    (re.compile(r"\beuros?\b|\beur\b", re.IGNORECASE), "€"),
    (re.compile(r"\bpounds? sterling\b|\bgbp\b", re.IGNORECASE), "£"),
    (re.compile(r"\byen\b|\bjpy\b", re.IGNORECASE), "¥"),
)


def _trim_number(text: str) -> str:
    return text.rstrip("0").rstrip(".") if "." in text else text


def _plain_number(value: float) -> str:
    """Compact, deterministic display for an unscaled number (K/M/B/T-free below 1e6)."""
    magnitude = abs(value)
    for threshold, suffix in ((1e12, "T"), (1e9, "B"), (1e6, "M")):
        if magnitude >= threshold:
            scaled = value / threshold
            if abs(scaled) < 10:
                return _trim_number(f"{scaled:.2f}") + suffix
            if abs(scaled) < 1000:
                return _trim_number(f"{scaled:.1f}") + suffix
            return f"{scaled:,.0f}{suffix}"
    if magnitude >= 1e4:
        return f"{value:,.0f}"
    if magnitude >= 100:
        return _trim_number(f"{value:.1f}")
    if magnitude >= 1:
        return _trim_number(f"{value:.2f}")
    if magnitude == 0:
        return "0"
    if magnitude >= 1e-3:
        return _trim_number(f"{value:.4f}")
    return f"{value:.2e}"


def _unit_profile(units: str) -> tuple[str, str, float]:
    """units → (kind, currency_symbol, scale)；kind ∈ percent|pp|currency|scaled|plain。"""
    low = str(units or "").casefold()
    if "percentage point" in low:
        return "pp", "", 1.0
    if "percent" in low or "%" in low or "百分比" in low:
        return "percent", "", 1.0
    scale = 1.0
    for word, factor in _SCALE_WORDS:
        if low.startswith(word) or f" {word}" in low:
            scale = factor
            break
    for pattern, symbol in _CURRENCY_SYMBOLS:
        if pattern.search(low):
            return "currency", symbol, scale
    if scale != 1.0:
        return "scaled", "", scale
    return "plain", "", 1.0


def _format_value(value: float, units: str) -> str:
    """Latest-point label text: '4.3%', '1.25 pp', '$71.24', '$27.6T', '159M', '312.2'."""
    kind, symbol, scale = _unit_profile(units)
    if kind == "percent":
        return _trim_number(f"{value:.2f}") + "%"
    if kind == "pp":
        return _trim_number(f"{value:.2f}") + " pp"
    absolute = value * scale
    sign = "-" if absolute < 0 else ""
    if kind == "currency":
        magnitude = abs(absolute)
        body = f"{magnitude:,.2f}" if 1 <= magnitude < 1e4 and scale == 1.0 else _plain_number(magnitude)
        return f"{sign}{symbol}{body}"
    if kind == "scaled":
        return _plain_number(absolute)
    return _plain_number(value)


def _tick_formatter(value: float, _pos=None) -> str:
    """Axis ticks stay in the axis units (no currency/scale rewrite), SI only when huge."""
    if abs(value) < 1e-12:
        return "0"
    if abs(value) >= 1e6:
        return _plain_number(value)
    if abs(value) >= 1e4:
        return f"{value:,.0f}"
    return _trim_number(f"{value:.6g}") if abs(value) >= 1e-3 else f"{value:.1e}"


def _period_label(day: dt.date, frequency: str, lang: str) -> str:
    """Observation period in the series' native frequency (image text, not audited)."""
    freq = str(frequency or "").upper()
    if freq == "A":
        return f"{day.year}年" if lang == "zh" else str(day.year)
    if freq == "Q":
        quarter = (day.month - 1) // 3 + 1
        return f"{day.year}年第{quarter}季度" if lang == "zh" else f"{day.year} Q{quarter}"
    if freq == "M":
        return f"{day.year}年{day.month}月" if lang == "zh" else f"{_MONTHS_EN[day.month - 1]} {day.year}"
    return day.isoformat()


def _wrap(text: str, width: int, max_lines: int) -> str:
    """Word-wrap (CJK-aware width) to at most *max_lines*, ellipsizing the remainder."""
    text = _clean_text(text, 400)
    if not text:
        return ""
    if _cjk_codepoints(text):
        width = max(8, width // 2)
    lines = textwrap.wrap(text, width=width, break_long_words=True, break_on_hyphens=True)
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        last = lines[-1]
        lines[-1] = (last[: max(1, width - 1)].rstrip() + "…") if len(last) >= width else last + "…"
    return "\n".join(lines)


def _mpl_text(text) -> str:
    """Escape '$' so matplotlib never enters mathtext for prose/currency."""
    return str(text or "").replace("$", r"\$")


def _plotly_text(value) -> str:
    """HTML-escape reader text and neutralize paired '$' (Plotly treats them as TeX)."""
    text = str(value or "")
    if text.count("$") >= 2:
        text = re.sub(r"\bUS\$", "USD ", text, flags=re.IGNORECASE)
        text = re.sub(r"(?<![A-Za-z])\$", "USD ", text)
    return html_lib.escape(text)


# ---------------------------------------------------------------------------
# 数据加载
# ---------------------------------------------------------------------------
class _Series:
    """One chartable official series (metadata + ascending, date-deduplicated points).

    A plain class rather than a dataclass: the renderer is also loaded via
    ``importlib.util.spec_from_file_location`` without a ``sys.modules`` entry,
    which dataclasses cannot introspect under postponed annotations.
    """

    def __init__(self, *, series: str, slug: str, provider: str, provider_name: str,
                 title: str, title_zh: str, units: str, frequency: str,
                 seasonal_adjustment: str, transform: str, retrieved: str,
                 points: list, projection_from: dt.date | None, kiqs: list,
                 source_id: str, order: int, statuses=None, periods=None) -> None:
        self.series = series
        self.slug = slug
        self.provider = provider
        self.provider_name = provider_name
        self.title = title
        self.title_zh = title_zh
        self.units = units
        self.frequency = frequency
        self.seasonal_adjustment = seasonal_adjustment
        self.transform = transform
        self.retrieved = retrieved            # 'YYYY-MM-DD' or ''
        self.points = points                  # [(date, float | None)] 升序、日期去重
        self.projection_from = projection_from
        self.kiqs = kiqs
        self.source_id = source_id
        self.order = order
        self.statuses = statuses or {}
        self.periods = periods or {}

    @property
    def native(self) -> str:
        return self.series.split(":", 1)[1] if ":" in self.series else self.series

    @property
    def chart_id(self) -> str:
        return f"{_OWNED_PREFIX}{self.slug}"

    def numeric_points(self) -> list:
        return [(day, value) for day, value in self.points if value is not None]

    def is_projection(self, day: dt.date) -> bool:
        return self.status(day) == "projection"

    def status(self, day: dt.date) -> str:
        return self.statuses.get(day, "projection" if self.projection_from and day >= self.projection_from else "observed")

    def period_label(self, day: dt.date, lang: str) -> str:
        metadata = self.periods.get(day.isoformat())
        if metadata:
            partial = ("（部分）" if lang == "zh" else " (partial)") if not metadata["complete"] else ""
            return metadata["label"] + partial
        return _period_label(day, self.frequency, lang)

    def latest_observed(self):
        for day, value in reversed(self.points):
            if value is not None and self.status(day) == "observed":
                return day, value
        return None


def _status(provider: str, series: str, flag: str, day: dt.date, cutoff: dt.date | None) -> str:
    # The native WB/USAspending paths lose status/missingness. Even an older
    # artifact's explicit status or cutoff cannot restore that lost authority.
    if provider == "wb" or series.startswith("usgov:spending/"):
        return "unknown"
    if flag in {"unknown", "preliminary", "estimate", "projection"}:
        return flag
    if flag == "p":
        return "preliminary" if provider == "bls" else "unknown"
    if flag in _PROJECTION_FLAGS:
        return "projection"
    if flag in {"e", "estimated"}:
        return "estimate"
    if flag in {"provisional", "prelim"}:
        return "preliminary"
    if flag in {"a", "actual", "observed", "reported", "r", "revised", "historical"}:
        return "unknown" if cutoff and day >= cutoff else "observed"
    if flag:
        return "unknown"
    if series.startswith(("imf:WEO/", "imf:WEO_")):
        return "unknown"
    if cutoff:
        return "projection" if day >= cutoff else "observed"
    return "unknown" if re.search(r"WEO|GEP", series, re.I) else "observed"


def _fiscal_periods(payload: dict, days: list) -> dict:
    provenance = payload.get("provenance") or {}
    periods = provenance.get("periods") if isinstance(provenance, dict) else None
    if not isinstance(periods, dict):
        return {}
    out = {}
    for day in days:
        record = periods.get(day.isoformat())
        if not isinstance(record, dict) or record.get("calendar") != "us_federal_fiscal_year":
            continue
        start, end = _parse_date(record.get("start")), _parse_date(record.get("end"))
        low, high = _parse_date(record.get("covered_start")), _parse_date(record.get("covered_end"))
        if (start != day or start.month != 10 or start.day != 1 or not end
                or end != dt.date(start.year + 1, 9, 30) or not low or not high
                or not start <= low <= high <= end or type(record.get("complete")) is not bool
                or record.get("label") != f"FY{end.year}"
                or record["complete"] != (low == start and high == end)):
            continue
        out[day.isoformat()] = dict(record)
    return out


def _derive_slug(series: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", str(series or "").casefold()).strip("_")
    return slug[:60].rstrip("_") or "series"


def _load_manifest(base: Path) -> tuple[list | None, str]:
    """Return (rows, "") or (None, reason) for out_dir/data/datasets.json."""
    path = base / "data" / "datasets.json"
    if not path.is_file():
        return None, "data/datasets.json is missing"
    if not _is_within(path, base):
        return None, "data/datasets.json resolves outside the run directory"
    payload = _read_json(path)
    if not isinstance(payload, dict):
        return None, "data/datasets.json is not a JSON object (corrupt or truncated)"
    version = payload.get("schema_version", 1)
    if version != 1:
        return None, f"data/datasets.json schema_version {version!r} is not supported (expected 1)"
    rows = payload.get("series")
    if not isinstance(rows, list) or not rows:
        return None, "data/datasets.json lists no series"
    return rows, ""


def _load_series(base: Path, row, order: int, used_slugs: set) -> tuple[_Series | None, str]:
    """One manifest row + its series file → _Series, or (None, skip reason)."""
    if not isinstance(row, dict):
        return None, "manifest row is not an object"
    series_id = _clean_text(row.get("series"), 160)
    if not series_id:
        return None, "manifest row has no series id"
    rel = str(row.get("file") or "").strip()
    if not rel:
        return None, "manifest row has no series file"
    path = base / rel
    if not _is_within(path, base):
        return None, "series file resolves outside the run directory"
    if not path.is_file():
        return None, f"series file {rel} is missing"
    payload = _read_json(path)
    if not isinstance(payload, dict):
        return None, f"series file {rel} is corrupt"
    raw_obs = payload.get("observations")
    if not isinstance(raw_obs, list):
        return None, f"series file {rel} has no observations list"

    def pick(key: str, limit: int = 240) -> str:
        return _clean_text(payload.get(key) if payload.get(key) not in (None, "") else row.get(key), limit)

    by_date: dict = {}
    flags = {}
    for obs in raw_obs:
        if not isinstance(obs, dict):
            continue
        day = _parse_date(obs.get("date"))
        if day is None:
            continue
        by_date[day] = _parse_value(obs.get("value"))   # 同日重复 → 后者覆盖（确定性）
        flags[day] = str(obs.get("flag") or "").strip().casefold()
    points = sorted(by_date.items())[-_MAX_POINTS:]
    cutoff = _parse_date(pick("projection_from", 40))
    provider = pick("provider", 20).casefold()
    statuses = {day: _status(provider, series_id, flags[day], day, cutoff) for day, _ in points}
    projected = [day for day, value in points if value is not None and statuses[day] == "projection"]
    projection_from = min(projected) if projected else None
    periods = _fiscal_periods(payload, [day for day, _ in points])
    if series_id.startswith("usgov:spending/") and len(periods) != len(points):
        return None, "missing or invalid date-keyed fiscal period metadata"

    slug = str(row.get("slug") or "").strip()
    if not _SLUG_RE.match(slug):
        slug = _derive_slug(series_id)
    base_slug, n = slug, 2
    while slug in used_slugs:
        suffix = f"_{n}"
        slug = base_slug[: 60 - len(suffix)] + suffix
        n += 1

    kiqs = row.get("kiqs")
    retrieved = _parse_date(pick("retrieved_at", 40))
    item = _Series(
        series=series_id,
        slug=slug,
        provider=pick("provider", 20).casefold(),
        provider_name=pick("provider_name", 120),
        title=pick("title", 200),
        title_zh=pick("title_zh", 200),
        units=pick("units", 120),
        frequency=pick("frequency", 4).upper(),
        seasonal_adjustment=pick("seasonal_adjustment", 8).upper(),
        transform=pick("transform", 12).casefold(),
        retrieved=retrieved.isoformat() if retrieved else "",
        points=points,
        projection_from=projection_from,
        kiqs=[str(k) for k in kiqs if str(k).strip()] if isinstance(kiqs, list) else [],
        source_id=_clean_text(row.get("source_id"), 20),
        order=order,
        statuses=statuses,
        periods=periods,
    )
    if len(item.numeric_points()) < _MIN_POINTS:
        return None, ("no numeric observations" if not item.numeric_points()
                      else "fewer than two numeric observations (a single value is a statistic, not a chart)")
    used_slugs.add(slug)
    return item, ""


def _priority(item: _Series) -> tuple:
    """--max selection order: KIQ-linked first, then cited (source_id), then catalog order."""
    return (0 if item.kiqs else 1, 0 if item.source_id else 1, item.order)


def _select(items: list, max_charts: int) -> tuple[list, list]:
    ranked = sorted(items, key=_priority)
    keep = ranked[:max_charts]
    dropped = [{"series": item.series, "reason": f"over the chart cap (--max {max_charts})"}
               for item in ranked[max_charts:]]
    keep.sort(key=lambda item: item.order)       # 输出顺序 = datasets.json 目录顺序
    return keep, dropped


# ---------------------------------------------------------------------------
# 字体：拉丁字体族逐台机器确定；含 CJK 的文字必须由一个真实覆盖全部字形的已安装字体
# 绘制（与 report_visualizer 同一判定），否则回退英文文案，绝不出豆腐块。
# ---------------------------------------------------------------------------
_FONT_STATE: dict = {}


def _font_file(family: str) -> str | None:
    """Installed font file for *family* without Matplotlib's silent default fallback."""
    font_logger = logging.getLogger("matplotlib.font_manager")
    previous = font_logger.level
    font_logger.setLevel(logging.ERROR)
    try:
        path = font_manager.findfont(font_manager.FontProperties(family=family),
                                     fallback_to_default=False)
    except Exception:  # noqa: BLE001 - a missing family is the expected negative answer
        return None
    finally:
        font_logger.setLevel(previous)
    return path if path and os.path.isfile(path) else None


def _latin_family() -> str:
    if "latin" not in _FONT_STATE:
        _FONT_STATE["latin"] = next(
            (family for family in _LATIN_FONT_FAMILIES if _font_file(family)), "DejaVu Sans")
    return _FONT_STATE["latin"]


def _cjk_fonts() -> list:
    """[(font file, charmap)] for installed CJK families, in _CJK_FONT_FAMILIES order."""
    if "cjk" not in _FONT_STATE:
        found: list = []
        seen: set = set()
        for family in _CJK_FONT_FAMILIES:
            path = _font_file(family)
            if not path:
                continue
            real = os.path.realpath(path)
            if real in seen:
                continue
            try:
                charmap = frozenset(ft2font.FT2Font(real).get_charmap())
            except Exception:  # noqa: BLE001 - unreadable font files are skipped
                continue
            if charmap:
                found.append((real, charmap))
                seen.add(real)
        _FONT_STATE["cjk"] = found
    return _FONT_STATE["cjk"]


class _Fonts:
    """Per-chart font chooser: the Latin family for plain text, one CJK file for CJK text."""

    def __init__(self, texts) -> None:
        required: set = set()
        for text in texts:
            required |= _cjk_codepoints(text)
        self.cjk_path = None
        self.ok = True
        if required:
            self.cjk_path = next(
                (path for path, charmap in _cjk_fonts() if required <= charmap), None)
            self.ok = self.cjk_path is not None

    def prop(self, text, size: float, weight: str = "normal"):
        if self.cjk_path and _cjk_codepoints(text):
            return font_manager.FontProperties(fname=self.cjk_path, size=size, weight=weight)
        return font_manager.FontProperties(family=_latin_family(), size=size, weight=weight)


def _rc() -> dict:
    return {
        "font.family": "sans-serif",
        "font.sans-serif": [_latin_family(), "DejaVu Sans"],
        "axes.formatter.use_mathtext": False,
        "axes.unicode_minus": True,
        "path.simplify": True,
    }


def _strip_cjk(text: str) -> str:
    points = _cjk_codepoints(text)
    return re.sub(r"\s+", " ", "".join(ch for ch in str(text or "") if ord(ch) not in points)).strip()


# ---------------------------------------------------------------------------
# 图内文案
# ---------------------------------------------------------------------------
def _subtitle(frequency: str, seasonal_adjustment: str, transform: str,
              projection_from: dt.date | None, lang: str) -> str:
    parts = [
        _FREQ_LABELS[lang].get(frequency, ""),
        _SA_LABELS[lang].get(seasonal_adjustment, ""),
        _TRANSFORM_LABELS[lang].get(transform, ""),
    ]
    if projection_from is not None:
        period = _period_label(projection_from, frequency, lang)
        parts.append(f"{period}起为预测" if lang == "zh" else f"projection from {period}")
    return " · ".join(part for part in parts if part)


def _compact_natives(native_ids: list) -> str:
    """'IMF_WEO_NGDP_RPCH/USA', '…/CHN' → 'IMF_WEO_NGDP_RPCH/USA, CHN' (shared id prefix once)."""
    if len(native_ids) < 2:
        return ", ".join(native_ids)
    prefix = os.path.commonprefix(native_ids)
    cut = max(prefix.rfind("/"), prefix.rfind("."))
    if cut < 0:
        return ", ".join(native_ids)
    return ", ".join([native_ids[0]] + [native[cut + 1:] for native in native_ids[1:]])


def _footer(provider_name: str, provider: str, native_ids: list, retrieved: str, lang: str) -> str:
    chrome = _CHROME[lang]
    natives = _compact_natives(native_ids)
    if len(natives) > 72:
        natives = natives[:71].rstrip(", ") + "…"
    name = provider_name or provider.upper() or "official source"
    sep = "：" if lang == "zh" else ": "
    text = f"{chrome['source']}{sep}{name} · {natives}"
    if retrieved:
        text += f" · {chrome['retrieved']} {retrieved}"
    return _clean_text(text, 150)


def _series_bundle(item: _Series, lang: str) -> dict:
    chrome = _CHROME[lang]
    title = (item.title_zh if lang == "zh" and item.title_zh else item.title) or item.native
    cutoff = item.projection_from
    if cutoff and any(item.status(day) != "projection" for day, _ in item.points if day >= cutoff):
        cutoff = None
    bundle = {
        "lang": lang,
        "title": title,
        "subtitle": _subtitle(item.frequency, item.seasonal_adjustment, item.transform,
                              cutoff, lang),
        "ylabel": item.units,
        "footer": _footer(item.provider_name, item.provider, [item.native], item.retrieved, lang),
        "observed": chrome["observed"],
        **{status: chrome[status] for status in _STATUS_STYLE},
        "value": "",
        "period": "",
    }
    latest = item.latest_observed()
    if latest is not None:
        bundle["value"] = _format_value(latest[1], item.units)
        bundle["period"] = item.period_label(latest[0], lang)
    return bundle


def _bundle_texts(bundle: dict) -> list:
    texts: list = []
    for key, value in bundle.items():
        if key == "lang":
            continue
        texts.extend(value if isinstance(value, list) else [value])
    return [str(text) for text in texts]


def _with_fonts(build, lang: str, chart_id: str) -> tuple[dict, _Fonts]:
    """Build the text bundle in *lang*; fall back to English, then to CJK-free text, when
    no installed font covers its CJK glyphs (never draw missing-glyph boxes)."""
    for candidate in ((lang, "en") if lang == "zh" else ("en",)):
        bundle = build(candidate)
        fonts = _Fonts(_bundle_texts(bundle))
        if fonts.ok:
            return bundle, fonts
        _log(f"{chart_id}: no installed font covers the {candidate} text; falling back")
    bundle = {}
    for key, value in build("en").items():
        if key == "lang":
            bundle[key] = value
        elif isinstance(value, list):
            bundle[key] = [_strip_cjk(text) or "?" for text in value]
        else:
            bundle[key] = _strip_cjk(value)
    bundle["title"] = bundle.get("title") or chart_id
    return bundle, _Fonts(())


# ---------------------------------------------------------------------------
# matplotlib 绘制（PNG 主交付物）
# ---------------------------------------------------------------------------
def _segments(item: _Series) -> tuple[list, list, list, list]:
    """Compatibility view of the observed/projection segments only."""
    segments = _status_segments(item)
    return (*segments.get("observed", ([], [])), *segments.get("projection", ([], [])))


def _status_segments(item: _Series) -> dict:
    segments = {}
    for status in _STATUS_STYLE:
        indices = [i for i, (day, value) in enumerate(item.points) if item.status(day) == status]
        if not any(item.points[i][1] is not None for i in indices):
            continue
        first, last = indices[0], indices[-1]
        # Only an adjacent actual point may bridge into a forecast. Never bridge
        # an unknown/preliminary/estimate/missing interval.
        bridge = (status == "projection" and first > 0
                  and item.status(item.points[first - 1][0]) == "observed"
                  and item.points[first - 1][1] is not None)
        if bridge:
            first -= 1
        xs, ys = [], []
        for i in range(first, last + 1):
            day, value = item.points[i]
            xs.append(day)
            ys.append(value if value is not None and (item.status(day) == status or bridge and i == first)
                      else math.nan)
        segments[status] = (xs, ys)
    return segments


def _projection_spans(item: _Series) -> list:
    spans = []
    start = None
    for i, (day, _) in enumerate(item.points):
        projected = item.is_projection(day)
        if projected and start is None:
            start = day
        if start is not None and (not projected or i == len(item.points) - 1):
            end = day
            if projected:
                months = {"M": 1, "Q": 3, "A": 12}.get(item.frequency)
                if months:
                    year, month = divmod(day.year * 12 + day.month - 1 + months, 12)
                    end = dt.date(year, month + 1, 1)
                else:
                    end = day + dt.timedelta(days=7 if item.frequency == "W" else 1)
            spans.append((start, end))
            start = None
    return spans


def _fiscal_axis(ax, item: _Series, lang: str) -> None:
    if not item.periods:
        return
    step = max(1, math.ceil(len(item.points) / 8))
    all_days = [day for day, _ in item.points]
    days = sorted(set(all_days[::step] + all_days[-1:]))
    ax.set_xticks(days, [item.period_label(day, lang) for day in days])


def _plotly_fiscal_axis(fig, item: _Series, lang: str) -> None:
    if item.periods:
        all_days = [day for day, _ in item.points]
        days = sorted(set(all_days[::max(1, math.ceil(len(all_days) / 8))] + all_days[-1:]))
        fig.update_xaxes(tickmode="array", tickvals=_iso(days),
                         ticktext=[item.period_label(day, lang) for day in days])


def _status_hover(item: _Series) -> str:
    return _hover(item.units).replace("%{x|%Y-%m-%d}", "%{customdata}") if item.periods else _hover(item.units)


def _isolated(xs: list, ys: list) -> tuple[list, list]:
    """Points with no numeric neighbour on either side (a line would draw nothing there)."""
    out_x, out_y = [], []
    for i, y in enumerate(ys):
        if math.isnan(y):
            continue
        left = i > 0 and not math.isnan(ys[i - 1])
        right = i + 1 < len(ys) and not math.isnan(ys[i + 1])
        if not left and not right:
            out_x.append(xs[i])
            out_y.append(y)
    return out_x, out_y


def _x_limits(first: dt.date, last: dt.date) -> tuple[dt.date, dt.date]:
    pad = dt.timedelta(days=max(1, int((last - first).days * 0.015)))
    return first - pad, last + pad


def _group_x_limits(group: list) -> tuple[dt.date, dt.date]:
    return _x_limits(min(item.numeric_points()[0][0] for item, _label in group),
                     max(item.numeric_points()[-1][0] for item, _label in group))


def _style_axes(ax, lang: str, fonts: _Fonts, ylabel: str) -> None:
    ax.set_facecolor(_SURFACE)
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color(_AXIS)
    ax.spines["bottom"].set_linewidth(0.8)
    ax.grid(axis="y", color=_GRID, linewidth=0.6)
    ax.grid(axis="x", visible=False)
    ax.set_axisbelow(True)
    ax.tick_params(axis="y", length=0, labelsize=8.5, labelcolor=_INK_2, pad=4)
    ax.tick_params(axis="x", length=3, color=_AXIS, labelsize=8.5, labelcolor=_INK_2)
    ax.yaxis.set_major_locator(MaxNLocator(nbins=6))
    ax.yaxis.set_major_formatter(FuncFormatter(_tick_formatter))
    locator = mdates.AutoDateLocator(minticks=4, maxticks=8)
    if lang == "zh":
        formatter = mdates.ConciseDateFormatter(
            locator,
            formats=["%Y", "%Y-%m", "%m-%d", "%H:%M", "%H:%M", "%S.%f"],
            zero_formats=["", "%Y", "%Y-%m", "%m-%d", "%H:%M", "%H:%M"],
            offset_formats=["", "", "%Y", "%Y-%m", "%Y-%m-%d", "%Y-%m-%d %H:%M"],
        )
    else:
        formatter = mdates.ConciseDateFormatter(locator)
    ax.xaxis.set_major_locator(locator)
    ax.xaxis.set_major_formatter(formatter)
    if ylabel:
        ax.set_ylabel(_mpl_text(_wrap(ylabel, 34, 3)), color=_INK_2,
                      fontproperties=fonts.prop(ylabel, 8.5), labelpad=6)


def _new_figure():
    """Fixed canvas; _layout positions the axes box afterwards (no layout engine)."""
    fig = plt.figure(figsize=_FIG_SIZE, dpi=_DPI)
    fig.patch.set_facecolor(_SURFACE)
    return fig, fig.add_axes((0.1, 0.15, 0.8, 0.7))


def _fit_text(artist, renderer, max_px: float) -> None:
    """Ellipsize a single-line Text until it fits *max_px* (deterministic prefix search)."""
    full = artist.get_text()
    if artist.get_window_extent(renderer).width <= max_px:
        return
    lo, hi = 0, len(full)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        artist.set_text(full[:mid].rstrip().rstrip("\\") + "…")
        if artist.get_window_extent(renderer).width <= max_px:
            lo = mid
        else:
            hi = mid - 1
    artist.set_text(full[:lo].rstrip().rstrip("\\") + "…")


def _layout(fig, ax, bundle: dict, fonts: _Fonts, legend=None) -> None:
    """Title and subtitle top-left, optional legend at the right of the subtitle row (one row
    lower when they would collide), footer bottom-left; then position the axes so its tick
    labels, axis label, annotations and in-axes legend fit the remaining box. Deterministic."""
    width_in, height_in = fig.get_size_inches()
    dpi = fig.dpi
    renderer = fig.canvas.get_renderer()
    left_x = _PAD_IN / width_in
    right_x = 1 - _PAD_IN / width_in
    max_px = (width_in - 2 * _PAD_IN) * dpi
    title_artist = fig.text(left_x, 1 - _PAD_IN / height_in, "", ha="left", va="top", color=_INK,
                            fontproperties=fonts.prop(bundle["title"], 12.5, "bold"))
    for width in (88, 80, 72, 64, 56):           # 最宽且实测放得下的折行宽度
        title = _wrap(bundle["title"], width, 2)
        title_artist.set_text(_mpl_text(title))
        if title_artist.get_window_extent(renderer).width <= max_px:
            break
    row_top = _PAD_IN + (title.count("\n") + 1) * 12.5 * 1.25 / 72 + 0.06
    row_height = 0.0
    sub_artist = None
    if bundle["subtitle"]:
        subtitle = _clean_text(bundle["subtitle"], 84)
        sub_artist = fig.text(left_x, 1 - row_top / height_in, _mpl_text(subtitle), ha="left",
                              va="top", color=_INK_2, fontproperties=fonts.prop(subtitle, 9))
        row_height = 9 * 1.3 / 72
    if legend is not None:
        handles, labels = legend
        leg = fig.legend(handles, labels, loc="upper right",
                         bbox_to_anchor=(right_x, 1 - (row_top - 0.02) / height_in),
                         ncol=min(3, len(labels)), frameon=False, borderaxespad=0.0, borderpad=0.0,
                         handlelength=2.6, columnspacing=1.4,
                         handler_map={tuple: HandlerTuple(ndivide=1)},
                         prop=fonts.prop(" ".join(labels), 8.5), labelcolor=_INK_2)
        leg_box = leg.get_window_extent(renderer)
        if sub_artist is not None and sub_artist.get_window_extent(renderer).x1 + 0.15 * dpi > leg_box.x0:
            row_top += row_height + 0.05            # 副标题过长：图例下移一行，仍右对齐
            leg.set_bbox_to_anchor((right_x, 1 - (row_top - 0.02) / height_in),
                                   transform=fig.transFigure)
        row_height = max(row_height, leg_box.height / dpi)
    top_in = row_top + row_height + _GAP_IN
    footer = fig.text(left_x, _PAD_IN / height_in, _mpl_text(bundle["footer"]), ha="left",
                      va="bottom", color=_INK_2, fontproperties=fonts.prop(bundle["footer"], 7.5))
    _fit_text(footer, renderer, max_px)
    bottom_in = _PAD_IN + 7.5 * 1.3 / 72 + _GAP_IN
    for _ in range(3):
        tight = ax.get_tightbbox(renderer)
        box = ax.get_window_extent(renderer)
        left = _PAD_IN + max(0.0, (box.x0 - tight.x0) / dpi)
        right = _PAD_IN + max(0.0, (tight.x1 - box.x1) / dpi)
        bottom = bottom_in + max(0.0, (box.y0 - tight.y0) / dpi)
        top = top_in + max(0.0, (tight.y1 - box.y1) / dpi)
        ax.set_position((left / width_in, bottom / height_in,
                         max(0.25, 1 - (left + right) / width_in),
                         max(0.25, 1 - (top + bottom) / height_in)))


def _zero_line(ax) -> None:
    low, high = ax.get_ylim()
    if low < 0 < high:
        ax.axhline(0, color=_AXIS, linewidth=0.8, zorder=1)


def _label_latest(ax, item: _Series, bundle: dict, fonts: _Fonts, color: str) -> None:
    """Latest observed point: ringed marker + value/period label placed off the line."""
    latest = item.latest_observed()
    if latest is None:
        return
    day, value = latest
    ax.plot([day], [value], marker="o", markersize=6.5, markerfacecolor=color,
            markeredgecolor=_SURFACE, markeredgewidth=1.6, linestyle="none",
            zorder=5, clip_on=False)
    numeric = item.numeric_points()
    later = [v for d, v in numeric if d > day]
    value_text = _mpl_text(bundle["value"])
    period_text = _mpl_text(bundle["period"])
    if not later:
        # 最新点即末点：数值在右侧边距，期别紧贴其下。
        ax.annotate(value_text, xy=(day, value), xytext=(7, 1), textcoords="offset points",
                    ha="left", va="bottom", color=_INK, annotation_clip=False,
                    fontproperties=fonts.prop(value_text, 9.5, "bold"))
        ax.annotate(period_text, xy=(day, value), xytext=(7, -1), textcoords="offset points",
                    ha="left", va="top", color=_INK_2, annotation_clip=False,
                    fontproperties=fonts.prop(period_text, 7.5))
        return
    # 最新点之后还有预测段：标签放在线的上方或下方（远离后续走势），衬底防压线。
    values = [v for _d, v in numeric]
    low, high = min(values), max(values)
    span = (high - low) or 1.0
    frac = (value - low) / span
    rising = max(later[:6]) > value
    below = frac > 0.75 or (frac >= 0.25 and rising)
    label = f"{bundle['value']} · {bundle['period']}"
    ax.annotate(_mpl_text(label), xy=(day, value), xytext=(0, -10 if below else 10),
                textcoords="offset points", ha="center", va="top" if below else "bottom",
                color=_INK, annotation_clip=False, zorder=6,
                fontproperties=fonts.prop(label, 8.5, "bold"),
                bbox={"boxstyle": "round,pad=0.25", "facecolor": _SURFACE,
                      "edgecolor": "none", "alpha": 0.9})


def _projection_handle(color: str) -> tuple:
    """Legend key for the projection: dashed line drawn over the shaded band."""
    band = Patch(facecolor=_BAND_COLOR, alpha=_BAND_ALPHA, edgecolor="none")
    dashed = Line2D([], [], color=color, linewidth=1.8, linestyle=(0, (4, 2.5)))
    return (band, dashed)


def _draw_series(item: _Series, bundle: dict, fonts: _Fonts):
    color = _PALETTE[0]
    fig, ax = _new_figure()
    _style_axes(ax, bundle["lang"], fonts, bundle["ylabel"])
    handles, labels = [], []
    segments = _status_segments(item)
    for status, (xs, ys) in segments.items():
        style, _, marker = _STATUS_STYLE[status]
        (line,) = ax.plot(xs, ys, color=color, linewidth=1.8, linestyle=style,
                          marker=marker if status != "observed" else None, markersize=4,
                          solid_joinstyle="round", solid_capstyle="round", zorder=3)
        iso_x, iso_y = _isolated(xs, ys)
        if iso_x and status == "observed":
            ax.plot(iso_x, iso_y, marker=marker, markersize=4, color=color,
                    linestyle="none", zorder=3)
        handles.append(line)
        labels.append(bundle[status])
    numeric = item.numeric_points()
    x_low, x_high = _x_limits(numeric[0][0], numeric[-1][0])
    for start, end in _projection_spans(item):
        ax.axvspan(max(start, x_low), min(end, x_high), facecolor=_BAND_COLOR,
                   alpha=_BAND_ALPHA, linewidth=0, zorder=0)
    legend = (handles, labels) if set(segments) != {"observed"} else None
    ax.set_xlim(x_low, x_high)
    ax.margins(y=0.12)
    ax.autoscale_view()
    _zero_line(ax)
    _label_latest(ax, item, bundle, fonts, color)
    _fiscal_axis(ax, item, bundle["lang"])
    _layout(fig, ax, bundle, fonts, legend)
    return fig


# ---------------------------------------------------------------------------
# plotly 交互孪生图（与 PNG 同一语法；plotly.js 内联、无网络依赖）
# ---------------------------------------------------------------------------
_EMBEDDED_FAVICON = (
    "data:image/svg+xml,%3Csvg xmlns=%22http://www.w3.org/2000/svg%22 "
    "viewBox=%220 0 64 64%22%3E%3Crect width=%2264%22 height=%2264%22 "
    "rx=%2214%22 fill=%22%2308172b%22/%3E%3Cpath d=%22M18 33h28M32 19v28%22 "
    "stroke=%22%2354d4ff%22 stroke-width=%226%22/%3E%3C/svg%3E"
)


def _apply_wave9_layout(fig, title: str, height=None, **kwargs) -> None:
    """统一 plotly 布局（镜像 report_visualizer._apply_layout）：浅色画布 + 细网格 +
    固定分类色板 + CJK 安全字体栈。就地修改 fig。"""
    layout = dict(
        title=dict(text=title, font=dict(size=16, color=_INK, family=_VIZ_FONT), x=0.02),
        font=dict(family=_VIZ_FONT, size=12, color=_INK_2),
        paper_bgcolor=_SURFACE, plot_bgcolor=_SURFACE,
        colorway=list(_PALETTE),
        margin=dict(l=10, r=24, t=58, b=46),
        hoverlabel=dict(font=dict(family=_VIZ_FONT, size=12)),
    )
    if height is not None:
        layout["height"] = height
    layout.update(kwargs)
    fig.update_layout(**layout)
    fig.update_xaxes(gridcolor=_GRID, zerolinecolor=_AXIS, linecolor=_AXIS,
                     tickfont=dict(size=11))
    fig.update_yaxes(gridcolor=_GRID, zerolinecolor=_AXIS, linecolor=_AXIS,
                     tickfont=dict(size=11))


def _iso(days: list) -> list:
    return [day.isoformat() for day in days]


def _nullable(values: list) -> list:
    return [None if math.isnan(value) else value for value in values]


def _hover(units: str) -> str:
    unit = _plotly_text(units)
    return "%{x|%Y-%m-%d}<br>%{y:,.4~g}" + (f" {unit}" if unit else "") + "<extra></extra>"


def _y_range(items: list) -> tuple[float, float]:
    values = [value for item in items for _day, value in item.numeric_points()]
    low, high = min(values), max(values)
    pad = (high - low) * 0.1 or (abs(high) * 0.1 or 1.0)
    return low - pad, high + pad


def _plotly_layout(fig, bundle: dict, *, showlegend: bool, x_low: dt.date, x_high: dt.date,
                   right_margin: int) -> None:
    title = _plotly_text(bundle["title"])
    if bundle["subtitle"]:
        title += f"<br><sup>{_plotly_text(bundle['subtitle'])}</sup>"
    _apply_wave9_layout(
        fig, title, height=520, showlegend=showlegend, legend=dict(_WAVE9_LEGEND),
        margin={"l": 10, "r": right_margin, "t": 96, "b": 86},
    )
    fig.update_xaxes(type="date", range=[x_low.isoformat(), x_high.isoformat()], showgrid=False)
    fig.update_yaxes(title_text=_plotly_text(_wrap(bundle["ylabel"], 34, 3)).replace("\n", "<br>"),
                     separatethousands=True)
    fig.add_annotation(
        xref="paper", yref="paper", x=0, y=-0.16, xanchor="left", yanchor="top",
        showarrow=False, align="left", text=_plotly_text(bundle["footer"]),
        font={"size": 10, "color": _INK_2},
    )


def _plotly_series(item: _Series, bundle: dict):
    color = _PALETTE[0]
    segments = _status_segments(item)
    hover = _status_hover(item)
    fig = go.Figure()
    for status, (xs, ys) in segments.items():
        fig.add_trace(go.Scatter(
            x=_iso(xs), y=_nullable(ys), mode="lines" if status == "observed" else "lines+markers",
            name=_plotly_text(bundle[status]),
            line={"color": color, "width": 2, "dash": _STATUS_STYLE[status][1]},
            marker={"symbol": {"o": "circle", "x": "x", "^": "triangle-up", "s": "square"}[_STATUS_STYLE[status][2]], "size": 6},
            connectgaps=False, hovertemplate=hover, customdata=[item.period_label(day, bundle["lang"]) for day in xs],
            showlegend=set(segments) != {"observed"},
        ))
        iso_x, iso_y = _isolated(xs, ys)
        if iso_x and status == "observed":
            fig.add_trace(go.Scatter(x=_iso(iso_x), y=iso_y, mode="markers", showlegend=False,
                                     marker={"color": color, "size": 6}, hovertemplate=hover,
                                     customdata=[item.period_label(day, bundle["lang"]) for day in iso_x]))
    numeric = item.numeric_points()
    x_low, x_high = _x_limits(numeric[0][0], numeric[-1][0])
    for start, end in _projection_spans(item):
        fig.add_vrect(x0=max(start, x_low).isoformat(), x1=min(end, x_high).isoformat(),
                      fillcolor=_BAND_COLOR, opacity=_BAND_ALPHA, line_width=0, layer="below")
    latest = item.latest_observed()
    if latest is not None:
        day, value = latest
        fig.add_trace(go.Scatter(
            x=[day.isoformat()], y=[value], mode="markers", showlegend=False, hovertemplate=hover,
            customdata=[item.period_label(day, bundle["lang"])],
            marker={"color": color, "size": 10, "line": {"color": _SURFACE, "width": 2}},
        ))
        later = any(d > day for d, _v in item.numeric_points())
        fig.add_annotation(
            x=day.isoformat(), y=value, showarrow=False,
            text=f"<b>{_plotly_text(bundle['value'])}</b><br>{_plotly_text(bundle['period'])}",
            xanchor="center" if later else "left", yanchor="bottom" if later else "middle",
            xshift=0 if later else 9, yshift=10 if later else 0, align="left",
            bgcolor=_SURFACE, font={"size": 11, "color": _INK},
        )
    _plotly_layout(fig, bundle, showlegend=set(segments) != {"observed"}, x_low=x_low, x_high=x_high,
                   right_margin=96)
    _plotly_fiscal_axis(fig, item, bundle["lang"])
    return fig


# ---------------------------------------------------------------------------
# 对比图：同单位 + 同频率 + 同变换，且只差地域（BIS/IMF 同 flow 仅地域维不同、
# World Bank 同指标不同 ISO3，或标题去掉唯一地域名后完全一致）。
# ---------------------------------------------------------------------------
_ZH_GEO_NAMES = (
    "美国", "中国", "日本", "德国", "法国", "英国", "意大利", "西班牙", "荷兰", "瑞士", "瑞典",
    "挪威", "加拿大", "澳大利亚", "新西兰", "韩国", "印度", "印度尼西亚", "巴西", "墨西哥",
    "阿根廷", "俄罗斯", "土耳其", "南非", "沙特阿拉伯", "新加坡", "中国香港", "香港", "台湾",
    "欧元区", "欧盟", "世界", "全球", "新兴市场", "发达经济体",
)
_ZH_GEO_RE = re.compile("|".join(
    re.escape(name) for name in sorted(set(_ZH_GEO_NAMES), key=lambda n: (-len(n), n))))


def _native_geo(item: _Series) -> tuple[tuple, str] | None:
    """(group key, geography code) from the native id, or None when not decomposable."""
    native = item.native.split("#", 1)[0]
    if item.provider == "wb":
        parts = [part for part in native.split("/") if part]
        if len(parts) >= 2 and _ISO3_RE.match(parts[-1]):
            return ("wb", "/".join(parts[:-1]).upper(), ""), parts[-1]
        return None
    if item.provider in ("bis", "imf"):
        flow, _sep, key = native.partition("/")
        dims = key.split(".") if key else []
        pattern = _BIS_AREA_RE if item.provider == "bis" else _ISO3_RE
        for index, dim in enumerate(dims):
            if pattern.match(dim):
                template = ".".join(dims[:index] + ["*"] + dims[index + 1:])
                return (item.provider, flow.upper(), template), dim
    return None


def _title_geo(title: str) -> tuple[str, str] | None:
    """(title template with the geography blanked, geography text) when exactly one is named."""
    matches = list(_GEO_RE.finditer(title or ""))
    if not matches or len({match.group(0).casefold() for match in matches}) != 1:
        return None
    template = re.sub(r"\s+", " ", _GEO_RE.sub("{geo}", title)).strip().casefold()
    return template, matches[0].group(0)


def _strip_geo(title: str, pattern=_GEO_RE) -> str:
    """Drop the geography and its connector: 'Policy rate - United States' → 'Policy rate'."""
    out = pattern.sub("\x00", title or "")
    out = re.sub(r"\s*(?:[-–—:,;|/]|\b(?:in|for|of)\b)?\s*(?:\bthe\s+)?\x00", "", out,
                 flags=re.IGNORECASE)
    out = re.sub(r"^\s*[-–—:,;|/]\s*", "", out)
    out = re.sub(r"[(（]\s*[)）]", "", out).replace("\x00", "")
    out = re.sub(r"^[的之]|[的之]$", "", re.sub(r"\s+", " ", out).strip())
    return out.strip(" -–—:,;|/")


def _compare_groups(items: list) -> list:
    """≤ _MAX_COMPARE_CHARTS groups of [(series, geography label)], ≤ _MAX_COMPARE_LINES each."""
    groups: dict = {}
    for item in sorted(items, key=_priority):
        units = re.sub(r"\s+", " ", item.units.casefold()).strip()
        if not units or not item.frequency:
            continue
        if any(not period["complete"] for period in item.periods.values()):
            continue  # A partial fiscal aggregate is not a comparable annual total.
        title_geo = _title_geo(item.title)
        native = _native_geo(item)
        if native:
            key, code = native
            label = title_geo[1] if title_geo else code
        elif title_geo:
            key, code, label = ("title", title_geo[0], ""), title_geo[1].casefold(), title_geo[1]
        else:
            continue
        calendar = "us_federal_fiscal_year" if item.periods else "calendar"
        members = groups.setdefault((key, units, item.frequency, item.transform, item.seasonal_adjustment, calendar), [])
        if any(code.casefold() == seen.casefold() for _item, seen, _label in members):
            continue
        if len(members) < _MAX_COMPARE_LINES:
            members.append((item, code, label))
    eligible = [members for members in groups.values() if len(members) >= 2]
    eligible.sort(key=lambda members: (-len(members), min(item.order for item, _c, _l in members)))
    return [[(item, label) for item, _code, label in members]
            for members in eligible[:_MAX_COMPARE_CHARTS]]


def _compare_slug(group: list, used: set) -> str:
    first = group[0][0]
    native = _native_geo(first)
    base = f"{native[0][0]}_{native[0][1]}" if native else (_strip_geo(first.title) or first.series)
    slug = "compare_" + _derive_slug(base)[:48].rstrip("_")
    candidate, n = slug, 2
    while candidate in used:
        candidate = f"{slug}_{n}"
        n += 1
    used.add(candidate)
    return candidate


def _compare_projection_from(group: list) -> dt.date | None:
    starts = [item.projection_from for item, _label in group
              if item.projection_from is not None
              and any(item.is_projection(day) for day, _value in item.points)]
    return min(starts) if starts else None


def _compare_bundle(group: list, lang: str) -> dict:
    first = group[0][0]
    chrome = _CHROME[lang]
    if lang == "zh" and first.title_zh:
        title = _strip_geo(first.title_zh, _ZH_GEO_RE) or first.title_zh
    else:
        title = _strip_geo(first.title) or first.title or first.native
    labels = []
    for item, label in group:
        zh_geo = _ZH_GEO_RE.search(item.title_zh or "") if lang == "zh" else None
        labels.append(_clean_text(zh_geo.group(0) if zh_geo else label, 24))
    providers: list = []
    for item, _label in group:
        name = item.provider_name or item.provider.upper()
        if name not in providers:
            providers.append(name)
    retrieved = max((item.retrieved for item, _label in group), default="")
    return {
        "lang": lang,
        "title": title,
        "subtitle": _subtitle(first.frequency, first.seasonal_adjustment, first.transform,
                              None, lang),
        "ylabel": first.units,
        "footer": _footer(" / ".join(providers), first.provider,
                          [item.native for item, _label in group], retrieved, lang),
        **{status: chrome[status] for status in _STATUS_STYLE},
        "labels": labels,
    }


def _spread(positions: list, gap: float, low: float = 0.02, high: float = 0.98) -> list:
    """Deterministically push label positions (axes fraction) at least *gap* apart."""
    n = len(positions)
    if n == 0:
        return []
    if gap * (n - 1) > high - low:
        gap = (high - low) / (n - 1)
    order = sorted(range(n), key=lambda i: (positions[i], i))
    ys = [min(max(positions[i], low), high) for i in order]
    for k in range(1, n):
        ys[k] = max(ys[k], ys[k - 1] + gap)
    if ys[-1] > high:
        ys[-1] = high
        for k in range(n - 2, -1, -1):
            ys[k] = min(ys[k], ys[k + 1] - gap)
    out = [0.0] * n
    for rank, index in enumerate(order):
        out[index] = ys[rank]
    return out


def _end_positions(group: list, y_low: float, y_high: float) -> list:
    span = (y_high - y_low) or 1.0
    natural = [(item.numeric_points()[-1][1] - y_low) / span for item, _label in group]
    return _spread(natural, gap=0.075)


def _draw_compare(group: list, bundle: dict, fonts: _Fonts):
    fig, ax = _new_figure()
    _style_axes(ax, bundle["lang"], fonts, bundle["ylabel"])
    x_low, x_high = _group_x_limits(group)
    handles, labels = [], []
    shown_statuses = set()
    for index, (item, _label) in enumerate(group):
        color = _PALETTE[index]
        handle = None
        for status, (xs, ys) in _status_segments(item).items():
            shown_statuses.add(status)
            (line,) = ax.plot(xs, ys, color=color, linewidth=1.6, zorder=3,
                              linestyle=_STATUS_STYLE[status][0],
                              marker=_STATUS_STYLE[status][2] if status != "observed" else None, markersize=3.5,
                              solid_joinstyle="round", dash_capstyle="round")
            iso_x, iso_y = _isolated(xs, ys)
            if iso_x and status == "observed":
                ax.plot(iso_x, iso_y, marker="o", markersize=3.5, color=color,
                        linestyle="none", zorder=3)
            handle = handle or line
        latest = item.latest_observed()
        if latest is not None:
            ax.plot([latest[0]], [latest[1]], marker="o", markersize=5, markerfacecolor=color,
                    markeredgecolor=_SURFACE, markeredgewidth=1.2, linestyle="none",
                    zorder=5, clip_on=False)
        handles.append(handle)
        labels.append(bundle["labels"][index])
        for start, end in _projection_spans(item):
            ax.axvspan(max(start, x_low), min(end, x_high), facecolor=_BAND_COLOR,
                       alpha=_BAND_ALPHA, linewidth=0, zorder=0)
    for status in _STATUS_STYLE:
        if status in shown_statuses and status != "observed":
            handles.append(Line2D([], [], color=_INK_2, linestyle=_STATUS_STYLE[status][0],
                                  marker=_STATUS_STYLE[status][2], markersize=4))
            labels.append(bundle[status])
    ax.set_xlim(x_low, x_high)
    y_low, y_high = _y_range([item for item, _l in group])
    ax.set_ylim(y_low, y_high)
    _fiscal_axis(ax, group[0][0], bundle["lang"])
    _zero_line(ax)
    # 直接末端标签：右侧边距内按最小间距排开，彩色引导线连回各自线端（文字用墨色）。
    positions = _end_positions(group, y_low, y_high)
    for index, ((item, _label), text) in enumerate(zip(group, bundle["labels"])):
        day, value = item.numeric_points()[-1]
        label = _mpl_text(text)
        ax.annotate(label, xy=(day, value), xycoords="data", xytext=(1.015, positions[index]),
                    textcoords="axes fraction", ha="left", va="center", color=_INK_2,
                    annotation_clip=False, fontproperties=fonts.prop(label, 8),
                    arrowprops={"arrowstyle": "-", "color": _PALETTE[index],
                                "linewidth": 0.9, "shrinkA": 2, "shrinkB": 3})
    legend_text = " ".join(labels)
    ax.legend(handles, labels, loc="upper left", bbox_to_anchor=(0.0, -0.12),
              ncol=min(len(labels), 4), frameon=False, borderaxespad=0.0, handlelength=2.4,
              columnspacing=1.4, handler_map={tuple: HandlerTuple(ndivide=1)},
              prop=fonts.prop(legend_text, 8.5), labelcolor=_INK_2)
    _layout(fig, ax, bundle, fonts)
    return fig


def _plotly_compare(group: list, bundle: dict):
    fig = go.Figure()
    x_low, x_high = _group_x_limits(group)
    y_low, y_high = _y_range([item for item, _l in group])
    for index, (item, _label) in enumerate(group):
        color = _PALETTE[index]
        name = _plotly_text(bundle["labels"][index])
        hover = _status_hover(item)
        segments = _status_segments(item)
        for status, (xs, ys) in segments.items():
            label = name if set(segments) == {"observed"} else name + " — " + bundle[status]
            fig.add_trace(go.Scatter(
                x=_iso(xs), y=_nullable(ys), mode="lines+markers", name=label, legendgroup=name,
                showlegend=True, connectgaps=False, hovertemplate=f"{_plotly_text(label)}<br>{hover}",
                customdata=[item.period_label(day, bundle["lang"]) for day in xs],
                line={"color": color, "width": 2, "dash": _STATUS_STYLE[status][1]},
                marker={"symbol": {"o": "circle", "x": "x", "^": "triangle-up", "s": "square"}[_STATUS_STYLE[status][2]], "size": 5},
            ))
        latest = item.latest_observed()
        if latest is not None:
            fig.add_trace(go.Scatter(
                x=[latest[0].isoformat()], y=[latest[1]], mode="markers", showlegend=False,
                legendgroup=name, hovertemplate=f"{name}<br>{hover}",
                customdata=[item.period_label(latest[0], bundle["lang"])],
                marker={"color": color, "size": 8, "line": {"color": _SURFACE, "width": 2}},
            ))
    positions = _end_positions(group, y_low, y_high)
    for index, text in enumerate(bundle["labels"]):
        fig.add_annotation(
            xref="paper", yref="paper", x=1.0, y=positions[index], xanchor="left",
            yanchor="middle", xshift=6, showarrow=False, font={"size": 11, "color": _INK_2},
            text=f'<span style="color:{_PALETTE[index]}">━</span> {_plotly_text(text)}',
        )
    for item, _ in group:
        for start, end in _projection_spans(item):
            fig.add_vrect(x0=max(start, x_low).isoformat(), x1=min(end, x_high).isoformat(),
                          fillcolor=_BAND_COLOR, opacity=_BAND_ALPHA, line_width=0, layer="below")
    _plotly_layout(fig, bundle, showlegend=True, x_low=x_low, x_high=x_high, right_margin=130)
    fig.update_yaxes(range=[y_low, y_high])
    _plotly_fiscal_axis(fig, group[0][0], bundle["lang"])
    return fig


# ---------------------------------------------------------------------------
# 输出写盘（原子替换，只写 charts/ 之内）
# ---------------------------------------------------------------------------
def _save_png(fig, path: Path) -> None:
    """Deterministic PNG: fixed canvas/dpi, no 'Software' text chunk, atomic replace."""
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.stem}.", suffix=".png")
    os.close(fd)
    try:
        fig.savefig(tmp, format="png", dpi=_DPI, facecolor=_SURFACE,
                    metadata={"Software": None})
        _publish(tmp, path)
    finally:
        plt.close(fig)
        if os.path.exists(tmp):
            os.unlink(tmp)


def _write_html(fig, path: Path, title: str) -> bool:
    """Self-contained HTML (plotly.js inline, document title + data favicon, no trailing
    whitespace — same document contract as forecast-visuals). False on failure."""
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.stem}.", suffix=".html")
    os.close(fd)
    try:
        fig.update_layout(paper_bgcolor=_SURFACE, plot_bgcolor=_SURFACE)
        fig.write_html(tmp, include_plotlyjs=True, full_html=True,
                       div_id=f"data-visual-{path.stem}", config={"displaylogo": False})
        raw = Path(tmp).read_text(encoding="utf-8")
        if "</head>" in raw.lower():
            metadata = (f"<title>{html_lib.escape(title)}</title>"
                        f'<link rel="icon" href="{_EMBEDDED_FAVICON}">')
            raw = re.sub(r"</head>", lambda _m: metadata + "</head>", raw, count=1,
                         flags=re.IGNORECASE)
        clean = "\n".join(line.rstrip(" \t") for line in raw.splitlines()) + "\n"
        Path(tmp).write_text(clean, encoding="utf-8")
        _publish(tmp, path)
        return True
    except Exception as exc:  # noqa: BLE001 — HTML 孪生图失败不影响 PNG
        _log(f"{path.name}: plotly HTML export failed ({type(exc).__name__}: {exc})")
        return False
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


# ---------------------------------------------------------------------------
# 清单条目（title/caption 数字中性化）
# ---------------------------------------------------------------------------
def _manifest_title(text: str, lang: str, suffix: str = "") -> str:
    title = _clean_text(_digit_free(text), 110)
    if not title or not _is_digit_free(title):
        title = "官方数据序列" if lang == "zh" else "Official data series"
    return title + suffix


def _caption(items: list, lang: str, *, compare: bool) -> str:
    """Short, digit-free reader caption: source family + how to read the marks."""
    short = _PROVIDER_SHORT[lang]
    sources: list = []
    for item in items:
        name = short.get(item.provider) or _digit_free(item.provider_name) or \
            ("官方来源" if lang == "zh" else "an official source")
        if name not in sources:
            sources.append(name)
    has_projection = any(any(item.is_projection(day) for day, _v in item.points) for item in items)
    has_gaps = any(value is None for item in items for _day, value in item.points[1:-1])
    latest = any(item.latest_observed() is not None for item in items)
    statuses = {item.status(day) for item in items for day, value in item.points if value is not None}
    fiscal = [period for item in items for period in item.periods.values()]
    fiscal_labels = sorted({period["label"] for period in fiscal})
    fiscal_note = "–".join([fiscal_labels[0], fiscal_labels[-1]]) if fiscal_labels else ""
    partial = any(not period["complete"] for period in fiscal)
    if lang == "zh":
        parts = ["官方数据：" + "、".join(sources),
                 "各经济体同轴对比" if compare else "",
                 "圆点标记最新实际观测值" if latest else "",
                 "、".join(_CHROME[lang][s] for s in ("unknown", "preliminary", "estimate") if s in statuses),
                 fiscal_note, "含部分财政年度合计" if partial else "",
                 "虚线段与阴影为预测" if has_projection else "",
                 "断线处为缺测期" if has_gaps else ""]
        text = "；".join(part for part in parts if part) + "。"
    else:
        parts = ["Official series from " + " and ".join(sources),
                 "economies compared on one axis" if compare else "",
                 ("latest observations marked" if compare else "latest observation marked") if latest else "",
                 ", ".join(_CHROME[lang][s] for s in ("unknown", "preliminary", "estimate") if s in statuses),
                 fiscal_note, "partial fiscal aggregates labeled" if partial else "",
                 "dashed shaded segment = projection" if has_projection else "",
                 "breaks mark missing periods" if has_gaps else ""]
        text = "; ".join(part for part in parts if part) + "."
    text = _clean_text(_digit_free(text) if not _is_digit_free(text) else text, 240)
    if not _is_digit_free(text):
        text = "官方数据序列；状态见图例。" if lang == "zh" else \
            "Official statistical series; see status labels."
    return text


def _entry(chart_id: str, title: str, caption: str, series: list, html_ok: bool) -> dict:
    row = {
        "id": chart_id,
        "title": title,
        "caption": caption,
        "source_data": _SOURCE_DATA,
        "data_class": _DATA_CLASS,
        "path": f"charts/{chart_id}.png",
    }
    if html_ok:
        row["html_path"] = f"charts/{chart_id}.html"
    row["series"] = series
    return row


def _render_series(item: _Series, charts_dir: Path, lang: str) -> dict:
    chart_id = item.chart_id
    if not _SAFE_NAME_RE.match(chart_id):
        raise ValueError(f"unsafe chart id {chart_id!r}")
    bundle, fonts = _with_fonts(lambda candidate: _series_bundle(item, candidate), lang, chart_id)
    with plt.rc_context(_rc()):
        _save_png(_draw_series(item, bundle, fonts), charts_dir / f"{chart_id}.png")
    html_ok = _HAS_PLOTLY and _write_html(
        _plotly_series(item, _series_bundle(item, lang)), charts_dir / f"{chart_id}.html",
        _clean_text(bundle["title"], 160))
    title_text = item.title_zh if lang == "zh" and item.title_zh else item.title
    return _entry(chart_id, _manifest_title(title_text, lang),
                  _caption([item], lang, compare=False), [item.series], html_ok)


def _render_compare(group: list, charts_dir: Path, lang: str, used: set) -> dict:
    chart_id = f"{_OWNED_PREFIX}{_compare_slug(group, used)}"
    if not _SAFE_NAME_RE.match(chart_id):
        raise ValueError(f"unsafe chart id {chart_id!r}")
    bundle, fonts = _with_fonts(lambda candidate: _compare_bundle(group, candidate), lang, chart_id)
    with plt.rc_context(_rc()):
        _save_png(_draw_compare(group, bundle, fonts), charts_dir / f"{chart_id}.png")
    html_ok = _HAS_PLOTLY and _write_html(
        _plotly_compare(group, _compare_bundle(group, lang)), charts_dir / f"{chart_id}.html",
        _clean_text(bundle["title"], 160))
    title_bundle = _compare_bundle(group, lang)
    suffix = "：跨经济体对比" if lang == "zh" else ": cross-economy comparison"
    items = [item for item, _label in group]
    return _entry(chart_id, _manifest_title(title_bundle["title"], lang, suffix),
                  _caption(items, lang, compare=True), [item.series for item in items], html_ok)


# ---------------------------------------------------------------------------
# charts.json 合并（与 forecast-visuals render.py 同一锁协议）
# ---------------------------------------------------------------------------
def _owned(row) -> bool:
    chart_id = row.get("id") if isinstance(row, dict) else None
    return isinstance(chart_id, str) and chart_id.strip().startswith(_OWNED_PREFIX)


def _merge_manifest(manifest_path: Path, new_entries: list) -> list:
    """Drop every previous ``data_`` row, keep all other rows in order, append this run's."""
    existing = _read_json(manifest_path)
    rows = [row for row in existing if isinstance(row, dict)] if isinstance(existing, list) else []
    merged = [row for row in rows if not _owned(row)]
    seen: set = set()
    for entry in new_entries:
        if _owned(entry) and entry["id"] not in seen:
            merged.append(entry)
            seen.add(entry["id"])
    return merged


@contextmanager
def _manifest_update_lock(manifest_path: Path):
    """Serialize the manifest read-merge-write transaction across renderers."""
    lock_path = manifest_path.with_name(manifest_path.name + ".lock")
    with open(lock_path, "a+", encoding="utf-8") as lock_file:
        if fcntl is not None:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            if fcntl is not None:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def _update_manifest(manifest_path: Path, entries: list) -> list:
    """Lock, merge, and atomically persist one renderer transaction."""
    with _manifest_update_lock(manifest_path):
        merged = _merge_manifest(manifest_path, entries)
        _atomic_write(manifest_path, json.dumps(merged, ensure_ascii=False, indent=2) + "\n")
        return merged


def _drop_stale_rows(manifest_path: Path) -> None:
    """No eligible data now: remove previous ``data_`` rows so the UI never shows stale charts
    (an absent manifest is left absent)."""
    if manifest_path.is_file() and any(_owned(row) for row in (_read_json(manifest_path) or [])
                                       if isinstance(row, dict)):
        _update_manifest(manifest_path, [])


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def _default_max() -> int:
    raw = str(os.environ.get("DATA_SOURCES_CHARTS_MAX", "") or "").strip()
    try:
        value = int(raw) if raw else _DEFAULT_MAX
    except ValueError:
        _log(f"DATA_SOURCES_CHARTS_MAX={raw!r} is not an integer; using {_DEFAULT_MAX}")
        value = _DEFAULT_MAX
    return max(0, value)


def _parse_args(argv):
    ap = argparse.ArgumentParser(description="data-visuals renderer: official series → charts")
    ap.add_argument("--dir", required=True,
                    help="run directory holding data/datasets.json (charts land in <dir>/charts)")
    ap.add_argument("--max", type=int, default=None,
                    help="max single-series charts (default: DATA_SOURCES_CHARTS_MAX or 8); "
                         "comparison charts (≤ 2) are extra")
    ap.add_argument("--lang", choices=("en", "zh"), default="en",
                    help="chart and manifest language (zh uses title_zh when present)")
    args = ap.parse_args(argv)
    args.max = max(0, args.max) if args.max is not None else _default_max()
    return args


def main(argv=None) -> int:
    args = _parse_args(argv)
    summary: dict = {"charts": [], "skipped": [], "dropped": []}

    def finish(code: int, error: str = "") -> int:
        if error:
            summary["error"] = error
        print(json.dumps(summary, ensure_ascii=False), flush=True)
        return code

    if not _HAS_MPL and args.max != 0:
        _log("matplotlib is not importable — install it or use the skill's faithful-table fallback")
        return finish(3, "matplotlib unavailable")
    base = Path(args.dir)
    if not base.is_dir():
        _log(f"run directory {args.dir} does not exist")
        return finish(2, "run directory does not exist")
    base = base.resolve()
    manifest_path = base / "charts.json"
    if args.max == 0:
        _drop_stale_rows(manifest_path)
        return finish(2, "data charts disabled by zero chart cap")

    rows, reason = _load_manifest(base)
    if rows is None:
        _log(reason)
        _drop_stale_rows(manifest_path)
        return finish(2, reason)

    items: list = []
    used_slugs: set = set()
    seen_series: set = set()
    for order, row in enumerate(rows):
        raw_id = _clean_text(row.get("series"), 160) if isinstance(row, dict) else ""
        key = raw_id.casefold()
        if key and key in seen_series:
            summary["skipped"].append({"series": raw_id, "reason": "duplicate series in datasets.json"})
            continue
        item, why = _load_series(base, row, order, used_slugs)
        if item is None:
            summary["skipped"].append({"series": raw_id or f"row {order + 1}", "reason": why})
            _log(f"{raw_id or f'row {order + 1}'}: skipped ({why})")
            continue
        seen_series.add(key)
        items.append(item)
    if not items:
        _drop_stale_rows(manifest_path)
        return finish(2, "no series with at least two numeric observations")

    selected, summary["dropped"] = _select(items, args.max)
    for dropped in summary["dropped"]:
        _log(f"{dropped['series']}: dropped ({dropped['reason']})")

    charts_dir = base / "charts"
    if charts_dir.is_symlink() or (charts_dir.exists() and not charts_dir.is_dir()):
        _log("charts/ is a symlink or not a directory; refusing to write outside the run directory")
        return finish(2, "charts/ is not a plain directory inside the run directory")
    charts_dir.mkdir(exist_ok=True)

    entries: list = []
    charted: list = []
    for item in selected:
        try:
            entries.append(_render_series(item, charts_dir, args.lang))
            charted.append(item)
            _log(f"{item.chart_id}: wrote {entries[-1]['path']}")
        except Exception as exc:  # noqa: BLE001 — 单图失败绝不拖垮其余
            _log(f"{item.chart_id}: render failed ({type(exc).__name__}: {exc})")
            summary["skipped"].append({"series": item.series,
                                       "reason": f"render failed ({type(exc).__name__})"})
    used_compare: set = set()
    for group in _compare_groups(charted):
        try:
            entries.append(_render_compare(group, charts_dir, args.lang, used_compare))
            _log(f"{entries[-1]['id']}: wrote {entries[-1]['path']}")
        except Exception as exc:  # noqa: BLE001
            members = ", ".join(item.series for item, _label in group)
            _log(f"comparison of {members}: render failed ({type(exc).__name__}: {exc})")
            summary["skipped"].append({"series": members,
                                       "reason": f"comparison render failed ({type(exc).__name__})"})

    if not entries:
        _drop_stale_rows(manifest_path)
        return finish(2, "every eligible series failed to render")
    merged = _update_manifest(manifest_path, entries)
    summary["charts"] = [entry["id"] for entry in entries]
    _log(f"charts.json updated ({len(entries)} data charts, {len(merged)} rows total)")
    return finish(0)


if __name__ == "__main__":
    raise SystemExit(main())
