"""RESEARCH-6: forecaster attribution in v3 fact extraction and cross-source
forecast-dispersion diagnostics (shadow only).

* RESEARCH_FORECASTER_ATTRIBUTION (default off): the facts task asks
  estimate/forecast/target rows for their forecaster, stated range and
  forecaster count; ``attribute_forecast_row`` keeps a bound only when its
  numbers are the report's, a count only next to a count noun, parses a
  range value into low/high and strips the keys from actual rows.
* REPORT_CONSENSUS_DIAGNOSTICS (off | shadow, default off): the report stage
  groups the research projections (``consensus_evidence``) and writes
  consensus_evidence.json plus forecast.quality.consensus, with zero model
  calls and no prompt, probability or gate change.

Both off: the facts prompt, quantitative.json and forecast.json are
byte-identical.  Offline: the scripted model and real bridge of
``test_research_engine_v3`` and the FakeLLMClient router of
``test_report_context_pack_wiring``.
"""

from __future__ import annotations

import copy
import datetime as dt
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

import pytest

import test_report_context_pack_wiring as packs
import test_research_engine_v3 as v3
from app.config import Config
from app.services import actor_context
from app.services import consensus_evidence as ce
from app.services import report_agent as ra
from app.services.hindcast_policy import HINDCAST_POLICY_VERSION
from test_orchestrator_research_wiring import _launch_capturing_child

# The shared fixtures (hermetic env, real bridge with network steps stubbed,
# report-stage Config pins).
_hermetic_env = v3._hermetic_env
bridge = v3.bridge
report_env = packs.report_env
lr = v3.lr
dr = v3.dr
po = v3.po

AS_OF = dt.date(2026, 9, 28)
CONSENSUS_KEYS = {"forecaster", "low", "high", "n_forecasters", "range_kind"}

# The report sentence the engine test's executive summary adds (its numbers
# are the provenance the kept bounds and count must match).
POLL_SENTENCE = ("A June 2025 poll of 40 economists puts 2030 capacity at 300 GW, with individual forecasts "
                 "from 260 to 340 GW [S{sid}]. Omdia expects utilisation of 52–56% by 2030 [S{sid}].")

FORECAST_FACTS = [
    # An actual row carrying consensus fields: none is kept, each is counted dropped.
    {"metric": "Installed capacity", "value": "176", "unit": "GW", "as_of_date": "2023-12-31",
     "value_type": "actual", "source_ref": "S1", "forecaster": "National energy agency", "low": "170",
     "high": "180", "n_forecasters": 0},
    # A poll: bounds and count stated in the report; the source (a publisher) stays.
    {"metric": "Data-centre capacity", "value": "300", "unit": "GW", "as_of_date": "2025-06",
     "period_end": "2030", "value_type": "forecast", "source": "Reuters", "source_ref": "S1",
     "forecaster": "Economist poll", "low": "260", "high": "340", "n_forecasters": 40},
    # The high bound is not on the report (both bounds go) and the count has no count noun.
    {"metric": "Grid-connected capacity", "value": "310", "unit": "GW", "as_of_date": "2025-06",
     "period_end": "2030", "value_type": "forecast", "source_ref": "S1", "forecaster": "Omdia",
     "low": "260", "high": "7,777", "n_forecasters": "12"},
    # A value written as a range, no bounds stated.
    {"metric": "Utilisation", "value": "52-56", "unit": "%", "as_of_date": "2025-06", "period_end": "2030",
     "value_type": "forecast", "source_ref": "S1", "forecaster": "Omdia", "low": "", "high": 0,
     "n_forecasters": 0},
]


class ForecastWorld(v3.World):
    """The standard world whose executive summary states a poll and whose
    facts reply carries forecaster fields."""

    def __init__(self, quant: list[dict] | None = None, **kwargs) -> None:
        super().__init__(**kwargs)
        self.quant = FORECAST_FACTS if quant is None else quant

    def exec_summary(self, call):
        sid = (re.findall(r"\[S(\d+)\]", call["messages"][2][1]) or ["1"])[0]
        body = (f"The Base case (50% probability) is most likely; capacity reached 176 GW in 2023 [S{sid}]. "
                "Accelerated build-out (30%) and Stalled expansion (20%) frame the tails. ") * 3
        return v3.ai(f"## Executive Summary\n\n{POLL_SENTENCE.format(sid=sid)}\n\n{body}")

    def facts(self, call):
        return v3.ai(json.dumps({
            "key_events": [{"date": "2023-12-31", "event": "Capacity reached 176 GW"}],
            "quantitative_facts": copy.deepcopy(self.quant), "contested_claims": []}))


@pytest.fixture
def fixed_as_of(monkeypatch):
    """The plan's as-of date (UTC today in production) pinned for stable dates."""
    monkeypatch.setattr(lr, "_utc_date", lambda: AS_OF.isoformat())


def _knobs(monkeypatch, *, attribution: bool, typing: bool = False, verify: bool = False) -> None:
    monkeypatch.setenv("RESEARCH_FORECASTER_ATTRIBUTION", "true" if attribution else "false")
    monkeypatch.setenv("RESEARCH_QUANT_TYPING", "true" if typing else "false")
    monkeypatch.setenv("RESEARCH_VERIFIED_FACTS", "true" if verify else "false")


def _plain_facts_task() -> str:
    return lr._render(lr._T_FACTS, max_events=lr.MAX_TIMELINE_ROWS, max_quant=lr.MAX_QUANT_ROWS,
                      max_contested=lr.MAX_CONTESTED_ROWS, language="English")


def _facts_tasks(model) -> list[str]:
    return [call["messages"][-1][1] for call in v3.calls_of(model, "FACT EXTRACTION TASK")]


def _load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _attributed(facts: list[dict], report: str) -> tuple[list[dict], list[str]]:
    """normalize_quant pairs through attribute_forecast_row: (rows, dropped names)."""
    numbers = lr.page_number_set(report)
    rows, dropped = [], []
    for row, item in lr.normalize_quant(copy.deepcopy(facts), [], with_items=True):
        dropped += lr.attribute_forecast_row(row, item, report, numbers)
        rows.append(row)
    return rows, dropped


# =============================================================== knobs and wiring

def test_knob_defaults_documented_forwarded_and_drift_clean(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "scripts"))
    import check_env_drift as drift

    defaults = drift.config_defaults()
    assert defaults["RESEARCH_FORECASTER_ATTRIBUTION"] == "false"
    assert defaults["REPORT_CONSENSUS_DIAGNOSTICS"] == "off"
    assert {"RESEARCH_FORECASTER_ATTRIBUTION", "REPORT_CONSENSUS_DIAGNOSTICS"} <= drift.documented_env_vars()
    strict = subprocess.run([sys.executable, drift.__file__, "--strict"], capture_output=True, text=True,
                            timeout=60)
    assert strict.returncode == 0, strict.stdout
    assert "RESEARCH_FORECASTER_ATTRIBUTION" in v3._ENV_EXACT
    assert ("RESEARCH_FORECASTER_ATTRIBUTION", "bool") in po.RESEARCH_CHILD_V3_KNOBS
    for name, value, expected in (("on", True, "true"), ("off", False, "false")):
        (tmp_path / name).mkdir()
        monkeypatch.setattr(po.Config, "RESEARCH_ENGINE", "v3", raising=False)
        monkeypatch.setattr(po.Config, "RESEARCH_FORECASTER_ATTRIBUTION", value, raising=False)
        monkeypatch.setenv("RESEARCH_FORECASTER_ATTRIBUTION", "false" if value else "true")  # ambient never decides
        child = _launch_capturing_child(monkeypatch, tmp_path / name, timeout=900)
        assert child["env"]["RESEARCH_FORECASTER_ATTRIBUTION"] == expected
    (tmp_path / "legacy").mkdir()
    monkeypatch.setattr(po.Config, "RESEARCH_ENGINE", "legacy", raising=False)
    monkeypatch.delenv("RESEARCH_FORECASTER_ATTRIBUTION", raising=False)
    child = _launch_capturing_child(monkeypatch, tmp_path / "legacy", timeout=900)
    assert "RESEARCH_FORECASTER_ATTRIBUTION" not in child["env"]


