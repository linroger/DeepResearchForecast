"""ADR 0003 slice S3, T10 — the bridge in the language variant.

``render_sim_bridge(chinese=True)`` is byte-stable, carries exactly the numbers of the
English rendering (dates and quantities included, through the translation parity helpers),
and is inserted into the translated variant at the world-appendix site by re-rendering —
never by translating the English block.
"""
from __future__ import annotations

import itertools
import json
import re
from pathlib import Path

import pytest

from app.config import Config
from app.services import report_agent as ra
from app.services import report_lint as rl
from app.services import sim_provenance as sp
from app.services.report_agent import ReportAgent, ReportManager
from tests.test_sim_bridge_isolation import (  # noqa: F401 — fixtures and the harness
    FORECAST, TOKENS, ScriptedModel, _record_fixture, make_agent, report_config, write_sim,
)

CHARTS = [
    {"id": "worldstate_trajectory", "path": "charts/worldstate_trajectory.html",
     "image": "charts/worldstate_trajectory.png"},
    {"id": "world_variables", "path": "charts/world_variables.html", "image": ""},
]
SPINE = {"scenarios": [{"name": "Truce holds", "probability": 0.6},
                       {"name": "Détente", "probability": 0.4}]}
WHATIF = ReportAgent._render_comparison_table({
    "scenario_label": "tariff shock",
    "dimensions": [{"name": "Truce holds", "baseline": "50.0%", "scenario": "42.0%",
                    "delta": "-8.0 pp", "verdict": "更不可能"}]})


def _both(record, **kwargs):
    en = ra.render_sim_bridge(record, chinese=False, **kwargs)
    zh = ra.render_sim_bridge(record, chinese=True, **kwargs)
    return en, zh


@pytest.mark.parametrize("name", ["en", "zh", "paths", "hollow"])
def test_chinese_rendering_is_byte_stable_with_numeric_heading_and_table_parity(name):
    record = _record_fixture(name)
    kwargs = dict(spine=SPINE, chart_rel_paths=CHARTS, whatif_table_md=WHATIF, record_sha256="f00d")
    en, zh = _both(record, **kwargs)
    assert zh == ra.render_sim_bridge(record, chinese=True, **kwargs)   # byte-stable
    assert en != zh
    assert zh.startswith(sp.BRIDGE_START + "\n## " + sp.BRIDGE_TITLE_ZH) and zh.endswith(sp.BRIDGE_END)
    assert sp.SIM_BANNER_ZH in zh and sp.SIM_BANNER_EN not in zh
    if name == "hollow":
        assert sp.CHART_OUTCOME_SHARES_ZH not in zh and sp.CHART_WORLD_VARIABLES_ZH not in zh
        assert ra._SIM_BRIDGE_TEXT["zh"]["shares_h"] not in zh
    else:
        assert sp.CHART_OUTCOME_SHARES_ZH in zh and sp.CHART_WORLD_VARIABLES_ZH in zh
        assert ra._SIM_BRIDGE_TEXT["zh"]["unchanged"].format(policy="diagnostic_only") in zh
    # every number in the bridge agrees between the two languages (dates/amounts canonicalized
    # exactly as the translation publication audit does), as do heading levels and table rows
    assert ReportAgent._translation_fact_multiset(en) == ReportAgent._translation_fact_multiset(zh)
    assert ReportAgent._translation_number_multiset(en) == ReportAgent._translation_number_multiset(zh)
    assert ReportAgent._translation_heading_signature(en) == ReportAgent._translation_heading_signature(zh)
    assert ReportAgent._translation_table_signature(en) == ReportAgent._translation_table_signature(zh)
    assert ReportAgent._translation_fence_signature(en) == ReportAgent._translation_fence_signature(zh) == []
    # the fenced block is invisible to the lint in either language and byte-stable through it
    for block in (en, zh):
        assert rl.leakage_hits(block) == []
        for lang in ("English", "Chinese"):
            out, rep = rl.lint_report(block, lang, mode="final")
            assert out == block and rep["changed"] is False


