"""确定性报告可视化器（VIZ-1 → WAVE9 plotly-first 重建）—— 无 LLM、纯数据驱动，把已落盘的
结构化工件（forecast / ensemble_forecast / timeline / actors / quantitative / sources /
contested / graph_priors / world_state_trajectory / comparison / market_price_history /
校准账本统计）渲染成三族可视化：

  (A) Mermaid 纯函数助手（保留为库函数，build_all 不再产出 mermaid——旧 mermaid 时间线/
      角色网络在前端/PDF 均无法渲染且字符规整会毁文本，已由 plotly 等价图取代）。
  (B) matplotlib PNG（Agg 后端，可选依赖）——作为 plotly/kaleido 缺失或 PNG 导出失败时的
      降级回退族，另含 plotly 无等价图的对比分组柱与校准曲线。
  (C) plotly 交互式 HTML + kaleido 静态 PNG 对（主族，预测数据优先）——情景概率误差棒
      （吃 ensemble stdev/min-max）、二元预测点阵、模型 vs 市场哑铃、研究指标轨迹（DRF2 按
      metric_family 跨 year 分组，region/technology/analyst 拆线）、技术份额柱、区域对比柱、
      时间线泳道、跨版本预测修订、世界态堆叠面积、市场价格历史折线、同分母定量基准。
      角色关系网络（networkx spring 布局，关系结构而非预测数据）、影响力×显著度、关键词
      “tornado”、来源权重争议哑铃与来源构成 sunburst 仍保留为诊断 helper，但不占用默认读者
      报告槽位（REPORT_META_CHARTS 可恢复 actor_network 与 source_mix_sunburst）。
      每图为自包含
      charts/<name>.html（plotly.js 内联，完全离线可开）+ charts/<name>.png（kaleido，
      scale=2、宽 1200，manifest 项挂 png_path）。

设计约束（与 report_agent 的确定性工具族一致）：
  · 纯函数式的 render_mermaid_* 助手：入参是普通 dict/list，返回 markdown 字符串；
    任何畸形输入 → ''（绝不抛异常）。
  · 可选依赖全部模块级探测（MATPLOTLIB_AVAILABLE / PLOTLY_AVAILABLE / NETWORKX_AVAILABLE /
    KALEIDO_AVAILABLE），缺失即整族/单图降级，绝不阻断报告生成。
  · build_all 返回 manifest 项列表（[{id,path,type,title,caption,source,placement_hint,
    png_path?}]），并把 {"schema_version":2,"items":[...],"skipped":[{builder,reason}]}
    落盘 reports/{id}/viz_manifest.json——跳过不再沉默：每个未产出的构建器都有 skipped 记录，
    并打一条 INFO 汇总日志（produced vs skipped）。
  · 所有输出确定性：相同工件 → 相同图表数据（networkx 布局固定 seed）。中文+英文双语注释，
    图表文案统一英文、字体栈带 CJK 回退（EN/ZH 数据均可渲染）。

env 旋钮（Config，全部 degrade-safe 默认）：
  REPORT_VISUALIZER      主开关（默认开）
  REPORT_VIZ_MERMAID     Mermaid 族开关（保留兼容；build_all 已不产 mermaid，仅影响库函数调用方）
  REPORT_VIZ_CHARTS      matplotlib PNG 回退族开关（默认开；matplotlib 缺失时自动无效）
  REPORT_VIZ_DPI         matplotlib PNG dpi（默认 160）
  REPORT_VIZ_MAX_NODES   通用节点/锚点上限（默认 40）
  REPORT_VIZ_PRICE_HISTORY  市场价格历史折线族开关（默认开）
  REPORT_VIZ_INTERACTIVE plotly 主族开关（默认开；plotly 缺失时自动无效）
  REPORT_VIZ_PNG_EXPORT  kaleido 静态 PNG 导出开关（默认开；kaleido 缺失/失败自动回退）
  REPORT_VIZ_TIMELINE_MAX_EVENTS  时间线泳道事件上限（默认 40）
  REPORT_VIZ_NETWORK_MAX_NODES    角色网络节点上限（默认 60）
  REPORT_META_CHARTS     管线元数据/方法论自证图开关（默认关：角色关系网络 actor_network、
                         来源构成 sunburst 等关系结构/方法论图不占默认报告槽位，仅显式开启时渲染）
"""

from __future__ import annotations

import datetime as dt
import hashlib
import html as html_lib
import json
import logging
import math
import os
import re
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlsplit

logger = logging.getLogger(__name__)

_EMBEDDED_FAVICON = (
    "data:image/svg+xml,%3Csvg xmlns=%22http://www.w3.org/2000/svg%22 "
    "viewBox=%220 0 64 64%22%3E%3Crect width=%2264%22 height=%2264%22 "
    "rx=%2214%22 fill=%22%2308172b%22/%3E%3Cpath d=%22M18 33h28M32 19v28%22 "
    "stroke=%22%2354d4ff%22 stroke-width=%226%22/%3E%3C/svg%3E"
)


def _plotly_document_title(fig: Any, filename: str) -> str:
    """Return a readable title for a standalone interactive chart document."""
    try:
        raw = str(fig.layout.title.text or "")
    except Exception:  # noqa: BLE001 - tolerate partially mocked optional dependency
        raw = ""
    plain = re.sub(r"<[^>]+>", " ", raw)
    plain = re.sub(r"\s+", " ", plain).strip()
    return plain or os.path.splitext(filename)[0].replace("_", " ").title()


def _finalize_plotly_html(raw_html: str, title: str) -> str:
    """Inject deterministic title/favicon metadata into a self-contained Plotly file."""
    if "</head>" not in raw_html.lower():
        return raw_html
    metadata = (
        f"<title>{html_lib.escape(title)}</title>"
        f'<link rel="icon" href="{_EMBEDDED_FAVICON}">'
    )
    return re.sub(r"</head>", metadata + "</head>", raw_html, count=1, flags=re.IGNORECASE)

# ─────────────────────────────────────────────────────────────────────────────
# matplotlib 可选依赖：导入失败 → 仅 Mermaid 模式（模块级单一真源标志）。
# 必须在任何 pyplot 导入之前强制 Agg 后端（无显示环境/服务器渲染 PNG）。
# ─────────────────────────────────────────────────────────────────────────────
try:  # pragma: no cover - 导入分支由 monkeypatch 测试覆盖
    import matplotlib
    matplotlib.use("Agg")  # 无头后端；必须在 pyplot 之前设置
    import matplotlib.pyplot as plt  # noqa: E402
    MATPLOTLIB_AVAILABLE = True
except Exception:  # noqa: BLE001 - 任何导入/后端失败都降级为仅 Mermaid
    plt = None  # type: ignore
    MATPLOTLIB_AVAILABLE = False


# ─────────────────────────────────────────────────────────────────────────────
# plotly 可选依赖（ITEM-16 交互式 HTML 图表族）：导入失败 → PLOTLY_AVAILABLE=False，
# HTML 族整体静默跳过（镜像 MATPLOTLIB_AVAILABLE 模式）。与 matplotlib 完全正交，二者可各自
# 缺失/可用而互不影响。plotly 生成的 HTML 在浏览器渲染，CJK 字形由浏览器字体处理（无需字形过滤）。
# ─────────────────────────────────────────────────────────────────────────────
try:  # pragma: no cover - 导入分支由 monkeypatch 测试覆盖
    import plotly.graph_objects as go  # noqa: E402
    PLOTLY_AVAILABLE = True
except Exception:  # noqa: BLE001 - 任何导入失败都降级（不生成 HTML 图族）
    go = None  # type: ignore
    PLOTLY_AVAILABLE = False


# ─────────────────────────────────────────────────────────────────────────────
# networkx 可选依赖（WAVE9 角色网络 spring 布局）：缺失 → 确定性同心圆回退布局。
# ─────────────────────────────────────────────────────────────────────────────
try:  # pragma: no cover
    import networkx as nx  # noqa: E402
    NETWORKX_AVAILABLE = True
except Exception:  # noqa: BLE001
    nx = None  # type: ignore
    NETWORKX_AVAILABLE = False


# ─────────────────────────────────────────────────────────────────────────────
# kaleido 可选依赖（WAVE9 plotly → 静态 PNG 导出）：只探测可导入性，不在 import 期启动
# Chromium。运行期渲染失败会把 _KALEIDO_RUNTIME_OK 置 False（进程内一次性熔断，避免每图重试
# 各等一次超时），并回退 matplotlib（有等价图时）。
# ─────────────────────────────────────────────────────────────────────────────
try:  # pragma: no cover
    import importlib.util as _ilu
    KALEIDO_AVAILABLE = _ilu.find_spec("kaleido") is not None
except Exception:  # noqa: BLE001
    KALEIDO_AVAILABLE = False

_KALEIDO_RUNTIME_OK = True  # 运行期熔断标志（首个渲染异常后本进程不再尝试 PNG 导出）


def _close_matplotlib_figure(fig: Any) -> None:
    """Close one builder-owned figure without touching figures from concurrent callers."""
    if fig is None or plt is None:
        return
    try:
        plt.close(fig)
    except Exception:  # noqa: BLE001 - cleanup must never mask the render result
        pass


# ─────────────────────────────────────────────────────────────────────────────
# 内部小工具（纯函数）
# ─────────────────────────────────────────────────────────────────────────────
def _cfg(name: str, default: Any) -> Any:
    """从 Config 读旋钮；Config 不可用/缺键 → default（模块可独立于 Flask 运行）。"""
    try:
        from ..config import Config
        return getattr(Config, name, default)
    except Exception:  # noqa: BLE001
        return default


def _meta_charts_on() -> bool:
    """REPORT_META_CHARTS 旋钮（默认关）：管线元数据/方法论自证图（来源构成 sunburst 等）
    是否占用默认报告槽位。读者要的是预测数据图（成本曲线/部署轨迹/区域对比），元数据图
    仅在显式开启（Config 属性，或 Config 缺键时读同名环境变量）后才恢复渲染。"""
    val = _cfg("REPORT_META_CHARTS", None)
    if val is None:
        val = os.environ.get("REPORT_META_CHARTS")
    if isinstance(val, str):
        return val.strip().lower() in {"1", "true", "yes", "on"}
    return bool(val)


# ─────────────────────────────────────────────────────────────────────────────
# WAVE9 统一图表风格（clean light surface + 浅灰网格 + CVD-safe 分类色板 + CJK 字体回退栈）。
# 色板与角色遵循 dataviz 参考色板：分类槽位固定顺序（不可循环生成）、正/负/中性边色用
# 发散对（蓝↔红）+ 中性灰、状态色（stale/unreachable）与分类色分离。
# ─────────────────────────────────────────────────────────────────────────────
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

# 影响力/显著度分级 → 数值（气泡图 y 轴与网络图节点排序共用）。
_LEVEL_NUM = {"very high": 4.0, "high": 3.0, "medium": 2.0, "med": 2.0,
              "moderate": 2.0, "low": 1.0, "very low": 0.5}

# VIZ-GAP2 最小数据密度门：整页图表必须承载足够信息，否则降级为紧凑表格
# （取证：1200px 的 model_vs_market.png 只画 1 条命题；quantitative_claims.png 两个
# 堆叠面板共 4 个数）。model-vs-market 需 ≥3 条带市场锚点的命题（单锚点已由二元点阵
# 图的成对菱形承载）；量化面板需 ≥4 个点或 ≥2 个互异指标。
_MODEL_VS_MARKET_MIN_ANCHORED = 3
_QUANT_PANEL_MIN_POINTS = 4
_QUANT_PANEL_MIN_CATEGORIES = 2


def _quant_panel_is_dense(panel: Dict[str, Any]) -> bool:
    rows = panel.get("rows") or []
    if len(rows) >= _QUANT_PANEL_MIN_POINTS:
        return True
    metrics = {str(row.get("metric") or "") for row in rows}
    return len(metrics) >= _QUANT_PANEL_MIN_CATEGORIES


def _quant_panel_subtitles(panels: List[Dict[str, Any]]) -> List[str]:
    """VIZ-GAP3(d)：面板互异的子图标题——绝不出现两个一模一样的 'USD/kW (n=2)'。
    先用 单位+as-of，重名再追加口径与首行指标名，仍重名则追加序号（确定性）。"""
    base = [
        f"{panel.get('unit', '')} — as of {panel.get('as_of', '?')}"
        f" (n={len(panel.get('rows') or [])})"
        for panel in panels
    ]
    counts: Dict[str, int] = {}
    for title in base:
        counts[title] = counts.get(title, 0) + 1
    titles: List[str] = []
    for panel, title in zip(panels, base, strict=True):
        if counts[title] > 1:
            basis = _html_text(panel.get("time_basis"), max_len=20)
            lead_rows = panel.get("rows") or []
            lead = _html_text(lead_rows[0].get("metric") if lead_rows else "",
                              max_len=26)
            detail = " · ".join(part for part in (basis, lead) if part)
            if detail:
                title = f"{title} · {detail}"
        titles.append(title)
    seen: Dict[str, int] = {}
    out: List[str] = []
    for title in titles:
        n = seen.get(title, 0)
        seen[title] = n + 1
        out.append(title if n == 0 else f"{title} ({n + 1})")
    return out

# 证据层级 → 序数权重（S1 最强）。用于量化断言排序/着色与争议断言证据权重。
_TIER_RANK = {"S1": 0, "S2": 1, "S3": 2, "S4": 3}
_TIER_COLOR = {"S1": "#184f95", "S2": "#3987e5", "S3": "#9ec5f4", "S4": "#cde2fb"}
_TIER_WEIGHT = {"S1": 3.0, "S2": 2.0, "S3": 1.0, "S4": 0.5}


def _apply_layout(fig, title: str, height: int = 520, **kwargs) -> None:
    """统一 plotly 布局：浅色画布 + 细网格 + 固定分类色板 + CJK 安全字体栈。就地修改 fig。"""
    fig.update_layout(
        title=dict(text=title, font=dict(size=16, color=_INK, family=_VIZ_FONT), x=0.02),
        font=dict(family=_VIZ_FONT, size=12, color=_INK_2),
        paper_bgcolor=_SURFACE, plot_bgcolor=_SURFACE,
        colorway=_PALETTE, height=height,
        margin=dict(l=10, r=24, t=58, b=46),
        hoverlabel=dict(font=dict(family=_VIZ_FONT, size=12)),
        **kwargs,
    )
    fig.update_xaxes(gridcolor=_GRID, zerolinecolor=_AXIS, linecolor=_AXIS,
                     tickfont=dict(size=11))
    fig.update_yaxes(gridcolor=_GRID, zerolinecolor=_AXIS, linecolor=_AXIS,
                     tickfont=dict(size=11))


def _wrap_hover(text: Any, width: int = 64, max_len: int = 480) -> str:
    """把长文本按词折行成 <br> 分隔的 hover 文案（HTML 转义 <>&）。空 → ''。"""
    s = re.sub(r"\s+", " ", str(text if text is not None else "")).strip()
    if not s:
        return ""
    if len(s) > max_len:
        s = s[: max_len - 1].rstrip() + "…"
    s = s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    # 成对 '$' 防 MathJax（见 _html_text）；须在 & 转义之后（实体自身含 &）。
    if s.count("$") >= 2:
        s = s.replace("$", "&#36;")
    words = s.split(" ")
    lines: List[str] = []
    cur = ""
    for w in words:
        if cur and len(cur) + 1 + len(w) > width:
            lines.append(cur)
            cur = w
        else:
            cur = f"{cur} {w}".strip()
    if cur:
        lines.append(cur)
    return "<br>".join(lines)


def _tokens(text: Any) -> set:
    """小写字母数字词元集合（时间线/驱动因子近重合并用）。"""
    return set(re.findall(r"[a-z0-9]{2,}", str(text or "").lower()))


def _jaccard(a: set, b: set) -> float:
    """两个词元集合的 Jaccard 相似度；任一为空 → 0。"""
    if not a or not b:
        return 0.0
    inter = len(a & b)
    return inter / float(len(a | b))


def _san_label(text: Any, max_len: int = 80) -> str:
    """规整 Mermaid 引号标签内的文本：去掉会破坏语法的字符（双引号/竖线/换行/尖括号），
    折叠空白并截断。空/None → ''。"""
    s = str(text if text is not None else "").strip()
    if not s:
        return ""
    s = s.replace('"', "'").replace("|", "/").replace("\n", " ").replace("\r", " ")
    # 尖括号/方括号会破坏 Mermaid 语法，但旧实现把 '>' 换成 ')' 会毁掉 '>$1T' 这类文本——
    # 改用全角等价字形（渲染语义不变、Mermaid 安全）。
    s = s.replace("<", "＜").replace(">", "＞").replace("[", "(").replace("]", ")")
    s = s.replace("{", "(").replace("}", ")").replace("#", "＃").replace("`", "'")
    s = re.sub(r"\s+", " ", s).strip()
    if len(s) > max_len:
        s = s[: max_len - 1].rstrip() + "…"
    return s


def _mpl_text(text: Any, fallback: str = "", max_len: int = 60) -> str:
    """Normalize a static-chart label without changing its language or identity.

    CJK text used to be stripped and replaced by labels such as ``Actor 4`` or ``Event``.  That is
    semantically false.  Font support is now checked separately by :func:`_mpl_font_for_text`;
    renderers either use a real installed font that covers every CJK codepoint or skip the chart.
    ``fallback`` therefore applies only to genuinely empty input.
    """
    s = str(text if text is not None else "").strip()
    s = re.sub(r"\s+", " ", s).strip()
    if not s:
        return fallback
    if len(s) > max_len:
        s = s[: max_len - 1].rstrip() + "…"
    # WAVE9：成对 '$' 会触发 matplotlib mathtext（'$100B vs $65B' 变斜体数学式），反斜杠转义。
    if s.count("$") >= 2:
        s = s.replace("$", r"\$")
    return s


_CJK_FONT_FAMILIES = (
    "Noto Sans CJK SC", "Noto Sans CJK TC", "Noto Sans CJK JP",
    "Source Han Sans SC", "Source Han Sans CN", "Microsoft YaHei", "SimHei",
    "PingFang SC", "PingFang HK", "Hiragino Sans GB", "Hiragino Sans",
    "Arial Unicode MS", "WenQuanYi Zen Hei", "Malgun Gothic",
)
_MPL_CJK_FONT_CACHE: Optional[List[Tuple[Any, frozenset]]] = None


def _cjk_codepoints(text: Any) -> frozenset:
    """Return CJK/Japanese/Korean codepoints whose glyph coverage must be explicit."""
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


def _installed_cjk_fonts() -> List[Tuple[Any, frozenset]]:
    """Discover deterministic, installed Matplotlib fonts and cache their real charmaps."""
    global _MPL_CJK_FONT_CACHE
    if _MPL_CJK_FONT_CACHE is not None:
        return _MPL_CJK_FONT_CACHE
    found: List[Tuple[Any, frozenset]] = []
    if not MATPLOTLIB_AVAILABLE:
        _MPL_CJK_FONT_CACHE = found
        return found
    try:
        from matplotlib import font_manager, ft2font

        seen_paths = set()
        font_logger = logging.getLogger("matplotlib.font_manager")
        previous_level = font_logger.level
        for family in _CJK_FONT_FAMILIES:
            try:
                font_logger.setLevel(logging.ERROR)
                prop = font_manager.FontProperties(family=family)
                path = font_manager.findfont(prop, fallback_to_default=False)
                real_path = os.path.realpath(path)
                if not real_path or real_path in seen_paths or not os.path.isfile(real_path):
                    continue
                charmap = frozenset(ft2font.FT2Font(real_path).get_charmap())
                if charmap:
                    found.append((font_manager.FontProperties(fname=real_path), charmap))
                    seen_paths.add(real_path)
            except Exception:  # noqa: BLE001 - one unavailable family is expected
                continue
            finally:
                font_logger.setLevel(previous_level)
    except Exception as exc:  # noqa: BLE001
        logger.debug("CJK font discovery failed; static CJK charts will be skipped: %s", exc)
    _MPL_CJK_FONT_CACHE = found
    return found


def _mpl_font_for_text(text: Any):
    """Return a real font covering all CJK glyphs in *text*, or ``None`` if unavailable.

    ``None`` also represents ordinary non-CJK text, which is safely handled by Matplotlib's
    default font.  Callers distinguish the two cases with :func:`_cjk_codepoints`.
    """
    required = _cjk_codepoints(text)
    if not required:
        return None
    for prop, charmap in _installed_cjk_fonts():
        if required <= charmap:
            return prop
    return None


def _mpl_labels_supported(text: Any) -> bool:
    """True when text needs no CJK font or an installed font covers every CJK glyph."""
    return not _cjk_codepoints(text) or _mpl_font_for_text(text) is not None


def _font_at_size(prop: Any, size: float):
    """Copy a FontProperties instance before applying an artist-specific point size."""
    if prop is None:
        return None
    try:
        copied = prop.copy()
        copied.set_size(size)
        return copied
    except Exception:  # noqa: BLE001
        return prop


def _boxes_overlap(left: Tuple[float, float, float, float],
                   right: Tuple[float, float, float, float], pad: float = 0.0) -> bool:
    """Axis-aligned collision predicate shared by deterministic label planners."""
    return not (left[2] + pad <= right[0] or right[2] + pad <= left[0]
                or left[3] + pad <= right[1] or right[3] + pad <= left[1])


def _timeline_label_plan(events: List[Dict[str, Any]], used_index: Dict[str, int],
                         max_labels: int = 12) -> Dict[Tuple[Any, str], Dict[str, Any]]:
    """Choose salient timeline labels and non-overlapping deterministic annotation slots.

    Bounding boxes are conservative estimates in ``(date ordinal, lane units)``.  Labels near the
    right boundary extend left; all others extend right.  A label is omitted when none of six
    vertical slots is collision-free, which is preferable to publishing unreadable overprint.
    """
    if not events or not used_index or max_labels <= 0:
        return {}
    ranked = sorted(events, key=lambda event: (
        -float(event.get("score", 0.0)), event["dt"], event["text"],
    ))[:max_labels]
    ordinals = [float(event["dt"].toordinal()) for event in events]
    x_min, x_max = min(ordinals), max(ordinals)
    span = max(30.0, x_max - x_min)
    lane_count = max(1, len(used_index))
    figure_height = max(3.8, 1.05 * lane_count + 2.4)
    lane_points = max(42.0, figure_height * 72.0 * 0.68 / lane_count)
    slots = (16, -20, 34, -38, 52, -56)
    occupied: List[Tuple[float, float, float, float]] = []
    plan: Dict[Tuple[Any, str], Dict[str, Any]] = {}

    for event in ranked:
        label = _mpl_text(event.get("text"), max_len=48)
        if not label:
            continue
        x = float(event["dt"].toordinal())
        lane = float(used_index[event["cat"]])
        # Eight-point labels occupy roughly 0.55% of an 11-inch axis per Latin character;
        # the estimate is deliberately conservative for full-width CJK glyphs.
        width = max(span * 0.05, span * min(0.25, 0.0055 * len(label)))
        extend_left = (x - x_min) / span > 0.72
        x0, x1 = ((x - width, x) if extend_left else (x, x + width))
        for slot in slots:
            center_y = lane + slot / lane_points
            half_height = 5.5 / lane_points
            box = (x0, center_y - half_height, x1, center_y + half_height)
            if any(_boxes_overlap(box, prior, pad=0.01) for prior in occupied):
                continue
            plan[(event["dt"], event["text"])] = {
                "label": label,
                "offset": (-4 if extend_left else 4, slot),
                "ha": "right" if extend_left else "left",
                "va": "bottom" if slot > 0 else "top",
                "bbox": box,
            }
            occupied.append(box)
            break
    for index, key in enumerate(sorted(plan, key=lambda item: (item[0], item[1])), 1):
        plan[key]["index"] = index
    return plan


def _actor_label_plan(nodes: List[str], positions: Dict[str, Tuple[float, float]],
                      weights: Dict[str, float], max_labels: int = 22
                      ) -> Dict[str, Dict[str, Any]]:
    """Place high-value actor labels around nodes without deterministic box collisions."""
    valid_nodes = [node for node in nodes if node in positions]
    if not valid_nodes or max_labels <= 0:
        return {}
    xs = [positions[node][0] for node in valid_nodes]
    ys = [positions[node][1] for node in valid_nodes]
    x_span = max(max(xs) - min(xs), 1.0)
    y_span = max(max(ys) - min(ys), 1.0)
    scale = max(x_span, y_span)
    center_x = sum(xs) / len(xs)
    center_y = sum(ys) / len(ys)
    occupied: List[Tuple[float, float, float, float]] = []
    plan: Dict[str, Dict[str, Any]] = {}
    ranked = sorted(valid_nodes, key=lambda node: (-weights.get(node, 0.0), node))[:max_labels]

    for node in ranked:
        label = _mpl_text(node, max_len=24)
        if not label:
            continue
        x, y = positions[node]
        radial = math.atan2(y - center_y, x - center_x)
        if abs(x - center_x) + abs(y - center_y) < 1e-9:
            radial = (sum((index + 1) * ord(char) for index, char in enumerate(node)) % 360
                      ) * math.pi / 180.0
        angles = (radial, radial + math.pi / 3, radial - math.pi / 3,
                  radial + math.pi, radial + math.pi / 2, radial - math.pi / 2,
                  0.0, math.pi)
        half_width = max(x_span * 0.04, x_span * min(0.18, 0.0065 * len(label)))
        half_height = y_span * 0.025
        placed = False
        for radius_factor in (0.07, 0.12, 0.18, 0.25, 0.34):
            radius = scale * radius_factor
            for angle in angles:
                label_x = x + radius * math.cos(angle)
                label_y = y + radius * math.sin(angle)
                box = (label_x - half_width, label_y - half_height,
                       label_x + half_width, label_y + half_height)
                if any(_boxes_overlap(box, prior, pad=scale * 0.008)
                       for prior in occupied):
                    continue
                # Keep labels clear of every node marker, not merely of other labels.
                if any(box[0] - scale * 0.018 <= node_x <= box[2] + scale * 0.018
                       and box[1] - scale * 0.018 <= node_y <= box[3] + scale * 0.018
                       for node_x, node_y in positions.values()):
                    continue
                plan[node] = {"label": label, "xytext": (label_x, label_y), "bbox": box}
                occupied.append(box)
                placed = True
                break
            if placed:
                break
    return plan


def _html_text(text: Any, fallback: str = "", max_len: int = 60) -> str:
    """plotly HTML 标签的文本规整（ITEM-16）：保留 CJK/非拉丁字形
    （浏览器字体可渲染，无缺字方块问题），仅折叠空白并截断。空 → fallback。
    WAVE9：成对 '$' 会被 plotly/MathJax 当 LaTeX 数学式渲染（'$100B vs $65B' 变斜体乱排），
    改写为 HTML 实体 &#36;（显示不变、MathJax 不再匹配）。"""
    s = str(text if text is not None else "").strip()
    s = re.sub(r"\s+", " ", s).strip()
    if not s:
        return fallback
    if len(s) > max_len:
        s = s[: max_len - 1].rstrip() + "…"
    if s.count("$") >= 2:
        s = s.replace("$", "&#36;")
    return s


def _wrap_label(text: Any, fallback: str = "", width: int = 55,
                max_lines: int = 2) -> str:
    """VIZ-GAP3：PNG 可读的轴/键标签——按词折行成 ≤max_lines 行（<br> 分隔），只有超出
    width*max_lines 总预算才截断加省略号（hover 在 PNG 里不存在，截断即信息丢失）。
    无空格的 CJK 长串按宽度硬切；成对 '$' 的 MathJax 防护与 _html_text 一致。"""
    s = str(text if text is not None else "").strip()
    s = re.sub(r"\s+", " ", s).strip()
    if not s:
        return fallback
    budget = width * max_lines
    if len(s) > budget:
        s = s[: budget - 1].rstrip() + "…"
    if s.count("$") >= 2:
        s = s.replace("$", "&#36;")
    words: List[str] = []
    for word in s.split(" "):
        while len(word) > width:  # 无空格长词（CJK/URL）硬切，绝不整串溢出
            words.append(word[:width])
            word = word[width:]
        if word:
            words.append(word)
    lines: List[str] = []
    cur = ""
    for word in words:
        if cur and len(cur) + 1 + len(word) > width:
            lines.append(cur)
            cur = word
        else:
            cur = f"{cur} {word}".strip()
    if cur:
        lines.append(cur)
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        lines[-1] = lines[-1].rstrip("…").rstrip() + "…"
    return "<br>".join(lines)


def _md_cell(text: Any, max_len: int = 80) -> str:
    """markdown 表单元格文本：_html_text 规整 + 竖线转义（防拆列）。"""
    return _html_text(text, max_len=max_len).replace("|", "/")


