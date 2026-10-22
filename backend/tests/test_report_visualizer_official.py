"""Official-data report exhibits rendered from the REAL 2026-10-11 carrier.

RPT-8 (every carried series charted; detail charts only for anchored or banded
series), RPT-6 (partial periods drawn distinctly, latest marker on the last complete
period), RPT-9 (scenario ``metric_range`` bands at any frequency), RPT-4/I1 (empirical
outcome fan), RPT-15 (readable threshold labels, no collisions) and the zoomed detail
window. Plotly figures are inspected through ``_save_pair``; the static fallback
through ``_save``.
"""
from __future__ import annotations

import html
import json
from copy import deepcopy
from pathlib import Path

import pytest

from app.services import forecast_extractor as fe
from app.services import report_visualizer as rv

REAL = Path(__file__).parent / "fixtures" / "data_sources" / "real"


@pytest.fixture(autouse=True)
def forbid_fetch(monkeypatch):
    from app.services import official_data as adapter

    def forbidden(*args, **kwargs):
        pytest.fail("Chart rendering attempted to acquire an upstream data client")
    monkeypatch.setattr(adapter, "get_data_sources", forbidden)
    api = adapter.data_api()
    if api is not None and hasattr(api, "get_data_sources"):
        monkeypatch.setattr(api, "get_data_sources", forbidden)


@pytest.fixture
def viz(monkeypatch):
    monkeypatch.setattr(rv.ReportVisualizer, "_png_export_ok", lambda self: False)
    return rv.ReportVisualizer()


@pytest.fixture
def carrier() -> dict:
    return json.loads((REAL / "forecast_carrier-2026-10-11.json").read_text())


@pytest.fixture
def history() -> dict:
    return json.loads((REAL / "forecast_history_v3-2026-10-11.json").read_text())


@pytest.fixture
def figures(monkeypatch):
    captured = {}
    original = rv.ReportVisualizer._save_pair

    def capture(self, fig, charts_dir, stem, item_id=None):
        captured[stem] = fig
        return original(self, fig, charts_dir, stem, item_id)
    monkeypatch.setattr(rv.ReportVisualizer, "_save_pair", capture)
    return captured


def _binary(statement, criteria, anchor, probability):
    return {"statement": statement, "probability": probability, "resolution_criteria": criteria,
            "data_anchor": dict(anchor)}


def _forecast(official_data):
    raw = [
        _binary("The US unemployment rate is at least 5% in June 2027",
                "Resolves YES if fred:UNRATE >= 5% in 2027-06 (source: FRED).",
                {"series": "fred:UNRATE", "comparator": ">=", "threshold": 5, "observation": "2027-06",
                 "units": "Percent"}, 0.3),
        _binary("US unemployment rate is at most 4% in June 2027",
                "fred:UNRATE <= 4% in 2027-06, per the BLS release on FRED.",
                {"series": "fred:UNRATE", "comparator": "<=", "threshold": 4, "observation": "2027-06",
                 "units": "Percent"}, 0.2),
        _binary("US public debt exceeds $45 trillion in December 2027",
                "usgov:treasury/debt_to_penny > 45000000000000 U.S. dollars in 2027-12 (source: Treasury).",
                {"series": "usgov:treasury/debt_to_penny", "comparator": ">", "threshold": 45e12,
                 "observation": "2027-12", "units": "U.S. dollars"}, 0.55),
    ]
    binaries = fe._normalize_binaries(raw, official_data=official_data)
    assert all("data_anchor" in b for b in binaries)
    scenarios = [
        {"name": "Soft landing", "probability": 0.5, "resolution_criteria": "x",
         "metric_range": {"series": "fred:UNRATE", "low": None, "high": 4.5, "period": "2027-06", "units": "%"}},
        {"name": "Mild slowdown", "probability": 0.3, "resolution_criteria": "y",
         "metric_range": {"series": "fred:UNRATE", "low": 4.5, "high": 5.5, "period": "2027-06"}},
        {"name": "Recession", "probability": 0.2, "resolution_criteria": "z",
         "metric_range": {"series": "fred:UNRATE", "low": 5.5, "high": None, "period": "2027-06"}},
    ]
    return {"horizon": "2027-12-31", "binary_forecasts": binaries, "scenarios": scenarios}


