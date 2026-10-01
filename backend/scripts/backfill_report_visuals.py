#!/usr/bin/env python3
"""Backfill outcome-focused visuals/citations for existing forecast reports.

This is offline and deterministic: it reads already-persisted report/pipeline
artifacts, rebuilds ReportVisualizer outputs, removes legacy Mermaid/text blocks,
runs the editorial lint, and re-injects the current manifest. ``--apply`` is
required for writes; every touched report receives a timestamped backup first.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from app.config import Config
from app.services.binary_targets import threshold_ladder_audit
from app.services.report_agent import (
    ReportAgent, ReportManager, _nonfinite_nulled_artifact, render_market_comparison_block,
)
from app.services.forecast_extractor import (
    _binary_quality,
    _binary_withheld_issue,
    _is_circular_market_forecast,
    build_market_comparison,
    reconcile_forecast_contract,
    render_binary_forecasts_block,
    upsert_binary_forecasts_block,
)
from app.services.report_lint import lint_report
from app.services.report_visualizer import ReportVisualizer
from app.utils.atomic import write_json_atomic, write_text_atomic
from app.utils.logger import get_logger
from app.utils.numeric import NonFiniteJSONError

logger = get_logger("mirofish.backfill_report_visuals")

DEFAULT_TARGETS = (
    ("pipe_f23527f7d903", "report_a03be154febc"),
    ("pipe_0f2bee7bd649", "report_1c312b400d33"),
    ("pipe_a8986bffd918", "report_1b70ace5c9e8"),
)
_REPORT_ID_RE = re.compile(r"^report_[A-Za-z0-9_-]+$")
_PIPELINE_ID_RE = re.compile(r"^pipe_[A-Za-z0-9_-]+$")
_VISUAL_ANNEX_RE = re.compile(r"^(?:visual annex|可视化附录(?:（visual annex）)?)$", re.I)
_CJK_RUN_RE = re.compile(r"[一-鿿㐀-䶿぀-ヿ가-힯]{2,}")
_LATIN_PROSE_RE = re.compile(r"[A-Za-z][A-Za-z0-9 ,.'’\-()%/&]{39,}")
_INLINE_PROTECTED_RE = re.compile(r"`[^`\n]*`|https?://[^\s)>\]}]+", re.I)
_RESIDUAL_SCENARIO_KEYS = (
    "维持现状", "其它", "其他", "兜底", "status quo", "other", "baseline",
)
_ZH_VISUAL_TITLES = {
    "scenario_probabilities": "情景概率（含集成离散度）",
    "binary_forecast_dotplot": "二元预测胜率与置信度",
    "model_vs_market": "模型概率与市场隐含概率",
    "timeline_lanes": "关键事件时间线",
    "actor_network": "关键行为者关系网络",
    "actor_influence_salience": "行为者影响力与显著度",
    "source_mix_sunburst": "来源层级、类型与可达性",
    "quantitative_claims": "关键定量断言",
    "driver_tornado": "关键预测驱动因素",
    "contested_claims": "争议断言与证据权重",
    "worldstate_trajectory": "预测结果份额轨迹",
}


class _Report:
    def __init__(self, markdown_content: str):
        self.markdown_content = markdown_content


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return None


def _write_forecast_artifact(path: Path, obj: Any, *, record_quality: bool = False) -> Any:
    """Write forecast.json or market_comparison.json; returns the object written.

    INFRA-4 (ARTIFACT_STRICT_JSON, default on): like the live report writer, never write NaN or
    Infinity. A non-finite leaf is logged and set to null in a copy (``obj`` is not mutated);
    with ``record_quality`` (forecast.json) its JSON path joins quality.nonfinite_nulled.
    Finite content is written byte for byte as before; off, the legacy write.
    """
    if not getattr(Config, "ARTIFACT_STRICT_JSON", True):
        write_json_atomic(str(path), obj)
        return obj
    try:
        write_json_atomic(str(path), obj, allow_nan=False)
        return obj
    except NonFiniteJSONError as exc:
        cleaned, paths = _nonfinite_nulled_artifact(obj, record_quality=record_quality)
        write_json_atomic(str(path), cleaned, allow_nan=False)
        logger.error(f"{path.name}: {exc}; written as standard JSON "
                     f"({len(paths)} non-finite value(s) set to null)")
        return cleaned


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def strip_generated_visuals(markdown: str) -> str:
    """Remove generated Visual Annex sections and marker-owned legacy blocks."""
    lines = str(markdown or "").split("\n")
    without_annex: List[str] = []
    i = 0
    while i < len(lines):
        heading = re.match(r"^##\s+(.+?)\s*$", lines[i].strip())
        if heading and _VISUAL_ANNEX_RE.match(heading.group(1).strip()):
            i += 1
            while i < len(lines) and not re.match(r"^##\s+", lines[i].strip()):
                i += 1
            continue
        without_annex.append(lines[i])
        i += 1

    out: List[str] = []
    i = 0
    while i < len(without_annex):
        if not re.match(r"^\s*<!--\s*viz:[^>]+-->\s*$", without_annex[i]):
            out.append(without_annex[i])
            i += 1
            continue
        i += 1
        while i < len(without_annex) and not without_annex[i].strip():
            i += 1
        if i < len(without_annex) and re.match(r"^\*\*.*\*\*\s*$", without_annex[i]):
            i += 1
            while i < len(without_annex) and not without_annex[i].strip():
                i += 1
        if i < len(without_annex) and without_annex[i].lstrip().startswith(("```", "~~~")):
            fence = without_annex[i].lstrip()[:3]
            i += 1
            while i < len(without_annex):
                closing = without_annex[i].lstrip().startswith(fence)
                i += 1
                if closing:
                    break
        elif i < len(without_annex) and (
                without_annex[i].lstrip().startswith("![")
                or re.match(r"^\*\*.*\*\*\s*[:：]", without_annex[i].strip())):
            i += 1
        while i < len(without_annex) and not without_annex[i].strip():
            i += 1
        if i < len(without_annex) and re.match(r"^\*[^*].*\*\s*$", without_annex[i].strip()):
            i += 1
        while i < len(without_annex) and not without_annex[i].strip():
            i += 1
        if out and out[-1].strip():
            out.append("")
    return re.sub(r"\n{3,}", "\n\n", "\n".join(out)).strip() + "\n"


def drop_irreparable_language_lines(
        markdown: str, language: str) -> Tuple[str, int]:
    """Offline-only repair for legacy prose that cannot be translated safely.

    Live generation uses the model-backed language-purity repair. Historical
    replay is deliberately network-free, so a foreign-language prose line is
    removed instead of shipping a broken mixed sentence or fabricating a
    translation. Table shape and image assets are preserved by redacting only
    contaminated cells/alt text. References retain original publication titles.
    """
    english = str(language or "").strip().lower().startswith("en")

    def contaminated(text: str) -> bool:
        scan = _INLINE_PROTECTED_RE.sub(" ", text)
        if english:
            return bool(_CJK_RUN_RE.search(scan))
        return any(match.count(" ") >= 4 for match in _LATIN_PROSE_RE.findall(scan))

    lines = str(markdown or "").split("\n")
    out: List[str] = []
    in_fence = False
    in_references = False
    removed = 0
    for line in lines:
        stripped = line.strip()
        if stripped.startswith(("```", "~~~")):
            in_fence = not in_fence
            out.append(line)
            continue
        if in_fence:
            out.append(line)
            continue
        if stripped in ("## References", "## 参考来源"):
            in_references = True
            out.append(line)
            continue
        if in_references or not stripped or not contaminated(stripped):
            out.append(line)
            continue
        removed += 1
        if stripped.startswith("|") and "|" in stripped:
            cells = line.split("|")
            out.append("|".join(
                " — " if contaminated(cell) else cell for cell in cells))
        elif "![" in line and "](" in line:
            out.append(re.sub(r"!\[[^\]]*\]", "![Visualization]", line))
        else:
            # Deleting the whole broken sentence is more truthful than keeping
            # isolated English/CJK fragments with corrupted grammar.
            out.append("")
    return re.sub(r"\n{3,}", "\n\n", "\n".join(out)).strip() + "\n", removed


def ensure_baseline_scenario_label(
        forecast: Dict[str, Any]) -> Optional[Tuple[str, str]]:
    """Label the existing modal path as baseline without changing probabilities."""
    scenarios = [
        row for row in (forecast.get("scenarios") or []) if isinstance(row, dict)
    ]
    if not scenarios or any(
        any(key in str(row.get("name") or "").lower()
            for key in _RESIDUAL_SCENARIO_KEYS)
        for row in scenarios
    ):
        return None
    candidate = max(
        scenarios,
        key=lambda row: (
            1 if re.search(r"\b(?:modal|base)\b", str(row.get("name") or ""), re.I)
            else 0,
            float(row.get("probability") or 0.0),
        ),
    )
    old = str(candidate.get("name") or "").strip()
    if not old:
        return None
    prefix = (
        "基线/维持现状 — " if _CJK_RUN_RE.search(old)
        else "Baseline / Status Quo — "
    )
    new = prefix + old
    candidate["name"] = new
    return old, new


def strip_circular_binary_rows(
        markdown: str,
        forecast_ids: Iterable[str],
        *,
        quality: Optional[Dict[str, Any]] = None) -> Tuple[str, int]:
    """Drop circular rows and synchronize bilingual forecast-count summaries."""
    ids = {str(value).strip() for value in forecast_ids if str(value).strip()}
    kept: List[str] = []
    removed = 0
    row_re = re.compile(r"^\|\s*([^|]+?)\s*\|")
    for line in str(markdown or "").split("\n"):
        match = row_re.match(line.strip())
        if match and match.group(1).strip() in ids:
            removed += 1
            continue
        kept.append(line)
    out = "\n".join(kept)
    if removed or isinstance(quality, dict):
        binary_rows = [
            line for line in kept
            if re.match(r"^\|\s*F\d+\s*\|", line.strip(), re.I)
        ]
        probabilities: List[int] = []
        for line in binary_rows:
            cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
            if len(cells) >= 3:
                match = re.fullmatch(r"(\d{1,3})%", cells[2])
                if match:
                    probabilities.append(int(match.group(1)))
        fallback_conviction = sum(value >= 70 or value <= 30 for value in probabilities)
        quality = quality if isinstance(quality, dict) else {}
        count_value = quality.get("count")
        conviction_value = quality.get("conviction_count")
        sharp_value = quality.get("sharp_criteria_count")
        count = int(count_value) if isinstance(count_value, (int, float)) else len(binary_rows)
        conviction = (int(conviction_value) if isinstance(conviction_value, (int, float))
                      else fallback_conviction)
        sharp_criteria = (int(sharp_value) if isinstance(sharp_value, (int, float))
                          else len(binary_rows))
        english_summary = (
            f"_{count} forecasts; {conviction} high-conviction "
            f"(≥70% or ≤30%); {sharp_criteria} with objective criteria._"
        )
        chinese_summary = (
            f"_共 {count} 项预测；其中 {conviction} 项为高确信度预测"
            f"（≥70% 或 ≤30%）；{sharp_criteria} 项具备客观判定标准。_"
        )
        out = re.sub(
            r"_\d+\s+forecasts;[^_\n]*_", english_summary, out, count=1, flags=re.I)
        out = re.sub(r"_共\s*\d+\s*项预测[^_\n]*_", chinese_summary, out, count=1)
    return out, removed


def synchronize_market_comparison(
        report_dir: Path, forecast: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Rebuild both comparison copies from the retained canonical binaries.

    A removed circular forecast must not remain in either the embedded payload
    or ``market_comparison.json``. If no retained binary has a market anchor,
    both stale copies are removed.
    """
    binaries = [
        row for row in (forecast.get("binary_forecasts") or [])
        if isinstance(row, dict)
    ]
    for row in binaries:
        anchor = row.get("market_anchor")
        if not isinstance(anchor, dict):
            continue
        try:
            model_probability = float(row.get("probability"))
            implied_probability = float(anchor.get("implied_yes_prob"))
        except (TypeError, ValueError):
            anchor.pop("divergence", None)
            continue
        anchor["divergence"] = round(model_probability - implied_probability, 4)
    comparison = build_market_comparison(binaries)
    standalone = report_dir / "market_comparison.json"
    if comparison.get("comparisons"):
        forecast["market_comparison"] = comparison
        # INFRA-4: the embedded copy keeps a non-finite value until forecast.json is written,
        # which nulls it and records its path.
        _write_forecast_artifact(standalone, comparison)
        return comparison
    forecast.pop("market_comparison", None)
    try:
        standalone.unlink()
    except FileNotFoundError:
        pass
    return None


