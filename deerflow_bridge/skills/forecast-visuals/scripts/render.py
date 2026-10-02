#!/usr/bin/env python3
"""forecast-visuals 捆绑渲染器 —— 管线工件 → 自包含 plotly 图表（WAVE9-RQ4）。

从一个运行目录（--dir，默认 CWD）读取结构化工件并渲染研究图表：

    actors.json        {actors:[{name,role_class,...}],
                        relationships:[{source,target,type,sign/valence/polarity,...}]}
    timeline.json      [{date, event}]
    quantitative.json  [{metric, value, unit, as_of_date, tier, ...}]
    prediction_markets.json
                        {as_of, markets:[{question,implied_yes_prob,volume,...}]}
    sources.json       [{title,url,tier,date,staleness_days,...}]
    charts_data.json   （可选兜底：{actors, relationships, timeline, quantitative,
                        prediction_markets, sources} ——
                        供抽取尚未落盘时由 agent 自写数据的 write-step 流程）

输出（全部落在 <dir>/charts/ 下 + <dir>/charts.json 清单）：
    charts/actor_network.{html,png}   actor 关系网络（可选 context；默认不产出）
    charts/timeline.{html,png}        分道事件时间线（按日期，≤40 事件，悬停出全文）
    charts/quant_metrics.{html,png}   同分母定量基准面板（实际值/预测值分符号）
    charts/metric_trajectories.{html,png}
                                      同一指标族（metric_family）跨地区/分析师的历史/预测轨迹
                                      （同族 ≥3 个不同年份才连线；预测点须有外部发布来源）
    charts/forecast_revisions.{html,png}
                                      同一预测指标跨三个以上发布版本的修订轨迹
    charts/market_probabilities.{html,png}
                                      最高流动性预测市场的隐含 P(yes)
    charts/source_quality.{html,png}  来源层级构成 + 时效性分布（诊断图，默认不产出；
                                      仅 --diagnostics / RESEARCH_CHARTS_INCLUDE_DIAGNOSTICS=1
                                      时渲染，且绝不进研究报告正文）

设计约束（与 SKILL.md 的失败模式清单一致）：
  * 缺哪个工件跳哪张图，绝不造数据；单图失败绝不拖垮其余（每图独立 try/except）。
  * 视觉主题与报告端 WAVE9 统一（见下方 WAVE9-THEME 块：#fcfcfb 画布、CVD-safe
    分类色板、顶部右侧图例、同款字体栈/网格），源真值是
    backend/app/services/report_visualizer.py。
  * HTML 自包含（plotly.js 内联），无网络依赖。
  * PNG：kaleido 可导入且能出图 → 用之；否则 matplotlib 简化重绘；两者皆无 → 只出
    HTML（清单条目仍登记，path 指向 html）。
  * plotly 缺失 → matplotlib-only PNG；plotly 与 matplotlib 都缺 → exit 3 并给出明确
    stderr（调用方按 degrade-safe 跳过整步）。
  * charts.json 跨进程加锁并原子整写（读旧清单 → 按稳定生产者 ID 替换 → 重写），
    幂等可重跑且并发渲染不会丢失外部生产者条目。

Exit codes: 0 = 至少写出一张图或清单已更新；2 = 无任何可渲染工件；3 = 无图形库。
"""

from __future__ import annotations

import argparse
from contextlib import contextmanager
import datetime as dt
import html as html_lib
import json
import math
import os
import re
import sys
import tempfile
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

try:
    import fcntl  # POSIX deployment: serialize cross-process manifest updates.
except ImportError:  # pragma: no cover - Windows remains atomic last-writer-wins.
    fcntl = None  # type: ignore

# ---------------------------------------------------------------------------
# 图形库探测（degrade 阶梯：plotly(+kaleido) → matplotlib → 无库退出 3）
# ---------------------------------------------------------------------------
try:
    import plotly.graph_objects as go  # type: ignore
    from plotly.subplots import make_subplots  # type: ignore
    _HAS_PLOTLY = True
except Exception:  # noqa: BLE001 — 导入失败即降级
    go = None  # type: ignore
    make_subplots = None  # type: ignore
    _HAS_PLOTLY = False

try:
    import matplotlib
    matplotlib.use("Agg")  # 无头环境
    import matplotlib.pyplot as plt  # type: ignore
    _HAS_MPL = True
except Exception:  # noqa: BLE001
    plt = None  # type: ignore
    _HAS_MPL = False

# ---------------------------------------------------------------------------
# WAVE9-THEME — duplicated verbatim from the report-stage renderer so research
# and report charts read as one product.
# SOURCE OF TRUTH: backend/app/services/report_visualizer.py（“WAVE9 统一图表
# 风格” 常量块 _VIZ_FONT/_PALETTE/_SEQ_BLUES/_COLOR_*/_SURFACE/_GRID/_AXIS/
# _INK/_INK_2 与 _apply_layout）。本脚本运行在 deer-flow venv、不可 import
# backend 包，只能整块复制。
# SYNC OBLIGATION: report_visualizer.py 的主题常量一旦变更，必须同步改这里
# （整块保持逐字一致以便 diff 校验），并重跑 runtime_skill_sync.py 让
# deer-flow/skills/public 的部署副本保持字节一致。未在本文件使用的常量
# （如 _COLOR_MARKET/_COLOR_GOOD）也保留，正是为了整块 diff 可核对。
# ---------------------------------------------------------------------------
_VIZ_FONT = ('system-ui, -apple-system, "Segoe UI", "Helvetica Neue", Arial, '
             '"PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", "Noto Sans CJK SC", '
             'sans-serif')
_PALETTE = ["#2a78d6", "#1baf7a", "#eda100", "#008300",
            "#4a3aa7", "#e34948", "#e87ba4", "#eb6834"]
_SEQ_BLUES = ["#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95"]
_COLOR_MODEL = "#2a78d6"    # 模型概率（分类槽 1 蓝）
_COLOR_MARKET = "#e34948"   # 市场隐含概率（发散对红极）
_COLOR_POS = "#1baf7a"      # 正向/结盟边
_COLOR_NEG = "#e34948"      # 负向/对抗边
_COLOR_NEU = "#b3b1a9"      # 中性/交易型边
_COLOR_STALE = "#d03b3b"    # 状态色 critical（陈旧/不可达标记，不与分类色混用）
_COLOR_GOOD = "#0ca30c"     # 状态色 good（可达）
_SURFACE = "#fcfcfb"
_GRID = "#e1e0d9"
_AXIS = "#c3c2b7"
_INK = "#0b0b0b"
_INK_2 = "#52514e"

# WAVE9 图例约定：顶部右侧横排（与 report_visualizer 各构建器一致）。
_WAVE9_LEGEND = {"orientation": "h", "yanchor": "bottom", "y": 1.02,
                 "xanchor": "right", "x": 1}

# 观测/预测双态色：与 report_visualizer 的 quantitative 构建器完全一致
# （Observed / reported = 分类槽 1 蓝；Published forecast / target = 分类槽 3 琥珀）。
_COLOR_OBSERVED = _COLOR_MODEL
_COLOR_FORECAST = _PALETTE[2]


def _apply_wave9_layout(fig, title: str, height=None, **kwargs) -> None:
    """统一 plotly 布局（镜像 report_visualizer._apply_layout）：浅色画布 + 细网格 +
    固定分类色板 + CJK 安全字体栈。就地修改 fig；height=None 时保留内容自驱高度。
    kwargs 覆盖默认布局键（margin/legend/axis 等），与 report 端调用形态一致。"""
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


def _mpl_finalize(f, path: str) -> None:
    """matplotlib 降级面同样落在 WAVE9 画布上：surface 底色 + 灰轴/刻度，再保存关图。"""
    f.patch.set_facecolor(_SURFACE)
    for ax in f.get_axes():
        ax.set_facecolor(_SURFACE)
        for spine in ax.spines.values():
            spine.set_color(_AXIS)
        ax.tick_params(colors=_INK_2, labelcolor=_INK_2)
    f.tight_layout()
    f.savefig(path, facecolor=_SURFACE)
    plt.close(f)


# 角色类 → 颜色（与 SKILL.md 的 role_class 分组一致；未知类回退中性灰）。
# 色相取自 WAVE9 固定顺序分类色板（绝不循环生成）；槽位组合已通过 dataviz
# 六检验证（all-pairs），CVD 6–8 底线对由节点常开直接标签兜底。
_ROLE_COLORS = {
    "principal": _PALETTE[0],     # 蓝
    "arbiter": _PALETTE[4],       # 紫
    "stakeholder": _PALETTE[1],   # 绿
    "amplifier": _PALETTE[2],     # 琥珀
    "intermediary": _PALETTE[6],  # 粉
}
_ROLE_FALLBACK = _COLOR_NEU
# 边 valence → 颜色：对抗（发散红极）/ 合作（正向绿）/ 治理（紫槽）/ 其他中性灰。
_EDGE_COLORS = {
    "adversarial": _COLOR_NEG,
    "cooperative": _COLOR_POS,
    "governance": _PALETTE[4],
}
_EDGE_FALLBACK = _COLOR_NEU
_LEVEL_WEIGHT = {
    "very high": 4.0, "high": 3.0, "medium": 2.0, "moderate": 2.0,
    "med": 2.0, "low": 1.0, "very low": 0.5,
}

# 本渲染器独占的六个生产者。charts.json 还可以包含 agent/用户自定义图表，
# 所以清理时只能替换这些稳定身份，不能整个覆盖 manifest。
_OWNED_CHART_IDS = (
    "actor_network",
    "timeline",
    "quant_metrics",
    "metric_trajectories",
    "forecast_revisions",
    "market_probabilities",
    "source_quality",
)
def _env_truthy(value) -> bool:
    """环境变量真值判定：1/true/yes/on（大小写不敏感）为真；空/未设/其它为假。"""
    return str(value or "").strip().casefold() in {"1", "true", "yes", "on"}


def _log(msg: str) -> None:
    print(f"[render] {msg}", file=sys.stderr)


def _read_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _atomic_write(path: Path, text: str) -> None:
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=path.name, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            try:
                os.unlink(tmp)
            except OSError:
                pass


def _num(v) -> float | None:
    """从 value 抽首个数字（'54' / '54.2' / '~$54B（2026 capex）' 都取 54/54.2）。"""
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return float(v) if v == v else None
    m = re.search(r"-?\d+(?:[.,]\d+)?", str(v or "").replace(",", ""))
    if not m:
        return None
    try:
        return float(m.group(0))
    except ValueError:
        return None


def _num_range(value) -> tuple[float, float] | None:
    """Return an explicit numeric range without inventing uncertainty."""
    text = str(value or "").replace(",", "")
    match = re.search(
        r"(-?\d+(?:\.\d+)?)\s*(?:[-–—~]|to)\s*(-?\d+(?:\.\d+)?)",
        text,
        re.IGNORECASE,
    )
    if not match:
        return None
    lo, hi = float(match.group(1)), float(match.group(2))
    return (min(lo, hi), max(lo, hi))


