"""report_lint — 确定性编辑纪律 lint + 修复（WAVE9）。

把成稿/研究档案中的「机器语法与方法学泄漏」按可判定规则清理掉，让交付物读起来是
关于现实世界的机构级预测，而不是对内部多智能体推演的叙述。全部为**纯函数**
（无 ReportAgent 状态、无 LLM、无 IO），报告链与编排器均可直接调用：

    cleaned_md, lint_report = lint_report(md, lang, mode="final", spine=spine)

修复类别（确定性，围栏代码块内一律跳过）：
  * [citation:...](url) 残留 → 删除；
  * 原始图谱边转储「（依据：A --[REL]--> B）」→ 自然语言关系括注；孤悬的
    「(According to：」「（依据：」→ 删除；
  * 旧版模拟标签「模拟代理人「X」推演：」/「Simulation Agent「X」Deduction/Reasoning:」
    → 新专家小组转述规范（情景推演专家视角——「X」： / Analytical perspective — X
    (scenario panel):）；
  * 引文被删后孤悬的归因行（以 :/： 结尾、后接标题/普通段落）→ 删除（research 模式带引用的行保留）；
  * [simulation_outcomes] 等原始工具名引用记号 → 删除；
  * 流水线 pass 叙述（[Pass 2 working notes] 等括注）→ 删除（带引用/S<n> 的括注不删）；
    散文中的提及 → 仅标记；
  * 引用记号变体（【S1】/[S1-a]/[S1 / fact 8]；成稿另含 (S1)）→ 规整为 [S1]；
  * 重复整句（跨章节逐字重复且引用集合相同的长句；执行摘要与正文分域）→ 去重（保首删后）。

research 模式引用不变量：lint 绝不删除或凭空生成 [S#]——任何改写若改变正文被引来源的
集合或首次出现顺序，整条规则回退（见 lint_report）。

检测类别（只记数/采样，不改写——修复责任在上游翻译/重写通道）：
  * 跨语言污染行（英文稿中的 CJK 行 / 中文稿中的长英文散文行）；
  * 表格单元疑似截断（超长且无句末标点）；
  * 情景概率与预测骨架不一致（传入 spine 时交叉核对）；
  * Tier-2 模拟机制泄漏句（模式清单导出给 report_agent 的泄漏修复通道复用）。

独立观测（不在 lint_report 内，由 report_agent 单独调用；只记数/采样）：
  * check_projection_attribution（RESEARCH-5）——研究量化行里的预期值被正文写成已发生事实
    （projection_as_fact）等已报告/预期归因错位。
"""

from __future__ import annotations

from collections import Counter
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
import re
from typing import Any, Dict, List, Optional, Tuple

from ..utils.absence import MARKER_SENTINELS
from ..utils.dates import parse_as_of
from ..utils.quant_typing import quant_class

# ──────────────────────────────────────────────────────────────
# 基础：围栏感知的行遍历
# ──────────────────────────────────────────────────────────────

def _fence_mask(lines: List[str]) -> List[bool]:
    """返回与 lines 等长的布尔表：True = 该行处于（或本身是）围栏代码块。"""
    mask: List[bool] = []
    in_fence = False
    for ln in lines:
        s = ln.lstrip()
        if s.startswith("```") or s.startswith("~~~"):
            mask.append(True)          # 围栏标记行本身也不参与改写
            in_fence = not in_fence
            continue
        mask.append(in_fence)
    return mask


# ──────────────────────────────────────────────────────────────
# 模式：Tier-1 机器语法 + Tier-2 泄漏检测（EN + ZH）
# ──────────────────────────────────────────────────────────────

# [citation:...](url) / 无 URL 的 [citation:...] 残留
_CITATION_RESIDUE_RE = re.compile(r"\[citation:[^\]]*\](?:\([^)\s]*\))?")

# 括注式边转储：（依据：A --[REL]--> B；C --[REL2]--> D）
_EDGE_DUMP_PAREN_RE = re.compile(
    r"[（(]\s*(?:依据|According to)\s*[:：]?\s*([^（）()]*?--\[[A-Z_]+\]-->[^（）()]*?)\s*[）)]")
# 散文内联的裸箭头（括注外兜底）：只把 ' --[REL]--> ' 箭头换成关系动词，不猜实体边界。
_EDGE_ARROW_RE = re.compile(r"\s*--\[([A-Z_]+)\]-->\s*")
# 孤悬的「（依据：」「(According to：」（后无内容直到行尾）
_DANGLING_EDGE_INTRO_RE = re.compile(r"[（(]\s*(?:依据|According to)\s*[:：]?\s*$")

# 原始工具名引用记号（[simulation_outcomes] 被当作来源引用）
_TOOL_TOKEN_RE = re.compile(
    r"[\[【]\s*(?:simulation_outcomes|coalition_map|scenario_diff|opinion_shift|"
    r"insight_forge|panorama_search|interview_agents|trace_cascade|faction_brief)\s*[\]】]")

# 旧版模拟标签（末尾冒号捕获——引导引文的标签保留冒号，句中内联用法改成从句式转述）
_SIM_LABEL_EN_RE = re.compile(
    r"(?:模拟)?Simulation Agent\s*[「『\"']?([^」』\"'\n:：]{1,60}?)[」』\"']?\s*"
    r"(?:Deduction(?:\s*/\s*Reasoning)?|Reasoning|推演)((?:\s*[:：])?)", re.I)
_SIM_LABEL_ZH_RE = re.compile(
    r"模拟代理人\s*[「『\"']?([^」』\"'\n:：]{1,60}?)[」』\"']?\s*推演((?:\s*[:：])?)")
_SIM_LABEL_ZH_ALT_RE = re.compile(
    r"仿真\s*Agent\s*[「『\"']?(?P<name>[^」』\"'\n:：]{1,60}?)[」』\"']?\s*"
    r"(?P<role>[（(][^）)\n]{1,80}[）)])?\s*"
    r"(?:演绎\s*/\s*推理|推演|推理)(?P<colon>(?:\s*[:：])?)",
    re.I,
)
_SIM_LABEL_ZH_STATEMENT_RE = re.compile(
    r"仿真\s*Agent\s*[「『\"']?(?P<name>[^」』\"'\n:：]{1,60}?)[」』\"']?\s*"
    r"(?P<role>[（(][^）)\n]{1,80}[）)])?\s*的(?:表述|观点|判断|评估)",
    re.I,
)
_SIM_LABEL_GARBLE_RE = re.compile(r"模拟\s*Deduction(?:\s*/\s*Reasoning)?")

# pass 叙述：括注/方括号内含 Pass N / working notes → 可安全删除。
# 引用安全（C41）：括注内容不得含任何括号字符——匹配既不能在 [S#] 引用的 ']' 上收口，也
# 不能跨过引用吞掉整段带引用的括注；"Pass N" 只认首字母大写/全大写的流水线标签，小写
# "pass N" 须由介词引出（"cited in pass 4"）——散文里的动词用法 "(Congress must pass 12
# appropriations bills)" 不是叙述；内容含 S<n> 记号的括注可能本身就是引用，由
# strip_pass_narration 原样保留。
_PASS_BRACKET_INNER = r"[^\[\]【】()（）\n]"
_PASS_BRACKET_RE = re.compile(
    r"[\[（(【](?P<inner>" + _PASS_BRACKET_INNER + r"{0,80}?"
    r"(?:\b(?:Pass|PASS)\s*\d+\b"
    r"|(?i:\b(?:in|per|from|via|during|see|after)\s+(?:the\s+)?(?:research\s+)?)pass\s*\d+\b"
    r"|(?i:working notes)|工作笔记)"
    + _PASS_BRACKET_INNER + r"{0,80}?)[\]）)】]")
_PASS_PROSE_RE = re.compile(r"\bPass\s+\d+\b|working notes|工作笔记", re.I)

# 引用记号（[S1]/[S1, S3]/[S2/S3]/[S1-a]/【S1】/占位 [S?]）与其中的来源编号（GS2024 之类不算）。
_CITE_MARKER_RE = re.compile(r"[\[【]\s*S[\d?#][^\]】]*[\]】]")
_CITE_NUMBER_RE = re.compile(r"(?<![A-Za-z0-9])S(\d+)")
# A source number, optionally the start of a range whose end may drop the S
# ("S3-5", "S3–S5"): ranges expand to every id in between (bounded).
_CITE_ID_RANGE_RE = re.compile(r"(?<![A-Za-z0-9])S(\d+)(?:[ \t]*+[-–—~][ \t]*+S?(\d+))?")
_CITE_RANGE_MAX = 20


def _citation_ids(token: str) -> List[str]:
    """Source numbers of one citation marker in order, ranges expanded
    ("[S3-5]" → 3, 4, 5); a reversed or implausibly long range keeps its two ends."""
    ids: List[str] = []
    for m in _CITE_ID_RANGE_RE.finditer(token or ""):
        start, end = int(m.group(1)), int(m.group(2)) if m.group(2) else None
        if end is not None and start < end <= start + _CITE_RANGE_MAX:
            nums = [str(n) for n in range(start, end + 1)]
        else:
            nums = [m.group(1)] + ([m.group(2)] if m.group(2) else [])
        for num in nums:
            if num not in ids:
                ids.append(num)
    return ids

# 引用记号变体 → [S{n}]（记号内的每个来源编号都保留：[S2/S3] → [S2][S3]）
_CITE_VARIANT_RES: List[re.Pattern] = [
    re.compile(r"【\s*S(\d+)[^】]*】"),                 # 【S1】/【S1-a】
    re.compile(r"\[\s*S(\d+)-[A-Za-z0-9]+\s*\]"),      # [S1-a]
    re.compile(r"\[\s*S(\d+)\s*/[^\]]*\]"),            # [S1 / fact 8]
    re.compile(r"\[\s*S(\d+)[ \t]*+[–—~][ \t]*+S?\d+\s*\]"),  # [S3–S5] / [S3—5]（区间，展开）
]
# 圆括号 (S1)：成稿里是引用变体；研究档案里是旧版提示词教的来源分级标签
# （"primary (S1) and high-quality secondary (S2) sources"）——research 模式不当引用规整（C44）。
_CITE_PAREN_VARIANT_RE = re.compile(r"\(\s*S(\d+)\s*\)")

# CJK 字符类（与 report_agent._CJK_CHAR 同源）
_CJK_CHAR = r"一-鿿㐀-䶿぀-ヿ가-힯"
_CJK_RUN_RE = re.compile(r"[" + _CJK_CHAR + r"]{2,}")
_LATIN_PROSE_RE = re.compile(r"[A-Za-z][A-Za-z0-9 ,.'’\-()%/&]{39,}")
_LANG_INLINE_PROTECTED_RE = re.compile(r"`[^`\n]*`|https?://[^\s)>\]}]+", re.I)

