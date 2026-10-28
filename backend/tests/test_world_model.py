"""Reflexive world-model kernel (design §2.3): pure, offline, deterministic.

Pins: quantity parsing, seed construction, decision mechanics (capacity, commitments,
alliance nudges), bounded arbiter application (change-ratio clamp), delayed effects
with a seeded RNG, lapsed commitments, snapshot/diff, agent-facing briefs (herding
guard: no scenario shares) and JSON round-trips.
"""

import json

import pytest

from app.services.world_model import (
    PendingEffect,
    Relationship,
    StateVariable,
    WorldModel,
    format_value,
    parse_quantity,
    slugify,
)


class _RNG:
    """Deterministic rng stand-in: returns the scripted values in order."""

    def __init__(self, values):
        self.values = list(values)

    def random(self):
        return self.values.pop(0) if self.values else 0.0


def _seed():
    return {
        "schema_version": "world-model-seed/v1",
        "question": "Will the grid permit unlock deployment by 2027?",
        "as_of_date": "2026-07-01",
        "horizon_date": "2027-03-31",
        "scenarios": ["Permit granted", "Permit delayed"],
        "state_variables": [
            {"name": "Alpha planned grid investment", "value": "US$2 billion", "as_of": "2026-07-01",
             "provenance": "research"},
            {"name": "Permit status", "value": "pending", "kind": "categorical", "provenance": "research"},
            {"name": "Regional capacity", "value": 120, "unit": "MW", "provenance": "official"},
        ],
        "actors": [
            {"agent_id": 0, "name": "Alpha Systems", "agency_class": "firm", "capacity_per_round": 2,
             "documented_plans": ["Build the Aurora line by 2027"], "red_lines": ["No unfinanced mandate"],
             "aliases": ["Alpha"], "outcome_power": 1.5},
            {"agent_id": 1, "name": "Beta Union", "agency_class": "labor_union", "capacity_per_round": 2},
            {"agent_id": 2, "name": "Grid Regulator", "agency_class": "regulator_agency", "capacity_per_round": 2},
        ],
        "relationships": [
            {"source": "Alpha Systems", "target": "Beta Union", "type": "OPPOSES", "valence": "adversarial",
             "strength": 0.8, "basis": "permit timetable"},
        ],
        "settings": {"max_change_ratio": 0.5},
    }


def _agent_configs():
    return [
        {"agent_id": 0, "entity_name": "Alpha Systems", "stance": "supportive", "gains_if": "timetable holds"},
        {"agent_id": 1, "entity_name": "Beta Union", "stance": "opposing"},
        {"agent_id": 2, "entity_name": "Grid Regulator", "stance": "neutral"},
        {"agent_id": 3, "entity_name": "Local Grid Co", "stance": "neutral"},
    ]


def _decision(agent_id, name, option, *, targets=(), magnitude=0.8, statement="", commitment=None,
              alliance_moves=(), status="ok"):
    return {
        "agent_id": agent_id, "actor_name": name, "option": option, "targets": list(targets),
        "magnitude": magnitude, "public_statement": statement, "commitment": commitment,
        "alliance_moves": list(alliance_moves), "status": status,
    }


# ----------------------------------------------------------------------------- parsing
@pytest.mark.parametrize("raw, number, unit", [
    ("US$2 billion", 2e9, "US$"),
    ("25%", 25.0, "%"),
    ("1,200 GW", 1200.0, "GW"),
    ("约 3.5 万亿", 3.5e12, ""),
    ("12.5 percent", 12.5, "%"),
    (7, 7.0, ""),
    ("pending", None, ""),
    (None, None, ""),
    (True, None, ""),
])
def test_parse_quantity_table(raw, number, unit):
    got_number, got_unit = parse_quantity(raw)
    assert got_number == number
    assert got_unit == unit


def test_slugify_stable_and_cjk_safe():
    assert slugify("US tariff rate on Chinese EVs (%)") == "us_tariff_rate_on_chinese_evs"
    assert slugify("关税 税率") == "关税_税率"
    assert slugify("") .startswith("var_")
    assert slugify("A" * 200) == "a" * 64


