"""RESEARCH-12: downstream consumers of the research question spec (drf.question_spec/v1).

RESEARCH-11's v3 research engine (RESEARCH_QUESTION_SPEC) pins how the forecast
resolves: an outcome definition, a resolution source, a horizon (label and ISO day),
a reference class and at most three defaults it chose instead of asking.  It
mirrors the whole normalized spec into actors.json ``question_spec`` so a consumer
can recompute ``spec_sha256`` from actors.json alone.  This module is the backend
side of that contract:

* :func:`load_question_spec` accepts only a well-formed spec of status ok or
  partial whose hash recomputes with the bridge's canonical JSON profile
  (``app.utils.canonical_json``); anything else is absent (fail closed: a damaged
  or edited spec never steers a forecast);
* :func:`spec_horizon_date` is the simulation calendar's horizon rung, ranked
  below the deterministic prompt dates and above the LLM fallback;
* :func:`render_spine_block` is the Chinese block prepended to the spine prompt's
  research inputs, so scenario resolution criteria share the spec's outcome,
  source and deadline;
* :func:`render_resolution_disclosure` is the report's "How to verify" subsection
  that discloses the operational definitions and every default assumption;
* :func:`summary` is forecast.json ``question_spec``.

QUESTION_SPEC_DOWNSTREAM (default on) gates every consumer through
:func:`downstream_spec`; it is a no-op unless actors.json carries a valid spec
(which needs RESEARCH_QUESTION_SPEC), and off is shadow mode (persisted, unused).
Everything but :func:`downstream_spec` (which reads Config) is pure; nothing but
:func:`spec_sha256` (on a non-JSON value) raises, and :func:`downstream_spec` never
does (an enhancement must not break a run).
"""

from __future__ import annotations

import calendar
import copy
import logging
import re
from datetime import date, datetime
from typing import Any, Dict, List, Mapping, Optional

from ..utils.canonical_json import canonical_json_sha256

logger = logging.getLogger(__name__)

QUESTION_SPEC_SCHEMA = "drf.question_spec/v1"
USABLE_STATUSES = ("ok", "partial")
# A horizon day is used only in (as_of, as_of + this many years] (the bridge's window).
MAX_HORIZON_YEARS = 30
# forecast.json ``question_spec`` keys (summary()).
SUMMARY_KEYS = ("spec_sha256", "horizon_date", "outcome_definition", "resolution_source", "assumptions")

SPINE_BLOCK_HEADER = ("[问题规范（操作化定义；各情景 resolution_criteria 须采用此结果定义、判定来源与判定日；"
                      "情景集合须划分该结果空间）]")
DISCLOSURE_HEADING_EN = "### Operational Definitions and Assumptions"
DISCLOSURE_HEADING_ZH = "### 操作化定义与本次运行的默认假设"

_ISO_DAY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_SOURCE_KIND_ZH = {
    "official_statistic": "官方统计", "index": "指数", "market": "市场",
    "consensus_reporting": "共识报道", "expert_panel": "专家组", "other": "其他",
}
_SLOT_EN = {"horizon": "deadline", "resolution_source": "resolution source", "units": "units",
            "entity": "entity", "outcome": "outcome"}
_SLOT_ZH = {"horizon": "判定日", "resolution_source": "判定来源", "units": "单位", "entity": "主体",
            "outcome": "结果"}


def spec_sha256(spec: Mapping[str, Any]) -> str:
    """sha256 of the canonical JSON of every key but ``spec_sha256`` (the bridge's
    ``question_spec_sha256``; raises TypeError/ValueError on a non-JSON value)."""
    return canonical_json_sha256({key: value for key, value in spec.items() if key != "spec_sha256"})


def _rejection(spec: Any) -> str:
    """Why ``spec`` is not usable downstream (``""``: usable)."""
    if not isinstance(spec, Mapping):
        return "not an object"
    if spec.get("schema") != QUESTION_SPEC_SCHEMA:
        return f"schema {spec.get('schema')!r}"
    if spec.get("status") not in USABLE_STATUSES:
        return f"status {spec.get('status')!r}"
    if not (isinstance(spec.get("horizon"), Mapping) and isinstance(spec.get("resolution_source"), Mapping)
            and isinstance(spec.get("assumptions"), list)):
        return "malformed fields"
    try:
        recomputed = spec_sha256(spec)
    except (TypeError, ValueError):
        return "not canonical JSON"
    if spec.get("spec_sha256") != recomputed:
        return "spec_sha256 mismatch"
    return ""


