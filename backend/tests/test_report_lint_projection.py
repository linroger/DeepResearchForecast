"""RESEARCH-5: observe-only reports-vs-projects attribution lint.

report_lint.check_projection_attribution counts prose sentences that restate a
research quantitative row (its key number, unit and a metric anchor) and flags a
projected row stated with realized wording and no projection wording
(projection_as_fact).  Pure and deterministic; lint_report is untouched.

Wiring (REPORT_PROJECTION_LINT, default on): ReportAgent._apply_report_lint adds
forecast.quality.projection_attribution and _audit_final_published_markdown adds
final_audit.projection_attribution.  Neither rewrites the markdown nor feeds the
publish gate; knob off (or no research rows) = byte-identical artifacts.
"""

from __future__ import annotations

import copy
import datetime as dt
import inspect
import json
import os
import sys
from types import SimpleNamespace

from app.config import Config
from app.services import forecast_extractor as fe
from app.services import report_lint as rl
from app.services.report_agent import ReportAgent, ReportManager

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))
import eval_forecast_quality as ev  # noqa: E402

AS_OF = dt.date(2026, 9, 28)
DC_FORECAST = {"metric": "Data-centre electricity demand", "series": "IEA base case", "value": 945,
               "unit": "TWh", "as_of_date": "2025-04-10", "period_end": "2030", "value_type": "forecast",
               "source": "IEA Energy and AI", "tier": "S1"}
DC_ACTUAL = {"metric": "Data-centre electricity demand", "value": 415, "unit": "TWh",
             "as_of_date": "2025-04-10", "period_end": "2024", "value_type": "actual",
             "source": "IEA Energy and AI", "tier": "S1"}
ZH_FORECAST = {"metric": "数据中心用电量", "value": 945, "unit": "太瓦时", "as_of_date": "2025-04-10",
               "period_end": "2030", "value_type": "forecast", "source": "国际能源署"}
# The collision a precision probe found: Deutsche Bank's 2026 forecast of 50,000
# humanoid robots vs Universal Robots' 50,000 cumulative cobots (a real report line).
DEUTSCHE_BANK = {"metric": "Deutsche Bank 2026 global forecast", "series": "Deutsche Bank 2026 global forecast",
                 "value": "50000", "unit": "units", "as_of_date": "2026-04-01", "period_end": "2026-12-31",
                 "value_type": "forecast", "source": "BigGo Finance Deutsche Bank humanoid shipment forecast"}
UNIVERSAL_ROBOTS = ("Universal Robots' cobot trajectory reached roughly 50,000 cumulative units globally "
                    "about twelve years after its first commercial unit in 2008.")
AS_FACT_EN = "Data-centre electricity demand reached 945 TWh [S3]."
AS_PROJECTION_EN = "Data-centre electricity demand is projected to reach 945 TWh by 2030 [S3]."


def _check(md, rows, **kwargs):
    kwargs.setdefault("as_of", AS_OF)
    return rl.check_projection_attribution(md, rows, **kwargs)


def _codes(report):
    return {code: report[code] for code in rl.PROJECTION_ATTRIBUTION_CODES}


# ── The detector ─────────────────────────────────────────────────────────────

def test_forecast_restated_with_realized_verb_is_projection_as_fact():
    report = _check(f"# Outlook\n\n{AS_FACT_EN}\n", [DC_FORECAST])
    assert report["checked_rows"] == 1
    assert report["matched_sentences"] == 1
    assert _codes(report) == {"projection_as_fact": 1, "projection_unmarked": 0,
                              "actual_as_projection": 0, "estimate_unattributed": 0}
    assert report["examples"] == [{
        "code": "projection_as_fact", "line": 3, "excerpt": AS_FACT_EN,
        "metric": "Data-centre electricity demand", "value": 945, "value_type": "forecast",
    }]


def test_forecast_stated_as_projection_is_not_flagged():
    report = _check(AS_PROJECTION_EN, [DC_FORECAST])
    assert report["matched_sentences"] == 1
    assert report["projection_as_fact"] == 0
    assert report["examples"] == []


def test_chinese_realized_wording_is_flagged_and_projection_wording_is_not():
    flagged = _check("数据中心用电已达945太瓦时。", [ZH_FORECAST], lang="Chinese")
    assert flagged["projection_as_fact"] == 1
    assert flagged["examples"][0]["excerpt"] == "数据中心用电已达945太瓦时。"
    projected = _check("数据中心用电预计到2030年达到945太瓦时。", [ZH_FORECAST], lang="Chinese")
    assert projected["matched_sentences"] == 1
    assert projected["projection_as_fact"] == 0


