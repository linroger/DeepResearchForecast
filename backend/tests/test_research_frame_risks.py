"""Documented risks in the v3 forecast frame (``forecast_inputs.risks`` → world-model shocks).

Pins: with method skills the ``FORECAST FRAME EXTRACTION TASK`` asks for the risks the report itself
attaches a probability to, with that probability and its window exactly as written, the [S<n>]
marker of the statement and effects on quantities the report names; ``normalize_frame_risks`` keeps
a risk only when a line of the report states its probability (one probability, never a published
range such as "5-25%") and names the event, keeps its window
and marker only when they stand on such a line, binds effects only to ``quantitative_facts`` metrics
(by their exact names) and an effect's size only when the report states it — anything else is left
empty or dropped and counted in ``meta.forecast_risks``, never invented; the counts are bounded; the
world-model seed (``world_model_seed.shocks_from_research``) turns what is kept into shocks that the
kernel can fire, and a report without documented risks writes ``risks: []`` (the seed then records
``no_documented_shocks``).

Offline and deterministic: the scripted model and ``run_engine`` harness of ``test_research_engine_v3``
(injected search/fetch, the real bridge module with prediction markets and charts stubbed), no
network, no LLM, no sleeps.
"""

from __future__ import annotations

import json
import math
import re

import pytest

import test_research_engine_v3 as v3
from app.services import world_model_seed as wms
from app.services.world_model import WorldModel

# The shared fixtures (hermetic env, real bridge with network steps stubbed).
_hermetic_env = v3._hermetic_env
bridge = v3.bridge
lr = v3.lr

_ZERO = dict.fromkeys(lr._FRAME_RISK_CHECKS, 0)

REPORT = """## Supply risks

A closure of the Strait of Hormuz carries a **5%** monthly probability, per the IEA risk note [S2]. A closure would lift the Brent crude price by 30% [S2].

Grid failure risk is 5-10% per year [S1].

A 15% chance of a court ruling against the merger within 12 months [S3]; the ruling would hit Acme Corp.

A tanker insurance crisis has a 1 in 20 chance over the forecast horizon [S4].

Refinery outages run at 12.5% of years [S1].
"""
SOURCES = [{"title": "Agency survey", "url": "https://agency.example/survey", "tier": "S1"},
           {"title": "IEA risk note", "url": "https://iea.example/note", "tier": "S1"},
           {"title": "Court docket", "url": "https://court.example/docket"},
           {"title": "Lloyd's market bulletin", "url": "https://lloyds.example/bulletin", "tier": "S2"}]
QUANT = [{"metric": "Brent crude price", "value": 80, "unit": "USD"},
         {"metric": "WTI crude price", "value": 76, "unit": "USD"},
         {"metric": "OPEC+ spare capacity", "value": "4.5", "unit": "mb/d"},
         {"metric": "Henry Hub gas price", "value": "3.1", "unit": "USD/MMBtu"}]
HORMUZ = {"event": "Strait of Hormuz closure", "probability": "5%", "per": "monthly", "source": "S2"}


def _risks(rows, report=REPORT, quant=QUANT, sources=SOURCES, scenarios=()):
    return lr.normalize_frame_risks({"risks": rows}, report, quant, sources, scenarios)


class _RNG:
    """Scripted ``random()`` draws."""

    def __init__(self, seq):
        self.seq = list(seq)

    def random(self):
        return self.seq.pop(0)


# =============================================================== the prompt

def _frame_prompt(language: str = "English") -> str:
    return lr._render(lr._T_FRAME, max_rates=lr.MAX_FRAME_BASE_RATES, max_drivers=lr.MAX_FRAME_DRIVERS,
                      max_risks=lr.MAX_FRAME_RISKS, max_effects=lr.MAX_FRAME_RISK_EFFECTS, language=language)


def test_frame_prompt_asks_for_the_documented_risks_in_the_contract_shape():
    prompt = _frame_prompt()
    assert prompt.startswith("FORECAST FRAME EXTRACTION TASK\n")
    shape = json.loads(prompt.split("in exactly this shape:\n", 1)[1].split("\nField rules:", 1)[0])
    assert list(shape) == ["base_rates", "drivers", "risks"]
    # the dossier contract of backend/app/utils/actors.py (forecast_inputs.risks)
    assert list(shape["risks"][0]) == ["event", "probability", "per", "source", "effects", "affects", "recurring"]
    assert list(shape["risks"][0]["effects"][0]) == ["metric", "change", "direction"]
    rule = next(line for line in prompt.splitlines() if line.startswith("- risks:"))
    for text in (f"at most {lr.MAX_FRAME_RISKS} discrete events", "the report itself attaches a probability",
                 "never the forecast question's own outcome or one of its scenarios",
                 "that probability exactly as the report writes it", "never one you estimate, convert or derive",
                 "per is the period that probability refers to, exactly as the report writes it",
                 '"" when the report states none', "the [S<n>] marker of that statement in the report, without "
                 "brackets", f"at most {lr.MAX_FRAME_RISK_EFFECTS} quantities",
                 "An empty list when the report attaches a probability to no such event"):
        assert text in rule, text
    assert "never invent a reference class, a probability, a number or a source" in prompt
    assert prompt.endswith("- Write text values in English.")
    # the bounds stay within what the seed admits (world_model_seed.MAX_SHOCKS and its parts)
    assert lr.MAX_FRAME_RISKS <= wms.MAX_SHOCKS and lr.MAX_FRAME_RISK_EFFECTS <= wms.MAX_SHOCK_EFFECTS
    assert lr.MAX_FRAME_RISK_AFFECTS <= 6


