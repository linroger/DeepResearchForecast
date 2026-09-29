"""Ensemble aggregation of multiple structured forecasts (EXECPLAN2 I-9-0/I-2-4/I-3-3).

A single OASIS run is one stochastic sample. Running the sim+report N times (with
different seeds) and aggregating the resulting structured forecasts turns a point
estimate into a *distribution*: frequency-derived scenario probabilities with
spread (a confidence-interval proxy) and an inter-run agreement score. Pure and
side-effect-free so it is unit-testable offline; the N-run driver lives in
scripts/forecast_tools.py (built on the existing PREPARE-fork).
"""

from __future__ import annotations

import math
import re
from typing import Any, Dict, List, Optional


def _cfg(name: str, default: Any) -> Any:
    """Read a Config flag with a safe default (degrade-safe; never raises)."""
    try:
        from ..config import Config
        return getattr(Config, name, default)
    except Exception:  # noqa: BLE001
        return default


def _norm_name(name) -> str:
    """Loose scenario-name key so 'Samsung leads' ~ 'samsung  leads.'."""
    return re.sub(r"\s+", " ", re.sub(r"[^\w一-鿿]+", " ", str(name or "").lower())).strip()


def _scenario_tokens(text) -> set:
    """W9-5：判定标准（resolution_criteria）的语义 token 集，供跨 run 情景对齐。

    拉丁词取 2+ 位字母数字串（含 '1.6t'、'tsmc' 等指标词），CJK 按单字符切分（中文判定
    标准无空格分词，逐字集合的 Jaccard 已足以区分「营收≥$1.6T」与「份额≥62%」类判据）。
    """
    s = str(text or "").lower()
    toks = set(re.findall(r"[a-z0-9][a-z0-9.%$]*", s))
    toks |= set(re.findall(r"[一-鿿]", s))
    # 单字符拉丁 token 噪声大（'a'/'c'），剔除以免把占位判据误判为高重叠。
    return {t for t in toks if len(t) >= 2 or re.match(r"[一-鿿]", t)}


def _token_overlap(a: set, b: set) -> float:
    """Jaccard 重叠度 ∈[0,1]；任一侧为空 → 0（无法据判据对齐）。"""
    if not a or not b:
        return 0.0
    inter = len(a & b)
    if not inter:
        return 0.0
    return inter / float(len(a | b))


def align_scenario_buckets(runs: List[Dict[str, Any]],
                           min_overlap: Optional[float] = None) -> List[Dict[str, Any]]:
    """W9-5（纯）：跨 run 的语义情景对齐——先精确规范名匹配，失败再按判定标准 token 重叠合并。

    多种子集成的三个种子会给同一个情景起不同的自由名（中英混排、'S1 — …' 前缀等），
    仅按规范名分桶会把它们打散成 support=1 的孤桶、一致度误报 0。这里在名字匹配不中时，
    用 resolution_criteria 的 token Jaccard（阈值 ``min_overlap``，默认
    Config.ENSEMBLE_ALIGN_MIN_OVERLAP=0.34）把跨 run 的同义情景并进同一桶；同一 run 内的
    两个情景按设计互斥，绝不互并（same-run guard）。

    返回 bucket 列表（首见顺序）：
    ``{name, names, criteria, tokens, entries: [(run_idx, scenario)], runs: set[int]}``。
    """
    if min_overlap is None:
        try:
            min_overlap = float(_cfg("ENSEMBLE_ALIGN_MIN_OVERLAP", 0.34) or 0.34)
        except (TypeError, ValueError):
            min_overlap = 0.34
    buckets: List[Dict[str, Any]] = []
    by_name: Dict[str, Dict[str, Any]] = {}
    for ri, f in enumerate(runs or []):
        if not isinstance(f, dict):
            continue
        for s in (f.get("scenarios") or []):
            if not isinstance(s, dict):
                continue
            key = _norm_name(s.get("name"))
            if not key:
                continue
            b = by_name.get(key)
            crit_toks = _scenario_tokens(s.get("resolution_criteria"))
            if b is None and crit_toks:
                # 名字不中 → 按判据 token 重叠找最佳既有桶（跳过含同 run 情景的桶）。
                best, best_ov = None, 0.0
                for cand in buckets:
                    if ri in cand["runs"]:
                        continue
                    ov = _token_overlap(crit_toks, cand["tokens"])
                    if ov > best_ov:
                        best, best_ov = cand, ov
                if best is not None and best_ov >= min_overlap:
                    b = best
            if b is None:
                b = {
                    "name": s.get("name"),
                    "names": [],
                    "criteria": str(s.get("resolution_criteria") or ""),
                    "tokens": set(crit_toks),
                    "entries": [],
                    "runs": set(),
                }
                buckets.append(b)
            b["entries"].append((ri, s))
            b["runs"].add(ri)
            b["tokens"] |= crit_toks
            nm = str(s.get("name") or "").strip()
            if nm and nm not in b["names"]:
                b["names"].append(nm)
            # 该桶的所有别名（含语义并入的名字）都指向同一桶，后续同名精确命中。
            by_name.setdefault(key, b)
    return buckets


