"""SIM-6 (P23): the pure per-period context renderer (app.services.sim_period_context).

Pins: expected-event / scenario-assumption labels without a doubled date prefix, the
REPORT-6 markers moved here verbatim (never "first period" after round 0), the stale
"covers" line, the per-agent catch-up of missed scheduled events (window, newest
first, whole-line cap with an omission marker, determinism, resume behaviour) and the
capped reaction-step context.  Offline and deterministic.
"""

import os

import pytest

from app.services import sim_period_context as spc
from app.services.sim_period_context import (
    EventCatchUp,
    compact_period_context,
    render_delta_lines,
    render_event_lines,
)

_BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

_RESEARCH = {"round": 1, "date": "2026-11-05", "content": "[2026-11-05] 事件A发生"}
_SCENARIO = {"round": 1, "date": "2026-12-01", "content": "Export ban extended",
             "is_scenario_injection": True}


# ------------------------------------------------------------------ knobs / markers
def test_knobs_default_on_and_documented():
    from app.config import Config
    assert Config.SIM_PERIOD_CONTEXT_V2 is True
    assert Config.SIM_EVENT_CATCHUP_MAX_CHARS == 1200
    with open(os.path.join(os.path.dirname(_BACKEND), ".env.example"), encoding="utf-8") as f:
        text = f.read()
    assert "# SIM_PERIOD_CONTEXT_V2=true" in text
    assert "# SIM_EVENT_CATCHUP_MAX_CHARS=1200" in text


def test_report6_markers_moved_verbatim():
    """REPORT-6's marker strings, byte-identical to the runner's former constants."""
    assert spc.WORLD_CLOCK_NO_EVENTS == (
        "(no dated research event is scheduled for this period — "
        "this does not mean nothing happened in the world)")
    assert spc.WORLD_CLOCK_FIRST_PERIOD == (
        "(first period — nothing has happened in this simulation yet)")
    assert spc.WORLD_CLOCK_QUIET_PERIOD == (
        "(no scheduled event and no notable public move was recorded last period)")
    assert spc.WORLD_CLOCK_SUMMARY_UNAVAILABLE == (
        "(last period's summary is unavailable in this run — "
        "this is not evidence that nothing happened)")
    assert spc.WORLD_CLOCK_SUMMARY_NOT_PRODUCED == (
        "(period summaries are not produced in this run — "
        "this is not evidence that nothing happened)")


def test_event_headings_never_claim_confirmation():
    assert spc.SCHEDULED_EVENTS_HEADING_V2 == (
        "## SCHEDULED EVENTS THIS PERIOD (research timeline — expected; "
        "outcomes not known in advance)")
    for heading in (spc.SCHEDULED_EVENTS_HEADING_V2, spc.CATCHUP_HEADING,
                    spc.THIS_PERIOD_HEADING):
        assert "CONFIRMED" not in heading.upper()


# ------------------------------------------------------------- render_event_lines
def test_render_event_lines_labels_scenarios_and_never_doubles_the_date():
    lines = render_event_lines([_RESEARCH, _SCENARIO], markers=True)
    assert lines == [
        "[2026-11-05] 事件A发生",  # already dated → no second "[date] "
        "SCENARIO ASSUMPTION (what-if, not observed): [2026-12-01] Export ban extended",
    ]
    assert render_event_lines([{"date": "2026-11-05", "content": "Plain"}],
                              markers=True) == ["[2026-11-05] Plain"]
    assert render_event_lines([{"content": "Undated"}], markers=True) == ["Undated"]
    # idempotent: an already labelled scenario line is not labelled again
    relabelled = dict(_SCENARIO, content=lines[1])
    assert render_event_lines([relabelled], markers=True) == [lines[1]]
    # legacy rendering (V2 off) keeps the scenario text unlabelled
    assert render_event_lines([_SCENARIO], markers=True, scenario_labels=False) == [
        "[2026-12-01] Export ban extended"]


