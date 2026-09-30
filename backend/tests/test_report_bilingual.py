"""Offline tests for BILINGUAL auto-translation (english⇄chinese report versions).

No LLM / network: a scripted fake-LLM (`.chat`) drives `_generate_bilingual_report`
via the same `__new__` + attribute-injection harness the other report tests use.
ReportManager.REPORTS_DIR is redirected into tmp so no artifacts leak.

Covers the design's required test bullets:
  * structure preservation — code/mermaid fences copied UNCHANGED, table column
    count kept, an H2-looking line INSIDE a fence is not treated as a boundary;
  * fail-closed integrity — immutable source tokens are reconstructed outside
    model control and residual bad prose still blocks publication;
  * skip on non-CJK/non-Latin (other) language — detection returns None → no file;
  * same-language / identity no-op — translation == source → nothing written;
  * degrade on LLM error — every section call raises → falls back to source →
    no crash, no file, main report untouched;
  * Chinese→English direction produces full_report.en.md;
  * PDF/md path helpers + export_pdf(lang=) parameterization;
  * API: GET /<id>/full_report.<lang>.md serving + /pdf?lang= wiring.
"""

import hashlib
import json
import os
import re
import shutil
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.config import Config  # noqa: E402
from app.services.report_agent import (  # noqa: E402
    ReportAgent, ReportManager, Report, ReportStatus,
)


# ─────────────────────────────── helpers ────────────────────────────────
class _TransLLM:
    """Scripted `.chat` whose response is `translate(user_markdown)`; records calls.

    `translate=None` + `raises=True` simulates an LLM outage (every call raises)."""

    def __init__(self, translate=None, raises=False, model="fake-translator"):
        self.model = model
        self.provider = "fake"
        self.calls = []
        self._t = translate
        self._raises = raises

    def chat(self, messages=None, temperature=0.7, max_tokens=4096, tier="strong", **kw):
        self.calls.append({"messages": messages, "tier": tier, "max_tokens": max_tokens,
                           "temperature": temperature})
        if self._raises:
            raise RuntimeError("simulated LLM outage")
        user = (messages or [{}])[-1].get("content", "")
        user = ReportAgent._decode_translation_placeholders(user)
        return self._t(user) if self._t else user


def _bili_agent(llm, output_language="English"):
    a = ReportAgent.__new__(ReportAgent)
    a.llm = llm
    a.output_language = output_language
    a.simulation_id = "sim_test"
    a.graph_id = "graph_test"
    return a


@pytest.fixture
def reports_tmp(tmp_path, monkeypatch):
    """Redirect ReportManager.REPORTS_DIR into tmp so bilingual artifacts stay isolated."""
    d = tmp_path / "reports"
    d.mkdir()
    monkeypatch.setattr(ReportManager, "REPORTS_DIR", str(d))
    return str(d)


def _publish_primary(rid: str, markdown: str = "# Primary\n\nAudited body.\n") -> None:
    report = Report(
        report_id=rid,
        simulation_id=f"sim_{rid}",
        graph_id="graph_test",
        simulation_requirement="Forecast the outcome.",
        status=ReportStatus.COMPLETED,
        markdown_content=markdown,
    )
    ReportManager.save_report(report)
    with open(ReportManager._get_report_final_audit_path(rid), "w", encoding="utf-8") as f:
        json.dump({
            "policy_version": 3,
            "hard_passed": True,
            "hard_issues": [],
            "markdown_sha256": hashlib.sha256(markdown.encode("utf-8")).hexdigest(),
            "publish_gate": {"enabled": True, "passed": True},
            "structured_forecast": {"required": False, "valid": True},
            "citation_artifacts": {"required": False, "passed": True},
        }, f)


def _publish_variant(
    rid: str, lang: str, markdown: str, markers=None
) -> None:
    with open(ReportManager._get_report_markdown_path(rid), encoding="utf-8") as f:
        source_markdown = f.read()
    source_sha = hashlib.sha256(source_markdown.encode("utf-8")).hexdigest()
    source_lang, target_lang, _target_name = ReportAgent._detect_translation_target(
        source_markdown
    )
    assert source_lang and target_lang == lang
    sha = hashlib.sha256(markdown.encode("utf-8")).hexdigest()
    with open(ReportManager._get_report_citations_path(rid, lang), "w", encoding="utf-8") as f:
        json.dump({
            "schema_version": 2,
            "report_id": rid,
            "language": lang,
            "source_language": source_lang,
            "source_markdown_sha256": source_sha,
            "markdown_sha256": sha,
            "markers": list(markers or []),
        }, f)
    with open(ReportManager._get_report_final_audit_path(rid, lang), "w", encoding="utf-8") as f:
        json.dump({
            "policy_version": 3,
            "report_id": rid,
            "language": lang,
            "source_language": source_lang,
            "source_markdown_sha256": source_sha,
            "hard_passed": True,
            "hard_issues": [],
            "markdown_sha256": sha,
        }, f)
    meta_path = ReportManager._get_report_path(rid)
    with open(meta_path, encoding="utf-8") as f:
        meta = json.load(f)
    meta["translations"] = [{
        "report_id": rid,
        "lang": lang,
        "source_lang": source_lang,
        "source_markdown_sha256": source_sha,
        "markdown_sha256": sha,
        "path": f"full_report.{lang}.md",
        "available": True,
    }]
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(meta, f)


# An English source report with: H1 + summary, two H2 sections, an H3, a markdown
# table (3 columns), a fenced code block that CONTAINS a line starting with '## '
# (must NOT be split as a section), and percentage tokens.
_EN_MD = """# Trade Outlook Report

> A concise Outlook of the 2027 trade posture.

## Executive Summary

The Outlook base case holds at 42% while the escalation path sits at 21%.

### Sub-point

Secondary Outlook detail with 15% weighting.

## Scenarios & Data

| Scenario | Probability | Note |
|---|---|---|
| Base | 42% | steady |
| Escalation | 21% | tail |

```python
# This is code, not a heading
## fake heading inside a fence must survive verbatim
x = 42
```
"""


def _translate_outlook(user: str) -> str:
    """Faithful deterministic translation; fenced code remains byte-identical."""
    replacements = {
        "# Trade Outlook Report": "# 贸易展望报告",
        "> A concise Outlook of the 2027 trade posture.": "> 2027 年贸易形势简报。",
        "## Executive Summary": "## 执行摘要",
        "The Outlook base case holds at 42% while the escalation path sits at 21%.":
            "基准情景为 42%，升级路径为 21%。",
        "### Sub-point": "### 次级要点",
        "Secondary Outlook detail with 15% weighting.": "次级细节权重为 15%。",
        "## Scenarios & Data": "## 情景与数据",
        "| Scenario | Probability | Note |": "| 情景 | 概率 | 备注 |",
        "| Base | 42% | steady |": "| 基准 | 42% | 稳定 |",
        "| Escalation | 21% | tail |": "| 升级 | 21% | 尾部 |",
    }
    in_fence = False
    output = []
    for line in user.splitlines():
        if line.lstrip().startswith(("```", "~~~")):
            in_fence = not in_fence
            output.append(line)
        elif in_fence:
            output.append(line)
        else:
            output.append(replacements.get(line, line))
    return "\n".join(output)