# =============================================================== attribution: pure

REPORT = ("A survey of 40 economists puts 2030 output at 250,000 units, with forecasts ranging from 38,000 "
          "to 1.2 million units [S1]. Omdia expects a 52–56% share by 2030 [S2]. 调查的40位经济学家给出区间。")


def _row(value="250,000", value_type="forecast", **extra):
    return {"metric": "Output", "value": value, "unit": "units", "value_type": value_type, **extra}


def test_bounds_on_the_report_are_kept_and_an_absent_high_is_dropped():
    numbers = lr.page_number_set(REPORT)
    kept = _row()
    assert lr.attribute_forecast_row(kept, {"forecaster": "Poll", "low": "38,000", "high": "1.2 million"},
                                     REPORT, numbers) == []
    assert (kept["low"], kept["high"]) == ("38,000", "1.2 million")      # kept as written
    assert "range_kind" not in kept                                     # a range without a count
    numeric = _row()
    assert lr.attribute_forecast_row(numeric, {"low": 38000, "high": 1200000.0}, REPORT, numbers) == []
    assert (numeric["low"], numeric["high"]) == (38000, 1200000.0)

    absent = _row()
    dropped = lr.attribute_forecast_row(absent, {"forecaster": "Poll", "low": "38,000", "high": "9,876"},
                                        REPORT, numbers)
    assert dropped == ["low", "high"]                                   # a lone bound is no range
    assert not {"low", "high", "range_kind"} & set(absent) and absent["forecaster"] == "Poll"


def test_low_above_high_or_a_value_outside_the_range_drops_both_bounds():
    numbers = lr.page_number_set(REPORT)
    inverted = _row()
    assert lr.attribute_forecast_row(inverted, {"low": "1.2 million", "high": "38,000"}, REPORT,
                                     numbers) == ["low", "high"]
    assert not {"low", "high"} & set(inverted)
    outside = _row(value="2 million")
    assert lr.attribute_forecast_row(outside, {"low": "38,000", "high": "1.2 million"}, REPORT,
                                     numbers) == ["low", "high"]
    unparsed = _row()
    assert lr.attribute_forecast_row(unparsed, {"low": "some", "high": "1.2 million"}, REPORT,
                                     numbers) == ["low", "high"]


@pytest.mark.parametrize("value, low, high", [("52-56", "52", "56"), ("52–56%", "52", "56"),
                                              ("52 to 56", "52", "56")])
def test_a_range_value_becomes_a_stated_range(value, low, high):
    row = _row(value=value)
    assert lr.attribute_forecast_row(row, {"forecaster": "Omdia", "low": "", "high": 0}, REPORT,
                                     lr.page_number_set(REPORT)) == []
    assert (row["low"], row["high"], row["range_kind"]) == (low, high, "stated_range")


def test_a_range_value_off_the_report_or_inverted_is_not_parsed():
    numbers = lr.page_number_set(REPORT)
    for value in ("61-64", "56-52"):
        row = _row(value=value)
        assert lr.attribute_forecast_row(row, {}, REPORT, numbers) == []
        assert not {"low", "high", "range_kind"} & set(row)


def test_n_forecasters_is_kept_only_next_to_a_count_noun():
    numbers = lr.page_number_set(REPORT)
    with_noun = _row()
    assert lr.attribute_forecast_row(with_noun, {"low": "38,000", "high": "1.2 million", "n_forecasters": 40},
                                     REPORT, numbers) == []
    assert with_noun["n_forecasters"] == 40 and with_noun["range_kind"] == "across_forecasters"
    bare = "Forecasts for 2030 range from 38,000 to 1.2 million units; 40 is the survey's page count."
    without_noun = _row()
    assert lr.attribute_forecast_row(without_noun, {"n_forecasters": "40"}, bare,
                                     lr.page_number_set(bare)) == ["n_forecasters"]
    assert "n_forecasters" not in without_noun
    for count in (1, "forty", 41, 2.5, True):
        row = _row()
        assert lr.attribute_forecast_row(row, {"n_forecasters": count}, REPORT, numbers) == ["n_forecasters"]
    assert lr._report_states_count(40, "a panel (n = 40) of forecasters")
    assert lr._report_states_count(40, "调查的40位经济学家")
    assert lr._report_states_count(1200, "1,200 respondents answered")
    assert not lr._report_states_count(40, "140 economists")
    assert not lr._report_states_count(40, "n = 40.5")


def test_numbers_beyond_the_float_range_are_dropped_not_raised():
    """A JSON integer like 10**400 overflows float(): only that field is
    dropped (the row keeps its forecaster), so one bad number no longer
    raises and costs every row of the run its attribution."""
    assert lr._magnitude(10 ** 400) is None and lr._magnitude(-(10 ** 400)) is None
    assert lr._magnitude("1" + "0" * 400) is None and lr._magnitude(10 ** 300) == 1e300
    numbers = lr.page_number_set(REPORT)
    row = _row()
    assert lr.attribute_forecast_row(row, {"forecaster": "Poll", "low": 10 ** 400, "high": "1.2 million",
                                           "n_forecasters": 10 ** 400}, REPORT, numbers) == [
        "low", "high", "n_forecasters"]
    assert row["forecaster"] == "Poll" and not {"low", "high", "n_forecasters"} & set(row)
    assert lr._forecaster_count(9_999_999) == 9_999_999 and lr._forecaster_count(10_000_000) is None


def test_a_bound_longer_than_a_value_is_refused_before_any_check():
    """Low/high text over a row value's 80-char cap is refused before any
    check, so a kept bound is always the text that was checked (never a cut
    that ends mid-number); a long digit run costs linear time, not
    quadratic (a 20,000-digit bound took ~11 s per row)."""
    long_number = "1" * 100
    report = f"Forecasts range from {long_number} to {long_number}1 units."
    numbers = lr.page_number_set(report)
    assert lr._checked_bound(long_number, numbers) is None
    row = _row(value="250,000")
    assert lr.attribute_forecast_row(row, {"low": long_number, "high": long_number + "1"}, report,
                                     numbers) == ["low", "high"]
    assert not {"low", "high"} & set(row)
    # The kept text is the collapsed text the check read.
    assert lr._checked_bound(" 38,000\n", lr.page_number_set(REPORT)) == ("38,000", 38000.0)

    huge = "1" * 20000
    started = time.perf_counter()
    assert lr._RANGE_PAIR_RE.search(huge + "x") is None and lr._magnitude(huge) is None
    assert lr.attribute_forecast_row(_row(), {"low": huge, "high": huge}, REPORT,
                                     lr.page_number_set(REPORT)) == ["low", "high"]
    assert time.perf_counter() - started < 2.0
    # Anchoring the pair at a digit run keeps every reading.
    assert lr._magnitude("1.2-1.5 trillion") == pytest.approx(1.35e12) and lr._magnitude("52–56%") == 54
    assert lr._magnitude("about 3 to 5") == 4 and lr._magnitude("-2.5") == -2.5


