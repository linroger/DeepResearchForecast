"""Synthetic kernel scenarios. Execute only through the coordinator's guard."""
from copy import deepcopy

import pytest

from app.services.world_simulation.contracts import (
    WorldError, add_days, initial_snapshot, stable_id, validate_decision, validate_spec,
)
from app.services.world_simulation.kernel import initialize_world, resolve_round, stage_interactions, validate_mechanisms
from app.services.world_simulation.observations import build_observation

pytestmark = pytest.mark.guarded_runner
BASIS = {"kind": "scenario_assumption", "refs": ["kernel-fixture-v1"]}
PUBLIC = {"kind": "public"}
START = "2030-01-01T00:00:00Z"


def record(**fields):
    return {"basis": deepcopy(BASIS), "visibility": deepcopy(PUBLIC), **fields}


def template(tid, kind, parameters, actors=("a",), inputs=None):
    return record(templateId=tid, kind=kind, actorIds=list(actors), parameters=parameters, inputs=inputs or {})


def fixture(*actions, periods=5, flows=None, scheduled=None, budget="10", duration="2"):
    """Local fixture: no imports of or writes to another worker's fixtures."""
    accounts = {
        "a_cash": record(ownerId="a", unit="currency", balance=budget),
        "b_cash": record(ownerId="b", unit="currency", balance="20"),
        "c_cash": record(ownerId="c", unit="currency", balance="0"),
        "sink": record(ownerId="external", unit="currency", balance="0"),
        "treasury": record(ownerId="institution", unit="currency", balance="80"),
        "raw": record(ownerId="external", unit="goods", balance="1000"),
        "stock": record(ownerId="a", unit="goods", balance="10"),
        "b_stock": record(ownerId="b", unit="goods", balance="0"),
    }
    catalog = [
        template("wait", "wait", {}, actors=("a", "b", "c", "institution")),
        template("expand", "investment", {"fromAccount": "a_cash", "toAccount": "sink", "cost": "6",
                 "targetMetric": "capacity", "delta": "3", "durationDays": duration, "requiresRule": "permit"}),
        template("give", "transfer", {"fromAccount": "a_cash", "toAccount": "b_cash"},
                 inputs={"amount": {"type": "decimal", "required": True, "min": "0"}}),
        template("order", "agreement", {"recipientIds": ["a"], "durationDays": "2", "requiresRule": "permit",
                 "transfers": [{"fromAccount": "stock", "toAccount": "b_stock", "amount": "$quantity"},
                               {"fromAccount": "b_cash", "toAccount": "a_cash", "amount": "$price"}]}, actors=("b",),
                 inputs={"quantity": {"type": "decimal", "required": True, "min": "0"},
                         "price": {"type": "decimal", "required": True, "min": "0"}}),
        template("restrict", "policy", {"ruleId": "permit", "value": False, "durationDays": "2",
                                         "authorityIds": ["institution"]}, actors=("a", "institution")),
        template("vote", "vote", {"motionId": "program", "weights": {"a": "45", "b": "30", "c": "25"},
                 "threshold": "51", "fromAccount": "treasury", "toAccount": "sink", "cost": "60",
                 "targetRule": "program", "ruleValue": True, "mandateRule": "mandate"}, actors=("a", "b", "c"),
                 inputs={"support": {"type": "boolean", "required": True}}),
        template("say", "message", {}, actors=("a", "b", "c", "institution"),
                 inputs={"text": {"type": "string", "required": True}}),
        template("breach", "breach", {"penaltyFromAccount": "a_cash", "penaltyToAccount": "b_cash", "penalty": "2",
                 "relationId": "trust", "relationValue": "damaged"},
                 inputs={"commitmentId": {"type": "string", "required": True}}),
        *actions,
    ]
    actors = [{"actorId": aid, "name": aid, "objectives": ["retain resources"], "values": ["independence"],
               "incentives": [], "constraints": [], "beliefs": [], "evidenceGrade": "scenario-assumption",
               "capabilities": [t["templateId"] for t in catalog if aid in t["actorIds"]], "basis": deepcopy(BASIS)}
              for aid in ("a", "b", "c", "institution")]
    return validate_spec({"schemaVersion": "simulation-world-spec/v1", "engine": "world-v1",
        "simulationId": "sim_kernel", "generationId": "generation_kernel", "actors": actors,
        "periods": [{"start": add_days(START, i), "end": add_days(START, i + 1)} for i in range(periods)],
        "initialState": {"accounts": accounts,
                         "metrics": {"capacity": record(kind="rate", unit="goods_per_day", value="4"),
                                     "limit": record(kind="rate", unit="goods_per_day", value="7")},
                         "rules": {"permit": record(value=True), "mandate": record(value=True), "program": record(value=False)},
                         "relations": {"trust": record(value="normal")}},
        "actionCatalog": catalog, "flows": flows or [], "scheduledEvents": scheduled or []})


def action(tid, *, operation="execute", parameters=None, **fields):
    return {"templateId": tid, "operation": operation, "parameters": parameters or {}, **fields}


def decision(spec, snapshot, aid, intents=(), *, phase="proposal", updates=None):
    observation = build_observation(spec, snapshot, aid, snapshot["round"] + 1, phase)
    return validate_decision(spec, {"actorId": aid, "observationId": observation["observationId"],
                                   "intents": list(intents), "stateUpdates": updates or {}}, aid, observation, phase=phase)


def response(spec, staged, aid, offer, operation="accept", parameters=None, **fields):
    return decision(spec, staged, aid, [action(offer["templateId"], operation=operation,
        parameters=parameters, interactionId=offer["interactionId"], termsVersion=offer["termsVersion"], **fields)], phase="response")


def order_decision(spec, state, **parameters):
    return decision(spec, state, "b", [action("order", operation="propose", parameters=parameters or {"quantity": "7", "price": "5"})])


def advance(spec, state, decisions=()):
    return resolve_round(spec, state, list(decisions), state["round"] + 1)


def offered(spec, state):
    proposal = order_decision(spec, state)
    staged = stage_interactions(spec, state, [proposal], state["round"] + 1)
    offer = next(v for v in staged["interactions"].values() if v["status"] == "pending")
    return proposal, staged, offer


def production():
    return record(flowId="production", sourceAccount="raw", targetAccount="stock", rateMetric="capacity", limitMetric="limit")


def test_investment_debits_now_completes_at_two_days_and_flows_follow_capacity():
    spec = fixture(flows=[production()])
    initial = initialize_world(spec)
    first = advance(spec, initial, [decision(spec, initial, "a", [action("expand")])])
    state = first["snapshot"]
    assert initial["accounts"]["a_cash"]["balance"] == "10"
    assert state["accounts"]["a_cash"]["balance"] == "4"
    assert state["accounts"]["sink"]["balance"] == "6"
    assert state["metrics"]["capacity"]["value"] == "4"
    assert state["accounts"]["stock"]["balance"] == "14"
    second = advance(spec, state)
    assert second["snapshot"]["metrics"]["capacity"]["value"] == "7"
    assert second["snapshot"]["accounts"]["stock"]["balance"] == "18"
    third = advance(spec, second["snapshot"])
    assert third["snapshot"]["accounts"]["stock"]["balance"] == "25"
    assert sum(e["kind"] == "commitment_settled" for r in (first, second, third) for e in r["events"]) == 1


