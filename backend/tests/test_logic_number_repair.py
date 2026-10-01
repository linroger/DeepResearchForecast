"""REPORT-3 (P08 stage 1b): alias-slot repair and audit wired into the report agent.

Offline: bare ReportAgents (``ReportAgent.__new__``) whose LLM-facing steps are stubbed,
so ``generate_report`` runs end to end on a per-test reports directory.  The fixture
reproduces report_ffe1ea6bf50d: final scenarios A：基准扩张 = 0.35 … D：超预期上行 = 0.05,
while the outline summary (the published blockquote) and the prose still say
"基准情景（40%）" / "基准扩张（40%）" / "仅10%概率超预期上行".
"""

import json
import os
from types import SimpleNamespace

import pytest

from app.config import Config
from app.services import report_lint as RL
from app.services.report_agent import (
    ReportAgent, ReportManager, ReportOutline, ReportSection, ReportStatus,
)
from tests.conftest import FakeLLMClient

FFE1_ROWS = [
    {"name": "A：基准扩张", "probability": 0.35},
    {"name": "B：电力受限", "probability": 0.30},
    {"name": "C：财务紧缩", "probability": 0.20},
    {"name": "D：超预期上行", "probability": 0.05},
    {"name": "E：其它/混合路径", "probability": 0.10},
]
STALE_SUMMARY = (
    "基准情景（40%）下2030年全球IT装机容量达190–210 GW、单年capex $2.5–3.2T，但电力硬约束"
    "（30%）与融资紧缩（20%）构成合计50%的下行尾部，仅10%概率超预期上行。"
)
FIXED_SUMMARY = STALE_SUMMARY.replace("基准情景（40%）", "基准情景（35%）").replace("仅10%", "仅5%")
SECTION_BODY = (
    "在基准扩张（40%）路径下，装机按管道打折后稳步兑现，电力与融资约束决定节奏。\n\n"
    "> 基准情景（40%）——某券商报告原话\n\n"
    + "本章比较各情景的电力接入、融资成本与资本开支节奏，并给出可观测的判别指标。" * 6
    + "\n"
)


def _spine():
    return {"headline": STALE_SUMMARY, "confidence": "medium", "critiqued": True,
            "scenarios": [dict(row) for row in FFE1_ROWS]}


def _agent(**over):
    a = ReportAgent.__new__(ReportAgent)
    for key, value in {
        "llm": FakeLLMClient(), "graph_id": "g1", "simulation_id": "sim_1",
        "simulation_requirement": "2030 年全球数据中心装机展望", "situation_brief": "",
        "actors": {"as_of_date": "2026-09-01"}, "sources": [], "research_report": "",
        "output_language": "Chinese", "scenario_label": "", "base_simulation_id": None,
        "_background_block": "", "_sources_index": "", "_signal_pack": "", "_market_pack": "",
        "_forecast_spine": _spine(), "_forecast_spine_block": "", "_retrieval_query": None,
        "_outline_degraded": False, "_outline_summary": "", "_section_tool_calls": 0,
        "report_logger": None, "console_logger": None, "tools": {},
    }.items():
        setattr(a, key, value)
    for key, value in over.items():
        setattr(a, key, value)
    return a


def _generating_agent(**over):
    a = _agent(**over)
    outline = ReportOutline(title="2030 全球数据中心展望", summary=STALE_SUMMARY,
                            sections=[ReportSection(title="情景分析")])
    a.plan_outline = lambda progress_callback=None, forecast_spine_block="", \
        require_forecast_structure=False: outline
    a._generate_section = lambda section, outline, previous_sections, \
        progress_callback=None, section_index=0: SECTION_BODY
    return a


@pytest.fixture
def reports_dir(monkeypatch, tmp_path):
    monkeypatch.setattr(Config, "UPLOAD_FOLDER", str(tmp_path), raising=False)
    monkeypatch.setattr(ReportManager, "REPORTS_DIR", str(tmp_path / "reports"), raising=False)
    monkeypatch.setattr(Config, "PIPELINE_DATA_DIR", str(tmp_path / "pipelines"), raising=False)
    monkeypatch.setattr(Config, "REPORT_NARRATIVE_SYNC", True, raising=False)
    # The repair is default off (REPORT_LOGIC_NUMBER_REPAIR); these tests exercise it on,
    # test_repair_is_off_by_default pins the default.
    monkeypatch.setattr(Config, "REPORT_LOGIC_NUMBER_REPAIR", True, raising=False)
    monkeypatch.setattr(Config, "REPORT_LOGIC_NUMBER_GATE", "observe", raising=False)
    monkeypatch.setattr(Config, "REPORT_FORECAST_LEDGER", False, raising=False)
    return tmp_path / "reports"


