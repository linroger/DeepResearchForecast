"""Content-filter-safe binary-forecast extraction (report stage).

Live run ``pipe_d569f211eb14`` (2026-10-16, glm-5.3): the single 48k-character
extraction prompt for Part-1 binary forecasts was rejected by the provider's
content filter (HTTP 400, code 1301, ``role: user``).  No fallback provider was
configured, the caller swallowed the exception, ``binary_count`` stayed 0 and the
publish gate failed the whole report.  This module wraps
:func:`forecast_extractor.extract_binary_forecasts` with two honest recoveries:

1. **Chunked retry.**  A content filter rejects the *input*; the sensitive
   passages are usually concentrated in a few sections.  The dossier is split at
   H2 headings into a handful of bounded chunks and each chunk is extracted on its
   own; filtered chunks are skipped, the rest are merged and renumbered.
2. **Scenario-partition fallback.**  When every chunk is filtered, the binary
   propositions are derived deterministically from the already-finalised
   scenario partition (P(outcome ∈ scenario) = the scenario probability).  Rows
   carry ``source="scenario-partition"`` and declare their membership, so the
   proposition-consistency audit holds by construction and the quality scorecard
   (short of ``min_count``) demotes confidence instead of blocking publication.

Non-filter exceptions propagate unchanged (the caller keeps its legacy logging).
"""

from __future__ import annotations

import logging
import math
import re
from typing import Any, Callable, Dict, List, Optional, Sequence

from ..utils.llm_client import _is_content_filter
from .forecast_extractor import (
    _binary_key,
    _binary_quality,
    _normalize_binaries,
    extract_binary_forecasts,
)

logger = logging.getLogger(__name__)

DEFAULT_CHUNK_CHARS = 14_000
DEFAULT_MAX_CHUNKS = 4
RECOVERY_SCHEMA = "binary-extraction-recovery/v1"


def _is_chinese(language: Any) -> bool:
    text = str(language or "").strip().lower()
    return text.startswith(("zh", "chinese", "中文"))


def split_markdown_chunks(markdown: str, *, chunk_chars: int = DEFAULT_CHUNK_CHARS,
                          max_chunks: int = DEFAULT_MAX_CHUNKS) -> List[str]:
    """Split a dossier at H2 headings into at most ``max_chunks`` bounded chunks.

    Consecutive sections are packed up to ``chunk_chars``; an oversized single
    section is hard-split.  When more chunks than ``max_chunks`` result, an evenly
    spaced subset that always keeps the first and last chunk is returned, so the
    retry still covers the document's head (framing) and tail (conclusions).
    """
    text = str(markdown or "")
    if not text.strip():
        return []
    chunk_chars = max(2_000, int(chunk_chars))
    parts = re.split(r"(?m)^(?=## )", text)
    sections = [p for p in parts if p.strip()]
    chunks: List[str] = []
    current = ""
    for section in sections:
        while len(section) > chunk_chars:
            if current:
                chunks.append(current)
                current = ""
            chunks.append(section[:chunk_chars])
            section = section[chunk_chars:]
        if current and len(current) + len(section) > chunk_chars:
            chunks.append(current)
            current = section
        else:
            current += section
    if current.strip():
        chunks.append(current)
    if max_chunks > 0 and len(chunks) > max_chunks:
        if max_chunks == 1:
            return [chunks[0]]
        step = (len(chunks) - 1) / float(max_chunks - 1)
        picked = sorted({int(round(i * step)) for i in range(max_chunks)})
        chunks = [chunks[i] for i in picked]
    return chunks


def scenario_partition_binaries(scenarios: Optional[Sequence[Dict[str, Any]]], *,
                                horizon_date: Optional[str] = None,
                                language: str = "English") -> List[Dict[str, Any]]:
    """Deterministic binary rows: one per scenario, P = the scenario probability."""
    rows: List[Dict[str, Any]] = []
    horizon = str(horizon_date or "").strip()
    year: Optional[int] = None
    if horizon:
        m = re.match(r"(\d{4})", horizon)
        if m:
            year = int(m.group(1))
    zh = _is_chinese(language)
    for row in scenarios or []:
        if not isinstance(row, dict):
            continue
        name = str(row.get("name") or "").strip()
        raw_prob = row.get("probability")
        try:
            prob = float(raw_prob) if raw_prob is not None else float("nan")
        except (TypeError, ValueError):
            continue
        if not name or not math.isfinite(prob):
            continue
        criteria = str(row.get("resolution_criteria") or "").strip()
        if zh:
            when = f"到 {horizon}" if horizon else "到预测判定日"
            statement = f"{when}，实际结果落入情景「{name}」。"
        else:
            when = f"By {horizon}" if horizon else "By the forecast horizon"
            statement = f'{when}, the realized outcome falls within the scenario "{name}".'
        rows.append({
            "statement": statement,
            "probability": round(max(0.02, min(0.98, prob)), 2),
            "resolution_criteria": criteria or (
                f"情景「{name}」的判定标准成立" if zh else f'The resolution criteria of scenario "{name}" are met'
            ),
            "resolution_source": "scenario partition",
            "theme": "scenario",
            "horizon_year": year,
            "base_rate_anchor": str(row.get("base_rate_anchor") or ""),
            "adjustment_rationale": str(row.get("adjustment_rationale") or ""),
            "source": "scenario-partition",
            "scenario_membership": {"derivable": True, "yes_scenarios": [name]},
        })
    return rows


