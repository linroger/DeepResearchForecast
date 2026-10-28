"""Offline proofs for the bounded legacy repairs in target-first review section 6."""

import copy
import json
import random

import pytest

from app.services import agent_decision as ad
from app.services import world_update as wu
from app.services.world_model import WorldModel


def _world():
    return WorldModel.from_seed({
        "question": "Will delivery expand capacity?",
        "state_variables": [
            {"name": "Capacity", "value": 100, "kind": "numeric"},
            {"name": "Permit", "value": False, "kind": "boolean"},
            {"name": "Status", "value": "pending", "kind": "categorical"},
        ],
        "actors": [
            {"agent_id": 0, "name": "Alpha", "agency_class": "firm", "capacity_per_round": 2},
            {"agent_id": 1, "name": "Regulator", "agency_class": "regulator_agency", "capacity_per_round": 2},
        ],
        "settings": {"max_change_ratio": None, "reversion_kappa": None, "max_drift_ratio": None},
    })


class _Scripted:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    def chat_json(self, **kwargs):
        self.calls.append(copy.deepcopy(kwargs))
        return copy.deepcopy(self.payload)


def _round(world, round_num, decisions=(), payload=None):
    return wu.run_world_round(world, round_num, {"label": f"P{round_num}"}, decisions, [],
                              llm=_Scripted(payload) if payload is not None else None,
                              rng=random.Random(42))


def _parse(world, raw, *, actor_id=0, options=None):
    actor = world.actors[actor_id]
    return ad.parse_decision(raw, actor=actor, world=world,
                             options=options if options is not None else ad.build_option_menu(actor, world, world.round),
                             scenarios=(), round_num=world.round)


def test_arbiter_never_reads_private_expectations_or_rationale():
    world = _world()
    world.start_round(1, {"label": "P1"})
    decision = _parse(world, {
        "option_id": "public_statement", "public_statement": "Public notice is safe.",
        "private_rationale": "PRIVATE_REASON_SENTINEL",
        "expected_reactions": [{"actor": "Regulator", "reaction": "PRIVATE_EXPECTATION_SENTINEL"}],
    })
    det = wu.deterministic_round_update(world, 1, world.period, [decision], [], random.Random(0))
    assert world.actors[0].expectations  # Private state is retained for its legitimate owner.
    llm = _Scripted({"narrative": "Quiet period."})
    status, _, _ = wu.run_arbiter(llm, world, 1, world.period, [decision], det, ())
    assert status == "applied"
    prompt = str(llm.calls)
    assert "Public notice is safe." in prompt
    assert "PRIVATE_REASON_SENTINEL" not in prompt
    assert "PRIVATE_EXPECTATION_SENTINEL" not in prompt
    assert "Expectations in play" not in prompt


def test_bad_numeric_and_due_fields_preserve_valid_rows_and_other_fields():
    """C8 labels repaired mixtures applied_partial instead of plain applied."""
    world = _world()
    result = _round(world, 1, payload={
        "variable_changes": [
            {"variable_id": "capacity", "delta": 10 ** 1000},
            {"variable_id": "capacity", "delta": 7},
            {"variable_id": "permit", "new_value": "agreed"},
        ],
        "pending_effects": [
            {"description": "Malformed due", "due_periods": float("inf")},
            {"description": "Valid later capacity", "due_periods": 2, "variable_id": "capacity", "delta": 3},
        ],
        "events": "not a list",
        "relationship_changes": [{"source": "Alpha", "target": "Regulator", "direction": "closer"}],
    })
    assert result["arbiter_status"] == "applied_partial"
    assert world.variables["capacity"].value == 107
    assert world.variables["permit"].value is True
    assert len(world.pending_effects) == 1
    assert world.pending_effects[0].due_round == 3
    assert world._relationship_between(0, 1).polarity > 0
    problems = " ".join(result["arbiter_problems"])
    assert "non-numeric" in problems and "invalid due_periods" in problems and "invalid events" in problems
    assert world.committed_round == 1