def test_actual_rows_lose_the_added_keys():
    row = _row(value="13,317", value_type="actual", low="stale", range_kind="x")
    dropped = lr.attribute_forecast_row(row, {"forecaster": "Omdia", "low": "38,000", "high": "1.2 million",
                                              "n_forecasters": 40}, REPORT, lr.page_number_set(REPORT))
    assert dropped == ["forecaster", "low", "high", "n_forecasters"]
    assert not CONSENSUS_KEYS & set(row) and "analyst" not in row
    untyped = {"metric": "Output", "value": "250,000"}
    assert lr.attribute_forecast_row(untyped, {"forecaster": "Omdia"}, REPORT, frozenset()) == ["forecaster"]
    assert untyped == {"metric": "Output", "value": "250,000"}


def test_analyst_is_the_forecaster_and_survives_enrichment():
    rows, _ = _attributed([{"metric": "Output", "value": "250000", "value_type": "forecast",
                            "source": "Reuters", "forecaster": "Goldman  Sachs"},
                           {"metric": "Output", "value": "250000", "value_type": "forecast",
                            "source": "Reuters"}], REPORT)
    enriched = dr.enrich_quantitative_rows(rows)
    assert enriched[0]["forecaster"] == enriched[0]["analyst"] == "Goldman Sachs"
    assert enriched[0]["source"] == "Reuters"                            # the publisher stays
    assert enriched[1]["analyst"] == "Reuters" and "forecaster" not in enriched[1]   # the bridge fallback


def test_normalize_quant_pairs_each_row_with_its_own_item():
    facts = [{"metric": "", "value": "1"}, "junk", {"metric": "A", "value": "10", "forecaster": "F-A"},
             {"metric": "B", "value": None}, {"metric": "C", "value": "30", "forecaster": "F-C"}]
    pairs = lr.normalize_quant(facts, [], with_items=True)
    assert [(row["metric"], item["forecaster"]) for row, item in pairs] == [("A", "F-A"), ("C", "F-C")]
    assert [row for row, _ in pairs] == lr.normalize_quant(facts, [])
    many = [{"metric": f"M{i}", "value": str(i), "forecaster": f"F{i}"} for i in range(lr.MAX_QUANT_ROWS + 5)]
    capped = lr.normalize_quant(many, [], with_items=True)
    assert len(capped) == lr.MAX_QUANT_ROWS
    assert all(item["forecaster"] == "F" + row["metric"][1:] for row, item in capped)


# =============================================================== attribution: engine

def test_facts_addendum_only_with_the_flag(tmp_path, bridge, monkeypatch, fixed_as_of):
    _knobs(monkeypatch, attribution=False)
    rc, meta, _, model, out = v3.run_engine(tmp_path, bridge, ForecastWorld(), out_dir=tmp_path / "off")
    assert rc == 0, meta.get("error")
    assert _facts_tasks(model) == [_plain_facts_task()]
    assert "forecaster_attribution" not in meta

    _knobs(monkeypatch, attribution=True)
    rc, meta, _, model, out = v3.run_engine(tmp_path, bridge, ForecastWorld(), out_dir=tmp_path / "on")
    assert rc == 0, meta.get("error")
    (task,) = _facts_tasks(model)
    assert task == _plain_facts_task() + "\n- " + lr._FACTS_FORECASTER_RULE
    memo = _load(out / "v3" / "extract" / "facts.json")
    assert memo["task_sha256"] == hashlib.sha256(task.encode("utf-8")).hexdigest()

    # Canonical order: the date rule first, the forecaster fields after it.
    _knobs(monkeypatch, attribution=True, typing=True)
    rc, _, _, model, _ = v3.run_engine(tmp_path, bridge, ForecastWorld(), out_dir=tmp_path / "typed")
    assert rc == 0
    assert _facts_tasks(model) == [_plain_facts_task() + "\n- " + lr._FACTS_DATE_RULE + "\n- "
                                   + lr._FACTS_FORECASTER_RULE]


def test_turning_the_flag_on_re_extracts_only_the_facts(tmp_path, bridge, monkeypatch, fixed_as_of):
    """The addendum changes the facts task hash: a resumed run memoized with
    the flag off extracts the facts (only) again, then reuses that memo."""
    out = tmp_path / "out"
    _knobs(monkeypatch, attribution=False)
    rc, _, _, _, _ = v3.run_engine(tmp_path, bridge, ForecastWorld(), out_dir=out)
    assert rc == 0
    world = ForecastWorld()
    facts_only = v3.ScriptedModel(lambda call: world(call) if v3.role_of(call) == "FACT EXTRACTION TASK"
                                  else pytest.fail(f"unexpected model call: {v3.role_of(call)}"))
    _knobs(monkeypatch, attribution=True)
    rc, meta, _, model, _ = v3.run_engine(tmp_path, bridge, world, out_dir=out, model=facts_only)
    assert rc == 0, meta.get("error")
    assert len(model.calls) == 1 and _facts_tasks(model)[0].endswith(lr._FACTS_FORECASTER_RULE)
    assert meta["forecaster_attribution"]["with_n"] == 1
    silent = v3.ScriptedModel(lambda call: pytest.fail(f"unexpected model call: {v3.role_of(call)}"))
    rc, _, _, model, _ = v3.run_engine(tmp_path, bridge, world, out_dir=out, model=silent)
    assert rc == 0 and model.calls == []


def test_engine_attributes_rows_against_the_report(tmp_path, bridge, monkeypatch, fixed_as_of):
    _knobs(monkeypatch, attribution=True, verify=True)
    rc, meta, plog, _, out = v3.run_engine(tmp_path, bridge, ForecastWorld())
    assert rc == 0, meta.get("error")
    report = (out / "research_report.md").read_text(encoding="utf-8")
    assert "poll of 40 economists" in report
    installed, poll, grid, utilisation = _load(out / "quantitative.json")

    assert not CONSENSUS_KEYS & set(installed)
    assert poll["forecaster"] == poll["analyst"] == "Economist poll" and poll["source"] == "Reuters"
    assert (poll["low"], poll["high"], poll["n_forecasters"], poll["range_kind"]) == (
        "260", "340", 40, "across_forecasters")
    assert grid["forecaster"] == "Omdia" and not {"low", "high", "n_forecasters", "range_kind"} & set(grid)
    assert (utilisation["low"], utilisation["high"], utilisation["range_kind"]) == ("52", "56", "stated_range")
    assert all("verification" in row for row in (installed, poll))       # RESEARCH-4 still runs after

    # Every kept bound and count is on the report the facts came from.
    body = lr.strip_references(report)
    numbers = lr.page_number_set(body)
    for row in (poll, utilisation):
        assert lr._stated_in_report(str(row["low"]), numbers) and lr._stated_in_report(str(row["high"]), numbers)
    assert lr._report_states_count(poll["n_forecasters"], body)

    assert meta["forecaster_attribution"] == {
        "rows": 4, "with_forecaster": 3, "with_range": 2, "with_n": 1,
        "fields_dropped": {"forecaster": 1, "high": 2, "low": 2, "n_forecasters": 1}}
    assert _load(out / "meta.json")["forecaster_attribution"] == meta["forecaster_attribution"]
    assert any(m.startswith("v3: forecaster attribution: ") for m in plog.of("ok"))
    actor_rows = _load(out / "actors.json")["quantitative_facts"]
    assert actor_rows[1]["forecaster"] == "Economist poll" and actor_rows[1]["n_forecasters"] == 40


