"""Per-round world update (design §2.5): deterministic step, arbiter validation, digest.

Offline with the conftest FakeLLMClient.  Pins: variable ids in the arbiter prompt,
unknown ids / actors filtered, numeric clamp through the kernel, arbiter failure
leaves the round committed with the deterministic update, digest herding guard.
"""

import random

from app.services import world_update as wu
from app.services.agent_decision import AgentDecision
from app.services.world_model import WorldModel
from tests.conftest import FakeLLMClient


def _world():
    seed = {
        "question": "Will the permit unlock deployment?",
        "scenarios": ["Permit granted", "Permit delayed"],
        "state_variables": [
            {"name": "Regional capacity", "value": 120, "unit": "MW", "provenance": "official"},
            {"name": "Permit status", "value": "pending", "kind": "categorical"},
        ],
        "actors": [
            {"agent_id": 0, "name": "Alpha Systems", "agency_class": "firm", "outcome_power": 1.5},
            {"agent_id": 1, "name": "Beta Union", "agency_class": "labor_union"},
            {"agent_id": 2, "name": "Grid Regulator", "agency_class": "regulator_agency"},
        ],
        "settings": {"max_change_ratio": 0.5},
    }
    cfgs = [{"agent_id": i, "entity_name": n} for i, n in enumerate(["Alpha Systems", "Beta Union", "Grid Regulator"])]
    return WorldModel.from_seed(seed, cfgs)


_PERIOD = {"label": "2026-Q3", "period_start": "2026-07-02", "period_end": "2026-09-30"}


def _decisions():
    invest = {"id": "invest_capex", "label": "Commit capital: new plant", "kind": "economic", "cost": 3, "lag": 2,
              "reversibility": "sticky"}
    return [
        AgentDecision(0, "Alpha Systems", invest, targets=[], magnitude=0.9,
                      public_statement="We commit $2bn to Aurora this quarter.", scenario="Permit granted",
                      scenario_confidence=0.8, round_num=1, period_end="2026-09-30"),
        AgentDecision(1, "Beta Union", {"id": "hold_position", "label": "Hold", "kind": "wait", "cost": 0},
                      targets=[], magnitude=0.0, public_statement="", scenario="abstain", round_num=1),
        AgentDecision(2, "Grid Regulator", {"id": "open_inquiry", "label": "Open an inquiry", "kind": "legal",
                                            "cost": 2, "lag": 1}, targets=["Alpha Systems"], magnitude=0.6,
                      public_statement="We open a review of the Aurora filing.", status="ok", round_num=1),
    ]


def test_deterministic_update_registers_everything():
    world = _world()
    world.start_round(1, _PERIOD)
    det = wu.deterministic_round_update(world, 1, _PERIOD, _decisions(),
                                        [{"date": "2026-09-15", "content": "[2026-09-15] Permit hearing"}],
                                        random.Random(1))
    assert det["scheduled_events"] == ["[2026-09-15] Permit hearing"]
    assert det["decisions"] == 3 and len(det["actions"]) == 3
    assert world.actors[0].capacity_used == 2 and world.actors[2].capacity_used == 2
    assert world.actors[0].pending_commitments()[0]["due_round"] == 3          # lag 2 → announced commitment
    assert world._relationship_between(2, 0).polarity < 0                       # legal move pushes apart


def test_arbiter_prompt_lists_variable_ids_moves_and_cast():
    world = _world()
    world.start_round(1, _PERIOD)
    det = wu.deterministic_round_update(world, 1, _PERIOD, _decisions(), [], random.Random(1))
    prompt = wu.build_arbiter_prompt(world, 1, _PERIOD, _decisions(), det, world.scenarios, language="English")
    assert "- regional_capacity: Regional capacity = 120 MW" in prompt
    assert "- permit_status: Permit status = pending [categorical]" in prompt
    assert "Alpha Systems: Commit capital: new plant (kind=economic, magnitude=0.9)" in prompt
    assert "Grid Regulator: Open an inquiry" in prompt and "→ Alpha Systems" in prompt
    assert "Beta Union" in prompt and "Hold" not in prompt.split("## Moves this period")[1].split("##")[0]
    assert "Candidate scenarios: Permit granted; Permit delayed" in prompt
    assert "Write narrative and descriptions in English." in prompt
    assert "Return ONLY JSON" in prompt