def rebuild_binary_quality(
        binaries: List[Dict[str, Any]], contract: Any, old_quality: Any) -> Dict[str, Any]:
    """The binary_quality of a replayed forecast, rebuilt over the retained rows.

    The scorecard is recomputed and carries the reconcile result; the extractor's
    ensemble block is kept. A report written with FORECAST_BINARY_STRUCTURED_TARGET
    (EVAL-14: its old block has ``threshold_ladder``, or a retained row still has a
    validated ``target``) gets the threshold-ladder audit recomputed over the retained
    rows, so a replay neither drops the audit nor keeps a removed rung in it.
    """
    old = old_quality if isinstance(old_quality, dict) else {}
    quality = _binary_quality(binaries, min_count=10)
    quality["proposition_consistency"] = contract
    if isinstance(old.get("ensemble"), dict):
        quality["ensemble"] = old["ensemble"]
    if "threshold_ladder" in old or any(isinstance(row.get("target"), dict) for row in binaries):
        quality["threshold_ladder"] = threshold_ladder_audit(binaries)
    return quality


def _report_completed_at(meta: Any) -> Optional[datetime]:
    """When the report completed (meta.json ``completed_at``), in UTC; None when unknown.

    A naive stamp is local time, as generate_report writes it (scripts/eval_bundle.py reads
    it the same way)."""
    stamp = meta.get("completed_at") if isinstance(meta, dict) else None
    if not isinstance(stamp, str) or not stamp.strip():
        return None
    try:
        return datetime.fromisoformat(stamp.strip()).astimezone(timezone.utc)
    except (ValueError, OverflowError, OSError):
        return None


