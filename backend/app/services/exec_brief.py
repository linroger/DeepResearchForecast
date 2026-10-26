"""DELIV-1 执行交付物构建器（Executive deliverables）。

从一份**已完成**报告的磁盘工件里，纯确定性地（NO LLM——只抽取，不生成）派生三样面向决策者
的轻量交付物：

  · exec_brief.md   —— 一页纸高管简报：预测问题 + 3 句论点（从成稿执行摘要段落确定性抽取）+
                       TOP 二元预测表（≤8 行：陈述 / 概率±集成离散 / 市场锚 Δ / 判定日期）+
                       关键情景概率 + 最承重的一张图（引用 scenario-bars PNG）+ 3 个带日期的
                       观察指标 + 一行诚实声明（pipeline_health / 模拟运行健康，若可得）。
  · exec_brief.pdf  —— 复用 ReportManager 现成的 pandoc 引擎选择 + PyMuPDF 回退（**去掉 --toc、
                       收紧边距**做单页版式），惰性构建 + 内容与发布代际绑定缓存。
  · digest.md       —— ~15 行 newsletter 式摘要：标题 + 3 条要点 + 头号预测 + 最大市场分歧 +
                       链接路径。

**双语**：译文读取已准入的不可变发布代际；无代际指针时保留历史 sidecar 读取兼容。
译文简报与 PDF 写入内容寻址派生目录，旧简报和已发布报告均不覆盖。

可选字段缺失时省略对应片段；所选发布代际失效或构建期间源发生变化时显式拒绝，绝不复用过期简报。总开关 REPORT_EXEC_BRIEF 关闭时
build() 返回空 dict、不落盘。
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ..config import Config
from ..utils.logger import get_logger
from . import sim_provenance as _sp

logger = get_logger('mirofish.services.exec_brief')


# ─────────────────────────── 语言 & 小节标签（单一真源）───────────────────────────

# 中/英两套小节标签。简报语言由成稿（或译文）的 CJK 占比确定性判定；未命中中文即英文。
_LABELS: Dict[str, Dict[str, str]] = {
    "en": {
        "brief_title": "Executive Brief",
        "question": "Forecast question",
        "thesis": "Thesis",
        "top_forecasts": "Top binary forecasts",
        "c_forecast": "Forecast",
        "c_prob": "Probability",
        "c_market": "Market Δ",
        "c_resolves": "Resolves",
        "scenarios": "Key scenario probabilities",
        "chart": "Most load-bearing chart",
        "watch": "What to watch",
        "honesty": "Honesty note",
        "digest_title": "Digest",
        "top_forecast": "Top forecast",
        "biggest_divergence": "Biggest market divergence",
        "links": "Links",
        "no_data": "_No structured forecast available._",
        "prob_sep": "±",
        "ph_ok": "pipeline health ok",
        "ph_degraded": "pipeline health degraded",
        "ph_failed": "pipeline health failed",
        "quality_pass": "forecast quality gate passed",
        "quality_fail": "forecast quality gate not passed",
        "coverage": "citation coverage",
        "sim_line": _sp.BRIEF_SIM_LINE_EN,
        "organic": "organic actions",
        "detail_sep": ", ",
        "gen_note": "Deterministically extracted from the full report — no model generation.",
        "indicators": "Key official indicators",
        "c_indicator": "Indicator",
        "c_latest": "Latest observed",
        "c_period": "Period",
        "c_change": "Year-over-year change",
        "c_source": "Source",
        "w_latest": "latest",
        "w_threshold": "threshold",
        "w_base_rate": "historical base rate",
    },
    "zh": {
        "brief_title": "高管简报",
        "question": "预测问题",
        "thesis": "核心论点",
        "top_forecasts": "头部二元预测",
        "c_forecast": "预测陈述",
        "c_prob": "概率",
        "c_market": "市场 Δ",
        "c_resolves": "判定日期",
        "scenarios": "关键情景概率",
        "chart": "最承重的图表",
        "watch": "观察指标",
        "honesty": "诚实声明",
        "digest_title": "速览",
        "top_forecast": "头号预测",
        "biggest_divergence": "最大市场分歧",
        "links": "链接",
        "no_data": "_暂无结构化预测数据。_",
        "prob_sep": "±",
        "ph_ok": "管线健康 ok",
        "ph_degraded": "管线健康 degraded",
        "ph_failed": "管线健康 failed",
        "quality_pass": "预测质量门通过",
        "quality_fail": "预测质量门未通过",
        "coverage": "引用覆盖率",
        "sim_line": _sp.BRIEF_SIM_LINE_ZH,
        "organic": "条有机行为",
        "detail_sep": "，",
        "gen_note": "全部从成稿确定性抽取——无模型生成。",
        "indicators": "关键官方指标",
        "c_indicator": "指标",
        "c_latest": "最新观测值",
        "c_period": "期间",
        "c_change": "同比变化",
        "c_source": "来源",
        "w_latest": "最新",
        "w_threshold": "阈值",
        "w_base_rate": "历史基率",
    },
}

# 执行摘要类小节标题关键词（小写，中英并列）——按文档顺序命中首个即取其正文首段作论点来源。
_SUMMARY_HEADING_KEYS = (
    "executive summary", "exec summary", "framework overview",
    "framework & synthesis", "framework and synthesis", "synthesis",
    "key findings", "bottom line", "thesis", "key takeaways", "overview",
    "执行摘要", "核心结论", "关键结论", "框架概览", "综述", "摘要", "概要", "总览",
)

# 英文月份名 → 月序（日期抽取/排序用；缩写与全称都覆盖）。
_MONTHS = {
    "jan": 1, "january": 1, "feb": 2, "february": 2, "mar": 3, "march": 3,
    "apr": 4, "april": 4, "may": 5, "jun": 6, "june": 6, "jul": 7, "july": 7,
    "aug": 8, "august": 8, "sep": 9, "sept": 9, "september": 9, "oct": 10,
    "october": 10, "nov": 11, "november": 11, "dec": 12, "december": 12,
}
_MONTH_ALT = "|".join(sorted(_MONTHS.keys(), key=len, reverse=True))
# 「November 3, 2026」/「Nov 3 2026」这类完整日期。
_DATE_MDY_RE = re.compile(rf"\b({_MONTH_ALT})\s+(\d{{1,2}}),?\s+(20\d{{2}})\b", re.I)
# 「December 2026」这类月-年（无日）。
_DATE_MY_RE = re.compile(rf"\b({_MONTH_ALT})\s+(20\d{{2}})\b", re.I)
# ISO「2026-11-03」。
_DATE_ISO_RE = re.compile(r"\b(20\d{2})-(\d{2})-(\d{2})\b")

# 句子切分终止符（中英）。用于从段落抽取前 N 句作论点。
_SENT_SPLIT_RE = re.compile(r"(?<=[.!?。！？])\s+")
# CJK 字符区间（判定简报语言）。
_CJK_RE = re.compile(r"[一-鿿]")


def _cfg(name: str, default: Any) -> Any:
    """读 Config 属性，缺失回退默认（degrade-safe，与仓内其它模块一致）。"""
    return getattr(Config, name, default)


# ─────────────────────────── 底层读取助手（全部 degrade-safe）───────────────────────────

def _read_json(path: str) -> Optional[Any]:
    """读 JSON；文件缺失/损坏 → None（绝不抛）。"""
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return None


def _read_text(path: str) -> Optional[str]:
    """读文本；缺失/读失败 → None。"""
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except OSError:
        return None


def _write_text_atomic(path: str, text: str) -> bool:
    """原子写文本（tmp→replace）；目录不可写等失败静默返回 False（degrade-safe）。"""
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp, path)
        return True
    except OSError as e:  # noqa: BLE001
        logger.warning(f"写执行简报工件失败: {path}: {e}")
        return False


def _detect_lang(md: str) -> str:
    """由 CJK 字符占比确定性判定简报语言：CJK 占字母类字符 >20% → 'zh'，否则 'en'。"""
    if not md:
        return "en"
    cjk = len(_CJK_RE.findall(md))
    latin = len(re.findall(r"[A-Za-z]", md))
    total = cjk + latin
    if total == 0:
        return "en"
    return "zh" if (cjk / total) > 0.2 else "en"


def _to_float(v: Any) -> Optional[float]:
    """尽力转 float；失败 → None。"""
    try:
        if v is None:
            return None
        return float(v)
    except (TypeError, ValueError):
        return None


def _fmt_pct(p: Optional[float]) -> str:
    """概率 [0,1] → 'NN%'；None → '—'。"""
    if p is None:
        return "—"
    return f"{p * 100:.0f}%"


def _md_cell(text: str, max_len: int = 140) -> str:
    """表格单元格净化：折叠空白、转义竖线/换行、按长度截断（避免撑破 markdown 表格）。"""
    s = re.sub(r"\s+", " ", str(text or "")).strip()
    s = s.replace("|", "\\|")
    if len(s) > max_len:
        s = s[: max_len - 1].rstrip() + "…"
    return s


# ─────────────────────────── 论点 / 日期 / 句子抽取 ───────────────────────────

def _iter_heading_bodies(md: str) -> List[Tuple[str, List[str]]]:
    """把成稿切成 [(标题文本, 正文行列表), ...]，跳过围栏代码块内的伪标题。H1 也算一个条目。"""
    out: List[Tuple[str, List[str]]] = []
    cur_title: Optional[str] = None
    cur_body: List[str] = []
    in_fence = False
    for ln in (md or "").splitlines():
        if ln.lstrip().startswith("```"):
            in_fence = not in_fence
            if cur_title is not None:
                cur_body.append(ln)
            continue
        m = None if in_fence else re.match(r"^\s*#{1,6}\s+(.*?)\s*$", ln)
        if m:
            if cur_title is not None:
                out.append((cur_title, cur_body))
            cur_title = m.group(1).strip()
            cur_body = []
        elif cur_title is not None:
            cur_body.append(ln)
    if cur_title is not None:
        out.append((cur_title, cur_body))
    return out


def _first_paragraph(body_lines: List[str]) -> str:
    """从一段正文行里取首个「实义段落」：跳过空行/表格行/图片行/纯分隔线，把连续的散文行（含
    blockquote，剥去前导 '> '）拼成一段，遇空行即止。表格/图片不作论点来源。"""
    para: List[str] = []
    for ln in body_lines:
        s = ln.strip()
        if not s:
            if para:
                break
            continue
        if s.startswith("#"):
            # 遇到子标题：若尚未开始收集，跳过继续找散文；已在收集中则视为段落结束。
            if para:
                break
            continue
        if s.startswith("|") or s.startswith("!") or set(s) <= set("-=|: "):
            # 表格/图片/分隔线不作论点；未开始则跳过，已开始则结束。
            if para:
                break
            continue
        if s.startswith(">"):
            s = s.lstrip(">").strip()
            if not s:
                continue
        para.append(s)
    return " ".join(para).strip()


def _strip_inline_markup(text: str) -> str:
    """剥去论点里的行内 markdown 噪声：**粗体**/*斜体*/`码`/[链接](url)/引用标记 [S1-a] / [依据: …]。"""
    t = text or ""
    t = re.sub(r"\[依据:[^\]]*\]", "", t)          # 图谱依据标记
    t = re.sub(r"\[[SR]\d+[^\]]*\]", "", t)        # [S1-a] / [R2] 引用标记
    t = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", t)  # [text](url) → text
    t = re.sub(r"[*`_]+", "", t)                    # 强调/码符
    t = re.sub(r"\s+", " ", t).strip()
    return t


def _first_sentences(text: str, n: int) -> str:
    """取净化后文本的前 n 句（中英终止符切分）。空文本 → ''。"""
    clean = _strip_inline_markup(text)
    if not clean:
        return ""
    sents = _SENT_SPLIT_RE.split(clean)
    picked = [s.strip() for s in sents if s.strip()][:n]
    joined = " ".join(picked).strip()
    # 若切不出终止符（整段一句无句号），直接返回整段（已净化）。
    return joined or clean


def _extract_thesis(md: str, outline_summary: str, lang: str, n: int = 3) -> str:
    """确定性抽取 3 句论点：① 成稿里首个「执行摘要类」小节的正文首段；② 回退 outline.summary
    （仅主语言可靠——译文简报不传此值）；③ 再回退成稿正文首两段。全部取前 n 句。"""
    bodies = _iter_heading_bodies(md)
    # ① 执行摘要类小节
    for title, body in bodies:
        tl = title.lower()
        if any(k in tl for k in _SUMMARY_HEADING_KEYS):
            para = _first_paragraph(body)
            if para:
                return _first_sentences(para, n)
    # ② outline.summary（调用方仅在主语言传入）
    if outline_summary:
        return _first_sentences(outline_summary, n)
    # ③ 正文首两段（跳过 H1 标题段）：把所有 body 拼起来找首个实义段落
    all_body: List[str] = []
    for _title, body in bodies:
        all_body.extend(body)
        all_body.append("")  # 段间空行
    para = _first_paragraph(all_body)
    return _first_sentences(para, n)


def _extract_date(*texts: str) -> Optional[Tuple[Tuple[int, int, int], str]]:
    """从若干文本里抽取首个「判定日期」，返回 ((year,month,day) 排序键, 展示串)。
    优先「Month D, YYYY」→ ISO → 「Month YYYY」（无日按 28 号排序键，展示不含日）。无 → None。"""
    for t in texts:
        if not t:
            continue
        m = _DATE_MDY_RE.search(t)
        if m:
            mon = _MONTHS.get(m.group(1).lower(), 1)
            day = int(m.group(2))
            year = int(m.group(3))
            disp = f"{m.group(1).title()} {day}, {year}"
            return (year, mon, day), disp
    for t in texts:
        if not t:
            continue
        m = _DATE_ISO_RE.search(t)
        if m:
            year, mon, day = int(m.group(1)), int(m.group(2)), int(m.group(3))
            return (year, mon, day), f"{year:04d}-{mon:02d}-{day:02d}"
    for t in texts:
        if not t:
            continue
        m = _DATE_MY_RE.search(t)
        if m:
            mon = _MONTHS.get(m.group(1).lower(), 1)
            year = int(m.group(2))
            return (year, mon, 28), f"{m.group(1).title()} {year}"
    return None


# ─────────────────────────── 图表 / 运行健康 ───────────────────────────

def _find_scenario_chart(report_dir: str) -> Optional[Tuple[str, str]]:
    """定位最承重的图（scenario-bars PNG）。先查 viz_manifest.json 里 type=png 且 placement_hint
    命中 'scenarios' 的条目，否则回退默认路径 charts/scenario_probabilities.png。返回
    (相对 report_dir 的路径, 图注) 或 None（图不存在时不引用）。"""
    manifest = _read_json(os.path.join(report_dir, "viz_manifest.json"))
    # WAVE9 schema v2 wraps the entries: {"schema_version": 2, "items": [...]}.
    entries = manifest.get("items") if isinstance(manifest, dict) else manifest
    if isinstance(entries, list):
        for item in entries:
            if not isinstance(item, dict):
                continue
            # ADR 0003: a chart drawn from simulation artifacts is never the
            # load-bearing chart, whatever hint an older manifest gave it.
            if _sp.is_simulated_chart(item):
                continue
            if item.get("type") == "png" and str(item.get("placement_hint") or "") == "scenarios":
                rel = str(item.get("path") or "")
                if rel and os.path.exists(os.path.join(report_dir, rel)):
                    return rel, str(item.get("caption") or "Scenario Probabilities")
    # 回退：约定路径
    default_rel = os.path.join("charts", "scenario_probabilities.png")
    if os.path.exists(os.path.join(report_dir, default_rel)):
        return default_rel, "Scenario Probabilities"
    return None


def _load_pipeline_health(report_dir: str) -> Optional[Dict[str, Any]]:
    """经报告 telemetry.json 的 run_id 定位 uploads/pipelines/<run_id>/pipeline_state.json，读出
    options.pipeline_health（含 status 与各阶段健康）。任一环节缺失 → None（诚实声明降级为仅用
    forecast 质量门）。跨目录只读、纯 best-effort。"""
    tele = _read_json(os.path.join(report_dir, "telemetry.json"))
    run_id = None
    if isinstance(tele, dict):
        run_id = ((tele.get("totals") or {}).get("run_id")
                  if isinstance(tele.get("totals"), dict) else None)
    if not run_id:
        return None
    # report_dir = <upload>/reports/<id> → pipelines 同级
    pipelines_dir = os.path.join(os.path.dirname(os.path.dirname(report_dir)), "pipelines")
    state = _read_json(os.path.join(pipelines_dir, str(run_id), "pipeline_state.json"))
    if not isinstance(state, dict):
        return None
    ph = (state.get("options") or {}).get("pipeline_health")
    return ph if isinstance(ph, dict) else None


def _load_pinned_simulation_policy(report_dir: str) -> Optional[str]:
    """The run's pinned SIMULATION_FORECAST_EFFECT (``options.safety_policy_v1`` in
    pipeline_state.json, same lookup as the health block); None when unavailable."""
    tele = _read_json(os.path.join(report_dir, "telemetry.json"))
    run_id = None
    if isinstance(tele, dict):
        run_id = ((tele.get("totals") or {}).get("run_id")
                  if isinstance(tele.get("totals"), dict) else None)
    if not run_id:
        return None
    pipelines_dir = os.path.join(os.path.dirname(os.path.dirname(report_dir)), "pipelines")
    state = _read_json(os.path.join(pipelines_dir, str(run_id), "pipeline_state.json"))
    if not isinstance(state, dict):
        return None
    policy = (state.get("options") or {}).get("safety_policy_v1")
    if not isinstance(policy, dict):
        return None
    value = policy.get("simulation_forecast_effect")
    return str(value) if value else None


def _build_honesty_note(forecast: Optional[Dict[str, Any]], report_dir: str,
                        L: Dict[str, str]) -> str:
    """拼一行诚实声明：pipeline_health 状态（若可得）+ forecast 质量门通过与否 + 引用覆盖率 +
    模拟运行健康（有机行为数）。全部 degrade-safe，缺片段即省略；至少给出 forecast 质量门读数。"""
    parts: List[str] = []
    ph = _load_pipeline_health(report_dir)
    if isinstance(ph, dict):
        status = str(ph.get("status") or "").lower()
        if status == "ok":
            parts.append(L["ph_ok"])
        elif status == "failed":
            parts.append(L["ph_failed"])
        elif status:
            parts.append(L["ph_degraded"])
        # Scenario-simulation disclosure (ADR 0003 / S0.3): health plus what the
        # simulation was for — mechanism analysis only, never probabilities.
        run_stage = (ph.get("stages") or {}).get("run") if isinstance(ph.get("stages"), dict) else None
        if isinstance(run_stage, dict):
            rh = str(run_stage.get("health") or "").strip()
            organic = run_stage.get("organic_actions")
            if rh:
                detail = ""
                if isinstance(organic, (int, float)):
                    detail = f"{L['detail_sep']}{int(organic)} {L['organic']}"
                role = _sp.brief_sim_role(_load_pinned_simulation_policy(report_dir),
                                          "zh" if L is _LABELS["zh"] else "en")
                parts.append(L["sim_line"].format(health=rh, detail=detail, role=role))

    # forecast 质量门（forecast.json 内，永远在报告目录里）
    if isinstance(forecast, dict):
        q = forecast.get("quality") if isinstance(forecast.get("quality"), dict) else {}
        bq = forecast.get("binary_quality") if isinstance(forecast.get("binary_quality"), dict) else {}
        passed = bool(q.get("passed")) and bool(bq.get("passed")) if (q or bq) else None
        if passed is True:
            parts.append(L["quality_pass"])
        elif passed is False:
            cov = _to_float(q.get("citation_coverage"))
            if cov is None:
                cov = _to_float((forecast.get("citation_audit") or {}).get("coverage")
                                if isinstance(forecast.get("citation_audit"), dict) else None)
            seg = L["quality_fail"]
            if cov is not None:
                seg += f" ({L['coverage']} {cov * 100:.0f}%)"
            parts.append(seg)

    if not parts:
        return ""
    sep = "；" if L is _LABELS["zh"] else "; "
    return sep.join(parts)


# ─────────────────────────── 预测排序 / 表格 ───────────────────────────

def _conviction(b: Dict[str, Any]) -> float:
    """二元预测的「承重度」：|prob − 0.5|（越极端越承重）。无概率 → -1（排到最后）。"""
    p = _to_float(b.get("probability"))
    return abs(p - 0.5) if p is not None else -1.0


def _market_delta_cell(b: Dict[str, Any]) -> str:
    """市场锚 Δ 单元格：优先 market_anchor.divergence（模型−市场，pp）；无 divergence 但有
    implied_yes_prob 时现算 model−implied。无市场锚 → '—'。"""
    anchor = b.get("market_anchor") if isinstance(b.get("market_anchor"), dict) else None
    if not anchor:
        return "—"
    div = _to_float(anchor.get("divergence"))
    implied = _to_float(anchor.get("implied_yes_prob"))
    if div is None and implied is not None:
        model = _to_float(b.get("probability"))
        if model is not None:
            div = model - implied
    if div is None:
        return "—"
    pp = div * 100
    core = f"{pp:+.0f}pt"
    if implied is not None:
        core += f" (mkt {implied * 100:.0f}%)"
    return core


def _prob_cell(b: Dict[str, Any], L: Dict[str, str]) -> str:
    """概率单元格：'NN%'，若有集成离散 ensemble.spread 则追加 '±MM%'。"""
    p = _to_float(b.get("probability"))
    cell = _fmt_pct(p)
    ens = b.get("ensemble") if isinstance(b.get("ensemble"), dict) else None
    if ens is not None:
        spread = _to_float(ens.get("spread"))
        if spread is not None and spread > 0:
            cell += f" {L['prob_sep']}{spread * 100:.0f}%"
    return cell


def _forecast_resolution_disp(b: Dict[str, Any]) -> str:
    """二元预测判定日期展示串：从 resolution_criteria/resolution_source 抽取日期，回退 horizon_year。"""
    d = _extract_date(str(b.get("resolution_criteria") or ""), str(b.get("resolution_source") or ""))
    if d:
        return d[1]
    hy = b.get("horizon_year")
    return str(hy) if hy else "—"


def _build_forecast_table(forecast: Dict[str, Any], L: Dict[str, str],
                          cap: int = 8) -> str:
    """按承重度降序取前 cap 条二元预测，渲染 markdown 表：陈述 / 概率±离散 / 市场 Δ / 判定日期。"""
    bfs = forecast.get("binary_forecasts")
    if not isinstance(bfs, list) or not bfs:
        return L["no_data"]
    rows = [b for b in bfs if isinstance(b, dict) and _to_float(b.get("probability")) is not None]
    if not rows:
        return L["no_data"]
    # 稳定排序：承重度降序，等价时保持原始顺序（enumerate 兜底）。
    rows = sorted(enumerate(rows), key=lambda t: (-_conviction(t[1]), t[0]))
    rows = [b for _i, b in rows][:cap]

    out = [
        f"| {L['c_forecast']} | {L['c_prob']} | {L['c_market']} | {L['c_resolves']} |",
        "|---|---|---|---|",
    ]
    for b in rows:
        out.append(
            f"| {_md_cell(b.get('statement'), 160)} | {_prob_cell(b, L)} "
            f"| {_md_cell(_market_delta_cell(b), 40)} | {_md_cell(_forecast_resolution_disp(b), 32)} |"
        )
    return "\n".join(out)


def _build_scenarios_block(forecast: Dict[str, Any], L: Dict[str, str],
                           cap: int = 5) -> str:
    """关键情景概率：按概率降序取前 cap 个，每行 '- 名称 — NN%（[p_low,p_high]）'。"""
    scenarios = forecast.get("scenarios")
    if not isinstance(scenarios, list) or not scenarios:
        return L["no_data"]
    items: List[Tuple[float, str]] = []
    for s in scenarios:
        if not isinstance(s, dict):
            continue
        p = _to_float(s.get("probability")) or _to_float(s.get("prob")) or _to_float(s.get("p"))
        if p is None:
            continue
        name = _md_cell(s.get("name") or s.get("label") or "Scenario", 120)
        lo = _to_float(s.get("p_low"))
        hi = _to_float(s.get("p_high"))
        band = f" ([{lo * 100:.0f}%, {hi * 100:.0f}%])" if (lo is not None and hi is not None) else ""
        items.append((p, f"- **{name}** — {_fmt_pct(p)}{band}"))
    if not items:
        return L["no_data"]
    items.sort(key=lambda t: -t[0])
    return "\n".join(line for _p, line in items[:cap])


def _official_amount(value: Optional[float], units: str, zh: bool) -> str:
    """A stored value as published plus its units (a level such as '58522249' Thousands of U.S.
    Dollars is meaningless without them) and the data layer's magnitude companion."""
    from .official_data import data_api, format_value
    api = data_api()
    text = format_value(value, units)
    if api is None or value is None or api.is_percent_units(units):
        return text
    scaled = api.scaled_value(value, units, "zh" if zh else "en")
    return f"{text} {units}".rstrip() + ((f"（{scaled}）" if zh else f" ({scaled})") if scaled else "")


