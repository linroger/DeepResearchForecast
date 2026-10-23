"""Per-round world update: deterministic kernel step plus a bounded LLM arbiter (design §2.5).

Once every platform has delivered a round, the coordinator runs ONE world update:

1. ``deterministic_round_update`` — scheduled research events, the actors'
   structured decisions (capacity, commitments, coalition / antagonistic
   relationship nudges), due delayed effects (seeded RNG) and lapsed
   commitments.  Never fabricates numeric effects.
2. ``run_arbiter`` — a structured LLM proposal that resolves contested moves,
   moves state variables, emits emergent events, relationship changes and
   delayed effects.  Its output is validated against the variable registry and
   the cast (``validate_arbiter_update``) before any arbiter mutation. Malformed
   content gets one constrained correction; unrepaired/transport failures
   commit only the deterministic update with ``arbiter_status=invalid/failed``.
   Rejected attempts carry hashes and bounded validator paths, never bodies.
3. ``build_round_digest`` — the agent-facing "WHAT CHANGED LAST PERIOD" text
   (herding guard: no scenario shares).

``run_world_round`` composes the three for the runner; it is pure given
``(world, decisions, llm, rng)`` and does no I/O.
"""

from __future__ import annotations

import copy
import hashlib
import json
import logging
import math
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from ..utils.llm_errors import classify_llm_error, error_code, error_status
from .agent_decision import LANGUAGE_MISMATCH, AgentDecision
from .world_model import (FULFILLMENT_PREFIX, MAX_ACTION_RESOLUTIONS, RESPONSE_PREFIXES, WorldModel, _bound_lines, _text, format_value, is_kind_name_unit,
                          normalize_label, slugify)

logger = logging.getLogger(__name__)

WORLD_UPDATE_VERSION = "world-update/v1"
ARBITER_STATUSES = ("applied", "failed", "invalid", "skipped")
RESOLUTION_OUTCOMES = ("success", "partial", "blocked", "pending", "failed")
PRESSURE_WORDS = ("up", "down", "flat")

MAX_VARIABLE_CHANGES = 12
MAX_NEW_VARIABLES = 3
MAX_EVENTS = 8
MAX_RELATIONSHIP_CHANGES = 8
MAX_PENDING_EFFECTS = 6
MAX_RESOLUTIONS = MAX_ACTION_RESOLUTIONS
MAX_RED_LINE_CROSSINGS = 4
MAX_RED_LINE_ACTORS = 8
NARRATIVE_MAX_CHARS = 700
# 2026-10-21: 1100→12000（digest 在面板整段展示，不再截断；仍保留病理上限）
DIGEST_MAX_CHARS = 12000
ARBITER_ERROR_SNIPPET_CHARS = 200


def _action_bindings(world: WorldModel, round_num: int) -> List[Dict[str, Any]]:
    """Use registered actions and the kernel's exact delivery gate, never prose."""
    bindings = []
    for actor in world.actors.values():
        action = actor.last_action or {}
        if (action.get("round") != round_num or action.get("status") != "ok"
                or action.get("option_id") == "hold_position"):
            continue
        commitment_id = None
        action_round = None
        if str(action.get("option_id", "")).startswith(FULFILLMENT_PREFIX):
            commitment_id = action.get("commitment_id")
            if world.delivery_resolution_target(actor.agent_id, commitment_id, round_num, round_num) is None:
                continue
            action_round = round_num
        bindings.append({"actor": actor.name, "agent_id": actor.agent_id, "option_id": action.get("option_id"),
                         "commitment_id": commitment_id, "action_round": action_round})
    return bindings


def build_arbiter_contract(world: WorldModel, scenarios: Sequence[str] = ()) -> Dict[str, Any]:
    """The runtime's typed proposal contract, also supplied verbatim to the model.

    This JSON Schema subset is interpreted by _contract_problems below. Semantic
    checks still use validate_arbiter_update and the kernel's binding methods.
    Omitted sections mean no proposal for that section; present rows may never
    be silently filtered, truncated, coerced or rebound in the runtime path.
    """
    def obj(properties, required=()):
        return {"type": "object", "properties": properties, "required": list(required),
                "additionalProperties": False}

    def array(items, cap):
        return {"type": "array", "items": items, "maxItems": cap}

    def text(cap, *, nonempty=False):
        return {"type": "string", "maxLength": cap, "minLength": int(nonempty)}

    number = {"type": "number"}  # finite JSON numbers only; bool is never numeric
    kinds = {"numeric": number, "boolean": {"type": "boolean"},
             "categorical": text(160, nonempty=True), "text": text(160, nonempty=True)}
    actor = {"enum": [a.agent_id for a in world.actors.values()] +
             [a.name for a in world.actors.values() if world.resolve_actor(a.name, exact=True) == a.agent_id]}
    actors = array(actor, 6)
    rationale = text(200)

    def typed_change(var, extra):
        fields = {**extra, "variable_id": {"const": var.id}, "new_value": kinds[var.kind]}
        if var.kind == "numeric":
            fields["delta"] = number
        shape = obj(fields, ("variable_id",))
        shape["oneOf"] = [{"required": ["new_value"]}, {"required": ["delta"]}] if var.kind == "numeric" else [
            {"required": ["new_value"]}]
        return shape

    changes = [typed_change(v, {"caused_by": {"anyOf": [actor, {"type": "null"}]},
                                "rationale": rationale}) for v in world.variables.values()]
    effects_base = {"description": text(220, nonempty=True),
                    "due_periods": {"type": "integer", "minimum": 1, "maximum": 12},
                    "probability": {**number, "minimum": 0, "maximum": 1}, "targets": actors}
    effects = [obj({**effects_base, "variable_id": {"type": "null"}}, ("description",))]
    for var in world.variables.values():
        shape = typed_change(var, effects_base)
        shape["required"].append("description")
        effects.append(shape)
    new_variables = [obj({"name": text(140, nonempty=True), "kind": {"const": kind},
                          "value": value, "unit": text(24), "rationale": rationale},
                         ("name", "kind", "value")) for kind, value in kinds.items()]
    resolution = obj({"agent_id": {"type": "integer"}, "actor": actor,
                      "outcome": {"enum": list(RESOLUTION_OUTCOMES)},
                      "rationale": text(200, nonempty=True),
                      "commitment_id": {"type": ["string", "null"]},
                      "action_round": {"type": ["integer", "null"]}}, ("outcome",))
    resolution["anyOf"] = [{"required": ["agent_id"]}, {"required": ["actor"]}]
    contract = obj({
        "narrative": text(NARRATIVE_MAX_CHARS),
        "variable_changes": array({"anyOf": changes}, MAX_VARIABLE_CHANGES),
        "new_variables": array({"anyOf": new_variables}, MAX_NEW_VARIABLES),
        "events": array(obj({"description": text(320, nonempty=True),
                             "kind": {"enum": ["emergent", "consequence", "resolution"]},
                             "actors": actors, "targets": actors,
                             "variable_ids": array({"enum": list(world.variables)}, 6)}, ("description",)), MAX_EVENTS),
        "relationship_changes": array(obj({"source": actor, "target": actor,
                                           "direction": {"enum": ["closer", "farther", "flat", "further", "break",
                                                                  "ally", "stable", "unchanged"]},
                                           "rationale": rationale}, ("source", "target", "direction")), MAX_RELATIONSHIP_CHANGES),
        "pending_effects": array({"anyOf": effects}, MAX_PENDING_EFFECTS),
        "action_resolutions": array(resolution, MAX_RESOLUTIONS),
        "red_line_crossings": array(obj({"actor": actor, "by": actor, "red_line": text(140, nonempty=True),
                                         "rationale": rationale}, ("actor", "by", "red_line")), MAX_RED_LINE_CROSSINGS),
        "scenario_pressure": obj({str(s): {"enum": list(PRESSURE_WORDS)} for s in scenarios}),
    })
    contract["minProperties"] = 1
    contract["x-world-round"] = world.round
    contract["x-variable-registry"] = [{"variable_id": v.id, "kind": v.kind, "unit": v.unit, "value": v.value}
                                       for v in world.variables.values()]
    contract["x-action-bindings"] = [
        {**binding, "target_ids": (world.delivery_target_ids(binding["agent_id"],
            world.delivery_resolution_target(binding["agent_id"], binding["commitment_id"], world.round, world.round))
            if binding["commitment_id"] is not None else None)}
        for binding in _action_bindings(world, world.round)]
    contract["x-resolution-policy"] = (
        "At most one resolution per current binding. Copy commitment_id/action_round exactly; ordinary moves "
        "use null (or omit both). A delivery requires a nonempty rationale and the kernel's exact owned promise, "
        "round and stored targets. Omitted resolutions remain unverified.")
    return contract