def load_question_spec(actors: Any) -> Optional[Dict[str, Any]]:
    """actors.json ``question_spec`` when usable, as an independent copy; else None.

    Usable: schema ``drf.question_spec/v1``, status ok or partial, the object
    fields the bridge writes, and a ``spec_sha256`` that recomputes.  An absent
    key is None silently; any other rejection logs a warning (fail closed)."""
    spec = actors.get("question_spec") if isinstance(actors, Mapping) else None
    if spec is None:
        return None
    reason = _rejection(spec)
    if reason:
        logger.warning(f"actors.json question_spec ignored ({reason}): downstream consumers run without it")
        return None
    return copy.deepcopy(dict(spec))


def downstream_spec(actors: Any) -> Optional[Dict[str, Any]]:
    """:func:`load_question_spec` when QUESTION_SPEC_DOWNSTREAM is on, else None.
    Config is read here, not at import, so importing this module never loads it.
    Degrade-safe: an unexpected error is logged and reads as no spec, so every
    consumer keeps its pre-spec behaviour instead of failing the run."""
    from ..config import Config
    if not getattr(Config, "QUESTION_SPEC_DOWNSTREAM", True):
        return None
    try:
        return load_question_spec(actors)
    except Exception as exc:  # noqa: BLE001 — a consumer enhancement never breaks a run
        logger.warning(f"actors.json question_spec ignored ({type(exc).__name__}: {exc}): "
                       "downstream consumers run without it")
        return None


def _window_end(as_of: date) -> date:
    """as_of + MAX_HORIZON_YEARS (29 February → 28 February; never past year 9999)."""
    year = min(as_of.year + MAX_HORIZON_YEARS, date.max.year)
    return as_of.replace(year=year, day=min(as_of.day, calendar.monthrange(year, as_of.month)[1]))


def spec_horizon_date(spec: Any, as_of: Any) -> Optional[date]:
    """The spec's ``horizon.date`` when it is an ISO day in (as_of, as_of + 30y]; else None."""
    if isinstance(as_of, datetime):
        as_of = as_of.date()
    if not isinstance(spec, Mapping) or not isinstance(as_of, date):
        return None
    horizon = spec.get("horizon")
    raw = horizon.get("date") if isinstance(horizon, Mapping) else None
    if not isinstance(raw, str) or not _ISO_DAY_RE.match(raw):
        return None
    try:
        day = date.fromisoformat(raw)
    except ValueError:
        return None
    return day if as_of < day <= _window_end(as_of) else None


def _text(value: Any) -> str:
    """A string field as one line (the bridge already collapses whitespace; a line break
    from any other producer must not split a prompt line or a Markdown bullet)."""
    return " ".join(value.split()) if isinstance(value, str) else ""


def _fields(spec: Any) -> Dict[str, Any]:
    """The displayed fields of ``spec`` as stripped text (empty when absent or mistyped)."""
    spec = spec if isinstance(spec, Mapping) else {}
    source = spec.get("resolution_source") if isinstance(spec.get("resolution_source"), Mapping) else {}
    horizon = spec.get("horizon") if isinstance(spec.get("horizon"), Mapping) else {}
    rows = spec.get("assumptions") if isinstance(spec.get("assumptions"), list) else []
    assumptions = [(_text(row.get("text")), _text(row.get("slot"))) for row in rows if isinstance(row, Mapping)]
    return {
        "outcome": _text(spec.get("outcome_definition")),
        "source_name": _text(source.get("name")),
        "source_kind": _text(source.get("kind")),
        "source_url": _text(source.get("url")),
        "label": _text(horizon.get("label")),
        "date": _text(horizon.get("date")),
        "reference_class": _text(spec.get("reference_class")),
        "assumptions": [(text, slot) for text, slot in assumptions if text],
    }


def _deadline(label: str, day: str, open_paren: str, close_paren: str) -> str:
    if label and day:
        return f"{label}{open_paren}{day}{close_paren}"
    return label or day


