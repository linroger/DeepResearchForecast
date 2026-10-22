"""SMOKE 实跑回归：report_a03be154febc 真实成稿上发现的泄漏残留类别。

对完整真实成稿跑确定性 lint + 模拟泄漏修复（无 LLM）后仍有 34 处命中，全部集中在
非散文结构里：表格行（`|` 开头）、加粗导语段（`**` 开头——被段落扫描器按列表/强调
跳过）。这些残留必须至少被 leakage_hits 计入 flag 遥测——本文件把这几个真实形状
钉成回归守卫，同时锁定实跑中的多边 edge-dump 变体确实被确定性改写清零。
"""

from app.services import report_lint as rl
from app.services.report_agent import ReportAgent


def _agent(lang: str = "English") -> ReportAgent:
    a = ReportAgent.__new__(ReportAgent)
    a.output_language = lang
    return a


# ── 真实成稿形状 1：多边、全角分号分隔的 edge dump（full_report.md:421 同款） ──

def test_real_run_multi_edge_dump_rewritten_clean():
    md = ("ASML remains the sole EUV supplier "
          "(According to：ASML Holding N.V. --[SUPPLIES]--> TSMC；"
          "ASML Holding N.V. --[SUPPLIES]--> Samsung Electronics；"
          "ASML Holding N.V. --[SUPPLIES]--> Intel Corporation).")
    out, n_dumps, _dangling = rl.rewrite_edge_dumps(md, "English")
    assert "--[" not in out
    assert n_dumps >= 1                      # 计数按转储块计，非按边计
    # 关系语义保留为自然语言，而不是整句蒸发
    assert "TSMC" in out and "ASML" in out


# ── 真实成稿形状 2：表格行内的 Simulation Agent 标签（linted 后残留 6 处的形状） ──

_TABLE_ROW = ("| Simulation Agent「sk_hynix_989」 | 15–20% 中段 | <10% | "
              "防守方（夸大压力以维持对 HBM 投入正当性） | [S2] |")


def test_table_row_sim_label_is_flagged_by_leakage_hits():
    hits = rl.leakage_hits(_TABLE_ROW)
    assert any(h == "simulation_agent_label" for h in hits), (
        "表格行里的 Simulation Agent 标签必须被 leakage_hits 计入 flag 遥测")


def test_table_row_sim_label_is_cleared_by_final_editorial_lint():
    md = "## Section\n\nProse line.\n\n" + _TABLE_ROW + "\n\nMore prose.\n"
    out, info = _agent()._repair_simulation_leakage(md)
    cleaned, rep = rl.lint_report(out, "English", mode="final")
    assert "Simulation Agent" not in cleaned
    assert rep["leakage_flags"] == 0
    # 无论走哪条路径，修复过程不得让文档丢失表格本体
    assert out.count("|") >= _TABLE_ROW.count("|") - 2


# ── 真实成稿形状 3：加粗导语的机制叙述段（linted 后 round_n/动作词残留的来源） ──

_BOLD_LEAD_PARA = ("**第二阶段“定位期”为 round 10–11**：54 与 39 次动作，"
                   "活跃 Agent 扩展到 14 和 12 个。此阶段主导动作从 CREATE_POST "
                   "转向 CREATE_COMMENT。")


def test_bold_lead_mechanics_paragraph_is_flagged():
    hits = rl.leakage_hits(_BOLD_LEAD_PARA)
    assert "round_n" in hits
    assert any(h == "action_type_tokens" for h in hits)


def test_bold_lead_mechanics_paragraph_is_removed_by_final_editorial_lint():
    md = "## 第九章\n\n" + _BOLD_LEAD_PARA + "\n\n正文继续。\n"
    out, info = _agent("Chinese")._repair_simulation_leakage(md)
    assert isinstance(info, dict)
    cleaned, rep = rl.lint_report(out, "Chinese", mode="final")
    assert "CREATE_POST" not in cleaned and "round 10" not in cleaned
    assert rep["leakage_flags"] == 0


# ── 真实成稿形状 4：大小写 possessive + “simulated world” 绕过旧模式 ──

def test_real_run_simulated_world_and_possessive_heading_are_reframed():
    md = (
        "Modern Mercantilism is colliding with AI, and the simulated world we "
        "constructed, populated by 322 active agents and 1,055 relationships, "
        "treats that simultaneity as the central fact.\n\n"
        "### What the Simulation's Power Map Says About Who Decides the Rationing\n\n"
        "In the simulated world, 10 binary forecasts are laid out as "
        "falsifiable, quantifiable outcomes.\n"
    )

    out, rep = rl.lint_report(md, "English", mode="final")

    assert "simulated world" not in out.lower()
    assert "simulation's" not in out.lower()
    assert "322 active agents" not in out
    # ADR 0003: sentences resting on the simulated world are removed whole,
    # never relabelled as "cross-actor evidence" / "actor-power evidence".
    assert "evidence treats" not in out and "actor-power" not in out.lower()
    assert "The report defines" not in out
    assert "Modern Mercantilism" not in out  # that clause lived in a simulated-world sentence
    # Both sentences under the leaky heading were simulated-world claims, so the
    # section emptied and the heading went with it: nothing is left to relabel.
    assert out.strip() == ""
    assert rep["simulation_mechanics"]["sentences_removed"] == 2
    assert rep["leakage_flags"] == 0
    assert rep["outcome_focus_ok"] is True


def test_real_run_agent_counts_action_telemetry_and_basis_traces_are_removed():
    md = (
        "### A Coalition of Convenience: The Single 16-Agent Bloc That Holds the Game\n\n"
        "Among 322 active agents and 1,055 relationships, the only cohesive "
        "16-agent faction spans four camps. The coalition binds because each "
        "actor needs access to compute.\n\n"
        "The graph contains 1,055 directed edges, weighted by sign and lag.\n\n"
        "The action-type distribution is diagnostic. The ratio of liking to "
        "posting is 2:1, indicating a coalition-formation phase.\n\n"
        "Policy remains exposed (Basis:Donald Trump enables NVIDIA H200; "
        "Donald Trump enables IEEPA). The public record is independently testable.\n"
    )

    out, rep = rl.lint_report(md, "English", mode="final")

    assert "16-Agent" not in out and "322 active agents" not in out
    assert "1,055 directed edges" not in out
    assert "liking to posting" not in out and "coalition-formation" not in out
    assert "Basis:" not in out
    assert "The coalition binds" in out
    assert "The public record is independently testable" in out
    assert rep["internal_basis_traces"] == 1
    assert rep["leakage_flags"] == 0


def test_real_run_named_proxy_and_simulated_evidence_are_reframed():
    md = (
        "The NVIDIA agent reads the displacement as structurally bounded. "
        "The simulated data shows HBM supply is constrained. "
        "The simulated evidence is that capacity moves offshore. "
        "That sentence, restated dozens of times across rounds and across "
        "clusters of agents, is the modal claim.\n"
    )

    out, rep = rl.lint_report(md, "English", mode="final")

    assert "NVIDIA agent" not in out
    assert "simulated data" not in out and "simulated evidence" not in out
    assert "rounds" not in out and "clusters of agents" not in out
    # ADR 0003: no relabelling as "available evidence" / "NVIDIA's public position".
    assert "available evidence" not in out and "public position" not in out
    assert "That sentence is the modal claim." in out
    assert rep["simulation_mechanics"]["sentences_removed"] == 3
    assert rep["leakage_flags"] == 0