_UNIT_ALIASES = {
    "% new vehicle sales": "% new car sales",
    "% of new vehicle sales": "% new car sales",
    "% of new car sales": "% new car sales",
    "usd/kwh": "USD per kWh",
    "usd per kwh": "USD per kWh",
    "us$ per kwh": "USD per kWh",
    "$/kwh": "USD per kWh",
}
_AMBIGUOUS_UNITS = {
    "%", "percent", "percentage", "unit", "units", "million units",
    "billion units", "count", "number", "usd million", "usd billion",
    "eur million", "eur billion", "cny million", "cny billion",
}
_FORECAST_SIGNAL_RE = re.compile(
    r"\b(?:forecast(?:ed|s|ing)?|project(?:ed|ion|ions)?|outlook|"
    r"estimate(?:d|s)?|expected|expectation|guidance|scenario|target|"
    r"revision|revised)\b",
    re.IGNORECASE,
)
_INTERNAL_FORECAST_SOURCE_RE = re.compile(
    r"\b(?:internal|dossier|synthesis|working\s+(?:assumption|interpolation)|"
    r"analyst\s+interpolation|our\s+(?:case|estimate|forecast))\b|内部推演|本报告|分析师插值",
    re.IGNORECASE,
)
_DENOMINATOR_PATTERNS = (
    ("fleet", r"\b(?:fleet|vehicle stock|installed base|vehicles? on (?:the )?road)\b"),
    ("registrations", r"\bregistrations?\b"),
    ("deliveries", r"\bdeliver(?:y|ies|ed)\b"),
    ("shipments", r"\bshipments?\b"),
    ("production", r"\bproduction\b"),
    ("capacity", r"\bcapacity\b"),
    ("revenue", r"\b(?:revenue|turnover)\b"),
    ("population", r"\bpopulation\b"),
    ("households", r"\bhouseholds?\b"),
    ("respondents", r"\brespondents?\b"),
    ("gdp", r"\bgdp\b"),
    ("sales", r"\bsales?\b"),
)
_TIME_BASIS_PATTERNS = (
    ("ytd", r"\b(?:ytd|year[- ]to[- ]date)\b"),
    ("trailing", r"\b(?:ttm|trailing\s+(?:twelve|12)\s+months?)\b"),
    ("monthly", r"\b(?:monthly|month)\b"),
    ("quarterly", r"\b(?:quarterly|quarter|q[1-4])\b"),
    ("annual", r"\b(?:annual|annually|yearly|calendar year|full[- ]year|fy\s*20\d{2})\b"),
)
_MEASURE_FAMILY_PATTERNS = (
    ("growth", r"\b(?:growth|cagr|change)\b"),
    ("share", r"\b(?:share|penetration|adoption|mix)\b"),
    ("price", r"\b(?:price|cost|capex)\b"),
    ("margin", r"\bmargin\b"),
    ("rate", r"\b(?:rate|yield)\b"),
    ("capacity", r"\bcapacity\b"),
    ("production", r"\b(?:production|output)\b"),
    ("volume", r"\b(?:sales|deliveries|shipments|registrations)\b"),
    ("density", r"\bdensity\b"),
    ("range", r"\brange\b"),
    ("emissions", r"\b(?:emissions?|intensity)\b"),
    ("revenue", r"\brevenue\b"),
)
_SUBJECT_STOPWORDS = {
    "actual", "adoption", "annual", "annually", "average", "calendar", "capacity",
    "car", "cars", "cost", "daily", "deliveries", "delivery", "domestic", "fleet",
    "forecast", "forecasted", "global", "growth", "market", "margin", "monthly",
    "new", "observed", "only", "passenger", "penetration", "percent", "percentage",
    "price", "production", "projected", "projection", "quarter", "quarterly", "rate",
    "region", "regional", "registrations", "reported", "revenue", "sale", "sales",
    "share", "shipments", "specific", "target", "total", "unit", "units", "vehicle",
    "vehicles", "volume", "weighted", "year", "yearly", "ytd", "the", "and", "for",
    "from", "into", "during", "with", "without", "per", "of", "to", "in", "on", "as",
}
_REVISION_NOISE_WORDS = {
    "a", "an", "at", "by", "edition", "estimate", "estimated", "for", "forecast",
    "forecasted", "forecasting", "forecasts", "in", "of", "on", "outlook", "projection",
    "projections", "projected", "publication", "published", "revision", "revisions",
    "revised", "scenario", "the", "to", "target", "update", "updated", "version", "vintage",
}
_GENERIC_SOURCE_FAMILY_WORDS = {
    "analysis", "forecast", "outlook", "projection", "recap", "report", "research", "source", "study",
}
_TIER_RANK = {"S1": 0, "S2": 1, "S3": 2, "S4": 3}


def _canonical_unit(unit) -> str:
    raw = re.sub(r"\s+", " ", str(unit or "")).strip()
    return _UNIT_ALIASES.get(raw.lower(), raw) if raw else ""


def _comparable_unit(unit) -> bool:
    canonical = _canonical_unit(unit)
    low = canonical.lower()
    if not low or low == "date" or low in _AMBIGUOUS_UNITS:
        return False
    if "%" in canonical:
        return len(low.replace("%", "").strip()) >= 3
    if " per " in low or "/" in low or " of " in low:
        return True
    return bool(re.fullmatch(
        r"(?:[kmgt]?wh|wh/kg|kg|tonnes?|barrels?|credits?|bps|basis points)", low
    ))


def _is_projection(row: dict) -> bool:
    explicit = row.get("is_projection")
    if isinstance(explicit, bool):
        return explicit
    is_actual = row.get("is_actual")
    if isinstance(is_actual, bool):
        return not is_actual
    for key in ("value_type", "observation_type", "fact_type", "status"):
        label = re.sub(r"[^a-z]+", "_", str(row.get(key) or "").casefold()).strip("_")
        if label in {"actual", "historical", "observed", "reported"}:
            return False
        if label in {"forecast", "forecasted", "projection", "projected", "target", "expected"}:
            return True
    text = " ".join(str(row.get(key) or "") for key in ("metric", "definition")).lower()
    return bool(_FORECAST_SIGNAL_RE.search(text))


def _truncate(s: str, n: int) -> str:
    s = str(s or "").strip()
    return s if len(s) <= n else s[: n - 1] + "…"


def _plotly_text(value) -> str:
    """Escape reader text and neutralize Plotly/MathJax dollar delimiters.

    Plotly treats paired ``$`` characters as TeX.  A perfectly ordinary event
    such as ``US$192 ... US$55`` therefore lost its numbered key and rendered a
    stray math fragment in the PNG.  Currency is prose here, so spell it as
    ``USD`` before HTML escaping instead of invoking MathJax.
    """
    text = str(value or "")
    text = re.sub(r"\bUS\$", "USD ", text, flags=re.IGNORECASE)
    text = re.sub(r"(?<![A-Za-z])\$", "USD ", text)
    return html_lib.escape(text)


def _parse_date(v) -> dt.date | None:
    """Parse an ISO-like source date without consulting wall-clock time."""
    raw = str(v or "").strip()
    match = re.search(r"\d{4}-\d{2}-\d{2}", raw)
    if not match:
        return None
    try:
        return dt.date.fromisoformat(match.group(0))
    except ValueError:
        return None


def _unit_denominator_key(unit: str) -> str:
    low = unit.casefold()
    if "margin" in low:
        return "revenue"
    for label, pattern in _DENOMINATOR_PATTERNS:
        if re.search(pattern, low):
            return label
    if " per " in low:
        return re.sub(r"[^a-z0-9]+", " ", low.rsplit(" per ", 1)[1]).strip()
    if "/" in low:
        return re.sub(r"[^a-z0-9]+", " ", low.rsplit("/", 1)[1]).strip()
    return low


def _quant_denominator_key(unit: str, definition: str) -> str | None:
    unit_key = _unit_denominator_key(unit)
    if "%" not in unit:
        return unit_key
    markers = {
        label for label, pattern in _DENOMINATOR_PATTERNS
        if re.search(pattern, definition, re.IGNORECASE)
    }
    if not markers:
        return unit_key
    if markers == {unit_key}:
        return unit_key
    return None


def _quant_time_basis(row: dict, metric: str, definition: str) -> str:
    explicit = []
    period = row.get("period")
    if isinstance(period, dict):
        for key in ("period_start", "period_end", "start", "end", "frequency", "label"):
            if period.get(key):
                explicit.append(f"{key}:{period[key]}")
    elif period:
        explicit.append(str(period))
    for key in ("period_start", "period_end", "frequency", "time_basis"):
        if row.get(key):
            explicit.append(f"{key}:{row[key]}")
    if explicit:
        return re.sub(r"\s+", " ", "|".join(explicit)).casefold().strip()
    text = f"{metric} {definition}"
    labels = [label for label, pattern in _TIME_BASIS_PATTERNS if re.search(pattern, text, re.IGNORECASE)]
    return "+".join(labels) if labels else "as-of"


def _quant_measure_family(metric: str, definition: str) -> str:
    text = f"{metric} {definition}"
    for label, pattern in _MEASURE_FAMILY_PATTERNS:
        if re.search(pattern, text, re.IGNORECASE):
            return label
    return re.sub(r"[^a-z0-9]+", " ", definition.casefold()).strip()


def _quant_subject_tokens(metric: str, definition: str) -> frozenset[str]:
    text = f"{metric} {definition}".casefold()
    text = re.sub(r"\b(?:battery electric vehicles?|plug[- ]in hybrid electric vehicles?)\b", " ev ", text)
    text = re.sub(r"\b(?:electric vehicles?|electric cars?|bev|phev|nev|zev)\b", " ev ", text)
    tokens = {
        token for token in re.findall(r"[a-z][a-z0-9]+", text)
        if token not in _SUBJECT_STOPWORDS and not re.fullmatch(r"20\d{2}", token)
    }
    if tokens:
        return frozenset(tokens)
    fallback = re.sub(r"\b20\d{2}\b", " ", definition.casefold())
    fallback = re.sub(r"[^a-z0-9]+", " ", fallback).strip()
    return frozenset({f"definition:{fallback}"}) if fallback else frozenset()


def _split_quant_families(rows: list[dict]) -> list[list[dict]]:
    families = []
    for row in rows:
        subjects = row["_subjects"]
        for family in families:
            common = family["common"] & subjects
            if common:
                family["rows"].append(row)
                family["common"] = common
                break
        else:
            families.append({"rows": [row], "common": subjects})
    return [family["rows"] for family in families if len(family["rows"]) >= 2]


