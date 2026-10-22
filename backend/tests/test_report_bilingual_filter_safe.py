"""Bilingual pass vs. the provider content filter (FILTER-SAFE, REPORT_BILINGUAL_FILTER_SAFE).

Live defect (report_0f2e07d62a34, glm-5.3 through the coding-plan endpoint): sixteen
translation calls were rejected with HTTP 400 code 1301, the affected text stayed in
English silently, the repair passes were rejected the same way, and the whole Chinese
version was lost to its own audit ("2 target-language contamination lines").  The same
run's numeric-parity failure was a second defect: two restored placeholders fused
("2025-Q4" + "3667亿美元" → "2025-Q43667亿美元", read by the amount parser as 43667亿).

Pins: a content-filtered unit is split smaller and retried once with the translation
directive (never with the generation rung's "refer to leaders by office" wording, which
is itself filtered); a unit rejected again keeps its source bytes and is disclosed with
its chunk and reason; the ladder outcome is memoised so the integrity retry and the
residual-line repair never replay the rejected request; a section that still drifts on a
hard invariant after its retry is kept verbatim and disclosed; the audit treats
disclosed lines as a partial translation (published, status "partial") while undisclosed
contamination and number drift still fail closed; the knob restores the previous
all-or-nothing behaviour; transient provider errors and the primary report's purity
path (ladder not armed) are unchanged; the restore guard keeps fused numeric tokens
apart.
"""

from __future__ import annotations

import json
import os
import re
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.config import Config  # noqa: E402
from app.services import report_filter_safe as fs  # noqa: E402
from app.services import report_lint as rl  # noqa: E402
from app.services.report_agent import ReportAgent, ReportManager  # noqa: E402
from tests.test_report_bilingual import _publish_primary  # noqa: E402

ZH = "简体中文（Simplified Chinese）"

FILTER_TEXT = (
    "Error code: 400 - {'contentFilter': [{'level': 1, 'role': 'assistant'}], 'error': "
    "{'code': '1301', 'message': '系统检测到输入或生成内容可能包含不安全或敏感内容'}}"
)


class _ContentFilterError(Exception):
    pass


SENSITIVE_1 = (
    "The two leaders traded accusations over the tariff truce and the chip export "
    "licences in a long and bitter exchange that the provider filter rejects."
)
SENSITIVE_2 = (
    "A second sensitive paragraph about the same leaders and the same export licences "
    "that the provider filter also rejects on every single attempt."
)
OUTLOOK_LINE = "The Outlook base case holds at 42% while the escalation path sits at 21%."

SRC = f"""# Trade Outlook Report

> A concise Outlook of the 2027 trade posture.

## Executive Summary

{OUTLOOK_LINE}

{SENSITIVE_1}

{SENSITIVE_2}

## Scenarios & Data

| Scenario | Probability | Note |
|---|---|---|
| Base | 42% | steady |
| Escalation | 21% | tail |
"""

_REPLACEMENTS = {
    "# Trade Outlook Report": "# 贸易展望报告",
    "> A concise Outlook of the 2027 trade posture.": "> 2027 年贸易形势简报。",
    "## Executive Summary": "## 执行摘要",
    OUTLOOK_LINE: "基准情景为 42%，升级路径为 21%。",
    SENSITIVE_1: "两位领导人就关税休战与芯片出口许可相互指责，提供方审查拒绝了这段长篇激烈交锋。",
    SENSITIVE_2: "第二段关于同一批领导人与出口许可的敏感内容，每一次尝试都被提供方拒绝。",
    "## Scenarios & Data": "## 情景与数据",
    "| Scenario | Probability | Note |": "| 情景 | 概率 | 备注 |",
    "| Base | 42% | steady |": "| 基准 | 42% | 稳定 |",
    "| Escalation | 21% | tail |": "| 升级 | 21% | 尾部 |",
}


def _translate(user: str) -> str:
    return "\n".join(_REPLACEMENTS.get(line, line) for line in user.splitlines())


