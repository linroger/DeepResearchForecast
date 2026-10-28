"""Per-round world update (design §2.5): deterministic step, arbiter validation, digest.

Offline with the conftest FakeLLMClient.  Pins: variable ids in the arbiter prompt,
unknown ids / actors filtered, numeric clamp through the kernel, arbiter failure
leaves the round committed with the deterministic update, digest herding guard,
provider failures recorded precisely (class, HTTP status, provider code, snippet,
failover outcome), one fallback-provider retry through the real LLMClient, and
kind-name units ("yes boolean") never reaching a brief.
"""

import random

from app.services import world_update as wu
from app.services.agent_decision import AgentDecision, catalog_for
from app.services.world_model import WorldModel
from tests.conftest import FakeLLMClient, content_filter_error


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
    """Old fixtures invented investment cost 3; C11 admits the class catalogue's cost and lag."""
    invest = next(t.to_option(label="Commit capital: new plant")
                  for t in catalog_for("firm") if t.id == "invest_capex")
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
    """Old cost-3 fixture was clipped to 2; C11 admits cost-2 investment and charges it exactly."""
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
            {"variable_id": "regional_capacity", "delta": "NaN"},
        ],
        "new_variables": [{"name": "Strike risk", "value": "elevated", "kind": "categorical"},
                          {"name": "Bad numeric", "value": "n/a", "kind": "numeric"},
                          {"name": "A"}, {"name": "B"}, {"name": "C"}],
        "events": [{"description": "Markets react", "kind": "weird", "actors": ["Alpha", "Zed"], "variable_ids": 1}],
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
    assert "unknown variable 'ghost'" in joined and "duplicate change for 'regional_capacity'" in joined
    assert "unknown actor 'Zed'" in joined and "sideways" in joined and "new variables dropped" in joined


def test_validate_rejects_non_finite_numeric_changes():
    world = _world()
    world.start_round(1, _PERIOD)
    update, problems = wu.validate_arbiter_update({
        "variable_changes": [
            {"variable_id": "regional_capacity", "delta": "Infinity"},
            {"variable_id": "regional_capacity", "new_value": "NaN"},
        ],
    }, world, world.scenarios)
    assert update["variable_changes"] == []
    assert any("non-numeric change for numeric variable" in p for p in problems)


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
    assert world.variables["regional_capacity"].value == 162.0  # 1000→步长钳180→回归171→漂移上限162
    assert world.variables["permit_status"].value == "under review"
    assert world.committed_round == 1
    assert record["decisions"] == {"total": 3, "ok": 3, "held": 1, "failed": 0, "invalid": 0,
                                   "language_mismatch": 0}
    assert record["scenario_pressure"] == {"Permit delayed": "up"}
    assert world.actors[0].last_action["resolution"] == "partial"
    assert len(world.pending_effects) == 1
    digest = record["digest"]
    assert digest.startswith("Alpha's pledge lifts expected capacity")
    assert '- Alpha Systems: Commit capital: new plant: "We commit $2bn to Aurora this quarter."' in digest
    assert "Held position: Beta Union" in digest
    assert "- Regional capacity: 120 MW → 162 MW" in digest
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
    assert record["arbiter_status"] == "failed" and record["arbiter_problems"] == ["llm error: RuntimeError: down"]
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

    class BadPayload:
        def chat_json(self, **kwargs):
            return {"events": [{"description": "Bad", "variable_ids": 1}]}

    world4 = _world()
    world4.start_round(1, _PERIOD)
    rec4 = wu.run_world_round(world4, 1, _PERIOD, _decisions(), [], llm=BadPayload(), rng=random.Random(0),
                              scenarios=world4.scenarios)
    assert rec4["arbiter_status"] == "applied"


def test_overdue_commitments_lapse_before_new_actions():
    """Old promises lapsed immediately after due_round; C11 permits one full grace period first."""
    world = _world()
    alpha = world.actors[0]
    alpha.add_commitment("Missed milestone", made_round=1, due_round=1)
    world.start_round(2, _PERIOD)
    decision = AgentDecision(0, "Alpha Systems", {"id": "public_statement", "label": "Speak", "kind": "communication", "cost": 1},
                             targets=[], magnitude=0.2, public_statement="Act now.", round_num=2)
    det = wu.deterministic_round_update(world, 2, _PERIOD, [decision], [], random.Random(0))
    assert det["commitments_lapsed"] == [] and alpha.commitments[0]["status"] == "due"
    world.commit_round(2)
    world.start_round(3, _PERIOD)
    det = wu.deterministic_round_update(world, 3, _PERIOD, [], [], random.Random(0))
    assert det["commitments_lapsed"] == ["Alpha Systems: Missed milestone"]
    assert alpha.commitments[0]["status"] == "lapsed"