def _quant_panel_subject(rows: list[dict]) -> str:
    """Build a compact common-subject label for one strict comparison panel."""
    if not rows:
        return "Comparable benchmarks"
    # Use metric labels for the visible title. Definitions are intentionally
    # verbose and may share boilerplate such as "class range cited" or
    # "approximately N hours" that is useful for grouping but awful as a title.
    metric_tokens = []
    for row in rows:
        tokens = {
            token
            for token in re.findall(r"[a-z][a-z0-9]+", str(row.get("metric") or "").casefold())
            if token not in _SUBJECT_STOPWORDS and not re.fullmatch(r"20\d{2}", token)
        }
        metric_tokens.append(tokens)
    common = set(metric_tokens[0]) if metric_tokens else set()
    for tokens in metric_tokens[1:]:
        common &= tokens
    common -= {"current", "best", "day", "intra", "multi", "target", "installed", "storage"}
    ordered = []
    first_text = str(rows[0].get("metric") or "")
    for token in re.findall(r"[a-z][a-z0-9]+", first_text.casefold()):
        if token in common and token not in ordered:
            ordered.append(token)
    if not ordered:
        base = "Comparable benchmarks"
    else:
        display = {"ldes": "LDES", "ev": "EV", "ai": "AI", "lcos": "LCOS"}
        base = " ".join(display.get(token, token) for token in ordered[:6])
    projections = {bool(row.get("projection")) for row in rows}
    if projections == {False}:
        return f"Current {base}"
    if projections == {True}:
        years = {
            int(year)
            for row in rows
            for year in re.findall(r"\b(20\d{2})\b", str(row.get("metric") or ""))
        }
        return f"{next(iter(years))} {base} targets" if len(years) == 1 \
            else f"{base} forecasts / targets"
    return base


def _source_outlook_family(source: str) -> str:
    text = source.casefold()
    text = re.sub(r"[’']s\b", "", text)
    text = re.sub(r"\[[^\]]*\]|【[^】]*】", " ", text)
    text = re.sub(
        r"\b(?:bloomberg\s*nef|bloombergnef|bloomberg new energy finance)\b",
        "bnef",
        text,
    )
    text = re.sub(r"\belectric vehicle outlook\b", "evo", text)
    text = re.sub(r"\bgevo\b", "global ev outlook", text)
    text = re.sub(r"\b20\d{2}\b", " ", text)
    noise = {
        "cited", "edition", "published", "publication", "recap", "recapping", "revision",
        "revised", "update", "updated", "version", "vintage",
    }
    tokens = [token for token in re.findall(r"[a-z][a-z0-9]+", text) if token not in noise]
    if not tokens or all(token in _GENERIC_SOURCE_FAMILY_WORDS for token in tokens):
        return ""
    return " ".join(tokens)


def _revision_target_year(name: str, definition: str, vintage: int) -> int | None:
    years = {int(year) for year in re.findall(r"\b(20\d{2})\b", f"{name} {definition}")}
    years.discard(vintage)
    return next(iter(years)) if len(years) == 1 else None


def _revision_identity_text(
    text: str,
    *,
    publisher_family: str,
    vintage: int,
    target_year: int,
) -> str:
    normalized = text.casefold()
    normalized = re.sub(
        r"\b(?:bloomberg\s*nef|bloombergnef|bloomberg new energy finance)\b",
        "bnef",
        normalized,
    )
    normalized = re.sub(r"\belectric vehicles?\b", "ev", normalized)
    normalized = re.split(
        r"\b(?:post|after|following|due to|because of|in response to)\b",
        normalized,
        maxsplit=1,
    )[0]
    normalized = re.sub(rf"\b(?:{vintage}|{target_year})\b", " ", normalized)
    publisher_tokens = set(publisher_family.split())
    tokens = [
        token for token in re.findall(r"[a-z][a-z0-9]+", normalized)
        if token not in _REVISION_NOISE_WORDS and token not in publisher_tokens
    ]
    return " ".join(tokens)


def _source_identity(row: dict) -> str:
    """Canonicalize a source identity without lowercasing case-sensitive paths."""
    raw_url = str(row.get("url") or "").strip()
    if raw_url:
        try:
            parsed = urlsplit(raw_url)
            if parsed.scheme and parsed.netloc:
                path = parsed.path.rstrip("/")
                return urlunsplit(
                    (parsed.scheme.lower(), parsed.netloc.lower(), path, parsed.query, "")
                )
        except ValueError:
            pass
        return raw_url.rstrip("/")
    return str(row.get("title") or "").strip().lower()


# ---------------------------------------------------------------------------
# 数据准备（纯函数——plotly 与 matplotlib 两个渲染面消费同一份 prep）
# ---------------------------------------------------------------------------


def prep_network(actors_obj, max_nodes: int = 30):
    """actors.json → optional relationship map with explicit, bounded proxy sizing.

    Only declared numeric scores or ordinal tiers may size nodes.  Numbers
    embedded in salience prose are never parsed.  Relationship endpoints are
    canonicalized through names, aliases, and a unique parenthetical prefix.
    """
    if not isinstance(actors_obj, dict):
        return None
    actors = [a for a in (actors_obj.get("actors") or []) if isinstance(a, dict) and str(a.get("name") or "").strip()]
    if not actors:
        return None

    def _influence(a) -> float:
        salience = a.get("salience")
        explicit = (
            a.get("influence_score"),
            a.get("salience_score"),
            salience.get("score") if isinstance(salience, dict) else None,
            a.get("influence") if isinstance(a.get("influence"), (int, float)) else None,
        )
        for raw in explicit:
            v = _num(raw)
            if v is not None:
                return v
        for raw in (
            a.get("influence"),
            salience.get("tier") if isinstance(salience, dict) else salience,
        ):
            level = _LEVEL_WEIGHT.get(str(raw or "").strip().lower())
            if level is not None:
                return level
        return 1.0

    actors = sorted(actors, key=lambda a: -_influence(a))[: max(2, max_nodes)]
    names = [str(a["name"]).strip() for a in actors]

    def _actor_key(value) -> str:
        return re.sub(r"\s+", " ", str(value or "")).strip(" .,;:'\"()").casefold()

    alias_candidates: dict[str, set[str]] = {}
    for actor, canonical in zip(actors, names, strict=False):
        candidates = [canonical]
        aliases = actor.get("aliases")
        if isinstance(aliases, list):
            candidates.extend(str(alias) for alias in aliases)
        prefix = re.sub(r"\s*\([^)]*\)\s*$", "", canonical).strip()
        if prefix and prefix != canonical:
            candidates.append(prefix)
        for candidate in candidates:
            key = _actor_key(candidate)
            if key:
                alias_candidates.setdefault(key, set()).add(canonical)
    alias_map = {
        key: next(iter(values)) for key, values in alias_candidates.items() if len(values) == 1
    }
    # 角色类分组圆布局：同 role_class 的节点相邻（角度连续段），确定性（无随机布局）。
    groups: dict[str, list[int]] = {}
    for i, a in enumerate(actors):
        groups.setdefault(str(a.get("role_class") or "other").strip().lower() or "other", []).append(i)
    pos: dict[int, tuple[float, float]] = {}
    ordered = [i for g in sorted(groups) for i in groups[g]]
    for rank, i in enumerate(ordered):
        theta = 2.0 * math.pi * rank / max(1, len(ordered))
        pos[i] = (math.cos(theta), math.sin(theta))
    infl = [_influence(a) for a in actors]
    max_i = max(infl) or 1.0
    nodes = []
    for i, a in enumerate(actors):
        rc = str(a.get("role_class") or "other").strip().lower() or "other"
        nodes.append({
            "name": names[i],
            "x": pos[i][0], "y": pos[i][1],
            "size": 14 + 26 * (infl[i] / max_i),
            "color": _ROLE_COLORS.get(rc, _ROLE_FALLBACK),
            "role_class": rc,
        })
    idx = {_actor_key(n): i for i, n in enumerate(names)}
    edges = []
    seen_edges: set = set()
    for r in actors_obj.get("relationships") or []:
        if not isinstance(r, dict):
            continue
        source_raw = str(r.get("source") or "").strip()
        target_raw = str(r.get("target") or "").strip()
        s = alias_map.get(_actor_key(source_raw))
        t = alias_map.get(_actor_key(target_raw))
        if not s or not t or _actor_key(s) == _actor_key(t):
            continue
        rtype = str(r.get("type") or "").strip().upper()
        key = (_actor_key(s), _actor_key(t), rtype)
        if key in seen_edges:  # 重复边去重（诊断里的 COMPETES_WITH ×4）
            continue
        seen_edges.add(key)
        valence = str(r.get("valence") or r.get("sign") or "").strip().lower()
        polarity = _num(r.get("polarity"))
        if valence in {"allied", "ally", "supportive", "positive", "cooperative", "+"}:
            semantic = "cooperative"
        elif valence in {"rival", "adversarial", "negative", "opposed", "-"}:
            semantic = "adversarial"
        elif valence in {"governance", "directional", "regulatory"} or rtype in {
            "REGULATES", "GOVERNS", "ENFORCES",
        }:
            semantic = "governance"
        elif polarity is not None and polarity > 0.15:
            semantic = "cooperative"
        elif polarity is not None and polarity < -0.15:
            semantic = "adversarial"
        else:
            semantic = "neutral"
        i, j = idx[_actor_key(s)], idx[_actor_key(t)]
        edges.append({
            "x0": pos[i][0], "y0": pos[i][1], "x1": pos[j][0], "y1": pos[j][1],
            "color": _EDGE_COLORS.get(semantic, _EDGE_FALLBACK),
            "label": f"{s} —{rtype or 'REL'}→ {t}" + (f" ({valence})" if valence else ""),
        })
    if not edges and len(nodes) < 3:
        return None
    return {"nodes": nodes, "edges": edges}


def prep_timeline(rows, max_events: int = 40):
    """timeline.json → dated points with stable numeric keys.

    Full event prose belongs in hover/the key, not on top of data points.  The
    stable index lets dense date clusters remain readable in both HTML and PNG.
    """
    events = []
    for r in rows or []:
        if not isinstance(r, dict):
            continue
        date = str(r.get("date") or "").strip()
        event = str(r.get("event") or "").strip()
        if date and event:
            events.append((date, event))
    if not events:
        return None
    # 去重（同日期同文案）后按日期排序；超上限保最近的 max_events 条。
    events = sorted(set(events), key=lambda e: e[0])
    if len(events) > max_events:
        events = events[-max_events:]
    lane_last_date: dict[int, dt.date] = {}
    points = []
    for i, (date, event) in enumerate(events):
        # Keep the exact evidence date on x while allocating a visual lane that
        # avoids marker collisions in dense clusters.  This changes layout
        # only: the date in the data, key and hover remains untouched.
        parsed_date = _parse_date(date)
        preferred_lanes = [((i + offset) % 6) + 1 for offset in range(6)]
        lane = preferred_lanes[0]
        if parsed_date is not None:
            lane = next(
                (
                    candidate
                    for candidate in preferred_lanes
                    if candidate not in lane_last_date
                    or (parsed_date - lane_last_date[candidate]).days >= 30
                ),
                min(
                    preferred_lanes,
                    key=lambda candidate: lane_last_date.get(candidate, dt.date.min),
                ),
            )
            lane_last_date[lane] = parsed_date
        points.append({
            "index": i + 1,
            "date": date,
            "lane": lane,
            "label": _truncate(event, 90),
            "full": event,
        })
    return {"points": points}