# =============================================================== parsing a scripted reply

def test_a_documented_risk_is_kept_as_written_with_its_source_and_tracked_effects():
    risks, checks = _risks([
        {**HORMUZ, "effects": [{"metric": "Brent price", "change": "+30%", "direction": "up"}],
         "affects": ["Saudi Aramco", "saudi aramco", "OPEC Secretariat"], "recurring": False},
        {"event": "Tanker insurance crisis", "probability": "1 in 20", "per": "over the forecast horizon",
         "source": "[S4]", "recurring": True},
        {"event": "Court ruling against the merger", "probability": 0.15, "per": "within 12 months",
         "source": "S3", "affects": "Acme Corp"},
    ])
    assert risks == [
        {"event": "Strait of Hormuz closure", "probability": "5%", "per": "monthly",
         "source": "IEA risk note [S2]", "source_url": "https://iea.example/note", "tier": "S1",
         "effects": [{"metric": "Brent crude price", "change": "+30%", "direction": "up"}],
         "affects": ["Saudi Aramco", "OPEC Secretariat"], "recurring": False},
        {"event": "Tanker insurance crisis", "probability": "1 in 20", "per": "over the forecast horizon",
         "source": "Lloyd's market bulletin [S4]", "source_url": "https://lloyds.example/bulletin", "tier": "S2",
         "effects": [], "affects": [], "recurring": True},
        # a bare number is kept in the form the report states it
        {"event": "Court ruling against the merger", "probability": "15%", "per": "within 12 months",
         "source": "Court docket [S3]", "source_url": "https://court.example/docket",
         "effects": [], "affects": ["Acme Corp"], "recurring": False},
    ]
    assert checks == {**_ZERO, "extracted": 3, "kept": 3, "effects_kept": 1}


@pytest.mark.parametrize("event, probability", [
    ("Strait of Hormuz closure", "7%"),          # the report never states it
    ("Grid failure", "5%"),                      # 5% is stated, but for Hormuz; the grid line has a range
    ("Grid failure", "10%"),                     # one end of the range "5-10%"
    ("Refinery outages", "2.5%"),                # inside the longer number 12.5%
    ("Refinery outages", "12%"),
    ("Strait of Hormuz closure", "likely"),      # not a probability
    ("Strait of Hormuz closure", True),
    ("Strait of Hormuz closure", 1.0),           # certain: a scheduled event, never a shock
    ("Strait of Hormuz closure", None),
    ("Strait of Hormuz closure", ""),
    ("A shock", "5%"),                           # an event named only in generic words names nothing
])
def test_a_probability_the_report_does_not_state_for_that_event_drops_the_risk(event, probability):
    risks, checks = _risks([{"event": event, "probability": probability, "per": "monthly", "source": "S2"}])
    assert risks == []
    assert checks == {**_ZERO, "extracted": 1, "probability_not_stated": 1}


@pytest.mark.parametrize("probability", ["5-10%", "5-25%", "between 1% and 5%", "0.5–1%", "5%至25%",
                                         "1 in 20 to 1 in 10"])
def test_a_published_range_is_no_single_probability(probability):
    """Risk registers publish likelihood bands. Copied as printed, the report states the band, but it
    is no one probability: the seed's parser would read one end of it as the shock's rate
    (world_model_seed.parse_risk_probability: "5-25%" → 0.25), so the risk is dropped and counted."""
    report = REPORT + (f"\nThe national risk register puts the probability of a regional grid blackout at "
                       f"{probability} over the next five years [S1].\n")
    risks, checks = _risks([{"event": "Regional grid blackout", "probability": probability,
                             "per": "over the next five years", "source": "S1"},
                            {"event": "Grid failure", "probability": "5-10%", "per": "per year", "source": "S1"}],
                           report=report)
    assert risks == [] and checks == {**_ZERO, "extracted": 2, "probability_range": 2}


@pytest.mark.parametrize("probability", ["1 in 20", "2 of 10 years", "12.5%", "1-in-100", "0.05", "5%", "15%"])
def test_a_single_probability_is_no_range(probability):
    assert not lr._PROBABILITY_RANGE_RE.search(lr._report_key(probability))


