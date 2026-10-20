"""Official-data report publication on the REAL captured bundle, English and Chinese.

tests/fixtures/data_sources/real/report_bundle-2026-10-11.json holds twelve live
FRED / BIS / World Bank Data360 / IMF / U.S. Treasury rows captured through the
data layer (values verbatim, history trimmed) plus the v3-shaped research sources
that cite eleven of them, and a live fred:DEXCHUS row whose units are a long
English phrase. Every model call raises (the provider is down or the quota is
spent), the language-purity pass never runs, and no provider is contacted: a
report must publish from the stored observations alone.

Covers the report-agent findings RPT-1, RPT-2 + MISSED-1, RPT-5, RPT-10,
RPT-11, RPT-12 (backend), RPT-13, RPT-14, RPT-16 and MISSED-4, plus G5 (the
official-data track record in forecast.json).
"""
from copy import deepcopy
import json
from pathlib import Path

import pytest

from app.config import Config
from app.services import forecast_extractor as fe
from app.services import report_agent as ra
from app.services.official_data import data_api, load_official_data
from app.services.report_agent import Report, ReportAgent, ReportManager, ReportStatus
from app.services.report_visualizer import CHART_TITLES_ZH

BUNDLE = Path(__file__).parent / "fixtures" / "data_sources" / "real" / "report_bundle-2026-10-11.json"
QUESTION = {"English": "Will the US enter a recession before the end of 2027?",
            "Chinese": "美国会在2027年底前陷入衰退吗？"}
# Exact stored values (fred:UNRATE 2026-09 = 4.2, 2025-09 = 4.4, 2020-04 = 14.8;
# fred:FEDFUNDS 2026-09 = 3.75, 2023-08 = 5.33; fred:GDPC1 2026-Q2 = 24408.011;
# imf:WEO world growth 2026 = 3.055974, an unclassified publisher value).
TRUE_SENTENCES = {
    "English": [
        "The unemployment rate stood at 4.2% in September 2026 [S1].",
        "Unemployment fell 0.2 percentage points from a year earlier [S1].",
        "The unemployment rate peaked at 14.8% in April 2020 [S1].",
        "The effective federal funds rate was 3.75% in September 2026, down from 5.33% in August 2023 [S3].",
        "Real GDP reached 24,408 billion chained 2017 dollars in the second quarter of 2026 [S2].",
        "World GDP growth is 3.06% in 2026 according to the IMF [S9].",
    ],
    "Chinese": [
        "美国失业率在2026年9月为4.2% [S1]。",
        "失业率较上年同期下降0.2个百分点 [S1]。",
        "失业率在2020年4月达到14.8%的峰值 [S1]。",
        "联邦基金有效利率在2026年9月为3.75%，低于2023年8月的5.33% [S3]。",
        "2026年第二季度美国实际国内生产总值约为244,080亿美元 [S2]。",
        "据国际货币基金组织发布，2026年世界经济增长率为3.06% [S9]。",
    ],
}
# The stored 2020-04 value is 14.8: a contradiction of the cited dataset.
FABRICATED = {"English": "The unemployment rate peaked at 15.2% in April 2020 [S1].",
              "Chinese": "失业率在2020年4月达到15.2%的峰值 [S1]。"}
HEADINGS = {"English": ("# Recession outlook", "## Economic baseline", "## Risks",
                        "Tighter policy would raise the risk of contraction."),
            "Chinese": ("# 衰退展望", "## 经济基线", "## 风险", "更紧的政策会提高收缩风险。")}
FLAGS = {
    "PREDICTION_MARKETS_ENABLED": False, "REPORT_VIZ_INTERACTIVE": False, "REPORT_VIZ_PNG_EXPORT": False,
    "REPORT_VIZ_PRICE_HISTORY": False, "REPORT_VIZ_CHARTS": True, "REPORT_VISUALIZER": True,
    "REPORT_VISUALIZATIONS": True, "REPORT_DATA_CHARTS": True, "REPORT_STRUCTURED_FORECAST": True,
    "REPORT_PUBLISH_GATE": True, "REPORT_CITATION_FINALIZER": True, "REPORT_EDITORIAL_LINT": True,
    "REPORT_FINAL_READ_ONLY_AUDIT": True,
}


class UnavailableModel:
    """Every model call raises, as when the provider is down or the quota is spent."""

    def __init__(self):
        self.calls = []

    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)

        def _call(*args, **kwargs):
            self.calls.append(name)
            raise RuntimeError(f"model unavailable ({name})")
        return _call


class RecordingModel:
    """Records prompts and answers with a fixed reply (prompt-shape tests only)."""

    def __init__(self, reply):
        self.reply = reply
        self.prompts = []

    def chat(self, messages, **kwargs):
        self.prompts.append(messages)
        return self.reply if isinstance(self.reply, str) else json.dumps(self.reply)

    def chat_json(self, messages, **kwargs):
        self.prompts.append(messages)
        return deepcopy(self.reply)


def _bundle():
    return json.loads(BUNDLE.read_text(encoding="utf-8"))


@pytest.fixture
def env(tmp_path, monkeypatch):
    for name, value in FLAGS.items():
        monkeypatch.setattr(Config, name, value, raising=False)
    monkeypatch.setattr(ReportManager, "REPORTS_DIR", str(tmp_path / "reports"))
    monkeypatch.setattr(Config, "OASIS_SIMULATION_DATA_DIR", str(tmp_path / "no-simulation"))
    monkeypatch.setattr(ReportAgent, "_define_tools", lambda self: {})
    monkeypatch.setattr(ReportAgent, "_locate_timeline", lambda self: None)
    monkeypatch.setattr(ReportAgent, "_locate_handoff_dir", lambda self: None)
    return tmp_path


def _carrier(tmp_path, rows, name="handoff"):
    api = data_api()
    handoff = tmp_path / name
    handoff.mkdir(exist_ok=True)
    api.write_dataset_files([api.Series.from_dict(row) for row in rows], handoff)
    carrier = load_official_data(handoff)
    assert carrier and [row["series"] for row in carrier["series"]] == [row["series"] for row in rows]
    return handoff, carrier


def _agent(monkeypatch, language, sources, carrier, model=None):
    monkeypatch.setenv("REPORT_OUTPUT_LANGUAGE", language)
    model = model or UnavailableModel()
    agent = ReportAgent("real_graph", "real_sim", QUESTION[language], llm_client=model,
                        zep_tools=UnavailableModel(), sources=sources, official_data=carrier)
    return agent, model


