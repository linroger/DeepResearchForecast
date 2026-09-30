"""Offline tests for the report-area audit fixes (findings_report.json).

Covers, with no LLM/network (stubbed deps):
  * RPT-2   section retry-with-backoff; all-placeholder report → FAILED (never completed);
            outline-degraded + first-two-sections-failed early abort
  * RPT-3   spine critiqued before prose; finalizer skips re-critique (data-driven)
  * RPT-4   contrarian binary framing rule + low-probability reframe top-up
  * RPT-5   quote-provenance audit v2 (system-blockquote exemptions, normalization,
            multi-probe, unverbatim-vs-fabricated split)
  * RPT-6   binary themes parameterized (no Bridgewater hardcoding)
  * RPT-7   live tool hints, XML key normalization, unknown-tool correction without
            budget burn, live unknown-tool message, interview_agents short-circuit
  * RPT-9   contextvar propagation into concurrent section workers
  * RPT-11  native-path tool batch sliced to budget + log_tool_result emitted
  * RPT-13  opinion_shift empty-actor guard
  * KG-1    cross-encoder recipe degrades to RRF twin under NoOpCrossEncoder
  * KG-2    query clamp: local default + semantic (prefix + tail entities) compression
  * XRUN-1  binary 'source' provenance field, sim-signal injection, cross-report
            sim-insensitivity gate
  * XRUN-5  compact retrieval query derivation
  * XRUN-7  progress.json failed_sections/forecast_ok bookkeeping
  * XRUN-16 skeleton→final scenario-count drift surfaced in forecast quality
"""

import asyncio
import contextvars
import json
import os
import sys
import threading

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.config import Config  # noqa: E402
from app.services import forecast_extractor as fe  # noqa: E402
from app.services.report_agent import (  # noqa: E402
    ReportAgent, ReportManager, ReportOutline, ReportSection, ReportStatus,
    SECTION_FAILURE_PLACEHOLDER, _current_report_id,
)
from app.services.zep_tools import (  # noqa: E402
    ZepToolsService, compact_graph_query, _semantic_clamp_query,
)


# ─────────────────────────────── helpers ────────────────────────────────
class _JsonLLM:
    """chat_json stub scripted per prompt marker; records every prompt."""

    def __init__(self, router):
        self.router = router
        self.prompts = []

    def chat_json(self, messages=None, temperature=0.2, max_tokens=2048, **kw):
        content = messages[-1]["content"]
        self.prompts.append(content)
        return self.router(content)


def _bare_agent(**over):
    a = ReportAgent.__new__(ReportAgent)
    a.graph_id = "g1"
    a.simulation_id = "sim1"
    a.simulation_requirement = "会发生什么？"
    a.situation_brief = ""
    a.actors = None
    a.sources = []
    a.research_report = ""
    a.output_language = "English"
    a.scenario_label = ""
    a.base_simulation_id = None
    a._background_block = ""
    a._sources_index = ""
    a._signal_pack = ""
    a._forecast_spine = None
    a._forecast_spine_block = ""
    a._retrieval_query = None
    a._outline_degraded = False
    a._outline_summary = ""
    a._section_tool_calls = 0
    a.report_logger = None
    a.console_logger = None
    a.tools = {}
    for k, v in over.items():
        setattr(a, k, v)
    return a


# ─────────────────────────── RPT-4 / RPT-6 / XRUN-1(a,b) ───────────────────────────
def _binary_rows(probs, theme="ai"):
    return [{"statement": f"Forecast number {i} resolves by 2027 at over {i}%.",
             "probability": p, "resolution_criteria": "指数 超过 10% 于 2027年前 (WTO)",
             "theme": theme, "horizon_year": 2027}
            for i, p in enumerate(probs, 1)]