def test_bad_field_validation_does_not_discard_unrelated_fields(monkeypatch):
    """C8 retains valid fields but makes partial application explicit."""
    original = wu._validate_arbiter_fields

    def one_bad_field(raw, *args):
        if raw.get("events"):
            raise ValueError("simulated field conversion failure")
        return original(raw, *args)

    monkeypatch.setattr(wu, "_validate_arbiter_fields", one_bad_field)
    world = _world()
    result = _round(world, 1, payload={
        "events": [{"description": "Malformed field"}],
        "variable_changes": [{"variable_id": "status", "new_value": "reviewed"}],
    })
    assert result["arbiter_status"] == "applied_partial"
    assert world.variables["status"].value == "reviewed"
    assert result["arbiter_problems"] == ["invalid events: ValueError"]


def test_field_repair_preserves_conflicting_resolution_rejection():
    """Conflicting attestations still fail; valid sibling changes are partial success."""
    world = _world()
    world.start_round(1, {"label": "P1"})
    decision = _parse(world, {"option_id": "public_statement"})
    result = _round(world, 1, [decision], {
        "variable_changes": [{"variable_id": "capacity", "delta": 2}],
        "action_resolutions": [
            {"actor": "Alpha", "outcome": "success"},
            {"actor": "Alpha", "outcome": "nonsense"},
        ],
    })
    assert result["arbiter_status"] == "applied_partial"
    assert world.variables["capacity"].value == 102
    assert world.actors[0].last_action["resolution"] is None
    assert "duplicate actor resolutions" in result["arbiter_problems"]


def test_boolean_repair_never_treats_false_text_as_truthy():
    """Rejected ambiguous boolean fields now produce applied_partial diagnostics."""
    world = _world()
    result = _round(world, 1, payload={
        "new_variables": [
            {"name": "Agreement", "kind": "boolean", "value": "false"},
            {"name": "Ambiguous", "kind": "boolean", "value": "perhaps"},
        ],
        "pending_effects": [{"description": "Permit rejected", "variable_id": "permit", "new_value": "false"}],
    })
    assert result["arbiter_status"] == "applied_partial"
    assert world.variables["agreement"].value is False
    assert "ambiguous" not in world.variables
    assert world.pending_effects[0].value is False
    _round(world, 2)
    assert world.variables["permit"].value is False


@pytest.mark.parametrize("field", ["variable_changes", "pending_effects"])
@pytest.mark.parametrize("option_id,actor_id,lag,variable,value", [
    ("invest_capex", 0, 2, "capacity", 120),
    ("open_inquiry", 1, 1, "status", "under review"),
])
def test_attributed_action_effects_wait_for_catalogue_lag(field, option_id, actor_id, lag, variable, value):
    world = _world()
    world.start_round(1, {"label": "P1"})
    decision = _parse(world, {"option_id": option_id, "targets": ["Alpha"]}, actor_id=actor_id)
    assert decision.ok
    effect = {"variable_id": variable, "new_value": value, "caused_by": decision.actor_name,
              "description": "Implementation", "rationale": "Implementation", "due_periods": 1}
    old_value = world.variables[variable].value
    result = _round(world, 1, [decision], {field: [effect]})
    assert result["arbiter_status"] == "applied"  # Enforcing lag is not a rejected field.
    assert world.variables[variable].value == old_value
    assert len(world.pending_effects) == 1
    assert world.pending_effects[0].due_round == 1 + lag
    # Stored action timing and due effects survive a normal serialization cycle.
    world = WorldModel.from_dict(world.to_dict())
    assert world.actors[actor_id].last_action["effective_round"] == 1 + lag
    for round_num in range(2, lag + 2):
        _round(world, round_num)
        assert world.variables[variable].value == (value if round_num == lag + 1 else old_value)


def test_repeated_delayed_effect_in_two_arbiter_fields_is_not_applied_twice():
    world = _world()
    world.start_round(1, {"label": "P1"})
    decision = _parse(world, {"option_id": "invest_capex"})
    effect = {"variable_id": "capacity", "delta": 10, "caused_by": "Alpha"}
    _round(world, 1, [decision], {
        "variable_changes": [effect],
        "pending_effects": [{**effect, "description": "Implementation", "due_periods": 1}],
    })
    assert len(world.pending_effects) == 1
    _round(world, 2)
    _round(world, 3)
    assert world.variables["capacity"].value == 110


