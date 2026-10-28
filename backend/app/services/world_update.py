"""Per-round world update: deterministic kernel step plus a bounded LLM arbiter (design §2.5).

Once every platform has delivered a round, the coordinator runs ONE world update:

1. ``deterministic_round_update`` — scheduled research events, the actors'
   structured decisions (capacity, commitments, coalition / antagonistic
   relationship nudges), due delayed effects (seeded RNG) and lapsed
   commitments.  Never fabricates numeric effects.
2. ``run_arbiter`` — one structured LLM call that resolves contested moves,
   moves state variables, emits emergent events, relationship changes and
   delayed effects.  Its output is validated against the variable registry and
   the cast (``validate_arbiter_update``) and clamped by the kernel before being
   applied.  Any failure leaves the round committed with the deterministic
   update only and ``arbiter_status=failed``; the failure record names the
   provider's error class, HTTP status / code and whether the LLM client's
   fallback provider took the call over (``arbiter_problems``).
3. ``build_round_digest`` — the agent-facing "WHAT CHANGED LAST PERIOD" text
   (herding guard: no scenario shares).

``run_world_round`` composes the three for the runner; it is pure given
``(world, decisions, llm, rng)`` and does no I/O.
"""

from __future__ import annotations

import logging
import math
import copy
import json
import re
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from ..utils.llm_errors import describe_llm_error
from .agent_decision import LANGUAGE_MISMATCH, AgentDecision
from .world_model import (FULFILLMENT_PREFIX, MAX_ACTION_RESOLUTIONS, RESPONSE_PREFIXES, WorldModel, _bound_lines, _text, format_value, is_kind_name_unit,
                          normalize_label)
from .world_text_budgets import STATEMENT_ARBITER_MAX_CHARS, STATEMENT_DIGEST_MAX_CHARS

logger = logging.getLogger(__name__)