def test_half_period_completion_integrates_only_remaining_capacity_and_input_limit():
    spec = fixture(duration="0.5", flows=[production()])
    spec["initialState"]["metrics"]["limit"]["value"] = "5"
    state = initialize_world(spec)
    result = advance(spec, state, [decision(spec, state, "a", [action("expand")])])
    assert result["snapshot"]["accounts"]["stock"]["balance"] == "14.5"
    flows = [e["details"] for e in result["events"] if e["kind"] == "flow_transfer"]
    assert [f["amount"] for f in flows] == ["2", "2.5"]
    assert flows[0]["end"] == flows[1]["start"] == add_days(START, "0.5")


def test_unaffordable_investment_and_announcement_never_add_capacity():
    spec = fixture(budget="5")
    state = initialize_world(spec)
    result = advance(spec, state, [decision(spec, state, "a", [action("expand"), action("say", parameters={"text": "We doubled capacity"})])])
    assert [r["accepted"] for r in result["resolutions"]] == [False, True]
    assert result["snapshot"]["accounts"] == state["accounts"]
    assert result["snapshot"]["metrics"] == state["metrics"]
    assert not result["snapshot"]["commitments"]


def test_beyond_horizon_obligation_remains_pending():
    spec = fixture(duration="10", periods=1)
    state = initialize_world(spec)
    result = advance(spec, state, [decision(spec, state, "a", [action("expand")])])
    commitment = next(iter(result["snapshot"]["commitments"].values()))
    assert commitment["status"] == "pending"
    assert commitment["dueAt"] == add_days(START, 10)
    assert result["snapshot"]["metrics"]["capacity"]["value"] == "4"


def test_scarce_transfers_are_atomic_ordered_and_replay_exact_without_mutation():
    spec = fixture(template("give_c", "transfer", {"fromAccount": "a_cash", "toAccount": "c_cash", "amount": "7"}, actors=("c",)))
    next(a for a in spec["actors"] if a["actorId"] == "c")["controlledAccounts"] = ["a_cash"]
    state = initialize_world(spec)
    state["revision"] = "store-owned-revision"
    decisions = [decision(spec, state, "c", [action("give_c")]), decision(spec, state, "a", [action("give", parameters={"amount": "7"})])]
    before = deepcopy((spec, state, decisions))
    forward = advance(spec, state, decisions)
    reverse = advance(spec, state, list(reversed(decisions)))
    assert forward == reverse
    assert (spec, state, decisions) == before
    assert "revision" not in forward["snapshot"]
    assert forward["snapshot"]["accounts"]["a_cash"]["balance"] == "3"
    assert forward["snapshot"]["accounts"]["c_cash"]["balance"] == "0"
    assert [(r["actorId"], r["accepted"]) for r in forward["resolutions"]] == [("a", True), ("c", False)]
    assert "3" not in forward["resolutions"][1]["explanation"]


@pytest.mark.parametrize("amount", ["-1", "NaN", "Infinity", 1.1])
def test_invalid_amount_never_mutates_accounts(amount):
    spec = fixture()
    state = initialize_world(spec)
    raw = decision(spec, state, "a", [action("give", parameters={"amount": "1"})])
    raw["intents"][0]["parameters"]["amount"] = amount
    result = advance(spec, state, [raw])
    assert result["snapshot"]["accounts"] == state["accounts"]
    assert result["resolutions"][0]["accepted"] is False
    assert not result["events"]


def test_duplicate_receipts_fail_round_and_input_ids_cannot_override_config():
    spec = fixture()
    state = initialize_world(spec)
    d = decision(spec, state, "a", [action("give", parameters={"amount": "1", "fromAccount": "b_cash"})])
    result = advance(spec, state, [d])
    assert result["resolutions"][0]["code"] == "invalid_input"
    assert result["snapshot"]["accounts"] == state["accounts"]
    with pytest.raises(WorldError, match="one decision slot"):
        advance(spec, state, [d, d])


def test_atomic_bundle_rolls_back_first_success_and_events():
    spec = fixture()
    state = initialize_world(spec)
    d = decision(spec, state, "a", [action("give", parameters={"amount": "7"}, bundleId="pair"),
                                     action("give", parameters={"amount": "7"}, bundleId="pair")])
    result = advance(spec, state, [d])
    assert result["snapshot"]["accounts"] == state["accounts"]
    assert not result["events"]
    assert [r["code"] for r in result["resolutions"]] == ["bundle_rejected", "bundle_rejected"]


def test_staging_preserves_physics_and_exact_consent_reserves_then_settles():
    spec = fixture()
    state = initialize_world(spec)
    proposal, staged, offer = offered(spec, state)
    for key in ("accounts", "metrics", "rules", "commitments", "actorStates", "round", "simulatedAt", "appliedEvents"):
        assert staged[key] == state[key]
    assert offer["interactionId"] == stable_id(spec["generationId"], proposal["intents"][0]["intentId"], "offer")
    result = advance(spec, state, [proposal, response(spec, staged, "a", offer)])
    assert all(r["accepted"] for r in result["resolutions"])
    next_state = result["snapshot"]
    assert next_state["accounts"]["stock"]["reserved"] == "7"
    assert next_state["accounts"]["b_cash"]["reserved"] == "5"
    settled = advance(spec, next_state)["snapshot"]
    assert settled["accounts"]["stock"]["balance"] == "3"
    assert settled["accounts"]["stock"]["reserved"] == "0"
    assert settled["accounts"]["b_stock"]["balance"] == "7"
    assert settled["accounts"]["a_cash"]["balance"] == "15"
    assert advance(spec, settled)["snapshot"]["accounts"] == settled["accounts"]


def test_stale_terms_and_joint_infeasibility_leave_no_partial_acceptance():
    spec = fixture()
    state = initialize_world(spec)
    proposal, staged, offer = offered(spec, state)
    stale = response(spec, staged, "a", offer)
    stale["intents"][0]["termsVersion"] = 999
    result = advance(spec, state, [proposal, stale])
    assert result["resolutions"][-1]["code"] == "stale_terms"
    assert result["snapshot"]["accounts"] == state["accounts"]
    proposal = order_decision(spec, state, quantity="11", price="5")
    staged = stage_interactions(spec, state, [proposal], 1)
    offer = next(iter(staged["interactions"].values()))
    result = advance(spec, state, [proposal, response(spec, staged, "a", offer)])
    assert result["resolutions"][-1]["code"] == "insufficient_resources"
    assert result["snapshot"]["accounts"] == state["accounts"]
    assert result["snapshot"]["interactions"][offer["interactionId"]]["acceptedBy"] == []
    assert result["snapshot"]["commitments"] == {}


