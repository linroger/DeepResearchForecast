"""Independent default-world commitment regression and calendar acceptance cases.

Execute only through the unchanged offline guard. Runtime harness imports are
lazy so pure contract checks do not initialize the OASIS loop.
"""

import asyncio
import copy
import json
import random
import re

import pytest

from app.services.agent_decision import (
    build_decision_prompt,
    build_option_menu,
    decision_memory_note,
    parse_decision,
)
from app.services.world_model import WorldModel
from app.services.world_update import run_world_round, validate_arbiter_update


_TERMS = "Exchange the audited tariff schedules before the next period ends."
_RATIONALE = "The audited schedule was delivered to the agreed counterparty this period."
_EXTRA_PLEDGE = "Invented bonus pledge to finance an unrelated conference."
_EXTRA_TERMS = "Invented side agreement to share unrelated conference funding."


def _world():
    return WorldModel.from_seed({
        "question": "Will the parties exchange audited schedules?",
        "actors": [
            {"agent_id": i, "name": f"Actor{i}", "agency_class": "firm",
             "capacity_per_round": 3}
            for i in range(3)
        ],
    })


def _period(round_num):
    return {"label": f"period-{round_num}"}


def _parse(world, actor_id, round_num, option_id, **raw):
    actor = world.actors[actor_id]
    return parse_decision(
        {"option_id": option_id, "scenario_commitment": "abstain", **raw},
        actor=actor, world=world,
        options=build_option_menu(actor, world, round_num),
        scenarios=(), round_num=round_num,
    )


class _Arbiter:
    def __init__(self, rows=(), *, fail=False):
        self.rows = list(rows)
        self.fail = fail
        self.prompts = []

    def chat_json(self, messages, **kwargs):
        self.prompts.append(messages[-1]["content"])
        if self.fail:
            raise RuntimeError("scripted offline arbiter failure")
        return {"narrative": "", "action_resolutions": copy.deepcopy(self.rows)}


def _advance(world, round_num, decisions=(), *, llm=None, enabled=False):
    return run_world_round(
        world, round_num, _period(round_num), decisions, (),
        llm=llm, rng=random.Random(29), arbiter_enabled=enabled,
    )


def _agreement():
    """Create real obligations through the menu, parser and round transition."""
    world = _world()
    world.start_round(1, _period(1))
    offer = _parse(world, 0, 1, "open_talks", targets=["Actor1"], terms=_TERMS)
    assert offer.ok
    _advance(world, 1, [offer])
    agreement = next(iter(world.interactions.values()))
    world.start_round(2, _period(2))
    accept = _parse(world, 1, 2, f"accept:{agreement.id}")
    assert accept.ok
    _advance(world, 2, [accept])
    assert agreement.status == "accepted"
    return world, agreement


def _obligation(world, actor_id, agreement):
    return next(c for c in world.actors[actor_id].commitments
                if c["source"] == f"agreement:{agreement.id}")


def _resolution(commitment, **changes):
    return {"actor": "Actor0", "commitment_id": commitment["id"],
            "action_round": 3, "outcome": "success", "rationale": _RATIONALE, **changes}


def _delivery_events(world):
    return [e.to_dict() for e in world.events
            if e.kind == "resolution" and e.source == "commitment"]


def _bound_attempt(world, promise, *, actor_id=0, round_num=3, **raw):
    world.start_round(round_num, _period(round_num))
    decision = _parse(world, actor_id, round_num, f"fulfill:{promise['id']}", **raw)
    assert decision.ok, decision.to_dict()
    assert decision.option["id"] == f"fulfill:{promise['id']}"
    return decision


def test_unrelated_public_statement_does_not_fulfil_due_promise():
    world = _world()
    promise = world.actors[0].add_commitment("Deliver audited schedule", made_round=1, due_round=2)
    world.start_round(2, _period(2))
    decision = _parse(world, 0, 2, "public_statement",
                      public_statement="Our office will be closed for the holiday.")
    assert decision.ok
    _advance(world, 2, [decision], llm=_Arbiter([
        {"actor": "Actor0", "outcome": "success", "rationale": "The unrelated notice was published."},
    ]), enabled=True)
    assert promise["status"] == "due"
    assert "fulfilled_round" not in promise
    assert "fulfillment_evidence" not in promise
    assert _delivery_events(world) == []


def test_accepting_second_offer_does_not_fulfil_first_agreement():
    world, first = _agreement()
    old = _obligation(world, 1, first)
    # The second proposer opens its offer through the same real decision path.
    second_offer = _parse(world, 2, 2, "open_talks", targets=["Actor1"],
                          terms="Arrange a separate press conference.")
    assert second_offer.ok
    world.register_decisions(2, [second_offer.to_dict()])
    second = next(it for it in world.interactions.values() if it.id != first.id)
    world.start_round(3, _period(3))
    accept = _parse(world, 1, 3, f"accept:{second.id}")
    assert accept.ok
    _advance(world, 3, [accept])
    assert second.status == "accepted"
    assert first.status == "accepted"
    assert old["status"] == "due"
    assert _obligation(world, 0, first)["status"] == "due"
    assert "fulfilled_round" not in old


def test_bound_delivery_is_only_an_attempt_until_matching_arbiter_success():
    """Old bound fulfillment spent one unit; saved explicit fulfillment now costs zero, with the same proof gate."""
    world, agreement = _agreement()
    actor = world.actors[0]
    chosen = _obligation(world, 0, agreement)
    other = actor.add_commitment("Deliver a separate report", made_round=2, due_round=3)
    relationships_before = [r.to_dict() for r in world.relationships.values()]
    decision = _bound_attempt(world, chosen, expected_reactions=[
        {"actor": "Actor1", "reaction": "Deliver its own audited schedule next period."},
    ])
    assert decision.targets == ["Actor1"]
    assert decision.option["cost"] == 0
    assert decision.option["kind"] == "operational"
    assert decision.option["lag"] == 0
    assert chosen["description"] in decision.option["label"]
    before_count = len(actor.commitments)
    world.register_decisions(3, [decision.to_dict()])
    assert chosen["status"] == other["status"] == "due"
    assert actor.capacity_used == 0
    assert actor.last_action["commitment_id"] == chosen["id"]
    assert actor.expectations == [{
        "round": 3, "about": "Actor1", "reaction": "Deliver its own audited schedule next period.",
    }]
    assert chosen["description"] in json.dumps(actor.last_action)
    assert len(actor.commitments) == before_count
    assert [r.to_dict() for r in world.relationships.values()] == relationships_before
    assert _delivery_events(world) == []

    validated, _ = validate_arbiter_update({"action_resolutions": [_resolution(chosen)]}, world)
    assert validated["action_resolutions"][0]["commitment_id"] == chosen["id"]
    summary = world.apply_arbiter_update(3, validated)
    assert chosen["status"] == "fulfilled"
    assert chosen["fulfilled_round"] == 3
    expected_evidence = {
        "round": 3, "option_id": f"fulfill:{chosen['id']}",
        "agent_id": actor.agent_id, "commitment_id": chosen["id"],
        "outcome": "success", "rationale": _RATIONALE,
    }
    for key, value in expected_evidence.items():
        assert chosen["fulfillment_evidence"][key] == value
    assert summary["commitments_fulfilled"]
    assert other["status"] == "due"
    assert _obligation(world, 1, agreement)["status"] == "due"
    assert len(_delivery_events(world)) == 1
    assert world.track_record(0)["kept"] == 1
    assert world.track_record(0)["outcomes"] == {"success": 1}


