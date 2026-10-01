"""REPORT-9 (C11 phase 2, detection only): the report's figures against the REPORT-8
verified-figures block (verified_facts.check_verified_figures), recorded in
forecast.quality.verified_figures and final_audit.json, and figure_provenance.json.
Shadow: never changes markdown bytes, never adds a hard or epistemic issue.  Offline."""

from __future__ import annotations

import hashlib
import inspect
import json
import os
from datetime import date
from types import SimpleNamespace

import pytest

from app.config import Config
from app.config_audit import RANGE_RULES
from app.services import verified_facts as vf
from app.services.forecast_extractor import BINARY_FORECAST_END_MARKER, BINARY_FORECAST_START_MARKER
from app.services.report_agent import ReportAgent, ReportManager
from app.utils.numeric_guards import scan_quantities, threshold_spans
from tests.conftest import FakeLLMClient

AS_OF = date(2026, 6, 30)
SHARE = {"metric": "Data-centre electricity share", "value": "24.6", "unit": "%", "when": "2025", "tag": "S1"}
CAPEX = {"metric": "Global data centre capex spending", "value": "1,200", "unit": "USD billion",
         "when": "2025", "tag": "S2"}


def _check(md, rows=(SHARE, CAPEX), **kwargs):
    return vf.check_verified_figures(md, list(rows), **kwargs)


def _counts(md, rows=(SHARE, CAPEX), **kwargs):
    return {k: v for k, v in _check(md, rows, **kwargs)["counts"].items() if v}


# ------------------------------------------------------------------ pure check
@pytest.mark.parametrize("line", [
    "The data-centre electricity share was 24.6% in 2025 [S1].",          # exact
    "The data-centre electricity share reached about 25% in 2025 [S1].",   # rounding to the claim
    "Global data centre capex spending hit $1.2 trillion in 2025 [S2].",   # scale
    "Global data centre capex spending hit $1,200 billion in 2025.",
])
def test_match_cases(line):
    result = _check(f"# T\n\n{line}\n")
    assert result["counts"]["matched"] == 1 and sum(result["counts"].values()) == 1
    (index,) = result["matched_rows"]
    assert result["matched_rows"][index] == [{"line": 3, "excerpt": line}]


def test_conflict_and_guards():
    conflict = _check("# T\n\nThe data-centre electricity share was 31% in 2025 [S3].\n")
    assert conflict["counts"]["conflict"] == 1
    assert conflict["examples"][0]["kind"] == "conflict" and conflict["examples"][0]["row_index"] == 0
    assert conflict["examples"][0]["cited"] == "S3"
    # Two candidate rows with different values: ambiguous, never a conflict.
    other = dict(SHARE, value="30", tag="S4")
    assert _counts("# T\n\nThe data-centre electricity share was 27% in 2025.\n", rows=(SHARE, other)) \
        == {"ambiguous": 1}
    # A year mismatch, a unit-class mismatch or a 10x ratio is no conflict.
    assert _counts("# T\n\nThe data-centre electricity share was 31% in 2019.\n") == {"unmatched": 1}
    assert _counts("# T\n\nThe data-centre electricity share was $31 billion in 2025.\n") == {"unmatched": 1}
    assert _counts("# T\n\nThe data-centre electricity share was 0.5% in 2025.\n") == {"unmatched": 1}
    # Within rel_tol is no conflict either.
    assert _counts("# T\n\nThe data-centre electricity share was 24.9% in 2025.\n", rel_tol=0.05) \
        == {"unmatched": 1}
    # No anchor: unmatched, whatever the number.
    assert _counts("# T\n\nShipments rose 31% in 2025.\n") == {"unmatched": 1}