def test_flag_off_quantitative_json_is_byte_identical(tmp_path, bridge, monkeypatch, fixed_as_of):
    """Knob off: the extra fields the model returned are ignored and the file
    equals the legacy normalize → enrich → annotate result."""
    _knobs(monkeypatch, attribution=False)
    rc, meta, _, _, out = v3.run_engine(tmp_path, bridge, ForecastWorld())
    assert rc == 0, meta.get("error")
    baseline = dr.enrich_quantitative_rows(lr.normalize_quant(copy.deepcopy(FORECAST_FACTS),
                                                              _load(out / "sources.json")))
    dr.annotate_recency_rows(baseline, AS_OF, lr.DEFAULT_STALE_DAYS, date_key="as_of_date")
    assert (out / "quantitative.json").read_bytes() == json.dumps(baseline, ensure_ascii=False,
                                                                   indent=2).encode("utf-8")
    assert not any(CONSENSUS_KEYS & set(row) for row in baseline)
    assert "forecaster_attribution" not in meta


def test_attribution_failure_degrades_safe(tmp_path, bridge, monkeypatch, fixed_as_of):
    _knobs(monkeypatch, attribution=True)
    calls = []

    def boom(row, item, body, numbers):
        calls.append(row["metric"])
        if len(calls) == 2:
            raise RuntimeError("attribution exploded")
        row["forecaster"] = "half-done"
        return []

    monkeypatch.setattr(lr, "attribute_forecast_row", boom)
    rc, meta, plog, _, out = v3.run_engine(tmp_path, bridge, ForecastWorld())
    assert rc == 0, meta.get("error")
    quant = _load(out / "quantitative.json")
    assert len(quant) == 4 and not any(CONSENSUS_KEYS & set(row) for row in quant)   # no half-stamped row
    assert "forecaster_attribution" not in meta
    assert {"helper": "forecaster_attribution", "error": "RuntimeError: attribution exploded"} in \
        meta["analytics_errors"]
    assert any("forecaster attribution failed" in m for m in plog.of("warn"))


def test_forecaster_keys_never_unmatch_a_previously_matched_actor_row():
    """actor_context matches a quant row to an actor on its JSON text
    (``_matches_structured_row``).  Attribution only adds keys, and the one
    value it replaces (analyst, which the bridge otherwise copies from the
    source) leaves that source in the row, so every row that matched an actor
    still matches it; the forecaster's own actor now also sees its forecast.
    Below the 32-row pack cap every previously packed row stays packed (the
    cap case is the next test)."""
    facts = [
        {"metric": "Humanoid shipments", "value": "250000", "unit": "units", "as_of_date": "2025-06-01",
         "period_end": "2030", "value_type": "forecast", "source": "Reuters",
         "definition": "Goldman Sachs base case", "forecaster": "Goldman Sachs"},
        {"metric": "Humanoid shipments", "value": "38000", "unit": "units", "as_of_date": "2024-07-01",
         "period_end": "2030", "value_type": "forecast", "source": "Omdia press release",
         "forecaster": "Omdia", "low": "38,000", "high": "1.2 million", "n_forecasters": 40},
        {"metric": "Unitree revenue", "value": "1.2", "unit": "CNY billion", "as_of_date": "2025-12-31",
         "value_type": "actual", "source": "Unitree filing", "forecaster": "Unitree"},
        {"metric": "Humanoid shipments", "value": "446000", "unit": "units", "as_of_date": "2026-06-24",
         "period_end": "2030", "value_type": "forecast", "source": "CNBC", "geography": "China",
         "forecaster": "Morgan Stanley"},
    ]
    before = dr.enrich_quantitative_rows(lr.normalize_quant(copy.deepcopy(facts), []))
    after = dr.enrich_quantitative_rows(_attributed(facts, REPORT)[0])
    cast = [{"name": "Goldman Sachs"}, {"name": "Omdia"}, {"name": "Unitree", "aliases": ["Unitree Robotics"]},
            {"name": "Reuters"}, {"name": "Morgan Stanley"}, {"name": "CNBC"}]
    gained = []
    for actor in cast:
        for old_row, new_row in zip(before, after, strict=True):
            if actor_context._matches_structured_row(old_row, actor):
                assert actor_context._matches_structured_row(new_row, actor), (actor["name"], old_row["metric"])
        old = [row["metric"] + row["value"] for row in actor_context._relevant_rows(before, actor, 32)]
        new = [row["metric"] + row["value"] for row in actor_context._relevant_rows(after, actor, 32)]
        assert set(old) <= set(new), actor["name"]
        gained += [(actor["name"], key) for key in new if key not in old]
    assert ("Morgan Stanley", "Humanoid shipments446000") in gained      # intended: its own forecast
    assert all(name != "Unitree" for name, _ in gained)                  # actual rows gain nothing


def test_at_the_pack_cap_new_forecaster_matches_displace_at_most_as_many_later_rows():
    """The PREPARE pack keeps an actor's first 32 matched rows in row order
    (``_relevant_rows``).  When that cap binds, an earlier row that newly
    matches through its forecaster pushes a later, previously matched row out
    of the pack: never more rows than it adds, always from the pack's end, and
    each displaced row still matches the actor."""
    goldman = {"name": "Goldman Sachs"}
    gaining = [{"metric": f"Projection {i}", "value": str(100 + i), "unit": "units", "period_end": "2030",
                "value_type": "forecast", "source": "Reuters", "forecaster": "Goldman Sachs"} for i in range(5)]
    matching = [{"metric": f"Metric {i}", "value": str(i + 1), "unit": "units", "as_of_date": "2025-12-31",
                 "value_type": "actual", "source": "Goldman Sachs Research"} for i in range(32)]
    before = dr.enrich_quantitative_rows(lr.normalize_quant(copy.deepcopy(gaining + matching), []))
    after = dr.enrich_quantitative_rows(_attributed(gaining + matching, REPORT)[0])
    old = [row["metric"] for row in actor_context._relevant_rows(before, goldman, 32)]
    new = [row["metric"] for row in actor_context._relevant_rows(after, goldman, 32)]
    assert old == [f"Metric {i}" for i in range(32)]
    assert new == [f"Projection {i}" for i in range(5)] + [f"Metric {i}" for i in range(27)]
    gained = [metric for metric in new if metric not in old]
    displaced = [metric for metric in old if metric not in new]
    assert len(displaced) <= len(gained) and displaced == old[len(old) - len(displaced):]
    assert all(actor_context._matches_structured_row(row, goldman) for row in after if row["metric"] in displaced)


# =============================================================== diagnostics: pure

HUMANOID_REPORT = (
    "Forecasts for 2030 humanoid shipments diverge widely: Omdia's cautious base case is 38,000 units [S1], "
    "Goldman Sachs expects more than 250,000 units [S2], Bank of America projects 1.2 million units "
    "globally [S3], and Morgan Stanley sees 446,000 units in China alone [S4]. Omdia counted 13,317 units "
    "shipped in 2025 [S1].")