@pytest.mark.parametrize("variant", [
    "absent", "missing_id", "wrong_id", "wrong_actor", "empty_rationale",
    "padded_id", "malformed_id", "malformed_rationale", "partial", "pending",
    "blocked", "failed", "duplicate_success", "conflicting", "missing_action_round",
    "old_action_round", "string_action_round", "boolean_action_round", "fractional_action_round",
])
def test_invalid_arbiter_evidence_never_credits_attempt(variant):
    world, agreement = _agreement()
    promise = _obligation(world, 0, agreement)
    decision = _bound_attempt(world, promise)
    row = _resolution(promise)
    rows = [row]
    if variant == "absent":
        rows = []
    elif variant == "missing_id":
        row.pop("commitment_id")
    elif variant == "wrong_id":
        row["commitment_id"] = _obligation(world, 1, agreement)["id"]
    elif variant == "wrong_actor":
        row["actor"] = "Actor1"
    elif variant == "empty_rationale":
        row["rationale"] = "   "
    elif variant == "padded_id":
        row["commitment_id"] = f" {promise['id']} "
    elif variant == "malformed_id":
        row["commitment_id"] = [promise["id"]]
    elif variant == "malformed_rationale":
        row["rationale"] = {"unsupported": "A mapping is not a delivery rationale."}
    elif variant == "missing_action_round":
        row.pop("action_round")
    elif variant == "old_action_round":
        row["action_round"] = 2
    elif variant == "string_action_round":
        row["action_round"] = "3"
    elif variant == "boolean_action_round":
        row["action_round"] = True
    elif variant == "fractional_action_round":
        row["action_round"] = 3.5
    elif variant in ("partial", "pending", "blocked", "failed"):
        row["outcome"] = variant
    elif variant == "duplicate_success":
        rows.append(dict(row))
    elif variant == "conflicting":
        rows.append({**row, "outcome": "failed"})
    _advance(world, 3, [decision], llm=_Arbiter(rows), enabled=True)
    assert promise["status"] == "due"
    assert "fulfillment_evidence" not in promise
    assert "fulfilled_round" not in promise
    assert _delivery_events(world) == []


@pytest.mark.parametrize("enabled,fail", [(False, False), (True, True)])
def test_arbiter_off_or_failure_keeps_attempt_open(enabled, fail):
    world, agreement = _agreement()
    promise = _obligation(world, 0, agreement)
    decision = _bound_attempt(world, promise)
    llm = _Arbiter([_resolution(promise)], fail=fail)
    record = _advance(world, 3, [decision], llm=llm, enabled=enabled)
    assert record["arbiter_status"] == ("failed" if fail else "skipped")
    assert len(llm.prompts) == int(enabled)
    assert promise["status"] == "due"
    assert _delivery_events(world) == []


@pytest.mark.parametrize("made,due,current,status,eligible", [
    (1, 3, 1, "pending", False),
    (1, 3, 2, "pending", True),
    (1, 3, 3, "pending", True),
    (1, 3, 4, "pending", True),
    (1, 3, 5, "pending", False),
    (1, 3, 3, "fulfilled", False),
    (1, 3, 3, "released", False),
    (1, 3, 3, "breached", False),
    (1, 3, 3, "lapsed", False),
])
def test_delivery_menu_respects_creation_deadline_and_closed_states(made, due, current, status, eligible):
    """Old menus offered fulfillment through due_round; C11 omits it but parses saved IDs through grace1."""
    world = _world()
    promise = world.actors[0].add_commitment("Publish audited accounts", made_round=made, due_round=due)
    promise["status"] = status  # Saved-state input, not manufactured delivery evidence.
    world.start_round(current, _period(current))
    option_id = f"fulfill:{promise['id']}"
    own = build_option_menu(world.actors[0], world, current)
    foreign = build_option_menu(world.actors[1], world, current)
    assert option_id not in {o["id"] for o in own}
    assert option_id not in {o["id"] for o in foreign}
    assert _parse(world, 0, current, option_id).ok is eligible
    assert not _parse(world, 1, current, option_id).ok


def test_delivery_menu_leaves_slots_for_moves_and_remains_bounded():
    """Old delivery slots displaced moves and needed capacity; C11 uses a separate zero-cost list."""
    world, agreement = _agreement()
    world.actors[0].documented_plans = ["Build another plant", "Expand logistics"]
    for i in range(5):
        world.actors[0].add_commitment(f"Deliver audit appendix {i}", made_round=2, due_round=4)
    incoming = _parse(world, 2, 2, "open_talks", targets=["Actor0"], terms="Discuss a new project.")
    assert incoming.ok
    world.register_decisions(2, [incoming.to_dict()])
    world.start_round(3, _period(3))
    menu = build_option_menu(world.actors[0], world, 3, max_options=4)
    assert len(menu) <= 4
    assert menu[-1]["id"] == "hold_position"
    assert all(not o["id"].startswith("fulfill:") for o in menu)
    assert menu[0]["id"].startswith("accept:")
    world.actors[0].capacity_used = world.actors[0].capacity_per_round
    assert not any(o["id"].startswith("fulfill:")
                   for o in build_option_menu(world.actors[0], world, 3))
    promise = _obligation(world, 0, agreement)
    assert _parse(world, 0, 3, "hold_position", deliveries=[promise["id"]]).ok


@pytest.mark.parametrize("damage", [
    "duplicate", "missing_agreement", "wrong_counterparty", "not_obligated", "agreement_breached",
])
def test_ambiguous_or_invalid_agreement_binding_has_no_delivery_option(damage):
    world, agreement = _agreement()
    actor = world.actors[0]
    promise = _obligation(world, 0, agreement)
    # Model old/corrupt persisted rows at the input boundary; never fabricate a
    # last_action or successful attestation in these negative cases.
    if damage == "duplicate":
        actor.commitments.append(copy.deepcopy(promise))
    elif damage == "missing_agreement":
        del world.interactions[agreement.id]
    elif damage == "wrong_counterparty":
        promise["counterparty"] = 2
    elif damage == "not_obligated":
        agreement.obligations.remove(promise["id"])
    elif damage == "agreement_breached":
        agreement.status = "breached"
    world.start_round(3, _period(3))
    option_id = f"fulfill:{promise['id']}"
    assert option_id not in {o["id"] for o in build_option_menu(actor, world, 3)}
    assert not _parse(world, 0, 3, option_id).ok


