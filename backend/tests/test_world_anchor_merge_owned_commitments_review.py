"""R5: real operative agreements at strict actor and authenticated restore boundaries.

Run only with main_offline_pytest.py. Existing anchor/publication fixtures are
reused unchanged; model transports are scripted and all durable writes are in
the guard's fresh evidence directory.
"""

import asyncio
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import sys

import pytest

from app.services import agent_decision as ad
from app.services import world_update as wu
from app.services.world_model import ActorState, WorldModel
from test_target_simulation import case as _target_case
from test_world_anchor_reflexive import _published_coordinator


pytestmark = pytest.mark.guarded_runner
target_case = _target_case

PERIODS = {
    1: {"period_start": "2026-10-28", "period_end": "2026-10-31"},
    2: {"period_start": "2026-11-01", "period_end": "2026-11-15"},
    3: {"period_start": "2026-11-16", "period_end": "2026-11-30"},
    4: {"period_start": "2026-12-01", "period_end": "2026-12-31"},
    5: {"period_start": "2027-01-01", "period_end": "2027-01-31"},
}
OPERATIVE = {
    "schema_version": "operative-terms/v1",
    "offer_expires_on": "2026-11-30",
    "effective_on": "2026-11-16",
    "delivery_deadline": "2026-12-15",
    "duration_days": 10,
    "fulfillment_condition": "Both parties publish the agreed schedule.",
}
PROSE = "Publish the jointly agreed schedule."


@pytest.fixture(scope="module", autouse=True)
def record_review_r5_source_pins():
    guard = sys.modules.get("main_offline_guard")
    assert guard is not None, "R5 requires the offline guard before application imports."
    root = Path(__file__).resolve().parents[2]
    names = [
        "backend/scripts/main_offline_pytest.py",
        "backend/scripts/run_parallel_simulation.py",
        "backend/app/services/world_model.py",
        "backend/app/services/world_model_seed.py",
        "backend/app/services/agent_decision.py",
        "backend/app/services/world_update.py",
        "backend/app/services/actor_context.py",
        "backend/app/services/world_anchor.py",
        "backend/app/services/official_data.py",
        "backend/app/services/simulation_manager.py",
        "backend/app/services/simulation_config_generator.py",
        "deerflow_bridge/world_anchor.py",
        "deerflow_bridge/world_anchor_binding.py",
        "deerflow_bridge/world_anchor_publication.py",
        "backend/tests/test_world_anchor_merge_owned_commitments_review.py",
        "backend/tests/test_world_anchor_reflexive.py",
        "backend/tests/test_world_anchor.py",
        "backend/tests/test_target_simulation.py",
        "backend/tests/test_agency_classification.py",
        "backend/tests/test_world_model_loop.py",
        "backend/tests/test_calendar_round_loop.py",
        "backend/tests/conftest.py",
    ]
    before = {name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in names}
    for name, digest in before.items():
        guard.source_hashes.setdefault(str(root / name), digest)
    yield
    after = {name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in names}
    (guard.root / "review-r5-source-freeze.json").write_text(json.dumps({
        "before": before, "after": after,
        "source_drift": [name for name in names if before[name] != after[name]],
    }, indent=2) + "\n")


def _record(stage, **data):
    path = Path(os.environ["MAIN_OFFLINE_EVIDENCE"]) / "review-r5-observations.jsonl"
    with path.open("a") as stream:
        stream.write(json.dumps({"test": os.environ.get("PYTEST_CURRENT_TEST"),
                                 "stage": stage, **data}, sort_keys=True) + "\n")


def _move(world, actor_id, option_id, **fields):
    actor = world.actors[actor_id]
    return ad.parse_decision({"option_id": option_id, **fields}, actor=actor, world=world,
                             options=ad.build_option_menu(actor, world, world.round, max_options=512),
                             scenarios=[], round_num=world.round)