def _anchor_watch_line(b: Dict[str, Any], L: Dict[str, str],
                       rows: Optional[Dict[str, Dict[str, Any]]] = None) -> Optional[Tuple[str, str]]:
    """RPT-11: an officially anchored binary as '(period, line)': latest stored value vs the
    threshold for the anchored period, plus the historical base rate when computed. ``rows``
    (the report's stored series by id) names a US federal fiscal year by its label ('FY2026')."""
    anchor = b.get("data_anchor")
    if not isinstance(anchor, dict) or _to_float(anchor.get("threshold")) is None:
        return None
    period = str(anchor.get("period") or "")
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", period) or anchor.get("comparator") not in (">", ">=", "<", "<="):
        return None
    from .forecast_extractor import official_fiscal_label
    from .report_agent import official_period_label
    units = str(anchor.get("units") or "")
    grid = {"frequency": anchor.get("frequency")}
    row = (rows or {}).get(str(anchor.get("series") or ""))

    def period_text(day: str) -> str:
        return official_fiscal_label(row, day) or official_period_label(grid, day)
    zh = L is _LABELS["zh"]
    parts = []
    latest, latest_date = _to_float(anchor.get("latest_value")), str(anchor.get("latest_date") or "")
    if latest is not None and re.fullmatch(r"\d{4}-\d{2}-\d{2}", latest_date):
        parts.append(f"{L['w_latest']} {_official_amount(latest, units, zh)} ({period_text(latest_date)})")
    parts.append(f"{L['w_threshold']} {anchor['comparator']} {_official_amount(_to_float(anchor['threshold']), units, zh)} "
                 f"({period_text(period)})")
    rate = anchor.get("empirical_base_rate")
    if isinstance(rate, dict) and _to_float(rate.get("p")) is not None:
        from .forecast_extractor import empirical_seasonal_note
        note = empirical_seasonal_note(rate, zh)
        parts.append(f"{L['w_base_rate']} {_fmt_pct(_to_float(rate.get('p')))}"
                     + ((f"（{note}）" if zh else f" ({note})") if note else ""))
    return period, f"- {_md_cell(b.get('statement'), 130)} — {'; '.join(_md_cell(part, 120) for part in parts)}"