@pytest.mark.parametrize("due,probability", [(6, 1.0), (2, 0.25), (6, 0.25), (2, 1.0)])
def test_distinct_delayed_timing_or_probability_never_erases_guaranteed_effect(due, probability):
    world = _world()
    world.start_round(1, {"label": "P1"})
    decision = _parse(world, {"option_id": "invest_capex"})
    effect = {"variable_id": "capacity", "delta": 10, "caused_by": "Alpha"}
    # Isolate each identity guard: only the fourth case differs by description.
    description = "Optional second line" if due == 2 and probability == 1.0 else "First production line"
    _round(world, 1, [decision], {
        "variable_changes": [{**effect, "rationale": "First production line"}],
        "pending_effects": [{**effect, "description": description, "due_periods": due,
                             "probability": probability}],
    })
    assert sorted((fx.due_round, fx.probability) for fx in world.pending_effects) == sorted(
        [(3, 1.0), (1 + due, probability)])
    _round(world, 2)
    _round(world, 3)
    assert world.variables["capacity"].value == (120 if due == 2 and probability == 1.0 else 110)


def test_decision_call_uses_json_system_prompt_and_retains_only_fenced_dossier():
    world = _world()
    world.start_round(1, {"label": "P1"})
    actor = world.actors[0]
    llm = _Scripted({"option_id": "hold_position"})
    platform = ("Use OASIS_PLATFORM_TOOL_SENTINEL and call create_post.\n"
                "BEGIN UNTRUSTED DOSSIER DATA\nDOCUMENTED_EVIDENCE_SENTINEL\nEND UNTRUSTED DOSSIER DATA\n"
                "Respond using OASIS_RESPONSE_METHOD_SENTINEL.")
    decision = ad.elicit_decision(llm, system_message=platform, user_prompt="Return ONLY JSON.",
                                  actor=actor, world=world, options=ad.build_option_menu(actor, world, 1),
                                  scenarios=(), round_num=1)
    assert decision.ok
    messages = llm.calls[0]["messages"]
    assert messages[0]["role"] == "system"
    assert "Return exactly one JSON object" in messages[0]["content"]
    assert "Do not call tools" in messages[0]["content"]
    assert "DOCUMENTED_EVIDENCE_SENTINEL" in messages[1]["content"]
    assert "OASIS_PLATFORM_TOOL_SENTINEL" not in str(messages)
    assert "OASIS_RESPONSE_METHOD_SENTINEL" not in str(messages)
    assert "create_post" not in str(messages)


def test_stale_menu_and_custom_moves_cannot_spend_exhausted_capacity():
    world = _world()
    world.start_round(1, {"label": "P1"})
    actor = world.actors[0]
    menu = ad.build_option_menu(actor, world, 1)
    actor.capacity_used = actor.capacity_per_round
    for raw in ({"option_id": "public_statement"},
                {"option_id": "custom", "custom_action": {"kind": "economic", "label": "Invest"}}):
        decision = _parse(world, raw, options=menu)
        assert decision.status == "invalid"
        assert decision.option["id"] == "hold_position"
        assert "capacity" in " ".join(decision.problems)
    assert _parse(world, {"option_id": "hold_position"}, options=menu).ok
    assert all(option["cost"] == 0 for option in ad.build_option_menu(actor, world, 1))


def test_custom_kind_requires_class_decision_right_and_preserves_cost_and_lag():
    world = _world()
    world.start_round(1, {"label": "P1"})
    blocked = _parse(world, {"option_id": "custom", "custom_action": {"kind": "policy", "label": "Set national tax"}})
    assert blocked.status == "invalid"
    assert "decision right" in " ".join(blocked.problems)
    accepted = _parse(world, {"option_id": "custom", "custom_action": {"kind": "legal", "label": "File suit"},
                              "targets": ["Regulator"]})
    assert accepted.ok and accepted.option["cost"] == 2 and accepted.option["lag"] == 1