def _node_id(counter: Dict[str, str], name: str) -> str:
    """把任意实体名映射到稳定的 Mermaid 节点 id（n0/n1/…，按首次出现顺序，确定性）。"""
    key = str(name)
    if key not in counter:
        counter[key] = f"n{len(counter)}"
    return counter[key]


def _to_float(v: Any) -> Optional[float]:
    """Best-effort numeric extraction without corrupting grouped thousands.

    Supports values such as ``37%``, ``D+3``, ``247,226`` and
    ``round 3 (12)`` (the first numeric token wins).  Commas are removed only
    after a valid thousands-grouped token has been isolated, so chart values
    cannot silently collapse from 1,808,511 to 1.
    """
    if v is None:
        return None
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        try:
            f = float(v)
            return f if f == f else None  # 过滤 NaN
        except (TypeError, ValueError):
            return None
    m = re.search(
        r"[-+]?(?:\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?|\.\d+)",
        str(v),
    )
    if not m:
        return None
    try:
        return float(m.group(0).replace(",", ""))
    except (TypeError, ValueError):
        return None


def _explicit_numeric_range(value: Any) -> Optional[Tuple[float, float]]:
    """Return a stated numeric interval, preserving it over scalar guesses."""
    text = str(value or "").replace(",", "")
    match = re.search(
        r"(-?\d+(?:\.\d+)?)\s*(?:[-–—~]|to)\s*(-?\d+(?:\.\d+)?)",
        text,
        re.IGNORECASE,
    )
    if not match:
        return None
    low, high = float(match.group(1)), float(match.group(2))
    return min(low, high), max(low, high)