def test_every_counterparty_must_consent_before_any_hold():
    spec = fixture()
    order = next(t for t in spec["actionCatalog"] if t["templateId"] == "order")
    order["parameters"]["recipientIds"] = ["a", "c"]
    state = initialize_world(spec)
    proposal, staged, offer = offered(spec, state)
    partial = advance(spec, state, [proposal, response(spec, staged, "a", offer)])
    assert partial["snapshot"]["accounts"] == state["accounts"]
    assert partial["snapshot"]["interactions"][offer["interactionId"]]["acceptedBy"] == ["a"]
    completed = advance(spec, partial["snapshot"], [response(spec, partial["snapshot"], "c", offer)])
    assert completed["snapshot"]["accounts"]["stock"]["reserved"] == "7"


def test_delay_defer_counter_and_expiry_preserve_durable_exact_terms():
    spec = fixture()
    order = next(t for t in spec["actionCatalog"] if t["templateId"] == "order")
    order["parameters"].update(messageDelayDays="1", offerTtlDays="3")
    state = initialize_world(spec)
    proposal, staged, offer = offered(spec, state)
    # Construct a normalized hostile early response using a legitimate later menu.
    early = deepcopy(proposal)
    early.update(actorId="a", phase="response", decisionId="early")
    early["intents"] = [{**action("order", operation="accept", interactionId=offer["interactionId"], termsVersion=1),
                         "actorId": "a", "phase": "response", "priority": 0, "intentId": "early_intent"}]
    result = advance(spec, state, [proposal, early])
    assert result["resolutions"][-1]["code"] == "undelivered_offer"
    state = result["snapshot"]
    deferred = advance(spec, state, [response(spec, state, "a", offer, "defer")])["snapshot"]
    assert deferred["interactions"][offer["interactionId"]]["lastResponseRound"] == 2
    counter = response(spec, deferred, "a", offer, "counter", {"quantity": "2", "price": "4"})
    result = advance(spec, deferred, [counter])
    old = result["snapshot"]["interactions"][offer["interactionId"]]
    new = result["snapshot"]["interactions"][old["supersededBy"]]
    assert old["status"] == "superseded"
    assert new["recipientIds"] == ["b"] and new["termsVersion"] == 2
    assert new["terms"] == {"quantity": "2", "price": "4"}
    assert new["deliverAt"] == add_days(START, 3)
    assert result["snapshot"]["accounts"] == state["accounts"]
    accepted = advance(spec, result["snapshot"], [response(spec, result["snapshot"], "b", new)])
    assert accepted["snapshot"]["accounts"]["stock"]["reserved"] == "2"


def test_withdrawn_and_expired_offers_cannot_settle():
    spec = fixture()
    order = next(t for t in spec["actionCatalog"] if t["templateId"] == "order")
    order["parameters"]["offerTtlDays"] = "1"
    state = initialize_world(spec)
    proposal, staged, offer = offered(spec, state)
    result = advance(spec, state, [proposal])
    assert result["snapshot"]["interactions"][offer["interactionId"]]["status"] == "expired"
    spec = fixture()
    state = initialize_world(spec)
    proposal, staged, offer = offered(spec, state)
    state = advance(spec, state, [proposal])["snapshot"]
    withdraw = decision(spec, state, "b", [action("order", operation="withdraw", interactionId=offer["interactionId"], termsVersion=1)])
    accept = response(spec, state, "a", offer)
    result = advance(spec, state, [withdraw, accept])
    assert result["snapshot"]["interactions"][offer["interactionId"]]["status"] == "withdrawn"
    assert result["resolutions"][-1]["code"] == "closed_offer"
    assert result["snapshot"]["accounts"] == state["accounts"]


def test_authority_delay_and_grandfathering_of_accepted_orders():
    spec = fixture()
    state = initialize_world(spec)
    denied = advance(spec, state, [decision(spec, state, "a", [action("restrict")])])
    assert denied["resolutions"][0]["code"] == "unauthorized_policy"
    proposal, staged, offer = offered(spec, state)
    policy = decision(spec, state, "institution", [action("restrict")])
    result = advance(spec, state, [proposal, policy, response(spec, staged, "a", offer)])
    assert result["snapshot"]["rules"]["permit"]["value"] is True
    later = advance(spec, result["snapshot"])["snapshot"]
    assert later["rules"]["permit"]["value"] is False
    assert later["accounts"]["b_stock"]["balance"] == "7"
    proposal, staged, offer = offered(spec, later)
    denied = advance(spec, later, [proposal, response(spec, staged, "a", offer)])
    assert denied["resolutions"][-1]["code"] == "rule_ineligible"


def test_independent_votes_and_promises_and_institutional_treasury():
    spec = fixture(template("steal", "transfer", {"fromAccount": "treasury", "toAccount": "a_cash", "amount": "1"}, actors=("institution",)))
    state = initialize_world(spec)
    first = advance(spec, state, [decision(spec, state, "a", [action("vote", parameters={"support": True})]),
            decision(spec, state, "b", [action("say", parameters={"text": "I promise to support"})]),
            decision(spec, state, "institution", [action("steal")])])
    assert first["snapshot"]["accounts"]["treasury"]["balance"] == "80"
    assert first["snapshot"]["rules"]["program"]["value"] is False
    assert first["resolutions"][-1]["code"] == "institutional_resource"
    state = first["snapshot"]
    second = advance(spec, state, [decision(spec, state, "b", [action("vote", parameters={"support": True})])])
    assert second["snapshot"]["accounts"]["treasury"]["balance"] == "20"
    assert second["snapshot"]["rules"]["program"]["value"] is True
    state = second["snapshot"]
    repeated = advance(spec, state, [decision(spec, state, "a", [action("vote", parameters={"support": True})])])
    assert repeated["resolutions"][0]["code"] == "motion_closed"
    assert repeated["snapshot"]["accounts"] == state["accounts"]


@pytest.mark.parametrize("invalid_mandate", [False, True])
def test_vote_funding_or_mandate_failure_cannot_execute(invalid_mandate):
    spec = fixture()
    spec["initialState"]["rules"]["mandate"]["value"] = not invalid_mandate
    spec["initialState"]["accounts"]["treasury"]["balance"] = "50"
    state = initialize_world(spec)
    result = advance(spec, state, [decision(spec, state, actor, [action("vote", parameters={"support": True})]) for actor in ("a", "b")])
    assert result["snapshot"]["accounts"] == state["accounts"]
    assert result["snapshot"]["rules"]["program"]["value"] is False
    assert result["resolutions"][-1]["code"] == ("invalid_mandate" if invalid_mandate else "insufficient_resources")


