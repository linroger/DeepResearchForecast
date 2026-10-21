"""Exogenous shocks from research (reflexive world model, design §2.12).

Pins: the PREPARE-time seed turns only documented risks (event, probability, the window it refers to,
source) into shocks with a per-day hazard and records a typed gap for everything else — never an
invented probability; effects bind only to tracked facts; the kernel rolls each eligible shock once per
period with the injected RNG at the hazard's probability for that period's length, fires it once
unless documented as recurring, moves facts under the change clamp (bounded against the value before
this period's shocks, never across zero), and the shock reaches the next public and private briefs, the
affected actor's option menu and the arbiter as a confirmed event — reproducibly for a given seed.
"""

import math
import random
from datetime import date

import pytest

from app.services import world_model_seed as wms
from app.services import world_update as wu
from app.services.agent_decision import build_option_menu
from app.services.world_model import SHOCK_EVENT_SUFFIX, Shock, WorldModel, period_days

_OCT = {"label": "2026-10", "period_start": "2026-10-01", "period_end": "2026-10-31"}
_NOV = {"label": "2026-11", "period_start": "2026-11-01", "period_end": "2026-11-30"}
_HORMUZ_HAZARD = -math.log(0.95) / 30.4375          # "5% per month"


class _RNG:
    """Scripted ``random()`` draws; counts how many were taken."""

    def __init__(self, seq):
        self.seq = list(seq)
        self.draws = 0

    def random(self):
        self.draws += 1
        return self.seq.pop(0)


# ============================================================================ seed
def _dossier(risks):
    return {
        "as_of_date": "2026-10-01",
        "actors": [{"name": "Saudi Aramco", "type": "Organization", "role": "producer"},
                   {"name": "OPEC Secretariat", "type": "Organization", "role": "cartel secretariat"}],
        "quantitative_facts": [
            {"metric": "Brent crude price", "value": "80", "unit": "USD", "as_of_date": "2026-09-30",
             "value_type": "actual", "source": "EIA"},
            {"metric": "OPEC+ spare capacity", "value": "4.5", "unit": "mb/d", "as_of_date": "2026-09-30",
             "value_type": "actual", "source": "IEA"},
        ],
        "forecast_inputs": {
            "base_rates": [{"reference_class": "Quarter averages above $100", "outcome_frequency": "22/79",
                            "basis": "EIA [S1]"}],
            "drivers": [{"variable": "Hormuz risk", "direction": "up", "why_it_matters": "supply"}],
            "risks": risks,
        },
    }


def _cfgs():
    return [{"agent_id": 0, "entity_name": "Saudi Aramco", "entity_type": "Company"},
            {"agent_id": 1, "entity_name": "OPEC Secretariat", "entity_type": "Organization"}]


_TIMELINE = {"as_of_date": "2026-10-01", "horizon_date": "2027-03-31"}


