"""Reflexivity: track records and expectations (pure, offline).

Before 2026-10-20 an actor's reputation was written (breaches, arbiter resolutions) but never shown
to anyone or given to the arbiter, and the reactions each actor said it expected were elicited and
discarded.  Now the world records each actor's conduct (commitments kept / lapsed / broken, how its
moves resolved) and shows it publicly and to the arbiter, stores each actor's expected reactions,
and shows the actor what the others actually did one period later.
"""

import json

from app.services import world_update as wu
from app.services.world_model import WorldModel


def _world():
    seed = {
        "question": "Will the port strike end before Q4?",
        "scenarios": ["Deal", "Long strike"],
        "state_variables": [{"name": "Containers handled", "value": 50000, "unit": "TEU", "provenance": "official"}],
        "actors": [
            {"agent_id": 0, "name": "Port Authority", "agency_class": "regulator_agency"},
            {"agent_id": 1, "name": "Dockworkers Union", "agency_class": "labor_union"},
            {"agent_id": 2, "name": "Shipping Alliance", "agency_class": "industry_coalition"},
        ],
        "settings": {"max_change_ratio": 0.5},
    }
    cfgs = [{"agent_id": i, "entity_name": n} for i, n in
            enumerate(["Port Authority", "Dockworkers Union", "Shipping Alliance"])]
    return WorldModel.from_seed(seed, cfgs)


def _move(agent_id, name, option_id="public_statement", kind="communication", *, targets=(), statement="",
          commitment=None, expected=(), status="ok"):
    return {"agent_id": agent_id, "actor_name": name,
            "option": {"id": option_id, "label": option_id.replace("_", " "), "kind": kind, "cost": 1, "lag": 0},
            "targets": list(targets), "magnitude": 0.7, "public_statement": statement, "commitment": commitment,
            "expected_reactions": [{"actor": a, "reaction": r} for a, r in expected], "status": status}


def _hold(agent_id, name):
    return _move(agent_id, name, "hold_position", "wait")


def _two_promises_one_kept(world):
    """Union promises twice in round 1; acts when they fall due (kept), holds the next time (lapsed)."""
    world.start_round(1, None)
    world.register_decisions(1, [_move(1, "Dockworkers Union", commitment={"description": "Return to work", "due_periods": 1})])
    world.start_round(2, None)
    world.register_decisions(2, [_move(1, "Dockworkers Union", commitment={"description": "Hold a ballot", "due_periods": 1})])
    world.start_round(3, None)
    world.lapse_overdue_commitments(3)
    world.register_decisions(3, [_hold(1, "Dockworkers Union")])
    world.start_round(4, None)
    world.lapse_overdue_commitments(4)


def test_track_record_counts_kept_lapsed_and_broken_commitments():
    world = _world()
    _two_promises_one_kept(world)
    rec = world.track_record(1)
    assert (rec["kept"], rec["lapsed"], rec["broken"], rec["resolved"]) == (1, 1, 0, 2)
    assert rec["reliability"] == 0.5
    assert world.track_record_text(1) == "kept 1 of 2 commitments (1 lapsed)"
    assert world.track_record_text(0) == ""                       # nothing resolved yet: no line
    assert world.track_record(99) == {}


def test_breaking_an_agreement_shows_in_the_public_track_record_first():
    world = _world()
    world.start_round(1, None)
    world.register_decisions(1, [_move(0, "Port Authority", "open_talks", "coalition", targets=["Dockworkers Union"],
                                       statement="Talks on overtime pay.")])
    (offer_id,) = list(world.interactions)
    world.start_round(2, None)
    world.register_decisions(2, [_move(1, "Dockworkers Union", f"accept:{offer_id}", "coalition")])
    world.start_round(3, None)
    world.register_decisions(3, [_move(1, "Dockworkers Union", "break_alliance", "coalition",
                                       targets=["Port Authority"], statement="We walk away.")])
    world.apply_arbiter_update(3, {"action_resolutions": [{"actor": "Shipping Alliance", "outcome": "blocked"},
                                                          {"actor": "Dockworkers Union", "outcome": "success"}]})
    union = world.track_record(1)
    assert union["broken"] == 1 and union["outcomes"] == {"success": 1}
    brief = world.render_public_brief(upto_round=3)
    section = brief.split("## Track records\n", 1)[1]
    assert section.splitlines()[0].startswith("- Dockworkers Union: kept 0 of 1 commitments (1 broken)")
    assert "- Shipping Alliance: moves 1 blocked" in section
    assert "%" not in section                                     # herding guard: no shares anywhere near it
    assert "Your track record as others see it: kept 0 of 1 commitments (1 broken)" in \
        world.render_private_brief(1, upto_round=3)