def test_table_cells_take_their_row_or_column_year():
    year_column = "# T\n\n| Metric | Year | Value |\n|---|---|---|\n| Data-centre electricity share | {year} | 31% |\n"
    # The year sits in another cell of the row: a 2030 row is no conflict with the 2025 figure.
    assert _counts(year_column.format(year=2030)) == {"unmatched": 1}
    assert _counts(year_column.format(year=2025)) == {"conflict": 1}
    # The year is the column header: each cell is read with its own column's year.
    by_column = ("# T\n\n| Metric | 2025 | 2030E |\n|---|---|---|\n"
                 "| Data-centre electricity share | 24.6% | 31% |\n")
    result = _check(by_column)
    assert {k: v for k, v in result["counts"].items() if v} == {"matched": 1, "unmatched": 1}
    assert result["matched_rows"] == {0: [{"line": 5, "excerpt": "24.6%"}]}
    # A cell's own year beats its column's.
    assert _counts("# T\n\n| Metric | 2030E |\n|---|---|\n| Data-centre electricity share | 31% (2025) |\n") \
        == {"conflict": 1}
    # A line outside the table ends it: a later headerless row takes no stale column year.
    assert _counts(by_column + "\nSee the table.\n\n| Data-centre electricity share | n/a | 31% |\n") \
        == {"matched": 1, "unmatched": 1, "conflict": 1}


def test_thresholds_and_probabilities_are_counted_apart():
    # Neither the probability nor the threshold states the metric's level.
    assert _counts("# T\n\nWe assign a 40% probability that the data-centre electricity share will exceed 30%.\n") \
        == {"threshold_or_probability": 2}
    assert _counts("# T\n\nThe odds are 35% that the data-centre electricity share stays below 20% in 2025.\n") \
        == {"threshold_or_probability": 2}
    zh_row = {"metric": "数据中心电力占比", "value": "24.6", "unit": "%", "when": "2025", "tag": "S1"}
    assert _counts("# T\n\n2025年数据中心电力占比超过30%的概率为40%。\n", rows=[zh_row]) \
        == {"threshold_or_probability": 2}
    assert _counts("# T\n\n2025年数据中心电力占比为31%。\n", rows=[zh_row]) == {"conflict": 1}
    # The level beside them is still checked.
    assert _counts("# T\n\nThe data-centre electricity share was 31% in 2025, with a 40% chance of exceeding "
                   "35% by 2030.\n") == {"conflict": 1, "threshold_or_probability": 2}


def test_threshold_spans_marks_only_comparator_governed_figures():
    text = "The share was 24.6% and may exceed 30%, or reach 5% or more; it sits between 28% and 38%."
    spans = threshold_spans(text)
    assert [hit["raw"] for hit in scan_quantities(text) if any(lo <= hit["start"] < hi for lo, hi in spans)] \
        == ["30%", "5%", "28%", "38%"]
    for unreadable in (None, {"a": 1}, True, ""):
        assert threshold_spans(unreadable) == []


def test_source_discrepancies_need_the_cited_source_to_support_the_claim():
    md = "# T\n\nThe data-centre electricity share was 31% in 2025 [S3].\n"
    assert _check(md, support_fn=lambda unit, tag: True)["source_discrepancies"] == [{
        "line": 3, "excerpt": md.splitlines()[2], "tag": "S3", "row_index": 0, "claim": "31%",
        "row_value": "24.6"}]
    for verdict in (False, None):
        assert _check(md, support_fn=lambda unit, tag, v=verdict: v)["source_discrepancies"] == []

    def boom(unit, tag):
        raise RuntimeError("support check failed")

    assert _check(md, support_fn=boom)["source_discrepancies"] == []
    uncited = "# T\n\nThe data-centre electricity share was 31% in 2025.\n"
    assert _check(uncited, support_fn=lambda unit, tag: True)["source_discrepancies"] == []


def test_citation_tags_follow_the_report_grammar():
    # Every tag of the unit is tried; the first that supports the claim is recorded,
    # normalised as forecast_extractor._norm_citation_tag does.
    md = "# T\n\nThe data-centre electricity share was 31% in 2025 [s3]【S1-A】.\n"
    seen = []

    def support(unit, tag):
        seen.append(tag)
        return tag == "S1-a"

    result = _check(md, support_fn=support)
    assert seen == ["S3", "S1-a"]
    assert [(d["tag"], d["claim"]) for d in result["source_discrepancies"]] == [("S1-a", "31%")]
    assert result["examples"][0]["cited"] == "S3"
    # A legacy tiered tag cites the unit: its restatement is the writer's own sourcing.
    unverified = {"metric": "Grid connection queue length", "value": "40", "unit": "months",
                  "verification": "unverified"}
    assert _counts("# T\n\nThe grid connection queue length reached 40 months [S5-b].\n",
                   excluded_rows=[unverified]) == {"unmatched": 1}