@pytest.fixture
def agreement_factory(tmp_path, monkeypatch, target_case):
    def make(*, action_policy=False, operative=None, accept=True):
        coordinator, _, context, _ = _published_coordinator(tmp_path, monkeypatch, target_case)
        world = coordinator.world
        world.settings["agreement_policy"] = "operative-deadline-v1"
        if action_policy:
            world.settings["action_policy"] = "affordable-menu-v2"
        else:
            world.settings.pop("action_policy", None)
        world.add_actor(ActorState(7, "Counterparty", agency_class="firm", capacity_per_round=3))
        world.start_round(1, PERIODS[1])
        proposal = _move(world, 7, "open_talks", targets=[0], terms=PROSE,
                         operative_terms=deepcopy(OPERATIVE if operative is None else operative),
                         public_statement="We offer a joint schedule.")
        assert proposal.ok, proposal.to_dict()
        world.register_decisions(1, [proposal.to_dict()])
        interaction = next(reversed(world.interactions.values()))
        assert interaction.status == "open"
        world.commit_round(1)
        world.start_round(2, PERIODS[2])
        if not accept:
            return coordinator, context, interaction, None
        decision = _move(world, 0, "accept:" + interaction.id,
                         accepted_terms_hash=interaction.operative_terms_hash,
                         terms=PROSE, public_statement="We accept the exact schedule terms.")
        assert decision.ok, decision.to_dict()
        world.register_decisions(2, [decision.to_dict()])
        assert interaction.status == "accepted"
        own = world.actors[0].commitments[0]
        rival = world.actors[7].commitments[0]
        assert own["id"] in interaction.obligations and rival["id"] in interaction.obligations
        assert own["made_round"] == 2 and own["due_round"] is None
        assert own["operative_terms"] == interaction.operative_terms
        assert own["operative_terms_hash"] == interaction.operative_terms_hash
        assert own["counterparty"] == 7
        own["private_note"] = "DENIED_PRIVATE_COMMITMENT"
        rival["description"] = "DENIED_RIVAL_COMMITMENT"
        world.actors[0].goals = ["DENIED_PRIVATE_GOAL"]
        _record("accepted", own_id=own["id"], due_round=own["due_round"],
                operative_terms=own["operative_terms"], obligations=interaction.obligations)
        return coordinator, context, interaction, own
    return make


def _advance(world, round_num, period=None):
    world.commit_round(world.round)
    world.start_round(round_num, PERIODS[round_num] if period is None else period)


def _reload(coordinator, context):
    saved = json.loads(json.dumps(coordinator.world.to_dict()))
    with pytest.raises(ValueError):
        WorldModel.from_dict(saved)
    with pytest.raises(ValueError):
        WorldModel.from_dict(saved, anchor_context={"pack_hash": context.pack_hash})
    restored = WorldModel.from_dict(saved, anchor_context=context)
    assert restored.to_dict() == saved
    assert restored._anchor_context is context
    coordinator._world = restored
    return restored


def _assert_open(projection, own):
    rows = projection["open_commitments"]
    assert [row["id"] for row in rows] == [own["id"]], projection
    row = rows[0]
    assert row["due_round"] is None
    assert row["operative_terms"] == own["operative_terms"]
    assert row["operative_terms_hash"] == own["operative_terms_hash"]
    assert set(row) == {"id", "description", "made_round", "due_round", "status",
                        "operative_terms", "operative_terms_hash"}


def _capture_requests(coordinator, context, channel):
    world = coordinator.world
    if channel == "structured":
        class Capture:
            def __init__(self):
                self.calls = []

            def chat_json(self, **kwargs):
                self.calls.append(deepcopy(kwargs["messages"]))
                return {"option_id": "hold_position"}

        model = Capture()
        result = ad.elicit_decision(model, system_message="DENIED_OLD_ROLE",
            user_prompt="DENIED_PRIVATE_CACHE", actor=world.actors[0], world=world,
            options=ad.build_option_menu(world.actors[0], world, world.round), scenarios=[],
            round_num=world.round, anchor_context=context, entity_uuid="entity-1")
        assert result.ok
        _record("captured_requests", channel=channel, requests=model.calls)
        return model.calls

    from camel.agents import ChatAgent
    from camel.messages import BaseMessage
    from camel.models.stub_model import StubModel
    from camel.types import ModelType, OpenAIBackendRole
    from test_world_model_loop import rps

    class NativeCapture(StubModel):
        calls = []

        async def _arun(self, messages, response_format=None, tools=None):
            self.calls.append(deepcopy(messages))
            return await super()._arun(messages, response_format, tools)

    backend = NativeCapture(ModelType.STUB)
    agent = ChatAgent(system_message="DENIED_NATIVE_ROLE", model=backend, agent_id="0")
    agent.update_memory(BaseMessage.make_user_message("user", "DENIED_NATIVE_CACHE"), OpenAIBackendRole.USER)
    rps._install_anchor_actor_payloads(coordinator, [(0, agent)], world.period)
    asyncio.run(agent.astep("Discuss your own obligations and verified outcomes."))
    reaction = rps._make_reaction_agent(agent, [])
    asyncio.run(reaction.astep("Respond about your own obligations and verified outcomes."))
    assert len(backend.calls) == 2
    _record("captured_requests", channel=channel, requests=backend.calls)
    return backend.calls


