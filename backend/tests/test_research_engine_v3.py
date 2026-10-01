"""Offline tests for the deep-research engine v3 (deerflow_bridge/linear_research.py).

The engine runs against a content-routed fake chat model (it answers by the task
marker in the request, so concurrent fan-out order does not matter), injected
search/fetch functions and the REAL ``deerflow_research`` bridge module with the
prediction-market and chart steps replaced by recording stubs.  The backend
venv has no langchain, so everything also proves the engine works on the
gateway's stand-in message classes.  Zero network, zero LLM, no sleeps.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import sys
import threading
import time
import types
from pathlib import Path

import pytest

_BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_REPO_ROOT = os.path.dirname(_BACKEND)
_BRIDGE = os.path.join(_REPO_ROOT, "deerflow_bridge")
for _path in (_BACKEND, _BRIDGE):
    if _path not in sys.path:
        sys.path.insert(0, _path)

import deerflow_research as dr  # noqa: E402
import linear_research as lr  # noqa: E402
import research_gateway as rg  # noqa: E402
from app.services import pipeline_orchestrator as po  # noqa: E402
from app.services.research_progress import ResearchProgressEstimator  # noqa: E402
from app.utils.actors import forecast_inputs_from_report_markdown  # noqa: E402

SystemMessage, HumanMessage, AIMessage, ToolMessage = rg._msg_classes()

_ENV_EXACT = ("DEERFLOW_RESEARCH_TIMEOUT", "RESEARCH_MODEL_CONCURRENCY_GLOBAL", "DEERFLOW_FALLBACK_MODEL",
              "ACTOR_CAST_MAX", "RESEARCH_STALE_DAYS", "RESEARCH_DEFAULT_SOURCE_TIER", "ACTOR_EXCLUDE_MEDIA",
              "RESEARCH_ENGINE", "RESEARCH_LINEAR_MODE", "RESEARCH_SOURCE_DENY_DOMAINS",
              "RESEARCH_QUANT_TYPING", "RESEARCH_VERIFIED_FACTS",
              "RESEARCH_FETCH_SHELL_DETECTION", "RESEARCH_FETCH_CALL_TIMEOUT_S", "RESEARCH_AS_OF_PIN",
              "RESEARCH_SOURCE_TAXONOMY", "RESEARCH_QUESTION_SPEC", "RESEARCH_FORECAST_INPUTS",
              "RESEARCH_V3_FORECAST_INPUTS", "RESEARCH_EVIDENCE_QUOTES", "RESEARCH_EVIDENCE_SUPPORTS",
              "RESEARCH_ABSENCE_DISCIPLINE", "RESEARCH_V3_CITATION_STATS",
              "RESEARCH_FORECASTER_ATTRIBUTION", "RESEARCH_EVIDENCE_HEADERS", "RESEARCH_TRUNCATION_FAIRNESS",
              "RESEARCH_JSON_STRICT_NUMBERS", "RESEARCH_DATA_TOOLS", "FRED_API_KEY", "SEC_EDGAR_USER_AGENT",
              "DATA_QUANT_ROWS_MAX")


@pytest.fixture(autouse=True)
def _hermetic_env(monkeypatch):
    """Engine knobs come only from the test (the developer .env must not leak in)."""
    for name in list(os.environ):
        if name.startswith("RESEARCH_LINEAR_") or name in _ENV_EXACT:
            monkeypatch.delenv(name, raising=False)


@pytest.fixture
def bridge(monkeypatch):
    """The real bridge module with the network-bound finalize steps recorded."""
    calls: dict[str, list] = {"markets": [], "charts": []}

    def markets(out_dir, question, report, meta, plog, model_name="claude"):
        calls["markets"].append({"out_dir": out_dir, "question": question, "report": report,
                                 "model_name": model_name})
        plog.write("stage", "prediction markets: stubbed in tests")

    def charts(out_dir, meta, plog, question=""):
        calls["charts"].append({"out_dir": out_dir, "question": question})
        return {}

    monkeypatch.setattr(dr, "_collect_prediction_markets", markets)
    monkeypatch.setattr(dr, "_render_research_charts", charts)
    dr._v3_test_calls = calls
    yield dr
    del dr._v3_test_calls


# =============================================================== fakes

class FakePlog:
    def __init__(self) -> None:
        self.lines: list[tuple[str, str]] = []
        self.closed = False
        self._lock = threading.Lock()

    def write(self, kind: str, message: str) -> None:
        with self._lock:
            self.lines.append((kind, str(message)))

    def close(self) -> None:  # the engine must never call this
        self.closed = True

    def of(self, kind: str) -> list[str]:
        return [message for k, message in self.lines if k == kind]

    def text(self) -> str:
        return "\n".join(f"[{k}] {m}" for k, m in self.lines)


class ScriptedModel:
    """Fake chat model: ``bind``/``bind_tools`` record kwargs and the tools
    object; ``invoke`` records (type, content) tuples and asks ``responder``."""

    def __init__(self, responder) -> None:
        self.model_name = "fake-model"
        self._state = {"calls": [], "lock": threading.Lock(), "responder": responder}
        self.bound: dict = {}
        self.tools = None

    @property
    def calls(self) -> list[dict]:
        return self._state["calls"]

    def _copy(self):
        clone = copy.copy(self)
        clone.bound = dict(self.bound)
        return clone

    def bind(self, **kwargs):
        clone = self._copy()
        clone.bound.update(kwargs)
        return clone

    def bind_tools(self, tools):
        clone = self._copy()
        clone.tools = tools
        return clone

    def invoke(self, messages):
        call = {"kwargs": copy.deepcopy(self.bound), "tools": self.tools,
                "messages": [(m.type, m.content if isinstance(m.content, str) else str(m.content))
                             for m in messages]}
        with self._state["lock"]:
            self.calls.append(call)
        return self._state["responder"](call)


def ai(text: str = "", tool_calls=None, invalid=None, *, inp: int = 1000, cached: int = 400,
       out: int = 200, finish: str = "stop"):
    return AIMessage(content=text, tool_calls=list(tool_calls or []), invalid_tool_calls=list(invalid or []),
                     usage_metadata={"input_tokens": inp, "output_tokens": out, "total_tokens": inp + out,
                                     "input_token_details": {"cache_read": cached}},
                     response_metadata={"finish_reason": finish})


TASK_MARKERS = ("SCOPE TASK", "QUESTION SPEC TASK", "PLANNING TASK", "KIQ INVESTIGATION TASK", "GAP REVIEW TASK",
                "SECTION WRITING TASK", "EXECUTIVE SUMMARY TASK", "CRITIQUE TASK",
                "ACTOR EXTRACTION TASK", "FACT EXTRACTION TASK", "CACHE WARM-UP")


def role_of(call: dict) -> str:
    last = call["messages"][-1][1]
    if last.startswith("CACHE WARM-UP"):
        return "prime"
    if call["tools"] is not None:
        return "agent"
    for marker in TASK_MARKERS:
        if last.startswith(marker):
            return marker
    raise AssertionError(f"unrecognized request: {last[:80]!r}")


def page_text(url: str) -> str:
    return (f"# Official statistics release for {url.split('/')[2]}\n\n"
            "Installed data-centre capacity reached 176 GW in 2023, up from 150 GW in 2022, "
            "according to the national energy agency's annual survey of operators.\n\n"
            "The agency projects demand growth of 12% per year through 2027 and notes that grid "
            "connection queues exceed 40 months in several regions.\n\n"
            "Operators reported capital expenditure of 1,234 million dollars in the first half.")


def fake_search(query: str, n: int) -> str:
    digest = hashlib.sha1(query.encode("utf-8")).hexdigest()[:6]
    results = [{"title": f"Capacity report {digest}-{i}",
                "url": f"https://www.agency{i}-{digest}.org/data/report-{digest}",
                "content": f"Capacity statistics 2023: 176 GW installed; outlook note {i}."}
               for i in range(1, 4)]
    return json.dumps({"query": query, "results": results})


class World:
    """Content-routed responder producing a realistic, parseable run."""

    SECTIONS = ["Market Baseline", "Demand Drivers", "Key Players", "Grid Constraints",
                "Scenarios and Probabilities", "Signposts to Watch"]

    def __init__(self, *, language: str = "English", fail=None, writer_delay_first: float = 0.0,
                 gap_followups: bool = False, reverse_writer: bool = True) -> None:
        self.language = language
        self.fail = fail  # callable(call, role) -> exception to raise, or None
        self.writer_delay_first = writer_delay_first
        self.gap_followups = gap_followups
        self.reverse_writer = reverse_writer
        self._lock = threading.Lock()
        self.first_writer_seen = False

    # ------------------------------------------------------------ dispatch
    def __call__(self, call: dict):
        role = role_of(call)
        if self.fail is not None:
            error = self.fail(call, role)
            if error is not None:
                raise error
        if role == "prime":
            return ai("OK", out=1)
        handler = {
            "SCOPE TASK": self.scope, "QUESTION SPEC TASK": self.question_spec, "PLANNING TASK": self.plan,
            "agent": self.agent,
            "GAP REVIEW TASK": self.gap, "SECTION WRITING TASK": self.writer,
            "EXECUTIVE SUMMARY TASK": self.exec_summary, "CRITIQUE TASK": self.critique,
            "ACTOR EXTRACTION TASK": self.actors, "FACT EXTRACTION TASK": self.facts,
        }[role]
        return handler(call)

    def zh(self) -> bool:
        return self.language == "Chinese"

    # ------------------------------------------------------------ planning
    def scope(self, call):
        return ai(json.dumps({"restated_question": "Will capacity exceed 250 GW by 2027?",
                              "horizon": "by end of 2027",
                              "scout_queries": ["data centre capacity 2023", "grid connection queue",
                                                "hyperscaler capex 2025", "数据中心 容量"],
                              "key_entities": ["National energy agency", "Hyperscalers"]}))

    def question_spec(self, call):
        return ai(json.dumps({
            "operational_question": "Will installed global data-centre capacity exceed 250 GW on 31 December 2027?",
            "outcome_definition": "Installed global data-centre IT capacity above 250 GW at the end of 2027.",
            "resolution_source": {"name": "National energy agency annual capacity survey",
                                  "url": "https://www.agency1.org/data/capacity", "kind": "official_statistic"},
            "horizon": {"label": "by 31 December 2027", "date": "2027-12-31", "basis": "explicit"},
            "reference_class": "Multi-year infrastructure build-out targets",
            "assumptions": [{"text": "Capacity means installed IT load, not grid connections.", "slot": "units"},
                            {"text": "The agency's end-2027 survey settles the question.",
                             "slot": "resolution_source"}]}))

    def plan(self, call):
        titles = (["市场基线", "需求驱动", "主要参与方", "电网约束", "情景与概率", "观察信号"] if self.zh()
                  else self.SECTIONS)
        sections = [{"title": "Executive Summary", "kiqs": [1], "focus": "summary"}]
        sections += [{"title": title, "kiqs": [i % 4 + 1], "focus": f"focus {i}"} for i, title in enumerate(titles)]
        sections.append({"title": "References", "kiqs": [], "focus": ""})
        names = ["基准情景", "加速扩张", "扩张停滞"] if self.zh() else ["Base case", "Accelerated build-out",
                                                                    "Stalled expansion"]
        plan = {
            "kiqs": [{"question": "What is installed capacity today?", "queries": ["capacity 2023 GW"], "kind": "data"},
                     {"question": "What drives demand growth?", "queries": ["demand drivers ai"], "kind": "general"},
                     {"question": "Which hyperscalers matter most?", "queries": ["hyperscaler capex"], "kind": "actor"},
                     {"question": "How binding are grid constraints?", "queries": ["grid queue months"],
                      "kind": "general", "id": "K99"}],
            "sections": sections,
            "scenarios": [{"name": names[0], "weight": "50%", "thesis": "Trends continue."},
                          {"name": names[1], "weight": "30%", "thesis": "Faster build-out."},
                          {"name": names[2], "weight": "20%", "thesis": "Grid limits bind."}],
            "actors": [{"name": "National energy agency", "type": "government", "why": "sets data"},
                       {"name": "Hyperscaler A", "type": "company", "why": "largest buyer"}],
        }
        return ai("Here is the plan:\n```json\n" + json.dumps(plan, ensure_ascii=False) + "\n```")

    # ------------------------------------------------------------ gathering
    def agent(self, call):
        messages = call["messages"]
        tool_results = [content for kind, content in messages if kind == "tool"]
        last_kind, last = messages[-1]
        task = messages[2][1]
        kid = re.search(r"Investigate (\S+):", task).group(1)
        if last_kind == "human" and last.startswith("STOP"):
            return ai(self.notes(tool_results))
        if not tool_results:
            url = re.search(r"https?://\S+", task)
            if url:
                return ai(tool_calls=[{"name": "web_fetch", "args": {"url": url.group(0), "focus": "capacity"},
                                       "id": f"{kid}-c1"}])
            return ai(tool_calls=[{"name": "web_search", "args": {"query": f"{kid} capacity"}, "id": f"{kid}-c1"}])
        if len(tool_results) == 1:
            return ai(tool_calls=[{"name": "web_search", "args": {"query": f"{kid} market outlook"},
                                   "id": f"{kid}-c2"}])
        return ai(self.notes(tool_results))

    def notes(self, tool_results) -> str:
        fetched = next((int(m.group(1)) for r in tool_results
                        for m in [re.match(r"\[S(\d+)\].*(?:excerpt|full page)", r)] if m), None)
        searched = [int(s) for r in tool_results for s in re.findall(r"^\[S(\d+)\]", r, re.M)]
        other = next((s for s in searched if s != fetched), fetched or 1)
        cite = fetched or other
        return "\n".join([
            "## Findings",
            f"- Installed capacity reached 176 GW in 2023 per the agency survey [S{cite}] (VERIFIED)",
            f"- Operators plan 250 GW of capacity by 2030 [S{cite}] (VERIFIED)",
            f"- Analysts expect 12% annual demand growth through 2027 [S{other}] (REPORTED)",
            "- An invented figure of 999 GW has no source [S99999] (VERIFIED)",
            "## Conflicts",
            f"- Sources differ on 2030 capacity [S{cite}][S{other}]",
            "## Open questions",
            "- Grid connection timelines remain unclear",
            "## Discovered",
            "- Role of on-site generation",
        ])

    def gap(self, call):
        if not self.gap_followups:
            return ai(json.dumps({"verdict": "complete", "follow_ups": []}))
        return ai(json.dumps({"verdict": "gaps", "follow_ups": [
            {"question": "What is installed capacity today?", "queries": ["dup"], "why": "duplicate"},
            {"question": "How fast are interconnection approvals in Europe and Asia?",
             "queries": ["interconnection approvals europe"], "why": "missing region"}]}))

    # ------------------------------------------------------------ writing
    def writer(self, call):
        context = call["messages"][2][1]
        sids = re.findall(r"^\[S(\d+)\]", context.split("SOURCE INDEX", 1)[-1], re.M) or ["1"]
        task = call["messages"][-1][1]
        titles = [line[3:] for line in task.split("Rules:")[0].splitlines() if line.startswith("## ")]
        with self._lock:
            first = not self.first_writer_seen
            self.first_writer_seen = True
        if first and self.writer_delay_first:
            time.sleep(self.writer_delay_first)
        blocks = []
        for title in titles:
            seed = int(hashlib.sha1(title.encode("utf-8")).hexdigest(), 16)
            first, second = (f"[S{sids[(seed + k) % len(sids)]}]" for k in (0, 1))
            paras = [self.paragraph(title, seed + k, cite) for k, cite in enumerate((first, second))]
            body = "\n\n".join(paras)
            if "Scenario" in title or "情景" in title:
                if self.zh():
                    body += "\n\n基准情景（45%）仍是最可能的路径。\n\n- **尾部风险（5%）**：极端情形。"
                else:
                    body += ("\n\nThe Base case (45% probability) remains the most likely path."
                             "\n\n- **Tail risk (5% probability):** an extreme outcome.")
            blocks.append(f"## {title}\n\n{body}")
        if self.reverse_writer:
            blocks.reverse()
        return ai("\n\n".join(blocks), out=1500)

    def paragraph(self, title: str, seed: int, cite: str) -> str:
        """A section-specific paragraph (cross-section dedup must not remove it)."""
        words = ["capacity", "queues", "capex", "tariffs", "cooling", "permits", "turbines", "leases",
                 "substations", "contracts", "financing", "latency"]
        picks = [words[(seed >> (4 * k)) % len(words)] for k in range(6)]
        if self.zh():
            return (f"{title}：{picks[0]}与{picks[1]}的证据显示，装机容量在2023年达到176吉瓦{cite}。"
                    f"围绕{picks[2]}、{picks[3]}和{picks[4]}的分析表明，第{seed % 97}号观察点的约束"
                    f"将决定扩张节奏，{picks[5]}是本节最重要的先行信号{cite}。")
        return (f"On {title.lower()}, evidence about {picks[0]} and {picks[1]} shows installed capacity reached "
                f"176 GW in 2023 {cite}. Analysis of {picks[2]}, {picks[3]} and {picks[4]} at observation "
                f"point {seed % 997} indicates how the pace of expansion responds, and {picks[5]} is the "
                f"leading signal this section tracks through 2027 {cite}.")

    def exec_summary(self, call):
        heading = "执行摘要" if self.zh() else "Executive Summary"
        leads = call["messages"][2][1]
        sid = (re.findall(r"\[S(\d+)\]", leads) or ["1"])[0]
        if self.zh():
            body = f"预测期内基准情景（50%）最可能，装机容量2023年达176吉瓦[S{sid}]。" * 6
        else:
            body = (f"The Base case (50% probability) is most likely; capacity reached 176 GW in 2023 [S{sid}]. "
                    "Accelerated build-out (30%) and Stalled expansion (20%) frame the tails. ") * 3
        return ai(f"## {heading}\n\n{body}")

    def critique(self, call):
        return ai(json.dumps({"issues": [{"section_title": self.SECTIONS[1], "issue": "Too few numbers",
                                          "fix": "Add the 2023 baseline"}]}))

    # ------------------------------------------------------------ extraction
    def actors(self, call):
        return ai(json.dumps({
            "central_question": "Will capacity exceed 250 GW by 2027?", "as_of_date": "2026-09-27",
            "situation_brief": {"current_situation": "Capacity is 176 GW.", "context": "AI demand",
                                "dynamics": "Grid queues", "fault_lines": ["grid"], "catalysts": ["capex"]},
            "actors": [
                {"name": "National energy agency", "type": "Government", "role": "statistics", "influence": "high",
                 "simulation_tier": 1, "role_class": "arbiter",
                 "intelligence": {"schema_version": "actor-intelligence/v1"}},
                {"name": "Hyperscaler A", "type": "Organization", "role": "buyer", "influence": "high",
                 "simulation_tier": "1", "role_class": "principal", "aliases": ["HSA"],
                 "incentives": [{"driver": "AI demand", "gains_if": "fast build", "loses_if": "delays",
                                 "intensity": "high"}]},
                {"name": "Grid operator", "type": "Organization", "role": "connects load", "influence": "medium"},
            ],
            "relationships": [{"source": "HSA", "target": "Grid operator", "type": "depends_on",
                               "valence": "transactional", "polarity": 0.2, "strength": 2},
                              {"source": "Nobody", "target": "Grid operator", "type": "OPPOSES"}],
            "hot_topics": ["grid queues"],
            "actor_intelligence_contract": {"schema_version": "actor-intelligence/v1"},
        }))

    def facts(self, call):
        return ai(json.dumps({
            "key_events": [{"date": "2023-12-31", "event": "Capacity reached 176 GW"}],
            "quantitative_facts": [{"metric": "Installed capacity", "value": "176", "unit": "GW",
                                    "as_of_date": "2023-12-31", "value_type": "actual", "source_ref": "S1"}],
            "contested_claims": [{"claim": "2030 capacity", "positions": [{"stance": "250 GW", "sources": ["S1"]}],
                                  "status": "contested", "why_they_differ": "scope"}],
        }))


def make_args(depth: str = "standard", **extra):
    return types.SimpleNamespace(model="fake-model", depth=depth, target_language=None, no_actors=False,
                                 **extra)


def run_engine(tmp_path: Path, bridge, world, *, question: str = "Will global data-centre capacity exceed "
               "250 GW by the end of 2027?", depth: str = "standard", model: ScriptedModel | None = None,
               args=None, out_dir: Path | None = None, fetch=None):
    out_dir = out_dir or (tmp_path / "out")
    out_dir.mkdir(parents=True, exist_ok=True)
    model = model or ScriptedModel(world)
    plog = FakePlog()
    meta = {"status": "running", "question": question, "research_engine": "v3"}

    def write_meta():
        (out_dir / "meta.json").write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")

    def gateway_factory(args, plog_arg, bridge_arg, preset):
        return rg.ModelGateway(model, plog_arg, max_concurrency=preset.workers, budget_units=preset.budget_units,
                               reserve_share=lr.RESERVE_SHARE, sleep=lambda seconds: None)

    def tools_factory(ledger, pages_dir, bridge_arg, plog_arg, limits):
        return rg.ResearchTools(ledger, pages_dir, search_fn=fake_search, fetch_fn=fetch or page_text,
                                bridge=bridge_arg, plog=plog_arg, limits=limits)

    rc = lr.run(question, out_dir, args or make_args(depth), meta, plog, write_meta, bridge=bridge,
                gateway_factory=gateway_factory, tools_factory=tools_factory)
    return rc, meta, plog, model, out_dir


def calls_of(model: ScriptedModel, role: str) -> list[dict]:
    return [c for c in model.calls if role_of(c) == role]


# =============================================================== prompts & presets

def test_every_prompt_template_renders_without_format_errors():
    """v2 died on str.format KeyErrors from literal JSON braces; every template
    must substitute cleanly and keep its JSON examples intact."""
    assert lr._PROMPT_TEMPLATES, "no templates registered"
    for name, template in lr._PROMPT_TEMPLATES.items():
        assert template.is_valid(), name
        identifiers = template.get_identifiers()
        rendered = lr._render(template, **{ident: f"<{ident}>" for ident in identifiers})
        assert "$" not in rendered, name
        for ident in identifiers:
            assert f"<{ident}>" in rendered, (name, ident)
    plan = lr._render(lr._T_PLAN, min_kiqs=4, max_kiqs=7, min_sections=8, max_sections=12,
                      language="English", actor_cap=20)
    assert '{"kiqs": [{"question": "...", "queries": ["...", "..."], "kind": "general"}],' in plan
    assert '{"issues": []}' in lr._render(lr._T_CRITIQUE, max_issues=5, language="English")
    with pytest.raises(KeyError):
        lr._render(lr._T_SCOPE, language="English")  # a missing field is a caller bug, not silent


def test_engine_core_is_static_long_and_question_free():
    core = lr.ENGINE_CORE
    assert len(core) / 4 >= 1200  # >= 1,200 tokens of shared, cacheable system prompt
    assert "$" not in core and "{" not in core
    assert not re.search(r"\b20\d\d-\d\d-\d\d\b", core)  # no dates / volatile text
    for rule in ("VERIFIED", "REPORTED", "[S12]", "DISCOVERED", "ONE JSON object", "canonical scenario frame"):
        assert rule in core


def test_resolve_preset_depth_table_env_overrides_and_caps():
    deep = lr.resolve_preset("deep", {})
    assert (deep.max_kiqs, deep.agent_max_steps, deep.gap_rounds, deep.critique) == (10, 9, 2, True)
    quick = lr.resolve_preset("quick", {})
    assert (quick.max_kiqs, quick.sections_min, quick.sections_max, quick.digest_cap) == (4, 6, 8, 30_000)
    env = {"RESEARCH_LINEAR_MAX_KIQS": "5", "RESEARCH_LINEAR_CRITIQUE": "yes", "RESEARCH_LINEAR_WORKERS": "8",
           "RESEARCH_MODEL_CONCURRENCY_GLOBAL": "3", "DEERFLOW_RESEARCH_TIMEOUT": "1000",
           "RESEARCH_LINEAR_GAP_ROUNDS": "banana", "RESEARCH_LINEAR_SECTIONS_MIN": "40"}
    preset = lr.resolve_preset("standard", env)
    assert preset.max_kiqs == 5 and preset.critique is True
    assert preset.workers == 3                       # capped by the provider envelope
    assert preset.time_budget_s == pytest.approx(850.0)  # 0.85 x watchdog budget
    assert preset.gap_rounds == 1                    # invalid override keeps the preset value
    assert preset.sections_min == preset.sections_max == 12  # clamped, then min <= max
    assert any("RESEARCH_LINEAR_GAP_ROUNDS" in note for note in preset.notes)
    assert lr.resolve_preset("bogus", {}).depth == "standard"
    assert lr.resolve_preset("quick", {"RESEARCH_LINEAR_CRITIQUE": "off"}).critique is False


@pytest.mark.parametrize("question,target,expected", [
    ("Will capacity exceed 250 GW by 2027?", None, "English"),
    ("2030 年前全球数据中心市场会如何发展？", None, "Chinese"),
    ("Which firms lead the 数据中心 market by 2030 according to analysts?", None, "English"),
    ("Anything", "zh-CN", "Chinese"),
    ("任何问题", "english", "English"),
    ("Anything", "Japanese", "Japanese"),
])
def test_detect_language(question, target, expected):
    assert lr.detect_language(question, target) == expected


# =============================================================== plan normalisation

def test_build_plan_normalizes_ids_sections_and_scenarios():
    preset = lr.resolve_preset("standard", {})
    raw = {
        "kiqs": [{"id": "X9", "question": "Q one?", "queries": ["a b", "c d", "e f", "g h"], "kind": "data"},
                 {"question": "Q one?"},  # duplicate → same id
                 {"question": "Q two?", "kind": "weird"},
                 "Q three as a string?"],
        "sections": [{"title": "1. Executive Summary", "kiqs": [1]}, {"title": "Background", "kiqs": [1, 2, 3]},
                     {"title": "Drivers", "kiqs": ["K4"]}, {"title": "References"}, {"title": "Sources"}],
        "scenarios": [{"name": "Base (50% probability)", "weight": 0.5}, {"name": "Upside", "weight": 0.3},
                      {"name": "Downside", "weight": 0.2}],
        "actors": [{"name": "Agency", "type": "regulator"}, {"name": "agency"}],
    }
    plan = lr.build_plan("Q?", "English", "2026-09-27", preset, 20, {"scout_queries": ["q"]}, raw)
    assert [k.id for k in plan.kiqs] == ["K1", "K2", "K3"]
    assert plan.kiqs[0].queries == ["a b", "c d", "e f"] and plan.kiqs[1].kind == "general"
    titles = [s.title for s in plan.sections]
    assert "Executive Summary" not in titles and "References" not in titles and "Sources" not in titles
    # model order is kept; the missing scenario section goes before the last analysis
    # section and default fillers (never near-duplicates of existing titles) before it
    assert titles[0] == "Background" and titles[-1] == "Drivers" and titles[-2] == "Scenarios and Probabilities"
    assert "Background and Current State" not in titles
    assert plan.sections[0].kiq_ids == ["K1", "K2"]
    assert preset.sections_min <= len(plan.sections) <= preset.sections_max
    assert sum(s.is_scenario for s in plan.sections) == 1
    assert [s.index for s in plan.sections] == list(range(1, len(plan.sections) + 1))
    assert [(s.name, s.weight) for s in plan.scenarios] == [("Base", 50), ("Upside", 30), ("Downside", 20)]
    assert plan.actors == [{"name": "Agency", "type": "Government", "why": ""}]
    assert "scenarios" not in plan.fallback


def test_fallback_plan_is_complete_and_localized():
    preset = lr.resolve_preset("deep", {})
    plan = lr.build_plan("2030 年前全球数据中心市场会如何发展？", "Chinese", "2026-09-27", preset, 20, None, None)
    assert {"scope", "plan", "kiqs", "sections", "scenarios"} <= set(plan.fallback)
    assert len(plan.kiqs) == 6 and plan.kiqs[0].question.startswith("现状与基线数据")
    assert all(k.queries and len(k.queries[0]) <= 300 for k in plan.kiqs)
    assert preset.sections_min <= len(plan.sections) <= preset.sections_max
    assert [s.name for s in plan.scenarios] == ["基准情景", "上行情景", "下行情景"]
    assert sum(s.weight for s in plan.scenarios) == 100
    brief = lr.render_brief(plan)
    assert brief.startswith("RUN BRIEF") and "K6:" in brief and "基准情景 — 50%" in brief


@pytest.mark.parametrize("raw,expected", [
    ([{"name": "A", "weight": "25%"}, {"name": "B", "weight": "75%"}], [25, 75]),
    ([{"name": "A", "weight": 0.2}, {"name": "B", "weight": 0.3}, {"name": "C", "weight": 0.2}], [29, 43, 28]),
    ([{"name": "A", "weight": 60}, {"name": "B", "weight": 30}, {"name": "C", "weight": 0}], [67, 33]),
    ([{"name": f"S{i}", "weight": 10 + i} for i in range(7)], [14, 15, 16, 17, 18, 20]),
    ([{"name": "A", "weight": 99.6}, {"name": "B", "weight": 0.2}, {"name": "C", "weight": 0.2}], [98, 1, 1]),
])
def test_normalize_scenarios_weights_sum_to_100(raw, expected):
    frame, used_default = lr.normalize_scenarios(raw, "English")
    assert not used_default
    assert sorted(s.weight for s in frame) == sorted(expected) and sum(s.weight for s in frame) == 100
    assert all(s.weight >= 1 for s in frame)


def test_normalize_scenarios_falls_back_below_two():
    frame, used_default = lr.normalize_scenarios([{"name": "Only", "weight": 100}], "English")
    assert used_default and [s.weight for s in frame] == [50, 25, 25]


# =============================================================== scenario block

@pytest.mark.parametrize("language,names,weights", [
    ("English", ["Base case", "Accelerated build-out", "Stalled expansion"], [50, 35, 15]),
    ("Chinese", ["基准情景", "加速扩张", "扩张停滞"], [50, 35, 15]),
    ("Chinese", ["情景甲", "情景乙", "情景丙", "情景丁"], [10, 19, 60, 11]),
    ("English", ["Soft landing", "Hard landing"], [99, 1]),
])
def test_scenario_block_parses_with_real_backend_parser(language, names, weights):
    frame = [lr.Scenario(n, w, f"thesis {i} with 30% growth")
             for i, (n, w) in enumerate(zip(names, weights, strict=True))]
    section = {"index": 1, "title": lr._text(language, "scenario_title"), "is_scenario": True,
               "body": "Writer analysis follows. 本节分析各情景。"}
    report = lr.render_report("Q?", language, "Summary text.", [section], frame)
    parsed = forecast_inputs_from_report_markdown(report)
    assert 2 <= len(parsed["scenarios"]) <= 6
    assert [row["name"] for row in parsed["scenarios"]] == names
    assert [round(row["probability"] * 100) for row in parsed["scenarios"]] == weights
    assert abs(sum(row["probability"] for row in parsed["scenarios"]) - 1.0) < 1e-9
    assert lr.scenarios_match_frame(lr.parse_report_scenarios(report), frame)


def test_chinese_probability_prefix_parses_identically_in_backend_and_mirror():
    """「概率 15%」 was once read as probability 1.0; both parsers now read 0.15."""
    block = "## 情景与概率\n\n- **甲（概率 50%）**：x\n- **乙（概率 35%）**：x\n- **丙（概率 15%）**：x\n"
    expected = [{"name": "甲", "probability": 0.5}, {"name": "乙", "probability": 0.35},
                {"name": "丙", "probability": 0.15}]
    assert forecast_inputs_from_report_markdown(block)["scenarios"] == expected
    assert [(s["name"], s["probability"]) for s in lr.parse_report_scenarios(block)] == [
        (s["name"], s["probability"]) for s in expected]


def test_mirror_parser_agrees_with_backend_on_tricky_reports():
    reports = [
        "## Scenario Drivers\n\n- **Energy (30%)**: x\n- **Chips (70%)**: y\n\n## Scenarios\n\n- **A (50%)**: z\n",
        "## Scenarios (mutually exclusive, summing to 100%)\n\n### A (60% probability)\n\n### B (40% probability)\n",
        "## 情景\n\n- **甲**（35%）：x\n- **乙**（65%）：y\n",
        "## Scenarios\n\n- **A (30–40%)**: x\n- **B (60–70%)**: y\n",
        "## Outlook\n\n- **A (50%)**: x\n- **B (50%)**: y\n",
    ]
    for report in reports:
        backend = forecast_inputs_from_report_markdown(report).get("scenarios", [])
        mirror = lr.parse_report_scenarios(report)
        assert [r["name"] for r in mirror] == [r["name"] for r in backend], report
        expected = [po_mid(r) for r in backend]
        assert [round(r["probability"], 6) for r in mirror] == expected, report


def po_mid(row: dict) -> float:
    from app.utils.actors import _parse_probability_value
    return round(_parse_probability_value(row.get("probability_band") or row.get("probability")), 6)


def test_weight_fix_and_neutralize_are_deterministic():
    frame = [lr.Scenario("Base case", 50, ""), lr.Scenario("Upside", 30, ""), lr.Scenario("Downside", 20, "")]
    body = "The Base case (45% probability) and Upside（概率 30%） hold; Downside (25%) is unlikely."
    fixed, fixes = lr.fix_scenario_weights(body, frame)
    assert "Base case (50% probability)" in fixed and "Downside (20%)" in fixed and "Upside（概率 30%）" in fixed
    assert {(f["name"], f["from"], f["to"]) for f in fixes} == {("Base case", "45", "50"), ("Downside", "25", "20")}
    neutral, changed = lr.neutralize_scenario_markup(
        "- **Tail (5%)**: x\n### Wild card (10% probability)\n- **Plain**: y")
    assert changed == 2 and "**Tail" not in neutral and "### Wild card" in neutral and "10%" not in neutral
    assert "- **Plain**: y" in neutral


# =============================================================== notes & verification

class _Ledger:
    def __init__(self, rows: dict[int, dict]) -> None:
        self.rows = rows

    def get(self, sid):
        return self.rows.get(int(sid))


def test_postprocess_notes_verification_rules():
    ledger = _Ledger({1: {"sid": 1, "fetched": True}, 2: {"sid": 2, "fetched": False}})
    pages = {1: lr.page_number_set("Capacity was 1,234.50 MW in 2023; growth 12%.")}
    notes = ("## Findings\n"
             "- Capacity was 1234.5 MW in 2023 [S1] (VERIFIED)\n"
             "- Capacity will be 2,000 MW in 2030 [S1] (VERIFIED)\n"
             "- Growth of 12% [S2] (VERIFIED)\n"
             "- Rumoured 77% share [S1, S9] (reported)\n"
             "  continued on the next line\n"
             "- As of 2024-06-30 growth held at 12% [S1] (VERIFIED)\n"
             "## Conflicts\n- A vs B [S1][S2]\n## Open questions\n- Unknown [S8]\n## Discovered\n- Lead\n")
    cleaned, parts = lr.postprocess_notes("K1", notes, ledger.get, pages.get)
    facts = parts["facts"]
    assert [f["tag"] for f in facts] == ["VERIFIED", "UNVERIFIED", "REPORTED", "REPORTED", "VERIFIED"]
    assert facts[0]["verified_numbers"] is True
    assert facts[1]["missing_numbers"] == ["2000", "2030"]
    assert facts[2]["verification"] == "no_fetched_source"
    assert facts[3]["sids"] == [1] and "[S9]" not in facts[3]["text"] and "next line" in facts[3]["text"]
    assert facts[4]["verified_numbers"] is True  # ISO dates are not number tokens
    assert parts["conflicts"] == ["A vs B [S1][S2]"] and parts["open_questions"] == ["Unknown"]
    assert parts["discovered"] == ["Lead"]
    assert "[S9]" not in cleaned and "[S8]" not in cleaned and "[S1][S9]" not in cleaned


def test_postprocess_notes_without_headings_and_chinese_tags():
    ledger = _Ledger({3: {"sid": 3, "fetched": True}})
    notes = "Summary line without bullets but long enough to count as a finding [S3]（已核实）"
    _, parts = lr.postprocess_notes("K2", notes, ledger.get, lambda sid: frozenset())
    assert len(parts["facts"]) == 1 and parts["facts"][0]["tag"] == "VERIFIED"
    assert parts["facts"][0]["sids"] == [3]


# =============================================================== digest & writer parsing

def test_build_digest_natural_order_priorities_and_source_index():
    ledger = _Ledger({1: {"title": "T1", "domain": "a.org", "tier": "S1", "fetched": True},
                      2: {"title": "T2", "domain": "b.org", "tier": "S3", "fetched": False}})
    records = [
        {"id": "K10", "question": "ten", "facts": [{"text": "late [S2]", "tag": "REPORTED"}]},
        {"id": "G1F1", "question": "follow", "facts": []},
        {"id": "K2", "question": "two", "facts": [
            {"text": "reported fact [S2]", "tag": "REPORTED"}, {"text": "verified fact [S1]", "tag": "VERIFIED"}],
         "open_questions": ["why " * 1000]},
    ]
    text, dropped = lr.build_digest(records, ledger.get, 5000, "English")
    order = [line.split(" — ")[0] for line in text.splitlines() if line.startswith("### ")]
    assert order == ["### K2", "### K10", "### G1F1"]
    k2 = text.split("### K2")[1].split("### K10")[0]
    assert k2.index("verified fact") < k2.index("reported fact")
    assert dropped == 1 and "why why" not in text  # the long open question went first
    assert "[S1] T1 — a.org (tier 1, fetched)" in text and "[S2] T2 — b.org (tier 3, snippet)" in text


def test_split_writer_output_matches_titles_and_demotes_unexpected():
    text = ("Preamble narration.\n## 2. Demand drivers\nBody B\n### Sub\nmore\n## Unexpected aside\nAside body\n"
            "## Market Baseline\nBody A\n## References\n- [S1] junk\n")
    parsed = lr.split_writer_output(text, ["Market Baseline", "Demand Drivers"])
    assert parsed["Market Baseline"] == "Body A"
    drivers = parsed["Demand Drivers"]
    assert drivers.startswith("Body B") and "### Unexpected aside\n\nAside body" in drivers
    assert "junk" not in json.dumps(parsed)
    assert lr.split_writer_output("Just prose for one section.", ["Only"]) == {"Only": "Just prose for one section."}


def test_renumber_citations_positional_and_references():
    text = "A [S7] b [S3][S7] c [S99] d [S3]."
    out, order = lr.renumber_citations(text, lambda sid: sid in (3, 7))
    assert order == [7, 3] and out == "A [S1] b [S2][S1] c d [S2]."
    refs = lr.render_references(order, {7: {"title": "Seven", "url": "https://s7.org/x", "tier": "S2",
                                            "fetched": True},
                                        3: {"title": "Three", "url": "https://s3.org/y", "tier": "S3",
                                            "fetched": False}}.get)
    assert refs.splitlines()[2:] == ["- [S1] Seven — https://s7.org/x (tier 2; fetched)",
                                     "- [S2] Three — https://s3.org/y (tier 3; search snippet)"]


def test_remove_error_markers_is_anchored():
    body = ("Margin of error: 2%.\nTraceback (most recent call last):\n  File \"x.py\", line 1\nValueError: boom\n"
            '{"error": "research_budget_exhausted"}\nError code: 503 - unavailable\nKept line.')
    cleaned, removed = lr.remove_error_markers(body)
    assert removed == 3 and cleaned == "Margin of error: 2%.\nKept line."


# =============================================================== end-to-end

def _references(report: str) -> list[tuple[int, str]]:
    refs = report.split("\n## References\n", 1)[1]
    return [(int(m.group(1)), m.group(2)) for m in re.finditer(r"^- \[S(\d+)\] .*? — (https?://\S+) \(", refs, re.M)]


def _progress(plog: FakePlog) -> list[int]:
    estimator = ResearchProgressEstimator()
    return [estimator.observe(f"2026-09-27T00:00:00+00:00 [{kind}] {message}") for kind, message in plog.lines]


def test_e2e_happy_path_writes_every_artifact(tmp_path, bridge):
    env_before = dict(os.environ)
    rc, meta, plog, model, out = run_engine(tmp_path, bridge, World())
    assert rc == 0, meta.get("error")
    assert dict(os.environ) == env_before          # no env mutation
    assert plog.closed is False                    # main owns the progress log
    for name in ("research_report.md", "sources.json", "actors.json", "timeline.json", "quantitative.json",
                 "contested.json", "meta.json"):
        assert (out / name).is_file(), name
    report = (out / "research_report.md").read_text(encoding="utf-8")
    sources = json.loads((out / "sources.json").read_text(encoding="utf-8"))

    # outline order, one canonical scenario block parsed by the REAL backend parser
    headings = re.findall(r"^## (.+)$", report, re.M)
    assert headings[0] == "Executive Summary" and headings[-1] == "References"
    assert [h for h in headings if h in World.SECTIONS] == World.SECTIONS  # model order kept
    assert len(headings) == 1 + 8 + 1   # standard preset: 8 body sections (2 default fillers)
    parsed = forecast_inputs_from_report_markdown(report)
    assert [(r["name"], r["probability"]) for r in parsed["scenarios"]] == [
        ("Base case", 0.5), ("Accelerated build-out", 0.3), ("Stalled expansion", 0.2)]
    assert "Base case (45% probability)" not in report      # restatement fixed to the frame
    assert "- **Tail risk" not in report                      # conflicting markup neutralized

    # References == cited-only positional renumbering == sources.json order
    refs = _references(report)
    assert [n for n, _ in refs] == list(range(1, len(sources) + 1)) and sources
    assert [url for _, url in refs] == [row["url"] for row in sources]
    body = report.split("\n## References\n", 1)[0]
    first_seen = list(dict.fromkeys(int(n) for n in re.findall(r"\[S(\d+)\]", body)))
    assert first_seen == list(range(1, len(sources) + 1))
    assert all(row["source_origin"] in ("fetched", "cited") and row["source_id"].startswith("src_")
               for row in sources)
    fetched_rows = [row for row in sources if row["source_origin"] == "fetched"]
    assert fetched_rows and all(row["reachable"] is True and row["content_sha256"] and row["excerpt"]
                                for row in fetched_rows)

    # structured artifacts: unsealed actor plane with forecast inputs
    actors = json.loads((out / "actors.json").read_text(encoding="utf-8"))
    dumped = json.dumps(actors)
    assert "intelligence" not in dumped and "actor_intelligence_contract" not in actors and "sources" not in actors
    assert [a["name"] for a in actors["actors"]] == ["National energy agency", "Hyperscaler A", "Grid operator"]
    assert actors["actors"][1]["simulation_tier"] == 1
    assert actors["relationships"] == [{"source": "Hyperscaler A", "target": "Grid operator", "type": "DEPENDS_ON",
                                        "valence": "transactional", "polarity": 0.2, "strength": 1.0}]
    fi = actors["forecast_inputs"]
    assert [(s["name"], s["probability"]) for s in fi["scenarios"]] == [
        ("Base case", 0.5), ("Accelerated build-out", 0.3), ("Stalled expansion", 0.2)]
    from app.utils.actors import valid_scenario_distribution
    assert valid_scenario_distribution(fi)
    quant = json.loads((out / "quantitative.json").read_text(encoding="utf-8"))
    assert quant[0]["value_num"] == 176.0 and "staleness_days" in quant[0]
    assert quant[0]["source_url"] == sources[0]["url"]
    assert json.loads((out / "timeline.json").read_text(encoding="utf-8"))[0]["event"]
    assert json.loads((out / "contested.json").read_text(encoding="utf-8"))[0]["claim"] == "2030 capacity"
    assert bridge._v3_test_calls["markets"] and bridge._v3_test_calls["charts"]

    # meta
    disk_meta = json.loads((out / "meta.json").read_text(encoding="utf-8"))
    assert disk_meta["status"] == "completed" and disk_meta["research_engine"] == "v3"
    assert disk_meta["engine_version"] == lr.ENGINE_VERSION and disk_meta["language"] == "English"
    assert disk_meta["research_qa"]["passed"] is True, disk_meta["research_qa"]
    usage = disk_meta["usage"]["total"]
    assert usage["calls"] == len(model.calls) and usage["cache_hit_ratio"] > 0
    assert "gather" in disk_meta["usage"]["phases"] and "synthesize" in disk_meta["usage"]["phases"]
    assert isinstance(disk_meta["research_quality"]["score"], float)
    assert set(disk_meta["source_tiers"]) == {"s1_count", "s2_count", "s3_count", "s4_count", "s_unknown"}
    assert disk_meta["kiqs"]["completed"] == 4 and disk_meta["kiqs"]["verified"] == 4
    assert all(disk_meta["phases"][p]["status"] == "done" for p in lr.PHASES)
    assert disk_meta["report_chars"] == len(report) and disk_meta["sources_count"] == len(sources)

    # one orchestrator-parseable [usage] line per model response, with cache reads
    usage_lines = plog.of("usage")
    assert len(usage_lines) == len(model.calls)
    assert all(po._parse_usage_line(line) is not None for line in usage_lines)
    assert sum(po._parse_usage_cached_tokens(line) for line in usage_lines) == usage["cached"] > 0

    # V3_SPEC §3.3 progress vocabulary, monotonic and ending at 99
    log = plog.text()
    for needle in ("[stage] research:v3:plan start", "[ok] research:v3:plan done (4 KIQs, 8 sections)",
                   "[stage] research:v3:gather start (4 KIQs, workers=4)", "[ok] research:v3:gather K1 facts=",
                   "[stage] research:v3:gap round 1", "[stage] research:v3:synthesize start (",
                   "[ok] research:v3:synthesize done", "[stage] research:v3:qa start",
                   "[ok] research:v3:qa passed=True",
                   "[stage] research:v3:finalize start", "[ok] wrote research_report.md", "[ok] wrote sources.json",
                   "[ok] wrote actors.json", "[ok] wrote timeline.json", "[ok] wrote quantitative.json",
                   "[done] research complete (v3:", "[tool] web_search", "[result] web_fetch"):
        assert needle in log, needle
    progress = _progress(plog)
    assert progress == sorted(progress) and progress[-1] == 99


def test_e2e_prefix_cache_invariants(tmp_path, bridge, monkeypatch):
    monkeypatch.setenv("RESEARCH_LINEAR_AGENT_MAX_STEPS", "2")  # force the STOP → final-notes path
    rc, meta, plog, model, _ = run_engine(tmp_path, bridge, World())
    assert rc == 0, meta.get("error")
    assert all(call["messages"][0] == ("system", lr.ENGINE_CORE) for call in model.calls)

    agent = [c for c in model.calls if c["tools"] is not None]
    assert agent and all(c["tools"] is rg.AGENT_TOOLS_SCHEMA for c in agent)  # incl. prime and final calls
    assert len({tuple(c["messages"][:2]) for c in agent}) == 1               # [system][brief] shared
    finals = [c for c in agent if c["messages"][-1][1].startswith("STOP")]
    assert finals and all(c["tools"] is rg.AGENT_TOOLS_SCHEMA for c in finals)
    conversations: dict[str, list] = {}
    for call in agent:
        if call["messages"][2][1].startswith("KIQ INVESTIGATION TASK"):
            conversations.setdefault(call["messages"][2][1], []).append(call["messages"])
    assert len(conversations) == 4
    for steps in conversations.values():                                      # append-only conversations
        steps.sort(key=len)
        for earlier, later in zip(steps, steps[1:], strict=False):
            assert later[:len(earlier)] == earlier
    tasks = [c["messages"][2][1] for c in agent if len(c["messages"]) == 3]
    assert len(set(tasks)) == len(tasks)   # the only per-KIQ text is the last (task) message

    evidence_block = "BEGIN UNTRUSTED EVIDENCE DATA — research evidence"
    writers = [c for c in model.calls if role_of(c) == "SECTION WRITING TASK" or
               (role_of(c) == "prime" and c["messages"][2][1].startswith(evidence_block))]
    assert len(writers) >= 3 and len({tuple(c["messages"][:3]) for c in writers}) == 1
    assert all(len(c["messages"]) == 4 for c in writers)
    extract = [c for c in model.calls if role_of(c) in ("ACTOR EXTRACTION TASK", "FACT EXTRACTION TASK")
               or (role_of(c) == "prime" and "research report" in c["messages"][2][1][:80])]
    assert len(extract) == 3 and len({tuple(c["messages"][:3]) for c in extract}) == 1
    primes = calls_of(model, "prime")
    assert {c["kwargs"]["max_tokens"] for c in primes} == {rg.PRIME_MAX_TOKENS} and len(primes) == 3
    # every prime precedes the fan-out it warms
    order = [role_of(c) for c in model.calls]
    assert order.index("prime") < order.index("agent")


def test_e2e_section_order_survives_out_of_order_completion(tmp_path, bridge):
    world = World(writer_delay_first=0.3, reverse_writer=True)
    rc, meta, _, model, out = run_engine(tmp_path, bridge, world)
    assert rc == 0, meta.get("error")
    report = (out / "research_report.md").read_text(encoding="utf-8")
    plan = json.loads((out / "v3" / "plan.json").read_text(encoding="utf-8"))
    expected = ["Executive Summary"] + [s["title"] for s in plan["sections"]] + ["References"]
    assert re.findall(r"^## (.+)$", report, re.M) == expected
    for section in plan["sections"]:
        assert (out / "v3" / "sections" / f"{section['index']:02d}.md").is_file()


def test_e2e_chinese_report(tmp_path, bridge):
    rc, meta, _, _, out = run_engine(tmp_path, bridge, World(language="Chinese"), depth="quick",
                                     question="2027 年底全球数据中心装机容量会超过 250 吉瓦吗？")
    assert rc == 0, meta.get("error")
    report = (out / "research_report.md").read_text(encoding="utf-8")
    assert "## 执行摘要" in report and "### 情景概率分布" in report and "## References" in report
    parsed = forecast_inputs_from_report_markdown(report)
    assert [(r["name"], r["probability"]) for r in parsed["scenarios"]] == [
        ("基准情景", 0.5), ("加速扩张", 0.3), ("扩张停滞", 0.2)]
    qa = meta["research_qa"]
    assert qa["passed"] is True and any(c["name"] == "language" and c["passed"] for c in qa["checks"])


# =============================================================== resume & robustness

def test_resume_skips_done_phases_and_archives_a_different_question(tmp_path, bridge):
    out = tmp_path / "out"
    rc, _, _, _, _ = run_engine(tmp_path, bridge, World(), out_dir=out)
    assert rc == 0
    first_report = (out / "research_report.md").read_text(encoding="utf-8")

    # same identity: every phase is reused, extraction is memoized → zero model calls
    silent = ScriptedModel(lambda call: pytest.fail(f"unexpected model call: {role_of(call)}"))
    rc, meta, plog, model, _ = run_engine(tmp_path, bridge, World(), out_dir=out, model=silent)
    assert rc == 0 and model.calls == [] and meta["status"] == "completed"
    assert (out / "research_report.md").read_text(encoding="utf-8") == first_report
    for phase in ("plan", "gather", "gap", "synthesize", "qa"):
        assert f"[resume] research:v3:{phase} reused" in plog.text()

    # another question in the same out_dir: the old work dir is archived, never reused
    rc, meta, plog, model, _ = run_engine(tmp_path, bridge, World(), out_dir=out,
                                          question="Will EU data-centre capacity double by 2030?")
    assert rc == 0 and calls_of(model, "PLANNING TASK")
    stale = [p for p in out.iterdir() if p.name.startswith("v3.stale-")]
    assert len(stale) == 1
    old_state = json.loads((stale[0] / "state.json").read_text(encoding="utf-8"))
    new_state = json.loads((out / "v3" / "state.json").read_text(encoding="utf-8"))
    assert old_state["identity"]["question_sha256"] != new_state["identity"]["question_sha256"]
    assert "archived it to v3.stale-" in plog.text()


def test_provider_failure_at_synthesis_exits_2_then_resumes_without_repaying(tmp_path, bridge):
    out = tmp_path / "out"

    def quota_on_writing(call, role):
        if role in ("SECTION WRITING TASK", "EXECUTIVE SUMMARY TASK"):
            return Exception("Error code: 429 - {'error': {'code': '1113', 'message': '余额不足'}}")
        return None

    rc, meta, plog, _, _ = run_engine(tmp_path, bridge, World(fail=quota_on_writing), out_dir=out)
    assert rc == 2 and plog.closed is False
    disk = json.loads((out / "meta.json").read_text(encoding="utf-8"))
    assert disk["status"] == "failed" and disk["error"].startswith("provider_unavailable: synthesis failed")
    assert disk["phases"]["plan"]["status"] == "done" and disk["phases"]["gather"]["status"] == "done"
    assert disk["phases"]["synthesize"]["status"] == "failed"
    assert not (out / "research_report.md").exists()
    assert all((out / "v3" / "kiq" / f"K{i}.json").is_file() for i in range(1, 5))

    rc, meta, plog, model, _ = run_engine(tmp_path, bridge, World(), out_dir=out)
    assert rc == 0 and meta["status"] == "completed"
    roles = {role_of(c) for c in model.calls}
    assert not roles & {"SCOPE TASK", "PLANNING TASK", "agent", "GAP REVIEW TASK"}
    assert "SECTION WRITING TASK" in roles and (out / "research_report.md").is_file()


def test_quota_during_gather_after_half_the_kiqs_still_reaches_synthesis(tmp_path, bridge, monkeypatch):
    # Fewer than half of the planned KIQs researched is a resumable exit 2
    # (review round 3, C28): here K1 and K2 of 4 finished before the outage.
    monkeypatch.setenv("RESEARCH_LINEAR_WORKERS", "1")  # K1, K2 finish before K3 starts

    def quota_from_k3(call, role):
        if role == "agent" and "Investigate K3:" in call["messages"][2][1]:
            return Exception("Error code: 429 - insufficient_quota: exceeded your current quota")
        return None

    rc, meta, plog, model, out = run_engine(tmp_path, bridge, World(fail=quota_from_k3))
    assert rc == 0, meta.get("error")
    assert meta["phases"]["gather"]["status"] == "partial"
    assert meta["kiqs"]["completed"] == 2
    assert not any("Investigate K4:" in c["messages"][2][1] for c in model.calls if c["tools"] is not None)
    assert "provider failure during gather" in plog.text()
    assert (out / "research_report.md").is_file() and calls_of(model, "SECTION WRITING TASK")


def test_provider_down_from_the_start_exits_2_with_resumable_state(tmp_path, bridge):
    def auth_error(call, role):
        return Exception("Error code: 401 - invalid api key")

    rc, meta, plog, _, out = run_engine(tmp_path, bridge, World(fail=auth_error))
    assert rc == 2
    assert meta["status"] == "failed" and meta["error"].startswith("provider_unavailable: gather failed")
    assert "plan" in meta["plan_fallback"]            # the plan fell back instead of failing
    assert (out / "v3" / "plan.json").is_file() and meta["phases"]["plan"]["status"] == "done"
    assert not (out / "research_report.md").exists()


class JunkWorld(World):
    """Every structured/writer call returns garbage; agents still work."""

    def scope(self, call):
        return ai("I would rather not answer in JSON.")

    def plan(self, call):
        return ai("Plan: [1] think {n} harder")

    def writer(self, call):
        return ai("")

    def exec_summary(self, call):
        return ai("")

    def actors(self, call):
        return ai("no json here")

    def facts(self, call):
        return ai('{"key_events": [')


def test_deterministic_fallbacks_when_plan_writer_and_extraction_fail(tmp_path, bridge):
    rc, meta, plog, model, out = run_engine(tmp_path, bridge, JunkWorld(), depth="quick")
    assert rc == 0, meta.get("error")
    assert {"scope", "plan", "kiqs", "sections", "scenarios"} <= set(meta["plan_fallback"])
    assert meta["synthesis_fallback_sections"] and meta["executive_summary_origin"] == "fallback"
    assert meta["actors_degraded"] is True and meta["structured_facts_degraded"] is True
    report = (out / "research_report.md").read_text(encoding="utf-8")
    assert len(report) >= lr.MIN_REPORT_CHARS and "## References" in report
    assert forecast_inputs_from_report_markdown(report)["scenarios"]  # default frame, still parseable
    for name in ("actors.json", "timeline.json", "quantitative.json", "contested.json"):
        assert (out / name).is_file(), name                              # all four always written
    assert json.loads((out / "quantitative.json").read_text(encoding="utf-8")) == []

    # JSON repair retries keep the cached prefix: the note is only in the LAST message
    plans = calls_of(model, "PLANNING TASK")
    assert len(plans) == 2 and plans[0]["messages"][:-1] == plans[1]["messages"][:-1]
    assert "not valid JSON" not in plans[0]["messages"][-1][1]
    assert "Your previous reply was not valid JSON" in plans[1]["messages"][-1][1]


def test_unexpected_exception_leaves_terminal_meta_and_open_plog(tmp_path, bridge, monkeypatch):
    def boom(self):
        raise RuntimeError("boom in qa")

    monkeypatch.setattr(lr._Engine, "phase_qa", boom)
    rc, meta, plog, _, out = run_engine(tmp_path, bridge, World(), depth="quick")
    assert rc == 2 and plog.closed is False
    disk = json.loads((out / "meta.json").read_text(encoding="utf-8"))
    assert disk["status"] == "failed" and disk["error"] == "v3 engine error: RuntimeError: boom in qa"
    assert "Traceback" in disk["traceback"] and disk["finished_at"]
    assert disk["usage"]["total"]["calls"] > 0          # telemetry still attached
    assert "[error] v3 engine error: RuntimeError: boom in qa" in plog.text()


def test_interrupt_is_recorded_and_propagates(tmp_path, bridge, monkeypatch):
    def interrupt(self):
        raise KeyboardInterrupt

    monkeypatch.setattr(lr._Engine, "phase_gather", interrupt)
    with pytest.raises(KeyboardInterrupt):
        run_engine(tmp_path, bridge, World(), depth="quick")
    disk = json.loads((tmp_path / "out" / "meta.json").read_text(encoding="utf-8"))
    assert disk["status"] == "failed" and "interrupted" in disk["error"]


def test_empty_question_fails_cleanly(tmp_path, bridge):
    rc, meta, _, _, _ = run_engine(tmp_path, bridge, World(), question="   ")
    assert rc == 2 and meta["status"] == "failed" and meta["error"] == "empty research question"


# =============================================================== agent protocol

class ProtocolWorld(World):
    """Step 1: a valid search, an unknown tool, an invalid call and a marker fetch;
    step 2: a call without an id (unanswerable) → the engine forces final notes."""

    def agent(self, call):
        messages = call["messages"]
        last_kind, last = messages[-1]
        task = messages[2][1]
        kid = re.search(r"Investigate (\S+):", task).group(1)
        if last_kind == "human" and last.startswith("STOP"):
            return ai(self.notes([c for k, c in messages if k == "tool"]))
        if not any(kind == "tool" for kind, _ in messages):
            seed = re.search(r"^\[S(\d+)\]", task, re.M).group(1)
            return ai(tool_calls=[
                {"name": "web_search", "args": {"query": f"{kid} grid queue data"}, "id": f"{kid}-a"},
                {"name": "web_teleport", "args": {}, "id": f"{kid}-b"},
                {"name": "web_fetch", "args": {"url": f"S{seed}", "focus": "capacity"}, "id": f"{kid}-d"},
            ], invalid=[{"name": "web_fetch", "args": "{bad json", "id": f"{kid}-c", "error": "bad JSON"}])
        return ai(tool_calls=[{"name": "web_search", "args": {"query": "no id"}, "id": ""}])


def test_agent_answers_every_tool_call_and_forces_final_on_unanswerable_calls(tmp_path, bridge, monkeypatch):
    monkeypatch.setenv("RESEARCH_LINEAR_WORKERS", "1")
    rc, meta, plog, model, out = run_engine(tmp_path, bridge, ProtocolWorld(), depth="quick")
    assert rc == 0, meta.get("error")
    k1 = [c for c in model.calls if c["tools"] is not None and "Investigate K1:" in c["messages"][2][1]]
    final = next(c for c in k1 if c["messages"][-1][1].startswith("STOP"))
    tool_messages = [content for kind, content in final["messages"] if kind == "tool"]
    assert len(tool_messages) == 4                          # one per call, invalid ones included
    by_order = dict(zip(["search", "unknown", "fetch", "invalid"], tool_messages, strict=True))
    assert by_order["search"].split("\n")[0].startswith("[S")
    assert by_order["unknown"].startswith("UNKNOWN_TOOL")
    assert by_order["fetch"].startswith("[S") and "FETCH_FAILED" not in by_order["fetch"]  # S<n> resolved
    assert by_order["invalid"].startswith("INVALID_TOOL_CALL: bad JSON")
    # the id-less assistant message was never appended (it could not be answered)
    assert [kind for kind, _ in final["messages"]][-2:] == ["tool", "human"]
    record = json.loads((out / "v3" / "kiq" / "K1.json").read_text(encoding="utf-8"))
    assert record["stats"]["forced"] == "unanswerable_tool_call" and record["stats"]["fetched"]


def test_content_filter_on_one_kiq_yields_deterministic_notes(tmp_path, bridge):
    def filtered(call, role):
        if role == "agent" and "Investigate K1:" in call["messages"][2][1]:
            return Exception("Error code: 400 - {'error': {'code': '1301', 'message': 'content filter'}}")
        return None

    rc, meta, plog, _, out = run_engine(tmp_path, bridge, World(fail=filtered), depth="quick")
    assert rc == 0, meta.get("error")
    record = json.loads((out / "v3" / "kiq" / "K1.json").read_text(encoding="utf-8"))
    assert record["stats"]["fallback"] == "content_filter"
    assert record["facts"] and all(f["tag"] == "REPORTED" for f in record["facts"])  # from seed snippets
    assert "[ok] research:v3:gather K1 facts=" in plog.text() and "fallback=content_filter" in plog.text()


def test_gap_round_runs_novel_follow_ups_with_engine_ids(tmp_path, bridge, monkeypatch):
    monkeypatch.setenv("RESEARCH_LINEAR_GAP_ROUNDS", "2")
    rc, meta, plog, model, out = run_engine(tmp_path, bridge, World(gap_followups=True))
    assert rc == 0, meta.get("error")
    round1 = json.loads((out / "v3" / "gap" / "round1.json").read_text(encoding="utf-8"))
    assert [k["id"] for k in round1["follow_ups"]] == ["G1F1"]
    assert round1["rejected"] and round1["rejected"][0]["reason"].startswith("near-duplicate")
    assert (out / "v3" / "kiq" / "G1F1.json").is_file()
    assert "### G1F1" in (out / "v3" / "digest.md").read_text(encoding="utf-8")
    assert len(calls_of(model, "GAP REVIEW TASK")) == 1       # stopped: diminishing returns
    assert "diminishing returns" in meta["phases"]["gap"]["detail"]
    log = plog.text()
    assert log.index("[stage] research:v3:gap round 1") < log.index("[ok] research:v3:gather G1F1")
    progress = _progress(plog)
    assert progress == sorted(progress) and progress[-1] == 99


def test_critique_rewrites_are_advisory_and_citation_preserving(tmp_path, bridge, monkeypatch):
    monkeypatch.setenv("RESEARCH_LINEAR_CRITIQUE", "1")
    rc, meta, _, model, _ = run_engine(tmp_path, bridge, World())
    assert rc == 0, meta.get("error")
    assert len(calls_of(model, "CRITIQUE TASK")) == 1
    rewrites = [c for c in calls_of(model, "SECTION WRITING TASK") if "Problem to fix: Too few numbers" in
                c["messages"][-1][1]]
    assert len(rewrites) == 1 and "Current version of this section" in rewrites[0]["messages"][-1][1]
    assert any(r["check"] == "critique" and r["section"] == "Demand Drivers" for r in meta["research_qa"]["repaired"])


def test_no_actors_skips_actor_extraction_but_writes_forecast_inputs(tmp_path, bridge):
    args = make_args("quick")
    args.no_actors = True
    rc, meta, _, model, out = run_engine(tmp_path, bridge, World(), args=args)
    assert rc == 0 and not calls_of(model, "ACTOR EXTRACTION TASK") and calls_of(model, "FACT EXTRACTION TASK")
    actors = json.loads((out / "actors.json").read_text(encoding="utf-8"))
    assert actors["actors"] == [] and actors["forecast_inputs"]["scenarios"] and meta["actors_skipped"] is True


def test_budget_exhaustion_degrades_to_deterministic_output(tmp_path, bridge, monkeypatch):
    monkeypatch.setenv("RESEARCH_LINEAR_BUDGET_UNITS", "1")  # every call is refused before paying
    rc, meta, plog, model, out = run_engine(tmp_path, bridge, World(), depth="quick")
    assert rc == 0, meta.get("error")
    assert model.calls == []                                 # nothing was paid for
    assert (out / "research_report.md").is_file() and meta["plan_fallback"]
    assert meta["synthesis_fallback_sections"]


# =============================================================== gateway fix + real dispatch

def test_search_rows_expose_fetchable_urls(tmp_path):
    """Regression (gateway fix): web_fetch needs a URL, so search rows must show it."""
    long_url = "https://www.example.org/" + "a" * 320
    payload = json.dumps({"results": [{"title": "Short", "url": "https://www.iea.org/reports/x", "content": "c"},
                                      {"title": "Long", "url": long_url, "content": "c"}]})
    ledger = rg.SourceLedger(tmp_path / "ledger.json")
    tools = rg.ResearchTools(ledger, tmp_path / "pages", search_fn=lambda q, n: payload, fetch_fn=page_text)
    text = tools.search("iea report", agent_id="K1")
    assert "\n    https://www.iea.org/reports/x\n" in text
    assert long_url not in text and "[S2] Long" in text     # too long to show whole: omitted, never cut


@pytest.fixture
def restore_environ():
    saved = dict(os.environ)
    try:
        yield
    finally:
        os.environ.clear()
        os.environ.update(saved)


def test_main_dispatches_research_engine_v3_end_to_end(tmp_path, bridge, monkeypatch, restore_environ):
    """deerflow_research.main() → hygiene → preflight → linear_research.run (real dispatch path)."""
    monkeypatch.setenv("RESEARCH_ENGINE", "v3")
    monkeypatch.setenv("MINIMAX_API_KEY", "test-key-not-used")
    model = ScriptedModel(World())
    seen: dict = {}

    def gateway_factory(args, plog, bridge_arg, preset):
        seen["bridge"], seen["depth"], seen["model"] = bridge_arg, preset.depth, args.model
        return rg.ModelGateway(model, plog, max_concurrency=preset.workers, budget_units=preset.budget_units,
                               reserve_share=lr.RESERVE_SHARE, sleep=lambda seconds: None)

    def tools_factory(ledger, pages_dir, bridge_arg, plog, limits):
        return rg.ResearchTools(ledger, pages_dir, search_fn=fake_search, fetch_fn=page_text,
                                bridge=bridge_arg, plog=plog, limits=limits)

    monkeypatch.setattr(lr, "_default_gateway_factory", gateway_factory)
    monkeypatch.setattr(lr, "_default_tools_factory", tools_factory)
    out = tmp_path / "handoff"
    old_argv = sys.argv
    sys.argv = ["deerflow_research.py", "--model", "minimax", "--depth", "quick", "--out-dir", str(out),
                "--prompt", "Will global data-centre capacity exceed 250 GW by the end of 2027?"]
    try:
        rc = dr.main()
    finally:
        sys.argv = old_argv
    assert rc == 0
    assert seen == {"bridge": dr, "depth": "quick", "model": "minimax"}
    meta = json.loads((out / dr.META_FILENAME).read_text(encoding="utf-8"))
    assert meta["status"] == "completed" and meta["research_engine"] == "v3" and meta["depth"] == "quick"
    log = (out / dr.PROGRESS_FILENAME).read_text(encoding="utf-8")
    assert "[stage] research engine: v3 (linear_research)" in log
    assert "[stage] research:v3:plan start" in log and "[done] research complete (v3:" in log
    for name in (dr.REPORT_FILENAME, dr.SOURCES_FILENAME, dr.ACTORS_FILENAME, dr.TIMELINE_FILENAME,
                 dr.QUANTITATIVE_FILENAME, dr.CONTESTED_FILENAME):
        assert (out / name).is_file(), name
    assert all(po._parse_usage_line(line) for line in log.splitlines() if " [usage] " in line)
