"""TIME-4: v3 quantitative sanity parity with the legacy engine.

RESEARCH_QUANT_RECONCILE (default on, forwarded to every research child) runs
the bridge's ``reconcile_quantitative`` and ``flag_implausible_quant`` in the
v3 finalize and in the extract-only salvage:

* rows on the same (metric, unit) that disagree become contested.json claims
  (origin ``quant_reconcile``; v3 adds at most QUANT_RECONCILE_MAX_CONTESTED),
  a ~1000x gap is also a probable unit-scale error in meta.quant_unit_warnings;
  v3 compares rows only within one scope (period end and length, geography,
  reported or projected), so a trajectory, a series over time, a year next to
  its fourth quarter, a multi-year total next to its last year or two regions
  never disagree, and the claim and warning name their scope; probable
  unit-scale errors come first under the cap;
* claimed actuals dated after the as-of are listed in meta.quant_implausible
  (v3: typed rows by epistemic_class, otherwise value_type actual or absent;
  the bound is a pinned run's as-of, else the day after the plan's), and v3
  also lists claimed actuals whose period_end ends after it;
* the extract-only reference date is never after today and ignores a year-
  or month-only extraction;
* capped meta lists keep their totals in meta.quant_sanity_truncated, and an
  extract-only salvage of a v3 handoff drops the v3 run's sanity keys;
* quantitative.json never changes, actors.json keeps the extracted claims, and
  with the knob off every artifact and meta are byte-identical to before.

Offline: the scripted model, injected search/fetch and real bridge of
``test_research_engine_v3``.
"""

from __future__ import annotations

import copy
import datetime as dt
import json
import subprocess
import sys
import types
from pathlib import Path

import pytest

import test_research_engine_v3 as v3

# The shared fixtures (hermetic env, real bridge with network steps stubbed).
_hermetic_env = v3._hermetic_env
bridge = v3.bridge
lr = v3.lr
dr = v3.dr

AS_OF = dt.date(2026, 9, 28)
KNOB = "RESEARCH_QUANT_RECONCILE"
NEW_META_KEYS = {"quant_unit_warnings", "quant_implausible", "quant_reconcile_contested"}
SANITY_HELPERS = ("reconcile_quantitative", "flag_implausible_quant")
MODEL_CONTESTED = [{"claim": "2030 capacity", "positions": [{"stance": "250 GW", "sources": ["S1"]}],
                    "status": "contested", "why_they_differ": "scope"}]


def _fact(metric, value, unit, as_of_date, value_type="actual"):
    row = {"metric": metric, "value": value, "unit": unit, "as_of_date": as_of_date, "source_ref": "S1"}
    if value_type is not None:
        row["value_type"] = value_type
    return row


# Two readings of one metric 1000x apart (a probable unit-scale error), an
# actual dated after the as-of and a forecast dated after it whose metric has
# no projection word (only the claimed-actual filter keeps it out).
PARITY_FACTS = [
    _fact("Data-centre electricity use", "1.2", "TWh", "2025-12-31"),
    _fact("Data-centre electricity use", "1200", "TWh", "2025-12-31"),
    _fact("Operating capacity", "185", "GW", "2027-06-30"),
    _fact("Installed capacity", "260", "GW", "2030-12-31", "forecast"),
]
# The bound is the day after the plan's as-of (typing's publication bound).
FUTURE_ACTUAL_FLAG = ("Operating capacity: as_of 2027-06-30 is AFTER research cutoff 2026-09-29 "
                      "(claimed-actual with future date)")


@pytest.fixture(autouse=True)
def _unset_knobs(monkeypatch):
    """The knob's default and a live (unpinned) run unless a test sets them."""
    monkeypatch.delenv(KNOB, raising=False)
    monkeypatch.delenv("RESEARCH_AS_OF", raising=False)


@pytest.fixture
def fixed_as_of(monkeypatch):
    """The plan's as-of date (UTC today in production) pinned for stable dates."""
    monkeypatch.setattr(lr, "_utc_date", lambda: AS_OF.isoformat())


class QuantWorld(v3.World):
    """The standard world with a scripted facts reply."""

    def __init__(self, quant: list[dict], **kwargs) -> None:
        super().__init__(**kwargs)
        self.quant = quant

    def facts(self, call):
        return v3.ai(json.dumps({
            "key_events": [{"date": "2023-12-31", "event": "Capacity reached 176 GW"}],
            "quantitative_facts": self.quant,
            "contested_claims": MODEL_CONTESTED,
        }))


def _load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _run(tmp_path: Path, bridge, name: str, quant: list[dict] = PARITY_FACTS):
    rc, meta, plog, _model, out = v3.run_engine(tmp_path / name, bridge, QuantWorld(copy.deepcopy(quant)))
    assert rc == 0, meta.get("error")
    return meta, plog, out


def _model_contested(out: Path) -> list[dict]:
    """contested.json as the engine wrote it before TIME-4: the normalized model claims."""
    return lr.normalize_contested(copy.deepcopy(MODEL_CONTESTED), _load(out / "sources.json"))


def _dump(obj) -> bytes:
    return json.dumps(obj, ensure_ascii=False, indent=2).encode("utf-8")


# =============================================================== v3 engine

