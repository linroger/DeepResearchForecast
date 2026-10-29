#!/usr/bin/env python3
"""Bounded saved-world acceptance; aggregate output, no providers or state writes.

Call main(["--input", FIXTURE, "--output", NEW_JSON]) from a test running under
main_offline_pytest.py. Both paths must be inside that guard's evidence root.
Importing this module is stdlib-only. An unguarded CLI invocation fails closed.

Historical actions are checked against *local, conditional* prerequisites. Final
state is never rolled backwards and no full trajectory equivalence is claimed.
Raw validation additionally needs an explicit full pre-arbiter state. Current
production arbiter-raw/v1 captures do not contain that state; the optional
pre_arbiter_world field is for independently prepared replay fixtures only.
"""
from __future__ import annotations

import argparse
from collections import Counter
import copy
import hashlib
import json
from pathlib import Path
import sys

FILES = ("simulation_config.json", "world_state.json", "world_actions.jsonl",
         "world_state_history.jsonl", "arbiter_raw.jsonl")
MAX_FILE_BYTES = 16 * 1024 * 1024


class ReplayInputError(ValueError):
    """Only fixed public codes, never values from a private input."""


def _guard_root():
    guard = sys.modules.get("main_offline_guard")
    if guard is None or not getattr(guard, "configured", False):
        raise ReplayInputError("offline_guard_required")
    return guard.root


def _models():
    _guard_root()
    from app.services.world_model import WorldModel, Interaction
    return WorldModel, Interaction


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def _object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ReplayInputError("duplicate_json_key")
        value[key] = item
    return value


def _json(text):
    def reject_constant(_):
        raise ReplayInputError("nonfinite_json_number")
    try:
        return json.loads(text, object_pairs_hook=_object, parse_constant=reject_constant)
    except (ValueError, UnicodeError):
        raise ReplayInputError("invalid_json") from None


def _require(condition, code):
    if not condition:
        raise ReplayInputError(code)


def _rows(value):
    return isinstance(value, list) and all(isinstance(row, dict) for row in value)


def _positive(value):
    return type(value) is int and value > 0


def _load(root):
    payload, hashes = {}, {}
    for name in FILES:
        path = root / name
        _require(not path.is_symlink(), "symlink_input")
        if not path.exists():
            hashes[name] = None
            continue
        _require(path.is_file() and path.stat().st_size <= MAX_FILE_BYTES, "invalid_input_file")
        data = path.read_bytes()
        hashes[name] = _sha(data)
        payload[name] = ([_json(line) for line in data.splitlines() if line.strip()]
                         if name.endswith("jsonl") else _json(data))
    return payload, hashes


def _validate_recorded_identities(world):
    """Shared final-state/raw-prestate checks; never normalize recorded IDs."""
    ids = [a.get("agent_id") for a in world["actors"]]
    _require(all(type(a) is int for a in ids) and len(set(ids)) == len(ids), "invalid_actor_ids")
    for actor in world["actors"]:
        _require(_rows(actor.get("commitments", [])), "invalid_commitments")
        commitments = actor.get("commitments", [])
        cids = [c.get("id") for c in commitments]
        _require(all(isinstance(cid, str) for cid in cids) and len(set(cids)) == len(cids), "invalid_commitment_ids")
        for c in commitments:
            _require(type(c.get("made_round")) is int and c["made_round"] >= 0
                     and _positive(c.get("due_round")), "invalid_commitment_rounds")
            _require(isinstance(c.get("description"), str) and isinstance(c.get("source"), str), "invalid_commitment_fields")
    iids = [row.get("id") for row in world["interactions"]]
    _require(all(isinstance(iid, str) for iid in iids) and len(set(iids)) == len(iids), "invalid_interaction_ids")
    for row in world["interactions"]:
        _require(all(type(row.get(key)) is int for key in ("proposer", "recipient", "opened_round", "expires_round"))
                 and isinstance(row.get("terms"), str), "invalid_interaction_fields")