def test_scope():
    stated = "The data-centre electricity share was 31% in 2025."
    md = "\n".join([
        "# The data-centre electricity share was 31% in 2025", "",
        "## Data-centre electricity share 31% in 2025", "",
        BINARY_FORECAST_START_MARKER, f"- F1: {stated} (70%)", BINARY_FORECAST_END_MARKER, "",
        "```", stated, "```", "",
        "## References", "", f"- {stated} [S1]", "",
    ])
    assert sum(_check(md)["counts"].values()) == 0
    # The same sentence in the body counts, and a section after References is read again.
    after = md + "\n## Outlook\n\n" + stated + "\n"
    assert _counts(after) == {"conflict": 1}
    # A table cell is read with its whole row as the anchor.
    table = "# T\n\n| Metric | 2025 |\n|---|---|\n| Data-centre electricity share | 31% |\n"
    assert _counts(table) == {"conflict": 1}


def test_states_unverified_and_market():
    unverified = {"metric": "Grid connection queue length", "value": "40", "unit": "months",
                  "verification": "unverified"}
    md = "# T\n\nThe grid connection queue length reached 40 months.\n"
    assert _counts(md, excluded_rows=[unverified]) == {"states_unverified": 1}
    # Cited, the restatement is the writer's own sourcing: not flagged.
    assert _counts(md.replace("months.", "months [S5]."), excluded_rows=[unverified]) == {"unmatched": 1}
    market = {"market_id": "m1", "question": "Will the AI liability directive be adopted by June 2026?",
              "implied_yes_prob": 0.30, "price_at_research": 0.25}
    wrong = "# T\n\nPolymarket implies a 45% chance the AI liability directive is adopted.\n"
    right = "# T\n\nPolymarket implies a 30% chance the AI liability directive is adopted.\n"
    research_price = "# T\n\nPolymarket implied 25% for the AI liability directive at research time.\n"
    assert _counts(wrong, market_rows=[market]) == {"market_conflict": 1}
    assert _counts(right, market_rows=[market]) == {"unmatched": 1}
    assert _counts(research_price, market_rows=[market]) == {"unmatched": 1}
    # No anchored market: nothing to compare against (and "45% chance" is a probability).
    assert _counts(wrong, market_rows=[dict(market, question="Will oil exceed $100?")]) \
        == {"threshold_or_probability": 1}
    assert _counts(wrong) == {"threshold_or_probability": 1}


def test_market_percentages_are_read_against_the_markets_only():
    # The market's question and the block's metric share their anchor words.
    market = {"market_id": "m2", "question": "Will the data-centre electricity share exceed 30% in 2030?",
              "implied_yes_prob": 0.45, "price_at_research": 0.40}
    price = "# T\n\nPolymarket implies a {p}% chance the data-centre electricity share exceeds 30%.\n"
    # The market's own price is no conflict with the block's 24.6%, nor is the threshold.
    assert _counts(price.format(p=45), market_rows=[market]) == {"threshold_or_probability": 1, "unmatched": 1}
    assert _counts(price.format(p=40), market_rows=[market]) == {"threshold_or_probability": 1, "unmatched": 1}
    assert _counts(price.format(p=60), market_rows=[market]) == {"threshold_or_probability": 1, "market_conflict": 1}
    # A level quoted beside the market: the block's value matches, any other is a market conflict.
    level = "# T\n\nPolymarket prices a 45% chance although the data-centre electricity share was {v}% in 2025.\n"
    assert _counts(level.format(v=24.6), market_rows=[market]) == {"matched": 1, "unmatched": 1}
    assert _counts(level.format(v=31), market_rows=[market]) == {"market_conflict": 1, "unmatched": 1}
    assert _counts(level.format(v=31)) == {"threshold_or_probability": 1, "unmatched": 1}
    # "manifold" and a bare "implied" are ordinary words: no market context.
    for line in ("A manifold rise took the data-centre electricity share to 31% in 2025.",
                 "The implied data-centre electricity share was 31% in 2025."):
        assert _counts(f"# T\n\n{line}\n", market_rows=[market]) == {"conflict": 1}
    assert _counts("# T\n\nThe implied probability of 60% puts the data-centre electricity share above 30%.\n",
                   market_rows=[market]) == {"market_conflict": 1, "threshold_or_probability": 1}


def test_bare_small_numbers_and_years_are_no_figures():
    assert sum(_check("# T\n\nThree of the 3 scenarios start in 2025 and end in 2030.\n")["counts"].values()) == 0


