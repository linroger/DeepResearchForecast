"""Documented risks in the v3 forecast frame (``forecast_inputs.risks`` → world-model shocks).

Pins: with method skills the ``FORECAST FRAME EXTRACTION TASK`` asks for the risks the report itself
attaches a probability to, with that probability and its window exactly as written, the [S<n>]
marker of the statement and effects on quantities the report names; ``normalize_frame_risks`` keeps
a risk only when a line of the report states its probability and names the event, keeps its window
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
                           scenarios=["Hormuz closure", "Calm"])
    assert [r["event"] for r in risks] == ["Strait of Hormuz closure", "Tanker insurance crisis"]
    assert risks[1]["affects"] == [f"Insurer {i}" for i in range(lr.MAX_FRAME_RISK_AFFECTS)]
    assert risks[1]["recurring"] is False                       # only a JSON true says it recurs
    assert checks["scenario"] == 1 and checks["extracted"] == 4 and checks["kept"] == 2
    for frame in (None, [], "risks", {"risks": "x"}, {"risks": [1, None, {"event": 5}, {"event": ""}, ["x"]]},
                  {"base_rates": []}):
        assert lr.normalize_frame_risks(frame, REPORT, QUANT, SOURCES) == ([], _ZERO)


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
