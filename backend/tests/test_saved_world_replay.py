"""Controlled and private-fixture checks; run only through main_offline_pytest.py.

Private acceptance reads ONLY <guard root>/fixtures/<simulation id>. Stage frozen
copies before installing the guard; never point this test at saved uploads.
"""
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

import pytest

pytestmark = pytest.mark.guarded_runner
SCRIPT = Path(__file__).resolve().parents[1] / "scripts/replay_saved_world.py"
SIMULATIONS = (("sim_2a4f7d0e73de", 138, 14), ("sim_1838cf014c0b", 61, 9))


@pytest.fixture
def replay():
    spec = importlib.util.spec_from_file_location("saved_world_replay_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _period(rnd):
    return {"round": rnd, "label": f"period-{rnd}"}


def _controlled():
    from app.services.world_model import WorldModel
    from app.services.agent_decision import build_option_menu, parse_decision
    seed = {
        "schema_version": "world-model-seed/v1", "question": "Exchange audited schedules?",
        "actors": [{"agent_id": i, "name": f"Actor{i}", "agency_class": "firm", "capacity_per_round": 3}
                   for i in range(2)],
        "state_variables": [{"name": "Capacity", "value": 100, "unit": "MW", "provenance": "controlled"}],
    }
    world = WorldModel.from_seed(seed)

    def action(rnd, aid, option, **extra):
        world.start_round(rnd, _period(rnd))
        actor = world.actors[aid]
        parsed = parse_decision({"option_id": option, "scenario_commitment": "abstain", **extra},
                                actor=actor, world=world, options=build_option_menu(actor, world, rnd),
                                scenarios=(), round_num=rnd)
        assert parsed.ok
        row = parsed.to_dict()
        world.register_decisions(rnd, [row])
        world.commit_round(rnd)
        return row

    rows = [action(1, 0, "open_talks", targets=["Actor1"], terms="Deliver audited schedules within three periods.")]
    iid = next(iter(world.interactions))
    rows.append(action(2, 1, "accept:" + iid))
    cid = world.actors[0].commitments[0]["id"]
    rows.append(action(3, 0, "fulfill:" + cid))
    state = world.to_dict()
    return {
        "simulation_config.json": {"world_model": seed, "agent_configs": []},
        "world_state.json": {"world": state},
        "world_actions.jsonl": rows,
        "world_state_history.jsonl": [{"round": r, "period": _period(r), "arbiter": {"events": 1}} for r in range(1, 4)],
    }


def _write(root, payload):
    root.mkdir()
    for name, value in payload.items():
        text = "\n".join(json.dumps(row) for row in value) if name.endswith("jsonl") else json.dumps(value)
        (root / name).write_text(text + "\n")


def _hashes(root):
    return {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in root.iterdir() if p.is_file()}


def test_import_is_stdlib_only_and_unguarded_execution_fails_closed(monkeypatch, replay, tmp_path, capsys):
    # Track imports during a fresh script load, even when other tests loaded app.
    import builtins
    original = builtins.__import__

    def checked_import(name, *args, **kwargs):
        assert name != "app" and not name.startswith("app.")
        return original(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", checked_import)
    spec = importlib.util.spec_from_file_location("saved_world_replay_import_check", SCRIPT)
    spec.loader.exec_module(importlib.util.module_from_spec(spec))
    monkeypatch.delitem(sys.modules, "main_offline_guard")
    assert replay.main(["--input", str(tmp_path), "--output", str(tmp_path / "unused.json")]) == 2
    assert "offline_guard_required" in capsys.readouterr().err


def test_recorded_semantics_deadline_grace_and_batch_breach(replay):
    payload = _controlled()
    before = copy.deepcopy(payload)
    report = replay.analyze(payload)
    assert payload == before
    deadlines, deliveries = report["deadlines"], report["deliveries"]
    assert deadlines["current_accepted"] == 1
    assert deadlines["deadline_changed_from_legacy_lag_rule"] == 1
    assert deadlines["recorded_due_matches_current_rule"] == 1
    assert deadlines["lapsed_in_current_grace"] == 0
    assert deadlines["lapsed_after_current_grace"] == 2
    assert deadlines["breach_events_after_current_grace"] == 2
    assert deadlines["released_after_current_grace"] == 0
    assert deliveries["current_admitted"] == 1
    assert deliveries["fulfilled_without_arbiter"] == 0
    assert report["raw"]["status"] == "missing"
    assert report["raw"]["history_arbiter_is_raw"] is False


@pytest.mark.parametrize("offset,admitted", [(0, True), (1, True), (2, False)])
def test_delivery_due_grace_and_expired(replay, offset, admitted):
    payload = _controlled()
    promise = payload["world_state.json"]["world"]["actors"][0]["commitments"][0]
    rnd = promise["due_round"] + offset
    payload["world_actions.jsonl"][-1]["round"] = rnd
    payload["world_state_history.jsonl"].append({"round": rnd, "period": _period(rnd)})
    counts = replay.analyze(payload)["deliveries"]
    assert counts["current_admitted" if admitted else "current_rejected"] == 1
    assert counts["in_current_grace_window"] == (offset == 1)
    assert counts["fulfilled_without_arbiter"] == 0


def test_changed_acceptance_terms_are_counter_not_deadline_evidence(replay):
    payload = _controlled()
    payload["world_actions.jsonl"][1]["terms"] = "An unrelated agreement to build a second factory."
    counts = replay.analyze(payload)["deadlines"]
    assert counts["current_countered"] == 1
    assert counts.get("current_accepted", 0) == 0


def test_expired_recorded_offer_is_rejected_by_current_admission(replay):
    payload = _controlled()
    payload["world_state.json"]["world"]["interactions"][0]["expires_round"] = 1
    counts = replay.analyze(payload)["deadlines"]
    assert counts["rejected_after_retained_offer_expiry"] == 1
    assert counts.get("current_accepted", 0) == 0


def _raw_fixture(payload, *, malformed_field=False):
    state = copy.deepcopy(payload["world_state.json"]["world"])
    state["committed_round"] = state["round"] - 1
    raw = {"variable_changes": [{"variable_id": state["variables"][0]["id"], "delta": 1}]}
    if malformed_field:
        raw["events"] = {"private": "RAW_PRIVATE_CANARY"}
    return {"schema_version": "arbiter-raw/v1", "round": state["round"],
            "arbiter_raw": raw, "pre_arbiter_world": state}


@pytest.mark.parametrize("mutation", [
    "duplicate_actor", "conflicting_actor", "coerced_actor_id", "missing_actor_id",
    "duplicate_variable", "missing_variable_id", "duplicate_interaction",
    "normalized_interaction_id", "duplicate_relationship", "dangling_relationship",
    "dangling_interaction", "duplicate_commitment", "dangling_agreement",
    "dangling_obligation", "wrong_counterparty", "dangling_effect_variable",
])
def test_raw_prestate_rejects_invalid_registries_before_model_load(replay, tmp_path, monkeypatch, mutation):
    from app.services.world_model import WorldModel
    payload = _controlled()
    capture = _raw_fixture(payload)
    state = capture["pre_arbiter_world"]
    if mutation in ("duplicate_actor", "conflicting_actor"):
        duplicate = copy.deepcopy(state["actors"][0])
        if mutation == "conflicting_actor":
            duplicate["agency_class"] = "PRIVATE_CONFLICT_CANARY"
        state["actors"].append(duplicate)
    elif mutation == "coerced_actor_id":
        state["actors"][0]["agent_id"] = "0"
    elif mutation == "missing_actor_id":
        del state["actors"][0]["agent_id"]
    elif mutation == "duplicate_variable":
        state["variables"].append(copy.deepcopy(state["variables"][0]))
    elif mutation == "missing_variable_id":
        del state["variables"][0]["id"]
    elif mutation == "duplicate_interaction":
        state["interactions"].append(copy.deepcopy(state["interactions"][0]))
    elif mutation == "normalized_interaction_id":
        state["interactions"][0]["id"] += " "
    elif mutation == "duplicate_relationship":
        state["relationships"].append(copy.deepcopy(state["relationships"][0]))
    elif mutation == "dangling_relationship":
        state["relationships"][0]["target"] = 999
    elif mutation == "dangling_interaction":
        state["interactions"][0]["recipient"] = 999
    elif mutation == "duplicate_commitment":
        actor = state["actors"][0]
        actor["commitments"].append(copy.deepcopy(actor["commitments"][0]))
    elif mutation == "dangling_agreement":
        state["actors"][0]["commitments"][0]["source"] = "agreement:missing"
    elif mutation == "dangling_obligation":
        state["interactions"][0]["obligations"].append("missing")
    elif mutation == "wrong_counterparty":
        state["actors"][0]["commitments"][0]["counterparty"] = 0
    elif mutation == "dangling_effect_variable":
        state["pending_effects"] = [{"id": "fx1", "due_round": 4, "description": "controlled effect",
                                     "variable_id": "missing", "op": "add", "value": 1}]
    payload["arbiter_raw.jsonl"] = [capture]
    root, output = tmp_path / "input", tmp_path / "result.json"
    _write(root, payload)
    before = _hashes(root)
    original_load = WorldModel.from_dict
    loads = []

    def tracked_load(cls, value):
        loads.append(True)
        return original_load(value)

    monkeypatch.setattr(WorldModel, "from_dict", classmethod(tracked_load))
    code = replay.main(["--input", str(root), "--output", str(output)])
    report = json.loads(output.read_text())
    assert code == 2
    assert loads == []
    assert report["status"] == "invalid_input"
    assert report.get("input_status") != "valid_structural"
    assert report.get("raw", {}).get("replayed", 0) == 0
    assert _hashes(root) == before
    assert "PRIVATE_CONFLICT_CANARY" not in output.read_text()


@pytest.mark.parametrize("malformed_field", [False, True])
def test_controlled_raw_capture_reaches_real_validation_and_apply(replay, tmp_path, malformed_field):
    payload = _controlled()
    payload["arbiter_raw.jsonl"] = [_raw_fixture(payload, malformed_field=malformed_field)]
    root, output = tmp_path / "input", tmp_path / "result.json"
    _write(root, payload)
    before = _hashes(root)
    assert replay.main(["--input", str(root), "--output", str(output)]) == 0
    report = json.loads(output.read_text())
    assert report["input_preserved"] and before == _hashes(root)
    assert report["raw"]["replayed"] == 1
    assert report["raw"]["field_variables_changed"] == 1
    assert report["raw"]["round_variables_changed"] == (0 if malformed_field else 1)
    assert report["raw"]["field_applied_partial" if malformed_field else "field_applied"] == 1
    assert "RAW_PRIVATE_CANARY" not in output.read_text()


def test_raw_prestate_keeps_shared_aliases_and_distinct_directed_edges(replay):
    payload = _controlled()
    capture = _raw_fixture(payload)
    state = capture["pre_arbiter_world"]
    for actor in state["actors"]:
        actor["aliases"] = ["Shared alias"]
    edge = state["relationships"][0]
    state["relationships"].append({**edge, "source": edge["target"], "target": edge["source"]})
    state["pending_effects"] = [{"id": "fx1", "due_round": 4, "description": "controlled effect",
                                 "actor_id": 0, "variable_id": state["variables"][0]["id"], "op": "add", "value": 1}]
    payload["arbiter_raw.jsonl"] = [capture]
    before = copy.deepcopy(payload)
    report = replay.analyze(payload)
    assert report["raw"]["replayed"] == 1
    assert report["raw"]["field_applied"] == report["raw"]["round_applied"] == 1
    assert payload == before


def test_raw_without_full_prestate_is_not_replayed(replay):
    payload = _controlled()
    row = _raw_fixture(payload)
    del row["pre_arbiter_world"]
    payload["arbiter_raw.jsonl"] = [row]
    report = replay.analyze(payload)
    assert report["raw"]["missing_full_prestate"] == 1
    assert report["raw"].get("replayed", 0) == 0


def test_observed_lapse_event_matches_legacy_but_is_preserved_in_current_grace(replay):
    payload = _controlled()
    world = payload["world_state.json"]["world"]
    actor = world["actors"][0]
    c = actor["commitments"][0]
    rnd = c["due_round"] + 1
    world["events"].append({"round": rnd, "source": "commitment", "kind": "consequence",
                            "actors": [actor["name"]],
                            "description": f"{actor['name']}'s commitment lapsed: {c['description']}"})
    payload["world_state_history.jsonl"].append({"round": rnd, "period": _period(rnd)})
    counts = replay.analyze(payload)["observed_lapses"]
    assert counts["local_checks"] == counts["matches_legacy_overdue_rule"] == 1
    assert counts["current_would_preserve"] == counts["in_current_grace_window"] == 1
    # Same description/creation metadata is insufficient to choose one of two IDs.
    actor["commitments"].append({**c, "id": "duplicate-description"})
    counts = replay.analyze(payload)["observed_lapses"]
    assert counts["unbound_or_ambiguous_events"] == 1
    assert counts.get("local_checks", 0) == 0


@pytest.mark.parametrize("mutation", ["missing_file", "bad_json", "bad_round", "duplicate_round", "bad_commitment", "non_object_row", "bad_raw_state", "duplicate_interaction"])
def test_malformed_input_is_explicit_sanitized_and_preserved(replay, tmp_path, mutation):
    payload = _controlled()
    if mutation == "missing_file":
        del payload["world_state.json"]
    elif mutation == "bad_round":
        payload["world_actions.jsonl"][0]["round"] = True
    elif mutation == "duplicate_round":
        payload["world_state_history.jsonl"].append(payload["world_state_history.jsonl"][0])
    elif mutation == "bad_commitment":
        payload["world_state.json"]["world"]["actors"][0]["commitments"][0]["due_round"] = "PRIVATE_CANARY"
    elif mutation == "non_object_row":
        payload["world_actions.jsonl"].append("PRIVATE_CANARY")
    elif mutation == "bad_raw_state":
        payload["arbiter_raw.jsonl"] = [{"schema_version": "arbiter-raw/v1", "arbiter_raw": {}, "pre_arbiter_world": []}]
    elif mutation == "duplicate_interaction":
        world = payload["world_state.json"]["world"]
        world["interactions"].append(world["interactions"][0])
    root, output = tmp_path / "input", tmp_path / "result.json"
    _write(root, payload)
    if mutation == "bad_json":
        (root / "world_actions.jsonl").write_text('{"PRIVATE_CANARY":')
    before = _hashes(root)
    assert replay.main(["--input", str(root), "--output", str(output)]) == 2
    assert _hashes(root) == before
    assert json.loads(output.read_text())["status"] == "invalid_input"
    assert "PRIVATE_CANARY" not in output.read_text()


def test_output_cannot_overwrite_or_enter_input(replay, tmp_path):
    root = tmp_path / "input"
    _write(root, _controlled())
    before = _hashes(root)
    assert replay.main(["--input", str(root), "--output", str(root / "receipt.json")]) == 2
    output = tmp_path / "existing.json"
    output.write_text("preserve")
    assert replay.main(["--input", str(root), "--output", str(output)]) == 2
    assert output.read_text() == "preserve" and _hashes(root) == before


def test_runtime_failure_is_nonzero_and_does_not_expose_private_exception(replay, tmp_path, monkeypatch):
    root, output = tmp_path / "input", tmp_path / "result.json"
    _write(root, _controlled())
    before = _hashes(root)

    def failure(*args):
        raise RuntimeError("PRIVATE_EXCEPTION_CANARY")

    monkeypatch.setattr(replay, "_deadline_checks", failure)
    assert replay.main(["--input", str(root), "--output", str(output)]) == 3
    assert json.loads(output.read_text())["status"] == "runtime_error"
    assert "PRIVATE_EXCEPTION_CANARY" not in output.read_text()
    assert _hashes(root) == before


@pytest.mark.parametrize("simulation,action_count,round_count", SIMULATIONS)
def test_frozen_specimens(replay, simulation, action_count, round_count):
    guard = sys.modules["main_offline_guard"]
    root = guard.root / "fixtures" / simulation
    if not root.is_dir():
        pytest.skip("private frozen specimen not staged in this guard evidence root")
    before = _hashes(root)
    output = guard.root / (simulation + "-replay.json")
    assert replay.main(["--input", str(root), "--output", str(output)]) == 0
    report = json.loads(output.read_text())
    assert _hashes(root) == before and report["input_preserved"]
    assert report["coverage"]["action_rows"] == action_count
    assert report["coverage"]["history_rounds"] == round_count
    assert report["coverage"]["local_action_checks"] > 0
    assert report["raw"]["status"] == "missing" and report["raw"]["replayed"] == 0
    assert report["status"] == "partial" and not report["full_trajectory_replay"]
    assert report["observed_lapses"]["local_checks"] == 8
    assert report["observed_lapses"]["current_would_preserve"] == 8
    # All output leaves belong to a fixed aggregate schema; no action text/IDs.
    forbidden = ("private_rationale", "public_statement", "actor_name", "description", "terms", "narrative")
    def check_keys(value):
        if isinstance(value, dict):
            assert not any(key in forbidden for key in value)
            for child in value.values():
                check_keys(child)
        elif isinstance(value, list):
            for child in value:
                check_keys(child)
    check_keys(report)
