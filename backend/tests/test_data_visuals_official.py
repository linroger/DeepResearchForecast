"""Research data charts on REAL official payloads (slice F of the data-sources fix contract).

Fixtures under ``tests/fixtures/data_sources/real/visuals/`` are trimmed normalized rows:
``current/`` was fetched live on 2026-10-11 through the current data layer (normalization
policy 3: WEO/GEP vintage status, WDI history, daily→monthly completeness), ``legacy/``
holds rows the eac717b data layer stored (policy 2). Only bulky provenance (tool receipts,
provider metadata) was dropped; observations, flags, periods, titles and units are as
captured. Every run directory is written with ``data_sources.write_dataset_files``, the
same writer the research engines use, and statuses are checked against the canonical
``data_sources.observation_kind`` rather than a restatement of it.
"""

from __future__ import annotations

import copy
import datetime as dt
import hashlib
import json
import math
import re
import sys
from pathlib import Path

import pytest

from tests.test_data_visuals_render import RENDERER_PATH, _load

REPO_ROOT = Path(__file__).resolve().parents[2]
_BRIDGE_DIR = str(REPO_ROOT / "deerflow_bridge")
if _BRIDGE_DIR not in sys.path:
    sys.path.insert(0, _BRIDGE_DIR)

import data_catalog  # noqa: E402
import data_sources  # noqa: E402

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "data_sources" / "real" / "visuals"
SKILL_PATH = REPO_ROOT / "deerflow_bridge" / "skills" / "data-visuals" / "SKILL.md"
AUDIT_NUMBER_RE = re.compile(r"\d+%|\b\d{2,}\b|\d{4}年")


@pytest.fixture(scope="module")
def renderer():
    module = _load(RENDERER_PATH, "data_visuals_official_under_test")
    if not module._HAS_MPL:
        pytest.skip("matplotlib is not importable in this interpreter")
    return module


def _row(kind: str, name: str) -> dict:
    return json.loads((FIXTURES / kind / f"{name}.json").read_text(encoding="utf-8"))


def _series(kind: str, name: str) -> data_sources.Series:
    return data_sources.Series.from_dict(_row(kind, name))


def _run_dir(tmp_path: Path, series: list, name: str = "run") -> Path:
    run = tmp_path / name
    run.mkdir()
    data_sources.write_dataset_files(series, run, citations={s.series: i + 1 for i, s in enumerate(series)})
    return run


def _items(renderer, run: Path) -> dict:
    rows, why = renderer._load_manifest(run)
    assert not why, why
    used: set = set()
    items = {}
    for order, row in enumerate(rows):
        item, why = renderer._load_series(run, row, order, used)
        assert item is not None, why
        items[item.series] = item
    return items


def _main(renderer, capsys, *argv) -> tuple[int, dict]:
    code = renderer.main(list(argv))
    lines = [line for line in capsys.readouterr().out.splitlines() if line.strip()]
    assert len(lines) == 1, lines
    return code, json.loads(lines[0])


def _digit_free(text: str) -> None:
    assert AUDIT_NUMBER_RE.search(text) is None and re.search(r"\b\d", text) is None, text


CURRENT = sorted(path.stem for path in (FIXTURES / "current").glob("*.json"))
LEGACY = sorted(path.stem for path in (FIXTURES / "legacy").glob("*.json"))


# ---------------------------------------------------------------------------
# L3 / downstream M1: one status rule, the data layer's
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("name", CURRENT)
def test_current_policy_status_matches_the_canonical_classifier(renderer, tmp_path, name):
    series = _series("current", name)
    item = _items(renderer, _run_dir(tmp_path, [series]))[series.series]
    for obs in series.observations:
        day = dt.date.fromisoformat(obs.date)
        assert item.status(day) == data_sources.observation_kind(obs, series), (name, obs.date)


@pytest.mark.parametrize("name", LEGACY)
def test_legacy_status_matches_the_canonical_classifier(renderer, tmp_path, name):
    series = _series("legacy", name)
    item = _items(renderer, _run_dir(tmp_path, [series]))[series.series]
    for obs in series.observations:
        assert item.status(dt.date.fromisoformat(obs.date)) == data_sources.observation_kind(obs, series)


