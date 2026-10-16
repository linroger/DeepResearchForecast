"""Structured actor decisions (design §2.4): agency classes, option menus, parsing.

Offline: the only LLM touch is the conftest FakeLLMClient.  Pins the typed
degradation (``invalid`` / ``failed`` → hold_position), target/scenario
validation, menu priorities and the roster rule (principals first, audience out).
"""

import pytest

from app.services import agent_decision as ad
from app.services.world_model import WorldModel
from tests.conftest import FakeLLMClient


def _world():
    seed = {
        "question": "Will the permit unlock deployment?",
        "scenarios": ["Permit granted", "Permit delayed"],
        "state_variables": [{"name": "Regional capacity", "value": 120, "unit": "MW"}],
        "actors": [
            {"agent_id": 0, "name": "Alpha Systems", "agency_class": "firm", "aliases": ["Alpha"],
             "documented_plans": ["Invest $2 billion in the Aurora line", "File a permit response"],
             "goals": ["Shape the permit timetable"], "incentives": {"gains_if": "timetable holds"}},
            {"agent_id": 1, "name": "Beta Union", "agency_class": "labor_union"},
            {"agent_id": 2, "name": "Grid Regulator", "agency_class": "regulator_agency"},
        ],
    }
    cfgs = [{"agent_id": i, "entity_name": n} for i, n in enumerate(["Alpha Systems", "Beta Union", "Grid Regulator"])]
    world = WorldModel.from_seed(seed, cfgs)
    world.start_round(1, {"label": "2026-Q3", "period_start": "2026-07-02", "period_end": "2026-09-30"})
    return world


# ----------------------------------------------------------------------------- agency classes
@pytest.mark.parametrize("type_name, role, expected", [
    ("Government", "Ministry of Commerce", "sovereign_government"),
    ("Organization", "Tesla Inc, EV maker", "firm"),
    ("Person", "Senator for Ohio", "legislature"),
    ("Person", "Fed Chair Jerome Powell", "central_bank"),
    ("MediaOutlet", "Reuters", "media_outlet"),
    ("Organization", "United Auto Workers union", "labor_union"),
    ("Organization", "European Commission", "regulator_agency"),
    ("Organization", "NATO", "international_org"),
    ("Organization", "Greenpeace", "ngo_advocacy"),
    ("Organization", "SEMI industry association", "industry_coalition"),
    ("Person", "Elon Musk, CEO", "individual_leader"),
    ("Collective", "EV buyers", "public_collective"),
    ("Organization", "", "firm"),
    ("Thing", "", "other_actor"),
    ("firm", "", "firm"),
])
def test_infer_agency_class(type_name, role, expected):
    assert ad.infer_agency_class(type_name, role) == expected


def test_infer_agency_class_word_boundaries_and_archetype():
    # "senator" must not be classified via the "nato" substring
    assert ad.infer_agency_class("Person", "Senator") != "international_org"
    assert ad.infer_agency_class("", "", archetype="collective") == "public_collective"
    assert ad.infer_agency_class(None, None) == "other_actor"
    assert ad.default_capacity("sovereign_government") == 3
    assert ad.default_capacity("unknown") == ad.DEFAULT_CAPACITY_BY_CLASS["other_actor"]


def test_catalog_covers_every_class_with_hold_available():
    for klass in ad.AGENCY_CLASSES:
        templates = ad.catalog_for(klass)
        assert templates, klass
        assert all(t.kind in ad.ACTION_KINDS for t in templates)
        ids = [t.id for t in templates]
        assert len(ids) == len(set(ids)), klass


# ----------------------------------------------------------------------------- option menu
def test_option_menu_priorities_and_capacity_filter():
    world = _world()
    alpha = world.actors[0]
    menu = ad.build_option_menu(alpha, world, 1)
    ids = [o["id"] for o in menu]
    assert ids[-1] == ad.HOLD_OPTION_ID
    assert ids[0] == "plan_1" and ids[1] == "plan_2"              # documented plans come first (no responses yet)
    assert menu[0]["kind"] == "economic" and menu[0]["lag"] == 2  # "invest" classified as economic
    assert menu[1]["kind"] == "legal"
    assert len(menu) <= ad.MAX_OPTIONS
    # capacity exhausted → only zero-cost moves (hold) remain affordable
    alpha.capacity_used = alpha.capacity_per_round
    menu2 = ad.build_option_menu(alpha, world, 1)
    assert all(o["cost"] <= 0 or o["id"].startswith("plan_") for o in menu2)
    assert menu2[-1]["id"] == ad.HOLD_OPTION_ID


