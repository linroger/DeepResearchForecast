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
   update only and ``arbiter_status=failed``.
3. ``build_round_digest`` — the agent-facing "WHAT CHANGED LAST PERIOD" text
   (herding guard: no scenario shares).

``run_world_round`` composes the three for the runner; it is pure given
``(world, decisions, llm, rng)`` and does no I/O.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from .agent_decision import AgentDecision
from .world_model import WorldModel, _bound_lines, _text, format_value, normalize_label

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
MAX_RESOLUTIONS = 24
NARRATIVE_MAX_CHARS = 700
DIGEST_MAX_CHARS = 1100


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
    action_events = world.register_decisions(round_num, rows)
    fired = world.fire_due_effects(round_num, rng)
    lapsed = world.lapse_overdue_commitments(round_num)
    return {
        "scheduled_events": [e.description for e in scheduled],
        "actions": [e.description for e in action_events if e.kind == "action"],
        "effects_fired": fired,
        "commitments_lapsed": [f"{c.get('actor')}: {c.get('description')}" for c in lapsed],
        "decisions": len(rows),
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
        "moves have partial, delayed or contested effects.",
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
        lines.append(f"- {v.id}: {v.name} = {format_value(v.value, v.unit)}{tail}")
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
        lines.append(f"- {d.get('actor_name')}: {opt.get('label')} (kind={opt.get('kind')}, "
                     f"magnitude={d.get('magnitude')}){tgt}.{stmt}")
        moved += 1
    if not moved:
        lines.append("- (no actor made a consequential move; the world drifts on its own momentum)")
    if deterministic.get("scheduled_events"):
        lines.append("")
        lines.append("## Confirmed events this period")
        lines.extend(f"- {e}" for e in deterministic["scheduled_events"][:10])
    mech: List[str] = []
    for fx in deterministic.get("effects_fired") or []:
        mech.append(fx.get("description", ""))
    mech.extend(deterministic.get("commitments_lapsed") or [])
    if mech:
        lines.append("")
        lines.append("## Already applied mechanically")
        lines.extend(f"- {m}" for m in mech[:10] if m)
    cast = ", ".join(a.name for a in list(world.actors.values())[:30])
    sc = "; ".join(str(s) for s in scenarios) or "(none)"
    lang = f" Write narrative and descriptions in {language}." if language else ""
    lines += [
        "",
        "## Your task",
        "Resolve the period. Return ONLY JSON with these keys:",
        '- "narrative": 2-4 sentences on what actually changed and why (≤600 chars).',
        '- "variable_changes": [{"variable_id": "<id from the list>", "new_value": <number or text> OR '
        '"delta": <number>, "rationale": "..."}] — only variables the moves/events plausibly affect; '
        "small, defensible moves; leave the rest untouched.",
        '- "new_variables": [{"name": "...", "value": ..., "unit": "...", "kind": "numeric|categorical|boolean|text", '
        '"rationale": "..."}] — at most 3, only when a move creates a new fact the world must now track.',
        '- "events": [{"description": "...", "kind": "emergent|consequence|resolution", "actors": ["<cast name>"], '
        '"targets": ["<cast name>"]}] — market, counterpart, public or institutional reactions (≤6).',
        '- "relationship_changes": [{"source": "<cast name>", "target": "<cast name>", "direction": "closer|farther", '
        '"rationale": "..."}].',
        '- "pending_effects": [{"description": "...", "due_periods": 1-12, "variable_id": "<id or null>", '
        '"new_value": ... OR "delta": ..., "probability": 0-1}] — delayed consequences that land later.',
        '- "action_resolutions": [{"actor": "<cast name>", "outcome": "success|partial|blocked|pending|failed", '
        '"rationale": "..."}] — one per actor that moved.',
        '- "scenario_pressure": {"<candidate scenario>": "up|down|flat"} — direction only, no numbers.',
        f"Cast: {cast}. Candidate scenarios: {sc}.{lang}",
    ]
    return "\n".join(lines)


def _num(value: Any) -> Optional[float]:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value).replace(",", "").replace("%", "").strip())
    except (TypeError, ValueError):
        return None