def _report(report_id, language, body):
    report = Report(report_id=report_id, simulation_id="real_sim", graph_id="real_graph",
                    simulation_requirement=QUESTION[language], status=ReportStatus.COMPLETED,
                    markdown_content=body, created_at="2026-10-12T00:00:00Z",
                    completed_at="2026-10-12T00:01:00Z")
    ReportManager.save_report(report)
    return report, Path(ReportManager._get_report_folder(report_id))


def _body(language, extra=()):
    title, baseline, risks, risk_text = HEADINGS[language]
    paragraphs = [*TRUE_SENTENCES[language], FABRICATED[language], *extra]
    return "\n\n".join([title, baseline, *paragraphs, risks, risk_text]) + "\n"


_ANCHOR_NAMES = {
    "English": {"fred:UNRATE": "US unemployment rate", "fred:SAHMREALTIME": "The Sahm rule recession indicator",
                "fred:FEDFUNDS": "The effective federal funds rate", "fred:DGS10": "The 10-year Treasury yield",
                "bis:WS_CBPOL/M.US": "The US central bank policy rate"},
    "Chinese": {"fred:UNRATE": "美国失业率", "fred:SAHMREALTIME": "萨姆规则衰退指标",
                "fred:FEDFUNDS": "联邦基金有效利率", "fred:DGS10": "美国10年期国债收益率",
                "bis:WS_CBPOL/M.US": "美国央行政策利率"},
}
_ANCHORS = [("fred:UNRATE", ">=", 4.5, "2027-06", 0.55, "Percent"),
            ("fred:UNRATE", ">=", 5, "2027-06", 0.3, "Percent"),
            ("fred:UNRATE", ">=", 6, "2027-12", 0.12, "Percent"),
            ("fred:SAHMREALTIME", ">=", 0.5, "2027-06", 0.35, "Percentage Points"),
            ("fred:FEDFUNDS", "<", 3, "2027-12", 0.45, "Percent"),
            ("fred:FEDFUNDS", "<", 2.5, "2027-12", 0.2, "Percent"),
            ("fred:DGS10", ">=", 5, "2027-06", 0.4, "Percent"),
            ("bis:WS_CBPOL/M.US", "<=", 3, "2027-06", 0.62, "Per cent per year"),
            ("bis:WS_CBPOL/M.US", "<=", 2.5, "2027-12", 0.8, "Per cent per year"),
            ("fred:UNRATE", "<", 4, "2027-12", 0.1, "Percent")]


def _anchored_forecast(language, carrier):
    """Ten binaries whose structured data_anchor names a stored series and period."""
    months = {"06": "June", "12": "December"}
    items = []
    for index, (series, comparator, threshold, period, probability, units) in enumerate(_ANCHORS):
        shown = f"{threshold:g}" + ("" if units == "Percentage Points" else "%")
        name = _ANCHOR_NAMES[language][series]
        statement = (f"{name} {comparator} {shown} in {months[period[5:]]} {period[:4]}" if language == "English"
                     else f"{name}在{period[:4]}年{int(period[5:])}月 {comparator} {shown}")
        items.append({"statement": statement, "probability": probability,
                      "resolution_criteria": f"{series} {comparator} {shown} in {period}",
                      "resolution_source": "FRED", "theme": ["labor", "policy", "macro"][index % 3],
                      "horizon_year": 2027, "scenario_membership": {"derivable": False, "yes_scenarios": []},
                      "data_anchor": {"series": series, "comparator": comparator, "threshold": threshold,
                                      "observation": period, "units": units, "transform": ""}})
    binaries = fe._normalize_binaries(items, official_data=carrier, language=language)
    english = language == "English"
    forecast = {
        "headline": "US recession risk" if english else "美国衰退风险", "horizon": "2027-12-31",
        "confidence": "medium",
        "scenarios": [
            {"name": "Baseline expansion" if english else "基线扩张", "probability": 0.6,
             "resolution_criteria": ("NBER announces no business-cycle peak dated before 2027-12-31." if english
                                     else "美国国家经济研究局未宣布2027-12-31前的经济周期峰值。")},
            {"name": "Recession" if english else "衰退", "probability": 0.4,
             "resolution_criteria": ("NBER announces a business-cycle peak dated before 2027-12-31." if english
                                     else "美国国家经济研究局宣布2027-12-31前的经济周期峰值。")}],
        "binary_forecasts": binaries,
        "binary_quality": fe._binary_quality(binaries, min_count=10),
    }
    anchored = [b["data_anchor"]["series"] for b in binaries if isinstance(b.get("data_anchor"), dict)]
    assert anchored.count("fred:UNRATE") == 4, anchored  # natural EN/ZH statements anchor (RPT-3)
    return forecast


def _publish(agent, report, folder, forecast):
    """generate_report's finalization order after the authored sections exist."""
    report_id = report.report_id
    agent._forecast_spine = forecast
    (folder / "forecast.json").write_text(json.dumps(forecast, ensure_ascii=False), encoding="utf-8")
    agent._persist_official_data(report_id)
    agent._prepend_binary_forecasts_section(report_id, report)
    agent._insert_official_indicators_section(report_id, report)
    agent._inject_visualizations(report_id, report)
    # The optional Part-2 synthesis is the one model call; generate_report catches
    # its failure and keeps the structure (no placeholder is written).
    unchanged = report.markdown_content
    with pytest.raises(RuntimeError, match="model unavailable"):
        agent._apply_three_part_skeleton(report_id, report)
    assert report.markdown_content == unchanged
    agent._append_resolution_section(report_id, report)
    agent._apply_report_lint(report_id, report)
    agent._stabilize_publish_markdown(report_id, report, max_passes=6)
    audit = agent._enforce_final_publish_audit(report_id, report)
    ReportManager.save_report(report)
    return audit


def _published(language, env, monkeypatch):
    bundle = _bundle()
    handoff, carrier = _carrier(env, bundle["series"])
    agent, model = _agent(monkeypatch, language, bundle["sources"], carrier)
    report, folder = _report(f"report_real_{language.lower()}", language, _body(language))
    audit = _publish(agent, report, folder, _anchored_forecast(language, carrier))
    return {"language": language, "agent": agent, "model": model, "report": report, "folder": folder,
            "audit": audit, "carrier": carrier, "handoff": handoff, "bundle": bundle}


@pytest.fixture(params=["English", "Chinese"])
def published(request, env, monkeypatch):
    return _published(request.param, env, monkeypatch)


@pytest.fixture
def published_en(env, monkeypatch):
    return _published("English", env, monkeypatch)