# ─────────────────────────── section splitting ──────────────────────────
def test_split_h2_respects_fences_and_boundaries():
    chunks = ReportAgent._split_markdown_h2_sections(_EN_MD)
    # preamble (H1 + summary) + 'Executive Summary' + 'Scenarios & Data' = 3 chunks.
    assert len(chunks) == 3
    assert chunks[0].startswith("# Trade Outlook Report")
    assert chunks[1].startswith("## Executive Summary")
    assert chunks[2].startswith("## Scenarios & Data")
    # The '## fake heading' inside the code fence must live in chunk 2, not split out.
    assert "## fake heading inside a fence" in chunks[2]
    # Lossless: concatenation with '\n' reproduces the source exactly.
    assert "\n".join(chunks) == _EN_MD


def test_number_integrity_ignores_sentence_punctuation_but_preserves_thousands():
    source = "By 2030, sales reach 1,808,511 units; probability is 42%."
    translated = "到 2030 年，销量达到 1,808,511 辆；概率为 42%。"

    assert ReportAgent._translation_number_multiset(source) == {
        "2030": 1,
        "1,808,511": 1,
        "42%": 1,
    }
    assert (
        ReportAgent._translation_number_multiset(source)
        == ReportAgent._translation_number_multiset(translated)
    )


def test_translation_protects_and_exactly_restores_immutable_tokens():
    source = (
        "Claim 42% [S1] by 2030; see [source](https://example.com/a?year=2030).\n\n"
        "```python\nx = 42\n```\n"
    )
    protected, mapping = ReportAgent._protect_translation_tokens(source)

    assert "42%" not in protected
    assert "[S1]" not in protected
    assert "https://example.com" not in protected
    assert "x = 42" not in protected
    assert "⟦P" in protected and "⟦F" in protected and "⟦X" in protected
    assert len(protected) < len(source) + 80

    # Scripted/offline translators may decode self-describing inline tokens;
    # opaque fences remain protected until the authoritative restore step.
    candidate = ReportAgent._decode_translation_placeholders(protected)
    restored, issues = ReportAgent._restore_translation_tokens(candidate, mapping)
    assert restored == source
    assert issues == []

    repeated, repeated_mapping = ReportAgent._protect_translation_tokens("2035 then 2035")
    first_placeholder = repeated_mapping[0][0]
    repeated = repeated.replace(first_placeholder, "", 1)
    _restored, repeated_issues = ReportAgent._restore_translation_tokens(
        repeated, repeated_mapping
    )
    assert repeated_issues and repeated_issues[0].startswith("missing:")


def test_large_translation_sections_are_split_at_paragraph_boundaries():
    first = "Alpha analysis without immutable values. " * 90
    second = "Beta outlook reaches 42% by 2035 [S1]. " * 90
    source = f"## Outlook\n\n{first}\n\n{second}"
    units = ReportAgent._split_translation_units(source, max_chars=4200)

    assert len(units) == 2
    assert "\n\n".join(units) == source
    assert all(len(unit) <= 4200 for unit in units)

    llm = _TransLLM(translate=lambda text: text.replace("Alpha", "甲").replace("Beta", "乙"))
    translated = _bili_agent(llm)._translate_section(source, "简体中文")
    assert len(llm.calls) == 2
    assert ReportAgent._translation_number_multiset(translated) == {"42%": 90, "2035": 90}
    assert ReportAgent._translation_marker_multiset(translated) == {"S1": 90}


def test_translation_chunking_never_splits_or_mutates_fenced_blocks():
    fence = (
        "```mermaid\n"
        "graph TD\n"
        "  A[DO_NOT_TRANSLATE] --> B\n\n"
        "  B --> C\n"
        "```"
    )
    source = (
        "## Outlook\n\n"
        + ("Alpha analysis paragraph. " * 18)
        + "\n\n"
        + fence
        + "\n\n"
        + ("Beta forecast paragraph. " * 18)
    )
    units = ReportAgent._split_translation_units(source, max_chars=240)

    assert len(units) >= 2
    assert "\n\n".join(units) == source
    assert sum(unit.count("```mermaid") for unit in units) == 1
    assert sum(unit.count("\n```") for unit in units) == 1
    assert any(fence in unit for unit in units)

    llm = _TransLLM(
        translate=lambda text: text.replace("Alpha", "甲").replace(
            "DO_NOT_TRANSLATE", "MUTATED"
        )
    )
    translated = _bili_agent(llm)._translate_section(source, "简体中文")
    assert fence in translated
    assert "MUTATED" not in translated
    assert ReportAgent._translation_fence_signature(source) == (
        ReportAgent._translation_fence_signature(translated)
    )


def test_dropped_placeholders_fall_back_to_source_skeleton_reconstruction():
    class SkeletonLLM:
        model = "fake-skeleton"
        provider = "fake"

        def __init__(self):
            self.calls = []

        def chat(self, messages=None, **_kwargs):
            self.calls.append(messages)
            system = messages[0]["content"]
            user = messages[-1]["content"]
            if "same alphabetic keys" in system:
                payload = json.loads(user)
                return json.dumps({
                    key: value.replace("Outlook", "展望").replace("reaches", "达到")
                    for key, value in payload.items()
                }, ensure_ascii=False)
            return re.sub(r"⟦[PXFX][^⟧]*⟧", "", user, count=1)

    source = (
        "## Outlook 2035\n\n"
        "Adoption reaches 42% by 2035 [S1]. "
        "See [source](https://example.com/forecast).\n"
        "<!-- viz:charts/adoption.html -->\n\n"
        "```text\n2035 stays immutable\n```"
    )
    llm = SkeletonLLM()
    translated = _bili_agent(llm)._translate_section(source, "简体中文")

    assert "## 展望 2035" in translated
    assert "达到 42%" in translated
    assert translated.count("2035") == source.count("2035")
    assert translated.count("[S1]") == 1
    assert "https://example.com/forecast" in translated
    assert "<!-- viz:charts/adoption.html -->" in translated
    assert "```text\n2035 stays immutable\n```" in translated
    assert "⟦" not in translated
    assert len(llm.calls) >= 2