def test_v3_run_records_unit_scale_error_and_future_dated_actual(tmp_path, bridge, fixed_as_of):
    """Knob unset (default on): the ~1000x disagreement is a unit warning and a
    contested.json claim; the future-dated actual is implausible, the
    future-dated forecast is not."""
    meta, plog, out = _run(tmp_path, bridge, "on")

    # The scope of rows dated only by as_of_date is its year.
    assert meta["quant_unit_warnings"] == [{"metric": "Data-centre electricity use", "unit": "TWh",
                                            "ratio": 1000.0, "values": ["1.2", "1200"], "scope": "as of 2025"}]
    assert meta["quant_implausible"] == [FUTURE_ACTUAL_FLAG]
    assert not any("Installed capacity" in flag for flag in meta["quant_implausible"])
    assert meta["quant_reconcile_contested"] == 1

    contested = _load(out / "contested.json")
    assert contested[:-1] == _model_contested(out)
    reconciled = contested[-1]
    assert reconciled["origin"] == "quant_reconcile" and reconciled["status"] == "contested"
    assert reconciled["claim"] == "Data-centre electricity use (as of 2025)"
    assert [position["stance"].split(" (")[0] for position in reconciled["positions"]] == ["1.2 TWh", "1200 TWh"]
    assert "probable unit-scale error" in reconciled["why_they_differ"]
    assert meta["contested_count"] == len(contested) == 2
    # actors.json keeps the extracted claims (the legacy engine's split).
    assert _load(out / "actors.json")["contested_claims"] == _model_contested(out)

    written = _load(out / "meta.json")
    assert {key: written[key] for key in NEW_META_KEYS} == {key: meta[key] for key in NEW_META_KEYS}
    assert "v3: quant reconcile: 1 probable unit-scale (~1000x) disagreement(s)" in plog.of("warn")
    assert "v3: quant reconcile: +1 contested claim(s) from numeric disagreement" in plog.of("ok")
    assert any(line.startswith("v3: quant sanity: 1 implausible/future-dated fact(s)") for line in plog.of("warn"))
    assert not any(error["helper"] in SANITY_HELPERS for error in meta.get("analytics_errors", []))


def test_quantitative_json_unchanged_and_flag_off_byte_identical(tmp_path, bridge, monkeypatch, fixed_as_of):
    """The step is read-only: every artifact but contested.json is byte-equal
    with the knob on and off; off, contested.json holds only the model claims,
    no helper runs and meta gains no key."""
    monkeypatch.setenv("RESEARCH_LINEAR_WORKERS", "1")   # deterministic runs: the artifacts compare
    meta_on, _, on = _run(tmp_path, bridge, "on")

    monkeypatch.setenv(KNOB, "false")
    for helper in SANITY_HELPERS:
        monkeypatch.setattr(bridge, helper, lambda *_a, _name=helper, **_k: pytest.fail(f"{_name} ran"))
    meta_off, plog_off, off = _run(tmp_path, bridge, "off")

    for name in ("quantitative.json", "actors.json", "timeline.json", "sources.json", "research_report.md",
                 lr.VERIFIED_FACTS_FILENAME):
        assert (on / name).read_bytes() == (off / name).read_bytes(), name
    quant = _load(off / "quantitative.json")
    assert [(row["metric"], row["value"]) for row in quant] == [(f["metric"], f["value"]) for f in PARITY_FACTS]
    assert not any(key in row for row in quant for key in ("origin", "positions"))

    assert (off / "contested.json").read_bytes() == _dump(_model_contested(off))
    assert _load(on / "contested.json")[:-1] == _load(off / "contested.json")
    assert NEW_META_KEYS.isdisjoint(meta_off) and NEW_META_KEYS <= set(meta_on)
    assert set(meta_on) - set(meta_off) == NEW_META_KEYS
    assert meta_off["contested_count"] == 1
    assert not any("quant reconcile" in line or "quant sanity" in line for _kind, line in plog_off.lines)
    assert not any(error["helper"] in SANITY_HELPERS for error in meta_off.get("analytics_errors", []))


@pytest.mark.parametrize("mode", ["missing", "raising"])
def test_sanity_helpers_degrade_safe(tmp_path, bridge, monkeypatch, fixed_as_of, mode):
    """A bridge without (or with failing) helpers: analytics_errors records
    them, contested.json keeps the model claims and the run completes."""
    for helper in SANITY_HELPERS:
        if mode == "missing":
            monkeypatch.delattr(bridge, helper)
        else:
            def boom(*_args, **_kwargs):
                raise RuntimeError("helper broke")
            monkeypatch.setattr(bridge, helper, boom)
    meta, plog, out = _run(tmp_path, bridge, mode)

    expected = "unavailable" if mode == "missing" else "RuntimeError: helper broke"
    errors = [error for error in meta["analytics_errors"] if error["helper"] in SANITY_HELPERS]
    assert errors == [{"helper": helper, "error": expected} for helper in SANITY_HELPERS]
    assert _load(out / "meta.json")["analytics_errors"] == meta["analytics_errors"]
    assert NEW_META_KEYS.isdisjoint(meta)
    assert (out / "contested.json").read_bytes() == _dump(_model_contested(out))
    assert meta["status"] == "completed"


def test_reconciled_contested_rows_are_capped(tmp_path, bridge, fixed_as_of):
    """Twelve disagreeing metrics: contested.json gains ten, the probable
    unit-scale error (found last) first, then the first nine 2x gaps (a
    disagreement but no unit-scale warning)."""
    metrics = [f"Regional capacity {chr(ord('A') + index)}" for index in range(12)]
    facts = [_fact(metric, value, "GW", "2025-12-31") for metric in metrics[:11] for value in ("10", "20")]
    facts += [_fact(metrics[11], value, "GW", "2025-12-31") for value in ("1.2", "1200")]
    meta, plog, out = _run(tmp_path, bridge, "capped", facts)

    assert lr.QUANT_RECONCILE_MAX_CONTESTED == 10
    contested = _load(out / "contested.json")
    assert contested[:1] == _model_contested(out)
    assert [row["claim"] for row in contested[1:]] == [f"{metric} (as of 2025)"
                                                       for metric in [metrics[11], *metrics[:9]]]
    assert "probable unit-scale error" in contested[1]["why_they_differ"]
    assert not any("probable unit-scale error" in row["why_they_differ"] for row in contested[2:])
    assert all(row["origin"] == "quant_reconcile" for row in contested[1:])
    assert meta["quant_reconcile_contested"] == 10 and meta["contested_count"] == 11
    assert meta["quant_sanity_truncated"] == {"quant_reconcile_contested": 12}
    assert _load(out / "meta.json")["quant_sanity_truncated"] == {"quant_reconcile_contested": 12}
    assert [warning["metric"] for warning in meta["quant_unit_warnings"]] == [metrics[11]]
    assert "quant_implausible" not in meta
    assert ("v3: quant reconcile: +10 contested claim(s) from numeric disagreement (the first 10 of 12)"
            in plog.of("ok"))