@pytest.mark.parametrize("key,value", [("cost", 0), ("lag", 0), ("kind", "policy")])
def test_tampered_catalogue_menu_cannot_discount_cost_lag_or_change_rights(key, value):
    world = _world()
    world.start_round(1, {"label": "P1"})
    option = next(t.to_option() for t in ad.catalog_for("firm") if t.id == "invest_capex")
    option[key] = value
    assert _parse(world, {"option_id": "invest_capex"}, options=[option]).status == "invalid"


def test_foreign_catalogue_right_is_not_granted_by_a_forged_menu():
    world = _world()
    world.start_round(1, {"label": "P1"})
    option = next(t.to_option() for t in ad.catalog_for("central_bank") if t.id == "rate_move")
    blocked = _parse(world, {"option_id": "rate_move"}, options=[option])
    assert blocked.status == "invalid"
    assert "decision right" in " ".join(blocked.problems)


def test_documented_plan_cost_is_not_discounted_to_fit_capacity():
    world = _world()
    world.start_round(1, {"label": "P1"})
    actor = world.actors[0]
    actor.documented_plans = ["Invest in a new factory"]
    assert not any(option["id"] == "plan_1" for option in ad.build_option_menu(actor, world, 1))
    actor.capacity_per_round = 3
    [plan] = [option for option in ad.build_option_menu(actor, world, 1) if option["id"] == "plan_1"]
    assert plan["cost"] == 3 and plan["lag"] == 2


def test_maintenance_identity_is_preserved_while_discretionary_options_remain_available():
    """C11 removes fulfill menu slots; an ordinary move still cannot imply delivery."""
    world = _world()
    promise = world.actors[0].add_commitment("Deliver audited report", made_round=1, due_round=2)
    world.start_round(2, {"label": "P2"})
    ids = [option["id"] for option in ad.build_option_menu(world.actors[0], world, 2)]
    assert not any(oid.startswith("fulfill:") for oid in ids) and "public_statement" in ids
    decision = _parse(world, {"option_id": "public_statement"})
    _round(world, 2, [decision])
    assert promise["status"] == "due"
    assert "fulfillment_evidence" not in promise


@pytest.mark.parametrize("repair,status,value", [("field", "applied_partial", 105), ("round", "invalid", 100)])
def test_arbiter_repair_policy_and_raw_evidence(repair, status, value):
    world = _world()
    payload = {"variable_changes": [{"variable_id": "capacity", "delta": 5}], "events": "invalid"}
    result = wu.run_world_round(world, 1, {"label": "P1"}, [], [], llm=_Scripted(payload),
                                rng=random.Random(0), arbiter_repair=repair)
    assert result["arbiter_status"] == status
    assert world.variables["capacity"].value == value
    assert result["arbiter_raw"] == payload
    assert result["arbiter_validated"]["variable_changes"][0]["delta"] == 5
    assert result["arbiter_problem_details"][0]["code"] == "field_rejected"
    assert world.committed_round == 1


def test_only_unparseable_json_gets_one_temperature_zero_correction():
    class Transport:
        def __init__(self, responses):
            self.responses = iter(responses)
            self.temperatures = []

        @staticmethod
        def _parse_json_response(text):
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                return None

        def chat(self, **kwargs):
            self.temperatures.append(kwargs["temperature"])
            return next(self.responses)

    for responses, expected, status in [
        (["not-json", '{"narrative":"Recovered"}'], [0.3, 0.0], "applied"),
        (['{"narrative":"Valid","events":3}'], [0.3], "applied_partial"),
        (["not-json", "still-invalid"], [0.3, 0.0], "invalid"),
        (["null"], [0.3], "invalid"),
        (["```json\nnull\n```"], [0.3], "invalid"),
    ]:
        llm = Transport(responses)
        result = wu.run_world_round(_world(), 1, None, [], [], llm=llm, rng=random.Random(0))
        assert llm.temperatures == expected
        assert result["arbiter_status"] == status and result["arbiter_attempts"] == responses


