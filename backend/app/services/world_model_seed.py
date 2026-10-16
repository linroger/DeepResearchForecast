"""PREPARE-time ``world_model`` block for the reflexive simulation (design §2.7).

Built deterministically (no LLM) inside ``SimulationConfigGenerator.generate_config``
before the config is sealed, from research artifacts the preparation stage already
holds:

* ``state_variables`` — numeric/categorical facts parsed from the dossier's
  ``quantitative_facts`` and the bound official-data snapshot (latest observation at
  or before the research as-of date), each with unit, as-of and provenance.
* ``actors`` — one row per cast member (audience fill excluded): agency class
  (dossier value → ontology/type/role inference), archetype, class capacity,
  declared outcome power only, documented plans / red lines / goals (bounded,
  sanitised, actor-own evidence), allies and rivals from the valenced relationships.
* ``relationships`` — valenced edges restricted to the cast.
* ``settings`` — arbiter switch, change-ratio clamp, barrier timeout.

Canonical actor-intelligence/v1 dossiers: plans, red lines and goals come only from
the validated context pack's producer-admitted claim rows (never from the flat
compatibility fields); analyst inference is skipped.  Legacy dossiers use their flat
fields.  Pure and never raises (a failure degrades to a smaller block).
"""

from __future__ import annotations

import math
from typing import Any, Dict, Iterable, List, Optional, Sequence

from ..utils.actors import (
    entity_archetype,
    extract_forecast_inputs,
    extract_quantitative_rows,
    extract_relationship_rows,
    match_actor,
    normalize_name,
    relation_polarity,
    relation_valence,
)
from .actor_role_prompt import sanitize_untrusted_dossier_text
from .agent_decision import default_capacity, infer_agency_class
from .world_model import parse_quantity, slugify

WORLD_MODEL_SEED_VERSION = "world-model-seed/v1"
DEFAULT_MAX_VARIABLES = 24
MAX_OFFICIAL_SERIES = 10
MAX_PLANS = 4
MAX_RED_LINES = 3
MAX_GOALS = 3
_PLAN_DIMENSIONS = ("future_plans", "likely_actions", "current_actions", "investments_capital_allocation")


def _clean(value: Any, max_chars: int) -> str:
    return sanitize_untrusted_dossier_text(value, max_chars) if value not in (None, "") else ""


def _dedupe(values: Iterable[str], limit: int) -> List[str]:
    out: List[str] = []
    for v in values:
        t = str(v or "").strip()
        if t and t.casefold() not in {o.casefold() for o in out}:
            out.append(t)
        if len(out) >= limit:
            break
    return out


def _is_canonical(actor: Dict[str, Any]) -> bool:
    intel = actor.get("intelligence")
    return isinstance(intel, dict) and str(intel.get("schema_version") or "") == "actor-intelligence/v1"


def _pack_claims(pack: Optional[Dict[str, Any]], dimensions: Sequence[str], limit: int) -> List[str]:
    """Documented (non-inference) claim texts of the actor's own validated context pack."""
    if not isinstance(pack, dict):
        return []
    intel = pack.get("actor_intelligence")
    dims = intel.get("dimensions") if isinstance(intel, dict) else None
    if not isinstance(dims, dict):
        return []
    out: List[str] = []
    for dim in dimensions:
        rows = dims.get(dim)
        if not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, dict):
                continue
            if str(row.get("evidence_type") or "").casefold().replace("-", "_") == "analyst_inference":
                continue
            if row.get("actor_knows") is False:
                continue
            claim = _clean(row.get("claim"), 200)
            if claim:
                out.append(claim)
    return _dedupe(out, limit)


def _legacy_list(actor: Dict[str, Any], keys: Sequence[str], limit: int) -> List[str]:
    out: List[str] = []
    for key in keys:
        value = actor.get(key)
        if isinstance(value, str):
            value = [value]
        if isinstance(value, dict):
            value = list(value.values())
        if not isinstance(value, list):
            continue
        for item in value:
            if isinstance(item, dict):
                item = item.get("claim") or item.get("text") or item.get("action") or item.get("description")
            text = _clean(item, 200)
            if text:
                out.append(text)
    intel = actor.get("intelligence")
    if isinstance(intel, dict) and not _is_canonical(actor):
        for key in keys:
            value = intel.get(key)
            if isinstance(value, list):
                for item in value:
                    if isinstance(item, dict):
                        item = item.get("claim") or item.get("text")
                    text = _clean(item, 200)
                    if text:
                        out.append(text)
    return _dedupe(out, limit)