HUMANOID_FACTS = [
    {"metric": "2025 global humanoid shipments", "value": "13317", "unit": "units", "as_of_date": "2026-01-01",
     "period_end": "2025-12-31", "value_type": "actual", "geography": "Global",
     "definition": "Omdia count of humanoid units shipped in 2025", "source": "Omdia Market Radar"},
    {"metric": "2030 humanoid robot shipments", "value": "38000", "unit": "units", "as_of_date": "2024-07-01",
     "period_end": "2030-12-31", "value_type": "forecast", "geography": "Global",
     "definition": "cautious base case for 2030 humanoid shipments", "source": "Omdia press release",
     "forecaster": "Omdia"},
    {"metric": "2030 humanoid robot shipments", "value": ">250000", "unit": "units", "as_of_date": "2025-06-01",
     "period_end": "2030-12-31", "value_type": "forecast", "geography": "Global",
     "definition": "base-case 2030 humanoid shipments", "source": "Goldman Sachs Insights",
     "forecaster": "Goldman Sachs"},
    {"metric": "2030 humanoid robot shipments", "value": "1.2 million", "unit": "units",
     "as_of_date": "2025-04-30", "period_end": "2030-12-31", "value_type": "forecast", "geography": "Global",
     "definition": "2030 global humanoid shipments trajectory", "source": "Forbes",
     "forecaster": "Bank of America"},
    {"metric": "2030 humanoid robot shipments", "value": "446000", "unit": "units", "as_of_date": "2026-06-24",
     "period_end": "2030-12-31", "value_type": "forecast", "geography": "China",
     "definition": "2030 China shipment base case", "source": "CNBC", "forecaster": "Morgan Stanley"},
]


def _humanoid_rows() -> list[dict]:
    """The humanoid-2030 facts as the flag-on engine writes them (attributed, then enriched)."""
    return dr.enrich_quantitative_rows(_attributed(HUMANOID_FACTS, HUMANOID_REPORT)[0])


def _forecast(metric, value, forecaster, as_of_date, *, unit="units", year="2030", geography="Global", **extra):
    return {"metric": metric, "value": value, "value_num": dr._quant_value_num(value), "unit": unit,
            "as_of_date": as_of_date, "period_end": year, "value_type": "forecast", "geography": geography,
            "forecaster": forecaster, "analyst": forecaster, **extra}


def test_humanoid_2030_groups_the_three_global_forecasters():
    rows = _humanoid_rows()
    assert {row.get("metric_family") for row in rows[1:]} == {"annual shipments"}
    diag = ce.build_dispersion_diagnostics(rows, [], "2026-07-15")
    assert diag["schema"] == "drf.consensus_diagnostics/v1"
    (group,) = diag["groups"]
    assert group["key"] == {"metric": "annual shipments", "region": "global", "target_year": 2030, "unit": "unit"}
    assert group["forecasters"] == ["Bank of America", "Goldman Sachs", "Omdia"]
    assert (group["n_forecasters"], group["n_rows"]) == (3, 3)
    # "1.2 million" reads at full scale next to "250,000".
    assert (group["min"], group["median"], group["max"]) == (38000, 250000, 1200000)
    assert group["spread_ratio"] == pytest.approx(31.6, abs=0.05)
    assert (group["oldest_as_of"], group["newest_as_of"]) == ("2024-07-01", "2025-06-01")
    # The newest vintage is 409 days old at the as-of date.
    assert group["stale"] is True and group["events_since"] == 0 and group["revisions"] == []
    # Morgan Stanley's China figure is its own (single-forecaster) key; the actual is no projection.
    assert all("Morgan Stanley" not in g["forecasters"] for g in diag["groups"])
    assert diag["counts"] == {"rows": 5, "projected": 4, "eligible": 4, "no_value": 0, "ambiguous_scale": 0,
                              "no_target_year": 0, "no_forecaster": 0}
    assert diag["leakage_guard"] is True
    assert ce.quality_summary(diag) == {"schema": ce.SCHEMA, "groups_n": 1, "wide_groups_n": 1,
                                        "forecasters_n": 3, "excluded_n": 0, "excluded_by_reason": {},
                                        "leakage_guard": True, "sha256": diag["sha256"]}


def test_metric_without_a_family_groups_on_the_forecaster_free_metric():
    rows = [_forecast("Omdia 2030 forecast of humanoid shipments", "38000", "Omdia", "2024-07-01"),
            _forecast("Goldman Sachs humanoid shipments projection", "250000", "Goldman Sachs", "2025-06-01"),
            _forecast("humanoid shipments", "90000", "IDC", "2025-03", geography="global", unit="Units")]
    (group,) = ce.build_dispersion_diagnostics(rows, [], "2026-07-15")["groups"]
    assert group["key"]["metric"] == "humanoid shipments" and group["n_forecasters"] == 3


def test_a_projection_dated_after_the_as_of_is_excluded():
    rows = [_forecast("humanoid shipments", "38000", "Omdia", "2024-07-01"),
            _forecast("humanoid shipments", "250000", "Goldman Sachs", "2025-06-01"),
            _forecast("humanoid shipments", "900000", "Leaky Bank", "2026-08-01")]
    diag = ce.build_dispersion_diagnostics(rows, [], dt.date(2026, 7, 15))
    assert diag["excluded"] == [{"metric": "humanoid shipments", "as_of_date": "2026-08-01",
                                 "reason": "after_as_of"}]
    (group,) = diag["groups"]
    assert "Leaky Bank" not in group["forecasters"] and group["max"] == 250000
    assert ce.quality_summary(diag)["excluded_n"] == 1
    # A coarse as-of date that starts on or before the as-of is not excluded.
    coarse = ce.build_dispersion_diagnostics([_forecast("x", "5", "A", "2026"), _forecast("x", "6", "B", "2026")],
                                             [], "2026-07-15")
    assert coarse["excluded"] == [] and coarse["groups"][0]["n_forecasters"] == 2


def test_a_target_date_misplaced_in_as_of_date_is_excluded_under_its_own_reason():
    """A row the research typing read as holding a target date in as_of_date
    (its as_of_is_target flag, or the target_date its repair copied) stays
    excluded, but not as a post-as-of vintage: after_as_of counts only those."""
    rows = [_forecast("humanoid shipments", "38000", "Omdia", "2024-07-01"),
            _forecast("humanoid shipments", "250000", "Goldman Sachs", "2025-06-01"),
            _forecast("humanoid shipments", "900000", "Flagged", "2029-12-31",
                      epistemic_flags=["as_of_is_target"]),
            _forecast("humanoid shipments", "800000", "Repaired", "2030-06", target_date="2030-06"),
            _forecast("humanoid shipments", "700000", "Leaky Bank", "2026-08-01", target_date="2030-12-31")]
    diag = ce.build_dispersion_diagnostics(rows, [], "2026-07-15")
    assert [(item["as_of_date"], item["reason"]) for item in diag["excluded"]] == [
        ("2026-08-01", "after_as_of"), ("2029-12-31", "as_of_is_target"), ("2030-06", "as_of_is_target")]
    (group,) = diag["groups"]
    assert group["forecasters"] == ["Goldman Sachs", "Omdia"]
    summary = ce.quality_summary(diag)
    assert summary["excluded_n"] == 3
    assert summary["excluded_by_reason"] == {"after_as_of": 1, "as_of_is_target": 2}