def test_breach_penalty_release_and_cancellation_once():
    spec = fixture()
    state = initialize_world(spec)
    proposal, staged, offer = offered(spec, state)
    state = advance(spec, state, [proposal, response(spec, staged, "a", offer)])["snapshot"]
    cid = next(iter(state["commitments"]))
    result = advance(spec, state, [decision(spec, state, "a", [action("breach", parameters={"commitmentId": cid})])])
    assert result["snapshot"]["accounts"]["stock"]["reserved"] == "0"
    assert result["snapshot"]["accounts"]["b_cash"]["reserved"] == "0"
    assert result["snapshot"]["accounts"]["a_cash"]["balance"] == "8"
    assert result["snapshot"]["accounts"]["b_stock"]["balance"] == "0"
    assert result["snapshot"]["relations"]["trust"]["value"] == "damaged"
    assert result["snapshot"]["commitments"][cid]["status"] == "breached"
    state = result["snapshot"]
    repeat = advance(spec, state, [decision(spec, state, "a", [action("breach", parameters={"commitmentId": cid})])])
    assert repeat["resolutions"][0]["code"] == "unavailable_obligation"
    assert repeat["snapshot"]["accounts"] == state["accounts"]


def test_unfunded_breach_cannot_release_reservations():
    spec = fixture(budget="1")
    state = initialize_world(spec)
    proposal, staged, offer = offered(spec, state)
    state = advance(spec, state, [proposal, response(spec, staged, "a", offer)])["snapshot"]
    cid = next(iter(state["commitments"]))
    # Move due date beyond this round with a longer declared agreement duration.
    # This fixture instead observes the rejection and eventual valid settlement.
    result = advance(spec, state, [decision(spec, state, "a", [action("breach", parameters={"commitmentId": cid})])])
    assert result["resolutions"][0]["code"] == "insufficient_resources"
    assert result["snapshot"]["commitments"][cid]["status"] == "settled"
    assert result["snapshot"]["accounts"]["b_stock"]["balance"] == "7"
    assert result["snapshot"]["accounts"]["a_cash"]["balance"] == "6"


def test_initial_and_midperiod_schedules_are_chronological_and_once_only():
    scheduled = [record(eventId="open", at=START, kind="metric_delta", parameters={"targetMetric": "capacity", "delta": "1"}),
                 record(eventId="half", at=add_days(START, "0.5"), kind="metric_delta", parameters={"targetMetric": "capacity", "delta": "2"}),
                 record(eventId="close", at=add_days(START, 1), kind="rule_set", parameters={"ruleId": "permit", "value": False})]
    spec = fixture(flows=[production()], scheduled=list(reversed(scheduled)))
    state = initialize_world(spec)
    assert state["metrics"]["capacity"]["value"] == "5"
    assert build_observation(spec, state, "b", 1)["world"]["metrics"]["capacity"]["value"] == "5"
    assert len(state["initialEvents"]) == 1
    result = advance(spec, state)
    assert result["snapshot"]["accounts"]["stock"]["balance"] == "16"
    assert result["snapshot"]["rules"]["permit"]["value"] is False
    assert [e["at"] for e in result["events"]] == sorted(e["at"] for e in result["events"])
    assert advance(spec, result["snapshot"])["snapshot"]["metrics"]["capacity"]["value"] == "7"
    with pytest.raises(WorldError, match="Initialize opening effects"):
        advance(spec, initial_snapshot(spec))


def test_scheduled_transfer_ties_use_event_identity_and_flow_cannot_spend_holds():
    spec = fixture(scheduled=[record(eventId="z", at=add_days(START, "0.5"), kind="transfer",
                                    parameters={"fromAccount": "a_cash", "toAccount": "b_cash", "amount": "5"}),
                             record(eventId="a", at=add_days(START, "0.5"), kind="transfer",
                                    parameters={"fromAccount": "b_cash", "toAccount": "a_cash", "amount": "5"})])
    state = initialize_world(spec)
    result = advance(spec, state)
    expected = [stable_id(spec["generationId"], key, "scheduled_transfer") for key in ("a", "z")]
    assert [e["eventId"] for e in result["events"]] == expected
    spec = fixture(flows=[record(flowId="consume", sourceAccount="stock", targetAccount="b_stock", ratePerDay="10")])
    state = initialize_world(spec)
    proposal, staged, offer = offered(spec, state)
    result = advance(spec, state, [proposal, response(spec, staged, "a", offer)])
    assert result["snapshot"]["accounts"]["stock"]["balance"] == "7"
    assert result["snapshot"]["accounts"]["stock"]["reserved"] == "7"
    assert result["snapshot"]["accounts"]["b_stock"]["balance"] == "3"


@pytest.mark.parametrize("mutation", [
    lambda s: s["actionCatalog"][1]["parameters"].update(undisclosedPower=True),
    lambda s: s["actionCatalog"][1]["parameters"].update(toAccount="stock"),
    lambda s: s["actionCatalog"][1]["parameters"].pop("durationDays"),
    lambda s: s["actionCatalog"][1]["parameters"].update(targetMetric="missing"),
    lambda s: s["flows"].append(record(flowId="bad", sourceAccount="raw", targetAccount="sink", ratePerDay="1")),
    lambda s: s["scheduledEvents"].append(record(eventId="old", at="2029-01-01T00:00:00Z", kind="rule_set", parameters={"ruleId": "permit", "value": False})),
])
def test_invalid_authoritative_mechanisms_fail_before_any_actor_action(mutation):
    spec = fixture()
    mutation(spec)
    before = deepcopy(spec)
    with pytest.raises(WorldError):
        initialize_world(spec)
    assert spec == before


def test_beliefs_have_observation_provenance_and_priorities_require_visible_predeclared_trigger():
    spec = fixture()
    spec["actors"][0]["priorityRules"] = [{"ruleId": "permit_priority", "priorityId": "secure_permit", "value": "high",
        "trigger": {"section": "rules", "recordId": "permit", "value": True}, "basis": deepcopy(BASIS)}]
    state = initialize_world(spec)
    d = decision(spec, state, "a", updates={"beliefs": [{"claim": "Permit is valid", "confidence": "0.8"}],
        "priorityChanges": [{"ruleId": "permit_priority", "priorityId": "secure_permit", "value": "high"}]})
    result = advance(spec, state, [d])
    belief = result["snapshot"]["actorStates"]["a"]["beliefs"][0]
    assert belief["observationId"] == d["observationId"]
    assert belief["basis"]["refs"] == [d["observationId"], d["decisionId"]]
    assert result["snapshot"]["actorStates"]["a"]["priorityChanges"][0]["value"] == "high"
    assert result["snapshot"]["actorStates"]["b"] == state["actorStates"]["b"]
    assert spec["actors"][0]["objectives"] == ["retain resources"]
    bad = deepcopy(d)
    bad["stateUpdates"]["priorityChanges"][0]["value"] = "anything"
    with pytest.raises(WorldError) as error:
        advance(spec, state, [bad])
    assert error.value.code == "unauthorized_priority"
    bad = deepcopy(d)
    bad["stateUpdates"]["beliefs"][0]["observationId"] = "not-observed"
    with pytest.raises(WorldError) as error:
        advance(spec, state, [bad])
    assert error.value.code == "invalid_actor_provenance"
    spec["initialState"]["rules"]["permit"]["visibility"] = {"kind": "analyst"}
    hidden = initialize_world(spec)
    with pytest.raises(WorldError, match="Priority trigger"):
        decision(spec, hidden, "a", updates=d["stateUpdates"])
    hidden_decision = decision(spec, hidden, "a")
    hidden_decision['stateUpdates'] = deepcopy(d['stateUpdates'])
    with pytest.raises(WorldError) as error:
        advance(spec, hidden, [hidden_decision])
    assert error.value.code == "unauthorized_priority"