@pytest.mark.parametrize("fail_pdf", [False, True])
def test_legacy_visual_replay_binds_or_rolls_back_new_track_record(env, monkeypatch, fail_pdf):
    """A replay's first historical capture follows the report transaction."""
    import hashlib
    import scripts.backfill_report_visuals as backfill
    from app.services import forecast_ledger

    monkeypatch.setattr(Config, "REPORT_FORECAST_LEDGER", False)
    monkeypatch.setattr(Config, "FORECAST_LEDGER_DIR", str(env / "replay-ledger"))
    published = _published("English", env, monkeypatch)
    report, folder = published["report"], published["folder"]
    companion = folder / "forecast_track_record.json"
    assert not companion.exists()
    before = {name: (folder / name).read_bytes() for name in
              ("meta.json", "forecast.json", "full_report.md", "final_audit.json")}
    pipeline = env / "pipelines" / "pipe_legacy_replay"
    pipeline.mkdir(parents=True)
    (published["handoff"] / "sources.json").write_text(
        json.dumps(published["bundle"]["sources"]), encoding="utf-8")
    (pipeline / "pipeline_state.json").write_text(json.dumps({
        "report_id": report.report_id, "simulation_id": "real_sim",
        "handoff_dir": str(published["handoff"]),
    }), encoding="utf-8")
    monkeypatch.setattr(Config, "PIPELINE_DATA_DIR", str(env / "pipelines"))
    monkeypatch.setattr(Config, "REPORT_FORECAST_LEDGER", True)
    reached = []

    def export_pdf(cls, report_id, force=False, lang=None):
        assert companion.exists()
        reached.append(report_id)
        if fail_pdf:
            raise RuntimeError("synthetic downstream PDF failure")
        path = Path(cls._get_report_pdf_path(report_id))
        path.write_bytes(b"%PDF-1.4 replay")
        return str(path)

    monkeypatch.setattr(ReportManager, "export_pdf", classmethod(export_pdf))
    if fail_pdf:
        with pytest.raises(RuntimeError, match="synthetic downstream PDF failure"):
            backfill.backfill_one("pipe_legacy_replay", report.report_id, apply=True)
        assert not companion.exists()
        assert all((folder / name).read_bytes() == value for name, value in before.items())
    else:
        backfill.backfill_one("pipe_legacy_replay", report.report_id, apply=True)
        forecast = json.loads((folder / "forecast.json").read_text())
        assert json.loads(companion.read_text()) == forecast["historical_calibration"]["forecast_track_record"]
        markdown = (folder / "full_report.md").read_bytes()
        assert json.loads((folder / "meta.json").read_text())["markdown_content"] == markdown.decode()
        assert json.loads((folder / "final_audit.json").read_text())["markdown_sha256"] == hashlib.sha256(markdown).hexdigest()
    assert reached
    # A visual replay is not a new forecasting admission.
    assert forecast_ledger.list_published_report_ids() == []
    assert ReportManager.publication_status(report.report_id)["publishable"]


def _section(markdown, heading):
    """Lines of one H2 section (heading excluded) up to the next H2."""
    lines = markdown.split("\n")
    start = lines.index(heading)
    end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith("## ")), len(lines))
    return lines[start + 1:end]


def _cells(row):
    return [cell.strip() for cell in row.strip().strip("|").split("|")]


def test_real_bundle_publishes_without_any_model(published):
    language, report, audit = published["language"], published["report"], published["audit"]
    assert audit["hard_passed"], audit["hard_issues"]
    assert ReportManager.is_publishable(report.report_id)
    # Nothing on the publication path depends on a model: the only attempt is the
    # optional Part-2 synthesis, which degrades by skipping the three-part skeleton.
    assert set(published["model"].calls) <= {"chat"}
    assert audit["lint"]["language_contamination"]["lines"] == 0
    assert audit["semantic_citations"]["unsupported"] == 0
    assert audit["official_chart_captions"]["passed"] and audit["official_chart_captions"]["checked"] >= 2
    if language == "Chinese":
        assert "Official Series History" not in report.markdown_content
        assert "Official Indicators" not in report.markdown_content


def test_key_official_indicators_table_is_the_stored_carrier(published):
    language, agent, report = published["language"], published["agent"], published["report"]
    lang = "en" if language == "English" else "zh"
    heading = ra.OFFICIAL_INDICATORS_HEADINGS[0 if lang == "en" else 1]
    markdown = report.markdown_content
    assert markdown.count(heading) == 1
    # Directly after Part 1, before the authored analysis.
    assert markdown.index("<!-- binary-forecast-block:end -->") < markdown.index(heading)
    assert markdown.index(heading) < markdown.index(HEADINGS[language][1])
    rows = [line for line in _section(markdown, heading) if line.startswith("| ") and "---" not in line][1:]
    tags = {row["series"]: agent._official_source_tag(row) for row in published["carrier"]["series"]}
    expected = [ra.render_official_indicator_row(summary, lang) for summary in ra.official_indicator_rows(
        published["carrier"], lang=lang, tag_for=lambda row: tags[row["series"]])]
    assert rows == expected and len(rows) == 12
    unrate = _cells(rows[0])
    if lang == "en":
        assert "Unemployment Rate" in unrate[0]
        assert unrate[1:] == ["Percent", "4.2%", "2026-09", "-0.2 pp", "3.4% to 4.7%", "—", "[S1]"]
    else:
        assert unrate[0].startswith("美国失业率")
        assert unrate[1:] == ["Percent", "4.2%", "2026-09", "-0.2 个百分点", "3.4% 至 4.7%", "—", "[S1]"]
    stored = {point["date"]: point["value"] for point in published["carrier"]["series"][0]["observations"]}
    assert stored["2026-09-01"] == 4.2 and stored["2025-09-01"] == 4.4
    # RPT-16: the dataset the research report never cited is still a citable source,
    # listed in References after the research positions.
    assert rows[-1].endswith("| [S13] |")
    references = _section(markdown, "## References" if lang == "en" else "## 参考来源")
    assert any("[S13]" in line and "fiscaldata.treasury.gov/datasets/monthly-treasury-statement" in line
               for line in references)
    # A points measure shows its points change only (0.23 -> 0 is not "-100%").
    sahm = next(row for row in rows if "Sahm" in row or "萨姆" in row)
    assert _cells(sahm)[1:5] == ["Percentage Points", "0", "2026-09", "-0.23"]