def test_documented_risks_become_shocks_and_the_rest_become_gaps():
    risks = [
        {"event": "Strait of Hormuz closure", "probability": "5%", "per": "month", "source": "IEA risk note [S3]",
         "effects": [{"metric": "Brent crude price", "change": "+30%"},
                     {"metric": "Global GDP growth", "change": "-1%"}],
         "affects": ["Saudi Aramco", "Unknown Actor"]},
        {"event": "Ceasefire collapse", "probability": "2 of 10 years", "basis": "own count [S4]",
         "effects": [{"metric": "OPEC+ spare capacity", "direction": "down"}]},
        {"event": "Tanker insurance crisis", "probability": 0.3, "window": "over the forecast horizon",
         "source": "Lloyd's [S7]", "recurring": True},
        {"event": "Snap embargo", "probability": "1 in 20", "source": "S2"},                     # no window
        {"event": "Refinery fire", "probability": "10% per quarter"},                             # no source
        {"event": "Price war", "per": "month", "source": "S5"},                                   # no probability
        {"event": "OPEC meeting held", "probability": 1.0, "per": "month", "source": "OPEC"},     # certain
    ]
    block = wms.build_world_model_seed(_dossier(risks), _cfgs(), temporal_timeline=_TIMELINE)
    shocks = {s["id"]: s for s in block["shocks"]}
    assert list(shocks) == ["shock_strait_of_hormuz_closure", "shock_ceasefire_collapse",
                            "shock_tanker_insurance_crisis"]
    hormuz = shocks["shock_strait_of_hormuz_closure"]
    assert hormuz["base_rate"] == {"probability": 0.05, "window": "month", "window_days": 30.4375, "text": "5%"}
    assert hormuz["hazard_per_day"] == pytest.approx(_HORMUZ_HAZARD)
    assert hormuz["source"] == "IEA risk note [S3]" and hormuz["affects"] == ["Saudi Aramco"]
    assert hormuz["effects"] == [{"variable_id": "brent_crude_price", "variable": "Brent crude price", "op": "mul",
                                  "value": 1.3, "direction": "up", "text": "+30%"}]
    assert hormuz["recurring"] is False
    ceasefire = shocks["shock_ceasefire_collapse"]          # "2 of 10 years" counts years: 20% per year
    assert ceasefire["base_rate"]["window"] == "year" and ceasefire["base_rate"]["probability"] == 0.2
    assert ceasefire["effects"][0]["op"] is None and ceasefire["effects"][0]["direction"] == "down"
    tanker = shocks["shock_tanker_insurance_crisis"]        # the horizon is 181 days from the as-of date
    assert tanker["base_rate"]["window"] == "horizon" and tanker["base_rate"]["window_days"] == 181.0
    assert tanker["hazard_per_day"] == pytest.approx(-math.log(0.7) / 181.0) and tanker["recurring"] is True
    # what fell short is a typed gap, listed before the actor gaps; no shock without its documentation
    kinds = [(g["kind"], g["subject"]) for g in block["gaps"]]
    assert kinds[:6] == [
        ("shock_effect_untracked", "Strait of Hormuz closure"),
        ("shock_effect_direction_only", "Ceasefire collapse"),
        ("shock_without_window", "Snap embargo"),
        ("shock_without_source", "Refinery fire"),
        ("shock_without_base_rate", "Price war"),
        ("shock_without_base_rate", "OPEC meeting held"),
    ]
    assert "no_documented_shocks" not in {g["kind"] for g in block["gaps"]}
    # the base rates of the forecast question are the share prior, never shocks
    assert not any("Quarter averages" in s["event"] for s in block["shocks"])


_FACTS = [{"id": "brent", "name": "Brent crude price", "value": 80.0, "unit": "USD", "kind": "numeric"},
          {"id": "tariff", "name": "Tariff rate", "value": 20.0, "unit": "%", "kind": "numeric"},
          {"id": "status", "name": "Strait status", "value": "open", "unit": "", "kind": "text"}]


@pytest.mark.parametrize("effect,expected", [
    ({"metric": "Brent crude price", "change": "+30%"}, ("mul", 1.3, "up")),
    ({"metric": "Brent crude price", "change": "30%", "direction": "down"}, ("mul", 0.7, "down")),
    ({"metric": "Brent", "change": "to 150"}, ("set", 150.0, "up")),
    ({"metric": "Brent crude price", "delta": -12}, ("add", -12.0, "down")),
    ({"metric": "Tariff rate", "change": "+50 bp"}, ("add", 0.5, "up")),
    ({"metric": "Tariff rate", "change": "+5 pp"}, ("add", 5.0, "up")),
    ({"metric": "Strait status", "change": "to closed"}, ("set", "closed", "")),
    # no size is guessed: a percentage of a percentage, a range, a percent-valued delta of a price
    ({"metric": "Tariff rate", "change": "+30%"}, (None, None, "up")),
    ({"metric": "Brent crude price", "change": "+30% to +50%", "direction": "up"}, (None, None, "up")),
    ({"metric": "Brent crude price", "delta": "-5%", "direction": "down"}, (None, None, "down")),
    ({"metric": "Brent crude price", "direction": "up"}, (None, None, "up")),
    # dropped: untracked fact, contradiction, a wipe-out, nothing stated
    ({"metric": "Global GDP growth", "change": "-1%"}, None),
    ({"metric": "Brent crude price", "change": "+5", "direction": "down"}, None),
    ({"metric": "Brent crude price", "change_pct": -150}, None),
    ({"metric": "Brent crude price", "delta": "-5%"}, None),
])
def test_effect_sizes_are_documented_or_left_to_the_arbiter(effect, expected):
    gaps = []
    row = wms._shock_effect(effect, _FACTS, lambda kind, note: gaps.append(kind))
    if expected is None:
        assert row is None and gaps and gaps[0] in ("shock_effect_untracked", "shock_effect_unreadable")
        return
    assert (row["op"], row["value"], row["direction"]) == expected
    assert gaps == ([] if expected[0] is not None else ["shock_effect_direction_only"])