def _official(items):
    return [i for i in items if i["source"] == "official_data"]


def test_every_carried_series_is_charted_and_details_never_repeat_plain_panels(viz, tmp_path, carrier, figures):
    if not rv.PLOTLY_AVAILABLE:
        pytest.skip("Plotly unavailable")
    bundle = json.loads((REAL / "report_bundle-2026-10-11.json").read_text())
    items = _official(viz.build_all("real", str(tmp_path), {"official_data": carrier, "forecast": _forecast(carrier),
                                                            "sources": bundle["sources"]}))
    carried = {r["series"] for r in fe.official_series_rows(carrier)}
    charted = {p["series"] for item in items for p in item["provenance"]}
    assert charted == carried and len(carried) == 12
    dashboard = next(i for i in items if i["id"] == "official_indicators")
    assert [p["series"] for p in dashboard["provenance"]][:2] == ["fred:UNRATE", "usgov:treasury/debt_to_penny"]
    details = [i for i in items if i["id"].startswith("official_series_")]
    assert sorted(p["series"] for d in details for p in d["provenance"]) == [
        "fred:UNRATE", "usgov:treasury/debt_to_penny"]
    fig = figures["official_indicators"]
    assert fig.layout.xaxis2.domain[0] > 0.5  # two-column small multiples
    assert fig.data[0].name == "Historical observations"  # legend order is fixed, not first-seen
    provenance = dashboard["provenance"][0]
    assert provenance["provider_name"].startswith("FRED") and provenance["title"] == "Unemployment Rate"
    assert provenance["source_id"] == "S1" and "[S1]" in dashboard["source_caption"]


def test_without_forecast_only_dashboards_are_published(viz, tmp_path, carrier):
    items = _official(viz.build_all("real", str(tmp_path), {"official_data": carrier}))
    assert [i["id"] for i in items] == ["official_indicators"]


def test_more_than_twelve_series_split_into_two_dashboards(viz, tmp_path, carrier):
    engine = json.loads((REAL / "v3_engine" / "series-2026-10-11.json").read_text())
    seen = {r["series"] for r in carrier["series"]}
    carrier["series"] += [r for r in engine["series"] if r["series"] not in seen]
    rows = fe.official_series_rows(carrier)
    assert len(rows) == 21
    items = _official(viz.build_all("real", str(tmp_path), {"official_data": carrier}))
    assert [i["id"] for i in items] == ["official_indicators", "official_indicators_more"]
    assert [len(i["provenance"]) for i in items] == [12, 9]
    assert {p["series"] for i in items for p in i["provenance"]} == {r["series"] for r in rows}