def test_validate_filters_unknowns_and_types():
    world = _world()
    world.start_round(1, _PERIOD)
    update, problems = wu.validate_arbiter_update({
        "narrative": "x" * 2000,
        "variable_changes": [
            {"variable_id": "regional_capacity", "delta": "15"},
            {"variable_id": "Permit status", "new_value": "under review"},          # name instead of id
            {"variable_id": "ghost", "new_value": 1},
            {"variable_id": "regional_capacity", "new_value": "lots"},
        ],
        "new_variables": [{"name": "Strike risk", "value": "elevated", "kind": "categorical"},
                          {"name": "Bad numeric", "value": "n/a", "kind": "numeric"},
                          {"name": "A"}, {"name": "B"}, {"name": "C"}],
        "events": [{"description": "Markets react", "kind": "weird", "actors": ["Alpha", "Zed"]}],
        "relationship_changes": [{"source": "Alpha Systems", "target": "Grid Regulator", "direction": "closer"},
                                 {"source": "Alpha Systems", "target": "Alpha", "direction": "closer"},
                                 {"source": "Alpha Systems", "target": "Beta Union", "direction": "sideways"}],
        "pending_effects": [{"description": "Permit lands", "due_periods": 99, "variable_id": "permit_status",
                             "new_value": "granted", "probability": 1.7},
                            {"description": "Capacity add", "variable_id": "regional_capacity", "delta": 30}],
        "action_resolutions": [{"actor": "Alpha Systems", "outcome": "partial"}, {"actor": "Zed", "outcome": "success"},
                               {"actor": "Beta Union", "outcome": "maybe"}],
        "scenario_pressure": {"permit granted": "up", "Permit delayed": "sideways", "Other": "down"},
    }, world, world.scenarios)
    assert len(update["narrative"]) <= wu.NARRATIVE_MAX_CHARS
    assert update["variable_changes"] == [
        {"variable_id": "regional_capacity", "rationale": "", "delta": 15.0},
        {"variable_id": "permit_status", "rationale": "", "new_value": "under review"},
    ]
    assert [nv["name"] for nv in update["new_variables"]] == ["Strike risk", "Bad numeric", "A"]
    assert update["new_variables"][1]["kind"] == "text"
    assert update["events"][0]["kind"] == "emergent" and update["events"][0]["actors"] == ["Alpha Systems"]
    assert update["relationship_changes"] == [{"source": "Alpha Systems", "target": "Grid Regulator",
                                               "direction": "closer", "rationale": ""}]
    assert update["pending_effects"][0]["due_periods"] == 12 and update["pending_effects"][0]["probability"] == 1.0
    assert update["pending_effects"][1]["delta"] == 30.0
    assert update["action_resolutions"] == [{"actor": "Alpha Systems", "outcome": "partial", "rationale": ""}]
    assert update["scenario_pressure"] == {"Permit granted": "up"}
    joined = " | ".join(problems)
    assert "unknown variable 'ghost'" in joined and "non-numeric change" in joined
    assert "unknown actor 'Zed'" in joined and "sideways" in joined and "new variables dropped" in joined


