"""Default-world producer contracts exercised through real parsing and round updates.

The saved war run reports numeric rejection in round 3 and unbound delivery
resolutions in rounds 3/4/6. Raw arbiter replies were not retained. These are
saved-shaped contract regressions, not a replay of those unavailable replies.
Run with scripts/main_offline_pytest.py; the provider is scripted, all world
validation, application, ledgers and next-actor prompt builders remain real.
"""

import copy
import json
import math
import random
import re

import pytest

from app.services.agent_decision import build_decision_prompt, build_option_menu, parse_decision
from app.services.world_model import WorldModel
from app.services.world_update import run_world_round, validate_arbiter_update
from tests.conftest import FakeLLMClient


def _world(*, duplicate_names=False):
    return WorldModel.from_seed({
        "question": "Will the parties deliver the agreed technical package?",
        "state_variables": [
            {"name": "Recent momentum", "value": 3.0, "kind": "numeric",
             "unit": "square miles in 4 weeks", "provenance": "research"},
            {"name": "Talks status", "value": "pending", "kind": "categorical"},
        ],
        "actors": [
            {"agent_id": i, "name": name, "agency_class": "firm", "capacity_per_round": 3}
            for i, name in enumerate(["Delegation", "Mediator", "Mediator" if duplicate_names else "Observer"])
        ],
    })


def _prompt(world, aid, round_num, digest=""):
    actor = world.actors[aid]
    return build_decision_prompt(
        actor, world_clock=f"Period {round_num}",
        public_brief=world.render_public_brief(),
        private_brief=world.render_private_brief(aid),
        options=build_option_menu(actor, world, round_num), scenarios=(),
        cast_names=[a.name for a in world.actors.values()], recent_discourse=digest,
    )


def _parse(world, aid, round_num, option_id, **fields):
    return parse_decision(
        {"option_id": option_id, "scenario_commitment": "abstain", **fields},
        actor=world.actors[aid], world=world,
        options=build_option_menu(world.actors[aid], world, round_num),
        scenarios=(), round_num=round_num,
    )


def _advance(world, round_num, decisions=(), payload=None):
    llm = FakeLLMClient(json_responses=[copy.deepcopy(payload or {})])
    record = run_world_round(
        world, round_num, {"label": f"period-{round_num}"}, decisions, (),
        llm=llm, rng=random.Random(29),
    )
    return record, llm.calls[0]["messages"][-1]["content"]


def _bindings(prompt):
    assert "## Action resolution bindings" in prompt
    section = prompt.split("## Action resolution bindings", 1)[1].split("\n## ", 1)[0]
    return [json.loads(line[2:]) for line in section.splitlines() if line.startswith('- {')]


def test_numeric_guidance_and_real_apply_reach_next_actor():
    world = _world()
    world.start_round(3, {"label": "period-3"})
    move = _parse(world, 0, 3, "public_statement", public_statement="We publish our technical assessment.")
    assert move.ok
    record, prompt = _advance(world, 3, [move], {
        "variable_changes": [{"variable_id": "recent_momentum", "new_value": 3.2,
                              "rationale": "Small observed territorial gains."}],
        "action_resolutions": [{"actor": "Delegation", "outcome": "success",
                                "commitment_id": None, "action_round": None}],
    })
    assert "Recent momentum = 3 square miles in 4 weeks [numeric]" in prompt
    assert "finite JSON number" in prompt
    assert "omit" in prompt and "prose" in prompt
    assert record["arbiter_status"] == "applied" and record["arbiter_problems"] == []
    # Real kernel reversion towards the research anchor remains in force.
    assert world.variables["recent_momentum"].value == pytest.approx(3.17)
    assert math.isfinite(world.variables["recent_momentum"].value)
    assert world.variables["recent_momentum"].kind == "numeric"
    assert record["diff"]["variables_changed"][0]["to"] == pytest.approx(3.17)
    world.start_round(4, {"label": "period-4"})
    next_prompt = _prompt(world, 2, 4, record["digest"])
    assert "Recent momentum" in next_prompt and "3.17" in next_prompt
    assert "3 square miles in 4 weeks → 3.17 square miles in 4 weeks" in next_prompt


