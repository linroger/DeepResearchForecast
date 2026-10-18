"""Boundary effects that cannot apply are recorded, not raised (pure; both suites run it).

Before the fix, a scheduled transfer out of an actor-owned account, a negative stock or
rate delta, or a settlement hitting insufficient_resources / negative_quantity raised inside
kernel._advance. The failure replayed from the saved decisions on every resume, so the
world could never pass that round (core-engine review B2, probe p2).
"""
from copy import deepcopy

import pytest

from app.services.world_simulation.contracts import WorldError, add_days, stable_id
from app.services.world_simulation.kernel import initialize_world, resolve_round
from app.services.world_simulation.observations import build_observation
from test_world_kernel import START, action, advance, decision, fixture, offered, record, response, template


def _kinds(result):
    return [event["kind"] for event in result["events"]]


def _replays_identically(spec, snapshot, decisions):
    first = resolve_round(spec, snapshot, decisions, snapshot["round"] + 1)
    second = resolve_round(deepcopy(spec), deepcopy(snapshot), deepcopy(decisions), snapshot["round"] + 1)
    assert first == second
    return first


def test_scheduled_transfer_out_of_a_spent_actor_account_is_recorded_as_failed():
    scheduled = [record(eventId="tax", at=add_days(START, "1.5"), kind="transfer",
                        parameters={"fromAccount": "a_cash", "toAccount": "sink", "amount": "5"})]
    spec = fixture(scheduled=scheduled)
    state = initialize_world(spec)
    spent = advance(spec, state, [decision(spec, state, "a", [action("give", parameters={"amount": "8"})])])
    assert spent["snapshot"]["accounts"]["a_cash"]["balance"] == "2"
    second = _replays_identically(spec, spent["snapshot"], [])
    failed = [event for event in second["events"] if event["kind"] == "scheduled_transfer_failed"]
    assert len(failed) == 1
    assert failed[0]["details"] == {"scheduledEventId": "tax", "code": "insufficient_resources"}
    assert failed[0]["eventId"] == stable_id(spec["generationId"], "tax", "scheduled_transfer_failed")
    assert failed[0]["at"] == add_days(START, "1.5")
    accounts = second["snapshot"]["accounts"]
    assert accounts["a_cash"]["balance"] == "2" and accounts["sink"]["balance"] == "0"
    # The failed effect is processed once: the next round neither retries it nor calls it overdue.
    third = advance(spec, second["snapshot"])
    assert "scheduled_transfer_failed" not in _kinds(third) and "scheduled_transfer" not in _kinds(third)
    assert third["snapshot"]["accounts"]["a_cash"]["balance"] == "2"


def test_repeated_negative_investment_fails_only_the_settlement_that_would_go_negative():
    shrink = template("shrink", "investment", {"fromAccount": "a_cash", "toAccount": "sink", "cost": "1",
                                               "targetMetric": "capacity", "delta": "-3", "durationDays": "1.5"})
    spec = fixture(shrink)
    state = initialize_world(spec)
    first = advance(spec, state, [decision(spec, state, "a", [action("shrink"), action("shrink")])])
    assert [r["accepted"] for r in first["resolutions"]] == [True, True]
    second = _replays_identically(spec, first["snapshot"], [])
    assert _kinds(second).count("commitment_settled") == 1
    failed = [event for event in second["events"] if event["kind"] == "commitment_failed"]
    assert len(failed) == 1 and failed[0]["details"]["code"] == "negative_quantity"
    assert failed[0]["actorId"] == "a"
    snapshot = second["snapshot"]
    assert snapshot["metrics"]["capacity"]["value"] == "1"
    statuses = sorted(c["status"] for c in snapshot["commitments"].values())
    assert statuses == ["failed", "settled"]
    failed_commitment = next(c for c in snapshot["commitments"].values() if c["status"] == "failed")
    assert failed[0]["details"]["commitmentId"] == failed_commitment["commitmentId"]
    # Both costs stay paid: the investment was executed; only its effect could not apply.
    assert snapshot["accounts"]["a_cash"]["balance"] == "8" and snapshot["accounts"]["sink"]["balance"] == "2"
    advance(spec, snapshot)  # A failed commitment is closed, never settled again.