def prep_quant(rows, max_bars: int = 10, max_panels: int = 3):
    """quantitative.json → strict same-denominator benchmark panels.

    Plain percentages, generic counts and broad currency units are rejected:
    they commonly mix margins, shares, periods or definitions despite looking
    numerically compatible.  Source/as-of/projection metadata survives for
    labels and hover text.
    """
    groups: dict[tuple[str, str, str, str, str], list[dict]] = {}
    for idx, r in enumerate(rows or []):
        if not isinstance(r, dict):
            continue
        interval = _num_range(r.get("value"))
        # An explicit interval owns its displayed center. A conflicting model-
        # supplied value_num must not place the marker outside its own whisker.
        v = (sum(interval) / 2.0) if interval else _num(r.get("value_num"))
        if v is None:
            v = _num(r.get("value"))
        metric = str(r.get("metric") or "").strip()
        unit = _canonical_unit(r.get("unit"))
        if v is None or not metric or not _comparable_unit(unit):
            continue
        source = str(r.get("source") or "").strip()
        definition = str(r.get("definition") or "").strip()
        as_of = _parse_date(r.get("as_of_date"))
        if not source or not definition or as_of is None:
            continue
        projection = _is_projection(r)
        staleness = _num(r.get("staleness_days"))
        # A future-dated actual is no observation: negative age, or the typed
        # recency pass's is_future_dated (which withholds the age).
        future_dated = (staleness is not None and staleness < 0) or r.get("is_future_dated") is True
        if future_dated and not projection:
            continue
        denominator = _quant_denominator_key(unit, definition)
        if not denominator:
            continue
        time_basis = _quant_time_basis(r, metric, definition)
        measure_family = _quant_measure_family(metric, definition)
        subjects = _quant_subject_tokens(metric, definition)
        if not measure_family or not subjects:
            continue
        key = (unit.casefold(), as_of.isoformat(), time_basis, denominator, measure_family)
        groups.setdefault(key, []).append({
            "metric": metric, "value": v,
            "value_label": str(r.get("value") or f"{v:g}").strip(),
            "low": interval[0] if interval else v,
            "high": interval[1] if interval else v,
            "unit": unit,
            "as_of": as_of.isoformat(),
            "tier": str(r.get("tier") or "").strip(),
            "source": source,
            "definition": definition,
            "projection": projection,
            "stale": bool(r.get("is_stale")),
            "_subjects": subjects,
            "idx": idx,
        })
    eligible = []
    for key, values in groups.items():
        eligible.extend((key, family) for family in _split_quant_families(values))
    if not eligible:
        return None
    eligible.sort(key=lambda item: (-len(item[1]), item[0]))
    panels = []
    for key, values in eligible[:max_panels]:
        values.sort(key=lambda row: (
            _TIER_RANK.get(row["tier"].upper(), 9),
            row["stale"],
            row["projection"],
            row["idx"],
        ))
        bars = []
        for row in values[:max_bars]:
            clean = {field: value for field, value in row.items() if not field.startswith("_")}
            bars.append({
                **clean,
                "label": _truncate(
                    row["metric"] + (f" (as of {row['as_of']})" if row["as_of"] else ""),
                    72,
                ),
            })
        panels.append({
            "unit": values[0]["unit"],
            "title": _quant_panel_subject(values),
            "as_of": key[1],
            "time_basis": key[2],
            "bars": bars,
        })
    return {"panels": panels}


def _trajectory_series_name(row: dict) -> str:
    explicit = re.sub(r"\s+", " ", str(row.get("series") or "")).strip()
    if explicit:
        explicit = re.sub(r"\b20\d{2}\b", " ", explicit)
        explicit = re.sub(
            r"\b(?:actual|observed|reported|forecast|forecasted|projected|target|"
            r"base case|q[1-4]|h[12]|fy)\b",
            " ",
            explicit,
            flags=re.IGNORECASE,
        )
        explicit = re.sub(r"\s+", " ", explicit).strip(" -–—:()")
        if explicit:
            return explicit
    metric = re.sub(r"\s+", " ", str(row.get("metric") or "")).strip()
    metric = re.sub(r"\b20\d{2}\b", " ", metric)
    metric = re.sub(
        r"\b(?:actual|observed|reported|forecast|forecasted|projected|target)\b",
        " ",
        metric,
        flags=re.IGNORECASE,
    )
    return re.sub(r"\s+", " ", metric).strip(" -–—:()")


# 地区规范化（与 deerflow_research 的富化保持同义），供跨行同族按地区分线。
_TRAJ_REGION_ALIASES = {
    "us": "United States", "u.s.": "United States", "usa": "United States",
    "u.s.a.": "United States", "america": "United States",
    "united states": "United States", "united states of america": "United States",
    "china": "China", "prc": "China", "mainland china": "China", "p.r.c.": "China",
    "eu": "Europe", "e.u.": "Europe", "europe": "Europe", "european union": "Europe",
    "european": "Europe", "india": "India", "bharat": "India",
    "global": "Global", "world": "Global", "worldwide": "Global", "row": "Global",
    "international": "Global",
}


def _canonical_region(text) -> str:
    raw = re.sub(r"\s+", " ", str(text or "")).strip()
    if not raw:
        return "Global"
    return _TRAJ_REGION_ALIASES.get(raw.casefold(), raw)


def _trajectory_unit_bucket(unit: str) -> str:
    """单位桶：把 % 归成 'percent'，其余用规范单位小写。用于同族内隔离量纲，
    防止把比率值与计数值误连进同一条轨迹（即便 metric_family 分类偶有噪声）。"""
    low = (unit or "").casefold()
    return "percent" if "%" in low else low


def _trajectory_year(row: dict) -> "int | None":
    """规范目标年（供 x 轴分桶）：canonical ``year`` → period_end/target_date →
    period.end；仅对『预测/目标』行再兜底从 metric/series 文本取最晚年份。

    观测行没有结构化 period_end 时不从文本猜——沿用旧约束，避免把发布日误画成观测年。
    """
    y = row.get("year")
    if isinstance(y, (int, float)) and not isinstance(y, bool) and 1900 <= int(y) <= 2100:
        return int(y)
    for key in ("period_end", "target_date"):
        d = _parse_date(row.get(key))
        if d is not None:
            return d.year
    period = row.get("period") if isinstance(row.get("period"), dict) else {}
    d = _parse_date(period.get("period_end") or period.get("end"))
    if d is not None:
        return d.year
    if _is_projection(row):
        text = f"{row.get('metric') or ''} {row.get('series') or ''}"
        years = [int(m) for m in re.findall(r"\b(20\d{2})\b", text)]
        if years:
            return max(years)  # 预测行文本里的年份即目标年，取最晚
    return None


def _trajectory_family(row: dict) -> str:
    """规范指标族：canonical ``metric_family`` 优先，否则折叠 series/metric 文本
    （去年份/口径词）。前者让不同分析师/年份的散点归到同族连线；后者兼容旧数据
    （同名系列跨年份仍能连成一条）。"""
    fam = re.sub(r"\s+", " ", str(row.get("metric_family") or "")).strip()
    if fam:
        return fam.casefold()
    return _trajectory_series_name(row).casefold()


def _trajectory_value(row: dict) -> "float | None":
    """取数：canonical ``value_num`` 优先，否则从 ``value`` 文本解析首个数字。"""
    vn = row.get("value_num")
    if isinstance(vn, (int, float)) and not isinstance(vn, bool) and vn == vn:
        return float(vn)
    return _num(row.get("value"))


def _trajectory_is_forecast(row: dict) -> bool:
    """actual/forecast：canonical ``value_kind`` 优先，否则回退既有 _is_projection。"""
    vk = re.sub(r"[^a-z]+", "", str(row.get("value_kind") or "").casefold())
    if vk in {"actual", "observed", "reported", "historical", "measured"}:
        return False
    if vk in {
        "forecast", "forecasted", "projection", "projected", "target",
        "estimate", "estimated", "expected", "guidance", "scenario",
    }:
        return True
    return _is_projection(row)


def _trajectory_row_is_publishable(row: dict, projection: bool) -> bool:
    """Fail closed on provenance needed to call a line sourced/published.

    Observations require a named source, definition and source as-of date.
    Forecast points additionally require an external URL and reject explicit
    dossier/internal analyst interpolations.  Such rows remain valid report
    tables; they simply cannot be mislabeled as a published trajectory.
    """
    source = re.sub(r"\s+", " ", str(row.get("source") or row.get("analyst") or "")).strip()
    definition = re.sub(r"\s+", " ", str(row.get("definition") or "")).strip()
    as_of = _parse_date(row.get("as_of_date"))
    if not source or not definition or as_of is None:
        return False
    if not projection:
        return True
    source_url = str(row.get("source_url") or "").strip()
    parsed_url = urlsplit(source_url)
    external_url = (
        parsed_url.scheme.casefold() in {"http", "https"}
        and bool(parsed_url.netloc)
    )
    return external_url and not _INTERNAL_FORECAST_SOURCE_RE.search(
        f"{source} {definition}"
    )