def test_free_text_dates_are_read_and_an_unreadable_as_of_date_fails_closed():
    """The leakage guard reads as_of_date as the research engine does: a
    free-text month after the as-of is excluded like an ISO one, a stated
    date no reading can date is excluded (unparsed_as_of), a blank or
    placeholder one is an undated vintage; timeline event dates are read
    the same way."""
    rows = [_forecast("humanoid shipments", "38000", "Omdia", "2024-07-01"),
            _forecast("humanoid shipments", "250000", "Goldman Sachs", "2026-05-01"),
            _forecast("humanoid shipments", "900000", "Leak A", "August 2026"),
            _forecast("humanoid shipments", "900000", "Leak B", "2026年8月"),
            _forecast("humanoid shipments", "900000", "Leak C", "2026年底"),
            _forecast("humanoid shipments", "900000", "Leak D", "FY29"),
            _forecast("humanoid shipments", "70000", "Undated A", "n/a"),
            _forecast("humanoid shipments", "80000", "Undated B", ""),
            _forecast("humanoid shipments", "90000", "Coarse", "July 2026")]
    timeline = [{"date": "June 2026", "event": "free-text month after the newest vintage"},
                {"date": "2026年6月", "event": "the same in Chinese"},
                {"date": "2026年底", "event": "after the as-of"}]
    diag = ce.build_dispersion_diagnostics(rows, timeline, "2026-07-15")
    assert diag["excluded"] == [
        {"metric": "humanoid shipments", "as_of_date": as_of_date, "reason": reason}
        for as_of_date, reason in (("2026年8月", "after_as_of"), ("2026年底", "after_as_of"),
                                   ("August 2026", "after_as_of"), ("FY29", "unparsed_as_of"))]
    (group,) = diag["groups"]
    assert group["forecasters"] == ["Coarse", "Goldman Sachs", "Omdia", "Undated A", "Undated B"]
    assert group["max"] == 250000 and group["newest_as_of"] == "July 2026"
    assert ce.quality_summary(diag)["excluded_n"] == 4

    dated = ce.build_dispersion_diagnostics(rows[:2], timeline, "2026-07-15")
    assert (dated["groups"][0]["stale"], dated["groups"][0]["events_since"]) == (True, 2)
    # Without a full as-of day the guard is off: nothing is excluded, and the digest says so.
    unguarded = ce.build_dispersion_diagnostics(rows, timeline, None)
    assert unguarded["excluded"] == [] and unguarded["leakage_guard"] is False
    assert ce.quality_summary(unguarded)["leakage_guard"] is False


def test_a_publication_year_is_no_target_year():
    """The bridge fills ``year`` from as_of_date when a row states no period:
    such a row never joins a genuine forecast for its publication year."""
    genuine, published, other = dr.enrich_quantitative_rows([
        _forecast("humanoid shipments", "20000", "Omdia", "2024-06-01", year="2025"),
        {"metric": "humanoid shipments", "value": "50000", "unit": "units", "as_of_date": "2025-03-10",
         "value_type": "forecast", "geography": "Global", "forecaster": "Goldman Sachs", "analyst": "Goldman Sachs"},
        _forecast("humanoid shipments", "38000", "Omdia", "2024-07-01")])
    assert published["year"] == 2025 and "period_end" not in published
    diag = ce.build_dispersion_diagnostics([genuine, published], [], "2026-07-15")
    assert diag["groups"] == [] and diag["counts"]["no_target_year"] == 1
    # A year the row states apart from its as_of_date is its target.
    (group,) = ce.build_dispersion_diagnostics([{**published, "year": 2030}, other], [], "2026-07-15")["groups"]
    assert group["key"]["target_year"] == 2030 and group["n_forecasters"] == 2


def test_the_scale_word_belongs_to_the_number_value_num_reads():
    """``value_num`` is the value's first range, else its first number; only
    the scale word right after that number scales it."""
    assert ce._value_scale("250,000 (1 million by 2035)") == 1.0
    assert ce._value_scale("1.2-1.5 trillion") == 1e12 and ce._value_scale("$5 to $7bn") == 1e9
    assert ce._value_scale("$1.2T") == 1e12 and ce._value_scale("3000亿元") == 1e8
    rows = [_forecast("humanoid shipments", "250,000 (1 million by 2035)", "Goldman Sachs", "2025-06-01"),
            _forecast("humanoid shipments", "38,000", "Omdia", "2024-07-01"),
            _forecast("humanoid shipments", "1.1-1.3 million", "Bank of America", "2025-04-30")]
    (group,) = ce.build_dispersion_diagnostics(rows, [], "2026-07-15")["groups"]
    assert (group["min"], group["median"], group["max"]) == (38000, 250000, 1200000)
    assert group["spread_ratio"] == pytest.approx(31.5789, abs=1e-4)


def test_a_bare_scale_letter_is_ambiguous_unless_the_unit_settles_it():
    """k/m/b/t without a currency sign may be a scale or a unit ("38k"
    units, "100 m"): such a row never enters the statistics (it once read
    "38k" as 38 and reported a 6,579x spread), unless the unit gives the
    scale or is that letter."""
    assert ce._value_scale("38k", "unit") is None and ce._value_scale("1.2T", "usd") is None
    assert ce._value_scale("$38k", "usd") == 1e3 and ce._value_scale("38 k", "unit", 1e3) == 1.0
    assert ce._value_scale("100 m", "m") == 1.0 and ce._value_scale("1.2 million", "unit") == 1e6
    rows = [_forecast("humanoid shipments", "38k", "Omdia", "2024-07-01"),
            _forecast("humanoid shipments", "250,000", "Goldman Sachs", "2025-06-01",
                      low="38k", high="1.2 million")]
    diag = ce.build_dispersion_diagnostics(rows, [], "2026-07-15")
    assert diag["groups"] == [] and diag["ranges"] == []
    assert (diag["counts"]["ambiguous_scale"], diag["counts"]["eligible"]) == (1, 1)
    settled = [_forecast("pipe length", "100 m", "A", "2024-07-01", unit="m"),
               _forecast("pipe length", "250", "B", "2025-06-01", unit="m"),
               _forecast("pipe length", "$38k", "C", "2025-06-01", unit="m")]
    (group,) = ce.build_dispersion_diagnostics(settled, [], "2026-07-15")["groups"]
    assert (group["min"], group["max"], group["n_forecasters"]) == (100, 38000, 3)
    thousands = [_forecast("output", "38k", "A", "2024-07-01", unit="thousand units"),
                 _forecast("output", "250", "B", "2025-06-01", unit="thousand units")]
    (group,) = ce.build_dispersion_diagnostics(thousands, [], "2026-07-15")["groups"]
    assert (group["min"], group["max"]) == (38000, 250000)


def test_values_beyond_the_float_range_never_sink_the_payload():
    """A value that overflows at full scale (or as an int) is counted as
    no_value; statistics of huge finite values stay finite; every other row
    still groups."""
    rows = [_forecast("capex", "1", "A", "2025-01", unit="USD trillion"),
            _forecast("capex", "2", "B", "2025-02", unit="USD trillion"),
            _forecast("capex", "3", "C", "2025-03", unit="USD trillion", low="1e300", high="1e301"),
            _forecast("capex", "4", "D", "2025-04", unit="USD trillion")]
    rows[0]["value_num"], rows[3]["value_num"] = 1e300, 10 ** 400
    diag = ce.build_dispersion_diagnostics(rows, [], "2026-07-15")
    assert "error" not in diag and diag["counts"]["no_value"] == 2 and diag["ranges"] == []
    (group,) = diag["groups"]
    assert group["forecasters"] == ["B", "C"] and group["max"] == 3_000_000_000_000
    huge = [_forecast("capex", "1", "A", "2025-01"), _forecast("capex", "1", "B", "2025-01")]
    huge[0]["value_num"], huge[1]["value_num"] = 1.5e308, 1.7e308
    (group,) = ce.build_dispersion_diagnostics(huge, [], "2026-07-15")["groups"]
    assert group["median"] == pytest.approx(1.6e308) and group["spread_ratio"] == pytest.approx(1.1333, abs=1e-4)
    huge[0]["value_num"] = 1e-300
    (group,) = ce.build_dispersion_diagnostics(huge, [], "2026-07-15")["groups"]
    assert group["spread_ratio"] is None                                  # max/min overflows: no ratio