def test_same_number_without_unit_or_metric_anchor_does_not_match():
    report = _check(UNIVERSAL_ROBOTS, [DEUTSCHE_BANK])
    assert report["checked_rows"] == 1
    assert report["matched_sentences"] == 0
    assert report["projection_as_fact"] == 0
    # A unit alone is not enough either: the sentence must share the row's unit.
    assert _check("Data-centre electricity demand reached 945 GW.", [DC_FORECAST])["matched_sentences"] == 0


def test_scenario_probability_rows_are_skipped():
    rows = [
        {"metric": "Lithium Dominance scenario probability", "value": 30, "unit": "%",
         "value_type": "forecast"},
        {"metric": "锂主导情景概率", "value": 30, "unit": "%", "value_type": "forecast"},
        {"metric": "Probability of a grid-capacity shortfall", "value": 0.35, "unit": "probability",
         "value_type": "forecast"},
    ]
    md = ("The Lithium Dominance scenario probability was 30%.\n锂主导情景概率为30%。\n"
          "The probability of a grid-capacity shortfall was 0.35 probability.")
    report = _check(md, rows)
    assert report["checked_rows"] == 0
    assert report["matched_sentences"] == 0


def test_untyped_and_unanchorable_rows_are_ignored():
    rows = [
        {"metric": "Data-centre electricity demand", "value": 945, "unit": "TWh"},          # untyped
        {**DC_FORECAST, "epistemic_class": "unknown"},                                       # stamped unknown
        {**DC_FORECAST, "value": 2030},                                                      # bare year
        {**DC_FORECAST, "value": 7},                                                         # lone digit
        {**DC_FORECAST, "metric": "Global total market", "series": "forecast 2030"},         # stop-listed
        {**DC_FORECAST, "unit": "t"},                                                        # unusable unit
    ]
    report = _check("Data-centre electricity demand reached 945 TWh, 2030 TWh and 7 TWh.", rows)
    assert report["checked_rows"] == 0
    assert report["matched_sentences"] == 0


def test_count_only_codes():
    estimate = {"metric": "Data-centre electricity demand", "value": 415, "unit": "TWh",
                "period_end": "2024", "value_type": "estimate"}
    md = "\n".join((
        "Data-centre electricity demand of 945 TWh is a large number.",            # projection_unmarked
        "Data-centre electricity demand will stay near 415 TWh.",                  # actual_as_projection
        "Data-centre electricity demand was 415 TWh in 2024.",                     # estimate, unattributed
        "Data-centre electricity demand was an estimated 415 TWh in 2024.",        # estimate, attributed
    ))
    report = _check(md, [DC_FORECAST, estimate])
    assert report["matched_sentences"] == 4
    assert _codes(report) == {"projection_as_fact": 0, "projection_unmarked": 1,
                              "actual_as_projection": 1, "estimate_unattributed": 2}
    assert report["examples"] == []


def test_a_year_after_as_of_is_a_projection_cue():
    md = "Data-centre electricity demand was 945 TWh in 2030."
    assert _check(md, [DC_FORECAST])["projection_as_fact"] == 0
    assert _check(md, [DC_FORECAST], as_of=dt.datetime(2026, 9, 28, 12, 0))["projection_as_fact"] == 0
    # Without an as-of date the year cue is off; the realized verb decides.
    assert _check(md, [DC_FORECAST], as_of=None)["projection_as_fact"] == 1
    # "by <year>" is a cue whatever the year; a month named May is not the modal.
    assert _check("Data-centre electricity demand reached 945 TWh by 2024.", [DC_FORECAST],
                  as_of=None)["projection_as_fact"] == 0
    assert _check("Data-centre electricity demand reached 945 TWh in May 2026.", [DC_FORECAST],
                  )["projection_as_fact"] == 1