@pytest.fixture
def report_env(reports_dir, monkeypatch):
    for name, value in (("REPORT_SECTION_CONCURRENCY", 1), ("REPORT_SECTION_RETRY_MAX", 0),
                        ("REPORT_STRUCTURED_FORECAST", False), ("REPORT_SIGNAL_PACK", False),
                        ("PREDICTION_MARKETS_ENABLED", False), ("LLM_TELEMETRY_ENABLED", False),
                        ("REPORT_EDITORIAL_LINT", False), ("REPORT_CITATION_FINALIZER", False),
                        ("REPORT_BILINGUAL", False), ("REPORT_FINAL_READ_ONLY_AUDIT", False)):
        monkeypatch.setattr(Config, name, value, raising=False)
    return reports_dir


def _read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def _blockquote(md):
    return next(line for line in md.split("\n") if line.startswith("> "))


# ------------------------------------------------------------------ outline lockstep
def test_outline_lockstep(report_env, monkeypatch):
    ungrounded = {}
    for sync in (False, True):
        monkeypatch.setattr(Config, "REPORT_NARRATIVE_SYNC", sync, raising=False)
        a = _generating_agent()
        report_id = f"r_lock_{sync}"
        folder = os.path.join(report_env, report_id)
        seen = []

        def section(section, outline, previous_sections, progress_callback=None,
                    section_index=0, _agent=a, _folder=folder, _seen=seen):
            # What the section prompts see: the summary is already repaired at planning
            # (step 1), not only by the late resync after assembly.
            _seen.append((outline.summary, _agent._outline_summary,
                          json.loads(_read(os.path.join(_folder, "outline.json")))["summary"]))
            return SECTION_BODY

        a._generate_section = section
        report = a.generate_report(report_id=report_id)
        assert report.status == ReportStatus.COMPLETED
        expected = FIXED_SUMMARY if sync else STALE_SUMMARY
        assert seen == [(expected, expected, expected)]
        summary = report.outline.summary
        assert summary == expected
        # Outline, meta outline, the quote-audit exemption and the published blockquote agree.
        assert a._outline_summary == summary
        assert json.loads(_read(os.path.join(folder, "outline.json")))["summary"] == summary
        assert json.loads(_read(os.path.join(folder, "meta.json")))["outline"]["summary"] == summary
        assert _blockquote(report.markdown_content) == f"> {summary}"
        assert _blockquote(_read(os.path.join(folder, "full_report.md"))) == f"> {summary}"
        ungrounded[sync] = a._audit_quote_provenance(report.markdown_content)["ungrounded"]
        if sync:
            # Had the exemption kept the stale text, the fixed blockquote would count.
            a._outline_summary = STALE_SUMMARY
            assert a._audit_quote_provenance(report.markdown_content)["ungrounded"] == \
                ungrounded[sync] + 1
    assert ungrounded[True] <= ungrounded[False]


def test_outline_summary_untouched_without_spine_scenarios(report_env):
    a = _generating_agent(_forecast_spine={"scenarios": []})
    report = a.generate_report(report_id="r_no_spine")
    assert report.outline.summary == STALE_SUMMARY == a._outline_summary
    assert "基准扩张（40%）" in report.markdown_content


# ------------------------------------------------------------------ prose repair
def _draft():
    return (
        "# 2030 全球数据中心展望\n\n"
        f"> {STALE_SUMMARY}\n\n---\n\n"
        "## 第二部分 · 框架与综合\n\n"
        "在基准扩张（40%）路径下装机稳步兑现，仅10%概率超预期上行。\n\n"
        "> 基准情景（40%）——某券商报告原话\n\n"
        "```text\n基准情景（40%）\n```\n\n"
        "电力受限（25%）与财务紧缩（25%）合计50%。\n"
    )


def _prepare(reports_dir, report_id, md):
    folder = reports_dir / report_id
    folder.mkdir(parents=True)
    (folder / "full_report.md").write_text(md, encoding="utf-8")
    return folder