def test_no_documented_risk_records_a_gap_and_invents_nothing():
    dossier = _dossier([])
    del dossier["forecast_inputs"]["risks"]
    block = wms.build_world_model_seed(dossier, _cfgs(), temporal_timeline=_TIMELINE)
    assert block["shocks"] == []
    assert block["gaps"][0] == {"kind": "no_documented_shocks", "subject": "world",
                                "note": "no risk is documented with a probability, its window and a source; "
                                        "the world has no exogenous shocks"}
    assert WorldModel.from_seed(block, _cfgs()).shocks == []
    # a block sealed before 2026-10-20 has no ``shocks`` key and reports no shock gap
    assert all(g["kind"] != "no_documented_shocks" for g in wms.seed_gaps({"state_variables": [], "actors": []}))


@pytest.mark.parametrize("raw,expected", [
    (0.05, 0.05), ("5%", 0.05), ("1 in 20", 0.05), ("2 of 10 years", 0.2), ("3/20", 0.15), ("0.05", 0.05),
    ("about 7% of years", 0.07), (1.5, None), ("150%", None), (True, None), (None, None), ("likely", None),
    ("5", None),
])
def test_risk_probability_parsing(raw, expected):
    got = wms.parse_risk_probability(raw)
    assert got == pytest.approx(expected) if expected is not None else got is None


@pytest.mark.parametrize("raw,expected", [
    ("per month", ("month", 30.4375)), ("5% a year", ("year", 365.25)), ("within 9 months", ("9 month", 273.9375)),
    ("2 of 10 years", ("year", 365.25)), ("1 in 20 years", ("year", 365.25)), ("quarterly", ("quarter", 91.3125)),
    ("semiannual", ("half_year", 182.625)), ("over the forecast horizon", ("horizon", 181.0)), ("每月", ("month", 30.4375)),
    ("5年内", ("5 year", 1826.25)), ("2027年6月", None), ("20% per term", None), ("by 2027-06-30", None), ("", None),
])
def test_risk_window_parsing(raw, expected):
    assert wms.parse_risk_window(raw, horizon_days=181.0) == expected


def test_horizon_window_needs_known_dates():
    assert wms.parse_risk_window("over the horizon", horizon_days=None) is None


# ============================================================================ kernel
def _world(shocks, *, ratio=0.5):
    seed = {
        "question": "Will Brent average above $100 in Q2 2027?",
        "scenarios": ["Spike", "Calm"],
        "state_variables": [{"name": "Brent crude price", "value": 80, "unit": "USD", "provenance": "research"},
                            {"name": "Strait status", "value": "open", "kind": "categorical"}],
        "actors": [{"agent_id": 0, "name": "Saudi Aramco", "agency_class": "firm"},
                   {"agent_id": 1, "name": "OPEC Secretariat", "agency_class": "intergovernmental_org"}],
        "settings": {"max_change_ratio": ratio},
        "shocks": shocks,
    }
    return WorldModel.from_seed(seed, _cfgs(), scenarios=["Spike", "Calm"])


def _shock(sid, *, hazard=_HORMUZ_HAZARD, effects=(), affects=(), recurring=False, event=None):
    return {"id": sid, "event": event or sid.replace("_", " "), "hazard_per_day": hazard,
            "base_rate": {"probability": 0.05, "window": "month", "window_days": 30.4375, "text": "5%"},
            "source": "IEA risk note [S3]", "effects": list(effects), "affects": list(affects), "recurring": recurring}


_HORMUZ = _shock("hormuz", event="Strait of Hormuz closure", affects=["Saudi Aramco"],
                 effects=[{"variable_id": "brent_crude_price", "op": "mul", "value": 1.3, "direction": "up"},
                          {"variable_id": "strait_status", "op": "set", "value": "closed"}])