def test_format_value_units():
    assert format_value(2e9, "US$") == "US$2.00 billion"
    assert format_value(25.0, "%") == "25%"
    assert format_value(1200.0, "GW") == "1200 GW"
    assert format_value(25000.0, "GW") == "25,000 GW"
    assert format_value(3.5e12, "CNY") == "CNY3.50 trillion"
    assert format_value("pending", "") == "pending"
    assert format_value(True, "") == "yes"


# ----------------------------------------------------------------------------- seed
def test_from_seed_builds_actors_variables_relationships():
    world = WorldModel.from_seed(_seed(), _agent_configs())
    assert set(world.actors) == {0, 1, 2, 3}                      # cast members without a seed row still exist
    assert world.actors[3].agency_class == "other_actor"
    assert world.actors[0].outcome_power == 1.5 and world.actors[1].outcome_power is None
    assert world.actors[0].incentives == {"gains_if": "timetable holds"}  # seed row has none → cfg fallback
    assert world.actors[3].incentives == {}
    inv = world.variables["alpha_planned_grid_investment"]
    assert inv.kind == "numeric" and inv.value == 2e9 and inv.unit == "US$"
    assert world.variables["permit_status"].kind == "categorical"
    assert world.variables["regional_capacity"].unit == "MW"
    rel = world.relationships[(0, 1)]
    assert rel.valence == "adversarial" and rel.polarity < 0
    assert world.resolve_actor("alpha") == 0                        # alias
    assert world.resolve_actor("beta union") == 1
    assert world.resolve_actor("Nobody") is None
    assert world.scenarios == ["Permit granted", "Permit delayed"]


def test_cfg_incentives_used_when_seed_has_none():
    seed = _seed()
    seed["actors"] = []
    world = WorldModel.from_seed(seed, _agent_configs())
    assert world.actors[0].incentives == {"gains_if": "timetable holds"}
    assert world.actors[0].posture == "supportive"


# ----------------------------------------------------------------------------- decisions
def test_register_decisions_consumes_capacity_commits_and_nudges():
    """Old overspending was clipped and failures looked like actions; canonical moves now spend exactly and failures are system events."""
    world = WorldModel.from_seed(_seed(), _agent_configs())
    world.start_round(1, {"label": "2026-Q3", "period_start": "2026-07-02", "period_end": "2026-09-30"})
    invest = {"id": "invest_capex", "label": "Commit capital", "kind": "economic", "cost": 2, "lag": 2,
              "reversibility": "sticky"}
    ally = {"id": "form_alliance", "label": "Form alliance", "kind": "coalition", "cost": 2, "lag": 1}
    events = world.register_decisions(1, [
        _decision(0, "Alpha Systems", invest, statement="We commit $2bn to Aurora.",
                  commitment={"description": "Break ground on Aurora", "due_periods": 2}),
        _decision(2, "Grid Regulator", ally, targets=["Local Grid Co"],
                  alliance_moves=[{"target": "Local Grid Co", "move": "propose"}]),
        _decision(1, "Beta Union", {"id": "hold_position", "label": "Hold", "kind": "wait", "cost": 0}),
        _decision(3, "Local Grid Co", {"id": "x", "label": "x", "kind": "communication"}, status="failed"),
    ])
    kinds = [e.kind for e in events]
    assert kinds.count("action") == 3 and kinds.count("system") == 1
    alpha = world.actors[0]
    assert alpha.capacity_used == 2                                  # full canonical cost, no clipping
    assert alpha.capacity_remaining == 0
    assert alpha.last_action["option_id"] == "invest_capex"
    assert [c["description"] for c in alpha.pending_commitments()] == ["Break ground on Aurora"]
    assert alpha.pending_commitments()[0]["due_round"] == 3
    # coalition move created a relationship and pulled it closer
    rel = world._relationship_between(2, 3)
    assert rel is not None and rel.polarity > 0
    # hold and failed decisions record events but no commitments
    assert world.actors[1].pending_commitments() == []
    assert world.actors[3].pending_commitments() == []
    assert any("no recorded move (failed)" in e.description for e in events)
    # statement preserved on the action event
    assert any(e.statement.startswith("We commit") for e in events)