def test_status_flag_and_policy_version_mirror_the_data_layer(renderer):
    assert renderer._DISPLAY_POLICY_VERSION == data_sources._DISPLAY_POLICY_VERSION
    for raw in ("A", "r", "actual", "Revised", "forecast", "projected", "estimated", "provisional",
                "observed;preliminary", "estimate, projection", "observed;", "p", "historical", "unknown"):
        assert renderer._status_flag(raw) == data_sources._status_flag(raw), raw


def test_weo_vintage_lanes_observed_estimate_projection(renderer, tmp_path):
    series = _series("current", "wb_imf_weo_ngdp_rpch_chn")
    item = _items(renderer, _run_dir(tmp_path, [series]))[series.series]
    kinds = {obs.date[:4]: data_sources.observation_kind(obs, series) for obs in series.observations}
    vintage = series.provenance["vintage_year"]
    assert kinds[str(vintage - 1)] == "estimate" and kinds[str(vintage)] == "projection"
    latest = data_sources.latest_observed(series)
    assert item.latest_observed() == (dt.date.fromisoformat(latest.date), latest.value)
    assert item.projection_from == dt.date(vintage, 1, 1)

    segments = renderer._status_segments(item)
    assert list(segments) == ["observed", "estimate", "projection"]
    # Lanes connect through the weaker status: observed → estimate → projection.
    assert segments["estimate"][0][0] == dt.date(vintage - 2, 1, 1)
    assert segments["projection"][0][0] == dt.date(vintage - 1, 1, 1)

    bundle, fonts = renderer._with_fonts(lambda lang: renderer._series_bundle(item, lang), "en", "weo")
    assert bundle["subtitle"] == f"Annual · projection from {vintage}"
    assert bundle["projection"] == "Projection (IMF WEO)"
    fig = renderer._draw_series(item, bundle, fonts)
    try:
        styles = {line.get_label(): line.get_linestyle() for line in fig.axes[0].lines}
        assert {"-", "-.", "--"} <= set(styles.values())
        assert fig.axes[0].patches, "projection band missing"
        legend = [text.get_text() for legend in fig.legends for text in legend.get_texts()]
        assert legend == ["Observed", "Estimate", "Projection (IMF WEO)"]
    finally:
        renderer.plt.close(fig)
    caption = renderer._caption([item], "en", compare=False)
    assert "dashed shaded segment = IMF WEO projection" in caption and "squares = estimates" in caption
    zh = renderer._series_bundle(item, "zh")
    assert zh["projection"] == "预测（IMF《世界经济展望》）" and zh["subtitle"] == f"年度 · {vintage}年起为预测"


def test_legacy_weo_without_status_is_a_light_solid_line_without_latest(renderer, tmp_path):
    series = _series("legacy", "wb_imf_weo_ngdp_rpch_chn")
    item = _items(renderer, _run_dir(tmp_path, [series]))[series.series]
    assert {item.status(day) for day, _v in item.points} == {"unknown"}
    assert item.latest_observed() is None and item.projection_from is None
    bundle, fonts = renderer._with_fonts(lambda lang: renderer._series_bundle(item, lang), "en", "weo")
    fig = renderer._draw_series(item, bundle, fonts)
    try:
        line = fig.axes[0].lines[0]
        assert line.get_linestyle() == "-" and line.get_alpha() < 1 and line.get_marker() in ("None", None, "")
        assert [t.get_text() for legend in fig.legends for t in legend.get_texts()] == ["Status not supplied"]
        assert not fig.axes[0].patches
    finally:
        renderer.plt.close(fig)
    assert "light line = status not supplied by the publisher" in renderer._caption([item], "en", compare=False)


@pytest.mark.parametrize("series_id", ["fred:GEPUCURRENT", "fred:NEWEOSPI", "fred:WEOGEP"])
def test_weo_or_gep_letters_inside_other_ids_are_not_publisher_outlooks(renderer, tmp_path, series_id):
    row = _row("current", "fred_gepucurrent")
    row["series"] = series_id
    series = data_sources.Series.from_dict(row)
    item = _items(renderer, _run_dir(tmp_path, [series]))[series_id]
    assert {item.status(day) for day, value in item.points if value is not None} == {"observed"}
    assert {data_sources.observation_kind(obs, series) for obs in series.observations} == {"observed"}
    assert item.latest_observed() is not None and item.publisher("en") == ""