class _FilterLLM:
    """Scripted translator that raises the provider's content-filter error.

    Every request whose user content carries one of ``sensitive`` sentences is
    rejected; with ``pass_with_directive`` the rejection stops once the translation
    directive is in the system prompt (the register retry succeeds).  ``translate``
    answers everything else.  ``error`` lets a test simulate a transient outage.
    """

    model = "fake-translator"
    provider = "fake"

    def __init__(self, translate=_translate, *, sensitive=(SENSITIVE_1, SENSITIVE_2),
                 pass_with_directive=False, error=None):
        self.calls = []
        self._translate = translate
        self._sensitive = tuple(sensitive)
        self._pass = pass_with_directive
        self._error = error

    def _rejects(self, system: str, user: str) -> bool:
        if not any(sentence in user for sentence in self._sensitive):
            return False
        if self._pass and fs.translation_register_directive() in system:
            return False
        return True

    def _record(self, kind, messages):
        system = messages[0]["content"]
        user = ReportAgent._decode_translation_placeholders(messages[-1]["content"])
        self.calls.append({"kind": kind, "system": system, "user": user})
        if self._rejects(system, user):
            raise (self._error or _ContentFilterError(FILTER_TEXT))
        return user

    def chat(self, messages=None, temperature=0.7, max_tokens=4096, tier="strong", **_kw):
        return self._translate(self._record("chat", messages))

    def chat_json(self, messages=None, **_kw):
        self._record("chat_json", messages)
        return {}


def _worker(llm, armed=True, source=SRC):
    worker = ReportAgent.__new__(ReportAgent)
    worker.llm = llm
    worker.output_language = "English"
    worker.simulation_id = "sim_test"
    worker.graph_id = "graph_test"
    worker._forecast_spine = None
    worker._translation_call_failures = 0
    if armed:
        worker._reset_translation_filter_safe_state(source)
    return worker


def _directive_calls(llm):
    return [c for c in llm.calls if fs.translation_register_directive() in c["system"]]


def _sensitive_calls(llm, sentence):
    return [c for c in llm.calls if sentence in c["user"]]


@pytest.fixture
def reports_tmp(tmp_path, monkeypatch):
    d = tmp_path / "reports"
    d.mkdir()
    monkeypatch.setattr(ReportManager, "REPORTS_DIR", str(d))
    monkeypatch.setattr(Config, "REPORT_TRANSLATION_CONCURRENCY", 1)
    return str(d)


# ───────────────────────────── directive ─────────────────────────────
def test_translation_directive_keeps_names_and_leaves_generation_rung_alone():
    directive = fs.translation_register_directive()
    assert "exactly as written in the source" in directive
    assert "不得以职务描述替代人名" in directive
    # The generation rung asks for offices instead of names; the translation rung must not.
    assert "by office" in fs.register_directive(1)
    assert "by office" not in directive
    assert "Institutional-register mode" in fs.register_directive(1)
    assert "Institutional-register mode" not in directive


# ───────────────────────── per-unit ladder ──────────────────────────
def test_filtered_unit_is_split_smaller_and_retried_with_directive():
    llm = _FilterLLM(pass_with_directive=True)
    worker = _worker(llm)
    chunk = ReportAgent._split_markdown_h2_sections(SRC)[1]

    out = worker._translate_section(chunk, ZH, chunk_index=1)

    assert _REPLACEMENTS[SENSITIVE_1] in out and _REPLACEMENTS[SENSITIVE_2] in out
    assert "## 执行摘要" in out and "基准情景为 42%" in out
    first = llm.calls[0]
    assert SENSITIVE_1 in first["user"] and fs.translation_register_directive() not in first["system"]
    retries = _directive_calls(llm)
    assert retries, "the retry rung must carry the translation directive"
    assert all(len(c["user"]) < len(first["user"]) for c in retries)
    assert "by office" not in retries[0]["system"]
    assert worker._translation_verbatim_regions == []


