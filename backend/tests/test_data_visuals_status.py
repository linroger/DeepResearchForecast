"""Research renderer fidelity: stored status and fiscal identity survive plotting.

Synthetic artifacts only. The CLI test needs the guarded runner's exact
render_data.py allowlist; no provider or vendor code is invoked.
"""
import datetime as dt
import json
import subprocess
import sys

import pytest

from tests.test_data_visuals_render import RENDERER_PATH, _load, _payload, _write_run


@pytest.fixture(scope="module")
def renderer():
    module = _load(RENDERER_PATH, "data_visuals_status_under_test")
    if not module._HAS_MPL:
        pytest.skip("matplotlib unavailable")
    return module


def _item(renderer, tmp_path, payload):
    run = _write_run(tmp_path, [payload])
    rows, why = renderer._load_manifest(run)
    assert not why
    item, why = renderer._load_series(run, rows[0], 0, set())
    assert item is not None, why
    return item


def _unknown(series="imf:WEO/USA.NGDP_RPCH.A"):
    return _payload(series, freq="A", values=[2.0, None, 3.25, 3.5],
                    flags=["unknown"] * 4, title="Reported growth", units="Percent change",
                    start_year=2022, sa="", provider_name="IMF")


def test_unknown_values_never_receive_latest_observed_marker(renderer, tmp_path):
    item = _item(renderer, tmp_path, _unknown())
    assert item.latest_observed() is None
    bundle = renderer._series_bundle(item, "en")
    assert bundle["value"] == "" and bundle["period"] == ""
    assert "status not supplied" in renderer._caption([item], "en", compare=False).lower()
    assert "latest observation marked" not in renderer._caption([item], "en", compare=False).lower()


def test_unknown_trace_retains_exact_values_and_gap(renderer, tmp_path):
    if not renderer._HAS_PLOTLY:
        pytest.skip("plotly unavailable")
    item = _item(renderer, tmp_path, _unknown())
    fig = renderer._plotly_series(item, renderer._series_bundle(item, "en"))
    unknown = next((trace for trace in fig.data if trace.name == "Status not supplied"), None)
    assert unknown is not None
    assert list(unknown.y) == [2.0, None, 3.25, 3.5]
    assert unknown.connectgaps is False
    assert not any(trace.name == "Observed" for trace in fig.data)
    assert fig.layout.yaxis.title.text == "Percent change"


def test_legacy_weo_cutoff_cannot_restore_lost_status(renderer, tmp_path):
    payload = _unknown()
    payload["projection_from"] = "2024-01-01"
    for point in payload["observations"]:
        point["flag"] = ""
    item = _item(renderer, tmp_path, payload)
    assert item.latest_observed() is None
    assert not any(item.is_projection(day) for day, _ in item.points)


def test_unknown_comparison_retains_status_caption(renderer, tmp_path):
    payloads = [_unknown("wb:IMF_WEO_NGDP_RPCH/USA"), _unknown("wb:IMF_WEO_NGDP_RPCH/CHN")]
    run = _write_run(tmp_path, payloads)
    rows, _ = renderer._load_manifest(run)
    used = set()
    items = [renderer._load_series(run, row, i, used)[0] for i, row in enumerate(rows)]
    groups = renderer._compare_groups(items)
    assert len(groups) == 1
    caption = renderer._caption(items, "en", compare=True).lower()
    assert "status not supplied" in caption and "latest observations marked" not in caption


