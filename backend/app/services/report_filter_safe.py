"""Content-filter-safe section generation (report stage).

Live run ``pipe_d569f211eb14`` (2026-10-17, glm-5.3 through the coding-plan endpoint):
the chapter "The Actor Architecture: Who Actually Decides the Outcome" was rejected by
the provider's content filter (HTTP 400, code 1301) on all six attempts and the publish
gate refused the whole report.  The agent log shows the mechanics:

* the first write after a 48k-character ``insight_forge`` dump was rejected on the
  *output* side (``role: assistant``);
* on later attempts the model produced a complete 13-15k-character ``Final Answer`` that
  passed the filter, the ReAct loop **rejected it for having made too few tool calls**,
  the model kept retrieving (another 22k-character dump), and the next request was
  rejected on the *input* side (``role: user``);
* every retry replayed the identical request (the LLM cache even replayed the same
  draft), so backoff could not help.

Live probes against the same provider (session scratchpad ``probe_filter*.py``) showed
that the chapter brief itself passes, that an institutional-register directive passes,
and that rewriting leaders' names as offices ("China's top leader") is *itself* a
trigger -- so this module does not redact names.  It supplies:

* :data:`LEVEL_DRAFT_ACCEPTED` -- when a content filter interrupts an attempt that
  already holds a complete, uncontaminated draft rejected only for the tool-call floor,
  the generators return that draft instead of raising (``filter_safe_sections`` = 0);
* :func:`register_directive` -- the system-prompt directive for the retry ladder that
  ``ReportAgent._generate_section_with_retry`` climbs after a content-filter rejection
  (never on other errors, never on the first attempt): level 1 keeps retrieval but asks
  for a neutral institutional register, lowers the tool-call floor to one and caps each
  retrieved passage; level 2 writes from the background dossier and the completed
  chapters with no retrieval tools (retrieved passages are the input-side trigger).

The report records which chapters needed which rung (``Report.filter_safe_sections``).

Bilingual pass (``report_0f2e07d62a34``, same run): sixteen translation calls were rejected
by the same filter and the Chinese version was lost to its own integrity audit.  The
translation rung is :func:`translation_register_directive`: a rejected chunk is split
smaller and retried once with that rule, and a chunk that is still rejected keeps its
source bytes and is disclosed as a partial translation (``ReportAgent`` bilingual code,
``REPORT_BILINGUAL_FILTER_SAFE``).  Unlike the generation directive it never asks for a
name to be replaced by an office: that rewrite is itself filtered, and a translation has to
reproduce the source names anyway.
"""

from __future__ import annotations

from ..utils.llm_client import _is_content_filter

#: ``filter_safe_sections`` value: a complete draft rejected only for the tool-call floor was
#: accepted after the provider content-filtered the retrieval that followed it.
LEVEL_DRAFT_ACCEPTED = 0
#: Retrieval kept; institutional register, tool-call floor lowered to one, passages capped.
LEVEL_REGISTER = 1
#: No retrieval tools; written from the background dossier and the completed chapters.
LEVEL_NO_TOOLS = 2
#: Highest ladder level.
FILTER_SAFE_MAX_LEVEL = LEVEL_NO_TOOLS

#: Per-passage cap for retrieved material injected into the conversation at level >= 1.  The
#: live failure accumulated 48k + 22k characters of retrieval dumps before the input filter
#: struck; the twelve passing chapters never carried that much.
OBSERVATION_CHARS_AT_LEVEL_1 = 6_000

#: Prior-chapter slice cap at level 2 (the dossier and source index stay in full).
PRIOR_SECTION_CHARS_AT_LEVEL_2 = 4_000


def is_content_filter(exc: BaseException) -> bool:
    """True when ``exc`` is a provider content-filter rejection (shared detector)."""
    return _is_content_filter(exc)  # type: ignore[arg-type]


_DIRECTIVE_L1 = (
    "\n\n【机构称谓写作模式（上一次尝试被提供方内容审查拒绝后启用）/ "
    "Institutional-register mode (enabled after the provider's content filter rejected the previous attempt)】\n"
    "- 以职务或机构指称在任的国家元首与政府首脑，把决策归因到政府、部委、机构与企业层面；"
    "保持中性、分析性的语气，转述立场而不逐字引用煽动性语句。\n"
    "- Refer to serving heads of state and government by office or institution and attribute decisions "
    "to governments, ministries, agencies and firms; keep a neutral, analytical tone and paraphrase "
    "positions rather than quoting inflammatory passages verbatim.\n"
    "- 证据归属、[S#] 引用与篇幅纪律全部不变。/ Every evidence-attribution, [S#] citation and length rule still applies."
)

_DIRECTIVE_L2 = (
    "\n- 本次尝试不提供检索工具，也不要发起任何工具调用：仅依据系统提示中的背景档案、来源索引与已完成章节撰写，"
    "直接输出本章正文；[S#] 只能引用来源索引中已有的编号。\n"
    "- No retrieval tools are available in this attempt and you must not issue tool calls: write from the "
    "background dossier, the source index and the completed chapters in this prompt and output the chapter "
    "directly; cite only [S#] numbers that already appear in the source index."
)


def register_directive(level: int) -> str:
    """System-prompt directive for ladder ``level`` (empty for level <= 0)."""
    if level <= 0:
        return ""
    text = _DIRECTIVE_L1
    if level >= LEVEL_NO_TOOLS:
        text += _DIRECTIVE_L2
    return text


#: Translation rung (bilingual pass): appended to the translator's system prompt for the one
#: retry of a chunk the provider content filter rejected.  Same neutral institutional register
#: as :data:`_DIRECTIVE_L1`, but fidelity-preserving: every personal, office and organisation
#: name stays exactly as written in the source.
_TRANSLATION_DIRECTIVE = (
    "INSTITUTIONAL-REGISTER RETRY — the provider's content filter rejected the previous "
    "attempt at this passage. Render it in the neutral, formal register of official "
    "institutional reporting (ministry communiqués, central-bank bulletins): standard official "
    "terminology, no colloquial, emotive or inflammatory wording, no added commentary. Fidelity "
    "is unchanged: translate every sentence and keep every personal, office and organisation "
    "name exactly as written in the source — never replace a name with a descriptor such as "
    "'the country's leader'.\n"
    "【机构语体重试】上一次尝试被提供方内容审查拒绝：以正式、中性的机构公文语体逐句翻译，使用规范的"
    "官方术语，不用口语化、情绪化或煽动性措辞，不增删内容；所有人名、职务与机构名称保持原文写法，"
    "不得以职务描述替代人名。"
)


def translation_register_directive() -> str:
    """Prompt rule for the single retry of a content-filtered translation chunk."""
    return _TRANSLATION_DIRECTIVE


def cap_observation(result: object, level: int) -> str:
    """Retrieved passage as injected into the conversation: capped at level >= 1, else unchanged."""
    text = str(result if result is not None else "")
    if level >= LEVEL_REGISTER and len(text) > OBSERVATION_CHARS_AT_LEVEL_1:
        return text[:OBSERVATION_CHARS_AT_LEVEL_1] + "\n…（检索回包已按机构称谓写作模式截断 / passage capped）"
    return text


def level_label(level: int) -> str:
    return {
        LEVEL_DRAFT_ACCEPTED: "L0 采纳已通过审查的完整草稿",
        LEVEL_REGISTER: "L1 机构称谓/工具下限 1/回包截断",
        LEVEL_NO_TOOLS: "L2 机构称谓/无检索工具",
    }.get(level, f"L{level}")