def validate_arbiter_update(raw: Any, world: WorldModel, scenarios: Sequence[str] = ()) -> Tuple[Dict[str, Any], List[str]]:
    """Bound and type-check the arbiter payload; returns ``(update, problems)``.

    Unknown variable ids, unknown actors, bad kinds and oversized lists are
    dropped with a recorded problem.  The returned update is safe to hand to
    ``WorldModel.apply_arbiter_update`` (which additionally clamps numeric moves).
    """
    problems: List[str] = []
    update: Dict[str, Any] = {"narrative": "", "variable_changes": [], "new_variables": [], "events": [],
                              "relationship_changes": [], "pending_effects": [], "action_resolutions": [],
                              "scenario_pressure": {}}
    if not isinstance(raw, dict):
        return update, ["payload is not an object"]
    update["narrative"] = _text(raw.get("narrative"), NARRATIVE_MAX_CHARS)
    changes = raw.get("variable_changes")
    if isinstance(changes, list):
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
            row: Dict[str, Any] = {"variable_id": var.id, "rationale": _text(ch.get("rationale"), 200)}
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
                    low = _text(val, 16).casefold()
                    if low in ("true", "yes", "是"):
                        val = True
                    elif low in ("false", "no", "否"):
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
    new_vars = raw.get("new_variables")
    if isinstance(new_vars, list):
        for nv in new_vars[:MAX_NEW_VARIABLES]:
            if not isinstance(nv, dict) or not _text(nv.get("name"), 140):
                continue
            kind = _text(nv.get("kind"), 16).casefold() or "numeric"
            if kind not in ("numeric", "categorical", "boolean", "text"):
                kind = "text"
            if kind == "numeric" and _num(nv.get("value")) is None:
                kind = "text"
            update["new_variables"].append({"name": _text(nv["name"], 140), "value": nv.get("value"),
                                            "unit": _text(nv.get("unit"), 24), "kind": kind,
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
            update["events"].append({"description": _text(ev["description"], 320), "kind": kind,
                                     "actors": _names(ev.get("actors")), "targets": _names(ev.get("targets")),
                                     "variable_ids": [str(x) for x in (ev.get("variable_ids") or [])
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
            if direction not in ("closer", "farther", "further", "break", "ally"):
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
        for r in res[:MAX_RESOLUTIONS]:
            if not isinstance(r, dict):
                continue
            aid = world.resolve_actor(r.get("actor") if r.get("actor") is not None else r.get("agent_id"))
            outcome = _text(r.get("outcome"), 16).casefold()
            if aid is None or outcome not in RESOLUTION_OUTCOMES:
                problems.append("resolution with unknown actor or outcome")
                continue
            update["action_resolutions"].append({"actor": world.actor_name(aid), "outcome": outcome,
                                                 "rationale": _text(r.get("rationale"), 200)})
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
                language: str = "", temperature: float = 0.3, max_tokens: int = 2200
                ) -> Tuple[str, Dict[str, Any], List[str]]:
    """One arbiter call → ``(status, validated_update, problems)``; never raises."""
    if llm is None:
        return "skipped", {}, ["no llm"]
    prompt = build_arbiter_prompt(world, round_num, period, decisions, deterministic, scenarios, language=language)
    try:
        raw = llm.chat_json(messages=[{"role": "user", "content": prompt}], temperature=temperature,
                            max_tokens=max_tokens)
    except Exception as exc:  # noqa: BLE001 — a failed arbiter must not break the round
        logger.warning("world arbiter failed in round %s (status=failed): %s", round_num, exc)
        return "failed", {}, [f"llm error: {type(exc).__name__}"]
    update, problems = validate_arbiter_update(raw, world, scenarios)
    if not isinstance(raw, dict):
        return "invalid", update, problems
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
        lines.append(_text(narrative, 360))
    rows = _decision_rows(decisions)
    moves = [d for d in rows if d.get("status") == "ok" and (d.get("option") or {}).get("id") != "hold_position"]
    if moves:
        lines.append("Moves:")
        for d in moves[:8]:
            opt = d.get("option") or {}
            tgt = f" (→ {', '.join(d.get('targets') or [])})" if d.get("targets") else ""
            stmt = f': "{_text(d.get("public_statement"), 140)}"' if d.get("public_statement") else ""
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
    consequences = world.events_in_round(round_num, ("scheduled", "consequence", "emergent", "resolution"))
    if consequences:
        lines.append("Events and consequences:")
        lines.extend(f"- {e.description}" for e in consequences[:8])
    if diff["relationships_changed"]:
        lines.append("Alliances and rivalries:")
        for rc in diff["relationships_changed"][:6]:
            direction = f" ({rc['direction']})" if rc.get("direction") else ""
            lines.append(f"- {rc['source']} — {rc['target']}: {rc['to']}{direction}")
    return _bound_lines(lines, max_chars)


def world_update_headline(world: WorldModel, round_num: int, record: Dict[str, Any]) -> str:
    """One line for the action log / run state: period + counts."""
    p = world.period or {}
    label = str(p.get("label") or f"round {round_num}")
    det = record.get("deterministic") or {}
    arb = record.get("arbiter") or {}
    bits = [f"{label}: {det.get('decisions', 0)} decisions",
            f"{len((record.get('diff') or {}).get('variables_changed') or [])} facts changed",
            f"{arb.get('events', 0)} events", f"arbiter={record.get('arbiter_status')}"]
    narrative = _text(record.get("narrative"), 140)
    if narrative:
        bits.append(narrative)
    return " · ".join(bits)


# ---------------------------------------------------------------------------
# composition
# ---------------------------------------------------------------------------

def run_world_round(world: WorldModel, round_num: int, period: Optional[Dict[str, Any]],
                    decisions: Iterable[Any], fired_events: Iterable[Dict[str, Any]], *, llm: Any, rng: Any,
                    scenarios: Sequence[str] = (), arbiter_enabled: bool = True, language: str = "") -> Dict[str, Any]:
    """Deterministic update → arbiter → commit → digest.  Returns the round record."""
    rows = _decision_rows(decisions)
    before = world.snapshot()
    deterministic = deterministic_round_update(world, round_num, period, rows, fired_events, rng)
    status, update, problems = ("skipped", {}, [])
    arbiter_summary: Dict[str, Any] = {}
    if arbiter_enabled:
        status, update, problems = run_arbiter(llm, world, round_num, period, rows, deterministic, scenarios,
                                               language=language)
        if status in ("applied", "invalid") and update:
            try:
                arbiter_summary = world.apply_arbiter_update(round_num, update)
            except Exception as exc:  # noqa: BLE001 — a kernel bug must not break the loop
                logger.warning("applying arbiter update failed in round %s: %s", round_num, exc)
                status = "failed"
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
                      "invalid": sum(1 for d in rows if d.get("status") == "invalid")},
        "deterministic": deterministic,
        "arbiter_status": status,
        "arbiter_problems": problems[:12],
        "arbiter": arbiter_summary,
        "scenario_pressure": dict(update.get("scenario_pressure") or {}) if isinstance(update, dict) else {},
        "narrative": narrative,
        "diff": diff,
        "digest": digest,
        "snapshot_before": before,
    }
    record["headline"] = world_update_headline(world, round_num, record)
    return record