@pytest.mark.parametrize("targets", [
    ["Actor2"], ["Actor1", "Actor2"], ["Unknown actor"], ["Actor10"],
    [{"actor": "Actor1"}], [1.0],
])
def test_explicit_wrong_counterparty_is_invalid(targets):
    world, agreement = _agreement()
    promise = _obligation(world, 0, agreement)
    world.start_round(3, _period(3))
    decision = _parse(world, 0, 3, f"fulfill:{promise['id']}", targets=targets)
    assert decision.status == "invalid"
    _advance(world, 3, [decision], llm=_Arbiter([_resolution(promise)]), enabled=True)
    assert promise["status"] == "due"
    assert _delivery_events(world) == []


@pytest.mark.parametrize("route", ["validator", "kernel"])
@pytest.mark.parametrize("actor_ref", ["Actor00", "Actor", "Shared office"])
def test_delivery_attestation_requires_unambiguous_exact_actor_identity(route, actor_ref):
    world, agreement = _agreement()
    for aid in (0, 2):
        world.actors[aid].aliases = ["Shared office"]
    world = WorldModel.from_dict(world.to_dict())
    promise = _obligation(world, 0, agreement)
    attempt = _bound_attempt(world, promise)
    world.register_decisions(3, [attempt.to_dict()])
    before = copy.deepcopy(world.to_dict())
    update = {"action_resolutions": [_resolution(promise, actor=actor_ref)]}
    if route == "validator":
        update, problems = validate_arbiter_update(update, world)
        assert problems and update["action_resolutions"] == []
    assert world.apply_arbiter_update(3, update)["commitments_fulfilled"] == 0
    assert world.to_dict() == before


def test_delivery_counterparty_rejects_shared_alias_even_when_first_match_is_correct():
    world, agreement = _agreement()
    for aid in (1, 2):
        world.actors[aid].aliases = ["Shared receiving office"]
    world = WorldModel.from_dict(world.to_dict())
    promise = _obligation(world, 0, agreement)
    world.start_round(3, _period(3))
    decision = _parse(world, 0, 3, f"fulfill:{promise['id']}", targets=["Shared receiving office"])
    assert decision.status == "invalid"
    assert promise["status"] == "due"


@pytest.mark.parametrize("field,value", [
    ("agent_id", "Actor00"), ("targets", ["Actor10"]), ("targets", [{"actor": "Actor1"}]),
])
def test_kernel_rejects_guessed_delivery_binding_before_spending_or_credit(field, value):
    world, agreement = _agreement()
    promise = _obligation(world, 0, agreement)
    row = _bound_attempt(world, promise).to_dict()
    row[field] = value
    world.register_decisions(3, [row])
    assert world.actors[0].capacity_used == 0
    assert "last_fulfillment_attempt" not in promise
    assert world.apply_arbiter_update(3, {"action_resolutions": [_resolution(promise)]})["commitments_fulfilled"] == 0
    assert promise["status"] == "due"
    assert world.track_record(0)["outcomes"] == {}


@pytest.mark.parametrize("actor_ref,target_ref", [
    (0, 1), ("0", "1"), (" actor0 ", "actor1"), ("Delivery office", "Receiving office"),
])
def test_exact_ids_names_and_unique_registered_aliases_can_deliver(actor_ref, target_ref):
    world, agreement = _agreement()
    world.actors[0].aliases = ["Delivery office"]
    world.actors[1].aliases = ["Receiving office"]
    world = WorldModel.from_dict(world.to_dict())
    promise = _obligation(world, 0, agreement)
    attempt = _bound_attempt(world, promise, targets=[target_ref])
    world.register_decisions(3, [attempt.to_dict()])
    update, problems = validate_arbiter_update(
        {"action_resolutions": [_resolution(promise, actor=actor_ref)]}, world,
    )
    assert not problems
    assert world.apply_arbiter_update(3, update)["commitments_fulfilled"] == 1
    assert promise["status"] == "fulfilled"
    assert world.track_record(0)["outcomes"] == {"success": 1}


def test_known_actor_id_survives_validation_when_display_names_collide():
    world, agreement = _agreement()
    world.actors[2].name = world.actors[0].name
    world = WorldModel.from_dict(world.to_dict())
    promise = _obligation(world, 0, agreement)
    attempt = _bound_attempt(world, promise)
    world.register_decisions(3, [attempt.to_dict()])
    update, problems = validate_arbiter_update(
        {"action_resolutions": [_resolution(promise, actor=0)]}, world,
    )
    assert not problems
    assert world.apply_arbiter_update(3, update)["commitments_fulfilled"] == 1
    assert world.track_record(0)["kept"] == 1
    assert world.track_record(2)["kept"] == 0


@pytest.mark.parametrize("targets", [None, [1], ["Unique receiving office"]])
def test_counterparty_binding_survives_serialization_when_display_names_collide(targets):
    """Old explicit fulfillment spent one unit; zero-cost compatibility still binds numeric counterparties."""
    world, agreement = _agreement()
    world.actors[1].aliases = ["Unique receiving office"]
    world.actors[2].name = world.actors[1].name
    world = WorldModel.from_dict(world.to_dict())
    promise = _obligation(world, 0, agreement)
    attempt = _bound_attempt(world, promise, targets=targets)
    row = json.loads(json.dumps(attempt.to_dict()))
    assert row["targets"] == ["Actor1"]  # Human-facing names remain available.
    world.register_decisions(3, [row])
    assert world.actors[0].last_action["status"] == "ok"
    assert world.actors[0].capacity_used == 0
    # The persisted current action must still bind the same numeric counterparty.
    world = WorldModel.from_dict(json.loads(json.dumps(world.to_dict())))
    promise = _obligation(world, 0, agreement)
    update, problems = validate_arbiter_update(
        {"action_resolutions": [_resolution(promise, actor=0)]}, world,
    )
    assert not problems
    assert world.apply_arbiter_update(3, update)["commitments_fulfilled"] == 1
    assert promise["status"] == "fulfilled"
    assert _obligation(world, 1, agreement)["status"] == "due"
    assert world.actors[2].commitments == []


@pytest.mark.parametrize("bad_ids", [[2], ["1"], [1.0], [True], [1, 2]])
def test_serialized_counterparty_ids_cannot_change_the_stored_agreement(bad_ids):
    world, agreement = _agreement()
    promise = _obligation(world, 0, agreement)
    row = _bound_attempt(world, promise).to_dict()
    row["option"]["commitment_target_ids"] = bad_ids
    world.register_decisions(3, [row])
    assert world.actors[0].capacity_used == 0
    assert "last_fulfillment_attempt" not in promise
    assert world.apply_arbiter_update(3, {"action_resolutions": [_resolution(promise)]})["commitments_fulfilled"] == 0
    assert promise["status"] == "due"


@pytest.mark.parametrize("route", ["validator", "kernel"])
def test_ambiguous_duplicate_attestation_cannot_leave_an_apparently_unique_success(route):
    world, agreement = _agreement()
    for aid in (0, 2):
        world.actors[aid].aliases = ["Shared office"]
    world = WorldModel.from_dict(world.to_dict())
    promise = _obligation(world, 0, agreement)
    attempt = _bound_attempt(world, promise)
    world.register_decisions(3, [attempt.to_dict()])
    before = copy.deepcopy(world.to_dict())
    update = {"action_resolutions": [
        _resolution(promise), _resolution(promise, actor="Shared office", outcome="failed"),
    ]}
    if route == "validator":
        update, _ = validate_arbiter_update(update, world)
    assert world.apply_arbiter_update(3, update)["commitments_fulfilled"] == 0
    assert world.to_dict() == before