def _contract_problems(value: Any, schema: Dict[str, Any], path: str = "$") -> List[str]:
    """Interpret only the schema keywords emitted above; never echo model values.

    Bounded path diagnostics are safe for correction prompts and round records.
    Dynamic/unknown property names are deliberately excluded from diagnostics.
    """
    def matches_type(kind):
        if kind == "number":
            try:
                return type(value) in (int, float) and math.isfinite(value)
            except OverflowError:
                return False
        return {"object": isinstance(value, dict), "array": isinstance(value, list),
                "string": isinstance(value, str), "integer": type(value) is int,
                "boolean": type(value) is bool, "null": value is None}.get(kind, False)

    kinds = schema.get("type")
    if kinds and not any(matches_type(kind) for kind in (kinds if isinstance(kinds, list) else [kinds])):
        return [f"{path}: expected {kinds} (numbers must be finite)"]
    choices = schema.get("enum", [schema["const"]] if "const" in schema else None)
    if choices is not None and not any(type(value) is type(choice) and value == choice for choice in choices):
        return [f"{path}: value outside current contract"]
    problems = []
    for keyword in ("anyOf", "oneOf"):
        if keyword in schema:
            branches = [_contract_problems(value, branch, path) for branch in schema[keyword]]
            matches = sum(not branch for branch in branches)
            if not matches or keyword == "oneOf" and matches != 1:
                best = min(branches, key=len, default=[])
                problems.extend(best or [f"{path}: requires exactly one value operation"])
    if isinstance(value, dict):
        fields = schema.get("properties", {})
        problems.extend(f"{path}.{key}: required" for key in schema.get("required", ()) if key not in value)
        if schema.get("additionalProperties") is False and any(key not in fields for key in value):
            problems.append(f"{path}: unknown fields")
        if len(value) < schema.get("minProperties", 0):
            problems.append(f"{path}: empty proposal")
        for key, field in fields.items():
            if key in value:
                problems.extend(_contract_problems(value[key], field, f"{path}.{key}"))
    if isinstance(value, list):
        cap = schema.get("maxItems", len(value))
        if len(value) > cap:
            problems.append(f"{path}: exceeds row cap {cap}")
        for index, entry in enumerate(value[:cap]):
            if "items" in schema:
                problems.extend(_contract_problems(entry, schema["items"], f"{path}[{index}]"))
    if isinstance(value, str) and (len(value.strip()) < schema.get("minLength", 0)
                                 or len(value) > schema.get("maxLength", len(value))):
        problems.append(f"{path}: invalid text length")
    if type(value) in (int, float) and (value < schema.get("minimum", value) or value > schema.get("maximum", value)):
        problems.append(f"{path}: outside allowed range")
    return [problem[:ARBITER_ERROR_SNIPPET_CHARS] for problem in problems[:12]]


