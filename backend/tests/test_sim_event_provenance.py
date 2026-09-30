"""SIM-5 (C42): the pure provenance helpers shared by the sim child and the report tools.

Pins the label strings, their idempotence, that the consumers' matcher set equals
exactly what fire_scheduled_events posts, and the injected-row truth table.
"""

import asyncio
import os
import sys

import pytest

_BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SCRIPTS = os.path.join(_BACKEND, "scripts")
for _p in (_BACKEND, _SCRIPTS):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import run_parallel_simulation as rps  # noqa: E402

from app.services.sim_event_provenance import (  # noqa: E402
    EVENT_AUTHOR_RESEARCH,
    EVENT_AUTHOR_SCENARIO,
    EVENT_PROVENANCE_RESEARCH,
    EVENT_PROVENANCE_SCENARIO,
    classify_event,
    event_author_label,
    event_post_contents,
    is_injected_row,
    label_event_post,
)

RESEARCH_PREFIX = "[WORLD EVENT · scheduled on the research timeline · not a statement by any actor] "
SCENARIO_PREFIX = "[SCENARIO ASSUMPTION · what-if, not observed] "


def test_classify_event_uses_only_the_scenario_flag():
    assert classify_event({"content": "x", "poster_agent_id": 1}) == EVENT_PROVENANCE_RESEARCH
    assert classify_event({"content": "x", "poster_name": "IBM"}) == EVENT_PROVENANCE_RESEARCH
    assert classify_event({"is_scenario_injection": True}) == EVENT_PROVENANCE_SCENARIO
    assert classify_event({"is_scenario_injection": False}) == EVENT_PROVENANCE_RESEARCH
    assert classify_event(None) == EVENT_PROVENANCE_RESEARCH
    assert EVENT_PROVENANCE_RESEARCH == "research_timeline"
    assert EVENT_PROVENANCE_SCENARIO == "scenario_assumption"


def test_label_event_post_prefixes_and_is_idempotent():
    research = label_event_post("BIS adds firms to the Entity List.", EVENT_PROVENANCE_RESEARCH)
    assert research == RESEARCH_PREFIX + "BIS adds firms to the Entity List."
    scenario = label_event_post("Taiwan blockade begins.", EVENT_PROVENANCE_SCENARIO)
    assert scenario == SCENARIO_PREFIX + "Taiwan blockade begins."
    # never double-prefixes, whichever label the text already carries
    assert label_event_post(research, EVENT_PROVENANCE_RESEARCH) == research
    assert label_event_post(research, EVENT_PROVENANCE_SCENARIO) == research
    assert label_event_post(scenario, EVENT_PROVENANCE_RESEARCH) == scenario
    # unknown provenance still labels the post as non-actor content
    assert label_event_post("x", "mystery").startswith(RESEARCH_PREFIX)


def test_event_author_label_follows_the_post_label():
    assert event_author_label(RESEARCH_PREFIX + "x") == EVENT_AUTHOR_RESEARCH
    assert event_author_label(SCENARIO_PREFIX + "x") == EVENT_AUTHOR_SCENARIO
    assert EVENT_AUTHOR_RESEARCH.startswith("SCHEDULED WORLD EVENT (research timeline")


def test_event_post_contents_skips_what_is_never_posted():
    events = [
        {"round": 1, "content": "  Event A  ", "poster_agent_id": 0},
        {"round": 2, "content": "Event B", "poster_agent_id": 1, "is_scenario_injection": True},
        {"round": 2, "content": "No poster", "poster_agent_id": None},
        {"round": 3, "content": "", "poster_agent_id": 2},
        "not-a-dict",
    ]
    assert event_post_contents(events, labelled=False) == {"Event A", "Event B"}
    assert event_post_contents(events, labelled=True) == {
        RESEARCH_PREFIX + "  Event A",
        SCENARIO_PREFIX + "Event B",
    }
    assert event_post_contents(None, labelled=True) == set()


class _Graph:
    def get_agent(self, aid):
        return f"agent-{aid}"


class _Env:
    def __init__(self):
        self.agent_graph = _Graph()
        self.steps = []

    async def step(self, actions):
        self.steps.append(actions)


@pytest.mark.parametrize("flag, labelled", [("true", True), ("false", False)])
def test_event_post_contents_equals_what_fire_scheduled_events_posts(monkeypatch, flag, labelled):
    monkeypatch.setenv("SIM_EVENT_PROVENANCE", flag)
    events = [
        {"round": 0, "content": "Event A ", "poster_agent_id": 0},
        {"round": 0, "content": "Event B", "poster_agent_id": 0, "is_scenario_injection": True},
        {"round": 0, "content": "Event C", "poster_agent_id": 1},
    ]
    env = _Env()
    fired = asyncio.run(rps.fire_scheduled_events(
        env, {"scheduled_events": events}, 0, {}, None, lambda _m: None))
    assert fired == 3
    posted = {a.action_args["content"].strip() for acts in env.steps[0].values() for a in acts}
    assert posted == event_post_contents(events, labelled=labelled)


@pytest.mark.parametrize("args, round_num, expected", [
    ({}, 0, True),                                   # round 0 seeding
    ({"content": "seed"}, -1, True),
    ({"content": "x"}, None, True),                  # unreadable round is not provably organic
    ({"content": "x"}, "abc", True),
    ({"content": "x", "is_scheduled_event": True}, 3, True),
    ({"is_seed_action": True}, 2, True),
    ({"post_id": 4, "is_engagement_sample": True}, 5, True),
    ({"content": "organic"}, 1, False),
    ({}, 7, False),
    (None, 2, False),
    ({"is_scheduled_event": False}, 2, False),
])
def test_is_injected_row_truth_table(args, round_num, expected):
    assert is_injected_row(args, round_num) is expected