def test_unit_rejected_on_the_retry_rung_is_kept_verbatim_and_disclosed():
    llm = _FilterLLM()
    worker = _worker(llm)
    chunk = ReportAgent._split_markdown_h2_sections(SRC)[1]

    out = worker._translate_section(chunk, ZH, chunk_index=1)

    assert SENSITIVE_1 in out and SENSITIVE_2 in out
    assert "## 执行摘要" in out and "基准情景为 42%" in out  # the clean pieces still translate
    regions = worker._translation_verbatim_regions
    assert [r["reason"] for r in regions] == ["content_filter", "content_filter"]
    assert all(r["scope"] == "unit" and r["chunk"] == 1 and r["heading"] == "Executive Summary"
               for r in regions)
    assert {r["sample"] for r in regions} == {SENSITIVE_1[:120], SENSITIVE_2[:120]}
    # Exactly one directive retry per rejected piece — no backoff loop, no replay:
    # the whole-unit call plus one piece call per sensitive paragraph.
    assert len(_sensitive_calls(llm, SENSITIVE_1)) == 2
    assert len(_sensitive_calls(llm, SENSITIVE_2)) == 2
    assert worker._translation_call_failures == 3


def test_ladder_outcome_is_memoised_so_rejected_units_are_never_replayed():
    llm = _FilterLLM()
    worker = _worker(llm)

    first = worker._translate_markdown_unit(SENSITIVE_1, ZH, chunk_index=1)
    calls_after_first = len(llm.calls)
    second = worker._translate_markdown_unit(SENSITIVE_1, ZH, "6. INTEGRITY RETRY", chunk_index=1)

    assert first == SENSITIVE_1 == second
    assert calls_after_first == 2 and len(llm.calls) == 2
    assert len(worker._translation_verbatim_regions) == 1


def test_transient_provider_error_keeps_source_without_disclosure():
    llm = _FilterLLM(error=RuntimeError("simulated provider outage"))
    worker = _worker(llm)

    out = worker._translate_markdown_unit(SENSITIVE_1, ZH, chunk_index=1)

    assert out == SENSITIVE_1
    assert len(llm.calls) == 1 and _directive_calls(llm) == []
    assert worker._translation_verbatim_regions == []
    assert worker._translation_call_failures == 1


def test_unarmed_worker_keeps_the_previous_single_call_behaviour():
    """The primary report's purity retranslation shares this code and must not change."""
    llm = _FilterLLM()
    worker = _worker(llm, armed=False)

    out = worker._translate_markdown_unit(SENSITIVE_1, ZH)

    assert out == SENSITIVE_1
    assert len(llm.calls) == 1 and _directive_calls(llm) == []
    assert not getattr(worker, "_translation_verbatim_regions", None)


def test_knob_off_disarms_the_ladder(monkeypatch):
    monkeypatch.setattr(Config, "REPORT_BILINGUAL_FILTER_SAFE", False)
    llm = _FilterLLM()
    worker = _worker(llm)

    out = worker._translate_markdown_unit(SENSITIVE_1, ZH, chunk_index=1)

    assert out == SENSITIVE_1
    assert len(llm.calls) == 1 and _directive_calls(llm) == []
    assert worker._translation_verbatim_regions == []


# ───────────────────── skeleton prose-slot fragments ─────────────────────
def test_prose_slot_rejected_with_directive_is_disclosed_as_fragment():
    table = (
        "| Scenario | Note |\n|---|---|\n"
        f"| Base | {SENSITIVE_1} |\n"
    )
    llm = _FilterLLM()
    worker = _worker(llm, source=f"## Table\n\n{table}")

    out = worker._translate_from_source_skeleton(table, ZH, chunk_index=0)

    assert SENSITIVE_1 in out and out.count("|") == table.count("|")
    regions = worker._translation_verbatim_regions
    assert len(regions) == 1 and regions[0]["scope"] == "fragment"
    assert regions[0]["reason"] == "content_filter" and regions[0]["chunk"] == 0
    assert regions[0]["sample"] == SENSITIVE_1[:120]
    # The batch call carried no directive; the smaller batch / single call did.
    assert fs.translation_register_directive() not in _sensitive_calls(llm, SENSITIVE_1)[0]["system"]
    assert _directive_calls(llm)


# ───────────────────── section-level integrity fallback ─────────────────────
SRC_CLEAN = SRC.replace(f"{SENSITIVE_1}\n\n{SENSITIVE_2}\n\n", "")


def _drifting_translate(user: str) -> str:
    """Faithful except that the 21% escalation share is dropped from the summary line."""
    out = _translate(user)
    return out.replace("基准情景为 42%，升级路径为 21%。", "基准情景为 42%，升级路径随之上升。")