def test_variant_gets_the_bridge_only_when_the_primary_carries_exactly_one(monkeypatch, tmp_path):
    agent = ReportAgent.__new__(ReportAgent)
    agent.output_language = "English"
    agent.simulation_id = "sim_variant"
    record = _record_fixture("paths")
    rendered = {}

    def fake_render(self, report_id, *, chinese):
        rendered["chinese"] = chinese
        return ra.render_sim_bridge(record, chinese=chinese, spine=SPINE, chart_rel_paths=None,
                                    whatif_table_md="", record_sha256="beef")

    monkeypatch.setattr(ReportAgent, "_render_sim_bridge_for_report", fake_render)
    en_block = ra.render_sim_bridge(record, chinese=False, spine=SPINE, chart_rel_paths=None,
                                    whatif_table_md="", record_sha256="beef")
    source = "# R\n\n## A\n\nProse.\n\n" + en_block + "\n\n## References\n\n1. [S1] x\n"
    translated = "# 报告\n\n## 甲\n\n正文。\n\n## 参考来源\n\n1. [S1] x\n"
    out = agent._insert_sim_bridge_variant("rid", source, translated, chinese=True)
    blocks = ra._sim_bridge_blocks(out)
    assert rendered == {"chinese": True}
    assert len(blocks) == 1 and sp.BRIDGE_TITLE_ZH in blocks[0] and sp.BRIDGE_TITLE_EN not in out
    assert out.index(sp.BRIDGE_END) < out.index("## 参考来源")
    # no bridge in the primary → none in the variant (policy is never inferred from the environment)
    assert agent._insert_sim_bridge_variant("rid", "# R\n\nProse.\n", translated, chinese=True) == translated
    # the primary's English block is stripped from what the translator is asked to translate
    assert sp.BRIDGE_START not in ra._sim_prose(source) and "## A" in ra._sim_prose(source)


# ── end to end: a real variant generation with a deterministic stand-in translator ──────

_CN_DIGITS = "〇一二三四五六七八九"
# Kept verbatim: ISO dates, citation tokens, URLs, identifiers that embed digits (``F1`` is not
# a number for the parity regex in either language, so it must stay whole) and numbers.
_PROTECTED = re.compile(
    r"\d{4}-\d{2}-\d{2}|\[S\d+\]|https?://\S+|(?<![A-Za-z0-9_])[A-Za-z_]+\d[A-Za-z0-9_]*"
    r"|(?<![A-Za-z0-9_])[-+]?\d[\d,]*(?:\.\d+)?\s*%?")


def _cn(n: int) -> str:
    return "".join(_CN_DIGITS[int(d)] for d in str(n))


def _zh_words(text: str, counter) -> str:
    """Replace every non-numeric run with unique Chinese text; numbers, dates and citation
    tokens survive byte-for-byte so the publication audit's parity checks hold."""
    parts, pos = [], 0
    for match in _PROTECTED.finditer(text):
        if text[pos:match.start()].strip():
            parts.append("中文" + _cn(next(counter)))
        parts.append(match.group(0))
        pos = match.end()
    if text[pos:].strip():
        parts.append("中文" + _cn(next(counter)) + "。")
    return "".join(parts) if parts else text


def _fake_translate(self, chunks, tgt_code, tgt_name, *, label, progress=None):
    counter = itertools.count(1)
    out = []
    for chunk in chunks:
        lines = []
        for line in chunk.split("\n"):
            stripped = line.strip()
            if not stripped or stripped.startswith("<!--") or re.match(r"^\|?\s*:?-{3,}", stripped):
                lines.append(line)
                continue
            heading = re.match(r"^(\s*#{1,6}\s+)(.*)$", line)
            if heading:
                lines.append(heading.group(1) + _zh_words(heading.group(2), counter))
                continue
            if stripped.startswith("|"):
                cells = line.split("|")
                lines.append("|".join(c if (not c.strip() or _PROTECTED.fullmatch(c.strip()))
                                      else " " + _zh_words(c.strip(), counter) + " " for c in cells))
                continue
            prefix = re.match(r"^(\s*(?:>\s*|[-*+]\s+|\d+[.)]\s+)?)", line).group(1)
            lines.append(prefix + _zh_words(line[len(prefix):], counter))
        out.append("\n".join(lines))
    return out, []