# ── Tier-2 泄漏检测模式（EN + ZH；导出供 report_agent 泄漏修复复用）──
LEAKAGE_PATTERNS: List[Tuple[str, re.Pattern]] = [
    # EN
    ("generation_failure_placeholder", re.compile(
        r"Chapter generation failed|章节生成失败|模型反复未能产出合格文本", re.I)),
    ("simulation_agent_label", re.compile(r"\bSimulation Agent\b")),
    ("deduction_reasoning", re.compile(r"Deduction\s*/\s*Reasoning")),
    ("the_simulation", re.compile(r"\bthe simulation(?:['’]s)?\b", re.I)),
    ("simulated_world", re.compile(r"\b(?:the|this|a) simulated world\b", re.I)),
    ("internal_harness_narration", re.compile(
        r"\b(?:the\s+)?harness(?:['’]s)?\b|\bagent clusters?\b|"
        r"\bsimulated environment\b|\bsimulation-derived\b|"
        r"\bworld[- ]state outputs?\b", re.I)),
    ("simulation_surfaced", re.compile(r"simulation (?:consistently |repeatedly )?surfaced", re.I)),
    ("n_actor_simulation", re.compile(r"\b\d+[- ](?:actor|agent|entity) simulation\b", re.I)),
    ("n_actions", re.compile(r"\b\d+\s+actions\b", re.I)),
    ("round_n", re.compile(r"\bround\s+\d+\b", re.I)),
    ("internal_agent_counts", re.compile(
        r"\b\d[\d,]*\s+(?:active\s+)?agents?\b", re.I)),
    ("internal_edge_counts", re.compile(
        r"\b\d[\d,]*\s+(?:directed\s+)?(?:edges|relationships)\b", re.I)),
    ("internal_action_telemetry", re.compile(
        r"\b(?:action-type distribution|ratio of liking to posting|"
        r"posts?\s+(?:vs\.?|versus)\s+\d+\s+likes?|"
        r"\d+\s+likes?\s*(?:,|and)\s*\d+\s+posts?)\b", re.I)),
    ("internal_round_cluster", re.compile(
        r"\b(?:across rounds?|clusters? of agents?|coalition-formation phase)\b", re.I)),
    ("internal_graph_narration", re.compile(
        r"\b(?:the graph (?:contains|places|shows)|causal neighborhood|"
        r"faction map|agent graph|coalition map)\b", re.I)),
    ("internal_graph_process", re.compile(
        r"\b(?:research graph|forecast graph|simulation graph|China subgraph|"
        r"sub-simulation|\d+[- ]edge graph|\d+[- ]agent convergence|"
        r"shared interaction targets|single node moving|"
        r"no node where|forecast graph|remaining Trump-neighborhood dependencies)\b", re.I)),
    ("internal_graph_telemetry", re.compile(
        r"\b(?:post-to-like ratio|combined actions?|network traffic|"
        r"action signatures?|consensus-seeking\s*\+\s*authority-projection|"
        r"consensus-keepers?|authority-projectors?|"
        r"count the action signatures)\b", re.I)),
    ("raw_ontology_relation", re.compile(
        r"\b(?:CAUSES|ENABLES|CONSTRAINS|TRIGGERS|ACCELERATES|INFLUENCES|"
        r"OPPOSES?|SUPPLIES|PARTNERS_WITH|COMPETES_WITH|FUNDED_BY|"
        r"INHERITS_R_AND_D_FROM|COMPOUND_PARITY_WITH)\b")),
    ("bold_graph_relation", re.compile(
        r"\*\*[^*\n]{2,120}\b(?:causes?|enables?|influences?|supplies|"
        r"opposes?)\b[^*\n]{1,120}\*\*", re.I)),
    ("simulated_evidence_data", re.compile(
        r"\bsimulated (?:data|evidence|world)\b", re.I)),
    ("named_proxy_agent", re.compile(
        r"\b(?:NVIDIA|AMD|Intel|TSMC|ASML|OpenAI|Anthropic|Google|Meta|"
        r"Microsoft|Amazon|Trump|Xi)\s+agent\b", re.I)),
    ("action_type_tokens", re.compile(
        r"\b(?:CREATE_POST|CREATE_COMMENT|LIKE_POST|LIKE_COMMENT|REPOST|QUOTE_POST|UNFOLLOW)\b")),
    ("agent_mechanics_en", re.compile(
        r"(?:\b(?:simulation|simulated|agent-based model)\b[^\n.!?]{0,80}"
        r"\bagent (?:discourse|network|behavio(?:r|ur))\b"
        r"|\bagent (?:discourse|network|behavio(?:r|ur))\b[^\n.!?]{0,80}"
        r"\b(?:simulation|simulated|agent-based model)\b"
        r"|\b(?:simulation|simulated|agent-based model)\b[^\n.!?]{0,80}"
        r"\bmost active agents?\b"
        r"|\bmost active agents?\b[^\n.!?]{0,80}"
        r"\b(?:simulation|simulated|agent-based model)\b)", re.I)),
    # These are valid real-world analytical concepts, so only classify them as
    # mechanics when the same sentence explicitly ties them to the simulation.
    ("sim_inference_terms_en", re.compile(
        r"(?:\b(?:simulation|simulated agents?|agent-based model|forecast model)\b"
        r"[^\n.!?]{0,100}\b(?:consensus formation|revealed preferences?)\b"
        r"|\b(?:consensus formation|revealed preferences?)\b[^\n.!?]{0,100}"
        r"\b(?:simulation|simulated agents?|agent-based model|forecast model)\b)", re.I)),
    ("sim_causal_graph", re.compile(
        r"(?:simulation|模拟)[^\n]{0,20}causal graph|causal graph[^\n]{0,20}(?:simulation|模拟)", re.I)),
    ("raw_edge", re.compile(r"--\[[A-Z_]+\]-->")),
    # ZH
    ("sim_agent_zh", re.compile(
        r"模拟代理人|模拟推演|模拟世界|本次模拟|模拟中|模拟的")),
    # 轮次/逐轮 are also real-world words (融资轮次 funding rounds, 谈判轮次): like
    # the English round_n / across-rounds patterns, only a numbered round, "across
    # rounds", or a sentence that ties rounds to the simulation is mechanics.
    ("sim_mechanics_zh", re.compile(
        r"次动作|峰值轮次|最活跃\s*Agent|派系图|派系聚类|因果图"
        r"|上帝视角|采访实录|模拟量化"
        r"|第\s*\d+\s*轮次|轮次\s*\d+|跨轮次"
        r"|(?:模拟|推演|仿真|智能体|Agent)[^。！？\n]{0,40}(?:轮次|逐轮)"
        r"|(?:轮次|逐轮)[^。！？\n]{0,40}(?:模拟|推演|仿真|智能体|Agent)")),
    ("sim_inference_terms_zh", re.compile(
        r"(?:(?:模拟|推演|智能体)[^。！？\n]{0,60}(?:共识形成|揭示性偏好|行为信号)"
        r"|(?:共识形成|揭示性偏好|行为信号)[^。！？\n]{0,60}(?:模拟|推演|智能体))")),
    # REPORT-4：提示词里的类型化缺失标记（utils/absence.py）被抄进正文 = 泄漏；哨兵短语只出现在
    # 标记文本里，final 模式整句删除。
    ("absence_marker_leak", re.compile(
        "|".join(re.escape(phrase) for phrase in MARKER_SENTINELS), re.I)),
]

# 平台行为引文（发帖/点赞/评论机制内容——应删除而非转写）
PLATFORM_BEHAVIOR_RE = re.compile(
    r"发帖|点赞|转发了?|关注了|在\s*(?:推特|Twitter|Reddit)\s*上发"
    r"|\bposted (?:a|the) (?:post|thread)\b|\bliked (?:a|the) post\b"
    r"|\bcommented on (?:a|the) post\b|\bretweet(?:ed)?\b|\brepost(?:ed)?\b", re.I)

# 关系动词映射（EN 名词短语 / ZH 名词）
_REL_EN = {
    "SUPPLIES": "supply", "COMPETES_WITH": "competitive", "DEPENDS_ON": "dependency",
    "REGULATES": "regulatory", "FUNDS": "funding", "CUSTOMER_OF": "customer",
    "PARTNERS_WITH": "partnership", "INVESTS_IN": "investment", "OWNS": "ownership",
    "SANCTIONS": "sanctions", "ACQUIRES": "acquisition", "LICENSES": "licensing",
}
_REL_ZH = {
    "SUPPLIES": "供应", "COMPETES_WITH": "竞争", "DEPENDS_ON": "依赖",
    "REGULATES": "监管", "FUNDS": "注资", "CUSTOMER_OF": "采购",
    "PARTNERS_WITH": "合作", "INVESTS_IN": "投资", "OWNS": "控股",
    "SANCTIONS": "制裁", "ACQUIRES": "并购", "LICENSES": "授权",
}
# 内联箭头替换用的动词形式（'A --[SUPPLIES]--> B' → 'A supplies B' / 'A 供应 B'）
_REL_VERB_EN = {
    "SUPPLIES": "supplies", "COMPETES_WITH": "competes with", "DEPENDS_ON": "depends on",
    "REGULATES": "regulates", "FUNDS": "funds", "CUSTOMER_OF": "is a customer of",
    "PARTNERS_WITH": "partners with", "INVESTS_IN": "invests in", "OWNS": "owns",
    "SANCTIONS": "sanctions", "ACQUIRES": "acquires", "LICENSES": "licenses",
}


def _rel_phrase(rel: str, zh: bool) -> str:
    rel = (rel or "").strip().upper()
    if zh:
        return _REL_ZH.get(rel, rel.replace("_", " ").lower())
    return _REL_EN.get(rel, rel.replace("_", " ").lower())


def _rel_verb(rel: str, zh: bool) -> str:
    rel = (rel or "").strip().upper()
    if zh:
        return _REL_ZH.get(rel, rel.replace("_", " ").lower())
    return _REL_VERB_EN.get(rel, rel.replace("_", " ").lower())


def _is_zh(lang: str) -> bool:
    return not str(lang or "").strip().lower().startswith("en")


# ──────────────────────────────────────────────────────────────
# 修复原语（纯函数；均返回 (new_text, count...)）
# ──────────────────────────────────────────────────────────────

def strip_citation_residue(md: str) -> Tuple[str, int]:
    """删除 [citation:...](url) / [citation:...] 残留记号。"""
    n = 0
    lines = (md or "").split("\n")
    mask = _fence_mask(lines)
    for i, ln in enumerate(lines):
        if mask[i]:
            continue
        new_ln, k = _CITATION_RESIDUE_RE.subn("", ln)
        if k:
            lines[i] = re.sub(r"[ \t]{2,}", " ", new_ln)
            n += k
    return "\n".join(lines), n


def rewrite_edge_dumps(md: str, lang: str = "English") -> Tuple[str, int, int]:
    """括注式边转储 → 自然语言关系括注；孤悬「（依据：」→ 删除。

    返回 (new_md, 转写的括注数, 删除的孤悬引子数)。散文内联的裸边（无括注包裹）
    也一并转写为自然语言。"""
    zh = _is_zh(lang)
    converted = 0
    dangling = 0

    def _render_edges(payload: str) -> str:
        parts: List[str] = []
        # 括注内可能有多条边（；/; 分隔）——先切再逐条解析，尾实体不被空格截断。
        for piece in re.split(r"[；;]", payload):
            m = re.match(r"\s*(.{1,80}?)\s*--\[([A-Z_]+)\]-->\s*(.{1,80}?)\s*$", piece)
            if not m:
                continue
            a, rel, b = m.group(1).strip(), m.group(2), m.group(3).strip()
            if not a or not b:
                continue
            if zh:
                parts.append(f"{a}与{b}的{_rel_phrase(rel, True)}关系")
            else:
                parts.append(f"{a}'s {_rel_phrase(rel, False)} relationship with {b}")
        if not parts:
            return ""
        if zh:
            return "（基于" + "、".join(parts) + "）"
        return "(reflecting " + " and ".join(parts) + ")"

    lines = (md or "").split("\n")
    mask = _fence_mask(lines)
    for i, ln in enumerate(lines):
        if mask[i]:
            continue
        new_ln = ln
        for m in list(_EDGE_DUMP_PAREN_RE.finditer(new_ln)):
            rendered = _render_edges(m.group(1))
            new_ln = new_ln.replace(m.group(0), rendered, 1)
            converted += 1
        # 散文内联裸箭头（未被括注包裹）：只换箭头为关系动词，不猜实体边界。
        new_ln, k_arrow = _EDGE_ARROW_RE.subn(
            lambda m: f" {_rel_verb(m.group(1), zh)} ", new_ln)
        converted += k_arrow
        stripped, k = _DANGLING_EDGE_INTRO_RE.subn("", new_ln)
        if k:
            new_ln = stripped.rstrip()
            dangling += k
        if new_ln != ln:
            lines[i] = new_ln
    return "\n".join(lines), converted, dangling