# ---------------------------------------------------------------------------
# Partial periods (daily→monthly aggregates, fiscal years)
# ---------------------------------------------------------------------------
def test_partial_month_is_marked_hollow_and_never_the_latest_observation(renderer, tmp_path):
    series = _series("current", "fred_dgs10")
    item = _items(renderer, _run_dir(tmp_path, [series]))[series.series]
    last = dt.date.fromisoformat(series.observations[-1].date)
    assert item.status(last) == "partial"
    latest = data_sources.latest_observed(series)
    assert item.latest_observed() == (dt.date.fromisoformat(latest.date), latest.value)
    assert item.period_label(last, "en").endswith("(partial)")
    bundle, fonts = renderer._with_fonts(lambda lang: renderer._series_bundle(item, lang), "en", "dgs10")
    assert bundle["subtitle"] == "Monthly · Not seasonally adjusted · average of daily data"
    fig = renderer._draw_series(item, bundle, fonts)
    try:
        partial = next(line for line in fig.axes[0].lines if line.get_linestyle() == ":")
        assert partial.get_markerfacecolor() == renderer._SURFACE        # hollow marker
        legend = [t.get_text() for legend in fig.legends for t in legend.get_texts()]
        assert legend == ["Observed", "Partial period"]
    finally:
        renderer.plt.close(fig)
    assert "hollow marker = partial period" in renderer._caption([item], "en", compare=False)


def test_legacy_daily_months_are_partial_only_where_coverage_or_time_is_short(renderer, tmp_path):
    # eac717b stored every aggregated month as incomplete; judge them from coverage and
    # settlement instead (data_sources._legacy_month_complete).
    series = _series("legacy", "fred_dgs10")
    item = _items(renderer, _run_dir(tmp_path, [series]))[series.series]
    retrieved = dt.date.fromisoformat(series.retrieved_at[:10])
    periods = series.provenance["periods"]
    for obs in series.observations:
        record = periods[obs.date]
        full = (record["covered_start"], record["covered_end"]) == (record["start"], record["end"])
        end = dt.date.fromisoformat(record["end"])
        settled = series.observations[-1].date > record["end"] or retrieved > end + dt.timedelta(days=7)
        expected = "observed" if full and settled else "partial"
        assert item.status(dt.date.fromisoformat(obs.date)) == expected, obs.date
    assert item.status(dt.date.fromisoformat(series.observations[-1].date)) == "partial"
    assert sum(item.status(day) == "observed" for day, _v in item.points) == len(item.points) - 2


@pytest.mark.parametrize("retrieved,september", [("2026-10-03", "partial"), ("2026-10-09", "observed")])
def test_legacy_last_month_settles_a_week_after_it_ends(renderer, tmp_path, retrieved, september):
    # A legacy row whose last stored month is fully covered (a window ending in September,
    # no October row) was not settled by a later period: until a week after month end the
    # data layer keeps it partial, so the chart must not mark it as the latest observation.
    row = copy.deepcopy(_row("legacy", "fred_dgs10"))
    row["observations"] = [obs for obs in row["observations"] if obs["date"] < "2026-10-01"]
    row["provenance"]["periods"] = {day: record for day, record in row["provenance"]["periods"].items()
                                    if day < "2026-10-01"}
    row["retrieved_at"] = f"{retrieved}T12:00:00+00:00"
    september_record = row["provenance"]["periods"]["2026-09-01"]
    assert (september_record["covered_start"], september_record["covered_end"], september_record["complete"]) \
        == ("2026-09-01", "2026-09-30", False)
    series = data_sources.Series.from_dict(row)
    item = _items(renderer, _run_dir(tmp_path, [series]))[series.series]
    for obs in series.observations:
        assert item.status(dt.date.fromisoformat(obs.date)) == data_sources.observation_kind(obs, series), obs.date
    assert item.status(dt.date(2026, 9, 1)) == september
    latest = data_sources.latest_observed(series)
    assert item.latest_observed() == (dt.date.fromisoformat(latest.date), latest.value)
    assert latest.date == ("2026-08-01" if september == "partial" else "2026-09-01")