def test_detail_slots_go_to_settleable_thresholds_before_scenario_ranges(viz, tmp_path, carrier):
    anchored = [("fred:UNRATE", "%", 5, "2027-06"), ("fred:FEDFUNDS", "%", 3, "2027-06"),
                ("fred:T10Y3M", "%", 1, "2027-06"), ("fred:DGS10", "%", 5, "2027-06"),
                ("fred:SAHMREALTIME", " pp", 0.5, "2027-06"), ("bis:WS_CBPOL/M.US", "%", 3, "2027-06"),
                ("fred:GDPC1", "", 24500, "2027-Q2")]
    rows = {r["series"]: r for r in fe.official_series_rows(carrier)}
    raw = []
    for series, unit, threshold, period in anchored:
        clause = f"{series} >= {threshold:g}{unit} in {period}"
        raw.append(_binary(clause, clause, {"series": series, "comparator": ">=", "threshold": threshold,
                                            "observation": period, "units": rows[series]["units"]}, 0.5))
    binaries = fe._normalize_binaries(raw, official_data=carrier)
    assert all("data_anchor" in b for b in binaries)
    forecast = {"horizon": "2027-12-31", "binary_forecasts": binaries, "scenarios": [
        {"name": "Debt drift", "probability": 1.0, "resolution_criteria": "x",
         "metric_range": {"series": "usgov:treasury/debt_to_penny", "low": 4.4e13, "high": 4.6e13,
                          "period": "2027-12", "units": "U.S. dollars"}}]}
    items = _official(viz.build_all("real", str(tmp_path), {"official_data": carrier, "forecast": forecast}))
    details = [i["provenance"][0]["series"] for i in items if i["id"].startswith("official_series_")]
    assert len(details) == rv.ReportVisualizer._OFFICIAL_DETAIL_MAX == 6
    assert "usgov:treasury/debt_to_penny" not in details
    skipped = json.loads((tmp_path / "viz_manifest.json").read_text())["skipped"]
    note = next(s for s in skipped if s["reason"] == "detail_chart_cap")
    assert "usgov:treasury/debt_to_penny" in note["series"]


def test_partial_periods_are_drawn_apart_from_history(viz, tmp_path, carrier, figures, monkeypatch):
    if not rv.PLOTLY_AVAILABLE:
        pytest.skip("Plotly unavailable")
    panel = next(p for p in viz._official_chart_panels(carrier, {}) if p["row"]["series"] == "fred:DGS10")
    assert list(panel["values"]) == ["historical observation", "partial-period value"]
    partial = dict(zip(panel["x"], panel["values"]["partial-period value"]))
    assert {x for x, v in partial.items() if v is not None} == {"2024-10-01", "2026-10-01"}
    assert panel["latest"] == {"date": "2026-09-01", "value": 4.989047619047619}
    viz._build_official_plotly([panel], str(tmp_path), "dgs", "Official Indicators", {}, detail=False)
    fig = figures["dgs"]
    trace = next(t for t in fig.data if t.name.startswith("Partial period"))
    assert trace.marker.symbol == "circle-open"
    latest = next(t for t in fig.data if t.name == "Latest historical observation")
    assert list(latest.x) == ["2026-09-01"]


def test_detail_chart_draws_thresholds_fan_bands_in_a_recent_window(viz, tmp_path, carrier, figures):
    if not rv.PLOTLY_AVAILABLE:
        pytest.skip("Plotly unavailable")
    forecast = _forecast(carrier)
    viz.build_all("real", str(tmp_path), {"official_data": carrier, "forecast": forecast})
    stem = next(s for s in figures if s.startswith("official_series_") and any(
        "Unemployment" in (a.text or "") for a in figures[s].layout.annotations))
    fig = figures[stem]
    names = [html.unescape(t.name or "") for t in fig.data]
    assert "Model threshold >= 5% (2027-06); P(yes)=30%; empirical base rate 9% (n=108)" in names
    assert "Model threshold <= 4% (2027-06); P(yes)=20%; empirical base rate 47% (n=108)" in names
    row = next(r for r in fe.official_series_rows(carrier) if r["series"] == "fred:UNRATE")
    fan = fe.official_empirical_fan(row, "2027-06-01")
    outer = next(t for t in fig.data if t.name == "Empirical outcome range p10–p90")
    assert list(outer.x) == ["2026-09-01"] + [p["date"] for p in fan]
    assert list(outer.y) == [4.2] + [p["p90"] for p in fan]
    assert any(t.name == "Empirical median path (historical changes)" for t in fig.data)
    bands = [s for s in fig.layout.shapes if s.type == "rect" and s.fillcolor in rv.ReportVisualizer._OFFICIAL_BAND_COLORS]
    assert len(bands) == 3
    assert {(b.y0, b.y1) for b in bands} >= {(4.5, 5.5)}
    assert all(b.x0 < "2027-06-15" < b.x1 for b in bands)
    assert "Model scenario: Mild slowdown — 2027-06 (P=30%; empirical 15%)" in names
    tags = [a for a in fig.layout.annotations if a.xref == "x domain" and a.x == 1.0]
    assert {html.unescape(a.text) for a in tags} == {"<= 4%", ">= 5%"}
    horizon = next(a for a in fig.layout.annotations if a.text == "Forecast horizon")
    assert horizon.y == 1.0 and horizon.yanchor == "bottom"
    window = fig.layout.xaxis.range
    assert "2021-01-01" < window[0] < "2021-12-31" and "2027-12-31" < window[1] < "2028-03-01"
    assert fig.layout.yaxis.range[1] < 7  # the 2020 spike (14.8%) is outside the zoomed window