def test_examples_and_matched_lines_are_capped():
    md = "# T\n\n" + "\n\n".join(["The data-centre electricity share was 31% in 2025."] * 30
                                 + ["The data-centre electricity share was 24.6% in 2025."] * 15) + "\n"
    result = _check(md)
    assert result["counts"]["conflict"] == 30 and len(result["examples"]) == vf.CHECK_EXAMPLES_MAX
    assert len(result["matched_rows"][0]) == vf.MATCHED_LINES_PER_ROW


# ------------------------------------------------------------------ report agent (shadow)
_SOURCE = {"title": "Energy agency annual review", "url": "https://agency.example/review", "tier": "S1",
           "content": "The data-centre electricity share was 24.6% in 2025."}
_OTHER = {"title": "Trade body survey", "url": "https://trade.example/survey", "tier": "S3",
          "content": "The trade body puts the data-centre electricity share at 31% in 2025."}
_MARKETS = [{"market_id": "m1", "question": "Will the share exceed 30% in 2026?", "implied_yes_prob": 0.2,
             "price_at_research": 0.25, "quoted_at": "2026-06-29T10:00:00+00:00",
             "snapshot_as_of": "2026-06-29T09:00:00+00:00", "volume": 1000}]
_QUANT = [{"metric": "Data-centre electricity share", "value": "24.6", "unit": "%", "as_of_date": "2025-12-31",
           "value_type": "actual", "tier": "S1", "source": "Energy agency annual review", "source_ref": "S1",
           "source_url": "https://agency.example/review", "verification": "verified", "verified": True},
          {"metric": "Grid connection queue length", "value": "40", "unit": "months", "as_of_date": "2026-03-01",
           "value_type": "actual", "tier": "S3", "source": "Wire story", "verification": "unverified"}]
MD = ("# Forecast\n\n"
      "The data-centre electricity share was 24.6% in 2025 [S1].\n\n"
      "The trade body puts the data-centre electricity share at 31% in 2025 [S2].\n\n"
      "The grid connection queue length reached 40 months.\n")


def _forecast():
    return {"headline": "Base case leads", "confidence": "high", "confidence_rationale": "Broad evidence.",
            "scenarios": [{"name": "Base case", "probability": 0.6, "resolution_criteria": "Filing records it."},
                          {"name": "Other / status quo", "probability": 0.4,
                           "resolution_criteria": "Any other outcome."}],
            "binary_forecasts": [{"id": "F1", "statement": "Share exceeds 30% by 2030.", "probability": 0.3,
                                  "resolution_criteria": "The agency reports above 30%."}],
            "quality": {}}


def _agent(*, labelled=True, quantitative=_QUANT):
    agent = ReportAgent.__new__(ReportAgent)
    agent.output_language = "English"
    agent.research_report = ""
    agent._outline_summary = ""
    agent.sources = [_SOURCE, _OTHER]
    agent._citation_index = {"S1": _SOURCE, "S2": _OTHER}
    agent._forecast_spine = None
    agent._prediction_markets = [dict(m) for m in _MARKETS]
    agent.quantitative = [dict(r) for r in quantitative]
    agent._verified_figures = vf.build_verified_figures_block(
        agent.quantitative if labelled else [], tag_for=lambda row: row.get("source_ref"), lang="en", as_of=AS_OF)
    return agent


def _prepare(tmp_path, monkeypatch, report_id, md=MD, forecast=None):
    reports = tmp_path / "reports"
    folder = reports / report_id
    folder.mkdir(parents=True)
    monkeypatch.setattr(ReportManager, "REPORTS_DIR", str(reports), raising=False)
    (folder / "full_report.md").write_text(md, encoding="utf-8")
    (folder / "meta.json").write_text(json.dumps({"report_id": report_id, "status": "completed",
                                                  "failed_sections": [], "partial": False}), encoding="utf-8")
    (folder / "forecast.json").write_text(json.dumps(forecast or _forecast()), encoding="utf-8")
    return folder