def test_same_round_new_rule_cannot_retroactively_authorize_priority_change():
    spec = fixture()
    spec["actors"][0]["priorityRules"] = [{"ruleId": "after_restriction", "priorityId": "reroute", "value": "high",
        "trigger": {"section": "rules", "recordId": "permit", "value": False}, "basis": deepcopy(BASIS)}]
    next(t for t in spec["actionCatalog"] if t["templateId"] == "restrict")["parameters"]["durationDays"] = "0"
    state = initialize_world(spec)
    updates = {"priorityChanges": [{"ruleId": "after_restriction", "priorityId": "reroute", "value": "high"}]}
    with pytest.raises(WorldError, match="Priority trigger"):
        decision(spec, state, "a", updates=updates)
    actor_decision = decision(spec, state, 'a')
    actor_decision['stateUpdates'] = updates
    decisions = [actor_decision, decision(spec, state, "institution", [action("restrict")])]
    with pytest.raises(WorldError) as error:
        advance(spec, state, decisions)
    assert error.value.code == "unauthorized_priority"
    assert state["rules"]["permit"]["value"] is True


def test_hidden_prerequisite_does_not_change_staged_recipient_observation():
    permitted = fixture()
    permitted["initialState"]["rules"]["permit"]["visibility"] = {"kind": "analyst"}
    denied = deepcopy(permitted)
    denied["initialState"]["rules"]["permit"]["value"] = False
    observations = []
    for spec in (permitted, denied):
        state = initialize_world(spec)
        _, staged, _ = offered(spec, state)
        observations.append(build_observation(spec, staged, "a", 1, "response"))
    assert observations[0] == observations[1]


def test_fixed_operating_terms_are_visible_and_bound_to_exact_consent():
    spec = fixture()
    order = next(t for t in spec["actionCatalog"] if t["templateId"] == "order")
    order["parameters"]["transfers"][1]["amount"] = "8"
    state = initialize_world(spec)
    proposal, staged, offer = offered(spec, state)
    obligations = build_observation(spec, staged, "a", 1, "response")["inbox"][0]["obligations"]
    assert obligations["durationDays"] == "2"
    assert obligations["transfers"][1] == {"fromAccount": "b_cash", "toAccount": "a_cash", "amount": "8",
        "fromActorId": "b", "toActorId": "a", "unit": "currency"}
    state = advance(spec, state, [proposal])["snapshot"]
    corrupted = deepcopy(state)
    corrupted["interactions"][offer["interactionId"]]["obligations"]["transfers"][1]["amount"] = "1"
    result = advance(spec, corrupted, [response(spec, corrupted, "a", offer)])
    assert result["resolutions"][0]["code"] == "stale_terms"
    assert result["snapshot"]["accounts"] == corrupted["accounts"]


def test_malformed_offer_identity_is_a_structured_rejection():
    spec = fixture()
    state = initialize_world(spec)
    proposal, staged, offer = offered(spec, state)
    d = response(spec, staged, "a", offer)
    d["intents"][0]["interactionId"] = []
    result = advance(spec, state, [proposal, d])
    assert result["resolutions"][-1]["code"] == "invalid_input"
    assert result["snapshot"]["accounts"] == state["accounts"]


def test_fractional_clock_with_unrepresentable_flow_is_rejected_before_dispatch():
    spec = fixture(flows=[record(flowId="one", sourceAccount="raw", targetAccount="stock", ratePerDay="1")],
        scheduled=[record(eventId="second", at="2030-01-01T00:00:01Z", kind="rule_set", parameters={"ruleId": "permit", "value": False})])
    with pytest.raises(WorldError) as error:
        initialize_world(spec)
    assert error.value.code == "invalid_flow_precision"


def test_immediate_agreement_event_sequence_records_consent_before_settlement():
    spec = fixture()
    next(t for t in spec["actionCatalog"] if t["templateId"] == "order")["parameters"]["durationDays"] = "0"
    state = initialize_world(spec)
    proposal, staged, offer = offered(spec, state)
    result = advance(spec, state, [proposal, response(spec, staged, "a", offer)])
    assert [e["kind"] for e in result["events"]] == ["agreement_accepted", "offer_accept", "commitment_settled"]


def test_rate_metric_units_are_explicitly_per_day_not_stock_units():
    spec = fixture(flows=[production()])
    spec["initialState"]["metrics"]["capacity"]["unit"] = "goods"
    with pytest.raises(WorldError) as error:
        initialize_world(spec)
    assert error.value.code == "invalid_mechanism"


def test_representable_flow_with_trailing_decimal_zeroes_remains_exact():
    spec = fixture(flows=[record(flowId="fixed", sourceAccount="raw", targetAccount="stock", ratePerDay="1.000000000000")],
        scheduled=[record(eventId="half", at=add_days(START, "0.5"), kind="rule_set", parameters={"ruleId": "permit", "value": False})])
    state = initialize_world(spec)
    result = advance(spec, state)
    assert result["snapshot"]["accounts"]["stock"]["balance"] == "11"
    assert [e["details"]["amount"] for e in result["events"] if e["kind"] == "flow_transfer"] == ["0.5", "0.5"]


def test_mixed_withdrawal_spending_bundle_cannot_remove_response_opportunity():
    spec = fixture(template("b_transfer", "transfer", {"fromAccount": "b_cash", "toAccount": "sink", "amount": "100"}, actors=("b",)))
    state = initialize_world(spec)
    proposal, _, _ = offered(spec, state)
    state = advance(spec, state, [proposal])["snapshot"]
    offer = next(iter(state["interactions"].values()))
    mixed = decision(spec, state, "b", [action("order", operation="withdraw", bundleId="mixed",
        interactionId=offer["interactionId"], termsVersion=offer["termsVersion"]), action("b_transfer", bundleId="mixed")])
    staged = stage_interactions(spec, state, [mixed], 2)
    inbox = build_observation(spec, staged, "a", 2, "response")["inbox"]
    assert [item["interactionId"] for item in inbox] == [offer["interactionId"]]
    assert staged["interactions"] == state["interactions"]
    result = advance(spec, state, [mixed, response(spec, staged, "a", offer)])
    assert [r["accepted"] for r in result["resolutions"]] == [False, False, True]
    assert result["snapshot"]["accounts"]["b_cash"]["reserved"] == "5"
    assert result["snapshot"]["accounts"]["sink"]["balance"] == "0"