def test_delloro_vintages_give_an_up_revision():
    rows = [_forecast("data center capex", "1.2", "Dell'Oro", "2024-02", unit="USD trillion", year="2029"),
            _forecast("data center capex", ">3", "Dell'Oro", "2026-01", unit="USD trillion", year="2029"),
            _forecast("data center capex", "2.5", "IDC", "2025-09", unit="USD trillion", year="2029")]
    diag = ce.build_dispersion_diagnostics(rows, [], "2026-07-15")
    (group,) = diag["groups"]
    revision = {"forecaster": "Dell'Oro", "from_as_of": "2024-02", "to_as_of": "2026-01",
                "from": 1_200_000_000_000, "to": 3_000_000_000_000, "direction": "up"}
    assert group["revisions"] == [revision]
    assert diag["revisions"] == [{"key": group["key"], **revision}]
    # Each forecaster adds its newest vintage only: the old 1.2T never widens the spread.
    assert (group["min"], group["max"], group["n_rows"], group["n_forecasters"]) == (
        2_500_000_000_000, 3_000_000_000_000, 3, 2)
    assert group["key"]["unit"] == "usd"

    # A single forecaster forms no group, but its revisions are still listed.
    alone = ce.build_dispersion_diagnostics(rows[:2], [], "2026-07-15")
    assert alone["groups"] == [] and [r["direction"] for r in alone["revisions"]] == ["up"]
    flat = [_forecast("capex", value, "A", date) for value, date in (("5", "2024-01"), ("4", "2024-06"),
                                                                    ("4", "2025-01"))]
    assert [r["direction"] for r in ce.build_dispersion_diagnostics(flat, [], "2026-07-15")["revisions"]] == [
        "down", "unchanged"]


def test_staleness_counts_timeline_events_after_the_newest_vintage():
    rows = [_forecast("capex", "5", "A", "2026-05-01"), _forecast("capex", "6", "B", "2026-06-01")]
    timeline = [{"date": "2026-05-15", "event": "before newest"}, {"date": "2026-06-20", "event": "after"},
                {"date": "2026-07", "event": "month after"}, {"date": "2026-08-01", "event": "after as-of"},
                {"date": "", "event": "undated"}]
    (fresh,) = ce.build_dispersion_diagnostics(rows, timeline[:1], "2026-07-15")["groups"]
    assert (fresh["stale"], fresh["events_since"]) == (False, 0)
    (group,) = ce.build_dispersion_diagnostics(rows, timeline, "2026-07-15")["groups"]
    assert (group["stale"], group["events_since"]) == (True, 2)
    (unknown,) = ce.build_dispersion_diagnostics(rows, timeline, None)["groups"]
    assert (unknown["stale"], unknown["events_since"]) == (None, None)


def test_a_coarse_newest_vintage_counts_from_its_first_day():
    """A vintage stated as "2026" may date from January 1: staleness and
    later events count from there (fail closed), and newest_as_of names the
    vintage staleness measured."""
    rows = [_forecast("capex", "5", "A", "2026"), _forecast("capex", "6", "B", "2024-01-01")]
    timeline = [{"date": "2026-05-01", "event": "after the coarse vintage began"}]
    (group,) = ce.build_dispersion_diagnostics(rows, timeline, "2026-12-01")["groups"]
    assert (group["stale"], group["events_since"], group["newest_as_of"]) == (True, 1, "2026")
    (quiet,) = ce.build_dispersion_diagnostics(rows, [], "2026-03-01")["groups"]
    assert (quiet["stale"], quiet["events_since"]) == (False, 0)            # 59 days from January 1
    # The newest vintage is the latest first day, even when an older period ends later ("2026"),
    # and staleness measures that same vintage: the July event follows it.
    spans = [_forecast("capex", "5", "A", "2026-06-15"), _forecast("capex", "6", "B", "2026")]
    (group,) = ce.build_dispersion_diagnostics(spans, [{"date": "2026-07-01", "event": "e"}],
                                               "2026-07-15")["groups"]
    assert (group["newest_as_of"], group["stale"], group["events_since"]) == ("2026-06-15", True, 1)


def test_rates_have_no_spread_ratio_and_ranges_are_listed_apart():
    rates = [_forecast("market share", "20", "A", "2026-01", unit="%"),
             _forecast("market share", "45", "B", "2026-02", unit="%")]
    (group,) = ce.build_dispersion_diagnostics(rates, [], "2026-07-15")["groups"]
    assert group["spread_ratio"] is None and ce.quality_summary({"groups": [group]})["wide_groups_n"] == 0
    rows = _attributed([{"metric": "Output", "value": "250,000", "unit": "units", "period_end": "2030",
                         "as_of_date": "2025-01", "value_type": "forecast", "forecaster": "Poll",
                         "low": "38,000", "high": "1.2 million", "n_forecasters": 40}], REPORT)[0]
    diag = ce.build_dispersion_diagnostics(dr.enrich_quantitative_rows(rows), [], "2026-07-15")
    assert diag["groups"] == []
    (entry,) = diag["ranges"]
    assert (entry["forecaster"], entry["low"], entry["high"], entry["n_forecasters"], entry["range_kind"]) == (
        "Poll", 38000, 1200000, 40, "across_forecasters")


def test_malformed_rows_never_raise_and_the_sha_ignores_key_order():
    junk = [None, "x", 3, {}, {"value_type": "forecast"}, {"value_type": "forecast", "value_num": "abc"},
            {"value_type": "forecast", "value_num": float("nan")},
            {"epistemic_class": "projected", "value_num": float("inf")},
            {"value_type": "forecast", "value_num": 5, "as_of_date": {"a": 1}, "metric": ["x"], "unit": 7,
             "year": True, "low": [], "high": {}, "period_end": 2030, "forecaster": 9, "analyst": None},
            {"value_type": "target", "value_num": 7, "as_of_date": "2026-13-45", "period_end": "FY2031",
             "metric": "m", "source": "S", "low": "9", "high": "3", "n_forecasters": True}]
    timelines = [[None, {"date": 5}, {"date": "garbage"}, "x"], "not a list", None]
    for quantitative in (junk, None, {"rows": junk}, "x"):
        for timeline in timelines:
            for as_of in ("garbage", None, 20260715, dt.datetime(2026, 7, 15, 9, 30)):
                diag = ce.build_dispersion_diagnostics(quantitative, timeline, as_of, stale_days=-3)
                assert diag["schema"] == ce.SCHEMA and "error" not in diag and len(diag["sha256"]) == 64
                assert diag["stale_days"] == ce.DEFAULT_STALE_DAYS
                json.dumps(diag, allow_nan=False)

    rows = _humanoid_rows() + [_forecast("humanoid shipments", "900000", "Leaky", "2026-08-01")]
    events = [{"date": "2025-09-01", "event": "e"}]
    diag = ce.build_dispersion_diagnostics(rows, events, "2026-07-15")
    reordered = [dict(reversed(list(row.items()))) for row in reversed(rows)]
    again = ce.build_dispersion_diagnostics(reordered, [dict(reversed(list(e.items()))) for e in events],
                                            "2026-07-15")
    assert again == diag and again["sha256"] == diag["sha256"]
    body = {key: value for key, value in diag.items() if key != "sha256"}
    canonical = json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    assert diag["sha256"] == hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    # Range entries that tie on every other field still order the same way.
    tied = [_forecast("output", "250000", "Poll", "2025-01", low="38,000", high="1.2 million", **extra)
            for extra in ({"n_forecasters": 3}, {"n_forecasters": 7}, {"n_forecasters": -1}, {},
                          {"range_kind": "stated_range"}, {"n_forecasters": 3, "range_kind": "across_forecasters"})]
    forward = ce.build_dispersion_diagnostics(tied, [], "2026-07-15")
    backward = ce.build_dispersion_diagnostics(tied[::-1], [], "2026-07-15")
    assert len(forward["ranges"]) == 6 and forward == backward