def rewrite_sim_labels(md: str, lang: str = "English") -> Tuple[str, int]:
    """旧版模拟代理人标签 → 新专家小组转述规范。EN/ZH 标签各自映射到对应语言的新规范。

    标签带冒号（引导引文）→ 新标签保留冒号；句中内联用法（无冒号）→ 从句式转述，
    不生造「…(scenario panel):pushes back」型粘连。"""
    n = 0

    def _en_repl(m: re.Match) -> str:
        name = m.group(1).strip()
        if m.group(2):
            return f"Evidence-based assessment — {name}:"
        return f"the evidence-based assessment for {name}"

    def _zh_repl(m: re.Match) -> str:
        name = m.group(1).strip()
        if m.group(2):
            return f"证据分析——「{name}」："
        return f"关于「{name}」的证据分析"

    def _zh_alt_repl(m: re.Match) -> str:
        name = m.group("name").strip()
        role = str(m.group("role") or "").strip()
        subject = f"「{name}」{role}"
        if m.group("colon"):
            return f"证据分析——{subject}："
        return f"关于{subject}的证据分析"

    def _zh_statement_repl(m: re.Match) -> str:
        name = m.group("name").strip()
        role = str(m.group("role") or "").strip()
        return f"「{name}」{role}的证据分析"

    lines = (md or "").split("\n")
    mask = _fence_mask(lines)
    for i, ln in enumerate(lines):
        if mask[i]:
            continue
        new_ln, k1 = _SIM_LABEL_EN_RE.subn(_en_repl, ln)
        new_ln, k2 = _SIM_LABEL_ZH_RE.subn(_zh_repl, new_ln)
        new_ln, k3 = _SIM_LABEL_ZH_ALT_RE.subn(_zh_alt_repl, new_ln)
        new_ln, k4 = _SIM_LABEL_ZH_STATEMENT_RE.subn(_zh_statement_repl, new_ln)
        new_ln, k5 = _SIM_LABEL_GARBLE_RE.subn("证据分析", new_ln)
        if k1 or k2 or k3 or k4 or k5:
            lines[i] = new_ln
            n += k1 + k2 + k3 + k4 + k5
    return "\n".join(lines), n


def strip_tool_tokens(md: str) -> Tuple[str, int]:
    """删除 [simulation_outcomes] 等原始工具名引用记号。"""
    n = 0
    lines = (md or "").split("\n")
    mask = _fence_mask(lines)
    for i, ln in enumerate(lines):
        if mask[i]:
            continue
        new_ln, k = _TOOL_TOKEN_RE.subn("", ln)
        if k:
            lines[i] = re.sub(r"[ \t]{2,}", " ", new_ln).rstrip()
            n += k
    return "\n".join(lines), n


# 归因线索（孤悬归因行删除的保守门：须像「某人/某视角 说/认为…：」）
_ATTRIBUTION_CUE_RE = re.compile(
    r"视角|表示|认为|指出|强调|反驳|推演|专家|警告|panel|perspective|argu|says|said|notes?d?\b"
    r"|according to|pushes? back|contend|assert|warn|observ|\bagent\b", re.I)


def remove_dangling_attributions(md: str, keep_cited: bool = False) -> Tuple[str, int]:
    """删除孤悬的引文归因行：以 :/： 结尾、含归因线索、其后（隔空行）不是引用块/列表/表格。

    典型成因：引文接地修复删掉了 blockquote，留下「X pushes back …:」的空引子。
    keep_cited=True（research 模式）：带 [S#] 引用的行是有出处的论断，保留——lint 不删引用。"""
    lines = (md or "").split("\n")
    mask = _fence_mask(lines)
    delete: set = set()
    for i, ln in enumerate(lines):
        if mask[i]:
            continue
        s = ln.strip()
        if not s or not s.endswith((":", "：")):
            continue
        if s.startswith(("#", ">", "|", "-", "*", "```", "~~~")) or re.match(r"^\d+[.、)]", s):
            continue
        if keep_cited and _has_citation(s):
            continue
        if not _ATTRIBUTION_CUE_RE.search(s):
            continue
        # 找下一个非空行
        j = i + 1
        while j < len(lines) and not lines[j].strip():
            j += 1
        if j >= len(lines):
            delete.add(i)          # 文档末尾的孤悬引子
            continue
        nxt = lines[j].strip()
        if nxt.startswith((">", "-", "*", "|", "```", "~~~")) or re.match(r"^\d+[.、)]", nxt):
            continue               # 引子后确有引用块/列表/表格 → 合法引子
        delete.add(i)              # 后面是标题或普通段落 → 引子已孤悬
    if not delete:
        return md, 0
    out: List[str] = [ln for i, ln in enumerate(lines) if i not in delete]
    # 折叠删除后产生的连续空行
    txt = re.sub(r"\n{3,}", "\n\n", "\n".join(out))
    return txt, len(delete)


def _strip_pass_brackets(line: str) -> Tuple[str, int]:
    """删除一行内的 pass 叙述括注；内容含 S<n> 记号的括注原样保留。返回 (新行, 删除数)。"""
    removed = 0

    def _repl(m: re.Match) -> str:
        nonlocal removed
        if _CITE_NUMBER_RE.search(m.group("inner")):
            return m.group(0)
        removed += 1
        return ""

    return _PASS_BRACKET_RE.sub(_repl, line), removed


def strip_pass_narration(md: str) -> Tuple[str, int, int]:
    """括注式 pass 叙述（[Pass 2 working notes] 等）→ 删除；散文提及 → 仅计数。

    引用安全：含 S<n> 记号的括注（如 [S37 Pass 4]）可能本身就是引用，原样保留、只计入
    flagged——lint 绝不删除 [S#] 记号。"""
    stripped = 0
    lines = (md or "").split("\n")
    mask = _fence_mask(lines)
    for i, ln in enumerate(lines):
        if mask[i]:
            continue
        new_ln, k = _strip_pass_brackets(ln)
        if k:
            lines[i] = re.sub(r"[ \t]{2,}", " ", new_ln).rstrip()
            stripped += k
    txt = "\n".join(lines)
    return txt, stripped, _count_pass_mentions(txt)


def _count_pass_mentions(md: str) -> int:
    """围栏外的 pass 叙述提及数（只标记不改写）。"""
    lines = (md or "").split("\n")
    mask = _fence_mask(lines)
    return sum(len(_PASS_PROSE_RE.findall(ln)) for i, ln in enumerate(lines) if not mask[i])


def _canonical_citation(m: re.Match) -> str:
    """变体记号 → 规范 [S{n}]；记号内出现的每个来源编号按序保留（[S2/S3] → [S2][S3]，
    区间展开：[S3-5] → [S3][S4][S5]），只丢注释（-a / fact 8 / -context），绝不丢引用。"""
    nums = _citation_ids(m.group(0)) or [m.group(1)]
    return "".join(f"[S{num}]" for num in nums)


def normalize_citation_variants(md: str, paren_labels: bool = True) -> Tuple[str, int]:
    """引用记号变体（【S1】/[S1-a]/[S1 / fact 8]，以及 paren_labels=True 时的 (S1)）→ 规整为 [S1]。

    paren_labels=False（research 模式）：圆括号 (S1) 是来源分级标签而非引用，原样保留——
    否则会在 bridge 校验完引用之后凭空生成引用/悬空引用。"""
    n = 0
    patterns = _CITE_VARIANT_RES + ([_CITE_PAREN_VARIANT_RE] if paren_labels else [])
    lines = (md or "").split("\n")
    mask = _fence_mask(lines)
    for i, ln in enumerate(lines):
        if mask[i]:
            continue
        new_ln = ln
        for pat in patterns:
            new_ln, k = pat.subn(_canonical_citation, new_ln)
            n += k
        if new_ln != ln:
            lines[i] = new_ln
    return "\n".join(lines), n


def detect_language_contamination(md: str, lang: str) -> Dict[str, Any]:
    """Detect foreign-language report text across structured Markdown.

    Fenced code is excluded. Headings, quotes, tables, and linked prose are included;
    only inline-code and URL destination tokens are masked, so a URL never exempts the
    rest of its line or a human-readable link label.
    """
    zh_target = _is_zh(lang)
    lines = (md or "").split("\n")
    mask = _fence_mask(lines)
    hits = 0
    samples: List[str] = []
    in_references = False
    for i, ln in enumerate(lines):
        if mask[i]:
            continue
        s = ln.strip()
        if not s:
            continue
        if s in ("## References", "## 参考来源"):
            in_references = True
            continue
        if in_references:
            # Original-language publication titles are citation metadata, not a
            # prose-language switch. The finalizer always places References last.
            continue
        scan = _LANG_INLINE_PROTECTED_RE.sub(" ", s)
        if zh_target:
            found = [c for c in _LATIN_PROSE_RE.findall(scan) if c.count(" ") >= 4]
        else:
            found = _CJK_RUN_RE.findall(scan)
        if found:
            hits += 1
            if len(samples) < 5:
                samples.append(s[:90])
    return {"lines": hits, "samples": samples}


def detect_table_cell_truncation(md: str, min_len: int = 160) -> List[str]:
    """表格单元疑似截断：超长且以字母/数字结尾（无句末标点）→ 采样标记（不改写）。"""
    out: List[str] = []
    lines = (md or "").split("\n")
    mask = _fence_mask(lines)
    for i, ln in enumerate(lines):
        if mask[i] or not ln.strip().startswith("|"):
            continue
        if re.match(r"^\s*\|[\s\-:|]+\|\s*$", ln):
            continue                            # 分隔行
        for cell in ln.strip().strip("|").split("|"):
            c = cell.strip()
            if len(c) >= min_len and c and (c[-1].isalnum()):
                out.append(c[-60:])
                if len(out) >= 8:
                    return out
    return out


_CITATION_SUFFIX_RE = re.compile(
    r"(?:\[\s*S\d+[^\]\n]*\]|【\s*S\d+[^】\n]*】)", re.I)
_SENTENCE_CLOSERS = frozenset("\"'”’」』）》】)")


def _split_sentences(text: str) -> List[str]:
    """Split prose without discarding punctuation, citations, or whitespace.

    English sentence terminals retain the historical whitespace/end-of-text
    boundary rule (so decimals and dotted identifiers are not split). Chinese
    terminals are boundaries even when the next sentence has no whitespace.
    A citation following terminal punctuation (directly or after spaces)
    belongs to the preceding sentence, as do closing quotation marks.
    """
    value = str(text or "")
    if not value:
        return []
    parts: List[str] = []
    start = 0
    index = 0
    while index < len(value):
        terminal = value[index]
        if terminal not in "。！？.!?":
            index += 1
            continue
        cursor = index + 1
        while cursor < len(value) and value[cursor] in _SENTENCE_CLOSERS:
            cursor += 1
        # Citations follow terminal punctuation ("claim.[S2]", "claim. [S2]");
        # keep them with the claim instead of opening the next sentence with an
        # orphan marker (a later duplicate of that fragment would take the
        # citation away from its own claim).
        while True:
            probe = cursor
            while probe < len(value) and value[probe] in " \t":
                probe += 1
            citation = _CITATION_SUFFIX_RE.match(value, probe)
            if citation is None:
                break
            cursor = citation.end()
            while cursor < len(value) and value[cursor] in _SENTENCE_CLOSERS:
                cursor += 1
        is_boundary = (
            terminal in "。！？"
            or cursor >= len(value)
            or value[cursor].isspace()
        )
        if not is_boundary:
            index += 1
            continue
        while cursor < len(value) and value[cursor].isspace():
            cursor += 1
        parts.append(value[start:cursor])
        start = cursor
        index = cursor
    if start < len(value):
        parts.append(value[start:])
    return parts


# 研究档案/成稿末尾的参考来源节标题——引用守卫只看它之前的正文。
_REFERENCES_HEADING_RE = re.compile(
    r"^\s{0,3}#{1,6}\s*(?:\d+[.、)]\s*)?(?:references|sources|bibliography|works cited|citations|"
    r"source list|sources and references|references and sources|"
    r"参考来源|参考文献|参考资料|资料来源|引用来源|来源)\s*$", re.I)
_MD_HEADING_RE = re.compile(r"^\s{0,3}(#{1,6})\s+(.*?)\s*#*\s*$")
# 执行摘要类标题（有界别名 + "executive summary"/"执行摘要" 子串；不做模糊匹配）。
_SUMMARY_HEADING_ALIASES = frozenset({
    "summary", "abstract", "key takeaways", "key findings", "key findings summary",
    "bottom line", "tl dr", "tldr", "executive overview", "management summary",
    "summary of findings", "research summary", "overview and summary",
    "摘要", "执行概要", "研究摘要", "核心摘要", "内容摘要", "概要", "摘要与核心结论",
    "核心结论", "关键结论",
})