def _drifting_section_translator(worker):
    """Section translator whose numeric drift survives the unit-level checks.

    The whole-unit translator already discards a drifted candidate (structure-preserving
    fallback), so the section-level fallback is exercised by stubbing the section call —
    the live defect reached this level through a parser-level fusion the unit checks
    could not see.
    """
    worker._section_translation_calls = []

    def _section(section_md, target_language_name, extra_rules="", *, chunk_index=None):
        worker._section_translation_calls.append((section_md, extra_rules, chunk_index))
        return _drifting_translate(section_md)
    worker._translate_section = _section
    return worker


def test_section_with_unrecoverable_number_drift_is_kept_verbatim_and_disclosed():
    chunks = ReportAgent._split_markdown_h2_sections(SRC_CLEAN)
    worker = _drifting_section_translator(_worker(_FilterLLM(sensitive=()), source=SRC_CLEAN))

    translated, drift = worker._translate_chunks_with_integrity(chunks, "zh", ZH, label="t")

    assert drift == []
    assert translated[1] == chunks[1]  # verbatim source section
    assert translated[0].startswith("# 贸易展望报告") and "| 基准 | 42% | 稳定 |" in translated[2]
    regions = worker._translation_verbatim_regions
    assert len(regions) == 1 and regions[0]["reason"] == "integrity"
    assert regions[0]["scope"] == "section" and regions[0]["chunk"] == 1
    assert regions[0]["heading"] == "Executive Summary"
    assert "numeric tokens" in regions[0]["detail"]
    repair_calls = [call for call in worker._section_translation_calls
                    if "NUMERIC SURGICAL REPAIR" in call[1]]
    assert len(repair_calls) == 1 and repair_calls[0][2] == 1


def test_armed_small_numeric_repair_keeps_only_an_exact_candidate():
    chunks = ReportAgent._split_markdown_h2_sections(SRC_CLEAN)
    worker = _worker(_FilterLLM(sensitive=()), source=SRC_CLEAN)
    calls = []

    def translate(section_md, target_language_name, extra_rules="", *, chunk_index=None):
        calls.append((section_md, extra_rules, chunk_index))
        return (_translate(section_md) if "NUMERIC SURGICAL REPAIR" in extra_rules
                else _drifting_translate(section_md))

    worker._translate_section = translate
    translated, drift = worker._translate_chunks_with_integrity(chunks, "zh", ZH, label="t")

    repair_calls = [call for call in calls if "NUMERIC SURGICAL REPAIR" in call[1]]
    assert len(repair_calls) == 1 and repair_calls[0][2] == 1
    assert len([call for call in calls if call[0] == chunks[1]]) == 3  # first + integrity + numeric
    assert translated[1] == _translate(chunks[1]) and drift == []
    assert worker._translation_verbatim_regions == []
    for source, variant in zip(chunks, translated):
        assert worker._translation_chunk_quality(source, variant, "zh")["hard"] == []


def test_knob_off_keeps_the_drifted_section_as_before(monkeypatch):
    monkeypatch.setattr(Config, "REPORT_BILINGUAL_FILTER_SAFE", False)
    chunks = ReportAgent._split_markdown_h2_sections(SRC_CLEAN)
    worker = _drifting_section_translator(_worker(_FilterLLM(sensitive=()), source=SRC_CLEAN))

    translated, _drift = worker._translate_chunks_with_integrity(chunks, "zh", ZH, label="t")

    assert "升级路径随之上升" in translated[1]
    assert worker._translation_verbatim_regions == []
    assert not any("NUMERIC SURGICAL REPAIR" in call[1] for call in worker._section_translation_calls)
    assert len([call for call in worker._section_translation_calls if call[0] == chunks[1]]) == 2


# ─────────────────────────── audit semantics ───────────────────────────
_AUDIT_SRC = (
    "# Report\n\n## Part\n\n"
    "First paragraph of the source report with the probability at 42%.\n\n"
    f"{SENSITIVE_1}\n\n{SENSITIVE_2}\n\n"
    "Fourth paragraph of the source report that translates cleanly every time.\n"
)
_AUDIT_VARIANT = (
    "# 报告\n\n## 部分\n\n"
    "源报告的第一段，概率为 42%。\n\n"
    f"{SENSITIVE_1}\n\n{SENSITIVE_2}\n\n"
    "源报告的第四段，每次都能顺利翻译。\n"
)