@pytest.mark.parametrize("field", ["new_value", "delta"])
@pytest.mark.parametrize("value", ["slowing", "4 square miles", True, float("nan"),
                                   float("inf"), "-Infinity", {"value": 4}, [4]])
def test_invalid_numeric_values_keep_diagnostic_and_never_change_fact(field, value):
    world = _world()
    record, _ = _advance(world, 3, payload={
        "variable_changes": [{"variable_id": "recent_momentum", field: value}],
    })
    assert record["arbiter_problems"] == ["non-numeric change for numeric variable 'recent_momentum'"]
    assert world.variables["recent_momentum"].value == 3.0
    assert world.variables["recent_momentum"].kind == "numeric"
    assert record["diff"]["variables_changed"] == []


def _promise(world, agreement):
    if not agreement:
        return world.actors[0].add_commitment(
            "Deliver a working agenda text before the technical talks.", made_round=1, due_round=3)
    world.start_round(1, {"label": "period-1"})
    offer = _parse(world, 0, 1, "open_talks", targets=[1],
                   terms="Exchange the audited technical schedules in the next period.")
    assert offer.ok
    _advance(world, 1, [offer])
    interaction = next(iter(world.interactions.values()))
    world.start_round(2, {"label": "period-2"})
    accept = _parse(world, 1, 2, f"accept:{interaction.id}")
    assert accept.ok
    _advance(world, 2, [accept])
    return next(c for c in world.actors[0].commitments if c["source"] == f"agreement:{interaction.id}")


@pytest.mark.parametrize("agreement,duplicate_names", [(False, False), (True, False), (True, True)],
                         ids=["self-promise", "agreement", "agreement-duplicate-counterparty-name"])
def test_actor_prompt_to_delivery_binding_to_next_actor_feedback(agreement, duplicate_names):
    world = _world(duplicate_names=duplicate_names)
    promise = _promise(world, agreement)
    other = world.actors[0].add_commitment("Publish an unrelated report.", made_round=2, due_round=4)
    world.start_round(3, {"label": "period-3"})
    option_id = f"fulfill:{promise['id']}"
    actor_prompt = _prompt(world, 0, 3)
    line = next(line for line in actor_prompt.splitlines() if f"[{option_id}]" in line)
    # Follow the target binding actually exposed to the actor, including [] for
    # a unilateral promise. Do not infer a recipient from its prose description.
    match = re.search(r"targets=(\[[^\n]*?\])", line)
    assert match, "Delivery option must expose its exact stored targets as JSON."
    targets = json.loads(match.group(1))
    assert targets == ([1] if agreement else [])
    decision = _parse(world, 0, 3, option_id, targets=targets,
                      public_statement="The audited technical package has been delivered.")
    assert decision.ok, decision.to_dict()
    record, arbiter_prompt = _advance(world, 3, [decision], {
        "action_resolutions": [{"agent_id": 0, "outcome": "success",
                                "commitment_id": promise["id"], "action_round": 3,
                                "rationale": "The complete package was delivered as promised."}],
    })
    bindings = _bindings(arbiter_prompt)
    assert bindings == [{"actor": "Delegation", "agent_id": 0, "option_id": option_id,
                         "commitment_id": promise["id"], "action_round": 3}]
    assert "The audited technical package has been delivered." in arbiter_prompt
    assert promise["description"] in arbiter_prompt
    assert record["arbiter_problems"] == []
    assert record["arbiter"]["commitments_fulfilled"] == 1
    assert promise["status"] == "fulfilled" and other["status"] == "pending"
    assert promise["fulfillment_evidence"]["option_id"] == option_id
    assert world.track_record(0)["kept"] == 1
    assert world.actors[0].last_action["resolution"] == "success"
    world.start_round(4, {"label": "period-4"})
    next_prompt = _prompt(world, 0, 4, record["digest"])
    assert f"fulfilled commitment [{promise['id']}]" in next_prompt
    assert "outcome so far: success" in next_prompt
    assert f"[fulfill:{other['id']}]" in next_prompt
    assert f"[fulfill:{promise['id']}]" not in next_prompt
    if agreement:
        counterpart = _prompt(world, 1, 4, record["digest"])
        assert f"fulfilled commitment [{promise['id']}]" in counterpart
        assert any(c["status"] == "due" for c in world.actors[1].commitments)