def _build_watch_block(forecast: Dict[str, Any], L: Dict[str, str], n: int = 3,
                       rows: Optional[Dict[str, Dict[str, Any]]] = None) -> str:
    """3 个带日期的观察指标：从二元预测里挑「有可解析判定日期」的，优先 criteria_sharp（客观判定），
    按日期升序（最近的最值得盯）取前 n 条，每行 '- 陈述 — 日期'。不足则用剩余带日期预测补足。

    RPT-11: binaries anchored to a stored official series come first (earliest
    anchored period first), shown as latest stored value vs threshold."""
    bfs = forecast.get("binary_forecasts")
    if not isinstance(bfs, list) or not bfs:
        return L["no_data"]
    anchored: List[Tuple[str, str]] = []
    dated: List[Tuple[bool, Tuple[int, int, int], str, str]] = []
    for b in bfs:
        if not isinstance(b, dict):
            continue
        anchor_line = _anchor_watch_line(b, L, rows)
        if anchor_line:
            anchored.append(anchor_line)
            continue
        d = _extract_date(str(b.get("resolution_criteria") or ""),
                          str(b.get("resolution_source") or ""))
        if not d:
            continue
        sort_key, disp = d
        dated.append((bool(b.get("criteria_sharp")), sort_key, _md_cell(b.get("statement"), 130), disp))
    if not anchored and not dated:
        return L["no_data"]
    # 排序：客观判定优先（sharp True 在前），再按日期升序。
    anchored.sort(key=lambda t: t[0])
    dated.sort(key=lambda t: (not t[0], t[1]))
    lines = [line for _period, line in anchored[:n]]
    lines += [f"- {stmt} — **{disp}**" for _sharp, _k, stmt, disp in dated[:max(0, n - len(lines))]]
    return "\n".join(lines)


