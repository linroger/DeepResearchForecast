"""Saved-run shapes through raw translation, independent review and native audit.

The five failed saved rows retained English fallbacks, not model candidates.
These are exact source excerpts and explicit Mandarin fixtures, not a replay of
the missing responses or a claim about live model quality. Original section hashes:
war6 843f141bdfc29b015c188cddb2479930bbab9c961d8a2729929a2e5f8f375092
war10 c10f1f5609d1151447f32dd5712dd51c0651adcdaa6d0cd1a2e48404976914de
gold12 180a25961a0fc92018389011999bec93efb0c4a570ae499784c7594f4640e87d
gold16 a6ea9944836882634d2451f71b9e5103e18e529e2d404f095683d332ad13a1a8
gold17 76ccc389e10a7a6cb06c3c66d6d93a79ab269de1f602beccc768bc7445a7e2cd
"""
from copy import deepcopy
import hashlib
import json

import pytest

from app.services import model_translation as core


SHAPES = {
    "war6": (
        "## The War-State Continuum: Defining and Forecasting the End-2027 Position\n\n"
        "**(b) Grinding attritional conflict at reduced intensity.** The modal single outcome.",
        "## 战争状态连续谱：定义并预测2027年末的位置\n\n"
        "**(b) 强度降低的消耗战。** 最可能的单一结果。",
    ),
    "war10": (
        "## Key Actors and Decision Nodes: Putin, Zelensky, Washington, Brussels, and Beijing\n\n"
        "- **November 10, 2026 trilateral convening (Abu Dhabi).** Technical-level talks resuming is the base case; [S6] the flip signal is level and artifact.\n"
        "- lapse, narrowing, or congressional binding shifts US policy coercive — the pivot on which the ceasefire-versus-attrition balance turns.",
        "## 关键参与者与决策节点：普京、泽连斯基、华盛顿、布鲁塞尔和北京\n\n"
        "- **2026年11月10日三方会晤（阿布扎比）。** 重启技术级会谈是基准情景；[S6] 转向信号是级别和产出文件。\n"
        "- 失效、收窄或国会约束将美国政策推向施压——这是停火与消耗战平衡的支点。",
    ),
    "gold12": (
        "## Official-Sector Demand: Buyers, Sellers and the De-Dollarization Floor\n\n"
        "<!-- viz:charts/quantitative_claims.html -->\n"
        "![Comparable Forecast Benchmarks](charts/quantitative_claims.png)\n\n"
        "*Comparable Forecast Benchmarks*",
        "## 官方部门需求：买方、卖方与去美元化底部\n\n"
        "<!-- viz:charts/quantitative_claims.html -->\n"
        "![可比预测基准](charts/quantitative_claims.png)\n\n"
        "*可比预测基准*",
    ),
    "gold16": (
        "## Binary Forecast Ledger: Twelve Price Milestones with Resolution Criteria\n\n"
        "### Path Milestones: Intra-2027 Price Excursions\n\n"
        "**B1.\nThe bear scenario contributes almost nothing. Resolution: any LBMA a.m./p.m.\n\n**B2.",
        "## 二元预测账本：十二个价格里程碑及判定标准\n\n"
        "### 路径里程碑：2027年内价格波动\n\n"
        "**B1.\n熊市情景几乎没有贡献。判定：任一次LBMA上午或下午拍卖。\n\n**B2.",
    ),
    "gold17": (
        "## Forecast Summary Table, Calibration and Divergences\n\n"
        "### The Consolidated Forecast Table\n\n**Central distribution (LBMA p.m.\n\n"
        "| # | Scenario | Probability | Resolution band (LBMA p.m., 31 Dec 2027) | Core mechanism | Primary falsifier |\n"
        "|---|---|---|---|---|---|\n"
        "| 2 | Range-bound consolidation | **28%** | $3,800–$4,300 | — | — |",
        "## 预测汇总表、校准与分歧\n\n"
        "### 综合预测表\n\n**核心分布（LBMA下午拍卖\n\n"
        "| # | 情景 | 概率 | 判定区间（LBMA下午拍卖，2027年12月31日） | 核心机制 | 主要证伪条件 |\n"
        "|---|---|---|---|---|---|\n"
        "| 2 | 区间盘整 | **28%** | $3,800–$4,300 | — | — |",
    ),
}