def test_skeleton_retries_missing_json_slots_as_individual_prose():
    class IndividualFallbackLLM:
        model = "fake-individual-fallback"
        provider = "fake"

        def chat(self, messages=None, **_kwargs):
            system = messages[0]["content"]
            user = messages[-1]["content"]
            if "same alphabetic keys" in system:
                return "{}"
            if "one Markdown prose fragment" in system:
                return user.replace("Outlook", "展望").replace("reaches", "达到")
            return re.sub(r"⟦[PXFX][^⟧]*⟧", "", user, count=1)

    source = "## Outlook 2035\n\nAdoption reaches 42% by 2035 [S1]."
    translated = _bili_agent(IndividualFallbackLLM())._translate_section(
        source, "简体中文"
    )

    assert translated == "## 展望 2035\n\nAdoption 达到 42% by 2035 [S1]."
    assert ReportAgent._translation_number_multiset(translated) == {
        "2035": 2,
        "42%": 1,
    }
    assert ReportAgent._translation_marker_multiset(translated) == {"S1": 1}


def test_reference_chunk_is_localized_deterministically_without_touching_entries():
    source = (
        "## References\n\n"
        "1. [S1] IEA Global EV Outlook 2026 — iea.org, 2026 — "
        "[https://www.iea.org/reports/global-ev-outlook-2026]"
        "(https://www.iea.org/reports/global-ev-outlook-2026)\n"
    )

    translated = ReportAgent._localize_translation_references(source, "zh")

    assert translated.startswith("## 参考来源\n\n")
    assert translated.split("\n", 1)[1] == source.split("\n", 1)[1]


def test_bilingual_repairs_residual_table_prose_once_and_keeps_reference_namespace(
    reports_tmp, monkeypatch,
):
    rid = "report_residual_repair"
    source = (
        "# Forecast 2030\n\n"
        "## Binary Forecasts\n\n"
        "| ID | Statement | Probability |\n"
        "|---|---|---|\n"
        "| F1 | Global electric vehicle market share exceeds 42% by 2030 [S1] | 42% |\n\n"
        "## References\n\n"
        "1. [S1] IEA Global EV Outlook 2026 — iea.org, 2026 — "
        "[https://www.iea.org/reports/global-ev-outlook-2026]"
        "(https://www.iea.org/reports/global-ev-outlook-2026)\n"
    )
    report = Report(
        report_id=rid,
        simulation_id="sim_test",
        graph_id="graph_test",
        simulation_requirement="Forecast EV share.",
        status=ReportStatus.COMPLETED,
        markdown_content=source,
    )
    ReportManager._ensure_report_folder(rid)
    source_sha = hashlib.sha256(source.encode("utf-8")).hexdigest()
    with open(ReportManager._get_report_citations_path(rid), "w", encoding="utf-8") as f:
        json.dump({
            "markdown_sha256": source_sha,
            "markers": [{
                "tag": "S1",
                "title": "IEA Global EV Outlook 2026",
                "domain": "iea.org",
                "date": "2026",
                "url": "https://www.iea.org/reports/global-ev-outlook-2026",
                "url_valid": True,
            }],
        }, f)

    body_attempts = 0

    def translate(user: str) -> str:
        nonlocal body_attempts
        if user.startswith("# Forecast"):
            return user.replace("# Forecast", "# 预测")
        if user.startswith("## Binary Forecasts"):
            body_attempts += 1
            out = user.replace("## Binary Forecasts", "## 二元预测")
            out = out.replace("| ID | Statement | Probability |", "| ID | 陈述 | 概率 |")
            if body_attempts > 1:
                out = out.replace(
                    "Global electric vehicle market share exceeds 42% by 2030 [S1]",
                    "全球电动汽车份额到 2030 年超过 42% [S1]",
                )
            return out
        raise AssertionError("References must not consume an LLM translation call")

    monkeypatch.setattr(Config, "REPORT_TRANSLATION_CONCURRENCY", 1)
    agent = _bili_agent(_TransLLM(translate=translate))
    agent._generate_bilingual_report(rid, report)

    assert body_attempts == 2
    assert ReportManager.is_publishable(rid, "zh") is False  # primary fixture is not published
    out_path = ReportManager._get_report_translation_path(rid, "zh")
    assert os.path.exists(out_path)
    out = open(out_path, encoding="utf-8").read()
    assert "全球电动汽车份额到 2030 年超过 42% [S1]" in out
    assert "## 参考来源" in out
    assert "https://www.iea.org/reports/global-ev-outlook-2026" in out
    assert report.translations and report.translations[0]["lang"] == "zh"


# ─────────────────────────── structure preservation ─────────────────────
def test_bilingual_preserves_structure_and_writes_zh(reports_tmp):
    rid = "report_struct"
    ReportManager._ensure_report_folder(rid)
    report = Report(report_id=rid, simulation_id="sim_test", graph_id="graph_test",
                    simulation_requirement="req", status=ReportStatus.COMPLETED,
                    markdown_content=_EN_MD)
    agent = _bili_agent(_TransLLM(translate=_translate_outlook), output_language="English")

    agent._generate_bilingual_report(rid, report)

    zh_path = os.path.join(reports_tmp, rid, "full_report.zh.md")
    assert os.path.exists(zh_path)
    with open(zh_path, encoding="utf-8") as f:
        out = f.read()
    # fence content copied UNCHANGED (the in-fence pseudo-heading + code survive verbatim)
    assert "## fake heading inside a fence must survive verbatim" in out
    assert "x = 42" in out
    # table shape kept: separator row + 3-column data rows intact
    assert "|---|---|---|" in out
    assert out.count("| 基准 | 42% | 稳定 |") == 1
    # prose actually translated (Outlook → 展望) — proves it wasn't a no-op skip
    assert "展望" in out and "Outlook" not in out
    # meta entry recorded on the report, number integrity OK
    assert report.translations and len(report.translations) == 1
    entry = report.translations[0]
    assert entry["lang"] == "zh" and entry["source_lang"] == "en"
    assert entry["path"] == "full_report.zh.md"
    assert entry["translation_quality"] == "ok"
    assert entry["missing_numbers"] == []
    assert entry["model"] == "fake-translator"
    assert entry["available"] is True
    assert entry["chars"] == len(out)
    assert entry["bytes"] == len(out.encode("utf-8"))
    assert entry["markdown_sha256"] == hashlib.sha256(out.encode("utf-8")).hexdigest()
    assert os.path.exists(ReportManager._get_report_citations_path(rid, "zh"))
    assert os.path.exists(ReportManager._get_report_final_audit_path(rid, "zh"))
    # primary deliverable never mutated
    assert report.markdown_content == _EN_MD
    # meta.json round-trips the translations block
    ReportManager.save_report(report)
    reloaded = ReportManager.get_report(rid)
    assert reloaded.translations and reloaded.translations[0]["lang"] == "zh"