def _declared_outcome_power(actor: Optional[Dict[str, Any]], cfg: Dict[str, Any]) -> Optional[float]:
    """Only an explicitly declared power counts (I-3); visibility is never reused."""
    for source in (cfg, actor or {}):
        if not isinstance(source, dict):
            continue
        for key in ("outcome_power", "power"):
            raw = source.get(key)
            if isinstance(raw, bool) or raw is None:
                continue
            try:
                value = float(raw)
            except (TypeError, ValueError):
                continue
            if math.isfinite(value) and value >= 0:
                return value
    return None


def _cfg_get(cfg: Any, key: str, default: Any = None) -> Any:
    if isinstance(cfg, dict):
        return cfg.get(key, default)
    return getattr(cfg, key, default)


def resolve_agency_class(actor: Optional[Dict[str, Any]], entity_type: str = "",
                         ontology_class: str = "") -> str:
    """Dossier value → ontology value → inference from type/role/description text."""
    for candidate in ((actor or {}).get("agency_class"), ontology_class):
        if isinstance(candidate, str) and candidate.strip():
            klass = infer_agency_class(candidate)
            if klass != "other_actor" or candidate.strip().casefold() == "other_actor":
                return klass
    actor = actor if isinstance(actor, dict) else {}
    generic = {"", "actor", "actors", "entity", "agent", "unknown"}
    type_name = entity_type if str(entity_type or "").strip().casefold() not in generic else ""
    return infer_agency_class(
        type_name or actor.get("type") or "",
        actor.get("role"), actor.get("role_class"), actor.get("description"), actor.get("name"),
        archetype=entity_archetype(actor) if actor else "",
    )


def state_variables_from_research(actors: Optional[Dict[str, Any]],
                                  official_data: Optional[Dict[str, Any]] = None, *,
                                  max_variables: int = DEFAULT_MAX_VARIABLES) -> List[Dict[str, Any]]:
    """Seed variables: dossier quantitative facts first, then the official snapshot."""
    out: List[Dict[str, Any]] = []
    seen: set = set()
    as_of = str((actors or {}).get("as_of_date") or "")[:10] if isinstance(actors, dict) else ""

    def push(row: Dict[str, Any]) -> bool:
        vid = slugify(row.get("name"))
        if vid in seen or len(out) >= max_variables:
            return False
        seen.add(vid)
        out.append({"id": vid, **row})
        return True

    for fact in extract_quantitative_rows(actors):
        name = _clean(fact.get("metric"), 140)
        if not name:
            continue
        number, parsed_unit = parse_quantity(fact.get("value"))
        unit = _clean(fact.get("unit"), 24) or parsed_unit
        row: Dict[str, Any] = {
            "name": name,
            "value": number if number is not None else _clean(fact.get("value"), 160),
            "unit": unit if number is not None else "",
            "kind": "numeric" if number is not None else "text",
            "as_of": _clean(fact.get("as_of_date") or fact.get("as_of"), 40) or (as_of or None),
            "provenance": "research",
        }
        source = _clean(fact.get("source"), 120)
        definition = _clean(fact.get("definition"), 160)
        rationale = "; ".join(x for x in (definition, source) if x)
        if rationale:
            row["rationale"] = rationale
        push(row)

    series = official_data.get("series") if isinstance(official_data, dict) else None
    taken = 0
    for row in series if isinstance(series, list) else []:
        if taken >= MAX_OFFICIAL_SERIES or len(out) >= max_variables:
            break
        if not isinstance(row, dict):
            continue
        name = _clean(row.get("title") or row.get("name") or row.get("series"), 140)
        units = _clean(row.get("units"), 24)
        obs = row.get("observations")
        if not name or not units or not isinstance(obs, list):
            continue  # the official snapshot applies the same no-units exclusion
        latest: Optional[Dict[str, Any]] = None
        for o in obs:
            if not isinstance(o, dict):
                continue
            value = o.get("value")
            date = str(o.get("date") or "")[:10]
            if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(float(value)):
                continue
            if as_of and date and date > as_of:
                continue
            if latest is None or date > str(latest.get("date") or ""):
                latest = {"date": date, "value": float(value)}
        if latest is None:
            continue
        provider = _clean(row.get("provider_name") or row.get("provider"), 80)
        if push({"name": name, "value": latest["value"], "unit": units, "kind": "numeric",
                 "as_of": latest["date"] or None, "provenance": "official",
                 "rationale": provider or "official statistics"}):
            taken += 1
    return out