def _v3_fact(metric, value, unit, period_end, geography, value_type="actual", series=None):
    row = _fact(metric, value, unit, "2026-07-15", value_type)
    row.update(period_end=period_end, geography=geography, series=series or f"{metric} series")
    return row


# Rows the facts schema splits across period_end, geography and value_type:
# on (metric, unit) alone each group below disagrees; only the last is one
# quantity read two ways (the same quarter in the United States, 1000x apart).
SCOPED_FACTS = [
    # One source's forecast trajectory (review round 1: BNEF 2030 1.0 TW vs 2035 2.1 TW).
    *(_v3_fact("Grid-scale storage power", value, "TW", year, "Global", "forecast", "BNEF outlook")
      for value, year in (("1.0", "2030-12-31"), ("2.1", "2035-12-31"), ("3.4", "2040-12-31"))),
    # One actual series over two years.
    _v3_fact("Battery pack price", "139", "USD/kWh", "2023", "Global"),
    _v3_fact("Battery pack price", "115", "USD/kWh", "2024", "Global"),
    # Two regions in one year (IEA global vs LBNL United States).
    _v3_fact("Data-centre electricity use", "415", "TWh", "2024", "Global", series="IEA"),
    _v3_fact("Data-centre electricity use", "176", "TWh", "2024", "United States", series="LBNL"),
    # An actual and a forecast for one period.
    _v3_fact("Installed storage", "180", "GW", "2025", "Global"),
    _v3_fact("Installed storage", "250", "GW", "2025", "Global", "forecast"),
    # A fiscal year next to its fourth quarter (review round 2: Nvidia FY2025 vs Q4).
    _v3_fact("Data-centre revenue", "115.2", "USD billion", "FY2025", "Global", series="10-K"),
    _v3_fact("Data-centre revenue", "35.6", "USD billion", "Q4 2025", "Global", series="Q4 release"),
    # A year next to its December.
    _v3_fact("EV sales", "1.5", "million units", "2025", "US", series="Cox annual"),
    _v3_fact("EV sales", "0.15", "million units", "2025-12", "US", series="Cox monthly"),
    # A cumulative multi-year forecast next to its last year's.
    _v3_fact("Data-centre capex", "6700", "USD billion", "2025-2030", "Global", "forecast", "McKinsey"),
    _v3_fact("Data-centre capex", "1500", "USD billion", "2030", "Global", "forecast", "Dell'Oro"),
    # The same quarter and country (US is the United States), 1000x apart.
    _v3_fact("Data-centre electricity use", "1.2", "TWh", "2025-Q2", "US", series="EIA"),
    _v3_fact("Data-centre electricity use", "1200", "TWh", "2025-Q2", "United States", series="Utility filings"),
]


def test_v3_reconciles_only_rows_of_one_scope(tmp_path, bridge, fixed_as_of):
    """A trajectory, a series over time, two regions, an actual next to a
    forecast, a year next to its fourth quarter or December and a multi-year
    total next to its last year add no contested claim and no unit warning;
    the same-period ~1000x pair still does, named by its scope."""
    meta, _, out = _run(tmp_path, bridge, "scoped", SCOPED_FACTS)

    quant = _load(out / "quantitative.json")
    # On (metric, unit) alone, as the legacy engine groups, every group disagrees.
    unscoped, _ = bridge.reconcile_quantitative(copy.deepcopy(quant))
    assert [row["claim"] for row in unscoped] == [
        "Grid-scale storage power", "Battery pack price", "Data-centre electricity use", "Installed storage",
        "Data-centre revenue", "EV sales", "Data-centre capex"]

    contested = _load(out / "contested.json")
    assert contested[:-1] == _model_contested(out)
    reconciled = contested[-1]
    assert reconciled["origin"] == "quant_reconcile"
    assert reconciled["claim"] == "Data-centre electricity use (2025-Q2, US)"
    assert [position["stance"].split(" (")[0] for position in reconciled["positions"]] == ["1.2 TWh", "1200 TWh"]
    assert meta["quant_reconcile_contested"] == 1 and meta["contested_count"] == 2
    assert meta["quant_unit_warnings"] == [{"metric": "Data-centre electricity use", "unit": "TWh", "ratio": 1000.0,
                                            "values": ["1.2", "1200"], "scope": "2025-Q2, US"}]
    assert "quant_implausible" not in meta and "quant_sanity_truncated" not in meta
    assert [(row["metric"], row["value"]) for row in quant] == [(f["metric"], f["value"]) for f in SCOPED_FACTS]


# Typed rows are claimed by epistemic_class; untyped ones by value_type.
TYPED_FACTS = [
    _fact("Operating capacity", "185", "GW", "2027-06-30"),                 # future actual: always flagged
    _fact("Installed capacity", "260", "GW", "2030-12-31", "forecast"),     # projected: never
    _fact("Capacity growth", "180", "% YoY", "2025-12-31", "estimate"),     # typed reported: flagged
    _fact("Rack density", "40", "kW", "2027-01-15", None),                  # untyped, no value_type: flagged
]


@pytest.mark.parametrize("typing, expected", [
    (False, [FUTURE_ACTUAL_FLAG,
             "Rack density: as_of 2027-01-15 is AFTER research cutoff 2026-09-29 (claimed-actual with future date)"]),
    (True, [FUTURE_ACTUAL_FLAG, "Capacity growth: 180 % yoy — extreme growth (>150%); verify vs parent total"]),
])
def test_claimed_actuals_follow_quant_typing(tmp_path, bridge, monkeypatch, fixed_as_of, typing, expected):
    monkeypatch.setenv("RESEARCH_QUANT_TYPING", "true" if typing else "false")
    meta, _, out = _run(tmp_path, bridge, "typed" if typing else "untyped", TYPED_FACTS)
    assert meta["quant_implausible"] == expected
    classes = [row.get("epistemic_class") for row in _load(out / "quantitative.json")]
    assert classes == (["unknown", "projected", "reported", "unknown"] if typing else [None] * 4)


