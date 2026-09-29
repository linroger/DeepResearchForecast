"""RESEARCH-4: deterministic quantitative-row provenance in the v3 engine.

* RESEARCH_VERIFIED_FACTS (default on): every quantitative.json row whose
  value has a checkable number is labelled against the page of the source it
  cites — ``verification`` in {verified, unverified, snippet_only, none} and a
  ``verified`` bool; values never change.
* RESEARCH_QUANT_TYPING (default off): reported/projected typing
  (``classify_quant_row``), target-date repair when a forecast's target date
  sits in ``as_of_date``, the facts-prompt date rule (memoized by task hash),
  and future-dated rows bucketed apart from fresh ones in ``quant_freshness``
  (the two chart builders read their ``is_future_dated`` mark).

Both off: quantitative.json, the facts task, the extraction memo and meta are
byte-identical to the engine before this change.  Offline: the scripted model,
injected search/fetch and real bridge of ``test_research_engine_v3``.
"""

from __future__ import annotations

import copy
import datetime as dt
import hashlib
import json
import types

import pytest

import test_research_engine_v3 as v3
from app.services import report_visualizer as rv
from test_forecast_visuals_manifest import _load_renderer
from test_orchestrator_research_wiring import _launch_capturing_child

# The shared fixtures (hermetic env, real bridge with network steps stubbed).
_hermetic_env = v3._hermetic_env
bridge = v3.bridge
lr = v3.lr
dr = v3.dr
rg = v3.rg
po = v3.po

AS_OF = dt.date(2026, 9, 28)
LEGACY_FRESHNESS_KEYS = {"fresh_le_90", "recent_le_365", "stale_gt_365", "undated", "n_stale"}
TYPING_KEYS = {"epistemic_class", "date_precision", "target_date", "epistemic_flags"}
VERIFY_KEYS = {"verification", "verified"}


@pytest.fixture
def fixed_as_of(monkeypatch):
    """The plan's as-of date (UTC today in production) pinned for stable dates."""
    monkeypatch.setattr(lr, "_utc_date", lambda: AS_OF.isoformat())


def _knobs(monkeypatch, *, typing: bool, verify: bool) -> None:
    monkeypatch.setenv("RESEARCH_QUANT_TYPING", "true" if typing else "false")
    monkeypatch.setenv("RESEARCH_VERIFIED_FACTS", "true" if verify else "false")


TYPED_FACTS = [
    # [S1] is the first cited source; its fetched page states "176 GW in 2023".
    {"metric": "Installed capacity", "value": "176", "unit": "GW", "as_of_date": "2023-12-31",
     "value_type": "actual", "source_ref": "S1"},
    # A forecast target whose target date sits in as_of_date (no period_end).
    {"metric": "Capacity target", "value": "250", "unit": "GW", "as_of_date": "2030-12-31", "period_end": "",
     "value_type": "target", "source_ref": "S1"},
    # No source marker at all.
    {"metric": "Grid connection queue", "value": "40", "unit": "months", "as_of_date": "2026-06",
     "value_type": "actual", "source_ref": ""},
    # A single digit is no checkable number.
    {"metric": "Regions with queues", "value": "5", "unit": "regions", "as_of_date": "2026-03-01",
     "value_type": "actual", "source_ref": "S1"},
]


class TypedWorld(v3.World):
    """The standard world with a richer facts reply."""

    def __init__(self, quant: list[dict] | None = None, **kwargs) -> None:
        super().__init__(**kwargs)
        self.quant = TYPED_FACTS if quant is None else quant

    def facts(self, call):
        return v3.ai(json.dumps({
            "key_events": [{"date": "2023-12-31", "event": "Capacity reached 176 GW"}],
            "quantitative_facts": self.quant,
            "contested_claims": [{"claim": "2030 capacity", "positions": [{"stance": "250 GW", "sources": ["S1"]}],
                                  "status": "contested", "why_they_differ": "scope"}],
        }))


def _plain_facts_task() -> str:
    """The facts task exactly as the engine rendered it before RESEARCH-4."""
    return lr._render(lr._T_FACTS, max_events=lr.MAX_TIMELINE_ROWS, max_quant=lr.MAX_QUANT_ROWS,
                      max_contested=lr.MAX_CONTESTED_ROWS, language="English")


def _facts_tasks(model) -> list[str]:
    return [call["messages"][-1][1] for call in v3.calls_of(model, "FACT EXTRACTION TASK")]


def _load(path):
    return json.loads(path.read_text(encoding="utf-8"))


# =============================================================== pure helpers

@pytest.mark.parametrize("value, expected", [
    ("2025", dt.date(2025, 12, 31)),
    ("FY2025", dt.date(2025, 12, 31)),
    ("fy 2025", dt.date(2025, 12, 31)),
    ("2025-02", dt.date(2025, 2, 28)),
    ("2024-02", dt.date(2024, 2, 29)),
    ("2025-11", dt.date(2025, 11, 30)),
    ("2025-Q1", dt.date(2025, 3, 31)),
    ("2025q3", dt.date(2025, 9, 30)),
    ("2025-Q4", dt.date(2025, 12, 31)),
    ("2025-H1", dt.date(2025, 6, 30)),
    ("2025-H2", dt.date(2025, 12, 31)),
    ("2026-03-09", dt.date(2026, 3, 9)),
    (" 2026-03-09 ", dt.date(2026, 3, 9)),
    # an ISO date-time is its day
    ("2029-12-31T00:00:00Z", dt.date(2029, 12, 31)),
    ("2025-06-30T12:00:00+08:00", dt.date(2025, 6, 30)),
    ("2025-06-30 12:00", dt.date(2025, 6, 30)),
    ("2025-06-30t08:15:30.5z", dt.date(2025, 6, 30)),
])
def test_period_end_date(value, expected):
    assert lr._period_end_date(value) == expected


@pytest.mark.parametrize("garbage", [None, "", "n/a", "by 2030", "2025-2035", "FY2025-2029", "2025-13",
                                     "2025-02-30", "2025-Q5", "2025-H3", "0000", "Q3 2025", "2026-03-09 draft",
                                     "2026-03-09T", "2026-03-09T25", "2030E"])
def test_period_end_date_returns_none_for_garbage(garbage):
    assert lr._period_end_date(garbage) is None