def _official_rows(report_dir: str) -> Dict[str, Dict[str, Any]]:
    """Stored rows of the report-local official_data.json by series id ({} when absent)."""
    from .forecast_extractor import official_series_rows
    from .report_agent import ReportManager, read_report_official_data
    record = read_report_official_data(os.path.join(report_dir, ReportManager.OFFICIAL_DATA_FILENAME))
    return {row["series"]: row for row in official_series_rows(record["official_data"])} if record else {}


def _official_summaries(report_dir: str, lang: str) -> List[Dict[str, Any]]:
    """Indicator summaries from the report-local official_data.json ([] when absent)."""
    from .report_agent import ReportManager, official_indicator_rows, read_report_official_data
    record = read_report_official_data(os.path.join(report_dir, ReportManager.OFFICIAL_DATA_FILENAME))
    if record is None:
        return []
    tags = record["source_tags"]
    return [summary for summary in official_indicator_rows(
        record["official_data"], lang=lang, tag_for=lambda row: tags.get(row["series"], ""))
        if summary["latest"]]


def _build_indicators_block(summaries: List[Dict[str, Any]], L: Dict[str, str], cap: int = 8) -> str:
    """RPT-11: localized Key official indicators mini-table (latest observed values only)."""
    if not summaries:
        return ""
    out = [f"| {L['c_indicator']} | {L['c_latest']} | {L['c_period']} | {L['c_change']} | {L['c_source']} |",
           "|---|---|---|---|---|"]
    zh = L is _LABELS["zh"]
    for summary in summaries[:cap]:
        change = summary["change"]["display"] if summary["change"] else "—"
        source = summary["provider_name"] or summary["provider"] or "Source"
        latest = _official_amount(summary["latest"]["value"], summary["units"], zh)
        out.append(f"| {_md_cell(summary['label'], 90)} | {_md_cell(latest, 120)} "
                   f"| {_md_cell(summary['latest']['period'], 16)} | {_md_cell(change, 60)} "
                   f"| [{_md_cell(source, 60)}](<{summary['source_url']}>) |")
    return "\n".join(out)