def test_parallel_translation_workers_inherit_run_telemetry_context(
    reports_tmp, monkeypatch
):
    from app.utils import telemetry

    class ContextLLM(_TransLLM):
        def __init__(self):
            super().__init__(translate=_translate_outlook)
            self.contexts = []

        def chat(self, *args, **kwargs):
            self.contexts.append(telemetry.get_run_context())
            return super().chat(*args, **kwargs)

    rid = "report_translation_context"
    ReportManager._ensure_report_folder(rid)
    report = Report(
        report_id=rid,
        simulation_id="sim_test",
        graph_id="graph_test",
        simulation_requirement="req",
        status=ReportStatus.COMPLETED,
        markdown_content=_EN_MD,
    )
    llm = ContextLLM()
    monkeypatch.setattr(Config, "REPORT_TRANSLATION_CONCURRENCY", 4)
    previous = telemetry.get_run_context()
    progress_updates = []
    telemetry.set_run_context("pipe_translation_context", "report-translation")
    try:
        _bili_agent(llm)._generate_bilingual_report(
            rid,
            report,
            progress_callback=lambda value, message: progress_updates.append(
                (value, message)
            ),
        )
    finally:
        telemetry.set_run_context(*previous)

    assert llm.contexts
    assert set(llm.contexts) == {("pipe_translation_context", "report-translation")}
    values = [value for value, _message in progress_updates]
    assert values == sorted(values)
    assert values[0] == 1 and values[-1] == 95
    assert any("translated" in message for _value, message in progress_updates)
    runtime = ReportManager._load_translation_runtime_status(rid, "zh")
    assert runtime and runtime["status"] == "available" and runtime["progress"] == 100


# ─────────────────────────── number-integrity flag ──────────────────────
def test_bilingual_number_mutation_is_repaired_but_bad_prose_still_blocks_variant(
    reports_tmp, monkeypatch,
):
    # Strict mode: with REPORT_TRANSLATION_RESIDUAL_LINES=0 any residual source-language
    # line blocks the variant (the default tolerance is covered in
    # tests/test_translation_robustness.py).
    monkeypatch.setattr(Config, "REPORT_TRANSLATION_RESIDUAL_LINES", 0)
    rid = "report_numint"
    ReportManager._ensure_report_folder(rid)
    report = Report(report_id=rid, simulation_id="s", graph_id="g",
                    simulation_requirement="req", status=ReportStatus.COMPLETED,
                    markdown_content=_EN_MD)
    # Corrupt the numbers: drop the '%' on 42% (→ '42 percent') in prose + table.
    llm = _TransLLM(translate=lambda u: _translate_outlook(u).replace("42%", "42 percent"))
    agent = _bili_agent(llm)

    agent._generate_bilingual_report(rid, report)

    assert not os.path.exists(os.path.join(reports_tmp, rid, "full_report.zh.md"))
    assert report.translations is None
    audit_path = ReportManager._get_report_final_audit_path(rid, "zh")
    with open(audit_path, encoding="utf-8") as handle:
        audit = json.load(handle)
    assert audit["hard_passed"] is False
    assert audit["number_parity"]["passed"] is True
    contamination = audit["language_lint"]["language_contamination"]["lines"]
    assert contamination >= 1
    assert any(
        issue.startswith("translation contains ")
        and issue.endswith(" target-language contamination lines")
        for issue in audit["issues"]
    )


def test_translation_variant_audit_rejects_heading_table_and_language_drift():
    source = (
        "# Forecast\n\n## Outcome\n\nThe outcome is 42%.\n\n"
        "| Metric | Value |\n|---|---|\n| Share | 42% |\n"
    )
    variant = (
        "# 预测\n\nThe untranslated outcome prose remains here at 42%.\n\n"
        "| 指标 |\n|---|\n| 42% |\n"
    )
    agent = _bili_agent(_TransLLM(translate=_translate_outlook))
    agent._forecast_spine = None

    audit, _citations = agent._audit_translation_variant(
        "report_variant_audit", source, variant, "en", "zh", {})

    assert audit["hard_passed"] is False
    assert audit["section_parity"]["passed"] is False
    assert audit["table_parity"]["passed"] is False
    assert audit["language_lint"]["language_contamination"]["lines"] >= 1


# ─────────────────────────── skip: other language ───────────────────────
def test_bilingual_skips_non_cjk_non_latin(reports_tmp):
    rid = "report_other"
    ReportManager._ensure_report_folder(rid)
    cyrillic = "# Отчет\n\n> Резюме\n\n## Обзор\n\nЭто текст на русском языке с 42% долей.\n"
    report = Report(report_id=rid, simulation_id="s", graph_id="g",
                    simulation_requirement="req", status=ReportStatus.COMPLETED,
                    markdown_content=cyrillic)
    llm = _TransLLM(translate=lambda u: u + " X")
    agent = _bili_agent(llm)

    agent._generate_bilingual_report(rid, report)

    # Other-script → detection returns None → no file, no translations, no LLM call.
    assert not os.path.exists(os.path.join(reports_tmp, rid, "full_report.en.md"))
    assert not os.path.exists(os.path.join(reports_tmp, rid, "full_report.zh.md"))
    assert report.translations is None
    assert llm.calls == []


# ─────────────────────────── skip: identity no-op ───────────────────────
def test_bilingual_identity_translation_is_noop(reports_tmp):
    rid = "report_ident"
    ReportManager._ensure_report_folder(rid)
    report = Report(report_id=rid, simulation_id="s", graph_id="g",
                    simulation_requirement="req", status=ReportStatus.COMPLETED,
                    markdown_content=_EN_MD)
    # Identity "translation" → translated == source → nothing to ship.
    agent = _bili_agent(_TransLLM(translate=lambda u: u))

    agent._generate_bilingual_report(rid, report)

    assert not os.path.exists(os.path.join(reports_tmp, rid, "full_report.zh.md"))
    assert report.translations is None


# ─────────────────────────── degrade on LLM error ───────────────────────
def test_bilingual_degrades_on_llm_error(reports_tmp):
    rid = "report_err"
    ReportManager._ensure_report_folder(rid)
    report = Report(report_id=rid, simulation_id="s", graph_id="g",
                    simulation_requirement="req", status=ReportStatus.COMPLETED,
                    markdown_content=_EN_MD)
    agent = _bili_agent(_TransLLM(raises=True))

    # Must not raise; every section falls back to source → identity → no file.
    agent._generate_bilingual_report(rid, report)

    assert not os.path.exists(os.path.join(reports_tmp, rid, "full_report.zh.md"))
    assert report.translations is None
    assert report.markdown_content == _EN_MD  # main deliverable untouched