EIA_COM = "usgov:eia/electricity_sales/US.COM"


def _eia_case(since: str):
    """The live data-centre carrier (EIA retail sales, NSA monthly to 2026-07) from ``since`` on,
    with a 0.1 binary anchored five months ahead at >= 140,000 million kWh."""
    questions = json.loads((REAL / "agent_usage" / "carriers-2026-10-13.json").read_text())["questions"]
    datacenter = {"schema_version": 1, "series": deepcopy(questions["q2_datacenter"]["series"])}
    row = next(r for r in datacenter["series"] if r["series"] == EIA_COM)
    row["observations"] = [p for p in row["observations"] if p["date"] >= since]
    binaries = fe._normalize_binaries([_binary(
        "US commercial-sector retail electricity sales are at least 140,000 million kilowatt-hours in December 2026.",
        f"Resolves YES if {EIA_COM} >= 140000 Million kilowatt-hours in 2026-12 (source: EIA).",
        {"series": EIA_COM, "comparator": ">=", "threshold": 140000, "observation": "2026-12",
         "units": "Million kilowatt-hours"}, 0.1)], official_data=datacenter)
    return datacenter, {"horizon": "2026-12-31", "binary_forecasts": binaries}


@pytest.mark.parametrize("since, basis, n, tag, fan_note", [
    ("2016-01-01", "seasonal_profile", 112, "seasonal profile", "seasonal profile"),
    ("2021-08-01", "all_start_months", 55, "seasons pooled", "start months pooled, not seasonally adjusted"),
])
def test_fan_and_threshold_say_which_seasonal_basis_they_use(viz, tmp_path, figures, since, basis, n, tag, fan_note):
    """NSA monthly EIA sales anchored five months ahead: the full stored history takes the seasonal
    profile, a 60-month history (four July starts) pools every start month; both say so."""
    if not rv.PLOTLY_AVAILABLE:
        pytest.skip("Plotly unavailable")
    datacenter, forecast = _eia_case(since)
    base = forecast["binary_forecasts"][0]["data_anchor"]["empirical_base_rate"]
    assert (base["seasonal_basis"], base["n"]) == (basis, n)
    viz.build_all("real", str(tmp_path), {"official_data": datacenter, "forecast": forecast})
    fig = next(f for s, f in figures.items() if s.startswith("official_series_") and any(
        "U.S. total, commercial sector" in (a.text or "") for a in f.layout.annotations))
    names = [html.unescape(t.name or "") for t in fig.data]
    assert any(name.endswith(f"; empirical base rate {base['p']:.0%} (n={n}, {tag})") for name in names)
    assert f"Empirical outcome range p10–p90 ({fan_note})" in names
    assert f"Empirical outcome range p25–p75 ({fan_note})" in names
    assert "Empirical outcome range p10–p90" not in names


