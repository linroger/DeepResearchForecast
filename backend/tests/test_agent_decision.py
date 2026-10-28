"""Structured actor decisions (design §2.4): agency classes, option menus, parsing.

Offline: the only LLM touch is the conftest FakeLLMClient (and a scripted, offline
LLMClient for the fallback-provider retry).  Pins the typed degradation
(``invalid`` / ``failed`` / ``language_mismatch`` → hold_position), target/scenario
validation, the run-language script check on public statements, precise provider
failure records, menu priorities and the roster rule (principals first, audience out).
"""

import pytest

from app.services import agent_decision as ad
from app.services.world_model import WorldModel
from tests.conftest import FakeLLMClient, content_filter_error


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
    """Old plans bypassed exhausted budgets; C11 filters plans like every paid move."""
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
    assert all(o["cost"] == 0 for o in menu2)
    assert menu2[-1]["id"] == ad.HOLD_OPTION_ID


def test_option_menu_adds_response_options_to_moves_aimed_at_actor():
    """Old raw strike cost 3 was trusted; C11 requires the union's canonical cost-2 move."""
    world = _world()
    world.register_decisions(1, [{
        "agent_id": 1, "actor_name": "Beta Union",
        "option": next(t.to_option(label="Call a strike")
                       for t in ad.catalog_for("labor_union") if t.id == "strike_action"),
        "targets": ["Alpha Systems"], "magnitude": 0.9, "status": "ok",
    }])
    world.commit_round(1)
    world.start_round(2, {"label": "2026-Q4"})
    menu = ad.build_option_menu(world.actors[0], world, 2)
    assert menu[0]["id"] == "respond_1_counter" and "Beta Union" in menu[0]["label"]
    assert menu[0]["suggested_targets"] == ["Beta Union"]
    assert menu[1]["id"] == "respond_1_negotiate"


def test_primary_catalog_actions_are_affordable_by_default_capacity():
    checks = [
        ("firm", "invest_capex"),
        ("central_bank", "rate_move"),
        ("labor_union", "strike_action"),
        ("regulator_agency", "issue_ruling"),
    ]
    for klass, option_id in checks:
        tmpl = next(t for t in ad.catalog_for(klass) if t.id == option_id)
        assert tmpl.cost <= ad.default_capacity(klass)


def test_irreversible_actions_are_not_offered_again_after_intervening_hold():
    world = _world()
    alpha = world.actors[0]
    world.register_decisions(1, [{
        "agent_id": 0, "actor_name": "Alpha Systems",
        "option": {"id": "product_launch", "label": "Launch", "kind": "operational", "cost": 2, "reversibility": "irreversible"},
        "targets": [], "magnitude": 0.9, "status": "ok",
    }])
    world.commit_round(1)
    world.start_round(2, {"label": "2026-Q4"})
    world.register_decisions(2, [{
        "agent_id": 0, "actor_name": "Alpha Systems",
        "option": {"id": ad.HOLD_OPTION_ID, "label": "Hold", "kind": "wait", "cost": 0},
        "targets": [], "magnitude": 0.0, "status": "ok",
    }])
    world.commit_round(2)
    world.start_round(3, {"label": "2027-Q1"})
    ids = [o["id"] for o in ad.build_option_menu(alpha, world, 3)]
    assert "product_launch" not in ids


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
    # the terms contract: an offer binds nobody until accepted; accept adopts the offer's terms verbatim
    assert "offer binds nobody until the other side accepts it" in prompt
    assert "an accept answer adopts the offer's terms verbatim" in prompt
    assert "an accept whose terms differ materially is recorded as a counter-offer, not an agreement" in prompt


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