def test_only_prose_and_bullets_are_scanned():
    skipped = "\n".join((
        f"## {AS_FACT_EN}",
        f"| {AS_FACT_EN} | x |",
        f"> {AS_FACT_EN}",
        "```",
        AS_FACT_EN,
        "```",
        rl._BINARY_FORECAST_START_MARKER,
        AS_FACT_EN,
        rl._BINARY_FORECAST_END_MARKER,
        f"<!-- {AS_FACT_EN} -->",
    ))
    references = f"## References\n\n1. {AS_FACT_EN}\n\n### Notes\n\n{AS_FACT_EN}\n"
    assert _check(skipped, [DC_FORECAST])["matched_sentences"] == 0
    assert _check(references, [DC_FORECAST])["matched_sentences"] == 0
    assert _check(references.replace("## References", "## 参考来源"), [DC_FORECAST])["matched_sentences"] == 0
    md = f"{skipped}\n## Findings\n\n- {AS_FACT_EN}\n12. {AS_FACT_EN}\n{references}## Annex\n\n{AS_FACT_EN}\n"
    report = _check(md, [DC_FORECAST])
    assert report["projection_as_fact"] == 3
    lines = md.split("\n")
    for example in report["examples"]:
        assert AS_FACT_EN in lines[example["line"] - 1]
        assert not lines[example["line"] - 1].startswith(("#", "|", ">"))


def test_each_code_counts_once_per_sentence_and_examples_are_capped():
    twin = {**DC_FORECAST, "series": "IEA lift-off case", "source": "IEA"}
    report = _check(AS_FACT_EN, [DC_FORECAST, twin])
    assert report["checked_rows"] == 2
    assert report["projection_as_fact"] == 1
    md = "\n".join([AS_FACT_EN] * 5)
    capped = _check(md, [DC_FORECAST], max_examples=2)
    assert capped["projection_as_fact"] == 5
    assert [example["line"] for example in capped["examples"]] == [1, 2]
    assert _check(md, [DC_FORECAST], max_examples=0)["examples"] == []
    long_line = "Data-centre electricity demand reached 945 TWh " + "and kept climbing " * 20 + "."
    [example] = _check(long_line, [DC_FORECAST])["examples"]
    assert len(example["excerpt"]) <= 160 and example["excerpt"].endswith("…")


def test_real_row_shapes_are_read():
    """A research row with a string value, a % unit and a stamp; comma thousands."""
    penetration = {"metric": "AI芯片液冷渗透率", "series": "liquid_cooling_penetration_ai", "value": "53",
                   "unit": "%", "as_of_date": "2026-08-17", "period_end": "2026-12-31",
                   "value_type": "forecast", "value_kind": "forecast"}
    md = "电力、液冷（渗透率已达53%并成为高端标配 [S23]）、CoWoS封装供给全部奖励集中部署。"
    assert _check(md, [penetration], lang="Chinese")["projection_as_fact"] == 1
    shipments = {"metric": "Humanoid robot shipments", "value": 50000, "unit": "units", "value_type": "target",
                 "epistemic_class": "projected"}
    assert _check("Humanoid robot shipments hit 50,000 units [S2].", [shipments])["projection_as_fact"] == 1


def test_marker_literals_equal_forecast_extractor_constants():
    assert rl._BINARY_FORECAST_START_MARKER == fe.BINARY_FORECAST_START_MARKER
    assert rl._BINARY_FORECAST_END_MARKER == fe.BINARY_FORECAST_END_MARKER


def test_check_is_deterministic_and_pure():
    rows = [DC_FORECAST, DC_ACTUAL, ZH_FORECAST, DEUTSCHE_BANK]
    frozen = copy.deepcopy(rows)
    md = "\n".join((AS_FACT_EN, AS_PROJECTION_EN, UNIVERSAL_ROBOTS, "数据中心用电已达945太瓦时。",
                    "Data-centre electricity demand will reach 415 TWh again."))
    first = _check(md, rows)
    second = _check(md, rows)
    assert first == second
    assert json.dumps(first, ensure_ascii=False, sort_keys=True) == json.dumps(second, ensure_ascii=False,
                                                                              sort_keys=True)
    assert rows == frozen
    assert _codes(first)["projection_as_fact"] == 2
    empty = _check(md, [])
    assert empty == {"lang": "English", "checked_rows": 0, "matched_sentences": 0,
                     **dict.fromkeys(rl.PROJECTION_ATTRIBUTION_CODES, 0), "examples": []}
    assert _check(md, None)["checked_rows"] == 0
    assert _check("", rows)["matched_sentences"] == 0


def test_lint_report_is_unchanged_by_the_feature():
    assert list(inspect.signature(rl.lint_report).parameters) == ["md", "lang", "mode", "spine"]
    md = f"# Outlook\n\n{AS_FACT_EN}\n\n{AS_PROJECTION_EN}\n"
    cleaned, report = rl.lint_report(md, "English", mode="final")
    assert cleaned == md
    assert not set(report) & {"projection_attribution", *rl.PROJECTION_ATTRIBUTION_CODES, "checked_rows"}
    _check(md, [DC_FORECAST])
    assert rl.lint_report(md, "English", mode="final") == (cleaned, report)