def _decision_rows(decisions: Iterable[Any]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for d in decisions or []:
        if isinstance(d, AgentDecision):
            rows.append(d.to_dict())
        elif isinstance(d, dict):
            rows.append(d)
    return rows


# ---------------------------------------------------------------------------
# 1. deterministic step
# ---------------------------------------------------------------------------

def deterministic_round_update(world: WorldModel, round_num: int, period: Optional[Dict[str, Any]],
                               decisions: Iterable[Any], fired_events: Iterable[Dict[str, Any]],
                               rng: Any) -> Dict[str, Any]:
    """Apply everything that follows mechanically from the round's inputs."""
    if world.round != int(round_num) or (period and world.period != period):
        world.start_round(round_num, period)
    scheduled = world.register_scheduled_events(round_num, fired_events)
    rows = _decision_rows(decisions)
    lapsed = world.lapse_overdue_commitments(round_num)
    lapsed_offers = world.lapse_expired_interactions(round_num)   # OFFERS: unanswered offers expire first
    action_events = world.register_decisions(round_num, rows)
    fired = world.fire_due_effects(round_num, rng)
    # EXOGENOUS SHOCKS: rolled after the due effects, so a world without shocks draws exactly as before
    shocks = world.fire_shocks(round_num, rng)
    breaches = [e.description for e in world.events_in_round(round_num, ("breach",))]
    extra = {"shocks_fired": shocks} if world.shocks else {}
    return {
        "scheduled_events": [e.description for e in scheduled],
        "actions": [e.description for e in action_events if e.kind == "action"],
        "effects_fired": fired,
        "commitments_lapsed": [f"{c.get('actor')}: {c.get('description')}" for c in lapsed],
        "decisions": len(rows),
        # OFFERS: what the consent mechanics did this period (opened / answered / lapsed / breached)
        "offers_opened": [e.description for e in action_events if e.kind == "offer" and " made an " in e.description],
        "offers_answered": [e.description for e in action_events
                            if e.kind in ("offer", "agreement") and " made an " not in e.description],
        "offers_lapsed": [f"{world.actor_name(o.get('proposer'))} → {world.actor_name(o.get('recipient'))}: {o.get('terms')}"
                          for o in lapsed_offers],
        "breaches": breaches,
        **extra,
    }


# ---------------------------------------------------------------------------
# 2. arbiter
# ---------------------------------------------------------------------------

def build_arbiter_prompt(world: WorldModel, round_num: int, period: Optional[Dict[str, Any]],
                         decisions: Iterable[Any], deterministic: Dict[str, Any],
                         scenarios: Sequence[str], *, language: str = "",
                         max_variables: int = 24) -> str:
    """Prompt for the consequence arbiter.  Variable ids are listed so the model
    can reference them exactly; the scenario distribution is NOT included."""
    p = period or {}
    label = str(p.get("label") or f"period {round_num}")
    span = f"{p.get('period_start')} → {p.get('period_end')}" if p.get("period_end") else ""
    lines: List[str] = [
        "You are the consequence arbiter of a multi-actor forecasting simulation. Each round is one "
        "calendar period. Real-world actors have just made their moves for the period; your job is to "
        "resolve what the world does in response — honestly, conservatively and consistently with how "
        "institutions, markets and counterparties actually react. Do not invent dramatic outcomes; most "
        "moves have partial, delayed or contested effects. The world is reflexive: markets and counterparties "
        "react to announcements and to what they expect before measures take effect, and they weigh each "
        "actor's word by its track record — threats and promises from actors who kept their commitments move "
        "others more than those from actors who broke them. Widely shared expectations can become "
        "self-fulfilling (expected shortages trigger stockpiling) or self-defeating (an expected crackdown is "
        "pre-empted); reflect that only where this period's moves and facts support it.",
        f"Forecast question: {world.question or '(not stated)'}",
        f"Period: {label}" + (f" ({span})" if span else "") + f" — round {round_num}"
        + (f"; forecast horizon {world.horizon_date}" if world.horizon_date else ""),
        "",
        "## World facts (variable_id: value)",
    ]
    vars_sorted = sorted(world.variables.values(),
                         key=lambda v: (-(v.history[-1].get("round", 0) if v.history else 0), v.name))
    for v in vars_sorted[:max_variables]:
        # A numeric-sounding label can also describe a qualitative trend. Expose
        # the registry type so the arbiter never has to infer it from the name.
        tail = f" [{v.kind}]"
        path = _recent_path(v)
        lines.append(f"- {v.id}: {v.name} = {format_value(v.value, v.unit)}{tail}" + (f" (path: {path})" if path else ""))
    if not world.variables:
        lines.append("- (no tracked variables yet — you may create up to 3 that the moves clearly affect)")
    lines.append("")
    lines.append("## Moves this period")
    rows = _decision_rows(decisions)
    moved = 0
    for d in rows:
        if d.get("status") != "ok" or (d.get("option") or {}).get("id") == "hold_position":
            continue
        opt = d.get("option") or {}
        tgt = f" → {', '.join(d.get('targets') or [])}" if d.get("targets") else ""
        stmt = f' Statement: "{_text(d.get("public_statement"), 240)}"' if d.get("public_statement") else ""
        aid = world.resolve_actor(d.get("agent_id"))
        record = world.track_record_text(aid) if aid is not None else ""
        lines.append(f"- {d.get('actor_name')}: {opt.get('label')} (kind={opt.get('kind')}, "
                     f"magnitude={d.get('magnitude')}){tgt}.{stmt}"
                     + (f" Track record: {record}." if record else ""))
        moved += 1
    if not moved:
        lines.append("- (no actor made a consequential move; the world drifts on its own momentum)")
    bindings = _action_bindings(world, round_num)
    attempts = [(world.actors[b["agent_id"]], world.actors[b["agent_id"]].last_action)
                for b in bindings if b["commitment_id"] is not None]
    lines.extend(["", "## Action resolution bindings",
                  "Resolve only the registered moves listed below. Copy agent_id, commitment_id and action_round "
                  "without inventing or inferring bindings. Do not resolve held, invalid or rejected moves, "
                  "including rejected delivery attempts. For an ordinary move use commitment_id=null and "
                  "action_round=null; an ordinary success never fulfils a promise. An empty string is not null."])
    lines.extend("- " + json.dumps(binding, ensure_ascii=False) for binding in bindings)
    if not bindings:
        lines.append("- (none; return action_resolutions: [])")
    if attempts:
        lines.extend(["", "## Specific commitment delivery attempts (not yet fulfilled)",
                      "Assess whether this exact promise was actually delivered in this period. Unrelated actions, "
                      "new agreements, announcements and partial progress are not fulfilment. Use success only "
                      "for full delivery; otherwise use partial, pending, blocked or failed. Return the exact "
                      "commitment_id AND action_round in that actor's resolution, with a concrete delivery rationale."])
        for actor, action in attempts:
            lines.append(f"- actor={actor.name}; commitment_id={action['commitment_id']}; action_round={round_num}; "
                         f"promise={action.get('commitment_description')}; counterparty={', '.join(action.get('targets') or []) or '(self)'}")
    expectations = [(a.name, e) for a in world.actors.values() for e in a.expectations
                    if int(e.get("round") or 0) == int(round_num)]
    if expectations:
        lines.append("")
        lines.append("## Expectations in play (what this period's movers expect others to do next)")
        lines.extend(f"- {name} expects {e.get('about')}: {e.get('reaction')}" for name, e in expectations[:8])
    stakes = _red_lines_at_stake(world, rows)
    if stakes:
        lines.append("")
        lines.append("## Red lines at stake (documented by each actor; report a crossing only when a move this "
                     "period clearly crosses one)")
        lines.extend(f"- {name}: " + "; ".join(red) for name, red in stakes)
    shocks = deterministic.get("shocks_fired") or []
    if deterministic.get("scheduled_events") or shocks:
        lines.append("")
        lines.append("## Confirmed events this period")
        lines.extend(f"- {e}" for e in (deterministic.get("scheduled_events") or [])[:10])
        lines.extend(f"- {_shock_line(s)}" for s in shocks[:6])
    mech: List[str] = []
    for fx in deterministic.get("effects_fired") or []:
        mech.append(fx.get("description", ""))
    mech.extend(deterministic.get("commitments_lapsed") or [])
    if mech:
        lines.append("")
        lines.append("## Already applied mechanically")
        lines.extend(f"- {m}" for m in mech[:10] if m)
    deals = (list(deterministic.get("offers_opened") or []) + list(deterministic.get("offers_answered") or [])
             + [f"Lapsed: {o}" for o in (deterministic.get("offers_lapsed") or [])]
             + list(deterministic.get("breaches") or []))
    open_offers = [it for it in world.interactions.values() if it.is_open()]
    if deals or open_offers:
        lines.append("")
        lines.append("## Offers and agreements (settled only by the parties' answers — never assume consent)")
        lines.extend(f"- {d}" for d in deals[:8])
        lines.extend(f"- Still open: {world.actor_name(it.proposer)} → {world.actor_name(it.recipient)} "
                     f"[{it.id}]: {it.terms}" for it in open_offers[:6])
    cast = ", ".join(a.name for a in list(world.actors.values())[:30])
    sc = "; ".join(str(s) for s in scenarios) or "(none)"
    lang = f" Write narrative and descriptions in {language}." if language else ""
    lines += [
        "",
        "## Your task",
        "Resolve the period. Return ONLY JSON with these keys:",
        '- "narrative": 2-4 sentences on what actually changed and why (≤600 chars).',
        '- "variable_changes": [{"variable_id": "<id from the list>", "new_value": <value matching the listed kind> OR '
        '"delta": <number>, "caused_by": "<cast name>" | null, "rationale": "..."}] — only variables the '
        "moves/events plausibly affect; small, defensible moves; leave the rest untouched. For [numeric], "
        "new_value or delta must be a finite JSON number in the listed unit, never prose, a direction, "
        "a boolean or a number with unit text; omit the change if no defensible number can be given. "
        "For [boolean], use true/false; for [categorical] or [text], use a string new_value. "
        "delta is only for numeric variables. Name caused_by "
        "only when a mover's own move this period sets the new value (an announced tariff, rate, quota or "
        f"price it states): a stated figure takes effect in full{_clamp_rule(world)}.",
        '- "new_variables": [{"name": "...", "value": ..., "unit": "...", "kind": "numeric|categorical|boolean|text", '
        '"rationale": "..."}] — at most 3, only when a move creates a new fact the world must now track.',
        '- "events": [{"description": "...", "kind": "emergent|consequence|resolution", "actors": ["<cast name>"], '
        '"targets": ["<cast name>"]}] — market, counterpart, public or institutional reactions (≤6).',
        '- "relationship_changes": [{"source": "<cast name>", "target": "<cast name>", "direction": "closer|farther|flat", '
        '"rationale": "..."}].',
        '- "pending_effects": [{"description": "...", "due_periods": 1-12, "variable_id": "<id or null>", '
        '"new_value": ... OR "delta": ..., "probability": 0-1}] — delayed consequences that land later; '
        'the same variable kind and finite-number rules apply.',
        '- "action_resolutions": [{"agent_id": <integer from resolution bindings>, '
        '"outcome": "success|partial|blocked|pending|failed", "rationale": "...", '
        '"commitment_id": <exact delivery id string or null from bindings>, '
        '"action_round": <exact delivery round integer or null from bindings>}] — at most one per listed '
        'move, none for unlisted actors; omit unsupported resolutions. Use the two nulls for ordinary moves. For a listed delivery '
        'attempt copy its exact id and round and give concrete evidence of whether that promise was delivered.',
        '- "red_line_crossings": [{"actor": "<whose red line>", "by": "<cast name whose move crossed it>", '
        '"red_line": "<the red line as listed>", "rationale": "..."}] — only for a listed red line that a move '
        "this period clearly crossed; usually none.",
        '- "scenario_pressure": {"<candidate scenario>": "up|down|flat"} — direction only, no numbers.',
        f"Cast: {cast}. Candidate scenarios: {sc}.{lang}",
    ]
    lines.extend(["", "## Machine-readable proposal contract",
                  "This is the runtime validator's current-world contract. All supplied fields must pass together. "
                  "Copy exact current action bindings; omit a section only when proposing no change there.",
                  json.dumps(build_arbiter_contract(world, scenarios), ensure_ascii=False, separators=(",", ":"))])
    return "\n".join(lines)


def _shock_line(shock: Dict[str, Any]) -> str:
    """EXOGENOUS SHOCKS: one confirmed-event line — the event, its documented base rate and source, what
    the kernel already applied, and the documented directions the arbiter must size."""
    line = (f"Exogenous shock: {_text(shock.get('event'), 200)} (a researched risk that materialised this period; "
            f"documented base rate {_text(shock.get('base_rate'), 80) or 'unstated'}, source: "
            f"{_text(shock.get('source'), 120) or 'unstated'}).")
    applied = [f"{c.get('name')} {format_value(c.get('from'), c.get('unit') or '')} → "
               f"{format_value(c.get('to'), c.get('unit') or '')}" for c in shock.get("variables_changed") or []]
    if applied:
        line += " Already applied within the per-period limit: " + "; ".join(applied[:4]) + "."
    if shock.get("to_size"):
        line += " Documented direction, size it: " + "; ".join(str(x) for x in shock["to_size"][:4]) + "."
    if shock.get("affects"):
        line += " Hits: " + ", ".join(str(x) for x in shock["affects"][:6]) + "."
    return line


def _clamp_rule(world: WorldModel) -> str:
    """The per-period bound the kernel applies to every change that was not announced."""
    ratio = world.change_ratio()
    if not ratio:
        return ""
    return f"; every other change is limited to about ±{float(ratio) * 100:g}% of the current value per period"


def _recent_path(var: Any, periods: int = 4) -> str:
    """TRENDS: a numeric fact's values at the end of its last ``periods`` recorded rounds, oldest
    first ("20% → 30% → 45%"); "" until it has changed at least once."""
    if getattr(var, "kind", "") != "numeric":
        return ""
    by_round = var.values_by_round()
    values = [by_round[r] for r in sorted(by_round)][-periods:]
    if len(values) < 2:
        return ""
    return " → ".join(format_value(v, var.unit) for v in values)


def _red_lines_at_stake(world: WorldModel, rows: List[Dict[str, Any]]) -> List[Tuple[str, List[str]]]:
    """RED LINES the arbiter should know: actors this period's moves targeted first, then the
    rest of the cast with documented red lines (bounded)."""
    targeted: List[int] = []
    for d in rows:
        if d.get("status") != "ok" or (d.get("option") or {}).get("id") == "hold_position":
            continue
        for t in d.get("targets") or []:
            aid = world.resolve_actor(t)
            if aid is not None and aid not in targeted:
                targeted.append(aid)
    ordered = targeted + [aid for aid in world.actors if aid not in targeted]
    out: List[Tuple[str, List[str]]] = []
    for aid in ordered:
        actor = world.actors.get(aid)
        if actor is not None and actor.red_lines:
            out.append((actor.name, [_text(x, 140) for x in actor.red_lines[:2]]))
        if len(out) >= MAX_RED_LINE_ACTORS:
            break
    return out


def _num(value: Any) -> Optional[float]:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        out = float(value)
        return out if math.isfinite(out) else None
    try:
        out = float(str(value).replace(",", "").replace("%", "").strip())
        return out if math.isfinite(out) else None
    except (TypeError, ValueError):
        return None


# 2026-10-22: 布尔变量的确定性词表（裁决短语 → 布尔）。保守集合：明确决断措辞才归类；
# "pending/unresolved/stalled/not yet" 归 False（判定日语义 = 届时未成立）。
_BOOL_TRUE_WORDS = {
    "true", "yes", "是", "agreed", "agree", "deal", "deal reached", "reached",
    "confirmed", "confirmed.", "signed", "in force", "done", "approved",
    "agreed in principle", "yes - agreed", "yes, agreed",
}
_BOOL_FALSE_WORDS = {
    "false", "no", "否", "not agreed", "no agreement", "not reached", "rejected",
    "unsigned", "off", "stalled", "pending", "unresolved", "no deal", "not yet",
    "not yet agreed", "pending agenda confirmation", "no", "broken", "collapsed",
}


def validate_arbiter_update(raw: Any, world: WorldModel, scenarios: Sequence[str] = (), *,
                            strict: bool = False) -> Tuple[Dict[str, Any], List[str]]:
    """Bound and type-check the arbiter payload; returns ``(update, problems)``.

    Unknown variable ids, unknown actors, bad kinds and oversized lists are
    dropped with a recorded problem.  The returned update is safe to hand to
    ``WorldModel.apply_arbiter_update`` (which additionally clamps numeric moves).
    ``strict=True`` is the runtime transaction gate. The default remains the
    historical filtering helper for callers inspecting legacy artifacts.
    """
    if strict:
        contract = build_arbiter_contract(world, scenarios)
        problems = _contract_problems(raw, contract)
        if problems:
            return {}, problems
        bindings = {b["agent_id"]: b for b in contract["x-action-bindings"]}
        resolved = set()
        for index, row in enumerate(raw.get("action_resolutions", [])):
            aid, _ = world.resolution_actor(row)
            binding = bindings.get(aid)
            if (binding is None or aid in resolved
                    or row.get("commitment_id") != binding["commitment_id"]
                    or type(row.get("action_round")) is not type(binding["action_round"])
                    or row.get("action_round") != binding["action_round"]):
                problems.append(f"$.action_resolutions[{index}]: not an exact current action binding")
            resolved.add(aid)
        variable_ids = set(world.variables)
        for index, row in enumerate(raw.get("new_variables", [])):
            vid = slugify(row["name"])
            if vid in variable_ids:
                problems.append(f"$.new_variables[{index}].name: variable identity already exists")
            variable_ids.add(vid)
        for index, row in enumerate(raw.get("red_line_crossings", [])):
            if world.resolve_actor(row["by"], exact=True) not in bindings:
                problems.append(f"$.red_line_crossings[{index}].by: no current registered move")
        if problems:
            return {}, problems[:12]
        update, legacy_problems = validate_arbiter_update(raw, world, scenarios)
        if legacy_problems:
            # Legacy diagnostics include candidate strings. Expose only fixed,
            # bounded section paths at the runtime boundary.
            return {}, ["$: semantic validation rejected proposal"]
        # The legacy helper renders non-numeric delayed values as text. Preserve
        # the already validated JSON type for the kernel, especially false.
        for effect, original in zip(update["pending_effects"], raw.get("pending_effects", [])):
            if "new_value" in original:
                effect["new_value"] = original["new_value"]
        # Legacy canonicalization uses display names and fuzzy scenario matching.
        # Typed current-world claims must retain their exact identities when the
        # kernel resolves them again, particularly with duplicate actor names or
        # scenario labels containing another label.
        for field, keys in (("relationship_changes", ("source", "target")),
                            ("red_line_crossings", ("actor", "by"))):
            for output, original in zip(update[field], raw.get(field, [])):
                for key in keys:
                    output[key] = world.resolve_actor(original[key], exact=True)
        for output, original in zip(update["variable_changes"], raw.get("variable_changes", [])):
            if original.get("caused_by") is not None:
                output["caused_by"] = world.resolve_actor(original["caused_by"], exact=True)
        update["scenario_pressure"] = dict(raw.get("scenario_pressure", {}))
        return update, []
    problems: List[str] = []
    update: Dict[str, Any] = {"narrative": "", "variable_changes": [], "new_variables": [], "events": [],
                              "relationship_changes": [], "pending_effects": [], "action_resolutions": [],
                              "red_line_crossings": [], "scenario_pressure": {}}
    if not isinstance(raw, dict):
        return update, ["payload is not an object"]
    update["narrative"] = _text(raw.get("narrative"), NARRATIVE_MAX_CHARS)
    changes = raw.get("variable_changes")
    if isinstance(changes, list):
        changed_ids: set = set()
        for ch in changes[:MAX_VARIABLE_CHANGES]:
            if not isinstance(ch, dict):
                continue
            vid = str(ch.get("variable_id") or ch.get("id") or "").strip()
            var = world.variables.get(vid)
            if var is None:
                # tolerate the model naming the variable instead of its id
                wanted = normalize_label(vid)
                var = next((v for v in world.variables.values() if normalize_label(v.name) == wanted), None)
            if var is None:
                problems.append(f"unknown variable '{vid}'")
                continue
            if var.id in changed_ids:
                problems.append(f"duplicate change for '{var.id}'")
                continue
            row: Dict[str, Any] = {"variable_id": var.id, "rationale": _text(ch.get("rationale"), 200)}
            cause = ch.get("caused_by")
            if cause not in (None, "") and var.kind == "numeric":
                # ANNOUNCED SETTINGS: the kernel lifts the clamp only when this actor's own move
                # this period stated the figure (WorldModel._announced_by); here it must be cast
                cause_id = world.resolve_actor(cause)
                if cause_id is None:
                    problems.append(f"unknown actor '{_text(cause, 80)}' in caused_by")
                else:
                    row["caused_by"] = world.actor_name(cause_id)
            if var.kind == "numeric":
                nv, dl = _num(ch.get("new_value")), _num(ch.get("delta"))
                if nv is None and dl is None:
                    problems.append(f"non-numeric change for numeric variable '{var.id}'")
                    continue
                if nv is not None:
                    row["new_value"] = nv
                else:
                    row["delta"] = dl
            elif var.kind == "boolean":
                val = ch.get("new_value")
                if not isinstance(val, bool):
                    low = _text(val, 40).casefold().strip(" .!?。，")
                    # 2026-10-22（pipe_0827b81a9998 round7）：仲裁常用短语而非裸布尔
                    # （"agreed"、"pending agenda confirmation"）→ 扩充词表确定性归类；
                    # 词表外的自由文本仍照旧拒绝（那是 categorical 语义，强转会歪曲事实）。
                    if low in _BOOL_TRUE_WORDS:
                        val = True
                    elif low in _BOOL_FALSE_WORDS:
                        val = False
                    else:
                        problems.append(f"non-boolean change for '{var.id}'")
                        continue
                row["new_value"] = val
            else:
                val = _text(ch.get("new_value"), 160)
                if not val:
                    problems.append(f"empty value for '{var.id}'")
                    continue
                row["new_value"] = val
            update["variable_changes"].append(row)
            changed_ids.add(var.id)
    new_vars = raw.get("new_variables")
    if isinstance(new_vars, list):
        for nv in new_vars[:MAX_NEW_VARIABLES]:
            if not isinstance(nv, dict) or not _text(nv.get("name"), 140):
                continue
            raw_kind = _text(nv.get("kind"), 16).casefold()
            kind = raw_kind or "numeric"
            if kind not in ("numeric", "categorical", "boolean", "text"):
                kind = "text"
            if kind == "numeric" and _num(nv.get("value")) is None:
                kind = "text"
            unit = _text(nv.get("unit"), 24)
            # a unit belongs to numeric facts only; models echo the kind ("boolean", "date")
            # into the unit field, which would otherwise render as "yes boolean"
            if kind != "numeric" or unit.casefold() in (kind, raw_kind) or is_kind_name_unit(unit):
                unit = ""
            update["new_variables"].append({"name": _text(nv["name"], 140), "value": nv.get("value"),
                                            "unit": unit, "kind": kind,
                                            "rationale": _text(nv.get("rationale"), 200)})
        if len(new_vars) > MAX_NEW_VARIABLES:
            problems.append(f"{len(new_vars) - MAX_NEW_VARIABLES} new variables dropped (cap {MAX_NEW_VARIABLES})")

    def _names(values: Any) -> List[str]:
        out: List[str] = []
        if isinstance(values, list):
            for v in values[:6]:
                aid = world.resolve_actor(v)
                if aid is not None:
                    name = world.actor_name(aid)
                    if name not in out:
                        out.append(name)
                elif _text(v, 80):
                    problems.append(f"unknown actor '{_text(v, 80)}'")
        return out

    events = raw.get("events")
    if isinstance(events, list):
        for ev in events[:MAX_EVENTS]:
            if not isinstance(ev, dict) or not _text(ev.get("description"), 320):
                continue
            kind = _text(ev.get("kind"), 16).casefold()
            if kind not in ("emergent", "consequence", "resolution"):
                kind = "emergent"
            var_ids = ev.get("variable_ids")
            if not isinstance(var_ids, list):
                var_ids = []
            update["events"].append({"description": _text(ev["description"], 320), "kind": kind,
                                     "actors": _names(ev.get("actors")), "targets": _names(ev.get("targets")),
                                     "variable_ids": [str(x) for x in var_ids
                                                      if str(x) in world.variables][:6]})
    rels = raw.get("relationship_changes")
    if isinstance(rels, list):
        for rc in rels[:MAX_RELATIONSHIP_CHANGES]:
            if not isinstance(rc, dict):
                continue
            a, b = world.resolve_actor(rc.get("source")), world.resolve_actor(rc.get("target"))
            direction = _text(rc.get("direction"), 16).casefold()
            if a is None or b is None or a == b:
                problems.append("relationship change with unknown or identical actors")
                continue
            # 2026-10-21：flat/stable/unchanged 是合法语义（同提示词的 PRESSURE_WORDS
            # 早在六行之外就背书了 flat）——此前被当 unknown 丢弃，裁决理由文本随之丢失。
            if direction not in ("closer", "farther", "further", "break", "ally",
                                 "flat", "stable", "unchanged"):
                problems.append(f"unknown relationship direction '{direction}'")
                continue
            update["relationship_changes"].append({"source": world.actor_name(a), "target": world.actor_name(b),
                                                   "direction": direction, "rationale": _text(rc.get("rationale"), 200)})
    effects = raw.get("pending_effects")
    if isinstance(effects, list):
        for fx in effects[:MAX_PENDING_EFFECTS]:
            if not isinstance(fx, dict) or not _text(fx.get("description"), 220):
                continue
            try:
                due = max(1, min(12, int(fx.get("due_periods", 1) or 1)))
            except (TypeError, ValueError):
                due = 1
            vid = fx.get("variable_id")
            vid = str(vid) if vid and str(vid) in world.variables else None
            row = {"description": _text(fx["description"], 220), "due_periods": due, "variable_id": vid,
                   "targets": _names(fx.get("targets"))}
            prob = _num(fx.get("probability"))
            row["probability"] = max(0.0, min(1.0, prob)) if prob is not None else 1.0
            if vid is not None:
                var = world.variables[vid]
                if var.kind == "numeric":
                    nv, dl = _num(fx.get("new_value")), _num(fx.get("delta"))
                    if nv is not None:
                        row["new_value"] = nv
                    elif dl is not None:
                        row["delta"] = dl
                    else:
                        row["variable_id"] = None
                else:
                    row["new_value"] = _text(fx.get("new_value"), 160) or None
                    if row["new_value"] is None:
                        row["variable_id"] = None
            update["pending_effects"].append(row)
    res = raw.get("action_resolutions")
    if isinstance(res, list):
        if len(res) > MAX_RESOLUTIONS:
            problems.append("too many action resolutions")
            res = []
        # Duplicates must be detected before filtering malformed outcomes or
        # truncating: conflicting attestations cannot become a single success.
        counts: Dict[int, int] = {}
        for r in res:
            if isinstance(r, dict):
                _, implicated = world.resolution_actor(r)
                for aid in implicated:
                    counts[aid] = counts.get(aid, 0) + 1
        for r in res:
            if not isinstance(r, dict):
                continue
            aid, _ = world.resolution_actor(r)
            outcome = _text(r.get("outcome"), 16).casefold()
            if aid is None or outcome not in RESOLUTION_OUTCOMES:
                problems.append("resolution with unknown actor or outcome")
                continue
            if counts[aid] != 1:
                problems.append("duplicate actor resolutions")
                continue
            row = {"actor": world.actor_name(aid), "outcome": outcome, "rationale": _text(r.get("rationale"), 200)}
            if world.resolve_actor(row["actor"], exact=True) != aid:
                # Keep a valid numeric/alias identity when display names collide;
                # canonicalization must not turn it into an ambiguous claim.
                row["actor"] = aid
            action = world.actors[aid].last_action or {}
            if str(action.get("option_id", "")).startswith(FULFILLMENT_PREFIX) or r.get("commitment_id") is not None:
                if (world.delivery_resolution_target(aid, r.get("commitment_id"), world.round, r.get("action_round")) is None
                        or not isinstance(r.get("rationale"), str) or not row["rationale"]):
                    problems.append("unbound commitment delivery resolution")
                    continue
                row.update(commitment_id=r["commitment_id"], action_round=r["action_round"])
            update["action_resolutions"].append(row)
    crossings = raw.get("red_line_crossings")
    if isinstance(crossings, list):
        for rl in crossings[:MAX_RED_LINE_CROSSINGS]:
            if not isinstance(rl, dict):
                continue
            aid, bid = world.resolve_actor(rl.get("actor")), world.resolve_actor(rl.get("by"))
            line = world.match_red_line(aid, rl.get("red_line")) if aid is not None else None
            if aid is None or bid is None or aid == bid or line is None:
                problems.append("red line crossing with unknown actors or an unlisted red line")
                continue
            update["red_line_crossings"].append({"actor": world.actor_name(aid), "by": world.actor_name(bid),
                                                 "red_line": line, "rationale": _text(rl.get("rationale"), 200)})
    pressure = raw.get("scenario_pressure")
    if isinstance(pressure, dict):
        for k, v in pressure.items():
            word = _text(v, 8).casefold()
            if word not in PRESSURE_WORDS:
                continue
            key = normalize_label(k)
            for s in scenarios:
                if normalize_label(s) == key or (len(key) >= 4 and key in normalize_label(s)):
                    update["scenario_pressure"][str(s)] = word
                    break
    return update, problems


def run_arbiter(llm: Any, world: WorldModel, round_num: int, period: Optional[Dict[str, Any]],
                decisions: Iterable[Any], deterministic: Dict[str, Any], scenarios: Sequence[str], *,
                language: str = "", temperature: float = 0.3, max_tokens: int = 2200,
                attempts: Optional[List[Dict[str, Any]]] = None,
                ) -> Tuple[str, Dict[str, Any], List[str]]:
    """Validate a whole proposal, with at most one constrained content correction.

    Production uses chat + strict JSON decoding so chat_json's internal content
    retry cannot multiply this budget. Transport/fallback stays inside the LLM
    client; an exception never causes an additional arbiter call. JSON-only
    legacy clients remain supported. No rejected body enters logs or feedback.
    """
    if llm is None:
        return "skipped", {}, ["no llm"]
    prompt = build_arbiter_prompt(world, round_num, period, decisions, deterministic, scenarios, language=language)
    source_hash = _arbiter_hash(prompt)
    messages = [{"role": "user", "content": prompt}]
    receipts = attempts if attempts is not None else []
    for attempt in range(2):
        try:
            # LLMClient exposes this parser as well as chat. Avoid importing or
            # constructing a provider client just to identify its capability.
            if callable(getattr(llm, "_parse_json_response", None)) and callable(getattr(llm, "chat", None)):
                candidate = llm.chat(messages=messages, temperature=temperature if not attempt else 0.0,
                                     max_tokens=max_tokens, response_format={"type": "json_object"})
            else:
                candidate = llm.chat_json(messages=messages, temperature=temperature if not attempt else 0.0,
                                          max_tokens=max_tokens)
        except Exception as exc:  # noqa: BLE001 — preserve deterministic round on transport failure
            detail = _arbiter_error(exc)
            receipts.append({"attempt": attempt + 1, "source_hash": source_hash, "status": "failed",
                             "problems": [detail]})
            logger.warning("world arbiter failed in round %s: %s", round_num, detail)
            return "failed", {}, [f"llm error: {detail}"]
        receipt = {"attempt": attempt + 1, "source_hash": source_hash,
                   "candidate_hash": _arbiter_hash(candidate)}
        try:
            raw = json.loads(candidate, object_pairs_hook=_unique_json_object) if isinstance(candidate, str) else candidate
        except (ValueError, TypeError, RecursionError):
            update, problems = {}, ["$: malformed JSON object"]
        else:
            try:
                update, problems = validate_arbiter_update(raw, world, scenarios, strict=True)
            except Exception as exc:  # noqa: BLE001 — do not expose candidate-derived exception text
                receipt.update(status="invalid", problems=[f"validation error: {type(exc).__name__}"])
                receipts.append(receipt)
                return "invalid", {}, receipt["problems"]
        receipt.update(status="invalid" if problems else "valid", problems=problems[:12])
        receipts.append(receipt)
        if not problems:
            return "applied", update, []
        logger.warning("world arbiter rejected round %s attempt %s: %s", round_num, attempt + 1,
                       json.dumps(receipt, ensure_ascii=True))
        if not attempt:
            messages = [messages[0], {"role": "user", "content":
                "Your proposal was rejected before any arbiter mutation. Return one complete corrected JSON "
                "proposal using the original current-world contract and bindings. Fix only defensible typed "
                "facts; omit unsupported changes. Never convert prose into a number or infer promise fulfilment. "
                "This is the only correction opportunity. Rejected candidate hash: " + receipt["candidate_hash"]
                + ". Validator paths: " + json.dumps(problems[:12], ensure_ascii=True)}]
    return "invalid", {}, problems[:12]


def _arbiter_hash(value: Any) -> str:
    if not isinstance(value, str):
        try:
            value = json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
        except (TypeError, ValueError, RecursionError):
            # A non-JSON legacy client result has no serializable body. Do not
            # call repr/str on arbitrary provider objects in a failure record.
            value = "non-JSON candidate type:" + type(value).__name__
    return hashlib.sha256(value.encode("utf-8", errors="backslashreplace")).hexdigest()


def _unique_json_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON field")
        result[key] = value
    return result


def _arbiter_error(exc: BaseException) -> str:
    """Retain error classification, never messages, notes or raw provider bodies."""
    parts = [type(exc).__name__]
    status = error_status(exc)
    if status is not None:
        parts.append(f"HTTP {status}")
    code = error_code(exc)
    if code.isdigit() and len(code) <= 6:
        parts.append(f"provider code {code}")
    kind = classify_llm_error(exc)
    if kind:
        parts.append(kind)
    return "; ".join(parts)


# ---------------------------------------------------------------------------
# 3. digest and headline
# ---------------------------------------------------------------------------

def build_round_digest(world: WorldModel, round_num: int, previous: Optional[Dict[str, Any]],
                       decisions: Iterable[Any], narrative: str = "", *,
                       max_chars: int = DIGEST_MAX_CHARS) -> str:
    """Agent-facing WHAT CHANGED LAST PERIOD text (no scenario shares, I-1)."""
    lines: List[str] = []
    if narrative:
        lines.append(_text(narrative, 4000))
    rows = _decision_rows(decisions)
    moves = [d for d in rows if d.get("status") == "ok" and (d.get("option") or {}).get("id") != "hold_position"]
    if moves:
        lines.append("Moves:")
        for d in moves[:8]:
            opt = d.get("option") or {}
            tgt = f" (→ {', '.join(d.get('targets') or [])})" if d.get("targets") else ""
            stmt = f': "{_text(d.get("public_statement"), 2400)}"' if d.get("public_statement") else ""
            lines.append(f"- {d.get('actor_name')}: {opt.get('label')}{tgt}{stmt}")
    holders = [d.get("actor_name") for d in rows if d.get("status") == "ok"
               and (d.get("option") or {}).get("id") == "hold_position"]
    if holders:
        lines.append("Held position: " + ", ".join(str(h) for h in holders[:8]))
    diff = world.diff(previous) if previous is not None else {"variables_changed": [], "variables_added": [],
                                                              "relationships_changed": []}
    if diff["variables_changed"] or diff["variables_added"]:
        lines.append("Facts that changed:")
        for ch in diff["variables_changed"][:8]:
            lines.append(f"- {ch['name']}: {format_value(ch['from'], ch['unit'])} → {format_value(ch['to'], ch['unit'])}")
        for nv in diff["variables_added"][:4]:
            lines.append(f"- New: {nv['name']} = {format_value(nv['value'], nv['unit'])}")
    consequences = world.events_in_round(round_num, ("scheduled", "consequence", "emergent", "resolution",
                                                     "red_line"))
    if consequences:
        lines.append("Events and consequences:")
        lines.extend(f"- {e.description}" for e in consequences[:8])
    deals = world.events_in_round(round_num, ("offer", "agreement", "breach"))
    if deals:
        lines.append("Offers and agreements:")
        lines.extend(f"- {e.description}" for e in deals[:8])
    if diff["relationships_changed"]:
        lines.append("Alliances and rivalries:")
        for rc in diff["relationships_changed"][:6]:
            direction = f" ({rc['direction']})" if rc.get("direction") else ""
            lines.append(f"- {rc['source']} — {rc['target']}: {rc['to']}{direction}")
    return _bound_lines(lines, max_chars)


def behaviour_metrics(world: WorldModel, round_num: int, decisions: Iterable[Any]) -> Dict[str, Any]:
    """Deterministic responsiveness diagnostics for one round (ported, in spirit, from the
    world-v1 behaviour evaluation's "consequence response" criterion — without an LLM judge).

    A move is *responsive* when it answers an offer, or when its public statement / rationale
    names a fact that changed last period or an actor that moved last period.  Round 1 has no
    prior period and scores nothing.  This is a textual diagnostic, not a realism verdict."""
    rows = _decision_rows(decisions)
    prev = int(round_num) - 1
    moves = [d for d in rows if d.get("status") == "ok" and (d.get("option") or {}).get("id") != "hold_position"]
    out: Dict[str, Any] = {"moves": len(moves), "responsive_moves": 0, "offers_answered": 0,
                           "responsive_share": None, "signals_last_period": 0,
                           "expectations_checked": 0, "expectations_reacted": 0}
    if prev < 1:
        return out
    # EXPECTATIONS: of the reactions actors expected after last period's moves, how many came
    for aid in world.actors:
        for check in world.expectation_checks(aid, int(round_num)):
            out["expectations_checked"] += 1
            out["expectations_reacted"] += int(bool(check["reacted"]))
    changed = [v.name.casefold() for v in world.variables.values()
               if any(isinstance(h, dict) and int(h.get("round") or 0) == prev for h in v.history)]
    movers = set()
    for e in world.events_in_round(prev, ("action", "offer", "agreement", "breach", "consequence", "emergent")):
        for name in e.actors[:2]:
            movers.add(name.casefold())
    out["signals_last_period"] = len(changed) + len(movers)
    for d in moves:
        option_id = str((d.get("option") or {}).get("id") or "")
        text = f"{d.get('private_rationale') or ''} {d.get('public_statement') or ''}".casefold()
        me = str(d.get("actor_name") or "").casefold()
        if option_id.startswith(RESPONSE_PREFIXES):
            out["offers_answered"] += 1
            out["responsive_moves"] += 1
        elif any(name and name in text for name in changed) or any(m and m != me and m in text for m in movers):
            out["responsive_moves"] += 1
    if moves:
        out["responsive_share"] = round(out["responsive_moves"] / len(moves), 3)
    return out


def world_update_headline(world: WorldModel, round_num: int, record: Dict[str, Any]) -> str:
    """One line for the action log / run state: period + counts."""
    p = world.period or {}
    label = str(p.get("label") or f"round {round_num}")
    det = record.get("deterministic") or {}
    arb = record.get("arbiter") or {}
    bits = [f"{label}: {det.get('decisions', 0)} decisions",
            f"{len((record.get('diff') or {}).get('variables_changed') or [])} facts changed",
            f"{arb.get('events', 0)} events"]
    # RED LINES: "events" counts the arbiter's emergent events only, so a crossing gets its own
    # count; a round without one keeps the headline it always had
    crossed = len(arb.get("red_lines_crossed") or [])
    if crossed:
        bits.append(f"{crossed} red line{'s' if crossed != 1 else ''} crossed")
    bits.append(f"arbiter={record.get('arbiter_status')}")
    narrative = _text(record.get("narrative"), 140)
    if narrative:
        bits.append(narrative)
    return " · ".join(bits)


# ---------------------------------------------------------------------------
# composition
# ---------------------------------------------------------------------------

def run_world_round(world: WorldModel, round_num: int, period: Optional[Dict[str, Any]],
                    decisions: Iterable[Any], fired_events: Iterable[Dict[str, Any]], *, llm: Any, rng: Any,
                    scenarios: Sequence[str] = (), arbiter_enabled: bool = True, language: str = "",
                    arbiter_temperature: float = 0.3) -> Dict[str, Any]:
    """Deterministic update → arbiter → commit → digest.  Returns the round record.

    ``arbiter_temperature`` stays at the arbiter's default for the path the agents live in; the
    sibling world paths (``world_paths``) sample it higher, bounded."""
    rows = _decision_rows(decisions)
    before = world.snapshot()
    deterministic = deterministic_round_update(world, round_num, period, rows, fired_events, rng)
    status, update, problems = ("skipped", {}, [])
    arbiter_summary: Dict[str, Any] = {}
    arbiter_attempts: List[Dict[str, Any]] = []
    if arbiter_enabled:
        status, update, problems = run_arbiter(llm, world, round_num, period, rows, deterministic, scenarios,
                                               language=language, temperature=arbiter_temperature,
                                               attempts=arbiter_attempts)
        if status == "applied" and update:
            checkpoint = copy.deepcopy(world.__dict__)
            try:
                arbiter_summary = world.apply_arbiter_update(round_num, update)
            except Exception as exc:  # noqa: BLE001 — a kernel bug must not break the loop
                world.__dict__.clear()
                world.__dict__.update(checkpoint)
                logger.warning("applying arbiter update failed in round %s: %s", round_num, type(exc).__name__)
                status = "failed"
                update = {}
                problems.append(f"apply error: {type(exc).__name__}")
    world.commit_round(round_num)
    diff = world.diff(before)
    narrative = str(update.get("narrative") or "") if isinstance(update, dict) else ""
    digest = build_round_digest(world, round_num, before, rows, narrative)
    record: Dict[str, Any] = {
        "schema_version": WORLD_UPDATE_VERSION,
        "round": int(round_num),
        "period": dict(period) if isinstance(period, dict) else None,
        "decisions": {"total": len(rows),
                      "ok": sum(1 for d in rows if d.get("status") == "ok"),
                      "held": sum(1 for d in rows if (d.get("option") or {}).get("id") == "hold_position"),
                      "failed": sum(1 for d in rows if d.get("status") == "failed"),
                      "invalid": sum(1 for d in rows if d.get("status") == "invalid"),
                      LANGUAGE_MISMATCH: sum(1 for d in rows if d.get("status") == LANGUAGE_MISMATCH)},
        "deterministic": deterministic,
        "arbiter_status": status,
        "arbiter_problems": problems[:12],
        "arbiter_attempts": arbiter_attempts,
        "arbiter": arbiter_summary,
        "scenario_pressure": dict(update.get("scenario_pressure") or {}) if isinstance(update, dict) else {},
        "narrative": narrative,
        "diff": diff,
        "digest": digest,
        "behaviour": behaviour_metrics(world, round_num, rows),
        "snapshot_before": before,
    }
    record["headline"] = world_update_headline(world, round_num, record)
    return record