@pytest.mark.parametrize("value, expected", [
    # a strictly stated period keeps its own bounds and precision
    ("2025-Q3", (dt.date(2025, 7, 1), dt.date(2025, 9, 30), "quarter")),
    ("2029-12-31T00:00:00Z", (dt.date(2029, 12, 31), dt.date(2029, 12, 31), "day")),
    # free text: Jan 1 of the earliest year named to Dec 31 of the latest
    ("2025-2035", (dt.date(2025, 1, 1), dt.date(2035, 12, 31), "year")),
    ("by 2030", (dt.date(2030, 1, 1), dt.date(2030, 12, 31), "year")),
    ("2030E", (dt.date(2030, 1, 1), dt.date(2030, 12, 31), "year")),
    ("FY2025-2029", (dt.date(2025, 1, 1), dt.date(2029, 12, 31), "year")),
    ("FY2025-29", (dt.date(2025, 1, 1), dt.date(2029, 12, 31), "year")),
    ("2025/26", (dt.date(2025, 1, 1), dt.date(2026, 12, 31), "year")),
    ("2025-26", (dt.date(2025, 1, 1), dt.date(2026, 12, 31), "year")),
    ("Q3 2025", (dt.date(2025, 1, 1), dt.date(2025, 12, 31), "year")),
    ("2025-13", (dt.date(2025, 1, 1), dt.date(2025, 12, 31), "year")),     # "13" closes no range
    # no year: nothing to read
    ("ongoing", (None, None, "none")),
    ("20251231", (None, None, "none")),
    (None, (None, None, "none")),
])
def test_loose_period_bounds(value, expected):
    assert lr._loose_period_bounds(value) == expected


@pytest.mark.parametrize("row, expected", [
    # actual in the past → reported
    ({"value_type": "actual", "as_of_date": "2025-11-01"},
     {"epistemic_class": "reported", "date_precision": "day"}),
    # actual dated after as-of → unknown, flagged (a year counts from its END)
    ({"value_type": "actual", "as_of_date": "2026-01-01", "period_end": "2026"},
     {"epistemic_class": "unknown", "date_precision": "year", "epistemic_flags": ["future_dated_reported"]}),
    ({"value_type": "actual", "as_of_date": "2026-09"},
     {"epistemic_class": "unknown", "date_precision": "month", "epistemic_flags": ["future_dated_reported"]}),
    # estimate: reported when its period is over, projected when it is not
    ({"value_type": "estimate", "as_of_date": "2022-01-01", "period_end": "2022-12-31"},
     {"epistemic_class": "reported", "date_precision": "day"}),
    ({"value_type": "estimate", "as_of_date": "2026-03-09", "period_end": "2036"},
     {"epistemic_class": "projected", "date_precision": "year"}),
    ({"value_type": "estimate", "as_of_date": "2026-Q3"},
     {"epistemic_class": "projected", "date_precision": "quarter"}),
    # target repair: the target date sits in as_of_date and period_end is empty
    ({"value_type": "target", "as_of_date": "2029-12-31", "period_end": ""},
     {"epistemic_class": "projected", "date_precision": "day", "target_date": "2029-12-31",
      "epistemic_flags": ["as_of_is_target"]}),
    ({"value_type": "target", "as_of_date": "2030"},
     {"epistemic_class": "projected", "date_precision": "year", "target_date": "2030",
      "epistemic_flags": ["as_of_is_target"]}),
    ({"value_type": "forecast", "as_of_date": "2026-12"},
     {"epistemic_class": "projected", "date_precision": "month", "target_date": "2026-12",
      "epistemic_flags": ["as_of_is_target"]}),
    # the target is in period_end already: flagged, no target_date
    ({"value_type": "forecast", "as_of_date": "2035-12-31", "period_end": "2035"},
     {"epistemic_class": "projected", "date_precision": "year", "epistemic_flags": ["as_of_is_target"]}),
    # a coarse date of the current period may be the publication date: no repair
    ({"value_type": "forecast", "as_of_date": "2026", "period_end": ""},
     {"epistemic_class": "projected", "date_precision": "year"}),
    ({"value_type": "target", "as_of_date": "2026-09", "period_end": "2030"},
     {"epistemic_class": "projected", "date_precision": "year"}),
    # a properly dated forecast needs no repair
    ({"value_type": "forecast", "as_of_date": "2025-06", "period_end": "2030-H2"},
     {"epistemic_class": "projected", "date_precision": "half"}),
    # a free-text period_end is read by the years it names — never replaced by the publication date
    ({"value_type": "estimate", "as_of_date": "2024-07-01", "period_end": "2025-2035"},
     {"epistemic_class": "projected", "date_precision": "year"}),
    ({"value_type": "estimate", "as_of_date": "2025-01-01", "period_end": "by 2030"},
     {"epistemic_class": "projected", "date_precision": "year"}),
    ({"value_type": "estimate", "as_of_date": "2025-01-01", "period_end": "2030E"},
     {"epistemic_class": "projected", "date_precision": "year"}),
    ({"value_type": "estimate", "as_of_date": "2025-01-01", "period_end": "2025/26"},
     {"epistemic_class": "projected", "date_precision": "year"}),
    ({"value_type": "estimate", "as_of_date": "2025-03-01", "period_end": "FY2024-25"},
     {"epistemic_class": "reported", "date_precision": "year"}),
    ({"value_type": "actual", "as_of_date": "2025-03-01", "period_end": "by 2027"},
     {"epistemic_class": "unknown", "date_precision": "year", "epistemic_flags": ["future_dated_reported"]}),
    # a period_end that names no year cannot be placed: never reported
    ({"value_type": "estimate", "as_of_date": "2025-01-01", "period_end": "ongoing"},
     {"epistemic_class": "unknown", "date_precision": "none", "epistemic_flags": ["period_unparsed"]}),
    ({"value_type": "actual", "as_of_date": "2025-01-01", "period_end": "cumulative to date"},
     {"epistemic_class": "unknown", "date_precision": "none", "epistemic_flags": ["period_unparsed"]}),
    ({"value_type": "forecast", "as_of_date": "2025-01-01", "period_end": "long term"},
     {"epistemic_class": "projected", "date_precision": "none", "epistemic_flags": ["period_unparsed"]}),
    ({"value_type": "forecast", "as_of_date": "2031", "period_end": "long term"},
     {"epistemic_class": "projected", "date_precision": "none", "target_date": "2031",
      "epistemic_flags": ["period_unparsed", "as_of_is_target"]}),
    # ... but a placeholder is no period
    ({"value_type": "actual", "as_of_date": "2025-01-01", "period_end": "N/A"},
     {"epistemic_class": "reported", "date_precision": "day"}),
    ({"value_type": "actual", "as_of_date": "2025-01-01", "period_end": " — "},
     {"epistemic_class": "reported", "date_precision": "day"}),
    # an as_of_date after as-of is no publication date, whatever period_end says
    ({"value_type": "actual", "as_of_date": "2029-12-31T00:00:00Z"},
     {"epistemic_class": "unknown", "date_precision": "day", "epistemic_flags": ["future_dated_reported"]}),
    ({"value_type": "actual", "as_of_date": "2030E"},
     {"epistemic_class": "unknown", "date_precision": "year", "epistemic_flags": ["future_dated_reported"]}),
    ({"value_type": "actual", "as_of_date": "2027-03", "period_end": "2025"},
     {"epistemic_class": "unknown", "date_precision": "year", "epistemic_flags": ["future_dated_reported"]}),
    ({"value_type": "estimate", "as_of_date": "2027-03", "period_end": "2025"},
     {"epistemic_class": "unknown", "date_precision": "year", "epistemic_flags": ["future_dated_reported"]}),
    ({"value_type": "actual", "as_of_date": "2025-06-30T12:00:00+08:00"},
     {"epistemic_class": "reported", "date_precision": "day"}),
    # target dates read by quarter or fiscal year
    ({"value_type": "target", "as_of_date": "2026-Q4"},
     {"epistemic_class": "projected", "date_precision": "quarter", "target_date": "2026-Q4",
      "epistemic_flags": ["as_of_is_target"]}),
    ({"value_type": "target", "as_of_date": "FY2027"},
     {"epistemic_class": "projected", "date_precision": "year", "target_date": "FY2027",
      "epistemic_flags": ["as_of_is_target"]}),
    # missing or unknown value_type → unknown
    ({"as_of_date": "2025-11-01"}, {"epistemic_class": "unknown", "date_precision": "day"}),
    ({"value_type": "guidance", "as_of_date": "2031"}, {"epistemic_class": "unknown", "date_precision": "year"}),
    ({"value_type": "actual"}, {"epistemic_class": "reported", "date_precision": "none"}),
])
def test_classify_table(row, expected):
    assert lr.classify_quant_row(row, AS_OF) == expected