def prep_trajectories(rows, max_series: int = 4):
    """把 quantitative.json 的散点按 canonical 指标族归组，连成观测/预测轨迹。

    分组键 = (metric_family, region, technology, unit 桶)：同族同地区同量纲的多年份点
    连成一条线；观测点与预测点分色分符号（实线圆点 vs 虚线菱形）。x 轴用目标年（period_end
    优先，缺失则由 canonical ``year`` 或预测行文本年兜底，落成 ``YYYY-12-31``）。

    canonical 字段（value_num/year/metric_family/region/value_kind，由抽取侧富化补上）在则
    走精确分组；缺失时退化：折叠 series 名当族、结构化日期取年——旧数据仍能连出同名跨年轨迹。
    只渲染『≥3 个不同年份』的族，避免两点斜线被误读成趋势。观测点须有命名
    来源/定义/as-of；预测点还须有外部 source_url，内部 dossier/analyst 插值仅保留表格。
    """
    grouped: dict[tuple[str, str, str, str], dict] = {}
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        value = _trajectory_value(row)
        family = _trajectory_family(row)
        year = _trajectory_year(row)
        projection = _trajectory_is_forecast(row)
        if value is None or not family or year is None \
                or not _trajectory_row_is_publishable(row, projection):
            continue
        unit = _canonical_unit(row.get("unit"))
        region = _canonical_region(row.get("region") or row.get("geography"))
        tech = re.sub(
            r"\s+", " ", str(row.get("technology") or row.get("technology_route") or "")
        ).strip()
        if tech.casefold() in {"all routes", "all", "n/a", "none"}:
            tech = ""
        # x 轴用真实 period_end（有则用），否则由目标年合成年末，保证可连线。
        nested_period = row.get("period") if isinstance(row.get("period"), dict) else {}
        period_end = _parse_date(
            row.get("period_end")
            or row.get("target_date")
            or nested_period.get("period_end")
            or nested_period.get("end")
        )
        period_end_iso = period_end.isoformat() if period_end else f"{year:04d}-12-31"
        definition = re.sub(r"\s+", " ", str(row.get("definition") or "")).strip()
        source = str(row.get("source") or row.get("analyst") or "").strip()
        source_url = str(row.get("source_url") or "").strip()
        as_of = _parse_date(row.get("as_of_date"))
        # 展示名：优先 metric_family（规范族名）；否则折叠后的 series 名。
        display_name = re.sub(r"\s+", " ", str(row.get("metric_family") or "")).strip() \
            or _trajectory_series_name(row) or family
        key = (family, region.casefold(), tech.casefold(), _trajectory_unit_bucket(unit))
        series = grouped.setdefault(
            key,
            {
                "name": display_name,
                "unit": unit or "",
                "geography": region,
                "technology_route": tech or "All routes",
                "points": {},
            },
        )
        candidate = {
            "period_end": period_end_iso,
            "year": year,
            "value": value,
            "as_of": as_of.isoformat() if as_of else "",
            "source": source,
            "source_url": source_url,
            "definition": definition,
            "projection": projection,
            "tier": str(row.get("tier") or "S3").strip().upper() or "S3",
        }
        # 同一年只保留最高层级（tier）的那个点，避免重复年份堆叠。
        prior = series["points"].get(year)
        if prior is None or _TIER_RANK.get(candidate["tier"], 9) < _TIER_RANK.get(
            prior["tier"], 9
        ):
            series["points"][year] = candidate

    eligible = []
    for series in grouped.values():
        points = [series["points"][yr] for yr in sorted(series["points"])]
        if len({point["year"] for point in points}) >= 3:  # ≥3 个不同年份才成轨迹
            eligible.append({**series, "points": points})
    eligible.sort(key=lambda row: (-len(row["points"]), row["name"].casefold()))
    return {"series": eligible[:max_series]} if eligible else None


def prep_revisions(rows, max_series: int = 3):
    """Extract ≥3 semantically identical published forecast vintages."""
    grouped: dict[tuple[str, int, str, str, str], dict] = {}
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        metric = re.sub(r"\s+", " ", str(row.get("metric") or "")).strip()
        match = re.search(r"\((20\d{2})\)\s*$", metric)
        if not match:
            continue
        text = " ".join((metric, str(row.get("definition") or "")))
        if not _FORECAST_SIGNAL_RE.search(text):
            continue
        value = _num(row.get("value"))
        unit = _canonical_unit(row.get("unit"))
        source = str(row.get("source") or "").strip()
        definition = str(row.get("definition") or "").strip()
        as_of = _parse_date(row.get("as_of_date"))
        if value is None or not unit or not source or not definition or as_of is None:
            continue
        name = metric[:match.start()].rstrip(" -–—:")
        vintage = int(match.group(1))
        if vintage != as_of.year:
            continue
        publisher_family = _source_outlook_family(source)
        target_year = _revision_target_year(name, definition, vintage)
        if not publisher_family or target_year is None:
            continue
        metric_family = _revision_identity_text(
            name,
            publisher_family=publisher_family,
            vintage=vintage,
            target_year=target_year,
        )
        definition_family = _revision_identity_text(
            definition,
            publisher_family=publisher_family,
            vintage=vintage,
            target_year=target_year,
        )
        if not metric_family or not definition_family:
            continue
        key = (
            publisher_family,
            target_year,
            unit.casefold(),
            metric_family,
            definition_family,
        )
        series = grouped.setdefault(
            key,
            {
                "name": name,
                "unit": unit,
                "publisher_family": publisher_family,
                "target_year": target_year,
                "points": {},
            },
        )
        candidate = {
            "vintage": vintage,
            "value": value,
            "as_of": as_of.isoformat(),
            "source": source,
            "tier": str(row.get("tier") or "S3").strip().upper() or "S3",
            "stale": bool(row.get("is_stale")),
        }
        previous = series["points"].get(vintage)
        if previous is None or _TIER_RANK.get(candidate["tier"], 9) < _TIER_RANK.get(
            previous["tier"], 9
        ):
            series["points"][vintage] = candidate
    eligible = []
    for series in grouped.values():
        points = [series["points"][year] for year in sorted(series["points"])]
        if len(points) >= 3:
            eligible.append({
                "name": series["name"],
                "unit": series["unit"],
                "publisher_family": series["publisher_family"],
                "target_year": series["target_year"],
                "points": points,
            })
    eligible.sort(key=lambda series: (-len(series["points"]), series["name"].lower()))
    return {"series": eligible[:max_series]} if eligible else None


def prep_markets(payload, max_bars: int = 12):
    """prediction_markets.json → most-liquid matched markets with P(yes)."""
    as_of = ""
    if isinstance(payload, dict):
        rows = payload.get("markets") or []
        as_of = str(payload.get("as_of") or "").strip()
    elif isinstance(payload, list):
        rows = payload
    else:
        return None

    by_identity: dict[str, dict] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        question = str(row.get("question") or row.get("title") or "").strip()
        probability = _num(
            row.get("implied_yes_prob", row.get("yes_probability", row.get("probability")))
        )
        if probability is not None and 1.0 < probability <= 100.0:
            probability /= 100.0
        if not question or probability is None or not (0.0 < probability < 1.0):
            continue
        volume = max(0.0, _num(row.get("volume")) or 0.0)
        identity = str(row.get("market_id") or question).strip().lower()
        candidate = {
            "label": _truncate(question, 76),
            "question": question,
            "probability": probability,
            "volume": volume,
            "liquidity": max(0.0, _num(row.get("liquidity")) or 0.0),
            "market_id": str(row.get("market_id") or "").strip(),
            "end_date": str(row.get("end_date") or "").strip(),
        }
        previous = by_identity.get(identity)
        if previous is None or (candidate["volume"], candidate["question"]) > (
            previous["volume"], previous["question"]
        ):
            by_identity[identity] = candidate
    if not by_identity:
        return None

    markets = sorted(
        by_identity.values(),
        key=lambda row: (-row["volume"], row["question"].lower(), row["market_id"]),
    )[:max_bars]
    markets.reverse()  # horizontal bars: most liquid appears at the top
    return {"markets": markets, "as_of": as_of}


def prep_sources(payload, run_anchor=None):
    """sources.json → deduplicated source-tier and freshness distributions.

    Explicit ``staleness_days`` wins. Otherwise freshness is measured against
    the latest parseable source date in the artifact, keeping this pure and
    deterministic instead of consulting today's date.
    """
    if isinstance(payload, dict):
        rows = payload.get("sources") or []
    elif isinstance(payload, list):
        rows = payload
    else:
        return None

    unique: list[dict] = []
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        identity = _source_identity(row)
        if not identity or identity in seen:
            continue
        seen.add(identity)
        source_date = _parse_date(
            row.get("date") or row.get("publication_date") or row.get("published_at")
            or row.get("as_of_date")
        )
        unique.append({"row": row, "date": source_date})
    if not unique:
        return None

    dated = [item["date"] for item in unique if item["date"] is not None]
    authoritative_anchor = _parse_date(run_anchor)
    explicit_anchors: list[dt.date] = []
    for item in unique:
        explicit_age = _num(item["row"].get("staleness_days"))
        if item["date"] is not None and explicit_age is not None and explicit_age >= 0:
            explicit_anchors.append(
                item["date"] + dt.timedelta(days=int(round(explicit_age)))
            )
    if authoritative_anchor is not None:
        reference_date = authoritative_anchor
        reference_source = "run_metadata"
    elif explicit_anchors:
        anchor_counts: dict[dt.date, int] = {}
        for anchor in explicit_anchors:
            anchor_counts[anchor] = anchor_counts.get(anchor, 0) + 1
        reference_date = max(anchor_counts, key=lambda anchor: (anchor_counts[anchor], anchor))
        reference_source = "explicit_staleness_anchor"
    else:
        reference_date = max(dated) if dated else None
        reference_source = "latest_dated_source" if reference_date else "none"
    tier_order = ("S1", "S2", "S3", "S4", "Untiered")
    freshness_order = ("≤30 days", "31–90 days", "91–365 days", ">365 days", "Undated")
    tier_counts = dict.fromkeys(tier_order, 0)
    freshness_counts = dict.fromkeys(freshness_order, 0)
    explicit_staleness_count = 0

    for item in unique:
        row = item["row"]
        tier_match = re.search(r"\bS([1-4])\b", str(row.get("tier") or "").upper())
        tier_counts[f"S{tier_match.group(1)}" if tier_match else "Untiered"] += 1

        explicit_age = _num(row.get("staleness_days"))
        if explicit_age is not None:
            explicit_staleness_count += 1
        if item["date"] is not None and reference_date is not None:
            age = float(max(0, (reference_date - item["date"]).days))
        elif explicit_age is not None:
            age = max(0.0, explicit_age)
        else:
            age = None
        if age is None:
            freshness_counts["Undated"] += 1
        elif age <= 30:
            freshness_counts["≤30 days"] += 1
        elif age <= 90:
            freshness_counts["31–90 days"] += 1
        elif age <= 365:
            freshness_counts["91–365 days"] += 1
        else:
            freshness_counts[">365 days"] += 1

    return {
        "tiers": [{"label": label, "count": tier_counts[label]} for label in tier_order],
        "freshness": [
            {"label": label, "count": freshness_counts[label]} for label in freshness_order
        ],
        "total": len(unique),
        "reference_date": reference_date.isoformat() if reference_date else "",
        "reference_source": reference_source,
        "explicit_staleness_count": explicit_staleness_count,
    }


# ---------------------------------------------------------------------------
# 渲染（plotly HTML + PNG；PNG 走 kaleido，失败降 matplotlib，再失败只出 HTML）
# ---------------------------------------------------------------------------


_EMBEDDED_FAVICON = (
    "data:image/svg+xml,%3Csvg xmlns=%22http://www.w3.org/2000/svg%22 "
    "viewBox=%220 0 64 64%22%3E%3Crect width=%2264%22 height=%2264%22 "
    "rx=%2214%22 fill=%22%2308172b%22/%3E%3Cpath d=%22M18 33h28M32 19v28%22 "
    "stroke=%22%2354d4ff%22 stroke-width=%226%22/%3E%3C/svg%3E"
)


def _document_title(fig, stem: str) -> str:
    """Return a plain, deterministic browser title for a standalone chart."""
    try:
        raw = str(fig.layout.title.text or "")
    except Exception:  # noqa: BLE001 - optional plotly object can be partially mocked
        raw = ""
    plain = re.sub(r"<[^>]+>", " ", raw)
    plain = re.sub(r"\s+", " ", plain).strip()
    return plain or stem.replace("_", " ").title()