def test_window_and_marker_count_only_on_the_line_that_states_the_probability():
    risks, checks = _risks([
        {**HORMUZ, "per": "per year"},                                  # not on the Hormuz line
        {"event": "Hormuz shipping halt", "probability": "5%", "per": "", "source": "S1"},  # S1 cited elsewhere
        {"event": "Hormuz mining", "probability": "5%", "per": "monthly", "source": "S9"},   # no such source
        {"event": "Hormuz blockade", "probability": "5%", "per": "monthly", "source": ""},
    ])
    assert [(r["event"], r["per"], r["source"]) for r in risks] == [
        ("Strait of Hormuz closure", "", "IEA risk note [S2]"), ("Hormuz shipping halt", "", ""),
        ("Hormuz mining", "monthly", ""), ("Hormuz blockade", "monthly", "")]
    assert checks == {**_ZERO, "extracted": 4, "kept": 4, "window_not_stated": 1, "source_not_stated": 3}
    # the seed records a typed gap for each, never a shock with a window or a source it lacks
    dossier = {"as_of_date": "2026-10-01", "quantitative_facts": QUANT, "forecast_inputs": {"risks": risks}}
    shocks, gaps = wms.shocks_from_research(dossier, [], {})
    assert shocks == []
    assert [g["kind"] for g in gaps] == ["shock_without_window", "shock_without_window",
                                         "shock_without_source", "shock_without_source"]


def test_effects_bind_only_to_quantitative_facts_metrics_with_the_sizes_the_report_states():
    risks, checks = _risks([{**HORMUZ, "effects": [
        {"metric": "Brent price", "change": "+30%", "direction": "up"},      # unique paraphrase → exact name
        {"metric": "crude price", "change": "+30%"},                         # Brent or WTI: ambiguous
        {"metric": "Global GDP", "change": "-1%"},                           # not a quantitative fact
        {"metric": "OPEC+ spare capacity", "change": "-2 mb/d"},             # size not in the report
        {"metric": "WTI crude price"},                                       # neither size nor direction
        {"metric": "Brent crude price", "change": "+30%", "direction": "up"},  # the same metric again
        "Henry Hub gas price",
    ]}])
    assert risks[0]["effects"] == [{"metric": "Brent crude price", "change": "+30%", "direction": "up"},
                                   {"metric": "OPEC+ spare capacity", "change": "", "direction": "down"}]
    assert checks == {**_ZERO, "extracted": 1, "kept": 1, "effects_kept": 2, "effects_untracked": 2,
                      "effects_unreadable": 1, "effect_sizes_not_stated": 1}
    # at most MAX_FRAME_RISK_EFFECTS per risk
    many, _ = _risks([{**HORMUZ, "effects": [{"metric": q["metric"], "direction": "up"} for q in QUANT]}])
    assert [e["metric"] for e in many[0]["effects"]] == [q["metric"] for q in QUANT][:lr.MAX_FRAME_RISK_EFFECTS]
    # without quantitative facts no effect binds
    bare, checks = _risks([{**HORMUZ, "effects": [{"metric": "Brent crude price", "change": "+30%"}]}], quant=[])
    assert bare[0]["effects"] == [] and checks["effects_untracked"] == 1


def test_counts_are_bounded_and_scenarios_duplicates_and_garbage_never_become_risks():
    names = ["alpha", "bravo", "charlie", "delta", "echo", "foxtrot", "golf", "hotel"]
    report = "\n".join(f"An {name} outage has a {i + 1}% chance per year [S1]." for i, name in enumerate(names))
    risks, checks = _risks([{"event": f"{name.title()} outage", "probability": f"{i + 1}%", "per": "per year",
                             "source": "S1"} for i, name in enumerate(names)], report=report)
    assert [r["event"] for r in risks] == [f"{name.title()} outage" for name in names][:lr.MAX_FRAME_RISKS]
    assert checks["extracted"] == len(names) and checks["kept"] == lr.MAX_FRAME_RISKS
    risks, checks = _risks([HORMUZ, {**HORMUZ, "event": "strait of hormuz CLOSURE"},
                            {"event": "Hormuz closure", "probability": "5%", "per": "monthly", "source": "S2"},
                            {**HORMUZ, "event": "Tanker insurance crisis", "probability": "1 in 20",
                             "per": "", "affects": [f"Insurer {i}" for i in range(9)], "recurring": "true"}],
                           scenarios=[lr.Scenario("Hormuz closure", 30, ""), lr.Scenario("Calm", 70, "")])
    assert [r["event"] for r in risks] == ["Strait of Hormuz closure", "Tanker insurance crisis"]
    assert risks[1]["affects"] == [f"Insurer {i}" for i in range(lr.MAX_FRAME_RISK_AFFECTS)]
    assert risks[1]["recurring"] is False                       # only a JSON true says it recurs
    assert checks["scenario"] == 1 and checks["extracted"] == 4 and checks["kept"] == 2
    for frame in (None, [], "risks", {"risks": "x"}, {"risks": [1, None, {"event": 5}, {"event": ""}, ["x"]]},
                  {"base_rates": []}):
        assert lr.normalize_frame_risks(frame, REPORT, QUANT, SOURCES) == ([], _ZERO)


