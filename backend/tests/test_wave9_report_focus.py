"""WAVE9 report-focus tests: 报告主语是现实世界，模拟只是内部方法。

Covers:
  * report_lint 纯函数：边转储改写 / 旧标签重写 / 孤悬归因清理 / 引用残留 & 记号规整 /
    重复整句去重 / 截断表格单元检测 / pass 叙述剥离 / 泄漏句删除 / lint_report 集成；
  * 反思护栏：裸 FAIL 跳过修订、反收缩护栏、截断检测 + 续写、动态章节字符下限；
  * 引文接地修复：归因行推演标签豁免 + 孤悬引子清理；
  * 泄漏修复 _repair_simulation_leakage（离线路径）与 _run_repair_passes 注册；
  * 信号包定性转写 salience_tiers_from_outcomes；大纲标题 lint；
  * render_resolution_block 语言参数 + 二元表 [:200] 截断移除。

全程离线（scripted fake LLM），与既有报告测试同一 __new__ + 属性注入 harness。
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.config import Config  # noqa: E402
from app.services import report_lint as rl  # noqa: E402
from app.services.forecast_extractor import (  # noqa: E402
    render_binary_forecasts_block, render_resolution_block,
    upsert_binary_forecasts_block,
)
from app.services.report_agent import (  # noqa: E402
    ReportAgent, ReportOutline, ReportSection, _looks_truncated,
    salience_tiers_from_outcomes,
)


# ─────────────────────────── report_lint 纯函数 ───────────────────────────
def test_lint_edge_dump_rewritten_to_natural_language():
    md = "TSMC keeps pricing power (According to：ASML Holding N.V. --[SUPPLIES]--> TSMC).\n"
    out, converted, dangling = rl.rewrite_edge_dumps(md, "English")
    assert converted == 1 and dangling == 0
    assert "--[" not in out
    assert "supply relationship" in out
    assert "ASML Holding N.V." in out and "TSMC" in out


def test_lint_dangling_edge_intro_stripped():
    md = "The dependency is structural (According to：\n"
    out, converted, dangling = rl.rewrite_edge_dumps(md, "English")
    assert dangling == 1
    assert "According to" not in out


def test_lint_legacy_sim_labels_counted_and_removed_not_relabelled():
    # ADR 0003: a legacy simulation-agent label marks a simulated statement.
    # It is counted and the sentence is removed; it is never rewritten into
    # "Evidence-based assessment — X:" / 「证据分析——「X」：」.
    md = (
        "> Simulation Agent「Hyperscalers」Deduction/Reasoning: \"capex holds through 2027\"\n\n"
        "> 模拟代理人「台积电」推演：先进制程供不应求。\n"
    )
    assert rl.count_legacy_sim_labels(md) == 2
    out, rep = rl.lint_report(md, "English", mode="final")
    assert rep["legacy_sim_labels"] == 2
    assert "Simulation Agent" not in out and "模拟代理人" not in out
    assert "Evidence-based assessment" not in out and "证据分析" not in out
    assert "capex holds through 2027" not in out and "先进制程供不应求" not in out
    assert rep["leakage_flags"] == 0


def test_lint_dangling_attribution_line_removed():
    md = (
        "Evidence-based assessment — TSMC pushes back with evidence:\n\n"
        "## Next Section\n\nNormal prose continues here.\n"
    )
    out, n = rl.remove_dangling_attributions(md)
    assert n == 1
    assert "pushes back with evidence:" not in out
    assert "## Next Section" in out


def test_lint_dangling_attribution_keeps_legit_intro_before_quote():
    md = "The panel perspective notes:\n\n> \"a grounded quotation follows\"\n"
    out, n = rl.remove_dangling_attributions(md)
    assert n == 0 and out == md


def test_lint_citation_residue_and_variant_normalization():
    md = ("Growth hit $1.4T [citation:BofA $1.4T](https://rallies.ai/x) by 2030.\n"
          "Backed by 【S3】 and [S2-d] and [S1 / fact 8].\n")
    out, n_resid = rl.strip_citation_residue(md)
    assert n_resid == 1 and "[citation:" not in out
    out, n_var = rl.normalize_citation_variants(out)
    assert n_var == 3
    assert "[S3]" in out and "[S2]" in out and "[S1]" in out
    assert "【S3】" not in out and "[S2-d]" not in out


def test_lint_duplicate_sentence_dedup():
    dup = ("The equipment segment reproduces the same structural claim about its own "
           "architecture across the entire industry every single cycle.")
    md = f"{dup} Unique tail one.\n\nMiddle paragraph stays.\n\n{dup} Unique tail two.\n"
    out, removed = rl.dedup_duplicate_sentences(md)
    assert removed == 1
    assert out.count("equipment segment reproduces") == 1
    assert "Unique tail one." in out and "Unique tail two." in out


def test_lint_table_cell_truncation_detected():
    long_cut = "measured against the blended average selling price basket used in Q3 202" + "x" * 90
    md = f"| # | criteria |\n|---|---|\n| 1 | {long_cut} |\n"
    hits = rl.detect_table_cell_truncation(md)
    assert hits, "expected the truncated cell to be flagged"


def test_lint_table_cell_truncation_spares_official_series_titles():
    # 官方数据表会把 FRED 系列全称原样贴进单元格：完整标题、无句末标点。
    title = ("Total Unemployed, Plus All Persons Marginally Attached to the Labor "
             "Force, Plus Total Employed Part Time for Economic Reasons, as a "
             "Percent of the Civilian Labor Force Plus All Persons Marginally "
             "Attached to the Labor Force (U-6) — United States")
    md = f"| Series | Unit | Latest |\n|---|---|---|\n| {title} | Percent | 7.6% |\n"
    assert rl.detect_table_cell_truncation(md) == []


def test_lint_table_cell_truncation_spares_complete_unpunctuated_prose():
    # Regression (2026-10-16 Burnham run): LLM scenario-matrix cells hold full
    # clause lists that simply end without terminal punctuation — content words
    # close the clause, so they are not width cuts and must not fail the gate.
    cells = [
        "(a) Burnham is Prime Minister; (b) a Railways Act has received Royal "
        "Assent devolving specified rail services to Greater Manchester control; "
        "(c) the GM Integrated Settlement envelope is confirmed at or near the "
        "NAO-recorded £3.5 billion",
        "at least two of three fail: funding — no confirmation of the GM envelope "
        "at NAO scale; rail — the January 2028 phase slips beyond mid-2028; "
        "fiscal powers — trailblazer provisions remain prospective or only "
        "partially commenced",
        "sustained national polling with Labour's lead below roughly three "
        "points; Burnham's favourability sustained below about +6 across two "
        "quarters",
    ]
    md = "| Scenario | Criteria |\n|---|---|\n"
    for i, c in enumerate(cells):
        md += f"| {i + 1} | {c} |\n"
    assert rl.detect_table_cell_truncation(md) == []


def test_lint_table_cell_truncation_flags_mid_clause_cuts():
    # Dangling function word, orphan tail after the last boundary, unbalanced
    # bracket and machine-length token are genuine width-cut signatures.
    base = ("The committee reviews the settlement profile, the January 2028 "
            "phase and the audited capital numbers published by the spending "
            "review each spring against the wider envelope ")
    assert len(base) > 160 or True  # each cut below must clear min_len=160
    cuts = [
        base + "with confirmation expected at or near",           # dangling word
        base + "across two consecutive; and the",                 # orphan tail
        base + "if the Railways Act carries section 7 (b",        # unbalanced paren
        base + "measured against the blended basket used in Q3 " + "x" * 60,  # machine token
    ]
    md = "| # | criteria |\n|---|---|\n"
    for i, c in enumerate(cuts):
        assert len(c) >= 160, f"cut {c[-20:]} too short for min_len"
        md += f"| {i + 1} | {c} |\n"
    hits = rl.detect_table_cell_truncation(md)
    assert len(hits) == len(cuts)


def test_lint_pass_narration_stripped_and_flagged():
    md = ("Big Fund III ¥344B [Pass 2 working notes] anchored the estimate.\n"
          "Pass 4 of the broader dossier documented the contradiction.\n")
    out, stripped, flagged = rl.strip_pass_narration(md)
    assert stripped == 1
    assert "[Pass 2 working notes]" not in out
    assert flagged >= 1                       # 散文提及只标记不删


def test_lint_leakage_sentence_strip():
    text = ("TSMC retains pricing power through 2030. "
            "The simulation surfaced this claim in round 3 with 48 actions. "
            "Export controls remain the binding constraint [S2].")
    out, removed = rl.strip_leakage_sentences(text)
    assert removed == 1
    assert "round 3" not in out and "simulation" not in out
    assert "pricing power" in out and "[S2]" in out


def test_final_lint_segments_chinese_without_spaces_and_preserves_citations():
    md = (
        "需求韧性仍强[S1]。"
        "模拟中，第 3 轮产生 48 次动作。"
        "监管约束仍是关键【S2】。"
    )

    out, rep = rl.lint_report(md, "Chinese", mode="final")

    assert "需求韧性仍强[S1]。" in out
    assert "监管约束仍是关键[S2]。" in out
    assert "第 3 轮" not in out and "48 次动作" not in out
    assert rep["simulation_mechanics"]["sentences_removed"] == 1


def test_final_lint_keeps_real_world_consensus_and_revealed_preference():
    md = (
        "Customer purchasing data provide a revealed preference signal. "
        "Consensus formation among regulators is advancing [S4].\n"
        "市场价格反映消费者的揭示性偏好。监管者正在形成共识【S5】。"
    )

    out, rep = rl.lint_report(md, "English", mode="final")

    assert "revealed preference signal" in out
    assert "Consensus formation among regulators" in out
    assert "消费者的揭示性偏好" in out and "监管者正在形成共识" in out
    assert rep["simulation_mechanics"]["sentences_removed"] == 0


def test_final_lint_removes_consensus_or_preference_only_with_simulation_context():
    md = (
        "The simulated agents exhibited revealed preferences in round 4. "
        "Demand remains resilient [S1].\n"
        "智能体行为信号被用于推断共识形成。供应仍然受限【S2】。"
    )

    out, rep = rl.lint_report(md, "English", mode="final")

    assert "revealed preferences" not in out and "round 4" not in out
    assert "智能体行为信号" not in out and "共识形成" not in out
    assert "Demand remains resilient [S1]." in out
    assert "供应仍然受限[S2]。" in out
    assert rep["simulation_mechanics"]["sentences_removed"] == 2


def test_final_lint_preserves_english_sentence_spacing():
    md = "Demand remains resilient [S1]. Supply remains constrained [S2]."

    out, rep = rl.lint_report(md, "English", mode="final")

    assert out == md
    assert ". Supply" in out
    assert rep["simulation_mechanics"]["sentences_removed"] == 0


def test_final_lint_repairs_legacy_sentence_joins_without_touching_initialisms():
    md = "The cycle reached its sharpest standoff in history.SK Hynix led the turn [S1]. U.S. policy held."

    out, rep = rl.lint_report(md, "English", mode="final")

    assert "history. SK Hynix" in out
    assert "U.S. policy" in out
    assert rep["sentence_spaces_repaired"] == 1


def test_final_lint_removes_real_legacy_chinese_simulation_forms():
    # ADR 0003: every sentence whose claim rests on the simulation is removed
    # whole; only the sourced real-world sentence survives. Nothing is
    # relabelled as 证据分析 / 现有证据 / 研究证据.
    md = (
        "需求增长了12%[S1]。"
        "仿真以清晰的细节捕捉到了产能爬坡至每月14万片[S2]。"
        "仿真图记录供应约束持续到2028年[S3]。"
        "仿真Agent「SK Hynix」演绎/推理：HBM份额将保持在50%以上[S4]。"
        "模拟证据显示出口限制仍是约束[S5]。"
        "模拟数据显示需求仍在增长[S6]。"
    )

    out, rep = rl.lint_report(md, "Chinese", mode="final")

    assert out == "需求增长了12%[S1]。"
    for residue in ("仿真", "模拟", "证据分析", "现有证据", "研究证据"):
        assert residue not in out
    assert rep["simulation_mechanics"]["sentences_removed"] == 5
    assert rep["legacy_sim_labels"] == 1
    assert rep["leakage_flags"] == 0


def test_final_lint_removes_role_qualified_legacy_agent_labels():
    # ADR 0003: role-qualified legacy labels are counted; the simulated
    # statements they introduce are removed, not relabelled as 证据分析.
    md = (
        "仿真Agent「China」（作为产业政策制定者）演绎/推理："
        "前沿逻辑制程份额将在2030年前增长[S1]。"
        "仿真Agent「China」（中方视角）演绎/推理："
        "出口管制仍将持续[S2]。"
        "仿真Agent「Intel Foundry」的表述则更为直接："
        "外部客户收入将在2027年超过20亿美元[S3]。"
    )

    out, rep = rl.lint_report(md, "Chinese", mode="final")

    assert "仿真Agent" not in out and "演绎/推理" not in out
    assert "证据分析" not in out
    assert "[S1]" not in out and "[S2]" not in out and "[S3]" not in out
    assert out.strip() == ""
    assert rep["legacy_sim_labels"] == 3 and rep["leakage_flags"] == 0


def test_final_lint_preserves_legitimate_simulation_industry_terms():
    md = (
        "工业仿真软件市场规模将在2030年超过1000亿元[S1]。"
        "汽车碰撞仿真需求将随数字孪生部署增长[S2]。"
        "芯片仿真工具收入预计在2028年前翻倍[S3]。"
    )

    out, rep = rl.lint_report(md, "Chinese", mode="final")

    assert out == md
    assert "工业仿真软件" in out and "汽车碰撞仿真" in out
    assert "芯片仿真工具" in out
    assert rep["simulation_mechanics"]["rewritten"] == 0
    assert rep["simulation_mechanics"]["sentences_removed"] == 0


def test_final_lint_preserves_agentic_ai_subject_matter():
    md = (
        "AI agent behavior in enterprise workflows will change by 2030 [S1]. "
        "The most active agents in enterprise workflows handle support tickets [S2]. "
        "AI智能体市场收入将在2030年超过1000亿美元[S3]。"
        "AI智能体网络协议采用率将在2030年超过50%[S4]。"
        "智能体动作规划软件收入将在2028年前翻倍[S5]。"
        "智能体模拟环境市场将随机器人训练需求增长[S6]。"
    )

    out, rep = rl.lint_report(md, "English", mode="final")

    assert "AI agent behavior" in out
    assert "The most active agents in enterprise workflows" in out
    assert "AI智能体市场收入" in out and "AI智能体网络协议" in out
    assert "智能体动作规划软件" in out and "智能体模拟环境市场" in out
    assert rep["simulation_mechanics"]["sentences_removed"] == 0


def test_final_lint_removes_simulation_claims_and_mechanics():
    # ADR 0003: "the simulation suggests 62%" is a simulated claim and is
    # removed whole; it is no longer reframed as "the evidence indicates".
    md = (
        "# Simulation Dynamics\n\n"
        "The simulation suggests a 62% chance of approval by 2028 [S2].\n\n"
        "Round 3 produced 48 actions and the most active agents amplified posts.\n\n"
        "| Signal | Reading |\n|---|---|\n"
        "| CREATE_POST | 54 actions |\n"
    )
    out, rep = rl.lint_report(md, "English", mode="final")
    assert "Forecast Drivers and Outcome Pathways" in out
    assert "evidence indicates" not in out.lower()
    assert "62%" not in out and "[S2]" not in out
    assert "Round 3" not in out and "CREATE_POST" not in out and "54 actions" not in out
    assert out.count("|") == md.count("|")
    assert rep["simulation_mechanics"]["sentences_removed"] >= 2
    assert rep["simulation_mechanics"]["table_cells_redacted"] >= 1
    assert rep["leakage_flags"] == 0
    assert rep["outcome_focus_ok"] is True


def test_final_lint_removes_exact_harness_process_residue():
    md = (
        "# Forecast\n\n"
        "The harness grouped stakeholders into three agent clusters. "
        "The simulated environment then emitted world-state outputs. "
        "A simulation-derived score drove the final recommendation.\n\n"
        "The observable election outcome remains tied to turnout and district margins [S1].\n"
    )

    out, rep = rl.lint_report(md, "English", mode="final")

    for residue in (
        "harness", "agent cluster", "simulated environment",
        "world-state output", "simulation-derived",
    ):
        assert residue not in out.lower()
    assert "observable election outcome" in out
    assert rep["simulation_mechanics"]["sentences_removed"] >= 3
    assert rep["leakage_flags"] == 0


def test_final_lint_removes_internal_telemetry_but_keeps_following_visuals():
    md = (
        "# Forecast\n\nUseful analysis.\n\n"
        "## Run Telemetry\n\n| Stage | Input tok |\n|---|---:|\n| research | 78000000 |\n\n"
        "## Visual Annex\n\n![Chart](charts/outcomes.png)\n"
    )
    out, rep = rl.lint_report(md, "English", mode="final")
    assert "Run Telemetry" not in out
    assert "78000000" not in out
    assert "## Visual Annex" in out and "charts/outcomes.png" in out
    assert rep["internal_telemetry_appendices"] == 1


def test_final_lint_removes_faction_cluster_method_language():
    # ADR 0003: a sentence resting on the faction/cluster clustering is
    # simulation content; it is removed, not reframed as "cross-actor evidence".
    out, rep = rl.lint_report(
        "The faction/cluster analysis shows a tightly coupled semiconductor coalition.",
        "English", mode="final")
    assert out.strip() == ""
    assert "cross-actor evidence" not in out.lower()
    assert rep["simulation_mechanics"]["sentences_removed"] == 1


def test_final_lint_removes_internal_graph_process_prose_and_relation_dumps():
    md = (
        "## The China Sub-Simulation — DeepSeek and SMIC\n\n"
        "Causal relationships (CAUSES, ENABLES) are distinguished from "
        "associative relationships (PARTNERS_WITH, COMPETES_WITH).\n\n"
        "The research graph maps this through five edges, and the sub-simulation "
        "predicts an entangled endgame.\n\n"
        "Lutnick had a post-to-like ratio and 76 combined actions, or 17% of "
        "network traffic.\n\n"
        "- Donald J. Trump enables NVIDIA H200\n"
        "- Donald J. Trump enables AMD\n"
        "- Donald J. Trump enables IEEPA\n"
        "- Donald J. Trump enables Masayoshi Son\n\n"
        "The dossier's base case assigns 43% to the modal outcome.\n\n"
        "TSMC's 2nm process node remains supply-constrained [S1] "
        "(reflecting TSMC's dependency relationship with ASML).\n\n"
        "Broadcom has a large backlog (According to: `Broadcom partners with Google`).\n"
    )

    out, rep = rl.lint_report(md, "English", mode="final")

    # ADR 0003: the sub-simulation heading is a mechanics heading and gets the
    # outcome-first title; it is not rebranded "China Outcome Analysis", and the
    # sentence resting on the sub-simulation is removed rather than reframed.
    assert "China Outcome Analysis" not in out
    assert "Forecast Drivers and Outcome Pathways" in out
    assert "sub-simulation" not in out.lower()
    assert "research graph" not in out.lower()
    assert "CAUSES" not in out and "PARTNERS_WITH" not in out
    assert "post-to-like" not in out and "combined actions" not in out
    assert "Donald J. Trump enables" not in out
    assert "dossier" not in out.lower()
    assert "forecast's base case" in out
    assert "2nm process node" in out  # real semiconductor terminology survives
    assert "reflecting TSMC" not in out and "According to:" not in out
    assert rep["internal_graph_parentheticals"] == 2
    assert rep["internal_relation_bullets"] == 4
    assert rep["leakage_flags"] == 0
    assert rep["outcome_focus_ok"] is True


def test_final_lint_removes_failed_empty_and_corrupted_legacy_sections():
    md = (
        "# Forecast\n\n"
        "## Complete Section\n\nA useful forecast remains [S1].\n\n"
        "## Failed Scenario\n\n"
        "（Chapter generation failed: claude-cli output contamination by system prompt.）\n\n"
        "## Broken Memory Section\n\n"
        "### HBM5（2029–2030）：Hybrid bonding becomes the next-generation watershed\n\n"
        "Capacity normalizes in 2027 second half，because all fabs reach scale。\n\n"
        "| — | — | [S2] |\n|---|---|---|\n| — | 10–15% | [S2] |\n\n"
        "## Forecast Drivers and Outcome Pathways\n\n[S2]\n\n"
        "## Final Section\n\nThe final outcome remains observable.\n"
    )

    out, rep = rl.lint_report(md, "English", mode="final")

    assert "Complete Section" in out and "Final Section" in out
    assert "Chapter generation failed" not in out
    assert "Failed Scenario" not in out
    assert "Broken Memory Section" not in out
    assert "| — | — |" not in out
    assert "\n[S2]\n" not in out
    assert "Forecast Drivers and Outcome Pathways" not in out
    assert rep["generation_failure_placeholders"] == 1
    assert rep["corrupted_mixed_punctuation_lines"] >= 2
    assert rep["empty_tables"] == 1
    assert rep["standalone_citation_lines"] >= 1
    assert rep["empty_sections"] >= 3
    assert rep["leakage_flags"] == 0


def test_lint_platform_behavior_quote_dropped():
    md = "> The TSMC agent posted a thread and liked the post about HBM supply.\n\nProse.\n"
    out, n = rl.drop_platform_behavior_quotes(md)
    assert n == 1 and "posted a thread" not in out and "Prose." in out


def test_lint_report_end_to_end_fence_aware():
    md = (
        "# Title\n\n"
        "Claim (According to：BIS --[REGULATES]--> H100). [citation:x](https://y)\n\n"
        "```mermaid\nA --[SUPPLIES]--> B\n```\n\n"
        "> Simulation Agent「X」Deduction/Reasoning: \"kept\"\n"
    )
    out, rep = rl.lint_report(md, "English", mode="final")
    assert rep["changed"] is True
    assert "A --[SUPPLIES]--> B" in out          # 围栏内原样保留
    assert "(According to：BIS" not in out
    assert "[citation:" not in out
    # ADR 0003: the legacy label is counted and its quote removed, never
    # relabelled as an evidence-based assessment.
    assert "Simulation Agent" not in out and "Evidence-based assessment" not in out
    assert '"kept"' not in out
    assert rep["edge_dumps"] == 1 and rep["citation_residue"] == 1
    assert rep["legacy_sim_labels"] == 1


def test_lint_report_scenario_prob_crosscheck():
    spine = {"scenarios": [{"name": "Structural Supercycle", "probability": 0.45}]}
    md = "The Structural Supercycle scenario carries 62% odds in our view.\n"
    _, rep = rl.lint_report(md, "English", spine=spine)
    assert rep["scenario_prob_mismatches"], "expected a prose-vs-spine mismatch flag"


# ─────────────────────────── 反思护栏（section destroyer） ───────────────────
_LONG_DRAFT = ("This is a full-length analytical paragraph with mechanisms and evidence. " * 60)


class _ChatLLM:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def chat(self, messages=None, temperature=0.7, max_tokens=4096, tier="strong", **kw):
        self.calls.append({"messages": messages, "temperature": temperature,
                           "max_tokens": max_tokens, "tier": tier})
        return self.responses[min(len(self.calls) - 1, len(self.responses) - 1)]


def _reflect_agent(responses, **over):
    a = ReportAgent.__new__(ReportAgent)
    a.output_language = "English"
    a._forecast_spine = {"scenarios": [{"name": "Escalation", "probability": 0.6}]}
    a._forecast_spine_block = ""
    a._signal_pack = ""
    a.llm = _ChatLLM(responses)
    for k, v in over.items():
        setattr(a, k, v)
    return a


def _sec_outline():
    sec = ReportSection(title="Body 1", description="")
    return sec, ReportOutline(title="T", summary="S", sections=[sec])


def test_reflection_bare_fail_skips_revision():
    a = _reflect_agent(["FAIL"])
    sec, outline = _sec_outline()
    out = a._reflect_and_maybe_revise_section(sec, outline, _LONG_DRAFT, previous_sections=[])
    assert out == _LONG_DRAFT
    assert len(a.llm.calls) == 1              # 只有质检调用，没有修订调用


def test_reflection_rejects_shrinking_revision():
    stub = "A tiny stub replacement that would destroy the section. " * 30  # ~1.7KB but <60%
    assert len(stub) < 0.6 * len(_LONG_DRAFT)
    a = _reflect_agent(["Tighten the probability framing.", stub])
    sec, outline = _sec_outline()
    out = a._reflect_and_maybe_revise_section(sec, outline, _LONG_DRAFT, previous_sections=[])
    assert out == _LONG_DRAFT                 # 收缩修订被拒绝，保留原稿
    assert len(a.llm.calls) == 2


def test_reflection_accepts_good_revision():
    revised = "Revised with better probability framing. " + _LONG_DRAFT
    a = _reflect_agent(["Align probabilities.", revised])
    sec, outline = _sec_outline()
    out = a._reflect_and_maybe_revise_section(sec, outline, _LONG_DRAFT, previous_sections=[])
    assert out == revised.strip()


def test_truncation_detector_and_continuation(monkeypatch):
    monkeypatch.setattr(Config, "REPORT_SECTION_TRUNCATION_CONTINUE", True, raising=False)
    truncated = _LONG_DRAFT + "\n\nSamsung's 2017-2018 cycle peaked at $46 and the (依据"
    assert _looks_truncated(truncated) is True
    assert _looks_truncated(_LONG_DRAFT) is False
    assert _looks_truncated("Ends with a list:\n- item one\n- item two") is False
    continuation = "billion capex round completed the argument. The section concludes cleanly."
    a = _reflect_agent(["PASS", continuation])
    sec, outline = _sec_outline()
    out = a._reflect_and_maybe_revise_section(sec, outline, truncated, previous_sections=[])
    assert "concludes cleanly." in out
    assert "(依据" not in out                  # 孤悬引子被剪掉
    assert len(a.llm.calls) == 2               # 质检 + 一次续写


def test_section_char_floor_scales_with_target(monkeypatch):
    monkeypatch.setattr(Config, "REPORT_SECTION_MIN_VALID_RATIO", 0.4, raising=False)
    a = _reflect_agent(["PASS"])
    a.simulation_requirement = ""
    a.research_report = ""
    floor = a._section_char_floor()
    lo, _ = Config.report_section_target_chars()
    assert floor == max(800, int(lo * 0.4))


# ───────────────────── 引文接地：归因行标签豁免 + 孤悬引子清理 ─────────────────
def _repair_agent(**over):
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


def test_quote_grounding_does_not_exempt_neutral_assessment_label():
    a = _repair_agent(research_report="irrelevant corpus")
    md = (
        "Evidence-based assessment — TSMC argues:\n\n"
        "> \"Advanced packaging stays the binding constraint through 2028 at least.\"\n"
    )
    new_md, removed = a._repair_quote_grounding(md)
    assert removed == 1
    assert "Advanced packaging stays" not in new_md


def test_quote_grounding_removes_dangling_intro_with_quote():
    a = _repair_agent(research_report="the only grounded fact in this corpus")
    md = (
        "The market view pushes back hard on this claim:\n\n"
        "> \"A fabricated quotation that matches nothing in the research corpus at all.\"\n\n"
        "Prose continues after the deleted quote block.\n"
    )
    new_md, removed = a._repair_quote_grounding(md)
    assert removed == 1
    assert "fabricated quotation" not in new_md
    assert "pushes back hard on this claim:" not in new_md   # 孤悬引子同步清理
    assert "Prose continues" in new_md


# ───────────────────── 泄漏修复 + 修复链注册（离线路径） ─────────────────────
def test_repair_simulation_leakage_offline_deterministic():
    a = _repair_agent()                        # 无 llm → Tier-2 走句子级删除
    md = (
        "## 9. Agent Behavior in the Simulation\n\n"
        "TSMC holds pricing power [S1]. The simulation surfaced 48 actions in round 0. "
        "Export controls bind through 2027 [S2].\n\n"
        "> The TSMC agent posted a thread and liked the post repeatedly.\n"
    )
    new_md, info = a._repair_simulation_leakage(md)
    assert info["headings_renamed"] == 1
    assert "Agent Behavior" not in new_md
    assert "48 actions" not in new_md and "round 0" not in new_md
    assert "pricing power [S1]" in new_md and "[S2]" in new_md
    assert "posted a thread" not in new_md     # 平台行为引文被删


def test_run_repair_passes_triggers_simleak(monkeypatch):
    monkeypatch.setattr(Config, "REPORT_SIMLEAK_REPAIR", True, raising=False)
    monkeypatch.setattr(Config, "REPORT_PUBLISH_GATE_MIN_COVERAGE", 0.0, raising=False)
    a = _repair_agent()
    md = "Solid claim [S1]. The simulation surfaced this in round 2 with 30 actions.\n"
    forecast = {"citation_audit": {"coverage": 1.0, "quantitative_claims": 0}, "quality": {}}
    new_md = a._run_repair_passes("rid_sl", forecast, md, report=None)
    assert "round 2" not in new_md
    rep = forecast["quality"]["repair"]
    assert any(p["dimension"] == "simulation_leakage" for p in rep["passes"])
    assert rep["before"]["sim_leakage_hits"] > rep["after"]["sim_leakage_hits"]
    assert forecast["quality"]["sim_leakage"]["after"] < forecast["quality"]["sim_leakage"]["before"]


# ───────────────────── 信号包定性转写 + 大纲标题 lint ─────────────────────
def test_salience_tiers_from_outcomes():
    outcomes = (
        "## 模拟量化结果（结构化，可直接引用）\n\n### 最活跃 Agent（Top 3，按总动作数）\n"
        "- TSMC(id=1): 共 48 次动作 [CREATE_POST×21]\n"
        "- NVIDIA(id=2): 共 40 次动作 [CREATE_COMMENT×12]\n"
        "- Micron(id=3): 共 5 次动作 [LIKE_POST×5]\n"
    )
    tiers = salience_tiers_from_outcomes(outcomes)
    assert "第一梯队" in tiers and "TSMC" in tiers and "NVIDIA" in tiers
    assert "第三梯队" in tiers and "Micron" in tiers
    assert "次动作" not in tiers and "48" not in tiers   # 机制数字不进注入文本
    assert salience_tiers_from_outcomes("（无数据）") == ""


def test_outline_title_lint_renames_leaky_titles():
    a = ReportAgent.__new__(ReportAgent)
    a.output_language = "English"
    sections = [
        ReportSection(title="Agent Behavior in the Simulation"),
        ReportSection(title="Power Transition Scenarios"),
        ReportSection(title="模拟证据与行为轨迹"),
    ]
    renamed = a._lint_outline_titles(sections)
    assert renamed == 2
    assert len(sections) == 3                  # 改名而非删除（章节数契约）
    titles = [s.title for s in sections]
    assert "Power Transition Scenarios" in titles
    for t in titles:
        assert not ReportAgent._LEAK_TITLE_RE.search(t), t


# ───────────────────── 判定章节语言 + 二元表截断移除 ─────────────────────
def test_render_resolution_block_english():
    fc = {"scenarios": [{"name": "Base case", "probability": 0.6,
                         "resolution_criteria": "Revenue >= $1T by 2030 per Gartner."}]}
    block = render_resolution_block(fc, [{"indicator": "HBM share", "date": "2027-01",
                                          "scenario": "Base case"}], language="English")
    assert "How to Verify This Forecast" in block
    assert "如何验证本预测" not in block
    assert "| Indicator | Due / trigger |" in block
    # 默认（中文）行为不变
    zh_block = render_resolution_block(fc)
    assert "如何验证本预测" in zh_block


def test_render_binary_forecasts_block_no_criteria_truncation():
    crit = ("Resolves YES if industry revenue measured against the blended basket used in "
            "Q3 2029 exceeds $1.6T per the arithmetic mean of Gartner and IDC full-year "
            "prints published before 2031-03-31, using vendor-reported segment definitions.")
    assert len(crit) > 200
    fc = {"binary_forecasts": [{"id": "F1", "statement": "Revenue ≥ $1.6T", "probability": 0.62,
                                "resolution_criteria": crit, "theme": "market"}]}
    block = render_binary_forecasts_block(fc, language="English")
    assert crit in block                       # 不再被 [:200] 截断


def test_upsert_binary_forecasts_replaces_legacy_truncated_part_one():
    old = (
        "# Forecast\n\n## Part 1 — Binary Forecasts\n\n"
        "| # | Resolution criteria |\n|---|---|\n| F1 | criterion cut at NVI |\n\n"
        "## Part 2 — Framework & Synthesis\n\nKeep this analysis.\n"
    )
    complete = (
        "## Part 1 — Binary Forecasts\n\n"
        "| # | Resolution criteria |\n|---|---|\n"
        "| F1 | Complete criterion through 2027 per NVIDIA filings. |"
    )

    updated, action = upsert_binary_forecasts_block(old, complete)

    assert action == "replaced"
    assert "cut at NVI" not in updated
    assert "Complete criterion through 2027" in updated
    assert updated.count("## Part 1 — Binary Forecasts") == 1
    assert "Keep this analysis." in updated
