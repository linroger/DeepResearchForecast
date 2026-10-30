"""Valid writer source -> real grounding -> publication -> translation.

The gold report establishes observed damage, not the historical writer's raw
reply. All reproductions below start with independently authored valid Markdown.
Run through main_offline_pytest.py in a fresh private mirror, before app imports.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import mistune
import pytest

from app.config import Config
from app.services.report_agent import Report, ReportAgent, ReportManager, ReportStatus
from test_final_publish_audit import _agent, _prepare
from model_translation_fakes import model_protocol, raw_fixture_zh


@pytest.fixture(autouse=True)
def strict_coverage(monkeypatch):
    monkeypatch.setattr(Config, "REPORT_PUBLISH_GATE", True)
    monkeypatch.setattr(Config, "REPORT_PUBLISH_GATE_MODE", "fail")
    monkeypatch.setattr(Config, "REPORT_PUBLISH_GATE_MIN_COVERAGE", 1.0)


def _record(tmp_path, source, result, info):
    (tmp_path / "grounding-proof.json").write_text(json.dumps({
        "source": source, "result": result, "diagnostics": info,
        "source_sha256": hashlib.sha256(source.encode()).hexdigest(),
        "result_sha256": hashlib.sha256(result.encode()).hexdigest(),
    }, ensure_ascii=False, indent=2))


@pytest.mark.parametrize("claim", [
    "**B1. Gold exceeds $5,000 by 31 December 2027.**",
    "**B2. Gold exceeds $5,200 by 31 December 2027.**",
    "**Central distribution (LBMA p.m. on 31 December 2027): 55%.**",
    "**Measured adoption reached 99%. The explanation remains speculative.**",
    "*Measured adoption reached 99%. The explanation remains speculative.*",
    "**Measured adoption\nreached 99%. The explanation remains speculative.**",
    "~~Measured adoption reached 99%. The explanation remains speculative.~~",
])
def test_valid_writer_inline_node_is_removed_atomically(claim, tmp_path):
    # A parsed strong/emphasis node exists before the real producer runs.
    parsed = mistune.create_markdown(renderer="ast", plugins=["strikethrough"])(claim)
    assert parsed[0]["children"][0]["type"] in {"strong", "emphasis", "strikethrough"}
    source = "# Evidence\n\n" + claim + "\n\nThe mechanism remains uncertain.\n"
    result, info = _agent()._repair_final_quantitative_grounding(source)
    _record(tmp_path, source, result, info)
    assert claim not in result
    assert "**" not in result and "*" not in result and "~~" not in result
    assert "B1." not in result and "B2." not in result
    assert "The mechanism remains uncertain." in result
    assert info["sentences_removed"] > 0
    assert info["passed"] is True
    again, _ = _agent()._repair_final_quantitative_grounding(result)
    assert again == result


@pytest.mark.parametrize("sentence", [
    "LBMA p.m. on 31 December 2027 exceeds $5,000.",
    "LBMA a.m./p.m. on 2027-12-31 exceeds $5,000.00.",
    "J.P. Morgan forecasts gold at $5,000 in 2027.",
    "The U.S. benchmark reaches 55.6% on 2027-12-31.",
])
def test_unsupported_abbreviation_sentence_leaves_no_prefix(sentence, tmp_path):
    source = "# Evidence\n\n" + sentence + " The mechanism remains uncertain.\n"
    result, info = _agent()._repair_final_quantitative_grounding(source)
    _record(tmp_path, source, result, info)
    assert result == "# Evidence\n\nThe mechanism remains uncertain.\n"
    assert info["passed"] is True


def test_labelled_authored_forecast_bold_is_preserved(tmp_path):
    source = (
        "# Forecast\n\n## Part 1 — Binary Forecasts\n\n"
        "**B1. LBMA p.m. gold exceeds $5,000.00 by 31 December 2027: 55%.**\n\n"
        "## Evidence\n\nUnsupported adoption reached 99%.\n"
    )
    result, info = _agent()._repair_final_quantitative_grounding(source)
    _record(tmp_path, source, result, info)
    assert "**B1. LBMA p.m. gold exceeds $5,000.00 by 31 December 2027: 55%.**" in result
    assert "Unsupported adoption" not in result
    assert info["passed"] is True


def test_cited_decimals_dates_and_table_survive_without_reserialization(tmp_path):
    source = (
        "# Evidence\n\nOfficial battery adoption reached **55.6%** in 2025. [S1] "
        "Unsupported adoption reached 99%.\n\n"
        "| Metric | Value | Note |\n|---|---:|---|\n"
        "| Battery adoption | **55.6%** [S1] | lunar adoption reached **99%.** |\n"
    )
    agent = _agent({"title": "Battery adoption", "url": "https://example.gov/adoption",
                    "supports": ["Official battery adoption reached 55.6% in 2025."]})
    result, info = agent._repair_final_quantitative_grounding(source)
    _record(tmp_path, source, result, info)
    assert "Official battery adoption reached **55.6%** in 2025. [S1]" in result
    assert "99" not in result
    assert "| Battery adoption | **55.6%** [S1] | — |" in result
    assert info["table_cells_cleared"] == 1
    assert agent._repair_final_quantitative_grounding(result)[0] == result


@pytest.mark.parametrize("ending", ["\n", "\r\n"])
def test_code_html_links_and_citations_are_exact_carriers(ending, tmp_path):
    carriers = (
        '```python\n# ## Evidence\nvalue = "99%. ** [S77]"\n```\n\n'
        '    value = "55.6% **"\n\n'
        '<div data-year="2027">Literal **markup** and 99%.</div>\n\n'
        'The [source](https://example.gov/2027?q=55.6) explains `code.value` semantics.\n\n'
        'See https://example.gov/2025 for details.\n\n'
        '[reference]: https://example.gov/2027?q=55.6\n\n'
    ).replace("\n", ending)
    source = ("# Evidence\n\nUnsupported adoption reached **99%.**\n\n").replace("\n", ending) + carriers
    result, info = _agent()._repair_final_quantitative_grounding(source)
    _record(tmp_path, source, result, info)
    assert carriers in result
    assert "Unsupported adoption" not in result
    assert _agent()._repair_final_quantitative_grounding(result)[0] == result


@pytest.mark.parametrize("body", [
    "Unsupported adoption reached 99% inside `code.value`.",
    "Unsupported adoption <em>reached 99%.</em>",
    "- Unsupported adoption reached **99%.**\n  A continued item must remain attached.",
    "> Unsupported adoption reached **99%.**\n> A continued quote must remain attached.",
])
def test_unsafe_structure_stops_real_publication_without_rewriting_source(body, monkeypatch, tmp_path):
    source = "# Evidence\n\n" + body + "\n"
    rid = "report_unsafe_structure"
    _prepare(monkeypatch, tmp_path, rid, source)
    report = Report(rid, "simulation_offline", "graph_offline", "Evidence",
                    status=ReportStatus.GENERATING, markdown_content=source)
    disk = tmp_path / "reports" / rid / "full_report.md"
    with pytest.raises(ValueError, match="Quantitative grounding cannot"):
        _agent()._repair_final_quantitative_grounding(source)
    assert disk.read_text() == source
    with pytest.raises(ValueError, match="Quantitative grounding cannot"):
        _agent()._stabilize_publish_markdown(rid, report)
    # The real citation finalizer precedes grounding and can normalize list
    # indentation. Grounding must leave its input structure and claim intact.
    from app.services.model_translation import markdown_structure
    assert markdown_structure(report.markdown_content) == markdown_structure(source)
    assert "99%" in report.markdown_content
    assert disk.read_text() == report.markdown_content
    assert ReportManager.publication_status(rid)["publishable"] is False


def test_citation_on_bold_sentence_does_not_exempt_adjacent_unsupported_sentence(tmp_path):
    source = "# Evidence\n\n**Official adoption reached 55.6%.** [S1] Unsupported adoption reached 99%.\n"
    result, info = _agent({"title": "Adoption", "url": "https://example.gov/adoption",
                           "supports": ["Official adoption reached 55.6%."]})._repair_final_quantitative_grounding(source)
    _record(tmp_path, source, result, info)
    assert "**Official adoption reached 55.6%.** [S1]" in result
    assert "99%" not in result
    assert info["passed"] is True


@pytest.mark.parametrize("carrier", [
    "`[S1]`", '<span data-source="[S1]">according to the source</span>',
])
def test_citation_literal_in_code_or_html_never_exempts_unsupported_claim(carrier, tmp_path):
    source = f"# Evidence\n\nMeasured adoption reached 99% according to {carrier}.\n"
    agent = _agent({"title": "Adoption", "url": "https://example.gov/adoption",
                    "supports": ["Official adoption reached 55.6%."]})
    with pytest.raises(ValueError, match="Quantitative grounding cannot"):
        agent._repair_final_quantitative_grounding(source)


def test_html_cannot_expand_the_scope_of_a_citation():
    source = (
        "# Evidence\n\n<span></span> **Official adoption reached 55.6%.** [S1] "
        "Unsupported adoption reached 99%.\n"
    )
    agent = _agent({"title": "Adoption", "url": "https://example.gov/adoption",
                    "supports": ["Official adoption reached 55.6%."]})
    with pytest.raises(ValueError, match="Quantitative grounding cannot"):
        agent._repair_final_quantitative_grounding(source)


def test_literal_delimiters_are_not_reparsed_as_new_citation_scope():
    source = (
        "# Evidence\n\n<span></span> "
        r"\***Official adoption reached 55.6%.** [S1] Unsupported adoption reached 99%.\*"
        "\n"
    )
    agent = _agent({"title": "Adoption", "url": "https://example.gov/adoption",
                    "supports": ["Official adoption reached 55.6%."]})
    with pytest.raises(ValueError, match="Quantitative grounding cannot"):
        agent._repair_final_quantitative_grounding(source)


@pytest.mark.parametrize("container", [">     print(99)", "-     print(99)"])
def test_single_line_container_cannot_delete_descendant_code(container):
    source = "# Evidence\n\n" + container + "\n"
    with pytest.raises(ValueError, match="Quantitative grounding cannot"):
        _agent()._repair_final_quantitative_grounding(source)


def test_setext_forecast_heading_preserves_authored_bold_without_waiving_audit(tmp_path):
    authored = "**B1. LBMA p.m. gold exceeds $5,000.00 by 31 December 2027: 55%.**"
    source = "# Forecast\n\nPart 1 — Binary Forecasts\n---\n\n" + authored + "\n"
    result, info = _agent()._repair_final_quantitative_grounding(source)
    _record(tmp_path, source, result, info)
    assert result == source
    # The unchanged downstream external-claim auditor only recognizes ATX H2s.
    # It must still reject this unsupported audit shape, not acquire an exemption.
    assert info["passed"] is False


def test_real_oddsense_scenario_list_uses_independent_parsed_item_spans(tmp_path):
    # Exact first failing container from the joint Oddsense publication trace.
    container = (
        "- **Baseline (60% probability):** Gradual expansion.\n"
        "- **Stress (40% probability):** Expansion is delayed.\n\n"
    )
    source = "# Outlook\n\n## Scenarios and probabilities\n\n" + container
    result, info = _agent()._repair_final_quantitative_grounding(source)
    _record(tmp_path, source, result, info)
    assert "60%" not in result and "40%" not in result
    assert "**" not in result
    assert info["sentences_removed"] == 2 and info["passed"] is True
    assert _agent()._repair_final_quantitative_grounding(result)[0] == result


@pytest.mark.parametrize("marker, sibling", [
    ("-\t", "- "), ("+\t", "+ "), ("*\t", "* "), ("1.\t", "2. "), ("1)\t", "2) "),
])
def test_partial_item_repair_preserves_validated_tab_marker(marker, sibling, tmp_path):
    source = ("# Evidence\n\n" + marker + "Unsupported adoption reached 99%. "
              "The mechanism remains uncertain.\n" + sibling + "Safe sibling remains.\n")
    result, info = _agent()._repair_final_quantitative_grounding(source)
    _record(tmp_path, source, result, info)
    assert marker + "The mechanism remains uncertain.\n" in result
    assert sibling + "Safe sibling remains.\n" in result
    assert "99%" not in result and info["passed"] is True
    nodes = mistune.create_markdown(renderer="ast")(result)
    lists = [node for node in nodes if node["type"] == "list"]
    assert len(lists) == 1 and len(lists[0]["children"]) == 2
    assert _agent()._repair_final_quantitative_grounding(result)[0] == result


def test_flat_list_keeps_cited_siblings_and_exact_validated_market_metadata(tmp_path):
    from app.services import news_market_context as context_api
    from test_news_context_reports import _context

    item = _context()["items"][0]
    item.update(provider="kalshi", id="kalshi:fixture", kind="market_quote",
                yes_bid=0.0, yes_ask=0.44, last_price=0.41,
                price_unit="USD_per_contract", quote_basis="provider_reported_dollars_per_contract",
                probability_basis="last_price_dollars/1_USD_binary_payout", outcome="Yes", quote_at=None,
                rules_primary="Use the synthetic annual release; no real trade or resolution.")
    capture = context_api._validated_copy(_context(items=[item]))
    agent = _agent({"title": "Adoption", "url": "https://example.gov/adoption",
                    "supports": ["Official adoption reached 55.6%."]})
    agent._news_context_sha256 = capture["sha256"]
    agent._news_market_context_json = json.dumps(capture, sort_keys=True)
    agent._news_context_block = context_api.render_context(capture)
    begin, end = agent._news_context_markers()
    metadata = begin + "\n" + agent._news_context_block + "\n" + end
    cited = "- Official adoption reached **55.6%.** [S1]\n"
    neutral = "- The mechanism remains uncertain.\n"
    source = ("# Outlook\n\n" + cited + "- Unsupported lunar adoption reached **99%.**\n" + neutral
              + "\n" + metadata + "\n\n### News and market context\n\n"
              + begin + "\n- Unsupported lunar adoption reached **98%.**\n" + end + "\n")
    result, info = agent._repair_final_quantitative_grounding(source)
    _record(tmp_path, source, result, info)
    assert cited in result and neutral in result
    assert metadata in result
    assert "99%" not in result and "98%" not in result
    assert "yes_bid=0.0" in result and "last_price=0.41" in result
    assert "price_unit=USD_per_contract" in result and item["rules_primary"] in result
    row = next(line for line in agent._news_context_block.splitlines() if "kalshi:fixture" in line)
    assert agent._news_context_canonical_line(row)
    assert not agent._news_context_canonical_line(row.replace("last_price=0.41", "last_price=0.99"))
    assert agent.news_market_context == capture
    assert info["passed"] is True
    assert agent._repair_final_quantitative_grounding(result)[0] == result


class _TranslationTransport:
    """Only transport is scripted; native parsing/review/persistence stay real."""
    model = "offline-grounding-consumer"
    provider = "scripted-transport-only"

    def __init__(self, corrupt):
        self.corrupt = corrupt
        self.calls = []

    def chat_json(self, messages=None, **kwargs):
        self.calls.append(json.loads(messages[-1]["content"]))
        def faithful(source):
            # The existing fixture renderer protects inline HTML tags. This
            # fixture also has an immutable block_html carrier, including its
            # text, which the native parser correctly requires byte-for-byte.
            html = "<div>Literal carrier.</div>"
            return html.join(raw_fixture_zh(part) for part in source.split(html))
        def render(source):
            translated = faithful(source)
            return translated.replace("**", "") if self.corrupt else translated
        return json.loads(model_protocol(messages, render, expected_fn=faithful))

    def chat(self, messages=None, **kwargs):
        return json.dumps(self.chat_json(messages=messages, **kwargs), ensure_ascii=False)


@pytest.mark.parametrize("corrupt_translation", [False, True])
def test_actual_publication_to_translation_consumer_keeps_strict_audits(
    corrupt_translation, monkeypatch, tmp_path,
):
    monkeypatch.setattr(ReportManager, "REPORTS_DIR", str(tmp_path / "reports"))
    monkeypatch.setattr(Config, "REPORT_STRUCTURED_FORECAST", False)
    monkeypatch.setattr(Config, "REPORT_FORECAST_LEDGER", False)
    monkeypatch.setattr(Config, "REPORT_BILINGUAL", True)
    rid = "report_grounding_translation"
    source = (
        "# Evidence\n\n**B1. Gold exceeds $5,000 by 31 December 2027.**\n\n"
        "Official battery adoption reached **55.6%** in 2025. [S1]\n\n"
        "The mechanism remains uncertain.\n\n"
        "```python\nvalue = '99%. ** [S77]'\n```\n\n"
        "<div>Literal carrier.</div>\n\n"
        "| Check | Value |\n|---|---|\n| Method | `code.value` |\n"
    )
    report = Report(rid, "simulation_offline", "graph_offline", "Evidence",
                    status=ReportStatus.COMPLETED, markdown_content=source)
    ReportManager.save_report(report)
    agent = _agent({"title": "Battery adoption", "url": "https://example.gov/adoption",
                    "supports": ["Official battery adoption reached 55.6% in 2025."]})
    stabilization = agent._stabilize_publish_markdown(rid, report)
    assert stabilization["stable"] is True
    assert "B1." not in report.markdown_content
    assert "**55.6%**" in report.markdown_content
    audit = agent._audit_final_published_markdown(rid, report)
    agent._require_final_publish_audit(audit)
    ReportManager.save_report(report)
    assert ReportManager.publication_status(rid)["publishable"] is True
    folder = Path(ReportManager._get_report_folder(rid))
    sealed = {name: (folder / name).read_bytes() for name in (
        "full_report.md", "final_audit.json", "citations.json",
    )}
    model = _TranslationTransport(corrupt_translation)
    status = ReportManager.generate_translation_variant(rid, "zh", llm_client=model)
    (tmp_path / "consumer-proof.json").write_text(json.dumps({
        "source_before_grounding": source, "stabilization": stabilization,
        "publication_audit": audit, "translation_status": status,
        "translation_calls": model.calls,
    }, ensure_ascii=False, indent=2))
    assert model.calls
    assert all((folder / name).read_bytes() == data for name, data in sealed.items())
    if corrupt_translation:
        assert status["available"] is False
        assert not (folder / "full_report.zh.md").exists()
    else:
        assert status["available"] is True, status
        assert ReportManager.publication_status(rid, "zh")["publishable"] is True
        translated = (folder / "full_report.zh.md").read_text()
        translation_audit = json.loads((folder / "final_audit.zh.json").read_text())
        assert "**55.6%**" in translated and "[S1]" in translated
        assert translation_audit["hard_passed"] is True
        assert translation_audit["source_markdown_sha256"] == hashlib.sha256(sealed["full_report.md"]).hexdigest()
        # Reuse must read the sealed variant without acquiring another sample.
        calls = len(model.calls)
        assert ReportManager.generate_translation_variant(rid, "zh", llm_client=model)["available"]
        assert len(model.calls) == calls