def test_a_scenario_restated_under_another_name_is_not_a_risk():
    """The frame's scenarios are the share prior, never shocks: a paraphrased scenario whose only
    stated probability is that scenario's own weight is dropped; an exogenous event with the same
    number on a line of its own is kept."""
    frame = [lr.Scenario("Coalition rupture and early election", 25, ""), lr.Scenario("Continuity", 75, "")]
    report = ("- Coalition rupture and early election — 25% — a coalition crisis triggers a snap election [S2].\n"
              "A no-confidence vote against the chancellor has a 25% chance per year [S2].\n")
    risks, checks = _risks([
        {"event": "Early election after a coalition crisis", "probability": "25%", "per": "", "source": "S2"},
        {"event": "No-confidence vote", "probability": "25%", "per": "per year", "source": "S2"},
    ], report=report, scenarios=frame)
    assert [(r["event"], r["per"], r["source"]) for r in risks] == [
        ("No-confidence vote", "per year", "IEA risk note [S2]")]
    assert checks == {**_ZERO, "extracted": 2, "kept": 1, "scenario": 1}


def test_a_chinese_report_keeps_its_own_window_words_and_full_width_numbers():
    report = "霍尔木兹海峡被封锁的月度概率为５％[S2]，封锁将推高布伦特原油价格３０％[S2]。"
    risks, checks = _risks([{"event": "霍尔木兹海峡封锁", "probability": "5%", "per": "月度", "source": "S2",
                             "effects": [{"metric": "布伦特油价", "change": "+30%", "direction": "上升"}]}],
                           report=report, quant=[{"metric": "布伦特原油价格", "value": 80, "unit": "美元"}])
    assert risks == [{"event": "霍尔木兹海峡封锁", "probability": "5%", "per": "月度",
                      "source": "IEA risk note [S2]", "source_url": "https://iea.example/note", "tier": "S1",
                      "effects": [{"metric": "布伦特原油价格", "change": "+30%", "direction": "上升"}],
                      "affects": [], "recurring": False}]
    assert checks["kept"] == 1 and checks["effects_kept"] == 1
    variables = wms.state_variables_from_research({"quantitative_facts": [
        {"metric": "布伦特原油价格", "value": "80", "unit": "美元", "value_type": "actual"}]})
    [shock], gaps = wms.shocks_from_research({"forecast_inputs": {"risks": risks}}, variables, {})
    assert shock["base_rate"]["window"] == "month" and shock["base_rate"]["probability"] == 0.05 and gaps == []
    assert shock["effects"][0]["op"] == "mul" and shock["effects"][0]["value"] == pytest.approx(1.3)


def test_a_report_without_documented_risks_yields_an_empty_list():
    rows = [HORMUZ, {"event": "Tanker insurance crisis", "probability": "1 in 20", "per": "", "source": "S4"}]
    assert _risks(rows, report="") == ([], {**_ZERO, "extracted": 2, "probability_not_stated": 2})
    assert _risks(rows, report="## Outlook\n\nCapacity grows steadily [S1].\n") == \
        ([], {**_ZERO, "extracted": 2, "probability_not_stated": 2})
    assert _risks([]) == ([], _ZERO)


# =============================================================== end to end

_RISK_LINE = ("A connection moratorium on new data-centre load carries a 10% probability per year, according to "
              "the operator survey [S{sid}]. A moratorium would cut installed capacity to 150 GW [S{sid}].")


class RiskWorld(v3.World):
    """The grid-constraints section documents one risk (probability, window, marker, effect); the
    frame reply extracts it as written, with the marker the report it reads carries, plus one risk
    the report never mentions and one effect on a quantity that is no quantitative fact."""

    def writer(self, call):
        reply = super().writer(call)
        context = call["messages"][2][1]
        sid = re.findall(r"^\[S(\d+)\]", context.split("SOURCE INDEX", 1)[-1], re.M)[0]
        if "## Grid Constraints\n\n" not in reply.content:
            return reply
        text = reply.content.replace("## Grid Constraints\n\n",
                                     "## Grid Constraints\n\n" + _RISK_LINE.format(sid=sid) + "\n\n", 1)
        return v3.ai(text, out=1500)

    def frame(self, call):
        line = next(line for _, content in call["messages"] for line in content.splitlines()
                    if "moratorium" in line and "10%" in line)
        marker = re.search(r"\[S(\d+)\]", line).group(1)
        return v3.ai(json.dumps({
            "base_rates": [], "drivers": [],
            "risks": [{"event": "Connection moratorium on new data-centre load", "probability": "10%",
                       "per": "per year", "source": f"S{marker}",
                       "effects": [{"metric": "Installed capacity", "change": "to 150 GW", "direction": "down"},
                                   {"metric": "Hyperscaler capex", "change": "-20%", "direction": "down"}],
                       "affects": ["Grid operator", "Hyperscaler A"], "recurring": False},
                      {"event": "Cooling-water ban", "probability": "3%", "per": "per year", "source": "S1"}],
        }))


_CFGS = [{"agent_id": 0, "entity_name": "Grid operator", "entity_type": "Organization"},
         {"agent_id": 1, "entity_name": "Hyperscaler A", "entity_type": "Organization"}]
_TIMELINE = {"as_of_date": "2026-09-27", "horizon_date": "2027-12-31"}


