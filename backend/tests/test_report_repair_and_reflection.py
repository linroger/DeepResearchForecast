"""Offline tests for RQ-2 report repair passes + RQ-5 per-section reflection.

No LLM/network for the repair passes (deterministic string surgery); a scripted
fake-LLM (`.chat` / `.chat_json`) for the reflection + language-purity paths — the
same __new__ + attribute-injection harness the other report tests use.

Covers:
  * RQ-2 citation backfill: uncited quant line whose number appears in a source →
    [S{i}] appended; coverage re-audited; forecast['quality']['repair'] recorded (merged).
  * RQ-2 quote grounding: ungrounded blockquote removed; cited/labeled quotes kept.
  * RQ-2 placeholder resolution: literal [S?-a]/【S?】/[S#] removed (multi-source) or
    resolved to [S1] (single source).
  * RQ-2 _run_repair_passes end-to-end: before/after recorded, existing quality keys merged.
  * RQ-2 language purity: CJK run in an English-target report translated inline;
    blockquotes do not re-inject the source-language impurity; disabled/empty → no-op.
  * RQ-5 reflection gating: PASS → draft unchanged (1 critique call); revision
    instruction → revised draft adopted; invalid revision → original kept; disabled /
    MAX_REFLECTION_ROUNDS<=0 / contaminated draft → skipped (no LLM calls); wired into
    _generate_section_with_retry.
"""

import logging
import os
import sys
from contextlib import contextmanager

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.config import Config  # noqa: E402
from app.services.report_agent import (  # noqa: E402
    ReportAgent, ReportManager, ReportOutline, ReportSection, MIN_VALID_SECTION_CHARS,
)


# ─────────────────────────────── helpers ────────────────────────────────
def _repair_agent(**over):
    """Bare agent with just the attrs the repair passes + audits touch."""
    a = ReportAgent.__new__(ReportAgent)
    a.sources = []
    a.research_report = ""
    a.situation_brief = ""
    a._background_block = ""
    a._outline_summary = ""
    a.output_language = "English"
    for k, v in over.items():
        setattr(a, k, v)
    return a