def test_seasonal_profile_fan_draws_the_seasonal_swing(viz, tmp_path, figures, monkeypatch):
    """The stored July-to-December fan of NSA EIA sales falls with the season (Plotly and static)."""
    datacenter, forecast = _eia_case("2016-01-01")
    row = next(r for r in fe.official_series_rows(datacenter) if r["series"] == EIA_COM)
    latest = row["observations"][-1]["value"]
    fan = {p["date"]: p for p in fe.official_empirical_fan(row, "2026-12-01")}
    assert all(p["seasonal_basis"] == "seasonal_profile" for p in fan.values())
    assert fan["2026-12-01"]["p90"] < 140000 < latest and fan["2026-11-01"]["p50"] < latest - 25000
    band = fe.validate_metric_range({"series": EIA_COM, "low": 120000, "high": 135000, "period": "2026-12"}, datacenter)
    share = band["empirical_base_rate"]["p"]
    assert rv.ReportVisualizer._official_band_label({**band, "name": "Winter dip", "probability": 0.6}, row) == (
        f"Model scenario: Winter dip — 2026-12 (P=60%; empirical {share:.0%}, seasonal profile)")
    if rv.PLOTLY_AVAILABLE:
        viz.build_all("real", str(tmp_path / "plotly"), {"official_data": datacenter, "forecast": forecast})
        fig = next(f for s, f in figures.items() if s.startswith("official_series_") and any(
            "U.S. total, commercial sector" in (a.text or "") for a in f.layout.annotations))
        median = next(t for t in fig.data if t.name == "Empirical median path (historical changes)")
        assert list(median.x) == ["2026-07-01", *fan] and list(median.y) == [latest] + [p["p50"] for p in fan.values()]
    if not rv.MATPLOTLIB_AVAILABLE:
        return
    monkeypatch.setattr(rv, "PLOTLY_AVAILABLE", False)
    legends = {}
    original = rv.ReportVisualizer._save

    def save(self, figure, charts_dir, filename):
        for legend in figure.legends:
            legends.setdefault(filename, []).extend(text.get_text() for text in legend.get_texts())
        return original(self, figure, charts_dir, filename)
    monkeypatch.setattr(rv.ReportVisualizer, "_save", save)
    viz.build_all("real", str(tmp_path / "static"), {"official_data": datacenter, "forecast": forecast})
    texts = [text for filename, found in legends.items() if filename.startswith("official_series_") for text in found]
    assert "Empirical outcome range p10–p90 (seasonal profile)" in texts
    assert any(text.endswith("; empirical base rate 0% (n=112, seasonal profile)") for text in texts)


def test_large_level_threshold_reads_in_words_without_overlap(viz, tmp_path, carrier, figures):
    if not rv.PLOTLY_AVAILABLE:
        pytest.skip("Plotly unavailable")
    viz.build_all("real", str(tmp_path), {"official_data": carrier, "forecast": _forecast(carrier)})
    fig = next(f for s, f in figures.items() if s.startswith("official_series_") and any(
        "Debt to the Penny" in (a.text or "") for a in f.layout.annotations))
    names = [t.name or "" for t in fig.data]
    assert ("Model threshold &gt; 45 trillion U.S. dollars (2027-12); P(yes)=55%; "
            "empirical base rate: insufficient history") in names
    tag = next(a for a in fig.layout.annotations if a.xref == "x domain")
    assert tag.text == "&gt; 45 trillion" and tag.xanchor == "left"
    assert "e+13" not in json.dumps(fig.to_plotly_json(), default=str)
    assert not any(t.name == "Empirical outcome range p10–p90" for t in fig.data)  # 25 months < 30 samples


def test_scenario_ranges_for_observed_periods_are_not_drawn(viz, carrier):
    forecast = {"horizon": "2027-12-31", "scenarios": [
        {"name": "Past", "probability": 0.5, "resolution_criteria": "x",
         "metric_range": {"series": "fred:UNRATE", "low": 4, "high": 5, "period": "2026-06"}},
        {"name": "Future", "probability": 0.5, "resolution_criteria": "y",
         "metric_range": {"series": "fred:UNRATE", "low": 4, "high": 5, "period": "2027-06"}}]}
    panel = next(p for p in viz._official_chart_panels(carrier, forecast) if p["row"]["series"] == "fred:UNRATE")
    assert [b["name"] for b in panel["bands"]] == ["Future"]