@pytest.mark.parametrize("agency_class", ad.AGENCY_CLASSES)
def test_every_catalogue_entry_is_affordable_and_reachable_across_rounds(agency_class):
    world = WorldModel.from_seed({"actors": [{"agent_id": 0, "name": "Actor", "agency_class": agency_class}]})
    actor = world.actors[0]
    catalogue = ad.catalog_for(agency_class)
    assert actor.capacity_per_round == ad.default_capacity(agency_class)
    assert all(t.cost <= actor.capacity_per_round for t in catalogue)
    reachable = set()
    for period in range(1, len(catalogue) + 1):
        world.start_round(period, None)
        menu = ad.build_option_menu(actor, world, period)
        assert len(menu) <= ad.MAX_OPTIONS
        reachable.update(o["id"] for o in menu)
    assert {t.id for t in catalogue} <= reachable


@pytest.mark.parametrize("option", [
    {"id": "custom", "label": "Free investment", "kind": "economic", "cost": 0, "lag": 1},
    {"id": "custom", "label": "Set national tax", "kind": "policy", "cost": 2, "lag": 1},
    {"id": "rate_move", "label": "Set rate", "kind": "policy", "cost": 2, "lag": 1},
    {"id": "invest_capex", "label": "Investment", "kind": "economic", "cost": 2, "lag": 0},
])
def test_raw_kernel_cannot_bypass_canonical_custom_rights_cost_or_lag(option):
    world = _world()
    world.start_round(1, None)
    world.register_decisions(1, [{"agent_id": 0, "status": "ok", "round": 1, "option": option}])
    assert world.actors[0].capacity_used == 0
    assert world.actors[0].last_action["status"] == "invalid"
    assert world.actors[0].commitments == []


def test_kernel_spends_cumulatively_and_preserves_first_valid_move():
    world = _world()
    world.start_round(1, None)
    first = _parse(world, {"option_id": "public_statement"})
    second = _parse(world, {"option_id": "invest_capex"})
    world.register_decisions(1, [first.to_dict(), second.to_dict()])
    actor = world.actors[0]
    assert actor.capacity_used == 1
    assert actor.last_action["option_id"] == "public_statement"
    assert actor.commitments == []


def test_discretionary_move_and_two_deliveries_have_independent_exact_resolutions():
    world = _world()
    actor = world.actors[0]
    promises = [actor.add_commitment(f"Deliver report {i}", made_round=1, due_round=2) for i in range(2)]
    world.start_round(2, {"label": "P2"})
    decision = _parse(world, {"option_id": "public_statement", "deliveries": [c["id"] for c in promises],
                              "public_statement": "We delivered both reports and announced a new schedule."})
    assert decision.ok
    payload = {"action_resolutions": [{"actor": "Alpha", "outcome": "partial", "rationale": "Schedule announced"},
        *[{"actor": "Alpha", "commitment_id": c["id"], "action_round": 2, "outcome": "success",
           "rationale": f"Confirmed receipt of {c['description']}"} for c in promises]]}
    record = _round(world, 2, [decision], payload)
    assert record["arbiter_status"] == "applied"
    assert record["arbiter"]["commitments_fulfilled"] == 2
    assert actor.capacity_used == 1
    assert actor.last_action["option_id"] == "public_statement" and actor.last_action["resolution"] == "partial"
    assert all(c["status"] == "fulfilled" for c in promises)
    # Replaying attestation cannot earn a second credit or change the move.
    accepted = copy.deepcopy(actor.to_dict())
    world.apply_arbiter_update(2, payload)
    assert actor.to_dict() == accepted