def _language(markdown: str, filename: str) -> str:
    if filename.endswith(".zh.md"):
        return "Chinese"
    if filename.endswith(".en.md"):
        return "English"
    sample = markdown[:20_000]
    cjk = len(re.findall(r"[一-鿿]", sample))
    return "Chinese" if cjk > max(1, len(sample)) * 0.05 else "English"


def localized_manifest(
        manifest: List[Dict[str, Any]], language: str) -> List[Dict[str, Any]]:
    """Localize reader-facing chart captions without changing chart identity/data."""
    if not str(language or "").strip().lower().startswith("chinese"):
        return [dict(item) for item in manifest if isinstance(item, dict)]
    localized: List[Dict[str, Any]] = []
    for item in manifest:
        if not isinstance(item, dict):
            continue
        row = dict(item)
        title = _ZH_VISUAL_TITLES.get(str(row.get("id") or ""))
        if title:
            row["title"] = title
            row["caption"] = title
        localized.append(row)
    return localized


def _artifacts(report_dir: Path, handoff: Path, simulation_id: str) -> Dict[str, Any]:
    result: Dict[str, Any] = {"handoff_dir": str(handoff)}
    for key, path in (
        ("forecast", report_dir / "forecast.json"),
        ("ensemble", report_dir / "ensemble_forecast.json"),
        ("comparison", report_dir / "comparison.json"),
        ("actors", handoff / "actors.json"),
        ("timeline", handoff / "timeline.json"),
        ("quantitative", handoff / "quantitative.json"),
        ("sources", handoff / "sources.json"),
        ("contested", handoff / "contested.json"),
        ("prediction_markets", handoff / "prediction_markets.json"),
        ("graph_priors", handoff / "graph_priors.json"),
        ("graph_priors_structural", handoff / "graph_priors_structural.json"),
    ):
        value = _read_json(path)
        if value not in (None, [], {}):
            result[key] = value
    worldstate = Path(Config.OASIS_SIMULATION_DATA_DIR) / simulation_id / "world_state_trajectory.json"
    value = _read_json(worldstate)
    if value:
        result["world_state_trajectory"] = value
    return result