def _audit(worker, variant=_AUDIT_VARIANT, source=_AUDIT_SRC):
    audit, _citations = worker._audit_translation_variant(
        "report_audit", source, variant, "en", "zh", {}, enforce_citations=False,
        verbatim_regions=worker._translation_verbatim_regions,
    )
    return audit


def test_audit_treats_disclosed_lines_as_partial_and_undisclosed_as_contamination():
    worker = _worker(_FilterLLM(), source=_AUDIT_SRC)
    worker._record_translation_verbatim_region(SENSITIVE_1, "content_filter", scope="unit")
    worker._record_translation_verbatim_region(SENSITIVE_2, "content_filter", scope="unit")

    audit = _audit(worker)

    assert audit["hard_passed"] is True, audit["issues"]
    assert audit["residual_source_lines"] == {
        "count": 0, "disclosed": 2, "tolerance": 1,
        "samples": audit["residual_source_lines"]["samples"],
    }
    assert audit["partial"]["disclosed_lines"] == 2 and audit["partial"]["undisclosed_lines"] == 0
    regions = audit["partial"]["verbatim_regions"]
    assert [r["chunk"] for r in regions] == [1, 1] and regions[0]["heading"] == "Part"
    assert regions[0]["kept_lines"] == 1 and "key" not in regions[0]
    assert any(w.startswith("partial translation: 2 source-language region(s)") for w in audit["warnings"])

    # Only one of the two lines disclosed: the other is real contamination (within tolerance).
    worker = _worker(_FilterLLM(), source=_AUDIT_SRC)
    worker._record_translation_verbatim_region(SENSITIVE_1, "content_filter", scope="unit")
    audit = _audit(worker)
    assert audit["hard_passed"] is True
    assert audit["residual_source_lines"]["count"] == 1
    assert audit["residual_source_lines"]["disclosed"] == 1

    # Nothing disclosed: the previous fail-closed verdict is unchanged.
    audit = _audit(_worker(_FilterLLM(), source=_AUDIT_SRC))
    assert audit["hard_passed"] is False
    assert "translation contains 2 target-language contamination lines" in audit["issues"]
    assert "partial" not in audit and audit["residual_source_lines"]["disclosed"] == 0


def test_audit_still_rejects_undisclosed_contamination_beyond_tolerance_and_number_drift():
    # Two lines nobody disclosed (the tolerance for this short body is one line).
    variant = _AUDIT_VARIANT.replace(
        "源报告的第四段，每次都能顺利翻译。",
        "A third untranslated paragraph that nobody disclosed and the model simply refused.",
    ).replace(
        "源报告的第一段，概率为 42%。",
        "First paragraph of the source report with the probability at 42%.",
    )
    worker = _worker(_FilterLLM(), source=_AUDIT_SRC)
    worker._record_translation_verbatim_region(SENSITIVE_1, "content_filter", scope="unit")
    worker._record_translation_verbatim_region(SENSITIVE_2, "content_filter", scope="unit")

    audit = _audit(worker, variant=variant)
    assert audit["hard_passed"] is False
    assert "translation contains 2 target-language contamination lines" in audit["issues"]
    assert audit["partial"]["disclosed_lines"] == 2 and audit["partial"]["undisclosed_lines"] == 2

    drifted = _AUDIT_VARIANT.replace("概率为 42%", "概率为 24%")
    audit = _audit(worker, variant=drifted)
    assert audit["hard_passed"] is False
    assert "translation numeric-token multiset differs from primary" in audit["issues"]


def test_region_translated_later_by_the_repair_pass_is_not_disclosed():
    worker = _worker(_FilterLLM(), source=_AUDIT_SRC)
    worker._record_translation_verbatim_region(SENSITIVE_1, "content_filter", scope="unit")
    worker._record_translation_verbatim_region(SENSITIVE_2, "content_filter", scope="unit")
    variant = _AUDIT_VARIANT.replace(SENSITIVE_1, _REPLACEMENTS[SENSITIVE_1])

    audit = _audit(worker, variant=variant)

    assert audit["hard_passed"] is True
    assert len(audit["partial"]["verbatim_regions"]) == 1
    assert audit["partial"]["verbatim_regions"][0]["sample"] == SENSITIVE_2[:120]


