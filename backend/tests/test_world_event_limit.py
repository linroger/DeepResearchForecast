"""The per-round event limit rejects the overflowing group instead of the round.

Before the fix, kernel._run_intents re-raised event_limit, so actors whose ordinary actions
filled maxEventsPerRound killed the round on every resume (core-engine review M5, probe
p7), and zero-amount flow receipts counted toward the limit. Pure scenarios; the store
case writes only under tmp_path, so both suites run this module.
"""
from copy import deepcopy

from app.services.world_simulation.contracts import add_days, validate_spec
from app.services.world_simulation.kernel import initialize_world, resolve_round, stage_interactions
from app.services.world_simulation.observations import response_actors
from test_world_kernel import START, action, decision, fixture, record, template


def limited(spec, limit):
    spec = deepcopy(spec)
    spec["limits"]["maxEventsPerRound"] = limit
    return validate_spec(spec)


def resolved(spec, snapshot, decisions):
    result = resolve_round(spec, snapshot, decisions, snapshot["round"] + 1)
    again = resolve_round(deepcopy(spec), deepcopy(snapshot), deepcopy(decisions), snapshot["round"] + 1)
    assert result == again  # Deterministic, so the store's commit replay reproduces it.
    return result


def codes(result):
    return [(r["actorId"], r["accepted"], r["code"]) for r in result["resolutions"]]


def counted(events):
    return sum(not (e["kind"] in {"flow_transfer", "flow_summary"} and e["details"]["amount"] == "0") for e in events)


def test_overflowing_message_group_is_rejected_and_the_round_commits():
    spec = limited(fixture(), 5)
    state = initialize_world(spec)
    decisions = [decision(spec, state, aid, [action("say", parameters={"text": f"{aid} one"}),
                                             action("say", parameters={"text": f"{aid} two"})])
                 for aid in ("a", "b", "c")]
    result = resolved(spec, state, decisions)
    assert result["snapshot"]["round"] == 1
    assert codes(result)[-1] == ("c", False, "event_limit")
    assert [accepted for _, accepted, _ in codes(result)] == [True] * 5 + [False]
    assert [e["kind"] for e in result["events"]] == ["message_accepted"] * 5
    # Staging gives recipients exactly the communication the resolution admits.
    staged = stage_interactions(spec, state, decisions, 1)
    assert staged["interactions"] == result["snapshot"]["interactions"]


def test_zero_amount_flow_receipts_do_not_count_toward_the_limit():
    idle = record(flowId="idle", sourceAccount="c_cash", targetAccount="sink", ratePerDay="1")
    splits = [record(eventId=f"noop_{i}", at=add_days(START, f"0.{i}"), kind="rule_set",
                     parameters={"ruleId": "permit", "value": True}) for i in (25, 5, 75)]
    spec = limited(fixture(flows=[idle], scheduled=splits), 4)
    state = initialize_world(spec)
    result = resolved(spec, state, [decision(spec, state, "a", [action("wait")])])
    zero = [e for e in result["events"] if e["kind"] in {"flow_transfer", "flow_summary"}]
    assert len(zero) == 5 and all(e["details"]["amount"] == "0" for e in zero)  # Still recorded.
    assert len(result["events"]) == 9 and counted(result["events"]) == 4
    assert codes(result) == [("a", True, "accepted")]


def test_group_admission_leaves_room_for_this_rounds_settlements():
    spec = limited(fixture(duration="0.5"), 3)
    state = initialize_world(spec)
    decisions = [decision(spec, state, "a", [action("expand")]),
                 decision(spec, state, "b", [action("wait")]), decision(spec, state, "c", [action("wait")])]
    result = resolved(spec, state, decisions)
    assert codes(result) == [("a", True, "accepted"), ("b", True, "accepted"), ("c", False, "event_limit")]
    assert [e["kind"] for e in result["events"]] == ["investment_accepted", "wait_accepted", "commitment_settled"]
    assert result["snapshot"]["metrics"]["capacity"]["value"] == "7"


def test_staged_offers_keep_their_budget_ahead_of_earlier_physical_groups():
    spec = limited(fixture(), 1)
    state = initialize_world(spec)
    proposal = decision(spec, state, "b", [action("order", operation="propose",
                                                  parameters={"quantity": "7", "price": "5"})])
    wait = decision(spec, state, "a", [action("wait")])
    staged = stage_interactions(spec, state, [proposal, wait], 1)
    assert response_actors(spec, staged, 1) == ["a"]  # a was shown the offer for its response phase
    result = resolved(spec, state, [wait, proposal])
    assert codes(result) == [("a", False, "event_limit"), ("b", True, "accepted")]
    assert result["snapshot"]["interactions"] == staged["interactions"]


def test_settlements_cannot_accumulate_past_a_later_rounds_limit():
    early = template("tiny", "investment", {"fromAccount": "a_cash", "toAccount": "sink", "cost": "1",
                     "targetMetric": "capacity", "delta": "1", "durationDays": "2.5"})
    late = template("tiny_late", "investment", {"fromAccount": "a_cash", "toAccount": "sink", "cost": "1",
                    "targetMetric": "capacity", "delta": "1", "durationDays": "1.5"})
    spec = limited(fixture(early, late), 2)
    state = initialize_world(spec)
    first = resolved(spec, state, [decision(spec, state, "a", [action("tiny"), action("tiny")])])
    assert [accepted for _, accepted, _ in codes(first)] == [True, True]
    state = first["snapshot"]
    # A third settlement due in round 3 would push that round's boundary phase over the limit.
    second = resolved(spec, state, [decision(spec, state, "a", [action("tiny_late")])])
    assert codes(second) == [("a", False, "event_limit")]
    third = resolved(spec, second["snapshot"], [])
    assert [e["kind"] for e in third["events"]] == ["commitment_settled", "commitment_settled"]
    assert third["snapshot"]["metrics"]["capacity"]["value"] == "6"


def test_store_commit_counts_only_receipts_that_moved_something(tmp_path):
    from app.services.world_simulation.store import WorldStore

    idle = record(flowId="idle", sourceAccount="c_cash", targetAccount="sink", ratePerDay="1")
    splits = [record(eventId=f"noop_{i}", at=add_days(START, f"0.{i}"), kind="rule_set",
                     parameters={"ruleId": "permit", "value": True}) for i in (25, 5, 75)]
    spec = limited(fixture(flows=[idle], scheduled=splits), 4)
    with WorldStore(tmp_path / "world.sqlite3", spec) as store:
        fence = store.acquire_writer("event-limit")
        store.freeze_phase(1, "proposal", [], fence)
        store.freeze_phase(1, "response", [], fence)
        result = resolve_round(store.spec, store.head(), [], 1)
        assert len(result["events"]) > 4 and counted(result["events"]) == 3
        store.commit_round(0, result["snapshot"], result["events"], result["resolutions"], [], fence)
        assert store.head()["round"] == 1