def test_e2e_a_documented_risk_reaches_actors_json_and_becomes_a_shock_the_world_can_fire(tmp_path, bridge):
    rc, meta, _, model, out = v3.run_engine(tmp_path, bridge, RiskWorld())
    assert rc == 0, meta.get("error")
    [frame_call] = v3.calls_of(model, "FORECAST FRAME EXTRACTION TASK")
    assert frame_call["messages"][-1][1] == _frame_prompt()
    # the task is the only volatile part: the extraction calls still share one cached prefix
    [actors_call] = v3.calls_of(model, "ACTOR EXTRACTION TASK")
    assert frame_call["messages"][:-1] == actors_call["messages"][:-1]

    body = lr.strip_references((out / "research_report.md").read_text(encoding="utf-8"))
    line = next(line for line in body.splitlines() if "moratorium" in line)
    number = int(re.search(r"\[S(\d+)\]", line).group(1))
    source = json.loads((out / "sources.json").read_text(encoding="utf-8"))[number - 1]
    actors = json.loads((out / "actors.json").read_text(encoding="utf-8"))
    [risk] = actors["forecast_inputs"]["risks"]
    assert risk == {"event": "Connection moratorium on new data-centre load", "probability": "10%",
                    "per": "per year", "source": f"{lr._collapse(source['title'], 120)} [S{number}]",
                    **{key: source[k] for key, k in (("source_url", "url"), ("tier", "tier")) if source.get(k)},
                    "effects": [{"metric": "Installed capacity", "change": "to 150 GW", "direction": "down"}],
                    "affects": ["Grid operator", "Hyperscaler A"], "recurring": False}
    assert json.loads((out / "meta.json").read_text(encoding="utf-8"))["forecast_risks"] == {
        **_ZERO, "extracted": 2, "kept": 1, "probability_not_stated": 1, "effects_kept": 1, "effects_untracked": 1}

    block = wms.build_world_model_seed(actors, _CFGS, temporal_timeline=_TIMELINE)
    [shock] = block["shocks"]
    assert shock["event"] == risk["event"] and shock["source"] == risk["source"]
    assert shock["base_rate"] == {"probability": 0.1, "window": "year", "window_days": 365.25, "text": "10%"}
    assert shock["effects"] == [{"variable_id": "installed_capacity", "variable": "Installed capacity", "op": "set",
                                 "value": 150.0, "direction": "down", "text": "to 150 GW"}]
    assert shock["affects"] == ["Grid operator", "Hyperscaler A"] and shock["recurring"] is False
    assert not [g for g in block["gaps"] if g["kind"] == "no_documented_shocks" or g["kind"].startswith("shock_")]

    world = WorldModel.from_seed(block, _CFGS, scenarios=block["scenarios"])
    world.start_round(1, {"label": "2026-10", "period_start": "2026-10-01", "period_end": "2026-10-31"})
    [fired] = world.fire_shocks(1, _RNG([0.0]))
    assert fired["event"] == risk["event"] and fired["affects"] == ["Grid operator", "Hyperscaler A"]
    assert fired["variables_changed"] == [{"id": "installed_capacity", "name": "Installed capacity",
                                           "from": 176.0, "to": 150.0, "unit": "GW"}]


def test_e2e_a_report_without_documented_risks_writes_an_empty_list(tmp_path, bridge, monkeypatch):
    rc, meta, _, model, out = v3.run_engine(tmp_path, bridge, v3.World())
    assert rc == 0, meta.get("error")
    assert len(v3.calls_of(model, "FORECAST FRAME EXTRACTION TASK")) == 1
    actors = json.loads((out / "actors.json").read_text(encoding="utf-8"))
    assert actors["forecast_inputs"]["risks"] == []
    assert json.loads((out / "meta.json").read_text(encoding="utf-8"))["forecast_risks"] == _ZERO
    block = wms.build_world_model_seed(actors, _CFGS, temporal_timeline=_TIMELINE)
    assert block["shocks"] == [] and block["gaps"][0]["kind"] == "no_documented_shocks"

    # without method skills no frame is extracted: the list is empty and meta has no checks
    monkeypatch.setenv("RESEARCH_SKILLS", "off")
    rc, meta, _, model, out = v3.run_engine(tmp_path, bridge, RiskWorld(), out_dir=tmp_path / "off")
    assert rc == 0, meta.get("error")
    assert not v3.calls_of(model, "FORECAST FRAME EXTRACTION TASK")
    assert json.loads((out / "actors.json").read_text(encoding="utf-8"))["forecast_inputs"]["risks"] == []
    assert "forecast_risks" not in json.loads((out / "meta.json").read_text(encoding="utf-8"))


# =============================================================== one row per stated probability (P1)
# Live check 2026-10-21 (docs/handoff/research-risks/handoff.md §7b, §12): pipe_fef5312f76f0's frame
# packed NOAA CPC's three window-specific odds into one probability string, which no line states, so the
# documented risk was dropped.  These are two lines of that run's report, verbatim but shortened.
CPC_LINES = (
    "CPC puts the probability that the event becomes historic — a three-month RONI of +2.5°C or higher, "
    "exceeding any El Niño since 1950 — at 54% for September–November 2026, 83% for October–December, and "
    "70% for November–January [S2].\n\n"
    "The ENSO Diagnostic Discussion, next due 12 November 2026, puts a greater-than-83% chance on "
    "strong-to-very-strong El Niño through January–March 2027, with historic-event probabilities of 54% "
    "(September–November), 83% (October–December) and 70% (November–January) [S2].\n")