@pytest.mark.parametrize("terms,due,basis", [
    ("Deliver both reports by 2026-12-31.", 4, "terms"),
    ("Deliver both reports within two periods.", 4, "terms"),
    ("Deliver both reports within 60 days.", 4, "terms"),
    ("Deliver both reports promptly.", 3, "default"),
])
def test_agreed_terms_grace_and_symmetric_breach_are_durable(terms, due, basis):
    world = _world()
    world.start_round(1, {"label": "2026-09", "period_start": "2026-09-01", "period_end": "2026-09-30"})
    world.open_interaction(1, 0, 1, "open_talks", terms)
    iid = next(iter(world.interactions))
    world.start_round(2, {"label": "2026-10", "period_start": "2026-10-01", "period_end": "2026-10-31"})
    world.resolve_interaction(2, iid, "accept", 1, lag=1)
    obligations = [a.commitments[0] for a in world.actors.values()]
    assert all(c["due_round"] == due and c["due_basis"] == basis for c in obligations)
    world = WorldModel.from_dict(world.to_dict())
    world.start_round(due + 1, None)
    assert world.lapse_overdue_commitments(due + 1) == []
    assert all(world.delivery_commitment(a.agent_id, a.commitments[0]["id"], due + 1) for a in world.actors.values())
    snapshot = world.to_dict()
    outcomes = []
    for reverse in (False, True):
        clone = WorldModel.from_dict(json.loads(json.dumps(snapshot)))
        if reverse:
            clone.actors = dict(reversed(list(clone.actors.items())))
        clone.start_round(due + 2, None)
        clone.lapse_overdue_commitments(due + 2)
        outcomes.append(sorted((aid, a.commitments[0]["status"], a.reputation) for aid, a in clone.actors.items()))
        assert all(a.commitments[0]["status"] == "breached" for a in clone.actors.values())
        assert len(clone.events_in_round(due + 2, ("breach",))) == 2
    assert outcomes[0] == outcomes[1]


def test_private_brief_prioritizes_red_lines_at_a_small_budget():
    world = _world()
    actor = world.actors[0]
    actor.red_lines = ["Never publish the confidential design."]
    actor.documented_plans = ["Long ongoing programme " * 50] * 4
    actor.goals = ["Long business goal " * 50] * 4
    text = world.render_private_brief(0, max_chars=180)
    assert "Never publish the confidential design." in text and len(text) <= 180


def _structural_world():
    projection = {
        "sources": [], "resolution": {"targetNodeId": "total"},
        "nodes": [
            {"nodeId": "base", "value": 10, "visibility": "public", "units": "units"},
            {"nodeId": "secret", "value": 4, "visibility": "private", "units": "units"},
            {"nodeId": "total", "value": 0, "visibility": "public", "units": "units"},
        ],
        "mechanisms": [{"mechanismId": "identity", "kind": "sum", "inputNodeIds": ["base", "secret"],
                        "outputNodeId": "total", "parameters": {}, "basis": "assumed", "sourceIds": [],
                        "gap": "Synthetic private-input identity for offline testing."}],
    }
    return WorldModel.from_seed({
        "target_projection": projection,
        "state_variables": [{"id": "base", "name": "Base", "value": 10},
                            {"id": "secret", "name": "PRIVATE_NODE_SENTINEL", "value": 4},
                            {"id": "total", "name": "Total", "value": 0, "read_only": True}],
        "actors": [{"agent_id": 0, "name": "Alpha", "agency_class": "firm"}],
    })


def test_kernel_propagates_structural_identity_without_flat_private_nodes_or_arbiter_writes():
    world = _structural_world()
    world.start_round(1, None)
    assert "secret" not in world.variables
    result = world.evaluate_target_projection(1, random.Random(9))
    assert result["status"] == "ready"
    assert world.public_target_values() == {"base": 10, "total": 14}
    assert world.variables["total"].value == 14
    payload = {"variable_changes": [{"variable_id": "total", "new_value": 999}],
               "new_variables": [{"name": "secret", "value": 999}],
               "pending_effects": [{"description": "Override target", "variable_id": "total", "delta": 10}]}
    update, problems = wu.validate_arbiter_update(payload, world)
    assert problems and not update["variable_changes"] and not update["new_variables"] and not update["pending_effects"]
    world.apply_arbiter_update(1, payload)  # Raw kernel bypass is guarded too.
    assert world.variables["total"].value == 14 and "secret" not in world.variables and not world.pending_effects
    prompt = wu.build_arbiter_prompt(world, 1, None, [], {}, ())
    assert "PRIVATE_NODE_SENTINEL" not in prompt and "secret" not in prompt
    restored = WorldModel.from_dict(json.loads(json.dumps(world.to_dict())))
    assert "secret" not in restored.variables
    restored.start_round(2, None)
    assert restored.public_target_values() == {}
    assert restored.evaluate_target_projection(2, random.Random(10))["status"] == "ready"
    assert restored.public_target_values()["total"] == 14