def _audit(tmp_path, monkeypatch, report_id, *, knob, labelled=True, forecast=None, quantitative=_QUANT,
           stale_sidecar=False):
    monkeypatch.setattr(Config, "REPORT_VERIFIED_FIGURES_CHECK", knob, raising=False)
    folder = _prepare(tmp_path, monkeypatch, report_id, forecast=forecast)
    if stale_sidecar:
        (folder / "figure_provenance.json").write_text(
            json.dumps({"schema": "drf.figure_provenance/v1", "block_sha256": "old"}), encoding="utf-8")
    agent = _agent(labelled=labelled, quantitative=quantitative)
    md_sha = hashlib.sha256((folder / "full_report.md").read_bytes()).hexdigest()
    report = SimpleNamespace(markdown_content=MD)
    audit = agent._audit_final_published_markdown(report_id, report)
    agent._write_figure_provenance(report_id, report)
    # Read-only: neither the audit nor the sidecar touches the published markdown.
    assert report.markdown_content == MD
    assert hashlib.sha256((folder / "full_report.md").read_bytes()).hexdigest() == md_sha
    forecast = json.loads((folder / "forecast.json").read_text(encoding="utf-8"))
    return folder, agent, report, audit, forecast


def test_shadow_only(tmp_path, monkeypatch):
    monkeypatch.setattr(Config, "REPORT_PUBLISH_GATE", True, raising=False)
    on_folder, on_agent, on_report, on, on_forecast = _audit(tmp_path, monkeypatch, "r_on", knob=True)
    off_folder, _, off_report, off, off_forecast = _audit(tmp_path, monkeypatch, "r_off", knob=False)

    # Markdown bytes, hard issues and the gate are what the knob-off run gives.
    assert on_report.markdown_content == off_report.markdown_content == MD
    assert (on_folder / "full_report.md").read_bytes() == (off_folder / "full_report.md").read_bytes()
    assert on["hard_issues"] == off["hard_issues"] and on["hard_passed"] == off["hard_passed"]
    assert on["publish_gate"]["issues"] == off["publish_gate"]["issues"]
    assert on_agent._final_audit_integrity_issues(on) == off["hard_issues"]
    # Apart from the new record (and the run's own id, time and forecast seal) the audit is the knob-off one.
    volatile = {"verified_figures", "report_id", "audited_at", "forecast_sha256"}
    assert {k: v for k, v in on.items() if k not in volatile} == {k: v for k, v in off.items() if k not in volatile}

    # The counts and the block fingerprint, in final_audit.json and forecast.json (kept by the gate).
    summary = on["verified_figures"]
    assert summary["counts"] == {"matched": 1, "conflict": 1, "ambiguous": 0, "states_unverified": 1,
                                 "market_conflict": 0, "threshold_or_probability": 0, "unmatched": 0}
    assert summary["block_sha256"] == on_agent._verified_figures["sha256"] and summary["source_discrepancies"] == 1
    assert on_forecast["quality"]["verified_figures"] == summary
    assert json.loads((on_folder / "final_audit.json").read_text())["verified_figures"] == summary
    assert "verified_figures" not in off and "verified_figures" not in off_forecast["quality"]

    # figure_provenance.json: each block row, its source and the lines that use it; market stamps.
    provenance = json.loads((on_folder / "figure_provenance.json").read_text(encoding="utf-8"))
    assert provenance["schema"] == "drf.figure_provenance/v1"
    assert provenance["block_sha256"] == summary["block_sha256"]
    assert provenance["markdown_sha256"] == hashlib.sha256(MD.encode("utf-8")).hexdigest()
    (row,) = provenance["rows"]
    assert (row["row_index"], row["metric"], row["value"], row["unit"], row["source_ref"], row["source_title"],
            row["source_url"], row["verification"]) == (
        0, "Data-centre electricity share", "24.6", "%", "S1", "Energy agency annual review",
        "https://agency.example/review", "verified")
    assert row["used_in"] == [{"line": 3, "excerpt": "The data-centre electricity share was 24.6% in 2025 [S1]."}]
    assert provenance["market_rows"] == [{"market_id": "m1", "implied_yes_prob": 0.2,
                                          "quoted_at": "2026-06-29T10:00:00+00:00", "price_at_research": 0.25,
                                          "snapshot_as_of": "2026-06-29T09:00:00+00:00",
                                          "price_time": "2026-06-29T10:00:00+00:00", "price_time_basis": "requote"}]
    assert [(d["tag"], d["claim"], d["row_value"]) for d in provenance["source_discrepancies"]] == [
        ("S2", "31%", "24.6")]
    assert provenance["unmatched_numeric_claims"] == 0
    # The per-figure examples, for the manual precision review that would gate any enforcement.
    assert provenance["counts"] == summary["counts"]
    assert [(e["kind"], e["line"], e["figure"], e["cited"], e["row_index"]) for e in provenance["examples"]] == [
        ("conflict", 5, "31%", "S2", 0), ("states_unverified", 7, "40 months", None, None)]
    assert not (off_folder / "figure_provenance.json").exists()