def test_alliance_break_moves_relationship_apart():
    """Old alliance extras supplied an implicit target; C11 requires the move's explicit target binding."""
    world = WorldModel.from_seed(_seed(), _agent_configs())
    world.start_round(1, None)
    before = world.relationships[(0, 1)].polarity
    world.register_decisions(1, [_decision(0, "Alpha Systems", {"id": "break_alliance", "label": "Break",
                                                               "kind": "coalition", "cost": 2},
                                           targets=["Beta Union"],
                                           alliance_moves=[{"target": "Beta Union", "move": "break"}])])
    assert world.relationships[(0, 1)].polarity < before


# ----------------------------------------------------------------------------- arbiter application
def test_apply_arbiter_update_clamps_and_records():
    """Old resolutions credited actors with no move; C11 requires a current admitted action, while numeric damping stays unchanged."""
    world = WorldModel.from_seed(_seed(), _agent_configs())
    world.start_round(1, {"label": "2026-Q3", "period_end": "2026-09-30"})
    world.register_decisions(1, [_decision(0, "Alpha Systems",
        {"id": "public_statement", "label": "Financing update", "kind": "communication", "cost": 1, "lag": 0})])
    summary = world.apply_arbiter_update(1, {
        "variable_changes": [
            {"variable_id": "regional_capacity", "new_value": 1000, "rationale": "Aurora announced"},
            {"variable_id": "permit_status", "new_value": "under review", "rationale": "inquiry"},
            {"variable_id": "does_not_exist", "new_value": 1},
        ],
        "new_variables": [{"name": "Union strike risk", "value": "elevated", "kind": "categorical",
                           "rationale": "Strike rhetoric escalated"}],
        "events": [{"description": "Markets react to the Aurora pledge", "kind": "emergent",
                    "actors": ["Alpha Systems"]}],
        "relationship_changes": [{"source": "Alpha Systems", "target": "Grid Regulator", "direction": "closer"}],
        "pending_effects": [{"description": "Permit decision lands", "due_periods": 1,
                             "variable_id": "permit_status", "new_value": "granted", "probability": 0.5}],
        "action_resolutions": [{"actor": "Alpha Systems", "outcome": "partial", "rationale": "financing open"}],
    })
    cap = world.variables["regional_capacity"]
    # 2026-10-22 三层阻尼：1000 → 步长钳 180 → 回归 κ=0.15 → 171 → 漂移上限
    # 120×1.35=162（sim_3ec25e64209e 复盘后单层步长钳不足以约束复合漂移）
    assert cap.value == 162.0
    assert cap.history[-1]["cause"].startswith("Aurora announced") and "damped" in cap.history[-1]["cause"]
    assert cap.history[-1]["source"] == "arbiter"
    assert world.variables["permit_status"].value == "under review"
    assert [c["id"] for c in summary["variables_changed"]] == ["regional_capacity", "permit_status"]
    assert summary["variables_added"][0]["id"] == "union_strike_risk"
    added = world.variables["union_strike_risk"]
    assert added.history[0]["round"] == 1 and added.history[0]["cause"] == "Strike rhetoric escalated"
    assert summary["events"] == 1 and summary["effects_added"] == 1 and summary["resolutions"] == 1
    assert world._relationship_between(0, 2).polarity > 0
    assert world.pending_effects[0].due_round == 2
    assert world.actors[0].last_action["status"] == "ok"
    assert world.actors[0].last_action["resolution"] == "partial"


def test_apply_arbiter_update_no_clamp_when_ratio_disabled():
    seed = _seed()
    # 2026-10-22：阻尼拆成三个独立旋钮（步长/回归/漂移），全部关闭才完全不钳。
    seed["settings"] = {"max_change_ratio": None, "reversion_kappa": 0, "max_drift_ratio": None}
    world = WorldModel.from_seed(seed, _agent_configs())
    world.start_round(1, None)
    world.apply_arbiter_update(1, {"variable_changes": [{"variable_id": "regional_capacity", "new_value": 1000}]})
    assert world.variables["regional_capacity"].value == 1000.0