def _norm_sentence(s: str) -> str:
    t = _CITE_MARKER_RE.sub("", s)
    t = re.sub(r"[*_`\"'“”‘’「」『』\s]+", "", t)
    return t.lower()


def _has_citation(s: str) -> bool:
    """文本是否含指向具体来源编号的引用记号（[S1]/[S1, S3]/【S1】…；(S1) 不算）。"""
    return any(_CITE_NUMBER_RE.search(tok) for tok in _CITE_MARKER_RE.findall(s))


def _citation_signature(s: str) -> frozenset:
    """句子引用的来源集合（[S1][S3] 与 [S1, S3] 等价；占位记号按原文比较）。"""
    ids: set = set()
    for tok in _CITE_MARKER_RE.findall(s):
        nums = _citation_ids(tok)
        ids.update(nums if nums else [re.sub(r"\s+", "", tok)])
    return frozenset(ids)


def _is_summary_heading(title: str) -> bool:
    """标题是否为执行摘要类小节（容忍前导编号与强调记号）。"""
    t = re.sub(r"[*_`]", "", title or "")
    t = re.sub(r"^\s*(?:\d+(?:\.\d+)*[.、)]?|[一二三四五六七八九十]+[、.．]|[IVX]+\.)\s*", "", t)
    key = re.sub(r"[\s\-–—_:：/|'’（）()&;；,，]+", " ", t).strip(" .!?！？。").lower()
    compact = key.replace(" ", "")
    return (key in _SUMMARY_HEADING_ALIASES or compact in _SUMMARY_HEADING_ALIASES
            or "executive summary" in key or "exec summary" in key
            or "执行摘要" in compact or "执行概要" in compact)


def _body_citations(md: str) -> List[str]:
    """正文（围栏外、末个参考来源节本身之外）每个引用记号的来源编号，按出现顺序、含重复。

    参考来源节 = 末个参考来源标题到下一个同级或更高级标题（或文末）；其后的正文照常计入。"""
    lines = (md or "").split("\n")
    mask = _fence_mask(lines)
    ref_start, ref_end = len(lines), len(lines)
    for i, ln in enumerate(lines):
        if not mask[i] and _REFERENCES_HEADING_RE.match(ln):
            ref_start = i
    if ref_start < len(lines):
        level = len(re.match(r"^\s{0,3}(#{1,6})", lines[ref_start]).group(1))
        for j in range(ref_start + 1, len(lines)):
            heading = _MD_HEADING_RE.match(lines[j])
            if not mask[j] and heading and len(heading.group(1)) <= level:
                ref_end = j
                break
    ids: List[str] = []
    for i, ln in enumerate(lines):
        if mask[i] or ref_start <= i < ref_end:
            continue
        for tok in _CITE_MARKER_RE.findall(ln):
            ids.extend(_citation_ids(tok))
    return ids


def _cited_sequence(md: str) -> List[str]:
    """正文所引来源编号的首次出现顺序（见 _body_citations）。

    [S#] 在下游按位置索引 sources.json、References 须等于被引集合——research 模式的引用
    守卫要求任何改写都不改变这个序列（既不删除也不凭空生成引用）。"""
    return list(dict.fromkeys(_body_citations(md)))


def dedup_duplicate_sentences(md: str, min_chars: int = 60) -> Tuple[str, int]:
    """跨章节逐字重复的长句去重（保留首次出现，删除后续重复）。

    仅作用于散文段落行（跳过标题/引用/列表/表格/围栏），归一化后 >= min_chars 的
    整句重复才判定——短句/套话不动，避免误伤。

    引用安全（C16/C42）：
      * 重复键 = 归一化正文 + 引用来源集合——同句引用不同来源时两份都保留（删掉后一份会让
        只在那里被引用的来源孤悬、References 与被引集合失配）；
      * 执行摘要与正文分域去重：摘要写在最后却排在最前（由各节首句写成），正文章节的首句
        绝不因摘要先复述过而被删，摘要也不因正文而被删。
    因此被删的只可能是同域内、与更早保留句引用集合完全相同的副本——被引集合与首次出现
    顺序都不变。"""
    seen: Dict[bool, set] = {True: set(), False: set()}   # in_summary → 已见 (正文, 引用集合)
    in_summary = False
    summary_level = 0
    removed = 0
    lines = (md or "").split("\n")
    mask = _fence_mask(lines)
    for i, ln in enumerate(lines):
        if mask[i]:
            continue
        heading = _MD_HEADING_RE.match(ln)
        if heading:
            level = len(heading.group(1))
            if _is_summary_heading(heading.group(2)):
                in_summary, summary_level = True, level
            elif in_summary and level <= max(summary_level, 2):
                in_summary = False          # 同级/更高级（或任一 H1/H2）标题结束摘要节
            continue
        s = ln.strip()
        if not s or s.startswith(("#", ">", "|", "-", "*", "!")) or re.match(r"^\d+[.、)]", s):
            continue
        sentences = _split_sentences(ln)
        if len(sentences) <= 0:
            continue
        scope = seen[in_summary]
        kept: List[str] = []
        changed = False
        for sent in sentences:
            key = _norm_sentence(sent)
            if len(key) >= min_chars:
                ident = (key, _citation_signature(sent))
                if ident in scope:
                    removed += 1
                    changed = True
                    continue
                scope.add(ident)
            kept.append(sent)
        if changed:
            lines[i] = "".join(x for x in kept if x.strip()).strip()
    return "\n".join(lines), removed


def check_scenario_probabilities(md: str, spine: Optional[Dict[str, Any]],
                                 alias_aware: bool = False) -> List[str]:
    """情景概率交叉核对（spine 为唯一真值源）：正文中情景名附近的百分比须与骨架一致（±1pt）。

    REPORT-3：alias_aware=True（REPORT_LOGIC_NUMBER_GATE=numeric）时再并入别名槽不符
    （logic_number.s11_mismatches，「基准情景（40%）」对 A=0.35），同一格式、去重后同受 8 条上限；
    默认 False 时输出逐字节不变。只检测不改写。"""
    if not isinstance(spine, dict):
        return []
    issues: List[str] = []
    text = md or ""
    for s in (spine.get("scenarios") or []):
        if not isinstance(s, dict):
            continue
        if s.get("probability") is None:
            continue  # REPORT-1：待复核（null）概率无可比对的值，不当作 0% 比对
        name = str(s.get("name") or "").strip()
        try:
            p = round(float(s.get("probability") or 0.0) * 100)
        except (TypeError, ValueError):
            continue
        if len(name) < 4:
            continue
        idx = text.find(name)
        if idx < 0:
            continue
        window = text[max(0, idx - 18):idx + len(name) + 55]
        pcts = [int(m.group(1)) for m in re.finditer(r"(\d{1,3})\s*%", window)
                if 0 <= int(m.group(1)) <= 100]
        if not pcts or any(abs(pv - p) <= 1 for pv in pcts):
            continue
        near = [pv for pv in pcts if abs(pv - p) <= 60]
        if near:
            pv = min(near, key=lambda x: abs(x - p))
            issues.append(f"scenario '{name[:28]}': prose {pv}% vs spine {p}%")
    if alias_aware:
        from .logic_number import s11_mismatches  # 惰性：仅 numeric 需要，模块级不引入服务层依赖

        for message in s11_mismatches(text, spine.get("scenarios") or [], reference="spine"):
            if message not in issues:
                issues.append(message)
    return issues[:8]


def leakage_hits(text: str) -> List[str]:
    """返回命中的 Tier-2 泄漏模式名列表（含重复命中，供计数）。"""
    hits: List[str] = []
    lines = (text or "").split("\n")
    mask = _fence_mask(lines)
    visible = "\n".join(
        line for index, line in enumerate(lines) if not mask[index]
    )
    for name, pat in LEAKAGE_PATTERNS:
        hits.extend(name for _ in pat.finditer(visible))
    return hits


def strip_leakage_sentences(text: str, max_scan: int = 400) -> Tuple[str, int]:
    """把散文文本中命中 Tier-2 泄漏模式的**整句**删除（用于 key-points 提炼与重写后兜底）。"""
    if not text:
        return text or "", 0
    sentences = _split_sentences(text)
    kept: List[str] = []
    removed = 0
    for sent in sentences[:max_scan]:
        if any(pat.search(sent) for _, pat in LEAKAGE_PATTERNS):
            removed += 1
            continue
        kept.append(sent)
    kept.extend(sentences[max_scan:])
    return "".join(x for x in kept if x.strip()).strip(), removed