def test_classify_table_never_touches_evidence_fields():
    row = {"metric": "Capacity target", "value": "250", "unit": "GW", "as_of_date": "2029-12-31", "period_end": "",
           "value_type": "target", "source": "Agency", "source_url": "https://www.iea.org/x", "tier": "S1"}
    before = copy.deepcopy(row)
    added = lr.classify_quant_row(row, AS_OF)
    assert row == before
    assert set(added) <= TYPING_KEYS and not set(added) & set(row)
    # A datetime as-of is taken as its date.
    assert lr.classify_quant_row(row, dt.datetime(2026, 9, 28, 12, 0)) == added


def test_classify_never_reports_a_period_that_has_not_ended():
    as_of_dates = ("2026-09-28", "2026-09", "2026-Q3", "2026-H2", "2026", "2027-01-15", "2026-09-29T00:00:00Z",
                   "2030E", "2024-07-01")
    period_ends = ("", "2025", "2026-09", "2025-2035", "by 2030", "2030E", "FY2025-29", "ongoing", "n/a")
    for as_of_date in as_of_dates:
        for period_end in period_ends:
            for value_type in ("actual", "estimate", "forecast", "target", None):
                row = {"value_type": value_type, "as_of_date": as_of_date, "period_end": period_end}
                if lr.classify_quant_row(row, AS_OF)["epistemic_class"] != "reported":
                    continue
                published, _, _ = lr._loose_period_bounds(as_of_date)
                assert published is None or published <= AS_OF, row
                assert (lr._loose_period_bounds(period_end)[1] or lr._loose_period_bounds(as_of_date)[1]) <= AS_OF, row


PAGE = ("Installed capacity reached 176 GW in 2023. Spending hit $1,200 billion. "
        "Demand grows 12% per year across 176 pages of tables.")


@pytest.mark.parametrize("value, unit, page, snippet, expected", [
    ("176", "GW", PAGE, "", (True, "page")),
    ("176 GW", "", PAGE, "", (True, "page")),
    ("12", "%", PAGE, "", (True, "page")),
    ("$1.2 trillion", "", PAGE, "", (True, "page")),
    ("1.2", "trillion USD", PAGE, "", (True, "page")),
    # the value is only in the search snippet (page fetched or never fetched)
    ("250", "GW", PAGE, "Operators plan 250 GW by 2030", (False, "snippet_only")),
    ("250", "GW", None, "Operators plan 250 GW by 2030", (False, "snippet_only")),
    # absent everywhere, or present as another quantity ("176 pages" is no power figure)
    ("250", "GW", PAGE, "Capacity outlook", (False, "none")),
    ("250", "GW", None, "", (False, "none")),
    ("176", "MW", "Printed on 176 pages.", "", (False, "none")),
    # no number of >= 2 digits or a decimal: nothing to check
    ("5", "", PAGE, "", (False, "not_checkable")),
    ("5", "regions", PAGE, "5 regions", (False, "not_checkable")),
    ("several", "", PAGE, "", (False, "not_checkable")),
])
def test_verify_quant_row(value, unit, page, snippet, expected):
    pages = lr.page_number_set(page) if page is not None else None
    row = {"metric": "m", "value": value, "unit": unit}
    assert lr.verify_quant_row(row, pages, snippet) == expected


def test_verify_quant_row_numeric_values():
    pages = lr.page_number_set(PAGE)
    assert lr.verify_quant_row({"value": 176, "unit": "GW"}, pages, "") == (True, "page")
    assert lr.verify_quant_row({"value": 176.0, "unit": "GW"}, pages, "") == (True, "page")
    assert lr.verify_quant_row({"value": 12}, pages, "") == (True, "page")