# Claimed actuals whose period_end ends after the as-of (review round 2): the
# bridge helper reads only as_of_date, and a v3 row states its period apart.
UNFINISHED_FACTS = [
    _v3_fact("Data-centre revenue", "51.2", "USD billion", "2027-Q3", "Global"),       # flagged
    _v3_fact("Quantum funding", "12", "EUR million", "2026", "EU"),                    # year not over: flagged
    _v3_fact("Installed capacity", "260", "GW", "2027-Q3", "Global", "forecast"),      # projected: never
    _v3_fact("Rack density", "40", "kW", "2027-Q3", "Global", "estimate"),             # projected: never
    _v3_fact("Battery pack price", "115", "USD/kWh", "2024", "Global"),                # ended: never
    # Its as_of_date is after the as-of too: the helper's one flag only.
    dict(_fact("Operating capacity", "185", "GW", "2027-06-30"), period_end="2027-06-30"),
]


@pytest.mark.parametrize("typing", [False, True], ids=["untyped", "typed"])
def test_claimed_actuals_for_an_unfinished_period_are_implausible(tmp_path, bridge, monkeypatch, fixed_as_of,
                                                                  typing):
    monkeypatch.setenv("RESEARCH_QUANT_TYPING", "true" if typing else "false")
    meta, plog, out = _run(tmp_path, bridge, "unfinished", UNFINISHED_FACTS)

    assert meta["quant_implausible"] == [
        FUTURE_ACTUAL_FLAG,
        "Data-centre revenue: period_end 2027-Q3 ends AFTER research cutoff 2026-09-29 "
        "(claimed-actual for an unfinished period)",
        "Quantum funding: period_end 2026 ends AFTER research cutoff 2026-09-29 "
        "(claimed-actual for an unfinished period)"]
    assert _load(out / "meta.json")["quant_implausible"] == meta["quant_implausible"]
    assert any(line.startswith("v3: quant sanity: 3 implausible/future-dated fact(s)") for line in plog.of("warn"))
    quant = _load(out / "quantitative.json")
    assert [(row["metric"], row["period_end"]) for row in quant] == [
        (fact["metric"], fact["period_end"]) for fact in UNFINISHED_FACTS]
    if typing:
        # The program classifier types the flagged rows as it reads them.
        assert [row["epistemic_class"] for row in quant] == [
            "unknown", "unknown", "projected", "projected", "reported", "unknown"]
        assert all("future_dated_reported" in quant[index]["epistemic_flags"] for index in (0, 1, 5))


def test_an_actual_published_the_day_after_the_plan_date_is_not_implausible(tmp_path, bridge, fixed_as_of):
    """A live run: plan.as_of is the UTC date fixed at plan time, and a run that
    crosses UTC midnight can cite a number published the next day (as typing
    allows)."""
    next_day, day_after = ((AS_OF + dt.timedelta(days=days)).isoformat() for days in (1, 2))
    facts = [_fact("Operating capacity", "185", "GW", next_day), _fact("Grid queue", "40", "months", day_after)]
    meta, _, _ = _run(tmp_path, bridge, "midnight", facts)
    assert meta["quant_implausible"] == [
        f"Grid queue: as_of {day_after} is AFTER research cutoff {next_day} (claimed-actual with future date)"]


@pytest.mark.parametrize("pin", [AS_OF - dt.timedelta(days=90), AS_OF], ids=["hindcast", "pinned-today"])
def test_a_pinned_run_flags_an_actual_published_the_day_after_its_as_of(tmp_path, bridge, monkeypatch,
                                                                       fixed_as_of, pin):
    """RESEARCH_AS_OF fixes the as-of (a hindcast, TIME-7): no midnight to
    cross, so a number published the day after it is a leak and the flag's
    cutoff is the pinned date itself."""
    monkeypatch.setenv("RESEARCH_AS_OF", pin.isoformat())
    next_day = (pin + dt.timedelta(days=1)).isoformat()
    facts = [_fact("Operating capacity", "185", "GW", pin.isoformat()), _fact("Grid queue", "40", "months", next_day)]
    meta, _, out = _run(tmp_path, bridge, "pinned", facts)
    assert _load(out / "actors.json")["as_of_date"] == pin.isoformat()
    assert meta["quant_implausible"] == [
        f"Grid queue: as_of {next_day} is AFTER research cutoff {pin.isoformat()} (claimed-actual with future date)"]


# =============================================================== pure parts

@pytest.mark.parametrize("row, claimed", [
    ({"value_type": "actual"}, True),
    ({}, True),
    ({"value_type": "estimate"}, False),
    ({"value_type": "forecast"}, False),
    ({"value_type": "target"}, False),
    ({"value_type": "actual", "epistemic_class": "reported"}, True),
    ({"value_type": "estimate", "epistemic_class": "reported"}, True),
    ({"value_type": "actual", "epistemic_class": "unknown",
      "epistemic_flags": ["future_dated_reported", "published_after_as_of"]}, True),
    ({"epistemic_class": "unknown", "epistemic_flags": ["published_after_as_of"]}, False),
    ({"value_type": "actual", "epistemic_class": "unknown", "epistemic_flags": ["period_unparsed"]}, False),
    ({"value_type": "forecast", "epistemic_class": "projected", "epistemic_flags": ["as_of_is_target"]}, False),
])
def test_claimed_actual(row, claimed):
    assert lr._claimed_actual(row) is claimed


UNFINISHED_ROW = {"metric": "Data-centre revenue", "value": "51.2", "unit": "USD billion", "period_end": "2027-Q3",
                  "as_of_date": "2026-08-27", "value_type": "actual"}