def _owned_from_request(messages):
    decoder = json.JSONDecoder()
    for message in messages:
        content = message["content"]
        for position, character in enumerate(content):
            if character != "{":
                continue
            try:
                value, _ = decoder.raw_decode(content[position:])
            except ValueError:
                continue
            if isinstance(value, dict) and "owned_simulated_state" in value:
                return value["owned_simulated_state"]
    pytest.fail("Actual model request did not contain owned_simulated_state.")


def _resolve_delivery(world, own, outcome="success"):
    assert world.delivery_commitment(0, own["id"], world.round) is own
    decision = _move(world, 0, "hold_position", deliveries=[own["id"]])
    assert decision.ok and decision.deliveries == [own["id"]], decision.to_dict()
    world.register_decisions(world.round, [decision.to_dict()])
    assert own["last_fulfillment_attempt"]["outcome"] == "unverified"
    update, problems = wu.validate_arbiter_update({"action_resolutions": [{
        "agent_id": 0, "commitment_id": own["id"], "action_round": world.round,
        "outcome": outcome, "rationale": "DENIED_PRIVATE_RESOLUTION_RATIONALE",
    }]}, world, strict=True)
    assert not problems, problems
    world.apply_arbiter_update(world.round, update)
    assert own["last_fulfillment_attempt"]["outcome"] == outcome
    if outcome == "success":
        assert own["status"] == "fulfilled" and own["fulfilled_round"] == world.round
    _record("delivery_resolved", outcome=outcome, commitment=own)


@pytest.mark.parametrize("action_policy", [False, True], ids=["separate-deliveries", "affordable-menu"])
@pytest.mark.parametrize("channel", ["structured", "organic-and-reaction"])
def test_r5_later_request_exposes_accepted_date_agreement_after_authenticated_reload(
        agreement_factory, action_policy, channel):
    coordinator, context, _, own = agreement_factory(action_policy=action_policy)
    _advance(coordinator.world, 3)
    world = _reload(coordinator, context)
    own = world.actors[0].commitments[0]
    assert world.delivery_commitment(0, own["id"], 3) is own
    if not action_policy:
        assert not any(o["id"].startswith("fulfill:")
                       for o in ad.build_option_menu(world.actors[0], world, 3))
    requests = _capture_requests(coordinator, context, channel)
    assert "DENIED_" not in json.dumps(requests)
    for messages in requests:
        projection = _owned_from_request(messages)
        _record("open_request", channel=channel, projection=projection)
        _assert_open(projection, own)


@pytest.mark.parametrize("outcome", ["success", "partial", "failed"])
@pytest.mark.parametrize("channel", ["structured", "organic-and-reaction"])
def test_r5_verified_delivery_outcome_survives_authenticated_reload_and_later_request(
        agreement_factory, outcome, channel):
    coordinator, context, _, own = agreement_factory()
    _advance(coordinator.world, 3)
    _resolve_delivery(coordinator.world, own, outcome)
    world = _reload(coordinator, context)
    _advance(world, 4)
    own = world.actors[0].commitments[0]
    assert own["due_round"] is None
    requests = _capture_requests(coordinator, context, channel)
    assert "DENIED_" not in json.dumps(requests)
    for messages in requests:
        projection = _owned_from_request(messages)
        _record("outcome_request", channel=channel, expected_outcome=outcome, projection=projection)
        assert {"commitment_id": own["id"], "round": 3, "outcome": outcome} in projection["own_outcomes"]
        if outcome == "success":
            assert projection["open_commitments"] == []
        else:
            _assert_open(projection, own)


@pytest.mark.parametrize("timing,round_num,period,deliverable,visible", [
    ("acceptance-period", 2, PERIODS[2], False, True),
    ("later-round-same-period", 3, PERIODS[2], False, True),
    ("later-round-same-period-effective", 3, PERIODS[2], True, True),
    ("effective-later-period", 3, PERIODS[3], True, True),
    ("deadline-in-period", 4, PERIODS[4], True, True),
    ("past-deadline", 5, PERIODS[5], False, False),
])
def test_r5_date_timing_does_not_invent_round_deadlines(
        agreement_factory, timing, round_num, period, deliverable, visible):
    operative = {**OPERATIVE, "effective_on": "2026-11-01"} if timing.endswith("-effective") else OPERATIVE
    coordinator, _, _, own = agreement_factory(operative=operative)
    world = coordinator.world
    if round_num != 2:
        _advance(world, round_num, period)
    assert (world.delivery_commitment(0, own["id"], round_num) is own) is deliverable
    projection = world.anchor_owned_simulated_state(0)
    _record("date_timing", timing=timing, deliverable=deliverable, projection=projection)
    assert own["due_round"] is None
    if visible:
        _assert_open(projection, own)
    else:
        assert projection["open_commitments"] == []