_SIMULATION_OUTCOME_REWRITES: List[Tuple[re.Pattern, str]] = [
    (re.compile(
        r"\bthe simulated world we constructed,\s*populated by\s*"
        r"\d[\d,]*\s+active agents?\s+and\s+\d[\d,]*\s+relationships,\s*treats\b",
        re.I,
    ), "the cross-actor evidence treats"),
    (re.compile(
        r"\bin the simulated world,\s*(\d+)\s+binary forecasts are laid out as\b",
        re.I,
    ), r"The report defines \1 binary forecasts as"),
    (re.compile(r"\b(?:the|this) simulation(?:['’]s)?\s+power map\b", re.I),
     "the actor-power evidence"),
    (re.compile(r"\b(?:the|this) simulated world\b", re.I),
     "the forecast evidence base"),
    (re.compile(r"\b(?:the\s+)?\d+-agent (?:bloc|faction|mega-coalition)\b", re.I),
     "the cross-camp coalition"),
    (re.compile(r"\bCoalition\s+1\b", re.I), "the cross-camp coalition"),
    (re.compile(r"\bagent graph\b", re.I), "stakeholder network"),
    (re.compile(r"\bfaction map\b", re.I), "stakeholder alignment map"),
    (re.compile(r"\bcausal neighborhood\b", re.I), "policy-leverage profile"),
    (re.compile(r"\bthe\s+\d+-actor faction graph\b", re.I),
     "the real-world actor relationship network"),
    (re.compile(r"\bTrump['’]s 11-edge graph\b", re.I),
     "Trump's concentrated policy-leverage structure"),
    (re.compile(r"\bTrump 11-edge policy-leverage profile\b", re.I),
     "Trump's concentrated policy-leverage profile"),
    (re.compile(r"\bthe forecast['’]s China subgraph\b", re.I),
     "the forecast's China evidence"),
    (re.compile(r"\bXi-Centered Subgraph\b", re.I),
     "China's Constraint Network"),
    (re.compile(r"\bChina subgraph\b", re.I), "China evidence"),
    (re.compile(r"\bChina Sub-Simulation\b", re.I), "China Outcome Analysis"),
    (re.compile(r"\bsub-simulation\b", re.I), "scenario analysis"),
    (re.compile(r"\b16-agent convergence\b", re.I), "cross-actor alignment"),
    (re.compile(r"\b(\d+)-agent coalition\b", re.I), r"\1-actor coalition"),
    (re.compile(r"\bshared interaction targets\b", re.I), "shared dependencies"),
    (re.compile(r"\bcluster into a single faction\b", re.I),
     "align within a single coalition"),
    (re.compile(r"\beach node needs the others\b", re.I),
     "each participant depends on the others"),
    (re.compile(r"\bevery member is a node\b", re.I),
     "every member is an actor"),
    (re.compile(r"\bsingle node moving\b", re.I),
     "single actor changing course"),
    (re.compile(
        r"\bthe causal graph has no node where ([^.!?]{1,80}) can intervene\b",
        re.I,
    ), r"the current policy structure gives \1 no direct institutional channel to intervene"),
    (re.compile(
        r"\bno bloc has an agent for ([^.!?]{1,100}) in the forecast graph\b",
        re.I,
    ), r"no bloc gives \1 meaningful institutional representation"),
    (re.compile(r"\bThat is not a bug\.\s*That is the forecast\.\s*", re.I),
     "That omission is itself consequential for the forecast. "),
    (re.compile(r"\bMarkets Know More Than the Graph\b", re.I),
     "Market Signals as a Counterweight"),
    (re.compile(r"\bthe research graph\b", re.I), "the underlying evidence"),
    (re.compile(r"\bthe causal graph\b", re.I), "the causal evidence"),
    (re.compile(r"\bthe forecast graph\b", re.I), "the forecast framework"),
    (re.compile(r"\bthe simulation graph\b", re.I), "the analytical framework"),
    (re.compile(r"\bthe graph\b", re.I), "the evidence"),
    (re.compile(r"\bremaining ([^.!?\n]{0,50}) edges tell\b", re.I),
     r"remaining \1 dependencies clarify"),
    (re.compile(r"\bvia two complementary edges\b", re.I),
     "through two complementary relationships"),
    (re.compile(r"\btwo edges that capture\b", re.I),
     "two relationships that capture"),
    (re.compile(r"\bis the edge that\b", re.I), "is the relationship that"),
    (re.compile(r"\btraceable edges\b", re.I), "traceable relationships"),
    (re.compile(r"\bedges that are inferred\b", re.I), "relationships inferred"),
    (re.compile(r"\bthe original dossier\b", re.I), "the source evidence"),
    (re.compile(r"\bthe research dossier\b", re.I), "the evidence base"),
    (re.compile(r"\bthe dossier['’]s\b", re.I), "the forecast's"),
    (re.compile(r"\bthe dossier\b", re.I), "the evidence base"),
    (re.compile(r"\bDossier\b"), "Forecast"),
    (re.compile(r"\bthe predictive skeleton\b", re.I), "the forecast framework"),
    (re.compile(r"\bthe power map\b", re.I), "the actor-power structure"),
    (re.compile(r"\bthe hyperscaler agent\b", re.I), "the hyperscaler evidence"),
    (re.compile(r"`ENABLES` signal", re.I), "enabling signal"),
    (re.compile(
        r",?\s*restated dozens of times across rounds and across clusters of agents,?",
        re.I,
    ), ""),
    (re.compile(r"\bthe\s+NVIDIA\s+agent\s+reads\b", re.I),
     "NVIDIA's public position indicates"),
    (re.compile(r"\bthe simulated data shows\b", re.I), "the available evidence shows"),
    (re.compile(r"\bthe simulated evidence is\b", re.I), "the available evidence indicates"),
    (re.compile(r"\bsimulation dynamics\b", re.I), "forecast drivers and outcome pathways"),
    (re.compile(r"\bagent dynamics\b", re.I), "stakeholder dynamics"),
    (re.compile(r"\b(?:multi-agent|agent-based|agentic) simulation\b", re.I), "forecast model"),
    (re.compile(
        r"\b(?:the|this) simulation(?:'s)?\s+"
        r"(?:shows?|showed|suggests?|suggested|indicates?|indicated|finds?|found|"
        r"reveals?|revealed|surfaced|produced)\b",
        re.I,
    ), "the evidence indicates"),
    (re.compile(r"\bbased on (?:the|this) simulation\b", re.I),
     "based on the available evidence"),
    (re.compile(r"\bin (?:the|this) simulation\b", re.I), "in the forecast"),
    (re.compile(r"\b(?:the\s+)?faction\s*/\s*cluster analysis shows\b", re.I),
     "The cross-actor evidence indicates"),
    (re.compile(r"模拟动力学|模拟动态|智能体动力学"), "预测驱动因素与结果路径"),
    (re.compile(r"模拟数据集(?:中)?"), "研究证据中"),
    (re.compile(r"模拟数据(?:中)?"), "研究证据"),
    (re.compile(r"模拟证据"), "现有证据"),
    (re.compile(r"模拟图谱"), "证据图谱"),
    (re.compile(r"模拟框架"), "分析框架"),
    (re.compile(r"仿真图"), "证据图谱"),
    # Legacy report prose used this exact internal-method construction. Keep
    # domain terms such as "工业仿真软件" and "碰撞仿真" untouched.
    (re.compile(r"仿真以"), "证据分析以"),
    (re.compile(r"(?:本次|该次|上述)?模拟(?:结果|推演)?(?:显示|表明|揭示|说明)"),
     "现有证据表明"),
    (re.compile(r"基于(?:本次|该次)?模拟(?:结果|推演)?"), "基于现有证据"),
    (re.compile(r"模拟情景中|模拟世界中|本次模拟中"), "预测情景中"),
]


_INTERNAL_TELEMETRY_HEADING_RE = re.compile(
    r"^##\s+(?:Run Telemetry|运行遥测|内部运行指标|运行成本与令牌)(?:\s+.*)?$", re.I)


def strip_internal_telemetry_appendices(md: str) -> Tuple[str, int]:
    """Remove operational cost/token tables from customer-facing Markdown.

    Telemetry remains available as ``telemetry.md`` and JSON artifacts.  This
    guard also cleans legacy reports where an older orchestrator appended it to
    ``full_report.md`` before the default was changed.
    """
    lines = (md or "").split("\n")
    out: List[str] = []
    removed = 0
    index = 0
    while index < len(lines):
        if not _INTERNAL_TELEMETRY_HEADING_RE.match(lines[index].strip()):
            out.append(lines[index])
            index += 1
            continue
        removed += 1
        index += 1
        while index < len(lines) and not re.match(r"^##\s+\S", lines[index].strip()):
            index += 1
        while out and not out[-1].strip():
            out.pop()
        if out:
            out.append("")
    return "\n".join(out), removed


def strip_internal_basis_traces(md: str) -> Tuple[str, int]:
    """Remove parenthesized ``Basis:`` graph/tool traces from customer prose.

    These traces are valuable debug provenance but are neither citations nor
    readable report content.  A tiny balanced-parenthesis scanner handles both
    ASCII and full-width wrappers and preserves all surrounding prose.
    """
    text = md or ""
    text, square_removed = re.subn(
        r"\[\s*Basis\s*:[^\]\n]*\]", "", text, flags=re.I
    )
    starts = re.compile(r"[（(]\s*Basis\s*:", re.I)
    removed = square_removed
    cursor = 0
    out: List[str] = []
    while True:
        match = starts.search(text, cursor)
        if not match:
            out.append(text[cursor:])
            break
        out.append(text[cursor:match.start()])
        depth = 0
        index = match.start()
        end = -1
        while index < len(text):
            char = text[index]
            if char in "(（":
                depth += 1
            elif char in ")）":
                depth -= 1
                if depth <= 0:
                    end = index + 1
                    break
            elif char == "\n" and depth == 1:
                break
            index += 1
        if end < 0:
            # An unterminated internal trace is still junk; remove through the
            # line boundary without consuming the next paragraph.
            newline = text.find("\n", match.start())
            end = len(text) if newline < 0 else newline
        removed += 1
        cursor = end
    cleaned = "".join(out)
    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)
    cleaned = re.sub(r"[ \t]+([,.;:，。；：])", r"\1", cleaned)
    return cleaned, removed


def strip_internal_graph_parentheticals(md: str) -> Tuple[str, int]:
    """Remove natural-language graph provenance that is not a reader citation.

    Legacy graph assembly leaked parentheticals such as ``(reflecting X's
    dependency relationship with Y)`` and ``(According to: `raw edge text`)``.
    They are internal trace prose, not evidence attribution.  A balanced scanner
    removes nested variants while preserving ordinary parentheticals and visible
    ``[S<n>]`` markers.
    """
    text = md or ""
    text, marker_repairs = re.subn(
        r"\(\s*According to\s+(\[S\d+\])\s*(?=\n|$)", r" \1", text,
        flags=re.I,
    )
    starts = re.compile(
        r"[（(]\s*(?:According to\s*[:：]|Source\s*[:：]|reflecting\b)", re.I
    )
    removed = marker_repairs
    cursor = 0
    out: List[str] = []
    while True:
        match = starts.search(text, cursor)
        if not match:
            out.append(text[cursor:])
            break
        out.append(text[cursor:match.start()])
        depth = 0
        index = match.start()
        end = -1
        while index < len(text):
            char = text[index]
            if char in "(（":
                depth += 1
            elif char in ")）":
                depth -= 1
                if depth <= 0:
                    end = index + 1
                    break
            elif char == "\n" and depth == 1:
                break
            index += 1
        if end < 0:
            newline = text.find("\n", match.start())
            end = len(text) if newline < 0 else newline
        fragment = text[match.start():end]
        is_according_trace = bool(re.match(
            r"[（(]\s*According to\s*[:：]", fragment, re.I
        ))
        is_relationship_trace = bool(
            re.match(r"[（(]\s*reflecting\b", fragment, re.I)
            and re.search(
                r"\b(?:relationship|edge|node|graph)\b", fragment, re.I
            )
        )
        is_source_trace = bool(
            re.match(r"[（(]\s*Source\s*[:：]", fragment, re.I)
            and re.search(
                r"\b(?:influences?|causes?|enables?|supplies|opposes?|"
                r"relationship|edge|node|graph)\b", fragment, re.I
            )
        )
        if is_according_trace or is_relationship_trace or is_source_trace:
            removed += 1
        else:
            out.append(fragment)
        cursor = end
    cleaned = "".join(out)
    cleaned = re.sub(
        r"\.\s+(?:partners with|opposes|causes|enables|supplies|depends on|"
        r"customer of)\s+[^.!?\n]{0,180}\)\)+\.",
        ".",
        cleaned,
        flags=re.I,
    )
    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)
    cleaned = re.sub(r"[ \t]+([,.;:，。；：])", r"\1", cleaned)
    return cleaned, removed


_RELATION_BULLET_RE = re.compile(
    r"^\s*[-*+]\s+.{2,120}\b(?:enables?|causes?|influences?|supplies|"
    r"opposes?|competes with|depends on|funds|partners with)\b.{0,140}$",
    re.I,
)


def strip_internal_relation_bullet_blocks(md: str) -> Tuple[str, int]:
    """Remove uncited runs of three or more graph-relation dump bullets."""
    lines = (md or "").split("\n")
    mask = _fence_mask(lines)
    delete: set[int] = set()
    index = 0
    while index < len(lines):
        if mask[index] or not _RELATION_BULLET_RE.match(lines[index]):
            index += 1
            continue
        start = index
        while (
            index < len(lines)
            and not mask[index]
            and _RELATION_BULLET_RE.match(lines[index])
            and not re.search(r"\[S\d+\]", lines[index], re.I)
        ):
            index += 1
        if index - start >= 3:
            delete.update(range(start, index))
    if not delete:
        return md, 0
    cleaned = "\n".join(line for i, line in enumerate(lines) if i not in delete)
    return re.sub(r"\n{3,}", "\n\n", cleaned), len(delete)


_GENERATION_FAILURE_RE = re.compile(
    r"Chapter generation failed|章节生成失败|模型反复未能产出合格文本|"
    r"claude-cli output contamination by system prompt",
    re.I,
)
_STANDALONE_CITATION_RE = re.compile(
    r"^\s*(?:\[S\d+\]\s*)+[.,;:，。；：]?\s*$", re.I
)


def strip_generation_failure_placeholders(md: str) -> Tuple[str, int]:
    """Remove customer-visible failed-section boilerplate before empty-section pruning."""
    lines = (md or "").split("\n")
    mask = _fence_mask(lines)
    removed = 0
    out: List[str] = []
    for index, line in enumerate(lines):
        if not mask[index] and _GENERATION_FAILURE_RE.search(line):
            removed += 1
            continue
        out.append(line)
    return re.sub(r"\n{3,}", "\n\n", "\n".join(out)), removed


def strip_standalone_citation_lines(md: str) -> Tuple[str, int]:
    """Remove source markers that annotate no claim and render as visual junk."""
    lines = (md or "").split("\n")
    mask = _fence_mask(lines)
    removed = 0
    out: List[str] = []
    for index, line in enumerate(lines):
        if not mask[index] and _STANDALONE_CITATION_RE.match(line):
            removed += 1
            continue
        out.append(line)
    return re.sub(r"\n{3,}", "\n\n", "\n".join(out)), removed


def strip_corrupted_mixed_punctuation_lines(
    md: str, lang: str = "English"
) -> Tuple[str, int]:
    """Drop legacy prose with dense punctuation from the wrong writing system."""
    if _is_zh(lang):
        return md, 0
    lines = (md or "").split("\n")
    mask = _fence_mask(lines)
    removed = 0
    out: List[str] = []
    in_references = False
    for index, line in enumerate(lines):
        stripped = line.strip()
        if stripped in {"## References", "## 参考来源"}:
            in_references = True
        if mask[index] or in_references or not stripped:
            out.append(line)
            continue
        punctuation_count = len(re.findall(r"[（），。：；、]", stripped))
        latin_count = len(re.findall(r"[A-Za-z]", stripped))
        if (
            punctuation_count >= 2
            and latin_count >= 20
            and not _CJK_RUN_RE.search(stripped)
        ):
            removed += 1
            continue
        out.append(line)
    return re.sub(r"\n{3,}", "\n\n", "\n".join(out)), removed