def test_repair_before_lint(reports_dir, monkeypatch):
    md = _draft()
    folder = _prepare(reports_dir, "r_fix", md)
    a = _agent(_logic_number_summary_repair=[])
    report = SimpleNamespace(markdown_content=md)
    a._repair_logic_number("r_fix", report)
    expected = md.replace("在基准扩张（40%）路径下装机稳步兑现，仅10%概率超预期上行。",
                          "在基准扩张（35%）路径下装机稳步兑现，仅5%概率超预期上行。")
    assert expected != md
    assert report.markdown_content == expected
    assert (folder / "full_report.md").read_text(encoding="utf-8") == expected
    # The summary blockquote (kept in lockstep with the outline), quotes and fences stay.
    assert f"> {STALE_SUMMARY}" in expected and "> 基准情景（40%）——" in expected
    assert "```text\n基准情景（40%）\n```" in expected
    assert a._logic_number_repair == {
        "applied": [
            {"where": "body", "scenario": "A：基准扩张", "alias": "基准扩张",
             "from": "40%", "to": "35%"},
            {"where": "body", "scenario": "D：超预期上行", "alias": "超预期上行",
             "from": "10%", "to": "5%"},
        ],
        "applied_count": 2, "summary_count": 0, "body_count": 2,
        # The sum statement's addends (B 25% vs 30%, C 25% vs 20%) are reported, never rewritten.
        "unresolved": 2,
    }

    # REPORT_NARRATIVE_SYNC=false: the draft and full_report.md stay byte-identical.
    monkeypatch.setattr(Config, "REPORT_NARRATIVE_SYNC", False, raising=False)
    folder_off = _prepare(reports_dir, "r_off", md)
    b = _agent()
    report_off = SimpleNamespace(markdown_content=md)
    b._repair_logic_number("r_off", report_off)
    assert report_off.markdown_content is md
    assert (folder_off / "full_report.md").read_bytes() == md.encode("utf-8")
    assert getattr(b, "_logic_number_repair", None) is None

    # No spine scenarios: nothing to compare against, nothing changes.
    monkeypatch.setattr(Config, "REPORT_NARRATIVE_SYNC", True, raising=False)
    c = _agent(_forecast_spine=None)
    report_none = SimpleNamespace(markdown_content=md)
    c._repair_logic_number("r_off", report_none)
    assert report_none.markdown_content is md


def test_late_summary_resync_keeps_lockstep(reports_dir):
    """Spine not ready at planning (or probabilities moved after it): the repair rewrites
    the summary blockquote only together with the outline summary and the exemption."""
    md = _draft()
    folder = _prepare(reports_dir, "r_late", md)
    outline = ReportOutline(title="2030 全球数据中心展望", summary=STALE_SUMMARY, sections=[])
    report = SimpleNamespace(markdown_content=md, outline=outline)
    a = _agent(_outline_summary=STALE_SUMMARY)
    ungrounded_before = a._audit_quote_provenance(md)["ungrounded"]
    a._repair_logic_number("r_late", report)
    assert outline.summary == FIXED_SUMMARY == a._outline_summary
    assert _blockquote(report.markdown_content) == f"> {FIXED_SUMMARY}"
    assert json.loads((folder / "outline.json").read_text(encoding="utf-8"))["summary"] == \
        FIXED_SUMMARY
    assert (folder / "full_report.md").read_text(encoding="utf-8") == report.markdown_content
    assert [row["where"] for row in a._logic_number_repair["applied"]] == [
        "outline_summary", "outline_summary", "body", "body"]
    assert (a._logic_number_repair["applied_count"], a._logic_number_repair["summary_count"],
            a._logic_number_repair["body_count"]) == (4, 2, 2)
    from app.services import logic_number as LN
    assert LN.audit_markdown(report.markdown_content, FFE1_ROWS)["fixable"] == 0
    assert a._audit_quote_provenance(report.markdown_content)["ungrounded"] == ungrounded_before

    # No line is exactly "> {summary}": the summary and its blockquote are left together.
    decorated = md.replace(f"> {STALE_SUMMARY}", f"> **{STALE_SUMMARY}**")
    _prepare(reports_dir, "r_late_decorated", decorated)
    outline2 = ReportOutline(title="T", summary=STALE_SUMMARY, sections=[])
    report2 = SimpleNamespace(markdown_content=decorated, outline=outline2)
    b = _agent(_outline_summary=STALE_SUMMARY)
    b._repair_logic_number("r_late_decorated", report2)
    assert outline2.summary == STALE_SUMMARY == b._outline_summary
    assert f"> **{STALE_SUMMARY}**" in report2.markdown_content
    assert "在基准扩张（35%）路径下" in report2.markdown_content