def _merge_rows(target: List[Dict[str, Any]], extra: Sequence[Dict[str, Any]]) -> None:
    seen = {_binary_key(str(b.get("statement") or "")) for b in target}
    for row in extra:
        if not isinstance(row, dict):
            continue
        key = _binary_key(str(row.get("statement") or ""))
        if key and key not in seen:
            seen.add(key)
            target.append(dict(row))


def _renumber(rows: List[Dict[str, Any]]) -> None:
    for index, row in enumerate(rows, start=1):
        row["id"] = f"F{index}"


def _error_brief(exc: Exception) -> str:
    return f"{type(exc).__name__}: {str(exc)[:200]}"


def extract_binary_forecasts_resilient(report_markdown: str, llm: Any, *,
                                       min_count: int = 10,
                                       chunk_chars: int = DEFAULT_CHUNK_CHARS,
                                       max_chunks: int = DEFAULT_MAX_CHUNKS,
                                       extractor: Optional[Callable[..., Dict[str, Any]]] = None,
                                       **kwargs: Any) -> Dict[str, Any]:
    """``extract_binary_forecasts`` with chunked retry and a scenario fallback.

    Returns the extractor's result shape (``binary_forecasts``, ``binary_quality``,
    …) plus a ``recovery`` record whenever a recovery path produced the rows.
    Only a provider content-filter rejection triggers recovery; every other
    exception propagates to the caller unchanged.
    """
    run = extractor or extract_binary_forecasts
    result: Any = None
    primary_error: Optional[Exception] = None
    try:
        result = run(report_markdown, llm, min_count=min_count, **kwargs)
        if isinstance(result, dict) and result.get("binary_forecasts"):
            return result
    except Exception as exc:  # noqa: BLE001 — only content filters are recoverable here
        if not _is_content_filter(exc):
            raise
        primary_error = exc
        logger.warning("binary extraction content-filtered by the provider; retrying in %d-char chunks: %s",
                       chunk_chars, _error_brief(exc))
    if primary_error is None:
        # The extractor answered but produced nothing: that is not a filter event, keep legacy behaviour.
        return result if isinstance(result, dict) else {"binary_forecasts": [], "binary_quality": {}}

    chunks = split_markdown_chunks(report_markdown, chunk_chars=chunk_chars, max_chunks=max_chunks)
    merged: List[Dict[str, Any]] = []
    base: Dict[str, Any] = {}
    filtered = 0
    failed = 0
    per_chunk_min = max(3, int(math.ceil(float(min_count) / max(1, len(chunks)))))
    for chunk in chunks:
        try:
            part = run(chunk, llm, min_count=per_chunk_min, **kwargs)
        except Exception as exc:  # noqa: BLE001 — a filtered or failed chunk is skipped, never fatal
            if _is_content_filter(exc):
                filtered += 1
            else:
                failed += 1
                logger.warning("binary extraction chunk failed (skipped): %s", _error_brief(exc))
            continue
        if not isinstance(part, dict):
            continue
        rows = part.get("binary_forecasts") or []
        if rows and not base:
            base = {k: v for k, v in part.items() if k not in ("binary_forecasts", "binary_quality")}
        _merge_rows(merged, rows)
        extra_mc = (part.get("market_comparison") or {}).get("comparisons") if isinstance(part.get("market_comparison"), dict) else None
        if extra_mc and isinstance(base.get("market_comparison"), dict):
            existing = base["market_comparison"].setdefault("comparisons", [])
            if isinstance(existing, list):
                existing.extend(c for c in extra_mc if c not in existing)
    themes = kwargs.get("themes")
    if merged:
        _renumber(merged)
        quality = _binary_quality(merged, min_count=min_count, themes_expected=themes)
        recovery = {
            "schema_version": RECOVERY_SCHEMA,
            "mode": "chunked_after_content_filter",
            "chunks": len(chunks),
            "filtered_chunks": filtered,
            "failed_chunks": failed,
            "primary_error": _error_brief(primary_error),
            "rows": len(merged),
        }
        logger.warning("binary extraction recovered from a content filter: %d rows from %d/%d chunks "
                       "(%d filtered, %d failed)", len(merged), len(chunks) - filtered - failed,
                       len(chunks), filtered, failed)
        return {**base, "binary_forecasts": merged, "binary_quality": quality, "recovery": recovery}

    scenario_rows = scenario_partition_binaries(
        kwargs.get("scenarios"), horizon_date=kwargs.get("horizon_date"),
        language=str(kwargs.get("language") or "English"))
    normalized = _normalize_binaries(scenario_rows, language=str(kwargs.get("language") or "English"))
    _renumber(normalized)
    quality = _binary_quality(normalized, min_count=min_count, themes_expected=themes)
    quality["passed"] = False
    issues = list(quality.get("issues") or [])
    issues.append(
        "二元预测由情景分区确定性派生：提供方对全部抽取尝试触发内容过滤（binary forecasts derived "
        "from the scenario partition after the provider content-filtered every extraction attempt）"
    )
    quality["issues"] = issues
    recovery = {
        "schema_version": RECOVERY_SCHEMA,
        "mode": "scenario_partition_fallback",
        "chunks": len(chunks),
        "filtered_chunks": filtered,
        "failed_chunks": failed,
        "primary_error": _error_brief(primary_error),
        "rows": len(normalized),
    }
    logger.warning("binary extraction fell back to %d scenario-partition propositions after %d/%d chunks were "
                   "content-filtered", len(normalized), filtered, len(chunks))
    return {"binary_forecasts": normalized, "binary_quality": quality, "recovery": recovery}