def test_language_contamination_lines_is_the_detector_walk():
    md = (
        "# 标题\n\n```\nfenced english text with many words inside the fence stays\n```\n\n"
        f"{SENSITIVE_1}\n\n中文行。\n\n## References\n\n- [S1] An English source title with many words\n"
    )
    rows = rl.language_contamination_lines(md, "Chinese")
    assert [line for _i, line, _runs in rows] == [SENSITIVE_1]
    assert rows[0][2] and rows[0][2][0].startswith("The two leaders")
    assert rl.detect_language_contamination(md, "Chinese") == {"lines": 1, "samples": [SENSITIVE_1[:90]]}


# ───────────────────── restore guard (live numeric defect) ─────────────────────
def test_restore_guard_keeps_fused_numeric_tokens_apart():
    src = "The series sits at $306.4 billion SAAR in 2026-Q2, below the 2025-Q4 peak of $366.7 billion."
    protected, mapping = ReportAgent._protect_translation_tokens(src, date_target="zh")
    # The live model dropped " peak of " and glued the quarter token to the amount token.
    candidate = (
        protected.replace("The series sits at ", "该序列处于").replace(" SAAR in ", "年化，于")
        .replace("below the ", "低于").replace(" peak of ", "")
    )
    fused, _issues = ReportAgent._restore_translation_tokens(candidate, mapping)
    guarded, issues = ReportAgent._restore_translation_tokens(candidate, mapping, separate_numbers=True)

    assert issues == []
    assert "2025-Q43667亿美元" in fused
    assert "2025-Q4 3667亿美元" in guarded
    assert ReportAgent._translation_fact_multiset(fused) != ReportAgent._translation_fact_multiset(src)
    assert ReportAgent._translation_fact_multiset(guarded) == ReportAgent._translation_fact_multiset(src)


def test_restore_guard_only_touches_fusing_neighbours():
    protected, mapping = ReportAgent._protect_translation_tokens("Growth of 42% in 2025 then 2026.")
    spaced = ReportAgent._decode_translation_placeholders(protected)
    assert ReportAgent._restore_translation_tokens(protected, mapping, separate_numbers=True)[0] == spaced
    glued = protected.replace(" then ", "")  # "...2025⟧⟦P…2026⟧" — digit against digit
    restored, _ = ReportAgent._restore_translation_tokens(glued, mapping, separate_numbers=True)
    assert "2025 2026" in restored
    protected, mapping = ReportAgent._protect_translation_tokens("Up 42% by 2025.", date_target="zh")
    candidate = "增长" + protected.split(" ", 1)[1].replace(" by ", "，到")
    restored, _ = ReportAgent._restore_translation_tokens(candidate, mapping, separate_numbers=True)
    assert "增长42%，到2025" in restored  # CJK neighbours never fuse, so no space is added