def test_complete_fiscal_coverage_still_marked_incomplete_is_a_partial_year(renderer, tmp_path):
    # A fiscal year fully covered but not yet final (late revisions) stays incomplete in the
    # data layer; the chart must keep it instead of rejecting the whole series.
    from tests.test_data_visuals_status import _fiscal
    from tests.test_data_visuals_render import _write_run
    payload = _fiscal()
    record = payload["provenance"]["periods"]["2024-10-01"]
    record["covered_end"] = "2025-09-30"
    run = _write_run(tmp_path, [payload])
    rows, _ = renderer._load_manifest(run)
    item, why = renderer._load_series(run, rows[0], 0, set())
    assert item is not None, why
    assert item.status(dt.date(2024, 10, 1)) == "partial"
    assert item.period_label(dt.date(2024, 10, 1), "en") == "FY2025 (partial)"


# ---------------------------------------------------------------------------
# L9: comparison members do not spend the chart cap on singles
# ---------------------------------------------------------------------------
def test_comparison_replaces_member_singles_within_the_cap(renderer, tmp_path, capsys):
    names = ["bis_ws_cbpol_m_us", "bis_ws_cbpol_m_gb", "bis_ws_cbpol_m_xm", "fred_cpiaucsl_yoy", "fred_unrate"]
    series = [_series("current", name) for name in names]
    run = _run_dir(tmp_path, series)
    code, summary = _main(renderer, capsys, "--dir", str(run), "--max", "3")
    assert code == 0 and summary["dropped"] == [] and summary["skipped"] == []
    manifest = json.loads((run / "charts.json").read_text(encoding="utf-8"))
    assert [row["series"] for row in manifest] == [
        ["bis:WS_CBPOL/M.US", "bis:WS_CBPOL/M.GB", "bis:WS_CBPOL/M.XM"], ["fred:CPIAUCSL#yoy"], ["fred:UNRATE"]]
    assert not any(row["id"].startswith("data_bis_") for row in manifest)
    compare = manifest[0]
    assert compare["title"] == "Central bank policy rates - End of period: cross-economy comparison"
    latest = {s.series: data_sources.latest_observed(s).value for s in series[:3]}
    names_by_id = {"bis:WS_CBPOL/M.US": "United States", "bis:WS_CBPOL/M.GB": "United Kingdom",
                   "bis:WS_CBPOL/M.XM": "Euro area"}
    top = names_by_id[max(latest, key=latest.get)]
    bottom = names_by_id[min(latest, key=latest.get)]
    assert f"latest observed value highest for {top} and lowest for {bottom}" in compare["caption"]
    # One cap smaller: the comparison still wins (KIQ/cited ties → catalog order) and the
    # remaining series are reported, not silently lost.
    code, summary = _main(renderer, capsys, "--dir", str(run), "--max", "2")
    assert [row["series"] for row in summary["dropped"]] == ["fred:UNRATE"]


def test_comparison_subtitle_names_the_frequency_once(renderer, tmp_path):
    series = [_series("current", name) for name in ("bis_ws_cbpol_m_us", "bis_ws_cbpol_m_gb")]
    items = _items(renderer, _run_dir(tmp_path, series))
    group = renderer._compare_groups(list(items.values()))[0]
    bundle = renderer._compare_bundle(group, "en")
    assert bundle["title"] == "Central bank policy rates - End of period"
    assert bundle["subtitle"] == "Monthly" and bundle["labels"] == ["United States", "United Kingdom"]
    assert renderer._compare_bundle(group, "zh")["labels"] == ["美国", "英国"]


# ---------------------------------------------------------------------------
# series_label titles, zh units, publisher credit
# ---------------------------------------------------------------------------
def test_geography_table_mirrors_the_catalog(renderer):
    assert renderer._GEOGRAPHIES == data_catalog.GEOGRAPHIES


def test_chart_titles_name_every_catalog_geography_as_the_data_layer_does(renderer):
    # The title rule, not only the table, is a copy: for every economy the catalog names
    # (and an unknown code), titles that already name it, name another economy, or name
    # none must read exactly as data_sources.series_label reads them.
    titles = ("GDP growth", "Hong Kong GDP", "China exports", "U.S. CPI", "UK gilt yield", "中国GDP",
              "中国香港出口", "Taiwan, China output", "Euro area HICP", "World trade volume",
              "Retail Sales of Electricity: Virginia, commercial sector", "弗吉尼亚州商业部门零售电量",
              "New York state output", "Washington consensus index")
    for code in [*data_catalog.GEOGRAPHIES, "KEN", ""]:
        for title in titles:
            for lang in ("en", "zh"):
                row = {"series": "fred:ZZOFFCATALOG", "title": title, "title_zh": title, "geography": code}
                assert renderer._series_label(title, title, row["series"], code, lang) \
                    == data_sources.series_label(row, lang), (code, title, lang)