def test_translated_variant_carries_the_rerendered_chinese_bridge(report_config, monkeypatch):
    monkeypatch.setattr(Config, "REPORT_BILINGUAL", True, raising=False)
    monkeypatch.setattr(ReportAgent, "_translate_chunks_with_integrity", _fake_translate)
    monkeypatch.setattr(ReportAgent, "_start_dashboard_localization", lambda self, *a, **k: None)
    audits = []
    original_audit = ReportAgent._audit_translation_variant

    def spy_audit(self, *args, **kwargs):
        result = original_audit(self, *args, **kwargs)
        audits.append(result[0])
        return result

    monkeypatch.setattr(ReportAgent, "_audit_translation_variant", spy_audit)
    root = Path(Config.OASIS_SIMULATION_DATA_DIR)
    write_sim(root, "sim_bridge_zh", shares={"Expansion": 0.44, "Status quo": 0.56}, token=TOKENS[0])
    model = ScriptedModel()
    agent = make_agent("sim_bridge_zh", model)
    report = agent.generate_report(report_id="report_bridge_zh")
    assert report.status.value == "completed", report.error
    en_blocks = ra._sim_bridge_blocks(report.markdown_content)
    assert len(en_blocks) == 1
    status = ReportManager.translation_status(report.report_id, "zh", report=report)
    diagnostics = {"status": status, "issues": [a.get("issues") for a in audits],
                   "number_diff": [a.get("number_parity", {}).get("diff") for a in audits]}
    assert report.translations and report.translations[0]["lang"] == "zh", diagnostics
    zh_md = Path(ReportManager._get_report_translation_path(report.report_id, "zh")).read_text(encoding="utf-8")
    zh_blocks = ra._sim_bridge_blocks(zh_md)
    assert len(zh_blocks) == 1
    assert zh_blocks[0] == agent._render_sim_bridge_for_report(report.report_id, chinese=True)
    assert zh_blocks[0] != en_blocks[0]
    assert sp.BRIDGE_TITLE_ZH in zh_blocks[0] and sp.BRIDGE_TITLE_EN not in zh_md
    assert TOKENS[0] in zh_blocks[0] and TOKENS[0] not in ra._sim_prose(zh_md)
    # the Chinese bridge was rendered, not translated: the stand-in translator never saw it
    assert "中文" not in zh_blocks[0]
    # numeric parity between the two bridges, and between the two whole documents
    assert ReportAgent._translation_fact_multiset(en_blocks[0]) == ReportAgent._translation_fact_multiset(zh_blocks[0])
    assert (ReportAgent._translation_fact_multiset(report.markdown_content)
            == ReportAgent._translation_fact_multiset(zh_md))
    audit = json.loads(Path(ReportManager._get_report_final_audit_path(report.report_id, "zh")).read_text())
    assert audit["section_parity"]["passed"] is True
    assert all(part["bytes_match"] for part in audit["simulation_bridge"].values())
    if "model_translation" in audit:
        from app.services.model_translation import valid_document_receipt
        proof = audit["model_translation"]
        target_body = "\n\n".join(row["target"] for row in proof["sections"]).strip() + "\n"
        assert valid_document_receipt(ra._sim_prose(report.markdown_content), target_body, "zh", proof)
        assert audit["fact_fidelity"]["passed"] is True
        assert all(token not in json.dumps(model.calls) for token in TOKENS)
        assert status["available"] is True, status
    else:
        assert audit["number_parity"]["passed"] is True
        assert audit["table_parity"]["passed"] is True