def test_period_probability_follows_the_documented_hazard():
    shock = Shock.from_dict(_HORMUZ)
    assert period_days(_OCT) == 31 and period_days({"label": "x"}) is None
    assert shock.period_probability(30.4375) == pytest.approx(0.05)
    assert shock.period_probability(31) == pytest.approx(1 - 0.95 ** (31 / 30.4375))
    assert shock.period_probability(91.3125) == pytest.approx(1 - 0.95 ** 3)          # a quarter: three months
    assert shock.base_rate_text() == "5% per month"


def test_fired_shock_is_an_emergent_event_with_clamped_effects():
    world = _world([_HORMUZ])
    world.start_round(1, _OCT)
    rng = _RNG([0.01])
    fired = world.fire_shocks(1, rng)
    assert rng.draws == 1
    assert fired == [{"id": "hormuz", "event": "Strait of Hormuz closure",
                      "probability": round(1 - 0.95 ** (31 / 30.4375), 6), "base_rate": "5% per month",
                      "source": "IEA risk note [S3]",
                      "variables_changed": [{"id": "brent_crude_price", "name": "Brent crude price", "from": 80.0,
                                             "to": 104.0, "unit": "USD"},
                                            {"id": "strait_status", "name": "Strait status", "from": "open",
                                             "to": "closed", "unit": ""}],
                      "to_size": [], "affects": ["Saudi Aramco"]}]
    [event] = world.events_in_round(1, ("emergent",))
    assert event.description == "Strait of Hormuz closure" + SHOCK_EVENT_SUFFIX and event.source == "shock"
    assert event.targets == ["Saudi Aramco"] and event.actors == []
    assert event.variable_ids == ["brent_crude_price", "strait_status"]
    assert world.variables["brent_crude_price"].history[-1] == {"round": 1, "value": 104.0,
                                                                "cause": "shock: Strait of Hormuz closure",
                                                                "source": "shock"}
    # once fired it is never rolled again (no draw is spent on it)
    world.start_round(2, _NOV)
    rng2 = _RNG([0.0])
    assert world.fire_shocks(2, rng2) == [] and rng2.draws == 0


def test_shocks_roll_in_seed_order_and_miss_without_effects():
    world = _world([_shock("a"), _shock("b"), _shock("c")])
    world.start_round(1, _OCT)
    rng = _RNG([0.9, 0.02, 0.9])
    assert [s["id"] for s in world.fire_shocks(1, rng)] == ["b"] and rng.draws == 3
    assert world.variables["brent_crude_price"].value == 80.0      # no documented effect → no fact moves


def test_shocks_on_one_fact_are_bounded_together_and_never_cross_zero():
    up = [{"variable_id": "brent_crude_price", "op": "mul", "value": 1.3, "direction": "up"}]
    double = [{"variable_id": "brent_crude_price", "op": "add", "value": 80, "direction": "up"}]
    world = _world([_shock("a", effects=up), _shock("b", effects=double)])
    world.start_round(1, _OCT)
    world.fire_shocks(1, _RNG([0.0, 0.0]))
    # +30% → 104, then +80 would reach 184: both are bounded by ±50% of the pre-shock 80
    assert world.variables["brent_crude_price"].value == 120.0
    crash = [{"variable_id": "brent_crude_price", "op": "set", "value": -50, "direction": "down"}]
    loose = _world([_shock("c", effects=crash)], ratio=5.0)
    loose.start_round(1, _OCT)
    loose.fire_shocks(1, _RNG([0.0]))
    assert loose.variables["brent_crude_price"].value == 0.0        # a shock never flips a fact's sign


def test_direction_only_effect_is_left_to_the_arbiter():
    vague = [{"variable_id": "brent_crude_price", "op": None, "value": None, "direction": "up"}]
    world = _world([_shock("a", effects=vague)])
    world.start_round(1, _OCT)
    [row] = world.fire_shocks(1, _RNG([0.0]))
    assert row["variables_changed"] == [] and row["to_size"] == ["Brent crude price up"]
    assert world.variables["brent_crude_price"].value == 80.0