def strip_empty_tables(md: str) -> Tuple[str, int]:
    """Remove malformed tables whose first row contains no semantic headers."""
    lines = (md or "").split("\n")
    mask = _fence_mask(lines)
    removed = 0
    out: List[str] = []
    index = 0

    def _semantic_cells(line: str) -> List[str]:
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        return [
            re.sub(r"\[S\d+\]", "", cell, flags=re.I).strip()
            for cell in cells
        ]

    while index < len(lines):
        if mask[index] or not lines[index].strip().startswith("|"):
            out.append(lines[index])
            index += 1
            continue
        start = index
        while index < len(lines) and lines[index].strip().startswith("|"):
            index += 1
        block = lines[start:index]
        header_cells = _semantic_cells(block[0]) if block else []
        empty_header = bool(header_cells) and all(
            not cell or re.fullmatch(r"[-—–]+", cell) for cell in header_cells
        )
        if empty_header:
            removed += 1
            continue
        out.extend(block)
    return re.sub(r"\n{3,}", "\n\n", "\n".join(out)), removed


def strip_empty_sections(md: str) -> Tuple[str, int]:
    """Remove H2+ sections with no prose, table, image, or other reader content."""
    text = md or ""
    total_removed = 0
    for _pass in range(3):
        lines = text.split("\n")
        headings: List[Tuple[int, int]] = []
        in_fence = False
        for index, line in enumerate(lines):
            stripped = line.lstrip()
            if stripped.startswith(("```", "~~~")):
                in_fence = not in_fence
                continue
            if in_fence:
                continue
            match = re.match(r"^(#{2,6})\s+\S", line)
            if match:
                headings.append((index, len(match.group(1))))
        delete: set[int] = set()
        for position, (start, level) in enumerate(headings):
            end = len(lines)
            for candidate_start, candidate_level in headings[position + 1:]:
                if candidate_level <= level:
                    end = candidate_start
                    break
            body = lines[start + 1:end]
            substantive = False
            body_fence = False
            for line in body:
                stripped = line.strip()
                if stripped.startswith(("```", "~~~")):
                    body_fence = not body_fence
                    substantive = True
                    continue
                if not stripped or stripped.startswith("<!--"):
                    continue
                if re.match(r"^#{2,6}\s+", stripped):
                    continue
                if _STANDALONE_CITATION_RE.match(stripped):
                    continue
                substantive = True
                break
            if not substantive:
                delete.update(range(start, end))
        if not delete:
            break
        total_removed += len([index for index in delete if re.match(
            r"^#{2,6}\s+", lines[index].strip()
        )])
        text = "\n".join(
            line for index, line in enumerate(lines) if index not in delete
        )
        text = re.sub(r"\n{3,}", "\n\n", text)
    return text, total_removed


def repair_malformed_report_prose(md: str) -> Tuple[str, int]:
    """Repair a small set of deterministic legacy splice artifacts."""
    lines = (md or "").split("\n")
    mask = _fence_mask(lines)
    repaired = 0
    rewrites: List[Tuple[re.Pattern, str]] = [
        (re.compile(r"\bthe available evidence indicates unambiguous\b", re.I),
         "the available evidence is unambiguous"),
        (re.compile(r"(?<=\d{4})(?=(?:complete|confirm|show|indicate|support)\b)", re.I),
         " "),
        (re.compile(r"\bDonald J\.\s+The China side\b"), "The China side"),
        (re.compile(
            r"\.\s+autocracies\)\s+but into chokepoint-dependency camps\.", re.I
        ), "; these dependencies divide actors into chokepoint-based camps rather than ideological blocs."),
        (re.compile(
            r"The 6-3 Supreme Court decision on 20 February 2026 in "
            r"\*Learning Resources v\.\s+(?:The evidence|The graph) records this "
            r"sequence in three separate edges:", re.I,
        ), "The 6-3 Supreme Court decision on 20 February 2026 in "
           "*Learning Resources v. Trump* redirected policy through three linked moves:"),
        (re.compile(r"\s+(?:This is|These are)\s*$", re.I), ""),
    ]
    for index, line in enumerate(lines):
        if mask[index] or not line:
            continue
        updated = line
        for pattern, replacement in rewrites:
            updated, count = pattern.subn(replacement, updated)
            repaired += count
        updated, count = re.subn(
            r"^(\s*(?:>\s*|[-*+]\s+|\d+[.)]\s+)?)the "
            r"(evidence|forecast|analysis|cross-actor)",
            lambda match: match.group(1) + "The " + match.group(2),
            updated,
        )
        repaired += count
        updated, count = re.subn(
            r"^(\s*(?:>\s*|[-*+]\s+|\d+[.)]\s+)?)the analytical perspective",
            lambda match: match.group(1) + "The analytical perspective",
            updated,
            flags=re.I,
        )
        repaired += count
        lines[index] = updated.rstrip()
    return "\n".join(lines), repaired


def scrub_simulation_mechanics(md: str, lang: str = "English") -> Tuple[str, Dict[str, int]]:
    """Remove internal simulation mechanics while retaining forecast outcomes.

    Safe phrases such as "the simulation suggests 62%" are reframed around the
    evidence and keep their numbers/citations. Residual mechanics sentences
    (rounds, action counts, platform behavior, agent-network telemetry) are
    removed. Markdown fences are untouched; tables keep their structure and
    redact only offending cells.
    """
    info = {"rewritten": 0, "sentences_removed": 0, "table_cells_redacted": 0}
    lines = (md or "").split("\n")
    mask = _fence_mask(lines)

    # SESSIONB-3（取证 report_5ca1a799ee0d 发布不收敛）：References 条目
    # 「…latest funding round 2025…」命中 LEAKAGE_PATTERNS 的 round 模式被整行删除，
    # 而 _finalize_citations_for_publish 随后按引用索引重建同一条目 → lint 与引注
    # 终结器互相改写、永不收敛。参考文献是逐字保真的出处记录，不是叙事正文——
    # 本规则对 References 节与引用条目行（编号 + [S<n>] 起头）一律免检。
    _refs_heading_re = re.compile(
        r"^\s*#{1,6}\s*(references|参考文献|引用文献|资料来源)\s*$", re.I)
    _ref_entry_re = re.compile(r"^\s*\d+[.)]\s*\[S\d+\]")
    in_refs_section = False

    def _rewrite(text: str) -> str:
        out = text
        for pattern, replacement in _SIMULATION_OUTCOME_REWRITES:
            out, count = pattern.subn(replacement, out)
            info["rewritten"] += count
        return out

    def _still_leaks(text: str) -> bool:
        return bool(PLATFORM_BEHAVIOR_RE.search(text) or any(
            pattern.search(text) for _name, pattern in LEAKAGE_PATTERNS
        ))

    for index, line in enumerate(lines):
        if mask[index] or not line.strip():
            continue
        if line.lstrip().startswith("#"):
            in_refs_section = bool(_refs_heading_re.match(line))
        if (in_refs_section and not line.lstrip().startswith("#")) or _ref_entry_re.match(line):
            continue
        rewritten = _rewrite(line)
        if rewritten.lstrip().startswith("|") and "|" in rewritten:
            cells = rewritten.split("|")
            first_cell = 1 if rewritten.lstrip().startswith("|") else 0
            last_cell = len(cells) - 1 if rewritten.rstrip().endswith("|") else len(cells)
            for cell_index in range(first_cell, last_cell):
                if _still_leaks(cells[cell_index]):
                    cells[cell_index] = " — "
                    info["table_cells_redacted"] += 1
            lines[index] = "|".join(cells)
            continue
        if rewritten.lstrip().startswith("#"):
            # Headings have no sentence punctuation; rewrite known phrases, and
            # replace any remaining mechanics heading with an outcome-first title.
            hashes = re.match(r"^(\s*#{1,6}\s*)", rewritten)
            prefix = hashes.group(1) if hashes else ""
            heading_body = rewritten[len(prefix):].strip() if prefix else rewritten.strip()
            if heading_body.lower() == "forecast drivers and outcome pathways":
                rewritten = prefix + "Forecast Drivers and Outcome Pathways"
            elif _still_leaks(rewritten):
                rewritten = prefix + (
                    "预测驱动因素与结果路径" if _is_zh(lang)
                    else "Forecast Drivers and Outcome Pathways"
                )
                info["rewritten"] += 1
            lines[index] = rewritten
            continue

        prefix_match = re.match(r"^(\s*(?:>\s*|[-*+]\s+|\d+[.)]\s+))", rewritten)
        prefix = prefix_match.group(1) if prefix_match else ""
        body = rewritten[len(prefix):] if prefix else rewritten
        sentences = _split_sentences(body)
        kept: List[str] = []
        for sentence in sentences:
            if _still_leaks(sentence):
                info["sentences_removed"] += 1
                continue
            if sentence.strip():
                # _split_sentences deliberately retains the separator after
                # each sentence. Stripping here glued clean English sentences
                # together (".[S1].Supply") across every backfilled report.
                kept.append(sentence)
        lines[index] = (prefix + "".join(kept).strip()).rstrip() if kept else ""
    return "\n".join(lines), info


_MISSING_SENTENCE_SPACE_RE = re.compile(
    r"(?<=[a-z0-9\]\)\"”’」』])([.!?])(?=[A-Z])")


# GLM-run 2026-09-18: regions where sentence-join repair must never apply —
# markdown link labels+destinations, bare URLs, and filename-ish tokens. The
# old implementation only masked code fences, so a cited URL like
# ``2025.Annual.Survey.Report.pdf`` matched ``digit.Uppercase`` three times per
# occurrence and the rule silently rewrote the URL; the citation finalizer then
# regenerated the appendix from its canonical index, producing the exact
# lint-changes / finalize-reverts ping-pong that failed publication twice
# (passes=4 and passes=6, semantic_unsupported=0 both times).
_URLISH_RE = re.compile(
    r"\[[^\]]*\]\([^)]*\)"      # [label](destination)
    r"|https?://\S+"                # bare URLs
    r"|www\.\S+"                   # www.*
    r"|\S*/[A-Za-z0-9_.\-%]+/\S*"   # path-like tokens (a slash-delimited run)
    r"|[A-Za-z0-9_-]+(?:\.[A-Za-z0-9_-]+){2,}"  # ASCII dotted tokens (filenames/hosts)
)


def _mask_urlish(line: str) -> List[Tuple[str, bool]]:
    """Split a line into (span, protected) segments; protected spans are opaque."""
    spans: List[Tuple[str, bool]] = []
    pos = 0
    for m in _URLISH_RE.finditer(line):
        if m.start() > pos:
            spans.append((line[pos:m.start()], False))
        spans.append((m.group(0), True))
        pos = m.end()
    if pos < len(line):
        spans.append((line[pos:], False))
    return spans or [(line, False)]


def repair_missing_sentence_spaces(md: str) -> Tuple[str, int]:
    """Repair legacy ``Sentence.Next`` joins without touching URLs/initialisms.

    The narrow boundary requires a lowercase/digit/closer before the terminal
    and an uppercase-led word after it. This fixes the historical lint bug
    while leaving ``N.V.``, ``U.S.``, decimals, lowercase domains, markdown
    links and bare/filename URLs intact (see ``_URLISH_RE``).
    """
    lines = (md or "").split("\n")
    mask = _fence_mask(lines)
    repaired = 0
    for index, line in enumerate(lines):
        if mask[index] or not line:
            continue
        out_parts: List[str] = []
        count = 0
        for span, protected in _mask_urlish(line):
            if protected:
                out_parts.append(span)
            else:
                fixed, n = _MISSING_SENTENCE_SPACE_RE.subn(r"\1 ", span)
                out_parts.append(fixed)
                count += n
        lines[index] = "".join(out_parts)
        repaired += count
    return "\n".join(lines), repaired