@pytest.mark.parametrize("midpoint", [False, True])
def test_competing_flows_require_declared_allocation_even_with_noop_event(midpoint):
    events = [record(eventId="noop", at=add_days(START, "0.5"), kind="rule_set",
                     parameters={"ruleId": "permit", "value": True})] if midpoint else []
    spec = fixture(flows=[record(flowId="first", sourceAccount="a_cash", targetAccount="b_cash", ratePerDay="10"),
                          record(flowId="second", sourceAccount="a_cash", targetAccount="c_cash", ratePerDay="10")], scheduled=events)
    with pytest.raises(WorldError, match="Competing flows require an explicit allocation"):
        initialize_world(spec)


def test_coupled_flows_require_explicit_process_instead_of_interval_dependent_order():
    spec = fixture(flows=[record(flowId="first", sourceAccount="raw", targetAccount="stock", ratePerDay="10"),
                          record(flowId="second", sourceAccount="stock", targetAccount="b_stock", ratePerDay="10")])
    with pytest.raises(WorldError, match="Coupled flows require an explicit process"):
        initialize_world(spec)


def test_independent_flow_outcomes_are_invariant_to_unrelated_boundaries():
    spec = fixture(flows=[record(flowId="money", sourceAccount="a_cash", targetAccount="b_cash", ratePerDay="20"),
                          record(flowId="goods", sourceAccount="raw", targetAccount="stock", ratePerDay="10")])
    plain = advance(spec, initialize_world(spec))["snapshot"]
    spec["scheduledEvents"] = [record(eventId="noop", at=add_days(START, "0.5"), kind="rule_set",
                                     parameters={"ruleId": "permit", "value": True})]
    split = advance(spec, initialize_world(spec))["snapshot"]
    assert plain["accounts"] == split["accounts"]


def test_decisive_vote_event_precedes_motion_execution():
    spec = fixture()
    state = initialize_world(spec)
    state = advance(spec, state, [decision(spec, state, "a", [action("vote", parameters={"support": True})])])["snapshot"]
    result = advance(spec, state, [decision(spec, state, "b", [action("vote", parameters={"support": True})])])
    assert [event["kind"] for event in result["events"]] == ["vote_accepted", "motion_passed"]


def test_readiness_rejects_empty_policy_authority_before_dispatch():
    spec = fixture()
    next(t for t in spec["actionCatalog"] if t["templateId"] == "restrict")["parameters"]["authorityIds"] = []
    before = deepcopy(spec)
    for admission in (validate_mechanisms, initialize_world):
        with pytest.raises(WorldError, match="Policy authority must be explicit and nonempty") as error:
            admission(spec)
        assert error.value.code == "invalid_mechanism"
    assert spec == before


@pytest.mark.parametrize("template_id,parameter", [
    ("expand", "requiresRule"), ("order", "requiresRule"), ("vote", "mandateRule"),
])
@pytest.mark.parametrize("missing", [False, True])
def test_readiness_requires_known_prerequisite_and_mandate_values(template_id, parameter, missing):
    spec = fixture()
    spec["initialState"]["rules"]["unknown_dependency"] = record(value=None)
    if missing:
        spec["initialState"]["rules"]["unknown_dependency"].pop("value")
    next(t for t in spec["actionCatalog"] if t["templateId"] == template_id)["parameters"][parameter] = "unknown_dependency"
    before = deepcopy(spec)
    for admission in (validate_mechanisms, initialize_world):
        with pytest.raises(WorldError, match="prerequisite or mandate rule must have a specified initial value") as error:
            admission(spec)
        assert error.value.code == "invalid_mechanism"
    assert spec == before


@pytest.mark.parametrize("dependency", ["investment", "scheduled_delta", "flow_rate", "flow_limit"])
@pytest.mark.parametrize("missing", [False, True])
def test_readiness_requires_known_numeric_dependencies(dependency, missing):
    spec = fixture()
    spec["initialState"]["metrics"]["unknown_dependency"] = record(kind="rate", unit="goods_per_day", value=None, valueStatus="unknown")
    if missing:
        spec["initialState"]["metrics"]["unknown_dependency"].pop("value")
    if dependency == "investment":
        next(t for t in spec["actionCatalog"] if t["templateId"] == "expand")["parameters"]["targetMetric"] = "unknown_dependency"
    elif dependency == "scheduled_delta":
        spec["scheduledEvents"] = [record(eventId="needs_baseline", at=add_days(START, 1), kind="metric_delta",
                                         parameters={"targetMetric": "unknown_dependency", "delta": "1"})]
    else:
        flow = production()
        flow["rateMetric" if dependency == "flow_rate" else "limitMetric"] = "unknown_dependency"
        spec["flows"] = [flow]
    before = deepcopy(spec)
    for admission in (validate_mechanisms, initialize_world):
        with pytest.raises(WorldError, match="required numeric metric must have a specified initial value") as error:
            admission(spec)
        assert error.value.code == "invalid_mechanism"
    assert spec == before


def test_known_false_prerequisite_is_ready_and_future_policy_enables_investment():
    spec = fixture()
    spec["initialState"]["rules"]["permit"]["value"] = False
    next(t for t in spec["actionCatalog"] if t["templateId"] == "restrict")["parameters"].update(value=True, durationDays="1")
    validate_mechanisms(spec)
    state = initialize_world(spec)
    first = advance(spec, state, [decision(spec, state, "a", [action("expand")]),
                                  decision(spec, state, "institution", [action("restrict")])])
    assert first["resolutions"][0]["code"] == "rule_ineligible"
    assert first["snapshot"]["accounts"]["a_cash"]["balance"] == "10"
    assert first["snapshot"]["rules"]["permit"]["value"] is True
    state = first["snapshot"]
    second = advance(spec, state, [decision(spec, state, "a", [action("expand")])])
    assert second["resolutions"][0]["accepted"] is True
    assert second["snapshot"]["accounts"]["a_cash"]["balance"] == "4"


def test_known_false_mandate_is_ready_and_future_policy_enables_voting():
    spec = fixture(template("enable_mandate", "policy", {"ruleId": "mandate", "value": True, "durationDays": "1",
                                                          "authorityIds": ["institution"]}, actors=("institution",)))
    spec["initialState"]["rules"]["mandate"]["value"] = False
    validate_mechanisms(spec)
    state = initialize_world(spec)
    first = advance(spec, state, [decision(spec, state, "a", [action("vote", parameters={"support": True})]),
                                  decision(spec, state, "institution", [action("enable_mandate")])])
    assert first["resolutions"][0]["code"] == "invalid_mandate"
    assert first["snapshot"]["accounts"]["treasury"]["balance"] == "80"
    assert first["snapshot"]["rules"]["mandate"]["value"] is True
    state = first["snapshot"]
    second = advance(spec, state, [decision(spec, state, aid, [action("vote", parameters={"support": True})]) for aid in ("a", "b")])
    assert all(r["accepted"] for r in second["resolutions"])
    assert second["snapshot"]["accounts"]["treasury"]["balance"] == "20"