def damaged(name, target):
    if name in {"war6", "war10"}:
        # Closing punctuation followed immediately by CJK loses parsed strong.
        return target.replace("。** ", "。**")
    if name == "gold12":
        return target.replace("charts/quantitative_claims.png", "charts/changed.png")
    if name == "gold16":
        return target.replace("**B1.", "**B1.**")
    return target.replace("**核心分布（LBMA下午拍卖", "**核心分布（LBMA下午拍卖**")


class Model:
    """Only the transport is substituted; the reviewer has a fixed target oracle."""
    model = "offline-run-structure"

    def __init__(self, first, faithful, *, repair=True, review=True):
        self.first, self.faithful = first, faithful
        self.repair, self.review = repair, review
        self.trace = []

    def chat(self, messages, **kwargs):
        payload = json.loads(messages[-1]["content"])
        self.trace.append(payload)
        if "entries" in payload:
            values = self.faithful if payload.get("repair") and self.repair else self.first
            return json.dumps({"translations": {k: values[s] for k, s in payload["entries"].items()}}, ensure_ascii=False)
        reviews = {}
        for key, pair in payload["pairs"].items():
            ok = self.review and pair["translation"] == self.faithful[pair["source"]]
            reviews[key] = {"faithful": ok, "complete": ok, "target_language": ok,
                            "issues": [] if ok else ["fixture fidelity mismatch"]}
        return json.dumps({"reviews": reviews})


def audit(source, target, proof, monkeypatch):
    from app.services.report_agent import ReportAgent, ReportManager
    # Keep the real read-only translation audit; there is no saved world in this fixture.
    monkeypatch.setattr(ReportManager, "load_world_result", classmethod(lambda cls, rid: None))
    return ReportAgent.__new__(ReportAgent)._audit_model_translation_variant(
        "report_offline_shapes", source, target, "en", "zh", {}, proof,
        enforce_citations=False,
    )[0]


@pytest.mark.parametrize("name", SHAPES)
def test_saved_shape_raw_repair_review_audit(name, tmp_path, monkeypatch):
    source, faithful = SHAPES[name]
    broken = damaged(name, faithful)
    assert core.structure_issues(source, broken), "negative fixture must reach the structure gate"
    assert not core.structure_issues(source, faithful), "Mandarin equivalent must retain parsed structure"
    model = Model({source: broken}, {source: faithful})
    target, proof = core.translate_document(model, source, "zh", max_calls=4)
    (tmp_path / (name + "-trace.json")).write_text(json.dumps({"trace": model.trace, "proof": proof}, ensure_ascii=False, indent=2))
    assert target == faithful + "\n" and core.valid_document_receipt(source, target, "zh", proof)
    assert "last_structure_failure" not in proof["sections"][0]
    repairs = [p for p in model.trace if p.get("repair")]
    assert len(repairs) == 1
    key = next(iter(repairs[0]["entries"]))
    assert repairs[0]["previous"][key] == broken
    feedback = repairs[0]["structure_feedback"][key]
    assert feedback["source_sha256"] == hashlib.sha256(source.encode()).hexdigest()
    assert feedback["differences"] and "path" in feedback["differences"][0]
    assert "expected" in feedback["differences"][0] and "actual" in feedback["differences"][0]
    reviews = [p for p in model.trace if "pairs" in p]
    assert len(reviews) == 1 and reviews[0]["pairs"][key] == {"source": source, "translation": faithful}
    assert audit(source, target, proof, monkeypatch)["hard_passed"]


@pytest.mark.parametrize("name", SHAPES)
def test_valid_mandarin_equivalence_needs_review_without_repair(name, monkeypatch):
    source, faithful = SHAPES[name]
    model = Model({source: faithful}, {source: faithful})
    target, proof = core.translate_document(model, source, "zh", max_calls=2)
    assert proof["calls_used"] == 2
    assert audit(source, target, proof, monkeypatch)["hard_passed"]
    assert not any(p.get("repair") for p in model.trace)


