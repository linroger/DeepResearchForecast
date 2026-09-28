"""Residual fixes after review round 3 of the deep-research engine v3.

* Percentages are verified only by percentages: a fact's "15%" is not
  VERIFIED by a page whose only 15 is a day of the month; page numbers
  written as percentages, range bounds and numbers in percent contexts
  (sentences, tables and header blocks with a percent marker) still verify.
* A plan the planner answered unusably (template questions or the default
  scenario frame) is a research_quality degradation event, not only a plan
  from a model outage.
* finalize writes sources.json before research_report.md, so a killed run
  never leaves a report without the sources its [S#] point into.

Offline and deterministic (the fakes and ``run_engine`` of
``test_research_engine_v3``).
"""

from __future__ import annotations

import json
import time

import pytest

import test_research_engine_v3 as v3

_hermetic_env = v3._hermetic_env
bridge = v3.bridge
lr = v3.lr
rg = v3.rg

PAGE = """# Grid report
Published 15 March 2024. The agency counted 176 GW of capacity in 2023, up 12% on 2022.
Operators expect 4.5 per cent annual growth.

| Region | Share (%) | Sites |
|---|---|---|
| North | 38 | 120 |

Utilisation reached 81 percent. Grid queues exceed 40 months."""


def _tags(*claims: str) -> list[tuple[str, list | None]]:
    numbers = lr.page_number_set(PAGE)
    notes = "\n".join(["## Findings", *(f"- {claim} [S1] (VERIFIED)" for claim in claims),
                       "## Conflicts", "## Open questions", "## Discovered"])
    _, parts = lr.postprocess_notes("K1", notes, {1: {"sid": 1, "fetched": True}}.get, lambda sid: numbers)
    return [(fact["tag"], fact.get("missing_numbers")) for fact in parts["facts"]]


# Real layouts the review found on cached tier-1 pages (Gartner, SEC/IR
# releases, BLS, NDRC, TrendForce): all of them must keep verifying.
REAL_LAYOUTS = """
|  |  |
| --- | --- |
| Market share % | 2024 |
| Intel | 7.6 |

Gross margin | 73.5 | % | Down 1.5 pts
DRAM prices expected to rise another 13–18% next quarter.
the rate changed little at 1.1
percent in May. A 2.8-percent increase. UK inflation hit 4.1pc.
Market share (%)
AMD 22.3

Footnote 33 applies."""


@pytest.mark.parametrize("claim, expected", [
    ("Capacity grew 15% in 2023", ("UNVERIFIED", ["15"])),   # the page's 15 is a day of the month
    ("Queues exceed 40% of requests", ("UNVERIFIED", ["40"])),  # the page's 40 counts months
    ("Capacity grew 12% in 2023", ("VERIFIED", None)),
    ("Growth of 4.5% a year is expected", ("VERIFIED", None)),  # "4.5 per cent" on the page
    ("The North held 38% of sites", ("VERIFIED", None)),        # a "Share (%)" table column
    ("Utilisation hit 81 per cent", ("VERIFIED", None)),        # "81 percent" on the page
    ("Capacity reached 176 GW", ("VERIFIED", None)),            # plain numbers are unchanged
])
def test_percentages_are_verified_only_by_percentages(claim, expected):
    assert _tags(claim) == [expected]


@pytest.mark.parametrize("number", ["7.6", "73.5", "1.5", "13", "18", "1.1", "2.8", "4.1", "22.3"])
def test_real_percentage_layouts_still_verify(number):
    assert "%" + number in lr.page_number_set(REAL_LAYOUTS)


def test_numbers_outside_percent_contexts_are_no_percentages():
    assert "%33" not in lr.page_number_set(REAL_LAYOUTS)


def test_fact_percent_tokens_and_page_percentages():
    assert lr.fact_percent_tokens("up 12% and 4.5 per cent, 3 pp, 7个百分点; 2024 rose") == {"12", "4.5", "3", "7"}
    numbers = lr.page_number_set(PAGE)
    assert {"%12", "%4.5", "%81", "%38", "%120"} <= numbers and "%15" not in numbers and "%40" not in numbers


def test_percentage_scans_are_linear_on_pathological_pages():
    started = time.perf_counter()
    lr.page_number_set("1" + " " * 50000 + "%")
    lr.page_number_set("| a (%) |\n" + "| 1 |\n" * 5000)
    lr.fact_percent_tokens("9" * 20000 + " " * 20000 + "percent")
    assert time.perf_counter() - started < 1.0


class UnusablePlanWorld(v3.World):
    """The planner answers, but with one question and no scenarios."""

    def plan(self, call):
        plan = {"kiqs": [{"question": "What is installed capacity today?", "queries": ["capacity 2023 GW"]}],
                "sections": [{"title": "Market Baseline", "kiqs": [1]}], "scenarios": []}
        return v3.ai("```json\n" + json.dumps(plan) + "\n```")


def test_an_unusable_plan_answer_is_a_degradation_event(tmp_path, bridge):
    rc, meta, _, _, _ = v3.run_engine(tmp_path, bridge, UnusablePlanWorld())
    assert rc == 0, meta.get("error")
    events = meta["research_quality"]["degradation"]
    assert meta["research_quality"]["degraded"] is True
    assert any("research questions filled from the deterministic templates" in e for e in events)
    assert any("scenario frame is the default template" in e for e in events)


def test_a_failed_planning_call_is_one_template_plan_event(tmp_path, bridge):
    rc, meta, _, _, _ = v3.run_engine(tmp_path, bridge, v3.JunkWorld(), depth="quick")
    assert rc == 0, meta.get("error")
    plan_events = [e for e in meta["research_quality"]["degradation"]
                   if e.startswith(("research plan", "research questions", "scenario frame"))]
    assert plan_events == ["research plan built from the deterministic templates: the planning call returned "
                           "no usable plan"]


def test_a_usable_plan_adds_no_plan_event(tmp_path, bridge):
    rc, meta, _, _, _ = v3.run_engine(tmp_path, bridge, v3.World())
    assert rc == 0, meta.get("error")
    events = (meta.get("research_quality") or {}).get("degradation") or []
    assert not [e for e in events if "template" in e]


def test_finalize_writes_sources_before_the_report(tmp_path, bridge, monkeypatch):
    order: list[str] = []
    real_text, real_json = lr._Engine.write_text, lr._Engine.write_json

    def write_text(self, path, text, *args, **kwargs):
        order.append(path.name)
        return real_text(self, path, text, *args, **kwargs)

    def write_json(self, path, obj, *args, **kwargs):
        order.append(path.name)
        return real_json(self, path, obj, *args, **kwargs)

    monkeypatch.setattr(lr._Engine, "write_text", write_text)
    monkeypatch.setattr(lr._Engine, "write_json", write_json)
    rc, meta, _, _, _ = v3.run_engine(tmp_path, bridge, v3.World())
    assert rc == 0, meta.get("error")
    assert order.index("sources.json") < order.index("research_report.md")


def test_fiscal_year_ranges_are_years_not_quantities():
    """Live run: "schedule risk to 2026-27" left "27" to verify (not on the page)."""
    assert lr.fact_number_tokens("risk to 2026-27 and FY2025/26 loads of 176 GW") == ["176"]
    # A range that is not next-year shorthand stays a pair of numbers.
    assert lr.fact_number_tokens("between 2026-30 there were 45 sites") == ["2026", "30", "45"]


def test_writers_are_told_to_prefer_fetched_sources():
    assert "cite the ones marked fetched in the SOURCE INDEX" in lr._SECTION_RULES