def test_unusable_structural_identity_explicitly_declines_predicate_values():
    world = _structural_world()
    world._target_projection["mechanisms"][0]["inputNodeIds"] = ["total"]  # cycle
    world.start_round(1, None)
    result = world.evaluate_target_projection(1, random.Random(9))
    assert result["status"] == "unavailable" and result["reason"] == "invalid_target_projection"
    assert world.public_target_values() == {}
    assert "secret" not in world.variables


def test_runner_persists_raw_validation_for_every_path_once_and_preserves_on_resume(tmp_path, monkeypatch):
    from tests.test_world_paths import _run_paths
    _run_paths(monkeypatch, tmp_path, k="2")
    evidence = tmp_path / "arbiter_raw.jsonl"
    before = evidence.read_bytes()
    rows = [json.loads(line) for line in before.splitlines()]
    assert {(r["round"], r["path"]) for r in rows} == {(r, p) for r in (1, 2, 3) for p in (0, 1)}
    assert len(rows) == 6
    assert all(isinstance(r["arbiter_raw"], dict) and isinstance(r["arbiter_validated"], dict) for r in rows)
    assert all(r["arbiter_repair"] == "field" and r["config_hash"] for r in rows)
    _run_paths(monkeypatch, tmp_path, k="2", resume=True)
    assert evidence.read_bytes() == before


def test_runner_rejects_unknown_repair_policy(tmp_path, monkeypatch):
    from tests.test_world_model_loop import rps
    monkeypatch.setenv("SIM_WORLD_ARBITER_REPAIR", "round-typo")
    with pytest.raises(ValueError, match="field or round"):
        rps._world_arbiter_repair()
    checkpoint = tmp_path / "world_state.json"
    checkpoint.write_text("PRESERVE_EXISTING_CHECKPOINT")
    with pytest.raises(ValueError, match="field or round"):
        rps._get_world_coordinator({"world_model": {}}, str(tmp_path), 1, lambda _: None, resume=False)
    assert checkpoint.read_text() == "PRESERVE_EXISTING_CHECKPOINT"


@pytest.mark.parametrize("repair", ["field", "round"])
def test_repair_rollback_does_not_disable_valid_kernel_lag(repair):
    world = _world()
    world.start_round(1, None)
    decision = _parse(world, {"option_id": "invest_capex"})
    record = wu.run_world_round(world, 1, None, [decision], [], llm=_Scripted({
        "variable_changes": [{"variable_id": "capacity", "delta": 10, "caused_by": "Alpha"}]}),
        rng=random.Random(1), arbiter_repair=repair)
    assert record["arbiter_status"] == "applied"
    assert world.variables["capacity"].value == 100
    assert len(world.pending_effects) == 1 and world.pending_effects[0].due_round == 3


@pytest.mark.parametrize("forged_duplicate", [False, True])
def test_raw_input_cannot_overwrite_kernel_canonical_timing(forged_duplicate):
    world = _world()
    world.start_round(1, None)
    # Missing metadata is restored by the kernel, not defaulted to a zero lag.
    rows = [{"agent_id": 0, "actor_name": "Alpha", "round": 1, "status": "ok",
             "option": {"id": "invest_capex"}}]
    if forged_duplicate:
        rows[0] = _parse(world, {"option_id": "invest_capex"}).to_dict()
        forged = copy.deepcopy(rows[0])
        forged["option"]["lag"] = 0
        forged["public_statement"] = "REJECTED_DUPLICATE_SENTINEL"
        rows.append(forged)
    _round(world, 1, rows, {"variable_changes": [
        {"variable_id": "capacity", "new_value": 150, "caused_by": "Alpha"}]})
    assert world.actors[0].last_action["lag"] == 2
    assert world.actors[0].last_action["effective_round"] == 3
    assert world.variables["capacity"].value == 100
    assert len(world.pending_effects) == 1 and world.pending_effects[0].due_round == 3
    prompt = wu.build_arbiter_prompt(world, 1, None, rows, {}, ())
    assert "REJECTED_DUPLICATE_SENTINEL" not in prompt
    assert "Implementation lag: 2 period(s)" in prompt