def _validate(payload):
    for name in FILES[:4]:
        _require(name in payload, "missing_required_file")
    config, state = payload[FILES[0]], payload[FILES[1]]
    _require(isinstance(config, dict) and isinstance(config.get("world_model"), dict), "missing_seed")
    _require(_rows(config.get("agent_configs", [])), "invalid_agent_configs")
    _require(isinstance(state, dict) and isinstance(state.get("world"), dict), "missing_final_world")
    world = state["world"]
    for key in ("actors", "variables", "relationships", "interactions", "events", "pending_effects"):
        _require(_rows(world.get(key)), "invalid_final_world_fields")
    _validate_recorded_identities(world)
    actions, history = payload[FILES[2]], payload[FILES[3]]
    _require(_rows(actions) and _rows(history), "invalid_record_rows")
    rounds = [row.get("round") for row in history]
    _require(all(_positive(r) for r in rounds) and len(set(rounds)) == len(rounds), "invalid_history_rounds")
    for row in history:
        _require(isinstance(row.get("period"), dict), "missing_period")
    for row in actions:
        _require(_positive(row.get("round")) and type(row.get("agent_id")) is int
                 and isinstance(row.get("option"), dict)
                 and isinstance(row["option"].get("id"), str), "invalid_action")
    _require(_rows(payload.get(FILES[4], [])), "invalid_raw_records")


def _base(config, history):
    WorldModel, _ = _models()
    world = WorldModel.from_seed(copy.deepcopy(config["world_model"]), copy.deepcopy(config.get("agent_configs", [])))
    world.set_period_labels({r["round"]: r["period"].get("label", "") for r in history})
    return world


def _deadline_checks(config, final, history, actions):
    """Replay recorded accept/counter semantics on isolated retained offer inputs."""
    _, Interaction = _models()
    counts = Counter()
    periods = {r["round"]: r["period"] for r in history}
    interactions = {r["id"]: r for r in final["interactions"]}
    for row in actions:
        if not row["option"]["id"].startswith("accept:"):
            continue
        counts["recorded_accept_actions"] += 1
        rnd, aid = row["round"], row["agent_id"]
        inter = interactions.get(row["option"]["id"].partition(":")[2])
        lag = row["option"].get("lag")
        if (inter is None or rnd not in periods or type(lag) is not int or lag < 0
                or inter.get("recipient") != aid or row.get("status") != "ok"):
            counts["missing_prerequisites"] += 1
            continue
        world = _base(config, history)
        if any(p not in world.actors for p in (inter.get("proposer"), aid)):
            counts["missing_prerequisites"] += 1
            continue
        restored = copy.deepcopy(inter)
        restored.update(status="open", obligations=[], resolved_round=None, response="")
        world.interactions[inter["id"]] = Interaction.from_dict(restored)
        world.start_round(rnd, periods[rnd])
        # Test the recorded action through real admission, including response binding.
        world.register_decisions(rnd, [copy.deepcopy(row)])
        current = world.interactions[inter["id"]]
        counts["local_checks"] += 1
        if current.status != "accepted":
            counts["current_countered" if current.status == "countered" else "current_not_admitted"] += 1
            problems = (world.actors[aid].action_rejections[-1].get("admission_problems", [])
                        if world.actors[aid].action_rejections else [])
            # Only known fixed codes; never emit free-form kernel messages.
            for text, code in (("invalid action target binding", "rejected_target_binding"),
                               ("invalid offer response binding", "rejected_offer_binding"),
                               ("option violates capacity, canonical metadata or decision rights", "rejected_option_metadata")):
                counts[code] += text in problems
            counts["rejected_after_retained_offer_expiry"] += (
                "invalid offer response binding" in problems and inter["expires_round"] < rnd)
            continue
        duties = [c for a in world.actors.values() for c in a.commitments
                  if c.get("source") == "agreement:" + inter["id"]]
        counts["current_accepted"] += 1
        current_due = duties[0]["due_round"]
        legacy_due = rnd + max(1, lag)  # Historical lag-only rule; classification, not a legacy kernel.
        counts["deadline_changed_from_legacy_lag_rule"] += current_due != legacy_due
        counts["terms_deadline" if duties[0].get("due_basis") == "terms" else "default_deadline"] += 1
        recorded = [c for a in final["actors"] for c in a.get("commitments", [])
                    if c.get("source") == "agreement:" + inter["id"] and c.get("made_round") == rnd]
        if len(recorded) == 2:
            counts["retained_obligation_pairs"] += 1
            counts["recorded_due_matches_legacy_rule"] += all(c["due_round"] == legacy_due for c in recorded)
            counts["recorded_due_matches_current_rule"] += all(c["due_round"] == current_due for c in recorded)
        else:
            counts["missing_retained_obligation_pair"] += 1
        # Conditional no-delivery probe, explicitly separate from observed history.
        world.start_round(current_due + 1, None)
        counts["lapsed_in_current_grace"] += len(world.lapse_overdue_commitments(current_due + 1))
        world.start_round(current_due + 2, None)
        counts["lapsed_after_current_grace"] += len(world.lapse_overdue_commitments(current_due + 2))
        counts["breach_events_after_current_grace"] += len(world.events_in_round(current_due + 2, ("breach",)))
        counts["released_after_current_grace"] += sum(c["status"] == "released" for c in duties)
    return dict(counts)


