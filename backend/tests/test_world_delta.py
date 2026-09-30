"""Tests for the qualitative world-delta digest (spec §4 / §7 item 5).

Pins: determinism, section order, char_cap truncation, the herding-guard regression
(NO percentage / numeric-share tokens ever in agent-facing output), and the
""-on-error / ""-on-empty contract.
"""

import re

from app.services.world_delta import build_world_delta


def _events():
    return [
        {"date": "2027-03-15", "content": "Regulator opens formal inquiry"},
        {"date": "2027-03-20", "content": "Flagship model ships"},
    ]


def _actions():
    return [
        {"actor_name": "Alice", "influence_weight": 0.9, "content": "We commit to the merger."},
        {"actor_name": "Bob", "influence_weight": 0.4, "content": "We will wait and see."},
        {"actor_name": "Carol", "influence_weight": 0.7, "content": "Alliance announced with Dana."},
    ]


# ------------------------------------------------------------------ determinism
def test_deterministic_and_section_order():
    a = build_world_delta(_actions(), _events(),
                          leader_move={"leader": "ScenarioA", "direction": "up"})
    b = build_world_delta(_actions(), _events(),
                          leader_move={"leader": "ScenarioA", "direction": "up"})
    assert a == b and a
    lines = a.split("\n")
    # 事件区在前（[date] content），其后按 influence_weight 降序的有机贴，最后 momentum
    assert lines[0] == "[2027-03-15] Regulator opens formal inquiry"
    assert lines[1] == "[2027-03-20] Flagship model ships"
    assert lines[2].startswith("Alice:")
    assert lines[3].startswith("Carol:")
    assert lines[4].startswith("Bob:")
    assert lines[-1] == "Momentum: ScenarioA strengthened this period."


def test_momentum_directions_and_invalid():
    down = build_world_delta([], _events(), leader_move={"leader": "X", "direction": "down"})
    assert "Momentum: X weakened this period." in down
    flat = build_world_delta([], _events(), leader_move={"leader": "X", "direction": "flat"})
    assert "Momentum: X held this period." in flat
    bad = build_world_delta([], _events(), leader_move={"leader": "X", "direction": "sideways"})
    assert "Momentum" not in bad


def test_top_k_limits_posts():
    actions = [{"actor_name": f"a{i}", "influence_weight": i / 10.0, "content": f"post {i}"}
               for i in range(8)]
    out = build_world_delta(actions, [], top_k=3)
    assert out.count("\n") == 2                      # exactly 3 lines
    assert out.split("\n")[0].startswith("a7:")      # highest weight first


def test_content_clipped_to_140_chars():
    long = "x" * 500
    out = build_world_delta([{"actor_name": "A", "influence_weight": 1.0, "content": long}], [])
    assert out == "A: " + "x" * 140


# --------------------------------------------------------------------- char cap
def test_char_cap_truncation():
    actions = [{"actor_name": f"agent{i}", "influence_weight": 1.0, "content": "y" * 140}
               for i in range(5)]
    out = build_world_delta(actions, _events(), char_cap=200)
    assert len(out) <= 200
    full = build_world_delta(actions, _events(), char_cap=100000)
    assert full.startswith(out)                      # truncation is a plain prefix cut


# ------------------------------------- herding-guard regression (no share tokens)
def test_no_percentage_or_share_tokens_in_output():
    """Even when leader_move smuggles numeric shares, none reach agent-facing text."""
    leader_move = {"leader": "ScenarioA", "direction": "up",
                   "share": 0.62, "leader_share": 0.62, "delta": 0.07, "pct": "62%"}
    actions = [{"actor_name": "Alice", "influence_weight": 0.9,
                "content": "We commit fully to the plan."}]
    events = [{"date": "2027-03-15", "content": "Regulator opens formal inquiry"}]
    out = build_world_delta(actions, events, leader_move=leader_move)
    assert out
    assert "%" not in out
    assert not re.search(r"\d+(\.\d+)?\s*%", out)
    assert not re.search(r"(?<!\d)0\.\d+", out)      # no float-style shares like 0.62
    # momentum 行必须是纯定性模板，不含任何数字
    momentum = [ln for ln in out.split("\n") if ln.startswith("Momentum")]
    assert momentum == ["Momentum: ScenarioA strengthened this period."]
    assert not re.search(r"\d", momentum[0])


# ------------------------------------------------------------- empty / error → ""
def test_empty_inputs_return_empty_string():
    assert build_world_delta([], []) == ""
    assert build_world_delta(None, None) == ""
    assert build_world_delta([], [], leader_move={}) == ""
    assert build_world_delta([], [], leader_move={"leader": "", "direction": "up"}) == ""


def test_garbage_inputs_return_empty_string():
    assert build_world_delta(object(), 42) == ""                      # non-iterables → ""
    assert build_world_delta([1, "x", None], [3.5, None]) == ""       # non-dict items skipped
    assert build_world_delta([{"content": ""}], [{"content": None}]) == ""


def test_event_date_prefix_not_duplicated():
    ev = [{"date": "2027-03-15", "content": "[2027-03-15] Already prefixed event"}]
    out = build_world_delta([], ev)
    assert out == "[2027-03-15] Already prefixed event"


# ================================================== SIM-6: sectioned caps (V2)
_EVENTS_H = "### Scheduled events last period"
_POSTS_H = "### Most-influential actor posts last period (peer claims, unverified)"