def test_receipt_write_failure_retains_batch_and_fences_checkpoints(tmp_path, monkeypatch):
    from tests.test_world_model_loop import rps
    from app.utils import atomic
    coordinator = object.__new__(rps._ReflexiveWorldCoordinator)
    coordinator._dir = str(tmp_path)
    coordinator._config = {"simulation_id": "offline-receipt-test"}
    coordinator._config_fingerprint = "fixture-config-hash"
    coordinator._paths = [{"path": 1}]
    coordinator._arbiter_records = {}
    coordinator._arbiter_records_dirty = False
    coordinator._arbiter_restore_failed = False
    coordinator._arbiter_repair = "field"
    real_write = atomic.write_text_atomic
    fail = True

    def fail_receipt(path, text, *args, **kwargs):
        if fail and str(path).endswith("arbiter_raw.jsonl"):
            raise OSError("scripted full disk")
        return real_write(path, text, *args, **kwargs)

    monkeypatch.setattr(atomic, "write_text_atomic", fail_receipt)
    record = {"arbiter_status": "applied", "arbiter_raw": {"narrative": "Round one"},
              "arbiter_validated": {"narrative": "Round one"}}
    with pytest.raises(OSError, match="full disk"):
        coordinator._write_arbiter_records(1, None, record, [record])
    assert set(coordinator._arbiter_records) == {(1, 0), (1, 1)}
    # Both checkpoint entrypoints fail before constructing or writing payloads.
    with pytest.raises(OSError, match="full disk"):
        coordinator._write_world_state()
    with pytest.raises(OSError, match="full disk"):
        coordinator._write_paths()
    assert not (tmp_path / "world_state.json").exists()
    assert not (tmp_path / "world_paths.json").exists()
    fail = False
    coordinator._write_arbiter_records(2, None, record, [record])
    rows = [json.loads(line) for line in (tmp_path / "arbiter_raw.jsonl").read_text().splitlines()]
    assert {(r["round"], r["path"]) for r in rows} == {(r, p) for r in (1, 2) for p in (0, 1)}
    assert not coordinator._arbiter_records_dirty


@pytest.mark.parametrize("status,accounted", [("failed", "failed"), ("invalid", "infeasible"), ("skipped", "missing")])
def test_runner_share_policy_preserves_failed_adjudication_status(status, accounted):
    from tests.test_world_model_loop import rps
    from app.services.worldstate import WorldState
    coordinator = object.__new__(rps._ReflexiveWorldCoordinator)
    world = _world()
    world.start_round(1, None)
    world.actors[0].outcome_power = 2
    state = WorldState(["A", "B"], share_prior="uniform", share_source="power_votes")
    rows = [{"agent_id": 0, "scenario": "A", "magnitude": 1, "confidence": 1}]
    coordinator._step_policy_shares(state, world, rows, 1, {"arbiter_status": status}, 0, None, "committed")
    assert state.round_statuses == [accounted]
    assert state.shares == {"A": 0.5, "B": 0.5}
    assert not state.converged()


def test_runner_trusts_declared_world_power_not_actor_vote_fields():
    from tests.test_world_model_loop import rps
    from app.services.worldstate import WorldState
    coordinator = object.__new__(rps._ReflexiveWorldCoordinator)
    world = _world()
    world.start_round(1, None)
    world.actors[0].last_action = {"round": 1, "option_id": "public_statement", "resolution": "success", "status": "ok"}
    rows = [{"agent_id": 0, "scenario": "A", "magnitude": 1, "confidence": 1, "outcome_power": 999999}]
    state = WorldState(["A", "B"], share_prior="uniform", share_source="power_votes")
    coordinator._step_policy_shares(state, world, rows, 1, {"arbiter_status": "applied"}, 0, None, "committed")
    assert state.shares == {"A": 0.5, "B": 0.5}
    assert state.outcome()["share_update_reason"] == "unknown_power"
    world.actors[0].outcome_power = 2
    coordinator._step_policy_shares(state, world, rows, 1, {"arbiter_status": "applied"}, 0, None, "committed")
    assert state.shares["A"] > state.shares["B"]