def test_recurring_shock_can_fire_again_and_switch_off_stops_rolls():
    world = _world([_shock("a", recurring=True)])
    world.start_round(1, _OCT)
    assert len(world.fire_shocks(1, _RNG([0.0]))) == 1
    world.start_round(2, _NOV)
    assert len(world.fire_shocks(2, _RNG([0.0]))) == 1
    assert world.shocks[0].fired_rounds == [1, 2]
    off = _world([_shock("a")])
    off.settings["shocks_enabled"] = False
    off.start_round(1, _OCT)
    rng = _RNG([0.0])
    assert off.fire_shocks(1, rng) == [] and rng.draws == 0
    undated = _world([_shock("a")])
    undated.start_round(1, {"label": "2026-10"})                    # no period length → no probability
    assert undated.fire_shocks(1, _RNG([0.0])) == []
    assert _world([_shock("a")]).fire_shocks(1, None) == []         # no RNG → nothing fires (never raises)


def test_shock_rolls_are_reproducible_and_match_the_base_rate():
    hazard = -math.log(0.8) / 31                                     # 20% for a 31-day period
    fired = 0
    for seed in range(2000):
        world = _world([_shock("a", hazard=hazard)])
        world.start_round(1, _OCT)
        fired += len(world.fire_shocks(1, random.Random(seed)))
    assert abs(fired / 2000 - 0.2) < 0.027                           # 3 standard errors of a 2,000-draw mean
    runs = []
    for _ in range(2):
        world = _world([_shock("a", hazard=hazard), _shock("b", hazard=hazard, recurring=True)])
        hits = []
        for rnd, period in ((1, _OCT), (2, _NOV)):
            world.start_round(rnd, period)
            hits.append([s["id"] for s in world.fire_shocks(rnd, random.Random(41 * 1000003 + rnd))])
        runs.append((hits, world.to_dict()))
    assert runs[0] == runs[1]


def test_shocks_survive_a_save_and_load_and_worlds_without_them_serialise_as_before():
    world = _world([_HORMUZ])
    world.start_round(1, _OCT)
    world.fire_shocks(1, _RNG([0.0]))
    again = WorldModel.from_dict(world.to_dict())
    assert [s.to_dict() for s in again.shocks] == [s.to_dict() for s in world.shocks]
    assert again.shocks[0].fired_rounds == [1]
    assert "shocks" not in _world([]).to_dict()


# ============================================================================ visibility
class _Arbiter:
    def __init__(self):
        self.prompts = []
        self.temperatures = []

    def chat_json(self, messages, temperature=0.3, max_tokens=2200, **kwargs):
        self.prompts.append(messages[-1]["content"])
        self.temperatures.append(temperature)
        return {"narrative": "Tankers reroute around the Cape.", "variable_changes": [], "events": [],
                "scenario_pressure": {"Spike": "up"}}


def test_shock_reaches_the_arbiter_the_briefs_and_the_menu():
    world = _world([_HORMUZ])
    arbiter = _Arbiter()
    before = world.snapshot()
    record = wu.run_world_round(world, 1, _OCT, [], [{"date": "2026-10-05", "content": "[2026-10-05] OPEC meets"}],
                                llm=arbiter, rng=_RNG([0.0]), scenarios=["Spike", "Calm"])
    [prompt] = arbiter.prompts
    assert arbiter.temperatures == [0.3]
    confirmed = prompt.split("## Confirmed events this period\n", 1)[1].split("\n\n", 1)[0]
    assert confirmed == (
        "- [2026-10-05] OPEC meets\n"
        "- Exogenous shock: Strait of Hormuz closure (a researched risk that materialised this period; documented "
        "base rate 5% per month, source: IEA risk note [S3]). Already applied within the per-period limit: Brent "
        "crude price USD80 → USD104; Strait status open → closed. Hits: Saudi Aramco.")
    assert record["deterministic"]["shocks_fired"][0]["id"] == "hormuz"
    assert "Strait of Hormuz closure" + SHOCK_EVENT_SUFFIX in record["digest"]
    # the next public brief: the fact moved and the event is listed; no scenario share anywhere
    brief = world.render_public_brief(upto_round=1, previous=before)
    assert "- Brent crude price: USD104 (was USD80 last period)" in brief
    assert ("## Consequences and events\n- [2026-10-05] OPEC meets\n- Strait of Hormuz closure"
            + SHOCK_EVENT_SUFFIX) in brief
    assert "Spike" not in brief and "%" not in brief
    # the hit actor sees it aimed at it and gets shock responses, not "Counter another actor's move"
    world.start_round(2, _NOV)
    private = world.render_private_brief(0, upto_round=1)
    assert "- Aimed at you last period:\n  · Strait of Hormuz closure" + SHOCK_EVENT_SUFFIX in private
    menu = build_option_menu(world.actors[0], world, 2)
    ids = [o["id"] for o in menu]
    assert ids[:3] == ["respond_1_contain", "respond_1_adapt", "respond_1_accommodate"]
    assert menu[0]["label"].startswith("Contain the fallout of: Strait of Hormuz closure")
    assert not any(o["id"].endswith("_counter") or "another actor's move" in o["label"] for o in menu)
    assert "Strait of Hormuz" not in "".join(o["label"] for o in build_option_menu(world.actors[1], world, 2))