def _offline_report_agent(
        language: str, sources: List[Dict[str, Any]], handoff: Path,
        artifacts: Dict[str, Any], forecast: Any) -> ReportAgent:
    """Reconstruct the subset of live ReportAgent state used by final repair/audit."""
    agent = ReportAgent.__new__(ReportAgent)
    agent.sources = sources
    agent._citation_index = {}
    agent.output_language = language
    agent.research_report = _read_text(handoff / "research_report.md")
    agent._outline_summary = ""
    agent._background_block = ""
    actors_obj = artifacts.get("actors")
    situation = (
        actors_obj.get("situation_brief")
        if isinstance(actors_obj, dict) else None
    )
    agent.situation_brief = (
        json.dumps(situation, ensure_ascii=False)
        if isinstance(situation, (dict, list)) else str(situation or "")
    )
    agent._forecast_spine = forecast if isinstance(forecast, dict) else None
    return agent


def _recorded_market_rows(snapshot: Any, previous: Any) -> List[Dict[str, Any]]:
    """The markets the run's previous figure_provenance.json recorded, as handoff snapshot
    rows (their question anchors the check) carrying the recorded prices and stamps."""
    recorded: Dict[str, Dict[str, Any]] = {}
    for row in (previous.get("market_rows") or []) if isinstance(previous, dict) else []:
        if isinstance(row, dict) and str(row.get("market_id") or "").strip():
            recorded.setdefault(str(row["market_id"]).strip(), row)
    markets = snapshot.get("markets") if isinstance(snapshot, dict) else snapshot
    rows: List[Dict[str, Any]] = []
    for market in markets if isinstance(markets, list) else []:
        prior = recorded.get(str(market.get("market_id") or "").strip()) if isinstance(market, dict) else None
        if prior is not None:
            rows.append(dict(market, **{key: prior.get(key) for key in
                                        ("implied_yes_prob", "price_at_research", "quoted_at", "snapshot_as_of")}))
    return rows


def _attach_verified_figure_inputs(agent: ReportAgent, artifacts: Dict[str, Any], report_dir: Path) -> None:
    """REPORT-9: the live run's inputs of the shadow verified-figure check, so the re-audit
    measures the replayed bytes instead of dropping the run's quality.verified_figures and
    figure_provenance.json (the shadow data an enforcement decision needs).

    The verified-figures block and its excluded rows are rebuilt from the handoff as the
    report built them (research quantitative rows, sources, research report, the actors'
    as-of date; RESEARCH-5's observe-only projection-attribution audit reads the same
    rows).  The report re-quoted its markets live, which an offline replay cannot redo:
    the market rows are the handoff snapshot's markets that the previous
    figure_provenance.json recorded, with the prices it recorded, and none without such a
    record (a research-time price would read a re-quoted one as a market conflict).  Call
    it only after every Markdown repair: market rows change what the stabilizer's
    quantitative grounding keeps.  Never raises; with no block the re-audit records
    nothing and the sidecar is removed, as before."""
    try:
        quantitative = artifacts.get("quantitative")
        actors = artifacts.get("actors")
        agent.quantitative = quantitative if isinstance(quantitative, list) and quantitative else None
        agent.actors = actors if isinstance(actors, dict) else None
        agent._prediction_markets = _recorded_market_rows(
            artifacts.get("prediction_markets"), _read_json(report_dir / "figure_provenance.json"))
        if getattr(Config, "REPORT_VERIFIED_FACTS_BLOCK", True):
            agent._build_verified_figures_block()
    except Exception as exc:  # noqa: BLE001 — shadow inputs only; the audit runs regardless
        logger.warning(f"verified-figure check inputs not rebuilt (shadow record dropped): {exc}")


def _backup(report_dir: Path) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = report_dir / f".codex-backup-{stamp}"
    backup.mkdir(parents=False, exist_ok=False)
    for path in report_dir.glob("full_report*.md"):
        shutil.copy2(path, backup / path.name)
    for path in report_dir.glob("full_report*.pdf"):
        shutil.copy2(path, backup / path.name)
    for name in (
            "meta.json", "forecast.json", "market_comparison.json",
            "viz_manifest.json", "pdf_export.json", "figure_provenance.json"):
        path = report_dir / name
        if path.exists():
            shutil.copy2(path, backup / name)
    for pattern in ("citations*.json", "final_audit*.json"):
        for path in report_dir.glob(pattern):
            shutil.copy2(path, backup / path.name)
    charts = report_dir / "charts"
    if charts.is_dir():
        shutil.copytree(charts, backup / "charts", symlinks=True)
    return backup