def _delivery_checks(config, final, history, actions):
    """Assume a retained promise is still open; never infer past status from final status."""
    _, Interaction = _models()
    counts = Counter()
    periods = {r["round"]: r["period"] for r in history}
    commitments = {(a["agent_id"], c["id"]): c for a in final["actors"] for c in a.get("commitments", [])}
    interactions = {r["id"]: r for r in final["interactions"]}
    for row in actions:
        if not row["option"]["id"].startswith("fulfill:"):
            continue
        counts["recorded_delivery_actions"] += 1
        rnd, aid = row["round"], row["agent_id"]
        c = commitments.get((aid, row["option"]["id"].partition(":")[2]))
        world = _base(config, history)
        if c is None or rnd not in periods or aid not in world.actors or row.get("status") != "ok":
            counts["missing_prerequisites"] += 1
            continue
        promise = {k: copy.deepcopy(c[k]) for k in ("id", "description", "made_round", "due_round", "source", "counterparty") if k in c}
        promise["status"] = "pending"
        world.actors[aid].commitments = [promise]
        source = str(c.get("source") or "")
        if source.startswith("agreement:"):
            inter = interactions.get(source.partition(":")[2])
            if inter is None or any(p not in world.actors for p in (inter.get("proposer"), inter.get("recipient"))):
                counts["missing_prerequisites"] += 1
                continue
            restored = copy.deepcopy(inter)
            restored["status"] = "accepted"
            world.interactions[inter["id"]] = Interaction.from_dict(restored)
        world.start_round(rnd, periods[rnd])
        world.lapse_overdue_commitments(rnd)
        events = world.register_decisions(rnd, [copy.deepcopy(row)])
        admitted = any(e.kind == "action" and e.source == "commitment" for e in events)
        counts["local_checks"] += 1
        counts["current_admitted" if admitted else "current_rejected"] += 1
        counts["within_legacy_due_window"] += c["made_round"] < rnd <= c["due_round"]
        counts["in_current_grace_window"] += rnd == c["due_round"] + 1
        counts["after_current_grace_window"] += rnd > c["due_round"] + 1
        counts["fulfilled_without_arbiter"] += promise["status"] == "fulfilled"
    return dict(counts)