def test_world_without_shocks_keeps_its_round_record_and_prompt():
    world = _world([])
    arbiter = _Arbiter()
    record = wu.run_world_round(world, 1, _OCT, [], [], llm=arbiter, rng=_RNG([]), scenarios=["Spike", "Calm"])
    assert "shocks_fired" not in record["deterministic"]
    assert "Confirmed events this period" not in arbiter.prompts[0]


# ============================================================================ dated windows
# docs/handoff/research-risks/handoff.md §12 P2: published outlooks give a probability for a stretch of the
# calendar ("83% October–December"); the shock then fires only inside that stretch.
_D = date.fromisoformat


@pytest.mark.parametrize("raw, as_of, span", [
    ("October–December 2026", "2026-10-20", ("2026-10-01", "2026-12-31")),
    ("October–December 2026", None, ("2026-10-01", "2026-12-31")),          # a written year needs no as-of date
    ("Oct-Dec", "2026-10-20", ("2026-10-01", "2026-12-31")),
    ("September–November", "2026-10-20", ("2026-09-01", "2026-11-30")),       # partly over: still this one
    ("September–November", "2026-12-15", ("2027-09-01", "2027-11-30")),       # over: the next one
    ("November–January", "2026-10-20", ("2026-11-01", "2027-01-31")),
    ("November–January 2026-27", None, ("2026-11-01", "2027-01-31")),
    ("Nov 2026–Jan 2027", None, ("2026-11-01", "2027-01-31")),
    ("December 2026–February", None, ("2026-12-01", "2027-02-28")),
    ("DJF 2026-27", None, ("2026-12-01", "2027-02-28")),
    ("DJF", "2026-10-20", ("2026-12-01", "2027-02-28")),
    ("JFM 2028", None, ("2028-01-01", "2028-03-31")),
    ("Q1 2027", None, ("2027-01-01", "2027-03-31")),
    ("the first quarter of 2027", None, ("2027-01-01", "2027-03-31")),
    ("2027Q2", None, ("2027-04-01", "2027-06-30")),
    ("Q4", "2026-10-20", ("2026-10-01", "2026-12-31")),
    ("January 2027", None, ("2027-01-01", "2027-01-31")),
    ("in 2027", None, ("2027-01-01", "2027-12-31")),
    ("calendar year 2027", None, ("2027-01-01", "2027-12-31")),
    ("1 October to 31 December 2026", None, ("2026-10-01", "2026-12-31")),
    ("15 December 2026 to 15 January", None, ("2026-12-15", "2027-01-15")),
    ("by 31 March 2027", "2026-10-20", ("2026-10-20", "2027-03-31")),        # "until" runs from the as-of date
    ("to 30 Nov 2026", "2026-10-20", ("2026-10-20", "2026-11-30")),
    ("until November 30, 2026", "2026-10-20", ("2026-10-20", "2026-11-30")),
    ("through March", "2026-10-20", ("2026-10-20", "2027-03-31")),
    ("by the end of March 2027", "2026-10-20", ("2026-10-20", "2027-03-31")),
    ("by end-2027", "2026-10-20", ("2026-10-20", "2027-12-31")),
    ("before 2027-06-30", "2026-10-20", ("2026-10-20", "2027-06-30")),
    ("10月至12月", "2026-10-20", ("2026-10-01", "2026-12-31")),
    ("2026年11月至2027年1月", None, ("2026-11-01", "2027-01-31")),
    ("2027年3月31日前", "2026-10-20", ("2026-10-20", "2027-03-31")),
    ("截至2026年11月30日", "2026-10-20", ("2026-10-20", "2026-11-30")),
    ("2026年底前", "2026-10-20", ("2026-10-20", "2026-12-31")),
    ("2027年第一季度", None, ("2027-01-01", "2027-03-31")),
    ("2027年6月", None, ("2027-06-01", "2027-06-30")),
    ("October–December 2025", "2026-10-20", ("2025-10-01", "2025-12-31")),   # read; the seed calls it elapsed
    # ambiguous, unplaceable or no stretch at all: never a guess
    ("Nov–Jan 2027", "2026-10-20", None), ("DJF 2027", "2026-10-20", None), ("djf 2026-27", None, None),
    ("by 2030", "2026-10-20", None), ("Oct-Dec", None, None), ("by 31 March 2027", None, None),
    ("winter 2026-27", "2026-10-20", None), ("the 2026 hurricane season", "2026-10-20", None),
    ("12 November 2026", "2026-10-20", None), ("per month", "2026-10-20", None),
    ("within 12 months", "2026-10-20", None), ("Oct-Dec; Jan-Mar", "2026-10-20", None),
    ("30 February 2027 to 1 March 2027", None, None), ("2016–2025", None, None), ("", "2026-10-20", None),
])
def test_dated_window_parsing(raw, as_of, span):
    got = wms.parse_dated_window(raw, as_of=as_of)
    assert got == (tuple(_D(d) for d in span) if span else None)