def test_dead_round_commits_with_no_decisions():
    world = _world()
    world.start_round(2, {"label": "2026-Q4", "period_end": "2026-12-31"})
    record = wu.run_world_round(world, 2, {"label": "2026-Q4", "period_end": "2026-12-31"}, [], [],
                                llm=FakeLLMClient(json_responses=[{"narrative": "Quiet quarter."}]),
                                rng=random.Random(0), scenarios=world.scenarios)
    assert record["decisions"]["total"] == 0 and record["arbiter_status"] == "applied"
    assert record["digest"].startswith("Quiet quarter.")
    assert world.committed_round == 2


# ---------------------------------------------------------------------------
# provider failures: precise records and the fallback-provider retry
# ---------------------------------------------------------------------------
_FILTER_HEAD = "llm error: BadRequestError (HTTP 400, provider code 1301, content filter"


class _Filtered:
    """Stand-in whose only answer is the live Zhipu content-filter rejection."""

    def chat_json(self, **kwargs):
        raise content_filter_error()


def test_arbiter_content_filter_failure_record_is_precise():
    """sim_d6ebcc77e22d recorded only ``llm error: BadRequestError`` for two content-filter
    rejections; the record must name class, HTTP status, provider code and the message."""
    world = _world()
    world.start_round(1, _PERIOD)
    record = wu.run_world_round(world, 1, _PERIOD, _decisions(), [], llm=_Filtered(), rng=random.Random(0),
                                scenarios=world.scenarios)
    assert record["arbiter_status"] == "failed" and world.committed_round == 1
    [problem] = record["arbiter_problems"]
    assert problem.startswith(_FILTER_HEAD + "): Error code: 400 - {'contentFilter'")
    assert "'code': '1301'" in problem
    assert len(problem) <= len(_FILTER_HEAD) + 2 + 2 + wu.ARBITER_ERROR_SNIPPET_CHARS
    assert world.variables["regional_capacity"].value == 120.0            # no fabricated numeric effect
    assert "arbiter=failed" in record["headline"]


def test_arbiter_content_filter_recovers_through_fallback_provider(scripted_failover):
    """The arbiter goes through the backend LLMClient: a content-filter rejection is retried ONCE
    on the configured fallback provider and the round is applied from its answer."""
    payload = {"narrative": "Fallback arbiter resolved the period.",
               "variable_changes": [{"variable_id": "permit_status", "new_value": "under review"}],
               "action_resolutions": [{"actor": "Alpha Systems", "outcome": "partial"}]}
    llm, transports = scripted_failover(content_filter_error(), payload)
    world = _world()
    world.start_round(1, _PERIOD)
    record = wu.run_world_round(world, 1, _PERIOD, _decisions(), [], llm=llm, rng=random.Random(0),
                                scenarios=world.scenarios)
    assert record["arbiter_status"] == "applied" and record["arbiter_problems"] == []
    assert transports == [("glm", False), ("kimi", True)]                  # one primary attempt, one fallback retry
    assert world.variables["permit_status"].value == "under review"
    assert world.actors[0].last_action["resolution"] == "partial"
    assert record["digest"].startswith("Fallback arbiter resolved the period.")


def test_arbiter_records_fallback_outcome_when_both_providers_fail(scripted_failover):
    llm, transports = scripted_failover(content_filter_error(), fallback_error=content_filter_error("assistant"))
    world = _world()
    world.start_round(1, _PERIOD)
    record = wu.run_world_round(world, 1, _PERIOD, _decisions(), [], llm=llm, rng=random.Random(0),
                                scenarios=world.scenarios)
    assert record["arbiter_status"] == "failed" and world.committed_round == 1
    [problem] = record["arbiter_problems"]
    assert problem.startswith(_FILTER_HEAD + "; fallback kimi: failed (BadRequestError (HTTP 400, provider code 1301, "
                              "content filter): Error code: 400")
    assert transports == [("glm", False), ("kimi", True)]                  # degrade-safe: no further attempts

    unconfigured, transports2 = scripted_failover(content_filter_error(), fallback_provider=None)
    world2 = _world()
    world2.start_round(1, _PERIOD)
    rec2 = wu.run_world_round(world2, 1, _PERIOD, _decisions(), [], llm=unconfigured, rng=random.Random(0),
                              scenarios=world2.scenarios)
    assert rec2["arbiter_status"] == "failed"
    assert rec2["arbiter_problems"][0].startswith(_FILTER_HEAD + "; fallback: not configured (LLM_FALLBACK_PROVIDER unset)")
    assert transports2 == [("glm", False)]