def test_render_event_lines_placeholders_and_garbage():
    assert render_event_lines([], markers=True) == [spc.WORLD_CLOCK_NO_EVENTS]
    assert render_event_lines(None, markers=False) == ["(none)"]
    junk = [None, "x", 3, {"content": ""}, {"content": "   ", "date": "2026-01-01"}]
    assert render_event_lines(junk, markers=False) == ["(none)"]
    assert render_event_lines(42, markers=True) == [spc.WORLD_CLOCK_NO_EVENTS]


# ------------------------------------------------------------- render_delta_lines
def test_render_delta_lines_markers_on():
    def rd(text, state, rnd, stale=""):
        return render_delta_lines(text, state, round_num=rnd, stale_label=stale, markers=True)

    assert rd("", "not_stepped", 0) == [spc.WORLD_CLOCK_FIRST_PERIOD]
    assert rd("Actor1: deal\nMomentum: A held this period.", "stepped", 2) == [
        "Actor1: deal", "Momentum: A held this period."]
    assert rd("  Actor1: deal ", "stepped", 2) == ["Actor1: deal"]
    assert rd("", "quiet", 2) == [spc.WORLD_CLOCK_QUIET_PERIOD]
    for state in ("failed", "not_stepped", "stepped", None, "garbage"):
        assert rd("", state, 2) == [spc.WORLD_CLOCK_SUMMARY_UNAVAILABLE]
    assert rd("", "no_inband", 2) == [spc.WORLD_CLOCK_SUMMARY_NOT_PRODUCED]
    # a digest from an older period says which period it covers
    assert rd("Actor1: deal", "stepped", 3, stale="2026-Q3") == [
        "(latest available digest covers 2026-Q3; no digest of the most recent period "
        "is available)", "Actor1: deal"]
    # the stale line annotates a digest; it never replaces a placeholder
    assert rd("", "failed", 3, stale="2026-Q3") == [spc.WORLD_CLOCK_SUMMARY_UNAVAILABLE]


def test_render_delta_lines_never_first_period_after_round_zero():
    for rnd in (1, 2, 7):
        for text in ("", "   ", "Actor1: deal"):
            for state in ("not_stepped", "stepped", "quiet", "failed", "no_inband", None):
                for stale in ("", "2026-Q3"):
                    out = "\n".join(render_delta_lines(text, state, round_num=rnd,
                                                       stale_label=stale, markers=True))
                    assert "first period" not in out
                    # the discarded draft placeholders never surface
                    assert "(period digest unavailable)" not in out
                    assert "(no public moves" not in out


def test_render_delta_lines_markers_off_is_legacy():
    for rnd in (0, 1, 2):
        for state in ("not_stepped", "stepped", "quiet", "failed", "no_inband", None):
            assert render_delta_lines("", state, round_num=rnd, markers=False) == [
                "(first period)"]
            assert render_delta_lines(" a\nb ", state, round_num=rnd, markers=False) == [
                "a", "b"]
            # the stale line is not a placeholder: SIM_PERIOD_CONTEXT_V2 (the caller passes
            # stale_label only then) governs it whatever SIM_ABSENCE_MARKERS says
            assert render_delta_lines(" a\nb ", state, round_num=rnd, stale_label="2026-Q3",
                                      markers=False) == [
                "(latest available digest covers 2026-Q3; no digest of the most recent period "
                "is available)", "a", "b"]
            assert render_delta_lines("", state, round_num=rnd, stale_label="2026-Q3",
                                      markers=False) == ["(first period)"]


# ------------------------------------------------------------------ EventCatchUp
def _catchup_config():
    return {"scheduled_events": [
        {"round": 0, "date": "2026-08-01", "content": "[2026-08-01] 事件0"},
        {"round": 1, "date": "2026-11-05", "content": "[2026-11-05] 事件A发生"},
        {"round": 2, "date": "2027-02-01", "content": "事件C", "is_scenario_injection": True},
        {"round": "bad", "content": "never indexed"},
        {"content": "no round → never due"},
        "junk",
    ]}