def test_binary_contrarian_rule_and_low_p_reframe(monkeypatch):
    monkeypatch.setattr(Config, "FORECAST_BINARY_CONTRARIAN", True, raising=False)
    calls = {"n": 0}

    def router(content):
        calls["n"] += 1
        if "0.05-0.35 range" in content:  # RPT-4: low-p reframe pass
            return {"binary_forecasts": [
                {"statement": f"Contrarian outcome {i} exceeds 30% by 2027.",
                 "probability": p, "resolution_criteria": "指数 超过 30% 于 2027年前 (IMF)",
                 "theme": "ai", "horizon_year": 2027}
                for i, p in enumerate([0.1, 0.2, 0.25], 1)
            ]}
        return {"binary_forecasts": _binary_rows([0.7, 0.72, 0.74, 0.71, 0.73,
                                                  0.7, 0.72, 0.74, 0.71, 0.73])}

    llm = _JsonLLM(router)
    out = fe.extract_binary_forecasts("dossier", llm, min_count=10)
    # first-pass prompt carries the contrarian framing rule
    assert "CONTRARIAN FRAMING" in llm.prompts[0]
    # all first-pass probs > 0.5 and stdev tiny → exactly one low-p reframe pass ran
    assert any("0.05-0.35 range" in p for p in llm.prompts)
    probs = [b["probability"] for b in out["binary_forecasts"]]
    assert min(probs) < 0.5
    # ids renumbered stably
    assert [b["id"] for b in out["binary_forecasts"]][:3] == ["F1", "F2", "F3"]


def test_binary_contrarian_flag_off_restores_legacy_prompt(monkeypatch):
    monkeypatch.setattr(Config, "FORECAST_BINARY_CONTRARIAN", False, raising=False)
    llm = _JsonLLM(lambda c: {"binary_forecasts": _binary_rows([0.7] * 10)})
    fe.extract_binary_forecasts("dossier", llm, min_count=10)
    assert all("CONTRARIAN FRAMING" not in p for p in llm.prompts)
    assert all("0.05-0.35 range" not in p for p in llm.prompts)


def test_binary_themes_parameterized(monkeypatch):
    monkeypatch.setattr(Config, "FORECAST_BINARY_CONTRARIAN", False, raising=False)
    # legacy trio: unknown themes coerced to the residual (last) theme — old behavior
    rows = _binary_rows([0.8] * 10, theme="weird")
    llm = _JsonLLM(lambda c: {"binary_forecasts": [dict(r) for r in rows]})
    out = fe.extract_binary_forecasts(
        "dossier", llm, min_count=10, themes=["mercantilism", "ai", "intersection"])
    assert "mercantilism|ai|intersection" in llm.prompts[0]
    assert all(b["theme"] == "intersection" for b in out["binary_forecasts"])
    assert set(out["binary_quality"]["themes"]) >= {"mercantilism", "ai", "intersection"}

    # no themes → free-form theme kept verbatim; no Bridgewater wording in the prompt
    llm2 = _JsonLLM(lambda c: {"binary_forecasts": [dict(r) for r in rows]})
    out2 = fe.extract_binary_forecasts("dossier", llm2, min_count=10)
    assert "mercantilism|ai|intersection" not in llm2.prompts[0]
    assert "Modern Mercantilism" not in llm2.prompts[0]
    assert all(b["theme"] == "weird" for b in out2["binary_forecasts"])
    assert out2["binary_quality"]["themes"].get("weird") == len(out2["binary_forecasts"])


def test_binary_source_provenance_and_signal_pack(monkeypatch):
    monkeypatch.setattr(Config, "FORECAST_BINARY_CONTRARIAN", False, raising=False)
    monkeypatch.setattr(Config, "FORECAST_SIM_SENSITIVITY", True, raising=False)
    # Foglamp WP1 (1D)：模拟信号进入二元概率生成仅剩 legacy_prompt（特征化）路径；
    # 本测试特征化该旧路径的溯源对账行为。默认 diagnostic_only 下模拟信号不再注入
    # （见 test_foglamp_containment.test_diagnostic_policy_keeps_sim_out_of_binary_probability_prompts）。
    monkeypatch.setattr(Config, "SIMULATION_FORECAST_EFFECT", "legacy_prompt", raising=False)
    rows = _binary_rows([0.8] * 10)
    rows[0]["source"] = "world-state outcome shares"
    llm = _JsonLLM(lambda c: {"binary_forecasts": [dict(r) for r in rows]})
    # SESSION-B（编造溯源修复）：source 须可对账到确实注入过的信号块——包里必须真有
    # world-state 块标记，该标签才被保留（不再无条件信任模型声称）。
    out = fe.extract_binary_forecasts(
        "dossier", llm, min_count=10,
        signal_pack="【预测结果分布 P(outcome)（内部分析先验）】\n· 突破: 60%")
    # XRUN-1(b): sim signals injected + move-from-anchor requirement stated
    assert "[Simulation quantitative signals]" in llm.prompts[0]
    assert "SIMULATION SENSITIVITY" in llm.prompts[0]
    # XRUN-1(a): explicit source preserved (block was injected); missing source
    # defaults to research-prior
    assert out["binary_forecasts"][0]["source"] == "world-state outcome shares"
    assert out["binary_forecasts"][1]["source"] == "research-prior"
    assert out["binary_quality"]["provenance_downgrades"] == 0