def test_an_unexpected_failure_returns_an_error_payload(monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("grouping exploded")

    monkeypatch.setattr(ce, "_build", boom)
    diag = ce.build_dispersion_diagnostics(_humanoid_rows(), [], "2026-07-15")
    assert diag["error"] == "RuntimeError: grouping exploded" and diag["groups"] == []
    summary = ce.quality_summary(diag)
    assert summary["groups_n"] == 0 and summary["error"] == diag["error"] and summary["sha256"] == diag["sha256"]


# =============================================================== diagnostics: report stage

def _report_agent(llm):
    agent = packs._agent(llm)
    agent.quantitative = _humanoid_rows() + [
        _forecast("humanoid shipments", "900000", "Leaky Bank",
                  (packs.AS_OF + dt.timedelta(days=30)).isoformat(), metric_family="annual shipments",
                  region="Global")]
    return agent


def _run_report(tmp_path, report_id):
    llm = packs._RouterLLM()
    agent, llm, _early, final = packs._run(tmp_path, report_id, llm=llm, agent=_report_agent(llm))
    return llm, final


def _sidecar(tmp_path, report_id):
    return os.path.join(packs._folder(tmp_path, report_id), ce.FILENAME)


def test_shadow_mode_writes_the_digest_and_the_sidecar(report_env, monkeypatch):
    monkeypatch.setattr(Config, "REPORT_CONSENSUS_DIAGNOSTICS", "shadow", raising=False)
    written = []
    real_write = ra.write_json_atomic

    def spy(path, obj, **kwargs):
        written.append(os.path.basename(path))
        return real_write(path, obj, **kwargs)

    monkeypatch.setattr(ra, "write_json_atomic", spy)
    _llm, final = _run_report(report_env, "report_shadow")
    assert ce.FILENAME in written
    sidecar = packs._read(report_env, "report_shadow", ce.FILENAME)
    assert sidecar["schema"] == ce.SCHEMA and sidecar["as_of"] == packs.AS_OF.isoformat()
    assert sidecar["excluded"][0]["reason"] == "after_as_of" and sidecar["leakage_guard"] is True
    assert final["quality"]["consensus"] == {
        "schema": ce.SCHEMA, "groups_n": 1, "wide_groups_n": 1, "forecasters_n": 3, "excluded_n": 1,
        "excluded_by_reason": {"after_as_of": 1}, "leakage_guard": True, "sha256": sidecar["sha256"]}


def test_shadow_mode_falls_back_to_the_hindcast_pin_as_of(report_env, monkeypatch):
    """actors.as_of_date that is no full day (legacy or salvaged research)
    yields to the hindcast pin's as-of; with neither, the digest says no
    leakage guard ran."""
    monkeypatch.setattr(Config, "REPORT_CONSENSUS_DIAGNOSTICS", "shadow", raising=False)
    llm = packs._RouterLLM()
    agent = _report_agent(llm)
    agent.actors = dict(agent.actors, as_of_date=str(packs.AS_OF.year))
    agent.hindcast = {"version": HINDCAST_POLICY_VERSION, "hindcast": True, "as_of": packs.AS_OF.isoformat()}
    _agent, _llm, _early, final = packs._run(report_env, "report_pinned", llm=llm, agent=agent)
    sidecar = packs._read(report_env, "report_pinned", ce.FILENAME)
    assert sidecar["as_of"] == packs.AS_OF.isoformat() and sidecar["leakage_guard"] is True
    assert final["quality"]["consensus"]["excluded_by_reason"] == {"after_as_of": 1}

    llm = packs._RouterLLM()
    agent = _report_agent(llm)
    agent.actors = dict(agent.actors, as_of_date="")
    _agent, _llm, _early, final = packs._run(report_env, "report_unguarded", llm=llm, agent=agent)
    consensus = final["quality"]["consensus"]
    assert (consensus["leakage_guard"], consensus["excluded_n"]) == (False, 0)
    assert packs._read(report_env, "report_unguarded", ce.FILENAME)["as_of"] is None


def test_shadow_mode_changes_no_prompt_call_count_or_probability(report_env, monkeypatch):
    monkeypatch.setattr(Config, "REPORT_CONSENSUS_DIAGNOSTICS", "off", raising=False)
    off_llm, off = _run_report(report_env, "report_cmp_off")
    monkeypatch.setattr(Config, "REPORT_CONSENSUS_DIAGNOSTICS", "shadow", raising=False)
    on_llm, on = _run_report(report_env, "report_cmp_on")

    assert len(on_llm.calls) == len(off_llm.calls)
    assert [c["kind"] for c in on_llm.calls] == [c["kind"] for c in off_llm.calls]
    assert [c["messages"] for c in on_llm.calls] == [c["messages"] for c in off_llm.calls]
    assert packs._spine_prompts(on_llm) and packs._prompts(on_llm, "[Research dossier]")
    consensus = on["quality"].pop("consensus")
    assert consensus["groups_n"] == 1
    if not on["quality"]:
        del on["quality"]
    assert json.dumps(on, sort_keys=True) == json.dumps(off, sort_keys=True)
    assert [s["probability"] for s in on["scenarios"]] == [s["probability"] for s in off["scenarios"]]
    assert [b["probability"] for b in on["binary_forecasts"]] == [b["probability"] for b in off["binary_forecasts"]]


@pytest.mark.parametrize("mode", ["off", "", "SHADOW-ish", "on"])
def test_off_or_an_invalid_mode_writes_no_key_and_no_file(report_env, monkeypatch, mode):
    monkeypatch.setattr(Config, "REPORT_CONSENSUS_DIAGNOSTICS", mode, raising=False)
    built = []
    monkeypatch.setattr(ce, "build_dispersion_diagnostics", lambda *a, **k: built.append(a) or {})
    _llm, final = _run_report(report_env, "report_off")
    assert built == []
    assert "consensus" not in (final.get("quality") or {})
    assert not os.path.exists(_sidecar(report_env, "report_off"))


def test_shadow_without_quantitative_rows_or_with_a_failing_writer_is_silent(report_env, monkeypatch):
    monkeypatch.setattr(Config, "REPORT_CONSENSUS_DIAGNOSTICS", "shadow", raising=False)
    llm = packs._RouterLLM()
    agent = packs._agent(llm)
    agent.quantitative = None
    _agent, _llm, _early, final = packs._run(report_env, "report_noquant", llm=llm, agent=agent)
    assert "consensus" not in (final.get("quality") or {})
    assert not os.path.exists(_sidecar(report_env, "report_noquant"))

    real_write = ra.write_json_atomic

    def failing(path, obj, **kwargs):
        if os.path.basename(path) == ce.FILENAME:
            raise OSError("disk full")
        return real_write(path, obj, **kwargs)

    monkeypatch.setattr(ra, "write_json_atomic", failing)
    _llm, final = _run_report(report_env, "report_diskfull")
    assert "consensus" not in (final.get("quality") or {})             # no digest without its sidecar
    assert final["scenarios"] and final["binary_forecasts"]