def test_exact_option_id_is_required_and_custom_label_cannot_impersonate_delivery():
    """Old tests read a fulfillment menu slot; C11 retains exact saved-ID parsing without such a slot."""
    world, agreement = _agreement()
    promise = _obligation(world, 0, agreement)
    world.start_round(3, _period(3))
    saved = _parse(world, 0, 3, f"fulfill:{promise['id']}")
    assert saved.ok
    option = saved.option
    by_label = _parse(world, 0, 3, option["label"])
    assert by_label.status == "invalid"
    custom = _parse(world, 0, 3, "custom",
                    custom_action={"kind": "operational", "label": option["label"]},
                    commitment_id=promise["id"], targets=["Actor1"])
    # A custom action may be a valid generic move, but its prose grants no binding.
    _advance(world, 3, [custom], llm=_Arbiter([_resolution(promise)]), enabled=True)
    assert promise["status"] == "due"
    assert not world.actors[0].last_action.get("commitment_id")
    assert _delivery_events(world) == []


def test_delivery_payload_cannot_add_pledges_or_alliance_credit():
    world, agreement = _agreement()
    promise = _obligation(world, 0, agreement)
    before_commitments = copy.deepcopy(world.actors[0].commitments)
    before_relationships = [r.to_dict() for r in world.relationships.values()]
    decision = _bound_attempt(
        world, promise,
        commitment={"description": "An unrelated new promise", "due_periods": 2},
        alliance_moves=[{"target": "Actor2", "move": "strengthen"}],
        terms="Invent a second alliance",
    )
    _advance(world, 3, [decision])
    assert len(world.actors[0].commitments) == len(before_commitments)
    assert {c["id"] for c in world.actors[0].commitments} == {c["id"] for c in before_commitments}
    assert [r.to_dict() for r in world.relationships.values()] == before_relationships
    assert list(world.interactions) == [agreement.id]
    assert promise["status"] == "due"


@pytest.mark.parametrize("next_action", ["none", "public_statement", "other_delivery"])
def test_stale_or_different_current_attempt_cannot_use_old_attestation(next_action):
    world = _world()
    promise = world.actors[0].add_commitment("Deliver schedule", made_round=1, due_round=4)
    other = world.actors[0].add_commitment("Deliver equipment", made_round=1, due_round=4)
    attempt = _bound_attempt(world, promise, round_num=2)
    _advance(world, 2, [attempt])
    world.start_round(3, _period(3))
    decisions = []
    if next_action == "public_statement":
        decisions = [_parse(world, 0, 3, "public_statement")]
    elif next_action == "other_delivery":
        decisions = [_bound_attempt(world, other)]
    _advance(world, 3, decisions, llm=_Arbiter([_resolution(promise, action_round=2)]), enabled=True)
    assert promise["status"] == other["status"] == "pending"
    assert _delivery_events(world) == []


@pytest.mark.parametrize("attestation_round,expected_status", [(2, "pending"), (3, "fulfilled")])
def test_retry_of_same_promise_requires_current_attempt_round(attestation_round, expected_status):
    world = _world()
    promise = world.actors[0].add_commitment("Deliver schedule", made_round=1, due_round=4)
    first = _bound_attempt(world, promise, round_num=2)
    _advance(world, 2, [first], llm=_Arbiter([
        _resolution(promise, action_round=2, outcome="failed", rationale="Delivery was blocked."),
    ]), enabled=True)
    assert promise["status"] == "pending"
    reputation_before_retry = world.actors[0].reputation
    second = _bound_attempt(world, promise, round_num=3)
    _advance(world, 3, [second], llm=_Arbiter([
        _resolution(promise, action_round=attestation_round),
    ]), enabled=True)
    assert promise["status"] == expected_status
    assert len(_delivery_events(world)) == int(expected_status == "fulfilled")
    if expected_status == "fulfilled":
        assert promise["fulfillment_evidence"]["round"] == 3
    else:
        assert "fulfillment_evidence" not in promise
        assert world.actors[0].reputation == reputation_before_retry


@pytest.mark.parametrize("first_outcome", ["success", "failed"])
def test_bound_attempt_can_receive_only_one_valid_review(first_outcome):
    world = _world()
    promise = world.actors[0].add_commitment("Deliver schedule", made_round=1, due_round=4)
    first = _bound_attempt(world, promise, round_num=2)
    _advance(world, 2, [first], llm=_Arbiter([
        _resolution(promise, action_round=2, outcome=first_outcome),
    ]), enabled=True)
    status_after_first = promise["status"]
    reputation_after_first = world.actors[0].reputation
    events_after_first = _delivery_events(world)
    last_action_after_first = copy.deepcopy(world.actors[0].last_action)
    # Identical and contradictory replays must not change the accepted review.
    for outcome in (first_outcome, "failed", "success"):
        validated, _ = validate_arbiter_update({"action_resolutions": [
            _resolution(promise, action_round=2, outcome=outcome),
        ]}, world)
        world.apply_arbiter_update(2, validated)
    assert promise["status"] == status_after_first
    assert world.actors[0].reputation == reputation_after_first
    assert world.actors[0].outcomes == {first_outcome: 1}
    assert _delivery_events(world) == events_after_first
    assert world.actors[0].last_action == last_action_after_first


@pytest.mark.parametrize("first_outcome", ["failed", "partial"])
def test_reregistering_reviewed_delivery_cannot_reset_review_or_spend_again(first_outcome):
    world = _world()
    actor = world.actors[0]
    promise = actor.add_commitment("Deliver schedule", made_round=1, due_round=4)
    decision = _bound_attempt(world, promise, round_num=2)
    row = decision.to_dict()
    world.register_decisions(2, [row])
    # The real registration must create the proof; the test never sets private
    # action fields, review flags or last_fulfillment_attempt metadata.
    assert promise["last_fulfillment_attempt"]["round"] == 2
    assert promise["last_fulfillment_attempt"]["option_id"] == decision.option["id"]
    assert promise["last_fulfillment_attempt"]["outcome"] == "unverified"
    validated, _ = validate_arbiter_update({"action_resolutions": [
        _resolution(promise, action_round=2, outcome=first_outcome),
    ]}, world)
    world.apply_arbiter_update(2, validated)
    assert actor.last_action["commitment_reviewed"] is True
    assert promise["last_fulfillment_attempt"]["outcome"] == first_outcome
    assert promise["status"] == "pending"
    last_action = copy.deepcopy(actor.last_action)
    attempt = copy.deepcopy(promise["last_fulfillment_attempt"])
    capacity = actor.capacity_used
    reputation = actor.reputation
    events = [e.to_dict() for e in world.events]

    for repeated_outcome in ("success", first_outcome):
        world.register_decisions(2, [copy.deepcopy(row)])
        assert actor.last_action == last_action
        assert promise["last_fulfillment_attempt"] == attempt
        assert actor.capacity_used == capacity
        assert [e.to_dict() for e in world.events] == events
        validated, _ = validate_arbiter_update({"action_resolutions": [
            _resolution(promise, action_round=2, outcome=repeated_outcome),
        ]}, world)
        summary = world.apply_arbiter_update(2, validated)
        assert summary["commitments_fulfilled"] == 0
        assert actor.reputation == reputation
        assert actor.outcomes == {first_outcome: 1}
        assert actor.capacity_used == capacity
        assert actor.last_action == last_action
        assert promise["last_fulfillment_attempt"] == attempt
        assert promise["status"] == "pending"
        assert "fulfillment_evidence" not in promise
        assert _delivery_events(world) == []