# ────────────────────────────────── RPT-13 ──────────────────────────────────
def test_opinion_shift_requires_actor_name(monkeypatch):
    from app.services.simulation_runner import SimulationRunner

    class _A:
        agent_name = "张三"
        round_num = 1
        action_type = "post"

    monkeypatch.setattr(SimulationRunner, "get_actions",
                        classmethod(lambda cls, sim, limit=100000: [_A()]))
    zt = ZepToolsService.__new__(ZepToolsService)
    out = zt.opinion_shift("sim1", "")
    assert "需要 actor_name" in out
    # non-empty actor still works
    assert "张三" in zt.opinion_shift("sim1", "张三")


# ─────────────────────────────────── KG-2 ───────────────────────────────────
def test_compact_graph_query_sentence_boundary():
    long = ("Two seismic forces are reshaping the global order today. " * 3
            + "What happens to Nvidia by 2030? " * 30)
    q = compact_graph_query(long, 120)
    assert len(q) <= 120
    assert q.endswith(".")            # cut at a sentence boundary
    short = "会发生什么？"
    assert compact_graph_query(short, 120) == short


def test_semantic_clamp_preserves_tail_entities():
    query = ("lowercase filler words " * 40
             + "Nvidia TSMC 2030 export-controls 45%").strip()
    out = _semantic_clamp_query(query, 200)
    assert len(out) <= 200
    # proper nouns + numbers from the truncated tail survive the clamp
    assert "Nvidia" in out and "TSMC" in out and "2030" in out


# ─────────────────────────────────── KG-1 ───────────────────────────────────
class _RecipeRecorder:
    def __init__(self, seen):
        self.seen = seen
        self.limit = None

    def model_copy(self, deep=False):
        return self


class _StubGraph:
    async def search_(self, query, **kwargs):
        class _R:
            edges = []
            nodes = []
        return _R()


def _kg1_runtime(cross_encoder):
    from app.services.graphiti_client.runtime import GraphitiRuntime

    rt = GraphitiRuntime.__new__(GraphitiRuntime)
    seen = {}

    async def _ensure(gid):
        return _StubGraph()

    rt._ensure_graph = _ensure
    rt._get_clients = lambda: (None, None, cross_encoder)
    rt._serialize_reads = lambda: False
    rt._to_search_filters = lambda spec: None
    rt._resolve_recipe = lambda sel, scope: (seen.setdefault("selector", sel),
                                             _RecipeRecorder(seen))[1]
    return rt, seen


def test_noop_cross_encoder_degrades_to_rrf():
    from app.services.graphiti_client.cross_encoder import NoOpCrossEncoder

    rt, seen = _kg1_runtime(NoOpCrossEncoder())
    asyncio.run(rt._search("g1", "q", 10, "edges", recipe="cross_encoder"))
    assert seen["selector"] == "rrf"

    rt2, seen2 = _kg1_runtime(NoOpCrossEncoder())
    asyncio.run(rt2._search("g1", "q", 10, "edges", recipe="combined_cross_encoder"))
    assert seen2["selector"] == "combined"   # keeps the multi-layer search


def test_real_reranker_keeps_cross_encoder_recipe():
    rt, seen = _kg1_runtime(object())  # anything not a NoOpCrossEncoder
    asyncio.run(rt._search("g1", "q", 10, "edges", recipe="cross_encoder"))
    assert seen["selector"] == "cross_encoder"