@pytest.mark.parametrize("name", CURRENT)
@pytest.mark.parametrize("lang", ["en", "zh"])
def test_chart_titles_are_the_data_layer_series_label(renderer, tmp_path, name, lang):
    series = _series("current", name)
    item = _items(renderer, _run_dir(tmp_path, [series]))[series.series]
    expected = data_sources.series_label(series, lang)
    assert renderer._series_bundle(item, lang)["title"] == expected
    # The same rule for a series outside the curated catalog (title fields only).
    row = {"series": "fred:ZZOFFCATALOG", "title": "Synthetic index", "title_zh": "合成指数",
           "geography": series.geography}
    assert renderer._series_label(row["title"], row["title_zh"], row["series"], row["geography"], lang) \
        == data_sources.series_label(row, lang)


def test_titles_name_the_geography_and_the_transform(renderer, tmp_path):
    series = [_series("current", name) for name in ("fred_unrate", "fred_cpiaucsl_yoy")]
    items = _items(renderer, _run_dir(tmp_path, series))
    assert renderer._series_bundle(items["fred:UNRATE"], "en")["title"] == "Unemployment Rate — United States"
    assert renderer._series_bundle(items["fred:CPIAUCSL#yoy"], "en")["title"].endswith(
        "(year-over-year % change)")
    assert renderer._series_bundle(items["fred:CPIAUCSL#yoy"], "zh")["title"].endswith("（同比）")


def test_zh_axis_units_and_publisher_credit(renderer, tmp_path):
    names = ["wb_imf_weo_ngdp_rpch_chn", "usgov_treasury_mts_deficit", "fred_unrate", "bis_ws_cbpol_m_us"]
    items = _items(renderer, _run_dir(tmp_path, [_series("current", name) for name in names]))
    weo = items["wb:IMF_WEO_NGDP_RPCH/CHN"]
    assert renderer._series_bundle(weo, "en")["footer"].startswith(
        "Source: IMF World Economic Outlook via World Bank Data360 · IMF_WEO_NGDP_RPCH/CHN")
    assert renderer._series_bundle(weo, "zh")["footer"].startswith(
        "来源：国际货币基金组织《世界经济展望》（经世界银行 Data360）")
    assert renderer._series_bundle(items["usgov:treasury/mts_deficit"], "en")["footer"].startswith(
        "Source: U.S. Treasury Fiscal Data · treasury/mts_deficit")
    assert renderer._series_bundle(items["fred:UNRATE"], "zh")["ylabel"] == "百分比（%）"
    assert renderer._series_bundle(items["bis:WS_CBPOL/M.US"], "zh")["ylabel"] == "年率（%）"
    assert renderer._series_bundle(weo, "zh")["ylabel"] == "变化率（%）"
    assert renderer._series_bundle(items["usgov:treasury/mts_deficit"], "zh")["ylabel"] == "美元"
    for units, expected in (("Index 1982-1984=100", "指数（1982-1984=100）"),
                            ("Index Jan 2000=100", "指数（2000年1月=100）"),
                            ("Billions of Chained 2017 Dollars", "十亿美元（2017年链式美元）"),
                            ("Hectolitres of pure alcohol", "Hectolitres of pure alcohol")):
        assert renderer._units_zh(units) == expected


# ---------------------------------------------------------------------------
# L18: data-driven, digit-free captions; derived average for noisy flows
# ---------------------------------------------------------------------------
def test_caption_reads_the_latest_observation_against_a_year_earlier(renderer, tmp_path):
    series = _series("current", "fred_unrate")
    item = _items(renderer, _run_dir(tmp_path, [series]))[series.series]
    latest = data_sources.latest_observed(series)
    prior = next(o for o in series.observations if o.date == data_sources._shift(latest.date, -12))
    word = "up" if latest.value > prior.value else "down" if latest.value < prior.value else "unchanged"
    for lang in ("en", "zh"):
        caption = renderer._caption([item], lang, compare=False)
        _digit_free(caption)
    assert f"latest observation marked: {word} from a year earlier" in renderer._caption([item], "en", compare=False)
    # The real October 2025 hole stays a break, and the caption says so.
    assert any(value is None for _day, value in item.points)
    assert "breaks mark missing periods" in renderer._caption([item], "en", compare=False)