def test_official_exhibits_sit_in_the_indicator_section_with_their_source_captions(published):
    language, report, folder = published["language"], published["report"], published["folder"]
    manifest = json.loads((folder / "viz_manifest.json").read_text(encoding="utf-8"))
    official = [item for item in manifest["items"] if item.get("source") == "official_data"]
    assert official[0]["id"] == "official_indicators" and len(official) >= 2
    heading = ra.OFFICIAL_INDICATORS_HEADINGS[0 if language == "English" else 1]
    section = "\n".join(_section(report.markdown_content, heading))
    prefix = "Source: " if language == "English" else "来源："
    for item in official:
        marker = f"<!-- viz:{item['path']} -->"
        assert marker in section
        block = section.split(marker, 1)[1].split("<!-- viz:", 1)[0]
        # RPT-2: a Chinese report shows the Chinese chart title as alt text and caption.
        caption = item["caption"] if language == "English" else CHART_TITLES_ZH[item["caption"]]
        assert f"![{caption}]({item['path']})" in block and f"*{caption}*" in block
        # MISSED-4: one caption helper for markdown and manifest, publisher names.
        assert item["source_caption"].startswith(prefix)
        assert "*" + item["source_caption"] + "*" in block
        stored = {row["series"]: row for row in published["carrier"]["series"]}
        for entry in item["provenance"]:
            assert f"[{stored[entry['series']]['provider_name']}](<{entry['source_url']}>) [{entry['source_id']}]" \
                in item["source_caption"]
    dashboard = official[0]["source_caption"]
    assert ("; Percent; Monthly; SA" if language == "English" else "; Percent; 月度; SA") in dashboard


def test_exact_official_sentences_keep_their_citations(published):
    language, report = published["language"], published["report"]
    for sentence in TRUE_SENTENCES[language]:
        assert sentence in report.markdown_content, sentence
    fabricated = FABRICATED[language]
    assert fabricated not in report.markdown_content
    claim = fabricated.replace(" [S1]", "")
    assert all("[S1]" not in line for line in report.markdown_content.split("\n") if claim.rstrip("。.") in line)


def test_anchored_watch_table_is_tagged_and_canonical(published):
    language, agent, report = published["language"], published["agent"], published["report"]
    heading = "### Official series to watch" if language == "English" else "### 官方观察序列"
    lines = report.markdown_content.split("\n")
    start = lines.index(heading)
    rows = []
    for line in lines[start + 3:]:
        if not line.startswith("| "):
            break
        rows.append(line)
    anchored = [b for b in agent._forecast_spine["binary_forecasts"] if isinstance(b.get("data_anchor"), dict)]
    assert len(rows) == len(anchored) >= 8
    for row, binary in zip(rows, anchored, strict=True):
        series = binary["data_anchor"]["series"]
        tag = next(t for t, source in agent._citation_index.items()
                   if isinstance(source.get("dataset"), dict) and source["dataset"].get("series") == series)
        assert row.endswith(f" [{tag}] |"), row
        assert f"({series})" in row or f"（{series}）" in row
        # Canonical metadata: validated byte for byte against the stored carrier.
        assert agent._official_watch_line_support(row, tag) is True
        assert agent._official_watch_line_support(row.replace(" / 2027-", " / 2028-"), tag) is not True
        assert agent._official_watch_line_support(row, "S12") is False
    unrate_5 = rows[1]
    assert ("4.2% (2026-09)" if language == "English" else "4.2%（2026-09）") in unrate_5
    assert ">= 5% / 2027-06" in unrate_5 and ("vs model 30%" if language == "English" else "vs 模型 30%") in unrate_5


def test_report_local_carrier_and_official_data_api(published):
    report, folder, carrier = published["report"], published["folder"], published["carrier"]
    record = ReportManager.load_report_official_data(report.report_id)
    assert record is not None and record["official_data"] == carrier
    assert record["source_tags"]["fred:UNRATE"] == "S1"
    assert record["source_tags"]["usgov:treasury/mts_deficit"] == "S13"
    from app import create_app
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as client:
        response = client.get(f"/api/report/{report.report_id}/official-data")
        assert response.status_code == 200
        data = response.get_json()["data"]
        assert data["available"] is True and data["sha256"] == record["sha256"]
        assert data["official_data"] == json.loads(json.dumps(carrier))
        assert len(data["indicators"]) == 12
        unrate = data["indicators"][0]
        assert unrate["series"] == "fred:UNRATE" and unrate["source_id"] == "S1"
        assert unrate["latest"]["display"] == "4.2%" and unrate["latest"]["period"] == "2026-09"
        assert unrate["provider_name"] == "FRED (Federal Reserve Bank of St. Louis)"
        assert data["indicators"][-1]["source_id"] == "S13"
        zh = client.get(f"/api/report/{report.report_id}/official-data?lang=zh").get_json()["data"]
        assert zh["lang"] == "zh" and zh["indicators"][0]["label"].startswith("美国失业率")
        assert client.get(f"/api/report/{report.report_id}/official-data?lang=fr").status_code == 400
        # A tampered carrier is never served (digest check).
        path = folder / "official_data.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["official_data"]["series"][0]["observations"][-1]["value"] = 9.9
        path.write_text(json.dumps(payload), encoding="utf-8")
        tampered = client.get(f"/api/report/{report.report_id}/official-data").get_json()["data"]
        assert tampered["available"] is False and tampered["indicators"] == []


def test_official_data_api_respects_the_publication_gate(env, monkeypatch):
    report, _folder = _report("report_unaudited", "English", "# Draft\n\nUnaudited draft.\n")
    from app import create_app
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as client:
        assert client.get("/api/report/report_unaudited/official-data").status_code == 409
        assert client.get("/api/report/report_missing/official-data").status_code == 404


def test_executive_brief_carries_indicators_and_anchored_watch(published):
    from app.services.exec_brief import ExecBriefBuilder
    language, report, folder = published["language"], published["report"], published["folder"]
    produced = ExecBriefBuilder.build(report.report_id, str(folder), force=True)
    brief = Path(produced["exec_brief"]).read_text(encoding="utf-8")
    digest = Path(produced["digest"]).read_text(encoding="utf-8")
    if language == "English":
        assert "## Key official indicators" in brief
        assert "| Indicator | Latest observed | Period | Year-over-year change | Source |" in brief
        assert "| 4.2% | 2026-09 | -0.2 pp | [FRED (Federal Reserve Bank of St. Louis)]" in brief
        assert ("- US unemployment rate >= 4.5% in June 2027 — latest 4.2% (2026-09); "
                "threshold >= 4.5% (2027-06); historical base rate") in brief
        assert "**Key official indicators:** " in digest and "4.2% (2026-09)" in digest
    else:
        assert "## 关键官方指标" in brief
        assert "| 指标 | 最新观测值 | 期间 | 同比变化 | 来源 |" in brief
        assert "| 4.2% | 2026-09 | -0.2 个百分点 |" in brief
        assert "— 最新 4.2% (2026-09); 阈值 >= 4.5% (2027-06); 历史基率" in brief
        assert "**关键官方指标:** " in digest