# ───────────────────────────── end to end ─────────────────────────────
def test_end_to_end_partial_translation_is_published_and_disclosed(reports_tmp):
    rid = "report_filter_partial"
    _publish_primary(rid, SRC)
    llm = _FilterLLM()

    status = ReportManager.generate_translation_variant(rid, "zh", llm_client=llm)

    assert status["available"] is True and status["status"] == "available"
    assert status["partial"] is True and status["can_update"] is True
    row = status["translation"]
    assert row["partial"] is True and row["residual_source_lines"] == 2
    chunks = row["verbatim_chunks"]
    assert len(chunks) == 2
    assert all(c["chunk"] == 1 and c["heading"] == "Executive Summary"
               and c["reason"] == "content_filter" and c["scope"] == "unit" for c in chunks)

    zh = open(ReportManager._get_report_translation_path(rid, "zh"), encoding="utf-8").read()
    assert SENSITIVE_1 in zh and SENSITIVE_2 in zh
    assert "基准情景为 42%" in zh and "| 基准 | 42% | 稳定 |" in zh and "## 情景与数据" in zh

    runtime = ReportManager._load_translation_runtime_status(rid, "zh")
    assert runtime["status"] == "partial" and runtime["progress"] == 100
    assert [c["sample"] for c in runtime["verbatim_chunks"]] == [SENSITIVE_1[:120], SENSITIVE_2[:120]]
    assert "issues" not in runtime
    assert any(w.startswith("partial translation") for w in runtime["warnings"])

    with open(ReportManager._get_report_path(rid), encoding="utf-8") as handle:
        meta = json.load(handle)
    entry = meta["translations"][0]
    assert entry["translation_quality"] == "partial" and len(entry["verbatim_chunks"]) == 2

    with open(ReportManager._get_report_final_audit_path(rid, "zh"), encoding="utf-8") as handle:
        audit = json.load(handle)
    assert audit["hard_passed"] is True and audit["partial"]["disclosed_lines"] == 2
    assert audit["residual_source_lines"]["count"] == 0

    # The primary report is untouched and the rejected requests were not replayed.
    assert open(ReportManager._get_report_markdown_path(rid), encoding="utf-8").read() == SRC
    directive = fs.translation_register_directive()
    unit_calls = [c for c in llm.calls if c["kind"] == "chat" and SENSITIVE_1 in c["user"]
                  and "Translate the following Markdown" in c["system"]]
    assert len(unit_calls) == 2 and directive in unit_calls[1]["system"]
    assert "by office" not in unit_calls[1]["system"]


def test_end_to_end_knob_off_rejects_the_variant_as_before(reports_tmp, monkeypatch):
    monkeypatch.setattr(Config, "REPORT_BILINGUAL_FILTER_SAFE", False)
    rid = "report_filter_legacy"
    _publish_primary(rid, SRC)
    llm = _FilterLLM()

    status = ReportManager.generate_translation_variant(rid, "zh", llm_client=llm)

    assert status["available"] is False and status["status"] == "failed"
    assert any("target-language contamination" in issue for issue in status["issues"])
    assert any("translation model call(s) failed" in issue for issue in status["issues"])
    assert _directive_calls(llm) == []
    assert not os.path.exists(ReportManager._get_report_translation_path(rid, "zh"))
    runtime = ReportManager._load_translation_runtime_status(rid, "zh")
    assert runtime["status"] == "failed" and runtime["verbatim_chunks"] == []


def test_end_to_end_directive_retry_publishes_a_full_translation(reports_tmp):
    rid = "report_filter_full"
    _publish_primary(rid, SRC)
    llm = _FilterLLM(pass_with_directive=True)

    status = ReportManager.generate_translation_variant(rid, "zh", llm_client=llm)

    assert status["available"] is True and status["partial"] is False
    assert status["can_update"] is False and status["translation"]["verbatim_chunks"] == []
    zh = open(ReportManager._get_report_translation_path(rid, "zh"), encoding="utf-8").read()
    assert _REPLACEMENTS[SENSITIVE_1] in zh and SENSITIVE_1 not in zh
    with open(ReportManager._get_report_path(rid), encoding="utf-8") as handle:
        meta = json.load(handle)
    assert meta["translations"][0]["translation_quality"] == "ok"
    assert "verbatim_chunks" not in meta["translations"][0]
    assert ReportManager._load_translation_runtime_status(rid, "zh")["status"] == "available"


# ───────────── FRED unit phrases in the binary-forecast table (live residual lines) ─────────────
# The 2026-10-17 live re-run of report_0f2e07d62a34 translated every filtered chunk, yet the
# audit still withheld the Chinese version: rows F4, F11 and F13 quote their FRED threshold
# as "25000 Millions of Dollars", which was not a recognised amount, so the frozen numeral
# made every faithful "250亿美元" fail the number guard and the rows stayed English
# (3 undisclosed lines against a tolerance of 1).
FRED_ROW_F4 = (
    "U.S. Imports of Goods by Customs Basis from China (fred:IMPCH) are below "
    "25000 Millions of Dollars in June 2027."
)
FRED_ROW_F13 = (
    "US goods imports from China (fred:IMPCH) fall below 20,000 millions of dollars in "
    "June 2027, sliding toward the June 2025 trough."
)
FRED_SRC = f"""# Trade Outlook Report

## Binary Forecasts

| ID | Statement | Probability | Resolution |
|---|---|---|---|
| F4 | {FRED_ROW_F4} | 35% | Resolves YES if fred:IMPCH < 25000 Millions of Dollars in 2027-06 (source: FRED). |
| F13 | {FRED_ROW_F13} | 15% | Resolves YES if fred:IMPCH < 20000 Millions of Dollars in 2027-06 (source: FRED/Census). |
"""