def test_readiness_preserves_unknown_unused_metrics_and_rule_set_targets():
    spec = fixture(template("set_unknown", "policy", {"ruleId": "unknown_target", "value": False, "durationDays": "1",
                                                       "authorityIds": ["institution"]}, actors=("institution",)))
    spec["initialState"]["rules"]["unknown_target"] = record(value=None)
    spec["initialState"]["rules"]["scheduled_target"] = record(value=None)
    spec["initialState"]["metrics"]["unused_unknown"] = record(kind="quantity", unit="goods", value=None, valueStatus="unknown")
    spec["scheduledEvents"] = [record(eventId="set_initially_unknown", at=add_days(START, 1), kind="rule_set",
                                     parameters={"ruleId": "scheduled_target", "value": True})]
    validate_mechanisms(spec)
    state = initialize_world(spec)
    result = advance(spec, state, [decision(spec, state, "institution", [action("set_unknown")])])
    assert result["snapshot"]["rules"]["unknown_target"]["value"] is False
    assert result["snapshot"]["rules"]["scheduled_target"]["value"] is True
    assert result["snapshot"]["metrics"]["unused_unknown"]["value"] is None


def test_rejected_action_reason_reaches_own_next_prompt_without_rival_disclosure():
    spec = fixture(budget="5")
    spec["initialState"]["accounts"]["a_cash"]["visibility"] = {"kind": "actors", "actorIds": ["a"]}
    state = initialize_world(spec)
    d = decision(spec, state, "a", [action("expand")])
    before = deepcopy((spec, state, d))
    result = advance(spec, state, [d])
    own = build_observation(spec, result["snapshot"], "a", 2)
    rival = build_observation(spec, result["snapshot"], "b", 2)
    control = build_observation(spec, advance(spec, state)["snapshot"], "b", 2)
    receipt = own["privateState"]["lastActionResults"]
    assert receipt == result["resolutions"]
    assert receipt[0]["code"] == "insufficient_resources"
    assert receipt[0]["accepted"] is False
    assert receipt[0]["intentId"] == d["intents"][0]["intentId"]
    assert receipt[0]["explanation"] == "Action cannot be funded under the declared resource constraints"
    assert "balance" not in receipt[0]["explanation"]
    assert rival["privateState"]["lastActionResults"] == []
    assert rival == control
    assert (spec, state, d) == before
    own["privateState"]["lastActionResults"][0]["explanation"] = "changed by consumer"
    assert result["snapshot"]["actorStates"]["a"]["lastActionResults"][0]["explanation"] == result["resolutions"][0]["explanation"]


def test_same_private_feasibility_failure_returns_identical_generic_feedback():
    payloads = []
    for balance in ("0", "5"):
        spec = fixture()
        spec["initialState"]["accounts"]["b_cash"]["balance"] = balance
        spec["initialState"]["accounts"]["b_cash"]["visibility"] = {"kind": "actors", "actorIds": ["b"]}
        state = initialize_world(spec)
        proposal = order_decision(spec, state, quantity="7", price="6")
        staged = stage_interactions(spec, state, [proposal], 1)
        offer = next(iter(staged["interactions"].values()))
        result = advance(spec, state, [proposal, response(spec, staged, "a", offer)])
        payloads.append(build_observation(spec, result["snapshot"], "a", 2))
    assert payloads[0] == payloads[1]
    assert payloads[0]["privateState"]["lastActionResults"][0]["code"] == "insufficient_resources"


def test_feedback_retains_only_visible_event_records_and_ids_with_exact_replay():
    spec = fixture(scheduled=[
        record(eventId="public_change", at=add_days(START, "0.5"), kind="rule_set",
               parameters={"ruleId": "permit", "value": False}),
        record(eventId="private_change", at=add_days(START, "0.5"), kind="rule_set",
               parameters={"ruleId": "private_rule", "value": True}, visibility={"kind": "actors", "actorIds": ["a"]}),
        record(eventId="analyst_change", at=add_days(START, "0.5"), kind="rule_set",
               parameters={"ruleId": "analyst_rule", "value": True}, visibility={"kind": "analyst"}),
    ])
    spec["initialState"]["rules"]["private_rule"] = record(value=False, visibility={"kind": "actors", "actorIds": ["a"]})
    spec["initialState"]["rules"]["analyst_rule"] = record(value=False, visibility={"kind": "analyst"})
    state = initialize_world(spec)
    before = deepcopy((spec, state))
    first = advance(spec, state)
    replay = advance(spec, state)
    assert first == replay
    own = build_observation(spec, first["snapshot"], "a", 2)
    rival = build_observation(spec, first["snapshot"], "b", 2)
    visible = [e for e in first["events"] if e["visibility"]["kind"] != "analyst"]
    public = [e for e in first["events"] if e["visibility"]["kind"] == "public"]
    assert own["privateState"]["lastObservedEvents"] == visible
    assert own["privateState"]["observedEvents"] == [e["eventId"] for e in visible]
    assert rival["privateState"]["lastObservedEvents"] == public
    assert rival["privateState"]["observedEvents"] == [e["eventId"] for e in public]
    assert own["world"]["rules"]["private_rule"]["value"] is True
    assert "private_rule" not in rival["world"]["rules"]
    assert "analyst_rule" not in own["world"]["rules"]
    assert (spec, state) == before
    assert build_observation(spec, replay["snapshot"], "a", 2) == own
    own["privateState"]["lastObservedEvents"][0]["description"] = "changed by consumer"
    assert first["snapshot"]["actorStates"]["a"]["lastObservedEvents"] == visible


def test_feedback_survives_quiet_round_until_an_actor_can_observe_it():
    spec = fixture(budget="5", scheduled=[record(eventId="public_update", at=add_days(START, "0.5"), kind="rule_set",
                                                parameters={"ruleId": "program", "value": True})])
    spec["actors"][0]["cadence"] = 2
    state = initialize_world(spec)
    first = advance(spec, state, [decision(spec, state, "a", [action("expand")])])
    quiet = advance(spec, first["snapshot"])
    later = build_observation(spec, quiet["snapshot"], "a", 3)["privateState"]
    assert later["lastActionResults"] == first["resolutions"]
    assert later["lastObservedEvents"] == first["events"]
    assert later["observedEvents"] == [e["eventId"] for e in first["events"]]
    next_result = advance(spec, quiet["snapshot"], [decision(spec, quiet["snapshot"], "a", [action("wait")])])
    assert next_result["snapshot"]["actorStates"]["a"]["lastActionResults"] == next_result["resolutions"]