def test_annual_band_is_drawn_with_or_without_complete_history(viz, tmp_path, carrier, history, figures):
    if not rv.PLOTLY_AVAILABLE:
        pytest.skip("Plotly unavailable")
    forecast = {"horizon": "2027-12-31", "scenarios": [
        {"name": "Contraction", "probability": 0.2, "resolution_criteria": "x",
         "metric_range": {"series": "wb:WB_WDI_NY_GDP_MKTP_KD_ZG/USA", "low": -3, "high": 0, "period": "2026",
                          "units": "%"}}]}
    for name, official_data in (("policy3", history), ("policy2", carrier)):
        panel = next(p for p in viz._official_chart_panels(official_data, forecast)
                     if p["row"]["series"] == "wb:WB_WDI_NY_GDP_MKTP_KD_ZG/USA")
        viz._build_official_plotly([panel], str(tmp_path), name, "Official Series History and Forecast Thresholds",
                                   forecast, detail=True)
        rect = next(s for s in figures[name].layout.shapes if s.type == "rect")
        assert (rect.x0, rect.x1, rect.y0, rect.y1) == ("2026-01-01", "2027-01-01", -3, 0)
    assert panel["latest"] is None  # policy-2 WDI rows carry no confirmed history
    # Independent outside view: share of past one-year moves from the 2025 value that land in [-3, 0].
    wdi = {int(p["date"][:4]): p["value"] for r in history["series"] if r["series"].startswith("wb:WB_WDI")
           for p in r["observations"]}
    moves = [wdi[y + 1] - wdi[y] for y in wdi if y + 1 in wdi]
    share = sum(-3 <= round(wdi[2025] + m, 9) <= 0 for m in moves) / len(moves)
    labels = [t.name for t in figures["policy3"].data if t.name and t.name.startswith("Model scenario")]
    assert labels == [f"Model scenario: Contraction — 2026 (P=20%; empirical {share:.0%})"] and len(moves) == 35


def test_static_fallback_renders_every_exhibit_with_readable_large_ticks(viz, tmp_path, carrier, monkeypatch):
    if not rv.MATPLOTLIB_AVAILABLE:
        pytest.skip("Matplotlib unavailable")
    monkeypatch.setattr(rv, "PLOTLY_AVAILABLE", False)
    formatted = {}
    original = rv.ReportVisualizer._save

    def save(self, figure, charts_dir, filename):
        for ax in figure.axes:
            if ax.get_visible() and "U.S. dollars" == ax.get_ylabel():
                formatted.setdefault(filename, {})[ax.get_title().split(":")[0]] = ax.yaxis.get_major_formatter()
        return original(self, figure, charts_dir, filename)
    monkeypatch.setattr(rv.ReportVisualizer, "_save", save)
    forecast = _forecast(carrier)
    forecast["scenarios"][0]["name"] = "温和" + forecast["scenarios"][0]["name"]
    items = _official(viz.build_all("real", str(tmp_path), {"official_data": carrier, "forecast": forecast}))
    cjk = rv._mpl_labels_supported("温和")
    expected = 3 if cjk else 2  # the UNRATE detail names a Chinese scenario
    assert len(items) == expected and all(i["type"] == "png" for i in items)
    assert all((tmp_path / i["path"]).is_file() for i in items)
    # Debt (trillions) and the monthly deficit (billions) panels; no '1e13' offset text.
    debt, deficit = (formatted["official_indicators.png"][k] for k in ("Debt to the Penny", "Monthly Treasury Statement"))
    assert [debt(v, 0) for v in (4.0e13, 3.6e13, 0.0)] == ["40T", "36T", "0"]
    assert [deficit(v, 0) for v in (-2.0e11, 2.0e11, -8.5e11)] == ["-200B", "200B", "-850B"]