def test_catchup_missed_window_and_mark_briefed():
    cu = EventCatchUp(_catchup_config(), 1200)
    # agent 2 was briefed in round 0, sat out rounds 1-2, event fired in round 1
    cu.mark_briefed(2, 0)
    assert [e["content"] for e in cu.missed(2, 3)] == ["[2026-11-05] 事件A发生", "事件C"]
    assert cu.missed(2, 2) == [_catchup_config()["scheduled_events"][1]]
    cu.mark_briefed(2, 3)
    assert cu.missed(2, 3) == [] and cu.missed(2, 4) == []
    # mark_briefed never moves backwards
    cu.mark_briefed(2, 1)
    assert cu.missed(2, 4) == []
    # an actor briefed every round never has anything to catch up on
    for rnd in range(4):
        assert cu.missed(0, rnd) == []
        cu.mark_briefed(0, rnd)
    assert cu.render(cu.missed(0, 4)) == ""


def test_catchup_first_activation_gets_all_earlier_events_newest_first():
    cu = EventCatchUp(_catchup_config(), 1200)
    block = cu.render(cu.missed(7, 3))
    assert block.split("\n") == [
        "## EARLIER SCHEDULED EVENTS YOU HAVE NOT BEEN BRIEFED ON",
        "SCENARIO ASSUMPTION (what-if, not observed): [2027-02-01] 事件C",
        "[2026-11-05] 事件A发生",
        "[2026-08-01] 事件0",
    ]
    assert "never indexed" not in block and "never due" not in block
    # deterministic: a fresh tracker renders byte-identical text
    assert EventCatchUp(_catchup_config(), 1200).render(cu.missed(7, 3)) == block
    assert cu.render([]) == "" and cu.render(None) == ""


def test_catchup_cap_keeps_whole_lines_with_omission_marker():
    events = [{"round": r, "date": f"2026-0{r + 1}-01", "content": f"event {r} " + "x" * 60}
              for r in range(5)]
    cu = EventCatchUp({"scheduled_events": events}, 250)
    block = cu.render(cu.missed(1, 5))
    lines = block.split("\n")
    assert len(block) <= 250
    assert lines[0] == spc.CATCHUP_HEADING
    kept = lines[1:-1]
    assert kept and all(line.endswith("x" * 60) for line in kept)  # whole lines only
    assert kept[0].startswith("[2026-05-01] event 4")                # newest first
    assert lines[-1] == f"(+{5 - len(kept)} earlier scheduled events omitted)"
    # a cap smaller than one line still names what was dropped
    tiny = EventCatchUp({"scheduled_events": events}, 10).render(events)
    assert tiny == spc.CATCHUP_HEADING + "\n(+5 earlier scheduled events omitted)"


def test_catchup_clips_a_newest_event_too_long_for_the_cap():
    """A newest event longer than the whole cap is cut with an explicit ending, not
    dropped: the actor always learns of the latest event it missed."""
    events = [{"round": 0, "date": "2026-08-01", "content": "older event"},
              {"round": 1, "date": "2026-11-05", "content": "word " * 400}]
    block = EventCatchUp({"scheduled_events": events}, 1200).render(events)
    lines = block.split("\n")
    assert len(block) <= 1200
    assert lines[0] == spc.CATCHUP_HEADING
    assert lines[1].startswith("[2026-11-05] word word") and lines[1].endswith(
        "word…(truncated)")
    assert lines[2] == "(+1 earlier scheduled events omitted)"


def test_catchup_is_resume_safe():
    """A resumed process rebuilds agent memory, so the first activation after a lossy
    resume re-delivers the earlier events; the index comes only from the config."""
    before = EventCatchUp(_catchup_config(), 1200)
    for rnd in range(3):
        before.mark_briefed(4, rnd)
    resumed = EventCatchUp(_catchup_config(), 1200)
    assert [e["content"] for e in resumed.missed(4, 3)] == [
        "[2026-08-01] 事件0", "[2026-11-05] 事件A发生", "事件C"]
    assert EventCatchUp(None, 1200).missed(4, 3) == []
    assert EventCatchUp({"scheduled_events": None}, 1200).missed(4, 3) == []


