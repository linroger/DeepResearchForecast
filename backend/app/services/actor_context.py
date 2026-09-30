"""Deterministic research-context packs for named simulation actors.

The research report is deliberately *not* copied wholesale into every OASIS
persona.  This module selects report sections and structured dossier rows that
are relevant to one actor, records what was omitted, and seals the result to
the exact ``actors.json`` object and report text used during preparation.

The pack is data, never instructions.  ``actor_role_prompt`` owns the final
sanitisation and compilation at the model boundary.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import unicodedata
from dataclasses import dataclass
from datetime import date
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from ..utils.actors import actor_identity_key, legacy_actor_key, stable_actor_id
from ..utils.atomic import write_json_atomic
from ..utils.canonical_json import canonical_json_sha256


ACTOR_CONTEXT_VERSION = "actor-context/v1"
ACTOR_CONTEXT_MANIFEST_VERSION = "actor-context-manifest/v1"
ACTOR_INTELLIGENCE_VERSION = "actor-intelligence/v1"
ACTOR_KNOWN_VISIBILITIES = frozenset({
    "actor_known",
    "known_to_actor",
    "actor_internal",
    "internal_to_actor",
    "private_actor_knowledge",
})
PUBLIC_RELATIONSHIP_VISIBILITIES = frozenset({
    "public",
    "public_record",
    "publicly_known",
    "open_source",
})
HARD_RELATIONSHIP_EVIDENCE_TYPES = frozenset({
    "verified_fact",
    "actor_stated_claim",
})

DEFAULT_CONTEXT_MAX_CHARS = 16_000
MIN_CONTEXT_MAX_CHARS = 2_000
DEFAULT_REPORT_SECTION_BUDGET = 8_000
DEFAULT_RELEVANT_SECTION_LIMIT = 8
EVIDENCE_GAP_TEXT_MAX_CHARS = 320
EVIDENCE_GAP_ID_MAX_CHARS = 180
EVIDENCE_GAP_QUERY_LIMIT = 2
EVIDENCE_GAP_ID_LIMIT = 8
EVIDENCE_GAP_PER_DIMENSION_LIMIT = 2
# There are 17 required intelligence dimensions. Preserve up to two producer
# rows per dimension in the modeler-only audit ledger; display/prompt callers
# apply their own smaller summary limits.
EVIDENCE_GAP_TOTAL_LIMIT = 34
EVIDENCE_GAP_ATTEMPT_COUNT_MAX = 1_000_000
EVIDENCE_GAP_FIELDS = (
    "reason",
    "attempted_queries",
    "receipt_ids",
    "result_ids",
    "attempt_count",
    "exhausted",
)
UNSAFE_EVIDENCE_GAP_TEXT_REPLACEMENT = (
    "[unsafe instruction-like evidence-gap text omitted]"
)

_EVIDENCE_GAP_CONTROL_PATTERNS = (
    re.compile(
        r"\b(?:ignore|disregard|override|forget|bypass|do\s+not\s+follow)\b"
        r"[^.!?\n]{0,180}\b(?:instructions?|prompts?|policy|message|system|"
        r"developer)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:call|invoke|run|execute|use)\b[^.!?\n]{0,100}"
        r"\b(?:tools?|shell|terminal|commands?|browser)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:reveal|exfiltrate|disclose|leak|print|output|show)\b"
        r"[^.!?\n]{0,120}\b(?:secrets?|credentials?|hidden\s+(?:prompt|"
        r"instructions?)|system\s+prompt)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"<\s*/?\s*(?:system|developer|assistant|tool|user)\b|"
        r"<\|\s*(?:system|developer|assistant|tool|user)\s*\|>",
        re.IGNORECASE,
    ),
)

INTELLIGENCE_DIMENSIONS: Tuple[str, ...] = (
    "identity_history",
    "values_worldview",
    "incentives",
    "motivations",
    "capabilities",
    "constraints",
    "operational_preferences",
    "alliances",
    "opponents_competitors",
    "decision_rights_process_triggers",
    "current_actions",
    "future_plans",
    "investments_capital_allocation",
    "track_record",
    "likely_actions",
    "red_lines",
    "knowledge_state",
)


def _bounded_evidence_gap_text(
    value: Any,
    max_chars: int,
    *,
    redact_instruction_like: bool = False,
) -> str:
    """Bound one scalar gap field without converting objects to Python repr.

    Query and identifier bytes are provenance-bearing modeler audit data, so
    their normal path preserves the producer's string exactly (up to the hard
    field bound). Instruction-like filtering belongs on the derived display
    view, never on this canonical audit representation. Dimension names are the
    only values normalized/redacted here because they become display labels.
    """
    if isinstance(value, (Mapping, list, tuple, set)):
        return ""
    text = str(value or "")
    if redact_instruction_like:
        text = unicodedata.normalize("NFKC", text)
        text = re.sub(
            r"[\u200b-\u200f\u202a-\u202e\u2060-\u206f\ufeff]", "", text
        )
        text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", text)
        text = " ".join(text.split()).strip()
        if any(
            pattern.search(text) for pattern in _EVIDENCE_GAP_CONTROL_PATTERNS
        ):
            return UNSAFE_EVIDENCE_GAP_TEXT_REPLACEMENT
    if len(text) <= max_chars:
        return text
    return text[:max(0, max_chars - 1)].rstrip() + "…"


def _gap_items(value: Any) -> List[Any]:
    if value in (None, ""):
        return []
    if isinstance(value, (list, tuple)):
        return list(value)
    return [value]


def normalize_evidence_gap(value: Any) -> Optional[Dict[str, Any]]:
    """Return one bounded typed evidence-gap row.

    Current ``actor-intelligence/v1`` objects retain their provenance fields.
    Legacy strings and claim-like gap rows are upgraded to the same explicit
    shape with zero attempts and ``exhausted=false``. No path uses ``str(dict)``.
    """
    if isinstance(value, Mapping):
        reason_value = (
            value.get("reason")
            or value.get("claim")
            or value.get("finding")
            or value.get("description")
            or value.get("text")
            or ""
        )
        raw_queries = value.get("attempted_queries")
        raw_receipt_ids = value.get("receipt_ids")
        raw_result_ids = value.get("result_ids")
        raw_attempt_count = value.get("attempt_count")
        exhausted = value.get("exhausted") is True
    else:
        reason_value = value
        raw_queries = []
        raw_receipt_ids = []
        raw_result_ids = []
        raw_attempt_count = 0
        exhausted = False

    reason = _bounded_evidence_gap_text(
        reason_value, EVIDENCE_GAP_TEXT_MAX_CHARS
    )
    attempted_queries = list(dict.fromkeys(
        clean
        for item in _gap_items(raw_queries)[:EVIDENCE_GAP_QUERY_LIMIT]
        if (
            clean := _bounded_evidence_gap_text(
                item, EVIDENCE_GAP_TEXT_MAX_CHARS
            )
        ).strip()
    ))
    receipt_ids = list(dict.fromkeys(
        clean
        for item in _gap_items(raw_receipt_ids)[:EVIDENCE_GAP_ID_LIMIT]
        if (
            clean := _bounded_evidence_gap_text(
                item, EVIDENCE_GAP_ID_MAX_CHARS
            )
        ).strip()
    ))
    result_ids = list(dict.fromkeys(
        clean
        for item in _gap_items(raw_result_ids)[:EVIDENCE_GAP_ID_LIMIT]
        if (
            clean := _bounded_evidence_gap_text(
                item, EVIDENCE_GAP_ID_MAX_CHARS
            )
        ).strip()
    ))
    try:
        attempt_count = (
            0 if isinstance(raw_attempt_count, bool)
            else min(
                EVIDENCE_GAP_ATTEMPT_COUNT_MAX,
                max(0, int(raw_attempt_count)),
            )
        )
    except (TypeError, ValueError):
        attempt_count = 0
    if not (reason.strip() or attempted_queries or receipt_ids or result_ids):
        return None
    return {
        "reason": reason,
        "attempted_queries": attempted_queries,
        "receipt_ids": receipt_ids,
        "result_ids": result_ids,
        "attempt_count": attempt_count,
        "exhausted": exhausted,
    }


def normalize_evidence_gap_map(
    value: Any,
    *,
    allowed_dimensions: Optional[Iterable[str]] = None,
    per_dimension_limit: int = EVIDENCE_GAP_PER_DIMENSION_LIMIT,
    total_limit: int = EVIDENCE_GAP_TOTAL_LIMIT,
    require_lossless: bool = False,
) -> Dict[str, List[Dict[str, Any]]]:
    """Normalize canonical maps and legacy rows into a bounded typed map.

    When ``require_lossless`` is true, any row that uses the current six-field
    structured contract is accepted only if normalization is byte/value
    preserving and every row fits the declared caps. Legacy strings and
    pre-contract claim rows remain upgradeable for compatibility.
    """
    allowed = (
        {str(item) for item in allowed_dimensions}
        if allowed_dimensions is not None else None
    )
    if isinstance(value, Mapping) and not any(
        key in value for key in (
            "reason", "claim", "finding", "description", "text",
            "attempted_queries", "receipt_ids", "result_ids",
            "attempt_count", "exhausted",
        )
    ):
        raw_map = value
    else:
        raw_map = {"general": value}

    has_structured_rows = any(
        isinstance(raw_row, Mapping)
        and any(field in raw_row for field in EVIDENCE_GAP_FIELDS)
        for raw_rows in raw_map.values()
        for raw_row in _gap_items(raw_rows)
    )
    if require_lossless and has_structured_rows:
        normalized: Dict[str, List[Dict[str, Any]]] = {}
        total = 0
        row_cap = max(1, int(per_dimension_limit))
        total_cap = max(1, int(total_limit))
        for raw_dimension, raw_rows in raw_map.items():
            if not isinstance(raw_dimension, str):
                raise ValueError(
                    "structured evidence-gap dimension must be a string"
                )
            dimension = _bounded_evidence_gap_text(
                raw_dimension,
                80,
                redact_instruction_like=True,
            )
            if dimension != raw_dimension:
                raise ValueError(
                    "structured evidence-gap dimension exceeds or violates "
                    "the audit boundary"
                )
            if allowed is not None and dimension not in allowed:
                raise ValueError(
                    f"unsupported structured evidence-gap dimension: {dimension}"
                )
            row_values = _gap_items(raw_rows)
            dimension_has_structured_rows = any(
                isinstance(raw_row, Mapping)
                and any(field in raw_row for field in EVIDENCE_GAP_FIELDS)
                for raw_row in row_values
            )
            if dimension_has_structured_rows and not isinstance(raw_rows, list):
                raise ValueError(
                    f"structured evidence-gap rows must be a list: {dimension}"
                )
            if len(row_values) > row_cap:
                raise ValueError(
                    f"structured evidence-gap row cap exceeded: {dimension}"
                )
            if total + len(row_values) > total_cap:
                raise ValueError(
                    "structured evidence-gap total row cap exceeded"
                )
            rows: List[Dict[str, Any]] = []
            for raw_row in row_values:
                structured_row = (
                    isinstance(raw_row, Mapping)
                    and any(
                        field in raw_row for field in EVIDENCE_GAP_FIELDS
                    )
                )
                if structured_row and set(raw_row) != set(EVIDENCE_GAP_FIELDS):
                    raise ValueError(
                        "structured evidence-gap row must contain exactly the "
                        "six v1 fields"
                    )
                gap = normalize_evidence_gap(raw_row)
                if structured_row and (
                    gap is None or gap != dict(raw_row)
                ):
                    raise ValueError(
                        "structured evidence-gap row cannot be normalized "
                        "losslessly within the audit bounds"
                    )
                if gap is not None:
                    rows.append(gap)
            if rows:
                normalized[dimension] = rows
            total += len(row_values)
        return normalized

    normalized: Dict[str, List[Dict[str, Any]]] = {}
    total = 0
    for raw_dimension, raw_rows in raw_map.items():
        dimension = _bounded_evidence_gap_text(
            raw_dimension,
            80,
            redact_instruction_like=True,
        )
        if not dimension or (allowed is not None and dimension not in allowed):
            continue
        rows: List[Dict[str, Any]] = []
        for raw_row in _gap_items(raw_rows):
            gap = normalize_evidence_gap(raw_row)
            if gap is None:
                continue
            rows.append(gap)
            total += 1
            if len(rows) >= max(1, int(per_dimension_limit)):
                break
            if total >= max(1, int(total_limit)):
                break
        if rows:
            normalized[dimension] = rows
        if total >= max(1, int(total_limit)):
            break
    return normalized

_LOAD_BEARING_TERMS = (
    "action", "plan", "target", "commitment", "investment", "capital",
    "incentive", "motivation", "capability", "constraint", "trigger",
    "decision", "alliance", "partner", "competitor", "opponent", "risk",
    "deadline", "horizon", "forecast", "scenario", "catalyst", "timeline",
    "行动", "计划", "目标", "承诺", "投资", "资本", "激励", "动机",
    "能力", "约束", "触发", "决策", "联盟", "伙伴", "竞争", "对手",
    "风险", "期限", "预测", "情景", "催化剂", "时间线",
)

_GENERIC_RELEVANCE_TERMS = {
    "actor", "company", "organization", "government", "role", "identity",
    "confidence", "source", "sources", "source_refs", "status", "unknown",
    "claim", "claims", "evidence", "gap", "gaps", "high", "medium", "low",
    "action", "actions", "plan", "plans", "investment", "investments",
    "capability", "capabilities", "future", "current", "decision", "risk",
    "主体", "公司", "组织", "政府", "角色", "身份", "置信度", "来源", "状态",
    "未知", "主张", "证据", "缺口", "行动", "计划", "投资", "能力", "未来",
    "当前", "决策", "风险",
}


def text_sha256(value: str) -> str:
    return hashlib.sha256(str(value or "").encode("utf-8")).hexdigest()


def _epistemic_token(value: Any) -> str:
    return re.sub(r"[^0-9a-z]+", "_", str(value or "").casefold()).strip("_")


def is_hard_public_relationship(row: Any) -> bool:
    """Return whether a canonical relationship may become runtime authority.

    A relationship is a particularly high-impact fact: it can change a role,
    following topology, sentiment, and action selection for two actors.  In
    ``actor-intelligence/v1`` it is executable only when it is explicitly
    source-bound, public, and either a verified fact or a public actor-stated
    claim.  Analyst/model-only inference, contested/unknown evidence, and
    private or merely actor-local knowledge remain audit data and never become
    a hard role or simulation fact.
    """
    if not isinstance(row, Mapping):
        return False
    refs = row.get("source_refs")
    if not (
        isinstance(refs, list)
        and any(str(ref or "").strip() for ref in refs)
    ):
        return False
    return (
        _epistemic_token(row.get("evidence_type"))
        in HARD_RELATIONSHIP_EVIDENCE_TYPES
        and _epistemic_token(row.get("visibility"))
        in PUBLIC_RELATIONSHIP_VISIBILITIES
    )


# INFRA-11: the surface-matching key lives in utils.actors (shared with actor_role_prompt).
_canonical_name = legacy_actor_key


def actor_id_for(actor: Mapping[str, Any]) -> str:
    """Explicit producer id, else ``stable_actor_id`` of the name.

    Latin names keep their historical hash; names whose legacy key would drop non-Latin
    letters (kana, hangul, Cyrillic…) get a distinct lossless id instead of an empty or
    colliding one.  Raises ValueError when the name normalizes to nothing.
    """
    explicit = str(actor.get("actor_id") or actor.get("id") or "").strip()
    if explicit:
        return explicit
    return stable_actor_id(actor.get("name"))


def _safe_pack_filename(actor_id: str) -> str:
    if re.fullmatch(r"[A-Za-z0-9_.-]{1,180}", actor_id) and actor_id not in {".", ".."}:
        return f"{actor_id}.json"
    suffix = hashlib.sha256(actor_id.encode("utf-8")).hexdigest()[:24]
    return f"actor_{suffix}.json"


def _actor_surfaces(actor: Mapping[str, Any]) -> List[str]:
    values: List[str] = []
    aliases = actor.get("aliases")
    aliases = aliases if isinstance(aliases, list) else []
    for value in [actor.get("name"), *aliases]:
        if not isinstance(value, str):
            continue
        clean = unicodedata.normalize("NFKC", value).strip()
        if clean and clean.casefold() not in {item.casefold() for item in values}:
            values.append(clean)
    return values


def _flatten_strings(value: Any, *, limit: int = 80) -> List[str]:
    out: List[str] = []

    def visit(item: Any, depth: int = 0) -> None:
        if len(out) >= limit or depth > 5:
            return
        if isinstance(item, str):
            clean = " ".join(item.split())
            if clean:
                out.append(clean)
        elif isinstance(item, Mapping):
            for key in sorted(item):
                visit(item[key], depth + 1)
        elif isinstance(item, Sequence) and not isinstance(item, (bytes, bytearray)):
            for child in item:
                visit(child, depth + 1)

    visit(value)
    return out


def _actor_terms(actor: Mapping[str, Any]) -> List[str]:
    """Return stable, discriminating report-relevance terms for one actor."""
    raw: List[str] = _actor_surfaces(actor)
    intelligence = actor.get("intelligence")
    canonical_v1 = (
        isinstance(intelligence, Mapping)
        and intelligence.get("schema_version") == ACTOR_INTELLIGENCE_VERSION
    )
    if not canonical_v1:
        for key in (
            "role", "description", "goals", "objectives", "resources", "assets",
            "current_actions", "future_plans", "investments_capital_allocation",
            "likely_actions", "incentives",
        ):
            raw.extend(_flatten_strings(actor.get(key), limit=24))
    dimensions = intelligence.get("dimensions") if isinstance(intelligence, dict) else None
    if isinstance(dimensions, dict):
        for dimension in INTELLIGENCE_DIMENSIONS:
            claims = dimensions.get(dimension)
            if not isinstance(claims, list):
                continue
            for claim in claims[:6]:
                if not isinstance(claim, dict):
                    continue
                if canonical_v1 and not (
                    isinstance(claim.get("source_refs"), list)
                    and any(str(ref or "").strip() for ref in claim["source_refs"])
                ):
                    continue
                raw.append(str(claim.get("claim") or ""))
                qualifiers = claim.get("qualifiers")
                if isinstance(qualifiers, dict):
                    for key in (
                        "project", "program", "product", "asset", "counterparty",
                        "geography", "amount", "scale", "strategic_purpose",
                    ):
                        if qualifiers.get(key):
                            raw.append(str(qualifiers[key]))

    terms: List[str] = []
    seen: set[str] = set()
    for value in raw:
        # Keep complete evidence phrases and proper identifiers. Splitting a
        # claim into common tokens (for example ``grid`` and ``permit``) makes
        # an unrelated actor's section look relevant merely because both
        # actors operate in the same domain.
        clean = " ".join(str(value).split()).strip(" ,.;:()[]{}")
        norm = _canonical_name(clean)
        if (
            len(norm) < 4
            or norm in seen
            or clean.casefold() in _GENERIC_RELEVANCE_TERMS
            or norm in {_canonical_name(item) for item in _GENERIC_RELEVANCE_TERMS}
        ):
            continue
        seen.add(norm)
        terms.append(clean)
        if len(terms) >= 48:
            return terms
    return terms


@dataclass(frozen=True)
class _ReportSection:
    ordinal: int
    level: int
    heading: str
    text: str


def _split_report_sections(report_text: str) -> List[_ReportSection]:
    text = str(report_text or "").replace("\r\n", "\n").replace("\r", "\n")
    if not text.strip():
        return []
    lines = text.splitlines()
    sections: List[_ReportSection] = []
    current_heading = "Report preamble"
    current_level = 0
    current: List[str] = []

    def flush() -> None:
        body = "\n".join(current).strip()
        if body:
            sections.append(_ReportSection(
                ordinal=len(sections),
                level=current_level,
                heading=current_heading,
                text=body,
            ))

    for line in lines:
        match = re.match(r"^(#{1,6})\s+(.+?)\s*$", line)
        if match:
            flush()
            current.clear()
            current_heading = match.group(2).strip()
            current_level = len(match.group(1))
            current.append(line.rstrip())
        else:
            current.append(line.rstrip())
    flush()
    return sections


def _contains_surface(text: str, surface: str) -> bool:
    if not surface:
        return False
    haystack = unicodedata.normalize("NFKC", text).casefold()
    needle = unicodedata.normalize("NFKC", surface).casefold()
    if re.fullmatch(r"[a-z0-9][a-z0-9_.& -]*", needle):
        return re.search(rf"(?<![a-z0-9]){re.escape(needle)}(?![a-z0-9])", haystack) is not None
    return needle in haystack


def _relevance(text: str, actor: Mapping[str, Any]) -> Tuple[int, List[str]]:
    surfaces = _actor_surfaces(actor)
    terms = _actor_terms(actor)
    matched: List[str] = []
    surface_matches: List[str] = []
    term_matches: List[str] = []
    score = 0
    for index, surface in enumerate(surfaces):
        if _contains_surface(text, surface):
            matched.append(surface)
            surface_matches.append(surface)
            score += 120 if index == 0 else 90
    for term in terms:
        if any(_canonical_name(term) == _canonical_name(item) for item in surfaces):
            continue
        if _contains_surface(text, term):
            matched.append(term)
            term_matches.append(term)
            score += 12 if " " in term else 5
    # A generic token cannot make an unrelated section actor-relevant. Without
    # an explicit name/alias anchor, require either two independent actor terms
    # or one long exact actor-specific phrase.
    discriminating_phrase = any(
        len(_canonical_name(term)) >= 14 and (" " in term or any(ch.isdigit() for ch in term))
        for term in term_matches
    )
    if not surface_matches and len(term_matches) < 2 and not discriminating_phrase:
        return 0, []
    if matched:
        lowered = unicodedata.normalize("NFKC", text).casefold()
        score += min(24, sum(lowered.count(term) for term in _LOAD_BEARING_TERMS) * 2)
        score += min(10, len(re.findall(r"\b20\d{2}(?:-\d{1,2}-\d{1,2})?\b", text)) * 2)
        score += min(8, len(re.findall(r"(?<!\w)(?:[$€£¥]|\d+(?:\.\d+)?\s*%)", text)))
    # Stable de-duplication keeps audit rows compact.
    unique: List[str] = []
    seen: set[str] = set()
    for item in matched:
        key = item.casefold()
        if key not in seen:
            seen.add(key)
            unique.append(item)
    return score, unique[:16]


def _bounded_relevant_text(
    section: _ReportSection,
    actor: Mapping[str, Any],
    max_chars: int,
) -> Tuple[str, str, int]:
    if len(section.text) <= max_chars:
        return section.text, "full_section", 0

    # Long sections are reduced by relevant paragraphs, never by taking an
    # arbitrary prefix.  Original paragraph order is restored after ranking.
    paragraphs = [part.strip() for part in re.split(r"\n\s*\n", section.text) if part.strip()]
    ranked: List[Tuple[int, int, str]] = []
    for index, paragraph in enumerate(paragraphs):
        score, _ = _relevance(paragraph, actor)
        ranked.append((score, index, paragraph))
    chosen: List[Tuple[int, str]] = []
    used = 0
    for score, index, paragraph in sorted(ranked, key=lambda row: (-row[0], row[1])):
        if score <= 0:
            continue
        extra = len(paragraph) + (2 if chosen else 0)
        if used + extra > max_chars:
            continue
        chosen.append((index, paragraph))
        used += extra
    if not chosen:
        # A section can score through its heading while the body has no repeated
        # surface. Preserve the shortest complete paragraph as context.
        candidates = sorted(enumerate(paragraphs), key=lambda row: (len(row[1]), row[0]))
        for index, paragraph in candidates:
            if len(paragraph) <= max_chars:
                chosen = [(index, paragraph)]
                break
    selected = "\n\n".join(text for _, text in sorted(chosen))
    omitted = max(0, len(paragraphs) - len(chosen))
    return selected, "relevance_selected_paragraphs", omitted


def _select_report_sections(
    report_text: str,
    actor: Mapping[str, Any],
    *,
    total_budget: int = DEFAULT_REPORT_SECTION_BUDGET,
    section_limit: int = DEFAULT_RELEVANT_SECTION_LIMIT,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    sections = _split_report_sections(report_text)
    candidates: List[Tuple[int, _ReportSection, List[str]]] = []
    audit_rows: List[Dict[str, Any]] = []
    for section in sections:
        score, matched = _relevance(f"{section.heading}\n{section.text}", actor)
        if score > 0:
            candidates.append((score, section, matched))
        else:
            audit_rows.append({
                "ordinal": section.ordinal,
                "heading": section.heading,
                "reason": "no actor-specific relevance signal",
                "characters": len(section.text),
            })

    selected: List[Dict[str, Any]] = []
    remaining = max(0, total_budget)
    selected_ordinals: set[int] = set()
    for score, section, matched in sorted(
        candidates, key=lambda row: (-row[0], row[1].ordinal)
    ):
        if len(selected) >= section_limit:
            break
        per_section = min(3_200, remaining)
        if per_section < 240:
            break
        bounded, mode, omitted_paragraphs = _bounded_relevant_text(
            section, actor, per_section
        )
        if not bounded:
            continue
        row = {
            "ordinal": section.ordinal,
            "heading": section.heading,
            "level": section.level,
            "relevance_score": score,
            "matched_terms": matched,
            "selection_mode": mode,
            "text": bounded,
        }
        if omitted_paragraphs:
            row["omitted_paragraph_count"] = omitted_paragraphs
        selected.append(row)
        selected_ordinals.add(section.ordinal)
        remaining -= len(bounded)

    for score, section, _matched in candidates:
        if section.ordinal in selected_ordinals:
            continue
        audit_rows.append({
            "ordinal": section.ordinal,
            "heading": section.heading,
            "reason": "ranked below actor context budget",
            "relevance_score": score,
            "characters": len(section.text),
        })
    selected.sort(key=lambda row: row["ordinal"])
    audit_rows.sort(key=lambda row: row["ordinal"])
    audit = {
        "report_section_count": len(sections),
        "selected_section_count": len(selected),
        "omitted_section_count": len(audit_rows),
        "selection_policy": (
            "canonical name/aliases and actor-specific evidence terms; then "
            "load-bearing, dated, and quantitative relevance"
        ),
        "report_section_budget_chars": total_budget,
        "omitted_sections": audit_rows,
    }
    return selected, audit


def _matches_structured_row(row: Any, actor: Mapping[str, Any]) -> bool:
    if not isinstance(row, Mapping):
        return False
    text = json.dumps(row, ensure_ascii=False, sort_keys=True, allow_nan=False)
    score, _ = _relevance(text, actor)
    return score > 0


def _incident_relationships(
    rows: Any, actor: Mapping[str, Any]
) -> List[Dict[str, Any]]:
    if not isinstance(rows, list):
        return []
    # INFRA-11: lossless identity keys, never the empty legacy key of a kana/hangul/Cyrillic
    # name, so a non-Latin actor cannot collect every relationship with a non-Latin endpoint.
    actor_names = {key for key in map(actor_identity_key, _actor_surfaces(actor)) if key}
    intelligence = actor.get("intelligence")
    canonical_v1 = (
        isinstance(intelligence, Mapping)
        and intelligence.get("schema_version") == ACTOR_INTELLIGENCE_VERSION
    )
    out: List[Dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        if canonical_v1 and not (
            isinstance(row.get("source_refs"), list)
            and any(str(ref or "").strip() for ref in row["source_refs"])
        ):
            continue
        endpoints = {
            actor_identity_key(row.get("source")),
            actor_identity_key(row.get("target")),
        }
        if actor_names.intersection(endpoints):
            out.append(row)
    return sorted(out, key=lambda row: (
        _canonical_name(row.get("source")),
        _canonical_name(row.get("target")),
        str(row.get("type") or row.get("relation_label") or "").casefold(),
    ))[:24]


def _relevant_rows(rows: Any, actor: Mapping[str, Any], limit: int) -> List[Dict[str, Any]]:
    if not isinstance(rows, list):
        return []
    intelligence = actor.get("intelligence")
    canonical_v1 = (
        isinstance(intelligence, Mapping)
        and intelligence.get("schema_version") == ACTOR_INTELLIGENCE_VERSION
    )
    matched = [
        row for row in rows
        if isinstance(row, dict)
        and (
            not canonical_v1
            or (
                isinstance(row.get("source_refs"), list)
                and any(str(ref or "").strip() for ref in row["source_refs"])
            )
        )
        and _matches_structured_row(row, actor)
    ]
    return matched[:limit]


def _shared_context(actors: Mapping[str, Any]) -> Dict[str, Any]:
    situation = actors.get("situation_brief")
    if not isinstance(situation, dict):
        situation = {}
    canonical_v1 = (
        isinstance(actors.get("actor_intelligence_contract"), Mapping)
        and actors["actor_intelligence_contract"].get("schema_version")
        == ACTOR_INTELLIGENCE_VERSION
    )
    shared = {
        "as_of_date": actors.get("as_of_date"),
        "forecast_horizon": actors.get("forecast_horizon") or actors.get("horizon"),
        "central_question": actors.get("central_question"),
        "situation_brief": {} if canonical_v1 else {
            key: situation.get(key)
            for key in (
                "current_situation", "context", "dynamics", "fault_lines", "catalysts"
            )
            if situation.get(key) not in (None, "", [])
        },
        "hot_topics": (
            [] if canonical_v1
            else actors.get("hot_topics")
            if isinstance(actors.get("hot_topics"), list)
            else []
        ),
    }
    return {key: value for key, value in shared.items() if value not in (None, "", [], {})}


def _dimension_coverage(actor: Mapping[str, Any]) -> Dict[str, Any]:
    intelligence = actor.get("intelligence")
    if not isinstance(intelligence, dict):
        return {
            "schema_version": None,
            "represented_dimensions": [],
            "grounded_dimensions": [],
            "explicit_gap_dimensions": [],
            "missing_dimensions": list(INTELLIGENCE_DIMENSIONS),
        }
    dimensions = intelligence.get("dimensions")
    gaps = intelligence.get("evidence_gaps")
    dimensions = dimensions if isinstance(dimensions, dict) else {}
    gaps = gaps if isinstance(gaps, dict) else {}
    represented: List[str] = []
    grounded: List[str] = []
    explicit: List[str] = []
    missing: List[str] = []
    for name in INTELLIGENCE_DIMENSIONS:
        claims = dimensions.get(name)
        evidence_gaps = gaps.get(name)
        if isinstance(claims, list):
            represented.append(name)
            if any(
                isinstance(item, dict)
                and str(item.get("claim") or "").strip()
                and isinstance(item.get("source_refs"), list)
                and any(str(ref or "").strip() for ref in item["source_refs"])
                for item in claims
            ):
                grounded.append(name)
        normalized_gaps = normalize_evidence_gap_map(
            {name: evidence_gaps},
            allowed_dimensions=(name,),
            require_lossless=(
                intelligence.get("schema_version")
                == ACTOR_INTELLIGENCE_VERSION
            ),
        )
        if normalized_gaps.get(name):
            explicit.append(name)
        if name not in grounded and name not in explicit:
            missing.append(name)
    return {
        "schema_version": intelligence.get("schema_version"),
        "represented_dimensions": represented,
        "grounded_dimensions": grounded,
        "explicit_gap_dimensions": explicit,
        "missing_dimensions": missing,
    }


def _parse_iso_date(value: Any) -> Optional[date]:
    text = str(value or "").strip()
    match = re.match(r"^(\d{4})-(\d{2})-(\d{2})", text)
    if not match:
        return None
    try:
        return date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
    except ValueError:
        return None


def _validate_intelligence_as_of(actor: Mapping[str, Any], cutoff_value: Any) -> None:
    cutoff = _parse_iso_date(cutoff_value)
    if cutoff is None:
        return
    intelligence = actor.get("intelligence")
    dimensions = intelligence.get("dimensions") if isinstance(intelligence, dict) else None
    if not isinstance(dimensions, dict):
        return
    for dimension, claims in dimensions.items():
        if not isinstance(claims, list):
            continue
        for claim in claims:
            if not isinstance(claim, dict):
                continue
            claim_as_of = _parse_iso_date(claim.get("as_of_date"))
            if claim_as_of is not None and claim_as_of > cutoff:
                raise ValueError(
                    f"actor intelligence claim exceeds as-of cutoff for "
                    f"{actor.get('name')}: {dimension} {claim_as_of.isoformat()} > "
                    f"{cutoff.isoformat()}"
                )


def _epistemic_context(
    actor: Mapping[str, Any], shared: Mapping[str, Any]
) -> Dict[str, Any]:
    intelligence = actor.get("intelligence")
    dimensions = intelligence.get("dimensions") if isinstance(intelligence, dict) else {}
    dimensions = dimensions if isinstance(dimensions, dict) else {}
    canonical_v1 = (
        isinstance(intelligence, Mapping)
        and intelligence.get("schema_version") == ACTOR_INTELLIGENCE_VERSION
    )

    documented_evidence: Dict[str, List[Dict[str, Any]]] = {}
    actor_known: Dict[str, List[Dict[str, Any]]] = {}
    actor_visible_contested: Dict[str, List[Dict[str, Any]]] = {}
    analyst: Dict[str, List[Dict[str, Any]]] = {}
    contested: Dict[str, List[Dict[str, Any]]] = {}

    def explicitly_known(row: Mapping[str, Any]) -> bool:
        qualifiers = row.get("qualifiers")
        qualifiers = qualifiers if isinstance(qualifiers, Mapping) else {}
        access_flags = (
            row.get("actor_knows"),
            qualifiers.get("actor_knows"),
        )
        # Consumer boundaries intentionally accept only JSON booleans. String
        # spellings such as "true"/"yes" are ambiguous research data, not an
        # authority grant. An explicit false also wins over a visibility label.
        if any(flag is False for flag in access_flags):
            return False
        if any(flag is True for flag in access_flags):
            return True
        visibility = str(
            row.get("visibility") or qualifiers.get("visibility") or ""
        ).strip().casefold().replace("-", "_").replace(" ", "_")
        return visibility in ACTOR_KNOWN_VISIBILITIES

    for dimension in INTELLIGENCE_DIMENSIONS:
        rows = dimensions.get(dimension)
        if not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, dict):
                continue
            if canonical_v1 and not (
                isinstance(row.get("source_refs"), list)
                and any(str(ref or "").strip() for ref in row["source_refs"])
            ):
                documented_evidence.setdefault(dimension, []).append(row)
                continue
            evidence_type = str(
                row.get("evidence_type") or "unknown"
            ).strip().casefold().replace("-", "_").replace(" ", "_")
            if evidence_type == "analyst_inference":
                # Epistemic inference remains modeler-only even if a malformed
                # source row asserts actor_knows/visibility.
                analyst.setdefault(dimension, []).append(row)
            elif evidence_type in {"contested", "unknown"}:
                if explicitly_known(row):
                    # Access and truth status are independent: the actor may
                    # know a contested claim while it remains contested.
                    actor_known.setdefault(dimension, []).append(row)
                    actor_visible_contested.setdefault(dimension, []).append(row)
                else:
                    contested.setdefault(dimension, []).append(row)
            elif explicitly_known(row):
                actor_known.setdefault(dimension, []).append(row)
            else:
                documented_evidence.setdefault(dimension, []).append(row)
    return {
        "shared_public_situation_evidence": shared,
        "documented_actor_evidence_not_automatically_actor_knowledge": (
            documented_evidence
        ),
        "documented_actor_beliefs_and_knowledge": actor_known,
        "actor_visible_contested_or_unknown": actor_visible_contested,
        "analyst_inference_not_automatically_known_by_actor": analyst,
        "contested_or_unknown_not_automatically_known_by_actor": contested,
        "evidence_gap_audit_not_actor_knowledge": normalize_evidence_gap_map(
            intelligence.get("evidence_gaps")
            if isinstance(intelligence, Mapping) else {},
            allowed_dimensions=INTELLIGENCE_DIMENSIONS,
            require_lossless=canonical_v1,
        ),
        "policy": (
            "Shared public evidence and documented evidence about the actor may ground "
            "behavior, but neither proves the actor knows a fact. Placement in "
            "knowledge_state is not an access grant. Only a literal boolean "
            "actor_knows=true or an allowlisted actor-known visibility may establish "
            "access. Analyst inference is always modeler-only; contested and unknown "
            "evidence retain their uncertainty even when actor-visible. Evidence-gap "
            "queries and receipt/result identifiers are modeler-only research audit "
            "metadata and never establish actor knowledge."
        ),
    }


def _bounded_intelligence_projection(actor: Mapping[str, Any], budget: int) -> Dict[str, Any]:
    intelligence = actor.get("intelligence")
    dimensions = intelligence.get("dimensions") if isinstance(intelligence, dict) else {}
    dimensions = dimensions if isinstance(dimensions, dict) else {}
    canonical_v1 = (
        isinstance(intelligence, Mapping)
        and intelligence.get("schema_version") == ACTOR_INTELLIGENCE_VERSION
    )

    def short(value: Any, limit: int) -> str:
        clean = " ".join(str(value or "").split())
        return clean if len(clean) <= limit else clean[: max(0, limit - 1)].rstrip() + "…"

    projection: Dict[str, Any] = {
        "actor_id": short(actor_id_for(actor), 240),
        "name": short(actor.get("name"), 240),
        "aliases": [
            short(alias, 160) for alias in (
                actor.get("aliases") if isinstance(actor.get("aliases"), list) else []
            )[:8]
        ],
        "role": short(actor.get("role"), 500),
        "dimensions": {},
        "evidence_gaps": {},
    }
    # Identity is load-bearing. If an extreme identifier/name cannot fit even
    # after bounded rendering, fail instead of returning a pack whose runtime
    # context silently lacks the actor identity.
    if len(json.dumps(
        projection, ensure_ascii=False, sort_keys=True, allow_nan=False
    )) > budget:
        projection["aliases"] = []
        projection["role"] = ""
    if len(json.dumps(
        projection, ensure_ascii=False, sort_keys=True, allow_nan=False
    )) > budget:
        raise ValueError("actor identity exceeds the bounded context identity budget")

    for dimension in INTELLIGENCE_DIMENSIONS:
        rows = dimensions.get(dimension)
        if not isinstance(rows, list):
            continue
        chosen: List[Dict[str, Any]] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            if canonical_v1 and not (
                isinstance(row.get("source_refs"), list)
                and any(str(ref or "").strip() for ref in row["source_refs"])
            ):
                continue
            candidate = dict(projection)
            candidate_dimensions = dict(projection["dimensions"])
            candidate_dimensions[dimension] = [*chosen, row]
            candidate["dimensions"] = candidate_dimensions
            if len(json.dumps(candidate, ensure_ascii=False, sort_keys=True, allow_nan=False)) > budget:
                continue
            chosen.append(row)
        if chosen:
            projection["dimensions"][dimension] = chosen

    evidence_gaps = (
        intelligence.get("evidence_gaps") if isinstance(intelligence, dict) else None
    )
    if isinstance(evidence_gaps, dict):
        for dimension in INTELLIGENCE_DIMENSIONS:
            gaps = evidence_gaps.get(dimension)
            if not isinstance(gaps, list):
                continue
            bounded_gaps = normalize_evidence_gap_map(
                {dimension: gaps},
                allowed_dimensions=(dimension,),
                require_lossless=canonical_v1,
            ).get(dimension, [])
            if not bounded_gaps:
                continue
            candidate = dict(projection)
            candidate_gaps = dict(projection["evidence_gaps"])
            candidate_gaps[dimension] = bounded_gaps
            candidate["evidence_gaps"] = candidate_gaps
            if len(json.dumps(
                candidate, ensure_ascii=False, sort_keys=True, allow_nan=False
            )) <= budget:
                projection["evidence_gaps"][dimension] = bounded_gaps
    return projection


def _bounded_context(
    actor: Mapping[str, Any],
    shared: Mapping[str, Any],
    relevant_sections: Sequence[Mapping[str, Any]],
    relationships: Sequence[Mapping[str, Any]],
    events: Sequence[Mapping[str, Any]],
    claims: Sequence[Mapping[str, Any]],
    quant: Sequence[Mapping[str, Any]],
    *,
    max_chars: int,
) -> str:
    evidence_boundary = (
        "EPISTEMIC BOUNDARY\nTreat shared public evidence as situation context. "
        "Treat only documented actor knowledge/beliefs as known by the actor. "
        "Analyst inference, contested claims, and unknowns are modeler context; "
        "they must not make the actor omniscient. Preserve source, confidence, "
        "status, as-of date, conditions, and contradictions. Evidence-gap "
        "queries and receipt/result IDs are modeler-only audit metadata, never "
        "actor knowledge."
    )
    identity_budget = max(1_600, min(6_000, max_chars // 3))
    identity = "ACTOR IDENTITY AND INTELLIGENCE\n" + json.dumps(
        _bounded_intelligence_projection(actor, identity_budget - 40),
        ensure_ascii=False,
        sort_keys=True,
        allow_nan=False,
    )
    required = [evidence_boundary, identity]
    required_chars = sum(len(block) for block in required) + 2
    if required_chars > max_chars:
        raise ValueError(
            "actor identity and epistemic boundary exceed the actor context budget"
        )
    blocks: List[Tuple[int, str]] = []
    if shared:
        blocks.append((1, "SHARED RESEARCH SITUATION\n" + json.dumps(
            shared, ensure_ascii=False, sort_keys=True, allow_nan=False
        )))
    for section in relevant_sections:
        blocks.append((2, f"REPORT SECTION: {section.get('heading')}\n{section.get('text', '')}"))
    for label, rows in (
        ("RELATIONSHIPS", relationships),
        ("EVENTS", events),
        ("CONTESTED CLAIMS", claims),
        ("QUANTITATIVE FACTS", quant),
    ):
        if rows:
            blocks.append((3, f"{label}\n" + json.dumps(
                list(rows), ensure_ascii=False, sort_keys=True, allow_nan=False
            )))

    chosen: List[str] = list(required)
    used = required_chars
    for _priority, block in sorted(enumerate(blocks), key=lambda row: (row[1][0], row[0])):
        text = block[1]
        extra = len(text) + (2 if chosen else 0)
        if extra + used <= max_chars:
            chosen.append(text)
            used += extra
    return "\n\n".join(chosen)


def _actor_intelligence_contract(actors: Mapping[str, Any]) -> Optional[Dict[str, Any]]:
    contract = actors.get("actor_intelligence_contract")
    return contract if isinstance(contract, dict) else None


def _is_sha256(value: Any) -> bool:
    return bool(re.fullmatch(r"[0-9a-f]{64}", str(value or "")))


def _validate_actor_intelligence_contract(
    actors: Mapping[str, Any], report_text: str
) -> Optional[Dict[str, Any]]:
    """Validate the non-circular producer contract before accepting v1 rows.

    A nested ``actor-intelligence/v1`` payload without its top-level binding is
    not a legacy dossier: it is incomplete new evidence and must fail closed.
    The report hash is checked against the exact prose supplied to prepare;
    other producer hashes bind inputs that are not independently available at
    this runtime boundary, so their strict shape and actor-roster binding are
    verified here and their exact values are carried into sealed provenance.
    """
    actor_rows = [
        row for row in (actors.get("actors") or []) if isinstance(row, Mapping)
    ]
    unsupported_versions = sorted({
        str(row["intelligence"].get("schema_version") or "").strip()
        for row in actor_rows
        if isinstance(row.get("intelligence"), Mapping)
        and str(row["intelligence"].get("schema_version") or "").strip()
        and row["intelligence"].get("schema_version")
        != ACTOR_INTELLIGENCE_VERSION
    })
    if unsupported_versions:
        raise ValueError(
            "unsupported actor intelligence row schema: "
            + ", ".join(unsupported_versions)
        )
    nested_v1 = [
        row for row in actor_rows
        if isinstance(row.get("intelligence"), Mapping)
        and row["intelligence"].get("schema_version") == ACTOR_INTELLIGENCE_VERSION
    ]
    contract = _actor_intelligence_contract(actors)
    if contract is None:
        if nested_v1:
            raise ValueError(
                "actor-intelligence/v1 rows require a top-level actor intelligence contract"
            )
        return None
    version = str(contract.get("schema_version") or "")
    if version != ACTOR_INTELLIGENCE_VERSION:
        raise ValueError(f"unsupported actor intelligence contract: {version or 'missing'}")
    if len(nested_v1) != len(actor_rows):
        raise ValueError(
            "top-level actor-intelligence/v1 contract does not cover every actor row"
        )
    for key in (
        "report_sha256", "dossier_sha256", "sources_sha256", "actor_ids_sha256"
    ):
        if not _is_sha256(contract.get(key)):
            raise ValueError(
                f"actor intelligence contract has invalid or missing {key}"
            )
    report_hash = text_sha256(report_text)
    if contract["report_sha256"] != report_hash:
        raise ValueError("actor intelligence report fingerprint mismatch")
    if not str(report_text or "").strip():
        raise ValueError("actor intelligence report is empty")

    actor_ids: List[str] = []
    for row in actor_rows:
        actor_id = str(row.get("actor_id") or "").strip()
        if not actor_id or actor_id in actor_ids:
            raise ValueError(
                "actor intelligence contract has missing or duplicate actor identities"
            )
        actor_ids.append(actor_id)
    expected_ids_sha = hashlib.sha256(
        "\n".join(sorted(actor_ids)).encode("utf-8")
    ).hexdigest()
    if contract["actor_ids_sha256"] != expected_ids_sha:
        raise ValueError("actor intelligence actor roster fingerprint mismatch")
    if type(contract.get("actor_count")) is not int or contract["actor_count"] != len(actor_rows):
        raise ValueError("actor intelligence actor_count binding mismatch")
    if (
        type(contract.get("source_count")) is not int
        or contract["source_count"] < 0
    ):
        raise ValueError("actor intelligence source_count binding is invalid")
    tier_count = contract.get("tier_1_2_actor_count")
    if type(tier_count) is not int or not 0 <= tier_count <= len(actor_rows):
        raise ValueError("actor intelligence tier actor count is invalid")
    if contract.get("dimensions") != list(INTELLIGENCE_DIMENSIONS):
        raise ValueError("actor intelligence dimension contract is incomplete or reordered")
    if not isinstance(contract.get("coverage"), Mapping):
        raise ValueError("actor intelligence coverage binding is missing")
    if not str(contract.get("generated_at") or "").strip():
        raise ValueError("actor intelligence generation binding is missing")
    return dict(contract)


def build_actor_context_pack(
    actors: Mapping[str, Any],
    actor: Mapping[str, Any],
    report_text: str,
    *,
    max_chars: int = DEFAULT_CONTEXT_MAX_CHARS,
) -> Dict[str, Any]:
    """Build one deterministic actor-specific runtime context pack."""
    if not isinstance(actors, Mapping):
        raise ValueError("actors dossier must be an object")
    if not isinstance(actor, Mapping):
        raise ValueError("selected actor must be an object")
    if int(max_chars) < MIN_CONTEXT_MAX_CHARS:
        raise ValueError(
            f"actor context budget is too small; minimum is {MIN_CONTEXT_MAX_CHARS} characters"
        )
    actor_id = actor_id_for(actor)
    actor_name = str(actor.get("name") or "").strip()
    if not actor_name:
        raise ValueError(f"selected actor {actor_id} has no canonical name")

    actors_hash = canonical_json_sha256(actors)
    report_hash = text_sha256(report_text)
    contract = _validate_actor_intelligence_contract(actors, report_text)
    contract_version = str((contract or {}).get("schema_version") or "") or None
    if contract_version == ACTOR_INTELLIGENCE_VERSION:
        bound_actor = next((
            row for row in (actors.get("actors") or [])
            if isinstance(row, Mapping) and str(row.get("actor_id") or "") == actor_id
        ), None)
        if (
            not isinstance(bound_actor, Mapping)
            or canonical_json_sha256(bound_actor) != canonical_json_sha256(actor)
        ):
            raise ValueError(
                f"selected actor {actor_name} differs from the top-level intelligence roster"
            )

    sections, omitted_audit = _select_report_sections(report_text, actor)
    shared = _shared_context(actors)
    relationships = _incident_relationships(actors.get("relationships"), actor)
    events = _relevant_rows(actors.get("key_events"), actor, 24)
    claims = _relevant_rows(actors.get("contested_claims"), actor, 16)
    quant = _relevant_rows(actors.get("quantitative_facts"), actor, 32)
    dimension_coverage = _dimension_coverage(actor)
    _validate_intelligence_as_of(actor, actors.get("as_of_date"))

    if contract_version == ACTOR_INTELLIGENCE_VERSION:
        if dimension_coverage["schema_version"] != ACTOR_INTELLIGENCE_VERSION:
            raise ValueError(f"actor intelligence is missing for selected actor {actor_name}")
        if dimension_coverage["missing_dimensions"]:
            raise ValueError(
                f"actor intelligence coverage is incomplete for {actor_name}: "
                + ", ".join(dimension_coverage["missing_dimensions"])
            )
        if not sections:
            raise ValueError(
                f"research report has no actor-relevant section for {actor_name}"
            )

    bounded = _bounded_context(
        actor,
        shared,
        sections,
        relationships,
        events,
        claims,
        quant,
        max_chars=max_chars,
    )
    if len(bounded) > max_chars:
        raise AssertionError("actor context compiler exceeded its hard character bound")

    structured_totals = {
        "events": len(actors.get("key_events")) if isinstance(actors.get("key_events"), list) else 0,
        "claims": len(actors.get("contested_claims")) if isinstance(actors.get("contested_claims"), list) else 0,
        "quantitative_facts": len(actors.get("quantitative_facts")) if isinstance(actors.get("quantitative_facts"), list) else 0,
        "relationships": len(actors.get("relationships")) if isinstance(actors.get("relationships"), list) else 0,
    }
    structured_selected = {
        "events": len(events),
        "claims": len(claims),
        "quantitative_facts": len(quant),
        "relationships": len(relationships),
    }
    return {
        "schema_version": ACTOR_CONTEXT_VERSION,
        "actor_id": actor_id,
        "actor_name": actor_name,
        "aliases": _actor_surfaces(actor)[1:],
        "source": {
            "actors_sha256": actors_hash,
            "report_sha256": report_hash,
            "actor_intelligence_contract_version": contract_version,
            "actor_intelligence_sha256": (
                canonical_json_sha256(actor.get("intelligence"))
                if isinstance(actor.get("intelligence"), dict) else None
            ),
            "dossier_sha256": (contract or {}).get("dossier_sha256"),
            "sources_sha256": (contract or {}).get("sources_sha256"),
            "actor_ids_sha256": (contract or {}).get("actor_ids_sha256"),
        },
        "shared_context": shared,
        "epistemic_context": _epistemic_context(actor, shared),
        "actor_intelligence": actor.get("intelligence") if isinstance(actor.get("intelligence"), dict) else None,
        "relevant_sections": sections,
        "events": events,
        "claims": claims,
        "quantitative_facts": quant,
        "relationships": relationships,
        "dimension_coverage": dimension_coverage,
        "bounded_context": bounded,
        "bounded_context_chars": len(bounded),
        "bounded_context_max_chars": max_chars,
        "omitted_section_audit": omitted_audit,
        "omitted_item_audit": {
            key: {
                "available": structured_totals[key],
                "selected": structured_selected[key],
                "omitted": max(0, structured_totals[key] - structured_selected[key]),
                "reason": "row lacked actor-specific relevance or exceeded the row cap",
            }
            for key in structured_totals
        },
    }


def build_actor_context_artifacts(
    sim_dir: str,
    actors: Mapping[str, Any],
    selected_actors: Sequence[Mapping[str, Any]],
    report_text: str,
    *,
    max_chars: int = DEFAULT_CONTEXT_MAX_CHARS,
) -> Tuple[Dict[str, Dict[str, Any]], Dict[str, Any], str]:
    """Persist selected-actor packs and a root manifest before persona creation."""
    if not isinstance(actors, Mapping):
        raise ValueError("actors dossier must be an object")
    context_dir = os.path.join(sim_dir, "actor_context")
    os.makedirs(context_dir, exist_ok=True)

    packs: Dict[str, Dict[str, Any]] = {}
    rows: List[Dict[str, Any]] = []
    seen: set[str] = set()
    for actor in selected_actors:
        actor_id = actor_id_for(actor)
        if actor_id in seen:
            raise ValueError(f"duplicate selected actor_id in context build: {actor_id}")
        seen.add(actor_id)
        pack = build_actor_context_pack(actors, actor, report_text, max_chars=max_chars)
        filename = _safe_pack_filename(actor_id)
        path = os.path.join(context_dir, filename)
        write_json_atomic(path, pack, ensure_ascii=False, indent=2, allow_nan=False)
        with open(path, "rb") as handle:
            pack_bytes = handle.read()
        pack_sha = hashlib.sha256(pack_bytes).hexdigest()
        # Return the exact deep-decoded object represented by the sealed bytes,
        # not the pre-serialization object that still aliases actors.json.
        sealed_pack = json.loads(pack_bytes.decode("utf-8"))
        packs[actor_id] = sealed_pack
        rows.append({
            "actor_id": actor_id,
            "actor_name": sealed_pack["actor_name"],
            "file": os.path.join("actor_context", filename),
            "sha256": pack_sha,
            "bounded_context_chars": sealed_pack["bounded_context_chars"],
            "relevant_section_count": len(sealed_pack["relevant_sections"]),
            "grounded_dimension_count": len(
                sealed_pack["dimension_coverage"]["grounded_dimensions"]
            ),
            "explicit_gap_dimension_count": len(
                sealed_pack["dimension_coverage"]["explicit_gap_dimensions"]
            ),
        })

    actor_ids = [row["actor_id"] for row in rows]
    contract = _actor_intelligence_contract(actors)
    manifest = {
        "schema_version": ACTOR_CONTEXT_MANIFEST_VERSION,
        "pack_schema_version": ACTOR_CONTEXT_VERSION,
        "actor_intelligence_contract_version": (
            str((contract or {}).get("schema_version") or "") or None
        ),
        "actors_sha256": canonical_json_sha256(actors),
        "report_sha256": text_sha256(report_text),
        "selected_actor_count": len(rows),
        "pack_count": len(rows),
        "actor_ids_sha256": canonical_json_sha256(actor_ids),
        "context_max_chars": max_chars,
        "packs": rows,
    }
    manifest_path = os.path.join(sim_dir, "actor_context_manifest.json")
    write_json_atomic(
        manifest_path, manifest, ensure_ascii=False, indent=2, allow_nan=False
    )
    with open(manifest_path, "rb") as handle:
        manifest_bytes = handle.read()
    manifest_sha = hashlib.sha256(manifest_bytes).hexdigest()
    sealed_manifest = json.loads(manifest_bytes.decode("utf-8"))
    return packs, sealed_manifest, manifest_sha


def validate_actor_context_artifacts(
    sim_dir: str,
    *,
    expected_count: Optional[int] = None,
    expected_manifest_sha256: Optional[str] = None,
    expected_report_sha256: Optional[str] = None,
    expected_actors_sha256: Optional[str] = None,
    expected_actor_ids: Optional[Iterable[str]] = None,
) -> Tuple[Dict[str, Any], Dict[str, Dict[str, Any]]]:
    """Fail closed if a prepared context manifest or selected pack was altered."""
    manifest_path = os.path.join(sim_dir, "actor_context_manifest.json")
    with open(manifest_path, "rb") as handle:
        manifest_bytes = handle.read()
    actual_manifest_sha = hashlib.sha256(manifest_bytes).hexdigest()
    if expected_manifest_sha256 and actual_manifest_sha != expected_manifest_sha256:
        raise ValueError("actor context manifest fingerprint mismatch")
    manifest = json.loads(manifest_bytes.decode("utf-8"))
    if not isinstance(manifest, dict):
        raise ValueError("actor context manifest must be an object")
    if manifest.get("schema_version") != ACTOR_CONTEXT_MANIFEST_VERSION:
        raise ValueError("actor context manifest schema is stale")
    if manifest.get("pack_schema_version") != ACTOR_CONTEXT_VERSION:
        raise ValueError("actor context pack schema is stale")
    rows = manifest.get("packs")
    if not isinstance(rows, list):
        raise ValueError("actor context manifest packs must be a list")
    count = int(manifest.get("pack_count", -1))
    if count != len(rows) or count != int(manifest.get("selected_actor_count", -2)):
        raise ValueError("actor context manifest count mismatch")
    if expected_count is not None and count != int(expected_count):
        raise ValueError("actor context manifest does not cover the selected cast")
    if expected_report_sha256 and manifest.get("report_sha256") != expected_report_sha256:
        raise ValueError("actor context report fingerprint mismatch")
    if expected_actors_sha256 and manifest.get("actors_sha256") != expected_actors_sha256:
        raise ValueError("actor context dossier fingerprint mismatch")

    ids: List[str] = []
    packs: Dict[str, Dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("actor context manifest row must be an object")
        actor_id = str(row.get("actor_id") or "")
        if not actor_id or actor_id in packs:
            raise ValueError("actor context actor identity is missing or duplicated")
        relative = str(row.get("file") or "")
        if not relative or os.path.isabs(relative):
            raise ValueError("actor context pack path must be relative")
        normalized = os.path.normpath(relative)
        if normalized.startswith(".." + os.sep) or normalized == "..":
            raise ValueError("actor context pack path escapes the simulation directory")
        expected_prefix = "actor_context" + os.sep
        if not normalized.startswith(expected_prefix):
            raise ValueError("actor context pack path is outside actor_context")
        path = os.path.join(sim_dir, normalized)
        with open(path, "rb") as handle:
            pack_bytes = handle.read()
        if hashlib.sha256(pack_bytes).hexdigest() != row.get("sha256"):
            raise ValueError(f"actor context pack fingerprint mismatch for {actor_id}")
        pack = json.loads(pack_bytes.decode("utf-8"))
        if not isinstance(pack, dict) or pack.get("schema_version") != ACTOR_CONTEXT_VERSION:
            raise ValueError(f"actor context pack schema is stale for {actor_id}")
        if pack.get("actor_id") != actor_id or pack.get("actor_name") != row.get("actor_name"):
            raise ValueError(f"actor context pack identity mismatch for {actor_id}")
        source = pack.get("source")
        if not isinstance(source, dict):
            raise ValueError(f"actor context source binding is missing for {actor_id}")
        if source.get("actors_sha256") != manifest.get("actors_sha256"):
            raise ValueError(f"actor context dossier binding mismatch for {actor_id}")
        if source.get("report_sha256") != manifest.get("report_sha256"):
            raise ValueError(f"actor context report binding mismatch for {actor_id}")
        bounded = pack.get("bounded_context")
        if not isinstance(bounded, str):
            raise ValueError(f"actor context text is missing for {actor_id}")
        max_chars = int(pack.get("bounded_context_max_chars", -1))
        if max_chars < 0 or len(bounded) > max_chars:
            raise ValueError(f"actor context text bound is invalid for {actor_id}")
        if manifest.get("actor_intelligence_contract_version") == ACTOR_INTELLIGENCE_VERSION:
            coverage = pack.get("dimension_coverage")
            if not isinstance(coverage, dict) or coverage.get("missing_dimensions"):
                raise ValueError(f"actor intelligence coverage is incomplete for {actor_id}")
            if not pack.get("relevant_sections"):
                raise ValueError(f"actor report coverage is missing for {actor_id}")
        ids.append(actor_id)
        packs[actor_id] = pack

    if manifest.get("actor_ids_sha256") != canonical_json_sha256(ids):
        raise ValueError("actor context roster fingerprint mismatch")
    if expected_actor_ids is not None and ids != list(expected_actor_ids):
        raise ValueError("actor context roster does not match the selected cast")
    return manifest, packs


def context_binding_by_actor_id(manifest: Mapping[str, Any]) -> Dict[str, Dict[str, Any]]:
    rows = manifest.get("packs") if isinstance(manifest, Mapping) else None
    if not isinstance(rows, list):
        return {}
    return {
        str(row.get("actor_id")): dict(row)
        for row in rows
        if isinstance(row, dict) and row.get("actor_id")
    }