@pytest.mark.parametrize('injected', [
    sp.BRIDGE_START + '\n模拟结果显示需求增长。\n' + sp.BRIDGE_END,
    sp.BRIDGE_START + '\n模拟结果显示需求增长。',
    sp.BRIDGE_END,
])
def test_translation_cannot_invent_a_lint_exempt_bridge(report_config, injected):
    agent = make_agent('sim_variant_rejected', ScriptedModel())
    audit, _ = agent._audit_translation_variant(
        'report_variant_rejected', '# Outlook\n\nObserved facts.',
        '# 展望\n\n观察事实。\n' + injected, 'en', 'zh', enforce_citations=False)
    assert not audit['hard_passed']
    assert any('simulation bridge' in issue for issue in audit['issues'])


def test_translation_bridge_must_match_exact_target_bytes(report_config):
    write_sim(Path(Config.OASIS_SIMULATION_DATA_DIR), 'sim_variant_tampered',
              shares={'Expansion': 0.44, 'Status quo': 0.56}, token=TOKENS[0])
    agent = make_agent('sim_variant_tampered', ScriptedModel())
    rid = 'report_variant_tampered'
    en = agent._render_sim_bridge_for_report(rid, chinese=False)
    zh = agent._render_sim_bridge_for_report(rid, chinese=True)
    good, _ = agent._audit_translation_variant(rid, en, zh, 'en', 'zh', enforce_citations=False)
    assert good['hard_passed'], good['issues']
    bad, _ = agent._audit_translation_variant(rid, en, zh.replace('声明假设下的模拟', '这是现实观察事实'),
                                             'en', 'zh', enforce_citations=False)
    assert not bad['hard_passed']
    assert any('simulation bridge' in issue for issue in bad['issues'])


@pytest.mark.skipif(not hasattr(ReportAgent, '_audit_model_translation_variant'),
                    reason='reviewed model translator is an independent working-tree integration')
def test_model_review_receipt_cannot_authorize_a_changed_bridge(report_config):
    from app.services.model_translation import translate_document
    write_sim(Path(Config.OASIS_SIMULATION_DATA_DIR), 'sim_model_bridge_gate',
              shares={'Expansion': 0.44, 'Status quo': 0.56}, token=TOKENS[0])
    agent = make_agent('sim_model_bridge_gate', ScriptedModel())
    rid = 'report_model_bridge_gate'
    source_body = '# Outlook\n\nThe ministry reports capacity of 25 MW.\n'
    en = agent._render_sim_bridge_for_report(rid, chinese=False)
    source = ra._insert_sim_bridge(source_body, en)
    translated, proof = translate_document(agent.llm, ra._sim_prose(source), 'zh')
    target = agent._insert_sim_bridge_variant(rid, source, translated, chinese=True)
    audit, _ = agent._audit_translation_variant(rid, source, target, 'en', 'zh',
                                               enforce_citations=False, model_proof=proof)
    assert audit['hard_passed'], audit['issues']
    for changed in (target.replace('声明假设下的模拟', '这是现实观察事实'),
                    target + sp.BRIDGE_START, target + '\n未经审阅的额外断言。\n'):
        audit, _ = agent._audit_translation_variant(rid, source, changed, 'en', 'zh',
                                                   enforce_citations=False, model_proof=proof)
        assert not audit['hard_passed']
        assert any('simulation bridge' in issue for issue in audit['issues'])
    # Valid prose review is not permission to invent a bridge for a bridge-free primary.
    source_body = ra._sim_prose(source)
    audit, _ = agent._audit_translation_variant(rid, source_body, target, 'en', 'zh',
                                               enforce_citations=False, model_proof=proof)
    assert not audit['hard_passed']
    assert any('simulation bridge' in issue for issue in audit['issues'])