def test_c1_old_unreviewed_attempt_cannot_be_resolved_after_world_advances():
    world = _world()
    promise = world.actors[0].add_commitment("Deliver schedule", made_round=1, due_round=5)
    decision = _bound_attempt(world, promise, round_num=3)
    world.register_decisions(3, [decision.to_dict()])
    old_resolution = _resolution(promise, action_round=3)
    assert promise["last_fulfillment_attempt"]["outcome"] == "unverified"
    world.start_round(4, _period(4))
    before = copy.deepcopy(world.to_dict())
    summary = world.apply_arbiter_update(3, {"action_resolutions": [old_resolution]})
    assert summary["commitments_fulfilled"] == 0
    assert world.to_dict() == before


def test_c1_saved_decision_round_cannot_be_relabelled_by_registration():
    """Old stale rows were silent no-ops; C11 records invalid admission without relabelling the attempt."""
    world = _world()
    actor = world.actors[0]
    promise = actor.add_commitment("Deliver schedule", made_round=1, due_round=5)
    decision = _bound_attempt(world, promise, round_num=2)
    saved_row = json.loads(json.dumps(decision.to_dict()))
    assert saved_row["round"] == 2
    world.register_decisions(2, [saved_row])
    attempt = copy.deepcopy(promise["last_fulfillment_attempt"])
    world.start_round(3, _period(3))
    assert actor.capacity_used == 0
    world.register_decisions(3, [saved_row])
    assert actor.capacity_used == 0
    assert actor.last_action["status"] == "invalid" and actor.last_action["round"] == 3
    assert actor.last_action["resolution"] is None
    assert promise["last_fulfillment_attempt"] == attempt
    assert promise["status"] == "pending"
    assert _delivery_events(world) == []


@pytest.mark.parametrize("route", ["validator", "kernel"])
@pytest.mark.parametrize("conflict", ["contradictory_identity", "malformed_duplicate"])
def test_c2_conflicting_actor_claims_reject_bound_resolutions(route, conflict):
    world = _world()
    promise = world.actors[0].add_commitment("Deliver schedule", made_round=1, due_round=5)
    decision = _bound_attempt(world, promise)
    world.register_decisions(3, [decision.to_dict()])
    if conflict == "contradictory_identity":
        rows = [_resolution(promise, actor="Actor0", agent_id=1)]
    else:
        rows = [
            _resolution(promise),
            _resolution(promise, actor="Unknown actor", agent_id=0),
        ]
    before = copy.deepcopy(world.to_dict())
    update = {"action_resolutions": rows}
    if route == "validator":
        update, _ = validate_arbiter_update(update, world)
        assert update["action_resolutions"] == []
    summary = world.apply_arbiter_update(3, update)
    assert summary["commitments_fulfilled"] == 0
    assert world.to_dict() == before


@pytest.mark.parametrize("outcome_form", ["missing", "empty"])
def test_c3_missing_direct_outcome_does_not_consume_review(outcome_form):
    world = _world()
    actor = world.actors[0]
    promise = actor.add_commitment("Deliver schedule", made_round=1, due_round=5)
    decision = _bound_attempt(world, promise)
    world.register_decisions(3, [decision.to_dict()])
    row = _resolution(promise)
    if outcome_form == "missing":
        row.pop("outcome")
    else:
        row["outcome"] = ""
    before = copy.deepcopy(world.to_dict())
    rejected = world.apply_arbiter_update(3, {"action_resolutions": [row]})
    assert rejected["commitments_fulfilled"] == 0
    assert world.to_dict() == before
    assert not actor.last_action.get("commitment_reviewed")
    assert promise["last_fulfillment_attempt"]["outcome"] == "unverified"
    accepted = world.apply_arbiter_update(3, {"action_resolutions": [_resolution(promise)]})
    assert accepted["commitments_fulfilled"] == 1
    assert actor.last_action["commitment_reviewed"] is True
    assert promise["status"] == "fulfilled"
    assert len(_delivery_events(world)) == 1


def test_c4_delivery_extras_are_normalized_before_serialization_and_memory():
    world, agreement = _agreement()
    promise = _obligation(world, 0, agreement)
    decision = _bound_attempt(
        world, promise,
        commitment={"description": _EXTRA_PLEDGE, "due_periods": 2},
        alliance_moves=[{"target": "Actor2", "move": "strengthen"}],
        terms=_EXTRA_TERMS,
    )
    assert decision.commitment is None
    assert decision.alliance_moves == []
    assert decision.terms == ""
    row = decision.to_dict()
    assert row["commitment"] is None and row["alliance_moves"] == [] and row["terms"] == ""
    note = decision_memory_note(decision, "period-3")
    assert note.startswith("# YOUR MOVE THIS PERIOD")
    assert "You chose:" in note and promise["description"] in note
    assert "You committed to:" not in note
    assert _EXTRA_PLEDGE not in note and _EXTRA_TERMS not in note
    assert _EXTRA_PLEDGE not in json.dumps(row) and _EXTRA_TERMS not in json.dumps(row)


def test_c5_long_pending_list_preserves_own_breach_in_default_private_prompt():
    """Old debt breached at 4 and only one side broke; C11 breaches both after grace5, visible in brief6."""
    world, agreement = _agreement()
    actor = world.actors[0]
    for index in range(5):
        actor.add_commitment(
            f"Long pending promise {index}: " + "Detailed documentation required for a separate project. " * 4,
            made_round=2, due_round=10,
        )
    _advance(world, 3)
    grace = _advance(world, 4)
    assert grace["deterministic"]["breaches"] == []
    record = _advance(world, 5)
    assert record["deterministic"]["breaches"]
    assert _obligation(world, 0, agreement)["status"] == "breached"
    breach = next(e for e in world.events_in_round(5, ("breach",)) if e.actors[0] == actor.name)
    assert len(actor.pending_commitments()) == 5
    assert sum(len(c["description"]) for c in actor.pending_commitments()) > 900
    world.start_round(6, _period(6))
    private_brief = world.render_private_brief(0)  # Main reserves 1300 characters for the richer brief.
    assert len(private_brief) <= 1300
    assert "Your simulated credibility (0–1): 0.35" in private_brief
    assert "Your commitment outcomes last period:" in private_brief
    assert breach.description in private_brief
    prompt = build_decision_prompt(
        actor, world_clock="# WORLD CLOCK\nperiod-6 — round 6/6",
        public_brief=world.render_public_brief(), private_brief=private_brief,
        options=build_option_menu(actor, world, 6), scenarios=(),
        cast_names=[a.name for a in world.actors.values()],
    )
    assert private_brief in prompt
    assert breach.description in prompt
    assert "Your simulated credibility (0–1): 0.35" in prompt