@pytest.mark.parametrize("raw, expected", [
    ("a three-month window", ("3 month", 91.3125)), ("over a two-year period", ("2 year", 730.5)),
    ("twelve months", ("12 month", 365.25)), ("two of ten years", ("year", 365.25)),
])
def test_spelled_out_counts_are_counts_not_the_bare_unit(raw, expected):
    """"Three-month" was read as "per month" (a hazard three times too high)."""
    assert wms.parse_risk_window(raw) == expected


_WINTER_TIMELINE = {"as_of_date": "2026-10-01", "horizon_date": "2027-03-31"}


def test_dated_risks_become_shocks_for_their_stretch_and_the_rest_become_gaps():
    risks = [
        {"event": "Historic El Niño", "probability": "83%", "per": "October–December", "source": "CPC [S2]"},
        {"event": "Historic El Niño", "probability": "70%", "per": "November–January", "source": "CPC [S2]"},
        {"event": "Gulf hurricane landfall", "probability": "5%", "per": "to 30 November 2026", "source": "NOAA [S3]"},
        {"event": "Wellhead freeze-off", "probability": "10%", "per": "per month through March 2027",
         "source": "EIA [S4]"},
        {"event": "Polar vortex", "probability": "20%", "per": "December–February 2025-26", "source": "CPC [S2]"},
        {"event": "Heat dome", "probability": "30%", "per": "June–August 2027", "source": "CPC [S2]"},
        {"event": "Cold winter", "probability": "40%", "per": "winter 2026-27", "source": "CPC [S2]"},
    ]
    block = wms.build_world_model_seed(_dossier(risks), _cfgs(), temporal_timeline=_WINTER_TIMELINE)
    shocks = {s["id"]: s for s in block["shocks"]}
    assert list(shocks) == ["shock_historic_el_niño_202610_202612", "shock_historic_el_niño_202611_202701",
                            "shock_gulf_hurricane_landfall_202610_202611", "shock_wellhead_freeze_off_202610_202703"]
    ond = shocks["shock_historic_el_niño_202610_202612"]
    assert ond["base_rate"] == {"probability": 0.83, "window": "dated", "window_days": 92.0, "text": "83%",
                                "window_start": "2026-10-01", "window_end": "2026-12-31",
                                "window_text": "October–December"}
    assert ond["hazard_per_day"] == pytest.approx(-math.log(0.17) / 92)
    hurricane = shocks["shock_gulf_hurricane_landfall_202610_202611"]      # "to <date>" runs from the as-of date
    assert (hurricane["base_rate"]["window_start"], hurricane["base_rate"]["window_end"]) == ("2026-10-01",
                                                                                             "2026-11-30")
    assert hurricane["hazard_per_day"] == pytest.approx(-math.log(0.95) / 61)
    freeze = shocks["shock_wellhead_freeze_off_202610_202703"]             # a rate per month, until March
    assert freeze["base_rate"]["window"] == "month" and freeze["base_rate"]["window_end"] == "2027-03-31"
    assert freeze["hazard_per_day"] == pytest.approx(-math.log(0.9) / 30.4375)
    kinds = [(g["kind"], g["subject"]) for g in block["gaps"]]
    assert kinds[:3] == [("shock_window_elapsed", "Polar vortex"), ("shock_window_after_horizon", "Heat dome"),
                         ("shock_without_window", "Cold winter")]
    assert "no_documented_shocks" not in {g["kind"] for g in block["gaps"]}