def _finalize_html_document(raw_html: str, title: str) -> str:
    """Add self-contained browser metadata without introducing network requests."""
    if "</head>" not in raw_html.lower():
        return raw_html
    metadata = (
        f"<title>{html_lib.escape(title)}</title>"
        f'<link rel="icon" href="{_EMBEDDED_FAVICON}">'
    )
    return re.sub(r"</head>", metadata + "</head>", raw_html, count=1, flags=re.IGNORECASE)


def _write_outputs(fig, mpl_draw, charts_dir: Path, stem: str) -> tuple[str | None, str | None]:
    """写 <stem>.html（plotly 可用时）+ <stem>.png（kaleido → matplotlib 降级）。
    返回 (png 相对路径 | None, html 相对路径 | None)；两者皆 None = 该图失败。"""
    html_rel = png_rel = None
    if _HAS_PLOTLY and fig is not None:
        # Pin the WAVE9 light surface so standalone PNG/PDF embedding stays
        # legible in dark-mode viewers, and respect each chart's content-driven
        # height instead of stretching every figure to the same 750px canvas.
        fig.update_layout(paper_bgcolor=_SURFACE, plot_bgcolor=_SURFACE)
        html_path = charts_dir / f"{stem}.html"
        try:
            fig.write_html(
                str(html_path),
                include_plotlyjs=True,
                full_html=True,
                div_id=f"forecast-visual-{stem}",
            )
            # Plotly's bundled JavaScript contains many line-ending spaces.
            # They are semantically inert but make generated assets fail
            # repository hygiene checks.  Normalize only trailing horizontal
            # whitespace while preserving line boundaries and final-newline
            # state so the self-contained document remains deterministic.
            raw_html = html_path.read_text(encoding="utf-8")
            raw_html = _finalize_html_document(raw_html, _document_title(fig, stem))
            had_final_newline = raw_html.endswith(("\n", "\r"))
            clean_html = "\n".join(line.rstrip(" \t") for line in raw_html.splitlines())
            if had_final_newline:
                clean_html += "\n"
            if clean_html != raw_html:
                html_path.write_text(clean_html, encoding="utf-8")
            html_rel = f"charts/{stem}.html"
        except Exception as e:  # noqa: BLE001
            _log(f"{stem}: write_html failed ({type(e).__name__}: {e})")
        png_path = charts_dir / f"{stem}.png"
        try:
            layout_height = int(getattr(fig.layout, "height", None) or 750)
            layout_width = int(getattr(fig.layout, "width", None) or 1200)
            fig.write_image(
                str(png_path),
                width=max(800, min(layout_width, 1800)),
                height=max(420, min(layout_height, 1800)),
                scale=2,
            )  # 需要 kaleido
            png_rel = f"charts/{stem}.png"
        except Exception as e:  # noqa: BLE001 — kaleido 缺失/Chrome 不可用 → matplotlib 降级
            _log(f"{stem}: plotly PNG export unavailable ({type(e).__name__}); trying matplotlib fallback")
    if png_rel is None and _HAS_MPL and mpl_draw is not None:
        png_path = charts_dir / f"{stem}.png"
        try:
            mpl_draw(str(png_path))
            png_rel = f"charts/{stem}.png"
        except Exception as e:  # noqa: BLE001
            _log(f"{stem}: matplotlib fallback failed ({type(e).__name__}: {e})")
    return png_rel, html_rel


def render_network(prep, charts_dir: Path):
    fig = None
    if _HAS_PLOTLY:
        fig = go.Figure()
        for e in prep["edges"]:
            fig.add_trace(go.Scatter(x=[e["x0"], e["x1"]], y=[e["y0"], e["y1"]], mode="lines",
                                     line={"color": e["color"], "width": 1.2},
                                     hoverinfo="text", text=e["label"], showlegend=False))
        nodes = prep["nodes"]
        fig.add_trace(go.Scatter(
            x=[n["x"] for n in nodes], y=[n["y"] for n in nodes],
            mode="markers+text", text=[n["name"] for n in nodes], textposition="top center",
            textfont={"size": 10},
            marker={"size": [n["size"] for n in nodes], "color": [n["color"] for n in nodes],
                        "line": {"color": _SURFACE, "width": 1}},
            hovertext=[f"{n['name']} ({n['role_class']})" for n in nodes], hoverinfo="text",
            showlegend=False))
        _apply_wave9_layout(
            fig, "Actor Relationship Network",
            xaxis={"visible": False}, yaxis={"visible": False},
            margin={"l": 20, "r": 20, "t": 60, "b": 20},
        )

    def mpl_draw(path: str) -> None:
        f, ax = plt.subplots(figsize=(12, 7.5), dpi=160)
        for e in prep["edges"]:
            ax.plot([e["x0"], e["x1"]], [e["y0"], e["y1"]], color=e["color"], lw=0.9, alpha=0.7, zorder=1)
        for n in prep["nodes"]:
            ax.scatter([n["x"]], [n["y"]], s=n["size"] ** 1.6, c=n["color"], zorder=2, edgecolors=_SURFACE)
            ax.annotate(n["name"], (n["x"], n["y"]), textcoords="offset points", xytext=(0, 8),
                        ha="center", fontsize=7)
        ax.set_title("Actor Relationship Network")
        ax.axis("off")
        _mpl_finalize(f, path)

    return _write_outputs(fig, mpl_draw, charts_dir, "actor_network")


def render_timeline(prep, charts_dir: Path):
    pts = prep["points"]
    lane_ceiling = max((point["lane"] for point in pts), default=1) + 1.5
    fig = None
    if _HAS_PLOTLY:
        fig = go.Figure(go.Scatter(
            x=[p["date"] for p in pts], y=[p["lane"] for p in pts],
            mode="markers+text", text=[f"{p['index']:02d}" for p in pts],
            textposition="middle center", textfont={"size": 8, "color": _SURFACE},
            hovertext=[f"<b>{_plotly_text(p['date'])}</b><br>{_plotly_text(p['full'])}" for p in pts],
            hoverinfo="text",
            marker={"size": 20, "color": _COLOR_MODEL,
                    "line": {"color": _SURFACE, "width": 1.5}}))
        key_columns = 2 if len(pts) > 14 else 1
        key_rows = max(1, math.ceil(len(pts) / key_columns))
        for position, point in enumerate(pts):
            column = position // key_rows
            row = position % key_rows
            fig.add_annotation(
                xref="paper", yref="paper", x=column / key_columns,
                y=-(0.14 + row * 0.055), showarrow=False,
                text=(f"<b>{point['index']:02d}</b>  {_plotly_text(point['date'])}  "
                      f"{_plotly_text(_truncate(point['label'], 68 if key_columns == 2 else 86))}"),
                xanchor="left", yanchor="top", align="left",
                font={"size": 9, "color": _INK_2},
            )
        _apply_wave9_layout(
            fig, f"Event Timeline ({len(pts)} key events)",
            height=max(620, 430 + 28 * key_rows),
            yaxis={"visible": False, "range": [0, lane_ceiling]}, xaxis_title="date",
            margin={"l": 30, "r": 30, "t": 60, "b": 90 + 23 * key_rows},
        )

    def mpl_draw(path: str) -> None:
        f, ax = plt.subplots(figsize=(12, 7.5), dpi=160)
        xs = list(range(len(pts)))
        ax.scatter(xs, [p["lane"] for p in pts], s=28, c=_COLOR_MODEL, zorder=2)
        for x, p in zip(xs, pts, strict=False):
            ax.annotate(f"{p['index']:02d}  {p['date']}\n{_truncate(p['label'], 54)}",
                        (x, p["lane"]),
                        textcoords="offset points", xytext=(0, 8), ha="center", fontsize=6)
        ax.set_title(f"Event Timeline ({len(pts)} key events)")
        ax.set_ylim(0, lane_ceiling)
        ax.set_yticks([])
        ax.set_xticks([])
        _mpl_finalize(f, path)

    return _write_outputs(fig, mpl_draw, charts_dir, "timeline")


def render_quant(prep, charts_dir: Path):
    panels = prep["panels"]
    title = "Comparable Forecast Benchmarks"
    fig = None
    if _HAS_PLOTLY:
        fig = make_subplots(
            rows=len(panels), cols=1,
            subplot_titles=[
                f"{panel['title']} · {panel['unit']} (n={len(panel['bars'])})"
                for panel in panels
            ],
            # Static exports need explicit breathing room between a panel's
            # x-axis title and the next panel heading.
            vertical_spacing=0.16,
            shared_xaxes=True,
        )
        shown = set()
        for row_no, panel in enumerate(panels, 1):
            for projection in (False, True):
                bars = [bar for bar in panel["bars"] if bar["projection"] is projection]
                if not bars:
                    continue
                status = "Published forecast / target" if projection else "Observed / reported"
                status_color = _COLOR_FORECAST if projection else _COLOR_OBSERVED
                fig.add_trace(go.Scatter(
                    x=[bar["value"] for bar in bars],
                    y=[bar["label"] + (" ⚠" if bar["stale"] else "") for bar in bars],
                    mode="markers",
                    name=status,
                    legendgroup=status,
                    showlegend=status not in shown,
                    marker={
                        "size": 11,
                        "symbol": "diamond" if projection else "circle",
                        "color": status_color,
                        "line": {
                            "color": [_COLOR_STALE if bar["stale"] else _SURFACE for bar in bars],
                            "width": 2,
                        },
                    },
                    error_x={
                        "type": "data",
                        "symmetric": False,
                        "array": [max(0.0, bar["high"] - bar["value"]) for bar in bars],
                        "arrayminus": [max(0.0, bar["value"] - bar["low"]) for bar in bars],
                        "visible": any(bar["high"] > bar["low"] for bar in bars),
                        "color": status_color,
                        "thickness": 1.4,
                    },
                    hovertext=["<br>".join(
                        part for part in (
                            f"<b>{_plotly_text(bar['metric'])}</b>",
                            f"{_plotly_text(bar['value_label'])} {panel['unit']}"
                            + (" · ⚠ stale" if bar["stale"] else ""),
                            f"as of {bar['as_of']}" if bar["as_of"] else "",
                            _plotly_text(bar["definition"]),
                            _plotly_text(bar["source"]),
                        ) if part
                    ) for bar in bars],
                    hoverinfo="text",
                ), row=row_no, col=1)
                shown.add(status)
            fig.update_xaxes(title_text=panel["unit"], row=row_no, col=1)
            fig.update_yaxes(autorange="reversed", row=row_no, col=1)
        _apply_wave9_layout(
            fig,
            f"{title}<br><sup>Each panel shares one explicit denominator; hover for source and as-of.</sup>",
            height=max(440, 260 * len(panels) + 120),
            margin={"l": 330, "r": 40, "t": 90, "b": 60},
            legend=dict(_WAVE9_LEGEND),
        )

    def mpl_draw(path: str) -> None:
        f, axes = plt.subplots(
            len(panels), 1, figsize=(12, max(7.5, 4.2 * len(panels))), dpi=160,
            squeeze=False,
        )
        for ax, panel in zip(axes[:, 0], panels, strict=False):
            bars = panel["bars"]
            ys = list(range(len(bars)))
            colors = [_COLOR_FORECAST if bar["projection"] else _COLOR_OBSERVED for bar in bars]
            markers = ["D" if bar["projection"] else "o" for bar in bars]
            for y, bar, color, marker in zip(ys, bars, colors, markers, strict=False):
                ax.errorbar(
                    [bar["value"]], [y],
                    xerr=[[max(0.0, bar["value"] - bar["low"])],
                          [max(0.0, bar["high"] - bar["value"])]],
                    color=color, marker=marker, markersize=7, capsize=3,
                    linestyle="none",
                )
            ax.set_yticks(ys, [bar["label"] + (" ⚠" if bar["stale"] else "") for bar in bars],
                          fontsize=7)
            ax.invert_yaxis()
            ax.set_title(f"{panel['title']} · {panel['unit']}")
            ax.set_xlabel(panel["unit"])
            ax.grid(axis="x", color=_GRID)
        f.suptitle(title)
        _mpl_finalize(f, path)

    return _write_outputs(fig, mpl_draw, charts_dir, "quant_metrics")