def test_saved_legacy_rows_preserve_closed_statuses_and_allow_unique_open_delivery(tmp_path):
    world = _world()
    actor = world.actors[0]
    for status in ("fulfilled", "released", "breached", "lapsed"):
        row = actor.add_commitment(f"Historical {status}", made_round=1, due_round=2)
        row["status"] = status
        if status == "fulfilled":
            row["fulfilled_round"] = 2
    open_row = actor.add_commitment("Historical open schedule", made_round=1, due_round=3)
    open_row["id"] = "legacy-open-schedule"
    closed_before = copy.deepcopy(actor.commitments[:-1])
    saved = tmp_path / "legacy_world.json"
    saved.write_text(json.dumps(world.to_dict()), encoding="utf-8")
    loaded = WorldModel.from_dict(json.loads(saved.read_text(encoding="utf-8")))
    promise = loaded.actors[0].commitments[-1]
    decision = _bound_attempt(loaded, promise)
    _advance(loaded, 3, [decision], llm=_Arbiter([_resolution(promise)]), enabled=True)
    assert promise["status"] == "fulfilled"
    assert loaded.actors[0].commitments[:-1] == closed_before


def test_delivery_and_breach_evidence_survive_save_load_without_duplicate_consequences(tmp_path):
    """Old due-3 debt breached in round 4; C11 preserves it during grace and breaches in round 5."""
    world, agreement = _agreement()
    promise = _obligation(world, 0, agreement)
    counterpart = _obligation(world, 1, agreement)
    decision = _bound_attempt(world, promise)
    unrelated = _parse(world, 1, 3, "public_statement",
                       public_statement="Our annual picnic will be held on Friday.")
    _advance(world, 3, [decision, unrelated], llm=_Arbiter([_resolution(promise)]), enabled=True)
    assert promise["status"] == "fulfilled" and counterpart["status"] == "due"
    evidence = copy.deepcopy(promise["fulfillment_evidence"])
    delivery_reputation = world.actors[0].reputation
    saved = tmp_path / "world.json"
    saved.write_text(json.dumps(world.to_dict()), encoding="utf-8")
    loaded = WorldModel.from_dict(json.loads(saved.read_text(encoding="utf-8")))
    restored = _obligation(loaded, 0, loaded.interactions[agreement.id])
    assert restored["fulfillment_evidence"] == evidence
    # Replaying the same successful attestation must not issue another event or
    # another delivery reward, including after a process boundary.
    validated, _ = validate_arbiter_update({"action_resolutions": [_resolution(restored)]}, loaded)
    loaded.apply_arbiter_update(3, validated)
    assert restored["fulfillment_evidence"] == evidence
    assert len(_delivery_events(loaded)) == 1
    assert loaded.actors[0].reputation == delivery_reputation

    reputation_before_breach = loaded.actors[1].reputation
    relation_before_breach = next(iter(loaded.relationships.values())).polarity
    grace = _advance(loaded, 4)
    assert grace["deterministic"]["commitments_lapsed"] == []
    assert grace["deterministic"]["breaches"] == []
    assert _obligation(loaded, 1, loaded.interactions[agreement.id])["status"] == "due"
    record = _advance(loaded, 5)
    assert record["deterministic"]["commitments_lapsed"]
    assert len(record["deterministic"]["breaches"]) == 1
    assert loaded.interactions[agreement.id].status == "breached"
    assert _obligation(loaded, 1, loaded.interactions[agreement.id])["status"] == "breached"
    assert restored["status"] == "fulfilled"
    assert loaded.actors[1].reputation == pytest.approx(reputation_before_breach - 0.15)
    assert next(iter(loaded.relationships.values())).polarity == pytest.approx(relation_before_breach - 0.3)
    assert "breach" in record["digest"].lower()
    after_breach = loaded.to_dict()
    saved.write_text(json.dumps(after_breach), encoding="utf-8")
    resumed = WorldModel.from_dict(json.loads(saved.read_text(encoding="utf-8")))
    next_record = _advance(resumed, 6)
    assert next_record["deterministic"]["breaches"] == []
    assert next_record["deterministic"]["commitments_lapsed"] == []
    assert len([e for e in resumed.events if e.kind == "breach"]) == 1
    assert len(_delivery_events(resumed)) == 1
    assert [a.reputation for a in resumed.actors.values()] == [a.reputation for a in loaded.actors.values()]
    assert [r.to_dict() for r in resumed.relationships.values()] == after_breach["relationships"]


class _CalendarDeliveryLLM:
    """Old replies found menu fulfillment IDs; saved-ID replies now read the owned private commitment."""

    def __init__(self):
        self.provider = "offline"
        self.model = "scripted-commitment-acceptance"
        self.calls = []
        self.agreement_id = None
        self.commitment_id = None

    def chat_json(self, messages, **kwargs):
        content = messages[-1]["content"]
        if "# DECIDE YOUR MOVE FOR THIS PERIOD" in content:
            round_num = int(re.search(r"round (\d+)/(\d+)", content).group(1))
            actor = re.search(r"# DECIDE YOUR MOVE FOR THIS PERIOD — (.+)", content).group(1).strip()
            self.calls.append({"kind": "decision", "round": round_num, "actor": actor, "content": content})
            if actor == "Actor0" and round_num == 1:
                return {
                    "option_id": "open_talks", "targets": ["Actor1"], "terms": _TERMS,
                    "public_statement": "We propose exchanging audited tariff schedules.",
                    "scenario_commitment": "abstain",
                }
            if actor == "Actor1" and round_num == 2:
                option = re.search(r"\[(accept:([^\]\s]+))\]", content)
                assert option, "Acceptance must be offered by the real menu."
                self.agreement_id = option.group(2)
                return {"option_id": option.group(1),
                        "public_statement": "We accept the exchange of audited schedules.",
                        "scenario_commitment": "abstain"}
            if actor == "Actor0" and round_num == 3:
                private = content.split("- Your open commitments:", 1)[1].split("# DECIDE YOUR MOVE", 1)[0]
                commitment = re.search(r"\[([^\]\s]+)\]", private)
                assert commitment, "The actor must see its own persisted commitment ID."
                self.commitment_id = commitment.group(1)
                return {"option_id": f"fulfill:{self.commitment_id}",
                        "public_statement": "We submit our audited schedule to Actor1 for the agreed exchange.",
                        "private_rationale": "Attempt the delivery promised in the accepted agreement.",
                        "commitment": {"description": _EXTRA_PLEDGE, "due_periods": 2},
                        "alliance_moves": [{"target": "Actor2", "move": "strengthen"}],
                        "terms": _EXTRA_TERMS,
                        "scenario_commitment": "abstain"}
            if actor == "Actor1" and round_num == 3:
                return {"option_id": "public_statement",
                        "public_statement": "Our annual staff picnic will be held on Friday.",
                        "private_rationale": "Publish an unrelated administrative announcement.",
                        "scenario_commitment": "abstain"}
            if actor == "Actor0" and round_num == 6:
                # This response is gated by the actual prompt, not just the round
                # number. Without persisted breach feedback the actor holds.
                if (f"Breach [{self.agreement_id}]" in content
                        and "Actor1 broke its agreement" in content):
                    return {"option_id": "public_statement", "targets": ["Actor1"],
                            "public_statement": "Because Actor1 breached the schedule agreement, "
                                                "we now require independently verified delivery safeguards.",
                            "private_rationale": "The prior breach makes unsupported assurances insufficient.",
                            "scenario_commitment": "abstain"}
            return {"option_id": "hold_position", "scenario_commitment": "abstain"}
        if "consequence arbiter" in content:
            round_num = int(re.search(r"— round (\d+)", content).group(1))
            self.calls.append({"kind": "arbiter", "round": round_num, "content": content})
            rows = []
            if round_num == 3:
                attempts = re.findall(
                    r"^- actor=([^;\n]+); commitment_id=([^;\n]+); action_round=(\d+); ",
                    content, flags=re.MULTILINE,
                )
                assert len(attempts) == 1, "The arbiter must see exactly one current delivery attempt."
                actor, commitment_id, action_round = attempts[0]
                assert actor == "Actor0" and commitment_id == self.commitment_id
                assert int(action_round) == round_num
                rows = [{"actor": actor, "commitment_id": commitment_id,
                         "action_round": int(action_round), "outcome": "success",
                         "rationale": _RATIONALE}]
            # Do not invent lapse, breach, reputation, relationships or narrative
            # feedback: the real world transitions and digest must supply them.
            return {"narrative": "", "action_resolutions": rows}
        raise AssertionError(f"Unexpected model prompt: {content[:100]}")