@pytest.mark.parametrize("damage", ["heading", "list", "table", "link", "code", "html", "citation", "grouped_citation", "suffix_citation"])
def test_structural_and_carrier_corruption_stays_rejected(damage, monkeypatch):
    source = ('## Evidence\n\n- Conditional [S1] [S9, S24] [S1-a].\n\n'
              '|Measure|Value|\n|---|---|\n|Capacity|25 MW|\n\n'
              '[Source](https://example.test/report?id=25)\n\n'
              '```python\ncapacity = 25\n```\n\n<!-- viz:charts/quantitative_claims.html -->')
    faithful = (source.replace('## Evidence', '## 证据').replace('Conditional', '附带条件')
                .replace('Measure', '指标').replace('Value', '数值').replace('Capacity', '产能')
                .replace('[Source]', '[来源]'))
    replacements = {
        "heading": ('## 证据', '### 证据'), "list": ('- 附带条件', '附带条件'),
        "table": ('|---|---|', '|---|---:|'),
        "link": ('report?id=25', 'report?id=26'), "code": ('capacity = 25', 'capacity = 26'),
        "html": ('claims.html', 'changed.html'), "citation": ('[S1]', '[S2]'),
        "grouped_citation": ('[S9, S24]', '[S9, S25]'),
        "suffix_citation": ('[S1-a]', '[S1-b]'),
    }
    bad = faithful.replace(*replacements[damage])
    model = Model({source: bad}, {source: faithful}, repair=False)
    target, proof = core.translate_document(model, source, "zh", max_calls=4)
    assert not proof["complete"] and not proof["sections"][0]["receipt"]
    assert not any("pairs" in p for p in model.trace)
    assert core.structure_issues(source, bad)
    assert not audit(source, target, proof, monkeypatch)["hard_passed"]


@pytest.mark.parametrize("damage", ["missing", "review", "source", "target", "context"])
def test_audit_still_requires_complete_source_bound_semantic_review(damage, monkeypatch):
    source, faithful = SHAPES["gold16"]
    model = Model({source: faithful}, {source: faithful})
    target, proof = core.translate_document(model, source, "zh", max_calls=2)
    proof = deepcopy(proof)
    if damage == "missing":
        proof["sections"][0]["receipt"] = None
    elif damage == "review":
        proof["sections"][0]["receipt"]["review"]["complete"] = False
    elif damage == "source":
        source += "\n\nA changed condition."
    elif damage == "target":
        target += "额外断言。"
    else:
        proof["context"] = "different outline"
    assert not audit(source, target, proof, monkeypatch)["hard_passed"]


def test_semantic_rejection_after_structure_repair_never_gets_a_receipt(monkeypatch):
    source, faithful = SHAPES["war6"]
    model = Model({source: damaged("war6", faithful)}, {source: faithful}, review=False)
    target, proof = core.translate_document(model, source, "zh", max_calls=4)
    assert len([p for p in model.trace if "pairs" in p]) == 1
    assert not proof["complete"] and not proof["sections"][0]["receipt"]
    assert not audit(source, target, proof, monkeypatch)["hard_passed"]


def test_grouped_citation_spacing_can_change_but_not_identities_or_counts(monkeypatch):
    source = "## Evidence\n\nThe claim is conditional [S1-a, S24]."
    faithful = "## 证据\n\n该论断附带条件 [S1-a,S24]。"
    model = Model({source: faithful}, {source: faithful})
    target, proof = core.translate_document(model, source, "zh", max_calls=2)
    assert core.valid_document_receipt(source, target, "zh", proof)
    assert audit(source, target, proof, monkeypatch)["hard_passed"]
    assert core.structure_issues(source, faithful.replace("S1-a", "S1-b"))
    assert core.structure_issues(source, faithful.replace("[S1-a,S24]", "[S1-a,S24] [S24]"))