def render_spine_block(spec: Any) -> str:
    """The spine prompt block (Chinese, like the spine prompt): the header, then the
    outcome, source, deadline, reference class and assumption lines the spec has;
    ``""`` when it has none of them."""
    f = _fields(spec)
    lines: List[str] = []
    if f["outcome"]:
        lines.append(f"结果定义：{f['outcome']}")
    if f["source_name"]:
        kind = _SOURCE_KIND_ZH.get(f["source_kind"], f["source_kind"])
        line = f"判定来源：{f['source_name']}" + (f"（{kind}）" if kind else "")
        lines.append(line + (f" {f['source_url']}" if f["source_url"] else ""))
    deadline = _deadline(f["label"], f["date"], "（", "）")
    if deadline:
        lines.append(f"判定日：{deadline}")
    if f["reference_class"]:
        lines.append(f"参考类：{f['reference_class']}")
    if f["assumptions"]:
        lines.append("本次运行的默认假设（研究阶段未经询问而采用）：")
        lines += [f"- {text}" for text, _slot in f["assumptions"]]
    return "\n".join([SPINE_BLOCK_HEADER, *lines]) if lines else ""


def render_resolution_disclosure(spec: Any, language: str = "Chinese") -> str:
    """The "How to verify" subsection: heading, one lead line, then the outcome,
    resolution source, deadline, reference class and every assumption the spec
    has (English when ``language`` starts with "en", else Chinese, the rule of
    render_resolution_block); ``""`` when it has none of them."""
    f = _fields(spec)
    zh = not str(language or "").strip().lower().startswith("en")
    rows: List[str] = []
    if zh:
        if f["outcome"]:
            rows.append(f"- **结果定义**：{f['outcome']}")
        if f["source_name"]:
            kind = _SOURCE_KIND_ZH.get(f["source_kind"], f["source_kind"])
            line = f"- **判定来源**：{f['source_name']}" + (f"（{kind}）" if kind else "")
            if f["source_url"]:
                line += ("— " if kind else " — ") + f["source_url"]
            rows.append(line)
        deadline = _deadline(f["label"], f["date"], "（", "）")
        if deadline:
            rows.append(f"- **判定日**：{deadline}")
        if f["reference_class"]:
            rows.append(f"- **参考类**：{f['reference_class']}")
        for text, slot in f["assumptions"]:
            rows.append(f"- **默认假设（{_SLOT_ZH.get(slot, slot or '结果')}）**：{text}")
        head = [DISCLOSURE_HEADING_ZH,
                "研究阶段在制定计划时固定了问题的操作化定义，并披露了未经询问而采用的默认假设。"]
    else:
        if f["outcome"]:
            rows.append(f"- **Outcome:** {f['outcome']}")
        if f["source_name"]:
            kind = f["source_kind"].replace("_", " ")
            line = f"- **Resolution source:** {f['source_name']}" + (f" ({kind})" if kind else "")
            rows.append(line + (f" — {f['source_url']}" if f["source_url"] else ""))
        deadline = _deadline(f["label"], f["date"], " (", ")")
        if deadline:
            rows.append(f"- **Deadline:** {deadline}")
        if f["reference_class"]:
            rows.append(f"- **Reference class:** {f['reference_class']}")
        for text, slot in f["assumptions"]:
            rows.append(f"- **Default assumption ({_SLOT_EN.get(slot, slot or 'outcome')}):** {text}")
        head = [DISCLOSURE_HEADING_EN,
                "The research run fixed this operational definition of the question at planning time "
                "and disclosed the defaults it chose instead of asking."]
    return "\n".join(head + rows) if rows else ""


def summary(spec: Mapping[str, Any]) -> Dict[str, Any]:
    """forecast.json ``question_spec``: the spec hash, horizon date (None when the spec
    has none), outcome definition, resolution source and assumptions (copies)."""
    spec = spec if isinstance(spec, Mapping) else {}
    horizon = spec.get("horizon") if isinstance(spec.get("horizon"), Mapping) else {}
    source = spec.get("resolution_source") if isinstance(spec.get("resolution_source"), Mapping) else {}
    rows = spec.get("assumptions") if isinstance(spec.get("assumptions"), list) else []
    return {
        "spec_sha256": spec.get("spec_sha256"),
        "horizon_date": horizon.get("date") or None,
        "outcome_definition": spec.get("outcome_definition") or "",
        "resolution_source": copy.deepcopy(dict(source)),
        "assumptions": [copy.deepcopy(dict(row)) for row in rows if isinstance(row, Mapping)],
    }