_QUANT_UNIT_ALIASES = {
    "% new vehicle sales": "% new car sales",
    "% of new vehicle sales": "% new car sales",
    "% of new car sales": "% new car sales",
    "usd/kwh": "USD per kWh",
    "usd per kwh": "USD per kWh",
    "us$ per kwh": "USD per kWh",
    "$/kwh": "USD per kWh",
}
_AMBIGUOUS_QUANT_UNITS = {
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
    r"analyst\s+interpolation|our\s+(?:case|estimate|forecast))\b|"
    r"内部推演|本报告|分析师插值",
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
    ("price", r"\b(?:price|cost)\b"),
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


def _canonical_quant_unit(unit: Any) -> str:
    """Return a conservative display/comparison key for one quantitative unit."""
    raw = re.sub(r"\s+", " ", str(unit or "")).strip()
    if not raw:
        return ""
    return _QUANT_UNIT_ALIASES.get(raw.lower(), raw)


def _quant_unit_is_comparable(unit: Any) -> bool:
    """Whether a unit carries enough denominator semantics for auto-comparison.

    A shared glyph is not a shared metric: plain ``%`` can mean margin, market
    share, growth or a policy rate, while ``USD billion`` can mix revenue,
    capex and market size.  Auto-generated reader charts therefore fail closed
    on these ambiguous units and require an explicit denominator (``% new car
    sales``), rate (``USD per kWh``), or physical measure.
    """
    canonical = _canonical_quant_unit(unit)
    low = canonical.lower()
    if not low or low == "date" or low in _AMBIGUOUS_QUANT_UNITS:
        return False
    if "%" in canonical:
        return len(low.replace("%", "").strip()) >= 3
    if " per " in low or "/" in low or " of " in low:
        return True
    return bool(re.fullmatch(
        r"(?:[kmgt]?wh|wh/kg|kg|tonnes?|barrels?|credits?|bps|basis points)",
        low,
    ))


def _parse_quant_date(value: Any) -> Optional[dt.date]:
    match = re.search(r"\d{4}-\d{2}-\d{2}", str(value or ""))
    if not match:
        return None
    try:
        return dt.date.fromisoformat(match.group(0))
    except ValueError:
        return None


def _metric_row_period_end(row: Dict[str, Any]) -> Optional[dt.date]:
    """Return the target/observation period end before any publication date."""
    candidates: List[Any] = [row.get("period_end"), row.get("target_date")]
    period = row.get("period")
    if isinstance(period, dict):
        candidates.extend([
            period.get("period_end"),
            period.get("end"),
        ])
    for raw in candidates:
        text = str(raw or "").strip()
        if not text:
            continue
        full = re.search(r"(?<!\d)(19\d{2}|20\d{2})-(\d{2})-(\d{2})(?!\d)", text)
        if full:
            try:
                return dt.date(
                    int(full.group(1)), int(full.group(2)), int(full.group(3)))
            except ValueError:
                continue
        year = re.search(r"(?<!\d)(19\d{2}|20\d{2})(?!\d)", text)
        if year:
            return dt.date(int(year.group(1)), 12, 31)
    return None


def _metric_row_is_publishable(
        row: Dict[str, Any], kind: Optional[str] = None) -> bool:
    """Apply the same provenance floor as the research forecast renderer.

    Observations need source, definition and source as-of date. Forward points
    additionally need an external HTTP(S) source and cannot be explicitly
    described as an internal/dossier interpolation.
    """
    source = re.sub(
        r"\s+", " ",
        str(row.get("source") or row.get("analyst") or ""),
    ).strip()
    definition = re.sub(
        r"\s+", " ", str(row.get("definition") or ""),
    ).strip()
    as_of = _parse_quant_date(row.get("as_of_date"))
    if not source or not definition or as_of is None:
        return False
    resolved_kind = kind or _metric_row_kind(row)
    if resolved_kind != "forecast":
        return True
    source_url = str(row.get("source_url") or "").strip()
    parsed = urlsplit(source_url)
    if parsed.scheme.casefold() not in {"http", "https"} or not parsed.netloc:
        return False
    return not bool(_INTERNAL_FORECAST_SOURCE_RE.search(
        f"{source} {definition}"))


def _quant_is_projection(row: Dict[str, Any]) -> bool:
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
    text = " ".join(str(row.get(k) or "") for k in ("metric", "definition")).lower()
    return bool(_FORECAST_SIGNAL_RE.search(text))


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


def _quant_denominator_key(unit: str, definition: str) -> Optional[str]:
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


def _quant_time_basis(row: Dict[str, Any], metric: str, definition: str) -> str:
    explicit: List[str] = []
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


def _split_quant_families(rows: List[Dict[str, Any]]) -> List[List[Dict[str, Any]]]:
    families: List[Dict[str, Any]] = []
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


def _revision_target_year(name: str, definition: str, vintage: int) -> Optional[int]:
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


def _prepare_quantitative_panels(
    quantitative: Any,
    *,
    max_panels: int = 3,
    max_rows: int = 10,
) -> List[Dict[str, Any]]:
    """Select strict, decision-relevant same-denominator comparison panels.

    Selection is deterministic and intentionally conservative.  It preserves
    source/as-of/projection metadata for the renderer and excludes generic
    counts or currencies whose equal units conceal incompatible periods and
    definitions.
    """
    if not isinstance(quantitative, list):
        return []
    groups: Dict[Tuple[str, str, str, str, str], List[Dict[str, Any]]] = {}
    for idx, q in enumerate(quantitative):
        if not isinstance(q, dict):
            continue
        metric = str(q.get("metric") or "").strip()
        unit = _canonical_quant_unit(q.get("unit"))
        value = _metric_row_value(q)
        if not metric or value is None or not _quant_unit_is_comparable(unit):
            continue
        source = str(q.get("source") or "").strip()
        definition = str(q.get("definition") or "").strip()
        as_of = _parse_quant_date(q.get("as_of_date"))
        if not source or not definition or as_of is None:
            continue
        projection = _quant_is_projection(q)
        if not _metric_row_is_publishable(
                q, "forecast" if projection else "actual"):
            continue
        staleness = _to_float(q.get("staleness_days"))
        # A future-dated actual is no observation: negative age, or the typed
        # recency pass's is_future_dated (which withholds the age).
        future_dated = (staleness is not None and staleness < 0) or q.get("is_future_dated") is True
        if future_dated and not projection:
            continue
        denominator = _quant_denominator_key(unit, definition)
        if not denominator:
            continue
        time_basis = _quant_time_basis(q, metric, definition)
        measure_family = _quant_measure_family(metric, definition)
        subjects = _quant_subject_tokens(metric, definition)
        if not measure_family or not subjects:
            continue
        tier = str(q.get("tier") or "S3").strip().upper() or "S3"
        key = (unit.casefold(), as_of.isoformat(), time_basis, denominator, measure_family)
        groups.setdefault(key, []).append({
            "metric": metric,
            "value": value,
            "display_value": str(q.get("value") or value),
            "unit": unit,
            "as_of": as_of.isoformat(),
            "source": source,
            "definition": definition,
            "tier": tier,
            "stale": bool(q.get("is_stale")),
            "projection": projection,
            "_subjects": subjects,
            "idx": idx,
        })

    eligible: List[Tuple[Tuple[str, str, str, str, str], List[Dict[str, Any]]]] = []
    for key, rows in groups.items():
        eligible.extend((key, family) for family in _split_quant_families(rows))
    eligible.sort(key=lambda item: (-len(item[1]), item[0]))
    panels: List[Dict[str, Any]] = []
    for key, rows in eligible[:max(0, max_panels)]:
        rows.sort(key=lambda row: (
            _TIER_RANK.get(row["tier"], 9),
            row["stale"],
            row["projection"],
            row["idx"],
        ))
        clean_rows = [
            {field: value for field, value in row.items() if not field.startswith("_")}
            for row in rows[:max(1, max_rows)]
        ]
        panels.append({
            "unit": clean_rows[0]["unit"],
            "as_of": key[1],
            "time_basis": key[2],
            "rows": clean_rows,
        })
    return panels


_METRIC_TIME_KEYS: Tuple[str, ...] = (
    "period_end", "target_date", "period", "period_start",
    "as_of_date", "as_of", "date",
)


def _parse_metric_point_time(row: Dict[str, Any]) -> Optional[dt.date]:
    """从 quantitative 行提取轨迹时点（比 _parse_quant_date 宽松）：依序扫
    date/as_of/period 族字段，接受 YYYY-MM-DD / YYYY-MM / YYYY / 'by YYYY' /
    'YYYY年'；年/月粒度统一归到该期首日，保证同轴排序确定性。不可解析 → None。"""
    period_end = _metric_row_period_end(row)
    if period_end is not None:
        return period_end
    for key in _METRIC_TIME_KEYS:
        raw = row.get(key)
        if isinstance(raw, dict):  # period:{...} → 取显式期末/期初/标签子值
            raw = (raw.get("period_end") or raw.get("end")
                   or raw.get("period_start") or raw.get("start") or raw.get("label"))
        s = str(raw or "").strip()
        if not s:
            continue
        m = re.search(r"\b(\d{4})-(\d{2})-(\d{2})\b", s)
        if m:
            try:
                return dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
            except ValueError:
                pass  # 畸形全日期（如 13 月）→ 继续尝试更粗粒度
        m = re.search(r"\b(\d{4})-(\d{2})\b", s)
        if m and 1 <= int(m.group(2)) <= 12:
            return dt.date(int(m.group(1)), int(m.group(2)), 1)
        m = re.search(r"(?<!\d)(19\d{2}|20\d{2})(?!\d)", s)
        if m:  # 覆盖裸年份与 'by 2030' / '2030年' 措辞
            return dt.date(int(m.group(1)), 1, 1)
    return None


def _metric_series_name(metric: str) -> str:
    """把 metric 名折叠成序列身份：剥离内嵌年份/季度与 forecast/target 措辞——
    研究抽取常把时点写进指标名（'Tesla Optimus 2026 target'、'GMI 2031 humanoid
    market revenue'），不折叠则同一指标的多时点行永远聚不成轨迹。剥空 → 退回
    原名（不猜）。"""
    s = re.sub(r"\b(?:by\s+)?(?:19|20)\d{2}\b", " ", str(metric))
    s = re.sub(r"\b(?:Q[1-4]|H[12]|FY)\b", " ", s)
    s = re.sub(r"\b(?:actual|observed|reported|forecast(?:ed)?|projected|"
               r"projections?|target|estimated?|estimates|guidance|plan)\b",
               " ", s, flags=re.IGNORECASE)
    s = re.sub(r"\s+", " ", s).strip(" -–—:(),")
    return s or str(metric).strip()


def _prepare_metric_trajectories(quantitative: Any,
                                 *, max_series: int = 8) -> List[Dict[str, Any]]:
    """把 quantitative 行聚成 (metric, unit) 时间序列——读者真正要的预测数据轨迹
    （成本曲线 / 部署量 / 渗透率 / 区域对比）。序列键 = (_metric_series_name 折叠
    后的指标名, 规范化 unit)；点资格 = 数值可解析 + 时点可解析；同一时点重复记录
    保首现（真实工件常见双写）；<2 点的序列剔除；输出按点数降序、(名称, unit)
    字典序截取前 max_series 条（确定性）。"""
    if not isinstance(quantitative, list):
        return []
    groups: Dict[Tuple[str, str], Dict[str, Any]] = {}
    for q in quantitative:
        if not isinstance(q, dict):
            continue
        metric = str(q.get("metric") or "").strip()
        unit = _canonical_quant_unit(q.get("unit"))
        value = _metric_row_value(q)
        when = _parse_metric_point_time(q)
        kind = _metric_row_kind(q)
        if (not metric or value is None or when is None
                or not _metric_row_is_publishable(q, kind)):
            continue
        name = _metric_series_name(metric)
        bucket = groups.setdefault((name.casefold(), unit.casefold()), {
            "metric": name,
            "unit": unit or "value",
            "points": {},
        })
        points = bucket["points"]
        if when in points:
            continue
        points[when] = {
            "date": when,
            "value": value,
            "display_value": str(q.get("value") or value),
            "metric": metric,
            "source": str(q.get("source") or "").strip(),
            "definition": str(q.get("definition") or "").strip(),
            "stale": bool(q.get("is_stale")),
            "projection": kind == "forecast",
        }
    series: List[Dict[str, Any]] = []
    for bucket in groups.values():
        points = bucket["points"]
        if len(points) < 2:
            continue
        series.append({
            "metric": bucket["metric"],
            "unit": bucket["unit"],
            "points": [points[d] for d in sorted(points)],
        })
    series.sort(key=lambda s: (-len(s["points"]), s["metric"], s["unit"]))
    return series[:max(0, max_series)]


# ─────────────────────────────────────────────────────────────────────────────
# DRF2 定量 schema 新增字段读取（metric_family / region / technology / year /
# value_num / value_kind / analyst）——由上游研究抽取补齐。全部「新字段优先、旧字段回退」：
#   · region     → region ?? geography（真实 handoff 用 geography）
#   · year       → year(int) ?? period_end/as_of_date 里的四位年（预测取目标/期末年，
#                  而非发布日：'2030 forecast' 的轨迹应落在 2030 而非发布年）
#   · value_num  → value_num(float) ?? _to_float(value)
#   · value_kind → value_kind ?? value_type ?? _quant_is_projection 推断（actual/forecast）
# 缺 metric_family 即视为「老数据」→ 走 _prepare_metric_trajectories 的折叠名回退路径。
# ─────────────────────────────────────────────────────────────────────────────
def _metric_row_family(row: Dict[str, Any]) -> Optional[str]:
    """显式 metric_family（分组主键）；缺失 → None（调用方回退折叠名路径）。"""
    fam = row.get("metric_family")
    if isinstance(fam, str) and fam.strip():
        return re.sub(r"\s+", " ", fam).strip()
    return None


def _metric_row_region(row: Dict[str, Any]) -> Optional[str]:
    """区域标签：region 优先，回退真实工件里的 geography；均空 → None。"""
    for key in ("region", "geography"):
        v = row.get(key)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return None


def _metric_row_technology(row: Dict[str, Any]) -> Optional[str]:
    """技术标签（domain tech tag）；缺/空 → None（人形机器人跑通常为空 → 跳过技术份额图）。"""
    v = row.get("technology")
    if isinstance(v, str) and v.strip():
        return v.strip()
    return None


def _metric_row_analyst(row: Dict[str, Any]) -> Optional[str]:
    """分析机构标签；缺/空 → None。"""
    v = row.get("analyst")
    if isinstance(v, str) and v.strip():
        return v.strip()
    return None


def _metric_row_year(row: Dict[str, Any]) -> Optional[int]:
    """轨迹 x 轴年份：显式 year(int) 优先；否则从 period_end→as_of_date→date→period 顺序
    取首个合理四位年（期末/目标年在前，发布日在后）。均不可解析 → None。"""
    y = row.get("year")
    if isinstance(y, bool):
        y = None
    if isinstance(y, (int, float)):
        yi = int(y)
        if 1900 <= yi <= 2100:
            return yi
    period_end = _metric_row_period_end(row)
    if period_end is not None:
        return period_end.year
    for key in ("period_start", "as_of_date", "date", "as_of"):
        raw = row.get(key)
        if isinstance(raw, dict):  # period:{...} → 取显式期末/期初/标签子值
            raw = (raw.get("period_end") or raw.get("end")
                   or raw.get("period_start") or raw.get("start") or raw.get("label"))
        m = re.search(r"(?<!\d)(19\d{2}|20\d{2})(?!\d)", str(raw or ""))
        if m:
            return int(m.group(1))
    return None


def _metric_row_value(row: Dict[str, Any]) -> Optional[float]:
    """Value midpoint for explicit ranges, then canonical scalar/fallback text."""
    interval = _explicit_numeric_range(row.get("value"))
    if interval is not None:
        return (interval[0] + interval[1]) / 2.0
    v = row.get("value_num")
    if isinstance(v, bool):
        v = None
    if isinstance(v, (int, float)):
        f = float(v)
        if f == f:  # 过滤 NaN
            return f
    return _to_float(row.get("value"))


def _metric_row_kind(row: Dict[str, Any]) -> str:
    """观测/预测判定（actual|forecast）：value_kind 优先，回退 value_type，再回退
    _quant_is_projection 语义推断。用于轨迹/区域图上区分实测点与预测点的记号样式。"""
    for key in ("value_kind", "value_type"):
        raw = row.get(key)
        if isinstance(raw, str):
            low = raw.strip().lower()
            if low in {"actual", "observed", "historical", "reported"}:
                return "actual"
            if low in {"forecast", "forecasted", "projection", "projected",
                       "target", "expected", "estimate", "estimated"}:
                return "forecast"
    return "forecast" if _quant_is_projection(row) else "actual"


def _aggregate_metric_points(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """把同一条折线（同一 split 值）的行按 year 聚成逐年点：同年多行取均值（预测/观测
    混排时优先取观测子集的均值并标 actual），确定性升序。rep 保留一条代表行供 hover。"""
    by_year: Dict[int, List[Dict[str, Any]]] = {}
    for r in rows:
        by_year.setdefault(r["year"], []).append(r)
    points: List[Dict[str, Any]] = []
    for year in sorted(by_year):
        grp = by_year[year]
        actuals = [g for g in grp if g["kind"] == "actual"]
        chosen = actuals or grp
        mean = sum(g["value"] for g in chosen) / len(chosen)
        points.append({
            "x": year,
            "x_label": str(year),
            "period_end": chosen[0].get("period_end") or f"{year:04d}-12-31",
            "value": mean,
            "kind": "actual" if actuals else "forecast",
            "stale": any(g["stale"] for g in chosen),
            "n": len(grp),
            "rep": chosen[0],
        })
    return points


def _build_metric_trajectory_lines(rows: List[Dict[str, Any]],
                                   split: Optional[str]) -> List[Dict[str, Any]]:
    """按 split 维度（region/technology/analyst 之一，或 None）把家族内的行拆成折线。
    split 为 None → 单折线（name=None）；否则每个非空 split 值一条折线（字典序）。"""
    lines: List[Dict[str, Any]] = []
    if split:
        groups: Dict[str, List[Dict[str, Any]]] = {}
        for r in rows:
            key = r.get(split)
            if not key:
                continue  # split 值缺失的行不进任何折线（避免伪造归属）
            groups.setdefault(str(key), []).append(r)
        for name in sorted(groups):
            pts = _aggregate_metric_points(groups[name])
            if pts:
                lines.append({"name": name, "points": pts})
    else:
        pts = _aggregate_metric_points(rows)
        if pts:
            lines.append({"name": None, "points": pts})
    return lines


def _prepare_metric_family_trajectories(quantitative: Any, *,
                                        max_families: int = 8) -> List[Dict[str, Any]]:
    """DRF2 主路径：按 metric_family（× unit）把行聚成家族，跨 year 画轨迹——一条折线对应
    一个 region/technology/analyst 分组（择首个有 ≥2 个不同取值的维度做拆分，否则单折线）。
    家族资格 = 该家族含 ≥2 个不同年份的点（否则不成轨迹）。观测点圆记号、预测点菱形记号。
    输出规范化 panel（title/unit/split/lines），按点数降序、标题字典序截断 max_families 条。"""
    if not isinstance(quantitative, list):
        return []
    families: Dict[Tuple[str, str], Dict[str, Any]] = {}
    for q in quantitative:
        if not isinstance(q, dict):
            continue
        fam = _metric_row_family(q)
        if not fam:
            continue
        unit = _canonical_quant_unit(q.get("unit")) or "value"
        year = _metric_row_year(q)
        val = _metric_row_value(q)
        kind = _metric_row_kind(q)
        if (year is None or val is None
                or not _metric_row_is_publishable(q, kind)):
            continue
        bucket = families.setdefault((fam.casefold(), unit.casefold()), {
            "family": fam,
            "unit": unit,
            "rows": [],
        })
        bucket["rows"].append({
            "year": year,
            "value": val,
            "kind": kind,
            "period_end": (
                _metric_row_period_end(q).isoformat()
                if _metric_row_period_end(q) is not None
                else f"{year:04d}-12-31"
            ),
            "region": _metric_row_region(q),
            "technology": _metric_row_technology(q),
            "analyst": _metric_row_analyst(q),
            "stale": bool(q.get("is_stale")),
            "metric": str(q.get("metric") or "").strip(),
            "display_value": str(q.get("value") if q.get("value") is not None else val),
            "source": str(q.get("source") or "").strip(),
            "definition": str(q.get("definition") or "").strip(),
        })
    panels: List[Dict[str, Any]] = []
    for bucket in families.values():
        rows = bucket["rows"]
        if len({r["year"] for r in rows}) < 2:  # 家族需 ≥2 个不同年份点才成轨迹
            continue
        split: Optional[str] = None
        for dim in ("region", "technology", "analyst"):
            if len({r[dim] for r in rows if r[dim]}) >= 2:
                split = dim
                break
        lines = _build_metric_trajectory_lines(rows, split)
        if not lines:
            continue
        panels.append({
            "title": f"{bucket['family']} · {bucket['unit']}"
                     + (f"  (by {split})" if split else ""),
            "unit": bucket["unit"],
            "split": split,
            "lines": lines,
        })
    panels.sort(key=lambda p: (-sum(len(ln["points"]) for ln in p["lines"]), p["title"]))
    return panels[:max(0, max_families)]


def _legacy_metric_trajectory_panels(quantitative: Any, *,
                                     max_families: int = 8) -> List[Dict[str, Any]]:
    """老数据回退：复用 _prepare_metric_trajectories（折叠名 × unit 单序列）并适配成
    与家族路径同构的 panel（单折线、x 为 ISO 日期字符串），供同一渲染器使用。"""
    series = _prepare_metric_trajectories(quantitative, max_series=max_families)
    panels: List[Dict[str, Any]] = []
    for s in series:
        pts = [{
            "x": p["date"],
            "x_label": p["date"].isoformat(),
            "value": p["value"],
            "kind": "forecast" if p["projection"] else "actual",
            "stale": p["stale"],
            "n": 1,
            "rep": {
                "metric": p["metric"],
                "display_value": p["display_value"],
                "source": p["source"],
                "definition": p["definition"],
            },
        } for p in s["points"]]
        panels.append({
            "title": f"{s['metric']} · {s['unit']}",
            "unit": s["unit"],
            "split": None,
            "lines": [{"name": None, "points": pts}],
        })
    return panels


def _metric_trajectory_panels(quantitative: Any, *,
                              max_families: int = 8) -> List[Dict[str, Any]]:
    """轨迹渲染的统一入口：任一行带 metric_family → 走 DRF2 家族分组路径；该路径产出为空
    （新字段不足）或全无 metric_family → 回退折叠名路径（保证老数据仍出图）。"""
    if isinstance(quantitative, list) and any(
            isinstance(q, dict) and _metric_row_family(q) for q in quantitative):
        panels = _prepare_metric_family_trajectories(quantitative,
                                                     max_families=max_families)
        if panels:
            return panels
    return _legacy_metric_trajectory_panels(quantitative, max_families=max_families)


def _prepare_technology_shares(quantitative: Any, *,
                               max_families: int = 4) -> List[Dict[str, Any]]:
    """DRF2 技术份额：某 metric_family 的行在某一年带 ≥2 个不同 technology → 取该家族
    「最新且技术数 ≥2」的年份，产出各技术的 value_num 与占比（同技术同年多行取均值）。
    人形机器人跑 technology 多为空 → 直接跳过；能源存储跑（磷酸铁锂/三元/钠离子…）会点亮。"""
    if not isinstance(quantitative, list):
        return []
    families: Dict[Tuple[str, str], Dict[str, Any]] = {}
    for q in quantitative:
        if not isinstance(q, dict):
            continue
        fam = _metric_row_family(q)
        tech = _metric_row_technology(q)
        year = _metric_row_year(q)
        val = _metric_row_value(q)
        kind = _metric_row_kind(q)
        if (not fam or not tech or year is None or val is None
                or not _metric_row_is_publishable(q, kind)):
            continue
        unit = _canonical_quant_unit(q.get("unit")) or "value"
        bucket = families.setdefault((fam.casefold(), unit.casefold()), {
            "family": fam,
            "unit": unit,
            "rows": [],
        })
        bucket["rows"].append({
            "tech": tech,
            "year": year,
            "value": val,
            "kind": kind,
            "metric": str(q.get("metric") or "").strip(),
            "source": str(q.get("source") or "").strip(),
            "display_value": str(q.get("value") if q.get("value") is not None else val),
        })
    panels: List[Dict[str, Any]] = []
    for bucket in families.values():
        by_year: Dict[int, Dict[str, List[Dict[str, Any]]]] = {}
        for r in bucket["rows"]:
            by_year.setdefault(r["year"], {}).setdefault(r["tech"], []).append(r)
        chosen_year: Optional[int] = None
        for year in sorted(by_year, reverse=True):  # 最新且技术数 ≥2 的年份
            if len(by_year[year]) >= 2:
                chosen_year = year
                break
        if chosen_year is None:
            continue
        techs: List[Dict[str, Any]] = []
        for tech in sorted(by_year[chosen_year]):
            grp = by_year[chosen_year][tech]
            mean = sum(g["value"] for g in grp) / len(grp)
            techs.append({"tech": tech, "value": mean, "n": len(grp), "rep": grp[0]})
        total = sum(t["value"] for t in techs) or 1.0
        for t in techs:
            t["share"] = t["value"] / total
        panels.append({
            "family": bucket["family"],
            "unit": bucket["unit"],
            "year": chosen_year,
            "techs": techs,
        })
    panels.sort(key=lambda p: (-len(p["techs"]), p["family"]))
    return panels[:max(0, max_families)]


def _prepare_regional_comparison(quantitative: Any, *,
                                 max_families: int = 4) -> List[Dict[str, Any]]:
    """DRF2 区域对比：某 metric_family 的行带 ≥2 个不同 region → 取该家族「最新且区域数 ≥2」
    的年份，产出各区域的 value_num（同区域同年多行优先取观测均值）。<2 区域 → 跳过。"""
    if not isinstance(quantitative, list):
        return []
    families: Dict[Tuple[str, str], Dict[str, Any]] = {}
    for q in quantitative:
        if not isinstance(q, dict):
            continue
        fam = _metric_row_family(q)
        region = _metric_row_region(q)
        year = _metric_row_year(q)
        val = _metric_row_value(q)
        kind = _metric_row_kind(q)
        if (not fam or not region or year is None or val is None
                or not _metric_row_is_publishable(q, kind)):
            continue
        unit = _canonical_quant_unit(q.get("unit")) or "value"
        bucket = families.setdefault((fam.casefold(), unit.casefold()), {
            "family": fam,
            "unit": unit,
            "rows": [],
        })
        bucket["rows"].append({
            "region": region,
            "year": year,
            "value": val,
            "kind": kind,
            "metric": str(q.get("metric") or "").strip(),
            "source": str(q.get("source") or "").strip(),
            "display_value": str(q.get("value") if q.get("value") is not None else val),
        })
    panels: List[Dict[str, Any]] = []
    for bucket in families.values():
        by_year: Dict[int, Dict[str, List[Dict[str, Any]]]] = {}
        for r in bucket["rows"]:
            by_year.setdefault(r["year"], {}).setdefault(r["region"], []).append(r)
        chosen_year: Optional[int] = None
        for year in sorted(by_year, reverse=True):  # 最新且区域数 ≥2 的年份
            if len(by_year[year]) >= 2:
                chosen_year = year
                break
        if chosen_year is None:
            continue
        regions: List[Dict[str, Any]] = []
        for region in sorted(by_year[chosen_year]):
            grp = by_year[chosen_year][region]
            actuals = [g for g in grp if g["kind"] == "actual"]
            chosen = actuals or grp
            mean = sum(g["value"] for g in chosen) / len(chosen)
            regions.append({
                "region": region,
                "value": mean,
                "kind": "actual" if actuals else "forecast",
                "n": len(grp),
                "rep": chosen[0],
            })
        panels.append({
            "family": bucket["family"],
            "unit": bucket["unit"],
            "year": chosen_year,
            "regions": regions,
        })
    panels.sort(key=lambda p: (-len(p["regions"]), p["family"]))
    return panels[:max(0, max_families)]


def _prepare_forecast_revision_series(
    quantitative: Any,
    *,
    max_series: int = 3,
) -> List[Dict[str, Any]]:
    """Extract repeated published forecast vintages from quantitative rows.

    A series is eligible only when three or more trailing ``(YYYY)`` labels are
    corroborated by ``as_of_date`` as publication vintages and share publisher/
    outlook family, fixed target horizon, unit, metric identity, and definition.
    Source citation years are ignored for family identity because a later outlook
    may legitimately recap an earlier vintage.
    """
    if not isinstance(quantitative, list):
        return []
    grouped: Dict[Tuple[str, int, str, str, str], Dict[str, Any]] = {}
    for q in quantitative:
        if not isinstance(q, dict):
            continue
        metric = re.sub(r"\s+", " ", str(q.get("metric") or "")).strip()
        match = re.search(r"\((20\d{2})\)\s*$", metric)
        if not match:
            continue
        descriptive = " ".join((metric, str(q.get("definition") or "")))
        if not _FORECAST_SIGNAL_RE.search(descriptive):
            continue
        value = _metric_row_value(q)
        unit = _canonical_quant_unit(q.get("unit"))
        source = str(q.get("source") or "").strip()
        definition = str(q.get("definition") or "").strip()
        as_of = _parse_quant_date(q.get("as_of_date"))
        if (value is None or not unit or not source or not definition
                or as_of is None
                or not _metric_row_is_publishable(q, "forecast")):
            continue
        vintage = int(match.group(1))
        if vintage != as_of.year:
            continue
        name = metric[:match.start()].rstrip(" -–—:")
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
        series = grouped.setdefault(key, {
            "name": name,
            "unit": unit,
            "publisher_family": publisher_family,
            "target_year": target_year,
            "points": {},
        })
        candidate = {
            "vintage": vintage,
            "value": value,
            "display_value": str(q.get("value") or value),
            "as_of": as_of.isoformat(),
            "source": source,
            "tier": str(q.get("tier") or "S3").strip().upper() or "S3",
            "stale": bool(q.get("is_stale")),
        }
        previous = series["points"].get(vintage)
        if previous is None or _TIER_RANK.get(candidate["tier"], 9) < _TIER_RANK.get(
            previous["tier"], 9
        ):
            series["points"][vintage] = candidate

    result: List[Dict[str, Any]] = []
    for series in grouped.values():
        points = [series["points"][v] for v in sorted(series["points"])]
        if len(points) >= 3:
            result.append({
                "name": series["name"],
                "unit": series["unit"],
                "publisher_family": series["publisher_family"],
                "target_year": series["target_year"],
                "points": points,
            })
    result.sort(key=lambda series: (-len(series["points"]), series["name"].lower()))
    return result[:max(0, max_series)]


# 关系类型 → 英文边标签（用于因果/网络图；未知类型原样大写）。
_REL_LABEL_EN = {
    "CAUSES": "CAUSES", "ENABLES": "ENABLES", "CONSTRAINS": "CONSTRAINS",
    "OPPOSES": "OPPOSES", "SUPPORTS": "SUPPORTS", "ALLIES": "ALLIES",
    "ALLIED_WITH": "ALLIED", "RIVALS": "RIVALS", "COMPETES": "COMPETES",
    "INFLUENCES": "INFLUENCES", "DEPENDS_ON": "DEPENDS", "PART_OF": "PART_OF",
    "NEGOTIATES": "NEGOTIATES", "FUNDS": "FUNDS", "THREATENS": "THREATENS",
}

# 关系 sign/valence → 符号（用于有向签名边）。
_SIGN_TOKEN = {
    "+": "+", "positive": "+", "supportive": "+", "ally": "+", "allied": "+",
    "-": "−", "negative": "−", "adversarial": "−", "rival": "−", "oppose": "−",
    "0": "±", "neutral": "±", "mixed": "±", "transactional": "±",
}


def _sign_of(rel: Dict[str, Any]) -> str:
    """从关系 dict 推导签名符号（+/−/±）：优先 sign，其次 valence，再看 polarity 数值。"""
    for key in ("sign", "valence", "polarity_label"):
        raw = str(rel.get(key, "") or "").strip().lower()
        if raw in _SIGN_TOKEN:
            return _SIGN_TOKEN[raw]
    pol = _to_float(rel.get("polarity"))
    if pol is not None:
        if pol > 0.15:
            return "+"
        if pol < -0.15:
            return "−"
        return "±"
    return ""


class ReportVisualizer:
    """报告可视化器。所有 render_mermaid_* 为纯静态助手；build_all 为落盘编排入口。

    典型用法（供 report_agent 钩子调用）：
        viz = ReportVisualizer()
        manifest = viz.build_all(report_id, report_dir, artifacts)
    其中 artifacts 是已从 report 文件夹 / handoff 目录读入的普通 dict/list 集合，键名见
    build_all 文档字符串。任何工件缺失/畸形都跳过对应图（并记入 manifest 的 skipped 列表），
    绝不阻断报告生成。
    """

    def __init__(self) -> None:
        # WAVE9 PNG 导出批处理状态：build_all 内先排队、末尾一次 flush（kaleido/Chromium 启动
        # 摊销到一次）；独立调用构建器时即时渲染。
        self._png_jobs: List[Tuple[Any, str, str, str]] = []  # (fig, abs_path, rel_path, item_id)
        self._png_done: Dict[str, str] = {}                   # item_id -> rel png path
        self._batch_mode = False
        self._kaleido_failed = False
        # VIZ-GAP2：构建器返回 None 时的结构化跳过说明（密度门降级为紧凑表格）。
        # item_id -> {"reason": ..., "fallback_path": ...}；build_all 的 _attempt 消费。
        self._skip_notes: Dict[str, Dict[str, str]] = {}

    # ============================ (A) Mermaid 族 ============================
    # 全部为 @staticmethod 纯函数：入参普通 dict/list，返回 ```mermaid``` 代码块字符串；
    # 畸形/空输入 → ''（never raises）。

    @staticmethod
    def render_mermaid_timeline(timeline: Any, title: str = "Event Timeline") -> str:
        """timeline.json（[{date,event}] 或 {timeline:[...]}）→ ```mermaid timeline```。

        兼容 zh/en 键：date/日期、event/事件/text/label。按日期升序（无日期项保持原序末尾）。
        无有效条目 → ''。"""
        try:
            rows = timeline.get("timeline") if isinstance(timeline, dict) else timeline
            if not isinstance(rows, list) or not rows:
                return ""
            items: List[Tuple[str, str]] = []
            for r in rows:
                if not isinstance(r, dict):
                    continue
                date = str(r.get("date") or r.get("日期") or r.get("when") or "").strip()
                event = (r.get("event") or r.get("事件") or r.get("text")
                         or r.get("label") or r.get("description"))
                ev = _san_label(event, max_len=90)
                if not ev:
                    continue
                items.append((date, ev))
            if not items:
                return ""
            # 稳定排序：有日期的按日期，无日期的排到末尾（保持相对顺序）。
            dated = [(d, e) for d, e in items if d]
            undated = [(d, e) for d, e in items if not d]
            dated.sort(key=lambda t: t[0])
            ordered = dated + undated

            lines = ["```mermaid", "timeline", f"    title {_san_label(title, 60)}"]
            # Mermaid timeline 语法：`<period> : <event>`。无日期时用序号占位周期。
            for i, (d, e) in enumerate(ordered, 1):
                period = _san_label(d, 24) if d else f"({i})"
                lines.append(f"    {period} : {e}")
            lines.append("```")
            return "\n".join(lines)
        except Exception:  # noqa: BLE001 - 纯助手永不抛错
            return ""

    @staticmethod
    def render_mermaid_causal(paths: Any, title: str = "") -> str:
        """因果路径 → ```mermaid flowchart LR```（带签名边标签）。

        接受两种入参（皆来自 KG trace 输出）：
          ① 字符串列表，形如 'A --[CAUSES,+,strong]--> B'（方括号内 逗号分隔：类型,符号,强度）；
          ② 结构化路径列表 [{source,target,relation/type,sign,strength}]（或 {paths:[...]}）。
        边标签为 `TYPE 符号/强度`（例如 `CAUSES +/strong`）。无有效边 → ''。"""
        try:
            if isinstance(paths, dict):
                paths = paths.get("paths") or paths.get("edges") or paths.get("causal") or []
            if not isinstance(paths, list) or not paths:
                return ""
            edges: List[Tuple[str, str, str]] = []  # (source, target, label)
            for p in paths:
                parsed = _parse_causal_item(p)
                if parsed:
                    edges.extend(parsed)
            if not edges:
                return ""
            max_nodes = int(_cfg("REPORT_VIZ_MAX_NODES", 40) or 40)
            counter: Dict[str, str] = {}
            lines = ["```mermaid", "flowchart LR"]
            if title:
                lines.insert(1, f"%% {_san_label(title, 60)}")
            emitted = 0
            for src, tgt, label in edges:
                if len(counter) >= max_nodes and (src not in counter or tgt not in counter):
                    break
                sid = _node_id(counter, src)
                tid = _node_id(counter, tgt)
                lines.append(f'    {sid}["{_san_label(src, 40)}"] '
                             f'-->|"{_san_label(label, 40)}"| {tid}["{_san_label(tgt, 40)}"]')
                emitted += 1
            if emitted == 0:
                return ""
            lines.append("```")
            return "\n".join(lines)
        except Exception:  # noqa: BLE001
            return ""

    @staticmethod
    def render_mermaid_coalition(coalition: Any, title: str = "Coalition Map") -> str:
        """派系/联盟聚类 → ```mermaid flowchart TB``` 的 subgraph 簇。

        接受灵活入参：
          ① {clusters:[{label,members:[...]}, ...]} 或 {coalitions:[...]}；
          ② [{label,members:[...]}, ...]；
          ③ [[name,name,...], ...]（每个子列表即一个派系）。
        每个 ≥1 成员的派系渲染为一个 subgraph。无有效派系 → ''。"""
        try:
            clusters = _normalize_clusters(coalition)
            if not clusters:
                return ""
            max_nodes = int(_cfg("REPORT_VIZ_MAX_NODES", 40) or 40)
            lines = ["```mermaid", "flowchart TB", f"%% {_san_label(title, 60)}"]
            mid = 0
            drawn = 0
            for ci, (label, members) in enumerate(clusters, 1):
                clean_members = [_san_label(m, 40) for m in members if _san_label(m, 40)]
                if not clean_members:
                    continue
                lbl = _san_label(label, 50) or f"Faction {ci}"
                lines.append(f'    subgraph c{ci}["{lbl} ({len(clean_members)})"]')
                lines.append("        direction TB")
                for m in clean_members:
                    if mid >= max_nodes:
                        break
                    lines.append(f'        m{mid}["{m}"]')
                    mid += 1
                lines.append("    end")
                drawn += 1
                if mid >= max_nodes:
                    break
            if drawn == 0:
                return ""
            lines.append("```")
            return "\n".join(lines)
        except Exception:  # noqa: BLE001
            return ""

    @staticmethod
    def render_mermaid_actor_network(actors: Any, title: str = "Actor Relationship Network") -> str:
        """actors.json 的 relationships[] → ```mermaid graph TD``` 有向类型化网络。

        接受 {relationships:[...]} 或直接 relationships 列表。每条关系需含 source/target；
        边标签为关系类型（英文），签名（+/−/±）追加。仅渲染出现在某条关系里的节点。
        无有效关系 → ''。"""
        try:
            if isinstance(actors, dict):
                rels = actors.get("relationships") or actors.get("relations") or actors.get("edges")
            else:
                rels = actors
            if not isinstance(rels, list) or not rels:
                return ""
            max_nodes = int(_cfg("REPORT_VIZ_MAX_NODES", 40) or 40)
            counter: Dict[str, str] = {}
            lines = ["```mermaid", "graph TD", f"%% {_san_label(title, 60)}"]
            emitted = 0
            for r in rels:
                if not isinstance(r, dict):
                    continue
                src = str(r.get("source") or r.get("from") or r.get("源") or "").strip()
                tgt = str(r.get("target") or r.get("to") or r.get("目标") or "").strip()
                if not src or not tgt:
                    continue
                if len(counter) >= max_nodes and (src not in counter or tgt not in counter):
                    continue
                typ = str(r.get("type") or r.get("relation") or r.get("rel") or "").strip().upper()
                label = _REL_LABEL_EN.get(typ, typ or "REL")
                sign = _sign_of(r)
                if sign:
                    label = f"{label} {sign}"
                sid = _node_id(counter, src)
                tid = _node_id(counter, tgt)
                lines.append(f'    {sid}["{_san_label(src, 40)}"] '
                             f'-->|"{_san_label(label, 30)}"| {tid}["{_san_label(tgt, 40)}"]')
                emitted += 1
            if emitted == 0:
                return ""
            lines.append("```")
            return "\n".join(lines)
        except Exception:  # noqa: BLE001
            return ""

    # ============================ (B) matplotlib 族 ============================
    # 全部为实例方法：入参普通 dict/list + 输出目录，成功落盘 PNG 返回相对路径，否则 None。
    # matplotlib 缺失 → 直接 None（build_all 会跳过整族）。一图一 figure，dpi 见旋钮。

    def _chart_ok(self) -> bool:
        return MATPLOTLIB_AVAILABLE and bool(_cfg("REPORT_VIZ_CHARTS", True))

    def _price_hist_ok(self) -> bool:
        """PM-6 市场价格历史折线族开关（默认开）。Config 未定义该属性时回退直接读 os.environ
        （避免跨文件改动 config.py 也能被 env 切换），仍缺 → 默认 True（degrade-safe）。"""
        val = _cfg("REPORT_VIZ_PRICE_HISTORY", None)
        if val is None:
            raw = os.environ.get("REPORT_VIZ_PRICE_HISTORY")
            if raw is None:
                return True
            return raw.strip().lower() == "true"
        return bool(val)

    def _dpi(self) -> int:
        try:
            return max(72, int(_cfg("REPORT_VIZ_DPI", 160) or 160))
        except (TypeError, ValueError):
            return 160

    def _save(self, fig, charts_dir: str, filename: str) -> Optional[str]:
        """把 figure 存成 PNG 并关闭；返回相对 report_dir 的路径 'charts/<file>'。失败 → None。"""
        try:
            os.makedirs(charts_dir, exist_ok=True)
            out_path = os.path.join(charts_dir, filename)
            fig.savefig(out_path, dpi=self._dpi(), bbox_inches="tight")
            return os.path.join("charts", filename)
        except Exception:  # noqa: BLE001
            return None
        finally:
            try:
                plt.close(fig)
            except Exception:  # noqa: BLE001
                pass

    def build_scenario_bars(self, forecast: Any, charts_dir: str,
                            ensemble: Any = None) -> Optional[str]:
        """(1) 情景概率横向柱状 + 来源可辨的误差棒。

        ``ensemble_forecast.json`` 的 min/max 显示为 ensemble spread；canonical
        ``forecast.json`` 自身的 p_low/p_high 显示为 declared uncertainty interval。
        两类区间使用不同颜色/标记且绝不互相冒充。无情景 → None。
        """
        if not self._chart_ok():
            return None
        fig = None
        try:
            rows = _extract_scenario_rows(forecast, ensemble)
            if not rows:
                return None
            names: List[str] = []
            probs: List[float] = []
            lo_err: List[float] = []
            hi_err: List[float] = []
            interval_sources: List[Optional[str]] = []
            for i, r in enumerate(rows, 1):
                nm = _mpl_text(r["name"], fallback=f"Scenario {i}", max_len=48)
                names.append(nm)
                probs.append(r["p"])
                if (r["lo"] is not None and r["hi"] is not None
                        and r["hi"] > r["lo"]):
                    lo_err.append(max(0.0, r["p"] - r["lo"]))
                    hi_err.append(max(0.0, r["hi"] - r["p"]))
                    interval_sources.append(r.get("interval_source"))
                else:
                    lo_err.append(0.0)
                    hi_err.append(0.0)
                    interval_sources.append(None)
            if not probs:
                return None
            label_text = " ".join(names)
            if not _mpl_labels_supported(label_text):
                logger.info("scenario static chart skipped: no installed font covers CJK labels")
                return None
            label_font = _mpl_font_for_text(label_text)
            y = list(range(len(names)))[::-1]  # 顶部为第一个情景
            fig, ax = plt.subplots(figsize=(9, max(2.2, 0.7 * len(names) + 1.2)))
            ax.barh(y, probs, color="#3b6fb0", height=0.6)
            for source in _SCENARIO_INTERVAL_ORDER:
                indices = [i for i, value in enumerate(interval_sources) if value == source]
                if not indices:
                    continue
                style = _SCENARIO_INTERVAL_STYLES[source]
                ax.errorbar(
                    [probs[i] for i in indices],
                    [y[i] for i in indices],
                    xerr=[
                        [lo_err[i] for i in indices],
                        [hi_err[i] for i in indices],
                    ],
                    fmt=style["marker"],
                    color=style["color"],
                    ecolor=style["color"],
                    markersize=3.5,
                    elinewidth=1.3,
                    capsize=style["capsize"],
                    label=style["label"],
                    zorder=3,
                )
            ax.set_yticks(y)
            ax.set_yticklabels(names, fontsize=9, fontproperties=label_font)
            ax.set_xlabel("Probability", fontsize=10)
            ax.set_xlim(0, max(1.0, max(probs) * 1.15))
            ax.set_title(_scenario_interval_title(rows), fontsize=12,
                         fontweight="bold", pad=18)
            # VIZ-GAP1(b)：区间溯源/裸点估计的副标题（PNG 是 PDF 的最终形态，必须自明）。
            subtitle = _scenario_interval_subtitle(rows, forecast).replace("<br>", " ")
            ax.text(0.5, 1.005, _mpl_text(subtitle, max_len=110),
                    transform=ax.transAxes, ha="center", va="bottom",
                    fontsize=8, color="#52514e")
            if any(interval_sources):
                ax.legend(loc="lower right", frameon=False, fontsize=8)
            for yi, p, err in zip(y, probs, hi_err, strict=True):
                # 数值标签让位于误差棒（放到区间上界之外），避免被误差线横穿。
                ax.text(p + err + 0.01, yi, f"{p * 100:.0f}%", va="center", fontsize=9)
            ax.grid(axis="x", linestyle=":", alpha=0.4)
            fig.tight_layout()
            return self._save(fig, charts_dir, "scenario_probabilities.png")
        except Exception as exc:  # noqa: BLE001
            logger.debug("build_scenario_bars 失败（跳过该图）：%s", exc)
            return None
        finally:
            _close_matplotlib_figure(fig)

    def build_model_vs_market(self, forecast: Any, charts_dir: str) -> Optional[str]:
        """(2) 模型 vs 市场哑铃图（来自 binary_forecasts[].market_anchor 的分歧）。

        每条二元预测：模型概率 vs market_anchor.implied_yes_prob，连线两点。只保留带 market_anchor
        的条目。无可比条目 → None。"""
        if not self._chart_ok():
            return None
        fig = None
        try:
            bfs = forecast.get("binary_forecasts") if isinstance(forecast, dict) else forecast
            if not isinstance(bfs, list) or not bfs:
                return None
            labels: List[str] = []
            model_p: List[float] = []
            market_p: List[float] = []
            for bf in bfs:
                if not isinstance(bf, dict):
                    continue
                anchor = bf.get("market_anchor")
                if not isinstance(anchor, dict):
                    continue
                mp = _to_float(bf.get("probability"))
                kp = _to_float(anchor.get("implied_yes_prob"))
                if kp is None:
                    kp = _to_float(anchor.get("implied_prob"))
                if mp is None or kp is None:
                    continue
                lab = _mpl_text(bf.get("id") or bf.get("statement") or bf.get("market_id")
                                or anchor.get("market_id"), fallback=f"F{len(labels) + 1}", max_len=46)
                labels.append(lab)
                model_p.append(mp)
                market_p.append(kp)
            if not labels:
                return None
            # VIZ-GAP2：与 plotly 版同一密度门——<3 条锚定命题不再产出整页静态图
            # （markdown 表降级由 plotly 构建器负责，避免重复登记）。
            if len(labels) < _MODEL_VS_MARKET_MIN_ANCHORED:
                return None
            label_text = " ".join(labels)
            if not _mpl_labels_supported(label_text):
                logger.info("model-vs-market static chart skipped: no installed font covers CJK labels")
                return None
            label_font = _mpl_font_for_text(label_text)
            y = list(range(len(labels)))[::-1]
            fig, ax = plt.subplots(figsize=(9, max(2.2, 0.6 * len(labels) + 1.4)))
            for yi, mp, kp in zip(y, model_p, market_p):
                ax.plot([kp, mp], [yi, yi], color="#9aa5b1", linewidth=2, zorder=1)
            ax.scatter(market_p, y, color="#c0603a", s=60, zorder=2, label="Market implied")
            ax.scatter(model_p, y, color="#3b6fb0", s=60, zorder=3, label="Model")
            ax.set_yticks(y)
            ax.set_yticklabels(labels, fontsize=9, fontproperties=label_font)
            ax.set_xlabel("P(yes)", fontsize=10)
            ax.set_xlim(0, 1)
            ax.set_title("Model vs Market (binary forecasts)", fontsize=12, fontweight="bold")
            ax.grid(axis="x", linestyle=":", alpha=0.4)
            ax.legend(loc="lower right", fontsize=9)
            fig.tight_layout()
            return self._save(fig, charts_dir, "model_vs_market.png")
        except Exception:  # noqa: BLE001
            return None
        finally:
            _close_matplotlib_figure(fig)

    def build_worldstate_area(self, trajectory: Any, charts_dir: str) -> Optional[str]:
        """(3) 结果世界态堆叠面积（world_state_trajectory.json 的 trajectory[].shares 随轮次）。

        兼容 {trajectory:[{round,shares:{name:share}}]} 或直接列表；shares 为情景→份额。
        少于 2 个时间点 → None（面积图无意义）。CAL-TEMPORAL：若所有行都带可解析的
        period_end/as_of（轨迹 schema v3，日历模式）→ 横轴改用日历日期并标注 "Date"；
        否则保持旧的 "Forecast update step" 轮次横轴（hours 模式行为字节不变）。"""
        if not self._chart_ok():
            return None
        fig = None
        try:
            rows = trajectory.get("trajectory") if isinstance(trajectory, dict) else trajectory
            if not isinstance(rows, list) or len(rows) < 2:
                return None
            # 收集所有出现过的情景名（稳定：首次出现顺序）。
            names: List[str] = []
            snaps: List[Tuple[float, Dict[str, float]]] = []
            dates: List[Any] = []  # CAL-TEMPORAL：与 snaps 一一对应的日历日期（可含 None）
            for i, r in enumerate(rows):
                if not isinstance(r, dict):
                    continue
                shares = r.get("shares")
                if not isinstance(shares, dict) or not shares:
                    continue
                x = _to_float(r.get("round"))
                if x is None:
                    x = float(i)
                clean: Dict[str, float] = {}
                for k, v in shares.items():
                    fv = _to_float(v)
                    if fv is None:
                        continue
                    clean[str(k)] = fv
                    if str(k) not in names:
                        names.append(str(k))
                if clean:
                    snaps.append((x, clean))
                    dates.append(_trajectory_row_date(r))
            if len(snaps) < 2 or not names:
                return None
            # CAL-TEMPORAL：任一快照缺日期 → 整体回退轮次横轴（degrade-safe）。
            use_dates = bool(dates) and all(d is not None for d in dates)
            xs: List[Any] = dates if use_dates else [x for x, _ in snaps]
            series = [[snap.get(nm, 0.0) for _, snap in snaps] for nm in names]
            fig, ax = plt.subplots(figsize=(9, 5))
            leg_labels = [_mpl_text(n, fallback=f"Series {i + 1}", max_len=40)
                          for i, n in enumerate(names)]
            label_text = " ".join(leg_labels)
            if not _mpl_labels_supported(label_text):
                logger.info("world-state static chart skipped: no installed font covers CJK labels")
                return None
            label_font = _mpl_font_for_text(label_text)
            ax.stackplot(xs, *series, labels=leg_labels, alpha=0.85)
            if use_dates:
                # 复用时间线泳道的日期横轴规范（AutoDateLocator + ConciseDateFormatter）。
                import matplotlib.dates as _mdates
                locator = _mdates.AutoDateLocator(minticks=3, maxticks=8)
                ax.xaxis.set_major_locator(locator)
                ax.xaxis.set_major_formatter(_mdates.ConciseDateFormatter(locator))
                ax.set_xlabel("Date", fontsize=10)
            else:
                ax.set_xlabel("Forecast update step", fontsize=10)
            ax.set_ylabel("Outcome share", fontsize=10)
            ax.set_title("Forecast Outcome-Share Trajectory", fontsize=12, fontweight="bold")
            ax.set_xlim(min(xs), max(xs))
            ax.set_ylim(0, max(1.0, max(sum(col) for col in zip(*series)) if series else 1.0))
            ax.legend(loc="upper left", fontsize=8, ncol=1, framealpha=0.85,
                      prop=_font_at_size(label_font, 8) if label_font else None)
            ax.grid(linestyle=":", alpha=0.35)
            fig.tight_layout()
            return self._save(fig, charts_dir, "worldstate_trajectory.png")
        except Exception:  # noqa: BLE001
            return None
        finally:
            _close_matplotlib_figure(fig)

    def build_timeline_lanes(self, timeline: Any, charts_dir: str) -> Optional[str]:
        """Static PNG counterpart to :meth:`build_timeline_lanes_html`.

        The builder intentionally consumes ``_prepare_timeline_events`` so the interactive and
        static paths share date parsing, de-duplication, salience ranking, lane classification,
        and ``REPORT_VIZ_TIMELINE_MAX_EVENTS`` enforcement.  It is used when Plotly is disabled
        or when an interactive figure has no exported PNG.
        """
        if not self._chart_ok():
            return None
        fig = None
        try:
            rows = timeline.get("timeline") if isinstance(timeline, dict) else timeline
            if not isinstance(rows, list) or not rows:
                return None
            events = _prepare_timeline_events(rows)
            if not events:
                return None

            lanes = [category for category, _ in _TL_CATEGORIES] + ["Other"]
            lane_order = {category: index for index, category in enumerate(lanes)}
            used = sorted({event["cat"] for event in events}, key=lane_order.get)
            used_index = {category: index for index, category in enumerate(used)}
            label_plan = _timeline_label_plan(events, used_index)
            label_text = " ".join(entry["label"] for entry in label_plan.values())
            if not _mpl_labels_supported(label_text):
                logger.info("timeline static chart skipped: no installed font covers CJK labels")
                return None
            label_font = _mpl_font_for_text(label_text)

            import datetime as _dt
            import matplotlib.dates as _mdates

            key_columns = 2 if len(label_plan) > 6 else 1
            key_rows = max(1, math.ceil(len(label_plan) / key_columns))
            timeline_height = max(3.2, 0.9 * len(used) + 2.0)
            key_height = max(1.15, 0.36 * key_rows + 0.35)
            fig, (ax, key_ax) = plt.subplots(
                2, 1,
                figsize=(11, timeline_height + key_height),
                gridspec_kw={"height_ratios": [timeline_height, key_height]},
            )
            fig.patch.set_facecolor(_SURFACE)
            ax.set_facecolor(_SURFACE)
            key_ax.set_facecolor(_SURFACE)

            for category in used:
                y_base = used_index[category]
                category_events = [event for event in events if event["cat"] == category]
                xs = [event["dt"] for event in category_events]
                ys = [y_base + ((index % 3) - 1) * 0.12
                      for index in range(len(category_events))]
                color = _PALETTE[lane_order[category] % len(_PALETTE)]
                ax.axhline(y_base, color=_GRID, linewidth=1.0, zorder=0)
                ax.scatter(
                    xs,
                    ys,
                    s=62,
                    color=color,
                    edgecolor=_SURFACE,
                    linewidth=1.4,
                    zorder=3,
                )
                for event, x, y in zip(category_events, xs, ys, strict=True):
                    placement = label_plan.get((event["dt"], event["text"]))
                    if placement is None:
                        continue
                    ax.annotate(
                        str(placement["index"]),
                        xy=(x, y),
                        xytext=placement["offset"],
                        textcoords="offset points",
                        ha=placement["ha"],
                        va=placement["va"],
                        fontsize=7.5,
                        color=_INK,
                        fontweight="bold",
                        arrowprops={"arrowstyle": "-", "color": _AXIS, "linewidth": 0.7},
                        bbox={"boxstyle": "circle,pad=0.16", "fc": _SURFACE,
                              "ec": color, "linewidth": 1.0, "alpha": 0.96},
                        zorder=4,
                    )

            dates = [event["dt"] for event in events]
            if min(dates) == max(dates):
                ax.set_xlim(min(dates) - _dt.timedelta(days=15),
                            max(dates) + _dt.timedelta(days=15))
            else:
                span = max(dates) - min(dates)
                margin = max(_dt.timedelta(days=7), span * 0.04)
                ax.set_xlim(min(dates) - margin, max(dates) + margin)
            locator = _mdates.AutoDateLocator(minticks=3, maxticks=8)
            ax.xaxis.set_major_locator(locator)
            ax.xaxis.set_major_formatter(_mdates.ConciseDateFormatter(locator))
            ax.set_yticks(range(len(used)))
            ax.set_yticklabels(used, fontsize=9)
            ax.set_ylim(len(used) - 0.55, -0.55)
            ax.set_title("Event Timeline", fontsize=13, fontweight="bold",
                         loc="left", color=_INK)
            ax.grid(axis="x", color=_GRID, linestyle=":", linewidth=0.8)
            ax.tick_params(colors=_INK_2)
            for spine in ("top", "right", "left"):
                ax.spines[spine].set_visible(False)
            ax.spines["bottom"].set_color(_AXIS)

            key_ax.axis("off")
            key_ax.text(0.0, 1.02, "Key events", transform=key_ax.transAxes,
                        ha="left", va="bottom", fontsize=9, fontweight="bold", color=_INK)
            ordered_plan = sorted(
                label_plan.items(), key=lambda item: (item[0][0], item[0][1]),
            )
            for position, ((event_date, _event_text), placement) in enumerate(ordered_plan):
                column = position // key_rows
                row = position % key_rows
                x = 0.01 + column * (1.0 / key_columns)
                y = 0.92 - row * (0.80 / max(1, key_rows - 1))
                key_ax.text(
                    x, y,
                    f"{placement['index']:02d}  {event_date:%Y-%m-%d}  {placement['label']}",
                    transform=key_ax.transAxes,
                    ha="left", va="top", fontsize=8,
                    fontproperties=label_font,
                    color=_INK_2,
                )
            fig.tight_layout(h_pad=0.8)
            return self._save(fig, charts_dir, "timeline_lanes.png")
        except Exception as exc:  # noqa: BLE001
            logger.debug("build_timeline_lanes 失败（跳过该图）：%s", exc)
            return None
        finally:
            _close_matplotlib_figure(fig)

    def build_actor_network(self, actors: Any, charts_dir: str,
                            graph_priors: Any = None) -> Optional[str]:
        """Static PNG counterpart to :meth:`build_actor_network_html`.

        Actor aliases, relationship de-duplication, node ranking/capping, signed edge colors, and
        deterministic network layout mirror the Plotly builder.  The result is a compact directed
        network suitable for Markdown/PDF reports when no interactive renderer is available.
        """
        if not self._chart_ok():
            return None
        fig = None
        try:
            rels = (actors.get("relationships") or actors.get("relations")
                    or actors.get("edges")) if isinstance(actors, dict) else actors
            if not isinstance(rels, list) or not rels:
                return None
            actor_list = actors.get("actors") if isinstance(actors, dict) else None
            canon = _canonical_actor_map(actor_list)
            priors: Dict[str, float] = {}
            if isinstance(graph_priors, dict):
                for key, value in graph_priors.items():
                    numeric = _to_float(value)
                    if numeric is not None and str(key).strip():
                        priors[_norm_key(key)] = numeric

            seen_edges: set = set()
            edges: List[Tuple[str, str, str, str]] = []
            node_order: List[str] = []
            degree: Dict[str, int] = {}
            for relation in rels:
                if not isinstance(relation, dict):
                    continue
                source = _canonicalize(
                    str(relation.get("source") or relation.get("from") or "").strip(), canon)
                target = _canonicalize(
                    str(relation.get("target") or relation.get("to") or "").strip(), canon)
                if not source or not target or source == target:
                    continue
                relation_type = str(
                    relation.get("type") or relation.get("relation")
                    or relation.get("rel") or "REL"
                ).strip().upper()
                edge_key = (source, target, relation_type)
                if edge_key in seen_edges:
                    continue
                seen_edges.add(edge_key)
                edges.append((source, target, relation_type, _sign_of(relation) or "±"))
                for node in (source, target):
                    if node not in degree:
                        degree[node] = 0
                        node_order.append(node)
                    degree[node] += 1
            if not edges:
                return None

            max_nodes = int(_cfg("REPORT_VIZ_NETWORK_MAX_NODES", 60) or 60)
            first_seen = {node: index for index, node in enumerate(node_order)}
            ranked = sorted(
                node_order,
                key=lambda node: (
                    -priors.get(_norm_key(node), 0.0),
                    -degree.get(node, 0),
                    first_seen[node],
                ),
            )
            kept = set(ranked[:max(2, max_nodes)])
            edges = [edge for edge in edges if edge[0] in kept and edge[1] in kept]
            nodes = [node for node in node_order if node in kept]
            if not edges or len(nodes) < 2:
                return None

            positions = _network_layout(nodes, edges)
            metadata: Dict[str, Dict[str, Any]] = {}
            if isinstance(actor_list, list):
                for actor in actor_list:
                    if isinstance(actor, dict) and str(actor.get("name") or "").strip():
                        metadata[_norm_key(actor["name"])] = actor

            has_prior = any(_norm_key(node) in priors for node in nodes)
            weights = {
                node: (priors.get(_norm_key(node), 0.0)
                       if has_prior else float(degree.get(node, 1)))
                for node in nodes
            }
            weight_max = max(weights.values()) or 1.0
            role_classes = sorted({
                str((metadata.get(_norm_key(node)) or {}).get("role_class") or "other")
                for node in nodes
            })
            class_color = {
                role_class: _PALETTE[index % len(_PALETTE)]
                for index, role_class in enumerate(role_classes)
            }
            label_plan = _actor_label_plan(nodes, positions, weights)
            label_text = " ".join(
                [entry["label"] for entry in label_plan.values()] + role_classes
            )
            if not _mpl_labels_supported(label_text):
                logger.info("actor-network static chart skipped: no installed font covers CJK labels")
                return None
            label_font = _mpl_font_for_text(label_text)

            from matplotlib.lines import Line2D
            from matplotlib.patches import FancyArrowPatch

            fig, ax = plt.subplots(figsize=(10.5, 7.5))
            fig.patch.set_facecolor(_SURFACE)
            ax.set_facecolor(_SURFACE)
            edge_colors = {"+": _COLOR_POS, "−": _COLOR_NEG, "±": _COLOR_NEU}
            for index, (source, target, _relation_type, sign) in enumerate(edges):
                arrow = FancyArrowPatch(
                    positions[source],
                    positions[target],
                    arrowstyle="-|>",
                    mutation_scale=9,
                    linewidth=1.15,
                    color=edge_colors.get(sign, _COLOR_NEU),
                    alpha=0.48,
                    shrinkA=14,
                    shrinkB=14,
                    connectionstyle=f"arc3,rad={((index % 3) - 1) * 0.035:.3f}",
                    zorder=1,
                )
                ax.add_patch(arrow)

            for role_class in role_classes:
                class_nodes = [
                    node for node in nodes
                    if str((metadata.get(_norm_key(node)) or {}).get("role_class") or "other")
                    == role_class
                ]
                ax.scatter(
                    [positions[node][0] for node in class_nodes],
                    [positions[node][1] for node in class_nodes],
                    s=[260 + 900 * (weights[node] / weight_max) for node in class_nodes],
                    color=class_color[role_class],
                    edgecolor=_SURFACE,
                    linewidth=2.0,
                    alpha=0.92,
                    zorder=3,
                )

            for node in nodes:
                placement = label_plan.get(node)
                if placement is None:
                    continue
                ax.annotate(
                    placement["label"],
                    xy=positions[node],
                    xytext=placement["xytext"],
                    textcoords="data",
                    ha="center",
                    va="center",
                    fontsize=8,
                    fontproperties=label_font,
                    color=_INK,
                    fontweight="bold",
                    arrowprops={"arrowstyle": "-", "color": _AXIS, "linewidth": 0.65,
                                "shrinkA": 2, "shrinkB": 8},
                    bbox={"boxstyle": "round,pad=0.18", "fc": _SURFACE,
                          "ec": "none", "alpha": 0.88},
                    zorder=4,
                )

            node_handles = [
                Line2D([0], [0], marker="o", linestyle="", label=role_class,
                       markerfacecolor=class_color[role_class], markeredgecolor=_SURFACE,
                       markersize=8)
                for role_class in role_classes
            ]
            edge_handles = [
                Line2D([0], [0], color=_COLOR_POS, linewidth=2, label="supportive (+)"),
                Line2D([0], [0], color=_COLOR_NEG, linewidth=2, label="adversarial (−)"),
                Line2D([0], [0], color=_COLOR_NEU, linewidth=2, label="neutral (±)"),
            ]
            ax.legend(handles=node_handles + edge_handles, loc="upper center",
                      bbox_to_anchor=(0.5, -0.02), ncol=min(4, len(node_handles + edge_handles)),
                      frameon=False, fontsize=8,
                      prop=_font_at_size(label_font, 8) if label_font else None)
            ax.set_title("Actor Relationship Network", fontsize=13, fontweight="bold",
                         loc="left", color=_INK)
            bounds = [entry["bbox"] for entry in label_plan.values()]
            xs = [positions[node][0] for node in nodes]
            ys = [positions[node][1] for node in nodes]
            if bounds:
                xs.extend(value for box in bounds for value in (box[0], box[2]))
                ys.extend(value for box in bounds for value in (box[1], box[3]))
            x_span = max(max(xs) - min(xs), 1.0)
            y_span = max(max(ys) - min(ys), 1.0)
            ax.set_xlim(min(xs) - x_span * 0.08, max(xs) + x_span * 0.08)
            ax.set_ylim(min(ys) - y_span * 0.10, max(ys) + y_span * 0.08)
            ax.set_aspect("equal", adjustable="box")
            ax.axis("off")
            fig.tight_layout()
            return self._save(fig, charts_dir, "actor_network.png")
        except Exception as exc:  # noqa: BLE001
            logger.debug("build_actor_network 失败（跳过该图）：%s", exc)
            return None
        finally:
            _close_matplotlib_figure(fig)

    def build_comparison_bars(self, comparison: Any, charts_dir: str) -> Optional[str]:
        """(4) 基线-情景分组柱（comparison.json 的 dimensions[]，仅取数值可解析的维度）。

        每个维度取 baseline/scenario 两根柱；无法解析为数字的维度跳过。无数值维度 → None。"""
        if not self._chart_ok():
            return None
        fig = None
        try:
            dims = comparison.get("dimensions") if isinstance(comparison, dict) else comparison
            if not isinstance(dims, list) or not dims:
                return None
            labels: List[str] = []
            base_vals: List[float] = []
            scen_vals: List[float] = []
            for d in dims:
                if not isinstance(d, dict):
                    continue
                b = _to_float(d.get("baseline"))
                s = _to_float(d.get("scenario"))
                if b is None or s is None:
                    continue
                labels.append(_mpl_text(d.get("name") or d.get("dimension"),
                                        fallback=f"Dim {len(labels) + 1}", max_len=30))
                base_vals.append(b)
                scen_vals.append(s)
            if not labels:
                return None
            label_text = " ".join(labels)
            if not _mpl_labels_supported(label_text):
                logger.info("comparison static chart skipped: no installed font covers CJK labels")
                return None
            label_font = _mpl_font_for_text(label_text)
            import numpy as _np  # matplotlib 依赖 numpy，一定可用
            x = _np.arange(len(labels))
            w = 0.38
            fig, ax = plt.subplots(figsize=(max(6, 1.4 * len(labels) + 2), 5))
            ax.bar(x - w / 2, base_vals, w, label="Baseline", color="#9aa5b1")
            ax.bar(x + w / 2, scen_vals, w, label="Scenario", color="#3b6fb0")
            ax.set_xticks(x)
            ax.set_xticklabels(labels, fontsize=9, rotation=20, ha="right",
                               fontproperties=label_font)
            ax.set_ylabel("Value", fontsize=10)
            ax.set_title("Baseline vs Scenario (comparison)", fontsize=12, fontweight="bold")
            ax.legend(fontsize=9)
            ax.grid(axis="y", linestyle=":", alpha=0.4)
            fig.tight_layout()
            return self._save(fig, charts_dir, "comparison_bars.png")
        except Exception:  # noqa: BLE001
            return None
        finally:
            _close_matplotlib_figure(fig)

    def build_calibration_curve(self, calibration: Any, charts_dir: str) -> Optional[str]:
        """(5) 校准曲线（来自 forecast-ledger 的 calibration_report 统计，若存在）。

        入参兼容 {bins:[{mean_predicted,observed/hit_rate,...}]} 或直接 bins 列表。
        画 mean_predicted vs observed 折线 + 对角线（完美校准）。有效点 <1 → None。"""
        if not self._chart_ok():
            return None
        fig = None
        try:
            bins = calibration.get("bins") if isinstance(calibration, dict) else calibration
            if not isinstance(bins, list) or not bins:
                return None
            xs: List[float] = []
            ys: List[float] = []
            for b in bins:
                if not isinstance(b, dict):
                    continue
                mp = _first_float(b, ("mean_predicted", "mean_pred", "pred"))
                ob = _first_float(b, ("observed", "hit_rate", "smoothed_hit_rate", "empirical"))
                if mp is None or ob is None:
                    continue
                xs.append(mp)
                ys.append(ob)
            if not xs:
                return None
            order = sorted(range(len(xs)), key=lambda i: xs[i])
            xs = [xs[i] for i in order]
            ys = [ys[i] for i in order]
            fig, ax = plt.subplots(figsize=(6, 6))
            ax.plot([0, 1], [0, 1], color="#9aa5b1", linestyle="--", label="Perfect calibration")
            ax.plot(xs, ys, marker="o", color="#3b6fb0", linewidth=1.8, label="Observed")
            ax.set_xlabel("Mean predicted probability", fontsize=10)
            ax.set_ylabel("Observed frequency", fontsize=10)
            ax.set_xlim(0, 1)
            ax.set_ylim(0, 1)
            ax.set_aspect("equal", adjustable="box")
            ax.set_title("Calibration Curve", fontsize=12, fontweight="bold")
            ax.legend(loc="upper left", fontsize=9)
            ax.grid(linestyle=":", alpha=0.4)
            fig.tight_layout()
            return self._save(fig, charts_dir, "calibration_curve.png")
        except Exception:  # noqa: BLE001
            return None
        finally:
            _close_matplotlib_figure(fig)

    def render_market_price_history(self, price_history: Any, anchors: Any,
                                    out_dir: str) -> List[str]:
        """(6) PM-6：每个带市场锚点的二元预测 → market-implied P(yes) 历史价折线图。

        对每个「有市场锚点且 market_id 命中 price_history」的二元预测，画一张：市场隐含
        P(yes) 随时间的折线 + 模型概率作带标签的水平参考线 + 分歧（model − market）标注。
        用途：报告 Part-1「Market Cross-Check」区（placement_hint='binary_forecasts'）。

        入参：
          price_history  {market_id: [{t,p}, ...]}（bridge/report 落盘；t 为 unix 秒，p∈[0,1]）；
          anchors        锚点列表——每项可为二元预测（含 market_anchor 子 dict）或已抽平的
                         {market_id, probability/model_prob, id/statement/label, divergence}。
                         仅保留 market_id 命中 price_history 且有效历史点 ≥2 的锚点，按原序去重。
        分组：锚点数 >6 时每图最多 2 个子图（压缩图数量）；否则一锚一图。锚点总数超
              REPORT_VIZ_MAX_NODES 时确定性截断（保留首现）。
        返回：相对 report_dir 的路径列表 ['charts/market_price_history_1.png', ...]；
        matplotlib 缺失/关闭、无 price_history、无可用锚点 → []（never raises）。"""
        if not self._chart_ok():
            return []
        fig = None
        try:
            if not isinstance(price_history, dict) or not price_history:
                return []
            norm = _normalize_price_anchors(anchors, price_history)
            if not norm:
                return []
            cap = int(_cfg("REPORT_VIZ_MAX_NODES", 40) or 40)
            if cap > 0 and len(norm) > cap:
                norm = norm[:cap]  # 病态超长输入的确定性上限（保留首现锚点）
            label_text = " ".join(str(anchor.get("label") or "") for anchor in norm)
            if not _mpl_labels_supported(label_text):
                logger.info("price-history static chart skipped: no installed font covers CJK labels")
                return []
            label_font = _mpl_font_for_text(label_text)
            import matplotlib.dates as _mdates  # 惰性导入（matplotlib 已确认可用）
            per_fig = 2 if len(norm) > 6 else 1  # >6 锚点 → 每图 2 子图，降低图数量
            groups = [norm[i:i + per_fig] for i in range(0, len(norm), per_fig)]
            paths: List[str] = []
            for gi, group in enumerate(groups, 1):
                n = len(group)
                fig, axes = plt.subplots(n, 1, figsize=(9, max(3.2, 3.0 * n)),
                                         squeeze=False)
                for ai, a in enumerate(group):
                    ax = axes[ai][0]
                    xs = [t for t, _ in a["series"]]
                    ys = [p for _, p in a["series"]]
                    ax.plot(xs, ys, color="#c0603a", linewidth=1.8, marker="o",
                            markersize=3, zorder=2, label="Market implied P(yes)")
                    mp = a["model_p"]
                    if mp is not None:
                        ax.axhline(mp, color="#3b6fb0", linestyle="--", linewidth=1.6,
                                   zorder=1, label=f"Model P(yes) = {mp * 100:.0f}%")
                    div = a["divergence"]
                    if div is not None:
                        ax.annotate(f"Divergence (model − market): {div * 100:+.0f} pp",
                                    xy=(0.02, 0.04), xycoords="axes fraction",
                                    fontsize=8, color="#2b2b2b",
                                    bbox={"boxstyle": "round,pad=0.3", "fc": "#f2f2f2",
                                          "ec": "#9aa5b1", "alpha": 0.85})
                    ax.set_ylim(0, 1)
                    ax.set_ylabel("P(yes)", fontsize=9)
                    ax.set_title(a["label"], fontsize=11, fontweight="bold",
                                 fontproperties=label_font)
                    ax.xaxis.set_major_formatter(_mdates.DateFormatter("%Y-%m-%d"))
                    ax.legend(loc="best", fontsize=8, framealpha=0.85)
                    ax.grid(linestyle=":", alpha=0.4)
                axes[-1][0].set_xlabel("Date", fontsize=10)
                fig.autofmt_xdate()
                fig.tight_layout()
                rel = self._save(fig, out_dir, f"market_price_history_{gi}.png")
                if rel:
                    paths.append(rel)
            return paths
        except Exception:  # noqa: BLE001
            return []
        finally:
            _close_matplotlib_figure(fig)

    # ============================ (C) plotly 交互式 HTML 族 ============================
    # ITEM-16：全部为实例方法，入参普通 dict/list + 输出目录，成功落盘 HTML 返回相对路径，
    # 否则 None（或 []）。plotly 缺失/关闭 → 直接跳过（build_all 会整族略过）。每个 HTML 用
    # include_plotlyjs='directory' 引用同目录共享 plotly.min.js（一份 ~4.9MB 全报告共享，
    # 不依赖 CDN/外链；见 _ensure_plotly_bundle，写不出 bundle 时回退 inline）。数据抽取逻辑与
    # 对应 matplotlib 构建器逐字对齐（复用 _to_float / _first_float / _normalize_price_anchors），
    # 保证同一工件下 PNG 与 HTML 描绘同一份数据。

    def _interactive_ok(self) -> bool:
        """ITEM-16 交互式 HTML 图表族开关（默认开）。plotly 缺失时恒为 False（整族跳过）。"""
        return PLOTLY_AVAILABLE and bool(_cfg("REPORT_VIZ_INTERACTIVE", True))

    def _png_export_ok(self) -> bool:
        """WAVE9：kaleido 静态 PNG 导出开关（默认开）。kaleido 缺失或运行期已熔断 → False。"""
        return (KALEIDO_AVAILABLE and _KALEIDO_RUNTIME_OK
                and bool(_cfg("REPORT_VIZ_PNG_EXPORT", True)))

    _PLOTLY_BUNDLE_NAME = "plotly.min.js"

    def _ensure_plotly_bundle(self, charts_dir: str) -> bool:
        """确保 charts_dir 下存在共享 plotly.min.js（幂等、原子写）。成功/已存在 → True。

        此前每份图表 HTML 都内联整份 plotly.js（4.86MB/图、~40MB/报告，累计 1.9GB）。
        改为整个 charts/ 目录共享一份 bundle，各 HTML 以相对路径引用（同目录，file://
        离线打开同样成立）。写入失败 → False（调用方回退 inline，离线自包含优先于体积）。"""
        bundle_path = os.path.join(charts_dir, self._PLOTLY_BUNDLE_NAME)
        if os.path.isfile(bundle_path):
            return True
        try:
            from plotly.offline import get_plotlyjs
            tmp = f"{bundle_path}.{os.getpid()}.tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                f.write(get_plotlyjs())
            os.replace(tmp, bundle_path)
            return True
        except Exception as exc:  # noqa: BLE001 - bundle 落盘失败只降级，不阻断图表
            logger.debug("共享 plotly.min.js 落盘失败（本图回退 inline）：%s", exc)
            return False

    @staticmethod
    def _inject_plotly_load_guard(html: str) -> str:
        """directory 模式的优雅降级：若共享 plotly.min.js 未能随 HTML 一起送达（例如
        经限制外链脚本的服务端点打开），在页顶插入一条可操作的提示，而不是留一页空白。
        内联脚本本身不依赖任何外部资源。"""
        guard = (
            '<script>window.addEventListener("DOMContentLoaded",function(){'
            'if(!window.Plotly){var d=document.createElement("div");'
            'd.style.cssText="margin:16px;padding:12px 16px;border:1px solid #d03b3b;'
            'border-radius:6px;font-family:system-ui,sans-serif;font-size:14px;'
            'color:#0b0b0b;background:#fdf1f1";'
            'd.textContent="Interactive chart could not load the shared plotly.min.js '
            'that lives next to this file. Open this chart from the report\'s charts/ '
            'folder (which contains plotly.min.js).";'
            'document.body.insertBefore(d,document.body.firstChild);}});</script>'
        )
        if "</body>" in html:
            return html.replace("</body>", guard + "</body>", 1)
        return html + guard

    def _save_html(self, fig, charts_dir: str, filename: str) -> Optional[str]:
        """把 plotly figure 存成 HTML 并返回相对 report_dir 的路径 'charts/<file>'。

        include_plotlyjs='directory'：HTML 仅 ~20-60KB，引用同目录共享 plotly.min.js
        （见 _ensure_plotly_bundle；此前逐图内联 4.86MB）。charts/ 目录整体分发（文件
        系统 / 打包下载）时相对引用离线成立。共享包写不出来 → 回退 inline（仍离线
        自包含）。原子写（.tmp→replace），失败 → None。"""
        try:
            os.makedirs(charts_dir, exist_ok=True)
            out_path = os.path.join(charts_dir, filename)
            # REPORT_VIZ_PLOTLYJS_INLINE（默认关）：一键回退旧的逐图内联行为——经只允许
            # 内联脚本的沙箱端点（/api/report/*/charts、/api/research/*/artifact）分发交互
            # 图时的运维逃生阀，代价是恢复每图 ~4.9MB 的体积。
            force_inline = bool(_cfg("REPORT_VIZ_PLOTLYJS_INLINE", False))
            include = ("inline" if force_inline or not self._ensure_plotly_bundle(charts_dir)
                       else "directory")
            html = fig.to_html(include_plotlyjs=include, full_html=True,
                               config={"displayModeBar": True, "responsive": True})
            html = _finalize_plotly_html(html, _plotly_document_title(fig, filename))
            if include == "directory":
                html = self._inject_plotly_load_guard(html)
            tmp = out_path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                f.write(html)
            os.replace(tmp, out_path)
            return os.path.join("charts", filename)
        except Exception as exc:  # noqa: BLE001 - 落盘失败不阻断其余可视化
            logger.debug("HTML 图落盘失败 %s：%s", filename, exc)
            return None

    def _save_png(self, fig, path: str) -> bool:
        """WAVE9：单张 plotly figure → 静态 PNG（kaleido，scale=2、宽 1200px，高取 fig 布局高）。
        成功 → True；任何失败 → False 并置进程级熔断标志（后续图不再逐个等待超时）。"""
        global _KALEIDO_RUNTIME_OK
        if not self._png_export_ok():
            return False
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            height = None
            try:
                height = int(fig.layout.height) if fig.layout.height else None
            except Exception:  # noqa: BLE001
                height = None
            fig.write_image(path, scale=2, width=1200, height=height)
            return os.path.exists(path)
        except Exception as exc:  # noqa: BLE001
            _KALEIDO_RUNTIME_OK = False
            self._kaleido_failed = True
            logger.warning("kaleido PNG 导出失败（本进程熔断，回退 matplotlib/仅 HTML）：%s", exc)
            return False

    def _queue_png(self, fig, charts_dir: str, stem: str, item_id: str) -> None:
        """WAVE9：登记一张待导出 PNG。build_all 批处理模式下排队（末尾一次 flush，摊销 Chromium
        启动），独立调用构建器时即时渲染。成功的 item_id → 相对路径记入 self._png_done。"""
        if not self._png_export_ok():
            return
        abs_path = os.path.join(charts_dir, f"{stem}.png")
        rel_path = os.path.join("charts", f"{stem}.png")
        if self._batch_mode:
            self._png_jobs.append((fig, abs_path, rel_path, item_id))
        elif self._save_png(fig, abs_path):
            self._png_done[item_id] = rel_path

    def _flush_png_jobs(self) -> None:
        """WAVE9：批量导出排队中的 PNG。优先 plotly.io.write_images（单次 Chromium 会话渲染全部
        图），不可用/整批失败时回退逐张 write_image；单张失败只丢那一张。"""
        global _KALEIDO_RUNTIME_OK
        jobs, self._png_jobs = self._png_jobs, []
        if not jobs or not self._png_export_ok():
            return
        try:
            import plotly.io as pio
            figs = [j[0] for j in jobs]
            paths = [j[1] for j in jobs]
            heights = []
            for f in figs:
                try:
                    heights.append(int(f.layout.height) if f.layout.height else 600)
                except Exception:  # noqa: BLE001
                    heights.append(600)
            pio.write_images(figs, paths, scale=2, width=1200, height=heights)
            for _, abs_path, rel_path, item_id in jobs:
                if os.path.exists(abs_path):
                    self._png_done[item_id] = rel_path
            return
        except Exception as exc:  # noqa: BLE001
            logger.info("kaleido 批量 PNG 导出不可用（%s），回退逐张导出", exc)
        # 逐张回退（_save_png 内部有熔断：首张失败后整体停止尝试）。
        for fig, abs_path, rel_path, item_id in jobs:
            if not self._png_export_ok():
                break
            if self._save_png(fig, abs_path):
                self._png_done[item_id] = rel_path

    def _write_density_fallback(self, item_id: str, stem: str,
                                lines: List[str], charts_dir: str) -> None:
        """VIZ-GAP2：低于密度门的图槽降级——落一张紧凑 markdown 表（charts/<stem>_table.md，
        原子写），并登记 {"reason": "below_density_threshold", "fallback_path": ...} 跳过
        说明供 build_all 写进 viz_manifest.json 的 skipped[]（schema v2 允许附加字符串键）。
        表落盘失败只丢 fallback_path，跳过原因仍如实记录（degrade-safe）。"""
        note = {"reason": "below_density_threshold"}
        try:
            os.makedirs(charts_dir, exist_ok=True)
            path = os.path.join(charts_dir, f"{stem}_table.md")
            tmp = path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                f.write("\n".join(lines) + "\n")
            os.replace(tmp, path)
            note["fallback_path"] = os.path.join("charts", f"{stem}_table.md")
        except Exception as exc:  # noqa: BLE001 - 表格是降级产物，失败不阻断
            logger.debug("密度降级表落盘失败 %s：%s", stem, exc)
        self._skip_notes[item_id] = note

    def _save_pair(self, fig, charts_dir: str, stem: str,
                   item_id: Optional[str] = None) -> Optional[str]:
        """WAVE9：HTML+PNG 成对落盘——HTML 即时写，PNG 排队/即时导出（见 _queue_png）。
        返回 HTML 相对路径（保持既有构建器签名不变）；PNG 路径经 self._png_done[item_id] 查询。"""
        rel = self._save_html(fig, charts_dir, f"{stem}.html")
        if rel:
            self._queue_png(fig, charts_dir, stem, item_id or stem)
        return rel

    def build_scenario_bars_html(self, forecast: Any, charts_dir: str,
                                 ensemble: Any = None) -> Optional[str]:
        """(C1) 情景概率横向柱 + 来源可辨误差棒（HTML+PNG 对）。

        Ensemble min/max 与 canonical p_low/p_high 分别使用独立图例、颜色、标记和
        hover 文案，避免把模型声明区间误标为 ensemble spread。无情景 → None。
        """
        if not self._interactive_ok():
            return None
        try:
            rows = _extract_scenario_rows(forecast, ensemble)
            if not rows:
                return None
            names = [r["name"] for r in rows]
            probs = [r["p"] for r in rows]
            hover = []
            for r in rows:
                parts = [f"<b>{_wrap_hover(r['name'], 48)}</b>", f"P = {r['p']:.1%}"]
                if (r["lo"] is not None and r["hi"] is not None
                        and r["hi"] > r["lo"]):
                    label = str(r.get("interval_label") or "Unspecified interval")
                    parts.append(f"{label}: {r['lo']:.1%} – {r['hi']:.1%}")
                if r.get("stdev") is not None:
                    parts.append(f"ensemble stdev {r['stdev']:.3f}")
                if r.get("support") is not None:
                    parts.append(f"support ratio {r['support']:.0%}")
                hover.append("<br>".join(parts))
            fig = go.Figure(go.Bar(
                x=probs, y=names, orientation="h", marker_color=_COLOR_MODEL,
                hovertext=hover, hoverinfo="text",
                name="Scenario probability", showlegend=False,
            ))
            # 数值标签放在区间上界之外（有区间时）——柱端标签会被误差棒横穿（PNG 取证）。
            x_max = max(1.0, max(probs) * 1.2)
            for row in rows:
                has_interval = (row["lo"] is not None and row["hi"] is not None
                                and row["hi"] > row["lo"])
                edge = row["hi"] if has_interval else row["p"]
                fig.add_annotation(
                    x=min(edge + 0.015 * x_max, x_max), y=row["name"],
                    text=f"{row['p'] * 100:.0f}%", showarrow=False,
                    xanchor="left", yanchor="middle",
                    font={"size": 11, "color": _INK_2, "family": _VIZ_FONT},
                )
            for source in _SCENARIO_INTERVAL_ORDER:
                source_rows = [
                    row for row in rows
                    if row.get("interval_source") == source
                    and row["lo"] is not None and row["hi"] is not None
                    and row["hi"] > row["lo"]
                ]
                if not source_rows:
                    continue
                style = _SCENARIO_INTERVAL_STYLES[source]
                fig.add_trace(go.Scatter(
                    x=[row["p"] for row in source_rows],
                    y=[row["name"] for row in source_rows],
                    mode="markers",
                    marker={
                        "color": style["color"],
                        "size": 6,
                        "symbol": style["plotly_symbol"],
                    },
                    error_x={
                        "type": "data",
                        "symmetric": False,
                        "array": [row["hi"] - row["p"] for row in source_rows],
                        "arrayminus": [row["p"] - row["lo"] for row in source_rows],
                        "color": style["color"],
                        "thickness": 1.4,
                        "width": style["capsize"],
                    },
                    customdata=[[row["lo"], row["hi"]] for row in source_rows],
                    name=style["label"],
                    hovertemplate=(
                        "<b>%{y}</b><br>" + style["label"]
                        + ": %{customdata[0]:.1%} – %{customdata[1]:.1%}"
                        + "<extra></extra>"
                    ),
                ))
            # VIZ-GAP1(b)：标题下挂一行区间溯源副标题；裸点估计明说而非沉默呈现为确定性。
            subtitle = _scenario_interval_subtitle(rows, forecast)
            title = (f"{_scenario_interval_title(rows)}"
                     f"<br><sup>{subtitle}</sup>")
            _apply_layout(fig, title, height=max(340, 42 * len(names) + 160))
            fig.update_layout(
                xaxis_title="Probability",
                xaxis=dict(range=[0, max(1.0, max(probs) * 1.2)], tickformat=".0%"),
                yaxis=dict(autorange="reversed"),  # 概率最高的情景显示在顶部
                margin={"l": 10, "r": 24, "t": 74, "b": 46},  # 两行标题需要更高的顶边距
            )
            return self._save_pair(fig, charts_dir, "scenario_probabilities",
                                   "scenario_probabilities")
        except Exception as exc:  # noqa: BLE001
            logger.debug("build_scenario_bars_html 失败（跳过该图）：%s", exc)
            return None

    def build_model_vs_market_html(self, forecast: Any, charts_dir: str) -> Optional[str]:
        """(C2) 模型 vs 市场哑铃图的交互式 HTML（对应 build_model_vs_market）。

        每条带 market_anchor 的二元预测连模型概率与市场隐含概率两点。无可比条目 → None。"""
        if not self._interactive_ok():
            return None
        try:
            bfs = forecast.get("binary_forecasts") if isinstance(forecast, dict) else forecast
            if not isinstance(bfs, list) or not bfs:
                return None
            labels: List[str] = []
            model_p: List[float] = []
            market_p: List[float] = []
            statements: List[str] = []
            for bf in bfs:
                if not isinstance(bf, dict):
                    continue
                anchor = bf.get("market_anchor")
                if not isinstance(anchor, dict):
                    continue
                mp = _to_float(bf.get("probability"))
                kp = _to_float(anchor.get("implied_yes_prob"))
                if kp is None:
                    kp = _to_float(anchor.get("implied_prob"))
                if mp is None or kp is None:
                    continue
                lab = _html_text(bf.get("id") or bf.get("statement") or bf.get("market_id")
                                 or anchor.get("market_id"), fallback=f"F{len(labels) + 1}", max_len=46)
                labels.append(lab)
                model_p.append(mp)
                market_p.append(kp)
                statements.append(_html_text(
                    bf.get("statement") or bf.get("id") or anchor.get("market_id"),
                    fallback=lab, max_len=110))
            if not labels:
                return None
            # VIZ-GAP2：<3 条锚定命题撑不起整页哑铃图（单锚点在二元点阵图里已有成对
            # 菱形）——降级为紧凑 markdown 表并登记 below_density_threshold。
            if len(labels) < _MODEL_VS_MARKET_MIN_ANCHORED:
                table = [
                    "# Model vs Market (binary forecasts)",
                    "",
                    (f"Only {len(labels)} market-anchored proposition(s) — below the "
                     f"{_MODEL_VS_MARKET_MIN_ANCHORED}-row chart threshold; the market "
                     "anchor also appears as a paired diamond on the binary dotplot."),
                    "",
                    "| Proposition | Model P(yes) | Market implied | Δ (model − market) |",
                    "| --- | --- | --- | --- |",
                ]
                for stmt, mp, kp in zip(statements, model_p, market_p, strict=True):
                    table.append(
                        f"| {_md_cell(stmt, max_len=110)} | {mp:.1%} | {kp:.1%} "
                        f"| {(mp - kp) * 100:+.1f}pp |")
                self._write_density_fallback(
                    "model_vs_market", "model_vs_market", table, charts_dir)
                return None
            self._skip_notes.pop("model_vs_market", None)
            fig = go.Figure()
            # 先画连线段（哑铃杆），每条一 trace 但不进图例。
            for lab, mp, kp in zip(labels, model_p, market_p):
                fig.add_trace(go.Scatter(
                    x=[kp, mp], y=[lab, lab], mode="lines",
                    line=dict(color=_COLOR_NEU, width=2),
                    showlegend=False, hoverinfo="skip",
                ))
            fig.add_trace(go.Scatter(
                x=market_p, y=labels, mode="markers", name="Market implied",
                marker=dict(color=_COLOR_MARKET, size=11,
                            line=dict(color=_SURFACE, width=2)),
                hovertemplate="%{y} — market: %{x:.1%}<extra></extra>",
            ))
            fig.add_trace(go.Scatter(
                x=model_p, y=labels, mode="markers", name="Model",
                marker=dict(color=_COLOR_MODEL, size=11,
                            line=dict(color=_SURFACE, width=2)),
                hovertemplate="%{y} — model: %{x:.1%}<extra></extra>",
            ))
            _apply_layout(
                fig,
                ("Model vs Market (binary forecasts)"
                 f"<br><sup>{len(labels)} market-anchored propositions — "
                 "point estimates vs market-implied P(yes)</sup>"),
                height=max(320, 40 * len(labels) + 170))
            fig.update_layout(
                xaxis_title="P(yes)", xaxis=dict(range=[0, 1], tickformat=".0%"),
                yaxis=dict(autorange="reversed"),
                legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
                margin={"l": 10, "r": 24, "t": 74, "b": 46},
            )
            return self._save_pair(fig, charts_dir, "model_vs_market", "model_vs_market")
        except Exception as exc:  # noqa: BLE001
            logger.debug("build_model_vs_market_html 失败（跳过该图）：%s", exc)
            return None

    def build_worldstate_area_html(self, trajectory: Any, charts_dir: str) -> Optional[str]:
        """(C3) 结果世界态堆叠面积的交互式 HTML（对应 build_worldstate_area）。

        兼容 {trajectory:[{round,shares:{name:share}}]} 或直接列表；<2 时间点 → None。
        CAL-TEMPORAL：所有行都带可解析的 period_end/as_of（schema v3）→ 横轴用日历日期
        （"Date"）；否则维持旧的 "Forecast update step" 轮次横轴（hours 模式字节不变）。"""
        if not self._interactive_ok():
            return None
        try:
            rows = trajectory.get("trajectory") if isinstance(trajectory, dict) else trajectory
            if not isinstance(rows, list) or len(rows) < 2:
                return None
            names: List[str] = []
            snaps: List[Tuple[float, Dict[str, float]]] = []
            dates: List[Any] = []  # CAL-TEMPORAL：与 snaps 一一对应的日历日期（可含 None）
            for i, r in enumerate(rows):
                if not isinstance(r, dict):
                    continue
                shares = r.get("shares")
                if not isinstance(shares, dict) or not shares:
                    continue
                x = _to_float(r.get("round"))
                if x is None:
                    x = float(i)
                clean: Dict[str, float] = {}
                for k, v in shares.items():
                    fv = _to_float(v)
                    if fv is None:
                        continue
                    clean[str(k)] = fv
                    if str(k) not in names:
                        names.append(str(k))
                if clean:
                    snaps.append((x, clean))
                    dates.append(_trajectory_row_date(r))
            if len(snaps) < 2 or not names:
                return None
            use_dates = bool(dates) and all(d is not None for d in dates)
            if use_dates:
                xs: List[Any] = [d.isoformat() for d in dates]  # plotly 自动识别 ISO 日期轴
                x_title = "Date"
                hover_x = "%{x|%Y-%m-%d}"
            else:
                xs = [x for x, _ in snaps]
                x_title = "Forecast update step"
                hover_x = "Forecast update step %{x}"
            fig = go.Figure()
            for i, nm in enumerate(names):
                ser = [snap.get(nm, 0.0) for _, snap in snaps]
                fig.add_trace(go.Scatter(
                    x=xs, y=ser, mode="lines", name=_html_text(nm, fallback=f"Series {i + 1}", max_len=40),
                    stackgroup="one",  # 堆叠面积
                    line=dict(width=1),
                    hovertemplate=hover_x + ": %{y:.2f}<extra>"
                                  + _html_text(nm, max_len=40) + "</extra>",
                ))
            _apply_layout(fig, "Forecast Outcome-Share Trajectory", height=460)
            fig.update_layout(xaxis_title=x_title, yaxis_title="Outcome share")
            return self._save_pair(fig, charts_dir, "worldstate_trajectory",
                                   "worldstate_trajectory")
        except Exception as exc:  # noqa: BLE001
            logger.debug("build_worldstate_area_html 失败（跳过该图）：%s", exc)
            return None

    def render_market_price_history_html(self, price_history: Any, anchors: Any,
                                         out_dir: str) -> List[str]:
        """(C4) 市场价格历史折线的交互式 HTML（对应 render_market_price_history）。

        每个「有市场锚点且 market_id 命中 price_history」的二元预测 → 一张自包含 HTML：市场隐含
        P(yes) 随时间折线 + 模型概率水平参考线 + 分歧标注（交互 hover）。锚点总数超
        REPORT_VIZ_MAX_NODES 确定性截断（保留首现）。返回相对 report_dir 路径列表；
        plotly 缺失/关闭、无 price_history、无可用锚点 → []（never raises）。"""
        if not self._interactive_ok():
            return []
        try:
            if not isinstance(price_history, dict) or not price_history:
                return []
            norm = _normalize_price_anchors(anchors, price_history)
            if not norm:
                return []
            cap = int(_cfg("REPORT_VIZ_MAX_NODES", 40) or 40)
            if cap > 0 and len(norm) > cap:
                norm = norm[:cap]  # 病态超长输入的确定性上限（保留首现锚点）
            paths: List[str] = []
            for gi, a in enumerate(norm, 1):
                xs = [t for t, _ in a["series"]]
                ys = [p for _, p in a["series"]]
                fig = go.Figure()
                fig.add_trace(go.Scatter(
                    x=xs, y=ys, mode="lines+markers", name="Market implied P(yes)",
                    line=dict(color=_COLOR_MARKET, width=2), marker=dict(size=5),
                    hovertemplate="%{x|%Y-%m-%d}: %{y:.1%}<extra></extra>",
                ))
                mp = a["model_p"]
                if mp is not None:
                    fig.add_hline(y=mp, line_dash="dash", line_color=_COLOR_MODEL,
                                  annotation_text=f"Model P(yes) = {mp * 100:.0f}%",
                                  annotation_position="top left")
                div = a["divergence"]
                if div is not None:
                    fig.add_annotation(
                        xref="paper", yref="paper", x=0.02, y=0.04, showarrow=False,
                        text=f"Divergence (model − market): {div * 100:+.0f} pp",
                        bgcolor="#f2f2f2", bordercolor=_COLOR_NEU, borderwidth=1,
                        font=dict(size=11, color=_INK_2),
                    )
                _apply_layout(fig, a["label"], height=420)
                fig.update_layout(
                    xaxis_title="Date", yaxis_title="P(yes)",
                    yaxis=dict(range=[0, 1], tickformat=".0%"),
                    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
                )
                stem = f"market_price_history_{gi}"
                rel = self._save_pair(fig, out_dir, stem, stem)
                if rel:
                    paths.append(rel)
            return paths
        except Exception as exc:  # noqa: BLE001
            logger.debug("render_market_price_history_html 失败（跳过该族）：%s", exc)
            return []

    # ==================== (D) WAVE9 新 plotly 构建器（HTML+PNG 对） ====================
    # 全部实例方法：入参普通 dict/list + 输出目录，成功返回 'charts/<name>.html' 相对路径，
    # 失败/无数据 → None（never raises，异常仅 debug 日志）。PNG 对经 _save_pair 排队导出。

    def build_binary_dotplot_html(self, forecast: Any, charts_dir: str) -> Optional[str]:
        """(D1) Binary P(yes) dot plot with optional *declared* confidence.

        Confidence is encoded only when every plotted proposition supplies a
        valid numeric value.  Distance from 50% is decisiveness, not confidence,
        and is never substituted.  Exact market anchors remain paired diamonds.
        """
        if not self._interactive_ok():
            return None
        try:
            bfs = forecast.get("binary_forecasts") if isinstance(forecast, dict) else forecast
            if not isinstance(bfs, list) or not bfs:
                return None
            rows: List[Dict[str, Any]] = []
            for bf in bfs:
                if not isinstance(bf, dict):
                    continue
                p = _first_float(bf, ("probability", "prob", "p"))
                if p is None:
                    continue
                conf = _first_float(bf, ("confidence",))
                if conf is None or not (0.0 <= conf <= 1.0):
                    conf = None
                anchor = bf.get("market_anchor")
                market = (_first_float(anchor, ("implied_yes_prob", "implied_prob"))
                          if isinstance(anchor, dict) else None)
                bid = _html_text(bf.get("id"), fallback=f"F{len(rows) + 1}", max_len=10)
                # VIZ-GAP3(a)：PNG 里没有 hover——语句折成 ≤2 行（~110 字符）而不是
                # 在阈值中间截到 64 字符。
                stmt = _wrap_label(bf.get("statement"), fallback=bid,
                                   width=55, max_lines=2)
                rows.append({
                    "label": f"{bid} · {stmt}", "p": p, "conf": conf, "market": market,
                    "hover": "<br>".join(x for x in (
                        f"<b>{bid}</b> P(yes) = {p:.1%}",
                        _wrap_hover(bf.get("statement"), 60),
                        f"theme: {_html_text(bf.get('theme'), max_len=40)}"
                        if bf.get("theme") else "",
                        f"market implied: {market:.1%}" if market is not None else "",
                    ) if x),
                })
            if not rows:
                return None
            rows.sort(key=lambda r: (-r["p"], r["label"]))
            labels = [r["label"] for r in rows]
            encode_confidence = all(r["conf"] is not None for r in rows)
            fig = go.Figure()
            # 市场锚点连线 + 菱形（有锚点的条目才有）。
            anchored = [r for r in rows if r["market"] is not None]
            for r in anchored:
                fig.add_trace(go.Scatter(
                    x=[r["market"], r["p"]], y=[r["label"], r["label"]], mode="lines",
                    line=dict(color=_COLOR_NEU, width=1.6),
                    showlegend=False, hoverinfo="skip",
                ))
            if anchored:
                fig.add_trace(go.Scatter(
                    x=[r["market"] for r in anchored], y=[r["label"] for r in anchored],
                    mode="markers", name="Market implied",
                    marker=dict(symbol="diamond", color=_COLOR_MARKET, size=10,
                                line=dict(color=_SURFACE, width=2)),
                    hovertemplate="market: %{x:.1%}<extra></extra>",
                ))
            model_marker: Dict[str, Any] = dict(
                size=11,
                color=(
                    [r["conf"] for r in rows] if encode_confidence else _COLOR_MODEL
                ),
                line=dict(color=_SURFACE, width=2),
            )
            if encode_confidence:
                model_marker.update(
                    cmin=0.0,
                    cmax=1.0,
                    colorscale=[[i / (len(_SEQ_BLUES) - 1), c]
                                for i, c in enumerate(_SEQ_BLUES)],
                    colorbar=dict(title=dict(text="Declared confidence", font=dict(size=11)),
                                  thickness=12, len=0.6, tickformat=".0%"),
                )
            fig.add_trace(go.Scatter(
                x=[r["p"] for r in rows], y=labels, mode="markers", name="Model P(yes)",
                marker=model_marker,
                hovertext=[r["hover"] for r in rows], hoverinfo="text",
            ))
            fig.add_vline(x=0.5, line_dash="dot", line_color=_AXIS)
            title = "Binary Forecasts — P(yes)"
            if encode_confidence:
                title += " with declared confidence"
            else:
                # VIZ-GAP1(b)：无声明 confidence 时明说是裸点估计（沉默呈现=虚假确定性）。
                subtitle_parts = ["point estimates — confidence not declared"]
                if anchored:
                    subtitle_parts.append(
                        f"{len(anchored)} market-anchored (paired diamonds)")
                title += f"<br><sup>{'; '.join(subtitle_parts)}</sup>"
            # 折行标签的行更高（两行文本），避免相邻标签互相压盖。
            row_height = 44 if any("<br>" in lab for lab in labels) else 30
            _apply_layout(fig, title,
                          height=max(340, row_height * len(rows) + 170))
            fig.update_layout(
                xaxis_title="P(yes)", xaxis=dict(range=[0, 1], tickformat=".0%"),
                yaxis=dict(autorange="reversed", categoryorder="array",
                           categoryarray=labels),
                legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
                margin={"l": 10, "r": 24, "t": 74, "b": 46},
            )
            return self._save_pair(fig, charts_dir, "binary_forecast_dotplot",
                                   "binary_forecast_dotplot")
        except Exception as exc:  # noqa: BLE001
            logger.debug("build_binary_dotplot_html 失败（跳过该图）：%s", exc)
            return None

    def build_timeline_lanes_html(self, timeline: Any, charts_dir: str) -> Optional[str]:
        """(D2) 时间线泳道图（取代旧 mermaid timeline）：x=日期、y=主题泳道（关键词归类），
        hover=完整事件文本（不截断、不毁字符），同日高词元重合事件去重，超上限
        （REPORT_VIZ_TIMELINE_MAX_EVENTS）按显著度截断后仍按时间升序。图内只显示编号，
        完整的显著事件短标签放在图下方的键中，避免密集日期簇的文本互相覆盖。"""
        if not self._interactive_ok():
            return None
        try:
            rows = timeline.get("timeline") if isinstance(timeline, dict) else timeline
            if not isinstance(rows, list) or not rows:
                return None
            events = _prepare_timeline_events(rows)
            if not events:
                return None
            lanes = [c for c, _ in _TL_CATEGORIES] + ["Other"]
            lane_order = {c: i for i, c in enumerate(lanes)}
            used = sorted({e["cat"] for e in events}, key=lambda c: lane_order[c])
            lane_idx = {c: i for i, c in enumerate(used)}
            label_plan = _timeline_label_plan(events, lane_idx, max_labels=10)
            fig = go.Figure()
            # 图内只放紧凑编号；完整短标签位于下方 key，完整原文始终保留在 hover。
            for cat in used:
                evs = [e for e in events if e["cat"] == cat]
                xs = [e["dt"] for e in evs]
                # Five vertical slots keep same-lane date clusters readable in PNG exports;
                # three slots still allowed every fourth point to land on top of an earlier one.
                jitter = (-0.40, -0.20, 0.0, 0.20, 0.40)
                ys = [lane_idx[cat] + jitter[k % len(jitter)] for k in range(len(evs))]
                texts = []
                marker_sizes = []
                for e in evs:
                    placement = label_plan.get((e["dt"], e["text"]))
                    texts.append(f"{placement['index']:02d}" if placement else "")
                    marker_sizes.append(19 if placement else 9)
                fig.add_trace(go.Scatter(
                    x=xs, y=ys, mode="markers+text", name=cat,
                    text=texts, textposition="middle center",
                    textfont=dict(size=7, color=_SURFACE, family=_VIZ_FONT),
                    marker=dict(size=marker_sizes,
                                color=_PALETTE[lane_idx[cat] % len(_PALETTE)],
                                line=dict(color=_SURFACE, width=1.5)),
                    hovertext=[f"<b>{e['date']}</b><br>{_wrap_hover(e['text'], 64)}"
                               for e in evs],
                    hoverinfo="text",
                ))
            ordered_key = sorted(label_plan.items(), key=lambda item: item[1]["index"])
            display_dates = {
                (event["dt"], event["text"]): event["date"] for event in events
            }
            # VIZ-GAP3(b)：key 标签从事件全文折行（≤2 行 ~110 字符），不再 52 字符截断
            # （PNG 里没有 hover，截断即信息丢失）。
            wrapped_key = [
                ((event_date, event_text), placement,
                 _wrap_label(event_text, fallback=placement["label"],
                             width=55, max_lines=2))
                for (event_date, event_text), placement in ordered_key
            ]
            unlabeled = max(0, len(events) - len(ordered_key))
            key_columns = 2 if len(wrapped_key) > 5 else 1
            key_rows = max(1, math.ceil(len(wrapped_key) / key_columns))
            # 行距逐行计算：该行（跨列取最大）有折行标签时 25 → 41，避免两行文本压到下一行。
            row_line_counts = [1] * key_rows
            for position, (_, _, wrapped_label) in enumerate(wrapped_key):
                row = position % key_rows
                row_line_counts[row] = max(row_line_counts[row],
                                           wrapped_label.count("<br>") + 1)
            row_offsets = [48]
            for lines_in_row in row_line_counts:
                row_offsets.append(row_offsets[-1] + (25 if lines_in_row == 1 else 41))
            more_note_height = 22 if unlabeled and wrapped_key else 0
            plot_height = max(390, 82 * len(used) + 155)
            key_height = (30 + row_offsets[-1] + more_note_height) if wrapped_key else 70
            paper_height = max(260, plot_height - 58)
            _apply_layout(fig, "Event Timeline", height=plot_height + key_height)
            fig.update_layout(
                # VIZ-GAP3(c)：key 区在场时压下 'Date' 轴标题——PNG 导出里它与
                # key 块可见碰撞，且日期刻度本身已自明。
                xaxis_title=None if wrapped_key else "Date",
                yaxis=dict(
                    tickvals=[lane_idx[c] for c in used], ticktext=used,
                    # 显式倒序区间（首个泳道在顶部）；不与 autorange 混用。
                    range=[max(lane_idx[c] for c in used) + 0.7, -0.7],
                    showgrid=True, zeroline=False,  # 泳道 0 不该有零线横贯
                ),
                showlegend=False,
                margin=dict(l=12, r=24, t=58, b=key_height),
            )
            if wrapped_key:
                fig.add_annotation(
                    xref="paper", yref="paper", x=0.0, y=-18 / paper_height,
                    text="<b>Key events</b>", showarrow=False,
                    xanchor="left", yanchor="top", align="left",
                    font=dict(size=10, color=_INK, family=_VIZ_FONT),
                )
            for position, ((event_date, _event_text), placement,
                           wrapped_label) in enumerate(wrapped_key):
                column = position // key_rows
                row = position % key_rows
                fig.add_annotation(
                    xref="paper", yref="paper",
                    x=column / key_columns + 0.01,
                    y=-row_offsets[row] / paper_height,
                    text=(f"<b>{placement['index']:02d}</b>  "
                          f"{_html_text(display_dates.get((event_date, _event_text)), max_len=24)}  "
                          f"{wrapped_label}"),
                    showarrow=False, xanchor="left", yanchor="top", align="left",
                    font=dict(size=9, color=_INK_2, family=_VIZ_FONT),
                )
            # VIZ-GAP3(c)：计划外事件不再是匿名圆点——给出 +N more 说明。
            if unlabeled and wrapped_key:
                fig.add_annotation(
                    xref="paper", yref="paper", x=0.0,
                    y=-(row_offsets[-1] + 4) / paper_height,
                    text=(f"+{unlabeled} more event(s) shown as unlabeled dots — "
                          "full text in the interactive chart hover"),
                    showarrow=False, xanchor="left", yanchor="top", align="left",
                    font={"size": 9, "color": _INK_2, "family": _VIZ_FONT},
                )
            return self._save_pair(fig, charts_dir, "timeline_lanes", "timeline_lanes")
        except Exception as exc:  # noqa: BLE001
            logger.debug("build_timeline_lanes_html 失败（跳过该图）：%s", exc)
            return None

    def build_actor_network_html(self, actors: Any, charts_dir: str,
                                 graph_priors: Any = None) -> Optional[str]:
        """(D3) 角色关系网络（取代旧 mermaid actor_network）：networkx spring 布局（固定 seed，
        缺 networkx 时确定性圆布局），节点大小=graph_priors 权重（缺则度数），边色=关系符号
        （+绿/−红/±灰），端点名经 actors 列表归一（'Samsung'→'Samsung Electronics' 类重复合并），
        边按 (src,dst,type) 去重，节点上限 REPORT_VIZ_NETWORK_MAX_NODES。"""
        if not self._interactive_ok():
            return None
        try:
            rels = (actors.get("relationships") or actors.get("relations")
                    or actors.get("edges")) if isinstance(actors, dict) else actors
            if not isinstance(rels, list) or not rels:
                return None
            actor_list = actors.get("actors") if isinstance(actors, dict) else None
            canon = _canonical_actor_map(actor_list)
            priors: Dict[str, float] = {}
            if isinstance(graph_priors, dict):
                for k, v in graph_priors.items():
                    fv = _to_float(v)
                    if fv is not None and str(k).strip():
                        priors[_norm_key(k)] = fv
            # 边收集：端点归一 + (src,dst,type) 去重 + 自环剔除。
            seen_edges: set = set()
            edges: List[Tuple[str, str, str, str]] = []  # (src, dst, type, sign)
            node_order: List[str] = []
            degree: Dict[str, int] = {}
            for r in rels:
                if not isinstance(r, dict):
                    continue
                src = _canonicalize(str(r.get("source") or r.get("from") or "").strip(), canon)
                tgt = _canonicalize(str(r.get("target") or r.get("to") or "").strip(), canon)
                if not src or not tgt or src == tgt:
                    continue
                typ = str(r.get("type") or r.get("relation") or r.get("rel") or "REL").strip().upper()
                key = (src, tgt, typ)
                if key in seen_edges:
                    continue
                seen_edges.add(key)
                edges.append((src, tgt, typ, _sign_of(r) or "±"))
                for n in (src, tgt):
                    if n not in degree:
                        degree[n] = 0
                        node_order.append(n)
                    degree[n] += 1
            if not edges:
                return None
            # 节点上限：graph_priors 权重优先，其次度数，再按首现序（确定性）。
            max_nodes = int(_cfg("REPORT_VIZ_NETWORK_MAX_NODES", 60) or 60)
            first_seen = {n: i for i, n in enumerate(node_order)}
            ranked = sorted(node_order,
                            key=lambda n: (-priors.get(_norm_key(n), 0.0),
                                           -degree.get(n, 0), first_seen[n]))
            kept = set(ranked[:max(2, max_nodes)])
            edges = [e for e in edges if e[0] in kept and e[1] in kept]
            nodes = [n for n in node_order if n in kept]
            if not edges or len(nodes) < 2:
                return None
            pos = _network_layout(nodes, edges)
            # 角色元数据（role_class/influence → hover + 着色）。
            meta: Dict[str, Dict[str, Any]] = {}
            if isinstance(actor_list, list):
                for a in actor_list:
                    if isinstance(a, dict) and str(a.get("name") or "").strip():
                        meta[_norm_key(a["name"])] = a
            # 三类符号边各一 trace（None 分隔的折线集合）。
            sign_style = {"+": (_COLOR_POS, "supportive (+)"),
                          "−": (_COLOR_NEG, "adversarial (−)"),
                          "±": (_COLOR_NEU, "neutral (±)")}
            fig = go.Figure()
            for sign, (color, label) in sign_style.items():
                xs: List[Any] = []
                ys: List[Any] = []
                for src, tgt, _typ, s in edges:
                    if s != sign:
                        continue
                    x0, y0 = pos[src]
                    x1, y1 = pos[tgt]
                    xs.extend([x0, x1, None])
                    ys.extend([y0, y1, None])
                if not xs:
                    continue
                fig.add_trace(go.Scatter(
                    x=xs, y=ys, mode="lines", name=label,
                    line=dict(color=color, width=1), opacity=0.55, hoverinfo="skip",
                ))
            # 节点：大小=priors 权重（缺则度数）归一，颜色=role_class 分类。
            weights = {}
            has_prior = any(_norm_key(n) in priors for n in nodes)
            for n in nodes:
                weights[n] = (priors.get(_norm_key(n), 0.0) if has_prior
                              else float(degree.get(n, 1)))
            wmax = max(weights.values()) or 1.0
            classes = sorted({str((meta.get(_norm_key(n)) or {}).get("role_class")
                                  or "other") for n in nodes})
            class_color = {c: _PALETTE[i % len(_PALETTE)] for i, c in enumerate(classes)}
            label_plan = _actor_label_plan(nodes, pos, weights, max_labels=16)
            for cls in classes:
                cnodes = [n for n in nodes
                          if str((meta.get(_norm_key(n)) or {}).get("role_class")
                                 or "other") == cls]
                if not cnodes:
                    continue
                hovers = []
                for n in cnodes:
                    m = meta.get(_norm_key(n)) or {}
                    hovers.append("<br>".join(x for x in (
                        f"<b>{_html_text(n, max_len=60)}</b>",
                        f"role_class: {cls}",
                        f"influence: {_html_text(m.get('influence'), max_len=20)}"
                        if m.get("influence") else "",
                        f"degree: {degree.get(n, 0)}",
                        f"graph prior: {priors.get(_norm_key(n)):.3f}"
                        if _norm_key(n) in priors else "",
                    ) if x))
                fig.add_trace(go.Scatter(
                    x=[pos[n][0] for n in cnodes], y=[pos[n][1] for n in cnodes],
                    mode="markers", name=cls,
                    marker=dict(
                        size=[10 + 26 * (weights[n] / wmax) for n in cnodes],
                        color=class_color[cls], line=dict(color=_SURFACE, width=2),
                    ),
                    hovertext=hovers, hoverinfo="text",
                ))
            for node, placement in label_plan.items():
                fig.add_annotation(
                    x=pos[node][0], y=pos[node][1], xref="x", yref="y",
                    ax=placement["xytext"][0], ay=placement["xytext"][1],
                    axref="x", ayref="y", showarrow=True, arrowhead=0,
                    arrowwidth=0.7, arrowcolor=_AXIS,
                    text=f"<b>{_html_text(node, max_len=24)}</b>",
                    font=dict(size=9, color=_INK, family=_VIZ_FONT),
                    bgcolor="rgba(255,255,255,0.88)", borderpad=2,
                    xanchor="center", yanchor="middle",
                )
            bounds = [entry["bbox"] for entry in label_plan.values()]
            x_values = [pos[node][0] for node in nodes]
            y_values = [pos[node][1] for node in nodes]
            if bounds:
                x_values.extend(value for box in bounds for value in (box[0], box[2]))
                y_values.extend(value for box in bounds for value in (box[1], box[3]))
            x_span = max(max(x_values) - min(x_values), 1.0)
            y_span = max(max(y_values) - min(y_values), 1.0)
            _apply_layout(fig, "Actor Relationship Network", height=780)
            fig.update_layout(
                xaxis=dict(visible=False,
                           range=[min(x_values) - x_span * 0.06,
                                  max(x_values) + x_span * 0.06]),
                yaxis=dict(visible=False,
                           range=[min(y_values) - y_span * 0.08,
                                  max(y_values) + y_span * 0.08],
                           scaleanchor="x", scaleratio=1),
                legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
            )
            return self._save_pair(fig, charts_dir, "actor_network", "actor_network")
        except Exception as exc:  # noqa: BLE001
            logger.debug("build_actor_network_html 失败（跳过该图）：%s", exc)
            return None

    def build_actor_bubble_html(self, actors: Any, charts_dir: str) -> Optional[str]:
        """(D4) 角色影响力×显著度气泡：x=salience score（0–1）、y=influence 分级（确定性微错位
        防重叠）、气泡大小=关系度数、颜色=role_class。"""
        if not self._interactive_ok():
            return None
        try:
            actor_list = actors.get("actors") if isinstance(actors, dict) else actors
            if not isinstance(actor_list, list) or not actor_list:
                return None
            rels = actors.get("relationships") if isinstance(actors, dict) else None
            degree: Dict[str, int] = {}
            if isinstance(rels, list):
                for r in rels:
                    if not isinstance(r, dict):
                        continue
                    for k in ("source", "target"):
                        n = _norm_key(str(r.get(k) or ""))
                        if n:
                            degree[n] = degree.get(n, 0) + 1
            rows: List[Dict[str, Any]] = []
            for i, a in enumerate(actor_list):
                if not isinstance(a, dict):
                    continue
                name = str(a.get("name") or "").strip()
                if not name:
                    continue
                sal = a.get("salience")
                if isinstance(sal, dict):
                    sx = _to_float(sal.get("score"))
                    if sx is None:
                        sx = (_LEVEL_NUM.get(str(sal.get("tier") or "").lower(), 2.0)) / 4.0
                else:
                    sx = _to_float(sal)
                    if sx is None:
                        sx = (_LEVEL_NUM.get(str(sal or "").lower(), 2.0)) / 4.0
                infl = _LEVEL_NUM.get(str(a.get("influence") or "").strip().lower(), 2.0)
                rows.append({
                    "name": name,
                    "x": max(0.0, min(1.0, sx)),
                    "y": infl + ((i % 5) - 2) * 0.09,  # 确定性微错位
                    "size": degree.get(_norm_key(name), 1),
                    "cls": str(a.get("role_class") or "other"),
                    "hover": "<br>".join(x for x in (
                        f"<b>{_html_text(name, max_len=60)}</b>",
                        _wrap_hover(a.get("role"), 60, max_len=240),
                        f"influence: {_html_text(a.get('influence'), max_len=20)} · "
                        f"salience: {sx:.2f} · degree: {degree.get(_norm_key(name), 0)}",
                    ) if x),
                })
            if not rows:
                return None
            smax = max(r["size"] for r in rows) or 1
            classes = sorted({r["cls"] for r in rows})
            fig = go.Figure()
            for ci, cls in enumerate(classes):
                sub = [r for r in rows if r["cls"] == cls]
                fig.add_trace(go.Scatter(
                    x=[r["x"] for r in sub], y=[r["y"] for r in sub],
                    mode="markers+text", name=cls,
                    text=[_html_text(r["name"], max_len=18) for r in sub],
                    textposition="top center", textfont=dict(size=9, color=_INK_2),
                    marker=dict(
                        size=[12 + 30 * (r["size"] / smax) for r in sub],
                        color=_PALETTE[ci % len(_PALETTE)], opacity=0.85,
                        line=dict(color=_SURFACE, width=2),
                    ),
                    hovertext=[r["hover"] for r in sub], hoverinfo="text",
                ))
            _apply_layout(fig, "Actors — Influence vs Salience "
                               "(bubble = relationship degree)", height=560)
            fig.update_layout(
                xaxis_title="Salience score",
                xaxis=dict(range=[-0.05, 1.1]),
                yaxis=dict(title="Influence", tickvals=[1, 2, 3, 4],
                           ticktext=["Low", "Medium", "High", "Very high"],
                           range=[0.4, 4.6]),
                legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
            )
            return self._save_pair(fig, charts_dir, "actor_influence_salience",
                                   "actor_influence_salience")
        except Exception as exc:  # noqa: BLE001
            logger.debug("build_actor_bubble_html 失败（跳过该图）：%s", exc)
            return None

    def build_source_sunburst_html(self, sources: Any, charts_dir: str) -> Optional[str]:
        """(D5) 来源构成 sunburst：tier（证据层级）→ source_origin（fetched/cited）→
        reachable（可达性）三层占比。"""
        if not self._interactive_ok():
            return None
        try:
            if not isinstance(sources, list) or not sources:
                return None
            counts: Dict[Tuple[str, str, str], int] = {}
            for s in sources:
                if not isinstance(s, dict):
                    continue
                tier = str(s.get("tier") or "untiered").strip() or "untiered"
                origin = str(s.get("source_origin") or "unknown").strip() or "unknown"
                reach = s.get("reachable")
                reach_lbl = ("reachable" if reach is True
                             else "unreachable" if reach is False else "unchecked")
                key = (tier, origin, reach_lbl)
                counts[key] = counts.get(key, 0) + 1
            if not counts:
                return None
            total = sum(counts.values())
            ids: List[str] = []
            labels: List[str] = []
            parents: List[str] = []
            values: List[int] = []
            colors: List[str] = []
            tier_totals: Dict[str, int] = {}
            origin_totals: Dict[Tuple[str, str], int] = {}
            for (tier, origin, _reach), n in counts.items():
                tier_totals[tier] = tier_totals.get(tier, 0) + n
                origin_totals[(tier, origin)] = origin_totals.get((tier, origin), 0) + n
            for tier in sorted(tier_totals, key=lambda t: (_TIER_RANK.get(t, 9), t)):
                ids.append(tier)
                labels.append(tier)
                parents.append("")
                values.append(tier_totals[tier])
                colors.append(_TIER_COLOR.get(tier, _COLOR_NEU))
            for (tier, origin) in sorted(origin_totals):
                ids.append(f"{tier}/{origin}")
                labels.append(origin)
                parents.append(tier)
                values.append(origin_totals[(tier, origin)])
                colors.append(_TIER_COLOR.get(tier, _COLOR_NEU))
            reach_color = {"reachable": _COLOR_GOOD, "unreachable": _COLOR_STALE,
                           "unchecked": _COLOR_NEU}
            for (tier, origin, reach) in sorted(counts):
                ids.append(f"{tier}/{origin}/{reach}")
                labels.append(reach)
                parents.append(f"{tier}/{origin}")
                values.append(counts[(tier, origin, reach)])
                colors.append(reach_color[reach])
            fig = go.Figure(go.Sunburst(
                ids=ids, labels=labels, parents=parents, values=values,
                branchvalues="total",
                marker=dict(colors=colors, line=dict(color=_SURFACE, width=1.5)),
                hovertemplate="%{id}: %{value} sources (%{percentRoot:.1%})<extra></extra>",
                textfont=dict(family=_VIZ_FONT, size=12),
            ))
            _apply_layout(fig, f"Source Mix — tier → origin → reachability "
                               f"(n={total})", height=560)
            return self._save_pair(fig, charts_dir, "source_mix_sunburst",
                                   "source_mix_sunburst")
        except Exception as exc:  # noqa: BLE001
            logger.debug("build_source_sunburst_html 失败（跳过该图）：%s", exc)
            return None

    @staticmethod
    def _metric_point_hover(point: Dict[str, Any], unit: str) -> str:
        """轨迹/折线单点 hover：代表行原始 metric 名 + 值/单位/年份 + 观测/预测 + 陈旧标记
        +（多行聚合时的 n）+ 口径 + 来源。空片段自动剔除。"""
        rep = point.get("rep") or {}
        head = _wrap_hover(rep.get("metric") or "", 56, max_len=160)
        line2 = (f"{rep.get('display_value', point['value'])} {unit} @ {point['x_label']}"
                 + (" · forecast" if point["kind"] == "forecast" else " · actual")
                 + (f" · n={point['n']}" if point.get("n", 1) > 1 else "")
                 + (" · ⚠ stale" if point.get("stale") else ""))
        return "<br>".join(x for x in (
            f"<b>{head}</b>" if head else "",
            line2,
            _wrap_hover(rep.get("definition") or "", 56, max_len=200),
            _wrap_hover(rep.get("source") or "", 56, max_len=160),
        ) if x)

    def build_metric_trajectories_html(self, quantitative: Any,
                                       charts_dir: str) -> Optional[str]:
        """(D5b) 研究抽取指标轨迹——读者真正要的预测数据图（成本曲线 / 部署量 / 渗透率 /
        区域对比），而非管线自证。DRF2：任一行带 metric_family → 按家族跨 year 分组，每条折线
        对应一个 region/technology/analyst 分组；否则回退折叠名单序列（老数据仍出图）。逐面板
        画折线+散点，观测点圆记号、预测点菱形记号，hover 保留口径/来源/年份。无合格面板 → None。"""
        if not self._interactive_ok():
            return None
        try:
            panels = _metric_trajectory_panels(quantitative)
            if not panels:
                return None
            from plotly.subplots import make_subplots
            fig = make_subplots(
                rows=len(panels), cols=1, shared_xaxes=False,
                subplot_titles=[_html_text(p["title"], max_len=80) for p in panels],
                # 面板数可达 8：间距须 < 1/(rows-1)，随行数收缩以免 plotly 校验抛错。
                vertical_spacing=min(0.12, 0.8 / max(1, len(panels))),
            )
            # 多折线面板需图例区分 region/tech/analyst；同名折线跨面板去重（legendgroup 联动）。
            multi = any(len(p["lines"]) > 1 for p in panels)
            legend_seen: set = set()
            for ri, panel in enumerate(panels, 1):
                # x 轴修复（shipped-chart bug）：此前一律传 x_label 字符串 → plotly 类别轴
                # 按「首现顺序」排布，多折线时首条线的 2027 会排在 2025 左边（年轴倒序）。
                # 家族路径的 p['x'] 为整型年份 → 直接按数值作图（轴天然升序）；legacy 路径
                # （ISO 日期标签）退回类别轴并强制 'category ascending'（ISO 字典序=时间序）。
                panel_numeric = all(
                    isinstance(p["x"], int) and not isinstance(p["x"], bool)
                    for line in panel["lines"] for p in line["points"])
                for li, line in enumerate(panel["lines"]):
                    pts = line["points"]
                    named = line["name"] is not None
                    color = (_PALETTE[li % len(_PALETTE)]
                             if (panel["split"] or multi) else _COLOR_MODEL)
                    show_legend = named and line["name"] not in legend_seen
                    if named:
                        legend_seen.add(line["name"])
                    fig.add_trace(go.Scatter(
                        x=[(p["x"] if panel_numeric else p["x_label"]) for p in pts],
                        y=[p["value"] for p in pts],
                        # 单点折线画不出线段（不可见）→ 仅记号；≥2 点才画线。
                        mode="lines+markers" if len(pts) >= 2 else "markers",
                        name=line["name"] or "series",
                        legendgroup=line["name"] or f"__panel{ri}",
                        showlegend=show_legend,
                        line={"color": color, "width": 2.5},
                        marker={
                            "size": 10,
                            "symbol": ["diamond" if p["kind"] == "forecast" else "circle"
                                       for p in pts],
                            "color": color,
                            "line": {
                                "color": [_COLOR_STALE if p["stale"] else _SURFACE
                                          for p in pts],
                                "width": 2,
                            },
                        },
                        hovertext=[self._metric_point_hover(p, panel["unit"]) for p in pts],
                        hoverinfo="text",
                    ), row=ri, col=1)
                fig.update_yaxes(title_text=panel["unit"], row=ri, col=1)
                if panel_numeric:
                    years = sorted({p["x"] for line in panel["lines"]
                                    for p in line["points"]})
                    # 整年刻度：小跨度逐年打刻度，避免 2025.5 之类的分数年刻度。
                    fig.update_xaxes(tickformat="d", row=ri, col=1)
                    if years and years[-1] - years[0] <= 12:
                        fig.update_xaxes(dtick=1, row=ri, col=1)
                else:
                    fig.update_xaxes(categoryorder="category ascending", row=ri, col=1)
            _apply_layout(
                fig, "Key Metric Trajectories (research-extracted)",
                height=max(420, 240 * len(panels) + 140),
            )
            if multi:
                # 图例置于整图底部：此前 y=1.02 的横向图例压在首个子图标题上。
                fig.update_layout(
                    legend={"orientation": "h", "yanchor": "top", "y": -0.04,
                            "xanchor": "left", "x": 0},
                    margin={"b": 96},
                )
            return self._save_pair(fig, charts_dir, "metric_trajectories",
                                   "metric_trajectories")
        except Exception as exc:  # noqa: BLE001
            logger.debug("build_metric_trajectories_html 失败（跳过该图）：%s", exc)
            return None

    def build_technology_shares_html(self, quantitative: Any,
                                     charts_dir: str) -> Optional[str]:
        """(D5c) 技术份额柱：某 metric_family 在其最新「技术数 ≥2」的年份，按 technology 画
        value_num 分组柱并标占比%。逐家族一个面板。无 ≥2 技术的家族 → None（degrade-safe）。"""
        if not self._interactive_ok():
            return None
        try:
            panels = _prepare_technology_shares(quantitative)
            if not panels:
                return None
            from plotly.subplots import make_subplots
            fig = make_subplots(
                rows=len(panels), cols=1, shared_xaxes=False,
                subplot_titles=[
                    _html_text(f"{p['family']} · {p['unit']} ({p['year']})", max_len=80)
                    for p in panels
                ],
                vertical_spacing=min(0.16, 0.8 / max(1, len(panels))),
            )
            for ri, panel in enumerate(panels, 1):
                techs = panel["techs"]
                fig.add_trace(go.Bar(
                    x=[_html_text(t["tech"], max_len=40) for t in techs],
                    y=[t["value"] for t in techs],
                    marker_color=[_PALETTE[i % len(_PALETTE)] for i in range(len(techs))],
                    text=[f"{t['share']:.0%}" for t in techs],
                    textposition="outside",
                    hovertext=["<br>".join(x for x in (
                        f"<b>{_html_text(t['tech'], max_len=48)}</b>",
                        f"{t['rep'].get('display_value', t['value'])} {panel['unit']}"
                        f" · {t['share']:.1%} share @ {panel['year']}"
                        + (f" · n={t['n']}" if t["n"] > 1 else ""),
                        _wrap_hover(t["rep"].get("source") or "", 56, max_len=160),
                    ) if x) for t in techs],
                    hoverinfo="text", showlegend=False,
                ), row=ri, col=1)
                fig.update_yaxes(title_text=panel["unit"], row=ri, col=1)
            _apply_layout(
                fig, "Technology Shares by Metric Family (research-extracted)",
                height=max(420, 260 * len(panels) + 120),
            )
            return self._save_pair(fig, charts_dir, "technology_shares",
                                   "technology_shares")
        except Exception as exc:  # noqa: BLE001
            logger.debug("build_technology_shares_html 失败（跳过该图）：%s", exc)
            return None

    def build_regional_comparison_html(self, quantitative: Any,
                                       charts_dir: str) -> Optional[str]:
        """(D5d) 区域对比柱：某 metric_family 在其最新「区域数 ≥2」的年份，按 region 画
        value_num 分组柱（观测柱/预测柱颜色区分）。逐家族一个面板。<2 区域 → None。"""
        if not self._interactive_ok():
            return None
        try:
            panels = _prepare_regional_comparison(quantitative)
            if not panels:
                return None
            from plotly.subplots import make_subplots
            fig = make_subplots(
                rows=len(panels), cols=1, shared_xaxes=False,
                subplot_titles=[
                    _html_text(f"{p['family']} · {p['unit']} ({p['year']})", max_len=80)
                    for p in panels
                ],
                vertical_spacing=min(0.16, 0.8 / max(1, len(panels))),
            )
            for ri, panel in enumerate(panels, 1):
                regions = panel["regions"]
                fig.add_trace(go.Bar(
                    x=[_html_text(r["region"], max_len=40) for r in regions],
                    y=[r["value"] for r in regions],
                    marker_color=[_PALETTE[2] if r["kind"] == "forecast" else _COLOR_MODEL
                                  for r in regions],
                    text=[f"{r['rep'].get('display_value', r['value'])}" for r in regions],
                    textposition="outside",
                    hovertext=["<br>".join(x for x in (
                        f"<b>{_html_text(r['region'], max_len=48)}</b>",
                        f"{r['rep'].get('display_value', r['value'])} {panel['unit']} @ {panel['year']}"
                        + (" · forecast" if r["kind"] == "forecast" else " · actual")
                        + (f" · n={r['n']}" if r["n"] > 1 else ""),
                        _wrap_hover(r["rep"].get("metric") or "", 56, max_len=160),
                        _wrap_hover(r["rep"].get("source") or "", 56, max_len=160),
                    ) if x) for r in regions],
                    hoverinfo="text", showlegend=False,
                ), row=ri, col=1)
                fig.update_yaxes(title_text=panel["unit"], row=ri, col=1)
            _apply_layout(
                fig, "Regional Comparison by Metric Family (latest year, research-extracted)",
                height=max(420, 260 * len(panels) + 120),
            )
            return self._save_pair(fig, charts_dir, "regional_comparison",
                                   "regional_comparison")
        except Exception as exc:  # noqa: BLE001
            logger.debug("build_regional_comparison_html 失败（跳过该图）：%s", exc)
            return None

    def build_quantitative_dots_html(self, quantitative: Any,
                                     charts_dir: str) -> Optional[str]:
        """(D6) Comparable quantitative benchmarks from sourced forecast data.

        Each panel has one explicit denominator/rate unit.  Ambiguous groups
        such as plain ``%``, ``units`` or ``USD billion`` fail closed because
        equal glyphs can conceal different definitions and time bases.
        Observed values use circles, projections use diamonds, and every hover
        retains its source and as-of date.
        """
        if not self._interactive_ok():
            return None
        try:
            panels = _prepare_quantitative_panels(quantitative)
            if not panels:
                return None
            # VIZ-GAP2：面板密度门——每个面板须 ≥4 个点或 ≥2 个互异指标；全部低于门槛
            # 时整图降级为紧凑 markdown 表（4 个数不配两个堆叠面板的整页版面）。
            dense_panels = [panel for panel in panels if _quant_panel_is_dense(panel)]
            if not dense_panels:
                table = [
                    "# Comparable Forecast Benchmarks",
                    "",
                    (f"All panels fall below the density threshold "
                     f"(≥{_QUANT_PANEL_MIN_POINTS} points or "
                     f"≥{_QUANT_PANEL_MIN_CATEGORIES} distinct metrics per panel) — "
                     "compact table instead of a full-page chart."),
                    "",
                    "| Metric | Value | Unit | As of | Tier | Status | Source |",
                    "| --- | --- | --- | --- | --- | --- | --- |",
                ]
                for panel in panels:
                    for row in panel["rows"]:
                        status = ("forecast/target" if row.get("projection")
                                  else "observed")
                        if row.get("stale"):
                            status += " · stale"
                        table.append(
                            f"| {_md_cell(row.get('metric'), max_len=80)} "
                            f"| {_md_cell(row.get('display_value'), max_len=24)} "
                            f"| {_md_cell(row.get('unit'), max_len=24)} "
                            f"| {_md_cell(row.get('as_of'), max_len=12)} "
                            f"| {_md_cell(row.get('tier'), max_len=4)} "
                            f"| {status} "
                            f"| {_md_cell(row.get('source'), max_len=48)} |")
                self._write_density_fallback(
                    "quantitative_claims", "quantitative_claims", table, charts_dir)
                return None
            self._skip_notes.pop("quantitative_claims", None)
            panels = dense_panels
            from plotly.subplots import make_subplots
            heights = [len(panel["rows"]) for panel in panels]
            fig = make_subplots(
                rows=len(panels), cols=1, shared_xaxes=False,
                # VIZ-GAP3(d)：面板互异的子图标题（不再出现两个 'USD/kW (n=2)'）。
                subplot_titles=_quant_panel_subtitles(panels),
                # Leave enough room for each panel's x-axis title and the next
                # subplot title.  Dense multi-panel exports otherwise remain
                # technically legible in HTML but collide in the static PNG.
                row_heights=[max(h, 2) for h in heights], vertical_spacing=0.16,
            )
            shown_status: set = set()
            for ri, panel in enumerate(panels, 1):
                for projection in (False, True):
                    sub = [row for row in panel["rows"] if row["projection"] is projection]
                    if not sub:
                        continue
                    status = "Published forecast / target" if projection else "Observed / reported"
                    color = _PALETTE[2] if projection else _COLOR_MODEL
                    fig.add_trace(go.Scatter(
                        x=[r["value"] for r in sub],
                        y=[_html_text(r["metric"], max_len=46)
                           + (" ⚠" if r["stale"] else "") for r in sub],
                        mode="markers", name=status, legendgroup=status,
                        showlegend=status not in shown_status,
                        marker={
                            "size": 11,
                            "symbol": "diamond" if projection else "circle",
                            "color": color,
                            "line": {
                                "color": [_COLOR_STALE if r["stale"]
                                          else _SURFACE
                                          for r in sub],
                                "width": 2,
                            },
                        },
                        hovertext=["<br>".join(x for x in (
                            f"<b>{_wrap_hover(r['metric'], 56, max_len=160)}</b>",
                            f"{r['display_value']} {r['unit']} · tier {r['tier']} · {status.lower()}"
                            + (" · ⚠ stale" if r["stale"] else ""),
                            f"as of {_html_text(r['as_of'], max_len=20)}" if r["as_of"] else "",
                            _wrap_hover(r["definition"], 56, max_len=200),
                            _wrap_hover(r["source"], 56, max_len=160),
                        ) if x) for r in sub],
                        hoverinfo="text",
                    ), row=ri, col=1)
                    shown_status.add(status)
                fig.update_xaxes(title_text=panel["unit"], row=ri, col=1)
            total_rows = sum(heights)
            _apply_layout(
                fig,
                "Comparable Forecast Benchmarks (same denominator within each panel)",
                height=max(560, 32 * total_rows + 145 * len(panels) + 160),
            )
            fig.update_layout(legend={
                "orientation": "h", "yanchor": "bottom", "y": 1.02,
                "xanchor": "right", "x": 1,
            })
            fig.update_yaxes(autorange="reversed")
            return self._save_pair(fig, charts_dir, "quantitative_claims",
                                   "quantitative_claims")
        except Exception as exc:  # noqa: BLE001
            logger.debug("build_quantitative_dots_html 失败（跳过该图）：%s", exc)
            return None

    def build_forecast_revisions_html(self, quantitative: Any,
                                      charts_dir: str) -> Optional[str]:
        """Plot how the same published forecast changed across ≥3 vintages."""
        if not self._interactive_ok():
            return None
        try:
            series = _prepare_forecast_revision_series(quantitative)
            if not series:
                return None
            from plotly.subplots import make_subplots
            fig = make_subplots(
                rows=len(series), cols=1, shared_xaxes=False,
                subplot_titles=[f"{row['name']} · {row['unit']}" for row in series],
                vertical_spacing=0.14,
            )
            for ri, row in enumerate(series, 1):
                points = row["points"]
                fig.add_trace(go.Scatter(
                    x=[point["vintage"] for point in points],
                    y=[point["value"] for point in points],
                    mode="lines+markers+text",
                    text=[f"{point['value']:g}" for point in points],
                    textposition="top center",
                    line={"color": _COLOR_MODEL, "width": 3},
                    marker={
                        "size": 11,
                        "color": [_COLOR_STALE if point["stale"] else _COLOR_MODEL
                                  for point in points],
                        "line": {"color": _SURFACE, "width": 2},
                    },
                    hovertext=["<br>".join(x for x in (
                        f"<b>{_wrap_hover(row['name'], 56, max_len=160)}</b>",
                        f"vintage {point['vintage']}: {point['display_value']} {row['unit']}",
                        f"published/as of {_html_text(point['as_of'], max_len=20)}"
                        if point["as_of"] else "",
                        _wrap_hover(point["source"], 56, max_len=160),
                    ) if x) for point in points],
                    hoverinfo="text",
                    showlegend=False,
                ), row=ri, col=1)
                fig.update_xaxes(title_text="Forecast vintage", dtick=1, row=ri, col=1)
                fig.update_yaxes(title_text=row["unit"], row=ri, col=1)
            _apply_layout(
                fig,
                "Forecast Revisions — What Changed Across Published Vintages",
                height=max(400, 300 * len(series) + 100),
            )
            return self._save_pair(
                fig, charts_dir, "forecast_revisions", "forecast_revisions",
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug("build_forecast_revisions_html 失败（跳过该图）：%s", exc)
            return None

    def build_driver_tornado_html(self, ensemble: Any, charts_dir: str,
                                  graph_priors: Any = None) -> Optional[str]:
        """(D7) 驱动因子 tornado：把 ensemble 各情景的 key_drivers 按概率加权累计（近重词元
        合并），graph_priors 里命中的实体权重作乘性加成，取 top 15 排序横条。"""
        if not self._interactive_ok():
            return None
        try:
            scenarios = (ensemble.get("scenarios")
                         if isinstance(ensemble, dict) else ensemble)
            if not isinstance(scenarios, list) or not scenarios:
                return None
            n_sc = max(1, len(scenarios))
            canon: List[Dict[str, Any]] = []
            for sc in scenarios:
                if not isinstance(sc, dict):
                    continue
                w = _first_float(sc, ("mean_probability", "probability", "support_ratio"))
                if w is None:
                    w = 1.0 / n_sc
                sc_name = _html_text(sc.get("name"), fallback="scenario", max_len=40)
                drivers = sc.get("key_drivers")
                if not isinstance(drivers, list):
                    continue
                for d in drivers:
                    text = str(d or "").strip()
                    if not text:
                        continue
                    toks = _tokens(text)
                    hit = None
                    for c in canon:
                        if _jaccard(toks, c["tokens"]) >= 0.6:
                            hit = c
                            break
                    if hit is None:
                        hit = {"text": text, "tokens": toks, "weight": 0.0,
                               "scenarios": []}
                        canon.append(hit)
                    hit["weight"] += w
                    if sc_name not in hit["scenarios"]:
                        hit["scenarios"].append(sc_name)
            if not canon:
                return None
            priors: Dict[str, float] = {}
            if isinstance(graph_priors, dict):
                for k, v in graph_priors.items():
                    fv = _to_float(v)
                    if fv is not None and len(str(k).strip()) >= 3:
                        priors[str(k).strip()] = fv
            for c in canon:
                boost = 0.0
                boost_ent = ""
                low = c["text"].casefold()
                for ent, pv in priors.items():
                    if ent.casefold() in low and pv > boost:
                        boost = pv
                        boost_ent = ent
                c["score"] = c["weight"] * (1.0 + boost)
                c["boost_ent"] = boost_ent
            canon.sort(key=lambda c: (-c["score"], c["text"]))
            top = canon[:15]
            fig = go.Figure(go.Bar(
                x=[c["score"] for c in top],
                y=[_html_text(c["text"], max_len=64) for c in top],
                orientation="h", marker_color=_COLOR_MODEL,
                hovertext=["<br>".join(x for x in (
                    f"<b>{_wrap_hover(c['text'], 60)}</b>",
                    f"weighted salience {c['score']:.2f} "
                    f"(cited by {len(c['scenarios'])} scenario"
                    f"{'s' if len(c['scenarios']) != 1 else ''})",
                    f"graph-prior boost via {c['boost_ent']}" if c["boost_ent"] else "",
                ) if x) for c in top],
                hoverinfo="text",
            ))
            _apply_layout(fig, "Key Drivers — probability-weighted salience "
                               "across ensemble scenarios",
                          height=max(360, 34 * len(top) + 160))
            fig.update_layout(
                xaxis_title="Weighted driver salience (Σ scenario prob × prior boost)",
                yaxis=dict(autorange="reversed"),
            )
            return self._save_pair(fig, charts_dir, "driver_tornado", "driver_tornado")
        except Exception as exc:  # noqa: BLE001
            logger.debug("build_driver_tornado_html 失败（跳过该图）：%s", exc)
            return None

    def build_contested_dumbbell_html(self, contested: Any,
                                      charts_dir: str) -> Optional[str]:
        """(D8) 争议断言哑铃：每条争议断言取前两个对立立场，端点=证据权重（来源数 × 层级权重），
        差距即证据不对称度。按总权重取 top 12。"""
        if not self._interactive_ok():
            return None
        try:
            if not isinstance(contested, list) or not contested:
                return None
            rows: List[Dict[str, Any]] = []
            for c in contested:
                if not isinstance(c, dict):
                    continue
                claim = str(c.get("claim") or "").strip()
                positions = c.get("positions")
                if not claim or not isinstance(positions, list) or len(positions) < 2:
                    continue
                def _pw(pos: Any) -> Optional[Dict[str, Any]]:
                    if not isinstance(pos, dict):
                        return None
                    srcs = pos.get("sources")
                    n = len(srcs) if isinstance(srcs, list) else 1
                    tier = str(pos.get("tier") or "S3").strip()
                    return {
                        "w": max(0.5, n) * _TIER_WEIGHT.get(tier, 1.0),
                        "stance": str(pos.get("stance") or "").strip(),
                        "tier": tier, "n": n,
                    }
                a = _pw(positions[0])
                b = _pw(positions[1])
                if a is None or b is None:
                    continue
                rows.append({"claim": claim, "a": a, "b": b,
                             "total": a["w"] + b["w"]})
            if not rows:
                return None
            rows.sort(key=lambda r: (-r["total"], r["claim"]))
            rows = rows[:12]
            labels = [_html_text(r["claim"], max_len=58) for r in rows]
            fig = go.Figure()
            for lab, r in zip(labels, rows):
                fig.add_trace(go.Scatter(
                    x=[r["a"]["w"], r["b"]["w"]], y=[lab, lab], mode="lines",
                    line=dict(color=_COLOR_NEU, width=2),
                    showlegend=False, hoverinfo="skip",
                ))
            def _pos_hover(r: Dict[str, Any], key: str) -> str:
                p = r[key]
                return "<br>".join(x for x in (
                    f"<b>{_wrap_hover(r['claim'], 56, max_len=160)}</b>",
                    _wrap_hover(p["stance"], 60, max_len=280),
                    f"{p['n']} source{'s' if p['n'] != 1 else ''} · tier {p['tier']} "
                    f"→ weight {p['w']:.1f}",
                ) if x)
            fig.add_trace(go.Scatter(
                x=[r["a"]["w"] for r in rows], y=labels, mode="markers",
                name="Position A (first stance)",
                marker=dict(color=_COLOR_MODEL, size=11,
                            line=dict(color=_SURFACE, width=2)),
                hovertext=[_pos_hover(r, "a") for r in rows], hoverinfo="text",
            ))
            fig.add_trace(go.Scatter(
                x=[r["b"]["w"] for r in rows], y=labels, mode="markers",
                name="Position B (second stance)",
                marker=dict(color="#eb6834", size=11,
                            line=dict(color=_SURFACE, width=2)),
                hovertext=[_pos_hover(r, "b") for r in rows], hoverinfo="text",
            ))
            _apply_layout(fig, "Contested Claims — evidence weight per position",
                          height=max(360, 42 * len(rows) + 170))
            fig.update_layout(
                xaxis_title="Evidence weight (source count × tier weight)",
                yaxis=dict(autorange="reversed"),
                legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
            )
            return self._save_pair(fig, charts_dir, "contested_claims",
                                   "contested_claims")
        except Exception as exc:  # noqa: BLE001
            logger.debug("build_contested_dumbbell_html 失败（跳过该图）：%s", exc)
            return None

    # ============================ 编排入口 ============================

    def build_all(self, report_id: str, report_dir: str,
                  artifacts: Dict[str, Any]) -> List[Dict[str, str]]:
        """WAVE9 plotly-first 编排：把所有可用工件渲染成 HTML+PNG 图表对，落盘 charts/，
        持久化 viz_manifest.json（{"schema_version":2,"items":[...],"skipped":[...]}），
        返回 items 列表（签名不变）。

        artifacts 键（全部可选，缺失即记 skipped['no_input'] 并跳过对应图）：
          forecast              forecast.json（dict）—— scenarios / binary_forecasts
          ensemble              ensemble_forecast.json（dict）—— 情景误差带 + 驱动因子 tornado
          timeline              timeline.json（list 或 {timeline:[...]}）
          actors                actors.json（dict：actors[] + relationships[]）
          quantitative          quantitative.json（list of rows）
          sources               sources.json（list）
          contested             contested.json（list）
          graph_priors          graph_priors.json（{entity: weight}）
          graph_priors_structural  结构先验（graph_priors 缺失时的回退）
          world_state_trajectory  world_state_trajectory.json（dict）
          comparison            comparison.json（dict，matplotlib 专属）
          calibration           校准统计（matplotlib 专属）
          market_price_history  {market_id:[{t,p}]}（缺则回退读 reports/{id}/ 与 handoff/ 同名文件）
          handoff_dir           研究 handoff 目录（定位 handoff/market_price_history.json）

        manifest 每项：{id,path,type,title,caption,source,placement_hint}
          + 可选 png_path（交互式 HTML 图的 kaleido 静态 PNG 对，供 PDF/exec-brief 内嵌）。
        caption 与 title 同值（caption 为旧消费方兼容别名）。

        降级链：plotly 缺失/关闭 → 整族记 skipped 并回退 matplotlib PNG 族；kaleido 缺失/
        运行失败 → HTML 保留、PNG 经 matplotlib 等价图补齐（有等价图时）。总开关
        REPORT_VISUALIZER 关闭 → 返回 [] 且不落盘（degrade-safe）。"""
        items: List[Dict[str, str]] = []
        skipped: List[Dict[str, str]] = []
        if not bool(_cfg("REPORT_VISUALIZER", True)):
            return items
        artifacts = artifacts or {}
        charts_dir = os.path.join(report_dir, "charts")

        # WAVE9：PNG 批处理状态复位（一次 build_all 一批，末尾统一 flush）。
        self._png_jobs = []
        self._png_done = {}
        self._batch_mode = True
        self._kaleido_failed = False
        self._skip_notes = {}

        forecast = artifacts.get("forecast")
        ensemble = artifacts.get("ensemble")
        actors = artifacts.get("actors")
        graph_priors = artifacts.get("graph_priors")
        if not isinstance(graph_priors, dict) or not graph_priors:
            graph_priors = artifacts.get("graph_priors_structural")
        plotly_on = self._interactive_ok()

        def _attempt(item_id: str, source: str, title: str, hint: str,
                     data_ok: bool, fn) -> None:
            """跑一个 plotly 构建器并登记结果/跳过原因（绝不抛）。"""
            if not plotly_on:
                skipped.append({"builder": item_id, "reason": "plotly_unavailable_or_disabled"})
                return
            if not data_ok:
                skipped.append({"builder": item_id, "reason": "no_input"})
                return
            try:
                rel = fn()
            except Exception as exc:  # noqa: BLE001 - 构建器自身已兜底，这里双保险
                logger.debug("可视化构建器 %s 异常：%s", item_id, exc)
                skipped.append({"builder": item_id,
                                "reason": f"exception:{type(exc).__name__}"})
                return
            if not rel:
                # VIZ-GAP2：构建器可能留下结构化跳过说明（密度门 + markdown 表降级）。
                note = self._skip_notes.pop(item_id, None)
                skipped.append({"builder": item_id,
                                **(note or {"reason": "empty_after_parse"})})
                return
            items.append({
                "id": item_id, "path": rel, "type": "html",
                "title": title, "caption": title,
                "source": source, "placement_hint": hint,
            })

        try:
            # ---- (C/D) plotly 主族 ----
            scen_ok = bool(_scenario_data_present(forecast, ensemble))
            _attempt("scenario_probabilities", "forecast",
                     "Scenario Probabilities", "scenarios",
                     scen_ok,
                     lambda: self.build_scenario_bars_html(forecast, charts_dir,
                                                           ensemble=ensemble))
            bfs = forecast.get("binary_forecasts") if isinstance(forecast, dict) else None
            _attempt("binary_forecast_dotplot", "forecast",
                     "Binary Forecasts — P(yes)", "binary_forecasts",
                     isinstance(bfs, list) and bool(bfs),
                     lambda: self.build_binary_dotplot_html(forecast, charts_dir))
            _attempt("model_vs_market", "forecast",
                     "Model vs Market (binary forecasts)", "binary_forecasts",
                     isinstance(bfs, list) and bool(bfs),
                     lambda: self.build_model_vs_market_html(forecast, charts_dir))
            tl = artifacts.get("timeline")
            _attempt("timeline_lanes", "timeline", "Event Timeline", "timeline",
                     bool(tl),
                     lambda: self.build_timeline_lanes_html(tl, charts_dir))
            # Actor relationship network is relationship *structure* (who relates to
            # whom, source salience) — not reader-facing forecast data. Demote to
            # opt-in exactly like source_mix_sunburst: default reports spend no slot on
            # it, REPORT_META_CHARTS restores it, and the builder stays callable.
            if _meta_charts_on():
                _attempt("actor_network", "actors", "Actor Relationship Network",
                         "actors", bool(actors),
                         lambda: self.build_actor_network_html(actors, charts_dir,
                                                               graph_priors=graph_priors))
            else:
                skipped.append({
                    "builder": "actor_network",
                    "reason": "methodology_not_reader_facing",
                })
            # Internal actor-ranking proxies are useful diagnostics, not customer-facing
            # forecast evidence. Keep the builder callable for compatibility but never
            # spend a default report slot on ordinal influence/salience scores.
            skipped.append({
                "builder": "actor_influence_salience",
                "reason": "internal_proxy_not_reader_facing",
            })
            src = artifacts.get("sources")
            # Source-mix composition is pipeline methodology (how we researched),
            # not reader-facing forecast evidence. Never spend a default report
            # slot on it; REPORT_META_CHARTS restores the old behaviour explicitly.
            if _meta_charts_on():
                _attempt("source_mix_sunburst", "sources",
                         "Source Mix — tier / origin / reachability", "sources",
                         isinstance(src, list) and bool(src),
                         lambda: self.build_source_sunburst_html(src, charts_dir))
            else:
                skipped.append({
                    "builder": "source_mix_sunburst",
                    "reason": "methodology_not_reader_facing",
                })
            quant = artifacts.get("quantitative")
            quant_ok = isinstance(quant, list) and bool(quant)
            _attempt("metric_trajectories", "quantitative",
                     "Key Metric Trajectories (research-extracted)", "quantitative",
                     quant_ok,
                     lambda: self.build_metric_trajectories_html(quant, charts_dir))
            # 技术份额 / 区域对比：DRF2 新字段（technology / region）在时才点亮，builder
            # 内部 <2 技术/区域即返回 None（记 empty_after_parse），degrade-safe。
            _attempt("technology_shares", "quantitative",
                     "Technology Shares by Metric Family", "quantitative",
                     quant_ok,
                     lambda: self.build_technology_shares_html(quant, charts_dir))
            _attempt("regional_comparison", "quantitative",
                     "Regional Comparison by Metric Family", "quantitative",
                     quant_ok,
                     lambda: self.build_regional_comparison_html(quant, charts_dir))
            _attempt("quantitative_claims", "quantitative",
                     "Comparable Forecast Benchmarks", "quantitative",
                     isinstance(quant, list) and bool(quant),
                     lambda: self.build_quantitative_dots_html(quant, charts_dir))
            _attempt("forecast_revisions", "quantitative",
                     "Forecast Revisions Across Published Vintages", "forecast_revisions",
                     isinstance(quant, list) and bool(quant),
                     lambda: self.build_forecast_revisions_html(quant, charts_dir))
            # Weighted keyword frequency is not a sensitivity analysis. A genuine
            # tornado requires measured perturbation deltas, so the old salience proxy
            # remains available only as an explicit diagnostic helper.
            skipped.append({
                "builder": "driver_tornado",
                "reason": "proxy_not_sensitivity_analysis",
            })
            cont = artifacts.get("contested")
            # Source-count × tier-weight is a transparent diagnostic formula but
            # not validated evidence strength. Preserve contested.json for a
            # position/evidence table and keep this chart helper opt-in only.
            skipped.append({
                "builder": "contested_claims",
                "reason": "proxy_evidence_weight_not_reader_facing",
            })
            wst = artifacts.get("world_state_trajectory")
            _attempt("worldstate_trajectory", "world_state_trajectory",
                     "Forecast Outcome-Share Trajectory", "scenarios",
                     bool(wst),
                     lambda: self.build_worldstate_area_html(wst, charts_dir))

            # 市场价格历史折线（多图族，逐图登记）。
            if not self._price_hist_ok():
                skipped.append({"builder": "market_price_history", "reason": "disabled"})
            else:
                price_history = self._load_price_history(report_dir, artifacts)
                ph_anchors = (forecast.get("binary_forecasts")
                              if isinstance(forecast, dict) else None)
                if not (isinstance(price_history, dict) and price_history
                        and isinstance(ph_anchors, list) and ph_anchors):
                    skipped.append({"builder": "market_price_history", "reason": "no_input"})
                elif not plotly_on:
                    skipped.append({"builder": "market_price_history",
                                    "reason": "plotly_unavailable_or_disabled"})
                else:
                    ph_rels = self.render_market_price_history_html(
                        price_history, ph_anchors, charts_dir)
                    if not ph_rels:
                        skipped.append({"builder": "market_price_history",
                                        "reason": "empty_after_parse"})
                    for rel in ph_rels:
                        stem = os.path.splitext(os.path.basename(rel))[0]
                        items.append({
                            "id": stem, "path": rel, "type": "html",
                            "title": "Market-Implied P(yes) History vs Model",
                            "caption": "Market-Implied P(yes) History vs Model",
                            "source": "market_price_history",
                            "placement_hint": "binary_forecasts",
                        })
        finally:
            self._batch_mode = False

        # ---- kaleido PNG 批量导出 + png_path 挂载 ----
        self._flush_png_jobs()
        for it in items:
            png = self._png_done.get(it["id"])
            if png and os.path.exists(os.path.join(report_dir, png)):
                it["png_path"] = png

        # ---- (B) matplotlib 回退族：为缺 PNG 对的核心图补静态图（PDF/exec-brief 需要），
        # plotly 整族缺席时这些图自身就是 manifest 项。comparison/calibration 无 plotly 等价，
        # 始终由 matplotlib 生成。----
        self._run_matplotlib_family(report_dir, charts_dir, artifacts, forecast,
                                    ensemble, items, skipped)

        # ---- 落盘 manifest（原子写；失败不影响已生成的图表）+ INFO 汇总（不再沉默跳过）----
        self._persist_manifest(report_dir, items, skipped,
                               provenance=self._manifest_provenance(artifacts))
        skip_summary = ", ".join(f"{s['builder']}={s['reason']}" for s in skipped) or "-"
        logger.info("报告可视化完成 report=%s：产出 %d 项（png_pair=%d），跳过 %d 项 [%s]",
                    report_id, len(items),
                    sum(1 for it in items if it.get("png_path")),
                    len(skipped), skip_summary)
        return items

    def _run_matplotlib_family(self, report_dir: str, charts_dir: str,
                               artifacts: Dict[str, Any], forecast: Any,
                               ensemble: Any, items: List[Dict[str, str]],
                               skipped: List[Dict[str, str]]) -> None:
        """WAVE9 matplotlib 回退族：
          · scenario/model-vs-market/worldstate/价格历史——仅当对应 plotly 项缺失或缺 PNG 对时
            生成（kaleido 失败/关闭时补 PDF 可嵌静态图）；有 plotly 项则把 PNG 挂到 png_path，
            无则作为独立 png manifest 项。
          · comparison/calibration——无 plotly 等价图，数据在即生成。
        matplotlib 缺失/REPORT_VIZ_CHARTS 关闭 → 整族记 skipped。"""
        if not self._chart_ok():
            skipped.append({"builder": "matplotlib_family",
                            "reason": "matplotlib_unavailable_or_disabled"})
            return

        by_id = {it["id"]: it for it in items}

        def _fallback(item_id: str, source: str, title: str, hint: str, fn) -> None:
            existing = by_id.get(item_id)
            if existing is not None and existing.get("png_path"):
                return  # plotly PNG 对已就位，无需回退
            try:
                rel = fn()
            except Exception as exc:  # noqa: BLE001
                logger.debug("matplotlib 回退 %s 异常：%s", item_id, exc)
                return
            if not rel:
                return
            if existing is not None:
                existing["png_path"] = rel  # HTML 在、PNG 缺 → 挂载回退 PNG
            else:
                items.append({
                    "id": item_id, "path": rel, "type": "png",
                    "title": title, "caption": title,
                    "source": source, "placement_hint": hint,
                })

        _fallback("scenario_probabilities", "forecast",
                  "Scenario Probabilities", "scenarios",
                  lambda: self.build_scenario_bars(forecast, charts_dir,
                                                   ensemble=ensemble))
        _fallback("model_vs_market", "forecast", "Model vs Market",
                  "binary_forecasts",
                  lambda: self.build_model_vs_market(forecast, charts_dir))
        _fallback("timeline_lanes", "timeline", "Event Timeline", "timeline",
                  lambda: self.build_timeline_lanes(
                      artifacts.get("timeline"), charts_dir))
        # actor_network 已降为 opt-in（见 build_all）：仅 REPORT_META_CHARTS 开时才补静态回退，
        # 否则这里会把它作为独立 PNG 项重新塞回 manifest，抵消降位。
        if _meta_charts_on():
            _fallback("actor_network", "actors", "Actor Relationship Network", "actors",
                      lambda: self.build_actor_network(
                          artifacts.get("actors"), charts_dir,
                          graph_priors=(artifacts.get("graph_priors")
                                        or artifacts.get("graph_priors_structural"))))
        _fallback("worldstate_trajectory", "world_state_trajectory",
                  "Forecast Outcome-Share Trajectory", "scenarios",
                  lambda: self.build_worldstate_area(
                      artifacts.get("world_state_trajectory"), charts_dir))

        # 价格历史回退：任何 plotly 价格历史项缺 PNG 时重画 matplotlib 版（同名 stem 覆盖挂载）。
        ph_items = [it for it in items if it["id"].startswith("market_price_history")]
        need_ph = ((not ph_items) or any(not it.get("png_path") for it in ph_items))
        if need_ph and self._price_hist_ok():
            price_history = self._load_price_history(report_dir, artifacts)
            ph_anchors = (forecast.get("binary_forecasts")
                          if isinstance(forecast, dict) else None)
            if isinstance(price_history, dict) and price_history \
                    and isinstance(ph_anchors, list) and ph_anchors:
                for rel in self.render_market_price_history(price_history, ph_anchors,
                                                            charts_dir):
                    stem = os.path.splitext(os.path.basename(rel))[0]
                    existing = by_id.get(stem)
                    if existing is not None:
                        if not existing.get("png_path"):
                            existing["png_path"] = rel
                    else:
                        items.append({
                            "id": stem, "path": rel, "type": "png",
                            "title": "Market-Implied P(yes) History vs Model",
                            "caption": "Market-Implied P(yes) History vs Model",
                            "source": "market_price_history",
                            "placement_hint": "binary_forecasts",
                        })

        # comparison / calibration：matplotlib 专属图（无 plotly 等价）。
        comp = artifacts.get("comparison")
        if comp:
            rel = self.build_comparison_bars(comp, charts_dir)
            if rel:
                items.append({
                    "id": "comparison_bars", "path": rel, "type": "png",
                    "title": "Baseline vs Scenario", "caption": "Baseline vs Scenario",
                    "source": "comparison", "placement_hint": "comparison",
                })
            else:
                skipped.append({"builder": "comparison_bars",
                                "reason": "empty_after_parse"})
        else:
            skipped.append({"builder": "comparison_bars", "reason": "no_input"})
        calib = artifacts.get("calibration")
        if calib:
            rel = self.build_calibration_curve(calib, charts_dir)
            if rel:
                items.append({
                    "id": "calibration_curve", "path": rel, "type": "png",
                    "title": "Calibration Curve", "caption": "Calibration Curve",
                    "source": "calibration", "placement_hint": "calibration",
                })
            else:
                skipped.append({"builder": "calibration_curve",
                                "reason": "empty_after_parse"})
        else:
            skipped.append({"builder": "calibration_curve", "reason": "no_input"})

    # ============================ 落盘助手 ============================

    @staticmethod
    def _write_mermaid(charts_dir: str, stem: str, block: str) -> Optional[str]:
        """把 Mermaid 代码块写到 charts/<stem>.mmd（含 ```mermaid 围栏，便于报告直接内联）。
        返回相对路径 'charts/<stem>.mmd'；失败 → None。"""
        try:
            os.makedirs(charts_dir, exist_ok=True)
            fname = f"{stem}.mmd"
            path = os.path.join(charts_dir, fname)
            tmp = path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                f.write(block)
            os.replace(tmp, path)
            return os.path.join("charts", fname)
        except Exception:  # noqa: BLE001
            return None

    @staticmethod
    def _persist_manifest(report_dir: str, items: List[Dict[str, str]],
                          skipped: Optional[List[Dict[str, str]]] = None,
                          provenance: Optional[Dict[str, Any]] = None) -> None:
        """原子写 reports/{id}/viz_manifest.json（WAVE9 schema v2：
        {"schema_version":2,"items":[...],"skipped":[{builder,reason}]}；
        i9 起可附加 additive 顶层键 "provenance"——消费方按键读取，未知键无害）。
        目录不可写等失败仅 debug 日志（degrade-safe）。"""
        try:
            os.makedirs(report_dir, exist_ok=True)
            path = os.path.join(report_dir, "viz_manifest.json")
            tmp = path + ".tmp"
            payload: Dict[str, Any] = {
                "schema_version": 2,
                "items": items,
                "skipped": skipped or [],
            }
            if isinstance(provenance, dict) and provenance:
                payload["provenance"] = provenance
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
            os.replace(tmp, path)
        except Exception as exc:  # noqa: BLE001
            logger.debug("viz_manifest.json 落盘失败：%s", exc)

    @staticmethod
    def _manifest_provenance(artifacts: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        """i9（LOOP-017「manifests lack policy/input hashes」）：图表溯源块。

        inputs_sha256：每个可 JSON 规范化（sort_keys）的输入工件的 sha256——审计方可以
        证明「这批图出自哪一版 forecast/sim 数据」；不可序列化的键跳过（记入
        unhashed_inputs，绝不冒充覆盖完整）。policy：影响渲染产物的关键旋钮描述符 +
        其自身 sha256。Pure、degrade-safe：任何失败返回 {}（manifest 不带 provenance，
        与 i8 前字节兼容）。"""
        try:
            inputs: Dict[str, str] = {}
            unhashed: List[str] = []
            for key in sorted((artifacts or {}).keys()):
                value = (artifacts or {})[key]
                try:
                    canonical = json.dumps(value, ensure_ascii=False, sort_keys=True,
                                           default=None, separators=(",", ":"))
                except (TypeError, ValueError):
                    unhashed.append(str(key))
                    continue
                inputs[str(key)] = hashlib.sha256(
                    canonical.encode("utf-8")).hexdigest()
            policy = {
                "renderer": "report_visualizer",
                "theme": "WAVE9",
                "schema_version": 2,
                "plotlyjs_inline": bool(_cfg("REPORT_VIZ_PLOTLYJS_INLINE", False)),
            }
            policy_sha = hashlib.sha256(json.dumps(
                policy, ensure_ascii=False, sort_keys=True,
                separators=(",", ":")).encode("utf-8")).hexdigest()
            out: Dict[str, Any] = {
                "inputs_sha256": inputs,
                "policy": policy,
                "policy_sha256": policy_sha,
            }
            if unhashed:
                out["unhashed_inputs"] = unhashed
            return out
        except Exception:  # noqa: BLE001 — 溯源是旁路增强
            return {}

    @staticmethod
    def _load_price_history(report_dir: str, artifacts: Dict[str, Any]) -> Dict[str, Any]:
        """PM-6：汇集市场价格历史 {market_id:[{t,p}]}。优先级：artifacts['market_price_history']
        （dict，已加载）> reports/{id}/market_price_history.json > handoff/market_price_history.json
        （artifacts['handoff_dir'] 指定）。同 market_id 以高优先级为准，文件仅补缺键。任何缺失/
        畸形静默跳过（degrade-safe），全无 → {}。"""
        merged: Dict[str, Any] = {}

        def _absorb(d: Any) -> None:
            if isinstance(d, dict):
                for k, v in d.items():
                    key = str(k)
                    if key not in merged and isinstance(v, list):
                        merged[key] = v

        arts = artifacts or {}
        # ① artifacts 内联 dict 最高优先，先 absorb。
        _absorb(arts.get("market_price_history"))
        # ② 文件来源（仅补 artifacts 缺失的 market_id）。
        candidates: List[str] = [os.path.join(report_dir or "", "market_price_history.json")]
        hd = arts.get("handoff_dir")
        if isinstance(hd, str) and hd.strip():
            candidates.append(os.path.join(hd, "market_price_history.json"))
        for path in candidates:
            try:
                if path and os.path.exists(path):
                    with open(path, "r", encoding="utf-8") as f:
                        _absorb(json.load(f))
            except Exception:  # noqa: BLE001
                continue  # 单个文件坏了不影响其余来源
        return merged


# ─────────────────────────────────────────────────────────────────────────────
# 模块级解析助手（供 Mermaid/图表族共享，纯函数）
# ─────────────────────────────────────────────────────────────────────────────
# 'A --[CAUSES,+,strong]--> B' 形式的因果字符串解析正则。
_CAUSAL_STR_RE = re.compile(r"^\s*(.+?)\s*--\[(.*?)\]-->\s*(.+?)\s*$")


def _parse_causal_item(item: Any) -> List[Tuple[str, str, str]]:
    """把单个因果项解析成 [(source, target, label)]。支持：
      · 字符串 'A --[CAUSES,+,strong]--> B'（方括号内逗号分隔 类型,符号,强度）；
      · 字符串 'A --[CAUSES]--> B'（仅类型）；
      · dict {source,target, relation/type, sign, strength}；
      · dict {path:[a,b,c], relation:...}（多跳，两两成边）。
    无法解析 → []。"""
    try:
        if isinstance(item, str):
            m = _CAUSAL_STR_RE.match(item)
            if not m:
                return []
            src, inner, tgt = m.group(1), m.group(2), m.group(3)
            parts = [p.strip() for p in inner.split(",") if p.strip()]
            typ = parts[0].upper() if parts else "REL"
            label = _REL_LABEL_EN.get(typ, typ)
            extras = parts[1:]
            sign = ""
            strength = ""
            for e in extras:
                el = e.lower()
                if el in _SIGN_TOKEN:
                    sign = _SIGN_TOKEN[el]
                else:
                    strength = e
            tail = "/".join(x for x in (sign, strength) if x)
            full = f"{label} {tail}".strip() if tail else label
            return [(src.strip(), tgt.strip(), full)]

        if isinstance(item, dict):
            # 多跳 path
            path = item.get("path") or item.get("nodes")
            typ = str(item.get("relation") or item.get("type") or item.get("rel") or "").strip().upper()
            label = _REL_LABEL_EN.get(typ, typ or "REL")
            sign = _sign_of(item)
            strength = str(item.get("strength") or "").strip()
            tail = "/".join(x for x in (sign, strength) if x)
            full = f"{label} {tail}".strip() if tail else label
            if isinstance(path, list) and len(path) >= 2:
                edges: List[Tuple[str, str, str]] = []
                for a, b in zip(path, path[1:]):
                    sa, sb = str(a).strip(), str(b).strip()
                    if sa and sb:
                        edges.append((sa, sb, full))
                return edges
            src = str(item.get("source") or item.get("from") or "").strip()
            tgt = str(item.get("target") or item.get("to") or "").strip()
            if src and tgt:
                return [(src, tgt, full)]
        return []
    except Exception:  # noqa: BLE001
        return []


def _normalize_clusters(coalition: Any) -> List[Tuple[str, List[str]]]:
    """把灵活的派系入参规整为 [(label, [members])]。无有效派系 → []。"""
    try:
        if isinstance(coalition, dict):
            clusters = (coalition.get("clusters") or coalition.get("coalitions")
                        or coalition.get("factions") or coalition.get("groups"))
        else:
            clusters = coalition
        if not isinstance(clusters, list) or not clusters:
            return []
        out: List[Tuple[str, List[str]]] = []
        for i, c in enumerate(clusters, 1):
            if isinstance(c, dict):
                members = c.get("members") or c.get("agents") or c.get("names") or []
                label = str(c.get("label") or c.get("name") or f"Faction {i}")
            elif isinstance(c, (list, tuple, set)):
                members = list(c)
                label = f"Faction {i}"
            else:
                continue
            members = [str(m) for m in members if str(m).strip()]
            if members:
                out.append((label, members))
        return out
    except Exception:  # noqa: BLE001
        return []


def _first_float(d: Dict[str, Any], keys: Tuple[str, ...]) -> Optional[float]:
    """按 keys 顺序取第一个可解析为 float 的值。全部缺失/不可解析 → None。"""
    if not isinstance(d, dict):
        return None
    for k in keys:
        if k in d:
            v = _to_float(d.get(k))
            if v is not None:
                return v
    return None


def _normalize_price_anchors(anchors: Any,
                             price_history: Dict[str, Any]) -> List[Dict[str, Any]]:
    """PM-6：把锚点列表规整为可绘制条目（供 render_market_price_history）。每项抽出
    {market_id, label, model_p, market_p, divergence, series}，其中 series 为按时间升序的
    [(datetime, p)] 列表（p 夹逼到 [0,1]）。

    锚点项兼容两种形态：① 二元预测 dict（含 market_anchor 子 dict）；② 已抽平 dict
    （market_id/probability/... 直接在顶层）。仅保留 market_id 命中 price_history 且有效历史点
    ≥2 的锚点，按首次出现顺序去重（确定性）。model_p 取二元预测的 probability；market_p 取
    market_anchor.implied_yes_prob，缺失则用最新历史点；divergence 取 market_anchor.divergence，
    缺失则由 model_p − market_p 现算。任何畸形 → 跳过该项，绝不抛。"""
    if not isinstance(anchors, list):
        return []
    import datetime as _dt
    out: List[Dict[str, Any]] = []
    seen: set = set()
    for it in anchors:
        if not isinstance(it, dict):
            continue
        anchor = it.get("market_anchor") if isinstance(it.get("market_anchor"), dict) else it
        market_id = str(anchor.get("market_id") or it.get("market_id") or "").strip()
        if not market_id or market_id in seen:
            continue
        raw_series = price_history.get(market_id)
        if not isinstance(raw_series, list) or len(raw_series) < 2:
            continue
        pts: List[Tuple[Any, float]] = []
        for pt in raw_series:
            if not isinstance(pt, dict):
                continue
            tf = _to_float(pt.get("t"))
            p = _to_float(pt.get("p"))
            if tf is None or p is None:
                continue
            try:
                dt = _dt.datetime.utcfromtimestamp(tf)
            except (OverflowError, OSError, ValueError):
                continue  # 病态时间戳跳过
            pts.append((dt, max(0.0, min(1.0, p))))
        if len(pts) < 2:
            continue
        pts.sort(key=lambda x: x[0])
        model_p = _first_float(it, ("probability", "model_prob", "model_p", "p"))
        market_p = _first_float(anchor, ("implied_yes_prob", "implied_prob"))
        if market_p is None:
            market_p = pts[-1][1]  # 缺市场概率 → 用最新历史点近似
        divergence = _first_float(anchor, ("divergence",))
        if divergence is None and model_p is not None and market_p is not None:
            divergence = model_p - market_p
        label = _mpl_text(it.get("id") or it.get("statement") or it.get("label") or market_id,
                          fallback=market_id, max_len=52)
        out.append({"market_id": market_id, "label": label, "model_p": model_p,
                    "market_p": market_p, "divergence": divergence, "series": pts})
        seen.add(market_id)
    return out


# ─────────────────────────────────────────────────────────────────────────────
# WAVE9 模块级助手（纯函数）：情景行抽取、时间线整备、角色名归一、网络布局。
# ─────────────────────────────────────────────────────────────────────────────

_SCENARIO_INTERVAL_STYLES = {
    "ensemble": {
        "label": "Ensemble spread",
        "color": "#2b2b2b",
        "marker": "o",
        "plotly_symbol": "circle",
        "capsize": 5,
    },
    "declared": {
        "label": "Declared uncertainty interval",
        "color": "#b26a00",
        "marker": "D",
        "plotly_symbol": "diamond",
        "capsize": 4,
    },
    # VIZ-GAP1：forecast.json 的自一致性池化区间（K 次抽取的 ±spread）。颜色取分类槽 5
    # 紫（与柱蓝/近黑/橙棕成对均过 CVD 相邻校验），标记方形作次级编码。
    "self_consistency": {
        "label": "Self-consistency spread",
        "color": "#4a3aa7",
        "marker": "s",
        "plotly_symbol": "square",
        "capsize": 4,
    },
}

# 情景区间来源的绘制/图例顺序（matplotlib 与 plotly 构建器共用，确定性）。
_SCENARIO_INTERVAL_ORDER = ("ensemble", "declared", "self_consistency")

_SCENARIO_INTERVAL_TITLES = {
    "ensemble": "Scenario Probabilities (ensemble spread)",
    "declared": "Scenario Probabilities (declared uncertainty intervals)",
    "self_consistency": "Scenario Probabilities (self-consistency spread)",
}


def _scenario_rows_with_interval(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [
        row for row in rows
        if row.get("lo") is not None and row.get("hi") is not None
        and row["hi"] > row["lo"]
    ]


def _scenario_interval_title(rows: List[Dict[str, Any]]) -> str:
    """Describe plotted interval provenance without overstating its evidence."""
    sources = {row.get("interval_source") for row in _scenario_rows_with_interval(rows)}
    if len(sources) == 1:
        title = _SCENARIO_INTERVAL_TITLES.get(next(iter(sources)))
        if title:
            return title
    if len(sources) > 1:
        return "Scenario Probabilities (intervals by source)"
    return "Scenario Probabilities"


def _scenario_interval_subtitle(rows: List[Dict[str, Any]], forecast: Any = None) -> str:
    """VIZ-GAP1(b)：一句话区间溯源副标题；裸点估计必须明说，不得沉默呈现为确定性。"""
    with_interval = _scenario_rows_with_interval(rows)
    if not with_interval:
        return "point estimates only — no interval data supplied"
    sources = {row.get("interval_source") for row in with_interval}
    partial = "" if len(with_interval) == len(rows) else "; unmarked bars are point estimates"
    if sources == {"self_consistency"}:
        prov = forecast.get("interval_provenance") if isinstance(forecast, dict) else None
        k = spread = None
        if isinstance(prov, dict):
            k = _to_float(prov.get("k"))
            spread = _to_float(prov.get("spread"))
        if k is None and isinstance(forecast, dict):
            k = _to_float(forecast.get("self_consistency_k"))
            spread = _to_float(forecast.get("self_consistency_mean_spread"))
        if k and spread is not None:
            return (f"interval: ±{spread * 100:.1f}pp spread from k={int(k)} "
                    f"self-consistency draws{partial}")
        return f"interval: ± spread across self-consistency draws{partial}"
    if sources == {"ensemble"}:
        return f"interval: min–max across ensemble runs{partial}"
    if sources == {"declared"}:
        return f"interval: declared p_low–p_high from forecast.json{partial}"
    return f"intervals: mixed provenance — see legend{partial}"


def _extract_scenario_rows(forecast: Any, ensemble: Any = None) -> List[Dict[str, Any]]:
    """Return one coherent scenario distribution for both static and Plotly charts.

    ``forecast.json`` is the canonical published distribution.  Ensemble runs may use different
    free-form names or even surface a different scenario taxonomy, so their rows MUST NOT be
    appended to the canonical rows: doing so produced charts whose bars summed to far more than
    100 percent.  An ensemble row now contributes uncertainty metadata only when its stable ID or
    normalized name/alias exactly matches a canonical scenario.

    If no canonical forecast scenarios exist, a coherent ensemble-only distribution may be used;
    in that fallback the normalized ``probability`` field is preferred over the diagnostic
    ``mean_probability``.  Every valid interval carries explicit ``interval_source`` and
    ``interval_label`` fields: canonical p_low/p_high are ``declared`` while matched ensemble
    min/max are ``ensemble``.  Returns rows sorted by probability and capped at 14 entries.
    Invalid probabilities are ignored and malformed input degrades to ``[]``.
    """

    def _probability(value: Any) -> Optional[float]:
        number = _to_float(value)
        if number is None or not 0.0 <= number <= 1.0:
            return None
        return number

    def _identity_parts(item: Dict[str, Any]) -> Tuple[set, set]:
        aliases = item.get("aliases") if isinstance(item.get("aliases"), list) else []
        ids = {
            _norm_key(item.get(key))
            for key in ("id", "scenario_id", "scenarioId", "slug")
            if _norm_key(item.get(key))
        }
        names = {
            re.sub(r"[^\w\u3400-\u9fff]+", " ", str(value or "").casefold()).strip()
            for value in (item.get("name"), item.get("label"), *aliases)
            if str(value or "").strip()
        }
        return ids, {name for name in names if name}

    def _uncertainty(item: Dict[str, Any], p: float) -> Tuple[Any, Any, Any, Any]:
        lo = _probability(_first_float(item, ("min", "p_low", "prob_low", "ci_low", "low")))
        hi = _probability(_first_float(item, ("max", "p_high", "prob_high", "ci_high", "high")))
        if lo is None or hi is None or not lo <= p <= hi:
            lo, hi = None, None
        stdev = _to_float(item.get("stdev") if item.get("stdev") is not None
                          else item.get("std"))
        support = _probability(item.get("support_ratio"))
        return lo, hi, stdev, support

    rows: List[Dict[str, Any]] = []
    try:
        ens_list = ensemble.get("scenarios") if isinstance(ensemble, dict) else None
        ensemble_rows = [item for item in (ens_list or []) if isinstance(item, dict)]
        scenarios = forecast.get("scenarios") if isinstance(forecast, dict) else forecast
        canonical = [item for item in (scenarios or []) if isinstance(item, dict)] \
            if isinstance(scenarios, list) else []

        if canonical:
            ensemble_identity = [(_identity_parts(item), item) for item in ensemble_rows]
            used_ensemble: set = set()
            for i, scenario in enumerate(canonical, 1):
                p = _probability(_first_float(scenario, ("probability", "prob", "p")))
                if p is None:
                    continue
                ids, names = _identity_parts(scenario)
                match = None
                for index, ((candidate_ids, candidate_names), candidate) in enumerate(
                        ensemble_identity):
                    if index in used_ensemble:
                        continue
                    if (ids and candidate_ids and ids & candidate_ids) or (names & candidate_names):
                        match = (index, candidate)
                        break
                source = scenario
                if match is not None:
                    used_ensemble.add(match[0])
                    source = match[1]
                # VIZ-GAP1：canonical 情景可携带显式 interval_source（自一致性池化
                # 的 ±spread）；没有该标记的自带区间仍按模型声明呈现。
                own_source = (
                    "self_consistency"
                    if str(scenario.get("interval_source") or "").strip().lower()
                    == "self_consistency_spread" else "declared"
                )
                lo, hi, stdev, support = _uncertainty(source, p)
                interval_source = "ensemble" if match is not None else own_source
                if lo is None or hi is None:
                    # A matching ensemble row without usable bounds is not evidence that the
                    # canonical p_low/p_high came from an ensemble. Preserve those declared
                    # bounds explicitly instead of dropping or laundering their provenance.
                    lo, hi, _, _ = _uncertainty(scenario, p)
                    interval_source = own_source
                    stdev, support = None, None
                if lo is None or hi is None:
                    interval_source = None
                rows.append({
                    "name": _html_text(scenario.get("name") or scenario.get("label"),
                                       fallback=f"Scenario {i}", max_len=56),
                    "p": p, "lo": lo, "hi": hi,
                    "stdev": stdev if interval_source == "ensemble" else None,
                    "support": support if interval_source == "ensemble" else None,
                    "interval_source": interval_source,
                    "interval_label": (
                        _SCENARIO_INTERVAL_STYLES[interval_source]["label"]
                        if interval_source else None
                    ),
                })
        elif ensemble_rows:
            for i, scenario in enumerate(ensemble_rows, 1):
                # ``probability`` is the normalized published ensemble distribution;
                # ``mean_probability`` is a per-bucket diagnostic and need not sum to one.
                p = _probability(_first_float(
                    scenario, ("probability", "prob", "p", "mean_probability"),
                ))
                if p is None:
                    continue
                lo, hi, stdev, support = _uncertainty(scenario, p)
                interval_source = "ensemble" if lo is not None and hi is not None else None
                rows.append({
                    "name": _html_text(scenario.get("name") or scenario.get("label"),
                                       fallback=f"Scenario {i}", max_len=56),
                    "p": p, "lo": lo, "hi": hi,
                    "stdev": stdev, "support": support,
                    "interval_source": interval_source,
                    "interval_label": (
                        _SCENARIO_INTERVAL_STYLES[interval_source]["label"]
                        if interval_source else None
                    ),
                })
            # Old/malformed ensemble schemas may expose only diagnostic bucket means.  When
            # semantic alignment failed those means can total 2x or 3x; omitting the chart is
            # safer than presenting a distribution that is mathematically impossible.
            total = sum(row["p"] for row in rows)
            if rows and not 0.95 <= total <= 1.05:
                return []
        rows.sort(key=lambda r: (-r["p"], r["name"]))
        return rows[:14]
    except Exception:  # noqa: BLE001
        return []


def _scenario_data_present(forecast: Any, ensemble: Any) -> bool:
    """build_all 的输入在位判定（区分 no_input 与 empty_after_parse）。"""
    if isinstance(ensemble, dict) and isinstance(ensemble.get("scenarios"), list) \
            and ensemble.get("scenarios"):
        return True
    if isinstance(forecast, dict) and isinstance(forecast.get("scenarios"), list) \
            and forecast.get("scenarios"):
        return True
    return isinstance(forecast, list) and bool(forecast)


_FLEX_DATE_RE = re.compile(r"(\d{4})(?:-(\d{1,2}))?(?:-(\d{1,2}))?")
_QUARTER_DATE_RE = re.compile(r"(\d{4})-Q([1-4])(?:-Q([1-4]))?", re.IGNORECASE)


def _parse_flex_date(s: Any):
    """Parse mixed-precision timeline dates without rewriting valid days.

    Exact ``YYYY-MM-DD`` values round-trip unchanged.  Month/year values and
    quarter windows are placed at their interval midpoint for plotting while
    callers retain the original label and precision for display.
    """
    import datetime as _dt
    import calendar as _calendar

    raw = str(s or "").strip()
    quarter = _QUARTER_DATE_RE.fullmatch(raw)
    if quarter:
        try:
            year = int(quarter.group(1))
            q_start = int(quarter.group(2))
            q_end = int(quarter.group(3) or q_start)
            if not (1900 <= year <= 2200) or q_end < q_start:
                return None
            start = _dt.date(year, (q_start - 1) * 3 + 1, 1)
            end_month = q_end * 3
            end = _dt.date(year, end_month, _calendar.monthrange(year, end_month)[1])
            midpoint = start + (end - start) // 2
            return _dt.datetime.combine(midpoint, _dt.time())
        except (TypeError, ValueError):
            return None

    m = _FLEX_DATE_RE.fullmatch(raw)
    if not m:
        return None
    try:
        year = int(m.group(1))
        month = int(m.group(2)) if m.group(2) else 6
        day = int(m.group(3)) if m.group(3) else 15
        if not (1900 <= year <= 2200 and 1 <= month <= 12):
            return None
        return _dt.datetime(year, month, day)
    except (TypeError, ValueError):
        return None


def _flex_date_precision(s: Any) -> str:
    raw = str(s or "").strip()
    quarter = _QUARTER_DATE_RE.fullmatch(raw)
    if quarter:
        return "quarter_range" if quarter.group(3) else "quarter"
    match = _FLEX_DATE_RE.fullmatch(raw)
    if not match:
        return "unknown"
    if match.group(3):
        return "day"
    if match.group(2):
        return "month"
    return "year"


def _trajectory_row_date(row: Any):
    """CAL-TEMPORAL：日历模式轨迹行（world_state_trajectory schema v3）的横轴日期。

    优先 as_of（第 0 行为 as_of_date，其余行等于 period_end），回退 period_end；
    严格 ISO YYYY-MM-DD 解析（不用 _parse_flex_date——轨迹契约只接受日精度，且不应把
    月/季度精度的可视化中点解释成真实状态日期）。
    解析失败 → None，调用方对任一行失败即整体回退旧的轮次横轴（degrade-safe）。"""
    import datetime as _dt
    if not isinstance(row, dict):
        return None
    raw = row.get("as_of") or row.get("period_end")
    if not raw:
        return None
    try:
        return _dt.date.fromisoformat(str(raw).strip()[:10])
    except (TypeError, ValueError):
        return None


# Reader-facing forecast timeline lanes.  The prior taxonomy was hard-coded to
# semiconductors (fabs/HBM/export controls), which sent most EV, energy, and
# consumer milestones to ``Other``.  These domain-neutral lanes preserve the
# question a reader is asking: what changed in policy, adoption, supply, or the
# competitive/technical route?  Order is precedence; first match wins.
_TL_CATEGORIES: List[Tuple[str, Tuple[str, ...]]] = [
    ("Policy & Regulation",
     ("mandate", "regulation", "standard", "credit", "tax", "subsid", "incentive",
      "tariff", "sanction", "export control", "export-control", "export restriction",
      "entity list", "license", "ban", "waiver", "executive order", "act signed",
      "emission", "zero-emission", "local content", "trade rule", "court", "ruling")),
    ("Geopolitics",
     ("taiwan strait", "invasion", "blockade", "war", "military", "ceasefire",
      "geopolit", "election", "president", "minister")),
    ("Consumer & Adoption",
     ("sales", "adoption", "penetration", "market share", "registrations", "consumer",
      "buyer", "affordab", "price parity", "charging access", "fleet", "demand")),
    ("Supply Chain & Economics",
     ("lithium", "cobalt", "nickel", "graphite", "rare earth", "mining", "refining",
      "supply", "shortage", "surplus", "inventory", "cost", "price", "capex",
      "funding", "bankrupt", "revenue", "earnings", "investment", "acquisition",
      "merger", "billion", "trillion")),
    ("Companies & Technology",
     ("battery", "cell", "cathode", "anode", "solid-state", "sodium-ion", "lfp",
      "charging", "charger", "vehicle", "automaker", "factory", "plant", "launch",
      "production", "capacity", "platform", "software", "autonomous", "announce",
      "fab", "chip", "semiconductor")),
]


def _tl_category(text: str) -> str:
    low = text.lower()
    for cat, kws in _TL_CATEGORIES:
        if any(kw in low for kw in kws):
            return cat
    return "Other"


def _prepare_timeline_events(rows: List[Any]) -> List[Dict[str, Any]]:
    """时间线事件整备：键名兼容（date/日期/when，event/事件/text/label/description）、
    宽松日期解析（不可解析日期的行剔除）、同日高词元重合去重（Jaccard ≥ 0.55，保留首现）、
    显著度评分（含数字/货币符号 + 文本长度），超上限（REPORT_VIZ_TIMELINE_MAX_EVENTS，
    默认 40）按显著度截断，最终按时间升序。"""
    events: List[Dict[str, Any]] = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        date_raw = str(r.get("date") or r.get("日期") or r.get("when") or "").strip()
        text = str(r.get("event") or r.get("事件") or r.get("text")
                   or r.get("label") or r.get("description") or "").strip()
        if not text:
            continue
        dt = _parse_flex_date(date_raw)
        if dt is None:
            continue
        toks = _tokens(text)
        # 同日近重去重（诊断实锤：同日 CHIPS Act / 2029-01-01 各出现两次）。
        dup = False
        for e in events:
            if e["dt"] == dt and _jaccard(toks, e["tokens"]) >= 0.55:
                dup = True
                break
        if dup:
            continue
        score = (1.0 if re.search(r"[$%€¥]|\d", text) else 0.0) + min(len(text) / 160.0, 1.0)
        events.append({"date": date_raw or dt.strftime("%Y-%m-%d"), "dt": dt,
                       "precision": _flex_date_precision(date_raw),
                       "text": text, "tokens": toks, "score": score,
                       "cat": _tl_category(text)})
    if not events:
        return []
    cap = int(_cfg("REPORT_VIZ_TIMELINE_MAX_EVENTS", 40) or 40)
    if cap > 0 and len(events) > cap:
        events = sorted(events, key=lambda e: -e["score"])[:cap]
    events.sort(key=lambda e: (e["dt"], e["text"]))
    return events


def _norm_key(name: Any) -> str:
    """实体名归一键：casefold + 折叠空白 + 去首尾标点。"""
    return re.sub(r"\s+", " ", str(name or "")).strip(" .,;:'\"()").casefold()


def _canonical_actor_map(actor_list: Any) -> Dict[str, str]:
    """从 actors[]（name + aliases）构建 归一键 → 规范名 映射，用于把关系端点上的
    'Samsung'/'Samsung Electronics' 类重复实体合并到同一节点。确定性：按名字排序遍历。"""
    canon: Dict[str, str] = {}
    names: List[str] = []
    if isinstance(actor_list, list):
        for a in actor_list:
            if not isinstance(a, dict):
                continue
            name = str(a.get("name") or "").strip()
            if not name:
                continue
            names.append(name)
            canon[_norm_key(name)] = name
            aliases = a.get("aliases")
            if isinstance(aliases, list):
                for al in aliases:
                    k = _norm_key(al)
                    if k and k not in canon:
                        canon[k] = name
    return canon


def _canonicalize(name: str, canon: Dict[str, str]) -> str:
    """把端点名映射到规范名：精确（含 alias）→ 前缀/包含（≥4 字符，唯一命中才归并，
    多个候选取最长规范名保证确定性）→ 原名。"""
    if not name:
        return ""
    key = _norm_key(name)
    if key in canon:
        return canon[key]
    if len(key) >= 4:
        hits = []
        for k, v in canon.items():
            if (key in k or k in key) and min(len(key), len(k)) >= 4:
                hits.append(v)
        if hits:
            return sorted(set(hits), key=lambda v: (-len(v), v))[0]
    return name


def _network_layout(nodes: List[str],
                    edges: List[Tuple[str, str, str, str]]) -> Dict[str, Tuple[float, float]]:
    """网络布局：networkx spring（固定 seed=7，k=0.9/√n，确定性）；networkx 缺失 → 按度数
    降序的确定性同心圆回退（高度数在内圈）。"""
    if NETWORKX_AVAILABLE:
        try:
            g = nx.Graph()
            g.add_nodes_from(nodes)
            g.add_edges_from([(s, t) for s, t, _typ, _sg in edges])
            n = max(1, g.number_of_nodes())
            pos = nx.spring_layout(g, seed=7, k=0.9 / math.sqrt(n), iterations=60)
            return {str(k): (float(v[0]), float(v[1])) for k, v in pos.items()}
        except Exception as exc:  # noqa: BLE001
            logger.debug("networkx spring 布局失败，回退同心圆：%s", exc)
    # 确定性同心圆回退：度数高者在内圈。
    degree: Dict[str, int] = dict.fromkeys(nodes, 0)
    for s, t, _typ, _sg in edges:
        degree[s] = degree.get(s, 0) + 1
        degree[t] = degree.get(t, 0) + 1
    ordered = sorted(nodes, key=lambda n: (-degree.get(n, 0), n))
    pos: Dict[str, Tuple[float, float]] = {}
    ring = 0
    idx = 0
    ring_cap = 6
    for name in ordered:
        radius = 0.35 + 0.55 * ring
        theta = 2 * math.pi * idx / ring_cap
        pos[name] = (radius * math.cos(theta), radius * math.sin(theta))
        idx += 1
        if idx >= ring_cap:
            ring += 1
            idx = 0
            ring_cap = int(ring_cap * 1.8)
    return pos