def test_structure_feedback_stops_after_eight_differences_and_bounds_subtree_preview():
    class Counted(list):
        visits = 0

        def __getitem__(self, index):
            self.visits += 1
            assert self.visits <= 8, "diagnostic traversal exceeded the difference limit"
            return super().__getitem__(index)

    from unittest.mock import patch

    expected, actual = Counted(range(10000)), Counted(range(1, 10001))
    with patch.object(core, "markdown_structure", side_effect=[expected, actual]):
        feedback = core._structure_feedback("source", "target")
    assert len(feedback["differences"]) == 8
    assert expected.visits == actual.visits == 8
    huge = ["block_code", {}, "x" * 100000, [["text", {}, "y" * 100000, []]] * 10000]
    with patch.object(core, "markdown_structure", side_effect=[[huge], []]):
        feedback = core._structure_feedback("source", "target")
    assert len(json.dumps(feedback)) < 2500
    assert "truncated" in json.dumps(feedback)


@pytest.mark.parametrize("budget, complete, calls", [(1, False, 0), (2, False, 1), (3, True, 3)])
def test_structural_repair_uses_existing_budget_and_never_returns_unreviewed_text(budget, complete, calls):
    source, faithful = SHAPES["war6"]
    model = Model({source: damaged("war6", faithful)}, {source: faithful})
    target, proof = core.translate_document(model, source, "zh", max_calls=budget)
    assert proof["complete"] is complete and proof["calls_used"] == calls
    assert core.valid_document_receipt(source, target, "zh", proof) is complete


def test_failed_document_retains_hash_only_bounded_diagnostics_without_review_authority(monkeypatch):
    source = '## Source\n\n[Source](https://example.test/evidence)\n\n```text\noriginal\n```'
    faithful = source.replace('## Source', '## 来源').replace('[Source]', '[来源]')
    bad = faithful.replace('original', 'CANDIDATE_BODY_MUST_NOT_BE_SAVED').replace(
        'https://example.test/evidence', 'https://example.test/evidence?token=PRIVATE_FIXTURE_TOKEN')
    model = Model({source: bad}, {source: faithful}, repair=False)
    target, proof = core.translate_document(model, source, "zh", max_calls=3)
    row = proof["sections"][0]
    diagnostic = row["last_structure_failure"]
    assert diagnostic["source_sha256"] == hashlib.sha256(source.encode()).hexdigest()
    assert diagnostic["candidate_sha256"] == hashlib.sha256(bad.encode()).hexdigest()
    assert diagnostic["attempt"] == 2 and 0 < len(diagnostic["differences"]) <= 8
    serialized = json.dumps(proof)
    assert 'CANDIDATE_BODY_MUST_NOT_BE_SAVED' not in serialized
    assert 'PRIVATE_FIXTURE_TOKEN' not in serialized
    assert len(json.dumps(diagnostic)) < 3500
    assert row["source"] == row["target"] == source and row["receipt"] is None
    # Diagnostic records describe rejection; even perfect-looking hashes cannot
    # supply the absent translation or semantic-review receipt.
    assert not core.valid_document_receipt(source, target, "zh", proof)
    assert not audit(source, target, proof, monkeypatch)["hard_passed"]


def test_reference_tuple_preview_is_bounded_even_for_a_long_destination():
    source = "## Evidence\n\n[Evidence][record]\n\n[record]: https://example.test/" + "a" * 4000
    target = source.replace("## Evidence", "## 证据").replace("[Evidence]", "[证据]").replace("/aaaa", "/bbbb")
    assert core.structure_issues(source, target)
    feedback = core._structure_feedback(source, target)
    assert len(json.dumps(feedback)) < 3000
    assert "truncated" in json.dumps(feedback)


def test_failure_signatures_explicitly_identify_truncated_previews():
    source = "## Code\n\n```text\n" + "a" * 1000 + "SOURCE_TAIL\n```"
    target = source.replace("## Code", "## 代码").replace("SOURCE_TAIL", "TARGET_TAIL")
    model = Model({source: target}, {source: source}, repair=False)
    _, proof = core.translate_document(model, source, "zh", max_calls=3)
    diagnostic = proof["sections"][0]["last_structure_failure"]
    difference = diagnostic["differences"][0]
    for side in ("expected", "actual"):
        assert difference[side]["truncated"] is True
        assert "preview_sha256" in difference[side] and "preview_type" in difference[side]
        assert "sha256" not in difference[side], "a preview digest must not claim to hash the complete carrier"
    assert diagnostic["source_sha256"] != diagnostic["candidate_sha256"]
    assert diagnostic["candidate_sha256"] == hashlib.sha256(target.encode()).hexdigest()