class _ChatLLM:
    """Scripted `.chat` recording every call; returns responses in order (last repeats)."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def chat(self, messages=None, temperature=0.7, max_tokens=4096, tier="strong", **kw):
        self.calls.append({"messages": messages, "temperature": temperature,
                           "max_tokens": max_tokens, "tier": tier})
        return self.responses[min(len(self.calls) - 1, len(self.responses) - 1)]


class _JsonChatLLM:
    """Scripted `.chat_json` for the language-purity batch-translation path."""

    def __init__(self, mapping):
        self.mapping = mapping
        self.calls = []

    def chat_json(self, messages=None, temperature=0.3, max_tokens=4096, tier="strong", **kw):
        self.calls.append({"messages": messages, "tier": tier})
        return dict(self.mapping)


@contextmanager
def _capture_report_agent_logs():
    """Collect 'mirofish.report_agent' messages (its logger has propagate=False,
    so pytest's caplog never sees them — attach a probe handler directly)."""

    class _Probe(logging.Handler):
        def __init__(self):
            super().__init__()
            self.messages = []

        def emit(self, record):
            self.messages.append(record.getMessage())

    probe = _Probe()
    target = logging.getLogger("mirofish.report_agent")
    target.addHandler(probe)
    try:
        yield probe.messages
    finally:
        target.removeHandler(probe)


_LONG = "This is a sufficiently long English body paragraph with real analysis. " * 20  # >800 chars


# ─────────────────────────── RQ-2 citation backfill ─────────────────────────
def test_repair_citation_backfill_appends_matching_source_tag():
    a = _repair_agent(sources=[{"title": "Trade dossier",
                                "url": "https://example.com/trade-dossier",
                                "content": "export volume rose 37% through 2027"}])
    md = "# Title\n\nExport volume rose 37% by mid-year and held.\n"
    new_md, n = a._repair_citation_backfill(md)
    assert n == 1
    assert "[S1]" in new_md
    # heading + already-cited lines are never touched
    md2 = "# 37% headline\n\nGrowth of 37% here already cited [S2].\n"
    _, n2 = a._repair_citation_backfill(md2)
    assert n2 == 0


def test_repair_citation_backfill_no_match_no_insert():
    a = _repair_agent(sources=[{"title": "Unrelated", "content": "nothing numeric here"}])
    md = "Revenue hit 99% penetration last quarter.\n"
    new_md, n = a._repair_citation_backfill(md)
    assert n == 0 and new_md == md


def test_repair_citation_backfill_calendar_year_alone_never_matches():
    a = _repair_agent(sources=[{"title": "Unrelated", "content": "published in 2027"}])
    md = "Revenue accelerated in 2027 across several markets.\n"
    new_md, n = a._repair_citation_backfill(md)
    assert n == 0 and new_md == md


def test_final_quantitative_grounding_preserves_forecasts_and_removes_false_precision(
    monkeypatch,
):
    monkeypatch.setattr(
        Config, "REPORT_PUBLISH_GATE_MIN_COVERAGE", 0.75, raising=False
    )
    source = {
        "title": "Official battery adoption report",
        "url": "https://example.gov/battery-adoption",
        "supports": ["Official battery adoption reached 55.6% in 2025."],
    }
    a = _repair_agent(sources=[source], _citation_index={"S1": source})
    md = (
        "# Forecast\n\n"
        "## Part 1 — Binary Forecasts\n\n"
        "| F1 | Authored outcome | 72% | Resolve above 40% by 2030 |\n\n"
        "## Part 2 — Framework & Synthesis\n\n"
        "Official battery adoption reached 55.6% in 2025.\n\n"
        "Unsupported lunar adoption reached 99% in 2027. "
        "The competitive mechanism remains material.\n\n"
        "## How to Verify This Forecast (Resolution Criteria & Indicators)\n\n"
        "Resolve the authored scenario at a 90% threshold by 2035.\n"
    )

    repaired, info = a._repair_final_quantitative_grounding(md)

    assert info["applied"] is True
    assert info["passed"] is True
    assert info["citations_added"] == 1
    assert info["sentences_removed"] == 1
    assert info["after"]["resolved_coverage"] == 1.0
    assert info["after"]["excluded_authored_forecast_claims"] == 3
    assert "Official battery adoption reached 55.6% in 2025. [S1]" in repaired
    assert "Unsupported lunar adoption" not in repaired
    assert "The competitive mechanism remains material." in repaired
    assert "| F1 | Authored outcome | 72% | Resolve above 40% by 2030 |" in repaired
    assert "90% threshold by 2035" in repaired


def test_final_quantitative_grounding_repairs_mixed_claims_and_preserves_table_shape(
    monkeypatch,
):
    monkeypatch.setattr(
        Config, "REPORT_PUBLISH_GATE_MIN_COVERAGE", 0.75, raising=False
    )
    source = {
        "title": "Official battery adoption report",
        "url": "https://example.gov/battery-adoption",
        "supports": ["Official battery adoption reached 55.6% in 2025."],
    }
    a = _repair_agent(sources=[source], _citation_index={"S1": source})
    md = (
        "# Evidence\n\n"
        "Official battery adoption reached 55.6% in 2025 [S1]. "
        "Unsupported lunar adoption reached 99% in 2027.\n\n"
        "| Metric | 2025 actual | 2026 forecast |\n"
        "|---|---:|---:|\n"
        "| Battery adoption | 55.6% | 99% |\n"
    )

    repaired, info = a._repair_final_quantitative_grounding(md)

    assert info["passed"] is True
    assert info["after"]["resolved_coverage"] == 1.0
    assert "Unsupported lunar adoption" not in repaired
    assert "| Metric | 2025 actual | 2026 forecast |" in repaired
    assert "|---|---:|---:|" in repaired
    assert "55.6% [S1]" in repaired
    assert "| Battery adoption | 55.6% [S1] | — |" in repaired
    semantically_repaired, semantic_info = a._repair_semantic_citations(repaired)
    assert "55.6% [S1]" in semantically_repaired
    assert semantic_info["stripped"] == 0
    assert a._audit_semantic_citations(
        semantically_repaired, a._citation_index_or_fallback()
    )["unsupported"] == 0


def test_final_quantitative_grounding_requires_matching_fence_delimiters(monkeypatch):
    monkeypatch.setattr(
        Config, "REPORT_PUBLISH_GATE_MIN_COVERAGE", 0.75, raising=False
    )
    a = _repair_agent()
    md = (
        "```text\n"
        "Inside code reached 99%.\n"
        "~~~\n"
        "Still inside code reached 88%.\n"
        "```\n"
        "Outside unsupported evidence reached 77%.\n"
    )

    repaired, info = a._repair_final_quantitative_grounding(md)

    assert "Inside code reached 99%." in repaired
    assert "Still inside code reached 88%." in repaired
    assert "Outside unsupported evidence" not in repaired
    assert info["passed"] is True


def test_final_quantitative_grounding_supports_exact_chinese_evidence(monkeypatch):
    monkeypatch.setattr(
        Config, "REPORT_PUBLISH_GATE_MIN_COVERAGE", 0.75, raising=False
    )
    source = {
        "title": "官方新能源汽车报告",
        "url": "https://example.gov.cn/ev-report",
        "supports": ["中国电动车销量在2025年达到55.6%。"],
    }
    a = _repair_agent(
        output_language="Chinese",
        sources=[source],
        _citation_index={"S1": source},
    )

    repaired, info = a._repair_final_quantitative_grounding(
        "中国电动车销量在2025年达到55.6%。\n"
    )

    assert "中国电动车销量在2025年达到55.6%。 [S1]" in repaired
    assert info["citations_added"] == 1
    assert info["passed"] is True


def test_chinese_han_adjacent_numeric_mismatch_never_gets_citation(monkeypatch):
    monkeypatch.setattr(
        Config, "REPORT_PUBLISH_GATE_MIN_COVERAGE", 0.75, raising=False
    )
    source = {
        "title": "官方新能源汽车报告",
        "url": "https://example.gov.cn/ev-report-mismatch",
        "supports": ["中国电动车销量在2025年达到12.3%。"],
    }
    a = _repair_agent(
        output_language="Chinese",
        sources=[source],
        _citation_index={"S1": source},
    )
    claim = "中国电动车销量在2025年达到55.6%。"

    assert a._semantic_citation_support(claim, source) is False
    repaired, info = a._repair_final_quantitative_grounding(claim + "\n")

    assert "[S1]" not in repaired
    assert claim not in repaired
    assert info["citations_added"] == 0
    assert info["passed"] is True


def test_final_quantitative_grounding_preserves_cross_language_unverifiable_claim(
    monkeypatch,
):
    monkeypatch.setattr(
        Config, "REPORT_PUBLISH_GATE_MIN_COVERAGE", 0.75, raising=False
    )
    source = {
        "title": "Official EV report",
        "url": "https://example.gov/ev-report",
        "supports": ["Electric vehicle registrations reached 55.6% in 2025."],
    }
    a = _repair_agent(
        output_language="Chinese",
        sources=[source],
        _citation_index={"S1": source},
    )
    claim = "中国电动车销量在2025年达到55.6%。"

    repaired, info = a._repair_final_quantitative_grounding(claim + "\n")

    # Cross-language lexical verification is inconclusive. Preserve the claim
    # uncited so the unchanged publication gate fails honestly; do not censor it.
    assert claim in repaired
    assert "[S1]" not in repaired
    assert info["passed"] is False
    assert info["unverifiable_claims_preserved"] == 1


def test_chinese_near_match_does_not_confuse_sales_with_production(monkeypatch):
    monkeypatch.setattr(
        Config, "REPORT_PUBLISH_GATE_MIN_COVERAGE", 0.75, raising=False
    )
    source = {
        "title": "官方新能源汽车报告",
        "url": "https://example.gov.cn/ev-production",
        "supports": ["中国电动车产量在2025年达到55.6%。"],
    }
    a = _repair_agent(
        output_language="Chinese",
        sources=[source],
        _citation_index={"S1": source},
    )
    claim = "中国电动车销量在2025年达到55.6%。"

    repaired, info = a._repair_final_quantitative_grounding(claim + "\n")

    assert claim in repaired
    assert "[S1]" not in repaired
    assert info["passed"] is False
    assert info["unverifiable_claims_preserved"] == 1


def test_semantic_citation_support_removes_the_complete_multi_digit_tag():
    source = {
        "title": "IEA Global EV Outlook 2026 Webinar",
        "url": "https://example.org/iea-global-ev-outlook-2026",
        "supports": ["Global EV adoption outlook scenarios for 2026–2035."],
    }
    a = _repair_agent(sources=[source], _citation_index={"S26": source})
    md = "Global EV adoption outlook scenarios for 2026–2035 [S26].\n"

    repaired, info = a._repair_semantic_citations(md)

    assert repaired == md
    assert info["kept"] == 1
    assert info["stripped"] == 0


def test_table_context_does_not_confuse_sales_with_production(monkeypatch):
    monkeypatch.setattr(
        Config, "REPORT_PUBLISH_GATE_MIN_COVERAGE", 0.75, raising=False
    )
    source = {
        "title": "Official battery production report",
        "url": "https://example.gov/battery-production",
        "supports": ["Battery production reached 55.6% in 2025."],
    }
    a = _repair_agent(sources=[source], _citation_index={"S1": source})
    md = (
        "| Metric | 2025 actual |\n"
        "|---|---:|\n"
        "| Battery sales | 55.6% |\n"
    )

    repaired, info = a._repair_final_quantitative_grounding(md)

    assert "[S1]" not in repaired
    assert "| Battery sales | — |" in repaired
    assert info["table_cells_cleared"] == 1
    assert info["passed"] is True


def test_table_header_words_cannot_override_contradictory_row_label(monkeypatch):
    monkeypatch.setattr(
        Config, "REPORT_PUBLISH_GATE_MIN_COVERAGE", 0.75, raising=False
    )
    source = {
        "title": "Earth battery adoption report",
        "url": "https://example.gov/earth-battery-adoption",
        "supports": ["Earth battery adoption reached 55.6% in 2025."],
    }
    a = _repair_agent(sources=[source], _citation_index={"S1": source})
    md = (
        "| Region | 2025 battery adoption |\n"
        "|---|---:|\n"
        "| Moon | 55.6% |\n"
    )

    repaired, info = a._repair_final_quantitative_grounding(md)

    assert "[S1]" not in repaired
    assert "| Moon | 55.6% |" in repaired
    assert info["unverifiable_claims_preserved"] == 1
    assert info["passed"] is False


def test_table_without_outer_pipes_preserves_shape_and_repairs_cells(monkeypatch):
    monkeypatch.setattr(
        Config, "REPORT_PUBLISH_GATE_MIN_COVERAGE", 0.75, raising=False
    )
    source = {
        "title": "Official battery adoption report",
        "url": "https://example.gov/battery-adoption",
        "supports": ["Battery adoption reached 55.6% in 2025."],
    }
    a = _repair_agent(sources=[source], _citation_index={"S1": source})
    md = (
        "Metric | 2025 actual | 2026 forecast\n"
        "--- | ---: | ---:\n"
        "Battery adoption | 55.6% | 99%\n"
    )

    repaired, info = a._repair_final_quantitative_grounding(md)

    assert "Metric | 2025 actual | 2026 forecast" in repaired
    assert "--- | ---: | ---:" in repaired
    assert "Battery adoption | 55.6% [S1] | —" in repaired
    assert info["passed"] is True


@pytest.mark.parametrize(
    "md",
    [
        "Earth adoption reached 55.6% [S1];Moon adoption reached 99% [S1].\n",
        "地球采用率在2025年达到55.6%[S1]；月球采用率在2025年达到99%[S1]。\n",
    ],
)
def test_unspaced_semicolon_keeps_semantic_citation_ownership_separate(md):
    source = {
        "title": "Earth adoption report",
        "url": "https://example.gov/earth-adoption",
        "supports": [
            "Earth adoption reached 55.6% in 2025.",
            "地球采用率在2025年达到55.6%。",
        ],
    }
    a = _repair_agent(sources=[source], _citation_index={"S1": source})

    audit = a._audit_semantic_citations(md, {"S1": source})
    repaired, info = a._repair_semantic_citations(md)

    assert audit["unsupported"] == 1
    assert audit["passed"] is False
    assert info["kept"] == 1
    assert info["stripped"] == 1
    assert repaired.count("[S1]") == 1
    assert "99% ." not in repaired


def test_repair_citation_backfill_ambiguous_evidence_tie_stays_uncited():
    a = _repair_agent(sources=[
        {"title": "Survey A", "content": "regional adoption penetration reached 42%"},
        {"title": "Survey B", "content": "regional adoption penetration reached 42%"},
    ])
    md = "Regional adoption penetration reached 42% this cycle.\n"
    new_md, n = a._repair_citation_backfill(md)
    assert n == 0 and new_md == md


# ──────────────────────────── RQ-2 quote grounding ──────────────────────────
def test_repair_quote_grounding_removes_only_ungrounded():
    a = _repair_agent(research_report="The GDP grew steadily according to the ministry report.")
    md = (
        "# T\n\n"
        "> The GDP grew steadily according to the ministry report.\n\n"   # grounded → kept
        "> Aliens seized the harbor in Tokyo overnight without warning.\n\n"  # ungrounded → removed
        "> A simulated agent predicted a collapse of the coalition soon.\n"   # sim-labeled → kept
    )
    new_md, removed = a._repair_quote_grounding(md)
    assert removed == 1
    assert "ministry report" in new_md
    assert "simulated agent" in new_md
    assert "Aliens seized the harbor" not in new_md


def test_repair_quote_grounding_dequotes_cited_paraphrase():
    a = _repair_agent(research_report="irrelevant grounding corpus")
    md = "> An unmatched but properly sourced statement here [S3].\n"
    new_md, removed = a._repair_quote_grounding(md)
    assert removed == 0
    assert new_md == "An unmatched but properly sourced statement here [S3]."


# ───────────────────────── RQ-2 placeholder resolution ──────────────────────
def test_repair_placeholder_tokens_removed_multi_source():
    a = _repair_agent(sources=[{"title": "a"}, {"title": "b"}])
    md = "Growth was strong [S?-a] and steady 【S?】 plus [S#] overall.\n"
    new_md, n = a._repair_placeholder_tokens(md)
    assert n == 3
    assert "[S?" not in new_md and "【S?】" not in new_md and "[S#]" not in new_md


def test_repair_placeholder_tokens_resolved_single_source():
    a = _repair_agent(sources=[{"title": "only"}])
    md = "Momentum held [S?-a] into Q4.\n"
    new_md, n = a._repair_placeholder_tokens(md)
    assert n == 1 and "[S1]" in new_md and "[S?" not in new_md


# ───────────────────────── RQ-2 _run_repair_passes E2E ──────────────────────
def test_run_repair_passes_records_before_after_and_merges(monkeypatch):
    monkeypatch.setattr(Config, "REPORT_PUBLISH_GATE_MIN_COVERAGE", 0.5, raising=False)
    a = _repair_agent(sources=[{
        "title": "src",
        "url": "https://example.com/regional-adoption",
        "content": "regional adoption penetration reached 42% in 2027",
    }])
    md = "# T\n\nRegional adoption penetration reached 42% this cycle.\n"
    forecast = {
        "citation_audit": {"coverage": 0.0, "quantitative_claims": 1},
        # pre-existing audit finding must survive the merge (never overwrite)
        "quality": {"numeric_consistency": {"mismatch_count": 2}},
    }
    new_md = a._run_repair_passes("rid_x", forecast, md, report=None)
    assert "[S1]" in new_md
    rep = forecast["quality"]["repair"]
    assert rep["applied"] is True
    assert rep["before"]["citation_coverage"] == 0.0
    assert rep["after"]["citation_coverage"] == 1.0
    assert any(p["dimension"] == "citation_backfill" for p in rep["passes"])
    # forecast.citation_audit was re-run on the repaired markdown
    assert forecast["citation_audit"]["coverage"] == 1.0
    # existing quality key preserved (merge, not overwrite)
    assert forecast["quality"]["numeric_consistency"] == {"mismatch_count": 2}


def test_run_repair_passes_noop_when_no_dimension_fails():
    a = _repair_agent()
    md = "# T\n\nNothing to fix here.\n"
    forecast = {"citation_audit": {"coverage": 1.0, "quantitative_claims": 0}, "quality": {}}
    out = a._run_repair_passes("rid_y", forecast, md, report=None)
    assert out == md
    assert "repair" not in forecast["quality"]  # untouched


# ─────────────────────────── RQ-2 language purity ───────────────────────────
def test_language_purity_translates_cjk_in_english_report(monkeypatch, tmp_path):
    monkeypatch.setattr(Config, "REPORT_LANGUAGE_PURITY", True, raising=False)
    monkeypatch.setattr(Config, "UPLOAD_FOLDER", str(tmp_path), raising=False)
    monkeypatch.setattr(ReportManager, "REPORTS_DIR", str(tmp_path / "reports"), raising=False)
    llm = _JsonChatLLM({"1": "market sentiment", "2": "supply chain shifted"})
    a = _repair_agent(output_language="English", llm=llm)

    class _Rep:
        markdown_content = (
            "# Title\n\n"
            "Analysts weigh 市场情绪 heading into Q3.\n\n"
            "> The 供应链转移 reshaped the sector.\n"
        )

    rep = _Rep()
    # full_report.md write is best-effort (wrapped in try/except); missing folder is tolerated.
    a._apply_language_purity("rid_lp", rep)
    md = rep.markdown_content
    assert "市场情绪" not in md              # prose CJK translated inline (replaced)
    assert "market sentiment" in md
    # A language-purity pass must not deliberately re-inject the original CJK in
    # parentheses, even inside a blockquote.
    assert "supply chain shifted" in md and "供应链转移" not in md
    assert llm.calls and llm.calls[0]["tier"] == "fast"


def test_language_purity_batches_large_residual_set(monkeypatch, tmp_path):
    monkeypatch.setattr(Config, "REPORT_LANGUAGE_PURITY", True, raising=False)
    monkeypatch.setattr(
        Config, "REPORT_PURITY_RETRANSLATE_SEGMENTS", 100, raising=False
    )
    monkeypatch.setattr(
        Config, "REPORT_PURITY_TRANSLATION_BATCH_SIZE", 20, raising=False
    )
    monkeypatch.setattr(ReportManager, "REPORTS_DIR", str(tmp_path / "reports"), raising=False)

    class _BatchLLM:
        """chat_json-only provider honoring the placeholder contract.

        Each numbered input line carries the segment's ⟦…⟧ number placeholder;
        a contract-valid translation copies it verbatim, so the restored
        candidate keeps the source number multiset and the BATCH path accepts
        it. The stub deliberately has no ``.chat``: per COST-1(a) escalation is
        guard-skipped for such providers, so batching alone must repair purity
        (pre-COST-1 the old stub's digit-corrupted translations were rejected,
        all 25 segments escalated, and 25 AttributeErrors were swallowed).
        """

        def __init__(self):
            self.calls = []

        def chat_json(self, messages=None, **kwargs):
            self.calls.append(messages)
            out = {}
            for index, line in enumerate(messages[-1]["content"].splitlines(), 1):
                token = ""
                if "⟦" in line and "⟧" in line:
                    token = line[line.index("⟦"): line.index("⟧") + 1]
                out[str(index)] = f"translated term {token}".strip()
            return out

    llm = _BatchLLM()
    a = _repair_agent(output_language="English", llm=llm)
    body = "\n".join(f"Residual 残留术语{i} appears here." for i in range(25))
    rep = type("_Rep", (), {"markdown_content": f"# Title\n\n{body}\n"})()

    a._apply_language_purity("rid_batches", rep)

    # 25 segments / batch size 20 → exactly 2 batched chat_json calls and zero
    # per-segment strong-tier escalations (the stub has no .chat to call).
    assert len(llm.calls) == 2
    assert not a._collect_impurity_segments(rep.markdown_content, False, cap=100)
    # Placeholder-protected digits survive the round trip byte-for-byte.
    assert "translated term 0" in rep.markdown_content
    assert "translated term 24" in rep.markdown_content


# ──────────────── COST-1: purity-escalation guard / cap / short-circuit ───────────────
class _EscalationLLM:
    """chat_json resolves nothing (forcing escalation); .chat is scripted."""

    def __init__(self, chat_behavior):
        self.chat_calls = 0
        self.json_calls = 0
        self._chat_behavior = chat_behavior

    def chat_json(self, messages=None, **kwargs):
        self.json_calls += 1
        return {}

    def chat(self, messages=None, **kwargs):
        self.chat_calls += 1
        result = self._chat_behavior(self.chat_calls)
        if isinstance(result, Exception):
            raise result
        return result


def test_purity_escalation_max_default_is_twelve():
    # New knob (COST-1(b)) — nothing in .env can predate it, so the class
    # attribute reflects the shipped default directly.
    assert Config.REPORT_PURITY_ESCALATION_MAX == 12


def test_purity_escalation_skipped_without_chat_logs_once():
    """COST-1(a): no .chat → escalation skipped wholesale with ONE log line,
    not one swallowed AttributeError per segment (25 pre-fix)."""

    class _JsonOnly:
        def chat_json(self, messages=None, **kwargs):
            return {}

    a = _repair_agent(llm=_JsonOnly())
    segments = [f"残留片段{i}" for i in range(5)]
    with _capture_report_agent_logs() as messages:
        mapping = a._translate_impurity_segments(segments, "English")
    assert mapping == []
    skip_lines = [m for m in messages if "无 chat 接口" in m]
    assert len(skip_lines) == 1 and "5" in skip_lines[0]
    assert not any("单片段翻译调用失败" in m for m in messages)


def test_purity_escalation_capped_per_report(monkeypatch):
    """COST-1(b): at most REPORT_PURITY_ESCALATION_MAX strong-tier calls per
    report; validation rejects do NOT count toward the outage short-circuit."""
    monkeypatch.setattr(Config, "REPORT_PURITY_ESCALATION_MAX", 4, raising=False)
    llm = _EscalationLLM(lambda n: "")  # every call completes but is rejected
    a = _repair_agent(llm=llm)
    segments = [f"残留片段{i}" for i in range(10)]
    with _capture_report_agent_logs() as messages:
        mapping = a._translate_impurity_segments(segments, "English")
    assert mapping == []
    assert llm.chat_calls == 4  # > 3 rejects in a row, yet no short-circuit
    assert any("达到上限" in m for m in messages)


def test_purity_escalation_short_circuits_after_three_consecutive_failures():
    """COST-1(c): 3 consecutive escalation-call exceptions ⇒ provider-down,
    stop escalating for this report (default cap 12 would otherwise allow more)."""
    llm = _EscalationLLM(lambda n: RuntimeError("provider down"))
    a = _repair_agent(llm=llm)
    segments = [f"残留片段{i}" for i in range(10)]
    with _capture_report_agent_logs() as messages:
        mapping = a._translate_impurity_segments(segments, "English")
    assert mapping == []
    assert llm.chat_calls == 3
    assert any("判定提供方故障" in m for m in messages)


def test_purity_escalation_failure_streak_resets_on_success():
    """Only CONSECUTIVE call failures short-circuit: a completed call (even if
    its candidate is rejected by validation) resets the streak."""
    llm = _EscalationLLM(
        lambda n: RuntimeError("blip") if n % 3 else ""  # fail, fail, complete, …
    )
    a = _repair_agent(llm=llm)
    segments = [f"残留片段{i}" for i in range(10)]
    mapping = a._translate_impurity_segments(segments, "English")
    assert mapping == []
    assert llm.chat_calls == 10  # never 3 consecutive failures → cap(12) not hit


def test_purity_number_folding_accepts_reformat_rejects_corruption():
    """COST-1(d): value-preserving number reformatting (full-width digits,
    thousands separators) is accepted by the batch path; digit-content changes
    are still rejected. The strict multiset (bilingual path) stays strict."""
    # (1) Full-width digits in a CJK segment, English translation with ASCII digits.
    seg_fullwidth = "市场共有１０００家企业"
    good_en = "the market has 1000 companies"
    # Pre-COST-1 the strict multiset rejected exactly this legitimate pair:
    assert ReportAgent._translation_number_multiset(seg_fullwidth) \
        != ReportAgent._translation_number_multiset(good_en)
    a = _repair_agent(llm=_JsonChatLLM({"1": good_en}))
    mapping = a._translate_impurity_segments([seg_fullwidth], "English")
    assert mapping == [(seg_fullwidth, good_en)]

    # (1b) A full-width amount is one rendered token: 1000亿元 is 100 billion yuan.
    # The frozen-numeral rendering "1000 billion yuan" is ten times too large.
    seg_amount = "市场规模１０００亿元"
    a = _repair_agent(llm=_JsonChatLLM({"1": "market size totals ⟦QA⟧"}))
    assert a._translate_impurity_segments([seg_amount], "English") == [
        (seg_amount, "market size totals RMB 100 billion")
    ]
    a = _repair_agent(llm=_JsonChatLLM({"1": "market size totals 1000 billion yuan"}))
    assert a._translate_impurity_segments([seg_amount], "English") == []

    # (2) Thousands separator dropped by a legitimate Chinese rendering.
    seg_latin = "The market reached 1,000 units across all regions"
    good_zh = "市场在所有地区达到1000个单位"
    assert ReportAgent._translation_number_multiset(seg_latin) \
        != ReportAgent._translation_number_multiset(good_zh)
    a = _repair_agent(llm=_JsonChatLLM({"1": good_zh}))
    mapping = a._translate_impurity_segments([seg_latin], "简体中文")
    assert mapping == [(seg_latin, good_zh)]

    # (3) Corrupted digit content is still rejected (no .chat → no escalation).
    for bad in ("市场在所有地区达到100个单位",          # 1,000 → 100
                "市场在所有地区达到1000个单位另加50"):  # stray new number
        a = _repair_agent(llm=_JsonChatLLM({"1": bad}))
        assert a._translate_impurity_segments([seg_latin], "简体中文") == []


def test_language_purity_rescans_whole_section_translation(monkeypatch, tmp_path):
    monkeypatch.setattr(Config, "REPORT_LANGUAGE_PURITY", True, raising=False)
    monkeypatch.setattr(
        Config, "REPORT_PURITY_RETRANSLATE_SEGMENTS", 1, raising=False
    )
    monkeypatch.setattr(ReportManager, "REPORTS_DIR", str(tmp_path / "reports"), raising=False)

    class _HybridLLM:
        def __init__(self):
            self.chat_calls = 0
            self.json_calls = 0

        def chat(self, **kwargs):
            self.chat_calls += 1
            return "## Outlook\n\nMost of the section is translated. 残留词语 remains."

        def chat_json(self, **kwargs):
            self.json_calls += 1
            return {"1": "residual term"}

    llm = _HybridLLM()
    a = _repair_agent(output_language="English", llm=llm)
    rep = type(
        "_Rep",
        (),
        {"markdown_content": "## Outlook\n\n市场情绪 weakens.\n\n供应链 shifted.\n"},
    )()

    a._apply_language_purity("rid_rescan", rep)

    assert llm.chat_calls == 1
    assert llm.json_calls == 1
    assert "残留词语" not in rep.markdown_content
    assert "residual term" in rep.markdown_content


def test_language_purity_runs_one_bounded_post_batch_rescan(monkeypatch, tmp_path):
    monkeypatch.setattr(Config, "REPORT_LANGUAGE_PURITY", True, raising=False)
    monkeypatch.setattr(
        Config, "REPORT_PURITY_RETRANSLATE_SEGMENTS", 100, raising=False
    )
    monkeypatch.setattr(ReportManager, "REPORTS_DIR", str(tmp_path / "reports"), raising=False)

    class _ResidualLLM:
        def __init__(self):
            self.calls = 0

        def chat_json(self, **kwargs):
            self.calls += 1
            if self.calls == 1:
                return {"1": "still 残留"}
            return {"1": "fully translated"}

    llm = _ResidualLLM()
    a = _repair_agent(output_language="English", llm=llm)
    rep = type(
        "_Rep",
        (),
        {"markdown_content": "# Outlook\n\nThe market has 原始污染 in this line.\n"},
    )()

    a._apply_language_purity("rid_second_scan", rep)

    assert llm.calls == 2
    assert "fully translated" in rep.markdown_content
    assert not a._collect_impurity_segments(rep.markdown_content, False, cap=100)


def test_language_purity_scans_structured_markdown_and_preserves_url(
    monkeypatch, tmp_path
):
    monkeypatch.setattr(Config, "REPORT_LANGUAGE_PURITY", True, raising=False)
    monkeypatch.setattr(
        Config, "REPORT_PURITY_RETRANSLATE_SEGMENTS", 100, raising=False
    )
    monkeypatch.setattr(ReportManager, "REPORTS_DIR", str(tmp_path / "reports"), raising=False)
    url = "https://example.com/English-slug-must-remain"
    md = (
        "## This English heading contains enough prose words to require translation\n\n"
        "| Metric | This English table cell contains enough prose words to require translation |\n"
        "|---|---|\n"
        "> This English blockquote contains enough prose words to require translation.\n\n"
        "Read [this English linked passage contains enough prose words for translation]"
        f"({url}) for evidence.\n"
    )
    llm = _JsonChatLLM({
        "1": "需要翻译的中文标题",
        "2": "需要翻译的中文表格内容",
        "3": "需要翻译的中文引文内容",
        "4": "需要翻译的中文链接文字",
    })
    a = _repair_agent(output_language="Chinese", llm=llm)
    rep = type("_Rep", (), {"markdown_content": md})()

    a._apply_language_purity("rid_structured", rep)

    assert url in rep.markdown_content
    assert rep.markdown_content.startswith("## 需要翻译的中文标题")
    assert "| Metric | 需要翻译的中文表格内容 |" in rep.markdown_content
    assert "> 需要翻译的中文引文内容" in rep.markdown_content
    assert f"[需要翻译的中文链接文字]({url})" in rep.markdown_content
    assert not a._collect_impurity_segments(rep.markdown_content, True, cap=100)


def test_final_contamination_detector_includes_structured_markdown_text():
    from app.services.report_lint import detect_language_contamination

    md = (
        "## This English heading contains enough prose words to trigger detection\n"
        "| This English table cell contains enough prose words to trigger detection |\n"
        "> This English blockquote contains enough prose words to trigger detection.\n"
        "Read [this English linked passage contains enough prose words for detection]"
        "(https://example.com/keep-this-url) now.\n"
        "```text\nThis fenced English prose must remain excluded from detection.\n```\n"
    )

    audit = detect_language_contamination(md, "Chinese")

    assert audit["lines"] == 4


def test_language_detector_allows_original_titles_in_references_appendix():
    from app.services.report_lint import detect_language_contamination

    md = (
        "# 中文预测报告\n\n正文保持中文。\n\n## 参考来源\n\n"
        "1. A Very Long Original English Publication Title That Must Stay Verbatim — "
        "2026-01-01 — https://example.com/source\n"
    )

    assert detect_language_contamination(md, "Chinese")["lines"] == 0


def test_language_purity_noop_when_pure(monkeypatch):
    monkeypatch.setattr(Config, "REPORT_LANGUAGE_PURITY", True, raising=False)
    llm = _JsonChatLLM({})
    a = _repair_agent(output_language="English", llm=llm)

    class _Rep:
        markdown_content = "# Title\n\nA fully English report with no contamination.\n"

    rep = _Rep()
    before = rep.markdown_content
    a._apply_language_purity("rid_pure", rep)
    assert rep.markdown_content == before
    assert not llm.calls  # no segments → no LLM call


def test_language_purity_disabled_is_noop(monkeypatch):
    monkeypatch.setattr(Config, "REPORT_LANGUAGE_PURITY", False, raising=False)
    llm = _JsonChatLLM({"1": "x"})
    a = _repair_agent(output_language="English", llm=llm)

    class _Rep:
        markdown_content = "# T\n\n市场情绪 lingers.\n"

    rep = _Rep()
    before = rep.markdown_content
    a._apply_language_purity("rid_off", rep)
    assert rep.markdown_content == before and not llm.calls


# ─────────────────────────── RQ-5 section reflection ────────────────────────
def _reflect_agent(responses, **over):
    a = ReportAgent.__new__(ReportAgent)
    a.output_language = "English"
    a._forecast_spine = {"scenarios": [{"name": "Escalation", "probability": 0.6},
                                       {"name": "Status quo", "probability": 0.4}]}
    a._forecast_spine_block = ""
    a._signal_pack = "Top actor: Alpha; peak actions: 42"
    a.llm = _ChatLLM(responses)
    for k, v in over.items():
        setattr(a, k, v)
    return a


def _sec_outline():
    sec = ReportSection(title="Body 1", description="")
    return sec, ReportOutline(title="T", summary="S", sections=[sec])


def test_reflection_pass_keeps_draft():
    a = _reflect_agent(["PASS"])
    sec, outline = _sec_outline()
    out = a._reflect_and_maybe_revise_section(sec, outline, _LONG, previous_sections=[])
    assert out == _LONG
    assert len(a.llm.calls) == 1                      # only the critique call
    assert a.llm.calls[0]["tier"] == "fast"           # critique routed to the cheap tier


def test_reflection_revises_on_instruction():
    revised = "Revised: " + _LONG
    a = _reflect_agent(["Align the escalation probability with the spine's 60%.", revised])
    sec, outline = _sec_outline()
    out = a._reflect_and_maybe_revise_section(sec, outline, _LONG, previous_sections=[])
    assert out == revised.strip()                     # _revise_section_draft strips the response
    assert len(a.llm.calls) == 2                      # critique + one revision draw


def test_reflection_invalid_revision_keeps_original():
    a = _reflect_agent(["Fix it.", "too short"])       # revision fails validity → keep original
    sec, outline = _sec_outline()
    out = a._reflect_and_maybe_revise_section(sec, outline, _LONG, previous_sections=[])
    assert out == _LONG
    assert len(a.llm.calls) == 2


def test_reflection_disabled_skips(monkeypatch):
    monkeypatch.setattr(Config, "REPORT_SECTION_REFLECTION", False, raising=False)
    a = _reflect_agent(["PASS"])
    sec, outline = _sec_outline()
    out = a._reflect_and_maybe_revise_section(sec, outline, _LONG, previous_sections=[])
    assert out == _LONG and not a.llm.calls


def test_reflection_capped_by_max_rounds_zero():
    a = _reflect_agent(["PASS"], MAX_REFLECTION_ROUNDS=0)
    sec, outline = _sec_outline()
    out = a._reflect_and_maybe_revise_section(sec, outline, _LONG, previous_sections=[])
    assert out == _LONG and not a.llm.calls


def test_reflection_skips_contaminated_draft():
    a = _reflect_agent(["PASS"])
    sec, outline = _sec_outline()
    short = "too short to be valid"                    # < MIN_VALID_SECTION_CHARS → skip
    assert len(short) < MIN_VALID_SECTION_CHARS
    out = a._reflect_and_maybe_revise_section(sec, outline, short, previous_sections=[])
    assert out == short and not a.llm.calls


def test_reflection_wired_into_generate_section_with_retry(monkeypatch):
    monkeypatch.setattr(Config, "REPORT_SECTION_RETRY_MAX", 0, raising=False)
    monkeypatch.setattr(Config, "REPORT_SECTION_REFLECTION", True, raising=False)
    a = _reflect_agent(["PASS"])
    a._generate_section = lambda *args, **kw: _LONG    # stub the actual draft generator
    sec, outline = _sec_outline()
    out = a._generate_section_with_retry(sec, outline, previous_sections=[])
    assert out == _LONG
    assert len(a.llm.calls) == 1                       # reflection critique ran once