def test_zh_report_publishes_without_purity_for_long_unit_series(env, monkeypatch):
    """RPT-2 + MISSED-1: Chinese chart titles and verbatim official captions (DEXCHUS
    units are a long English phrase) publish with no purity pass and no model."""
    bundle = _bundle()
    for name in ("REPORT_STRUCTURED_FORECAST", "REPORT_PUBLISH_GATE"):
        monkeypatch.setattr(Config, name, False)
    rows = bundle["dexchus"]["series"] + bundle["series"][:1]
    sources = bundle["dexchus"]["sources"] + bundle["sources"][:1]
    _handoff, carrier = _carrier(env, rows)
    agent, model = _agent(monkeypatch, "Chinese", sources, carrier)
    body = "# 汇率与就业\n\n## 官方数据基线\n\n人民币汇率与就业是两项关键基线。\n\n## 风险\n\n政策收紧会提高下行风险。\n"
    report, folder = _report("report_zh_dexchus", "Chinese", body)
    agent._inject_visualizations(report.report_id, report)
    agent._apply_report_lint(report.report_id, report)
    agent._stabilize_publish_markdown(report.report_id, report, max_passes=6)
    audit = agent._enforce_final_publish_audit(report.report_id, report)
    assert audit["hard_passed"], audit["hard_issues"]
    assert audit["lint"]["language_contamination"]["lines"] == 0
    assert "Chinese Yuan Renminbi to One U.S. Dollar" in report.markdown_content
    assert "![官方指标](charts/official_indicators.png)" in report.markdown_content
    assert model.calls == []


@pytest.mark.parametrize("language", ["English", "Chinese"])
def test_cited_official_claims_are_checked_against_the_stored_series(env, monkeypatch, language):
    """RPT-1: the publication repair and the final audit use carrier-backed support."""
    bundle = _bundle()
    _handoff, carrier = _carrier(env, bundle["series"])
    agent, _model = _agent(monkeypatch, language, bundle["sources"], carrier)
    index = agent._citation_index_or_fallback()
    for sentence in TRUE_SENTENCES[language]:
        tag = sentence.rsplit("[", 1)[1].split("]", 1)[0]
        claim = sentence.replace(f" [{tag}]", "")
        assert agent._report_citation_support(claim, index[tag]) is True, sentence
    fabricated = FABRICATED[language].replace(" [S1]", "")
    assert agent._report_citation_support(fabricated, index["S1"]) is False
    # A stored value of a different series, or a different period, is not support.
    other = "The unemployment rate stood at 3.75% in September 2026." if language == "English" \
        else "美国失业率在2026年9月为3.75%。"
    assert agent._report_citation_support(other, index["S1"]) is False


def test_quantitative_repair_cites_true_official_claims(env, monkeypatch):
    """RPT-1 / RPT-16: uncited true values gain the stored series' marker, including a
    dataset no research source cited; a contradicted value never gains one."""
    bundle = _bundle()
    _handoff, carrier = _carrier(env, bundle["series"])
    monkeypatch.setattr(Config, "REPORT_PUBLISH_GATE_MIN_COVERAGE", 0.99, raising=False)
    agent, _model = _agent(monkeypatch, "English", bundle["sources"], carrier)
    markdown = "\n".join(["## Analysis", "",
                          "The unemployment rate peaked at 14.8% in April 2020.", "",
                          "The unemployment rate peaked at 15.2% in April 2020.", "",
                          "The monthly federal deficit was about $166.8 billion in August 2026.", "",
                          "China's unemployment rate was 4.2% in September 2026."])
    repaired, info = agent._repair_final_quantitative_grounding(markdown)
    assert info["applied"]
    assert "The unemployment rate peaked at 14.8% in April 2020. [S1]" in repaired
    assert "The monthly federal deficit was about $166.8 billion in August 2026. [S13]" in repaired
    assert "15.2%" not in repaired
    assert "China's unemployment rate was 4.2% in September 2026." in repaired
    assert "September 2026. [S1]" not in repaired

    zh_agent, _model = _agent(monkeypatch, "Chinese", bundle["sources"], carrier)
    zh = "\n".join(["## 分析", "", "美国失业率在2026年9月为4.2%。", "",
                    "2026年8月联邦财政月度赤字约为1,668亿美元。"])
    repaired, _info = zh_agent._repair_final_quantitative_grounding(zh)
    assert "美国失业率在2026年9月为4.2%。 [S1]" in repaired
    assert "2026年8月联邦财政月度赤字约为1,668亿美元。 [S13]" in repaired


def test_data_pack_rows_stay_whole_and_name_omissions(env, monkeypatch):
    """RPT-5: rows end only at row boundaries, carry labels, and omissions are named."""
    bundle = _bundle()
    _handoff, carrier = _carrier(env, bundle["series"])
    agent, _model = _agent(monkeypatch, "English", bundle["sources"], carrier)
    full = agent._data_pack
    assert len(full) <= 5000
    ids = [row["series"] for row in carrier["series"]]
    shown = [series for series in ids if f"({series}) |" in full]
    note = next((line for line in full.split("\n") if "further stored series not shown" in line), "")
    assert all(series in note for series in ids if series not in shown)
    assert "| Unemployment Rate — United States (fred:UNRATE) | 4.2% / 2026-09 |" in full
    assert "Year-over-year change: -0.25 percentage points [S7]" in full  # BIS 'Per cent per year'
    assert "Source: https://" not in full  # every stored dataset has a marker (RPT-16)
    assert "(unclassified publisher value) [S9]" in full

    small = agent._build_data_pack(budget=1500)
    assert len(small) <= 1500
    kept = [series for series in ids if f"({series}) |" in small]
    dropped = [series for series in ids if series not in kept]
    assert kept and dropped
    assert small.endswith(f"{len(dropped)} further stored series not shown: {', '.join(dropped)}.")
    for line in small.split("\n")[2:]:
        assert line.startswith(("| ", "|---", "Year-over-year change: ", "Historical five-year range",
                                "Transform: ", f"{len(dropped)} further")) or ": " in line, line