def render_trajectories(prep, charts_dir: Path):
    series = prep["series"]
    title = "Observed and Sourced Forecast Trajectories"
    fig = None
    if _HAS_PLOTLY:
        fig = make_subplots(
            rows=len(series), cols=1,
            subplot_titles=[
                f"{row['name']} · {row['geography']} · {row['unit']}"
                for row in series
            ],
            vertical_spacing=0.14,
        )
        shown = set()
        for row_no, row in enumerate(series, 1):
            points = row["points"]
            for projection in (False, True):
                subset = [point for point in points if point["projection"] is projection]
                if not subset:
                    continue
                status = "Published forecast / target" if projection else "Observed / reported"
                status_color = _COLOR_FORECAST if projection else _COLOR_OBSERVED
                fig.add_trace(
                    go.Scatter(
                        x=[point["year"] for point in subset],
                        y=[point["value"] for point in subset],
                        mode="lines+markers",
                        name=status,
                        legendgroup=status,
                        showlegend=status not in shown,
                        line={
                            "color": status_color,
                            "dash": "dash" if projection else "solid",
                            "width": 3,
                        },
                        marker={
                            "size": 10,
                            "symbol": "diamond" if projection else "circle",
                            "color": status_color,
                            "line": {"color": _SURFACE, "width": 2},
                        },
                        hovertext=["<br>".join(part for part in (
                            f"<b>{row['name']}</b>",
                            f"period end {point['period_end']}: {point['value']:g} {row['unit']}",
                            f"source as of {point['as_of']}",
                            _plotly_text(point["definition"]),
                            _plotly_text(point["source"]),
                            _plotly_text(point["source_url"]),
                        ) if part) for point in subset],
                        hoverinfo="text",
                    ),
                    row=row_no,
                    col=1,
                )
                shown.add(status)
            fig.update_xaxes(
                title_text="measurement / target year", dtick=1,
                row=row_no, col=1,
            )
            fig.update_yaxes(title_text=row["unit"], row=row_no, col=1)
        _apply_wave9_layout(
            fig,
            (
                f"{title}<br><sup>Period dates drive the x-axis; publication/as-of dates "
                "remain in hover. Dashed diamonds are forecasts or targets.</sup>"
            ),
            height=max(560, 330 * len(series)),
            margin={"l": 110, "r": 40, "t": 90, "b": 55},
            legend=dict(_WAVE9_LEGEND),
        )

    def mpl_draw(path: str) -> None:
        f, axes = plt.subplots(
            len(series), 1,
            figsize=(12, max(7.5, 4.2 * len(series))),
            dpi=160,
            squeeze=False,
        )
        for ax, row in zip(axes[:, 0], series, strict=False):
            for projection, color, marker, linestyle in (
                (False, _COLOR_OBSERVED, "o", "-"),
                (True, _COLOR_FORECAST, "D", "--"),
            ):
                points = [p for p in row["points"] if p["projection"] is projection]
                if not points:
                    continue
                ax.plot(
                    [p["year"] for p in points],
                    [p["value"] for p in points],
                    color=color,
                    marker=marker,
                    linestyle=linestyle,
                    lw=2.5,
                )
            ax.set_title(f"{row['name']} · {row['geography']}")
            ax.set_ylabel(row["unit"])
            ax.xaxis.set_major_locator(matplotlib.ticker.MaxNLocator(integer=True))
            ax.grid(color=_GRID)
        f.suptitle(title)
        _mpl_finalize(f, path)

    return _write_outputs(fig, mpl_draw, charts_dir, "metric_trajectories")


def render_revisions(prep, charts_dir: Path):
    series = prep["series"]
    title = "Forecast Revisions Across Published Vintages"
    fig = None
    if _HAS_PLOTLY:
        fig = make_subplots(
            rows=len(series), cols=1,
            subplot_titles=[f"{row['name']} · {row['unit']}" for row in series],
            vertical_spacing=0.14,
        )
        for row_no, row in enumerate(series, 1):
            points = row["points"]
            fig.add_trace(go.Scatter(
                x=[point["vintage"] for point in points],
                y=[point["value"] for point in points],
                mode="lines+markers+text",
                text=[f"{point['value']:g}" for point in points],
                textposition="top center",
                line={"color": _COLOR_MODEL, "width": 3},
                marker={"size": 10, "color": _COLOR_MODEL,
                        "line": {"color": _SURFACE, "width": 2}},
                hovertext=["<br>".join(part for part in (
                    f"<b>{row['name']}</b>",
                    f"vintage {point['vintage']}: {point['value']:g} {row['unit']}",
                    f"as of {point['as_of']}" if point["as_of"] else "",
                    point["source"],
                ) if part) for point in points],
                hoverinfo="text",
                showlegend=False,
            ), row=row_no, col=1)
            fig.update_xaxes(title_text="forecast vintage", dtick=1, row=row_no, col=1)
            fig.update_yaxes(title_text=row["unit"], row=row_no, col=1)
        _apply_wave9_layout(
            fig, title, height=max(520, 320 * len(series)),
            margin={"l": 100, "r": 40, "t": 75, "b": 45},
        )

    def mpl_draw(path: str) -> None:
        f, axes = plt.subplots(
            len(series), 1, figsize=(12, max(7.5, 4.2 * len(series))), dpi=160,
            squeeze=False,
        )
        for ax, row in zip(axes[:, 0], series, strict=False):
            points = row["points"]
            xs = [point["vintage"] for point in points]
            ys = [point["value"] for point in points]
            ax.plot(xs, ys, color=_COLOR_MODEL, marker="o", lw=2.5)
            for x, y in zip(xs, ys, strict=False):
                ax.annotate(f"{y:g}", (x, y), xytext=(0, 7), textcoords="offset points",
                            ha="center", fontsize=8)
            ax.set_title(f"{row['name']} · {row['unit']}")
            ax.set_xlabel("forecast vintage")
            ax.set_ylabel(row["unit"])
            ax.set_xticks(xs)
            ax.grid(color=_GRID)
        f.suptitle(title)
        _mpl_finalize(f, path)

    return _write_outputs(fig, mpl_draw, charts_dir, "forecast_revisions")


def render_markets(prep, charts_dir: Path):
    markets = prep["markets"]
    probabilities = [row["probability"] * 100.0 for row in markets]
    as_of = prep.get("as_of") or ""
    title = "Prediction-Market Implied Probabilities"
    if as_of:
        parsed_as_of = _parse_date(as_of)
        title += f" (as of {parsed_as_of.isoformat() if parsed_as_of else _truncate(as_of, 24)})"
    fig = None
    if _HAS_PLOTLY:
        customdata = [
            [row["volume"], row["liquidity"], row["market_id"], row["end_date"]]
            for row in markets
        ]
        fig = go.Figure(go.Bar(
            x=probabilities,
            y=[row["label"] for row in markets],
            orientation="h",
            marker={
                "color": probabilities,
                "colorscale": [[i / (len(_SEQ_BLUES) - 1), c]
                               for i, c in enumerate(_SEQ_BLUES)],
                "cmin": 0,
                "cmax": 100,
            },
            text=[f"{probability:.1f}%" for probability in probabilities],
            textposition="auto",
            customdata=customdata,
            hovertemplate=(
                "%{y}<br>P(yes): %{x:.1f}%<br>Volume: $%{customdata[0]:,.0f}"
                "<br>Liquidity: $%{customdata[1]:,.0f}<br>Market: %{customdata[2]}"
                "<br>Ends: %{customdata[3]}<extra></extra>"
            ),
        ))
        fig.add_vline(x=50, line_dash="dot", line_color=_AXIS, line_width=1)
        _apply_wave9_layout(
            fig, title,
            xaxis={"title": "market-implied P(yes)", "range": [0, 100], "ticksuffix": "%"},
            margin={"l": 360, "r": 40, "t": 70, "b": 40},
            showlegend=False,
        )

    def mpl_draw(path: str) -> None:
        f, ax = plt.subplots(figsize=(12, 7.5), dpi=160)
        bars = ax.barh([row["label"] for row in markets], probabilities, color=_COLOR_MODEL)
        if hasattr(ax, "bar_label"):
            ax.bar_label(bars, fmt="%.1f%%", padding=3, fontsize=7)
        ax.axvline(50, color=_AXIS, lw=1, ls="--")
        ax.set_xlim(0, 100)
        ax.set_title(title)
        ax.set_xlabel("market-implied P(yes), %")
        ax.tick_params(axis="y", labelsize=7)
        _mpl_finalize(f, path)

    return _write_outputs(fig, mpl_draw, charts_dir, "market_probabilities")