def test_detail_window_keeps_short_histories_whole(viz, carrier):
    forecast = _forecast(carrier)
    panel = next(p for p in viz._official_chart_panels(carrier, forecast)
                 if p["row"]["series"] == "usgov:treasury/debt_to_penny")
    start, end = rv.ReportVisualizer._official_detail_window(panel, "2027-12-31")
    assert start < "2024-10-01" < "2028-01-01" < end
    visible = rv.ReportVisualizer._official_visible(panel, (start, end))
    assert visible["values"] == panel["values"]
    unchanged = deepcopy(panel)
    rv.ReportVisualizer._official_visible(panel, ("2026-01-01", "2026-12-31"))
    assert panel == unchanged


def test_natural_phrasing_anchors_reach_the_detail_charts(viz, tmp_path, carrier):
    """EN spread and ZH fed-funds phrasings anchor, so their thresholds are charted; the
    spread (daily data averaged to months) stays charted though the monitor cannot settle it."""
    spread = fe._normalize_binaries([_binary(
        "The 10-year minus 3-month Treasury spread < 0% in June 2027",
        "Resolves YES if fred:T10Y3M < 0% in 2027-06 (source: FRED).",
        {"series": "fred:T10Y3M", "comparator": "<", "threshold": 0, "observation": "2027-06", "units": "Percent"},
        0.25)], official_data=carrier)
    funds = fe._normalize_binaries([_binary(
        "联邦基金有效利率在 2027 年 12 月 < 3%", "若fred:FEDFUNDS于2027年12月低于3%，判定为是（数据来源：FRED）。",
        {"series": "fred:FEDFUNDS", "comparator": "<", "threshold": 3, "observation": "2027-12", "units": "Percent"},
        0.45)], start_index=2, official_data=carrier, language="Chinese")
    binaries = spread + funds
    assert [b["data_anchor"]["auto_resolvable"] for b in binaries] == [False, True]
    forecast = {"horizon": "2027-12-31", "binary_forecasts": binaries, "scenarios": []}
    panels = {p["row"]["series"]: p for p in viz._official_chart_panels(carrier, forecast)}
    assert [(t["comparator"], t["threshold"], t["period"]) for t in panels["fred:T10Y3M"]["thresholds"]] == [
        ("<", 0.0, "2027-06-01")]
    assert [(t["comparator"], t["threshold"], t["period"]) for t in panels["fred:FEDFUNDS"]["thresholds"]] == [
        ("<", 3.0, "2027-12-01")]
    items = _official(viz.build_all("real", str(tmp_path), {"official_data": carrier, "forecast": forecast}))
    details = {i["provenance"][0]["series"] for i in items if i["id"].startswith("official_series_")}
    assert details == {"fred:T10Y3M", "fred:FEDFUNDS"}


@pytest.mark.parametrize("bases, expected", [
    ([], "Range"),
    (["seasonal_profile"] * 3, "Range (seasonal profile)"),
    (["all_start_months"], "Range (start months pooled, not seasonally adjusted)"),
    # RPT-R3-5: a fan whose far steps fall back to pooled seasons names both bases in step order.
    (["seasonal_profile", "seasonal_profile", "all_start_months"],
     "Range (seasonal profile, then seasons pooled; not seasonally adjusted)"),
    ([None, "same_calendar_month"], "Range (same-month starts only, not seasonally adjusted)"),
])
def test_fan_legend_names_every_seasonal_basis_of_its_steps(bases, expected):
    fan = [{"seasonal_basis": basis} if basis else {} for basis in bases]
    assert rv.ReportVisualizer._official_fan_label("Range", fan) == expected