_FRED_ZH = [
    (r"^# Trade Outlook Report$", "# 贸易展望报告"),
    (r"^## Binary Forecasts$", "## 二元预测"),
    (r"^\| ID \| Statement \| Probability \| Resolution \|$", "| ID | 陈述 | 概率 | 判定 |"),
    (r"U\.S\. Imports of Goods by Customs Basis from China \(fred:IMPCH\) are below "
     r"(⟦Q[A-Z]+⟧) in (⟦D[A-Z]+⟧)\.",
     r"美国自中国商品进口额（海关口径）(fred:IMPCH) 在\2低于\1。"),
    (r"US goods imports from China \(fred:IMPCH\) fall below (⟦Q[A-Z]+⟧) in (⟦D[A-Z]+⟧), "
     r"sliding toward the (⟦D[A-Z]+⟧) trough\.",
     r"美国自中国商品进口额 (fred:IMPCH) 在\2跌破\1，滑向\3的低谷。"),
    (r"Resolves YES if fred:IMPCH < (⟦Q[A-Z]+⟧) in 2027-06 \(source: ([A-Za-z/]+)\)\.",
     r"若 fred:IMPCH 在 2027-06 低于\1，则判定为 YES（来源：\2）。"),
]


def _translate_fred(user: str) -> str:
    """Faithful translator: every ⟦Q…⟧ / ⟦D…⟧ token is copied where the amount or date belongs."""
    out = user
    for pattern, replacement in _FRED_ZH:
        out = re.sub(pattern, replacement, out, flags=re.M)
    return out


def test_binary_forecast_rows_with_fred_unit_phrases_translate_and_pass_the_number_guard(
    reports_tmp,
):
    rid = "report_fred_units"
    _publish_primary(rid, FRED_SRC)
    llm = _FilterLLM(_translate_fred, sensitive=())

    status = ReportManager.generate_translation_variant(rid, "zh", llm_client=llm)

    assert status["available"] is True and status["status"] == "available", status.get("issues")
    assert status["partial"] is False and status["translation"]["verbatim_chunks"] == []
    zh = open(ReportManager._get_report_translation_path(rid, "zh"), encoding="utf-8").read()
    assert ("| F4 | 美国自中国商品进口额（海关口径）(fred:IMPCH) 在2027年6月低于250亿美元。 | 35% | "
            "若 fred:IMPCH 在 2027-06 低于250亿美元，则判定为 YES（来源：FRED）。 |") in zh
    assert ("| F13 | 美国自中国商品进口额 (fred:IMPCH) 在2027年6月跌破200亿美元，滑向2025年6月的低谷。"
            " | 15% | 若 fred:IMPCH 在 2027-06 低于200亿美元，则判定为 YES（来源：FRED/Census）。 |") in zh
    assert "## 二元预测" in zh and "| ID | 陈述 | 概率 | 判定 |" in zh
    for english in ("Millions", "millions", "25000", "20,000", "20000", "June"):
        assert english not in zh
    # Every ⟦Q…⟧ the model saw was the whole phrase, already rendered in Chinese.
    unit_call = next(c for c in llm.calls if FRED_ROW_F4.split(" are below ")[0] in c["user"])
    assert "Millions of Dollars" not in unit_call["user"] and "25000" not in unit_call["user"]
    assert "⟦Q" in unit_call["user"]

    with open(ReportManager._get_report_final_audit_path(rid, "zh"), encoding="utf-8") as handle:
        audit = json.load(handle)
    assert audit["hard_passed"] is True and audit["number_parity"]["passed"] is True
    assert audit["residual_source_lines"]["count"] == 0
    assert audit["residual_source_lines"]["disclosed"] == 0
    assert ReportAgent._translation_fact_multiset(zh) == ReportAgent._translation_fact_multiset(FRED_SRC)
    assert open(ReportManager._get_report_markdown_path(rid), encoding="utf-8").read() == FRED_SRC