def render_sources(prep, charts_dir: Path):
    # barh draws the final row at the top; reverse so S1/freshest lead visually.
    tiers = list(reversed(prep["tiers"]))
    freshness = list(reversed(prep["freshness"]))
    reference = prep.get("reference_date") or ""
    title = f"Source Quality and Freshness ({prep['total']} unique sources)"
    fig = None
    if _HAS_PLOTLY:
        fig = make_subplots(
            rows=1,
            cols=2,
            subplot_titles=("Evidence tier", "Freshness"),
            horizontal_spacing=0.18,
        )
        fig.add_trace(
            go.Bar(
                x=[row["count"] for row in tiers],
                y=[row["label"] for row in tiers],
                orientation="h",
                marker_color=_PALETTE[4],
                hovertemplate="%{y}: %{x} sources<extra></extra>",
                showlegend=False,
            ),
            row=1,
            col=1,
        )
        fig.add_trace(
            go.Bar(
                x=[row["count"] for row in freshness],
                y=[row["label"] for row in freshness],
                orientation="h",
                marker_color=_PALETTE[1],
                hovertemplate="%{y}: %{x} sources<extra></extra>",
                showlegend=False,
            ),
            row=1,
            col=2,
        )
        if reference and prep.get("reference_source") == "run_metadata":
            freshness_note = (
                f"All dated rows use the research-run anchor ({reference}) from meta.finished_at."
            )
        elif reference and prep.get("reference_source") == "explicit_staleness_anchor":
            freshness_note = (
                f"All dated rows use one run-level anchor ({reference}), inferred from "
                "explicit staleness metadata."
            )
        elif reference:
            freshness_note = f"Dated buckets are relative to {reference}; undated rows are explicit."
        else:
            freshness_note = "No parseable source dates; freshness is reported as undated."
        fig.update_xaxes(title_text="source count", row=1, col=1)
        fig.update_xaxes(title_text="source count", row=1, col=2)
        _apply_wave9_layout(
            fig, f"{title}<br><sup>{freshness_note}</sup>",
            margin={"l": 100, "r": 40, "t": 100, "b": 45},
        )

    def mpl_draw(path: str) -> None:
        f, axes = plt.subplots(1, 2, figsize=(12, 7.5), dpi=160)
        axes[0].barh([row["label"] for row in tiers], [row["count"] for row in tiers],
                     color=_PALETTE[4])
        axes[0].set_title("Evidence tier")
        axes[0].set_xlabel("source count")
        axes[1].barh(
            [row["label"] for row in freshness],
            [row["count"] for row in freshness],
            color=_PALETTE[1],
        )
        axes[1].set_title("Freshness" + (f" vs {reference}" if reference else ""))
        axes[1].set_xlabel("source count")
        f.suptitle(title)
        _mpl_finalize(f, path)

    return _write_outputs(fig, mpl_draw, charts_dir, "source_quality")


def _owned_chart_id(row: dict) -> str | None:
    """返回条目所属的本渲染器生产者 ID。

    新清单以显式 ``id`` 为权威身份；旧清单没有 id，才从规范输出文件
    stem 恢复身份。``source_data`` 不能证明所有权，因为自定义生产者可以
    合法消费同一个输入。显式声明其它 id 的条目始终视为外部所有。
    """
    explicit = row.get("id")
    if isinstance(explicit, str) and explicit.strip():
        normalized = explicit.strip().lower()
        return normalized if normalized in _OWNED_CHART_IDS else None

    # Legacy renderer rows predate explicit IDs, but their canonical output
    # stem is stable. Infer ownership from that stem only: ``source_data`` is
    # shared by custom producers and is therefore insufficient evidence.
    for field in ("path", "html_path", "png_path"):
        value = row.get(field)
        if not isinstance(value, str) or not value.strip():
            continue
        stem = Path(value.strip().replace("\\", "/")).stem.lower()
        if stem in _OWNED_CHART_IDS:
            return stem
    return None


def _merge_manifest(manifest_path: Path, new_entries: list) -> list:
    """替换本渲染器的条目，保留其它生产者的条目。

    一次调用总是检查 actor/timeline/quant/revision/market/source 六个当前输入，因此旧的六类
    条目必须先作为一个集合删除，再按固定顺序加入本次成功产物。
    这同时解决 HTML-only → PNG+HTML 重跑时 ``path`` 改变导致的双条目，
    以及当前输入已缺失时清单仍指向旧图的问题。
    """
    existing = _read_json(manifest_path)
    rows = [r for r in existing if isinstance(r, dict)] if isinstance(existing, list) else []

    # 不属于本渲染器的条目（包括无法识别的旧/损坏 dict）按原顺序保留。
    merged = [row for row in rows if _owned_chart_id(row) is None]

    # 每个稳定生产者最多一条；即使调用方误传重复项，也由后者确定性覆盖。
    current: dict[str, dict] = {}
    for entry in new_entries:
        if not isinstance(entry, dict):
            continue
        owned_id = _owned_chart_id(entry)
        if owned_id:
            current[owned_id] = entry

    merged.extend(current[owned_id] for owned_id in _OWNED_CHART_IDS if owned_id in current)
    return merged


@contextmanager
def _manifest_update_lock(manifest_path: Path):
    """Serialize the manifest read-merge-write transaction across renderers."""
    lock_path = manifest_path.with_name(manifest_path.name + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
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
        _atomic_write(
            manifest_path,
            json.dumps(merged, ensure_ascii=False, indent=2) + "\n",
        )
        return merged


def main() -> int:
    ap = argparse.ArgumentParser(description="forecast-visuals bundled renderer (plotly-local)")
    ap.add_argument(
        "--dir",
        default=".",
        help=(
            "run working dir holding actors.json/timeline.json/quantitative.json/"
            "prediction_markets.json/sources.json"
        ),
    )
    ap.add_argument(
        "--context",
        action="store_true",
        default=None,
        help=(
            "additionally render the optional actor relationship map. Off by default "
            "because context/proxy structure must not displace forecast-domain data; "
            "RESEARCH_CHARTS_INCLUDE_CONTEXT=1 also enables it."
        ),
    )
    ap.add_argument(
        "--diagnostics",
        action="store_true",
        default=None,
        help=(
            "additionally render diagnostic-only charts (e.g. source_quality). These "
            "are methodology/audit figures and never belong in the report body. Off by "
            "default; RESEARCH_CHARTS_INCLUDE_DIAGNOSTICS=1 also enables them."
        ),
    )
    args = ap.parse_args()
    # 诊断图开关：显式 --diagnostics 或环境变量为真才产出。默认关——用户明确不要
    # source_quality「来源显著性」图进正文；关掉后它连 charts.json 都不登记。
    include_diagnostics = bool(args.diagnostics) or _env_truthy(
        os.environ.get("RESEARCH_CHARTS_INCLUDE_DIAGNOSTICS")
    )
    include_context = bool(args.context) or _env_truthy(
        os.environ.get("RESEARCH_CHARTS_INCLUDE_CONTEXT")
    )
    if not _HAS_PLOTLY and not _HAS_MPL:
        _log(
            "neither plotly nor matplotlib importable — install one "
            "(pip install plotly kaleido) or use the skill's deterministic table fallback"
        )
        return 3

    base = Path(args.dir).resolve()
    charts_dir = base / "charts"
    charts_dir.mkdir(parents=True, exist_ok=True)

    # 工件加载：一等公民文件优先，charts_data.json 兜底（write-step 由 agent 自写数据的流程）。
    fallback = _read_json(base / "charts_data.json") or {}
    actors_obj = _read_json(base / "actors.json")
    if not isinstance(actors_obj, dict):
        actors_obj = {"actors": fallback.get("actors"), "relationships": fallback.get("relationships")} \
            if isinstance(fallback, dict) and fallback.get("actors") else None
    timeline_rows = _read_json(base / "timeline.json")
    if not isinstance(timeline_rows, list):
        timeline_rows = fallback.get("timeline") if isinstance(fallback, dict) else None
    quant_rows = _read_json(base / "quantitative.json")
    if not isinstance(quant_rows, list):
        quant_rows = fallback.get("quantitative") if isinstance(fallback, dict) else None
    markets_payload = _read_json(base / "prediction_markets.json")
    if not isinstance(markets_payload, (dict, list)):
        markets_payload = fallback.get("prediction_markets") if isinstance(fallback, dict) else None
    sources_payload = _read_json(base / "sources.json")
    if not isinstance(sources_payload, (dict, list)):
        sources_payload = fallback.get("sources") if isinstance(fallback, dict) else None
    run_meta = _read_json(base / "meta.json")
    run_anchor = run_meta.get("finished_at") if isinstance(run_meta, dict) else None

    jobs = [
        ("timeline", prep_timeline(timeline_rows), render_timeline,
         "timeline.json", "Event Timeline",
         "Dated key events driving the forecast, most recent window.", "forecast_domain"),
        ("quant_metrics", prep_quant(quant_rows), render_quant,
         "quantitative.json", "Comparable Forecast Benchmarks",
         "Strict same-denominator panels; hover retains source, as-of, and forecast status.",
         "forecast_domain"),
        ("metric_trajectories", prep_trajectories(quant_rows), render_trajectories,
         "quantitative.json", "Observed and Published Forecast Trajectories",
         "Three or more sourced points on one definition; x-axis is period end, not publication date.",
         "forecast_domain"),
        ("forecast_revisions", prep_revisions(quant_rows), render_revisions,
         "quantitative.json", "Forecast Revisions Across Published Vintages",
         "The same sourced forecast metric across three or more published vintages.",
         "forecast_domain"),
        ("market_probabilities", prep_markets(markets_payload), render_markets,
         "prediction_markets.json", "Prediction-Market Implied Probabilities",
         "Most-liquid matched markets; implied probabilities are calibration anchors, not truth.",
         "forecast_domain"),
    ]
    if include_context:
        jobs.insert(0, (
            "actor_network", prep_network(actors_obj), render_network,
            "actors.json", "Actor Relationship Network",
            "Optional industrial-chain context. Node size uses declared tiers/scores when "
            "present; it is not market share or forecast impact.", "context",
        ))
    # source_quality 是诊断图（data_class='diagnostic'），默认不产出、不登记进 charts.json，
    # 更不会被 embed 进研究报告正文；仅在显式开诊断时补渲染，供方法学/审计场景。
    if include_diagnostics:
        jobs.append((
            "source_quality", prep_sources(sources_payload, run_anchor), render_sources,
            "sources.json", "Source Quality and Freshness",
            "Deduplicated source counts by evidence tier and deterministic freshness bucket.",
            "diagnostic",
        ))
    entries = []
    for stem, prep, renderer, source, title, caption, data_class in jobs:
        if not prep:
            _log(f"{stem}: input artifact missing/empty — skipped (never fabricated)")
            continue
        try:
            png_rel, html_rel = renderer(prep, charts_dir)
        except Exception as e:  # noqa: BLE001 — 单图失败绝不拖垮其余
            _log(f"{stem}: render failed ({type(e).__name__}: {e})")
            continue
        path = png_rel or html_rel
        if not path:
            continue
        entry = {
            "id": stem,
            "title": title,
            "caption": caption,
            "source_data": source,
            "data_class": data_class,
            "path": path,
        }
        if html_rel and png_rel:
            entry["html_path"] = html_rel
        entries.append(entry)
        _log(f"{stem}: wrote {path}" + (f" (+ {html_rel})" if html_rel and png_rel else ""))

    manifest_path = base / "charts.json"
    # 若之前有 manifest，即使本次一张也没生成，也必须落盘清理结果；
    # 否则已删除的输入仍会在 UI 中显示上一轮的旧图。全新空目录不创建空清单。
    if entries or manifest_path.exists():
        merged = _update_manifest(manifest_path, entries)
    else:
        merged = []
    if not entries:
        _log(
            "no renderable artifacts found (actors.json/timeline.json/quantitative.json/"
            "prediction_markets.json/sources.json all missing or empty)"
        )
        return 2
    _log(f"charts.json updated ({len(entries)} new/refreshed, {len(merged)} total)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