def test_verify_quant_row_never_matches_an_exponent_by_its_parts():
    """str(1.2e-05) is "1.2e-05": its mantissa alone matched "1.2 billion"."""
    billion = lr.page_number_set("Spending hit 1.2 billion; 20 regions report.")
    assert lr.verify_quant_row({"value": 1.2e-05}, billion, "") == (False, "none")
    assert lr.verify_quant_row({"value": 1e20}, billion, "") == (False, "none")
    # A float is written out positionally, so its real digits still verify.
    dose = lr.page_number_set("The limit is 0.000012 mg per litre.")
    assert lr.verify_quant_row({"value": 1.2e-05, "unit": "mg"}, dose, "") == (True, "page")
    # Exponent notation in text cannot be tokenized honestly: unchecked.
    for value in ("1.2E6", "3.5e9 dollars", "2e+3"):
        assert lr.verify_quant_row({"value": value, "unit": "USD"}, billion, "1.2 billion") == (False, "not_checkable")
    for value in (float("nan"), float("inf"), True, None):
        assert lr.verify_quant_row({"value": value}, billion, "") == (False, "not_checkable")


# ============================================================ engine row labelling

def test_verify_quant_rows_stamps_the_closed_enum(tmp_path):
    """Source resolution through the ledger and the stored label per case."""
    ledger = rg.SourceLedger(tmp_path / "ledger.json")
    fetched = ledger.register("https://www.iea.org/fetched", "Fetched", "Outlook: 999 GW by 2030")
    ledger.mark_fetched(fetched["sid"], content_sha256="x", chars=10, page_path=str(tmp_path / "p1.txt"))
    lost = ledger.register("https://www.iea.org/lost-page", "Lost", "")
    ledger.mark_fetched(lost["sid"], content_sha256="y", chars=10, page_path=str(tmp_path / "missing.txt"))
    cited = ledger.register("https://www.iea.org/cited", "Cited", "Capacity of 176 GW")
    pages = {fetched["sid"]: lr.page_number_set("Installed capacity reached 176 GW in 2023.")}
    engine = types.SimpleNamespace(ledger=ledger, page_numbers=pages.get)

    def row(value, url=None, unit="GW"):
        out = {"metric": "m", "value": value, "unit": unit}
        if url:
            out["source_url"] = url
        return out

    rows = [
        row("176", fetched["url"]),                     # on the fetched page
        row("250", fetched["url"]),                     # fetched, not on the page
        row("999", fetched["url"]),                     # fetched, only in its snippet
        row("176", cited["url"]),                       # never fetched
        row("5", cited["url"], "regions"),              # never fetched, no checkable number
        row("176", lost["url"]),                        # fetched but its page text is gone
        row("5", fetched["url"], "regions"),            # fetched, no checkable number
        row("176"),                                     # no source
        row("176", "https://unknown.example.org/x"),    # a source the ledger never saw
    ]
    before = copy.deepcopy(rows)
    lr._Engine._verify_quant_rows(engine, rows)
    assert [r.get("verification") for r in rows] == [
        "verified", "unverified", "unverified", "snippet_only", "snippet_only", "snippet_only", None, "none", "none"]
    assert [r.get("verified") for r in rows] == [True, False, False, False, False, False, None, False, False]
    for got, was in zip(rows, before, strict=True):
        assert {k: v for k, v in got.items() if k not in VERIFY_KEYS} == was   # values never modified


def test_verify_quant_rows_stamps_all_or_nothing(tmp_path):
    """A failure part-way leaves no row labelled (never a half-labelled table)."""
    ledger = rg.SourceLedger(tmp_path / "ledger.json")
    fetched = ledger.register("https://www.iea.org/fetched", "Fetched", "")
    ledger.mark_fetched(fetched["sid"], content_sha256="x", chars=10, page_path=str(tmp_path / "p1.txt"))
    reads = []

    def page_numbers(sid):
        reads.append(sid)
        if len(reads) > 1:
            raise OSError("page store unreadable")
        return lr.page_number_set("Installed capacity reached 176 GW in 2023.")

    engine = types.SimpleNamespace(ledger=ledger, page_numbers=page_numbers)
    rows = [{"metric": "m", "value": "176", "unit": "GW", "source_url": fetched["url"]} for _ in range(3)]
    before = copy.deepcopy(rows)
    with pytest.raises(OSError):
        lr._Engine._verify_quant_rows(engine, rows)
    assert rows == before and len(reads) == 2


class _StubEngine:
    def __init__(self, fail: bool = False) -> None:
        self.meta: dict = {}
        self.analytics_errors: list[dict] = []
        self.lines: list[tuple[str, str]] = []
        self.fail = fail

    def log(self, kind, message):
        self.lines.append((kind, message))

    def _verify_quant_rows(self, quant):
        if self.fail:
            raise RuntimeError("page store unreadable")
        for row in quant[:1]:
            row.update(verification="verified", verified=True)


def _failing_classifier(monkeypatch):
    """classify_quant_row that fails on the second row, after typing the first."""
    real, seen = lr.classify_quant_row, []

    def classify(row, as_of):
        seen.append(row)
        if len(seen) > 1:
            raise ValueError("bad period")
        return real(row, as_of)

    monkeypatch.setattr(lr, "classify_quant_row", classify)


def test_quant_provenance_summary_has_only_the_enabled_parts():
    rows = [{"value": "176", "as_of_date": "2023-12-31", "value_type": "actual"},
            {"value": "250", "as_of_date": "2030-12-31", "value_type": "target"}]
    engine = _StubEngine()
    lr._Engine._quant_provenance(engine, copy.deepcopy(rows), AS_OF, verify=True, typing=False)
    assert engine.meta["quant_provenance"] == {"rows": 2, "verification_hist": {"unchecked": 1, "verified": 1},
                                               "verified_ratio": 1.0}
    engine = _StubEngine()
    typed = copy.deepcopy(rows)
    lr._Engine._quant_provenance(engine, typed, AS_OF, verify=False, typing=True)
    assert engine.meta["quant_provenance"] == {"rows": 2, "class_hist": {"projected": 1, "reported": 1},
                                               "future_dated_reported": 0, "period_unparsed": 0,
                                               "as_of_is_target": 1}
    assert "verification" not in typed[0] and typed[1]["target_date"] == "2030-12-31"
    engine = _StubEngine()
    lr._Engine._quant_provenance(engine, [], AS_OF, verify=True, typing=True)
    assert engine.meta["quant_provenance"] == {"rows": 0, "class_hist": {}, "verification_hist": {},
                                               "verified_ratio": None, "future_dated_reported": 0,
                                               "period_unparsed": 0, "as_of_is_target": 0}