# the row exactly as the live frame model returned it
CPC_ROW = {"event": "Historic-strength El Nino event (3-month RONI of +2.5C or higher)",
           "probability": "54% (Sep-Nov 2026); 83% (Oct-Dec); 70% (Nov-Jan)",
           "per": "per three-month window as stated", "source": "S2",
           "effects": [{"metric": "Henry Hub gas price", "change": "", "direction": "down"}],
           "affects": ["NOAA Climate Prediction Center"], "recurring": False}


def test_frame_prompt_asks_for_one_row_per_stated_probability_with_its_window_as_written():
    rule = next(line for line in _frame_prompt().splitlines() if line.startswith("- risks:"))
    for text in ("one probability per row, so probabilities the report states for several windows are several "
                 "rows, each with its own window",
                 "exactly as the report writes it in the sentence that states the probability",
                 '"October–December 2026"'):
        assert text in rule, text


@pytest.mark.parametrize("raw, parts", [
    ("54% (Sep-Nov 2026); 83% (Oct-Dec); 70% (Nov-Jan)",
     [("54%", "sep-nov 2026"), ("83%", "oct-dec"), ("70%", "nov-jan")]),
    ("54% for September–November, 83% for October–December and 70% for November–January",
     [("54%", "september–november"), ("83%", "october–december"), ("70%", "november–january")]),
    ("83% (Oct-Dec)", [("83%", "oct-dec")]),
    # never split: no window per percentage, a published range, a band with labelled ends, no number
    ("5%", []), ("54% and 83%", []), ("between 1% and 5%", []), ("between 1% (2026) and 5% (2027)", []),
    ("5% (low) to 25% (high)", []), ("5-25% (per year)", []), ("likely (Oct-Dec)", []), (0.05, []), (None, []),
])
def test_a_probability_with_a_window_per_percentage_splits_and_a_range_never_does(raw, parts):
    assert lr._probability_parts(raw) == parts


def test_a_probability_stated_for_several_windows_becomes_one_risk_per_window():
    risks, checks = _risks([CPC_ROW], report=REPORT + "\n" + CPC_LINES)
    assert [(r["event"], r["probability"], r["per"]) for r in risks] == [
        (f"{CPC_ROW['event']} (September–November 2026)", "54%", "September–November 2026"),
        (f"{CPC_ROW['event']} (October–December)", "83%", "October–December"),
        (f"{CPC_ROW['event']} (November–January)", "70%", "November–January"),
    ]
    # every part is a documented risk of its own: source, effects and actors as the row gives them
    assert {r["source"] for r in risks} == {"IEA risk note [S2]"}
    assert all(r["effects"] == [{"metric": "Henry Hub gas price", "change": "", "direction": "down"}]
               and r["affects"] == ["NOAA Climate Prediction Center"] for r in risks)
    assert checks == {**_ZERO, "extracted": 1, "split": 2, "kept": 3, "effects_kept": 3}


@pytest.mark.parametrize("probability, per, kept", [
    ("83%", "Oct-Dec", "October–December"),                  # the line's own phrase, not the abbreviation
    ("83%", "Oct-Dec 2026", "October–December"),             # a year only the model adds is dropped
    ("54%", "Sep–Nov", "September–November 2026"),           # the line's year is kept
    ("54%", "september-november 2026", "September–November 2026"),
    ("54%", "Sep-Nov 2025", "September–November"),           # the year-less line states the span, not 2025
    ("83%", "Q4 2026", "October–December"),                  # the same months, written another way
    ("83%", "OND 2026", "October–December"),
    ("54%", "Oct-Dec", ""),                                  # the window of another probability on the line
    ("70%", "Oct-Dec", ""),
    ("83%", "January–March 2027", "January–March 2027"),     # "greater-than-83% … through January–March 2027"
    ("83%", "Nov-Jan", ""),
    ("54%", "Sep-Nov 2027", "September–November"),           # the year-less line pairs it; its phrase rules
    ("83%", "the 2026 hurricane season", ""),                # not on the line, and no calendar span
])
def test_a_calendar_window_counts_when_its_span_stands_beside_the_probability_on_the_line(probability, per, kept):
    risks, checks = _risks([{**CPC_ROW, "probability": probability, "per": per}], report=REPORT + "\n" + CPC_LINES)
    [risk] = risks
    assert risk["per"] == kept and risk["probability"] == probability
    assert checks["window_not_stated"] == (not kept)