# ─────────────────────────────────── RPT-5 ──────────────────────────────────
def test_quote_provenance_v2_exemptions_and_split(monkeypatch):
    monkeypatch.setattr(Config, "REPORT_QUOTE_AUDIT_V2", True, raising=False)
    ground = ("The AI compute buildout is the largest capital-expenditure cycle in history, "
              "according to the fund's co-CIOs, reshaping capital allocation worldwide.")
    a = _bare_agent(research_report=ground,
                    _outline_summary="本报告分析未来十年的 AI 与重商主义交汇。")
    md = "\n\n".join([
        "# T",
        "> 本报告分析未来十年的 AI 与重商主义交汇。",                       # system summary → exempt
        "> " + ReportAgent._TABLE_NOTE_TEXT,                                  # table note → exempt
        '> "The **AI compute buildout** is the largest capital-expenditure cycle in history"',  # verbatim (emphasis) → ok
        '> "Bridgewater’s CIOs frame the buildout as a once-in-a-century regime change" [S1]',  # cited paraphrase → unverbatim
        '> "The world government confirmed the treaty was signed on Mars in 2031"',             # fabricated → ungrounded
    ])
    out = a._audit_quote_provenance(md)
    assert out["ungrounded"] == 1
    assert "Mars" in out["examples"][0]
    assert out["cited_unverbatim"] == 1
    assert "CIOs" in out["unverbatim_examples"][0]


def test_quote_provenance_v1_flag_off_restores_legacy(monkeypatch):
    monkeypatch.setattr(Config, "REPORT_QUOTE_AUDIT_V2", False, raising=False)
    a = _bare_agent(research_report="some ground text")
    md = "> completely fabricated quote that matches nothing here at all"
    out = a._audit_quote_provenance(md)
    assert out["ungrounded"] == 1
    assert "cited_unverbatim" not in out


# ─────────────────────────────────── RPT-7 ──────────────────────────────────
def _min_tools():
    return {
        "insight_forge": {"name": "insight_forge", "description": "d", "parameters": {}},
        "quick_search": {"name": "quick_search", "description": "d", "parameters": {}},
    }


def test_tool_usage_hints_track_live_tools():
    a = _bare_agent(tools=_min_tools())
    hints = a._tool_usage_hints()
    assert "insight_forge" in hints and "quick_search" in hints
    assert "interview_agents" not in hints
    a.tools["interview_agents"] = {"name": "interview_agents", "description": "d", "parameters": {}}
    assert "interview_agents" in a._tool_usage_hints()


def test_execute_tool_unknown_message_lists_live_tools():
    a = _bare_agent(tools=_min_tools())
    msg = a._execute_tool("no_such_tool", {})
    assert "insight_forge" in msg and "quick_search" in msg
    assert "no_such_tool" in msg


def test_execute_tool_interview_short_circuit_when_removed():
    a = _bare_agent(tools=_min_tools())  # interview_agents popped (env offline)
    out = a._execute_tool("interview_agents", {"interview_topic": "t"})
    assert "不可用" in out


def test_parse_tool_calls_normalizes_xml_keys():
    a = _bare_agent(tools=_min_tools())
    calls = a._parse_tool_calls(
        '<tool_call>\n{"tool": "quick_search", "params": {"query": "q"}}\n</tool_call>')
    assert calls and calls[0]["name"] == "quick_search"
    assert calls[0]["parameters"] == {"query": "q"}


def test_react_unknown_tool_corrected_without_budget_burn():
    body = "这是一段足够长的中文正文内容。" * 60  # RQ-1: >= MIN_VALID_SECTION_CHARS(800)
    executed = []

    class _LLM:
        def __init__(self):
            self.calls = []
            self._i = 0
            self.responses = [
                '<tool_call>\n{"name": "interview_agents", "parameters": {}}\n</tool_call>',
                "Final Answer: " + body,
            ]

        def chat(self, messages=None, temperature=0.3, max_tokens=4096, **kw):
            self.calls.append([dict(m) for m in messages])
            r = self.responses[min(self._i, len(self.responses) - 1)]
            self._i += 1
            return r

    a = _bare_agent(tools=_min_tools())
    a.MIN_TOOL_CALLS_PER_SECTION = 0
    a.MAX_TOOL_CALLS_PER_SECTION = 2
    a.llm = _LLM()
    a._execute_tool = lambda name, params, report_context="": executed.append(name) or "R"
    section = ReportSection(title="正文1")
    outline = ReportOutline(title="T", summary="S", sections=[section])
    result = a._generate_section_react(section, outline, previous_sections=[])
    assert body in result
    assert executed == []  # unknown tool was never executed → no budget burned
    corrective = [m["content"] for msgs in a.llm.calls for m in msgs
                  if isinstance(m.get("content"), str) and "不是可用工具" in m["content"]]
    assert corrective and "quick_search" in corrective[0]