ROWS = [{"value": "176", "as_of_date": "2023-12-31", "value_type": "actual"},
        {"value": "250", "as_of_date": "2030-12-31", "value_type": "target"}]


def test_quant_provenance_verification_failure_still_types():
    engine = _StubEngine(fail=True)
    rows = copy.deepcopy(ROWS)
    lr._Engine._quant_provenance(engine, rows, AS_OF, verify=True, typing=True)
    assert engine.analytics_errors == [{"helper": "quant_provenance:verify",
                                        "error": "RuntimeError: page store unreadable"}]
    assert engine.lines[0] == ("warn", "v3: quantitative provenance (verify) failed "
                                       "(RuntimeError: page store unreadable)")
    # Typing ran and is summarised; verification claims nothing.
    assert engine.meta["quant_provenance"] == {"rows": 2, "class_hist": {"projected": 1, "reported": 1},
                                               "future_dated_reported": 0, "period_unparsed": 0,
                                               "as_of_is_target": 1}
    assert [row["epistemic_class"] for row in rows] == ["reported", "projected"]
    assert not any(VERIFY_KEYS & set(row) for row in rows)


def test_quant_provenance_typing_failure_still_verifies(monkeypatch):
    _failing_classifier(monkeypatch)
    engine = _StubEngine()
    rows = copy.deepcopy(ROWS)
    lr._Engine._quant_provenance(engine, rows, AS_OF, verify=True, typing=True)
    assert engine.analytics_errors == [{"helper": "quant_provenance:typing", "error": "ValueError: bad period"}]
    assert engine.meta["quant_provenance"] == {"rows": 2, "verification_hist": {"unchecked": 1, "verified": 1},
                                               "verified_ratio": 1.0}
    # The first row's classification was never stamped: typing is all or nothing.
    assert rows == [dict(ROWS[0], verification="verified", verified=True), ROWS[1]]


def test_quant_provenance_degrades_safe(monkeypatch):
    _failing_classifier(monkeypatch)
    engine = _StubEngine(fail=True)
    rows = copy.deepcopy(ROWS)
    lr._Engine._quant_provenance(engine, rows, AS_OF, verify=True, typing=True)
    assert "quant_provenance" not in engine.meta
    assert [error["helper"] for error in engine.analytics_errors] == ["quant_provenance:verify",
                                                                      "quant_provenance:typing"]
    assert [kind for kind, _ in engine.lines] == ["warn", "warn"]
    assert rows == ROWS   # nothing half-claimed


# =============================================================== engine end to end

def test_engine_flag_on(tmp_path, bridge, monkeypatch, fixed_as_of):
    _knobs(monkeypatch, typing=True, verify=True)
    rc, meta, plog, model, out = v3.run_engine(tmp_path, bridge, TypedWorld())
    assert rc == 0, meta.get("error")
    sources = _load(out / "sources.json")
    assert sources[0]["source_origin"] == "fetched"
    quant = _load(out / "quantitative.json")
    capacity, target, queue, regions = quant

    # [S1] 176 GW: on the fetched page, a past actual.
    assert capacity["value"] == "176" and capacity["source_url"] == sources[0]["url"]
    assert capacity["verified"] is True and capacity["verification"] == "verified"
    assert capacity["epistemic_class"] == "reported" and capacity["date_precision"] == "day"
    assert "epistemic_flags" not in capacity and "target_date" not in capacity
    # The target row: its target date moves to target_date; it is future-dated, not fresh.
    assert target["epistemic_class"] == "projected" and target["target_date"] == "2030-12-31"
    assert target["epistemic_flags"] == ["as_of_is_target"] and target["as_of_date"] == "2030-12-31"
    assert target["verification"] == "unverified" and target["verified"] is False   # 250 is not on the page
    assert target["staleness_days"] is None and target["is_stale"] is False and target["is_future_dated"] is True
    # No resolvable source; a single digit is left unchecked.
    assert queue["verification"] == "none" and queue["verified"] is False and "source_url" not in queue
    assert regions["value"] == "5" and not VERIFY_KEYS & set(regions)
    assert all(VERIFY_KEYS <= set(row) for row in quant if row is not regions)

    assert meta["quant_provenance"] == {
        "rows": 4, "class_hist": {"projected": 1, "reported": 3},
        "verification_hist": {"none": 1, "unchecked": 1, "unverified": 1, "verified": 1},
        "verified_ratio": round(1 / 3, 3), "future_dated_reported": 0, "period_unparsed": 0, "as_of_is_target": 1}
    assert meta["quant_freshness"] == {"fresh_le_90": 0, "recent_le_365": 2, "stale_gt_365": 1, "undated": 0,
                                       "n_stale": 1, "future_dated": 1}
    assert _load(out / "meta.json")["quant_provenance"] == meta["quant_provenance"]
    assert any(m.startswith("v3: quantitative provenance: ") for m in plog.of("ok"))

    # The facts task carries the date rule once, after the template's own rules.
    (task,) = _facts_tasks(model)
    assert task == _plain_facts_task() + "\n- " + lr._FACTS_DATE_RULE
    memo = _load(out / "v3" / "extract" / "facts.json")
    assert memo["task_sha256"] == hashlib.sha256(task.encode("utf-8")).hexdigest()
    # Timeline recency is untouched by typing.
    assert "future_dated" not in meta["timeline_freshness"]


def test_engine_defaults_verify_but_do_not_type(tmp_path, bridge, fixed_as_of):
    """Knobs unset: verification on, typing and its prompt rule off."""
    rc, meta, _, model, out = v3.run_engine(tmp_path, bridge, TypedWorld())
    assert rc == 0, meta.get("error")
    quant = _load(out / "quantitative.json")
    assert [row.get("verification") for row in quant] == ["verified", "unverified", "none", None]
    assert not any(TYPING_KEYS & set(row) or "is_future_dated" in row for row in quant)
    assert set(meta["quant_provenance"]) == {"rows", "verification_hist", "verified_ratio"}
    assert set(meta["quant_freshness"]) == LEGACY_FRESHNESS_KEYS
    assert _facts_tasks(model) == [_plain_facts_task()]
    assert "task_sha256" not in _load(out / "v3" / "extract" / "facts.json")