# ---------------------------------------------------------------------------
# units: a kind name is never a unit
# ---------------------------------------------------------------------------
def test_validate_blanks_kind_named_units_on_new_variables():
    world = _world()
    world.start_round(1, _PERIOD)
    update, _ = wu.validate_arbiter_update({"new_variables": [
        {"name": "Truce talks opened", "value": True, "unit": "boolean", "kind": "boolean"},
        {"name": "Deadline agreed", "value": "2027-03-10", "unit": "date", "kind": "date"},
        {"name": "Licence backlog", "value": 12, "unit": "numeric", "kind": "numeric"},
    ]}, world, world.scenarios)
    assert [(nv["kind"], nv["unit"]) for nv in update["new_variables"]] == [("boolean", ""), ("text", ""), ("numeric", "")]
    update2, _ = wu.validate_arbiter_update({"new_variables": [
        {"name": "Tariff floor", "value": 10, "unit": "%", "kind": "numeric"},
        {"name": "Status note", "value": "pending", "unit": "USD", "kind": "text"},      # text facts carry no unit
    ]}, world, world.scenarios)
    assert [(nv["kind"], nv["unit"]) for nv in update2["new_variables"]] == [("numeric", "%"), ("text", "")]


def test_briefs_never_print_a_kind_name_as_unit():
    world = _world()
    world.start_round(1, _PERIOD)
    llm = FakeLLMClient(json_responses=[{"narrative": "Talks opened.", "new_variables": [
        {"name": "Truce talks opened", "value": True, "unit": "boolean", "kind": "boolean"},
        {"name": "Deadline agreed", "value": "2027-03-10", "unit": "date", "kind": "date"}]}])
    record = wu.run_world_round(world, 1, _PERIOD, _decisions(), [], llm=llm, rng=random.Random(0),
                                scenarios=world.scenarios)
    assert record["arbiter_status"] == "applied"
    assert world.variables["truce_talks_opened"].unit == "" and world.variables["deadline_agreed"].unit == ""
    assert "- New: Truce talks opened = yes" in record["digest"]
    assert "- New: Deadline agreed = 2027-03-10" in record["digest"]
    brief = world.render_public_brief(upto_round=1, previous=record["snapshot_before"])
    assert "- Truce talks opened: yes" in brief and "- Deadline agreed: 2027-03-10" in brief
    world.start_round(2, {"label": "2026-Q4", "period_end": "2026-12-31"})
    prompt = wu.build_arbiter_prompt(world, 2, world.period, [], {}, world.scenarios)
    assert "Truce talks opened = yes [boolean]" in prompt and "Deadline agreed = 2027-03-10 [text]" in prompt
    for text in (record["digest"], brief, prompt):
        assert "yes boolean" not in text and "2027-03-10 date" not in text


def test_behaviour_metrics_count_moves_that_answer_last_period():
    """Old firms could use government policy IDs; C11 uses real firm moves to test response metrics."""
    world = _world()
    names = [a.name for a in world.actors.values()]
    world.start_round(1, {"label": "P1"})
    var = next(iter(world.variables.values()))
    var.set_value(99, round_num=1, source="arbiter", cause="shock")
    world.register_decisions(1, [{"agent_id": list(world.actors)[0], "option": {"id": "price_move", "label": "Raise prices", "kind": "economic", "cost": 1, "lag": 0},
                                 "targets": [names[1]], "magnitude": 0.5, "public_statement": "Imposed.", "status": "ok"}])
    world.commit_round(1)
    assert wu.behaviour_metrics(world, 1, [])["responsive_share"] is None          # no prior period
    world.start_round(2, {"label": "P2"})
    a0, a1 = list(world.actors)[:2]
    rows = [
        {"agent_id": a1, "actor_name": names[1], "option": {"id": "public_statement", "label": "Say", "kind": "communication", "cost": 1},
         "public_statement": f"After {var.name} jumped we answer {names[0]} in kind.", "private_rationale": "", "status": "ok"},
        {"agent_id": a0, "actor_name": names[0], "option": {"id": "invest_capex", "label": "Invest", "kind": "economic", "cost": 2, "lag": 2},
         "public_statement": "A new programme.", "private_rationale": "unrelated", "status": "ok"},
        {"agent_id": a0, "actor_name": names[0], "option": {"id": "hold_position", "label": "Hold", "kind": "wait", "cost": 0},
         "public_statement": "", "status": "ok"},
        {"agent_id": a1, "actor_name": names[1], "option": {"id": "accept:i1_1", "label": "Accept", "kind": "coalition", "cost": 1},
         "public_statement": "Accepted.", "status": "ok"},
    ]
    m = wu.behaviour_metrics(world, 2, rows)
    assert m == {"moves": 3, "responsive_moves": 2, "offers_answered": 1, "responsive_share": 0.667,
                 "signals_last_period": m["signals_last_period"],
                 "expectations_checked": 0, "expectations_reacted": 0}
    assert m["signals_last_period"] >= 2
    record = wu.run_world_round(world, 2, {"label": "P2"}, rows[:2], [], llm=None, rng=None, arbiter_enabled=False)
    assert record["behaviour"]["moves"] == 2 and record["behaviour"]["responsive_moves"] == 1