def test_comparison_png_status_keys_show_distinct_markers(renderer, tmp_path):
    payloads = [_payload("bis:WS_CBPOL/M.US", values=[1, 2], flags=["unknown"] * 2),
                _payload("bis:WS_CBPOL/M.GB", values=[2, 3], flags=["preliminary"] * 2)]
    run = _write_run(tmp_path, payloads)
    rows, _ = renderer._load_manifest(run)
    used = set()
    items = [renderer._load_series(run, row, i, used)[0] for i, row in enumerate(rows)]
    group = renderer._compare_groups(items)[0]
    bundle, fonts = renderer._with_fonts(lambda lang: renderer._compare_bundle(group, lang), "en", "comparison")
    figure = renderer._draw_compare(group, bundle, fonts)
    try:
        legend = figure.axes[0].get_legend()
        markers = {label.get_text(): handle.get_marker()
                   for label, handle in zip(legend.get_texts(), legend.legend_handles, strict=True)}
        keys = {label.get_text(): handle
                for label, handle in zip(legend.get_texts(), legend.legend_handles, strict=True)}
        # Status not supplied is a light solid line (never a projection-like dashed key).
        assert markers["Status not supplied"] in ("None", None, "")
        assert keys["Status not supplied"].get_linestyle() == "-"
        assert keys["Status not supplied"].get_alpha() < 1
        assert markers["Preliminary"] == "^"
    finally:
        renderer.plt.close(figure)


@pytest.mark.parametrize("flag,provider,expected", [
    ("observed", "fred", "Observed"), ("unknown", "imf", "Status not supplied"),
    ("preliminary", "bls", "Preliminary"), ("estimate", "imf", "Estimate"),
    ("projection", "imf", "Projection"), ("P", "bls", "Preliminary"),
    ("P", "bis", "Status not supplied"),
    ("projection", "wb", "Status not supplied"), ("observed", "wb", "Status not supplied"),
])
def test_status_survives_loading_and_controls_latest(renderer, tmp_path, flag, provider, expected):
    if not renderer._HAS_PLOTLY:
        pytest.skip("plotly unavailable")
    payload = _payload(f"{provider}:TEST", values=[1.25, 2.75], flags=[flag, flag], title="Status fidelity")
    item = _item(renderer, tmp_path, payload)
    fig = renderer._plotly_series(item, renderer._series_bundle(item, "en"))
    assert any(t.name == expected for t in fig.data)
    assert (item.latest_observed() is not None) == (flag == "observed" and provider != "wb")
    assert any(t.name == "Projection" for t in fig.data) == (flag == "projection" and provider != "wb")


def test_explicit_flags_override_cutoff_without_splicing_statuses(renderer, tmp_path):
    payload = _payload("bls:LNS14000000", values=[1, 2, None, 4, 5, 6, 7],
                       flags=["observed", "projection", "unknown", "preliminary", "estimate", "unknown", "observed"],
                       projection_from="2016-02-01", title="Status transitions")
    item = _item(renderer, tmp_path, payload)
    assert item.latest_observed() == (dt.date(2016, 1, 1), 1.0)
    if renderer._HAS_PLOTLY:
        fig = renderer._plotly_series(item, renderer._series_bundle(item, "en"))
        values = {t.name: list(t.y) for t in fig.data if t.showlegend}
        assert 4.0 in values["Preliminary"] and 5.0 in values["Estimate"]
        assert 6.0 in values["Status not supplied"] and 7.0 in values["Status not supplied"]
        assert 4.0 not in values["Projection"] and 7.0 not in values["Observed"]
        styles = {t.name: t.marker.symbol for t in fig.data if t.showlegend}
        assert styles["Status not supplied"] != styles["Preliminary"]
    assert "status not supplied" in renderer._caption([item], "en", compare=False).lower()


def _fiscal():
    payload = _payload("usgov:spending/total", freq="A", values=[100, 124.5],
                       flags=["unknown", "unknown"], units="USD", title="Federal obligations", sa="",
                       provider_name="USAspending (synthetic fixture)")
    payload["source_url"] = "https://www.usaspending.gov/"
    payload["observations"] = [{"date": "2023-10-01", "value": 100, "flag": "unknown"},
                               {"date": "2024-10-01", "value": 124.5, "flag": "unknown"}]
    payload["provenance"] = {"resolution_safe": False, "fiscal_start_month": 10, "periods": {
        "2023-10-01": {"calendar": "us_federal_fiscal_year", "label": "FY2024", "start": "2023-10-01",
                       "end": "2024-09-30", "covered_start": "2023-10-01", "covered_end": "2024-09-30", "complete": True},
        "2024-10-01": {"calendar": "us_federal_fiscal_year", "label": "FY2025", "start": "2024-10-01",
                       "end": "2025-09-30", "covered_start": "2024-10-01", "covered_end": "2025-03-31", "complete": False},
    }}
    return payload