def test_spine_critique_and_fallback_receive_the_stored_pack(env, monkeypatch):
    """RPT-5 / RPT-14: a spine-sized pack the spine never cuts, plus the pack for
    critique, pre-mortem and fallback extraction; nothing changes without data."""
    bundle = _bundle()
    _handoff, carrier = _carrier(env, bundle["series"])
    monkeypatch.setattr(Config, "REPORT_FORECAST_SELF_CRITIQUE", True, raising=False)
    monkeypatch.setattr(Config, "REPORT_CRITIQUE_BEFORE_PROSE", True, raising=False)
    monkeypatch.setattr(Config, "FORECAST_EMIT_BINARY", False, raising=False)
    captured = {}
    spine = {"headline": "h", "horizon": "2027-12-31", "confidence": "medium",
             "scenarios": [{"name": "Baseline", "probability": 1.0, "resolution_criteria": "r"}]}

    def _spine(llm, **kwargs):
        captured["spine"] = kwargs
        return deepcopy(spine)

    def _critique(forecast, llm, language="", **kwargs):
        captured["critique"] = kwargs
        return forecast

    def _premortem(forecast, llm, language="", **kwargs):
        captured["premortem"] = kwargs
        return forecast

    def _extract(markdown, llm, **kwargs):
        captured["extract"] = kwargs
        return deepcopy(spine)

    monkeypatch.setattr(fe, "derive_forecast_spine", _spine)
    monkeypatch.setattr(fe, "self_critique_forecast", _critique)
    monkeypatch.setattr(fe, "premortem_forecast", _premortem)
    monkeypatch.setattr(fe, "extract_structured_forecast", _extract)
    for official in (carrier, None):
        captured.clear()
        agent, _model = _agent(monkeypatch, "English", bundle["sources"], official)
        _report_obj, _folder = _report("report_spine_" + ("data" if official else "none"), "English", "# R\n")
        agent._derive_and_pin_forecast_spine(_report_obj.report_id)
        agent._forecast_spine = None
        agent._finalize_structured_forecast(_report_obj.report_id, "# R\n")
        if official:
            facts = captured["spine"]["quantitative_facts"]
            assert facts == agent._build_data_pack(budget=fe.OFFICIAL_PACK_PROMPT_CAP) == agent._data_pack
            assert fe._cap_at_line(facts, fe.OFFICIAL_PACK_PROMPT_CAP) == facts  # never cut mid-row
            assert captured["spine"]["official_data"] is carrier
            # The judging stages get the pack plus the empirical outside view.
            judged = agent._data_pack + "\n\n" + fe.official_outside_view_block(carrier, None, "English")
            for stage in ("critique", "premortem"):
                assert captured[stage] == {"data_pack": judged}, stage
            assert captured["extract"]["data_pack"] == judged
        else:
            assert agent._data_pack == "" and captured["spine"]["quantitative_facts"] == ""
            assert "official_data" not in captured["spine"]
            assert "data_pack" not in captured["critique"] and "data_pack" not in captured["premortem"]
            assert "data_pack" not in captured["extract"]


def test_outline_and_chat_prompts_use_the_pack_only_with_official_data(env, monkeypatch):
    """RPT-10 outline rule and RPT-14 chat: present with stored data, absent otherwise."""
    bundle = _bundle()
    _handoff, carrier = _carrier(env, bundle["series"])

    class Zep(UnavailableModel):
        def get_simulation_context(self, **kwargs):
            return {}

    prompts = {}
    for official in (carrier, None):
        model = RecordingModel({"title": "Outline", "summary": "s",
                                "sections": [{"title": f"Section {i}", "description": "d"} for i in range(6)]})
        agent, _model = _agent(monkeypatch, "English", bundle["sources"], official, model=model)
        agent.zep_tools = Zep()
        agent.plan_outline()
        model.reply = "Final Answer: stored values only."
        agent.chat("What is the latest unemployment rate?")
        prompts[bool(official)] = (model.prompts[0][1]["content"], model.prompts[1][0]["content"], agent._data_pack)
    plan, chat, pack = prompts[True]
    assert pack and pack in plan and plan.endswith(ra.OFFICIAL_DATA_PLAN_RULE)
    assert chat.endswith("\n\n" + pack + "\n回答涉及上述官方指标的问题时，只使用这些存储值及其期间与来源标记 [S#]；"
                         "不要编造未列出的数值。")
    plan, chat, pack = prompts[False]
    assert pack == "" and ra.OFFICIAL_DATA_PLAN_RULE not in plan and "[Official data snapshot]" not in plan
    assert "[Official data snapshot]" not in chat and "官方指标" not in chat


def test_backfill_keeps_official_exhibits_captions_and_audit(published_en, monkeypatch):
    """RPT-13: replaying visuals on a published report keeps every official exhibit and
    its attribution, leaves no orphan caption and passes the same final audit."""
    import scripts.backfill_report_visuals as backfill
    published = published_en
    report, folder, env_root = published["report"], published["folder"], published["handoff"].parent
    before = report.markdown_content
    pipeline = env_root / "pipelines" / "pipe_real_backfill"
    pipeline.mkdir(parents=True)
    (published["handoff"] / "sources.json").write_text(json.dumps(published["bundle"]["sources"]), encoding="utf-8")
    (pipeline / "pipeline_state.json").write_text(json.dumps({
        "report_id": report.report_id, "simulation_id": "real_sim", "handoff_dir": str(published["handoff"]),
    }), encoding="utf-8")
    monkeypatch.setattr(Config, "PIPELINE_DATA_DIR", str(env_root / "pipelines"), raising=False)

    def _export_pdf(cls, report_id, force=False, lang=None):
        path = Path(cls._get_report_pdf_path(report_id))
        path.write_bytes(b"%PDF-1.4 replay")
        return str(path)

    monkeypatch.setattr(ReportManager, "export_pdf", classmethod(_export_pdf))
    backfill.backfill_one("pipe_real_backfill", report.report_id, apply=True)
    after = (folder / "full_report.md").read_text(encoding="utf-8")
    audit = json.loads((folder / "final_audit.json").read_text(encoding="utf-8"))
    assert audit["hard_passed"], audit["hard_issues"]
    manifest = json.loads((folder / "viz_manifest.json").read_text(encoding="utf-8"))
    official = [item for item in manifest["items"] if item.get("source") == "official_data"]
    assert [line for line in after.split("\n") if line.startswith("*Source: ")] == [
        "*" + item["source_caption"] + "*" for item in official]
    assert sum(f"<!-- viz:{item['path']} -->" in before for item in official) == len(official)
    assert all(f"<!-- viz:{item['path']} -->" in after for item in official)
    assert after.count(ra.OFFICIAL_INDICATORS_HEADINGS[0]) == 1
    assert all(sentence in after for sentence in TRUE_SENTENCES["English"])