@pytest.mark.parametrize("change, flagged", [
    ({}, True),
    ({"epistemic_class": "unknown", "epistemic_flags": ["future_dated_reported"]}, True),
    ({"value_type": None}, True),
    ({"period_end": "2026"}, True),
    ({"period_end": "Q4 2026", "as_of_date": None}, True),
    ({"period_end": "2026-09-30"}, True),
    ({"period_end": AS_OF.isoformat()}, False),          # ends on the cutoff
    ({"period_end": "2025"}, False),
    ({"period_end": "cumulative"}, False),               # unreadable: no end
    ({"period_end": "n/a"}, False),
    ({"period_end": None}, False),
    ({"as_of_date": "2027-01-01"}, False),               # the helper's date check owns it
    ({"as_of_date": "2027"}, False),
    ({"value_type": "forecast"}, False),
    ({"value_type": "estimate"}, False),
    ({"epistemic_class": "projected"}, False),
])
def test_unfinished_period_flags(change, flagged):
    row = {**UNFINISHED_ROW, **change}
    before = copy.deepcopy(row)
    flags = lr._unfinished_period_flags([row], AS_OF)
    assert row == before
    assert flags == ([f"Data-centre revenue: period_end {row['period_end']} ends AFTER research cutoff "
                      f"{AS_OF.isoformat()} (claimed-actual for an unfinished period)"] if flagged else [])


@pytest.mark.parametrize("first, second, same", [
    # Period: the end of period_end, whatever its spelling.
    ({"period_end": "2030"}, {"period_end": "2030-12-31"}, True),
    ({"period_end": "FY2030"}, {"period_end": "by 2030"}, True),
    ({"period_end": "2030"}, {"period_end": "2035"}, False),
    ({"period_end": "2025-Q1"}, {"period_end": "2025-Q2"}, False),
    ({"period_end": "2025-06"}, {"period_end": "Jun 2025"}, True),
    ({"period_end": "2025-Q4"}, {"period_end": "Q4 2025"}, True),
    ({"period_end": "2025-2030"}, {"period_end": "FY2025-30"}, True),
    # ... and its length: a year never meets a quarter, half or month ending
    # with it, nor a multi-year span its last year or a span starting elsewhere.
    ({"period_end": "2025"}, {"period_end": "2025-Q4"}, False),
    ({"period_end": "FY2025"}, {"period_end": "Q4 2025"}, False),
    ({"period_end": "2025"}, {"period_end": "2025-12"}, False),
    ({"period_end": "2025"}, {"period_end": "2025-H2"}, False),
    ({"period_end": "2025-Q4"}, {"period_end": "2025-12"}, False),
    ({"period_end": "2025-Q4"}, {"period_end": "2025-12-31"}, False),
    ({"period_end": "2025-2030"}, {"period_end": "2030"}, False),
    ({"period_end": "2025-2030"}, {"period_end": "2020-2030"}, False),
    # Unreadable periods by their text; a placeholder is no period.
    ({"period_end": "Cumulative"}, {"period_end": " cumulative "}, True),
    ({"period_end": "cumulative"}, {"period_end": "2025"}, False),
    ({"period_end": "cumulative"}, {"period_end": "lifetime"}, False),
    ({"period_end": "n/a", "as_of_date": "2025-03-01"}, {"as_of_date": "2025-11-20"}, True),
    # Without a period: the year of as_of_date (two polls weeks apart meet).
    ({"as_of_date": "2026-05-26"}, {"as_of_date": "2026-06-17"}, True),
    ({"as_of_date": "2025-12-31"}, {"as_of_date": "2026-01-15"}, False),
    ({"as_of_date": "2025"}, {"period_end": "2025"}, False),
    ({}, {"as_of_date": "2025"}, False),
    ({}, {"as_of_date": "unknown"}, True),
    # Geography: the canonical region, else the text, ignoring case and spacing.
    ({"geography": "US", "region": "United States"}, {"geography": "United States", "region": "United States"},
     True),
    ({"geography": "Global"}, {"geography": " global "}, True),
    ({"geography": "Global"}, {}, False),
    ({"geography": "China"}, {"geography": "India"}, False),
    # Reported or projected: value_type, or epistemic_class when typed.
    ({"value_type": "actual"}, {"value_type": "estimate"}, True),
    ({"value_type": "actual"}, {}, True),
    ({"value_type": "forecast"}, {"value_type": "target"}, True),
    ({"value_type": "actual"}, {"value_type": "forecast"}, False),
    ({"value_type": "estimate", "epistemic_class": "projected"}, {"value_type": "forecast",
                                                                  "epistemic_class": "projected"}, True),
    ({"value_type": "estimate", "epistemic_class": "projected"}, {"value_type": "actual",
                                                                  "epistemic_class": "reported"}, False),
    # The series names the source's series: different sources on one quantity meet.
    ({"series": "IEA STEPS"}, {"series": "BNEF NEO"}, True),
])
def test_quant_scope(first, second, same):
    assert (lr._quant_scope(first)[0] == lr._quant_scope(second)[0]) is same


@pytest.mark.parametrize("row, label", [
    ({"period_end": "2030", "geography": "Global", "as_of_date": "2026-07-15"}, "2030, Global"),
    ({"as_of_date": "2025-12-31"}, "as of 2025"),
    ({"geography": "  United   States "}, "United States"),
    ({"period_end": "2030", "geography": "Global", "value_type": "forecast"}, "2030, Global, projected"),
    ({"period_end": "2025", "value_type": "actual", "epistemic_class": "reported"}, "2025"),
    ({"period_end": "2025", "value_type": "actual", "epistemic_class": "unknown"}, "2025, unclassified"),
    ({"value_type": "target"}, "projected"),
    ({"period_end": "N/A"}, ""),
    ({}, ""),
])
def test_quant_scope_label(row, label):
    assert lr._quant_scope(row)[1] == label


# Review round 2: scopes that differ only by class, or by a period_end year
# against an as_of_date year, once shared a label (the claim text the report
# block shows and the contested chart's category).
DISTINCT_SCOPE_ROWS = [
    {"period_end": "2025", "geography": "Global", "value_type": "actual"},
    {"period_end": "2025", "geography": "Global", "value_type": "forecast"},
    {"period_end": "2025", "geography": "Global", "value_type": "actual", "epistemic_class": "unknown"},
    {"period_end": "2024"},
    {"as_of_date": "2024-05-01"},
    {"period_end": "2025-Q4"},
    {"period_end": "2025"},
    {},
    {"value_type": "forecast"},
]