def _lapse_checks(config, final, history):
    """Bind exact retained lapse events to promises, then apply today's grace rule.

    The event proves a historical lapse, not all pre-lapse state. Replay assumes
    the matched obligation was still open. Ambiguous descriptions stay unbound.
    """
    _, Interaction = _models()
    counts = Counter()
    periods = {r["round"]: r["period"] for r in history}
    interactions = {r["id"]: r for r in final["interactions"]}
    for event in final["events"]:
        if event.get("source") != "commitment" or event.get("kind") != "consequence":
            continue
        counts["retained_commitment_consequence_events"] += 1
        rnd = event.get("round")
        matches = [(a, c) for a in final["actors"] for c in a.get("commitments", [])
                   if event.get("actors") == [a.get("name")]
                   and event.get("description") == f"{a.get('name')}'s commitment lapsed: {c.get('description')}"
                   and type(rnd) is int and c["made_round"] < rnd]
        if len(matches) != 1 or rnd not in periods:
            counts["unbound_or_ambiguous_events"] += 1
            continue
        actor, c = matches[0]
        world = _base(config, history)
        aid = actor["agent_id"]
        if aid not in world.actors:
            counts["missing_prerequisites"] += 1
            continue
        promise = {k: copy.deepcopy(c[k]) for k in ("id", "description", "made_round", "due_round", "source", "counterparty") if k in c}
        promise["status"] = "pending"
        world.actors[aid].commitments = [promise]
        if c["source"].startswith("agreement:"):
            inter = interactions.get(c["source"].partition(":")[2])
            if inter is None or any(p not in world.actors for p in (inter.get("proposer"), inter.get("recipient"))):
                counts["missing_prerequisites"] += 1
                continue
            restored = copy.deepcopy(inter)
            restored["status"] = "accepted"
            world.interactions[inter["id"]] = Interaction.from_dict(restored)
        world.start_round(rnd, periods[rnd])
        lapsed = world.lapse_overdue_commitments(rnd)
        counts["local_checks"] += 1
        counts["matches_legacy_overdue_rule"] += c["due_round"] < rnd
        counts["current_would_lapse" if lapsed else "current_would_preserve"] += 1
        counts["in_current_grace_window"] += rnd == c["due_round"] + 1
    return dict(counts)


def _recorded_id(value, limit=None):
    return (isinstance(value, str) and bool(value) and not any(char.isspace() for char in value)
            and (limit is None or len(value) <= limit))