def test_late_resync_of_a_multiline_summary(reports_dir):
    """An outline summary with a newline is published as "> line 1\nline 2" (review round
    2): the resync rewrites the whole block together with the outline summary, and a
    block it cannot find is left whole — its continuation line is never body text."""
    summary = "装机稳步兑现。\n基准情景（40%）下电力约束决定节奏。"
    fixed = summary.replace("基准情景（40%）", "基准情景（35%）")
    md = _draft().replace(f"> {STALE_SUMMARY}", f"> {summary}")
    folder = _prepare(reports_dir, "r_multi", md)
    outline = ReportOutline(title="2030 全球数据中心展望", summary=summary, sections=[])
    report = SimpleNamespace(markdown_content=md, outline=outline)
    a = _agent(_outline_summary=summary)
    a._repair_logic_number("r_multi", report)
    assert outline.summary == fixed == a._outline_summary
    assert f"\n> {fixed}\n" in report.markdown_content
    assert "在基准扩张（35%）路径下" in report.markdown_content
    assert (folder / "full_report.md").read_text(encoding="utf-8") == report.markdown_content
    assert json.loads((folder / "outline.json").read_text(encoding="utf-8"))["summary"] == fixed
    assert [row["where"] for row in a._logic_number_repair["applied"]] == [
        "outline_summary", "body", "body"]

    # The published block differs from "> {summary}": outline and blockquote stay together.
    decorated = _draft().replace(f"> {STALE_SUMMARY}",
                                 "> **装机稳步兑现。**\n基准情景（40%）下电力约束决定节奏。")
    _prepare(reports_dir, "r_multi_decorated", decorated)
    outline2 = ReportOutline(title="T", summary=summary, sections=[])
    report2 = SimpleNamespace(markdown_content=decorated, outline=outline2)
    b = _agent(_outline_summary=summary)
    b._repair_logic_number("r_multi_decorated", report2)
    assert outline2.summary == summary == b._outline_summary
    assert "\n基准情景（40%）下电力约束决定节奏。\n" in report2.markdown_content
    assert "在基准扩张（35%）路径下" in report2.markdown_content


def test_repair_runs_after_purity_and_before_lint_and_stabilizer(report_env, monkeypatch):
    for name in ("REPORT_EDITORIAL_LINT", "REPORT_CITATION_FINALIZER", "REPORT_STRUCTURED_FORECAST",
                 "FORECAST_EMIT_BINARY", "REPORT_VISUALIZATIONS", "REPORT_THREE_PART_SKELETON",
                 "REPORT_RESOLUTION_SECTION", "REPORT_LANGUAGE_PURITY"):
        monkeypatch.setattr(Config, name, True, raising=False)
    monkeypatch.setattr(Config, "REPORT_FORECAST_SPINE_FIRST", False, raising=False)
    a = _generating_agent()
    calls = []
    # The structured-forecast block's steps, recorded in place (the spine is already pinned).
    for step in ("_prepend_binary_forecasts_section", "_inject_visualizations",
                 "_apply_three_part_skeleton", "_append_resolution_section",
                 "_apply_language_purity"):
        setattr(a, step, lambda report_id, report, _step=step: calls.append(_step))
    a._finalize_structured_forecast = lambda report_id, md, report=None: calls.append("finalize")
    real_repair = a._repair_logic_number

    def repair(report_id, report):
        calls.append("repair")
        return real_repair(report_id, report)

    def lint(report_id, report):
        calls.append(("lint", report.markdown_content))

    def stabilize(report_id, report, max_passes=4):
        calls.append("stabilize")
        return {"stable": True}

    a._repair_logic_number = repair
    a._apply_report_lint = lint
    a._stabilize_publish_markdown = stabilize
    a.generate_report(report_id="r_order")
    assert [c if isinstance(c, str) else c[0] for c in calls] == [
        "finalize", "_prepend_binary_forecasts_section", "_inject_visualizations",
        "_apply_three_part_skeleton", "_append_resolution_section", "_apply_language_purity",
        "repair", "lint", "stabilize"]
    assert "在基准扩张（35%）路径下" in calls[-2][1]


def test_repair_record_counts_beyond_the_cap(reports_dir):
    from app.services import logic_number as LN
    md = "# T\n\n" + "\n\n".join(f"第{i}段：A情景（40%）。" for i in range(30)) + "\n"
    folder = _prepare(reports_dir, "r_many", md)
    a = _agent()
    report = SimpleNamespace(markdown_content=md)
    a._repair_logic_number("r_many", report)
    record = a._logic_number_repair
    assert len(record["applied"]) == LN.LOGIC_NUMBER_FINDINGS_CAP < 30
    assert (record["applied_count"], record["summary_count"], record["body_count"]) == (30, 0, 30)
    assert "A情景（40%）" not in report.markdown_content
    assert (folder / "full_report.md").read_text(encoding="utf-8") == report.markdown_content