def test_market_price_time_follows_its_knob_and_the_row(tmp_path, monkeypatch):
    monkeypatch.setattr(Config, "MARKET_ANCHOR_PRICE_TIME", False, raising=False)
    folder, *_ = _audit(tmp_path, monkeypatch, "r_no_price_time", knob=True)
    (market,) = json.loads((folder / "figure_provenance.json").read_text(encoding="utf-8"))["market_rows"]
    assert (market["quoted_at"], market["price_time"], market["price_time_basis"]) == (
        "2026-06-29T10:00:00+00:00", None, None)
    monkeypatch.setattr(Config, "MARKET_ANCHOR_PRICE_TIME", True, raising=False)
    agent = _agent()
    agent._prediction_markets = [{"market_id": "m9", "snapshot_as_of": "2026-06-29T09:00:00+00:00"}, "junk"]
    agent._write_figure_provenance("r_no_price_time", SimpleNamespace(markdown_content=MD))
    (market,) = json.loads((folder / "figure_provenance.json").read_text(encoding="utf-8"))["market_rows"]
    assert market == {"market_id": "m9", "implied_yes_prob": None, "quoted_at": None, "price_at_research": None,
                      "snapshot_as_of": "2026-06-29T09:00:00+00:00", "price_time": "2026-06-29T09:00:00+00:00",
                      "price_time_basis": "snapshot"}


def test_untagged_row_keeps_its_source_title_and_url(tmp_path, monkeypatch):
    untagged = [dict(_QUANT[0], source_ref=None), _QUANT[1]]
    folder, agent, *_ = _audit(tmp_path, monkeypatch, "r_untagged", knob=True, quantitative=untagged)
    (row,) = json.loads((folder / "figure_provenance.json").read_text(encoding="utf-8"))["rows"]
    assert (row["source_ref"], row["source_title"], row["source_url"]) == (
        None, "Energy agency annual review", "https://agency.example/review")
    # The rendered block is unchanged by the unrendered provenance fields.
    assert "source_url" not in agent._verified_figures["rendered"]
    assert agent._verified_figures["rows"][0]["source"] == "Energy agency annual review"


def test_empty_block_writes_nothing(tmp_path, monkeypatch):
    folder, _, _, audit, forecast = _audit(tmp_path, monkeypatch, "r_legacy", knob=True, labelled=False)
    assert "verified_figures" not in audit and "verified_figures" not in forecast["quality"]
    assert not (folder / "figure_provenance.json").exists()


@pytest.mark.parametrize("why", ["empty_block", "knob_off", "check_raises"])
def test_unmeasured_final_audit_drops_stale_draft_values_and_sidecar(tmp_path, monkeypatch, why):
    """A final audit that measured nothing must not re-seal the draft's counts, nor leave a
    figure_provenance.json describing other bytes."""
    if why == "check_raises":
        def boom(self, md):
            raise RuntimeError("check failed")

        monkeypatch.setattr(ReportAgent, "_verified_figures_check", boom)
    stale = {"counts": {"conflict": 99}, "block_sha256": "old", "source_discrepancies": 0}
    seeded = dict(_forecast(), quality={"verified_figures": stale})
    folder, _, _, audit, forecast = _audit(
        tmp_path, monkeypatch, f"r_stale_{why}", knob=why != "knob_off", labelled=why != "empty_block",
        forecast=seeded, stale_sidecar=True)
    assert "verified_figures" not in audit and "verified_figures" not in forecast["quality"]
    assert "verified_figures" not in json.loads((folder / "final_audit.json").read_text(encoding="utf-8"))
    assert not (folder / "figure_provenance.json").exists()