def test_rejected_delivery_and_hold_are_excluded_from_resolution_bindings():
    world = _world()
    promise = _promise(world, False)
    world.start_round(3, {"label": "period-3"})
    invalid = _parse(world, 0, 3, f"fulfill:{promise['id']}", targets=["Mediator"])
    hold = _parse(world, 1, 3, "hold_position")
    mover = _parse(world, 2, 3, "public_statement", public_statement="Our office published a notice.")
    assert invalid.status == "invalid" and invalid.problems == ["invalid commitment delivery binding"]
    record, prompt = _advance(world, 3, [invalid, hold, mover])
    assert _bindings(prompt) == [{"actor": "Observer", "agent_id": 2, "option_id": "public_statement",
                                  "commitment_id": None, "action_round": None}]
    assert "Do not resolve held, invalid or rejected moves" in prompt
    assert promise["status"] == "due" and record["arbiter"]["commitments_fulfilled"] == 0


@pytest.mark.parametrize("claim", [None, "", "owned"])
def test_unrelated_action_never_satisfies_promise_even_with_success(claim):
    world = _world()
    promise = _promise(world, False)
    world.start_round(3, {"label": "period-3"})
    unrelated = _parse(world, 0, 3, "public_statement", public_statement="Our office is closed for the holiday.")
    row = {"actor": "Delegation", "outcome": "success", "commitment_id": promise["id"] if claim == "owned" else claim,
           "action_round": 3, "rationale": "The holiday notice was published."}
    record, prompt = _advance(world, 3, [unrelated], {"action_resolutions": [row]})
    assert _bindings(prompt)[0]["commitment_id"] is None
    assert promise["status"] == "due" and "fulfillment_evidence" not in promise
    assert record["arbiter"]["commitments_fulfilled"] == 0
    assert world.track_record(0)["kept"] == 0
    if claim is not None:
        assert record["arbiter_problems"] == ["unbound commitment delivery resolution"]
        assert record["arbiter"]["resolutions"] == 0
    else:
        assert record["arbiter_problems"] == [] and record["arbiter"]["resolutions"] == 1


@pytest.mark.parametrize("mutation", ["missing_id", "wrong_id", "wrong_round", "string_round",
                                      "no_rationale", "duplicate", "malformed_id"])
def test_delivery_guidance_does_not_relax_attestation_validation(mutation):
    world = _world()
    promise = _promise(world, False)
    world.start_round(3, {"label": "period-3"})
    delivery = _parse(world, 0, 3, f"fulfill:{promise['id']}", targets=[])
    assert delivery.ok
    world.register_decisions(3, [delivery.to_dict()])
    row = {"actor": "Delegation", "commitment_id": promise["id"], "action_round": 3,
           "outcome": "success", "rationale": "The entire promised package was delivered."}
    rows = [row]
    if mutation == "missing_id":
        row.pop("commitment_id")
    elif mutation == "wrong_id":
        row["commitment_id"] = "other-promise"
    elif mutation == "wrong_round":
        row["action_round"] = 2
    elif mutation == "string_round":
        row["action_round"] = "3"
    elif mutation == "no_rationale":
        row["rationale"] = ""
    elif mutation == "duplicate":
        rows.append(dict(row))
    elif mutation == "malformed_id":
        row["commitment_id"] = [promise["id"]]
    validated, problems = validate_arbiter_update({"action_resolutions": rows}, world)
    assert validated["action_resolutions"] == [] and problems
    summary = world.apply_arbiter_update(3, validated)
    assert summary["commitments_fulfilled"] == 0
    assert promise["status"] == "due" and "fulfillment_evidence" not in promise