def test_repair_failure_is_degrade_safe(reports_dir, monkeypatch):
    md = _draft()
    _prepare(reports_dir, "r_boom", md)
    from app.services import logic_number as LN

    def boom(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(LN, "audit_markdown", boom)
    a = _agent()
    report = SimpleNamespace(markdown_content=md)
    a._repair_logic_number("r_boom", report)
    assert report.markdown_content is md
    outline = SimpleNamespace(summary=STALE_SUMMARY)
    monkeypatch.setattr(LN, "find_probability_slots", boom)
    a._repair_outline_summary_numbers(outline)
    assert outline.summary == STALE_SUMMARY


def test_repair_refreshes_the_draft_observation(reports_dir, monkeypatch):
    """_finalize_structured_forecast observed the pre-repair draft.  When the repair rewrites
    the report, forecast.json's quality.logic_number describes the repaired bytes and carries
    the repair record (review round 3), so it holds without the final audit
    (REPORT_FINAL_READ_ONLY_AUDIT=false).  Gate off, an unchanged report or no forecast.json
    leave the files as they were."""
    from app.services import logic_number as LN
    draft = {"findings": [], "count": 9, "fixable": 9, "unresolved": 0, "skipped": {}}

    def prepare(report_id, md):
        folder = _prepare(reports_dir, report_id, md)
        forecast = _spine()
        forecast["quality"] = {"logic_number": draft, "lint": {"changed": False}}
        (folder / "forecast.json").write_text(json.dumps(forecast, ensure_ascii=False),
                                              encoding="utf-8")
        a = _agent(_logic_number_summary_repair=[])
        a._forecast_spine["quality"] = {"logic_number": draft}
        return folder, a

    md = _draft()
    folder, a = prepare("r_refresh", md)
    report = SimpleNamespace(markdown_content=md)
    a._repair_logic_number("r_refresh", report)
    assert report.markdown_content != md
    saved = json.loads((folder / "forecast.json").read_text(encoding="utf-8"))
    expected = LN.audit_markdown(report.markdown_content, FFE1_ROWS)
    expected["repair"] = a._logic_number_repair
    assert saved["quality"]["logic_number"] == expected
    assert saved["quality"]["lint"] == {"changed": False}
    assert a._forecast_spine["quality"]["logic_number"] == expected
    # Left: the summary blockquote (repaired only with the outline) and the sum's addends.
    body = report.markdown_content.index("## ")
    assert (expected["fixable"], expected["unresolved"]) == (2, 2)
    assert all(f["start"] < body for f in expected["findings"] if f["status"] == "fixable")

    # The repaired report again: nothing changes, forecast.json stays byte-identical.
    folder_same, b = prepare("r_refresh_same", report.markdown_content)
    before = (folder_same / "forecast.json").read_bytes()
    b._repair_logic_number("r_refresh_same", SimpleNamespace(markdown_content=report.markdown_content))
    assert (folder_same / "forecast.json").read_bytes() == before

    # Gate off: the repair still runs (REPORT_NARRATIVE_SYNC), the observation is not taken.
    monkeypatch.setattr(Config, "REPORT_LOGIC_NUMBER_GATE", "off", raising=False)
    folder_off, c = prepare("r_refresh_off", md)
    before = (folder_off / "forecast.json").read_bytes()
    report_off = SimpleNamespace(markdown_content=md)
    c._repair_logic_number("r_refresh_off", report_off)
    assert report_off.markdown_content == report.markdown_content
    assert (folder_off / "forecast.json").read_bytes() == before

    # No forecast.json: none is created.
    monkeypatch.setattr(Config, "REPORT_LOGIC_NUMBER_GATE", "observe", raising=False)
    folder_none = _prepare(reports_dir, "r_refresh_none", md)
    d = _agent()
    d._repair_logic_number("r_refresh_none", SimpleNamespace(markdown_content=md))
    assert not (folder_none / "forecast.json").exists()


# ------------------------------------------------------------------ acceptance fixture
def test_ffe1_fixture_publishes_synced_numbers(report_env, monkeypatch):
    """The ffe1 reproduction: summary blockquote and prose carry 35% before the
    stabilizer, and the final audit shows no fixable alias slot left."""
    monkeypatch.setattr(Config, "REPORT_CITATION_FINALIZER", True, raising=False)
    monkeypatch.setattr(Config, "REPORT_FINAL_READ_ONLY_AUDIT", True, raising=False)
    monkeypatch.setattr(Config, "REPORT_PUBLISH_GATE", True, raising=False)
    a = _generating_agent()
    captured = {}

    def stabilize(report_id, report, max_passes=4):
        captured["md"] = report.markdown_content
        captured["disk"] = _read(os.path.join(report_env, report_id, "full_report.md"))
        return {"stable": True}

    a._stabilize_publish_markdown = stabilize
    a.generate_report(report_id="r_ffe1")
    md = captured["md"]
    assert captured["disk"] == md
    assert _blockquote(md) == f"> {FIXED_SUMMARY}"
    assert "在基准扩张（35%）路径下" in md and "基准扩张（40%）" not in md
    assert "> 基准情景（40%）——某券商报告原话" in md          # a quote is never rewritten

    audit = json.loads(_read(os.path.join(report_env, "r_ffe1", "final_audit.json")))
    logic = audit["logic_number"]
    assert (logic["count"], logic["fixable"], logic["unresolved"]) == (0, 0, 0)
    assert logic["repair"]["applied"] == [
        {"where": "outline_summary", "scenario": "A：基准扩张", "alias": "基准情景",
         "from": "40%", "to": "35%"},
        {"where": "outline_summary", "scenario": "D：超预期上行", "alias": "超预期上行",
         "from": "10%", "to": "5%"},
        {"where": "body", "scenario": "A：基准扩张", "alias": "基准扩张",
         "from": "40%", "to": "35%"},
    ]
    assert (logic["repair"]["applied_count"], logic["repair"]["summary_count"],
            logic["repair"]["body_count"]) == (3, 2, 1)
    assert audit["policy_version"] == 3
    assert not any("骨架不一致" in issue or "(S11)" in issue for issue in audit["hard_issues"])
    assert a.llm.calls == []                                   # zero LLM calls added


# ------------------------------------------------------------------ gate modes
def _finalize_env(monkeypatch):
    for name, value in (("FORECAST_EMIT_BINARY", False), ("REPORT_FORECAST_SELF_CRITIQUE", False),
                        ("REPORT_PUBLISH_GATE", False), ("REPORT_REPAIR_PASSES", False),
                        ("REPORT_FORECAST_LEDGER", False)):
        monkeypatch.setattr(Config, name, value, raising=False)


ALIAS_ONLY_MD = (
    "# 展望\n\n> 基准情景（40%）下装机稳步兑现。\n\n---\n\n"
    "## 分析\n\n正文里A情景（40%）仍是主路径，超预期上行只是尾部。\n"
)
ALIAS_MISMATCH = "scenario 'A：基准扩张': prose 40% vs forecast.json 35%"


def test_gate_modes(reports_dir, monkeypatch):
    _finalize_env(monkeypatch)
    forecast = _spine()
    a = _agent()

    results = {}
    for mode in ("off", "observe", "numeric", "bogus-mode"):
        monkeypatch.setattr(Config, "REPORT_LOGIC_NUMBER_GATE", mode, raising=False)
        results[mode] = a._audit_numeric_consistency(ALIAS_ONLY_MD, forecast)
    # The legacy S11 anchors on the full name, which this text never writes.
    assert results["off"] == {"scenario_prob_mismatches": [], "mismatch_count": 0}
    assert results["observe"] == results["off"] == results["bogus-mode"]
    assert results["numeric"] == {"scenario_prob_mismatches": [ALIAS_MISMATCH], "mismatch_count": 1}

    lint = {}
    for aware in (False, True):
        lint[aware] = RL.lint_report(ALIAS_ONLY_MD, "Chinese", mode="final", spine=forecast,
                                     alias_aware_s11=aware)
    assert lint[True][0] == lint[False][0]
    assert lint[True][1]["changed"] == lint[False][1]["changed"]
    assert lint[False][1]["scenario_prob_mismatches"] == \
        RL.check_scenario_probabilities(lint[False][0], forecast) == []
    assert lint[True][1]["scenario_prob_mismatches"] == [
        "scenario 'A：基准扩张': prose 40% vs spine 35%"]
    assert RL.lint_report(ALIAS_ONLY_MD, "Chinese", mode="final", spine=forecast) == lint[False]

    quality = {}
    for mode in ("off", "observe", "numeric"):
        monkeypatch.setattr(Config, "REPORT_LOGIC_NUMBER_GATE", mode, raising=False)
        report_id = f"r_gate_{mode}"
        (reports_dir / report_id).mkdir(parents=True)
        agent = _agent()
        agent._finalize_structured_forecast(report_id, ALIAS_ONLY_MD)
        saved = json.loads(_read(os.path.join(reports_dir, report_id, "forecast.json")))
        quality[mode] = saved.get("quality") or {}
    assert "logic_number" not in quality["off"]
    observed = quality["observe"]["logic_number"]
    assert (observed["count"], observed["fixable"], observed["unresolved"]) == (2, 2, 0)
    assert [f["alias"] for f in observed["findings"]] == ["基准情景", "A情景"]
    assert "repair" not in observed
    assert "numeric_consistency" not in quality["observe"]
    assert quality["numeric"]["numeric_consistency"]["scenario_prob_mismatches"] == [ALIAS_MISMATCH]


def test_finalize_attaches_repair_record(reports_dir, monkeypatch):
    _finalize_env(monkeypatch)
    (reports_dir / "r_rep").mkdir(parents=True)
    a = _agent(_logic_number_repair={"applied": [], "unresolved": 0})
    a._finalize_structured_forecast("r_rep", ALIAS_ONLY_MD)
    saved = json.loads(_read(os.path.join(reports_dir, "r_rep", "forecast.json")))
    assert saved["quality"]["logic_number"]["repair"] == {"applied": [], "unresolved": 0}


def _audit_folder(reports_dir, report_id, md):
    folder = _prepare(reports_dir, report_id, md)
    (folder / "meta.json").write_text(json.dumps({
        "report_id": report_id, "status": "completed", "failed_sections": [], "partial": False,
    }), encoding="utf-8")
    forecast = _spine()
    forecast["binary_forecasts"] = [{
        "id": "F1", "statement": "全球IT装机在2030年达到190 GW。", "probability": 0.6,
        "resolution_criteria": "以2030年底权威统计为准。",
    }]
    (folder / "forecast.json").write_text(json.dumps(forecast, ensure_ascii=False),
                                          encoding="utf-8")


def test_default_gate_changes_no_hard_rule(reports_dir, monkeypatch):
    monkeypatch.setattr(Config, "REPORT_PUBLISH_GATE", True, raising=False)
    audits = {}
    for mode in ("off", "observe", "numeric"):
        monkeypatch.setattr(Config, "REPORT_LOGIC_NUMBER_GATE", mode, raising=False)
        report_id = f"r_audit_{mode}"
        _audit_folder(reports_dir, report_id, ALIAS_ONLY_MD)
        a = _agent()
        report = SimpleNamespace(markdown_content=ALIAS_ONLY_MD, failed_sections=[])
        audits[mode] = a._audit_final_published_markdown(report_id, report)
        persisted = json.loads(_read(os.path.join(reports_dir, report_id, "final_audit.json")))
        assert persisted.get("logic_number") == audits[mode].get("logic_number")
    assert Config.REPORT_FINAL_AUDIT_POLICY_VERSION == 3
    assert {audit["policy_version"] for audit in audits.values()} == {3}
    assert "logic_number" not in audits["off"]
    assert audits["observe"]["logic_number"]["fixable"] == 2
    # observe: every hard verdict equals the gate-off audit.
    assert audits["observe"]["hard_issues"] == audits["off"]["hard_issues"]
    assert audits["observe"]["publish_gate"] == audits["off"]["publish_gate"]
    assert audits["observe"]["lint"] == audits["off"]["lint"]
    assert audits["observe"]["numeric_consistency"] == audits["off"]["numeric_consistency"]
    # numeric (owner decision): the alias mismatch reaches both existing hard S11 paths.
    assert any("情景概率/骨架不一致" in issue for issue in audits["numeric"]["hard_issues"])
    assert any("(S11)" in issue for issue in audits["numeric"]["publish_gate"]["hard_issues"])
    assert not any("(S11)" in issue for issue in audits["observe"]["publish_gate"]["hard_issues"])


def test_sealed_forecast_carries_the_final_logic_number_audit(reports_dir, monkeypatch):
    """forecast.json's quality.logic_number is the final-bytes audit plus this run's repair
    record, not the draft-stage value _finalize_structured_forecast took before the repair
    (review round 2); gate off removes it."""
    repair = {"applied": [{"where": "body", "scenario": "A：基准扩张", "alias": "基准扩张",
                           "from": "40%", "to": "35%"}],
              "applied_count": 1, "summary_count": 0, "body_count": 1, "unresolved": 0}
    stale = {"findings": [], "count": 3, "fixable": 3, "unresolved": 0, "skipped": {}}
    repaired_md = ALIAS_ONLY_MD.replace("（40%）", "（35%）")
    sealed = {}
    for mode in ("observe", "off"):
        monkeypatch.setattr(Config, "REPORT_LOGIC_NUMBER_GATE", mode, raising=False)
        report_id = f"r_sealed_{mode}"
        _audit_folder(reports_dir, report_id, repaired_md)
        path = reports_dir / report_id / "forecast.json"
        forecast = json.loads(path.read_text(encoding="utf-8"))
        forecast["quality"] = {"logic_number": stale}
        path.write_text(json.dumps(forecast, ensure_ascii=False), encoding="utf-8")
        a = _agent(_logic_number_repair=repair)
        report = SimpleNamespace(markdown_content=repaired_md, failed_sections=[])
        audit = a._audit_final_published_markdown(report_id, report)
        sealed[mode] = (audit, json.loads(path.read_text(encoding="utf-8"))["quality"])
    audit, quality = sealed["observe"]
    assert quality["logic_number"] == audit["logic_number"]
    assert (quality["logic_number"]["count"], quality["logic_number"]["fixable"]) == (0, 0)
    assert quality["logic_number"]["repair"] == repair
    audit_off, quality_off = sealed["off"]
    assert "logic_number" not in audit_off and "logic_number" not in quality_off


def test_lint_alias_s11_fails_closed(monkeypatch):
    """An exception inside the numeric-mode alias audit is a mismatch, not a skipped lint
    (review round 2), exactly as in ReportAgent._audit_numeric_consistency."""
    from app.services import logic_number as LN

    def boom(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(LN, "s11_mismatches", boom)
    forecast = _spine()
    failure = "logic-number alias audit failed: RuntimeError"
    assert RL.check_scenario_probabilities(ALIAS_ONLY_MD, forecast, alias_aware=True) == [failure]
    assert RL.check_scenario_probabilities(ALIAS_ONLY_MD, forecast) == []
    _cleaned, lint = RL.lint_report(ALIAS_ONLY_MD, "Chinese", mode="final", spine=forecast,
                                    alias_aware_s11=True)
    assert lint["scenario_prob_mismatches"] == [failure]
    monkeypatch.setattr(Config, "REPORT_LOGIC_NUMBER_GATE", "numeric", raising=False)
    assert _agent()._audit_numeric_consistency(ALIAS_ONLY_MD, forecast)[
        "scenario_prob_mismatches"] == [failure]


def test_config_default_and_env_example():
    assert Config.REPORT_LOGIC_NUMBER_GATE == "observe"
    assert ReportAgent._logic_number_gate() == "observe"
    assert Config.REPORT_LOGIC_NUMBER_REPAIR is False
    assert ReportAgent._logic_number_repair_enabled() is False
    env_example = os.path.join(os.path.dirname(__file__), "..", "..", ".env.example")
    assert "# REPORT_LOGIC_NUMBER_GATE=observe" in _read(env_example)
    assert "# REPORT_LOGIC_NUMBER_REPAIR=false" in _read(env_example)


def test_repair_is_off_by_default(report_env, monkeypatch):
    """Orchestrator decision after review round 4: the zero-token rewrite is opt-in.  With
    REPORT_LOGIC_NUMBER_REPAIR off (its default) and REPORT_NARRATIVE_SYNC on, neither the
    outline summary nor the prose is rewritten; the read-only audit still finds the stale
    slots, the evidence for turning the repair on."""
    from app.services import logic_number as LN
    monkeypatch.setattr(Config, "REPORT_LOGIC_NUMBER_REPAIR", False, raising=False)
    a = _generating_agent()
    report = a.generate_report(report_id="r_off")
    assert report.status == ReportStatus.COMPLETED
    assert report.outline.summary == STALE_SUMMARY == a._outline_summary
    assert _blockquote(report.markdown_content) == f"> {STALE_SUMMARY}"
    assert "在基准扩张（40%）路径下" in report.markdown_content
    assert a._logic_number_repair is None
    assert LN.audit_markdown(report.markdown_content, FFE1_ROWS)["fixable"] > 0

    md = _draft()
    folder = _prepare(report_env, "r_off_unit", md)
    b = _agent(_logic_number_summary_repair=[])
    unit = SimpleNamespace(markdown_content=md)
    b._repair_logic_number("r_off_unit", unit)
    assert unit.markdown_content == md and _read(folder / "full_report.md") == md
    assert getattr(b, "_logic_number_repair", None) is None


def test_summary_only_repair_refreshes_the_observation(reports_dir):
    """Review round 4: a plan-time summary repair with a body that needs no rewrite still
    replaces the draft observation, so forecast.json records the repair without the final
    audit."""
    clean = _draft().replace(f"> {STALE_SUMMARY}", f"> {FIXED_SUMMARY}").replace(
        "在基准扩张（40%）路径下装机稳步兑现，仅10%概率超预期上行。",
        "在基准扩张（35%）路径下装机稳步兑现，仅5%概率超预期上行。")
    folder = _prepare(reports_dir, "r_summary_only", clean)
    forecast = _spine()
    draft = {"findings": [], "count": 0, "fixable": 0, "unresolved": 0, "skipped": {}}
    forecast["quality"] = {"logic_number": draft}
    (folder / "forecast.json").write_text(json.dumps(forecast, ensure_ascii=False), encoding="utf-8")
    summary_rows = [{"where": "outline_summary", "alias": "基准情景", "claimed": 40, "expected_pct": 35}]
    a = _agent(_logic_number_summary_repair=summary_rows)
    report = SimpleNamespace(markdown_content=clean)
    a._repair_logic_number("r_summary_only", report)
    assert report.markdown_content == clean
    saved = json.loads((folder / "forecast.json").read_text(encoding="utf-8"))
    assert saved["quality"]["logic_number"]["repair"]["summary_count"] == 1
    assert saved["quality"]["logic_number"]["repair"]["body_count"] == 0