def test_parse_preserves_explicit_zero_scenario_confidence():
    world = _world()
    menu = _menu(world)
    d = ad.parse_decision({
        "option_id": "plan_1",
        "public_statement": "Proceed.",
        "scenario_commitment": {"scenario": "Permit delayed", "confidence": 0},
    }, actor=world.actors[0], world=world, options=menu, scenarios=world.scenarios, round_num=1)
    row = d.scenario_commitment(outcome_power=1.0)
    assert row is not None and row["confidence"] == 0.0


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
    """Old caller system text passed through; C11 builds the actor's JSON-only brief."""
    world = _world()
    menu = _menu(world)
    llm = FakeLLMClient(json_responses=[{"option_id": "plan_1", "public_statement": "Go.",
                                         "scenario_commitment": {"scenario": "Permit delayed", "confidence": 0.5}}])
    d = ad.elicit_decision(llm, system_message="ROLE BRIEF", user_prompt="decide", actor=world.actors[0], world=world,
                           options=menu, scenarios=world.scenarios, round_num=1)
    assert d.ok and d.scenario == "Permit delayed"
    system = llm.calls[0]["messages"][0]
    assert system["role"] == "system"
    assert system["content"].startswith(ad.DECISION_SYSTEM_PROMPT)
    assert "Alpha Systems" in system["content"] and "Shape the permit timetable" in system["content"]
    assert "ROLE BRIEF" not in system["content"] and "tool calling" not in system["content"].lower()

    class Boom:
        def chat_json(self, **kwargs):
            raise RuntimeError("provider down")

    failed = ad.elicit_decision(Boom(), system_message="", user_prompt="decide", actor=world.actors[0], world=world,
                                options=menu, scenarios=world.scenarios, round_num=1)
    assert failed.status == "failed" and failed.option["id"] == ad.HOLD_OPTION_ID
    assert ad.elicit_decision(None, system_message="", user_prompt="x", actor=world.actors[0], world=world,
                              options=menu, scenarios=world.scenarios, round_num=1).status == "failed"
    counts = ad.summarize_decisions([d, failed])
    assert counts == {"ok": 1, "invalid": 0, "failed": 1, "language_mismatch": 0, "hold": 1}
    assert failed.problems == ["llm error: RuntimeError: provider down"]


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


# ----------------------------------------------------------------------------- run language
@pytest.mark.parametrize("text, script", [
    ("We commit $2bn to Aurora now.", "latin"),
    ("商务部将对石墨出口许可进行审查。", "cjk"),
    ("MOFCOM (商务部) will review graphite export licences next month.", "latin"),   # a quoted name stays Latin
    ("商务部将审查石墨出口许可（USTR 第 301 条）", "cjk"),                              # acronyms stay CJK
    ("東京は関税を25%に引き上げた。", "cjk"),
    ("25% — 2027-03-10", ""),                                                         # no letters: unknown
    ("", ""),
])
def test_text_script_heuristic(text, script):
    assert ad.text_script(text) == script


@pytest.mark.parametrize("language, script", [
    ("English", "latin"), ("en", "latin"), ("English (US)", "latin"), ("Deutsch", "latin"), ("Chinese", "cjk"),
    ("zh-CN", "cjk"), ("中文", "cjk"), ("Japanese", "cjk"), ("", ""), ("auto", ""), ("Russian", ""),
    ("Javanese", ""), ("Estonian", ""),
])
def test_expected_script(language, script):
    assert ad.expected_script(language) == script
    assert ad.statement_matches_language("anything", "") and ad.statement_matches_language("", language)


def test_parse_rejects_wrong_script_statement_with_typed_status():
    """sim_d6ebcc77e22d: one of fifty statements came out in Chinese in an English run although the
    prompt said "Write public_statement in English." — structure-only validation let it through."""
    world = _world()
    menu = _menu(world)
    raw = {"option_id": "plan_1", "targets": ["Beta Union"], "magnitude": 0.8,
           "public_statement": "我们将于本季度向极光项目投入20亿美元。",
           "scenario_commitment": {"scenario": "Permit granted", "confidence": 0.8}}
    d = ad.parse_decision(raw, actor=world.actors[0], world=world, options=menu, scenarios=world.scenarios,
                          round_num=1, period_end="2026-09-30", language="English")
    assert d.status == ad.LANGUAGE_MISMATCH and not d.ok
    assert d.option["id"] == ad.HOLD_OPTION_ID and d.raw_option_id == "plan_1"
    assert d.public_statement == "" and d.scenario_commitment() is None           # nothing to publish or commit
    assert d.problems == ['public_statement is cjk-script but the run language is English: '
                          '"我们将于本季度向极光项目投入20亿美元。"']
    row = d.to_dict()
    assert row["status"] == "language_mismatch" and row["problems"] == d.problems
    # the same payload is a valid move when the run language matches, or when none is set
    assert ad.parse_decision(raw, actor=world.actors[0], world=world, options=menu, scenarios=world.scenarios,
                             round_num=1, language="Chinese").ok
    assert ad.parse_decision(raw, actor=world.actors[0], world=world, options=menu, scenarios=world.scenarios,
                             round_num=1).ok
    # an English run keeps a Latin statement that quotes a Chinese name; a Chinese run rejects English
    en = dict(raw, public_statement="MOFCOM (商务部) will review the Aurora filing in Q3.")
    assert ad.parse_decision(en, actor=world.actors[0], world=world, options=menu, scenarios=world.scenarios,
                             round_num=1, language="English").ok
    zh = ad.parse_decision(en, actor=world.actors[0], world=world, options=menu, scenarios=world.scenarios,
                           round_num=1, language="Chinese")
    assert zh.status == ad.LANGUAGE_MISMATCH and zh.problems[0].startswith("public_statement is latin-script")
    # holding publishes nothing, and a synthesised statement is never checked
    hold = ad.parse_decision({"option_id": ad.HOLD_OPTION_ID, "public_statement": "保持观望。"}, actor=world.actors[0],
                             world=world, options=menu, scenarios=world.scenarios, round_num=1, language="English")
    assert hold.ok
    synth = ad.parse_decision({"option_id": "plan_1"}, actor=world.actors[0], world=world, options=menu,
                              scenarios=world.scenarios, round_num=1, language="Chinese")
    assert synth.ok and synth.public_statement.startswith("Alpha Systems: ")
    assert ad.summarize_decisions([d, zh, hold, synth]) == {"ok": 2, "invalid": 0, "failed": 0,
                                                            "language_mismatch": 2, "hold": 3}


