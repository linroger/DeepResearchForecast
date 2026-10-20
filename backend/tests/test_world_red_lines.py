"""Red lines and trends (pure, offline).

Before 2026-10-20 an actor's documented red lines were shown only to that actor; the arbiter never
saw them and nothing recorded a move that crossed one, so escalation after a red line was crossed
was left to chance.  Facts also showed only last period's change, so momentum was invisible.  Now
the arbiter sees the red lines at stake and may report a crossing; a crossing that holds up (the
crossing actor moved this period, the text matches the actor's own red line) becomes a ``red_line``
event aimed at that actor, pushes the relationship apart, appears in the briefs and gives the actor
response options.  Facts that moved the same way for several periods are marked as trends.
"""

from app.services import world_update as wu
from app.services.agent_decision import build_option_menu
from app.services.world_model import WorldModel


def _world():
    seed = {
        "question": "Will the strait stay open to commercial shipping through 2027?",
        "scenarios": ["Open", "Closed"],
        "state_variables": [{"name": "Tanker insurance premium", "value": "0.2%", "provenance": "research"}],
        "actors": [
            {"agent_id": 0, "name": "Coastal State", "agency_class": "sovereign_government",
             "red_lines": ["No foreign warships inside territorial waters", "No sanctions on oil exports"]},
            {"agent_id": 1, "name": "Naval Coalition", "agency_class": "international_org"},
            {"agent_id": 2, "name": "Shipping Insurers", "agency_class": "financial_institution"},
        ],
        "settings": {"max_change_ratio": 0.5},
    }
    cfgs = [{"agent_id": i, "entity_name": n} for i, n in enumerate(["Coastal State", "Naval Coalition", "Shipping Insurers"])]
    return WorldModel.from_seed(seed, cfgs)


def _move(agent_id, name, option_id, kind, targets=(), statement=""):
    return {"agent_id": agent_id, "actor_name": name,
            "option": {"id": option_id, "label": option_id.replace("_", " "), "kind": kind, "cost": 1, "lag": 0},
            "targets": list(targets), "magnitude": 0.8, "public_statement": statement, "status": "ok"}


def _patrol(world, round_num=1):
    world.start_round(round_num, {"label": f"P{round_num}"})
    rows = [_move(1, "Naval Coalition", "security_action", "coercive", ["Coastal State"],
                  "Escort missions will enter the strait's territorial waters.")]
    world.register_decisions(round_num, rows)
    return rows


def test_the_arbiter_sees_the_red_lines_at_stake_and_the_contract():
    world = _world()
    rows = _patrol(world)
    prompt = wu.build_arbiter_prompt(world, 1, None, rows, {}, ["Open", "Closed"])
    assert "## Red lines at stake" in prompt
    assert "- Coastal State: No foreign warships inside territorial waters; No sanctions on oil exports" in prompt
    assert '"red_line_crossings"' in prompt


def test_a_crossing_that_holds_up_becomes_an_event_aimed_at_the_actor():
    world = _world()
    _patrol(world)
    update, problems = wu.validate_arbiter_update({"red_line_crossings": [
        {"actor": "Coastal State", "by": "Naval Coalition", "red_line": "foreign warships inside territorial waters",
         "rationale": "escorts entered the 12-mile zone"}]}, world)
    assert problems == []
    assert update["red_line_crossings"][0]["red_line"] == "No foreign warships inside territorial waters"
    before = world._relationship_between(0, 1).polarity     # the patrol itself already pushed it apart
    summary = world.apply_arbiter_update(1, update)
    assert summary["red_lines_crossed"] == [{"actor": "Coastal State", "by": "Naval Coalition",
                                             "red_line": "No foreign warships inside territorial waters"}]
    assert world._relationship_between(0, 1).polarity < before
    (event,) = world.events_in_round(1, ("red_line",))
    assert event.description.startswith("Naval Coalition crossed Coastal State's red line: No foreign warships")
    assert event.targets == ["Coastal State"]
    assert "crossed Coastal State's red line" in world.render_public_brief(upto_round=1)
    assert "crossed Coastal State's red line" in world.render_private_brief(0, upto_round=1)
    menu = build_option_menu(world.actors[0], world, 2)
    responses = [o for o in menu if o["id"].startswith("respond_")]
    assert responses and responses[0]["why"] == "Naval Coalition crossed your red line last period"
    assert responses[0]["suggested_targets"] == ["Naval Coalition"]


def test_crossings_that_do_not_hold_up_are_dropped():
    world = _world()
    _patrol(world)
    update, problems = wu.validate_arbiter_update({"red_line_crossings": [
        {"actor": "Coastal State", "by": "Naval Coalition", "red_line": "no tariffs on fish"},       # not its red line
        {"actor": "Naval Coalition", "by": "Coastal State", "red_line": "anything"},                # no red lines
        {"actor": "Coastal State", "by": "Coastal State", "red_line": "No sanctions on oil exports"},  # itself
    ]}, world)
    assert update["red_line_crossings"] == [] and len(problems) == 3
    # validated but the named actor made no move this period: the kernel records nothing
    assert world.cross_red_line(1, "Coastal State", "Shipping Insurers", "No sanctions on oil exports") is None
    assert world.events_in_round(1, ("red_line",)) == []


def test_red_line_matching_is_about_the_actors_own_text():
    world = _world()
    assert world.match_red_line(0, "sanctions on its oil exports") == "No sanctions on oil exports"
    assert world.match_red_line(0, "NO FOREIGN WARSHIPS INSIDE TERRITORIAL WATERS") == \
        "No foreign warships inside territorial waters"
    assert world.match_red_line(0, "warships") is None            # too little of the red line repeated
    assert world.match_red_line(1, "No sanctions on oil exports") is None


def test_trends_are_marked_after_two_periods_the_same_way():
    world = _world()
    var = world.variables["tanker_insurance_premium"]
    for rnd, value in ((1, 0.3), (2, 0.45), (3, 0.6)):
        world.start_round(rnd, {"label": f"P{rnd}"})
        world.apply_arbiter_update(rnd, {"variable_changes": [{"variable_id": var.id, "new_value": value}]})
        world.commit_round(rnd)
    assert var.trend(3) == ("rising", 3)
    assert var.trend(2) == ("rising", 2)
    brief = world.render_public_brief(upto_round=3)
    assert "- Tanker insurance premium: 0.6% (rising 3 periods running)" in brief
    prompt = wu.build_arbiter_prompt(world, 4, None, [], {}, [])
    assert "(path: 0.2% → 0.3% → 0.45% → 0.6%)" in prompt         # the last four recorded values
    world.start_round(4, {"label": "P4"})
    world.apply_arbiter_update(4, {"variable_changes": [{"variable_id": var.id, "new_value": 0.5}]})
    assert var.trend(4) == ("falling", 1)
    assert "periods running" not in world.render_public_brief(upto_round=4)
    world.start_round(5, None)
    assert var.trend(5) == ("", 0)                                # no change recorded in period 5
