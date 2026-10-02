"""INFRA-9: contextvars propagation into the profile-generation and retrieval pools.

Offline: the LLM is a FakeLLMClient that meters its calls the way LLMClient
does (no explicit run id, so attribution comes from the calling thread's
telemetry context), and graph search is a local stub.
"""

from __future__ import annotations

import contextvars
import json
import sys
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from app.config import Config
from app.services.oasis_profile_generator import OasisProfileGenerator
from app.services.zep_entity_reader import EntityNode
from app.services.zep_tools import SearchResult, ZepToolsService
from app.utils import telemetry
from app.utils.ctxpool import submit_with_context
from tests.conftest import FakeLLMClient

_PROBE: contextvars.ContextVar = contextvars.ContextVar("infra9_probe", default=None)

RUN = "pipe_infra9_main"
OTHER_RUN = "pipe_infra9_other"


# ------------------------------------------------------------------ helper


def test_contextvar_set_by_submitter_is_visible_inside_the_task():
    def body():
        _PROBE.set("parent")
        with ThreadPoolExecutor(max_workers=1) as executor:
            inherited = submit_with_context(executor, _PROBE.get).result(timeout=10)
            bare = executor.submit(_PROBE.get).result(timeout=10)
        return inherited, bare

    inherited, bare = contextvars.copy_context().run(body)
    assert inherited == "parent"
    if not getattr(sys.flags, "thread_inherit_context", 0):
        # The defect this helper fixes: a bare submit runs in an empty context.
        assert bare is None


def test_concurrent_tasks_mutating_the_var_do_not_affect_each_other_or_the_parent():
    both_set = threading.Barrier(2, timeout=10)

    def task(value):
        _PROBE.set(value)
        both_set.wait()  # both tasks hold their own write at the same time
        return _PROBE.get()

    def body():
        _PROBE.set("parent")
        with ThreadPoolExecutor(max_workers=2) as executor:
            # One Context cannot be entered by two threads at once, so this also
            # proves every task runs in its own copy.
            futures = [submit_with_context(executor, task, value) for value in ("a", "b")]
            results = [future.result(timeout=10) for future in futures]
        return results, _PROBE.get()

    results, parent_after = contextvars.copy_context().run(body)
    assert results == ["a", "b"]
    assert parent_after == "parent"


def test_arguments_results_and_exceptions_pass_through():
    def combine(a, b, *, c):
        return a + b + c

    def boom():
        raise ValueError("task failed")

    with ThreadPoolExecutor(max_workers=1) as executor:
        assert submit_with_context(executor, combine, 1, 2, c=3).result(timeout=10) == 6
        with pytest.raises(ValueError, match="task failed"):
            submit_with_context(executor, boom).result(timeout=10)


# ------------------------------------------------------------- run metering


class _MeteredFakeLLM(FakeLLMClient):
    """FakeLLMClient whose calls are metered like LLMClient's (no explicit run id)."""

    def chat(self, messages, temperature=0.7, max_tokens=4096, response_format=None,
             tier=None, **kwargs):
        telemetry.LLMMeter.record(self.provider, self.model, 100, 50, 1.0)
        super().chat(messages, temperature=temperature, max_tokens=max_tokens,
                     response_format=response_format, tier=tier, **kwargs)
        return json.dumps({"bio": "A grid operator.", "persona": "Pragmatic and cautious.",
                           "age": 45, "gender": "other", "mbti": "ISTJ",
                           "country": "US", "profession": "Operator",
                           "interested_topics": ["grid"]})


def _calls(run_id):
    meter = telemetry.LLMMeter._runs.get(run_id)
    return meter.total.calls if meter is not None else 0


@pytest.fixture
def two_active_runs():
    """RUN and OTHER_RUN both in flight: the sole-active-run fallback cannot apply."""
    registered = threading.Thread(target=telemetry.set_run_context, args=(OTHER_RUN,))
    registered.start()
    registered.join()
    assert set(telemetry.active_run_ids()) == {OTHER_RUN}
    yield
    for run_id in (RUN, OTHER_RUN):
        telemetry.LLMMeter.reset(run_id)


def _in_run(fn):
    """Call ``fn`` in a copy of the current context with RUN as the telemetry run."""
    def body():
        telemetry.set_run_context(RUN, "prepare")
        assert len(telemetry.active_run_ids()) == 2
        return fn()

    return contextvars.copy_context().run(body)