# ─────────────────────── disabled flag → hard skip ──────────────────────
def test_bilingual_disabled_flag_skips(reports_tmp, monkeypatch):
    monkeypatch.setattr(Config, "REPORT_BILINGUAL", False)
    rid = "report_off"
    ReportManager._ensure_report_folder(rid)
    report = Report(report_id=rid, simulation_id="s", graph_id="g",
                    simulation_requirement="req", status=ReportStatus.COMPLETED,
                    markdown_content=_EN_MD)
    llm = _TransLLM(translate=_translate_outlook)
    agent = _bili_agent(llm)

    agent._generate_bilingual_report(rid, report)

    assert not os.path.exists(os.path.join(reports_tmp, rid, "full_report.zh.md"))
    assert report.translations is None
    assert llm.calls == []


# ─────────────────────── zh→en direction ─────────────────────────────────
def test_bilingual_chinese_source_produces_english(reports_tmp):
    rid = "report_zh"
    ReportManager._ensure_report_folder(rid)
    zh_md = ("# 贸易展望报告\n\n> 简要摘要\n\n## 执行摘要\n\n"
             "基准情景维持在 42%，升级路径为 21%。\n")
    report = Report(report_id=rid, simulation_id="s", graph_id="g",
                    simulation_requirement="req", status=ReportStatus.COMPLETED,
                    markdown_content=zh_md)
    # Faithful fake English translation that keeps the numeric tokens.
    def _to_en(user: str) -> str:
        return (user.replace("# 贸易展望报告", "# Trade Outlook Report")
                .replace("> 简要摘要", "> Concise summary.")
                .replace("## 执行摘要", "## Executive Summary")
                .replace("基准情景维持在 42%，升级路径为 21%。",
                         "The base case is 42%, while escalation is 21%."))

    agent = _bili_agent(_TransLLM(translate=_to_en),
                        output_language="Chinese")

    agent._generate_bilingual_report(rid, report)

    en_path = os.path.join(reports_tmp, rid, "full_report.en.md")
    assert os.path.exists(en_path)
    assert report.translations[0]["lang"] == "en"
    assert report.translations[0]["source_lang"] == "zh"


def test_existing_report_translation_preserves_unrelated_metadata(reports_tmp):
    rid = "report_existing_translate"
    source = "# EV Forecast 2030\n\n## Outlook\n\nEV share reaches 42% by 2030.\n"
    _publish_primary(rid, source)
    meta_path = ReportManager._get_report_path(rid)
    meta = json.loads(open(meta_path, encoding="utf-8").read())
    meta["pipeline_id"] = "pipe_must_survive"
    meta["custom_release_field"] = {"keep": True}
    with open(meta_path, "w", encoding="utf-8") as handle:
        json.dump(meta, handle, ensure_ascii=False)

    def translate(user: str) -> str:
        return (user.replace("# EV Forecast", "# 电动汽车预测")
                .replace("## Outlook", "## 展望")
                .replace("EV share reaches 42% by 2030.",
                         "到 2030 年，电动汽车份额达到 42%。"))

    result = ReportManager.generate_translation_variant(
        rid, "zh", llm_client=_TransLLM(translate=translate)
    )

    assert result["status"] == "available"
    assert result["available"] is True
    saved = json.loads(open(meta_path, encoding="utf-8").read())
    assert saved["pipeline_id"] == "pipe_must_survive"
    assert saved["custom_release_field"] == {"keep": True}
    assert saved["translations"][0]["lang"] == "zh"


def test_translation_status_exposes_failed_audit_for_retry(reports_tmp):
    rid = "report_translation_failed_status"
    source = "# EV Forecast\n\nAudited English body.\n"
    _publish_primary(rid, source)
    with open(ReportManager._get_report_final_audit_path(rid, "zh"), "w", encoding="utf-8") as f:
        json.dump({
            "policy_version": 3,
            "language": "zh",
            "source_language": "en",
            "source_markdown_sha256": hashlib.sha256(source.encode("utf-8")).hexdigest(),
            "hard_passed": False,
            "issues": ["translation contains target-language contamination"],
        }, f)

    state = ReportManager.translation_status(rid, "zh")

    assert state["status"] == "failed"
    assert state["available"] is False
    assert state["can_generate"] is True
    assert state["source_lang"] == "en"
    assert state["target_lang"] == "zh"
    assert state["issues"] == ["translation contains target-language contamination"]


def test_translation_runtime_failure_preserves_source_identity_and_task(reports_tmp):
    rid = "report_translation_runtime_identity"
    source = "# EV Forecast\n\nAudited English body.\n"
    _publish_primary(rid, source)
    source_sha = hashlib.sha256(source.encode("utf-8")).hexdigest()
    ReportManager._set_translation_runtime_status(
        rid,
        "zh",
        "generating",
        source_markdown_sha256=source_sha,
        task_id="task-durable",
        owner="pid:123",
        progress=55,
    )
    # A terminal writer may only know the error.  The durable record must merge,
    # not discard the source/task identity needed after a restart.
    ReportManager._set_translation_runtime_status(
        rid, "zh", "failed", issues=["translator unavailable"]
    )

    state = ReportManager.translation_status(rid, "zh")
    assert state["status"] == "failed"
    assert state["can_generate"] is True
    assert state["source_markdown_sha256"] == source_sha
    assert state["task_id"] == "task-durable"
    assert state["owner"] == "pid:123"
    assert state["progress"] == 100


def test_publication_payload_rebuilds_only_verified_translation_rows(reports_tmp):
    from app.api.report import _report_publication_payload

    rid = "report_stale_translation_metadata"
    source = "# EV Forecast\n\nAudited English body.\n"
    _publish_primary(rid, source)
    report = ReportManager.get_report(rid)
    assert report is not None
    report.translations = [{
        "lang": "zh",
        "path": "full_report.zh.md",
        "available": True,
        "source_markdown_sha256": "stale",
        "markdown_sha256": "stale",
    }]

    payload = _report_publication_payload(report)
    assert payload["translations"] == []
    assert payload["translation_status"]["available"] is False


# ─────────────────────── path helpers + export_pdf(lang=) ───────────────
def test_pdf_and_translation_path_helpers(reports_tmp):
    rid = "report_paths"
    assert ReportManager._get_report_pdf_path(rid).endswith("full_report.pdf")
    assert ReportManager._get_report_pdf_path(rid, "zh").endswith("full_report.zh.pdf")
    # bogus lang → primary pdf (never a full_report.None.pdf)
    assert ReportManager._get_report_pdf_path(rid, "xx").endswith("full_report.pdf")
    assert ReportManager._get_report_translation_path(rid, "en").endswith("full_report.en.md")