def test_flag_off_byte_identical(tmp_path, bridge, monkeypatch, fixed_as_of):
    """Both knobs off: the artifacts equal what the pre-RESEARCH-4 finalize
    produced from the same extraction (normalize → enrich → annotate)."""
    _knobs(monkeypatch, typing=False, verify=False)
    rc, meta, plog, model, out = v3.run_engine(tmp_path, bridge, TypedWorld())
    assert rc == 0, meta.get("error")
    sources = _load(out / "sources.json")
    baseline = lr.normalize_quant(copy.deepcopy(TYPED_FACTS), sources)
    baseline = dr.enrich_quantitative_rows(baseline)
    legacy_hist = dr.annotate_recency_rows(baseline, AS_OF, lr.DEFAULT_STALE_DAYS, date_key="as_of_date")
    assert (out / "quantitative.json").read_bytes() == json.dumps(baseline, ensure_ascii=False,
                                                                   indent=2).encode("utf-8")
    assert _facts_tasks(model) == [_plain_facts_task()]
    assert set(_load(out / "v3" / "extract" / "facts.json")) == {"report_sha256", "result", "truncated"}
    assert "quant_provenance" not in meta and meta["quant_freshness"] == legacy_hist
    assert set(legacy_hist) == LEGACY_FRESHNESS_KEYS
    assert not any(m.startswith("v3: quantitative provenance") for m in plog.of("ok"))


def test_facts_memo_task_hash(tmp_path, bridge, monkeypatch, fixed_as_of):
    out = tmp_path / "out"
    _knobs(monkeypatch, typing=False, verify=False)
    rc, _, _, _, _ = v3.run_engine(tmp_path, bridge, TypedWorld(), out_dir=out)
    assert rc == 0
    memo_path = out / "v3" / "extract" / "facts.json"
    assert "task_sha256" not in _load(memo_path)

    # Flag off: a memo without task_sha256 is reused — zero model calls.
    silent = v3.ScriptedModel(lambda call: pytest.fail(f"unexpected model call: {v3.role_of(call)}"))
    rc, _, _, model, _ = v3.run_engine(tmp_path, bridge, TypedWorld(), out_dir=out, model=silent)
    assert rc == 0 and model.calls == []

    def facts_only(world):
        return v3.ScriptedModel(lambda call: world(call) if v3.role_of(call) == "FACT EXTRACTION TASK"
                                else pytest.fail(f"unexpected model call: {v3.role_of(call)}"))

    # Flag on: the task changed, so facts (only) are extracted again and hashed.
    _knobs(monkeypatch, typing=True, verify=False)
    world = TypedWorld()
    rc, meta, _, model, _ = v3.run_engine(tmp_path, bridge, world, out_dir=out, model=facts_only(world))
    assert rc == 0, meta.get("error")
    (task,) = _facts_tasks(model)
    assert task.endswith("\n- " + lr._FACTS_DATE_RULE) and len(model.calls) == 1
    assert _load(memo_path)["task_sha256"] == hashlib.sha256(task.encode("utf-8")).hexdigest()

    # Same task again: reused.
    rc, _, _, model, _ = v3.run_engine(tmp_path, bridge, TypedWorld(), out_dir=out, model=silent)
    assert rc == 0 and model.calls == []

    # Flag off again: a memo made for the extended task is not reused.
    _knobs(monkeypatch, typing=False, verify=False)
    rc, _, _, model, _ = v3.run_engine(tmp_path, bridge, world, out_dir=out, model=facts_only(world))
    assert rc == 0 and _facts_tasks(model) == [_plain_facts_task()] and len(model.calls) == 1
    assert "task_sha256" not in _load(memo_path)


# ======================================= acceptance: pipe_6c4190b31f0b-shaped rows