# ----------------------------------------------------------------------------- delayed effects & commitments
def test_fire_due_effects_rolls_probability_with_seeded_rng():
    world = WorldModel.from_seed(_seed(), _agent_configs())
    world.start_round(1, None)
    world.pending_effects.append(PendingEffect("fx1", due_round=2, description="Permit granted",
                                               variable_id="permit_status", op="set", value="granted",
                                               probability=0.5, source="arbiter"))
    world.pending_effects.append(PendingEffect("fx2", due_round=2, description="Capacity add",
                                               variable_id="regional_capacity", op="add", value=30,
                                               probability=0.5, source="arbiter"))
    world.pending_effects.append(PendingEffect("fx3", due_round=5, description="Later", probability=1.0))
    assert world.fire_due_effects(1, _RNG([0.9, 0.9])) == []        # nothing due yet
    world.start_round(2, {"label": "2026-Q4"})
    fired = world.fire_due_effects(2, _RNG([0.1, 0.9]))              # first happens, second does not
    assert [f["happened"] for f in fired] == [True, False]
    assert world.variables["permit_status"].value == "granted"
    assert world.variables["regional_capacity"].value == 120.0
    assert [fx.id for fx in world.pending_effects] == ["fx3"]
    descs = [e.description for e in world.events_in_round(2, ("consequence",))]
    assert "Permit granted" in descs and any(d.startswith("Did not materialise") for d in descs)


def test_commitments_become_due_then_lapse():
    """Old due-2 promises lapsed at 3; C11 keeps grace3 and lapses at 4."""
    world = WorldModel.from_seed(_seed(), _agent_configs())
    world.start_round(1, None)
    world.actors[0].add_commitment("Break ground", made_round=1, due_round=2)
    world.start_round(2, None)
    assert world.actors[0].commitments[0]["status"] == "due"
    assert world.lapse_overdue_commitments(2) == []
    world.start_round(3, None)
    assert world.lapse_overdue_commitments(3) == []
    assert world.actors[0].commitments[0]["status"] == "due"
    world.start_round(4, None)
    lapsed = world.lapse_overdue_commitments(4)
    assert lapsed and lapsed[0]["status"] == "lapsed"
    assert any("lapsed" in e.description for e in world.events_in_round(4))


def test_unrelated_action_and_generic_resolution_do_not_fulfil_due_commitment():
    """Old investment fixture bypassed cost/lag checks; C11 admits the canonical move before proving generic success cannot deliver."""
    world = WorldModel.from_seed(_seed(), _agent_configs())
    world.set_period_labels({1: "2026-Q3", 2: "2026-Q4"})
    world.start_round(1, None)
    world.actors[0].add_commitment("Break ground", made_round=1, due_round=2)
    world.apply_arbiter_update(1, {"action_resolutions": [{"actor": "Alpha Systems", "outcome": "success"}]})
    assert world.actors[0].commitments[0]["status"] == "pending"      # success of the move ≠ delivery of the pledge
    world.start_round(2, None)
    assert "due 2026-Q4" in world.render_public_brief(upto_round=1)
    world.register_decisions(2, [_decision(0, "Alpha Systems", {"id": "invest_capex", "label": "Commit capital",
                                                               "kind": "economic", "cost": 2, "lag": 2})])
    assert world.actors[0].last_action["status"] == "ok"
    world.apply_arbiter_update(2, {"action_resolutions": [{"actor": "Alpha Systems", "outcome": "success"}]})
    assert world.actors[0].commitments[0]["status"] == "due"
    assert "fulfilled_round" not in world.actors[0].commitments[0]