def test_export_pdf_uses_translation_source(reports_tmp, monkeypatch):
    rid = "report_pdf_lang"
    _publish_primary(rid)
    # Write a zh translation md; stub the actual PDF backends so no pandoc/PyMuPDF needed.
    zh_path = ReportManager._get_report_translation_path(rid, "zh")
    zh_md = (
        "# 标题\n\n正文 42% [S1]。\n\n## 参考来源\n\n"
        "1. [S1] 中文来源 — [https://example.cn/zh](https://example.cn/zh)\n"
    )
    with open(zh_path, "w", encoding="utf-8") as f:
        f.write(zh_md)
    with open(ReportManager._get_report_citations_path(rid), "w", encoding="utf-8") as f:
        json.dump({"markers": [{"tag": "S1", "title": "WRONG PRIMARY",
                                "domain": "wrong.example", "url": "https://wrong.example",
                                "url_valid": True}]}, f)
    _publish_variant(rid, "zh", zh_md, markers=[{
        "tag": "S1", "title": "中文来源", "domain": "example.cn",
        "url": "https://example.cn/zh", "url_valid": True,
    }])

    seen = {}

    def _fake_pandoc(cls, report_id, md, folder, pdf_path):
        seen["pdf_path"] = pdf_path
        seen["md"] = md
        with open(pdf_path, "wb") as fh:
            fh.write(b"%PDF-1.4 fake")
        return True

    monkeypatch.setattr(Config, "REPORT_PDF_EXPORT", True)
    monkeypatch.setattr(ReportManager, "_export_pdf_pandoc", classmethod(_fake_pandoc))
    monkeypatch.setattr(
        ReportManager,
        "_validate_pdf_content",
        staticmethod(lambda path, md: (True, {"page_count": 1, "issues": []})),
    )

    out = ReportManager.export_pdf(rid, lang="zh")
    assert out and out.endswith("full_report.zh.pdf")
    assert seen["pdf_path"].endswith("full_report.zh.pdf")
    assert "标题" in seen["md"]
    assert "中文来源" in seen["md"] and "WRONG PRIMARY" not in seen["md"]
    # Missing translation for 'en' → None (degrade-safe), no crash.
    assert ReportManager.export_pdf(rid, lang="en") is None


def test_translation_pdf_cache_cannot_bypass_missing_variant_audit(reports_tmp, monkeypatch):
    rid = "report_pdf_unaudited"
    ReportManager._ensure_report_folder(rid)
    md_path = ReportManager._get_report_translation_path(rid, "zh")
    pdf_path = ReportManager._get_report_pdf_path(rid, "zh")
    with open(md_path, "w", encoding="utf-8") as handle:
        handle.write("# 标题\n\n未审计译文。\n")
    with open(pdf_path, "wb") as handle:
        handle.write(b"%PDF-1.4 stale")
    os.utime(pdf_path, (os.path.getmtime(md_path) + 10,) * 2)
    monkeypatch.setattr(Config, "REPORT_PDF_EXPORT", True)

    assert ReportManager.export_pdf(rid, lang="zh") is None


def test_variant_artifacts_cannot_be_rebound_to_another_report(reports_tmp):
    """A complete copied sidecar bundle never publishes under another report."""
    report_a = "report_variant_owner_a"
    report_b = "report_variant_owner_b"
    _publish_primary(report_a, "# Forecast A\n\nEnglish source A 42%.\n")
    _publish_primary(report_b, "# Forecast B\n\nEnglish source B 57%.\n")
    zh_a = "# 预测 A\n\n中文译文 A 42%。\n"
    with open(
        ReportManager._get_report_translation_path(report_a, "zh"),
        "w",
        encoding="utf-8",
    ) as handle:
        handle.write(zh_a)
    _publish_variant(report_a, "zh", zh_a)

    for getter in (
        ReportManager._get_report_translation_path,
        ReportManager._get_report_citations_path,
        ReportManager._get_report_final_audit_path,
    ):
        shutil.copyfile(getter(report_a, "zh"), getter(report_b, "zh"))
    with open(ReportManager._get_report_path(report_a), encoding="utf-8") as handle:
        a_meta = json.load(handle)
    with open(ReportManager._get_report_path(report_b), encoding="utf-8") as handle:
        b_meta = json.load(handle)
    b_meta["translations"] = a_meta["translations"]
    with open(ReportManager._get_report_path(report_b), "w", encoding="utf-8") as handle:
        json.dump(b_meta, handle)

    first = ReportManager.publication_status(report_b, "zh")
    assert first["publishable"] is False
    assert any("another report" in reason for reason in first["reasons"])

    # Even rewriting only the visible report IDs cannot defeat source-byte binding.
    for path in (
        ReportManager._get_report_citations_path(report_b, "zh"),
        ReportManager._get_report_final_audit_path(report_b, "zh"),
    ):
        with open(path, encoding="utf-8") as handle:
            payload = json.load(handle)
        payload["report_id"] = report_b
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle)
    b_meta["translations"][0]["report_id"] = report_b
    with open(ReportManager._get_report_path(report_b), "w", encoding="utf-8") as handle:
        json.dump(b_meta, handle)

    second = ReportManager.publication_status(report_b, "zh")
    assert second["publishable"] is False
    assert any("source fingerprint" in reason for reason in second["reasons"])


# ─────────────────────── API: md serving + pdf?lang= ─────────────────────
@pytest.fixture
def client(reports_tmp, monkeypatch):
    from app import create_app
    app = create_app()
    app.config["TESTING"] = True
    return app.test_client()


def test_api_serves_translation_md(client, reports_tmp):
    rid = "report_api_md"
    _publish_primary(rid)
    zh_md = "# 中文标题\n\n译文正文。\n"
    with open(ReportManager._get_report_translation_path(rid, "zh"), "w", encoding="utf-8") as f:
        f.write(zh_md)
    _publish_variant(rid, "zh", zh_md)

    resp = client.get(f"/api/report/{rid}/full_report.zh.md")
    assert resp.status_code == 200
    assert "中文标题" in resp.get_data(as_text=True)

    # Missing en version → 404 (degrade-safe)
    assert client.get(f"/api/report/{rid}/full_report.en.md").status_code == 404
    # Unsupported lang → 404
    assert client.get(f"/api/report/{rid}/full_report.fr.md").status_code == 404