def test_rubric_no_longer_credits_simulation_agent_quotes():
    with open(ev.RUBRIC_PATH, encoding="utf-8") as handle:
        text = handle.read()
    assert "simulation agent quotes" not in text
    assert "agent quotes" not in text
    parsed = ev.parse_rubric(text)
    assert set(parsed) == set(ev.RUBRIC_DIMENSIONS)
    assert ("Attribution\nphrasing without a resolvable [S#] marker or market snapshot is not grounding."
            in parsed["groundedness"])


# ── Wiring: ReportAgent ──────────────────────────────────────────────────────

REPORT_MD = (
    "# Forecast\n\n"
    "Data-centre electricity demand reached 945 TWh [S1].\n\n"
    "Data-centre electricity demand was 945 TWh in 2027 [S1].\n\n"
    "Revenue could reach 65% by 2030 [S1].\n"
)
SOURCE = {"title": "Official outlook", "url": "https://example.gov/outlook", "date": "2026-06-30",
          "tier": "S1", "content": "Data-centre electricity demand could reach 945 TWh by 2030; "
                                   "revenue could reach 65% by 2030 according to the official source."}


def _forecast():
    return {
        "headline": "Base case leads",
        "confidence": "high",
        "confidence_rationale": "Evidence is broad.",
        "scenarios": [
            {"name": "Base case", "probability": 0.6,
             "resolution_criteria": "The audited 2030 filing records the base-case outcome."},
            {"name": "Other / status quo", "probability": 0.4,
             "resolution_criteria": "Any other measurable outcome in the audited 2030 filing."},
        ],
        "binary_forecasts": [{
            "id": "F1", "statement": "Revenue reaches 65% by 2030.", "probability": 0.65,
            "resolution_criteria": "The audited 2030 filing reports revenue at 65%.",
        }],
        "quality": {},
    }


def _agent(quantitative):
    agent = ReportAgent.__new__(ReportAgent)
    agent.output_language = "English"
    agent.research_report = "Revenue evidence from the official source."
    agent._outline_summary = ""
    agent.sources = [SOURCE]
    agent._citation_index = {"S1": SOURCE}
    agent._forecast_spine = None
    agent.actors = {"as_of_date": "2026-09-28"}
    agent.quantitative = quantitative
    return agent


def _prepare(monkeypatch, root, report_id="report_projection_lint"):
    reports = root / "reports"
    folder = reports / report_id
    folder.mkdir(parents=True)
    monkeypatch.setattr(ReportManager, "REPORTS_DIR", str(reports), raising=False)
    (folder / "full_report.md").write_text(REPORT_MD, encoding="utf-8")
    (folder / "meta.json").write_text(json.dumps({"report_id": report_id, "status": "completed",
                                                  "failed_sections": [], "partial": False}), encoding="utf-8")
    (folder / "forecast.json").write_text(json.dumps(_forecast()), encoding="utf-8")
    return report_id, folder


def _run_lint(monkeypatch, root, *, enabled, quantitative):
    monkeypatch.setattr(Config, "REPORT_PROJECTION_LINT", enabled, raising=False)
    report_id, folder = _prepare(monkeypatch, root)
    agent = _agent(quantitative)
    agent._forecast_spine = _forecast()
    report = SimpleNamespace(markdown_content=REPORT_MD)
    agent._apply_report_lint(report_id, report)
    return agent, report, folder


def test_apply_report_lint_records_projection_attribution(monkeypatch, tmp_path):
    agent, report, folder = _run_lint(monkeypatch, tmp_path / "on", enabled=True,
                                      quantitative=[DC_FORECAST, DC_ACTUAL])
    _, base_report, base_folder = _run_lint(monkeypatch, tmp_path / "base", enabled=True, quantitative=None)
    fc = json.loads((folder / "forecast.json").read_text(encoding="utf-8"))
    projection = fc["quality"]["projection_attribution"]
    # The 2027 sentence is a projection only against the actors' as-of date (2026-09-28).
    assert projection["projection_as_fact"] == 1
    assert projection["examples"][0]["line"] == 3
    assert agent._forecast_spine["quality"]["projection_attribution"] == projection
    # Only the new key differs; the markdown is never rewritten by the check.
    base_fc = json.loads((base_folder / "forecast.json").read_text(encoding="utf-8"))
    del fc["quality"]["projection_attribution"]
    assert fc == base_fc
    assert report.markdown_content == base_report.markdown_content
    assert (folder / "full_report.md").read_bytes() == (base_folder / "full_report.md").read_bytes()