def test_scheduled_negative_shock_without_any_actor_is_recorded_as_failed():
    scheduled = [record(eventId="shock", at=add_days(START, "1.5"), kind="metric_delta",
                        parameters={"targetMetric": "capacity", "delta": "-10"})]
    spec = fixture(scheduled=scheduled)
    first = advance(spec, initialize_world(spec))
    second = _replays_identically(spec, first["snapshot"], [])
    assert _kinds(second) == ["scheduled_metric_delta_failed"]
    assert second["events"][0]["details"] == {"scheduledEventId": "shock", "code": "negative_quantity"}
    assert second["snapshot"]["metrics"]["capacity"]["value"] == "4"
    # Permitted audiences learn the failure through their ordinary next observation.
    seen = build_observation(spec, second["snapshot"], "b", 3)["privateState"]["lastObservedEvents"]
    assert [event["kind"] for event in seen] == ["scheduled_metric_delta_failed"]


def test_failed_settlement_releases_holds_and_moves_nothing():
    spec = fixture()
    state = initialize_world(spec)
    proposal, staged, offer = offered(spec, state)
    accepted = advance(spec, state, [proposal, response(spec, staged, "a", offer)])["snapshot"]
    commitment = next(iter(accepted["commitments"].values()))
    assert accepted["accounts"]["stock"]["reserved"] == "7" and accepted["accounts"]["b_cash"]["reserved"] == "5"
    # White-box: give the held agreement an effect that cannot apply at settlement. No
    # declared mechanism produces one today; the boundary must still fail it atomically.
    commitment["effects"] = [{"kind": "metric_delta", "parameters": {"targetMetric": "capacity", "delta": "-10"}}]
    before = deepcopy(accepted["accounts"])
    settled = _replays_identically(spec, accepted, [])
    item = settled["snapshot"]["commitments"][commitment["commitmentId"]]
    assert item["status"] == "failed"
    assert [e["kind"] for e in settled["events"] if e["kind"].startswith("commitment_")] == ["commitment_failed"]
    accounts = settled["snapshot"]["accounts"]
    for key in ("stock", "b_cash", "a_cash", "b_stock"):
        assert accounts[key]["balance"] == before[key]["balance"]
        assert accounts[key]["reserved"] == "0"
    assert settled["snapshot"]["metrics"]["capacity"]["value"] == "4"


def test_store_commit_replays_a_round_with_a_failed_boundary_effect(tmp_path):
    from app.services.world_simulation.store import WorldStore

    scheduled = [record(eventId="shock", at=add_days(START, "0.5"), kind="metric_delta",
                        parameters={"targetMetric": "capacity", "delta": "-10"})]
    spec = fixture(scheduled=scheduled)
    path = tmp_path / "world.sqlite3"
    with WorldStore(path, spec) as store:
        fence = store.acquire_writer("boundary")
        store.freeze_phase(1, "proposal", [], fence)
        store.freeze_phase(1, "response", [], fence)
        result = resolve_round(store.spec, store.head(), [], 1)
        assert [e["kind"] for e in result["events"]] == ["scheduled_metric_delta_failed"]
        store.commit_round(0, result["snapshot"], result["events"], result["resolutions"], [], fence)
        store.release_writer(fence)
    with WorldStore(path, read_only=True) as reopened:  # The full revision chain verifies on open.
        assert reopened.head()["round"] == 1
        assert [e["kind"] for e in reopened.events()] == ["scheduled_metric_delta_failed"]


def test_opening_effects_at_as_of_still_fail_preparation():
    scheduled = [record(eventId="opening_shock", at=START, kind="metric_delta",
                        parameters={"targetMetric": "capacity", "delta": "-10"})]
    with pytest.raises(WorldError) as caught:
        initialize_world(fixture(scheduled=scheduled))
    assert caught.value.code == "negative_quantity"


def test_same_instant_actor_settlement_still_rejects_only_its_own_intent():
    instant = template("instant_shrink", "investment", {"fromAccount": "a_cash", "toAccount": "sink", "cost": "1",
                       "targetMetric": "capacity", "delta": "-10", "durationDays": "0"})
    spec = fixture(instant)
    state = initialize_world(spec)
    result = advance(spec, state, [decision(spec, state, "a", [action("instant_shrink")])])
    assert result["resolutions"][0]["accepted"] is False
    assert result["resolutions"][0]["code"] == "negative_quantity"
    assert result["snapshot"]["accounts"] == state["accounts"]