def test_a_window_without_a_calendar_span_counts_only_as_written_and_a_span_only_as_stated():
    report = REPORT + ("\nA court ruling against the merger carries a 40% probability within the review period [S3].\n"
                       "An appeal of the merger ruling has a 15% chance [S3].\n"
                       "CPC gives a historic El Niño a 54% chance for September–November 2026 [S2].\n")
    risks, checks = _risks([{"event": "Court ruling against the merger", "probability": "40%",
                             "per": "within the review period", "source": "S3"},
                            {"event": "Appeal of the merger ruling", "probability": "15%", "per": "Q1 2027",
                             "source": "S3"},
                            {"event": "Historic El Niño", "probability": "54%", "per": "Sep-Nov 2027",
                             "source": "S2"}], report=report)
    # the appeal's line states no span; the only line stating 54% names 2026, not the model's 2027
    assert [(r["probability"], r["per"]) for r in risks] == [("40%", "within the review period"), ("15%", ""),
                                                             ("54%", "")]
    assert checks["window_not_stated"] == 2


def test_cpc_season_codes_count_only_when_the_report_writes_them_in_capitals():
    report = REPORT + ("\nCPC gives a strong El Niño winter a 40% chance for DJF 2026-27 [S2].\n"
                       "Analysts gave the son of the founder a 12% chance of taking over [S3].\n")
    risks, _ = _risks([{"event": "Strong El Niño winter", "probability": "40%", "per": "Dec-Feb 2026-27",
                        "source": "S2"},
                       {"event": "Founder's son takes over", "probability": "12%", "per": "Sep-Nov",
                        "source": "S3"}], report=report)
    assert [(r["probability"], r["per"]) for r in risks] == [("40%", "DJF 2026-27"), ("12%", "")]


def test_a_probability_between_two_windows_of_equal_claim_keeps_neither():
    """"Since January 2026 … 23% … for Q1 2027": either window could be the probability's, so neither is
    taken; a day date ("next due 12 November 2026") is no window at all."""
    report = REPORT + ("\nSince January 2026 the grid emergency risk has stood at 23% for Q1 2027 [S1].\n"
                       "The next grid emergency review, due 12 November 2026, puts the risk at 9% [S1].\n")
    for probability, per in (("23%", "Q1 2027"), ("23%", "January 2026"), ("9%", "November 2026")):
        [risk], checks = _risks([{"event": "Grid emergency", "probability": probability, "per": per,
                                  "source": "S1"}], report=report)
        assert risk["per"] == "" and checks["window_not_stated"] == 1, (probability, per)


def test_a_chinese_window_is_checked_by_its_span():
    report = REPORT + "\n国际能源署估计，2026年10月至12月发生霍尔木兹海峡关闭的概率为15%[S2]。\n"
    risks, checks = _risks([{"event": "霍尔木兹海峡关闭", "probability": "15%", "per": "10月至12月", "source": "S2"},
                            {"event": "霍尔木兹海峡关闭", "probability": "15%", "per": "第四季度", "source": "S2"}],
                           report=report)
    assert [(r["probability"], r["per"]) for r in risks] == [("15%", "2026年10月至12月")]


# The research extraction and the world-model seed read the same calendar forms (the bridge runs in
# deer-flow's interpreter and cannot import the backend, so each keeps its own copy of the grammar).
_CALENDAR_PHRASES = [
    "Sep-Nov 2026", "September–November", "October–December 2026", "November–January 2026-27", "Nov–Jan 2027",
    "Nov 2026–Jan 2027", "December 2026–February", "DJF 2026-27", "djf 2026-27", "DJF 2027", "OND 2026", "SON",
    "Q1 2027", "q4", "the first quarter of 2027", "2027Q2", "2027-Q3", "to 30 Nov 2026", "by 31 March 2027",
    "by end-2027", "by the end of March 2027", "by 2030", "through March", "until November 30, 2026",
    "before 2027-06-30", "1 October to 31 December 2026", "15 December 2026 to 15 January", "January 2027",
    "May 2027", "may", "his son", "winter 2026-27", "the 2026 hurricane season", "per month", "within 12 months",
    "30 February 2027 to 1 March 2027", "10月至12月", "2026年10月至12月", "2026年11月至2027年1月",
    "2027年3月31日前", "截至2026年11月30日", "2026年底前", "2027年6月底前", "2027年第一季度", "2027年6月",
    "Oct-Dec; Jan-Mar", "12 November 2026", "next due 12th November 2026",
]


@pytest.mark.parametrize("phrase", _CALENDAR_PHRASES)
def test_the_research_extraction_and_the_seed_read_the_same_calendar_spans(phrase):
    assert lr._calendar_spec(phrase) == wms.calendar_window_spec(phrase)


def test_the_live_run_s_cpc_odds_reach_the_seed_as_three_dated_shocks():
    """pipe_fef5312f76f0 (as-of 2026-10-20, horizon 2027-01-31): the compound row of the live frame
    becomes three risks and the seed three shocks, each rolled only inside its own stretch."""
    risks, _ = _risks([CPC_ROW], report=REPORT + "\n" + CPC_LINES)
    dossier = {"as_of_date": "2026-10-20", "actors": [{"name": "NOAA Climate Prediction Center",
                                                       "type": "Organization"}],
               "quantitative_facts": [], "forecast_inputs": {"risks": risks}}
    shocks, gaps = wms.shocks_from_research(dossier, [], as_of="2026-10-20", horizon="2027-01-31")
    assert [(s["base_rate"]["window_start"], s["base_rate"]["window_end"], s["base_rate"]["probability"])
            for s in shocks] == [("2026-09-01", "2026-11-30", 0.54), ("2026-10-01", "2026-12-31", 0.83),
                                 ("2026-11-01", "2027-01-31", 0.7)]
    assert [s["hazard_per_day"] for s in shocks] == pytest.approx(
        [-math.log(0.46) / 91, -math.log(0.17) / 92, -math.log(0.3) / 92])
    assert len({s["id"] for s in shocks}) == 3
    assert [g["kind"] for g in gaps] == ["shock_effect_untracked"] * 3      # no tracked gas price here