def test_sectioned_emits_both_sections_then_momentum():
    out = build_world_delta(_actions(), _events(),
                            leader_move={"leader": "ScenarioA", "direction": "up"},
                            sectioned=True)
    assert out.split("\n") == [
        _EVENTS_H,
        "[2027-03-15] Regulator opens formal inquiry",
        "[2027-03-20] Flagship model ships",
        _POSTS_H,
        "Alice: We commit to the merger.",
        "Carol: Alliance announced with Dana.",
        "Bob: We will wait and see.",
        "Momentum: ScenarioA strengthened this period.",
    ]
    # the default arguments keep the legacy flat digest
    assert build_world_delta(_actions(), _events()) == build_world_delta(
        _actions(), _events(), sectioned=False)
    assert "###" not in build_world_delta(_actions(), _events())


def test_sectioned_skips_empty_sections_and_stays_empty_when_quiet():
    only_posts = build_world_delta(_actions(), [], sectioned=True)
    assert only_posts.startswith(_POSTS_H) and _EVENTS_H not in only_posts
    only_events = build_world_delta([], _events(), sectioned=True)
    assert only_events.startswith(_EVENTS_H) and _POSTS_H not in only_events
    assert build_world_delta([], [], sectioned=True) == ""
    assert build_world_delta(object(), 42, sectioned=True) == ""


def test_sectioned_labels_scenario_injections():
    events = [{"date": "2027-04-01", "content": "Export ban extended",
               "is_scenario_injection": True},
              {"date": "2027-04-02", "content": "[2027-04-02] Research event"}]
    out = build_world_delta([], events, sectioned=True).split("\n")
    assert out[1] == "SCENARIO ASSUMPTION (what-if, not observed): [2027-04-01] Export ban extended"
    assert out[2] == "[2027-04-02] Research event"
    legacy = build_world_delta([], events)
    assert "SCENARIO ASSUMPTION" not in legacy       # legacy digest unchanged


def test_sectioned_oversized_events_cannot_starve_posts_and_vice_versa():
    big_events = [{"date": f"2027-03-{10 + i}", "content": "E" * 300} for i in range(6)]
    big_posts = [{"actor_name": f"agent{i}", "influence_weight": 1.0 - i / 10,
                  "content": "P" * 140} for i in range(5)]
    lead = {"leader": "ScenarioA", "direction": "down"}
    out = build_world_delta(big_posts, big_events, leader_move=lead, sectioned=True,
                            event_char_cap=600, post_char_cap=400)
    lines = out.split("\n")
    ev = lines[lines.index(_EVENTS_H) + 1:lines.index(_POSTS_H)]
    posts = lines[lines.index(_POSTS_H) + 1:-1]
    # each section keeps whole lines within its own cap and names what it dropped
    assert all(line.endswith("E" * 300) for line in ev[:-1]) and len(ev) - 1 == 1
    assert ev[-1] == "(+5 more omitted)"
    assert len("\n".join(ev)) <= 600
    assert all(line.startswith("agent") and line.endswith("P" * 140) for line in posts[:-1])
    assert posts[-1] == f"(+{5 - (len(posts) - 1)} more omitted)"
    assert len("\n".join(posts)) <= 400 and len(posts) - 1 >= 1
    # the momentum line survives both overflows and stays last
    assert lines[-1] == "Momentum: ScenarioA weakened this period."
    # a single event longer than its cap is dropped whole, with the marker, posts intact
    one = build_world_delta(big_posts[:1], [{"date": "2027-03-10", "content": "E" * 900}],
                            sectioned=True, event_char_cap=600)
    assert one.split("\n")[:3] == [_EVENTS_H, "(+1 more omitted)", _POSTS_H]


def test_sectioned_marks_clipped_posts():
    out = build_world_delta([{"actor_name": "A", "influence_weight": 1.0, "content": "x" * 500}],
                            [], sectioned=True)
    assert out == _POSTS_H + "\nA: " + "x" * 140 + "…"
    short = build_world_delta([{"actor_name": "A", "content": "y" * 140}], [], sectioned=True)
    assert short.endswith("A: " + "y" * 140)


def test_sectioned_herding_guard_no_share_tokens():
    leader_move = {"leader": "ScenarioA", "direction": "up",
                   "share": 0.62, "leader_share": 0.62, "delta": 0.07, "pct": "62%"}
    events = [{"date": "2027-03-15", "content": "E" * 700}]
    posts = [{"actor_name": f"agent{i}", "influence_weight": 1.0, "content": "P" * 140}
             for i in range(8)]
    out = build_world_delta(posts, events, leader_move=leader_move, sectioned=True,
                            event_char_cap=100, post_char_cap=300)
    assert "%" not in out
    assert not re.search(r"(?<!\d)0\.\d+", out)
    assert "62" not in out and "0.07" not in out
    momentum = [ln for ln in out.split("\n") if ln.startswith("Momentum")]
    assert momentum == ["Momentum: ScenarioA strengthened this period."]
    assert out.split("\n")[-1] == momentum[0]


def test_fit_whole_lines():
    from app.services.world_delta import fit_whole_lines

    def marker(n):
        return f"(+{n} more omitted)"

    lines = ["a" * 10, "b" * 10, "c" * 10]
    assert fit_whole_lines(lines, 32, marker) == (lines, 0)           # fits exactly
    kept, omitted = fit_whole_lines(lines, 31, marker)
    assert (kept, omitted) == (lines[:1], 2)                          # a + "\n" + marker
    assert len("\n".join(kept + [marker(omitted)])) <= 31
    assert fit_whole_lines(lines, 5, marker) == ([], 3)
    assert fit_whole_lines([], 0, marker) == ([], 0)