# The 57 quantitative rows of live run pipe_6c4190b31f0b (as of 2026-09-28;
# five unit labels shortened to fit the line):
# [metric, value, unit, as_of_date, period_end, value_type].  14 rows put a
# forecast's target date in as_of_date and were counted as fresh_le_90.
PIPE_ROWS = [
    ["qubit count", "105", "qubits", "2024-12-01", "", "actual"],
    ["two-qubit gate fidelity (parallel)", "99.62", "%", "2025-03-03", "", "actual"],
    ["logical qubits", "200", "logical qubits", "2029-12-31", "", "target"],
    ["physical qubits", "98", "qubits", "2025-11-01", "", "actual"],
    ["two-qubit gate fidelity (all pairs)", "99.921", "%", "2025-11-01", "", "actual"],
    ["error-corrected logical qubits", "48", "logical qubits", "2025-11-01", "", "actual"],
    ["two-qubit gate fidelity", "99.99", "%", "2025-10-01", "", "actual"],
    ["physical qubits", "260", "qubits", "2025-01-01", "", "actual"],
    ["logical qubits", "256", "logical qubits", "2028-12-31", "", "target"],
    ["detected photons", "255", "photons", "2023-01-01", "", "actual"],
    ["photons", "3050", "photons", "2025-08-12", "", "actual"],
    ["physical qubits", "180", "computational qubits", "2025-12-01", "", "actual"],
    ["suppression factor", "1.40(6)", "Λ (dimensionless)", "2025-12-22", "", "actual"],
    ["US federal quantum R&D spending", "1", "billion USD", "2022-01-01", "2022-12-31", "estimate"],
    ["authorization in lapsed bill", "1.8", "billion USD", "2024-07-25", "FY2025-2029", "target"],
    ["cumulative global public quantum funding", "56.7", "billion USD", "2025-12-31", "", "estimate"],
    ["Chinese government quantum funding", "15", "billion USD (approximately)", "2022-01-01", "", "estimate"],
    ["cumulative US private quantum funding", "3.7", "billion USD (approx.)", "2025-01-01", "", "estimate"],
    ["cumulative Chinese private quantum funding", "255", "million USD (approx.)", "2025-01-01", "", "estimate"],
    ["Origin Quantum total raise", "150-165", "million USD (approximately)", "2025-01-01", "", "estimate"],
    ["global quantum start-up investment", "12.6", "billion USD", "2025-12-31", "2025", "actual"],
    ["global quantum start-up investment", "1.7", "billion USD", "2023-12-31", "2023", "actual"],
    ["global quantum venture capital", "4.9", "billion USD", "2025-12-31", "2025", "actual"],
    ["global quantum-computing revenue", "1.4", "billion USD", "2025-12-31", "2025", "actual"],
    ["global quantum-computing revenue forecast", "3", "billion USD", "2028-12-31", "2028", "forecast"],
    ["pure-play quantum companies in EU", "173", "companies", "2025-12-31", "", "actual"],
    ["pure-play quantum companies in US", "164", "companies", "2025-12-31", "", "actual"],
    ["pure-play quantum workforce", "16500", "professionals (approximately)", "2025-12-31", "2025", "actual"],
    ["economic value for companies by 2035", "1.3-2.7", "trillion USD", "2035-12-31", "2035", "forecast"],
    ["economic value creation by 2040", "450-850", "billion USD", "2040-12-31", "2040", "forecast"],
    ["quantum-computing revenue 2035 forecast", "28-72", "billion USD", "2035-12-31", "2035", "forecast"],
    ["quantum-computing revenue 2040 forecast", "20.20", "billion USD", "2035-12-31", "2035", "forecast"],
    ["quantum-computing market 2030 forecast", "7.3", "billion USD", "2030-12-31", "2030", "forecast"],
    ["finance sector value by 2035", "400-600", "billion USD", "2035-12-31", "2035", "forecast"],
    ["pharmaceuticals value by 2035", "50-400", "billion USD", "2035-12-31", "2035", "forecast"],
    ["federal PQC migration cost estimate", "7.1", "billion USD (2024)", "2024-07-01", "2025-2035", "estimate"],
    ["PQC products-and-services market", "1.9", "billion USD", "2025-12-31", "2025", "estimate"],
    ["expert probability of CRQC within ten years", "28-49", "%", "2026-03-09", "2036", "estimate"],
    ["expert probability of CRQC within fifteen years", "51-70", "%", "2026-03-09", "2041", "estimate"],
    ["bulk helium-3 price", "1900-2600", "USD per liter", "2025-01-01", "", "estimate"],
    ["rare-earth reserve share", "69", "% of global reserves", "2025-01-01", "", "actual"],
    ["dilution-refrigerator market share", "70", "% (approximately)", "2025-01-01", "", "estimate"],
    ["EuroHPC quantum-technology funding calls", "119", "million EUR", "2026-01-01", "2026", "actual"],
    ["European public quantum pledges", "12", "billion USD (approximately)", "2025-01-01", "", "estimate"],
    ["China emerging-technology fund", "138", "billion USD", "2025-01-01", "", "estimate"],
    ["PsiQuantum DARPA agreement", "125", "million USD", "2025-01-01", "", "estimate"],
    ["IonQ 2028 roadmap", "1600", "logical qubits (approximately)", "2028-12-31", "", "target"],
    ["IonQ acquisition of Oxford Ionics", "1.1", "billion USD (approximately)", "2025-12-31", "2025", "actual"],
    ["China kiloqubit target", "1000", "qubits (qubit-class)", "2030-12-31", "", "target"],
    ["quantum jobs projection 2035", "250000", "new jobs (approx.)", "2035-12-31", "2035", "forecast"],
    ["quantum jobs projection 2035", "840000", "jobs (approximately)", "2035-12-31", "2035", "forecast"],
    ["Heron r2/r3 qubit count", "156", "qubits", "2025-01-01", "", "actual"],
    ["IBM gross-code encoding", "12 logical into 288 physical", "qubits", "2024-01-01", "2024", "actual"],
    ["Quantum Volume record", "65536", "Quantum Volume", "2023-05-09", "", "actual"],
    ["Liangyi Technology revenue", "74.35", "million yuan (¥)", "2024-12-31", "2024", "actual"],
    ["Tianyan cloud platform visits", "37", "million visits (over, reported)", "2025-01-01", "", "estimate"],
    ["quantum-engaged organizations worldwide", "7418", "organizations", "2025-12-31", "", "actual"],
]
_PIPE_FIELDS = ("metric", "value", "unit", "as_of_date", "period_end", "value_type")


def _pipe_facts() -> list[dict]:
    return [dict(zip(_PIPE_FIELDS, row, strict=True)) for row in PIPE_ROWS]


def _reference_date(row: dict) -> dt.date | None:
    """The classifier's reference date: period_end's end, else as_of_date's, free text read by its years."""
    return lr._loose_period_bounds(row.get("period_end"))[1] or lr._loose_period_bounds(row.get("as_of_date"))[1]


def test_pipe_fixture_rows_are_typed_and_future_rows_leave_the_fresh_bucket():
    rows = _pipe_facts()
    legacy = dr.annotate_recency_rows(copy.deepcopy(rows), AS_OF, 365, date_key="as_of_date")
    assert len(rows) == 57
    # The live run's meta.quant_freshness: every "fresh" row was a future target date.
    assert legacy == {"fresh_le_90": 14, "recent_le_365": 19, "stale_gt_365": 24, "undated": 0, "n_stale": 24}
    for row in rows:
        row.update(lr.classify_quant_row(row, AS_OF))
    hist = dr.annotate_recency_rows(rows, AS_OF, 365, date_key="as_of_date", future_bucket=True)

    assert not [r["metric"] for r in rows if r["epistemic_class"] == "reported" and _reference_date(r) > AS_OF]
    future = [r for r in rows if lr._period_end_date(r["as_of_date"]) > AS_OF]
    assert len(future) == 14
    assert all(r["epistemic_class"] == "projected" and "as_of_is_target" in r["epistemic_flags"]
               and r["is_future_dated"] is True and r["staleness_days"] is None for r in future)
    # Without a period_end the target date moves to target_date; otherwise period_end holds it.
    assert all(r.get("target_date") == (r["as_of_date"] if not r["period_end"] else None) for r in future)
    assert sorted(r["target_date"] for r in future if "target_date" in r) == [
        "2028-12-31", "2028-12-31", "2029-12-31", "2030-12-31"]
    assert hist["fresh_le_90"] == 0 and hist["future_dated"] == 14
    assert sum(hist[k] for k in ("fresh_le_90", "recent_le_365", "stale_gt_365", "undated", "future_dated")) == 57
    # The one actual for a period not yet over is not reported.
    (euro,) = [r for r in rows if r["metric"].startswith("EuroHPC")]
    assert euro["epistemic_class"] == "unknown" and euro["epistemic_flags"] == ["future_dated_reported"]
    # A cost estimate for "2025-2035" (published 2024-07) is a projection, not a reported number.
    (pqc,) = [r for r in rows if r["metric"] == "federal PQC migration cost estimate"]
    assert pqc["epistemic_class"] == "projected" and pqc["date_precision"] == "year"
    assert not [r["metric"] for r in rows if "period_unparsed" in r.get("epistemic_flags", ())]