# ─────────────────────────── 顶层构建器 ───────────────────────────

class ExecBriefBuilder:
    """执行交付物构建器：build() 生成 exec_brief.md（+译文版）与 digest.md；build_pdf() 惰性
    把 exec_brief.md 导为一页 PDF。所有产物落在 report_dir 下，与 full_report.* 同源。"""

    # 产物文件名（单一真源）。
    BRIEF_NAME = "exec_brief.md"
    DIGEST_NAME = "digest.md"
    PDF_NAME = "exec_brief.pdf"

    _TRANSLATION_LANGS = ("en", "zh")

    # ── 路径助手 ──
    @classmethod
    def brief_path(cls, report_dir: str, lang: Optional[str] = None) -> str:
        """exec_brief.md（主）或 exec_brief.<lang>.md（译文版；lang ∈ {en,zh}）。"""
        if lang in cls._TRANSLATION_LANGS:
            return os.path.join(report_dir, f"exec_brief.{lang}.md")
        return os.path.join(report_dir, cls.BRIEF_NAME)

    @classmethod
    def digest_path(cls, report_dir: str) -> str:
        return os.path.join(report_dir, cls.DIGEST_NAME)

    @classmethod
    def pdf_path(cls, report_dir: str, lang: Optional[str] = None) -> str:
        if lang in cls._TRANSLATION_LANGS:
            return os.path.join(report_dir, f"exec_brief.{lang}.pdf")
        return os.path.join(report_dir, cls.PDF_NAME)

    # ── 缓存判定 ──
    @staticmethod
    def _needs_rebuild(out_path: str, *source_paths: str) -> bool:
        """out 缺失，或其 mtime 早于任一存在的源文件 → 需重建（与 PDF 端点 mtime 缓存同思路）。"""
        if not os.path.exists(out_path):
            return True
        try:
            out_m = os.path.getmtime(out_path)
        except OSError:
            return True
        for sp in source_paths:
            try:
                if os.path.exists(sp) and os.path.getmtime(sp) > out_m:
                    return True
            except OSError:
                return True
        return False

    _CACHE_VERSION = "exec-brief/v2"

    @staticmethod
    def _digest(value):
        data = value if isinstance(value, bytes) else json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(data).hexdigest()

    @classmethod
    def _capture(cls, report_id, report_dir, lang=None):
        """Capture exact brief inputs; public generation assets never mix sidecars."""
        from .report_agent import ReportManager
        from .translation.artifacts import ArtifactError, figure_inventory
        source_path = os.path.join(report_dir, "full_report.md")
        meta = _read_json(os.path.join(report_dir, "meta.json")) or {}
        primary = _read_text(source_path) or meta.get("markdown_content") or ""
        snapshot = None
        if lang:
            snapshot = ReportManager.resolve_translation(report_id, lang)
            if snapshot and not ReportManager.is_publishable(report_id, lang):
                raise ArtifactError("stale_artifact", "Executive brief publication is no longer admitted; reload")
            try:
                md = snapshot.markdown if snapshot else ReportManager.read_translation_markdown(report_id, lang)
            except FileNotFoundError:
                return None
            if not md:
                return None
        else:
            md = primary
        language = lang or _detect_lang(md)
        forecast, info = ReportManager.load_localized_forecast(report_id, language, snapshot=snapshot)
        if snapshot is None and not info.get("localized"):
            # Historical primary/legacy builders also support optional unsealed
            # fixture/old forecast files. Generation readers keep validated fallback.
            forecast = _read_json(os.path.join(report_dir, "forecast.json"))
        if lang:
            display = None
            if snapshot and "display.json" in snapshot.assets:
                try:
                    display = json.loads(snapshot.assets["display.json"])
                except (TypeError, ValueError):
                    pass
            title = display.get("title") if isinstance(display, dict) else None
            if not isinstance(title, str) or not title.strip():
                heading = re.search(r"^\s*#\s+(.+?)\s*$", md, re.M)
                title = heading.group(1).strip() if heading else str((forecast or {}).get("headline") or report_id)
            # The translated brief must not take its title/question from primary
            # metadata. These are admitted display/Markdown bytes, not new prose.
            meta = {**meta, "simulation_requirement": title,
                    "outline": {**(meta.get("outline") or {}), "title": title}}
        summary = "" if lang else str((meta.get("outline") or {}).get("summary") or "")
        brief = cls._render_brief(report_id, report_dir, md, forecast, meta, language, summary)
        identity = {
            "version": cls._CACHE_VERSION, "report_id": report_id, "lang": lang,
            "generation": snapshot.generation if snapshot else None,
            "source_sha256": cls._digest(primary.encode("utf-8")),
            "markdown_sha256": cls._digest(md.encode("utf-8")),
            "forecast_sha256": cls._digest(forecast), "meta_sha256": cls._digest(meta),
            "brief_sha256": cls._digest(brief.encode("utf-8")),
            "figures": figure_inventory(brief, source_path),
        }
        return brief, identity, (md, forecast, meta, language)

    @classmethod
    def _check_capture(cls, report_id, report_dir, lang, identity):
        from .translation.artifacts import ArtifactError
        current = cls._capture(report_id, report_dir, lang)
        if current is None or current[1] != identity:
            raise ArtifactError("stale_artifact", "Executive brief source or publication changed; retry")

    @classmethod
    def _translated_brief(cls, report_id, report_dir, lang):
        from .translation.artifacts import artifact_lock, atomic_bytes
        captured = cls._capture(report_id, report_dir, lang)
        if captured is None:
            return None
        brief, identity, _ = captured
        directory = Path(report_dir) / ".exec-brief" / cls._digest(identity)
        path = directory / f"exec_brief.{lang}.md"
        data = brief.encode("utf-8")
        with artifact_lock(str(directory) + ".lock", blocking=False):
            cls._check_capture(report_id, report_dir, lang, identity)
            if not path.is_file() or path.read_bytes() != data:
                atomic_bytes(path, data)
            atomic_bytes(str(path) + ".manifest.json", json.dumps({"input": identity,
                "sha256": cls._digest(data)}, sort_keys=True).encode("utf-8"))
            cls._check_capture(report_id, report_dir, lang, identity)
        return str(path)

    @classmethod
    def read_current(cls, report_id, report_dir, path, lang=None):
        """Return verified bytes; delivery must not reopen a mutable legacy path."""
        from .translation.artifacts import ArtifactError
        try:
            data = Path(path).read_bytes()
        except OSError as exc:
            raise ArtifactError("stale_artifact", "Executive brief cache is unavailable; retry") from exc
        manifest = _read_json(str(path) + ".manifest.json")
        if manifest:
            cls._check_capture(report_id, report_dir, lang, manifest["input"])
            if cls._digest(data) != manifest.get("sha256"):
                raise ArtifactError("stale_artifact", "Executive brief cache changed; retry")
        elif lang or str(path).endswith(".pdf"):
            raise ArtifactError("stale_artifact", "Executive brief cache is not bound to its inputs")
        else:
            captured = cls._capture(report_id, report_dir)
            if cls._digest(data) != captured[1]["brief_sha256"]:
                raise ArtifactError("stale_artifact", "Executive brief source changed; retry")
        return data

    @classmethod
    def assert_current(cls, report_id, report_dir, path, lang=None):
        """Recheck a returned derived path immediately before public delivery."""
        cls.read_current(report_id, report_dir, path, lang)

    # ── 主入口 ──
    @classmethod
    def build(cls, report_id: str, report_dir: str, force: bool = False, *,
              lang: Optional[str] = None) -> Dict[str, str]:
        """Build deterministic briefs; explicit language reads one selected generation.

        Primary Markdown/digest paths retain their historical contract. Translated
        paths are immutable and callers must consume this method's returned path.
        """
        if not bool(_cfg("REPORT_EXEC_BRIEF", True)) or not os.path.isdir(report_dir):
            return {}
        if lang in cls._TRANSLATION_LANGS:
            path = cls._translated_brief(report_id, report_dir, lang)
            return {f"exec_brief.{lang}": path} if path else {}
        from .translation.artifacts import ArtifactError, atomic_bytes
        captured = cls._capture(report_id, report_dir)
        brief_md, identity, (md, forecast, meta, primary_lang) = captured
        digest_md = cls._render_digest(report_id, md, forecast, meta, primary_lang, report_dir=report_dir)
        brief_out, digest_out = cls.brief_path(report_dir), cls.digest_path(report_dir)
        # Retain legacy timestamp refresh behavior, but content equality is also
        # mandatory: equal mtimes and deleted dependencies cannot hide a change.
        rebuild = force or cls._needs_rebuild(brief_out, *(os.path.join(report_dir, name)
            for name in ("full_report.md", "forecast.json", "meta.json", "final_audit.json")))
        cls._check_capture(report_id, report_dir, None, identity)
        produced = {}
        for key, path, value in (("exec_brief", brief_out, brief_md), ("digest", digest_out, digest_md)):
            if not rebuild and _read_text(path) == value or _write_text_atomic(path, value):
                if key == "digest":
                    atomic_bytes(path + ".manifest.json", json.dumps({"input": identity,
                        "sha256": cls._digest(value.encode("utf-8"))}, sort_keys=True).encode("utf-8"))
                produced[key] = path
        # Optional bulk compatibility must not make a primary brief unavailable
        # merely because an unrelated target generation is stale.
        for target in cls._TRANSLATION_LANGS:
            if target == primary_lang:
                continue
            try:
                path = cls._translated_brief(report_id, report_dir, target)
                if path:
                    produced[f"exec_brief.{target}"] = path
            except ArtifactError:
                continue
        return produced

    # ── 简报渲染（一页纸）──
    @classmethod
    def _render_brief(cls, report_id: str, report_dir: str, md: str,
                      forecast: Optional[Dict[str, Any]], meta: Dict[str, Any],
                      lang: str, outline_summary: str) -> str:
        """渲染 exec_brief.md 内容（一页纸、目标语言）。纯确定性拼装。"""
        L = _LABELS.get(lang, _LABELS["en"])
        fc = forecast if isinstance(forecast, dict) else {}

        # 预测问题：优先 meta.simulation_requirement，回退 outline.title / forecast.headline / H1。
        question = ""
        if isinstance(meta, dict):
            question = str(meta.get("simulation_requirement") or "").strip()
            if not question:
                question = str((meta.get("outline") or {}).get("title") or "").strip()
        if not question:
            question = str(fc.get("headline") or "").strip()
        if not question:
            m = re.search(r"^\s*#\s+(.+?)\s*$", md or "", re.M)
            question = m.group(1).strip() if m else report_id
        question = _strip_inline_markup(question)

        title = _strip_inline_markup(str((meta.get("outline") or {}).get("title")
                                          or fc.get("headline") or question)) if isinstance(meta, dict) else question

        thesis = _extract_thesis(md, outline_summary, lang) or L["no_data"]

        parts: List[str] = []
        parts.append(f"# {L['brief_title']} — {_md_cell(title, 120)}")
        parts.append("")
        parts.append(f"**{L['question']}:** {question}")
        parts.append("")
        parts.append(f"## {L['thesis']}")
        parts.append("")
        parts.append(thesis)
        parts.append("")

        # TOP 二元预测表
        parts.append(f"## {L['top_forecasts']}")
        parts.append("")
        parts.append(_build_forecast_table(fc, L) if fc else L["no_data"])
        parts.append("")

        # 关键情景概率
        parts.append(f"## {L['scenarios']}")
        parts.append("")
        parts.append(_build_scenarios_block(fc, L) if fc else L["no_data"])
        parts.append("")

        # RPT-11: stored official indicators (report-local carrier), when present.
        indicators = _build_indicators_block(_official_summaries(report_dir, lang), L)
        if indicators:
            parts.append(f"## {L['indicators']}")
            parts.append("")
            parts.append(indicators)
            parts.append("")

        # 最承重的图（scenario-bars PNG，若存在）
        chart = _find_scenario_chart(report_dir)
        if chart:
            rel, caption = chart
            parts.append(f"## {L['chart']}")
            parts.append("")
            parts.append(f"![{_md_cell(caption, 80)}]({rel})")
            parts.append("")

        # 观察指标（3 个带日期）
        parts.append(f"## {L['watch']}")
        parts.append("")
        parts.append(_build_watch_block(fc, L, rows=_official_rows(report_dir)) if fc else L["no_data"])
        parts.append("")

        # 一行诚实声明
        honesty = _build_honesty_note(fc if fc else None, report_dir, L)
        if honesty:
            parts.append(f"> **{L['honesty']}:** {honesty}")
            parts.append("")

        parts.append(f"_{L['gen_note']}_")
        parts.append("")
        return "\n".join(parts)

    # ── 速览渲染（~15 行 newsletter）──
    @classmethod
    def _render_digest(cls, report_id: str, md: str, forecast: Optional[Dict[str, Any]],
                       meta: Dict[str, Any], lang: str, report_dir: str = "") -> str:
        """渲染 digest.md：标题 + 3 条要点（top 情景/驱动）+ 头号预测 + 最大市场分歧 + 链接路径。

        RPT-11: plus one line of up to three stored official indicators."""
        L = _LABELS.get(lang, _LABELS["en"])
        fc = forecast if isinstance(forecast, dict) else {}

        headline = str(fc.get("headline") or "").strip()
        if not headline and isinstance(meta, dict):
            headline = str((meta.get("outline") or {}).get("title") or "").strip()
        if not headline:
            m = re.search(r"^\s*#\s+(.+?)\s*$", md or "", re.M)
            headline = m.group(1).strip() if m else report_id
        headline = _strip_inline_markup(headline)

        lines: List[str] = []
        lines.append(f"# {L['digest_title']}: {_md_cell(headline, 140)}")
        lines.append("")

        # 3 条要点：top 3 情景（名称 + 概率）
        bullets: List[str] = []
        scenarios = fc.get("scenarios") if isinstance(fc.get("scenarios"), list) else []
        scen_ranked = sorted(
            [s for s in scenarios if isinstance(s, dict) and _to_float(s.get("probability")) is not None],
            key=lambda s: -(_to_float(s.get("probability")) or 0.0),
        )
        for s in scen_ranked[:3]:
            nm = _md_cell(s.get("name") or "Scenario", 110)
            bullets.append(f"- {nm} — **{_fmt_pct(_to_float(s.get('probability')))}**")
        for b in bullets:
            lines.append(b)
        if bullets:
            lines.append("")

        # 头号预测（承重度最高的二元预测）
        bfs = [b for b in (fc.get("binary_forecasts") or [])
               if isinstance(b, dict) and _to_float(b.get("probability")) is not None]
        if bfs:
            top = sorted(enumerate(bfs), key=lambda t: (-_conviction(t[1]), t[0]))[0][1]
            lines.append(f"**{L['top_forecast']}:** {_md_cell(top.get('statement'), 160)} "
                         f"— {_prob_cell(top, L)}")
            lines.append("")

            # 最大市场分歧（|divergence| 最大的带市场锚预测）
            anchored = []
            for b in bfs:
                anchor = b.get("market_anchor") if isinstance(b.get("market_anchor"), dict) else None
                if not anchor:
                    continue
                div = _to_float(anchor.get("divergence"))
                if div is None:
                    implied = _to_float(anchor.get("implied_yes_prob"))
                    model = _to_float(b.get("probability"))
                    if implied is not None and model is not None:
                        div = model - implied
                if div is not None:
                    anchored.append((abs(div), b))
            if anchored:
                anchored.sort(key=lambda t: -t[0])
                b = anchored[0][1]
                lines.append(f"**{L['biggest_divergence']}:** {_md_cell(b.get('statement'), 140)} "
                             f"— {_md_cell(_market_delta_cell(b), 48)}")
                lines.append("")

        summaries = _official_summaries(report_dir, lang) if report_dir else []
        if summaries:
            facts = [f"{_md_cell(summary['label'], 70)} "
                     f"{_md_cell(_official_amount(summary['latest']['value'], summary['units'], lang == 'zh'), 100)} "
                     f"({summary['latest']['period']})" for summary in summaries[:3]]
            lines.append(f"**{L['indicators']}:** " + "; ".join(facts))
            lines.append("")

        # 链接路径（相对 API 路径，便于分享/嵌入）
        base = f"/api/report/{report_id}"
        lines.append(f"**{L['links']}:** "
                     f"[brief]({base}/exec-brief) · "
                     f"[brief.pdf]({base}/exec-brief.pdf) · "
                     f"[digest]({base}/digest) · "
                     f"[full report]({base}/download) · "
                     f"[report.pdf]({base}/pdf)")
        lines.append("")
        return "\n".join(lines)

    # ── PDF（内容/代际缓存，保留 no-toc 单页版式）──
    @classmethod
    def build_pdf(cls, report_id: str, report_dir: str, lang: Optional[str] = None,
                  force: bool = False) -> Optional[str]:
        """Render the current brief to an immutable PDF without touching old exports."""
        from .report_agent import ReportManager
        from .translation.artifacts import ArtifactError, artifact_lock, atomic_bytes, file_digest
        if not _cfg("REPORT_EXEC_BRIEF", True) or not _cfg("REPORT_PDF_EXPORT", True):
            return None
        lang = lang if lang in cls._TRANSLATION_LANGS else None
        captured = cls._capture(report_id, report_dir, lang)
        if captured is None:
            return None
        md, identity, _ = captured
        renderer = {**ReportManager._pdf_renderer_fingerprint(), "toc": False, "margin": "1.8cm",
                    "brief_version": cls._CACHE_VERSION, "brief_pdf_policy": "content-audit/v1"}
        cache = Path(report_dir) / ".exec-brief" / cls._digest({"input": identity, "renderer": renderer})
        pointer = cache / "pdf.json"
        with artifact_lock(str(cache) + ".lock", blocking=False):
            cls._check_capture(report_id, report_dir, lang, identity)
            cached = _read_json(str(pointer))
            if not force and isinstance(cached, dict):
                sha = cached.get("sha256")
                if isinstance(sha, str) and re.fullmatch(r"[a-f0-9]{64}", sha):
                    path = cache / sha / os.path.basename(cls.pdf_path(report_dir, lang))
                    if file_digest(path) == sha and not path.is_symlink():
                        cls.assert_current(report_id, report_dir, str(path), lang)
                        return str(path)
            with tempfile.TemporaryDirectory(prefix=".exec-brief-stage-", dir=report_dir) as staging:
                temporary = os.path.join(staging, "exec_brief.pdf")
                proc_md = ReportManager._rewrite_chart_paths_for_pdf(md, report_dir)
                rendered = cls._export_pdf_pandoc_no_toc(report_id, proc_md, staging, temporary)
                if not rendered:
                    # Pandoc displays image alt text as a caption; Story does not.
                    # Preserve that visible text once for the shared content gate.
                    fallback_md = re.sub(r"!\[([^\]]+)\]\(([^)]+)\)", r"![](\2)\n\n\1", proc_md)
                    rendered = ReportManager._export_pdf_pymupdf(fallback_md, report_dir, temporary)
                if not rendered or not ReportManager._is_pdf_file(temporary):
                    return None
                valid, content_audit = ReportManager._validate_pdf_content(temporary, md)
                if not valid:
                    return None
                cls._check_capture(report_id, report_dir, lang, identity)
                data = Path(temporary).read_bytes()
                sha = cls._digest(data)
                path = cache / sha / os.path.basename(cls.pdf_path(report_dir, lang))
                if file_digest(path) != sha:
                    atomic_bytes(path, data)
                manifest = {"input": identity, "renderer": renderer, "sha256": sha,
                            "content_audit": content_audit}
                atomic_bytes(str(path) + ".manifest.json", json.dumps(manifest, sort_keys=True).encode("utf-8"))
                cls.assert_current(report_id, report_dir, str(path), lang)
                atomic_bytes(pointer, json.dumps({"sha256": sha}).encode("utf-8"))
                return str(path)

    @classmethod
    def _export_pdf_pandoc_no_toc(cls, report_id: str, md: str, folder: str,
                                  pdf_path: str) -> bool:
        """pandoc + xelatex 构建一页 PDF——复用 ReportManager._resolve_pandoc 的引擎选择与
        _is_pdf_file/_safe_unlink，但命令去掉 --toc、收紧边距（geometry margin=1.8cm）。用独立的
        临时文件名（_exec_brief_source.md / _exec_brief.building.pdf）避免与主报告 PDF 构建撞名。
        成功（产出有效 PDF）→ True；pandoc 不可用/非零/无产出/超时 → False（触发回退）。"""
        import subprocess

        from .report_agent import ReportManager

        resolved = ReportManager._resolve_pandoc()
        if not resolved:
            return False
        pandoc, xelatex = resolved
        src_md = os.path.join(folder, "_exec_brief_source.md")
        # 临时产物必须 .pdf 结尾——pandoc 由扩展名推断格式。
        tmp_pdf = os.path.join(folder, "_exec_brief.building.pdf")
        try:
            with open(src_md, "w", encoding="utf-8") as f:
                f.write(md)
        except OSError as e:
            logger.warning(f"写 exec_brief PDF 源 md 失败: {e}")
            return False
        cmd = [
            pandoc, src_md,
            f"--pdf-engine={xelatex or 'xelatex'}",
            "-V", "CJKmainfont=PingFang SC",
            "-V", "geometry:margin=1.8cm",
            # 注意：无 --toc（一页版式）。
            "-o", tmp_pdf,
        ]
        try:
            proc = subprocess.run(
                cmd, capture_output=True, cwd=folder,
                timeout=int(_cfg("REPORT_PDF_TIMEOUT", 180) or 180),
            )
        except Exception as e:  # noqa: BLE001 — 超时/OS 错误 → 回退
            logger.warning(f"exec_brief pandoc 执行异常，回退 PyMuPDF: {e}")
            ReportManager._safe_unlink(src_md, tmp_pdf)
            return False
        rc = getattr(proc, "returncode", 1)
        if rc != 0 or not os.path.exists(tmp_pdf) or os.path.getsize(tmp_pdf) == 0 \
                or not ReportManager._is_pdf_file(tmp_pdf):
            _stderr = getattr(proc, "stderr", b"") or b""
            _tail = (_stderr[-400:].decode("utf-8", "ignore")
                     if isinstance(_stderr, (bytes, bytearray)) else str(_stderr)[-400:])
            logger.warning(f"exec_brief pandoc 未产出有效 PDF（rc={rc}），回退 PyMuPDF：{_tail}")
            ReportManager._safe_unlink(src_md, tmp_pdf)
            return False
        try:
            os.replace(tmp_pdf, pdf_path)
        except OSError as e:
            logger.warning(f"exec_brief PDF 原子替换失败: {e}")
            ReportManager._safe_unlink(src_md, tmp_pdf)
            return False
        ReportManager._safe_unlink(src_md)
        logger.info(f"pandoc 导出 exec_brief PDF 成功: {report_id}")
        return True