# ─────────────────────────────────── RPT-9 ──────────────────────────────────
def test_concurrent_sections_inherit_report_id_contextvar():
    a = _bare_agent()

    def _fake_gen(section, outline, previous_sections, progress_callback=None, section_index=0):
        return f"CTX={_current_report_id.get()}"

    a._generate_section_with_retry = (
        lambda section, outline, previous_sections, progress_callback=None, section_index=0:
        _fake_gen(section, outline, previous_sections, progress_callback, section_index))
    outline = ReportOutline(title="T", summary="S", sections=[
        ReportSection(title="正文1"), ReportSection(title="正文2"),
    ])
    token = _current_report_id.set("report_ctx_test")
    try:
        contents = a._generate_sections_concurrent(outline, concurrency=2)
    finally:
        _current_report_id.reset(token)
    assert contents[0] == "CTX=report_ctx_test"
    assert contents[1] == "CTX=report_ctx_test"


# ─────────────────────────────────── RPT-11 ─────────────────────────────────
def test_native_path_slices_batch_and_logs_results():
    executed = []
    tool_msgs = []

    class _NativeLLM:
        def __init__(self):
            self._i = 0

        def chat_with_tools(self, messages, schemas, temperature=0.5, max_tokens=4096):
            self._i += 1
            if self._i == 1:
                return {"content": "", "tool_calls": [
                    {"id": f"c{k}", "name": "quick_search", "arguments": {"query": str(k)}}
                    for k in range(4)
                ]}
            return {"content": "本章正文" * 100, "tool_calls": []}

        def chat(self, **kw):
            return "fallback"

    class _Logger:
        def __init__(self):
            self.results = []

        def log_section_start(self, *a, **k):
            pass

        def log_tool_call(self, *a, **k):
            pass

        def log_tool_result(self, title, idx, name, result, iteration):
            self.results.append((name, result))

    a = _bare_agent(tools=_min_tools())
    a.MIN_TOOL_CALLS_PER_SECTION = 0
    a.MAX_TOOL_CALLS_PER_SECTION = 2
    a.llm = _NativeLLM()
    a.report_logger = _Logger()
    a._execute_tool = lambda name, args, report_context="": executed.append(args) or "R"
    section = ReportSection(title="正文1")
    outline = ReportOutline(title="T", summary="S", sections=[section])
    out = a._generate_section_native(section, outline, previous_sections=[])
    assert "本章正文" in out
    # batch of 4 sliced to the remaining budget of 2
    assert len(executed) == 2
    # RPT-11: tool results now logged on the native path
    assert len(a.report_logger.results) == 2


# ───────────────────────────── RPT-2 / XRUN-7 ──────────────────────────────
def test_section_retry_before_placeholder(monkeypatch):
    monkeypatch.setattr(Config, "REPORT_SECTION_RETRY_MAX", 1, raising=False)
    monkeypatch.setattr(Config, "REPORT_SECTION_RETRY_BACKOFF_S", 0.0, raising=False)
    a = _bare_agent()
    attempts = {"n": 0}

    def _flaky(section, outline, previous_sections, progress_callback=None, section_index=0):
        attempts["n"] += 1
        if attempts["n"] == 1:
            raise RuntimeError("transient 500")
        return "ok-body"

    a._generate_section = _flaky
    section = ReportSection(title="正文1")
    outline = ReportOutline(title="T", summary="S", sections=[section])
    assert a._generate_section_with_retry(section, outline, []) == "ok-body"
    assert attempts["n"] == 2

    # retries exhausted → the exception propagates (caller writes the placeholder)
    a2 = _bare_agent()
    a2._generate_section = lambda *args, **kw: (_ for _ in ()).throw(RuntimeError("dead"))
    with pytest.raises(RuntimeError):
        a2._generate_section_with_retry(section, outline, [])


def _wire_report_dirs(monkeypatch, tmp_path):
    monkeypatch.setattr(Config, "UPLOAD_FOLDER", str(tmp_path), raising=False)
    monkeypatch.setattr(ReportManager, "REPORTS_DIR", str(tmp_path / "reports"), raising=False)
    monkeypatch.setattr(Config, "REPORT_SECTION_CONCURRENCY", 1, raising=False)
    monkeypatch.setattr(Config, "REPORT_SECTION_RETRY_MAX", 0, raising=False)
    monkeypatch.setattr(Config, "REPORT_STRUCTURED_FORECAST", False, raising=False)
    monkeypatch.setattr(Config, "REPORT_SIGNAL_PACK", False, raising=False)
    monkeypatch.setattr(Config, "LLM_TELEMETRY_ENABLED", False, raising=False)