# ----------------------------------------------------------------------------- snapshot / diff / briefs
def test_diff_reports_changed_added_and_relationship_moves():
    world = WorldModel.from_seed(_seed(), _agent_configs())
    world.start_round(1, None)
    before = world.snapshot()
    world.apply_arbiter_update(1, {
        "variable_changes": [{"variable_id": "regional_capacity", "new_value": 150}],
        "new_variables": [{"name": "Permit filings", "value": 3}],
        "relationship_changes": [{"source": "Alpha Systems", "target": "Beta Union", "direction": "closer"}],
    })
    diff = world.diff(before)
    assert diff["variables_changed"][0]["id"] == "regional_capacity" and diff["variables_changed"][0]["to"] == 145.5  # 150 经 κ=0.15 回归锚点 120
    assert diff["variables_added"][0]["name"] == "Permit filings"
    assert diff["relationships_changed"][0]["direction"] == "closer"


def test_public_brief_shows_facts_moves_consequences_and_no_scenario_shares():
    """Old cost-3 investment was silently clipped; canonical cost 2 now admits the same published move and pledge."""
    world = WorldModel.from_seed(_seed(), _agent_configs())
    world.scenario_shares = {"Permit granted": 0.63, "Permit delayed": 0.37}
    world.start_round(1, {"label": "2026-Q3", "period_start": "2026-07-02", "period_end": "2026-09-30"})
    before = world.snapshot()
    world.register_scheduled_events(1, [{"date": "2026-09-15", "content": "[2026-09-15] Permit hearing held"}])
    world.register_decisions(1, [_decision(0, "Alpha Systems", {"id": "invest_capex", "label": "Commit capital",
                                                               "kind": "economic", "cost": 2, "lag": 2},
                                           statement="We commit to Aurora now.",
                                           commitment={"description": "Break ground", "due_periods": 2})])
    world.apply_arbiter_update(1, {"variable_changes": [{"variable_id": "regional_capacity", "new_value": 150}]})
    world.commit_round(1)
    brief = world.render_public_brief(upto_round=1, previous=before)
    assert brief.startswith("# WORLD STATE — as of 2026-09-30 (after 2026-Q3)")
    assert "## Key facts" in brief and "Regional capacity: 145.5 MW (was 120 MW last period)" in brief
    assert "## Moves last period" in brief and 'Alpha Systems: Commit capital — "We commit to Aurora now."' in brief
    assert "## Consequences and events" in brief and "Permit hearing held" in brief
    assert "## Pending and announced" in brief and "Break ground" in brief
    # herding guard: the scenario distribution never reaches agent-facing text
    assert "63" not in brief and "37" not in brief and "%" not in brief
    assert "Permit granted" not in brief and "Permit delayed" not in brief


def test_private_brief_lists_own_commitments_and_moves_aimed_at_actor():
    """Old over-budget fixtures passed and the title came first; C11 admits canonical costs and protects red lines first."""
    world = WorldModel.from_seed(_seed(), _agent_configs())
    world.start_round(1, {"label": "2026-Q3", "period_end": "2026-09-30"})
    world.register_decisions(1, [
        _decision(1, "Beta Union", {"id": "strike_action", "label": "Call a strike", "kind": "coercive",
                                    "cost": 2, "lag": 0}, targets=["Alpha Systems"]),
        _decision(0, "Alpha Systems", {"id": "invest_capex", "label": "Commit capital", "kind": "economic",
                                       "cost": 2, "lag": 2}, commitment={"description": "Break ground", "due_periods": 1}),
    ])
    world.commit_round(1)
    world.start_round(2, {"label": "2026-Q4", "period_end": "2026-12-31"})
    note = world.render_private_brief(0, upto_round=1)
    assert note.startswith("- Your red lines: No unfinanced mandate\n# YOUR SITUATION — Alpha Systems")
    assert "Capacity this period: 2/2" in note
    assert "Break ground" in note and "(DUE NOW)" in note
    assert "Aimed at you last period" in note and "Beta Union: Call a strike" in note
    assert "Rivals / opponents: Beta Union" in note
    assert "Your red lines: No unfinanced mandate" in note
    assert world.render_private_brief(99) == ""


def test_brief_respects_char_budget_on_line_boundaries():
    world = WorldModel.from_seed(_seed(), _agent_configs())
    world.start_round(1, None)
    brief = world.render_public_brief(upto_round=0, previous=None, max_chars=80)
    assert len(brief) <= 80
    assert not brief.endswith("…") or "\n" not in brief


