"""Hermetic checks for the data-visuals renderer (official series → charts).

Every dataset is synthetic and written under ``tmp_path``; nothing touches the
network or the vendored data servers.  The renderer is exercised both in-process
(``main(argv)``) and as a real subprocess with the backend interpreter.
"""

from __future__ import annotations

import datetime as dt
import importlib.util
import json
import math
import os
import re
import struct
import subprocess
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
RENDERER_PATH = (
    REPO_ROOT / "deerflow_bridge" / "skills" / "data-visuals" / "scripts" / "render_data.py"
)
FORECAST_RENDERER_PATH = (
    REPO_ROOT / "deerflow_bridge" / "skills" / "forecast-visuals" / "scripts" / "render.py"
)
# The report audits treat these as uncited numeric claims (report_agent _NUMBER_RE).
AUDIT_NUMBER_RE = re.compile(r"\d+%|\b\d{2,}\b|\d{4}年")
SAFE_CHART_PATH_RE = re.compile(r"charts/[A-Za-z0-9._-]+")


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def renderer():
    module = _load(RENDERER_PATH, "data_visuals_renderer_under_test")
    if not module._HAS_MPL:
        pytest.skip("matplotlib is not importable in this interpreter")
    return module


# ---------------------------------------------------------------------------
# synthetic datasets
# ---------------------------------------------------------------------------
def _dates(freq: str, n: int, start_year: int = 2016) -> list[str]:
    if freq == "D":
        first = dt.date(start_year, 1, 1)
        return [(first + dt.timedelta(days=i)).isoformat() for i in range(n)]
    step = {"M": 1, "Q": 3, "A": 12}[freq]
    out = []
    for i in range(n):
        months = i * step
        out.append(dt.date(start_year + months // 12, months % 12 + 1, 1).isoformat())
    return out


def _payload(series: str, *, freq: str = "M", values=None, n: int = 36, title: str = "",
             title_zh: str = "", units: str = "Percent", sa: str = "SA",
             projection_from: str = "", flags=None, start_year: int = 2016,
             provider_name: str = "FRED (Federal Reserve Bank of St. Louis)") -> dict:
    if values is None:
        values = [round(4 + math.sin(i / 4) + i * 0.01, 3) for i in range(n)]
    dates = _dates(freq, len(values), start_year)
    flags = flags or [""] * len(values)
    return {
        "series": series,
        "provider": series.split(":", 1)[0],
        "provider_name": provider_name,
        "title": title or f"Synthetic series {series.split(':', 1)[1]}",
        "title_zh": title_zh,
        "units": units,
        "frequency": freq,
        "seasonal_adjustment": sa,
        "observations": [
            {"date": d, "value": v, "flag": f} for d, v, f in zip(dates, values, flags, strict=True)
        ],
        "source_url": "https://fred.stlouisfed.org/series/TEST",
        "api_url": "",
        "retrieved_at": "2026-10-11T08:30:00Z",
        "last_updated": "",
        "transform": "",
        "projection_from": projection_from,
        "notes": "",
        "route": "mcp",
    }


def _slug(series: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", series.casefold()).strip("_")[:60]


def _write_run(base: Path, payloads: list[dict], overrides: dict | None = None,
               extra_rows: list | None = None) -> Path:
    data = base / "data"
    data.mkdir(parents=True, exist_ok=True)
    rows = []
    for payload in payloads:
        slug = _slug(payload["series"])
        (data / f"{slug}.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        row = {
            "series": payload["series"], "slug": slug, "provider": payload["provider"],
            "title": payload["title"], "title_zh": payload["title_zh"], "units": payload["units"],
            "frequency": payload["frequency"], "seasonal_adjustment": payload["seasonal_adjustment"],
            "projection_from": payload["projection_from"], "transform": "",
            "file": f"data/{slug}.json", "csv": f"data/{slug}.csv", "kiqs": [], "source_id": "",
        }
        row.update((overrides or {}).get(payload["series"], {}))
        rows.append(row)
    rows.extend(extra_rows or [])
    manifest = {"schema_version": 1, "generated_at": "2026-10-11T08:30:00Z", "series": rows}
    (data / "datasets.json").write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    return base


def _run(renderer, capsys, *argv: str) -> tuple[int, dict]:
    code = renderer.main(list(argv))
    lines = [line for line in capsys.readouterr().out.splitlines() if line.strip()]
    assert len(lines) == 1, lines
    return code, json.loads(lines[0])


def _manifest(base: Path) -> list:
    return json.loads((base / "charts.json").read_text(encoding="utf-8"))


def _png_size(path: Path) -> tuple[int, int]:
    data = path.read_bytes()
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    return struct.unpack(">II", data[16:24])


def _assert_digit_free(text: str) -> None:
    assert AUDIT_NUMBER_RE.search(text) is None, text
    assert re.search(r"\b\d", text) is None, text


def _projection_payload(series: str = "wb:IMF_WEO_NGDP_RPCH/USA", geo: str = "United States",
                        **kw) -> dict:
    values = [2.7, 1.6, 2.3, 2.1, 2.5, 2.9, 1.8, 2.5, 3.0, 2.6, -2.1, 6.1, 2.5, 2.9, 2.8, 2.1,
              2.3, 2.1, 2.1, 1.9, 1.8, 1.8]
    return _payload(series, freq="A", values=values, start_year=2010, units="Percent change", sa="",
                    title=f"Real GDP growth (IMF WEO): {geo}", projection_from="2026-01-01",
                    provider_name="World Bank Data360 (IMF World Economic Outlook)", **kw)


# ---------------------------------------------------------------------------
# rendering across frequencies, projection, gaps
# ---------------------------------------------------------------------------
def test_renders_png_and_html_for_each_frequency(renderer, tmp_path, capsys):
    run = _write_run(tmp_path / "run", [
        _payload("fred:UNRATE", freq="M", n=120, title="Unemployment Rate"),
        _payload("fred:GDPC1", freq="Q", n=40, title="Real Gross Domestic Product",
                 units="Billions of Chained 2017 Dollars", sa="SAAR",
                 values=[18000 + 120 * i for i in range(40)]),
        _projection_payload(),
        _payload("fred:DGS10", freq="D", n=500, title="Market Yield on U.S. Treasury Securities",
                 sa="NSA", values=[3.5 + math.sin(i / 30) for i in range(500)]),
    ])
    outside_before = sorted(p.name for p in tmp_path.iterdir())

    code, summary = _run(renderer, capsys, "--dir", str(run))

    assert code == 0
    assert summary["charts"] == [
        "data_fred_unrate", "data_fred_gdpc1", "data_wb_imf_weo_ngdp_rpch_usa", "data_fred_dgs10",
    ]
    assert summary["skipped"] == [] and summary["dropped"] == []
    rows = {row["id"]: row for row in _manifest(run)}
    for chart_id in summary["charts"]:
        row = rows[chart_id]
        png = run / row["path"]
        assert _png_size(png) == (1600, 900)
        assert SAFE_CHART_PATH_RE.fullmatch(row["path"])
        assert row["source_data"] == "data/datasets.json"
        assert row["data_class"] == "official_statistics"
        if renderer._HAS_PLOTLY:
            html = (run / row["html_path"]).read_text(encoding="utf-8")
            assert "<title>" in html and 'rel="icon" href="data:' in html
            assert re.search(r'<script[^>]+src="https?://', html) is None   # self-contained
            assert SAFE_CHART_PATH_RE.fullmatch(row["html_path"])
        else:
            assert "html_path" not in row
    assert rows["data_fred_unrate"]["series"] == ["fred:UNRATE"]
    # Nothing is written next to the run directory; charts are readable by other processes.
    assert sorted(p.name for p in tmp_path.iterdir()) == outside_before
    assert (os.stat(run / "charts" / "data_fred_unrate.png").st_mode & 0o044) == 0o044
    assert not [p for p in (run / "charts").iterdir() if p.name.startswith(".")]


def test_projection_segment_is_dashed_shaded_and_labelled(renderer, tmp_path):
    payload = _projection_payload("fred:SYNTHETIC_GROWTH")
    payload["provider_name"] = "Synthetic FRED fixture"
    run = _write_run(tmp_path / "run", [payload])
    rows, _ = renderer._load_manifest(run)
    item, why = renderer._load_series(run, rows[0], 0, set())
    assert why == "" and item.projection_from == dt.date(2026, 1, 1)
    obs_x, obs_y, proj_x, proj_y = renderer._segments(item)
    assert obs_x[-1] == dt.date(2025, 1, 1)
    assert proj_x[0] == dt.date(2025, 1, 1) and proj_x[1] == dt.date(2026, 1, 1)
    assert item.latest_observed() == (dt.date(2025, 1, 1), 2.1)

    bundle, fonts = renderer._with_fonts(lambda lang: renderer._series_bundle(item, lang), "en", "t")
    fig = renderer._draw_series(item, bundle, fonts)
    try:
        ax = fig.axes[0]
        styles = {line.get_linestyle() for line in ax.lines}
        assert "--" in styles and "-" in styles
        assert ax.patches, "projection band missing"
        legend_texts = [text.get_text() for legend in fig.legends for text in legend.get_texts()]
        assert legend_texts == ["Observed", "Projection"]
        assert "projection from 2026" in bundle["subtitle"]
    finally:
        renderer.plt.close(fig)


def test_projection_boundary_falls_back_to_projection_flags(renderer, tmp_path):
    payload = _projection_payload("fred:SYNTHETIC_GROWTH")
    payload["provider_name"] = "Synthetic FRED fixture"
    payload["projection_from"] = ""
    for obs in payload["observations"]:
        obs["flag"] = "projection" if obs["date"] >= "2027-01-01" else ""
    run = _write_run(tmp_path / "run", [payload], overrides={payload["series"]: {"projection_from": ""}})
    rows, _ = renderer._load_manifest(run)
    item, _ = renderer._load_series(run, rows[0], 0, set())
    assert item.projection_from == dt.date(2027, 1, 1)


def test_gaps_break_the_line_and_isolated_points_stay_visible(renderer, tmp_path):
    values = [4.0, 4.1, 4.2, 4.3, 4.4, None, 4.5, None, 4.6, None, 4.7, 4.8]
    run = _write_run(tmp_path / "run", [_payload("fred:UNRATE", values=values, title="Unemployment Rate")])
    rows, _ = renderer._load_manifest(run)
    item, _ = renderer._load_series(run, rows[0], 0, set())
    bundle, fonts = renderer._with_fonts(lambda lang: renderer._series_bundle(item, lang), "en", "t")
    fig = renderer._draw_series(item, bundle, fonts)
    try:
        main_line = fig.axes[0].lines[0]
        ydata = list(main_line.get_ydata())
        assert math.isnan(ydata[5]) and math.isnan(ydata[7]) and math.isnan(ydata[9])
        assert ydata[6] == 4.5           # never interpolated, never dropped
        isolated = fig.axes[0].lines[1]
        assert list(isolated.get_xdata()) == [dt.date(2016, 7, 1), dt.date(2016, 9, 1)]
    finally:
        renderer.plt.close(fig)
    if renderer._HAS_PLOTLY:
        figure = renderer._plotly_series(item, renderer._series_bundle(item, "en"))
        trace = figure.data[0]
        assert trace.connectgaps is False and trace.y[5] is None


# ---------------------------------------------------------------------------
# grouped comparison charts
# ---------------------------------------------------------------------------
def test_comparison_charts_for_bis_flow_and_geography_titles(renderer, tmp_path, capsys):
    bis = [
        _payload(f"bis:WS_CBPOL/M.{code}", title=f"Central bank policy rate - {name}",
                 units="Percent per annum", sa="NSA", provider_name="BIS (Bank for International Settlements)",
                 values=[base + 0.1 * i for i in range(36)])
        for code, name, base in (("US", "United States", 1.0), ("GB", "United Kingdom", 0.5),
                                 ("XM", "Euro area", 0.0))
    ]
    fred = [
        _payload(f"fred:LRHUTTTT{code}M156S", title=f"Harmonized Unemployment Rate: Total: All Persons for {name}",
                 values=[base + 0.05 * i for i in range(36)])
        for code, name, base in (("JP", "Japan", 2.5), ("DE", "Germany", 3.5))
    ]
    unrelated = [
        _payload("fred:UNRATE", title="Unemployment Rate"),
        _payload("fred:CIVPART", title="Labor Force Participation Rate for Japan"),
    ]
    run = _write_run(tmp_path / "run", bis + fred + unrelated)

    code, summary = _run(renderer, capsys, "--dir", str(run), "--max", "10")

    assert code == 0
    compare = [row for row in _manifest(run) if row["id"].startswith("data_compare_")]
    assert [row["id"] for row in compare] == [
        "data_compare_bis_ws_cbpol", "data_compare_harmonized_unemployment_rate_total_all_persons",
    ]
    assert compare[0]["series"] == ["bis:WS_CBPOL/M.US", "bis:WS_CBPOL/M.GB", "bis:WS_CBPOL/M.XM"]
    assert compare[1]["series"] == ["fred:LRHUTTTTJPM156S", "fred:LRHUTTTTDEM156S"]
    assert compare[0]["title"] == "Central bank policy rate: cross-economy comparison"
    for row in compare:
        assert _png_size(run / row["path"]) == (1600, 900)
        _assert_digit_free(row["title"])
        _assert_digit_free(row["caption"])


def test_comparison_caps_lines_and_needs_identical_units_and_frequency(renderer, tmp_path, capsys):
    codes = ("US", "GB", "JP", "CA", "AU", "CH", "SE", "NO")
    payloads = [
        _payload(f"bis:WS_CBPOL/M.{code}", title=f"Central bank policy rate {code}",
                 units="Percent per annum", values=[i * 0.1 + k for i in range(24)])
        for k, code in enumerate(codes)
    ]
    payloads.append(_payload("bis:WS_CBPOL/Q.US", freq="Q", units="Percent per annum",
                             title="Central bank policy rate quarterly"))
    run = _write_run(tmp_path / "run", payloads)

    code, summary = _run(renderer, capsys, "--dir", str(run), "--max", "9")

    assert code == 0
    compare = [row for row in _manifest(run) if row["id"].startswith("data_compare_")]
    assert len(compare) == 1
    assert compare[0]["series"] == [f"bis:WS_CBPOL/M.{code}" for code in codes[:6]]


# ---------------------------------------------------------------------------
# selection, manifest merge, lock
# ---------------------------------------------------------------------------
def test_max_selection_prefers_kiqs_then_source_ids_and_logs_dropped(renderer, tmp_path, capsys):
    names = ["fred:AAA", "fred:BBB", "fred:CCC", "fred:DDD", "fred:EEE"]
    run = _write_run(
        tmp_path / "run",
        [_payload(name, title=f"Indicator {name[-3:]}") for name in names],
        overrides={
            "fred:BBB": {"source_id": "S2"},
            "fred:DDD": {"kiqs": ["K2"]},
            "fred:EEE": {"kiqs": ["K1"], "source_id": "S5"},
        },
    )

    code, summary = _run(renderer, capsys, "--dir", str(run), "--max", "2")

    assert code == 0
    assert summary["charts"] == ["data_fred_ddd", "data_fred_eee"]
    assert [row["series"] for row in summary["dropped"]] == ["fred:BBB", "fred:AAA", "fred:CCC"]
    assert all("--max 2" in row["reason"] for row in summary["dropped"])


def test_env_default_max_and_invalid_env_value(renderer, tmp_path, capsys, monkeypatch):
    run = _write_run(tmp_path / "run", [_payload(f"fred:S{c}", title=f"Indicator {c}") for c in "ABC"])
    monkeypatch.setenv("DATA_SOURCES_CHARTS_MAX", "1")
    code, summary = _run(renderer, capsys, "--dir", str(run))
    assert code == 0 and summary["charts"] == ["data_fred_sa"] and len(summary["dropped"]) == 2
    monkeypatch.setenv("DATA_SOURCES_CHARTS_MAX", "lots")
    code, summary = _run(renderer, capsys, "--dir", str(run))
    assert code == 0 and len(summary["charts"]) == 3 and summary["dropped"] == []


def test_manifest_merge_keeps_foreign_rows_and_replaces_previous_data_rows(renderer, tmp_path, capsys):
    run = _write_run(tmp_path / "run", [_payload("fred:UNRATE", title="Unemployment Rate")])
    timeline = {"id": "timeline", "title": "Event Timeline", "path": "charts/timeline.png",
                "source_data": "timeline.json"}
    custom = {"id": "custom_market_map", "title": "Custom", "path": "charts/custom.svg"}
    stale = {"id": "data_fred_old", "title": "Old", "path": "charts/data_fred_old.png"}
    (run / "charts.json").write_text(json.dumps([timeline, stale, "junk", custom]), encoding="utf-8")

    code, _ = _run(renderer, capsys, "--dir", str(run))
    first = _manifest(run)
    code_again, _ = _run(renderer, capsys, "--dir", str(run))

    assert code == code_again == 0
    assert [row["id"] for row in first] == ["timeline", "custom_market_map", "data_fred_unrate"]
    assert first[:2] == [timeline, custom]
    assert _manifest(run) == first                                  # idempotent rerun
    # The forecast-visuals renderer, run afterwards, keeps the data_ rows it does not own.
    forecast = _load(FORECAST_RENDERER_PATH, "forecast_visuals_renderer_for_data_merge")
    merged = forecast._merge_manifest(run / "charts.json", [])
    assert [row["id"] for row in merged] == ["custom_market_map", "data_fred_unrate"]


def test_manifest_update_takes_the_shared_lock(renderer, tmp_path, monkeypatch):
    calls = []

    class FakeFcntl:
        LOCK_EX = 2
        LOCK_UN = 8

        @staticmethod
        def flock(fd, op):
            calls.append(op)

    monkeypatch.setattr(renderer, "fcntl", FakeFcntl)
    manifest = tmp_path / "charts.json"
    entry = {"id": "data_x", "title": "X", "path": "charts/data_x.png"}
    merged = renderer._update_manifest(manifest, [entry])
    assert merged == [entry]
    assert calls == [FakeFcntl.LOCK_EX, FakeFcntl.LOCK_UN]
    assert (tmp_path / "charts.json.lock").exists()
    assert manifest.read_text(encoding="utf-8").endswith("\n")


# ---------------------------------------------------------------------------
# exit codes
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("case", ["missing", "corrupt", "empty", "schema", "ineligible"])
def test_exit_2_without_eligible_data_and_stale_rows_are_removed(renderer, tmp_path, capsys, case):
    run = tmp_path / "run"
    (run / "data").mkdir(parents=True)
    manifest = run / "data" / "datasets.json"
    if case == "corrupt":
        manifest.write_text("{not json", encoding="utf-8")
    elif case == "empty":
        manifest.write_text(json.dumps({"schema_version": 1, "series": []}), encoding="utf-8")
    elif case == "schema":
        manifest.write_text(json.dumps({"schema_version": 2, "series": [{"series": "fred:X"}]}),
                            encoding="utf-8")
    elif case == "ineligible":
        _write_run(run, [_payload("fred:EMPTY", values=[None, None, None])])
    timeline = {"id": "timeline", "path": "charts/timeline.png"}
    (run / "charts.json").write_text(
        json.dumps([timeline, {"id": "data_fred_old", "path": "charts/data_fred_old.png"}]),
        encoding="utf-8")

    code, summary = _run(renderer, capsys, "--dir", str(run))

    assert code == 2
    assert summary["charts"] == [] and summary["error"]
    assert _manifest(run) == [timeline]
    assert not (run / "charts").exists()


def test_exit_2_leaves_an_absent_manifest_absent(renderer, tmp_path, capsys):
    run = tmp_path / "run"
    run.mkdir()
    code, summary = _run(renderer, capsys, "--dir", str(run))
    assert code == 2 and "missing" in summary["error"]
    assert sorted(p.name for p in run.iterdir()) == []
    code, _ = _run(renderer, capsys, "--dir", str(tmp_path / "does-not-exist"))
    assert code == 2 and not (tmp_path / "does-not-exist").exists()


def test_exit_3_when_matplotlib_is_unavailable_in_process(renderer, tmp_path, capsys, monkeypatch):
    run = _write_run(tmp_path / "run", [_payload("fred:UNRATE")])
    monkeypatch.setattr(renderer, "_HAS_MPL", False)
    code, summary = _run(renderer, capsys, "--dir", str(run))
    assert code == 3 and summary["error"] == "matplotlib unavailable"
    assert not (run / "charts").exists() and not (run / "charts.json").exists()


def _hidden_package_env(tmp_path: Path, package: str) -> dict:
    shim = tmp_path / f"hide_{package}" / package
    shim.mkdir(parents=True)
    (shim / "__init__.py").write_text(f"raise ImportError('{package} hidden for this test')\n",
                                      encoding="utf-8")
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(
        part for part in (str(shim.parent), env.get("PYTHONPATH", "")) if part)
    return env


def test_exit_3_subprocess_without_matplotlib(tmp_path):
    run = _write_run(tmp_path / "run", [_payload("fred:UNRATE")])
    proc = subprocess.run(
        [sys.executable, str(RENDERER_PATH), "--dir", str(run)],
        capture_output=True, text=True, timeout=180, env=_hidden_package_env(tmp_path, "matplotlib"),
    )
    assert proc.returncode == 3, proc.stderr
    assert json.loads(proc.stdout.strip())["error"] == "matplotlib unavailable"
    assert not (run / "charts").exists()


# ---------------------------------------------------------------------------
# CLI subprocess, determinism, language, captions, robustness
# ---------------------------------------------------------------------------
def test_cli_subprocess_end_to_end(renderer, tmp_path):
    run = _write_run(tmp_path / "run", [
        _payload("fred:UNRATE", title="Unemployment Rate"),
        _projection_payload(),
    ])
    proc = subprocess.run(
        [sys.executable, str(RENDERER_PATH), "--dir", str(run), "--max", "5", "--lang", "en"],
        capture_output=True, text=True, timeout=180,
    )
    assert proc.returncode == 0, proc.stderr
    stdout_lines = [line for line in proc.stdout.splitlines() if line.strip()]
    assert len(stdout_lines) == 1
    summary = json.loads(stdout_lines[0])
    assert summary["charts"] == ["data_fred_unrate", "data_wb_imf_weo_ngdp_rpch_usa"]
    assert "[render_data]" in proc.stderr
    assert [row["id"] for row in _manifest(run)] == summary["charts"]


def test_plotly_missing_omits_html_path(renderer, tmp_path):
    run = _write_run(tmp_path / "run", [_payload("fred:UNRATE", title="Unemployment Rate")])
    proc = subprocess.run(
        [sys.executable, str(RENDERER_PATH), "--dir", str(run)],
        capture_output=True, text=True, timeout=180, env=_hidden_package_env(tmp_path, "plotly"),
    )
    assert proc.returncode == 0, proc.stderr
    (row,) = _manifest(run)
    assert "html_path" not in row and (run / row["path"]).is_file()
    assert not (run / "charts" / "data_fred_unrate.html").exists()


def test_png_and_html_bytes_are_deterministic(renderer, tmp_path, capsys):
    payloads = [_payload("fred:UNRATE", title="Unemployment Rate"), _projection_payload(),
                _projection_payload("wb:IMF_WEO_NGDP_RPCH/CHN", geo="China")]
    first = _write_run(tmp_path / "first", payloads)
    second = _write_run(tmp_path / "second", payloads)
    assert _run(renderer, capsys, "--dir", str(first))[0] == 0
    first_bytes = {p.name: p.read_bytes() for p in (first / "charts").iterdir()}
    assert _run(renderer, capsys, "--dir", str(first))[0] == 0      # rerun in place
    assert _run(renderer, capsys, "--dir", str(second))[0] == 0     # fresh directory
    for directory in (first, second):
        current = {p.name: p.read_bytes() for p in (directory / "charts").iterdir()}
        assert current == first_bytes
    png = first_bytes["data_fred_unrate.png"]
    assert b"Software" not in png and b"Matplotlib" not in png
    assert "data_compare_wb_imf_weo_ngdp_rpch.png" in first_bytes


def test_zh_mode_uses_title_zh(renderer, tmp_path, capsys):
    payload = _payload("fred:UNRATE", title="Unemployment Rate", title_zh="失业率")
    run = _write_run(tmp_path / "run", [payload, _projection_payload(title_zh="美国实际GDP增长率")])

    code, _ = _run(renderer, capsys, "--dir", str(run), "--lang", "zh")

    assert code == 0
    rows = {row["id"]: row for row in _manifest(run)}
    assert rows["data_fred_unrate"]["title"] == "失业率"
    assert rows["data_wb_imf_weo_ngdp_rpch_usa"]["title"] == "美国实际GDP增长率"
    assert rows["data_wb_imf_weo_ngdp_rpch_usa"]["caption"].startswith("官方数据：")
    rows_in, _ = renderer._load_manifest(run)
    item, _ = renderer._load_series(run, rows_in[0], 0, set())
    bundle, _fonts = renderer._with_fonts(lambda lang: renderer._series_bundle(item, lang), "zh", "t")
    if renderer._Fonts(["失业率 实际值 来源"]).ok:
        assert bundle["title"] == "失业率" and bundle["lang"] == "zh"
    else:                                                # no CJK font installed: English image
        assert bundle["title"] == "Unemployment Rate" and bundle["lang"] == "en"


def test_manifest_titles_and_captions_are_digit_free(renderer, tmp_path, capsys):
    run = _write_run(tmp_path / "run", [
        _payload("fred:DGS10", title="10-Year Treasury Constant Maturity Rate"),
        _payload("fred:CPIAUCSL", title="Consumer Price Index (1982-1984=100), 2026 vintage",
                 units="Index 1982-1984=100", values=[300 + i for i in range(36)]),
        _payload("fred:SP500", title="S&P 500", units="Index", values=[5000 + 10 * i for i in range(36)]),
        _projection_payload(title_zh="美国2026年实际GDP增长率"),
        _projection_payload("wb:IMF_WEO_NGDP_RPCH/DEU", geo="Germany"),
    ])
    for lang in ("en", "zh"):
        code, _ = _run(renderer, capsys, "--dir", str(run), "--lang", lang)
        assert code == 0
        for row in _manifest(run):
            _assert_digit_free(row["title"])
            _assert_digit_free(row["caption"])
            assert re.fullmatch(r"[A-Za-z0-9._-]+", row["id"])
    titles = {row["id"]: row["title"] for row in _manifest(run)}
    assert titles["data_wb_imf_weo_ngdp_rpch_usa"] == "美国实际GDP增长率"
    code, _ = _run(renderer, capsys, "--dir", str(run), "--lang", "en")
    titles = {row["id"]: row["title"] for row in _manifest(run)}
    assert titles["data_fred_dgs10"] == "Ten-Year Treasury Constant Maturity Rate"
    assert titles["data_fred_cpiaucsl"] == "Consumer Price Index, vintage"


def test_robust_to_bad_rows_and_extreme_values(renderer, tmp_path, capsys):
    run = tmp_path / "run"
    outside = tmp_path / "outside.json"
    outside.write_text(json.dumps(_payload("fred:OUTSIDE")), encoding="utf-8")
    good = [
        _payload("fred:HUGE", title="Gross federal debt", units="Dollars",
                 values=[2.5e13 + 1e11 * i for i in range(30)]),
        _payload("fred:NEG", title="Federal surplus or deficit", units="Billions of Dollars",
                 values=[-1800 + 25 * i for i in range(30)]),
        _payload("fred:SAOPAULO", title="Índice de preços ao consumidor — São Paulo", units="Índice"),
        _payload("fred:MIXEDQ", freq="Q", n=12, title="Quarterly indicator"),
        _payload("fred:WEEKLY", freq="D", n=400, title="Daily indicator",
                 values=[None if i % 7 in (5, 6) else 1.0 + i / 100 for i in range(400)]),
    ]
    bad = [
        _payload("fred:ALLNONE", values=[None] * 12),
        _payload("fred:SINGLE", values=[None, 3.0, None]),
    ]
    _write_run(run, good + bad, extra_rows=[
        {"series": "fred:NOFILE", "file": "data/missing.json"},
        {"series": "fred:TRAVERSE", "file": "../outside.json"},
        {"series": "fred:CORRUPT", "file": "data/corrupt.json"},
        {"series": "fred:HUGE", "file": "data/fred_huge.json"},
        "not-a-row",
        {"file": "data/fred_neg.json"},
    ])
    (run / "data" / "corrupt.json").write_text("{\"observations\": [", encoding="utf-8")
    payload = json.loads((run / "data" / "fred_saopaulo.json").read_text(encoding="utf-8"))
    payload["observations"][3]["date"] = "garbage"
    payload["observations"][4]["value"] = "NaN"
    payload["observations"][5]["value"] = "inf"
    (run / "data" / "fred_saopaulo.json").write_text(json.dumps(payload), encoding="utf-8")

    code, summary = _run(renderer, capsys, "--dir", str(run), "--max", "8")

    assert code == 0
    assert summary["charts"] == [
        "data_fred_huge", "data_fred_neg", "data_fred_saopaulo", "data_fred_mixedq", "data_fred_weekly",
    ]
    reasons = {row["series"]: row["reason"] for row in summary["skipped"]}
    assert reasons["fred:ALLNONE"] == "no numeric observations"
    assert reasons["fred:SINGLE"].startswith("fewer than two numeric observations")
    assert "missing" in reasons["fred:NOFILE"]
    assert "outside the run directory" in reasons["fred:TRAVERSE"]
    assert "corrupt" in reasons["fred:CORRUPT"]
    assert reasons["fred:HUGE"] == "duplicate series in datasets.json"
    assert reasons["row 12"] == "manifest row is not an object"
    assert reasons["row 13"] == "manifest row has no series id"
    for chart_id in summary["charts"]:
        assert _png_size(run / "charts" / f"{chart_id}.png") == (1600, 900)


def test_value_and_tick_formatting(renderer):
    fmt = renderer._format_value
    assert fmt(4.25, "Percent") == "4.25%"
    assert fmt(-3.4, "Percent change") == "-3.4%"
    assert fmt(1.25, "Percentage Points") == "1.25 pp"
    assert fmt(71.236, "Dollars per Barrel") == "$71.24"
    assert fmt(27600, "Billions of Dollars") == "$27.6T"
    assert fmt(-1800, "Billions of Dollars") == "-$1.8T"
    assert fmt(159500, "Thousands of Persons") == "159.5M"
    assert fmt(312.2345, "Index 1982-1984=100") == "312.2"
    assert fmt(2.5e13, "Dollars") == "$25T"
    assert renderer._tick_formatter(12500) == "12,500"
    assert renderer._tick_formatter(3.5e9) == "3.5B"
    assert renderer._tick_formatter(0.5) == "0.5"


def test_refuses_a_symlinked_charts_directory(renderer, tmp_path, capsys):
    run = _write_run(tmp_path / "run", [_payload("fred:UNRATE")])
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (run / "charts").symlink_to(elsewhere, target_is_directory=True)
    code, summary = _run(renderer, capsys, "--dir", str(run))
    assert code == 2 and "charts/" in summary["error"]
    assert list(elsewhere.iterdir()) == []