def test_option_menu_adds_response_options_to_moves_aimed_at_actor():
    world = _world()
    world.register_decisions(1, [{
        "agent_id": 1, "actor_name": "Beta Union",
        "option": {"id": "strike_action", "label": "Call a strike", "kind": "coercive", "cost": 3},
        "targets": ["Alpha Systems"], "magnitude": 0.9, "status": "ok",
    }])
    world.commit_round(1)
    world.start_round(2, {"label": "2026-Q4"})
    menu = ad.build_option_menu(world.actors[0], world, 2)
    assert menu[0]["id"] == "respond_1_counter" and "Beta Union" in menu[0]["label"]
    assert menu[0]["suggested_targets"] == ["Beta Union"]
    assert menu[1]["id"] == "respond_1_negotiate"


def test_deciding_roster_principals_first_audience_excluded_capped():
    cfgs = [
        {"agent_id": 0, "entity_name": "A", "cadence": "sampled", "influence_weight": 0.9},
        {"agent_id": 1, "entity_name": "B", "cadence": "principal", "influence_weight": 0.5},
        {"agent_id": 2, "entity_name": "C", "cadence": "principal", "influence_weight": 0.8},
        {"agent_id": 3, "entity_name": "Aud", "entity_type": "Audience", "influence_weight": 1.0},
        {"agent_id": 4, "entity_name": "D", "influence_weight": 0.2},
    ]
    assert ad.deciding_roster(cfgs, active_ids=[0, 3, 4]) == [2, 1, 0, 4]
    assert ad.deciding_roster(cfgs, active_ids=[0, 4], max_actors=3) == [2, 1, 0]
    assert ad.deciding_roster(cfgs, active_ids=[]) == [2, 1]        # principals decide even when not sampled


# ----------------------------------------------------------------------------- prompt
def test_decision_prompt_carries_briefs_options_scenarios_and_contract():
    world = _world()
    alpha = world.actors[0]
    menu = ad.build_option_menu(alpha, world, 1)
    prompt = ad.build_decision_prompt(alpha, world_clock="# WORLD CLOCK — 2026-Q3", public_brief="# WORLD STATE\n- x",
                                      private_brief="# YOUR SITUATION — Alpha Systems", options=menu,
                                      scenarios=world.scenarios, cast_names=["Alpha Systems", "Beta Union"],
                                      language="English")
    assert prompt.startswith("# WORLD CLOCK — 2026-Q3")
    assert "# WORLD STATE" in prompt and "# YOUR SITUATION" in prompt
    assert "[plan_1]" in prompt and f"[{ad.HOLD_OPTION_ID}]" in prompt
    assert "Candidate scenarios: Permit granted; Permit delayed" in prompt
    assert "Your documented goals: Shape the permit timetable" in prompt
    assert "you gain if: timetable holds" in prompt
    assert "Write public_statement in English." in prompt
    assert '"scenario_commitment"' in prompt and "Return ONLY JSON" in prompt


# ----------------------------------------------------------------------------- parsing
def _menu(world):
    return ad.build_option_menu(world.actors[0], world, 1)


def test_parse_valid_decision_resolves_targets_and_scenario():
    world = _world()
    menu = _menu(world)
    raw = {
        "option_id": "plan_1", "targets": ["beta union", "Nobody Known", "Alpha Systems"], "magnitude": 1.7,
        "public_statement": "We commit $2bn to Aurora now.", "private_rationale": "lock the timetable",
        "commitment": {"description": "Break ground on Aurora", "due_periods": 2},
        "alliance_moves": [{"target": "Grid Regulator", "move": "propose"}, {"target": "Alpha Systems", "move": "break"}],
        "expected_reactions": [{"actor": "Beta Union", "reaction": "strike threat"}],
        "scenario_commitment": {"scenario": "permit granted", "confidence": 0.8},
    }
    d = ad.parse_decision(raw, actor=world.actors[0], world=world, options=menu, scenarios=world.scenarios,
                          round_num=1, period_end="2026-09-30")
    assert d.ok and d.option["id"] == "plan_1"
    assert d.targets == ["Beta Union"]                                # unknown and self dropped
    assert d.magnitude == 1.0
    assert d.commitment == {"description": "Break ground on Aurora", "due_periods": 2}
    assert d.alliance_moves == [{"target": "Grid Regulator", "move": "propose"}]
    assert d.scenario == "Permit granted" and d.scenario_confidence == 0.8
    row = d.scenario_commitment(outcome_power=1.5)
    assert row["scenario"] == "Permit granted" and row["outcome_power"] == 1.5 and row["period_end"] == "2026-09-30"
    assert d.to_dict()["schema_version"] == ad.DECISION_CONTRACT_VERSION