def test_r5_duration_without_deadline_remains_open_in_later_period(agreement_factory):
    coordinator, context, _, own = agreement_factory(operative={**OPERATIVE, "delivery_deadline": None})
    _advance(coordinator.world, 5)
    world = _reload(coordinator, context)
    own = world.actors[0].commitments[0]
    assert world.commitment_timing(own, 5) == (False, False)
    assert world.delivery_commitment(0, own["id"], 5) is own
    projection = world.anchor_owned_simulated_state(0)
    _record("duration_is_not_deadline", projection=projection)
    _assert_open(projection, own)


@pytest.mark.parametrize("period", [PERIODS[2], PERIODS[3]], ids=["same-period", "later-period"])
def test_r5_valid_date_delivery_and_authenticated_reload_control(agreement_factory, period):
    coordinator, context, _, own = agreement_factory(operative={**OPERATIVE, "effective_on": "2026-11-01"})
    world = coordinator.world
    assert world.delivery_commitment(0, own["id"], 2) is None
    _advance(world, 3, period)
    _resolve_delivery(world, own)
    world = _reload(coordinator, context)
    restored = world.actors[0].commitments[0]
    assert restored["due_round"] is None
    assert restored["fulfillment_evidence"] == own["fulfillment_evidence"]
    assert restored["fulfillment_evidence"]["commitment_target_ids"] == [7]


def test_r5_verified_success_remains_owned_after_calendar_deadline(agreement_factory):
    coordinator, context, interaction, own = agreement_factory()
    world = coordinator.world
    _advance(world, 3)
    _resolve_delivery(world, own)
    _advance(world, 5)
    world.lapse_overdue_commitments(5)
    assert interaction.status == "breached"
    world = _reload(coordinator, context)
    restored = world.actors[0].commitments[0]
    assert restored["status"] == "fulfilled"
    projection = world.anchor_owned_simulated_state(0)
    _record("outcome_after_deadline", projection=projection)
    assert projection == {"open_commitments": [], "own_outcomes": [
        {"commitment_id": own["id"], "round": 3, "outcome": "success"}]}


@pytest.mark.parametrize("phase", ["open", "fulfilled", "breached"])
@pytest.mark.parametrize("forgery", ["terms", "hash", "source", "obligation", "counterparty", "owner", "duplicate-id"])
def test_r5_forged_binding_is_excluded_from_owned_projection(agreement_factory, forgery, phase):
    coordinator, context, interaction, own = agreement_factory()
    world = coordinator.world
    _advance(world, 3)
    assert world.delivery_commitment(0, own["id"], 3) is own
    if phase != "open":
        _resolve_delivery(world, own)
    if phase == "breached":
        _advance(world, 5)
        world.lapse_overdue_commitments(5)
        assert interaction.status == "breached"
    world = _reload(coordinator, context)
    own = world.actors[0].commitments[0]
    interaction = world.interactions[interaction.id]
    if forgery == "terms":
        own["operative_terms"]["fulfillment_condition"] = "DENIED_FORGED_TERMS"
    elif forgery == "hash":
        own["operative_terms_hash"] = "0" * 64
    elif forgery == "source":
        own["source"] = "agreement:missing"
    elif forgery == "obligation":
        interaction.obligations.remove(own["id"])
    elif forgery == "counterparty":
        own["counterparty"] = 0
    elif forgery == "owner":
        world.actors[0].commitments = [deepcopy(world.actors[7].commitments[0])]
    else:
        world.actors[0].commitments.append(deepcopy(own))
    assert world.delivery_commitment(0, own["id"], world.round) is None
    projection = world.anchor_owned_simulated_state(0)
    assert projection == {"open_commitments": [], "own_outcomes": []}


@pytest.mark.parametrize("change", ["terms", "hash", "source", "obligation"])
def test_r5_authenticated_reload_rejects_forged_operative_binding(agreement_factory, change):
    coordinator, context, _, own = agreement_factory()
    saved = coordinator.world.to_dict()
    commitment = next(a for a in saved["actors"] if a["agent_id"] == 0)["commitments"][0]
    if change == "terms":
        commitment["operative_terms"]["delivery_deadline"] = "2026-12-16"
    elif change == "hash":
        commitment["operative_terms_hash"] = "0" * 64
    elif change == "source":
        commitment["source"] = "agreement:missing"
    else:
        saved["interactions"][0]["obligations"].remove(own["id"])
    with pytest.raises(ValueError, match="operative_terms.*binding mismatch"):
        WorldModel.from_dict(saved, anchor_context=context)