WORLD_UPDATE_VERSION = "world-update/v1"
ARBITER_STATUSES = ("applied", "applied_partial", "failed", "invalid", "skipped")
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
    # Canonical cost and timing belong exclusively to kernel admission. Never
    # rewrite them from raw rows: an omitted field or rejected duplicate can
    # otherwise replace the admitted action's lag with zero.
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
        tail = f" [{v.kind}]" if v.kind != "numeric" else ""
        path = _recent_path(v)
        lines.append(f"- {v.id}: {v.name} = {format_value(v.value, v.unit)}{tail}" + (f" (path: {path})" if path else ""))
    if not world.variables:
        lines.append("- (no tracked variables yet — you may create up to 3 that the moves clearly affect)")
    lines.append("")
    lines.append("## Moves this period")
    rows = _decision_rows(decisions)
    moved = 0
    public_rows = []
    seen_moves = set()
    for supplied in rows:
        d = supplied
        aid = world.resolve_actor(d.get("agent_id"))
        actor = world.actors.get(aid)
        action = actor.last_action if actor is not None else None
        if action and action.get("round") == round_num:
            if aid in seen_moves:
                continue
            seen_moves.add(aid)
            # Adjudicate what admission recorded, never rejected duplicate text
            # or omitted raw metadata that the kernel canonically restored.
            d = {"agent_id": aid, "actor_name": actor.name, "status": action.get("status"),
                 "targets": action.get("targets", []), "magnitude": action.get("magnitude", 0),
                 "public_statement": action.get("statement", ""),
                 "option": {"id": action.get("option_id"), "label": action.get("label"),
                            "kind": action.get("kind"), "lag": action.get("lag", 0)}}
        if d.get("status") != "ok" or (d.get("option") or {}).get("id") == "hold_position":
            continue
        public_rows.append(d)
        opt = d.get("option") or {}
        tgt = f" → {', '.join(d.get('targets') or [])}" if d.get("targets") else ""
        stmt = f' Statement: "{_text(d.get("public_statement"), STATEMENT_ARBITER_MAX_CHARS)}"' if d.get("public_statement") else ""
        record = world.track_record_text(aid) if aid is not None else ""
        lines.append(f"- {d.get('actor_name')}: {opt.get('label')} (kind={opt.get('kind')}, "
                     f"magnitude={d.get('magnitude')}){tgt}.{stmt}"
                     + (f" Implementation lag: {opt['lag']} period(s); the action's direct effect cannot land "
                        f"before round {round_num + opt['lag']}." if type(opt.get("lag")) is int and opt["lag"] > 0 else "")
                     + (f" Track record: {record}." if record else ""))
        moved += 1
    if not moved:
        lines.append("- (no actor made a consequential move; the world drifts on its own momentum)")
    attempts = [(actor, c) for actor in world.actors.values() for c in actor.commitments
                if (c.get("last_fulfillment_attempt") or {}).get("round") == round_num
                and (c.get("last_fulfillment_attempt") or {}).get("outcome") == "unverified"]
    if attempts:
        lines.extend(["", "## Specific commitment delivery attempts (not yet fulfilled)",
                      "Assess whether this exact promise was actually delivered in this period. Unrelated actions, "
                      "new agreements, announcements and partial progress are not fulfilment. Use success only "
                      "for full delivery; otherwise use partial, pending, blocked or failed. Return the exact "
                      "commitment_id AND action_round in that actor's resolution, with a concrete delivery rationale."])
        for actor, commitment in attempts:
            lines.append(f"- actor={actor.name}; commitment_id={commitment['id']}; action_round={round_num}; "
                         f"promise={commitment.get('description')}; counterparty="
                         f"{', '.join(world.delivery_targets(actor.agent_id, commitment)) or '(self)'}")
    stakes = _red_lines_at_stake(world, public_rows)
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
        '- "variable_changes": [{"variable_id": "<id from the list>", "new_value": <number or text> OR '
        '"delta": <number>, "caused_by": "<cast name>" | null, "rationale": "..."}] — only variables the '
        "moves/events plausibly affect; small, defensible moves; leave the rest untouched. Name caused_by "
        "only when a mover's own move this period sets the new value (an announced tariff, rate, quota or "
        "price it states), for every variable kind. Direct implementation effects respect the stated action lag; "
        "an announcement is not completed implementation. Immediate expectation or market reactions need their "
        "own distinct rationale and variable. For a move with zero implementation lag, "
        f"a stated figure takes effect in full{_clamp_rule(world)}. Delayed effects retain the kernel's "
        "per-period, reversion and cumulative drift bounds when they land.",
        '- "new_variables": [{"name": "...", "value": ..., "unit": "...", "kind": "numeric|categorical|boolean|text", '
        '"rationale": "..."}] — at most 3, only when a move creates a new fact the world must now track.',
        '- "events": [{"description": "...", "kind": "emergent|consequence|resolution", "actors": ["<cast name>"], '
        '"targets": ["<cast name>"]}] — market, counterpart, public or institutional reactions (≤6).',
        '- "relationship_changes": [{"source": "<cast name>", "target": "<cast name>", "direction": "closer|farther|flat", '
        '"rationale": "..."}].',
        '- "pending_effects": [{"description": "...", "due_periods": 1-12, "variable_id": "<id or null>", '
        '"new_value": ... OR "delta": ..., "probability": 0-1, "caused_by": "<cast name>" | null}] '
        '— delayed consequences that land later; identify the actor for direct implementation effects. '
        'List each effect once, either here or in variable_changes, never both.',
        '- "action_resolutions": [{"actor": "<cast name>", "outcome": "success|partial|blocked|pending|failed", '
        '"rationale": "...", "commitment_id": "<exact id for delivery attempts, otherwise null>", '
        '"action_round": <current round integer for delivery attempts>}] — one ordinary resolution per actor '
        'that moved, plus one separate resolution per listed delivery attempt. Never conflate maintenance '
        'with the discretionary move; deliveries require their exact commitment_id and action_round.',
        '- "red_line_crossings": [{"actor": "<whose red line>", "by": "<cast name whose move crossed it>", '
        '"red_line": "<the red line as listed>", "rationale": "..."}] — only for a listed red line that a move '
        "this period clearly crossed; usually none.",
        '- "scenario_pressure": {"<candidate scenario>": "up|down|flat"} — direction only, no numbers.',
        f"Cast: {cast}. Candidate scenarios: {sc}.{lang}",
    ]
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
    try:
        out = (float(value) if isinstance(value, (int, float))
               else float(str(value).replace(",", "").replace("%", "").strip()))
        return out if math.isfinite(out) else None
    except (TypeError, ValueError, OverflowError):
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