def _restore_from_backup(report_dir: Path, backup: Path) -> None:
    """Restore every artifact family mutated by a replay attempt."""
    for pattern in (
        "full_report*.md", "full_report*.pdf", "citations*.json",
        "final_audit*.json",
    ):
        for path in report_dir.glob(pattern):
            if path.is_file() or path.is_symlink():
                path.unlink()
    for name in (
        "meta.json", "forecast.json", "market_comparison.json",
        "viz_manifest.json", "pdf_export.json", "figure_provenance.json",
    ):
        path = report_dir / name
        if path.exists() or path.is_symlink():
            path.unlink()
    charts = report_dir / "charts"
    if charts.exists() or charts.is_symlink():
        if charts.is_dir() and not charts.is_symlink():
            shutil.rmtree(charts)
        else:
            charts.unlink()
    for path in backup.iterdir():
        if path.name in {"charts", "replay_failure.json"}:
            continue
        if path.is_file():
            shutil.copy2(path, report_dir / path.name)
    if (backup / "charts").is_dir():
        shutil.copytree(backup / "charts", charts, symlinks=True)


# FU-1 (EVAL-10 open issue): the scorecard lines _binary_quality writes, which the
# backfill rebuilds from the retained rows. The withheld line is rebuilt from
# needs_review_count, the provenance line from the recounted downgrades and the ensemble
# line from the binary ids it names that are still retained; every other stored issue
# line is carried in its stored order.
_SCORE_ISSUE_RES = tuple(re.compile(pattern) for pattern in (
    r"only \d+ binaries \(< \d+\)",
    r"probability spread too low \(stdev -?[0-9.]+\) — hedging",
    r"\d+/\d+ forecasts in 0\.40-0\.60 — under-committed",
    r"fewer than 3 high-conviction calls \(p>=0\.70 or <=0\.30\)",
    r"only \d+/\d+ have objective metric\+number\+date criteria",
    r"all forecasts share a single theme — no thematic spread",
))
_WITHHELD_ISSUE_RE = re.compile(r"\d+ binary probabilities unreadable — withheld, not clamped")
_PROVENANCE_ISSUE_RE = re.compile(
    r"\d+ forecast\(s\) claimed a simulation signal that was never injected into the prompt "
    r"— source downgraded to research-prior \(see source_claimed\)")
# Groups: the spread threshold as written, then the comma-separated binary ids.
_ENSEMBLE_ISSUE_RE = re.compile(
    r"\d+ forecast\(s\) show cross-model disagreement \(spread > ([^\s)]+)\): (.+)")


def _provenance_issue(count: int) -> str:
    """The extractor's provenance-downgrade issue line (forecast_extractor wording)."""
    return (f"{count} forecast(s) claimed a simulation signal that was never "
            "injected into the prompt — source downgraded to research-prior (see source_claimed)")


def _ensemble_issue(ids: List[str], spread_threshold: str) -> str:
    """The extractor's cross-model disagreement issue line (forecast_extractor wording)."""
    return (f"{len(ids)} forecast(s) show cross-model disagreement "
            f"(spread > {spread_threshold}): {', '.join(ids)}")


def carry_binary_quality(old_quality: Dict[str, Any], quality: Dict[str, Any],
                         retained: List[Dict[str, Any]]) -> Dict[str, Any]:
    """``quality`` (the scorecard rebuilt from ``retained``) completed from the stored
    ``old_quality`` (FU-1): every key the rebuild does not produce is kept as stored
    (world_state_outcome, needs_review_*, market_window_ended_excluded and the other
    extractor-only keys do not depend on which published rows remain), except
    ``ensemble``, which the caller keeps only when it is a dict (as before FU-1), and
    ``provenance_downgrades``, which is recounted from the retained rows (rows the
    extractor downgraded carry ``source_claimed``).  Issue lines: the withheld line
    first (as the extractor and ReportAgent order it), the rebuilt scorecard lines,
    then the stored lines that are not scorecard lines in their stored order, the
    provenance line restated with the recounted number (dropped at zero; written after
    the scorecard lines, where the extractor puts it, when a non-zero count has no
    stored line), the ensemble line restated without the ids of rows that are no
    longer retained (dropped when none remains; the ``ensemble`` block itself, which
    the Part-1 footnote reads, stays as stored).  Only a list of stored issue lines is
    read.  Mutates and returns ``quality``."""
    for key, value in old_quality.items():
        if key not in ("issues", "ensemble") and key not in quality:
            quality[key] = value
    downgrades: Optional[int] = None
    if "provenance_downgrades" in old_quality:
        downgrades = sum(1 for row in retained if "source_claimed" in row)
        quality["provenance_downgrades"] = downgrades
    retained_ids = {str(row.get("id") or "").strip() for row in retained}
    issues = quality.setdefault("issues", [])
    if quality.get("needs_review_count"):
        issues.insert(0, _binary_withheld_issue(quality["needs_review_count"]))
    scorecard_end = len(issues)
    provenance_stored = False
    stored_issues = old_quality.get("issues")
    for line in stored_issues if isinstance(stored_issues, list) else []:
        if not isinstance(line, str):
            continue
        disagreement = _ENSEMBLE_ISSUE_RE.fullmatch(line)
        if _PROVENANCE_ISSUE_RE.fullmatch(line) and downgrades is not None:
            provenance_stored = True
            line = _provenance_issue(downgrades) if downgrades else ""
        elif _WITHHELD_ISSUE_RE.fullmatch(line) or any(r.fullmatch(line) for r in _SCORE_ISSUE_RES):
            continue
        elif disagreement:
            named = disagreement.group(2).split(", ")
            kept = [bid for bid in named if bid in retained_ids]
            if kept != named:
                line = _ensemble_issue(kept, disagreement.group(1)) if kept else ""
        if line and line not in issues:
            issues.append(line)
    if downgrades and not provenance_stored:
        issues.insert(scorecard_end, _provenance_issue(downgrades))
    return quality