def _extremized_logodds(probs: List[float], a: float, eps: float = 1e-6) -> float:
    """R2-CAL-2: geometric (log-odds) pool of probabilities with extremizing factor a.

    pooled = sigmoid( a * mean(logit(p_i)) ). a=1 is plain geometric-odds pooling;
    a>1 sharpens toward 0/1 (counteracts the under-confidence of arithmetic averaging).
    """
    ls = []
    for p in probs:
        try:
            pf = float(p)
        except (TypeError, ValueError):
            continue
        pf = min(1.0 - eps, max(eps, pf))
        ls.append(math.log(pf / (1.0 - pf)))
    if not ls:
        return 0.0
    z = a * (sum(ls) / len(ls))
    z = max(-50.0, min(50.0, z))  # guard exp overflow
    return 1.0 / (1.0 + math.exp(-z))


def _mean(xs: List[float]) -> float:
    return sum(xs) / len(xs) if xs else 0.0


def _stdev(xs: List[float]) -> float:
    if len(xs) < 2:
        return 0.0
    m = _mean(xs)
    return math.sqrt(sum((x - m) ** 2 for x in xs) / (len(xs) - 1))


def aggregate_forecasts(forecasts: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Aggregate N structured-forecast dicts (from forecast_extractor) into one.

    Scenarios are matched across runs by normalized name; with
    ``ENSEMBLE_SEMANTIC_ALIGN`` (default on, W9-5) name misses fall back to
    resolution-criteria token overlap so the same scenario under freeform /
    mixed-language names still lands in one bucket. For each matched scenario we
    report the mean probability, spread (stdev + min/max as a CI proxy), and how
    many of the N runs surfaced it (support). Probabilities are renormalized to
    sum to 1. ``agreement`` ∈ [0,1]（对齐后有效共识桶 <2 时为 None——无法判定，
    而非误报 0）。
    """
    runs = [f for f in (forecasts or []) if isinstance(f, dict)]
    # REPORT-1：概率待复核（needs_review，含 null 概率）的 run 不参与池化——null 绝不以 0
    # 计入均值；仅当确有剔除时才记 n_runs_excluded（格式良好的集成输出逐字节不变）。
    excluded = sum(1 for f in runs if f.get("probability_status") == "needs_review")
    if excluded:
        runs = [f for f in runs if f.get("probability_status") != "needs_review"]
    n = len(runs)
    if n == 0:
        empty: Dict[str, Any] = {"n_runs": 0, "scenarios": [], "agreement": None, "schema_version": 1}
        if excluded:
            empty["n_runs_excluded"] = excluded
        return empty

    semantic = bool(_cfg("ENSEMBLE_SEMANTIC_ALIGN", True))
    aligned: Optional[List[Dict[str, Any]]] = None
    buckets: Dict[str, Dict[str, Any]] = {}
    if semantic:
        aligned = align_scenario_buckets(runs)
        for i, ab in enumerate(aligned):
            b = {"name": ab["name"], "probs": [], "drivers": set(), "criteria": "",
                 "aliases": list(ab.get("names") or [])}
            for _ri, s in ab["entries"]:
                try:
                    b["probs"].append(float(s.get("probability") or 0.0))
                except (TypeError, ValueError):
                    pass
                for d in (s.get("key_drivers") or []):
                    b["drivers"].add(str(d))
                if not b["criteria"] and s.get("resolution_criteria"):
                    b["criteria"] = str(s.get("resolution_criteria"))
            buckets[f"__bucket_{i}"] = b
    else:
        # legacy 精确规范名分桶（ENSEMBLE_SEMANTIC_ALIGN=false 时逐字节复现旧行为）
        for f in runs:
            for s in (f.get("scenarios") or []):
                if not isinstance(s, dict):
                    continue
                key = _norm_name(s.get("name"))
                if not key:
                    continue
                b = buckets.setdefault(key, {"name": s.get("name"), "probs": [], "drivers": set(), "criteria": ""})
                try:
                    b["probs"].append(float(s.get("probability") or 0.0))
                except (TypeError, ValueError):
                    pass
                for d in (s.get("key_drivers") or []):
                    b["drivers"].add(str(d))
                if not b["criteria"] and s.get("resolution_criteria"):
                    b["criteria"] = str(s.get("resolution_criteria"))

    # R2-CAL-2：用 extremizing log-odds（几何）池化作为发布概率；算术均值保留为诊断。
    # ENSEMBLE_EXTREMIZE_A 未设置时 → 退回算术均值（默认路径逐字节一致，degrade-safe）。
    a_raw = _cfg("ENSEMBLE_EXTREMIZE_A", None)
    try:
        a = float(a_raw) if a_raw is not None else None
    except (TypeError, ValueError):
        a = None

    agg = []
    for b in buckets.values():
        probs = b["probs"] or [0.0]
        mean_p = _mean(probs)
        sd = _stdev(probs)
        row = {
            "name": b["name"],
            "mean_probability": round(mean_p, 4),       # arithmetic mean (diagnostic)
            "stdev": round(sd, 4),
            "min": round(min(probs), 4),
            "max": round(max(probs), 4),
            "support": len(b["probs"]),          # how many runs surfaced it
            "support_ratio": round(len(b["probs"]) / n, 3),
            "key_drivers": sorted(b["drivers"])[:8],
            "resolution_criteria": b["criteria"],
        }
        # W9-5：语义对齐并入的原始名（>1 个才有信息量），供审计「谁被并进了这个桶」。
        if len(b.get("aliases") or []) > 1:
            row["aliases"] = list(b["aliases"])
        # pre-renormalization point estimate: extremized pool when a is set, else mean
        row["_point"] = _extremized_logodds(probs, a) if a is not None else mean_p
        agg.append(row)

    # renormalize the chosen point estimate to sum to 1
    total = sum(s["_point"] for s in agg)
    for s in agg:
        s["probability"] = round(s["_point"] / total, 4) if total > 0 else 0.0
        # R2-CAL-17：把跨 run 的离散度落成发布区间 [p_low, p_high]（以 stdev 为半宽）。
        s["p_low"] = round(max(0.0, s["probability"] - s["stdev"]), 4)
        s["p_high"] = round(min(1.0, s["probability"] + s["stdev"]), 4)
        s["pooling"] = "extremized_logodds" if a is not None else "arithmetic_mean"
        del s["_point"]
    agg.sort(key=lambda s: s["probability"], reverse=True)

    result: Dict[str, Any] = {
        "n_runs": n,
        "scenarios": agg,
        # R2-CAL-9: TV-distance + support；W9-5：语义对齐时按对齐桶计算，
        # 有效共识桶（support≥2）不足 2 个 → None（无法判定一致度）。
        "agreement": _ensemble_agreement(runs, buckets=aligned),
        "agreement_spread": round(max(0.0, 1.0 - (_mean([s["stdev"] for s in agg]) if agg else 0.0) * 2), 3),
        "semantic_alignment": semantic,
        "extremize_a": a,
        "headline": runs[0].get("headline", ""),
        "horizon": runs[0].get("horizon", ""),
        "schema_version": 1,
    }
    if excluded:
        result["n_runs_excluded"] = excluded
        if n < 2:
            # 剔除后只剩 1 个可读 run：没有可比对象，一致度无法判定（None），绝不以单 run
            # 的 1.0 冒充「高度一致」（编排器据 agreement 映射信心）。
            result["agreement"] = None
            result["agreement_spread"] = None
    return result


def pool_binary_forecasts(primary: List[Dict[str, Any]],
                          secondary: Dict[str, List[Dict[str, Any]]], *,
                          primary_model: str = "primary",
                          extremize_a: Optional[float] = None,
                          spread_threshold: float = 0.15) -> List[str]:
    """ITEM 12：多模型二元预测集成——把主模型与各副模型对同一条二元预测的概率池化（就地改写 primary）。

    ``primary`` 是权威二元预测列表（其陈述/id/判定标准为准）；``secondary`` 为 {模型名: 二元预测列表}
    （各副模型对同一研究档案独立抽取的一遍结果）。逐条 primary 预测，用「归一化陈述」优先、其次「id」
    与每个副模型的预测匹配（同源 F1-Fn 表，故 id/陈述应对齐）；把匹配到的各模型概率与主模型概率一起，
    用与种子集成同一套 extremizing log-odds 池化（``extremize_a`` 给出时；否则退回算术均值）得到发布概率，
    并把 ``{models, probs, pooled, spread}`` 记入 ``binary['ensemble']``、用 pooled 覆盖 ``binary['probability']``。
    ``spread``（各模型概率的样本 stdev）> ``spread_threshold`` 的预测其 id 收进返回列表（low-agreement）。
    某条 primary 无任何副模型匹配 → 保留主模型概率、不加 ensemble 块（unmatched→keep primary）。Pure。
    """
    prim = [b for b in (primary or []) if isinstance(b, dict)]
    if not prim or not secondary:
        return []
    # 复用 forecast_extractor 的陈述归一化键（惰性导入避免模块级循环依赖）。
    try:
        from .forecast_extractor import _binary_key as _bk
    except Exception:  # noqa: BLE001 — 退回等价内联实现
        def _bk(s: Any) -> str:
            return re.sub(r"\W+", " ", str(s or "").lower()).strip()

    # 为每个副模型建两张查找表：陈述键→概率、id→概率（各取首现，忽略非法概率）。
    indexed: Dict[str, Any] = {}
    for model, blist in (secondary or {}).items():
        by_key: Dict[str, float] = {}
        by_id: Dict[str, float] = {}
        for b in (blist or []):
            if not isinstance(b, dict):
                continue
            try:
                pf = float(b.get("probability"))
            except (TypeError, ValueError):
                continue
            k = _bk(b.get("statement"))
            if k and k not in by_key:
                by_key[k] = pf
            bid = str(b.get("id") or "").strip()
            if bid and bid not in by_id:
                by_id[bid] = pf
        indexed[str(model)] = (by_key, by_id)

    try:
        a = float(extremize_a) if extremize_a is not None else None
    except (TypeError, ValueError):
        a = None

    low_agreement: List[str] = []
    for b in prim:
        try:
            p0 = float(b.get("probability"))
        except (TypeError, ValueError):
            continue
        models = [str(primary_model)]
        probs = [p0]
        k = _bk(b.get("statement"))
        bid = str(b.get("id") or "").strip()
        for model, (by_key, by_id) in indexed.items():
            mp: Optional[float] = None
            if k and k in by_key:
                mp = by_key[k]
            elif bid and bid in by_id:
                mp = by_id[bid]
            if mp is not None:
                models.append(model)
                probs.append(mp)
        if len(probs) <= 1:
            continue  # 无副模型匹配 → 保留主模型概率（unmatched→keep primary）
        pooled = _extremized_logodds(probs, a) if a is not None else _mean(probs)
        spread = _stdev(probs)
        b["ensemble"] = {
            "models": models,
            "probs": [round(x, 4) for x in probs],
            "pooled": round(pooled, 4),
            "spread": round(spread, 4),
        }
        b["probability"] = round(pooled, 2)  # 与 _normalize_binaries 的 2 位约定一致
        if spread > spread_threshold:
            _bid = str(b.get("id") or "").strip()
            if _bid:
                low_agreement.append(_bid)
    return low_agreement


def _ensemble_agreement(runs: List[Dict[str, Any]],
                        buckets: Optional[List[Dict[str, Any]]] = None) -> Optional[float]:
    """R2-CAL-9: inter-run agreement = (1 - mean pairwise total-variation distance)
    between each run's scenario distribution, penalized by low scenario support.

    TV(p,q) = 0.5 * sum_i |p_i - q_i| over the union of scenario names (missing→0).
    Each run's distribution is renormalized first so unequal scenario sets compare
    fairly. The support penalty multiplies by the mean per-scenario presence ratio so
    runs that disagree on *which* scenarios exist cannot score a spuriously high
    agreement. Returns 1.0 for a single run (no disagreement), None when empty.

    W9-5：传入 ``buckets``（align_scenario_buckets 的结果）时改按对齐桶而非规范名建
    每 run 分布——跨 run 同义情景在同一坐标轴上比较；且当「有效共识桶」（≥2 个 run
    命中的桶）不足 2 个时返回 None（对齐失败/情景集合根本对不上时不臆造一致度）。
    不传 buckets 时行为与旧签名逐字节一致（degrade-safe）。
    """
    if not runs:
        return None
    dists: List[Dict[str, float]] = []
    if buckets is not None:
        per_run: Dict[int, Dict[str, float]] = {}
        for bi, b in enumerate(buckets):
            for ri, s in (b.get("entries") or []):
                try:
                    p = max(0.0, float(s.get("probability") or 0.0))
                except (TypeError, ValueError):
                    continue
                d = per_run.setdefault(ri, {})
                d[f"b{bi}"] = d.get(f"b{bi}", 0.0) + p
        for _ri in sorted(per_run):
            d = per_run[_ri]
            tot = sum(d.values())
            if tot > 0:
                d = {k: v / tot for k, v in d.items()}
            if d:
                dists.append(d)
        if len(dists) < 2:
            return 1.0
        matched = sum(1 for b in buckets if len(b.get("runs") or ()) >= 2)
        if matched < 2:
            return None
    else:
        for f in runs:
            d: Dict[str, float] = {}
            for s in (f.get("scenarios") or []):
                if not isinstance(s, dict):
                    continue
                k = _norm_name(s.get("name"))
                if not k:
                    continue
                try:
                    d[k] = d.get(k, 0.0) + max(0.0, float(s.get("probability") or 0.0))
                except (TypeError, ValueError):
                    continue
            tot = sum(d.values())
            if tot > 0:
                d = {k: v / tot for k, v in d.items()}
            if d:
                dists.append(d)
        if len(dists) < 2:
            return 1.0
    keys = set().union(*[set(d.keys()) for d in dists])
    tvs = []
    for i in range(len(dists)):
        for j in range(i + 1, len(dists)):
            tv = 0.5 * sum(abs(dists[i].get(k, 0.0) - dists[j].get(k, 0.0)) for k in keys)
            tvs.append(tv)
    agreement_tv = 1.0 - (sum(tvs) / len(tvs) if tvs else 0.0)
    # support penalty: mean fraction of runs in which each scenario appears
    presence = [sum(1 for d in dists if k in d) / len(dists) for k in keys]
    support_factor = sum(presence) / len(presence) if presence else 1.0
    return round(max(0.0, min(1.0, agreement_tv * support_factor)), 3)
