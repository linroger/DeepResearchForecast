"""The reflexive loop end to end (offline, scripted arbiter; acceptance check R9, 2026-10-20).

One escalation told in four periods through ``world_update.run_world_round``, the round the runner
commits:

1. The United States announces a 145% tariff and expects China to back down. The canonical lag
   defers the numeric effect, while the arbiter records the announcement as a red-line crossing.
2. The tariff effect lands with normal damping and China answers the red-line crossing with a
   counter-measure. The US private brief shows that its expectation was wrong.
3. The US opens talks.
4. China accepts and the US withdraws in the same period: a breach that now shows in the US public
   track record, which every actor and the arbiter read next period.

Only APIs that exist before this iteration are used, so the same file shows what the old code did.
"""

from app.services import world_update as wu
from app.services.agent_decision import HOLD_TEMPLATE, build_option_menu, catalog_for
from app.services.world_model import WorldModel
from app.services.worldstate import WorldState, commitments_from_decisions

SCENARIOS = ["Truce", "Escalation"]


def _world():
    seed = {
        "question": "Will US-China tariffs exceed 100% at the end of 2026?",
        "scenarios": SCENARIOS,
        "state_variables": [{"name": "US tariff on Chinese goods", "value": "20%", "provenance": "official"}],
        "actors": [
            {"agent_id": 0, "name": "United States Government", "agency_class": "sovereign_government"},
            {"agent_id": 1, "name": "China Ministry of Commerce", "agency_class": "sovereign_government",
             "red_lines": ["No tariffs above 100% on Chinese goods"]},
        ],
        "settings": {"max_change_ratio": 0.5},
    }
    cfgs = [{"agent_id": 0, "entity_name": "United States Government"},
            {"agent_id": 1, "entity_name": "China Ministry of Commerce"}]
    return WorldModel.from_seed(seed, cfgs)


class _Arbiter:
    """Scripted consequence arbiter: one answer per period."""

    def __init__(self, answers):
        self.answers = list(answers)
        self.prompts = []

    def chat_json(self, messages, temperature=0.3, max_tokens=4096, **kwargs):
        self.prompts.append(messages[-1]["content"])
        return self.answers.pop(0)


def _decision(agent_id, name, option_id, kind, *, targets=(), statement="", terms="", expected=(),
              scenario=None, option=None):
    """Old decisions invented cost 1/lag 0; use sovereign templates or the supplied real response menu row."""
    if option is None:
        option = (HOLD_TEMPLATE.to_option() if option_id == "hold_position" else
                  next(t.to_option() for t in catalog_for("sovereign_government") if t.id == option_id))
    assert option["id"] == option_id and option["kind"] == kind
    return {"agent_id": agent_id, "actor_name": name,
            "option": dict(option),
            "targets": list(targets), "magnitude": 0.9, "public_statement": statement, "terms": terms,
            "expected_reactions": [{"actor": a, "reaction": r} for a, r in expected],
            "scenario": scenario, "scenario_confidence": 0.8, "status": "ok"}


def _step_shares(ws, record, decisions):
    """The share step as the runner takes it, world channel included."""
    from app.services.worldstate import commitment_mass, pressure_commitments

    rows = [{"agent_id": d["agent_id"], "scenario": d["scenario"], "magnitude": d["magnitude"],
             "confidence": d["scenario_confidence"]} for d in decisions if d.get("scenario")]
    conv = commitments_from_decisions(rows)
    world = (pressure_commitments(record.get("scenario_pressure"), dict(ws.shares), commitment_mass(conv),
                                  weight_ratio=0.35) if record.get("arbiter_status") == "applied" else [])
    ws.step(conv + world, round_status="committed" if conv else "abstained")