def _backfill_one_impl(pipeline_id: str, report_id: str, *, apply: bool) -> Dict[str, Any]:
    if not _PIPELINE_ID_RE.fullmatch(pipeline_id) or not _REPORT_ID_RE.fullmatch(report_id):
        raise ValueError("invalid pipeline/report id")
    pipeline_dir = Path(Config.PIPELINE_DATA_DIR) / pipeline_id
    state = _read_json(pipeline_dir / "pipeline_state.json") or {}
    if state.get("report_id") != report_id:
        raise ValueError(f"{pipeline_id} does not own {report_id}")
    report_dir = Path(ReportManager._get_report_folder(report_id)).resolve()
    if not report_dir.is_dir():
        raise FileNotFoundError(report_dir)
    handoff = Path(state.get("handoff_dir") or pipeline_dir / "handoff").resolve()
    simulation_id = str(state.get("simulation_id") or "")
    markdown_paths = sorted(report_dir.glob("full_report*.md"))
    plan = {
        "pipeline_id": pipeline_id,
        "report_id": report_id,
        "simulation_id": simulation_id,
        "markdown_files": [path.name for path in markdown_paths],
        "apply": apply,
    }
    if not apply:
        return plan

    backup = _backup(report_dir)
    artifacts = _artifacts(report_dir, handoff, simulation_id)
    forecast_obj = artifacts.get("forecast")
    circular_ids: List[str] = []
    scenario_label_change: Optional[Tuple[str, str]] = None
    if isinstance(forecast_obj, dict):
        binaries = [row for row in (forecast_obj.get("binary_forecasts") or [])
                    if isinstance(row, dict)]
        circular_ids = [
            str(row.get("id") or "").strip() for row in binaries
            if _is_circular_market_forecast(
                row.get("statement"), row.get("resolution_criteria"))
        ]
        circular_set = set(circular_ids)
        retained = [row for row in binaries if str(row.get("id") or "").strip()
                    not in circular_set]
        forecast_obj["binary_forecasts"] = retained
        contract = reconcile_forecast_contract(forecast_obj)
        retained = [
            row for row in (forecast_obj.get("binary_forecasts") or [])
            if isinstance(row, dict)
        ]
        old_quality = forecast_obj.get("binary_quality") if isinstance(
            forecast_obj.get("binary_quality"), dict) else {}
        # The rebuild recomputes the scorecard and (EVAL-14) the threshold-ladder audit;
        # carry only fills the keys the rebuild did not produce (FU-1), so a stale
        # stored ladder never overrides the recomputed one.
        quality = rebuild_binary_quality(retained, contract, old_quality)
        forecast_obj["binary_quality"] = carry_binary_quality(old_quality, quality, retained)
        # Always rebuild/remove both comparison copies. This repairs a stale
        # partial backfill even after the offending circular binary was already
        # removed by an earlier attempt.
        synchronize_market_comparison(report_dir, forecast_obj)
        scenario_label_change = ensure_baseline_scenario_label(forecast_obj)
        # INFRA-4: keep rendering what was written (non-finite leaves nulled).
        forecast_obj = artifacts["forecast"] = _write_forecast_artifact(
            report_dir / "forecast.json", forecast_obj, record_quality=True)
    manifest = ReportVisualizer().build_all(report_id, str(report_dir), artifacts)
    sources = artifacts.get("sources") or []
    main_lint: Optional[Dict[str, Any]] = None
    main_markdown = ""
    main_agent: Optional[ReportAgent] = None
    language_lines_removed = 0
    ungrounded_quotes_removed = 0

    # Primary report is the only artifact eligible for deterministic prose repair.
    # Language variants are audited against these finalized bytes later; replay must
    # never delete translated prose/headings to manufacture a passing variant.
    primary_path = report_dir / "full_report.md"
    if primary_path not in markdown_paths:
        raise FileNotFoundError(primary_path)
    original = _read_text(primary_path)
    primary_language = _language(original, primary_path.name)
    cleaned = strip_generated_visuals(original)
    if scenario_label_change:
        cleaned = cleaned.replace(*scenario_label_change)
    quality = forecast_obj.get("binary_quality") if isinstance(forecast_obj, dict) else None
    cleaned, _ = strip_circular_binary_rows(cleaned, circular_ids, quality=quality)
    if isinstance(forecast_obj, dict):
        binary_block = render_binary_forecasts_block(
            forecast_obj, language=primary_language)
        # FU-5: window-ended labels are judged at the report's own completion time, never
        # the replay day; when that time is unknown only the stamps saved with the report
        # count, so replaying the same artifacts always writes the same bytes.
        completed_at = _report_completed_at(_read_json(report_dir / "meta.json"))
        market_block = render_market_comparison_block(
            forecast_obj,
            markets=artifacts.get("prediction_markets") or [],
            lang=primary_language,
            now=completed_at,
            restamp=completed_at is not None,
        )
        if market_block:
            binary_block = binary_block + "\n\n" + market_block
        cleaned, _part1_action = upsert_binary_forecasts_block(
            cleaned, binary_block)
    cleaned, removed_language = drop_irreparable_language_lines(
        cleaned, primary_language)
    language_lines_removed += removed_language
    main_agent = _offline_report_agent(
        primary_language, sources, handoff, artifacts, forecast_obj)
    cleaned, removed_quotes = main_agent._repair_quote_grounding(cleaned)
    ungrounded_quotes_removed += removed_quotes
    cleaned, main_lint = lint_report(
        cleaned, primary_language, mode="final", spine=artifacts.get("forecast"))
    placer = ReportAgent.__new__(ReportAgent)
    placer.output_language = primary_language
    updated = placer._place_visualizations(cleaned, str(report_dir), manifest)
    primary_report = _Report(updated)
    stabilization = main_agent._stabilize_publish_markdown(
        report_id, primary_report)
    ungrounded_quotes_removed += int(stabilization.get("quotes_removed", 0) or 0)
    if isinstance(stabilization.get("lint"), dict):
        main_lint = stabilization["lint"]
    main_markdown = primary_report.markdown_content
    write_text_atomic(str(primary_path), main_markdown)

    forecast_path = report_dir / "forecast.json"
    forecast = _read_json(forecast_path)
    if isinstance(forecast, dict) and main_lint:
        forecast.setdefault("quality", {})["lint"] = main_lint
        forecast = _write_forecast_artifact(forecast_path, forecast, record_quality=True)
    meta_path = report_dir / "meta.json"
    meta = _read_json(meta_path)
    if not isinstance(meta, dict):
        meta = {}
    if main_markdown:
        meta["markdown_content"] = main_markdown

    # The backfill mutates the same publishable Markdown/citation artifacts as
    # a live report finalization. Run the identical authoritative read-only
    # audit last, so replayed reports cannot retain a stale draft-era quality
    # gate or silently publish dead references/process leakage.
    final_audit: Dict[str, Any] = {}
    if main_markdown and main_agent is not None:
        main_agent._forecast_spine = (
            forecast if isinstance(forecast, dict) else forecast_obj)
        _attach_verified_figure_inputs(main_agent, artifacts, report_dir)
        final_audit = main_agent._enforce_final_publish_audit(
            report_id, _Report(main_markdown))
        # REPORT-9: the shadow figure_provenance.json describes the re-audited bytes,
        # or is removed when this agent measured nothing (no verified-figures block).
        main_agent._write_figure_provenance(report_id, _Report(main_markdown))

    primary_citations = _read_json(report_dir / "citations.json")
    primary_citations = primary_citations if isinstance(primary_citations, dict) else {}
    source_lang = "zh" if primary_language == "Chinese" else "en"
    existing_entries = {
        str(entry.get("lang") or "").strip().lower(): entry
        for entry in (meta.get("translations") or [])
        if isinstance(entry, dict) and entry.get("lang")
    }
    unavailable_entries = [
        entry for entry in (meta.get("unavailable_translations") or [])
        if isinstance(entry, dict)
    ]
    available_entries: List[Dict[str, Any]] = []
    variant_results: List[Dict[str, Any]] = []
    valid_variant_paths: List[Tuple[Path, str, Dict[str, Any]]] = []

    for path in markdown_paths:
        if path.name == "full_report.md":
            continue
        match = re.fullmatch(r"full_report\.(en|zh)\.md", path.name)
        if not match:
            continue
        lang = match.group(1)
        original_variant = _read_text(path)
        language = "Chinese" if lang == "zh" else "English"
        candidate = strip_generated_visuals(original_variant)
        if scenario_label_change:
            candidate = candidate.replace(*scenario_label_change)
        candidate, _ = strip_circular_binary_rows(
            candidate, circular_ids, quality=quality)
        variant_placer = ReportAgent.__new__(ReportAgent)
        variant_placer.output_language = language
        candidate = variant_placer._place_visualizations(
            candidate, str(report_dir), localized_manifest(manifest, language))

        audit, citations_payload = main_agent._audit_translation_variant(
            report_id,
            main_markdown,
            candidate,
            source_lang,
            lang,
            primary_citations,
        )
        citations_path = report_dir / f"citations.{lang}.json"
        audit_path = report_dir / f"final_audit.{lang}.json"
        pdf_path = report_dir / f"full_report.{lang}.pdf"
        unavailable_entries = [
            entry for entry in unavailable_entries
            if str(entry.get("lang") or "").strip().lower() != lang
        ]

        if not audit.get("hard_passed"):
            # The untouched original is already in `backup`; remove active bytes so
            # API/PDF consumers cannot discover an artifact metadata marks unavailable.
            for stale in (path, pdf_path, citations_path):
                try:
                    stale.unlink()
                except FileNotFoundError:
                    pass
            write_json_atomic(str(audit_path), audit)
            unavailable = {
                "lang": lang,
                "source_lang": source_lang,
                "available": False,
                "status": "unavailable",
                "reason": "translation_variant_audit_failed",
                "issues": list(audit.get("issues") or [])[:20],
                "original_chars": len(original_variant),
                "original_markdown_sha256": hashlib.sha256(
                    original_variant.encode("utf-8")).hexdigest(),
                # Bundle-relative provenance is portable and never leaks the
                # workstation's absolute upload path through report metadata.
                "backup_path": f"{backup.name}/{path.name}",
                "final_audit_path": audit_path.name,
                "audited_at": audit.get("audited_at"),
            }
            unavailable_entries.append(unavailable)
            variant_results.append(unavailable)
            continue

        # Publish barrier mirrors live generation: citation/audit first, Markdown last.
        write_json_atomic(str(citations_path), citations_payload)
        write_json_atomic(str(audit_path), audit)
        write_text_atomic(str(path), candidate)
        previous = existing_entries.get(lang) or {}
        entry = {
            "lang": lang,
            "source_lang": source_lang,
            "path": path.name,
            "chars": len(candidate),
            "bytes": len(candidate.encode("utf-8")),
            "markdown_sha256": audit["markdown_sha256"],
            "created_at": datetime.now(timezone.utc).isoformat(),
            "model": previous.get("model"),
            "translation_quality": "ok",
            "available": True,
            "citations_path": citations_path.name,
            "final_audit_path": audit_path.name,
            "missing_numbers": [],
        }
        available_entries.append(entry)
        variant_results.append(entry)
        valid_variant_paths.append((path, lang, audit))

    meta["translations"] = available_entries
    if unavailable_entries:
        meta["unavailable_translations"] = unavailable_entries
    else:
        meta.pop("unavailable_translations", None)
    write_json_atomic(str(meta_path), meta)

    pdf_exports: List[Dict[str, Any]] = []
    export_candidates: List[Tuple[Path, Optional[str], Dict[str, Any]]] = [
        (primary_path, None, final_audit),
        *[(path, lang, audit) for path, lang, audit in valid_variant_paths],
    ]
    for markdown_path, lang, artifact_audit in export_candidates:
        pdf_path = ReportManager.export_pdf(
            report_id, force=True, lang=lang)
        if not pdf_path or not ReportManager._is_pdf_file(pdf_path):
            raise RuntimeError(
                f"PDF export failed for audited artifact {markdown_path.name}")
        pdf_file = Path(pdf_path)
        pdf_exports.append({
            "language": lang or "primary",
            "markdown": markdown_path.name,
            "markdown_sha256": hashlib.sha256(
                markdown_path.read_bytes()).hexdigest(),
            "final_audit_sha256": artifact_audit.get("markdown_sha256"),
            "pdf": pdf_file.name,
            "pdf_bytes": pdf_file.stat().st_size,
        })
    if pdf_exports:
        write_json_atomic(str(report_dir / "pdf_export.json"), {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "report_id": report_id,
            "primary_final_audit_sha256": final_audit.get("markdown_sha256"),
            "exports": pdf_exports,
        })

    plan.update({
        "backup": str(backup),
        "visual_items": len(manifest),
        "visual_ids": [item.get("id") for item in manifest if isinstance(item, dict)],
        "outcome_focus_ok": bool((main_lint or {}).get("outcome_focus_ok")),
        "residual_mechanics": int((main_lint or {}).get("leakage_flags") or 0),
        "circular_market_forecasts_removed": circular_ids,
        "language_lines_removed": language_lines_removed,
        "ungrounded_quotes_removed": ungrounded_quotes_removed,
        "scenario_label_change": scenario_label_change,
        "final_audit_hard_passed": final_audit.get("hard_passed"),
        "publish_gate_passed": (final_audit.get("publish_gate") or {}).get("passed"),
        "final_audit_sha256": final_audit.get("markdown_sha256"),
        "translation_variants": variant_results,
        "pdf_exports": pdf_exports,
    })
    return plan