def drop_platform_behavior_quotes(md: str) -> Tuple[str, int]:
    """删除内容为平台行为机制（发帖/点赞/评论/转发）的 blockquote 行——这类引文应删不应转写。"""
    removed = 0
    lines = (md or "").split("\n")
    mask = _fence_mask(lines)
    out: List[str] = []
    for i, ln in enumerate(lines):
        s = ln.strip()
        if (not mask[i]) and s.startswith(">") and PLATFORM_BEHAVIOR_RE.search(s):
            removed += 1
            continue
        out.append(ln)
    return "\n".join(out), removed


# ──────────────────────────────────────────────────────────────
# RESEARCH-5：已报告 vs 预期的归因观测（只记数/采样，不改写；不属于 lint_report）
# ──────────────────────────────────────────────────────────────

# Part-1 binary-forecast block markers: copies of forecast_extractor's
# BINARY_FORECAST_START_MARKER / BINARY_FORECAST_END_MARKER (this module imports
# nothing from the forecast plane); test_report_lint_projection pins the equality.
_BINARY_FORECAST_START_MARKER = "<!-- binary-forecast-block:start -->"
_BINARY_FORECAST_END_MARKER = "<!-- binary-forecast-block:end -->"

PROJECTION_ATTRIBUTION_CODES = (
    "projection_as_fact", "projection_unmarked", "actual_as_projection", "estimate_unattributed",
)
_PROJECTION_EXCERPT_CHARS = 160
_PROJECTION_DEFAULT_EXAMPLES = 8
# Bytes that carry numbers but no claim: comments, inline code, link targets,
# bare URLs and [S#] citation markers.  Every bracketed alternative stops at the
# next opener of its kind (comments and citations never nest), so an unclosed
# "<!--", "](" or "[S1" costs only the text up to the next one: linear time.
_PROJECTION_NOISE_RE = re.compile(
    r"<!--(?:(?!<!--).)*?-->|`[^`\n]*`|\]\([^)\s\]]*\)|https?://\S+"
    r"|[\[【]\s*S[\d?#][^\[\]【】]*[\]】]")
_PROJECTION_LIST_MARKER_RE = re.compile(r"^(?:[-*+]|\d{1,3}[.)])\s+")
# A number as written: thousands separators, decimals and a trailing percent sign
# stay one token; the ASCII-only look-behind lets a number follow CJK text.
_PROJECTION_NUMBER_RE = re.compile(
    r"(?<![A-Za-z0-9_.])(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?(?![0-9])(?:\s*[%％])?")
_PROJECTION_YEAR_RE = re.compile(r"(?<![0-9])((?:19|20|21)\d{2})(?![0-9])")
_PROJECTION_LATIN_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9]*")
# A year-like metric token ("fy2025", "2030e" has no leading letter and never tokenizes).
_PROJECTION_YEARISH_RE = re.compile(r"(?:fy|cy|q[1-4]|h[12])?(?:19|20|21)\d{2}[a-z]?")
_PROJECTION_CJK_RUN_RE = re.compile(r"[" + _CJK_CHAR + r"]+")
# Words that anchor nothing on their own (compared after the plural fold of
# _projection_stem): generic metric words, generic quantity/period words, and
# English function words of >= 4 letters (shorter tokens never anchor).  Each entry
# is its own stem (a test pins it).
_PROJECTION_ANCHOR_STOPWORDS = frozenset({
    "global", "total", "market", "forecast", "forecasted", "estimate", "estimated", "base", "case",
    "year", "yearly", "annual", "annually", "fiscal", "quarter", "quarterly", "month", "monthly",
    "period", "share", "rate", "growth", "level", "number", "value", "amount", "average", "change",
    "percent", "percentage",
    "about", "after", "also", "among", "been", "before", "between", "both", "during",
    "each", "from", "have", "into", "more", "most", "only", "other", "over", "such", "than", "that",
    "their", "them", "then", "there", "these", "they", "this", "those", "through", "under", "until",
    "were", "what", "when", "where", "which", "while", "will", "with", "within", "without", "would",
})
_PROJECTION_CJK_STOP_BIGRAMS = frozenset({
    "全球", "总计", "合计", "总量", "市场", "预测", "预计", "预期", "估计", "估算", "基准", "情景",
})
# Rows whose metric is a scenario or probability figure, not a world quantity.
_PROJECTION_PROBABILITY_METRIC_RE = re.compile(r"probabilit|scenario|概率|情景", re.I)
_PROJECTION_NO_UNIT = frozenset({"n/a", "na", "none", "null", "-", "—", "unitless", "dimensionless"})
_PROJECTION_UNIT_STOPWORDS = frozenset({"per", "of", "the", "and", "or", "in", "an", "to", "as", "us"})
_PROJECTION_PERCENT_UNIT_RE = re.compile(r"%|％|\bpercent|\bper\s*cent\b|\bpct\b|百分", re.I)
# Currency units written as a symbol or a word in prose.
_PROJECTION_UNIT_ALIASES = {
    "usd": r"usd|us\$|\$|dollars?", "$": r"usd|us\$|\$|dollars?",
    "eur": r"eur|€|euros?", "€": r"eur|€|euros?",
    "cny": r"cny|rmb|yuan|人民币|元", "rmb": r"cny|rmb|yuan|人民币|元",
}
# PROJ cues: a projection is being stated (future modal, forecast vocabulary, "by <year>").
_PROJECTION_CUE_RE = re.compile(
    r"\b(?:will|would|could|may(?!\s+\d)|expect\w*|forecast\w*|project\w*|estimat\w*|target\w*"
    r"|aim\w*\s+to|plan\w*\s+to|outlook|guidance|anticipat\w*)\b"
    r"|\bby\s+(?:the\s+end\s+of\s+)?(?:19|20|21)\d{2}\b"
    r"|预计|预测|预期|有望|将|目标|计划|估计|展望|到[^，。；,;！？]{0,8}?(?:19|20|21)\d{2}\s*年",
    re.I)
# REAL cues: a realized value is being stated.
_REALIZED_CUE_RE = re.compile(
    r"\b(?:was|were|reached|hit|stood\s+at|totall?ed|rose\s+to|fell\s+to|recorded|has\s+reached)\b"
    r"|已达|已经达到|录得|实现了|达到了|跨过|突破|升至",
    re.I)
# An estimate presented as one (approximation or attribution wording).
_ESTIMATE_CUE_RE = re.compile(
    r"\b(?:estimat\w*|approx\w*|about|around|roughly|nearly|according\s+to)\b|~|≈"
    r"|估|约|左右|根据|据(?:称|统计|测算|报道|悉)",
    re.I)


def _projection_stem(token: str) -> str:
    """Case- and plural-folded Latin token ("Robots" → "robot")."""
    token = token.lower()
    return token[:-1] if len(token) > 4 and token.endswith("s") and not token.endswith("ss") else token


def _canonical_number(token: str) -> Optional[str]:
    """A number token as a plain decimal string ("1,000.0 %" → "1000"); None if unreadable."""
    try:
        value = Decimal(re.sub(r"[\s,%％]", "", token))
    except InvalidOperation:
        return None
    return format(value.normalize(), "f") if value.is_finite() else None


def _projection_key_numbers(value: Any, percent_unit: bool) -> frozenset:
    """Canonical key numbers of a row value: a decimal, a percentage, or >= 2 digits
    that is not a bare year 1900-2100 (a lone digit or year matches too much prose)."""
    if isinstance(value, bool):
        return frozenset()
    text = format(Decimal(repr(value)), "f") if isinstance(value, float) else str(value or "")
    keys = set()
    for match in _PROJECTION_NUMBER_RE.finditer(text):
        canonical = _canonical_number(match.group(0))
        if canonical is None:
            continue
        percent = percent_unit or match.group(0).rstrip().endswith(("%", "％"))
        if percent or "." in canonical or (len(canonical) >= 2 and not 1900 <= int(canonical) <= 2100):
            keys.add(canonical)
    return frozenset(keys)


def _projection_unit_patterns(unit: Any) -> Optional[List["re.Pattern[str]"]]:
    """Patterns of which a matching sentence must contain one: [] = the row states no
    unit (no requirement); None = a unit no sentence token can stand for (row skipped)."""
    text = re.sub(r"\s+", " ", str(unit or "")).strip()
    if not text or text.casefold() in _PROJECTION_NO_UNIT:
        return []
    if _PROJECTION_PERCENT_UNIT_RE.search(text):
        return [_PROJECTION_PERCENT_UNIT_RE]
    patterns: List["re.Pattern[str]"] = []
    for word in re.findall(r"[A-Za-z]+|[$€]", text):
        folded = _projection_stem(word)
        if folded in _PROJECTION_UNIT_STOPWORDS or (len(folded) < 2 and folded not in _PROJECTION_UNIT_ALIASES):
            continue
        alias = _PROJECTION_UNIT_ALIASES.get(folded)
        body = alias if alias else re.escape(folded) + r"(?:s|es)?"
        patterns.append(re.compile(r"(?<![A-Za-z])(?:" + body + r")(?![A-Za-z])", re.I))
    patterns.extend(re.compile(re.escape(run)) for run in _PROJECTION_CJK_RUN_RE.findall(text))
    return patterns or None


def _projection_anchors(names: str) -> Tuple[frozenset, frozenset]:
    """(Latin anchors, CJK bigrams) of a row's metric/series: Latin tokens of >= 4
    characters outside the stop-list and not year-like; CJK bigrams outside the
    CJK stop-list."""
    latin = frozenset(
        _projection_stem(token) for token in _PROJECTION_LATIN_TOKEN_RE.findall(names)
        if len(token) >= 4 and not _PROJECTION_YEARISH_RE.fullmatch(token.lower())
        and _projection_stem(token) not in _PROJECTION_ANCHOR_STOPWORDS)
    bigrams = frozenset(
        run[i:i + 2] for run in _PROJECTION_CJK_RUN_RE.findall(names) for i in range(len(run) - 1)
    ) - _PROJECTION_CJK_STOP_BIGRAMS
    return latin, bigrams


def _projection_rows(quant_rows: Any, as_of: Optional[date]) -> List[Dict[str, Any]]:
    """The typed rows the check can anchor, in input order."""
    prepared: List[Dict[str, Any]] = []
    for row in quant_rows if isinstance(quant_rows, list) else []:
        if not isinstance(row, dict):
            continue
        klass = quant_class(row, as_of)
        if klass not in ("reported", "projected"):
            continue
        names = " ".join(str(row.get(key) or "") for key in ("metric", "series"))
        if _PROJECTION_PROBABILITY_METRIC_RE.search(names):
            continue
        units = _projection_unit_patterns(row.get("unit"))
        percent_unit = bool(_PROJECTION_PERCENT_UNIT_RE.search(str(row.get("unit") or "")))
        keys = _projection_key_numbers(row.get("value"), percent_unit)
        latin, bigrams = _projection_anchors(names)
        if units is None or not keys or not (latin or len(bigrams) >= 2):
            continue
        prepared.append({"row": row, "class": klass, "keys": keys, "units": units,
                         "latin": latin, "bigrams": bigrams,
                         "estimate": str(row.get("value_type") or "").strip().lower() == "estimate"})
    return prepared


def _projection_scan_lines(md: str) -> List[Tuple[int, str]]:
    """(1-based line number, text) of the prose and bullet lines: fenced code,
    headings, tables, blockquotes, HTML comments, References / 参考来源 sections
    and the Part-1 binary-forecast block are skipped; list markers are dropped."""
    lines = (md or "").split("\n")
    mask = _fence_mask(lines)
    out: List[Tuple[int, str]] = []
    in_part1 = False
    references_level = 0          # > 0 inside a References section: its heading level
    for number, (line, fenced) in enumerate(zip(lines, mask, strict=True), start=1):
        stripped = line.strip()
        if stripped == _BINARY_FORECAST_START_MARKER:
            in_part1 = True
            continue
        if stripped == _BINARY_FORECAST_END_MARKER:
            in_part1 = False
            continue
        if fenced or in_part1 or not stripped:
            continue
        if _MD_HEADING_RE.match(line) or _REFERENCES_HEADING_RE.match(line):
            level = len(stripped) - len(stripped.lstrip("#"))
            if references_level and level <= references_level:
                references_level = 0
            if _REFERENCES_HEADING_RE.match(line):
                references_level = level
            continue
        if references_level or stripped.startswith(("|", ">", "<!--")):
            continue
        out.append((number, _PROJECTION_LIST_MARKER_RE.sub("", stripped, count=1)))
    return out