def test_api_translation_retry_task_is_report_and_language_bound(
    client, reports_tmp, monkeypatch,
):
    from app.api import report as report_api

    rid = "report_api_translate_retry"
    _publish_primary(rid, "# EV Forecast\n\nEnglish report body for translation.\n")

    def fake_generate(
        cls,
        report_id,
        lang,
        llm_client=None,
        progress_callback=None,
        force=False,
    ):
        assert report_id == rid and lang == "zh"
        assert progress_callback is not None
        assert force is False  # a retry of a missing variant is not a forced update
        progress_callback(55, "Translating report sections")
        return {
            "report_id": rid,
            "requested_lang": "zh",
            "status": "available",
            "available": True,
            "issues": [],
        }

    monkeypatch.setattr(
        ReportManager, "generate_translation_variant", classmethod(fake_generate)
    )
    monkeypatch.setattr(report_api, "_launch_translation_thread", lambda target: target())

    started = client.post(f"/api/report/{rid}/translations/zh")
    assert started.status_code == 202
    task_id = started.get_json()["data"]["task_id"]

    status = client.get(
        f"/api/report/{rid}/translations/zh/status?task_id={task_id}"
    )
    payload = status.get_json()["data"]
    assert status.status_code == 200
    assert payload["status"] == "completed"
    assert payload["result"]["available"] is True

    wrong_lang = client.get(
        f"/api/report/{rid}/translations/en/status?task_id={task_id}"
    )
    assert wrong_lang.status_code == 409


def test_api_translation_post_deduplicates_from_durable_lease_after_restart(
    client, reports_tmp, monkeypatch,
):
    from app.api import report as report_api
    from app.models.task import TaskManager

    rid = "report_api_translate_durable_dedup"
    _publish_primary(rid, "# EV Forecast\n\nEnglish report body for translation.\n")
    # Keep the worker queued so the durable pending record remains observable.
    monkeypatch.setattr(report_api, "_launch_translation_thread", lambda _target: None)

    first = client.post(f"/api/report/{rid}/translations/zh")
    assert first.status_code == 202
    first_data = first.get_json()["data"]
    task_id = first_data["task_id"]

    # A second POST in the same process returns the existing task even though
    # can_generate is false while the durable lease is active.
    second = client.post(f"/api/report/{rid}/translations/zh")
    assert second.status_code == 202
    assert second.get_json()["data"]["task_id"] == task_id

    # Simulate a backend restart / another worker: in-memory task state is gone,
    # but the source-bound durable lease still deduplicates the request.
    manager = TaskManager()
    with manager._task_lock:
        manager._tasks.pop(task_id, None)
    third = client.post(f"/api/report/{rid}/translations/zh")
    assert third.status_code == 202
    third_data = third.get_json()["data"]
    assert third_data["status"] == "generating"
    assert third_data["task_id"] == task_id
    assert third_data["source_markdown_sha256"]


def test_api_translation_post_answers_duplicates_while_generation_holds_lease(
    client, reports_tmp, monkeypatch,
):
    """A generation holds the lease for its whole run; a duplicate POST (second tab,
    click after a reload) must answer from the task state instead of hanging."""
    import threading
    import time

    from app.api import report as report_api

    rid = "report_api_translate_duplicate_nonblocking"
    _publish_primary(rid, "# EV Forecast\n\nEnglish report body for translation.\n")
    monkeypatch.setattr(report_api, "_launch_translation_thread", lambda _target: None)
    first = client.post(f"/api/report/{rid}/translations/zh")
    assert first.status_code == 202
    task_id = first.get_json()["data"]["task_id"]

    held, release = threading.Event(), threading.Event()

    def _worker_holding_lease():
        with ReportManager._translation_generation_lease(rid, "zh"):
            held.set()
            release.wait(10)

    worker = threading.Thread(target=_worker_holding_lease)
    worker.start()
    assert held.wait(5)
    try:
        started = time.monotonic()
        second = client.post(f"/api/report/{rid}/translations/zh")
        elapsed = time.monotonic() - started
    finally:
        release.set()
        worker.join(5)
    assert second.status_code == 202
    assert second.get_json()["data"]["task_id"] == task_id
    assert elapsed < 2.0


def test_report_payload_translation_row_satisfies_the_ui_identity_contract(client, reports_tmp):
    """The report UI (frontend/src/utils/reportLanguages.js isVerifiedTranslationRow)
    shows the language toggle only for a row carrying every identity field below; a
    missing citations_path hid the toggle after every successful translation."""
    rid = "report_ui_translation_contract"
    _publish_primary(rid, "# EV Forecast\n\nEnglish report body for translation.\n")
    zh_md = "# 电动车预测\n\n中文报告正文。\n"
    with open(ReportManager._get_report_translation_path(rid, "zh"), "w", encoding="utf-8") as f:
        f.write(zh_md)
    _publish_variant(rid, "zh", zh_md)

    data = client.get(f"/api/report/{rid}").get_json()["data"]
    state = data["translation_status"]
    assert state["status"] == "available" and state["available"] is True
    assert (state["source_lang"], state["target_lang"]) == ("en", "zh")
    [row] = data["translations"]
    assert row["report_id"] == rid and row["available"] is True
    assert (row["lang"], row["source_lang"]) == ("zh", "en")
    assert row["path"] == "full_report.zh.md"
    assert row["citations_path"] == "citations.zh.json"
    assert row["final_audit_path"] == "final_audit.zh.json"
    assert row["markdown_sha256"] == state["markdown_sha256"]
    assert re.fullmatch(r"[0-9a-f]{64}", row["source_markdown_sha256"])
    verified = state["translation"]
    assert verified["markdown_sha256"] == state["markdown_sha256"]
    assert (verified["lang"], verified["source_lang"], verified["path"]) == (
        "zh", "en", "full_report.zh.md"
    )


def _publish_old_variant(rid: str) -> str:
    """A published zh variant from an older engine (no translator_version stamp)."""
    _publish_primary(rid, _EN_MD)
    old_zh = "# 旧译文\n\n旧的中文正文。\n"
    with open(ReportManager._get_report_translation_path(rid, "zh"), "w", encoding="utf-8") as f:
        f.write(old_zh)
    _publish_variant(rid, "zh", old_zh)
    return old_zh


def test_outdated_translation_updates_in_place_and_survives_a_failed_update(reports_tmp):
    rid = "report_update_translation"
    old_zh = _publish_old_variant(rid)
    state = ReportManager.translation_status(rid, "zh")
    assert state["available"] is True
    assert state["outdated"] is True and state["can_update"] is True

    # A rejected update (the model echoes English) leaves the published variant alone.
    rejected = ReportManager.generate_translation_variant(
        rid, "zh", llm_client=_TransLLM(translate=lambda text: text), force=True
    )
    assert rejected["available"] is True and rejected["updated"] is False
    assert rejected["issues"]
    with open(ReportManager._get_report_translation_path(rid, "zh"), encoding="utf-8") as f:
        assert f.read() == old_zh
    assert ReportManager.is_publishable(rid, "zh")

    # A passing update replaces it with a current-engine variant.
    accepted = ReportManager.generate_translation_variant(
        rid, "zh", llm_client=_TransLLM(translate=_translate_outlook), force=True
    )
    assert accepted["updated"] is True
    state = ReportManager.translation_status(rid, "zh")
    assert state["outdated"] is False and state["can_update"] is False
    assert state["translation"]["translator_version"] == ReportAgent._TRANSLATOR_VERSION