def _outage_agent(fail_all=True):
    a = _bare_agent()
    outline = ReportOutline(title="T", summary="S", sections=[
        ReportSection(title=f"正文{i}") for i in range(1, 4)
    ])
    a.plan_outline = lambda progress_callback=None, forecast_spine_block="", \
        require_forecast_structure=False: outline
    a._outline_degraded = True

    def _gen(section, outline, previous_sections, progress_callback=None, section_index=0):
        if fail_all:
            raise RuntimeError("LLM outage")
        return "这是一段足够长的正文内容。" * 40

    a._generate_section = _gen
    return a


def test_all_placeholder_report_is_failed_not_completed(monkeypatch, tmp_path):
    _wire_report_dirs(monkeypatch, tmp_path)
    monkeypatch.setattr(Config, "REPORT_ABORT_ON_LLM_OUTAGE", True, raising=False)
    a = _outage_agent(fail_all=True)
    report = a.generate_report(report_id="report_outage_test")
    assert report.status == ReportStatus.FAILED
    prog = ReportManager.get_progress("report_outage_test")
    assert prog["status"] == "failed"


def test_outage_aborts_after_first_two_sections(monkeypatch, tmp_path):
    """RPT-2(b): outline degraded + first two sections placeholder ⇒ abort before section 3."""
    _wire_report_dirs(monkeypatch, tmp_path)
    monkeypatch.setattr(Config, "REPORT_ABORT_ON_LLM_OUTAGE", True, raising=False)
    a = _outage_agent(fail_all=True)
    calls = {"n": 0}
    orig = a._generate_section

    def _counting(section, outline, previous_sections, progress_callback=None, section_index=0):
        calls["n"] += 1
        return orig(section, outline, previous_sections, progress_callback, section_index)

    a._generate_section = _counting
    report = a.generate_report(report_id="report_outage_abort")
    assert report.status == ReportStatus.FAILED
    assert calls["n"] == 2  # burned 2 sections, not all 3


def test_outage_flag_off_keeps_legacy_completed(monkeypatch, tmp_path):
    _wire_report_dirs(monkeypatch, tmp_path)
    monkeypatch.setattr(Config, "REPORT_ABORT_ON_LLM_OUTAGE", False, raising=False)
    # Isolate the legacy outage flag. The default-on final publish audit now
    # correctly rejects the placeholder-only/mixed-language artifact regardless.
    monkeypatch.setattr(Config, "REPORT_FINAL_READ_ONLY_AUDIT", False, raising=False)
    a = _outage_agent(fail_all=True)
    report = a.generate_report(report_id="report_outage_legacy")
    assert report.status == ReportStatus.COMPLETED  # today's (broken) behavior preserved
    assert len(report.failed_sections) == 3


def test_progress_json_reports_failed_sections(monkeypatch, tmp_path):
    monkeypatch.setattr(Config, "UPLOAD_FOLDER", str(tmp_path), raising=False)
    monkeypatch.setattr(ReportManager, "REPORTS_DIR", str(tmp_path / "reports"), raising=False)
    ReportManager.update_progress(
        "report_p1", "completed", 100, "done",
        completed_sections=["A", "B", "C"],
        failed_sections=["B"],
        forecast_ok=False,
    )
    prog = ReportManager.get_progress("report_p1")
    assert prog["completed_sections"] == ["A", "C"]
    assert prog["failed_sections"] == ["B"]
    assert prog["placeholder_count"] == 1
    assert prog["health"] == "degraded"
    assert prog["forecast_ok"] is False
    # legacy call shape unchanged (no new keys when kwargs omitted)
    ReportManager.update_progress("report_p2", "generating", 50, "msg",
                                  completed_sections=["A"])
    prog2 = ReportManager.get_progress("report_p2")
    assert "failed_sections" not in prog2 and "forecast_ok" not in prog2