def _projection_matches(row: Dict[str, Any], text: str, numbers: frozenset, tokens: frozenset) -> bool:
    """A sentence restates a row only with its key number, its unit (when it has
    one) and a metric anchor (a Latin anchor word, or >= 2 CJK bigrams)."""
    if not row["keys"] & numbers:
        return False
    if row["units"] and not any(pattern.search(text) for pattern in row["units"]):
        return False
    return bool(row["latin"] & tokens) or sum(1 for gram in row["bigrams"] if gram in text) >= 2


def _projection_cue(text: str, as_of: Optional[date]) -> bool:
    if _PROJECTION_CUE_RE.search(text):
        return True
    return as_of is not None and any(
        int(year) > as_of.year for year in _PROJECTION_YEAR_RE.findall(text))


def _projection_excerpt(sentence: str) -> str:
    text = re.sub(r"\s+", " ", sentence).strip()
    limit = _PROJECTION_EXCERPT_CHARS
    return text if len(text) <= limit else text[:limit - 1].rstrip() + "…"


def _projection_as_of(as_of: Any) -> Optional[date]:
    """The as-of day of a date, a datetime or a date string (dates.parse_as_of); else None."""
    if isinstance(as_of, str):
        as_of = parse_as_of(as_of)
    if isinstance(as_of, datetime):
        return as_of.date()
    return as_of if isinstance(as_of, date) else None


def _projection_example_cap(max_examples: Any) -> int:
    """``max_examples`` as a count >= 0; the default when it is not a readable number."""
    if isinstance(max_examples, bool):
        return _PROJECTION_DEFAULT_EXAMPLES
    try:
        return max(0, int(max_examples))
    except (TypeError, ValueError, OverflowError):
        return _PROJECTION_DEFAULT_EXAMPLES


def check_projection_attribution(md: str, quant_rows: Any, *, as_of: Any = None,
                                 lang: str = "English",
                                 max_examples: int = _PROJECTION_DEFAULT_EXAMPLES) -> Dict[str, Any]:
    """Reports-vs-projects attribution check (RESEARCH-5).  Pure, deterministic and
    observe-only: it counts, never rewrites, and lint_report does not call it.

    Rows are typed with quant_typing.quant_class against ``as_of`` (a date, a
    datetime or a date string read with dates.parse_as_of; anything else = no as-of
    date); untyped rows are ignored (precision first), as are scenario/probability
    rows and rows without a key number, a usable unit or a metric anchor.  A prose or
    bullet sentence (see _projection_scan_lines) restates a row when it holds the row's
    key number, its unit and a metric anchor; the row's [S#] is not consulted, since
    the prose may cite a different source than the row.  Cues are read per sentence
    in both languages (``lang`` is recorded only): PROJ = future modal, forecast
    vocabulary, "by <year>", 预计/预测/…/到…年, or a year after the as-of year; REAL =
    was/were/reached/…, 已达/录得/…

    Codes (each at most once per sentence):
      * projection_as_fact     -- projected row, REAL cue, no PROJ cue (sampled in
        ``examples``, at most ``max_examples``);
      * projection_unmarked    -- projected row, neither cue (count only);
      * actual_as_projection   -- reported row, PROJ cue, no REAL cue (count only);
      * estimate_unattributed  -- value_type estimate, no approximation/attribution
        wording (count only).

    Cross-language restatements (an English row in a Chinese sentence) never match.
    Malformed arguments degrade instead of raising: a non-str ``md`` is empty and an
    unreadable ``max_examples`` is the default.
    """
    as_of = _projection_as_of(as_of)
    rows = _projection_rows(quant_rows, as_of)
    report: Dict[str, Any] = {"lang": str(lang or ""), "checked_rows": len(rows), "matched_sentences": 0}
    report.update(dict.fromkeys(PROJECTION_ATTRIBUTION_CODES, 0))
    examples: List[Dict[str, Any]] = []
    report["examples"] = examples
    if not rows:
        return report
    cap = _projection_example_cap(max_examples)
    for number, line in _projection_scan_lines(md if isinstance(md, str) else ""):
        for sentence in _split_sentences(line):
            text = _PROJECTION_NOISE_RE.sub(" ", sentence)
            numbers = frozenset(filter(None, (
                _canonical_number(match.group(0)) for match in _PROJECTION_NUMBER_RE.finditer(text))))
            if not numbers:
                continue
            tokens = frozenset(_projection_stem(t) for t in _PROJECTION_LATIN_TOKEN_RE.findall(text))
            matched = [row for row in rows if _projection_matches(row, text, numbers, tokens)]
            if not matched:
                continue
            report["matched_sentences"] += 1
            projection = _projection_cue(text, as_of)
            realized = bool(_REALIZED_CUE_RE.search(text))
            hits: Dict[str, Dict[str, Any]] = {}
            for row in matched:
                if row["class"] == "projected" and not projection:
                    hits.setdefault("projection_as_fact" if realized else "projection_unmarked", row)
                if row["class"] == "reported" and projection and not realized:
                    hits.setdefault("actual_as_projection", row)
                if row["estimate"] and not _ESTIMATE_CUE_RE.search(text):
                    hits.setdefault("estimate_unattributed", row)
            for code in hits:
                report[code] += 1
            as_fact = hits.get("projection_as_fact")
            if as_fact is not None and len(examples) < cap:
                source_row = as_fact["row"]
                value = source_row.get("value")
                value_type = source_row.get("value_type")
                examples.append({
                    "code": "projection_as_fact",
                    "line": number,
                    "excerpt": _projection_excerpt(sentence),
                    "metric": _projection_excerpt(str(source_row.get("metric") or "")),
                    "value": value if isinstance(value, (int, float, str)) and not isinstance(value, bool)
                    else str(value),
                    "value_type": str(value_type) if value_type is not None else None,
                })
    return report


# ──────────────────────────────────────────────────────────────
# 入口：lint_report
# ──────────────────────────────────────────────────────────────

def lint_report(md: str, lang: str, mode: str = "final",
                spine: Optional[Dict[str, Any]] = None, *,
                alias_aware_s11: bool = False) -> Tuple[str, Dict[str, Any]]:
    """确定性编辑纪律 lint + 修复。纯函数（无状态、无 LLM、无 IO）。

    Args:
        md: 报告 markdown。
        lang: 目标输出语言（"English"/"Chinese"，其它按 CJK 处理）。
        mode: "final"（成稿）| "research"（研究档案——额外剥离 pass 叙述括注）。
        spine: 可选预测骨架 dict（{"scenarios": [{name, probability}...]}）——传入时做
            情景概率交叉核对（只记数不改写）。
        alias_aware_s11: REPORT-3——情景概率核对并入别名槽不符（REPORT_LOGIC_NUMBER_GATE=
            numeric）；只影响 scenario_prob_mismatches，改写结果与 changed 不变。

    research 模式的引用不变量：研究档案的 [S#] 已由 bridge 定稿（按位置索引 sources.json，
    References = 被引集合），lint 绝不删除或凭空生成引用——(S1) 分级标签不当引用规整、
    带引用的归因行保留；每条改写规则之后核对正文被引来源的首次出现顺序与（去重以外的规则）
    每个来源的引用次数，若被改变则整条规则回退并记入 citation_guard_rules（兜底守卫）。

    Returns:
        (cleaned_md, report_dict)：清理后的 markdown + 逐类别命中/动作报告。
    """
    text = md or ""
    rep: Dict[str, Any] = {"mode": mode, "lang": str(lang or "")}
    research = mode != "final"
    guard_rules: List[str] = []

    def _adopt(rule: str, result: Tuple[Any, ...]) -> Tuple[Any, ...]:
        """采纳一条改写规则的 (new_text, *counts)；research 模式下若改变了正文被引来源的
        首次出现顺序，或（去重以外的规则）改变了任一来源的引用次数，则回退该规则（计数归零）。
        去重只删除引用集合完全相同的整句重复，故只核对顺序。返回 counts。"""
        nonlocal text
        new_text, counts = result[0], tuple(result[1:])
        if research and new_text != text:
            before, after = _body_citations(text), _body_citations(new_text)
            changed = list(dict.fromkeys(before)) != list(dict.fromkeys(after))
            if not changed and rule != "duplicate_sentences":
                changed = Counter(before) != Counter(after)
            if changed:
                guard_rules.append(rule)
                return tuple(0 for _ in counts)
        text = new_text
        return counts

    rep["citation_residue"] = _adopt("citation_residue", strip_citation_residue(text))[0]
    rep["edge_dumps"], rep["dangling_edge_intros"] = _adopt(
        "edge_dumps", rewrite_edge_dumps(text, lang))
    rep["legacy_sim_labels"] = _adopt("legacy_sim_labels", rewrite_sim_labels(text, lang))[0]
    rep["tool_tokens"] = _adopt("tool_tokens", strip_tool_tokens(text))[0]
    if mode == "final":
        text, rep["generation_failure_placeholders"] = strip_generation_failure_placeholders(text)
        text, rep["internal_telemetry_appendices"] = strip_internal_telemetry_appendices(text)
        text, rep["internal_basis_traces"] = strip_internal_basis_traces(text)
        text, rep["internal_graph_parentheticals"] = strip_internal_graph_parentheticals(text)
        text, rep["internal_relation_bullets"] = strip_internal_relation_bullet_blocks(text)
        text, rep["standalone_citation_lines"] = strip_standalone_citation_lines(text)
        text, rep["corrupted_mixed_punctuation_lines"] = (
            strip_corrupted_mixed_punctuation_lines(text, lang)
        )
        text, rep["empty_tables"] = strip_empty_tables(text)
    else:
        rep["generation_failure_placeholders"] = 0
        rep["internal_telemetry_appendices"] = 0
        rep["internal_basis_traces"] = 0
        rep["internal_graph_parentheticals"] = 0
        rep["internal_relation_bullets"] = 0
        rep["standalone_citation_lines"] = 0
        rep["corrupted_mixed_punctuation_lines"] = 0
        rep["empty_tables"] = 0
    rep["dangling_attributions"] = _adopt(
        "dangling_attributions", remove_dangling_attributions(text, keep_cited=research))[0]
    _pn_stripped, _pn_flagged = _adopt("pass_narration", strip_pass_narration(text))
    if "pass_narration" in guard_rules:
        _pn_flagged = _count_pass_mentions(text)
    rep["pass_narration"] = {"stripped": _pn_stripped, "flagged": _pn_flagged}
    rep["citation_variants"] = _adopt(
        "citation_variants", normalize_citation_variants(text, paren_labels=not research))[0]
    rep["duplicate_sentences_removed"] = _adopt(
        "duplicate_sentences", dedup_duplicate_sentences(text))[0]
    rep["citation_guard_rules"] = guard_rules
    rep["citation_guard_reverts"] = len(guard_rules)
    if mode == "final":
        text, rep["simulation_mechanics"] = scrub_simulation_mechanics(text, lang)
        text, rep["malformed_prose_repairs"] = repair_malformed_report_prose(text)
        text, rep["sentence_spaces_repaired"] = repair_missing_sentence_spaces(text)
        text, rep["empty_sections"] = strip_empty_sections(text)
    else:
        rep["simulation_mechanics"] = {
            "rewritten": 0, "sentences_removed": 0, "table_cells_redacted": 0,
        }
        rep["malformed_prose_repairs"] = 0
        rep["sentence_spaces_repaired"] = 0
        rep["empty_sections"] = 0

    # 检测类（不改写）
    rep["language_contamination"] = detect_language_contamination(text, lang)
    rep["table_cell_truncations"] = detect_table_cell_truncation(text)
    rep["scenario_prob_mismatches"] = check_scenario_probabilities(
        text, spine, alias_aware=alias_aware_s11)
    rep["leakage_flags"] = len(leakage_hits(text))
    rep["outcome_focus_ok"] = rep["leakage_flags"] == 0
    rep["changed"] = text != (md or "")
    return text, rep