def test_failures_degrade_to_nothing(tmp_path, monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("checker failed")

    monkeypatch.setattr(vf, "check_verified_figures", boom)
    folder, _, report, audit, forecast = _audit(tmp_path, monkeypatch, "r_boom", knob=True)
    assert report.markdown_content == MD and "verified_figures" not in audit
    assert not (folder / "figure_provenance.json").exists()


def _finalize(tmp_path, monkeypatch, report_id, *, knob):
    """forecast.json as _finalize_structured_forecast writes it for MD (offline: the spine is
    pinned, so nothing is extracted, critiqued or drawn)."""
    monkeypatch.setattr(Config, "REPORT_VERIFIED_FIGURES_CHECK", knob, raising=False)
    monkeypatch.setattr(Config, "UPLOAD_FOLDER", str(tmp_path), raising=False)
    monkeypatch.setattr(ReportManager, "REPORTS_DIR", str(tmp_path / "reports"), raising=False)
    monkeypatch.setattr(Config, "FORECAST_LEDGER_DIR", str(tmp_path / "ledger"), raising=False)
    for name in ("REPORT_REPAIR_PASSES", "REPORT_FORECAST_SELF_CRITIQUE", "FORECAST_EMIT_BINARY",
                 "PREDICTION_MARKETS_ENABLED"):
        monkeypatch.setattr(Config, name, False, raising=False)
    agent = _agent()
    for key, value in {
        "graph_id": "g1", "simulation_id": "sim1", "llm": FakeLLMClient(),
        "simulation_requirement": "Will the data-centre electricity share exceed 30% by 2030?",
        "situation_brief": "", "actors": None, "scenario_label": "", "base_simulation_id": None,
        "_background_block": "", "_sources_index": "", "_signal_pack": "", "_market_pack": "",
        "_forecast_spine": _forecast(), "_forecast_spine_block": "", "_retrieval_query": None,
        "_outline_degraded": False, "_section_tool_calls": 0, "report_logger": None, "console_logger": None,
        "tools": {},
    }.items():
        setattr(agent, key, value)
    agent._finalize_structured_forecast(report_id, MD)
    path = tmp_path / "reports" / report_id / "forecast.json"
    return agent, json.loads(path.read_text(encoding="utf-8"))


def test_finalize_records_the_draft_counts_and_changes_nothing_else(tmp_path, monkeypatch):
    agent, on = _finalize(tmp_path, monkeypatch, "r_final_on", knob=True)
    expected = ReportAgent._verified_figures_summary(agent._verified_figures_check(MD))
    _, off = _finalize(tmp_path, monkeypatch, "r_final_off", knob=False)
    summary = on["quality"].pop("verified_figures")
    assert summary == expected
    assert summary["counts"]["conflict"] == 1 and summary["block_sha256"] == agent._verified_figures["sha256"]
    # Knob off: no key, and everything else is what the knob-on run wrote.
    assert "verified_figures" not in off["quality"]
    assert json.dumps(on, sort_keys=True) == json.dumps(off, sort_keys=True)


def test_finalize_survives_a_failing_check(tmp_path, monkeypatch):
    def boom(self, md):
        raise RuntimeError("check failed")

    monkeypatch.setattr(ReportAgent, "_verified_figures_check", boom)
    _, forecast = _finalize(tmp_path, monkeypatch, "r_final_boom", knob=True)
    assert forecast["scenarios"] and "verified_figures" not in forecast["quality"]


def test_generate_writes_the_sidecar_between_the_final_audit_and_the_translation():
    generate = inspect.getsource(ReportAgent.generate_report)
    assert generate.index("self._enforce_final_publish_audit(report_id, report)") \
        < generate.index("self._write_figure_provenance(report_id, report)") \
        < generate.index("self._generate_bilingual_report(report_id, report)")


def test_knob_defaults_range_and_documentation():
    assert Config.REPORT_VERIFIED_FIGURES_CHECK is True
    assert Config.REPORT_VERIFIED_FIGURE_REL_TOL == pytest.approx(0.02)
    assert "REPORT_VERIFIED_FIGURE_REL_TOL" in RANGE_RULES
    env = open(os.path.join(os.path.dirname(__file__), "..", "..", ".env.example"), encoding="utf-8").read()
    assert "# REPORT_VERIFIED_FIGURES_CHECK=true" in env and "# REPORT_VERIFIED_FIGURE_REL_TOL=0.02" in env


def test_block_sha_matches_rendered_block():
    agent = _agent()
    assert agent._verified_figures["sha256"] == hashlib.sha256(
        agent._verified_figures["rendered"].encode("utf-8")).hexdigest()
