"""T3 — the lint flips from relabelling to provenance (ADR 0003, design §3.4, S0.4).

A sentence whose claim rests on the simulation is removed by the final scrub and
flagged by the read-only leakage scan.  It is never rewritten into evidence
wording ("the evidence indicates", 现有证据表明, "Evidence-based assessment").
"""
from __future__ import annotations

import re

from app.services import report_lint as rl

EVIDENCE_WORDING = (
    "the evidence indicates", "the available evidence", "the forecast evidence base",
    "evidence-based assessment", "public position", "stakeholder", "cross-actor",
    "the forecast defines", "the report defines",
    "现有证据", "研究证据", "证据分析", "预测情景中", "证据图谱",
)

SIM_SOURCE_WORDS = ("simulat", "agent", "faction", "cluster", "coalition",
                    "模拟", "仿真", "智能体", "推演")
LAUNDERING_TARGETS = ("evidence", "forecast", "analysis", "stakeholder", "position",
                      "证据", "预测", "分析", "情景")


def _assert_no_evidence_wording(out: str) -> None:
    low = out.lower()
    for phrase in EVIDENCE_WORDING:
        assert phrase.lower() not in low, phrase


def test_english_simulation_claim_is_removed_not_relabelled():
    md = ("The simulation shows demand grows 12% by 2028 [S4]. "
          "Independent trackers report 14% growth [S6].")
    out, rep = rl.lint_report(md, "English", mode="final")
    assert "simulation" not in out.lower()
    assert "12%" not in out and "[S4]" not in out          # the simulated claim is gone
    assert "Independent trackers report 14% growth [S6]." in out
    _assert_no_evidence_wording(out)
    assert rep["simulation_mechanics"]["sentences_removed"] == 1
    assert rep["leakage_flags"] == 0 and rep["changed"] is True


def test_chinese_simulation_claim_is_removed_not_relabelled():
    md = "模拟结果显示需求仍在增长[S6]。官方统计显示产能在2027年翻倍[S7]。基于本次模拟，出口限制仍是约束[S8]。"
    out, rep = rl.lint_report(md, "Chinese", mode="final")
    assert "模拟" not in out
    assert "官方统计显示产能在2027年翻倍[S7]。" in out
    assert "[S6]" not in out and "[S8]" not in out
    _assert_no_evidence_wording(out)
    assert rep["simulation_mechanics"]["sentences_removed"] == 2
    assert rep["leakage_flags"] == 0


def test_read_only_scan_flags_the_same_claims():
    for text in ("The simulation shows demand grows.", "Based on the simulation, X holds.",
                 "The simulated world treats Y as central.", "模拟结果显示需求增长。",
                 "基于模拟，限制仍在。", "仿真Agent「X」演绎/推理：Z。", "模拟证据表明 W。",
                 "The 16-agent faction spans four camps.", "The hyperscaler agent reads this as bounded.",
                 "An agent-based simulation of the market suggests Z."):
        assert rl.leakage_hits(text), text


def test_domain_terms_are_not_mechanics():
    for text in ("工业仿真软件市场规模将在2030年超过1000亿元[S1]。",
                 "汽车碰撞仿真需求将随数字孪生部署增长[S2]。",
                 "模拟芯片市场在2027年恢复增长[S3]。",
                 "模拟显示器出货量持续下滑[S4]。",
                 "AI agent dynamics in enterprise software will change procurement [S5].",
                 "Regulators formed a coalition of 12 agencies [S6]."):
        out, rep = rl.lint_report(text, "Chinese" if re.search(r"[一-鿿]", text) else "English",
                                  mode="final")
        assert rep["simulation_mechanics"]["sentences_removed"] == 0, text
        assert out == text, text


def test_legacy_agent_labels_are_counted_and_their_sentences_removed():
    md = ("> Simulation Agent「Hyperscalers」Deduction/Reasoning: \"capex holds through 2027\"\n\n"
          "> 模拟代理人「台积电」推演：先进制程供不应求。\n\n"
          "仿真Agent「China」（中方视角）演绎/推理：出口管制仍将持续[S2]。\n\n"
          "Real-world prose with a source stays [S1].\n")
    assert rl.count_legacy_sim_labels(md) == 3
    out, rep = rl.lint_report(md, "English", mode="final")
    assert rep["legacy_sim_labels"] == 3
    for residue in ("Simulation Agent", "模拟代理人", "仿真Agent", "演绎/推理",
                    "capex holds", "先进制程供不应求", "出口管制仍将持续"):
        assert residue not in out, residue
    assert "Real-world prose with a source stays [S1]." in out
    _assert_no_evidence_wording(out)
    assert rep["leakage_flags"] == 0


def test_no_rewrite_relabels_simulation_sources_as_evidence():
    """Guard the rewrite table itself: any rule whose source mentions the
    simulation, agents, factions or clusters must not replace it with
    evidence/forecast/analysis wording.  Graph/edge/dossier neutralisation is
    allowed (the graph is a projection of the research evidence)."""
    for pattern, replacement in rl._SIMULATION_OUTCOME_REWRITES:
        src = pattern.pattern.lower()
        if not any(w in src for w in SIM_SOURCE_WORDS):
            continue
        repl = str(replacement).lower()
        for bad in LAUNDERING_TARGETS:
            assert bad not in repl, (pattern.pattern, replacement)


def test_rewrite_sim_labels_no_longer_exists():
    assert not hasattr(rl, "rewrite_sim_labels")