def test_strip_generated_visuals_consumes_official_attribution():
    """RPT-13: an official exhibit's attribution line belongs to the exhibit."""
    from scripts.backfill_report_visuals import strip_generated_visuals
    caption = ("*Source: [FRED (Federal Reserve Bank of St. Louis)](<https://fred.stlouisfed.org/series/UNRATE>)"
               " [S1]; Percent; Monthly; SA*")
    markdown = "\n".join([
        "## Key official indicators", "", "| Indicator | Latest |", "|---|---|", "| Unemployment | 4.2% |", "",
        "<!-- viz:charts/official_indicators.png -->", "![Official Indicators](charts/official_indicators.png)", "",
        "*Official Indicators*", "", caption, "",
        "<!-- viz:charts/official_series_abc.png -->", "![官方序列历史与预测阈值](charts/official_series_abc.png)", "",
        "*官方序列历史与预测阈值*", "", caption.replace("*Source: ", "*来源：").replace("Monthly", "月度"), "",
        "## Analysis", "", "*Source: field interviews*", "", "Prose stays.",
    ])
    stripped = strip_generated_visuals(markdown)
    assert "viz:" not in stripped and "fred.stlouisfed.org" not in stripped
    assert "| Unemployment | 4.2% |" in stripped and "*Source: field interviews*" in stripped
    assert strip_generated_visuals(stripped) == stripped


def test_absent_official_data_changes_no_report_surface(env, monkeypatch):
    """Invariant §0.2: without a carrier the citation index, pack, section and brief
    are exactly the pre-integration ones."""
    from app.services.exec_brief import ExecBriefBuilder
    bundle = _bundle()
    agent, _model = _agent(monkeypatch, "English", bundle["sources"], None)
    assert agent._data_pack == "" and agent._official_pack_kwargs() == {}
    assert agent._build_sources_index() == agent._build_research_sources_index()
    report, folder = _report("report_no_official", "English", _body("English"))
    before = report.markdown_content
    agent._insert_official_indicators_section(report.report_id, report)
    assert report.markdown_content == before
    agent._persist_official_data(report.report_id)
    assert ReportManager.load_report_official_data(report.report_id) is None
    brief = Path(ExecBriefBuilder.build(report.report_id, str(folder), force=True)["exec_brief"])
    assert "Key official indicators" not in brief.read_text(encoding="utf-8")


def test_malformed_stored_row_degrades_instead_of_failing_the_report(env, monkeypatch):
    """Invariant §0.1: a stored row that cannot be summarized is skipped everywhere
    (pack, citation index, indicator table); the agent and the report still build."""
    bundle = _bundle()
    _handoff, carrier = _carrier(env, bundle["series"])
    summarize = ra.official_indicator_summary
    broken = {"fred:GDPC1", "usgov:treasury/mts_deficit"}

    def _summary(row, **kwargs):
        if row["series"] in broken:
            raise ValueError("malformed stored row")
        return summarize(row, **kwargs)

    monkeypatch.setattr(ra, "official_indicator_summary", _summary)
    agent, _model = _agent(monkeypatch, "English", bundle["sources"], carrier)
    assert "(fred:UNRATE) |" in agent._data_pack and "(fred:GDPC1) |" not in agent._data_pack
    assert "S13" not in agent._citation_index  # the unsummarizable uncited dataset gets no source
    report, _folder = _report("report_degraded_row", "English", _body("English"))
    agent._insert_official_indicators_section(report.report_id, report)
    table = _section(report.markdown_content, ra.OFFICIAL_INDICATORS_HEADINGS[0])
    rows = [line for line in table if line.startswith("| ") and "---" not in line][1:]
    assert len(rows) == len(carrier["series"]) - len(broken)
    assert all(agent._official_indicator_line_support(row, "") is True for row in rows)


@pytest.mark.parametrize("language", ["English", "Chinese"])
def test_forecast_json_keeps_the_official_data_track_record_separate(env, monkeypatch, language):
    """G5: binaries the resolution monitor settled against the stored observation give the
    next forecast.json a separate binary track record under historical_calibration. It never
    enters the scenario Brier or the confidence note, and forecast.json has no
    historical_calibration until something has resolved."""
    from types import SimpleNamespace
    import scripts.resolution_monitor as monitor
    from app.services import forecast_ledger
    bundle = _bundle()
    _handoff, carrier = _carrier(env, bundle["series"])
    ledger = env / "ledger"
    monkeypatch.setattr(forecast_ledger, "ledger_dir", lambda: str(ledger))
    for name, value in {"REPORT_FORECAST_LEDGER": True, "FORECAST_EMIT_BINARY": False,
                        "REPORT_FORECAST_SELF_CRITIQUE": False, "REPORT_REPAIR_PASSES": False,
                        "DATA_SOURCES_ENABLED": True}.items():
        monkeypatch.setattr(Config, name, value, raising=False)

    def finalize(report_id):
        agent, model = _agent(monkeypatch, language, bundle["sources"], carrier)
        agent._forecast_spine = {**_anchored_forecast(language, carrier), "critiqued": True}
        report, folder = _report(report_id, language, _body(language))
        agent._finalize_structured_forecast(report_id, report.markdown_content, report)
        assert model.calls == []
        return json.loads((folder / "forecast.json").read_text(encoding="utf-8"))

    untracked = finalize("report_track_none")
    assert "historical_calibration" not in untracked
    assert forecast_ledger.official_data_track_record() is None

    # A prior report's September 2026 anchors settle on the stored fred:UNRATE value (4.2).
    prior = fe._normalize_binaries([
        {"statement": f"{_ANCHOR_NAMES['English']['fred:UNRATE']} >= {threshold:g}% in September 2026",
         "probability": probability, "resolution_criteria": f"fred:UNRATE >= {threshold:g}% in 2026-09",
         "resolution_source": "FRED", "theme": "labor", "horizon_year": 2026,
         "scenario_membership": {"derivable": False, "yes_scenarios": []},
         "data_anchor": {"series": "fred:UNRATE", "comparator": ">=", "threshold": threshold,
                         "observation": "2026-09", "units": "Percent", "transform": ""}}
        for threshold, probability in ((4, 0.7), (4.5, 0.4))], official_data=carrier, language="English")
    stored = next(row for row in bundle["series"] if row["series"] == "fred:UNRATE")
    data_client = SimpleNamespace(get=lambda series, **kwargs: data_api().Series.from_dict(stored))
    result = monitor.run_monitor("report_prior", forecast={"binary_forecasts": prior}, client=SimpleNamespace(),
                                 data_client=data_client, as_of="2026-10-12", write_report=False,
                                 report_folder=str(env / "prior"), ledger_dir=str(ledger))
    assert [row["status"] for row in result["data_resolution_status"]] == ["resolved", "resolved"]
    track_record = {"n_resolved": 2, "mean_brier": 0.125, "source": "data_resolutions.jsonl",
                    "scoring": "binary Brier vs official observation"}  # (0.7-1)^2=0.09, (0.4-0)^2=0.16

    tracked = finalize("report_track_data")
    assert tracked["historical_calibration"] == {"n_resolved": 0, "mean_brier": None, "calibration_error": None,
                                                 "official_data_track_record": track_record}
    assert "confidence_rationale" not in tracked  # no scenario has resolved: no calibration note
    assert {key: value for key, value in tracked.items() if key != "historical_calibration"} == untracked

    # Draft finalization no longer admits production forecasts. Seed a historical
    # legacy row explicitly to verify its separately labeled compatibility summary.
    assert forecast_ledger.read_ledger() == []
    forecast_ledger.append_forecast(untracked, report_id="legacy_scenario", created_at="2026-10-01T00:00:00Z")
    # A resolved scenario forecast keeps its own Brier; the binary record stays beside it.
    entries = forecast_ledger.read_ledger()
    entries[0].update(resolved=True, outcome=untracked["scenarios"][1]["name"])
    (ledger / "ledger.jsonl").write_text("".join(json.dumps(entry, ensure_ascii=False) + "\n" for entry in entries),
                                         encoding="utf-8")
    scenario = forecast_ledger.calibration_summary()
    assert scenario["n_resolved"] == 1 and scenario["mean_brier"] is not None
    both = finalize("report_track_both")
    assert both["historical_calibration"] == {**scenario, "official_data_track_record": track_record}
    assert f"平均 Brier {scenario['mean_brier']}" in both["confidence_rationale"]
    assert "0.125" not in both["confidence_rationale"]