def test_noisy_monthly_flow_gets_a_derived_twelve_month_average(renderer, tmp_path):
    series = [_series("current", name) for name in ("usgov_treasury_mts_deficit", "fred_unrate")]
    items = _items(renderer, _run_dir(tmp_path, series))
    deficit = items["usgov:treasury/mts_deficit"]
    rolling = renderer._rolling(deficit)
    assert rolling is not None and renderer._rolling(items["fred:UNRATE"]) is None
    values = {dt.date.fromisoformat(o.date): o.value for o in series[0].observations}
    day, average = next((d, v) for d, v in reversed(rolling) if not math.isnan(v))
    window = [values[dt.date(day.year - (day.month - k <= 0), (day.month - k - 1) % 12 + 1, 1)] for k in range(12)]
    assert average == pytest.approx(sum(window) / 12)
    bundle, fonts = renderer._with_fonts(lambda lang: renderer._series_bundle(deficit, lang), "en", "mts")
    fig = renderer._draw_series(deficit, bundle, fonts)
    try:
        legend = [t.get_text() for legend in fig.legends for t in legend.get_texts()]
        assert legend == ["Monthly values", "12-month average (derived)"]
        raw = fig.axes[0].lines[0]
        assert [v for v in raw.get_ydata() if not math.isnan(v)] == [o.value for o in series[0].observations]
    finally:
        renderer.plt.close(fig)
    assert "derived twelve-month average" in renderer._caption([deficit], "en", compare=False)


def test_latest_label_does_not_sit_on_the_line(renderer, tmp_path):
    series = _series("current", "wb_wb_gep_nygdpmktpkdz_chn")
    item = _items(renderer, _run_dir(tmp_path, [series]))[series.series]
    bundle, fonts = renderer._with_fonts(lambda lang: renderer._series_bundle(item, lang), "en", "gep")
    fig = renderer._draw_series(item, bundle, fonts)
    try:
        ax = fig.axes[0]
        fig.canvas.draw()
        renderer_ = fig.canvas.get_renderer()
        label = next(text for text in ax.texts if text.get_text().startswith(renderer._mpl_text(bundle["value"])))
        box = label.get_window_extent(renderer_)
        for line in ax.get_lines():
            if str(line.get_linestyle()).lower() in ("none", ""):
                continue
            points = line.get_transform().transform(line.get_xydata())
            for a, b in zip(points, points[1:]):
                if not all(math.isfinite(v) for v in (*a, *b)):
                    continue
                for t in (i / 200 for i in range(201)):        # sample the segment densely
                    x, y = a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t
                    assert not (box.x0 <= x <= box.x1 and box.y0 <= y <= box.y1), (line.get_label(), x, y)
    finally:
        renderer.plt.close(fig)


def test_percent_labels_keep_policy_rate_precision(renderer, tmp_path):
    assert renderer._format_value(3.875, "Per cent per year") == "3.875%"
    assert renderer._format_value(4.125, "Percent") == data_sources.format_value(4.125, "Percent")
    assert renderer._format_value(-0.0001, "Percentage Points") == "0 pp"
    series = _series("current", "bis_ws_cbpol_m_us")
    item = _items(renderer, _run_dir(tmp_path, [series]))[series.series]
    latest = data_sources.latest_observed(series)
    assert renderer._series_bundle(item, "en")["value"] == data_sources.format_value(latest.value, series.units)


# ---------------------------------------------------------------------------
# L19: one shared plotly bundle, inlined by the API at serve time
# ---------------------------------------------------------------------------
def test_html_twins_share_one_bundle_that_the_api_inlines(renderer, tmp_path, capsys):
    if not renderer._HAS_PLOTLY:
        pytest.skip("plotly unavailable")
    from plotly.offline import get_plotlyjs

    from app.utils.chart_html import inline_plotly_bundle

    series = [_series("current", name) for name in ("fred_unrate", "wb_imf_weo_ngdp_rpch_chn",
                                                    "wb_imf_weo_ngdp_rpch_usa")]
    run = _run_dir(tmp_path, series)
    code, summary = _main(renderer, capsys, "--dir", str(run))
    assert code == 0
    bundle = run / "charts" / "plotly.min.js"
    assert bundle.read_text(encoding="utf-8") == get_plotlyjs()
    rows = json.loads((run / "charts.json").read_text(encoding="utf-8"))
    assert len(rows) == 2 and all(row.get("html_path") for row in rows)
    for row in rows:
        path = run / row["html_path"]
        html = path.read_text(encoding="utf-8")
        assert path.stat().st_size < 200_000, path.stat().st_size
        assert re.search(r'<script[^>]*src="plotly\.min\.js"', html)
        assert "could not load the shared plotly.min.js" in html
        served = inline_plotly_bundle(str(path))
        assert served is not None and get_plotlyjs()[:2000] in served
        assert re.search(r'<script[^>]*src=', served) is None