@pytest.fixture
def calendar_harness(tmp_path, monkeypatch):
    # Import lazily: selecting pure cases must not import OASIS at collection.
    from datetime import date
    from test_world_model_loop import _patch_world, _world_config
    from test_calendar_round_loop import _run, _read_events
    import run_parallel_simulation as rps

    sim_dir = str(tmp_path)
    envs = []
    _patch_world(monkeypatch, sim_dir, envs)
    llm = _CalendarDeliveryLLM()
    monkeypatch.setattr("app.utils.llm_client.LLMClient", lambda *a, **k: llm)
    monkeypatch.setattr(rps, "_shutdown_event", None)
    cfg = _world_config()
    # Extend the existing quarterly harness enough to observe the period AFTER
    # the real overdue consequence. No synthetic prior state is inserted.
    cfg["temporal_config"]["round_dates"] = [
        *cfg["temporal_config"]["round_dates"],
        {"round": 3, "period_start": "2027-04-01", "period_end": "2027-06-30", "label": "2027-Q2"},
        {"round": 4, "period_start": "2027-07-01", "period_end": "2027-09-30", "label": "2027-Q3"},
        {"round": 5, "period_start": "2027-10-01", "period_end": "2027-12-31", "label": "2027-Q4"},
    ]
    cfg["temporal_config"].update(
        n_rounds=6, horizon_date="2027-12-31", horizon_text="Q4 2027",
        span_days=(date(2027, 12, 31) - date(2026, 7, 11)).days,
    )
    cfg["time_config"]["total_simulation_hours"] = 6
    cfg["world_model"]["horizon_date"] = "2027-12-31"
    cfg["world_model"]["question"] = "Will the parties honour the schedule exchange by Q4 2027?"
    cfg["world_state_seed"]["horizon_date"] = "2027-12-31"
    cfg["event_config"]["scheduled_events"] = []
    for actor in cfg["agent_configs"]:
        if actor["agent_id"] in (0, 1):
            actor["cadence"] = "principal"
        else:
            actor["activity_level"] = 0.0
    # Leave default world-model activation in force: no engine or feature flag
    # is installed and no coordinator, QA, parser or consequence gate is stubbed.
    yield cfg, sim_dir, envs, llm, rps, _run, _read_events
    rps._WORLD_COORDINATORS.clear()
    rps._WORLD_TRAJ_WRITTEN.clear()