# ─────────────────────────────────── RPT-3 ──────────────────────────────────
def test_spine_critiqued_before_prose(monkeypatch, tmp_path):
    monkeypatch.setattr(Config, "UPLOAD_FOLDER", str(tmp_path), raising=False)
    monkeypatch.setattr(ReportManager, "REPORTS_DIR", str(tmp_path / "reports"), raising=False)
    monkeypatch.setattr(Config, "REPORT_CRITIQUE_BEFORE_PROSE", True, raising=False)
    monkeypatch.setattr(Config, "REPORT_FORECAST_SELF_CRITIQUE", True, raising=False)
    monkeypatch.setattr(Config, "REPORT_PREMORTEM", False, raising=False)
    monkeypatch.setattr(Config, "REPORT_SPINE_SELFCONSISTENCY_K", 1, raising=False)

    scen = [{"name": "情景A维持现状", "probability": 0.6, "summary": "s",
             "resolution_criteria": "指数 超过 10% 于 2027年前"},
            {"name": "情景B剧变", "probability": 0.4, "summary": "s",
             "resolution_criteria": "指数 低于 5% 于 2027年前"}]

    def router(content):
        if "红队评审" in content:
            out = [dict(s) for s in scen]
            out[0]["critique_note"] = "回归基率"
            return {"scenarios": out, "confidence": "medium"}
        return {"headline": "h", "horizon": "2030", "scenarios": scen,
                "confidence": "medium"}

    (tmp_path / "reports" / "report_spine_test").mkdir(parents=True)  # 生产路径由 generate_report 预建
    a = _bare_agent(llm=_JsonLLM(router))
    a._derive_and_pin_forecast_spine("report_spine_test")
    assert a._forecast_spine is not None
    # RPT-3: spine carries the data-driven critiqued marker BEFORE any prose exists
    assert a._forecast_spine.get("critiqued") is True
    # the early forecast.json also ships the critiqued probabilities
    fpath = os.path.join(str(tmp_path), "reports", "report_spine_test", "forecast.json")
    with open(fpath, encoding="utf-8") as f:
        assert json.load(f).get("critiqued") is True


def test_finalizer_skips_recritique_when_spine_critiqued(monkeypatch, tmp_path):
    monkeypatch.setattr(Config, "UPLOAD_FOLDER", str(tmp_path), raising=False)
    monkeypatch.setattr(ReportManager, "REPORTS_DIR", str(tmp_path / "reports"), raising=False)
    monkeypatch.setattr(Config, "REPORT_FORECAST_SELF_CRITIQUE", True, raising=False)
    monkeypatch.setattr(Config, "FORECAST_EMIT_BINARY", False, raising=False)
    monkeypatch.setattr(Config, "REPORT_PUBLISH_GATE", False, raising=False)
    monkeypatch.setattr(Config, "REPORT_FORECAST_LEDGER", False, raising=False)
    spine = {"headline": "h", "horizon": "2030", "confidence": "medium",
             "confidence_rationale": "", "key_uncertainties": [],
             "scenarios": [{"name": "情景A", "probability": 1.0, "summary": "",
                            "key_drivers": [], "resolution_criteria": ""}],
             "critiqued": True, "schema_version": 1}
    llm = _JsonLLM(lambda c: {})
    a = _bare_agent(llm=llm, _forecast_spine=dict(spine))
    a._finalize_structured_forecast("report_fin_test", "# T\n\n正文")
    # critiqued spine → no red-team prompt was issued at finalize time
    assert all("红队评审" not in p for p in llm.prompts)


# ────────────────────────────── XRUN-1(c) / XRUN-16 ─────────────────────────
def _write_other_report(tmp_path, rid, graph_id, sim_id, probs):
    folder = tmp_path / "reports" / rid
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "meta.json").write_text(json.dumps(
        {"graph_id": graph_id, "simulation_id": sim_id}), encoding="utf-8")
    (folder / "forecast.json").write_text(json.dumps(
        {"binary_forecasts": [{"statement": f"s{i}", "probability": p}
                              for i, p in enumerate(probs)]}), encoding="utf-8")