def test_html_twin_inlines_plotly_when_the_shared_bundle_cannot_be_written(renderer, tmp_path, capsys,
                                                                            monkeypatch):
    if not renderer._HAS_PLOTLY:
        pytest.skip("plotly unavailable")
    monkeypatch.setattr(renderer, "_ensure_plotly_bundle", lambda _charts: False)
    run = _run_dir(tmp_path, [_series("current", "fred_unrate")])
    code, _summary = _main(renderer, capsys, "--dir", str(run))
    assert code == 0
    html = (run / "charts" / json.loads((run / "charts.json").read_text())[0]["html_path"].split("/")[-1])
    text = html.read_text(encoding="utf-8")
    assert 'src="plotly.min.js"' not in text and len(text) > 1_000_000
    assert not (run / "charts" / "plotly.min.js").exists()


def test_stale_or_symlinked_bundle_is_replaced(renderer, tmp_path):
    if not renderer._HAS_PLOTLY:
        pytest.skip("plotly unavailable")
    from plotly.offline import get_plotlyjs
    charts = tmp_path / "charts"
    charts.mkdir()
    outside = tmp_path / "elsewhere.js"
    outside.write_text("stale", encoding="utf-8")
    (charts / "plotly.min.js").symlink_to(outside)
    assert renderer._ensure_plotly_bundle(charts)
    bundle = charts / "plotly.min.js"
    assert not bundle.is_symlink() and bundle.read_text(encoding="utf-8") == get_plotlyjs()
    assert outside.read_text(encoding="utf-8") == "stale"


# ---------------------------------------------------------------------------
# End to end on real rows, EN and ZH: every chart renders, manifests stay digit-free
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("lang", ["en", "zh"])
def test_real_rows_render_end_to_end(renderer, tmp_path, capsys, lang):
    series = [_series("current", name) for name in CURRENT]
    run = _run_dir(tmp_path, series)
    code, summary = _main(renderer, capsys, "--dir", str(run), "--lang", lang, "--max", "12")
    assert code == 0 and summary["skipped"] == []
    rows = json.loads((run / "charts.json").read_text(encoding="utf-8"))
    charted = [sid for row in rows for sid in row["series"]]
    assert sorted(charted + [row["series"] for row in summary["dropped"]]) == sorted(s.series for s in series)
    for row in rows:
        assert (run / row["path"]).read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
        _digit_free(row["title"])
        _digit_free(row["caption"])


# ---------------------------------------------------------------------------
# The skill metadata advertised in every legacy research prompt is unchanged
# ---------------------------------------------------------------------------
def test_skill_frontmatter_is_byte_identical_to_the_advertised_metadata():
    text = SKILL_PATH.read_text(encoding="utf-8")
    frontmatter = text.split("---", 2)[1]
    assert hashlib.sha256(frontmatter.encode("utf-8")).hexdigest() == (
        "29dbcc778a753001684138f89a5f33566bd7c0c5126d594964cbd414799fd9c0")


def test_a_us_state_series_title_needs_no_country_suffix(renderer):
    """Live eval 2026-10-14: 'Retail Sales of Electricity: Virginia, commercial sector — United States'."""
    for title, lang in (("Retail Sales of Electricity: Virginia, commercial sector", "en"),
                        ("弗吉尼亚州商业部门零售电量", "zh")):
        row = {"series": "fred:ZZOFFCATALOG", "title": title, "title_zh": title, "geography": "USA"}
        assert data_sources.series_label(row, lang) == title
        assert renderer._series_label(title, title, row["series"], "USA", lang) == title
    row = {"series": "fred:ZZOFFCATALOG", "title": "Retail sales of electricity", "geography": "USA"}
    assert data_sources.series_label(row) == "Retail sales of electricity — United States"