def _translate_outlook_partially(user: str) -> str:
    """Leaves both body sentences in English, so the variant audit rejects it."""
    return (
        _translate_outlook(user)
        .replace("基准情景为 42%，升级路径为 21%。",
                 "The Outlook base case holds at 42% while the escalation path sits at 21%.")
        .replace("次级细节权重为 15%。", "Secondary Outlook detail with 15% weighting.")
    )


def test_a_rejected_update_keeps_its_text_and_audit_for_diagnosis(reports_tmp):
    rid = "report_rejected_update"
    old_zh = _publish_old_variant(rid)
    result = ReportManager.generate_translation_variant(
        rid, "zh", llm_client=_TransLLM(translate=_translate_outlook_partially), force=True
    )
    assert result["available"] is True and result["updated"] is False
    with open(ReportManager._get_report_translation_path(rid, "zh"), encoding="utf-8") as f:
        assert f.read() == old_zh
    assert ReportManager.is_publishable(rid, "zh")
    base = ReportManager._get_report_translation_path(rid, "zh")[: -len(".md")]
    with open(base + ".rejected.md", encoding="utf-8") as f:
        assert "Secondary Outlook detail" in f.read()
    rejected_audit = ReportManager._get_report_final_audit_path(rid, "zh")[: -len(".json")]
    with open(rejected_audit + ".rejected.json", encoding="utf-8") as f:
        assert json.load(f)["hard_passed"] is False


def test_date_aware_variant_without_a_version_stamp_is_dated_by_its_facts(
    reports_tmp, monkeypatch
):
    """Variants audited by the date-aware engine before the stamp existed record
    date facts in their number parity: they are the 2026-09-29.1 engine's, current
    while that engine was, and outdated once the amount-aware engine replaced it."""
    rid = "report_version_inferred"
    _publish_old_variant(rid)
    audit_path = ReportManager._get_report_final_audit_path(rid, "zh")
    with open(audit_path, encoding="utf-8") as f:
        audit = json.load(f)
    audit["number_parity"] = {"passed": True, "source": {"date:2025-09": 1}, "variant": {"date:2025-09": 1}}
    with open(audit_path, "w", encoding="utf-8") as f:
        json.dump(audit, f)
    state = ReportManager.translation_status(rid, "zh")
    assert state["available"] is True
    assert state["translation"]["translator_version"] == "2026-09-29.1"
    assert state["outdated"] is True and state["can_update"] is True

    monkeypatch.setattr(ReportAgent, "_TRANSLATOR_VERSION", "2026-09-29.1")
    state = ReportManager.translation_status(rid, "zh")
    assert state["available"] is True and state["outdated"] is False


def test_api_forced_update_is_task_bound_not_instantly_available(client, reports_tmp, monkeypatch):
    from app.api import report as report_api

    rid = "report_api_force_update"
    _publish_old_variant(rid)
    monkeypatch.setattr(report_api, "_launch_translation_thread", lambda _target: None)

    plain = client.post(f"/api/report/{rid}/translations/zh")
    assert plain.status_code == 200 and plain.get_json()["data"]["available"] is True

    forced = client.post(f"/api/report/{rid}/translations/zh?force=1")
    assert forced.status_code == 202
    data = forced.get_json()["data"]
    assert data["available"] is False and data["task_id"]

    polled = client.get(
        f"/api/report/{rid}/translations/zh/status?task_id={data['task_id']}"
    ).get_json()["data"]
    assert polled["available"] is False and polled["status"] == "pending"


def test_api_pdf_lang_param(client, reports_tmp, monkeypatch):
    rid = "report_api_pdf"
    ReportManager._ensure_report_folder(rid)
    # meta.json so ReportManager.get_report(rid) succeeds inside the endpoint.
    report = Report(report_id=rid, simulation_id="s", graph_id="g",
                    simulation_requirement="req", status=ReportStatus.COMPLETED,
                    markdown_content="# T\n\nbody 42%.\n")
    ReportManager.save_report(report)
    primary_md = report.markdown_content
    with open(ReportManager._get_report_final_audit_path(rid), "w", encoding="utf-8") as f:
        json.dump({
            "policy_version": 3,
            "hard_passed": True,
            "hard_issues": [],
            "markdown_sha256": hashlib.sha256(primary_md.encode("utf-8")).hexdigest(),
            "publish_gate": {"enabled": True, "passed": True},
            "structured_forecast": {"required": False, "valid": True},
            "citation_artifacts": {"required": False, "passed": True},
        }, f)
    zh_md = "# 标题\n\n正文 42%。\n"
    with open(ReportManager._get_report_translation_path(rid, "zh"), "w", encoding="utf-8") as f:
        f.write(zh_md)
    _publish_variant(rid, "zh", zh_md)

    captured = {}

    def _fake_export(cls, report_id, force=False, lang=None):
        captured["lang"] = lang
        p = ReportManager._get_report_pdf_path(report_id, lang)
        with open(p, "wb") as fh:
            fh.write(b"%PDF-1.4 fake")
        return p

    monkeypatch.setattr(ReportManager, "export_pdf", classmethod(_fake_export))

    resp = client.get(f"/api/report/{rid}/pdf?lang=zh")
    assert resp.status_code == 200
    assert captured["lang"] == "zh"
    assert resp.mimetype == "application/pdf"
    disposition = resp.headers.get("Content-Disposition", "")
    assert "attachment" in disposition
    assert f"{rid}.zh.pdf" in disposition
    # An explicit bogus language fails; it never silently returns the primary PDF.
    bad = client.get(f"/api/report/{rid}/pdf?lang=fr")
    assert bad.status_code == 400
    assert captured["lang"] == "zh"


def test_api_pdf_disabled_is_typed_service_error(client, reports_tmp, monkeypatch):
    rid = "report_api_pdf_disabled"
    _publish_primary(rid)
    monkeypatch.setattr(Config, "REPORT_PDF_EXPORT", False)

    response = client.get(f"/api/report/{rid}/pdf")
    assert response.status_code == 503
    assert response.get_json()["code"] == "pdf_export_disabled"


def test_api_pdf_internal_error_does_not_leak_traceback(
    client, reports_tmp, monkeypatch,
):
    rid = "report_api_pdf_internal"
    _publish_primary(rid)

    def _explode(cls, report_id, force=False, lang=None):
        raise RuntimeError("private renderer detail")

    monkeypatch.setattr(ReportManager, "export_pdf", classmethod(_explode))
    response = client.get(f"/api/report/{rid}/pdf")
    payload = response.get_json()
    assert response.status_code == 500
    assert payload["code"] == "pdf_internal_error"
    assert "traceback" not in payload
    assert "private renderer detail" not in json.dumps(payload)