def test_sim_insensitivity_gate(monkeypatch, tmp_path):
    monkeypatch.setattr(Config, "UPLOAD_FOLDER", str(tmp_path), raising=False)
    monkeypatch.setattr(ReportManager, "REPORTS_DIR", str(tmp_path / "reports"), raising=False)
    probs = [0.82, 0.8, 0.78, 0.72, 0.62, 0.7]
    _write_other_report(tmp_path, "report_other", "g1", "sim_OTHER", probs)
    a = _bare_agent(graph_id="g1", simulation_id="sim_MINE")
    fc = {"binary_forecasts": [{"statement": f"x{i}", "probability": p}
                               for i, p in enumerate(probs)]}
    hit = a._check_binary_sim_sensitivity("report_mine", fc)
    assert hit and hit["other_report_id"] == "report_other"
    # different vector → no hit; same simulation_id → no hit
    fc2 = {"binary_forecasts": [{"statement": f"x{i}", "probability": p - 0.1}
                                for i, p in enumerate(probs)]}
    assert a._check_binary_sim_sensitivity("report_mine", fc2) is None
    a2 = _bare_agent(graph_id="g1", simulation_id="sim_OTHER")
    assert a2._check_binary_sim_sensitivity("report_mine", fc) is None


def test_scenario_count_drift_surfaced(monkeypatch, tmp_path):
    monkeypatch.setattr(Config, "UPLOAD_FOLDER", str(tmp_path), raising=False)
    monkeypatch.setattr(ReportManager, "REPORTS_DIR", str(tmp_path / "reports"), raising=False)
    monkeypatch.setattr(Config, "REPORT_FORECAST_SELF_CRITIQUE", True, raising=False)
    monkeypatch.setattr(Config, "REPORT_CRITIQUE_BEFORE_PROSE", False, raising=False)
    monkeypatch.setattr(Config, "FORECAST_EMIT_BINARY", False, raising=False)
    monkeypatch.setattr(Config, "REPORT_PUBLISH_GATE", False, raising=False)
    monkeypatch.setattr(Config, "REPORT_FORECAST_LEDGER", False, raising=False)
    spine = {"headline": "h", "horizon": "2030", "confidence": "medium",
             "confidence_rationale": "", "key_uncertainties": [],
             "scenarios": [
                 {"name": "情景甲乙丙", "probability": 0.6, "summary": "", "key_drivers": [],
                  "resolution_criteria": ""},
                 {"name": "情景丁戊己", "probability": 0.4, "summary": "", "key_drivers": [],
                  "resolution_criteria": ""}],
             "schema_version": 1}

    def router(content):
        if "红队评审" in content:  # critique adds a residual scenario → 2 → 3 drift
            return {"scenarios": [
                {"name": "情景甲乙丙", "probability": 0.5,
                 "resolution_criteria": "截至2030年指标高于10%"},
                {"name": "情景丁戊己", "probability": 0.3,
                 "resolution_criteria": "截至2030年指标低于5%"},
                {"name": "其它维持现状", "probability": 0.2,
                 "resolution_criteria": "截至2030年不满足其它已命名情景"}]}
        return {}

    a = _bare_agent(llm=_JsonLLM(router), _forecast_spine=dict(spine))
    a._finalize_structured_forecast("report_drift_test", "# T\n\n正文")
    fpath = os.path.join(str(tmp_path), "reports", "report_drift_test", "forecast.json")
    with open(fpath, encoding="utf-8") as f:
        fc = json.load(f)
    drift = (fc.get("quality") or {}).get("scenario_count_drift")
    assert drift == {"pinned": 2, "final": 3}


# ─────────────────────────────────── XRUN-5 ─────────────────────────────────
def test_compact_retrieval_query_derivation(monkeypatch):
    monkeypatch.setattr(Config, "REPORT_COMPACT_RETRIEVAL_QUERY", True, raising=False)
    long_req = ("Two seismic forces are reshaping the global order. " * 20
                + "What is the probability that Nvidia keeps 80% share by 2030?")
    actors = {"actors": [{"name": "Nvidia", "salience": {"score": 0.9}},
                         {"name": "TSMC", "salience": {"score": 0.8}}]}
    a = _bare_agent(simulation_requirement=long_req, actors=actors)
    q = a._compact_retrieval_query()
    assert len(q) <= 360
    assert "Nvidia" in q            # top-salience actors appended
    assert q == a._compact_retrieval_query()  # cached
    # flag off → raw requirement passes through untouched
    monkeypatch.setattr(Config, "REPORT_COMPACT_RETRIEVAL_QUERY", False, raising=False)
    a2 = _bare_agent(simulation_requirement=long_req)
    assert a2._compact_retrieval_query() == long_req