class _Filtered:
    """Stand-in whose only answer is the live Zhipu content-filter rejection."""

    def chat_json(self, **kwargs):
        raise content_filter_error()


def test_elicit_decision_applies_language_check_and_records_provider_errors():
    world = _world()
    menu = _menu(world)
    llm = FakeLLMClient(json_responses=[{"option_id": "plan_1", "public_statement": "我们现在就投资极光项目。"}])
    d = ad.elicit_decision(llm, system_message="ROLE", user_prompt="decide", actor=world.actors[0], world=world,
                           options=menu, scenarios=world.scenarios, round_num=1, language="English")
    assert d.status == ad.LANGUAGE_MISMATCH and d.raw_option_id == "plan_1"

    failed = ad.elicit_decision(_Filtered(), system_message="", user_prompt="decide", actor=world.actors[0],
                                world=world, options=menu, scenarios=world.scenarios, round_num=1)
    assert failed.status == "failed" and failed.option["id"] == ad.HOLD_OPTION_ID
    [problem] = failed.problems
    assert problem.startswith("llm error: BadRequestError (HTTP 400, provider code 1301, content filter): "
                              "Error code: 400 - {'contentFilter'")
    assert len(problem) <= 300
    assert ad.elicit_decision(None, system_message="", user_prompt="x", actor=world.actors[0], world=world,
                              options=menu, scenarios=world.scenarios, round_num=1).problems == ["no llm client"]


def test_elicit_decision_recovers_through_fallback_provider(scripted_failover):
    """The decision step goes through the backend LLMClient: a content-filter rejection is retried
    ONCE on the configured fallback provider and the fallback's answer is the decision."""
    world = _world()
    menu = _menu(world)
    llm, transports = scripted_failover(content_filter_error(), {
        "option_id": "plan_1", "public_statement": "We commit $2bn to Aurora now.",
        "scenario_commitment": {"scenario": "Permit granted", "confidence": 0.7}})
    d = ad.elicit_decision(llm, system_message="ROLE", user_prompt="decide", actor=world.actors[0], world=world,
                           options=menu, scenarios=world.scenarios, round_num=1, language="English")
    assert d.ok and d.option["id"] == "plan_1" and d.scenario == "Permit granted" and d.problems == []
    assert transports == [("glm", False), ("kimi", True)]                      # one primary attempt, one fallback retry


def test_elicit_decision_records_fallback_failure(scripted_failover):
    world = _world()
    menu = _menu(world)
    llm, transports = scripted_failover(content_filter_error(), fallback_error=content_filter_error("assistant"))
    d = ad.elicit_decision(llm, system_message="ROLE", user_prompt="decide", actor=world.actors[0], world=world,
                           options=menu, scenarios=world.scenarios, round_num=1, language="English")
    assert d.status == "failed" and d.option["id"] == ad.HOLD_OPTION_ID
    assert "; fallback kimi: failed (BadRequestError (HTTP 400, provider code 1301, content filter)" in d.problems[0]
    assert transports == [("glm", False), ("kimi", True)]                      # degrade-safe: no further attempts