def _read_rows(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


@pytest.mark.parametrize("resume_after_delivery", [False, True], ids=["continuous", "resume"])
def test_calendar_loop_delivery_breach_and_next_actor_feedback(
    calendar_harness, tmp_path, monkeypatch, resume_after_delivery,
):
    """Old menu delivery and round-4 breach become saved-ID delivery, grace4, breach5 and feedback6."""
    cfg, sim_dir, envs, llm, rps, run, read_events = calendar_harness
    prior_calls = []
    saved_evidence = None
    if resume_after_delivery:
        original_commit = rps._ReflexiveWorldCoordinator._commit_round
        stop = asyncio.Event()

        async def commit_then_stop(self, round_num, buf):
            # Same interruption boundary as the existing calendar resume tests:
            # the full production commit finishes before shutdown is signalled.
            await original_commit(self, round_num, buf)
            if round_num == 2:
                stop.set()

        monkeypatch.setattr(rps._ReflexiveWorldCoordinator, "_commit_round", commit_then_stop)
        monkeypatch.setattr(rps, "_shutdown_event", stop)
        run(cfg, sim_dir)
        partial = json.loads((tmp_path / "world_state.json").read_text(encoding="utf-8"))
        assert partial["committed_round"] == 3
        partial_actors = {a["agent_id"]: a for a in partial["world"]["actors"]}
        delivered = next(c for c in partial_actors[0]["commitments"] if c["id"] == llm.commitment_id)
        assert delivered["status"] == "fulfilled"
        saved_evidence = copy.deepcopy(delivered["fulfillment_evidence"])
        assert partial_actors[1]["commitments"][0]["status"] == "due"
        assert not any(e["kind"] == "breach" for e in partial["world"]["events"])
        prior_calls = copy.deepcopy(llm.calls)
        monkeypatch.setattr(rps._ReflexiveWorldCoordinator, "_commit_round", original_commit)
        monkeypatch.setattr(rps, "_shutdown_event", None)
        rps._WORLD_COORDINATORS.clear()
        rps._WORLD_TRAJ_WRITTEN.clear()
        run(cfg, sim_dir, resume=True)
        assert llm.calls[:len(prior_calls)] == prior_calls
        assert all(c["round"] > 3 for c in llm.calls[len(prior_calls):])
    else:
        run(cfg, sim_dir)

    state = json.loads((tmp_path / "world_state.json").read_text(encoding="utf-8"))
    history = _read_rows(tmp_path / "world_state_history.jsonl")
    actions = _read_rows(tmp_path / "world_actions.jsonl")
    digests = _read_rows(tmp_path / "world_digest.jsonl")
    platform_events = read_events(sim_dir)
    actors = {a["agent_id"]: a for a in state["world"]["actors"]}
    agreement = next(it for it in state["world"]["interactions"] if it["id"] == llm.agreement_id)
    delivered = next(c for c in actors[0]["commitments"] if c["id"] == llm.commitment_id)
    owed = next(c for c in actors[1]["commitments"] if c["source"] == f"agreement:{agreement['id']}")

    assert state["committed_round"] == 6
    assert [h["round"] for h in history] == [1, 2, 3, 4, 5, 6]
    assert [d["round"] for d in digests] == [1, 2, 3, 4, 5, 6]
    assert all(h["arbiter_status"] == "applied" for h in history)
    assert agreement["status"] == "breached"
    assert delivered["status"] == "fulfilled"
    expected_evidence = {
        "round": 3, "option_id": f"fulfill:{llm.commitment_id}",
        "agent_id": actors[0]["agent_id"], "commitment_id": delivered["id"],
        "outcome": "success", "rationale": _RATIONALE,
    }
    for key, value in expected_evidence.items():
        assert delivered["fulfillment_evidence"][key] == value
    if saved_evidence is not None:
        assert delivered["fulfillment_evidence"] == saved_evidence
    assert owed["status"] == "breached" and "fulfillment_evidence" not in owed
    assert actors[0]["reputation"] == pytest.approx(0.52)
    assert actors[1]["reputation"] == pytest.approx(0.35)
    assert actors[0]["track_record"]["kept"] == 1
    assert actors[0]["track_record"]["outcomes"] == {"success": 1}
    assert actors[1]["track_record"]["broken"] == 1
    assert actors[1]["track_record"]["kept"] == 0
    # No delivery-generated lag pledge or second alliance may have appeared.
    assert len(actors[0]["commitments"]) == len(actors[1]["commitments"]) == 1
    assert len(state["world"]["interactions"]) == 1

    round3 = history[2]
    round4 = history[3]
    round5 = history[4]
    round6 = history[5]
    assert round3["arbiter"]["commitments_fulfilled"]
    assert round3["deterministic"]["breaches"] == []
    assert round4["deterministic"]["commitments_lapsed"] == []
    assert round4["deterministic"]["breaches"] == []
    assert len(round5["deterministic"]["commitments_lapsed"]) == 1
    assert len(round5["deterministic"]["breaches"]) == 1
    assert "Actor1" in round5["deterministic"]["breaches"][0]
    assert round6["deterministic"]["breaches"] == []
    changes = round5["diff"]["relationships_changed"]
    assert len(changes) == 1 and changes[0]["direction"] == "farther"
    relation = next(r for r in state["world"]["relationships"] if {r["source"], r["target"]} == {0, 1})
    assert [entry["round"] for entry in relation["history"]] == [1, 2, 5]
    accepted, breached = relation["history"][-2:]
    assert accepted["to"] == pytest.approx(0.2775)
    assert breached["from"] == accepted["to"]
    assert breached["to"] == pytest.approx(-0.0225)
    assert breached["to"] == pytest.approx(breached["from"] - 0.3)
    assert breached["cause"] == "Actor1 breached the agreement with Actor0"
    assert relation["polarity"] == breached["to"] == changes[0]["polarity"]
    assert relation["last_changed_round"] == 5
    assert round6["diff"]["relationships_changed"] == []

    world = WorldModel.from_dict(state["world"])
    delivery_events = _delivery_events(world)
    breaches = [e for e in state["world"]["events"] if e["kind"] == "breach"]
    assert len(delivery_events) == 1 and delivery_events[0]["round"] == 3
    assert len(breaches) == 1 and breaches[0]["round"] == 5
    assert "Actor1" in breaches[0]["description"]
    assert delivery_events[0]["description"] in digests[2]["digest"]
    assert breaches[0]["description"] in digests[4]["digest"]

    action_by_actor_round = {(a["actor_name"], a["round"]): a for a in actions}
    assert len(action_by_actor_round) == len(actions)
    delivery_action = action_by_actor_round[("Actor0", 3)]
    unrelated_action = action_by_actor_round[("Actor1", 3)]
    response_action = action_by_actor_round[("Actor0", 6)]
    assert delivery_action["status"] == "ok"
    assert delivery_action["option"]["id"] == f"fulfill:{llm.commitment_id}"
    assert delivery_action["targets"] == ["Actor1"]
    assert delivery_action["commitment"] is None
    assert delivery_action["alliance_moves"] == []
    assert delivery_action["terms"] == ""
    assert unrelated_action["option"]["id"] == "public_statement"
    assert "picnic" in unrelated_action["public_statement"]
    assert response_action["option"]["id"] == "public_statement"
    assert "independently verified delivery safeguards" in response_action["public_statement"]

    decision_calls = [c for c in llm.calls if c["kind"] == "decision"]
    for actor in ("Actor0", "Actor1"):
        assert [c["round"] for c in decision_calls if c["actor"] == actor] == [1, 2, 3, 4, 5, 6]
    assert [c["round"] for c in llm.calls if c["kind"] == "arbiter"] == [1, 2, 3, 4, 5, 6]
    delivery_prompt = next(c["content"] for c in decision_calls if c["actor"] == "Actor0" and c["round"] == 3)
    response_prompt = next(c["content"] for c in decision_calls if c["actor"] == "Actor0" and c["round"] == 6)
    breacher_prompt = next(c["content"] for c in decision_calls if c["actor"] == "Actor1" and c["round"] == 6)
    assert f"[{llm.commitment_id}]" in delivery_prompt and "DUE NOW" in delivery_prompt
    assert f"[fulfill:{llm.commitment_id}]" not in delivery_prompt
    assert breaches[0]["description"] in response_prompt
    assert "Your commitment outcomes last period:" in response_prompt
    assert "Your simulated credibility (0–1): 0.52" in response_prompt
    assert breaches[0]["description"] in breacher_prompt
    assert "Your commitment outcomes last period:" in breacher_prompt
    assert "Your simulated credibility (0–1): 0.35" in breacher_prompt
    assert "Relationships that moved last period: Actor1" in response_prompt
    notes = [text for env in envs for text, _ in env.agent_graph.get_agent(0).memory_notes
             if text.startswith("# WORLD CLOCK") and "round 6/6" in text]
    assert notes and breaches[0]["description"] in notes[0]
    move_notes = [text for env in envs for text, _ in env.agent_graph.get_agent(0).memory_notes
                  if text.startswith("# YOUR MOVE THIS PERIOD")]
    delivery_notes = [text for text in move_notes if delivered["description"] in text]
    assert len(delivery_notes) == 1
    assert "You committed to:" not in delivery_notes[0]
    assert all(_EXTRA_PLEDGE not in text and _EXTRA_TERMS not in text for text in move_notes)
    posts = [e for e in platform_events
             if e.get("action_type") == "CREATE_POST" and e.get("round") == 6
             and e.get("agent_name") == "Actor0"]
    assert any("independently verified delivery safeguards" in json.dumps(p["action_args"]) for p in posts)
    updates = [e for e in platform_events if e.get("event_type") == "world_update"]
    assert [e["round"] for e in updates] == [1, 2, 3, 4, 5, 6]