def test_parse_unknown_option_and_bad_payload_degrade_to_typed_hold():
    world = _world()
    menu = _menu(world)
    bad = ad.parse_decision({"option_id": "nuke_everything", "public_statement": "x"}, actor=world.actors[0],
                            world=world, options=menu, scenarios=world.scenarios, round_num=1)
    assert bad.status == "invalid" and bad.option["id"] == ad.HOLD_OPTION_ID and bad.raw_option_id == "nuke_everything"
    assert bad.scenario_commitment() is None
    assert ad.parse_decision("not json", actor=world.actors[0], world=world, options=menu,
                             scenarios=world.scenarios, round_num=1).status == "invalid"
    assert ad.parse_decision(None, actor=world.actors[0], world=world, options=menu,
                             scenarios=world.scenarios, round_num=1).status == "invalid"


def test_parse_custom_option_requires_catalogued_kind():
    world = _world()
    menu = _menu(world)
    ok = ad.parse_decision({"option_id": "custom", "custom_action": {"kind": "legal", "label": "File an injunction"},
                            "targets": ["Grid Regulator"], "public_statement": "We are filing."},
                           actor=world.actors[0], world=world, options=menu, scenarios=world.scenarios, round_num=1)
    assert ok.ok and ok.option["id"] == "custom" and ok.option["kind"] == "legal" and ok.option["lag"] == 1
    bad = ad.parse_decision({"option_id": "custom", "custom_action": {"kind": "magic", "label": "x"}},
                            actor=world.actors[0], world=world, options=menu, scenarios=world.scenarios, round_num=1)
    assert bad.status == "invalid"


def test_parse_tolerates_label_echo_and_fills_statement():
    world = _world()
    menu = _menu(world)
    d = ad.parse_decision({"option_id": "Hold position: wait", "scenario_commitment": "abstain"},
                          actor=world.actors[0], world=world, options=menu, scenarios=world.scenarios, round_num=1)
    assert d.ok and d.option["id"] == ad.HOLD_OPTION_ID and d.scenario == ad.ABSTAIN
    assert d.public_statement == ""                                    # holding needs no statement
    d2 = ad.parse_decision({"option_id": "public_statement"}, actor=world.actors[0], world=world, options=menu,
                           scenarios=world.scenarios, round_num=1)
    assert d2.ok and d2.public_statement.startswith("Alpha Systems: ")  # a move always has something to publish


def test_elicit_decision_with_fake_llm_and_failure():
    world = _world()
    menu = _menu(world)
    llm = FakeLLMClient(json_responses=[{"option_id": "plan_1", "public_statement": "Go.",
                                         "scenario_commitment": {"scenario": "Permit delayed", "confidence": 0.5}}])
    d = ad.elicit_decision(llm, system_message="ROLE BRIEF", user_prompt="decide", actor=world.actors[0], world=world,
                           options=menu, scenarios=world.scenarios, round_num=1)
    assert d.ok and d.scenario == "Permit delayed"
    assert llm.calls[0]["messages"][0] == {"role": "system", "content": "ROLE BRIEF"}

    class Boom:
        def chat_json(self, **kwargs):
            raise RuntimeError("provider down")

    failed = ad.elicit_decision(Boom(), system_message="", user_prompt="decide", actor=world.actors[0], world=world,
                                options=menu, scenarios=world.scenarios, round_num=1)
    assert failed.status == "failed" and failed.option["id"] == ad.HOLD_OPTION_ID
    assert ad.elicit_decision(None, system_message="", user_prompt="x", actor=world.actors[0], world=world,
                              options=menu, scenarios=world.scenarios, round_num=1).status == "failed"
    counts = ad.summarize_decisions([d, failed])
    assert counts == {"ok": 1, "invalid": 0, "failed": 1, "hold": 1}


def test_memory_note_and_hold_note():
    world = _world()
    menu = _menu(world)
    d = ad.parse_decision({"option_id": "plan_1", "targets": ["Beta Union"], "public_statement": "Go.",
                           "private_rationale": "secret", "commitment": {"description": "Break ground", "due_periods": 1}},
                          actor=world.actors[0], world=world, options=menu, scenarios=world.scenarios, round_num=1)
    note = ad.decision_memory_note(d, "2026-Q3")
    assert note.startswith("# YOUR MOVE THIS PERIOD — 2026-Q3")
    assert "Directed at: Beta Union" in note and 'You announced: "Go."' in note
    assert "You committed to: Break ground" in note and "secret" in note
    hold = ad.hold_decision(world.actors[0], status="failed", round_num=1, period_end=None)
    assert ad.decision_memory_note(hold) == ""