def test_event_feedback_is_capped_after_visibility_filter_and_hidden_events_do_not_evict():
    spec = fixture(scheduled=[
        record(eventId=f"public_{index}", at=add_days(START, "0.5"), kind="rule_set",
               parameters={"ruleId": "program", "value": bool(index % 2)}) for index in range(4)
    ])
    spec["limits"]["maxInboxItems"] = 2
    state = initialize_world(spec)
    first = advance(spec, state)
    private = build_observation(spec, first["snapshot"], "a", 2)["privateState"]
    assert private["lastObservedEvents"] == first["events"][-2:]
    assert private["observedEvents"] == [e["eventId"] for e in first["events"][-2:]]
    hidden = deepcopy(spec)
    hidden["initialState"]["rules"]["hidden_rule"] = record(value=False, visibility={"kind": "analyst"})
    hidden["scheduledEvents"].extend([
        record(eventId=f"z_hidden_{index}", at=add_days(START, "0.5"), kind="rule_set",
               parameters={"ruleId": "hidden_rule", "value": bool(index % 2)}, visibility={"kind": "analyst"}) for index in range(5)
    ])
    hidden_result = advance(hidden, initialize_world(hidden))
    assert build_observation(hidden, hidden_result["snapshot"], "a", 2) == build_observation(spec, first["snapshot"], "a", 2)


def test_action_feedback_keeps_both_phase_results_within_declared_cap():
    spec = fixture()
    spec["limits"]["maxIntentsPerPhase"] = 1
    state = initialize_world(spec)
    own = decision(spec, state, "a", [action("wait")])
    proposal, staged, offer = offered(spec, state)
    answer = response(spec, staged, "a", offer)
    result = advance(spec, state, [proposal, own, answer])
    private = build_observation(spec, result["snapshot"], "a", 2)["privateState"]
    expected = [r for r in result["resolutions"] if r["actorId"] == "a"]
    assert private["lastActionResults"] == expected
    assert len(expected) == spec["limits"]["maxIntentsPerPhase"] * 2
    assert all(r["actorId"] == "a" for r in private["lastActionResults"])


def test_visible_initial_effects_enter_first_observation_feedback():
    spec = fixture(scheduled=[record(eventId="initial_update", at=START, kind="rule_set",
                                    parameters={"ruleId": "program", "value": True})])
    state = initialize_world(spec)
    private = build_observation(spec, state, "a", 1)["privateState"]
    assert private["lastActionResults"] == []
    assert private["lastObservedEvents"] == state["initialEvents"]
    assert private["observedEvents"] == [e["eventId"] for e in state["initialEvents"]]


@pytest.mark.parametrize("kind", ["agreement", "message"])
def test_interaction_feedback_waits_for_delivery_then_survives_replay(kind):
    spec = fixture()
    template_id = "order" if kind == "agreement" else "say"
    next(t for t in spec["actionCatalog"] if t["templateId"] == template_id)["parameters"].update(messageDelayDays="3")
    state = initialize_world(spec)
    proposal = order_decision(spec, state) if kind == "agreement" else decision(spec, state, "b", [
        action("say", parameters={"text": "Delayed announcement"})])
    first = advance(spec, state, [proposal])
    sent = first["events"][0]
    own = build_observation(spec, first["snapshot"], "b", 2)
    early = build_observation(spec, first["snapshot"], "a", 2)
    assert sent in own["privateState"]["lastObservedEvents"]
    assert early["privateState"]["lastObservedEvents"] == []
    assert early["privateState"]["observedEvents"] == []
    assert early["inbox"] == [] and early["messages"] == []
    assert "pendingFeedbackEvents" not in early
    second = advance(spec, first["snapshot"])
    assert build_observation(spec, second["snapshot"], "a", 3)["privateState"]["lastObservedEvents"] == []
    third = advance(spec, second["snapshot"])
    assert third == advance(spec, deepcopy(second["snapshot"]))
    delivered = build_observation(spec, third["snapshot"], "a", 4)
    assert delivered["privateState"]["lastObservedEvents"] == [sent]
    assert delivered["privateState"]["observedEvents"] == [sent["eventId"]]
    assert third["snapshot"]["pendingFeedbackEvents"] == []
    assert delivered["inbox" if kind == "agreement" else "messages"]


def test_flow_feedback_does_not_disclose_private_noop_boundaries_or_evict_visible_memory():
    spec = fixture(flows=[record(flowId="steady", sourceAccount="raw", targetAccount="stock", ratePerDay="1")])
    spec["limits"]["maxInboxItems"] = 1
    state = initialize_world(spec)
    plain = advance(spec, state)
    hidden = deepcopy(spec)
    hidden["initialState"]["rules"]["private_noop"] = record(value=False, visibility={"kind": "analyst"})
    hidden["scheduledEvents"] = [record(eventId="hidden_midpoint", at=add_days(START, "0.5"), kind="rule_set",
        parameters={"ruleId": "private_noop", "value": False}, visibility={"kind": "analyst"})]
    split = advance(hidden, initialize_world(hidden))
    assert len([e for e in plain["events"] if e["kind"] == "flow_transfer"]) == 1
    assert len([e for e in split["events"] if e["kind"] == "flow_transfer"]) == 2
    for aid in ("a", "b", "c", "institution"):
        expected = build_observation(spec, plain["snapshot"], aid, 2)
        assert build_observation(hidden, split["snapshot"], aid, 2) == expected
        summary = expected["privateState"]["lastObservedEvents"]
        assert len(summary) == 1 and summary[0]["kind"] == "flow_summary"
        assert summary[0]["details"]["amount"] == "1"
        assert summary[0]["eventId"] in plain["snapshot"]["appliedEvents"]
        assert summary[0] in plain["events"]
        assert expected["privateState"]["observedEvents"] == [summary[0]["eventId"]]


def test_counteroffer_feedback_uses_new_offer_delivery_boundary():
    spec = fixture(periods=6)
    next(t for t in spec["actionCatalog"] if t["templateId"] == "order")["parameters"]["messageDelayDays"] = "2"
    state = initialize_world(spec)
    proposal, _, _ = offered(spec, state)
    state = advance(spec, state, [proposal])["snapshot"]
    state = advance(spec, state)["snapshot"]
    offer = next(iter(state["interactions"].values()))
    counter = response(spec, state, "a", offer, "counter", {"quantity": "2", "price": "3"})
    sent = advance(spec, state, [counter])
    receipt = next(event for event in sent["events"] if event["kind"] == "offer_counter")
    early = build_observation(spec, sent["snapshot"], "b", 4)
    assert receipt not in early["privateState"]["lastObservedEvents"]
    assert receipt["eventId"] not in early["privateState"]["observedEvents"]
    later = advance(spec, sent["snapshot"])
    delivered = build_observation(spec, later["snapshot"], "b", 5)
    assert receipt in delivered["privateState"]["lastObservedEvents"]
    assert delivered["inbox"][0]["terms"] == {"quantity": "2", "price": "3"}