def backfill_one(pipeline_id: str, report_id: str, *, apply: bool) -> Dict[str, Any]:
    """Replay one report transactionally, restoring the prior bundle on failure."""
    if not apply:
        return _backfill_one_impl(pipeline_id, report_id, apply=False)
    report_dir = Path(ReportManager._get_report_folder(report_id)).resolve()
    prior_backups = set(report_dir.glob(".codex-backup-*")) if report_dir.is_dir() else set()
    try:
        return _backfill_one_impl(pipeline_id, report_id, apply=True)
    except Exception as exc:
        created = [
            path for path in report_dir.glob(".codex-backup-*")
            if path not in prior_backups and path.is_dir()
        ]
        if created:
            backup = max(created, key=lambda path: path.stat().st_mtime_ns)
            try:
                _restore_from_backup(report_dir, backup)
                write_json_atomic(str(backup / "replay_failure.json"), {
                    "failed_at": datetime.now(timezone.utc).isoformat(),
                    "pipeline_id": pipeline_id,
                    "report_id": report_id,
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                    "restored": True,
                })
            except Exception as restore_exc:  # noqa: BLE001 - preserve both causes
                raise RuntimeError(
                    f"report replay failed ({type(exc).__name__}) and rollback failed "
                    f"({type(restore_exc).__name__}): {restore_exc}"
                ) from exc
        raise


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="write changes after backups")
    parser.add_argument("--target", action="append", default=[], metavar="PIPELINE:REPORT")
    args = parser.parse_args()
    targets: Iterable[Tuple[str, str]] = DEFAULT_TARGETS
    if args.target:
        parsed: List[Tuple[str, str]] = []
        for target in args.target:
            pipeline_id, sep, report_id = target.partition(":")
            if not sep:
                parser.error("--target must be PIPELINE:REPORT")
            parsed.append((pipeline_id, report_id))
        targets = parsed
    results = [backfill_one(pipeline, report, apply=args.apply) for pipeline, report in targets]
    print(json.dumps(results, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