def test_fiscal_labels_are_bound_by_date_and_show_partial_coverage(renderer, tmp_path):
    payload = _fiscal()
    payload["observations"].reverse()  # Metadata must survive sorting by date identity.
    item = _item(renderer, tmp_path, payload)
    bundle, fonts = renderer._with_fonts(lambda lang: renderer._series_bundle(item, lang), "en", "fiscal")
    fig = renderer._draw_series(item, bundle, fonts)
    try:
        tick_labels = " ".join(t.get_text() for t in fig.axes[0].get_xticklabels())
        assert "FY2024" in tick_labels and "FY2025" in tick_labels and "partial" in tick_labels.lower()
        assert "2024-10-01" not in tick_labels
    finally:
        renderer.plt.close(fig)
    assert item.latest_observed() is None
    assert "partial" in renderer._caption([item], "en", compare=False).lower()
    assert "FY2025" in renderer._caption([item], "zh", compare=False)
    assert item.period_label(dt.date(2024, 10, 1), "zh") == "FY2025（部分）"
    if renderer._HAS_PLOTLY:
        interactive = renderer._plotly_series(item, bundle)
        assert "FY2025" in " ".join(interactive.layout.xaxis.ticktext)
        assert "partial" in str(interactive.to_plotly_json()).lower()


def test_missing_fiscal_metadata_is_unavailable_instead_of_calendar_relabel(renderer, tmp_path):
    payload = _fiscal()
    del payload["provenance"]["periods"]["2024-10-01"]
    run = _write_run(tmp_path, [payload])
    rows, _ = renderer._load_manifest(run)
    item, reason = renderer._load_series(run, rows[0], 0, set())
    assert item is None and "fiscal period metadata" in reason


def test_real_cli_renders_status_and_fiscal_pngs_without_replacing_siblings(renderer, tmp_path):
    run = _write_run(tmp_path / "run", [_unknown(), _fiscal()])
    sibling = {"id": "timeline", "path": "charts/timeline.png", "title": "Existing timeline"}
    (run / "charts.json").write_text(json.dumps([sibling]))
    result = subprocess.run([sys.executable, str(RENDERER_PATH), "--dir", str(run), "--lang", "en"],
                            text=True, capture_output=True, timeout=60)
    assert result.returncode == 0, result.stderr
    summary = json.loads(result.stdout)
    assert len(summary["charts"]) == 2
    rows = json.loads((run / "charts.json").read_text())
    assert rows[0] == sibling
    for row in rows[1:]:
        assert (run / row["path"]).read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
        assert "status not supplied" in row["caption"].lower()
    assert "partial" in rows[2]["caption"].lower()


@pytest.mark.parametrize("explicit", [False, True])
@pytest.mark.parametrize("matplotlib_available", [False, True])
def test_zero_chart_cap_removes_only_owned_manifest_rows(renderer, tmp_path, capsys, monkeypatch, explicit, matplotlib_available):
    run = _write_run(tmp_path, [_payload("fred:TEST")])
    foreign = {"id": "timeline", "path": "charts/timeline.png"}
    (run / "charts.json").write_text(json.dumps([foreign, {"id": "data_old", "path": "charts/data_old.png"}]))
    monkeypatch.setenv("DATA_SOURCES_CHARTS_MAX", "0")
    monkeypatch.setattr(renderer, "_HAS_MPL", matplotlib_available)
    code = renderer.main(["--dir", str(run)] + (["--max", "0"] if explicit else []))
    summary = json.loads(capsys.readouterr().out)
    assert code == 2 and summary["charts"] == []
    assert json.loads((run / "charts.json").read_text()) == [foreign]
    assert not (run / "charts").exists()