def _validate_raw_prestate(pre_state):
    """Reject lossy registry admission before the permissive runtime loader.

    Actor names/aliases and event actor/target labels are not unique IDs. Validate
    explicit ID references only; do not invent identities from narrative labels.
    A pruned/dangling referenced registry cannot establish complete replay input.
    """
    _require(isinstance(pre_state, dict) and pre_state.get("schema_version") == "world-model-state/v1", "invalid_raw_prestate")
    for key in ("actors", "variables", "relationships", "interactions", "events", "pending_effects"):
        _require(_rows(pre_state.get(key)), "incomplete_raw_prestate")
    rnd = pre_state.get("round")
    _require(_positive(rnd) and type(pre_state.get("committed_round")) is int
             and pre_state["committed_round"] == rnd - 1, "invalid_raw_prestate_round")
    _validate_recorded_identities(pre_state)
    actors = {a["agent_id"]: a for a in pre_state["actors"]}

    def actor_ref(value):
        return type(value) is int and value in actors

    for actor in actors.values():
        _require(isinstance(actor.get("name"), str) and bool(actor["name"].strip())
                 and isinstance(actor.get("agency_class"), str) and bool(actor["agency_class"].strip()),
                 "invalid_raw_actor_fields")
        _require(_rows(actor.get("commitments")), "incomplete_raw_actor_commitments")
    variable_ids = [row.get("id") for row in pre_state["variables"]]
    _require(all(_recorded_id(vid) for vid in variable_ids)
             and len(set(variable_ids)) == len(variable_ids), "invalid_raw_variable_ids")
    variables = set(variable_ids)
    for row in pre_state["variables"]:
        _require(isinstance(row.get("name"), str) and bool(row["name"].strip()) and "value" in row
                 and row.get("kind") in ("numeric", "boolean", "categorical", "text"), "invalid_raw_variable_fields")
    relationship_keys = []
    for row in pre_state["relationships"]:
        _require(actor_ref(row.get("source")) and actor_ref(row.get("target")), "invalid_raw_relationship_reference")
        relationship_keys.append((row["source"], row["target"]))
    _require(len(set(relationship_keys)) == len(relationship_keys), "duplicate_raw_relationship")
    interactions = {row["id"]: row for row in pre_state["interactions"]}
    for iid, row in interactions.items():
        # Interaction.__init__ trims/collapses/truncates its 40-character key.
        _require(_recorded_id(iid, 40), "invalid_raw_interaction_id")
        _require(actor_ref(row["proposer"]) and actor_ref(row["recipient"]), "invalid_raw_interaction_reference")
        obligations = row.get("obligations")
        _require(isinstance(obligations, list) and len(obligations) <= 4
                 and all(_recorded_id(cid, 56) for cid in obligations)
                 and len(set(obligations)) == len(obligations), "invalid_raw_obligations")
        parent = row.get("parent_id", "")
        _require(parent == "" or isinstance(parent, str) and parent in interactions and parent != iid,
                 "invalid_raw_parent_reference")
        for cid in obligations:
            matches = [c for aid in (row["proposer"], row["recipient"])
                       for c in actors[aid]["commitments"] if c["id"] == cid]
            _require(len(matches) == 1 and matches[0]["source"] == "agreement:" + iid,
                     "invalid_raw_obligation_reference")
    for aid, actor in actors.items():
        for c in actor["commitments"]:
            _require(_recorded_id(c["id"], 56), "invalid_raw_commitment_id")
            if "counterparty" in c:
                _require(actor_ref(c["counterparty"]), "invalid_raw_counterparty")
            if c["source"].startswith("agreement:"):
                inter = interactions.get(c["source"].partition(":")[2])
                _require(inter is not None and aid in (inter["proposer"], inter["recipient"])
                         and c["id"] in inter["obligations"], "invalid_raw_agreement_reference")
                other = inter["recipient"] if aid == inter["proposer"] else inter["proposer"]
                _require(c.get("counterparty", other) == other, "invalid_raw_counterparty")
    for row in pre_state["pending_effects"]:
        _require(_recorded_id(row.get("id")) and type(row.get("due_round")) is int
                 and isinstance(row.get("description"), str), "invalid_raw_effect_fields")
        vid, aid = row.get("variable_id"), row.get("actor_id")
        _require(vid is None or isinstance(vid, str) and vid in variables, "invalid_raw_effect_variable_reference")
        _require(aid is None or actor_ref(aid), "invalid_raw_effect_actor_reference")
    for row in pre_state["events"]:
        _require(type(row.get("round")) is int and isinstance(row.get("kind"), str)
                 and isinstance(row.get("description"), str), "invalid_raw_event_fields")
        refs = row.get("variable_ids", [])
        _require(isinstance(refs, list) and len(refs) <= 8
                 and all(isinstance(vid, str) and vid in variables for vid in refs), "invalid_raw_event_variable_reference")


def replay_raw(pre_state, raw):
    """One captured response through both production repair policies; no transport."""
    _guard_root()
    _validate_raw_prestate(pre_state)
    WorldModel, _ = _models()
    from app.services.world_update import run_arbiter
    rnd = pre_state["round"]

    class CapturedResponse:
        def chat_json(self, **_):
            # Only decoded capture objects are admitted here; no invented JSON repair.
            return copy.deepcopy(raw)

    if isinstance(raw, str):
        raw = _json(raw)
    result = {}
    for policy in ("field", "round"):
        world = WorldModel.from_dict(copy.deepcopy(pre_state))
        status, update, problems = run_arbiter(CapturedResponse(), world, rnd, world.period, (), {},
                                               world.scenarios, repair_mode=policy)
        before = world.snapshot()
        if status in ("applied", "applied_partial"):
            world.apply_arbiter_update(rnd, update)
        result[policy] = {"status": status, "problems": len(problems),
                          "variables_changed": len(world.diff(before)["variables_changed"])}
    return result