def build_world_model_seed(
    actors: Optional[Dict[str, Any]],
    agent_configs: Sequence[Any],
    *,
    question: str = "",
    actor_context_packs: Optional[Dict[str, Dict[str, Any]]] = None,
    official_data: Optional[Dict[str, Any]] = None,
    temporal_timeline: Any = None,
    audience_entity_type: str = "Audience",
    ontology_classes: Optional[Dict[str, str]] = None,
    max_variables: int = DEFAULT_MAX_VARIABLES,
    arbiter_enabled: bool = True,
    max_change_ratio: float = 0.5,
    barrier_timeout_s: float = 1800.0,
) -> Dict[str, Any]:
    """The sealed ``world_model`` block.  Degrades to a smaller block, never raises."""
    block: Dict[str, Any] = {
        "schema_version": WORLD_MODEL_SEED_VERSION,
        "question": _clean(question, 400),
        "as_of_date": None,
        "horizon_date": None,
        "scenarios": [],
        "state_variables": [],
        "actors": [],
        "relationships": [],
        "scenario_indicators": [],
        "settings": {
            "arbiter_enabled": bool(arbiter_enabled),
            "max_change_ratio": float(max_change_ratio),
            "barrier_timeout_s": float(barrier_timeout_s),
        },
    }
    actors_dict = actors if isinstance(actors, dict) else {}
    try:
        block["as_of_date"] = _clean(actors_dict.get("as_of_date"), 40) or None
        if temporal_timeline is not None:
            block["as_of_date"] = _clean(getattr(temporal_timeline, "as_of_date", None)
                                         or (temporal_timeline.get("as_of_date") if isinstance(temporal_timeline, dict) else None), 40) or block["as_of_date"]
            block["horizon_date"] = _clean(getattr(temporal_timeline, "horizon_date", None)
                                           or (temporal_timeline.get("horizon_date") if isinstance(temporal_timeline, dict) else None), 40) or None
        fi = extract_forecast_inputs(actors_dict)
        block["scenarios"] = _dedupe(
            (str(s.get("name") or s.get("scenario") or "") for s in fi.get("scenarios") or []), 8)
        block["scenario_indicators"] = [
            {"indicator": _clean(i.get("indicator") or i.get("name") or i.get("metric"), 160),
             "direction": _clean(i.get("direction") or i.get("signal"), 60)}
            for i in (fi.get("indicators") or [])[:8]
            if isinstance(i, dict) and _clean(i.get("indicator") or i.get("name") or i.get("metric"), 160)
        ]
    except Exception:  # noqa: BLE001
        pass
    try:
        block["state_variables"] = state_variables_from_research(actors_dict, official_data,
                                                                 max_variables=max_variables)
    except Exception:  # noqa: BLE001
        block["state_variables"] = []

    # actors ------------------------------------------------------------------------------
    packs = actor_context_packs if isinstance(actor_context_packs, dict) else {}
    pack_by_name: Dict[str, Dict[str, Any]] = {}
    for pack in packs.values():
        if isinstance(pack, dict) and pack.get("actor_name"):
            pack_by_name[normalize_name(str(pack["actor_name"]))] = pack
    name_to_agent: Dict[str, int] = {}
    rows: List[Dict[str, Any]] = []
    for cfg in agent_configs or []:
        try:
            aid = _cfg_get(cfg, "agent_id")
            if aid is None:
                continue
            aid = int(aid)
            entity_type = str(_cfg_get(cfg, "entity_type", "") or "")
            if entity_type == audience_entity_type:
                continue
            name = _clean(_cfg_get(cfg, "entity_name", "") or f"Agent_{aid}", 160)
            actor = match_actor(name, actors_dict) if actors_dict else None
            actor = actor if isinstance(actor, dict) else None
            ontology_class = (ontology_classes or {}).get(entity_type, "") if ontology_classes else ""
            agency = resolve_agency_class(actor, entity_type, ontology_class)
            canonical = bool(actor and _is_canonical(actor))
            pack = pack_by_name.get(normalize_name(name)) if canonical else None
            if canonical:
                plans = _pack_claims(pack, _PLAN_DIMENSIONS, MAX_PLANS)
                red_lines = _pack_claims(pack, ("red_lines",), MAX_RED_LINES)
                goals = _pack_claims(pack, ("motivations", "values_worldview"), MAX_GOALS)
            else:
                plans = _legacy_list(actor or {}, ("future_plans", "plans", "likely_actions", "current_actions",
                                                   "actions_in_progress"), MAX_PLANS)
                red_lines = _legacy_list(actor or {}, ("red_lines", "non_negotiables"), MAX_RED_LINES)
                goals = _legacy_list(actor or {}, ("goals", "objectives", "motivations"), MAX_GOALS)
            aliases = []
            if actor:
                raw_aliases = actor.get("aliases")
                if isinstance(raw_aliases, list):
                    aliases = _dedupe((_clean(a, 80) for a in raw_aliases), 6)
            incentives = {}
            for key in ("gains_if", "loses_if"):
                value = _clean(_cfg_get(cfg, key, ""), 220)
                if value:
                    incentives[key] = value
            row = {
                "agent_id": aid,
                "name": name,
                "agency_class": agency,
                "archetype": entity_archetype(actor) if actor else (
                    "collective" if agency == "public_collective" else "actor"),
                "capacity_per_round": default_capacity(agency),
                "outcome_power": _declared_outcome_power(actor, cfg if isinstance(cfg, dict) else {
                    "outcome_power": _cfg_get(cfg, "outcome_power")}),
                "posture": _clean(_cfg_get(cfg, "stance", ""), 60),
                "documented_plans": plans,
                "red_lines": red_lines,
                "goals": goals,
                "incentives": incentives,
                "aliases": aliases,
                "allies": [],
                "rivals": [],
            }
            rows.append(row)
            name_to_agent[normalize_name(name)] = aid
            for alias in aliases:
                name_to_agent.setdefault(normalize_name(alias), aid)
        except Exception:  # noqa: BLE001 — one malformed agent never drops the block
            continue
    block["actors"] = rows

    # relationships -------------------------------------------------------------------------
    rels: List[Dict[str, Any]] = []
    by_id = {r["agent_id"]: r for r in rows}
    try:
        for rel in extract_relationship_rows(actors_dict):
            s = name_to_agent.get(normalize_name(str(rel.get("source") or "")))
            t = name_to_agent.get(normalize_name(str(rel.get("target") or "")))
            if s is None or t is None or s == t:
                continue
            valence = relation_valence(rel)
            polarity = relation_polarity(rel)
            rels.append({
                "source_agent_id": s, "target_agent_id": t,
                "source": by_id[s]["name"], "target": by_id[t]["name"],
                "kind": str(rel.get("type") or "RELATES_TO").upper(),
                "valence": valence, "polarity": round(polarity, 4),
                "basis": _clean(rel.get("basis") or rel.get("evidence"), 160),
            })
            if valence == "allied":
                by_id[s]["allies"].append(by_id[t]["name"])
                by_id[t]["allies"].append(by_id[s]["name"])
            elif valence == "adversarial":
                by_id[s]["rivals"].append(by_id[t]["name"])
                by_id[t]["rivals"].append(by_id[s]["name"])
    except Exception:  # noqa: BLE001
        rels = []
    for row in rows:
        row["allies"] = _dedupe(row["allies"], 8)
        row["rivals"] = _dedupe(row["rivals"], 8)
    block["relationships"] = rels[:80]
    return block


def world_model_seed_summary(block: Optional[Dict[str, Any]]) -> str:
    if not isinstance(block, dict):
        return ""
    return (f"world model: {len(block.get('state_variables') or [])} variables, "
            f"{len(block.get('actors') or [])} actors, {len(block.get('relationships') or [])} relationships")