def test_quant_scope_labels_of_different_keys_differ():
    scopes = [lr._quant_scope(row) for row in DISTINCT_SCOPE_ROWS]
    assert len({key for key, _label in scopes}) == len(scopes)
    assert len({label for _key, label in scopes}) == len(scopes)


def test_quant_scopes_are_copies_in_first_seen_order():
    rows = [{"metric": "a", "period_end": "2030"}, {"metric": "b", "period_end": "2035"},
            {"metric": "c", "period_end": "2030-12-31"}]
    scopes = lr._quant_scopes(rows)
    assert [(label, [row["metric"] for row in group]) for label, group in scopes] == [("2030", ["a", "c"]),
                                                                                     ("2035", ["b"])]
    scopes[0][1][0]["metric"] = "changed"
    assert rows[0]["metric"] == "a"


class _SanityStub:
    """The engine surface _quant_sanity uses: bridge_call, meta, log."""

    bridge_call = lr._Engine.bridge_call

    def __init__(self, bridge) -> None:
        self.bridge = bridge
        self.meta: dict = {}
        self.analytics_errors: list[dict] = []
        self.lines: list[tuple[str, str]] = []

    def log(self, kind, message):
        self.lines.append((kind, message))


ROWS = [{"metric": "Capacity", "value": "1", "unit": "GW", "as_of_date": "2025-12-31", "value_type": "actual"}]


@pytest.mark.parametrize("reconcile, implausible", [
    ([["claim"], []], "not a list"),
    ((["claim"],), {"flags": ["x"]}),
    (([{"claim": "x"}], "not a list"), None),
    (None, []),
])
def test_quant_sanity_ignores_results_of_another_shape(reconcile, implausible):
    stub = _SanityStub(types.SimpleNamespace(reconcile_quantitative=lambda rows: reconcile,
                                             flag_implausible_quant=lambda rows, as_of: implausible))
    assert lr._Engine._quant_sanity(stub, copy.deepcopy(ROWS), AS_OF) == []
    assert stub.meta == {} and stub.analytics_errors == [] and stub.lines == []


def test_quant_sanity_is_read_only_and_caps_every_list():
    """Reconcile runs once per scope on copies (a helper that writes its input
    changes no row); non-dict contested rows are dropped, claims and warnings
    name their scope, each meta list keeps 20 entries and
    meta.quant_sanity_truncated records every total before the cut."""
    seen: dict = {"reconcile": []}

    def reconcile(rows):
        seen["reconcile"].append([row["metric"] for row in rows])
        metric = rows[0]["metric"]
        rows[0]["value"] = "rewritten"
        found = [{"claim": f"{metric} {index}", "origin": "quant_reconcile"} for index in range(6)]
        return ["junk", *found], [{"metric": f"{metric} {index}"} for index in range(13)]

    def flag(rows, as_of):
        seen["flag"] = (rows, as_of)
        rows[0]["value_type"] = "rewritten"
        return [f"flag {index}" for index in range(25)]

    stub = _SanityStub(types.SimpleNamespace(reconcile_quantitative=reconcile, flag_implausible_quant=flag))
    # Two scopes: the 2025 actuals, and the undated target.
    rows = copy.deepcopy(ROWS) + [{"metric": "Target", "value": "9", "value_type": "target"},
                                  {"metric": "Capacity", "value": "2", "unit": "GW", "as_of_date": "2025-06-30"}]
    before = copy.deepcopy(rows)
    extra = lr._Engine._quant_sanity(stub, rows, AS_OF)

    assert rows == before
    assert seen["reconcile"] == [["Capacity", "Capacity"], ["Target"]]
    assert seen["flag"][1] == AS_OF and [row["metric"] for row in seen["flag"][0]] == ["Capacity", "Capacity"]
    assert extra == ([{"claim": f"Capacity {index} (as of 2025)", "origin": "quant_reconcile"} for index in range(6)]
                     + [{"claim": f"Target {index} (projected)", "origin": "quant_reconcile"} for index in range(4)])
    assert stub.meta == {
        "quant_unit_warnings": ([{"metric": f"Capacity {index}", "scope": "as of 2025"} for index in range(13)]
                                + [{"metric": f"Target {index}", "scope": "projected"} for index in range(7)]),
        "quant_reconcile_contested": 10,
        "quant_implausible": [f"flag {index}" for index in range(20)],
        "quant_sanity_truncated": {"quant_unit_warnings": 26, "quant_reconcile_contested": 12,
                                   "quant_implausible": 25}}
    assert lr.QUANT_SANITY_MAX_FLAGS == 20


def test_quant_sanity_keeps_the_scopes_before_a_failed_reconcile():
    """Reconcile stops at its first failure (recorded once), keeping what the
    scopes before it found; nothing is truncated."""
    calls: list[str] = []

    def reconcile(rows):
        calls.append(rows[0]["metric"])
        if len(calls) > 1:
            raise RuntimeError("helper broke")
        return [{"claim": "Capacity", "origin": "quant_reconcile"}], []

    stub = _SanityStub(types.SimpleNamespace(reconcile_quantitative=reconcile,
                                             flag_implausible_quant=lambda rows, as_of: []))
    rows = [dict(ROWS[0], metric=metric, period_end=period) for metric, period in
            (("Capacity", "2023"), ("Load", "2024"), ("Price", "2025"))]
    assert lr._Engine._quant_sanity(stub, rows, AS_OF) == [{"claim": "Capacity (2023)", "origin": "quant_reconcile"}]
    assert calls == ["Capacity", "Load"]
    assert stub.analytics_errors == [{"helper": "reconcile_quantitative", "error": "RuntimeError: helper broke"}]
    assert stub.meta == {"quant_reconcile_contested": 1}