# ----------------------------------------------------------------------------- persistence
def test_json_round_trip_preserves_state():
    """Old two moves silently overspent one period; C11 saves canonical investment and irreversible launch in separate periods."""
    world = WorldModel.from_seed(_seed(), _agent_configs())
    world.start_round(1, {"label": "2026-Q3", "period_end": "2026-09-30"})
    world.register_decisions(1, [
        _decision(0, "Alpha Systems", {"id": "invest_capex", "label": "Commit capital",
                                       "kind": "economic", "cost": 2, "lag": 2},
                  commitment={"description": "Break ground", "due_periods": 1}),
    ])
    world.commit_round(1)
    world.start_round(2, {"label": "2026-Q4", "period_end": "2026-12-31"})
    world.register_decisions(2, [_decision(0, "Alpha Systems",
        {"id": "product_launch", "label": "Launch", "kind": "operational",
         "cost": 2, "lag": 1, "reversibility": "irreversible"})])
    world.apply_arbiter_update(2, {"pending_effects": [{"description": "Permit lands", "due_periods": 1}],
                                   "events": [{"description": "Reaction", "kind": "emergent"}]})
    world.commit_round(2)
    world.scenario_shares = {"Permit granted": 0.6, "Permit delayed": 0.4}
    payload = json.loads(json.dumps(world.to_dict(), ensure_ascii=False))
    clone = WorldModel.from_dict(payload)
    assert clone.snapshot() == world.snapshot()
    assert clone.committed_round == 2 and clone.round == 2
    assert clone.actors[0].pending_commitments()[0]["description"] == "Break ground"
    assert [fx.description for fx in clone.pending_effects] == ["Permit lands"]
    assert [e.description for e in clone.events] == [e.description for e in world.events]
    assert clone.scenario_shares == world.scenario_shares
    assert clone.resolve_actor("Alpha") == 0
    assert "product_launch" in clone.actors[0].irreversible_option_ids
    assert clone.to_dict() == world.to_dict()


def test_state_variable_never_keeps_a_kind_name_as_unit():
    """Arbiter-created facts of the live run carried unit='boolean' / 'text' / 'date' (the kind
    echoed into the unit field) and rendered as "yes boolean"; a unit belongs to numeric facts
    only, and a kind name is never a unit — in the kernel, on load and in format_value."""
    assert StateVariable("t", "Talks opened", True, unit="boolean", kind="boolean").unit == ""
    assert StateVariable("d", "Deadline", "2027-03-10", unit="date", kind="text").unit == ""
    assert StateVariable("n", "Backlog", 12, unit="numeric", kind="numeric").unit == ""
    assert StateVariable("p", "Tariff", 10, unit="%", kind="numeric").unit == "%"
    var = StateVariable("c", "Capacity", 120, unit="MW", kind="numeric")
    assert var.set_value("suspended", round_num=1, source="arbiter", cause="test") is True
    assert var.kind == "text" and var.unit == ""
    loaded = StateVariable.from_dict({"id": "t", "name": "Talks opened", "value": True, "unit": "boolean",
                                      "kind": "boolean"})
    assert loaded.unit == "" and loaded.value is True
    assert format_value(True, "boolean") == "yes"
    assert format_value("2027-03-10", "date") == "2027-03-10"
    assert format_value(12.0, "numeric") == "12"
    assert format_value(12.0, "MW") == "12 MW"


def test_state_variable_and_relationship_dicts():
    var = StateVariable("x", "X", "12%", kind="numeric")
    assert var.value == 12.0 and var.unit == "" and var.kind == "numeric"
    assert var.set_value(15, round_num=2, source="arbiter", cause="test") is True
    assert var.set_value(15, round_num=3, source="arbiter", cause="noop") is False
    rel = Relationship(0, 1, kind="ALLY_OF", valence="allied")
    rel.nudge(-0.9, round_num=1, cause="betrayal")
    assert rel.valence == "adversarial" and rel.polarity == -0.1 or rel.polarity < 0
    assert Relationship.from_dict(rel.to_dict()).to_dict() == rel.to_dict()