def test_announcement_red_line_expectation_and_breach_feed_back_into_the_world():
    """Old invented metadata landed 145 instantly and created no tariff pledge.

    C11 admits canonical moves, defers lag 1, and records that undelivered pledge's
    lapse after one grace period alongside the later agreement's explicit breach.
    """
    world = _world()
    ws = WorldState(SCENARIOS, {"Truce": 0.5, "Escalation": 0.5})
    arbiter = _Arbiter([
        {"narrative": "The tariff increase is announced; Beijing calls it a red line.",
         "variable_changes": [{"variable_id": "us_tariff_on_chinese_goods", "new_value": 145,
                               "caused_by": "United States Government", "rationale": "executive order"}],
         "red_line_crossings": [{"actor": "China Ministry of Commerce", "by": "United States Government",
                                 "red_line": "tariffs above 100% on Chinese goods", "rationale": "145% announced"}],
         "action_resolutions": [{"actor": "United States Government", "outcome": "success"}],
         "scenario_pressure": {"Escalation": "up", "Truce": "down"}},
        {"narrative": "Retaliation follows.", "scenario_pressure": {"Escalation": "up"}},
        {"narrative": "Talks open.", "scenario_pressure": {"Truce": "up"}},
        {"narrative": "Washington walks away.", "scenario_pressure": {"Escalation": "up"}},
    ])

    # -- period 1: the announcement crosses a red line; its numeric effect is not due yet ------------
    d1 = [_decision(0, "United States Government", "impose_measure", "policy", targets=["China Ministry of Commerce"],
                    statement="Tariffs on Chinese goods rise to 145% from Thursday.",
                    expected=[("China Ministry of Commerce", "back down and seek talks")], scenario="Escalation")]
    r1 = wu.run_world_round(world, 1, {"label": "2026-04"}, d1, [], llm=arbiter, rng=None, scenarios=SCENARIOS)
    _step_shares(ws, r1, d1)
    assert world.actors[0].last_action["status"] == "ok"
    assert world.actors[0].capacity_used == 3
    assert world.variables["us_tariff_on_chinese_goods"].value == 20.0
    assert len(world.pending_effects) == 1 and world.pending_effects[0].due_round == 2
    assert world.pending_effects[0].value == 145.0
    tariff_pledge = world.actors[0].commitments[0]
    assert tariff_pledge["source"] == "option_lag" and tariff_pledge["due_round"] == 2
    assert [e.kind for e in world.events_in_round(1, ("red_line",))] == ["red_line"]
    assert "Red lines at stake" in arbiter.prompts[0] and "No tariffs above 100%" in arbiter.prompts[0]
    menu = build_option_menu(world.actors[1], world, 2)
    assert menu[0]["why"] == "United States Government crossed your red line last period"
    escalation_after_1 = ws.shares["Escalation"]

    # -- period 2: the other side answers; the expectation was wrong ----------------------------------
    d2 = [_decision(1, "China Ministry of Commerce", menu[0]["id"], menu[0]["kind"],
                    targets=["United States Government"], statement="Counter-tariffs of 125% take effect.",
                    scenario="Escalation", option=menu[0]),
          _decision(0, "United States Government", "hold_position", "wait")]
    r2 = wu.run_world_round(world, 2, {"label": "2026-05"}, d2, [], llm=arbiter, rng=None, scenarios=SCENARIOS)
    _step_shares(ws, r2, d2)
    assert world.actors[1].last_action["status"] == "ok"
    assert world.variables["us_tariff_on_chinese_goods"].value == 27.0  # 20 -> step 30 -> reversion 28.5 -> drift cap 27
    assert world.variables["us_tariff_on_chinese_goods"].history[-1]["source"] == "effect"
    assert world.pending_effects == []
    us_note = world.render_private_brief(0, upto_round=2)
    assert "you expected \"back down and seek talks\"" in us_note and "China Ministry of Commerce" in us_note
    assert r2["behaviour"]["expectations_checked"] == 1 and r2["behaviour"]["expectations_reacted"] == 1
    assert ws.shares["Escalation"] > escalation_after_1 > 0.5

    # -- periods 3 and 4: an offer, then explicit acceptance and withdrawal (not a lapse) -------------
    d3 = [_decision(0, "United States Government", "open_talks", "coalition", targets=["China Ministry of Commerce"],
                    statement="We propose a 90-day pause.", terms="Both sides cut tariffs to 10% for 90 days",
                    scenario="Truce")]
    wu.run_world_round(world, 3, {"label": "2026-06"}, d3, [], llm=arbiter, rng=None, scenarios=SCENARIOS)
    assert tariff_pledge["status"] == "due"  # Round 3 is the grace period, not a delivery.
    (offer_id,) = [i for i, it in world.interactions.items() if it.is_open()]
    acceptance = next(o for o in build_option_menu(world.actors[1], world, 4)
                      if o["id"] == f"accept:{offer_id}")
    d4 = [_decision(1, "China Ministry of Commerce", f"accept:{offer_id}", "coalition", statement="Agreed.",
                    targets=["United States Government"], option=acceptance),
          _decision(0, "United States Government", "break_alliance", "coalition",
                    targets=["China Ministry of Commerce"], statement="We withdraw from the pause.")]
    wu.run_world_round(world, 4, {"label": "2026-07"}, d4, [], llm=arbiter, rng=None, scenarios=SCENARIOS)
    # the acceptance happened in period 4 and the US withdrew in the same period: its obligation is broken
    record = world.track_record(0)
    assert record["broken"] == 1 and record["kept"] == 0 and record["lapsed"] == 1
    assert tariff_pledge["status"] == "lapsed"
    brief = world.render_public_brief(upto_round=4)
    assert "## Track records" in brief and "- United States Government: kept 0 of 2 commitments (1 lapsed, 1 broken)" in brief
    rows = [_decision(0, "United States Government", "impose_measure", "policy", statement="New tariffs.",
                      targets=["China Ministry of Commerce"])]
    world.start_round(5, {"label": "2026-08"})
    world.register_decisions(5, rows)
    assert "Track record: kept 0 of 2 commitments (1 lapsed, 1 broken)" in wu.build_arbiter_prompt(world, 5, None, rows, {}, SCENARIOS)
    assert "%" not in brief.split("## Track records", 1)[1].split("##", 1)[0]   # herding guard holds