def test_quant_sanity_period_flags_follow_the_helper_under_one_cap():
    """The unfinished-period flags follow the helper's under the one cap (the
    truncation total counts both), and stand without the helper."""
    rows = [dict(UNFINISHED_ROW, metric=f"Revenue {index}") for index in range(2)]
    period_flags = lr._unfinished_period_flags(rows, AS_OF)
    assert len(period_flags) == 2
    helper_flags = [f"flag {index}" for index in range(19)]
    stub = _SanityStub(types.SimpleNamespace(reconcile_quantitative=lambda rows: ([], []),
                                             flag_implausible_quant=lambda rows, as_of: list(helper_flags)))
    assert lr._Engine._quant_sanity(stub, copy.deepcopy(rows), AS_OF) == []
    assert stub.meta == {"quant_implausible": [*helper_flags, period_flags[0]],
                         "quant_sanity_truncated": {"quant_implausible": 21}}

    stub = _SanityStub(types.SimpleNamespace(reconcile_quantitative=lambda rows: ([], [])))
    assert lr._Engine._quant_sanity(stub, copy.deepcopy(rows), AS_OF) == []
    assert stub.analytics_errors == [{"helper": "flag_implausible_quant", "error": "unavailable"}]
    assert stub.meta == {"quant_implausible": period_flags}


# =============================================================== Config

_CONFIG_CHILD = r"""
import importlib, json, os, sys
import dotenv
dotenv.load_dotenv = lambda *a, **k: False  # the repo .env must not decide
import app.config as config_module
out = []
for raw in json.loads(sys.argv[1]):
    if raw is None:
        os.environ.pop("RESEARCH_QUANT_RECONCILE", None)
    else:
        os.environ["RESEARCH_QUANT_RECONCILE"] = raw
    out.append(importlib.reload(config_module).Config.RESEARCH_QUANT_RECONCILE)
print("<<<JSON>>>" + json.dumps(out))
"""


def test_config_parses_the_knob_like_the_bridge(monkeypatch):
    """Config reads RESEARCH_QUANT_RECONCILE as the bridge always has (blank =
    true, else 1/true/yes/on), so forwarding it changes no engine's reading.
    A clean child process: app.config loads the repo .env at import."""
    raws = [None, "", "  ", "true", " TRUE ", "1", "yes", "on", "false", "0", "no", "off", "maybe"]
    bridge_reads = []
    for raw in raws:
        if raw is None:
            monkeypatch.delenv(KNOB, raising=False)
        else:
            monkeypatch.setenv(KNOB, raw)
        bridge_reads.append(dr._env_flag(KNOB, True))
    assert bridge_reads == [True, True, True, True, True, True, True, True, False, False, False, False, False]
    backend = Path(__file__).resolve().parents[1]
    proc = subprocess.run([sys.executable, "-c", _CONFIG_CHILD, json.dumps(raws)],
                          cwd=str(backend), capture_output=True, text=True, timeout=120)
    assert proc.returncode == 0, proc.stderr
    line = [ln for ln in proc.stdout.splitlines() if ln.startswith("<<<JSON>>>")][-1]
    assert json.loads(line[len("<<<JSON>>>"):]) == bridge_reads


# =============================================================== extract-only salvage

class _Log:
    def __init__(self) -> None:
        self.rows: list[tuple[str, str]] = []

    def write(self, kind, message):
        self.rows.append((kind, str(message)))

    def close(self):
        pass

    def of(self, kind: str) -> list[str]:
        return [message for k, message in self.rows if k == kind]


def _utc_today() -> dt.date:
    return dt.datetime.now(dt.timezone.utc).date()


EXTRACT_FACTS = [
    {"metric": "Data-centre electricity use", "value": "1.2", "unit": "TWh", "as_of_date": "2025-12-31"},
    {"metric": "Data-centre electricity use", "value": "1200", "unit": "TWh", "as_of_date": "2025-12-31"},
    {"metric": "Operating capacity", "value": "185", "unit": "GW", "as_of_date": "2099-06-30"},
    # The bridge's check reads projection words: a forecast is never implausible for its date.
    {"metric": "Installed capacity forecast", "value": "260", "unit": "GW", "as_of_date": "2099-12-31"},
]


def _extract_only(tmp_path: Path, monkeypatch, *, as_of_date, facts=EXTRACT_FACTS):
    out = tmp_path
    out.mkdir(parents=True, exist_ok=True)
    (out / dr.REPORT_FILENAME).write_text("# Report\n\n" + "evidence " * 100, encoding="utf-8")
    obj = {"actors": [{"name": "Acme", "type": "Organization"}],
           "quantitative_facts": copy.deepcopy(facts),
           "contested_claims": copy.deepcopy(MODEL_CONTESTED)}
    if as_of_date is not None:
        obj["as_of_date"] = as_of_date
    monkeypatch.setattr(dr, "extract_complete_structured_tool_free", lambda *_a, **_k: ("{}", obj, [], False))
    monkeypatch.setattr(dr, "_collect_prediction_markets", lambda *_a, **_k: None)
    monkeypatch.setattr(dr, "_render_research_charts", lambda *_a, **_k: {})
    meta: dict = {}
    log = _Log()
    args = types.SimpleNamespace(no_actors=False, target_language="English", model="glm", depth="standard")
    rc = dr.run_extract_only("Q", out, args, meta, log, lambda: None)
    assert rc == 0 and meta["status"] == "completed", meta.get("error")
    return meta, log, out


def test_extract_only_records_unit_warnings_and_implausible_facts(tmp_path, monkeypatch):
    as_of = (_utc_today() - dt.timedelta(days=3)).isoformat()
    meta, log, out = _extract_only(tmp_path / "on", monkeypatch, as_of_date=as_of)

    assert meta["quant_unit_warnings"] == [{"metric": "Data-centre electricity use", "unit": "TWh",
                                            "ratio": 1000.0, "values": ["1.2", "1200"]}]
    assert meta["quant_implausible"] == [
        f"Operating capacity: as_of 2099-06-30 is AFTER research cutoff {as_of} (claimed-actual with future date)"]
    contested = _load(out / dr.CONTESTED_FILENAME)
    assert contested[0] == MODEL_CONTESTED[0] and contested[1]["origin"] == "quant_reconcile"
    assert meta["contested_count"] == 2
    assert "extract-only: quant reconcile: 1 probable unit-scale (~1000x) disagreement(s)" in log.of("warn")
    assert any(line.startswith(f"extract-only: quant sanity: 1 implausible/future-dated fact(s) against {as_of}")
               for line in log.of("warn"))

    # Knob off: the salvage writes what it wrote before (no reconciled claim, no new meta).
    monkeypatch.setenv(KNOB, "false")
    meta_off, log_off, off = _extract_only(tmp_path / "off", monkeypatch, as_of_date=as_of)
    assert NEW_META_KEYS.isdisjoint(meta_off)
    assert _load(off / dr.CONTESTED_FILENAME) == MODEL_CONTESTED
    quant_bytes = (out / dr.QUANTITATIVE_FILENAME).read_bytes()
    assert quant_bytes == (off / dr.QUANTITATIVE_FILENAME).read_bytes()
    assert [row["metric"] for row in json.loads(quant_bytes)] == [row["metric"] for row in EXTRACT_FACTS]
    assert not any("quant reconcile" in line or "quant sanity" in line for line in log_off.of("warn"))