# ---------------------------------------------------------- compact_period_context
def test_compact_period_context_fits_unchanged():
    out = compact_period_context(["[2026-11-05] 事件A发生"], ["Actor1: deal"])
    assert out == ("## THIS PERIOD — scheduled events (research timeline)\n"
                   "[2026-11-05] 事件A发生\n## WHAT CHANGED LAST PERIOD\nActor1: deal")
    # no delta lines (SIM_WORLD_DELTA off) → no WHAT CHANGED section
    assert compact_period_context([spc.WORLD_CLOCK_NO_EVENTS], []) == (
        spc.THIS_PERIOD_HEADING + "\n" + spc.WORLD_CLOCK_NO_EVENTS)


@pytest.mark.parametrize("max_chars", [400, 600, 1200])
def test_compact_period_context_is_capped_on_whole_lines(max_chars):
    events = [f"[2026-11-0{i}] event {i} " + "e" * 80 for i in range(1, 10)]
    delta = [f"Actor{i}: " + "d" * 90 for i in range(12)] + ["Momentum: A held this period."]
    out = compact_period_context(events, delta, max_chars=max_chars)
    assert len(out) <= max_chars
    head, tail = out.split("\n" + spc.WHAT_CHANGED_HEADING + "\n")
    ev_lines = head.split("\n")[1:]
    de_lines = tail.split("\n")
    assert head.startswith(spc.THIS_PERIOD_HEADING)
    # oversized events never starve the delta section and vice versa
    assert ev_lines[0] == events[0] and de_lines[0] == delta[0]
    assert set(ev_lines[:-1]) <= set(events) and set(de_lines[:-1]) <= set(delta)
    assert ev_lines[-1] == f"(+{len(events) - len(ev_lines) + 1} more omitted)"
    assert de_lines[-1] == f"(+{len(delta) - len(de_lines) + 1} more omitted)"


def test_compact_period_context_short_section_lends_its_budget():
    events = ["[2026-11-05] 事件A发生"]
    delta = [f"Actor{i}: " + "d" * 90 for i in range(20)]
    out = compact_period_context(events, delta, max_chars=1200)
    assert len(out) <= 1200
    assert "[2026-11-05] 事件A发生\n" in out                    # the short section is intact
    assert out.count("d" * 90) > 1200 // 2 // 100                 # delta took the slack
    assert out.endswith("more omitted)")


def test_compact_period_context_gives_this_periods_events_priority():
    """A long event line (more than half the budget) stays whole while the digest
    overflows; the digest keeps a reserve of whole lines and its omission marker."""
    event = "[2026-11-05] " + "long scheduled event text " * 26
    assert 600 < len(event) < 800
    delta = [f"Actor{i}: " + "d" * 90 for i in range(12)]
    out = compact_period_context([event], delta, max_chars=1200)
    assert len(out) <= 1200
    head, tail = out.split("\n" + spc.WHAT_CHANGED_HEADING + "\n")
    assert head == spc.THIS_PERIOD_HEADING + "\n" + event
    de_lines = tail.split("\n")
    assert len(de_lines) >= 3 and de_lines[:-1] == delta[:len(de_lines) - 1]
    assert de_lines[-1] == f"(+{len(delta) - len(de_lines) + 1} more omitted)"


def test_compact_period_context_clips_an_event_too_long_for_its_section():
    event = "[2026-11-05] " + "word " * 500
    delta = [f"Actor{i}: " + "d" * 90 for i in range(12)]
    out = compact_period_context([event, "[2026-11-06] second event"], delta, max_chars=1200)
    assert len(out) <= 1200
    lines = out.split("\n")
    assert lines[1].startswith("[2026-11-05] word") and lines[1].endswith("word…(truncated)")
    assert lines[2] == "(+1 more omitted)" and lines[3] == spc.WHAT_CHANGED_HEADING
    assert lines[4] == delta[0]


def test_compact_period_context_tiny_cap_still_names_omissions():
    out = compact_period_context(["e" * 50, "f" * 50], ["d" * 50], max_chars=10)
    assert out == (spc.THIS_PERIOD_HEADING + "\n(+2 more omitted)\n"
                   + spc.WHAT_CHANGED_HEADING + "\n(+1 more omitted)")