def analyze(payload):
    _validate(payload)
    config, final = payload[FILES[0]], payload[FILES[1]]["world"]
    actions, history = payload[FILES[2]], payload[FILES[3]]
    raw_rows = payload.get(FILES[4], [])
    raw_counts = Counter(records=len(raw_rows), replayed=0)
    for row in raw_rows:
        _require(row.get("schema_version") == "arbiter-raw/v1", "invalid_raw_record_schema")
        if "arbiter_raw" not in row or row["arbiter_raw"] is None:
            raw_counts["missing_raw"] += 1
        elif "pre_arbiter_world" not in row:
            raw_counts["missing_full_prestate"] += 1
        else:
            _require(isinstance(row["pre_arbiter_world"], dict), "invalid_raw_prestate")
            _require(row.get("round") == row["pre_arbiter_world"].get("round"), "raw_round_mismatch")
            result = replay_raw(row["pre_arbiter_world"], row["arbiter_raw"])
            raw_counts["replayed"] += 1
            for policy, verdict in result.items():
                raw_counts[policy + "_" + verdict["status"]] += 1
                raw_counts[policy + "_variables_changed"] += verdict["variables_changed"]
    deadlines = _deadline_checks(config, final, history, actions)
    deliveries = _delivery_checks(config, final, history, actions)
    checked = deadlines.get("local_checks", 0) + deliveries.get("local_checks", 0)
    return {
        "status": "partial", "input_status": "valid_structural", "full_trajectory_replay": False,
        "confidence": {"local_helper_execution": "direct", "historical_preconditions": "conditional",
                       "full_historical_equivalence": "unavailable"},
        "assumptions": ["isolated_offer_open_before_recorded_answer", "isolated_promise_open_before_recorded_delivery",
                        "breach_probe_assumes_no_delivery_by_either_party", "legacy_is_scalar_rule_comparison_only"],
        "coverage": {"history_rounds": len(history), "action_rows": len(actions), "local_action_checks": checked,
                     "actions_not_checked": len(actions) - checked,
                     "retained_commitments": sum(len(a.get("commitments", [])) for a in final["actors"]),
                     "retained_interactions": len(final["interactions"]), "retained_events": len(final["events"]),
                     "scheduled_event_records": sum(e.get("source") == "research_timeline" for e in final["events"]),
                     "complete_round_prestate_records": 0},
        "raw": {"file_present": FILES[4] in payload,
                "status": "missing" if FILES[4] not in payload else "empty" if not raw_rows else "partial" if raw_counts["replayed"] != len(raw_rows) else "checked",
                "history_arbiter_is_raw": False, **dict(raw_counts)},
        "deadlines": deadlines, "deliveries": deliveries,
        "observed_lapses": _lapse_checks(config, final, history),
        "limits": ["final_state_is_not_a_pre_round_checkpoint", "history_arbiter_is_application_summary",
                   "no_rng_or_pending_effect_trajectory_reconstruction", "other_actions_not_replayed",
                   "no_historical_raw_repair_lift_without_capture_and_full_prestate"],
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        guard_root = _guard_root()
        root, output = args.input.resolve(), args.output.absolute()
        _require(root.is_relative_to(guard_root) and root.is_dir(), "input_requires_guard_fixture_root")
        _require(output.parent.resolve().is_relative_to(guard_root) and not output.resolve().is_relative_to(root), "invalid_output_location")
        _require(not output.exists() and not output.is_symlink(), "output_must_be_new")
    except ReplayInputError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    code = 0
    try:
        payload, hashes = _load(root)
        report = analyze(payload)
        _, after = _load(root)
        _require(hashes == after, "input_changed_during_replay")
        report.update(input_sha256=hashes, input_preserved=True)
    except ReplayInputError as exc:
        report, code = {"status": "invalid_input", "error": str(exc)}, 2
    except Exception as exc:
        # Kernel defects are visible as failed checks, never hidden behind 'partial'.
        report, code = {"status": "runtime_error", "error_type": type(exc).__name__}, 3
    sources = [Path(__file__).resolve()]
    sources += [Path(module.__file__) for name, module in list(sys.modules.items())
                if name.startswith("app.services.world_") or name == "app.services.agent_decision"]
    report["source_sha256"] = {str(p.relative_to(Path(__file__).resolve().parents[2])): _sha(p.read_bytes()) for p in sources}
    report["schema_version"] = "saved-world-replay/v1"
    with output.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