def _entity(index):
    return EntityNode(uuid=f"infra9-{index}", name=f"Grid Operator {index}",
                      labels=["Entity", "Organization"], summary="Runs the regional grid.",
                      attributes={}, related_edges=[], related_nodes=[])


def test_pooled_profile_generation_is_attributed_to_the_submitting_run(two_active_runs):
    generator = OasisProfileGenerator.__new__(OasisProfileGenerator)
    generator.persona_language = "en"
    generator.graph_id = None
    generator.zep_client = None
    generator.llm = _MeteredFakeLLM()
    generator._build_entity_context = lambda entity: ""
    generator._print_generated_profile = lambda *args: None
    global_before = _calls("_global")

    profiles = _in_run(lambda: generator.generate_profiles_from_entities(
        [_entity(i) for i in range(4)], use_llm=True, parallel_count=4))

    assert [p.generation_path for p in profiles] == ["llm"] * 4
    assert len(generator.llm.calls) == 4
    assert _calls(RUN) == 4
    assert telemetry.LLMMeter.snapshot(RUN)["by_stage"]["prepare"]["calls"] == 4
    assert telemetry.LLMMeter.snapshot(RUN)["fallback_attributed"]["calls"] == 0
    assert _calls(OTHER_RUN) == 0
    assert _calls("_global") == global_before


class _RecordingGraph:
    def __init__(self):
        self.seen = []
        self.lock = threading.Lock()

    def search(self, *, query, graph_id, limit, scope, reranker):
        telemetry.LLMMeter.record("fake", "reranker", 10, 0, 1.0)
        with self.lock:
            self.seen.append((scope, telemetry.get_run_context()))
        return None


def test_profile_graph_search_pool_keeps_the_run_context(two_active_runs, monkeypatch):
    monkeypatch.setattr(Config, "PROFILE_ZEP_SEARCH_MAX_RETRIES", 1, raising=False)
    generator = OasisProfileGenerator.__new__(OasisProfileGenerator)
    generator.graph_id = "graph_infra9"
    graph = _RecordingGraph()
    generator.zep_client = type("_Zep", (), {"graph": graph})()
    global_before = _calls("_global")

    _in_run(lambda: generator._search_zep_for_entity(_entity(0)))

    assert sorted(graph.seen) == [("edges", (RUN, "prepare")), ("nodes", (RUN, "prepare"))]
    assert _calls(RUN) == 2
    assert _calls("_global") == global_before


def test_insight_forge_parallel_retrieval_keeps_the_run_context(two_active_runs, monkeypatch):
    monkeypatch.setattr(Config, "REPORT_RETRIEVAL_PARALLEL", True, raising=False)
    monkeypatch.setattr(Config, "REPORT_RETRIEVAL_PARALLEL_WORKERS", 4, raising=False)
    monkeypatch.setattr(Config, "REPORT_RETRIEVAL_CACHE", False, raising=False)
    monkeypatch.setattr(Config, "GRAPH_SEARCH_RECIPE", "rrf", raising=False)
    service = ZepToolsService.__new__(ZepToolsService)
    service._cache_lock = threading.RLock()
    service._forge_cache = {}
    service._coverage = {}
    seen = []
    lock = threading.Lock()

    def search_graph(graph_id, query, limit=10, scope="edges", recipe=None, search_filter=None):
        telemetry.LLMMeter.record("fake", "reranker", 10, 0, 1.0)
        with lock:
            seen.append((scope, telemetry.get_run_context()))
        return SearchResult(facts=[f"fact about {query}"], edges=[], nodes=[], query=query,
                            total_count=1)

    service.search_graph = search_graph
    service._generate_sub_queries = lambda **kwargs: ["q1", "q2", "q3"]
    service.get_all_nodes = lambda graph_id: []
    global_before = _calls("_global")

    def forge():
        telemetry.set_stage("report")
        return service.insight_forge("graph_infra9", "main question", "requirement")

    result = _in_run(forge)

    # Four pooled edge searches (three sub-queries + the question) and one inline node search.
    assert sorted(scope for scope, _ in seen) == ["edges"] * 4 + ["nodes"]
    assert {ctx for _, ctx in seen} == {(RUN, "report")}
    assert result.semantic_facts == [f"fact about {q}" for q in ("q1", "q2", "q3",
                                                                   "main question")]
    assert _calls(RUN) == 5
    assert _calls(OTHER_RUN) == 0
    assert _calls("_global") == global_before