@pytest.mark.parametrize("language", ["English", "Chinese"])
def test_canonical_official_lines_do_not_count_toward_the_per_source_cap(env, monkeypatch, language):
    """RPT-16 + SESSIONB-2: each anchored binary adds a tagged 'Official series to watch' row,
    so a heavily anchored series used to pass REPORT_MAX_CITATIONS_PER_SOURCE and the
    concentration repair stripped the [S#] from its chart caption, failing the final audit.
    Canonical official lines (exhibit captions, indicator and watch rows) are attribution, not
    reliance on one source in prose: they are neither counted nor stripped, prose still is."""
    bundle = _bundle()
    _handoff, carrier = _carrier(env, bundle["series"])
    agent, _model = _agent(monkeypatch, language, bundle["sources"], carrier)
    name, months = _ANCHOR_NAMES[language]["fred:UNRATE"], {"06": "June", "12": "December"}
    items = []
    for index in range(12):
        threshold, period = round(4.3 + index / 10, 1), ("2027-06" if index % 2 else "2027-12")
        items.append({
            "statement": (f"{name} >= {threshold:g}% in {months[period[5:]]} {period[:4]}" if language == "English"
                          else f"{name}在{period[:4]}年{int(period[5:])}月 >= {threshold:g}%"),
            "probability": round(0.9 - index * 0.06, 2), "resolution_criteria": f"fred:UNRATE >= {threshold:g}% in {period}",
            "resolution_source": "FRED", "theme": ["labor", "policy", "macro"][index % 3], "horizon_year": 2027,
            "scenario_membership": {"derivable": False, "yes_scenarios": []},
            "data_anchor": {"series": "fred:UNRATE", "comparator": ">=", "threshold": threshold,
                            "observation": period, "units": "Percent", "transform": ""}})
    binaries = fe._normalize_binaries(items, official_data=carrier, language=language)
    assert sum(isinstance(binary.get("data_anchor"), dict) for binary in binaries) == 12
    forecast = _anchored_forecast(language, carrier)
    forecast.update(binary_forecasts=binaries, binary_quality=fe._binary_quality(binaries, min_count=10))
    # Four more exact stored values (2026-02 4.4, 03 4.3, 06 4.2, 07 4.1): seven [S1] prose claims.
    stored = [("02", "February", 4.4), ("03", "March", 4.3), ("06", "June", 4.2), ("07", "July", 4.1)]
    extra = [f"The unemployment rate was {value:g}% in {month} 2026 [S1]." if language == "English"
             else f"美国失业率在2026年{int(number)}月为{value:g}% [S1]。" for number, month, value in stored]
    report, folder = _report(f"report_cap_{language.lower()}", language, _body(language, extra))
    audit = _publish(agent, report, folder, forecast)
    assert audit["hard_passed"], audit["hard_issues"]
    assert audit["official_chart_captions"]["passed"] and audit["official_chart_captions"]["checked"] == 2
    assert audit["semantic_citations"]["overused_sources"] == []
    markdown = report.markdown_content
    manifest = json.loads((folder / "viz_manifest.json").read_text(encoding="utf-8"))
    for item in manifest["items"]:
        if item.get("source") == "official_data":
            assert "*" + item["source_caption"] + "*" in markdown.split("\n"), item["path"]
    watch = [line for line in markdown.split("\n") if line.startswith("| ") and "fred:UNRATE" in line
             and agent._official_watch_line_support(line, "S1") is True]
    assert len(watch) == 12 and all(line.endswith(" [S1] |") for line in watch)
    assert all(sentence in markdown for sentence in [*TRUE_SENTENCES[language][:3], *extra])
    body = markdown
    for heading in ra._REFS_HEADINGS:
        body = body.split("\n" + heading + "\n")[0]
    assert body.count("[S1]") > 20  # 12 watch rows, the indicator row, 2 captions and 7 prose claims
    # Reliance on one source in prose is still capped: 14 more cited notes push prose alone past 20.
    notes = [f"Labour demand cools in the {word} sector [S1]." for word in (
        "retail", "housing", "energy", "health", "transport", "finance", "education", "mining",
        "software", "leisure", "farming", "media", "defence", "utilities")]
    flooded = body + "\n\n" + "\n\n".join(notes) + "\n"
    assert agent._audit_semantic_citations(flooded)["overused_sources"] == [{"tag": "S1", "count": 21, "limit": 20}]
    capped, stripped = agent._repair_overused_citations(flooded)
    assert stripped == 1 and all(line in capped.split("\n") for line in watch)