def _validate_arbiter_fields(raw: Any, world: WorldModel, scenarios: Sequence[str] = ()) -> Tuple[Dict[str, Any], List[str]]:
    """Bound and type-check the arbiter payload; returns ``(update, problems)``.

    Unknown variable ids, unknown actors, bad kinds and oversized lists are
    dropped with a recorded problem.  The returned update is safe to hand to
    ``WorldModel.apply_arbiter_update`` (which additionally clamps numeric moves).
    """
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
            if world.is_derived_variable(var.id):
                problems.append("write to derived or private target variable rejected")
                continue
            if var.id in changed_ids:
                problems.append(f"duplicate change for '{var.id}'")
                continue
            row: Dict[str, Any] = {"variable_id": var.id, "rationale": _text(ch.get("rationale"), 200)}
            cause = ch.get("caused_by")
            if cause not in (None, ""):
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
            if world.is_derived_variable(nv.get("name")) or world.is_derived_variable(nv.get("id")):
                problems.append("creation of derived or private target variable rejected")
                continue
            raw_kind = _text(nv.get("kind"), 16).casefold()
            kind = raw_kind or "numeric"
            if kind not in ("numeric", "categorical", "boolean", "text"):
                kind = "text"
            if kind == "numeric" and _num(nv.get("value")) is None:
                kind = "text"
            value = nv.get("value")
            if kind == "numeric":
                value = _num(value)
            elif kind == "boolean" and not isinstance(value, bool):
                word = _text(value, 40).casefold().strip(" .!?。，")
                if word not in _BOOL_TRUE_WORDS | _BOOL_FALSE_WORDS:
                    problems.append(f"non-boolean new variable '{_text(nv['name'], 80)}'")
                    continue
                value = word in _BOOL_TRUE_WORDS
            elif kind != "boolean":
                value = _text(value, 160)
            unit = _text(nv.get("unit"), 24)
            # a unit belongs to numeric facts only; models echo the kind ("boolean", "date")
            # into the unit field, which would otherwise render as "yes boolean"
            if kind != "numeric" or unit.casefold() in (kind, raw_kind) or is_kind_name_unit(unit):
                unit = ""
            update["new_variables"].append({"name": _text(nv["name"], 140), "value": value,
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
            if world.is_derived_variable(fx.get("variable_id")):
                problems.append("pending write to derived or private target variable rejected")
                continue
            try:
                due = max(1, min(12, int(fx.get("due_periods", 1) or 1)))
            except (TypeError, ValueError, OverflowError):
                problems.append("pending effect with invalid due_periods")
                continue
            vid = fx.get("variable_id")
            vid = str(vid) if vid and str(vid) in world.variables else None
            row = {"description": _text(fx["description"], 220), "due_periods": due, "variable_id": vid,
                   "targets": _names(fx.get("targets"))}
            cause = world.resolve_actor(fx.get("caused_by"))
            if cause is not None:
                row["caused_by"] = world.actor_name(cause)
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
                elif var.kind == "boolean":
                    value = fx.get("new_value")
                    if not isinstance(value, bool):
                        word = _text(value, 40).casefold().strip(" .!?。，")
                        if word not in _BOOL_TRUE_WORDS | _BOOL_FALSE_WORDS:
                            problems.append(f"non-boolean pending effect for '{vid}'")
                            continue
                        value = word in _BOOL_TRUE_WORDS
                    row["new_value"] = value
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
        counts: Dict[Tuple[int, Optional[str]], int] = {}
        for r in res:
            if isinstance(r, dict):
                _, implicated = world.resolution_key(r)
                for key in implicated:
                    counts[key] = counts.get(key, 0) + 1
        for r in res:
            if not isinstance(r, dict):
                continue
            key, _ = world.resolution_key(r)
            outcome = _text(r.get("outcome"), 16).casefold()
            if key is None or outcome not in RESOLUTION_OUTCOMES:
                problems.append("resolution with unknown actor or outcome")
                continue
            aid, cid = key
            if counts[key] != 1:
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


def validate_arbiter_update(raw: Any, world: WorldModel, scenarios: Sequence[str] = ()) -> Tuple[Dict[str, Any], List[str]]:
    """Repair fields independently while preserving duplicate-resolution guards.

    A malformed field cannot discard valid changes in another field. Resolution
    rows remain a batch so conflicting attestations cannot be repaired into a
    false success. Missing/rejected values leave deterministic state untouched.
    """
    update, problems = _validate_arbiter_fields({}, world, scenarios)
    if not isinstance(raw, dict):
        return update, ["payload is not an object"]
    for field in update:
        if field not in raw:
            continue
        expected = str if field == "narrative" else dict if field == "scenario_pressure" else list
        if not isinstance(raw[field], expected):
            problems.append(f"invalid {field}: expected {expected.__name__}")
            continue
        try:
            validated, rejected = _validate_arbiter_fields({field: raw[field]}, world, scenarios)
            update[field] = validated[field]
            problems.extend(rejected)
        except (TypeError, ValueError, OverflowError, KeyError) as exc:
            problems.append(f"invalid {field}: {type(exc).__name__}")
    _defer_action_effects(update, world, problems)
    return update, problems


def _defer_action_effects(update: Dict[str, Any], world: WorldModel, problems: List[str]) -> None:
    """Enforce a recorded lag on direct, attributed implementation effects."""
    def remaining(row: Dict[str, Any]) -> int:
        return world.action_effect_due(row.get("caused_by"), world.round) - world.round

    for effect in update["pending_effects"]:
        effect["due_periods"] = max(effect["due_periods"], remaining(effect))
    immediate = []
    for change in update["variable_changes"]:
        delay = remaining(change)
        if not delay:
            immediate.append(change)
            continue
        effect = {"description": change.get("rationale") or "Delayed action implementation",
                  "due_periods": delay, "variable_id": change["variable_id"],
                  "probability": 1.0, "caused_by": change["caused_by"]}
        key = "new_value" if "new_value" in change else "delta"
        effect[key] = change[key]
        # Models sometimes repeat the same delayed effect in both channels.
        if not any(fx.get("variable_id") == effect["variable_id"] and fx.get(key) == effect[key]
                   and fx.get("caused_by") == effect["caused_by"]
                   and fx.get("due_periods") == effect["due_periods"]
                   and fx.get("probability") == effect["probability"]
                   and (not change.get("rationale") or fx.get("description") == change["rationale"])
                   for fx in update["pending_effects"]):
            update["pending_effects"].append(effect)
        problems.append(f"deferred '{change['variable_id']}' for action lag ({delay} periods)")
    update["variable_changes"] = immediate


def run_arbiter(llm: Any, world: WorldModel, round_num: int, period: Optional[Dict[str, Any]],
                decisions: Iterable[Any], deterministic: Dict[str, Any], scenarios: Sequence[str], *,
                language: str = "", temperature: float = 0.3, max_tokens: int = 2200,
                repair_mode: str = "field", evidence: Optional[Dict[str, Any]] = None
                ) -> Tuple[str, Dict[str, Any], List[str]]:
    """One arbiter call → ``(status, validated_update, problems)``; never raises.

    ``llm.chat_json`` is the backend ``LLMClient`` surface: on a content-filter or other
    non-retryable 4xx rejection the client itself retries the request once on the
    configured fallback provider (``LLMClient.chat`` failover) before raising.  A failure
    that survives that is recorded with the provider's error class, HTTP status / code, a
    bounded message snippet and the failover outcome, so ``arbiter_problems`` says why
    the round carries only the deterministic update.
    """
    if repair_mode not in ("field", "round"):
        raise ValueError("SIM_WORLD_ARBITER_REPAIR must be field or round")
    capture = evidence if evidence is not None else {}
    if llm is None:
        return "skipped", {}, ["no llm"]
    prompt = build_arbiter_prompt(world, round_num, period, decisions, deterministic, scenarios, language=language)
    try:
        messages = [{"role": "user", "content": prompt}]
        parser = getattr(llm, "_parse_json_response", None)
        if callable(parser):
            # Use the provider's normal transport/fallback, but own the JSON
            # retry: exactly one temperature-zero correction for syntax only.
            attempts = []
            for attempt in range(2):
                response = llm.chat(messages=messages, temperature=temperature if attempt == 0 else 0.0,
                                    max_tokens=max_tokens, response_format={"type": "json_object"})
                attempts.append(response)
                capture.update(raw=response, attempts=attempts)
                # The shared parser returns None both for JSON null and for a
                # syntax failure. A parsed null is a bad payload, not a retry.
                cleaned = re.sub(r"^```(?:json)?\s*\n?", "", response.strip(), flags=re.IGNORECASE)
                cleaned = re.sub(r"\n?```\s*$", "", cleaned).strip()
                try:
                    raw = json.loads(cleaned)
                    break
                except json.JSONDecodeError:
                    pass
                raw = parser(response)
                if raw is not None:
                    break
            else:
                return "invalid", {}, ["unparseable JSON after one correction"]
        else:
            raw = llm.chat_json(messages=messages, temperature=temperature, max_tokens=max_tokens)
            capture["raw"] = copy.deepcopy(raw)
    except Exception as exc:  # noqa: BLE001 — a failed arbiter must not break the round
        detail = describe_llm_error(exc, max_chars=ARBITER_ERROR_SNIPPET_CHARS)
        logger.warning("world arbiter failed in round %s (status=failed): %s", round_num, detail)
        return "failed", {}, [f"llm error: {detail}"]
    try:
        update, problems = validate_arbiter_update(raw, world, scenarios)
        capture["validated"] = copy.deepcopy(update)
    except Exception as exc:  # noqa: BLE001 — malformed payload must not break round commit
        logger.warning("world arbiter validation failed in round %s: %s", round_num, exc)
        return "invalid", {}, [f"validation error: {type(exc).__name__}"]
    if not isinstance(raw, dict):
        return "invalid", update, problems
    # Kernel timing is mandatory in both policies. A valid effect deferred to
    # its implementation date is an advisory, not a rejected arbiter field.
    rejected = [problem for problem in problems if not problem.startswith("deferred '")]
    if rejected and repair_mode == "round":
        return "invalid", {}, problems
    if rejected:
        return ("applied_partial" if any(update.values()) else "invalid"), update, problems
    return "applied", update, problems


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
            stmt = f': "{_text(d.get("public_statement"), STATEMENT_DIGEST_MAX_CHARS)}"' if d.get("public_statement") else ""
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
                    arbiter_temperature: float = 0.3, arbiter_repair: str = "field") -> Dict[str, Any]:
    """Deterministic update → arbiter → commit → digest.  Returns the round record.

    ``arbiter_temperature`` stays at the arbiter's default for the path the agents live in; the
    sibling world paths (``world_paths``) sample it higher, bounded."""
    if arbiter_repair not in ("field", "round"):
        raise ValueError("SIM_WORLD_ARBITER_REPAIR must be field or round")
    rows = _decision_rows(decisions)
    before = world.snapshot()
    deterministic = deterministic_round_update(world, round_num, period, rows, fired_events, rng)
    status, update, problems = ("skipped", {}, [])
    arbiter_summary: Dict[str, Any] = {}
    evidence: Dict[str, Any] = {}
    if arbiter_enabled:
        status, update, problems = run_arbiter(llm, world, round_num, period, rows, deterministic, scenarios,
                                               language=language, temperature=arbiter_temperature,
                                               repair_mode=arbiter_repair, evidence=evidence)
        if status in ("applied", "applied_partial") and update:
            try:
                arbiter_summary = world.apply_arbiter_update(round_num, update)
            except Exception as exc:  # noqa: BLE001 — a kernel bug must not break the loop
                logger.warning("applying arbiter update failed in round %s: %s", round_num, exc)
                status = "failed"
                problems.append(f"apply error: {describe_llm_error(exc, max_chars=120)}")
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
        "arbiter_problem_details": [{"code": "effect_deferred" if p.startswith("deferred ") else
                                     "provider_failure" if p.startswith("llm error:") else "field_rejected",
                                     "message": p} for p in problems],
        "arbiter_repair": arbiter_repair,
        "arbiter_raw": evidence.get("raw"),
        "arbiter_validated": evidence.get("validated", {}),
        "arbiter_attempts": evidence.get("attempts", []),
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