def test_pipe_fixture_through_the_engine(tmp_path, bridge, monkeypatch, fixed_as_of):
    _knobs(monkeypatch, typing=True, verify=True)
    facts = [dict(row, source_ref="") for row in _pipe_facts()]
    rc, meta, _, _, out = v3.run_engine(tmp_path, bridge, TypedWorld(quant=facts))
    assert rc == 0, meta.get("error")
    quant = _load(out / "quantitative.json")
    assert len(quant) == 57
    assert not [r["metric"] for r in quant if r["epistemic_class"] == "reported" and _reference_date(r) > AS_OF]
    assert meta["quant_freshness"]["fresh_le_90"] == 0 and meta["quant_freshness"]["future_dated"] == 14
    provenance = meta["quant_provenance"]
    assert provenance["as_of_is_target"] == 14 and provenance["future_dated_reported"] == 1
    assert provenance["verification_hist"] == {"none": 57}
    assert all(row["verification"] == "none" and row["verified"] is False for row in quant)


# ============================================== chart builders read the typed rows

def _pack_price(value: str, as_of_date: str, source: str, value_type: str = "actual") -> dict:
    return {"metric": "battery pack price", "value": value, "unit": "USD per kWh", "as_of_date": as_of_date,
            "value_type": value_type, "source": source, "definition": "average lithium-ion battery pack price"}


def test_chart_builders_never_plot_future_dated_actuals_from_typed_rows():
    """Typed recency withholds a future row's age (staleness_days None), which
    the chart builders read as their only future-dated guard: is_future_dated
    must keep a future 'actual' off the observed-value panels."""
    renderer = _load_renderer()
    rows = [_pack_price("115", "2025-12-31", "IEA"), _pack_price("118", "2025-12-31", "BNEF"),
            _pack_price("80", "2027-12-31", "Agency A"), _pack_price("82", "2027-12-31", "Agency B"),
            _pack_price("70", "2030-12-31", "Agency A", "forecast"),
            _pack_price("72", "2030-12-31", "Agency B", "forecast")]
    legacy = copy.deepcopy(rows)
    dr.annotate_recency_rows(legacy, AS_OF, 365, date_key="as_of_date")
    typed = copy.deepcopy(rows)
    for row in typed:
        row.update(lr.classify_quant_row(row, AS_OF))
    dr.annotate_recency_rows(typed, AS_OF, 365, date_key="as_of_date", future_bucket=True)
    assert [row.get("is_future_dated") for row in typed] == [None, None, True, True, True, True]
    assert typed[2]["epistemic_class"] == "unknown" and typed[2]["staleness_days"] is None

    def report_panels(annotated):
        return [[(row["value"], row["projection"]) for row in panel["rows"]]
                for panel in rv._prepare_quantitative_panels(annotated)]

    def skill_panels(annotated):
        return [[(bar["value"], bar["projection"]) for bar in panel["bars"]]
                for panel in renderer.prep_quant(annotated)["panels"]]

    assert report_panels(typed) == report_panels(legacy) == [[(115.0, False), (118.0, False)]]
    # The future forecasts still chart, as projections.
    assert skill_panels(typed) == skill_panels(legacy) == [[(115.0, False), (118.0, False)],
                                                            [(70.0, True), (72.0, True)]]


# ================================================================== parent wiring

def test_runner_forwards_quant_knobs_from_config_to_v3_only(monkeypatch, tmp_path):
    for name in ("defaults", "flipped", "legacy"):
        (tmp_path / name).mkdir()
    monkeypatch.setattr(po.Config, "RESEARCH_ENGINE", "v3", raising=False)
    monkeypatch.setattr(po.Config, "RESEARCH_VERIFIED_FACTS", True, raising=False)
    monkeypatch.setattr(po.Config, "RESEARCH_QUANT_TYPING", False, raising=False)
    # Ambient env never decides: the parent's Config does.
    monkeypatch.setenv("RESEARCH_VERIFIED_FACTS", "false")
    monkeypatch.setenv("RESEARCH_QUANT_TYPING", "true")
    child = _launch_capturing_child(monkeypatch, tmp_path / "defaults", timeout=900)
    assert (child["env"]["RESEARCH_VERIFIED_FACTS"], child["env"]["RESEARCH_QUANT_TYPING"]) == ("true", "false")

    monkeypatch.setattr(po.Config, "RESEARCH_VERIFIED_FACTS", False, raising=False)
    monkeypatch.setattr(po.Config, "RESEARCH_QUANT_TYPING", True, raising=False)
    child = _launch_capturing_child(monkeypatch, tmp_path / "flipped", timeout=900)
    assert (child["env"]["RESEARCH_VERIFIED_FACTS"], child["env"]["RESEARCH_QUANT_TYPING"]) == ("false", "true")

    monkeypatch.setattr(po.Config, "RESEARCH_ENGINE", "legacy", raising=False)
    monkeypatch.delenv("RESEARCH_VERIFIED_FACTS")
    monkeypatch.delenv("RESEARCH_QUANT_TYPING")
    child = _launch_capturing_child(monkeypatch, tmp_path / "legacy", timeout=900)
    assert "RESEARCH_VERIFIED_FACTS" not in child["env"] and "RESEARCH_QUANT_TYPING" not in child["env"]


@pytest.mark.parametrize("raw, default, expected", [
    (None, True, True), ("", False, False), ("true", False, True), ("ON", False, True), ("1", False, True),
    ("false", True, False), ("no", True, False), ("0", True, False), ("maybe", True, True), ("maybe", False, False),
])
def test_env_flag(raw, default, expected):
    env = {} if raw is None else {"KNOB": raw}
    assert lr._env_flag(env, "KNOB", default) is expected
    assert lr._env_flag(None, "KNOB", default) is default