def test_the_arbiter_weighs_moves_by_track_record():
    world = _world()
    _two_promises_one_kept(world)
    rows = [_move(1, "Dockworkers Union", "strike_action", "coercive", statement="Strike extended.")]
    world.register_decisions(4, rows)
    prompt = wu.build_arbiter_prompt(world, 4, None, rows, {}, ["Deal", "Long strike"])
    assert "Track record: kept 1 of 2 commitments (1 lapsed)." in prompt
    assert "weigh each actor's word by its track record" in prompt
    assert "self-fulfilling" in prompt and "self-defeating" in prompt


def test_expectations_are_stored_and_compared_one_period_later():
    world = _world()
    world.start_round(1, None)
    world.register_decisions(1, [
        _move(0, "Port Authority", "issue_ruling", "legal", targets=["Dockworkers Union"],
              expected=[("Dockworkers Union", "back down and return to work"),
                        ("Nobody Corp", "ignored: not in the cast"),
                        ("Port Authority", "ignored: about itself")]),
        _move(2, "Shipping Alliance", expected=[("Port Authority", "fine the union")]),
    ])
    assert world.actors[0].expectations == [{"round": 1, "about": "Dockworkers Union",
                                             "reaction": "back down and return to work"}]
    world.start_round(2, None)
    world.register_decisions(2, [
        _move(1, "Dockworkers Union", "strike_action", "coercive", targets=["Port Authority"],
              statement="We escalate the strike."),
        _hold(0, "Port Authority"),
    ])
    checks = world.expectation_checks(0, 2)
    assert checks == [{"made_round": 1, "about": "Dockworkers Union", "expected": "back down and return to work",
                       "actual": "strike action → Port Authority", "reacted": True, "aimed_at_you": True}]
    note = world.render_private_brief(0, upto_round=2)
    assert ('· Dockworkers Union: you expected "back down and return to work"; '
            "it did: strike action → Port Authority") in note
    alliance = world.expectation_checks(2, 2)[0]
    assert alliance["reacted"] is False and alliance["actual"] == "Port Authority holds position"
    metrics = wu.behaviour_metrics(world, 2, [])
    assert (metrics["expectations_checked"], metrics["expectations_reacted"]) == (2, 1)
    assert world.expectation_checks(0, 3) == []                  # only the period right after counts


def test_the_arbiter_sees_the_expectations_in_play():
    world = _world()
    world.start_round(1, None)
    rows = [_move(0, "Port Authority", "issue_ruling", "legal", targets=["Dockworkers Union"],
                  expected=[("Dockworkers Union", "return to work")])]
    world.register_decisions(1, rows)
    prompt = wu.build_arbiter_prompt(world, 1, None, rows, {}, [])
    assert "## Expectations in play" in prompt
    assert "- Port Authority expects Dockworkers Union: return to work" in prompt


def test_typed_non_decisions_record_no_expectations():
    world = _world()
    world.start_round(1, None)
    world.register_decisions(1, [_move(0, "Port Authority", expected=[("Dockworkers Union", "x")], status="failed")])
    assert world.actors[0].expectations == []


def test_records_and_expectations_survive_a_json_round_trip():
    world = _world()
    _two_promises_one_kept(world)
    world.actors[0].outcomes = {"partial": 2}
    world.actors[0].expectations = [{"round": 3, "about": "Shipping Alliance", "reaction": "reroute"}]
    data = json.loads(json.dumps(world.to_dict()))
    actor = next(a for a in data["actors"] if a["agent_id"] == 1)
    assert actor["track_record"]["lapsed"] == 1                 # derived, for the API and the panel
    again = WorldModel.from_dict(data)
    assert again.track_record_text(1) == world.track_record_text(1)
    assert again.actors[0].outcomes == {"partial": 2}
    assert again.actors[0].expectations == world.actors[0].expectations
    assert again.to_dict() == world.to_dict()
