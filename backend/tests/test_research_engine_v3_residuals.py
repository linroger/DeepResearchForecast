"""Residual fixes after review round 3 of the deep-research engine v3.

* Percentages are verified only by percentages: a fact's "15%" is not
  VERIFIED by a page whose only 15 is a day of the month; page numbers
  written as percentages, range bounds and numbers in percent contexts
  (sentences, tables and header blocks with a percent marker) still verify.
* Numbers written with a power, energy or currency unit are verified only
  by the same number in the same unit class ("176 GW" is not VERIFIED by
  "176 pages", "12%" or a "w55c" image URL); real unit layouts (KPI cards,
  table captions, header blocks, RMB statements, price ranges) still verify.
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


# Unit-aware verification: a number the fact writes with a power (W family),
# energy (Wh family) or currency unit is verified only by the same number on
# the page in the same unit class.  The coincidences below are real ones from
# the cached pages of real runs (176 pages, "up 12%", a "w55c" image host,
# "Figure 10", "100 gigawatts" cited for "€100 bn"); the layouts are real
# page layouts that must keep verifying (BNEF KPI cards, Gartner table
# captions, Tencent/Alibaba RMB statements, SEC EPS lines, EIA/NEA tables).
UNIT_PAGE = """# Storage outlook
The report runs to 176 pages. Installations grew 12% in 2025, and 100 gigawatts were added.
![banner](https://tags.w55c.net/rs?id=1005X300)
Figure 10. Cost ranges by technology.

Global energy storage annual additions in 2025

158

GW

A 300-megawatt plant. Operators expect between 40 and 55 GW by 2030, led by five 50+ MW batteries.
净利润为人民币1,635.09億元。GAAP EPS of $****0.48** per share; a net loss of CNY -8.328 billion.
Consumption could reach 1000TWh9 by 2026. Capex totals $1,200 billion.

**Table 1. Worldwide IT Spending Forecast (Billions of U.S. Dollars)**

|  | 2026 Spending |
| --- | --- |
| Data Center Systems | 822 |

单位：万千瓦
风电 441

USD

140.35"""


def _unit_tags(*claims: str) -> list[tuple[str, list | None]]:
    numbers = lr.page_number_set(UNIT_PAGE)
    notes = "\n".join(["## Findings", *(f"- {claim} [S1] (VERIFIED)" for claim in claims),
                       "## Conflicts", "## Open questions", "## Discovered"])
    _, parts = lr.postprocess_notes("K1", notes, {1: {"sid": 1, "fetched": True}}.get, lambda sid: numbers)
    return [(fact["tag"], fact.get("missing_numbers")) for fact in parts["facts"]]


@pytest.mark.parametrize("claim, missing", [
    ("Storage additions reached 176 GW in 2025", ["176"]),     # the page's 176 counts pages
    ("BYD signed 12 GWh with SEC", ["12"]),                     # the page's 12 is a percentage
    ("ERCOT revenue fell to US$55/kW-yr", ["55"]),              # only in an image URL
    ("Terna's MACSE auction awarded 10 GWh", ["10"]),           # "Figure 10"
    ("Roughly €100 bn of projects are stalled", ["100"]),       # the page's 100 is gigawatts
    ("The plant delivers 300 kWh per cycle", ["300"]),          # the page's 300 is megawatts
])
def test_unit_figures_need_the_same_unit_class_on_the_page(claim, missing):
    assert _unit_tags(claim) == [("UNVERIFIED", missing)]


@pytest.mark.parametrize("claim", [
    "BNEF counts 158 GW of additions in 2025",          # KPI card: "158\n\nGW"
    "A 300 MW plant",                                     # "300-megawatt"
    "Operators expect at least 40 GW by 2030",           # "between 40 and 55 GW"
    "Five batteries of 50 MW each",                       # "50+ MW"
    "净利润1635.09亿元",                                  # traditional 億 on the page
    "Non-GAAP EPS was $0.48",                             # "$****0.48**"
    "The net loss was CNY 8.328 billion",                # "CNY -8.328 billion"
    "Consumption could reach 1,000 TWh",                  # "1000TWh9" (glued footnote)
    "Capex totals US$1.2 trillion",                       # "$1,200 billion": same value
    "Data center systems spending reaches $822 billion",  # table caption names the unit
    "风电装机441万千瓦",                                  # "单位：万千瓦" header block
    "Shares closed at $140.35",                           # "USD\n\n140.35" quote card
    "The report runs to 176 pages",                       # numbers without a unit: unchanged
    "Utilisation stayed at 1005 hours",
])
def test_real_unit_layouts_still_verify(claim):
    assert _unit_tags(claim) == [("VERIFIED", None)]


def test_fact_unit_tokens():
    assert lr.fact_unit_tokens("112 GW/307 GWh at US$192/kW-yr, RMB 100 billion, 5亿元, 300-megawatt, "
                               "20 countries in 2025") == {
        "112": {"power"}, "307": {"energy"}, "192": {"currency"}, "100": {"currency"}, "5": {"currency"},
        "300": {"power"}}


def test_unit_scans_are_linear_on_pathological_pages():
    started = time.perf_counter()
    lr.page_number_set("1-" * 25000 + "1 GW")
    lr.page_number_set("1 and " * 8000 + "1 GWh")
    lr.page_number_set("$" + "*" * 50000 + "x")
    lr.page_number_set("| $ |\n" + "| 1 |\n" * 8000)
    lr.page_number_set("Capacity (GW)\n" + "1 2 3\n" * 8000)
    lr.fact_unit_tokens("9" * 20000 + " " * 20000 + "GW")
    assert time.perf_counter() - started < 2.0


# Currency layouts from real cached pages (Meta/Alphabet capex guidance,
# China tender prices, EU cost tables, Indian investment news): the upper
# bound of a range whose lower bound carries the sign, a sign written after
# the number, and rupees.  "$5-10%" and "RS-485" are no prices.
UNIT_CURRENCY_PAGE = """Meta expects 2026 capex of $115-135 billion; the sector lost $1.3bn–1.4bn in a day.
Bids ranged from CNY430-960 per kWh. A 10 to 100 kWp rooftop system cost around 14,000 €/kWp in 1990.
Adani Green will invest Rs 24,500 crore in three projects. Tariffs were $5-10% higher.
Controllers expose RS-485 ports."""


def _currency_tags(*claims: str) -> list[tuple[str, list | None]]:
    numbers = lr.page_number_set(UNIT_CURRENCY_PAGE)
    notes = "\n".join(["## Findings", *(f"- {claim} [S1] (VERIFIED)" for claim in claims),
                       "## Conflicts", "## Open questions", "## Discovered"])
    _, parts = lr.postprocess_notes("K1", notes, {1: {"sid": 1, "fetched": True}}.get, lambda sid: numbers)
    return [(fact["tag"], fact.get("missing_numbers")) for fact in parts["facts"]]


@pytest.mark.parametrize("claim", [
    "Meta guided 2026 capex of up to $135 billion",       # "$115-135 billion"
    "The sector lost $1.4 billion in a day",              # "$1.3bn–1.4bn": same value
    "Bids reached CNY 960 per kWh",                       # "CNY430-960"
    "Rooftop systems cost €14,000/kWp in 1990",           # "14,000 €/kWp"
    "Adani Green will invest ₹24,500 crore",              # "Rs 24,500 crore"
])
def test_currency_range_bounds_signs_after_and_rupees_verify(claim):
    assert _currency_tags(claim) == [("VERIFIED", None)]


@pytest.mark.parametrize("claim, missing", [
    ("Tariffs rose by $10 per MWh", ["10"]),      # "$5-10%" is a percentage; "10 to 100 kWp" is power
    ("The permit fee is Rs 485", ["485"]),        # "RS-485" is a serial port
])
def test_currency_lookalikes_do_not_verify(claim, missing):
    assert _currency_tags(claim) == [("UNVERIFIED", missing)]


def test_currency_page_scans_are_linear():
    started = time.perf_counter()
    lr.page_number_set("$1-" * 20000 + "1")
    lr.page_number_set("$1 b " * 12000)
    lr.page_number_set("1" + " " * 50000 + "$")
    lr.page_number_set("1 $ " * 15000 + "Rs. " * 15000)
    assert time.perf_counter() - started < 2.0


@pytest.mark.parametrize("fact, page", [
    ("India reached 157.05 GW of solar capacity", "India's solar power installed capacity reached 157.05 GWAC"),
    ("The plant added 500 MW", "Expanded active power by nearly 500 MWs"),
    ("Three projects total 1.8 GW", "three new PSH projects totaling 1.8 GWs"),
    ("The farm is 176 MW", "the farm has 176 MWP installed"),
    ("Storage reached 307 GWh", "Deployments reached 307 GW·h in 2025"),
])
def test_power_and_energy_units_in_any_case_or_plural_still_verify(fact, page):
    """Real cached-page layouts (upper-case suffixes, plurals, 'GW·h') that the
    first unit-aware rules missed; the plain-unit fact must stay VERIFIED."""
    numbers = lr.page_number_set(page)
    _, parts = lr.postprocess_notes("K1", f"## Findings\n- {fact} [S1] (VERIFIED)\n## Conflicts\n## Open questions\n"
                                    "## Discovered", {1: {"sid": 1, "fetched": True}}.get, lambda sid: numbers)
    assert parts["facts"][0]["tag"] == "VERIFIED"


def test_energy_written_with_a_middle_dot_is_not_power():
    numbers = lr.page_number_set("Deployments reached 307 GW·h in 2025")
    _, parts = lr.postprocess_notes("K1", "## Findings\n- Capacity reached 307 GW [S1] (VERIFIED)\n## Conflicts\n"
                                    "## Open questions\n## Discovered", {1: {"sid": 1, "fetched": True}}.get,
                                    lambda sid: numbers)
    assert parts["facts"][0]["tag"] == "UNVERIFIED"