def test_apply_report_lint_knob_off_is_byte_identical(monkeypatch, tmp_path):
    _, _, off_folder = _run_lint(monkeypatch, tmp_path / "off", enabled=False, quantitative=[DC_FORECAST])
    _, _, base_folder = _run_lint(monkeypatch, tmp_path / "base", enabled=False, quantitative=None)
    assert (off_folder / "forecast.json").read_bytes() == (base_folder / "forecast.json").read_bytes()
    assert "projection_attribution" not in json.loads((off_folder / "forecast.json").read_text())["quality"]


def test_projection_check_failure_degrades_safe(monkeypatch, tmp_path):
    def boom(*_args, **_kwargs):
        raise RuntimeError("detector exploded")

    monkeypatch.setattr(rl, "check_projection_attribution", boom)
    _, _, folder = _run_lint(monkeypatch, tmp_path / "boom", enabled=True, quantitative=[DC_FORECAST])
    quality = json.loads((folder / "forecast.json").read_text(encoding="utf-8"))["quality"]
    assert "lint" in quality and "projection_attribution" not in quality
    audit = _run_final_audit(monkeypatch, tmp_path / "boom-audit", enabled=True, quantitative=[DC_FORECAST])[0]
    assert "projection_attribution" not in audit and audit["hard_passed"] is True


def _run_final_audit(monkeypatch, root, *, enabled, quantitative):
    monkeypatch.setattr(Config, "REPORT_PROJECTION_LINT", enabled, raising=False)
    monkeypatch.setattr(Config, "REPORT_PUBLISH_GATE", True, raising=False)
    monkeypatch.setattr(Config, "REPORT_PUBLISH_GATE_MIN_COVERAGE", 0.5, raising=False)
    report_id, folder = _prepare(monkeypatch, root)
    agent = _agent(quantitative)
    report = SimpleNamespace(markdown_content=REPORT_MD)
    agent._finalize_citations(report_id, report)
    published = report.markdown_content
    disk_before = (folder / "full_report.md").read_bytes()
    audit = agent._audit_final_published_markdown(report_id, report)
    assert report.markdown_content == published
    assert (folder / "full_report.md").read_bytes() == disk_before
    final_audit = json.loads((folder / "final_audit.json").read_text(encoding="utf-8"))
    forecast = json.loads((folder / "forecast.json").read_text(encoding="utf-8"))
    return audit, final_audit, forecast, published


def _without(mapping, *keys):
    return {key: value for key, value in mapping.items() if key not in keys}


def test_final_audit_records_projection_attribution_without_gating(monkeypatch, tmp_path):
    on = _run_final_audit(monkeypatch, tmp_path / "on", enabled=True, quantitative=[DC_FORECAST])
    off = _run_final_audit(monkeypatch, tmp_path / "off", enabled=False, quantitative=[DC_FORECAST])
    base = _run_final_audit(monkeypatch, tmp_path / "base", enabled=True, quantitative=None)
    audit, final_audit, forecast, published = on
    projection = final_audit["projection_attribution"]
    assert projection["projection_as_fact"] == 1
    assert audit["projection_attribution"] == projection
    assert forecast["quality"]["final_audit"]["projection_attribution"] == projection
    # Same published bytes, hard issues and gate outcome with the check on, off or without rows.
    for other_audit, other_final, other_forecast, other_published in (off, base):
        assert other_published == published
        assert "projection_attribution" not in other_final
        assert other_audit["hard_issues"] == audit["hard_issues"]
        assert other_audit["publish_gate"] == audit["publish_gate"]
        assert _without(other_final, "audited_at", "forecast_sha256") == \
            _without(final_audit, "audited_at", "forecast_sha256", "projection_attribution")
        mine = copy.deepcopy(forecast)
        theirs = copy.deepcopy(other_forecast)
        for fc in (mine, theirs):
            fc["quality"]["final_audit"].pop("audited_at")
        mine["quality"]["final_audit"].pop("projection_attribution")
        assert mine == theirs
    # The gate never reads it: the integrity check is blind to the new key.
    assert ReportAgent._final_audit_integrity_issues(audit) == \
        ReportAgent._final_audit_integrity_issues(_without(audit, "projection_attribution"))