def test_extract_only_reference_date_defaults_to_today_and_is_clamped(tmp_path, monkeypatch):
    """No extracted as_of_date: the reference is today (UTC).  A stale one (a
    model's training cutoff) is clamped to the run date, as in the full legacy
    run, so a past actual after it is no false positive."""
    meta, _, _ = _extract_only(tmp_path / "none", monkeypatch, as_of_date=None)
    (flag,) = meta["quant_implausible"]
    assert flag.startswith("Operating capacity: as_of 2099-06-30 is AFTER research cutoff 20")

    past_actual = [{"metric": "Grid capacity", "value": "90", "unit": "GW", "as_of_date": "2024-06-30"}]
    meta, _, _ = _extract_only(tmp_path / "stale", monkeypatch, as_of_date="2020-01-15", facts=past_actual)
    assert "quant_implausible" not in meta


def test_extract_only_reference_date_is_never_after_today_nor_a_period_start(tmp_path, monkeypatch):
    """A future extracted as_of_date does not hide a 2099 actual (no source
    publishes after the run date), and a year- or month-only one names no
    cutoff day: read as its first day it would flag that period's actuals.
    The stale clamp is widened so only the coarse reading decides."""
    meta, _, _ = _extract_only(tmp_path / "future", monkeypatch, as_of_date="2099-12-31")
    (flag,) = meta["quant_implausible"]
    prefix = "Operating capacity: as_of 2099-06-30 is AFTER research cutoff "
    assert flag.startswith(prefix)
    assert dt.date.fromisoformat(flag[len(prefix):len(prefix) + 10]) <= _utc_today()

    monkeypatch.setenv("RESEARCH_ASOF_MAX_LAG_DAYS", "400")
    last_month_end = _utc_today().replace(day=1) - dt.timedelta(days=1)
    actual = [{"metric": "Grid capacity", "value": "90", "unit": "GW", "as_of_date": last_month_end.isoformat()}]
    for coarse in (last_month_end.strftime("%Y-%m"), str(last_month_end.year)):
        meta, _, _ = _extract_only(tmp_path / coarse, monkeypatch, as_of_date=coarse, facts=actual)
        assert "quant_implausible" not in meta, coarse
    # A day is still the reference: the same actual is after a day before it.
    day_before = (last_month_end - dt.timedelta(days=1)).isoformat()
    meta, _, _ = _extract_only(tmp_path / "day", monkeypatch, as_of_date=day_before, facts=actual)
    assert meta["quant_implausible"] == [
        f"Grid capacity: as_of {last_month_end.isoformat()} is AFTER research cutoff {day_before} "
        "(claimed-actual with future date)"]


def test_extract_only_sanity_failure_is_additive(tmp_path, monkeypatch):
    def boom(*_args, **_kwargs):
        raise RuntimeError("sanity broke")

    monkeypatch.setattr(dr, "flag_implausible_quant", boom)
    meta, log, out = _extract_only(tmp_path, monkeypatch, as_of_date=None)
    assert "quant_implausible" not in meta and len(meta["quant_unit_warnings"]) == 1
    assert "extract-only: quant sanity check skipped (non-fatal): sanity broke" in log.of("warn")
    assert _load(out / dr.CONTESTED_FILENAME)[-1]["origin"] == "quant_reconcile"


def test_extract_only_salvage_drops_the_v3_quant_sanity_keys(tmp_path, monkeypatch):
    """The parent salvages a killed v3 run with the legacy extract-only path,
    which rewrites quantitative.json and contested.json: the v3 run's sanity
    keys describe the files it replaces and must not survive into the salvage
    meta (the salvage records its own)."""
    (tmp_path / dr.REPORT_FILENAME).write_text("x" * 1000, encoding="utf-8")
    prior = {"status": "running", "research_engine": "v3", "research_quality": {"score": 0.61},
             "quant_unit_warnings": [{"metric": "Load", "unit": "TWh", "ratio": 1000.0, "values": ["1", "1000"]}],
             "quant_implausible": ["Load: as_of 2027-01-01 is AFTER research cutoff 2026-09-29"],
             "quant_reconcile_contested": 1, "quant_sanity_truncated": {"quant_implausible": 25}}
    (tmp_path / "meta.json").write_text(json.dumps(prior), encoding="utf-8")
    monkeypatch.setenv("MINIMAX_API_KEY", "test-key-not-used")
    seen = {}

    def fake_extract_only(question, out_dir, args, meta, plog, write_meta):
        seen["meta"] = dict(meta)
        plog.close()
        return 0

    monkeypatch.setattr(dr, "run_extract_only", fake_extract_only)
    monkeypatch.setattr(sys, "argv", ["deerflow_research.py", "--extract-only", "--model", "minimax",
                                      "--out-dir", str(tmp_path), "--prompt", "Q"])
    assert dr.main() == 0
    meta = seen["meta"]
    assert meta["salvage"]["mode"] == "extract_only" and meta["research_engine"] == "v3"
    assert (NEW_META_KEYS | {"quant_sanity_truncated"}).isdisjoint(meta)
    assert (NEW_META_KEYS | {"quant_sanity_truncated"}).isdisjoint(_load(tmp_path / "meta.json"))
    # The rest of the v3 meta is still carried over.
    assert meta["research_quality"] == prior["research_quality"]