def test_run_world_round_applies_arbiter_and_builds_digest():
    world = _world()
    world.start_round(1, _PERIOD)
    llm = FakeLLMClient(json_responses=[{
        "narrative": "Alpha's pledge lifts expected capacity; the regulator's review slows the timetable.",
        "variable_changes": [{"variable_id": "regional_capacity", "new_value": 400, "rationale": "pledge"},
                             {"variable_id": "permit_status", "new_value": "under review"}],
        "events": [{"description": "Bond market prices Aurora financing", "kind": "emergent", "actors": ["Alpha Systems"]}],
        "pending_effects": [{"description": "Review concludes", "due_periods": 1, "variable_id": "permit_status",
                             "new_value": "granted", "probability": 0.5}],
        "action_resolutions": [{"actor": "Alpha Systems", "outcome": "partial"},
                               {"actor": "Grid Regulator", "outcome": "success"}],
        "scenario_pressure": {"Permit delayed": "up"},
    }])
    record = wu.run_world_round(world, 1, _PERIOD, _decisions(), [], llm=llm, rng=random.Random(3),
                                scenarios=world.scenarios, language="English")
    assert record["arbiter_status"] == "applied" and record["arbiter_problems"] == []
    assert world.variables["regional_capacity"].value == 180.0                  # 120 → clamped to +50%
    assert world.variables["permit_status"].value == "under review"
    assert world.committed_round == 1
    assert record["decisions"] == {"total": 3, "ok": 3, "held": 1, "failed": 0, "invalid": 0}
    assert record["scenario_pressure"] == {"Permit delayed": "up"}
    assert world.actors[0].last_action["resolution"] == "partial"
    assert len(world.pending_effects) == 1
    digest = record["digest"]
    assert digest.startswith("Alpha's pledge lifts expected capacity")
    assert '- Alpha Systems: Commit capital: new plant: "We commit $2bn to Aurora this quarter."' in digest
    assert "Held position: Beta Union" in digest
    assert "- Regional capacity: 120 MW → 180 MW" in digest
    assert "Bond market prices Aurora financing" in digest
    assert "Alpha Systems — Grid Regulator: adversarial" in digest or "Grid Regulator — Alpha Systems" in digest
    # herding guard: no scenario shares / percentages in agent-facing text
    assert "%" not in digest and "Permit granted" not in digest
    assert "2026-Q3: 3 decisions" in record["headline"] and "arbiter=applied" in record["headline"]
    assert llm.calls and "Return ONLY JSON" in llm.calls[0]["messages"][0]["content"]


def test_run_world_round_survives_arbiter_failure_and_disabled():
    class Boom:
        def chat_json(self, **kwargs):
            raise RuntimeError("down")

    world = _world()
    world.start_round(1, _PERIOD)
    record = wu.run_world_round(world, 1, _PERIOD, _decisions(), [], llm=Boom(), rng=random.Random(0),
                                scenarios=world.scenarios)
    assert record["arbiter_status"] == "failed" and record["arbiter_problems"] == ["llm error: RuntimeError"]
    assert world.committed_round == 1 and world.variables["regional_capacity"].value == 120.0
    assert record["decisions"]["total"] == 3 and "Alpha Systems" in record["digest"]

    world2 = _world()
    world2.start_round(1, _PERIOD)
    rec2 = wu.run_world_round(world2, 1, _PERIOD, _decisions(), [], llm=None, rng=random.Random(0),
                              scenarios=world2.scenarios, arbiter_enabled=False)
    assert rec2["arbiter_status"] == "skipped" and world2.committed_round == 1

    world3 = _world()
    world3.start_round(1, _PERIOD)
    rec3 = wu.run_world_round(world3, 1, _PERIOD, _decisions(), [], llm=FakeLLMClient(json_responses=["garbage"]),
                              rng=random.Random(0), scenarios=world3.scenarios)
    assert rec3["arbiter_status"] == "invalid" and world3.committed_round == 1


def test_dead_round_commits_with_no_decisions():
    world = _world()
    world.start_round(2, {"label": "2026-Q4", "period_end": "2026-12-31"})
    record = wu.run_world_round(world, 2, {"label": "2026-Q4", "period_end": "2026-12-31"}, [], [],
                                llm=FakeLLMClient(json_responses=[{"narrative": "Quiet quarter."}]),
                                rng=random.Random(0), scenarios=world.scenarios)
    assert record["decisions"]["total"] == 0 and record["arbiter_status"] == "applied"
    assert record["digest"].startswith("Quiet quarter.")
    assert world.committed_round == 2