def _dated(sid, start, end, *, p=0.83, window="dated", days=92.0, text="October–December", recurring=False):
    hazard = -math.log(1 - p) / days
    return {"id": sid, "event": sid.replace("_", " "), "hazard_per_day": hazard,
            "base_rate": {"probability": p, "window": window, "window_days": days, "text": f"{p:.0%}",
                          "window_start": start, "window_end": end, "window_text": text},
            "source": "CPC [S2]", "effects": [], "affects": [], "recurring": recurring}


def test_a_dated_shock_rolls_only_on_the_days_a_period_shares_with_its_stretch():
    shock = Shock.from_dict(_dated("el_nino", "2026-10-01", "2026-12-31"))
    assert shock.active_days(_month_period("2026-09-01", "2026-09-30")) == 0
    assert shock.active_days(_OCT) == 31
    assert shock.active_days(_month_period("2026-12-15", "2027-01-14")) == 17
    assert shock.active_days({"label": "x"}) is None
    # a shock without a stretch fires over every whole period, as before
    assert Shock.from_dict(_HORMUZ).active_days(_OCT) == 31 and Shock.from_dict(_HORMUZ).window_start is None
    # a malformed stretch is no stretch
    broken = Shock.from_dict(_dated("x", "2026-12-31", "2026-10-01"))
    assert broken.window_start is None and broken.active_days(_OCT) == 31

    world = _world([_dated("el_nino", "2026-10-01", "2026-12-31", recurring=True)])
    rng = _RNG([0.99, 0.99, 0.99])
    for rnd, (start, end) in enumerate((("2026-09-01", "2026-09-30"), ("2026-10-01", "2026-10-31"),
                                        ("2026-12-15", "2027-01-14"), ("2027-01-15", "2027-02-14")), 1):
        world.start_round(rnd, _month_period(start, end))
        assert world.fire_shocks(rnd, rng) == []
    assert rng.draws == 2                       # September and February take no draw; October and December do
    world.start_round(5, _month_period("2026-12-15", "2027-01-14"))
    [fired] = world.fire_shocks(5, _RNG([0.0]))
    assert fired["probability"] == pytest.approx(1 - math.exp(-world.shocks[0].hazard_per_day * 17), abs=1e-6)
    assert fired["base_rate"] == "83% October–December (2026-10-01 to 2026-12-31)"


def test_a_partly_elapsed_stretch_never_gets_its_whole_probability():
    """54% for September–November, sealed on 20 October: the remaining 42 days get 1 − 0.46^(42/91)."""
    world = _world([_dated("son", "2026-09-01", "2026-11-30", p=0.54, days=91.0, text="September–November")])
    world.start_round(1, _month_period("2026-10-20", "2026-11-30"))
    [fired] = world.fire_shocks(1, _RNG([0.0]))
    assert fired["probability"] == pytest.approx(1 - 0.46 ** (42 / 91), abs=1e-6)
    assert fired["probability"] < 0.54


def test_a_rate_per_unit_with_an_end_date_names_both():
    shock = Shock.from_dict(_dated("freeze", "2026-10-01", "2027-03-31", p=0.1, window="month", days=30.4375,
                                   text="per month through March 2027"))
    assert shock.base_rate_text() == "10% per month (2026-10-01 to 2027-03-31)"


def test_dated_shocks_survive_a_save_and_load():
    world = _world([_dated("el_nino", "2026-10-01", "2026-12-31")])
    again = WorldModel.from_dict(world.to_dict())
    [shock] = again.shocks
    assert (shock.window_start, shock.window_end) == (_D("2026-10-01"), _D("2026-12-31"))
    assert again.to_dict()["shocks"] == world.to_dict()["shocks"]


def _month_period(start, end):
    return {"label": start[:7], "period_start": start, "period_end": end}