@pytest.mark.parametrize("change", ["terms", "hash", "prose"])
def test_r5_acceptance_keeps_exact_operative_and_prose_validation(agreement_factory, change):
    coordinator, _, interaction, _ = agreement_factory(accept=False)
    world = coordinator.world
    fields = {"accepted_terms_hash": interaction.operative_terms_hash, "terms": PROSE}
    if change == "terms":
        fields["operative_terms"] = {**OPERATIVE, "delivery_deadline": "2026-12-16"}
    elif change == "hash":
        fields["accepted_terms_hash"] = "0" * 64
    else:
        fields["terms"] = PROSE + " subject to a different condition."
    before = deepcopy(world.to_dict())
    rejected = _move(world, 0, "accept:" + interaction.id, **fields)
    assert not rejected.ok
    world.register_decisions(2, [rejected.to_dict()])
    assert interaction.status == "open"
    assert all(not actor.commitments for actor in world.actors.values())
    assert world.to_dict()["relationships"] == before["relationships"]


@pytest.mark.parametrize("change", ["agent", "commitment", "targets", "round"])
def test_r5_forged_resolution_evidence_never_enters_owned_outcomes(agreement_factory, change):
    coordinator, _, _, own = agreement_factory()
    world = coordinator.world
    _advance(world, 3)
    _resolve_delivery(world, own)
    for key in ("last_fulfillment_attempt", "fulfillment_evidence"):
        evidence = own[key]
        if change == "agent":
            evidence["agent_id"] = 7
        elif change == "commitment":
            evidence["commitment_id"] = world.actors[7].commitments[0]["id"]
        elif change == "targets":
            evidence["commitment_target_ids"] = [0]
        else:
            evidence["round"] = own["made_round"]
    assert world.anchor_owned_simulated_state(0) == {"open_commitments": [], "own_outcomes": []}


def test_r5_missing_due_round_saved_commitment_never_reaches_projection_keyerror(agreement_factory):
    coordinator, context, _, _ = agreement_factory()
    _advance(coordinator.world, 3)
    saved = coordinator.world.to_dict()
    commitment = next(a for a in saved["actors"] if a["agent_id"] == 0)["commitments"][0]
    assert commitment.pop("due_round") is None
    with pytest.raises(ValueError, match="operative_terms"):
        restored = WorldModel.from_dict(saved, anchor_context=context)
        _record("missing_due_round_survived_restore", commitment_id=commitment["id"])
        restored.anchor_owned_simulated_state(0)


@pytest.mark.parametrize("phase", ["open", "fulfilled", "breached"])
@pytest.mark.parametrize("boundary", ["restore", "projection"])
def test_r5_missing_due_round_is_a_typed_binding_failure(agreement_factory, phase, boundary):
    coordinator, context, interaction, own = agreement_factory()
    world = coordinator.world
    _advance(world, 3)
    if phase != "open":
        _resolve_delivery(world, own)
    if phase == "breached":
        _advance(world, 5)
        world.lapse_overdue_commitments(5)
        assert interaction.status == "breached"
    world = _reload(coordinator, context)
    own = world.actors[0].commitments[0]
    assert own.pop("due_round") is None
    _record("missing_due_round_boundary", boundary=boundary, phase=phase, commitment_id=own["id"])
    with pytest.raises(ValueError, match="operative_terms"):
        if boundary == "restore":
            WorldModel.from_dict(world.to_dict(), anchor_context=context)
        else:
            world.anchor_owned_simulated_state(0)


@pytest.mark.parametrize("phase", ["open", "fulfilled"])
def test_r5_explicit_null_due_round_preserves_authenticated_projection(agreement_factory, phase):
    coordinator, context, _, own = agreement_factory()
    _advance(coordinator.world, 3)
    if phase == "fulfilled":
        _resolve_delivery(coordinator.world, own)
    world = _reload(coordinator, context)
    own = world.actors[0].commitments[0]
    assert "due_round" in own and own["due_round"] is None
    projection = world.anchor_owned_simulated_state(0)
    _record("explicit_null_due_round", phase=phase, projection=projection)
    if phase == "open":
        _assert_open(projection, own)
    else:
        assert projection == {"open_commitments": [], "own_outcomes": [
            {"commitment_id": own["id"], "round": 3, "outcome": "success"}]}