_COMPOUND_LINE = ("The operator's outage outlook gives a grid emergency declaration a 23% probability for "
                  "November–January and 11% for February–April [S{sid}]. An emergency would cut installed "
                  "capacity to 150 GW [S{sid}].")


class CompoundRiskWorld(v3.World):
    """The grid-constraints section states one risk's probability for two windows; the frame reply
    packs both into one probability string, abbreviating the months and adding a year."""

    def writer(self, call):
        reply = super().writer(call)
        context = call["messages"][2][1]
        sid = re.findall(r"^\[S(\d+)\]", context.split("SOURCE INDEX", 1)[-1], re.M)[0]
        if "## Grid Constraints\n\n" not in reply.content:
            return reply
        text = reply.content.replace("## Grid Constraints\n\n",
                                     "## Grid Constraints\n\n" + _COMPOUND_LINE.format(sid=sid) + "\n\n", 1)
        return v3.ai(text, out=1500)

    def frame(self, call):
        line = next(line for _, content in call["messages"] for line in content.splitlines()
                    if "grid emergency" in line and "23%" in line)
        marker = re.search(r"\[S(\d+)\]", line).group(1)
        return v3.ai(json.dumps({
            "base_rates": [], "drivers": [],
            "risks": [{"event": "Grid emergency declaration", "probability": "23% (Nov-Jan); 11% (Feb-Apr 2027)",
                       "per": "", "source": f"S{marker}",
                       "effects": [{"metric": "Installed capacity", "change": "to 150 GW", "direction": "down"}],
                       "affects": ["Grid operator"], "recurring": False}],
        }))


def _month(label, start, end):
    return {"label": label, "period_start": start, "period_end": end}


def test_e2e_a_probability_stated_for_two_windows_becomes_two_dated_shocks_that_fire_only_inside_them(
        tmp_path, bridge):
    rc, meta, _, model, out = v3.run_engine(tmp_path, bridge, CompoundRiskWorld())
    assert rc == 0, meta.get("error")
    actors = json.loads((out / "actors.json").read_text(encoding="utf-8"))
    risks = actors["forecast_inputs"]["risks"]
    assert [(r["event"], r["probability"], r["per"]) for r in risks] == [
        ("Grid emergency declaration (November–January)", "23%", "November–January"),
        ("Grid emergency declaration (February–April)", "11%", "February–April"),
    ]
    assert json.loads((out / "meta.json").read_text(encoding="utf-8"))["forecast_risks"] == {
        **_ZERO, "extracted": 1, "split": 1, "kept": 2, "effects_kept": 2}

    # as-of 2026-09-27: each span is its first occurrence that has not ended yet
    block = wms.build_world_model_seed(actors, _CFGS, temporal_timeline=_TIMELINE)
    winter, spring = block["shocks"]
    assert (winter["base_rate"]["window_start"], winter["base_rate"]["window_end"]) == ("2026-11-01", "2027-01-31")
    assert (spring["base_rate"]["window_start"], spring["base_rate"]["window_end"]) == ("2027-02-01", "2027-04-30")
    assert winter["hazard_per_day"] == pytest.approx(-math.log(0.77) / 92)
    assert not [g for g in block["gaps"] if g["kind"] == "no_documented_shocks" or g["kind"].startswith("shock_")]

    world = WorldModel.from_seed(block, _CFGS, scenarios=block["scenarios"])
    world.start_round(1, _month("2026-10", "2026-10-01", "2026-10-31"))
    assert world.fire_shocks(1, _RNG([])) == []                 # before both stretches: not even a draw
    world.start_round(2, _month("2026-11", "2026-11-01", "2026-11-30"))
    [fired] = world.fire_shocks(2, _RNG([0.0]))                 # only the winter stretch rolls
    assert fired["event"] == winter["event"]
    assert fired["probability"] == pytest.approx(1 - math.exp(-winter["hazard_per_day"] * 30), abs=1e-6)
    assert fired["base_rate"] == "23% November–January (2026-11-01 to 2027-01-31)"
    assert fired["variables_changed"] == [{"id": "installed_capacity", "name": "Installed capacity",
                                           "from": 176.0, "to": 150.0, "unit": "GW"}]
    world.start_round(3, _month("2027-02", "2027-02-01", "2027-02-28"))
    assert world.fire_shocks(3, _RNG([0.99])) == []             # the spring stretch rolls and misses
    world.start_round(4, _month("2027-05", "2027-05-01", "2027-05-31"))
    assert world.fire_shocks(4, _RNG([])) == []                 # after it: no draw
