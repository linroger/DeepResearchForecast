"""Real child gateway/tool paths, a real SQLite authority, fake Model/HTTP only.

Synthetic tariffs and credentials are fixtures, never live route qualification.
Run only through main_offline_pytest.py; all storage stays inside its tmp root.
"""
from __future__ import annotations

import asyncio
import contextvars
import copy
import hashlib
import importlib
import json
import sqlite3
import sys
import threading
import types
from contextlib import contextmanager
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
for path in (REPO, REPO / "deerflow_bridge"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import run_spending as sp
import research_gateway as rg
import cached_fetch as cf
import search_tools as st
import linear_research as lr

KEY = "offline-synthetic-credential"
ENDPOINT = "https://model.invalid/v1"
MODEL = "synthetic-model"


@pytest.fixture(autouse=True)
def isolated(monkeypatch, tmp_path):
    # Permanent production authority has no reset API. These private resets
    # isolate tests only; every real run_lock is still exited by its fixture.
    monkeypatch.setattr(sp, "_REQUIRED", False)
    monkeypatch.setattr(sp, "_ACTIVE_AUTH", None)
    monkeypatch.setattr(sp, "_ENV_PIN", None)
    monkeypatch.setattr(sp, "_LOCAL_STOPS", {})
    monkeypatch.setattr(sp, "_binding", contextvars.ContextVar("test_binding", default=None))
    monkeypatch.setattr(sp, "_operation", contextvars.ContextVar("test_operation", default=None))
    for key in list(__import__("os").environ):
        if key.startswith("DRF_RUN_SPENDING_") or key in (
            "DRF_BACKTEST_POLICY", "OPENAI_ORG_ID", "OPENAI_ORGANIZATION", "OPENAI_PROJECT_ID",
            "LANGCHAIN_TRACING", "LANGCHAIN_TRACING_V2", "LANGSMITH_TRACING", "LANGSMITH_TRACING_V2"):
            monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("FIRECRAWL_API_KEY", KEY)
    monkeypatch.setenv("FIRECRAWL_SEARCH_API_URL", "https://firecrawl.invalid/v2/search")
    monkeypatch.setenv("FIRECRAWL_API_URL", "https://firecrawl.invalid/v2/scrape")
    monkeypatch.setenv("RESEARCH_SEARCH_CACHE_DIR", str(tmp_path / "search-cache"))
    monkeypatch.setenv("RESEARCH_SOURCE_CACHE_DIR", str(tmp_path / "fetch-cache"))
    monkeypatch.setenv("RESEARCH_SEARCH_CACHE_TTL_H", "6")
    monkeypatch.setenv("RESEARCH_SOURCE_CACHE_TTL_H", "72")
    monkeypatch.setenv("RESEARCH_FIRECRAWL_CALLS_PER_MINUTE", "0")
    monkeypatch.setenv("RESEARCH_BUDGET_ENABLED", "false")
    monkeypatch.setattr(st, "_firecrawl_search_calls", 0)
    monkeypatch.setattr(cf, "_firecrawl_fetch_calls", 0)


@pytest.fixture(autouse=True)
def fake_model_runtime(monkeypatch):
    model_module = types.ModuleType("langchain_openai")
    model_module.ChatOpenAI = FakeModel
    config_module = types.ModuleType("langchain_core.runnables.config")
    config_module.var_child_runnable_config = contextvars.ContextVar("fake_callbacks", default=None)
    tracer_module = types.ModuleType("langchain_core.tracers.context")
    tracer_module._configure_hooks = []
    tracer_module.tracing_v2_callback_var = contextvars.ContextVar("fake_tracer", default=None)
    tracer_module.global_enabled = False
    tracer_module._tracing_v2_is_enabled = lambda: (tracer_module.global_enabled
        or tracer_module.tracing_v2_callback_var.get() is not None)
    smith_module = types.ModuleType("langsmith.run_helpers")
    smith_module.get_tracing_context = lambda: {"enabled": False, "parent": None, "client": None}
    for name, module in (("langchain_openai", model_module),
                         ("langchain_core.runnables.config", config_module),
                         ("langchain_core.tracers.context", tracer_module),
                         ("langsmith.run_helpers", smith_module)):
        monkeypatch.setitem(sys.modules, name, module)


def rows(binding):
    with sqlite3.connect(Path(binding["db_path"]).as_uri() + "?mode=ro", uri=True) as db:
        db.row_factory = sqlite3.Row
        return [dict(row) for row in db.execute("SELECT * FROM attempts ORDER BY rowid")]


@contextmanager
def run_authority(tmp_path, monkeypatch, *, cap="10", model=MODEL, alias=None):
    root = tmp_path / "runtime"
    (root / "spend").mkdir(parents=True)
    source_files = {}
    for name in ("run_spending.py", "research_gateway.py", "linear_research.py", "search_tools.py", "cached_fetch.py"):
        data = (REPO / "deerflow_bridge" / name).read_bytes()
        relative = "deerflow_bridge/" + name
        target = root / relative
        target.parent.mkdir(exist_ok=True)
        target.write_bytes(data)
        source_files[relative] = hashlib.sha256(data).hexdigest()
    common = {"account_sha256": hashlib.sha256(KEY.encode()).hexdigest(),
              "basis_sha256": sp.hash_payload({"synthetic": "offline-only"}),
              "coverage": "all_billable_dimensions"}
    routes = {"model": dict(common, kind="openai_chat", endpoint=ENDPOINT, model=model,
        billing_class="external_model", input_bound="enforced_context_ceiling", input_ceiling=1000,
        max_output_tokens=128000, max_tool_units=0,
        pricing={"input_usd_per_million": "1", "output_usd_per_million": "2", "tool_usd_per_unit": "0", "fixed_usd": "0", "surcharge_usd": "0"})}
    for name, units in (("search", 5), ("scrape", 1)):
        routes[name] = dict(common, kind="firecrawl_" + name, endpoint="https://firecrawl.invalid/v2/" + name,
            model="", billing_class="external_tool", input_bound="not_applicable", input_ceiling=0,
            max_output_tokens=0, max_tool_units=units,
            pricing={"input_usd_per_million": "0", "output_usd_per_million": "0", "tool_usd_per_unit": "0.01", "fixed_usd": "0", "surcharge_usd": "0"})
    request = {"prompt": "What is official capacity?", "mode": "full", "depth": "quick", "language": "English",
               "model": alias or MODEL, "forecast_authority": "target-first-v1",
               "target_simulation": {"paths": 1, "periods": 1, "seed": 0}}
    (root / "control").mkdir()
    control = root / "control/request.json"
    control.write_text(json.dumps(request, sort_keys=True))
    source_files["control/request.json"] = hashlib.sha256(control.read_bytes()).hexdigest()
    manifest = {"schema": "target-run-spending/v1", "authorization_id": "child-fixture",
        "root": str(root), "currency": "USD", "cap_usd": cap,
        "request_sha256": sp.hash_payload(request), "source_files": source_files,
        "source_sha256": sp.hash_payload(source_files), "routes_sha256": sp.hash_payload(routes),
        "resume_policy": "explicit_clean_only", "routes": routes}
    path = root / "spend/authorization.json"
    path.write_text(json.dumps(manifest))
    (tmp_path / "registry").mkdir()
    binding = sp.create_authorization(path, registry_dir=tmp_path / "registry")
    with sp.run_lock(binding):
        binding = sp.bind_pipeline(binding, "pipeline-synthetic", request)
        sp.activate_binding(binding)
        with sp.operation("research", "parent-supplied-child-root"):
            for key, value in sp.export_environment(binding).items():
                monkeypatch.setenv(key, value)
            yield binding


def ai(text="ok", *, finish="stop", usage=True, output=2):
    return rg._msg_classes()[2](content=text, tool_calls=[],
        usage_metadata={"input_tokens": 12, "output_tokens": output, "total_tokens": 12 + output} if usage else None,
        response_metadata={"finish_reason": finish})


class BaseChatOpenAI:
    """Inspectable fake SDK model; production gateway and serializer path stay real."""


class FakeModel(BaseChatOpenAI):
    def __init__(self, script=(), *, model=MODEL):
        self.model_name, self.openai_api_base, self.openai_api_key = model, ENDPOINT, KEY
        self.max_retries, self.n, self.streaming = 0, 1, False
        self.cache, self.use_responses_api = False, False
        http = types.SimpleNamespace(follow_redirects=False, _mounts={},
            _transport=types.SimpleNamespace(_pool=types.SimpleNamespace(_retries=0)))
        self.root_client = types.SimpleNamespace(base_url=ENDPOINT, api_key=KEY, max_retries=0,
            _client=http, _custom_headers={}, _custom_query={})
        self.client = types.SimpleNamespace(_client=self.root_client)
        self.client.with_raw_response = types.SimpleNamespace(create=self._physical_create)
        self.root_client.chat = types.SimpleNamespace(completions=self.client)
        self.bound, self.tools = {}, None
        self.state = {"script": list(script), "calls": [], "copies": 0, "lock": threading.Lock()}

    @property
    def calls(self):
        return self.state["calls"]

    def model_copy(self, *, update):
        self.state["copies"] += 1
        clone = copy.copy(self)
        for name, value in update.items():
            setattr(clone, name, value)
        return clone

    def bind(self, **kwargs):
        clone = copy.copy(self)
        clone.bound = dict(self.bound, **kwargs)
        return clone

    def bind_tools(self, tools):
        clone = copy.copy(self)
        clone.tools = tools
        return clone

    def _get_request_payload(self, messages, **kwargs):
        payload = {"model": self.model_name, "stream": False, "n": 1,
            "messages": [{"role": m.type, "content": m.content} for m in messages], **kwargs}
        if "max_tokens" in payload:
            payload["max_completion_tokens"] = payload.pop("max_tokens")
        return payload

    def _physical_create(self, **kwargs):
        binding = sp.check_context()
        committed = rows(binding)
        assert committed, "physical model send preceded durable admission"
        payload = dict(kwargs)
        payload.pop("timeout", None)
        payload.update(payload.pop("extra_body", None) or {})
        with self.state["lock"]:
            self.calls.append({"payload": payload, "committed": committed})
            action = self.state["script"].pop(0) if self.state["script"] else ai()
        if isinstance(action, BaseException):
            raise action
        action = action() if callable(action) else action
        if isinstance(action, dict):
            body = action
        else:
            usage = getattr(action, "usage_metadata", None)
            body = {"choices": [{"message": {"content": action.content}}]}
            if usage:
                body["usage"] = {"prompt_tokens": usage["input_tokens"], "completion_tokens": usage["output_tokens"]}
        return types.SimpleNamespace(http_response=types.SimpleNamespace(status_code=200, json=lambda: body),
                                     parse=lambda: action)

    def invoke(self, messages, config=None):
        kwargs = dict(self.bound)
        if self.tools:
            kwargs["tools"] = list(self.tools)
        raw = self.client.with_raw_response.create(**self._get_request_payload(messages, **kwargs))
        result = raw.parse()
        if callable(getattr(result, "model_dump", None)):
            result = result.model_dump()
        if isinstance(result, dict):
            if not result.get("choices"):
                raise ValueError("malformed choices after raw usage")
            usage = result.get("usage")
            return ai(result["choices"][0]["message"]["content"], usage=bool(usage),
                      output=usage["completion_tokens"] if usage else 2)
        return result


def messages():
    return rg.build_messages("core", ["brief"], "task")


def gateway(model):
    return rg.ModelGateway(model, None, sleep=lambda _: None)


class FakeHTTP:
    def __init__(self, monkeypatch, *, status=200, error=None):
        import httpx
        self.posts, self.clients, self.status = [], [], status
        owner = self

        class Response:
            status_code = status
            text = "synthetic"
            def __init__(self, endpoint):
                self.endpoint = endpoint
            def json(self):
                if self.endpoint.endswith("search"):
                    return {"creditsUsed": 1, "data": {"web": [{"title": "Official evidence",
                        "url": "https://agency.example/report", "description": "Capacity reached 176 GW."}]}}
                return {"creditsUsed": 1, "data": {"markdown": "# Official evidence\n\n" +
                    "Capacity reached 176 GW. The agency recorded audited annual output. " * 12}}

        class Client:
            def __init__(self, **kwargs):
                owner.clients.append(kwargs)
                assert kwargs["follow_redirects"] is False and kwargs["trust_env"] is False
            def __enter__(self):
                return self
            def __exit__(self, *args):
                pass
            def post(self, endpoint, **kwargs):
                binding = sp.check_context()
                committed = rows(binding)
                assert committed, "physical POST preceded durable admission"
                owner.posts.append({"endpoint": endpoint, "json": kwargs["json"], "committed": committed})
                if error is not None:
                    raise error
                return Response(endpoint)

        class AsyncClient(Client):
            async def __aenter__(self):
                return self
            async def __aexit__(self, *args):
                pass
            async def post(self, endpoint, **kwargs):
                return super().post(endpoint, **kwargs)

        def transport(**kwargs):
            assert kwargs == {"retries": 0}
            return object()
        monkeypatch.setattr(httpx, "Client", Client)
        monkeypatch.setattr(httpx, "AsyncClient", AsyncClient)
        monkeypatch.setattr(httpx, "HTTPTransport", transport)
        monkeypatch.setattr(httpx, "AsyncHTTPTransport", transport)


def research_tools(tmp_path):
    return rg.ResearchTools(rg.SourceLedger(tmp_path / "sources.json"), tmp_path / "pages")


def test_one_module_one_ledger_actual_model_search_scrape(tmp_path, monkeypatch):
    from app.services.official_data import bridge_module
    assert importlib.import_module("deerflow_bridge.run_spending") is sp
    assert bridge_module("run_spending") is sp
    package_gateway = importlib.import_module("deerflow_bridge.research_gateway")
    assert rg._spending is st._spending is cf._spending is lr._spending is sp
    assert package_gateway._spending is sp
    with run_authority(tmp_path, monkeypatch) as binding:
        http = FakeHTTP(monkeypatch)
        model = FakeModel([ai()])
        package_gateway.ModelGateway(model, None).invoke(messages(), kind="agent", label="KIQ-1", max_tokens=8,
                                                          tools=rg.AGENT_TOOLS_SCHEMA)
        tools = research_tools(tmp_path)
        tools.search("official capacity", agent_id="K1")
        tools.fetch("https://agency.example/report", agent_id="K1")
        assert len(model.calls) == 1 and len(http.posts) == 2
        assert len(rows(binding)) == 3
        assert sp.summary(binding)["reserved_max_microusd"] == 1016 + 50000 + 10000
        assert json.loads(rows(binding)[0]["envelope"])["input_tokens"] == 1000
        assert all(call["committed"][-1]["state"] == "unknown" for call in [model.calls[0], *http.posts])
        assert [len(call["committed"]) for call in [model.calls[0], *http.posts]] == [1, 2, 3]
        assert all("parent-supplied-child-root" not in json.dumps(call["payload"]) for call in model.calls)


def test_widened_reasoning_and_json_repair_each_reserve(tmp_path, monkeypatch):
    with run_authority(tmp_path, monkeypatch) as binding:
        model = FakeModel([ai("", finish="length", output=8), ai("ok")])
        gw = gateway(model)
        assert gw.invoke(messages(), kind="agent", label="wide", max_tokens=8).text == "ok"
        assert [c["payload"]["max_completion_tokens"] for c in model.calls] == [8, 16]
        repaired = FakeModel([ai("not json", usage=False), ai('{"answer":1}')])
        assert gateway(repaired).json(lambda _: messages(), label="repair", required_keys=["answer"])["answer"] == 1
        assert len(rows(binding)) == 4
        assert sp.summary(binding)["usage_kinds"] == {"missing": 1, "estimated": 0, "provider_reported": 3}
        assert [json.loads(row["envelope"])["max_output_tokens"] for row in rows(binding)[:2]] == [8, 16]
        assert all(len(call["committed"]) == index for index, call in enumerate(model.calls + repaired.calls, 1))


def test_exhaustion_stops_widened_attempt_before_send(tmp_path, monkeypatch):
    with run_authority(tmp_path, monkeypatch, cap="0.001020") as binding:
        model = FakeModel([ai("", finish="length", output=8), ai("must not send")])
        with pytest.raises(sp.SpendingStop):
            gateway(model).invoke(messages(), kind="agent", label="wide", max_tokens=8)
        assert len(model.calls) == len(rows(binding)) == 1


@pytest.mark.parametrize("error", [TimeoutError("private"), ConnectionError("private")])
def test_unknown_model_failure_halts_without_retry(tmp_path, monkeypatch, error):
    with run_authority(tmp_path, monkeypatch) as binding:
        model = FakeModel([error, ai("must not send")])
        gw = gateway(model)
        with pytest.raises(sp.SpendingStop):
            gw.json(lambda _: messages(), label="unknown", required_keys=["answer"])
        with pytest.raises(sp.SpendingStop):
            gw.prime(messages(), kind="agent", label="later")
        assert len(model.calls) == len(rows(binding)) == 1


def test_outer_wait_timeout_halts_before_late_worker_returns(tmp_path, monkeypatch):
    with run_authority(tmp_path, monkeypatch) as binding:
        entered, release, returned = threading.Event(), threading.Event(), threading.Event()
        def late():
            entered.set()
            release.wait(2)
            returned.set()
            return ai()
        model = FakeModel([late])
        gw = gateway(model)
        monkeypatch.setattr(gw, "_timeout_for", lambda *args: 0.01)
        monkeypatch.setattr(rg, "CALL_WAIT_GRACE_S", 0.01)
        try:
            with pytest.raises(sp.SpendingStop):
                gw.invoke(messages(), kind="agent", label="timeout", max_tokens=8)
            assert entered.is_set()
            with pytest.raises(sp.SpendingStop):
                gw.invoke(messages(), kind="agent", label="blocked", max_tokens=8)
        finally:
            release.set()
            assert returned.wait(2)
        assert len(model.calls) == len(rows(binding)) == 1
        with pytest.raises(sp.SpendingStop):
            sp.check_active()


def test_missing_worker_context_and_removed_env_cannot_restore_legacy(tmp_path, monkeypatch):
    with run_authority(tmp_path, monkeypatch) as binding:
        failures = []
        def unbound_worker():
            try:
                gateway(FakeModel())
            except sp.SpendingStop as exc:
                failures.append(exc)
        worker = threading.Thread(target=unbound_worker)
        worker.start(); worker.join()
        assert len(failures) == 1 and not rows(binding)
        monkeypatch.delenv("DRF_RUN_SPENDING_BINDING", raising=False)
        with pytest.raises(sp.SpendingStop):
            gateway(FakeModel())


@pytest.mark.parametrize("status", [429, 503])
@pytest.mark.parametrize("kind", ["search", "fetch"])
def test_firecrawl_unknown_post_never_falls_back_or_retries(tmp_path, monkeypatch, status, kind):
    with run_authority(tmp_path, monkeypatch) as binding:
        http = FakeHTTP(monkeypatch, status=status)
        monkeypatch.setenv("SERPER_API_KEY", "unused")
        monkeypatch.setenv("TAVILY_API_KEY", "unused")
        monkeypatch.setenv("EXA_API_KEY", "unused")
        monkeypatch.setenv("RESEARCH_DIRECT_FETCH_FALLBACK", "true")
        tools = research_tools(tmp_path)
        with pytest.raises(sp.SpendingStop):
            if kind == "search":
                tools.search("capacity", agent_id="K1")
            else:
                tools.fetch("https://agency.example/report", agent_id="K1")
        assert len(http.posts) == len(rows(binding)) == 1
        assert http.posts[0]["endpoint"].endswith("search" if kind == "search" else "scrape")
        with pytest.raises(sp.SpendingStop):
            tools.search("different query", agent_id="K2")


def test_positive_cache_singleflight_and_async_worker_add_no_debit(tmp_path, monkeypatch):
    with run_authority(tmp_path, monkeypatch) as binding:
        http = FakeHTTP(monkeypatch)
        tools, gw = research_tools(tmp_path), gateway(FakeModel())
        result = gw.fan_out([lambda: tools.search("same capacity", agent_id="K1") for _ in range(4)], warm_first=False)
        assert len(result) == 4 and not any(isinstance(item, BaseException) for item in result)
        assert len(http.posts) == 1
        async def from_running_loop():
            return tools.fetch("https://agency.example/report", agent_id="K1")
        assert asyncio.run(from_running_loop())
        tools.fetch("https://agency.example/report", agent_id="K2")
        assert len(http.posts) == len(rows(binding)) == 2
        # New gateway memory still reuses the actual provider's local disk caches.
        again = research_tools(tmp_path / "again")
        again.search("same capacity", agent_id="K3")
        again.fetch("https://agency.example/report", agent_id="K3")
        assert len(http.posts) == len(rows(binding)) == 2


@pytest.mark.parametrize("mutation", ["sdk_retry", "redirect", "http_retry", "resource", "endpoint", "credential", "opaque"])
def test_model_route_retry_and_identity_fail_before_send(tmp_path, monkeypatch, mutation):
    with run_authority(tmp_path, monkeypatch) as binding:
        model = FakeModel()
        if mutation == "sdk_retry":
            model.max_retries = model.root_client.max_retries = 2
        elif mutation == "redirect": model.root_client._client.follow_redirects = True
        elif mutation == "http_retry": model.root_client._client._transport._pool._retries = 1
        elif mutation == "resource": model.client = types.SimpleNamespace()
        elif mutation == "endpoint": model.root_client.base_url = "https://elsewhere.invalid/v1"
        elif mutation == "credential": model.root_client.api_key = "other"
        elif mutation == "opaque": model._get_request_payload = None
        with pytest.raises(sp.SpendingStop):
            gateway(model).invoke(messages(), kind="agent", label="denied", max_tokens=8)
        assert not model.calls and not rows(binding)


@pytest.mark.parametrize("tool", ["data_search", "data_get", "context_query", "archive"])
def test_unpriced_tool_paths_closed_before_acquisition(tmp_path, monkeypatch, tool):
    with run_authority(tmp_path, monkeypatch) as binding:
        http = FakeHTTP(monkeypatch)
        tools = research_tools(tmp_path)
        with pytest.raises(sp.SpendingStop):
            if tool == "data_search": tools.data_search("GDP", agent_id="K1")
            elif tool == "data_get": tools.data_get("fred:GDP", agent_id="K1")
            elif tool == "context_query": tools.context_query("news_search", "GDP", agent_id="K1")
            else: tools._fetch_as_of("https://agency.example/report", "key", [], [], "K1")
        assert not http.clients and not rows(binding)


def make_engine(tmp_path, model):
    import deerflow_research as bridge
    args = types.SimpleNamespace(model=MODEL, depth="quick", target_language="English", no_actors=True,
                                 forecast_authority="target-first-v1")
    meta = {"status": "running"}
    engine = lr._Engine("What is official capacity?", tmp_path / "out", args, meta, lr._Reporter(None),
        lambda: None, bridge, lambda *args: gateway(model), lr._default_tools_factory, __import__("os").environ)
    return engine, args, meta, bridge


def test_nested_kiq_tool_workers_copy_required_context(tmp_path, monkeypatch):
    with run_authority(tmp_path, monkeypatch) as binding:
        http = FakeHTTP(monkeypatch)
        engine, _, _, _ = make_engine(tmp_path, FakeModel())
        kiq = lr.Kiq(id="K1", question="capacity", queries=["capacity"], kind="baseline")
        agent = lr.KiqAgent(engine, kiq, "task", [], rg.Deadline(30))
        calls = [{"name": "web_search", "id": "s1", "args": {"query": "capacity north"}},
                 {"name": "web_search", "id": "s2", "args": {"query": "capacity south"}}]
        result, _ = agent._execute(calls)
        assert len(result) == 2 and len(http.posts) == len(rows(binding)) == 2
        assert engine.meta["data_sources"]["status"] == "disabled_spending_profile"
        assert engine.meta["news_market_context"]["status"] == "disabled_spending_profile"


def test_kiq_best_effort_wrapper_does_not_swallow_spending_stop(tmp_path, monkeypatch):
    with run_authority(tmp_path, monkeypatch) as binding:
        http = FakeHTTP(monkeypatch, status=503)
        engine, _, _, _ = make_engine(tmp_path, FakeModel())
        agent = lr.KiqAgent(engine, lr.Kiq(id="K1", question="capacity", queries=[]), "task", [], rg.Deadline(30))
        with pytest.raises(sp.SpendingStop):
            agent._call_tool({"name": "web_search", "id": "s1", "args": {"query": "capacity"}})
        assert len(http.posts) == len(rows(binding)) == 1


def test_real_engine_run_propagates_model_stop_and_marks_failed(tmp_path, monkeypatch):
    import deerflow_research as bridge
    with run_authority(tmp_path, monkeypatch) as binding:
        model = FakeModel([TimeoutError("synthetic ambiguous transport")])
        args = types.SimpleNamespace(model=MODEL, depth="quick", target_language="English", no_actors=True,
                                     forecast_authority="target-first-v1")
        output = Path(binding["root"]) / "app/backend/uploads/pipelines" / binding["pipeline_id"] / "handoff"
        meta = {"status": "running"}
        with pytest.raises(sp.SpendingStop):
            lr.run("What is official capacity?", output, args, meta, None, lambda: None,
                   bridge=bridge, gateway_factory=lambda *args: gateway(model))
        assert meta["status"] == "failed" and meta["error"] == "unknown_outcome"
        assert len(model.calls) == len(rows(binding)) == 1
        assert not (output / "research_report.md").exists()


def install_factory_dependencies(monkeypatch, *, endpoint=ENDPOINT, model=MODEL, api_key=KEY, alias=None):
    config = types.SimpleNamespace(use="langchain_openai:ChatOpenAI", model=model, base_url=endpoint, api_key=api_key)
    def selected(name):
        if alias is not None:
            assert name == alias
        return config
    app_config = types.SimpleNamespace(get_model_config=selected)
    package = types.ModuleType("deerflow")
    config_module = types.ModuleType("deerflow.config")
    config_module.get_app_config = lambda: app_config
    models = types.ModuleType("langchain_openai")
    created = []
    class FactoryModel(FakeModel):
        def __init__(self, **kwargs):
            created.append(kwargs)
            super().__init__(model=kwargs["model"])
    models.ChatOpenAI = FactoryModel
    monkeypatch.setitem(sys.modules, "deerflow", package)
    monkeypatch.setitem(sys.modules, "deerflow.config", config_module)
    monkeypatch.setitem(sys.modules, "langchain_openai", models)
    return created


def test_factory_qualifies_before_construction_and_disables_sdk_retries(tmp_path, monkeypatch):
    with run_authority(tmp_path, monkeypatch):
        http = FakeHTTP(monkeypatch)
        created = install_factory_dependencies(monkeypatch)
        monkeypatch.setenv("DEERFLOW_FALLBACK_MODEL", "unpriced")
        args = types.SimpleNamespace(model=MODEL, config=None)
        gw = lr._default_gateway_factory(args, None, None, lr.resolve_preset("quick", {}))
        assert isinstance(gw, rg.ModelGateway) and gw._fallback is None
        assert len(created) == 1 and len(http.clients) == 2
        assert created[0]["max_retries"] == 0 and created[0]["streaming"] is False
        assert created[0]["use_responses_api"] is False


@pytest.mark.parametrize("invalid", ["route", "module_hash", "binding", "operation"])
def test_child_contract_or_route_invalid_before_factory_clients(tmp_path, monkeypatch, invalid):
    with run_authority(tmp_path, monkeypatch) as binding:
        child = sp.register_participant(binding, "research-child",
            spawn_receipt_sha256=sp.hash_payload({"spawn": "synthetic"}))
        env = sp.export_environment(child)
        for key, value in env.items(): monkeypatch.setenv(key, value)
        if invalid == "route":
            sp.activate_binding(child)
        if invalid == "module_hash": monkeypatch.setenv("DRF_RUN_SPENDING_MODULE_SHA256", "0" * 64)
        elif invalid == "binding": monkeypatch.delenv("DRF_RUN_SPENDING_BINDING")
        elif invalid == "operation": monkeypatch.delenv("DRF_RUN_SPENDING_OPERATION")
        http = FakeHTTP(monkeypatch)
        created = install_factory_dependencies(monkeypatch,
            endpoint="https://unpriced.invalid/v1" if invalid == "route" else ENDPOINT)
        args = types.SimpleNamespace(model=MODEL, config=None)
        with pytest.raises(sp.SpendingStop):
            lr._default_gateway_factory(args, None, None, lr.resolve_preset("quick", {}))
        assert not created and not http.clients and not rows(binding)


def test_raw_missing_usage_does_not_become_normalizer_estimate(tmp_path, monkeypatch):
    with run_authority(tmp_path, monkeypatch) as binding:
        model = FakeModel([ai("reported text", usage=False)])
        gateway(model).invoke(messages(), kind="agent", label="missing-usage", max_tokens=8)
        entry = rows(binding)[0]
        assert entry["reserved"] == 1016
        assert json.loads(entry["observation"]) == {"kind": "missing", "outcome": "response_observed"}
        assert sp.summary(binding)["usage_kinds"]["estimated"] == 0


def test_async_cancellation_is_unknown_and_cannot_retry(tmp_path, monkeypatch):
    with run_authority(tmp_path, monkeypatch) as binding:
        http = FakeHTTP(monkeypatch, error=asyncio.CancelledError())
        with pytest.raises(sp.SpendingStop):
            asyncio.run(cf._firecrawl_fetch("https://agency.example/report"))
        assert len(http.posts) == len(rows(binding)) == 1
        assert sp.summary(binding)["state"] == "halted_unknown"
        with pytest.raises(sp.SpendingStop):
            st.web_search_impl("next query")


def test_valid_registered_child_contract_restores_root_operation_before_factory(tmp_path, monkeypatch):
    with run_authority(tmp_path, monkeypatch) as binding:
        child = sp.register_participant(binding, "research-child",
            spawn_receipt_sha256=sp.hash_payload({"spawn": "synthetic"}))
        for key, value in sp.export_environment(child).items(): monkeypatch.setenv(key, value)
        # Simulate an entering interpreter's empty context without resetting its
        # permanent required latch or the real parent-owned run lock.
        sp._binding.set(None)
        sp._operation.set(None)
        restored = sp.binding_from_environment()
        sp.activate_binding(restored)
        http = FakeHTTP(monkeypatch)
        created = install_factory_dependencies(monkeypatch)
        args = types.SimpleNamespace(model=MODEL, config=None)
        gw = lr._default_gateway_factory(args, None, None, lr.resolve_preset("quick", {}))
        gw.invoke(messages(), kind="agent", label="child-call", max_tokens=8)
        assert len(created) == 1 and len(http.clients) == 2
        assert rows(binding)[0]["participant_id"] == "research-child"
        assert sp.summary(binding)["reserved_max_microusd"] == 1016


def test_finalize_market_helper_is_not_acquired_when_bound(tmp_path, monkeypatch):
    with run_authority(tmp_path, monkeypatch) as binding:
        http = FakeHTTP(monkeypatch)
        engine, _, _, _ = make_engine(tmp_path, FakeModel())
        assert engine.bridge_call("_collect_prediction_markets", engine.out_dir, engine.question,
                                  "report", engine.meta, engine.reporter) is None
        assert not http.clients and not rows(binding)


@pytest.mark.parametrize("bad", ["subclass", "global_cache", "tracing_env", "inherited_callbacks",
                                 "tracing_v2_env", "tracer_context", "tracing_global"])
def test_opaque_subclass_cache_and_tracing_denied(tmp_path, monkeypatch, bad):
    with run_authority(tmp_path, monkeypatch) as binding:
        class Subclass(FakeModel):
            pass
        model = Subclass() if bad == "subclass" else FakeModel()
        if bad == "global_cache": model.cache = None
        elif bad == "tracing_env": monkeypatch.setenv("LANGSMITH_TRACING", "true")
        elif bad == "inherited_callbacks":
            sys.modules["langchain_core.runnables.config"].var_child_runnable_config.set({"callbacks": [object()]})
        elif bad == "tracing_v2_env": monkeypatch.setenv("LANGSMITH_TRACING_V2", "true")
        elif bad == "tracer_context":
            sys.modules["langchain_core.tracers.context"].tracing_v2_callback_var.set(object())
        elif bad == "tracing_global":
            sys.modules["langchain_core.tracers.context"].global_enabled = True
        with pytest.raises(sp.SpendingStop):
            gateway(model).invoke(messages(), kind="agent", label="closed", max_tokens=8)
        assert not model.calls and not rows(binding)


@pytest.mark.parametrize("output", [2, 999])
def test_raw_usage_recorded_before_malformed_choices(tmp_path, monkeypatch, output):
    with run_authority(tmp_path, monkeypatch) as binding:
        model = FakeModel([{"usage": {"prompt_tokens": 12, "completion_tokens": output}, "choices": None}])
        with pytest.raises(sp.SpendingStop if output > 8 else rg.BadRequest):
            gateway(model).invoke(messages(), kind="agent", label="bad-choices", max_tokens=8)
        assert len(model.calls) == len(rows(binding)) == 1
        if output <= 8:
            assert json.loads(rows(binding)[0]["observation"])["output_tokens"] == output
            assert rows(binding)[0]["state"] == "response_observed"
        else:
            assert sp.summary(binding)["stop_code"] == "usage_integrity"


@pytest.mark.parametrize("model_name", [MODEL, "glm-5.3"])
def test_real_openai_sdk_http_json_matches_ledger_body_hash(tmp_path, monkeypatch, model_name):
    import httpx
    from openai import OpenAI
    with run_authority(tmp_path, monkeypatch, model=model_name) as binding:
        bodies = []
        class Transport(httpx.BaseTransport):
            _pool = types.SimpleNamespace(_retries=0)
            def handle_request(self, request):
                body = json.loads(request.content)
                bodies.append(body)
                assert rows(binding)[-1]["state"] == "unknown"
                return httpx.Response(200, json={"id": "synthetic", "object": "chat.completion", "created": 1,
                    "model": model_name, "usage": {"prompt_tokens": 12, "completion_tokens": 2, "total_tokens": 14},
                    "choices": [{"index": 0, "message": {"role": "assistant", "content": "ok"}, "finish_reason": "stop"}]})
        model = FakeModel(model=model_name)
        with httpx.Client(transport=Transport(), follow_redirects=False, trust_env=False) as http:
            model.root_client = OpenAI(api_key=KEY, base_url=ENDPOINT, max_retries=0, http_client=http)
            model.client = model.root_client.chat.completions
            assert gateway(model).invoke(messages(), kind="agent", label="wire", max_tokens=8).text == "ok"
        assert len(bodies) == 1 and rows(binding)[0]["request_sha256"] == sp.hash_payload(bodies[0])
        assert "timeout" not in bodies[0] and "extra_body" not in bodies[0]
        if model_name == "glm-5.3":
            assert bodies[0]["max_tokens"] == bodies[0]["max_completion_tokens"] == 8


def test_factory_alias_is_not_the_qualified_billing_model(tmp_path, monkeypatch):
    with run_authority(tmp_path, monkeypatch, model="glm-5.3", alias="glm") as binding:
        FakeHTTP(monkeypatch)
        monkeypatch.setenv("LLM_API_KEY", KEY)
        created = install_factory_dependencies(monkeypatch, model="glm-5.3", api_key="$LLM_API_KEY", alias="glm")
        args = types.SimpleNamespace(model="glm", config=None)
        gw = lr._default_gateway_factory(args, None, None, lr.resolve_preset("quick", {}))
        assert gw.invoke(messages(), kind="agent", label="alias", max_tokens=8).text == "ok"
        assert created[0]["model"] == "glm-5.3" and created[0]["api_key"] == KEY
        assert json.loads(rows(binding)[0]["envelope"])["model"] == "glm-5.3"


def test_finalize_extraction_does_not_convert_stop_into_deterministic_output(tmp_path, monkeypatch):
    with run_authority(tmp_path, monkeypatch) as binding:
        model = FakeModel([TimeoutError("unknown finalize transport")])
        engine, _, _, _ = make_engine(tmp_path, model)
        with pytest.raises(sp.SpendingStop):
            engine._structured("Official capacity report " * 40, rg.Deadline(30))
        assert len(model.calls) == len(rows(binding)) == 1
        assert not (engine.work / "extract/facts.json").exists()


def test_singleflight_leader_stop_never_redispatches_followers(tmp_path, monkeypatch):
    with run_authority(tmp_path, monkeypatch) as binding:
        http = FakeHTTP(monkeypatch, status=503)
        tools, gw = research_tools(tmp_path), gateway(FakeModel())
        with pytest.raises(sp.SpendingStop):
            gw.fan_out([lambda: tools.search("same failing query", agent_id="K1") for _ in range(4)], warm_first=False)
        assert len(http.posts) == len(rows(binding)) == 1


@pytest.mark.parametrize("unpriced", ["digest_auth", "request_hook", "response_hook"])
def test_http_auth_and_hooks_cannot_resend_or_mutate_beneath_sdk(tmp_path, monkeypatch, unpriced):
    import httpx
    from openai import OpenAI
    with run_authority(tmp_path, monkeypatch) as binding:
        sent = []
        class Transport(httpx.BaseTransport):
            _pool = types.SimpleNamespace(_retries=0)
            def handle_request(self, request):
                sent.append(request)
                return httpx.Response(401, headers={"www-authenticate": 'Digest realm="test", nonce="synthetic", qop="auth"'})
        with httpx.Client(transport=Transport(), follow_redirects=False, trust_env=False) as http:
            if unpriced == "digest_auth": http.auth = httpx.DigestAuth("synthetic", "synthetic")
            elif unpriced == "request_hook": http.event_hooks["request"] = [lambda request: request.headers.update({"x-mutated": "1"})]
            else: http.event_hooks["response"] = [lambda response: None]
            model = FakeModel()
            model.root_client = OpenAI(api_key=KEY, base_url=ENDPOINT, max_retries=0, http_client=http)
            model.client = model.root_client.chat.completions
            with pytest.raises(sp.SpendingStop):
                gateway(model).invoke(messages(), kind="agent", label="hidden-dispatch", max_tokens=8)
        assert not sent and not rows(binding)


def test_invalid_route_does_not_reconstruct_sdk_before_denial(tmp_path, monkeypatch):
    with run_authority(tmp_path, monkeypatch) as binding:
        model = FakeModel()
        model.openai_api_base = model.root_client.base_url = "https://unpriced.invalid/v1"
        model.max_retries = model.root_client.max_retries = 2
        with pytest.raises(sp.SpendingStop):
            gateway(model)
        assert model.state["copies"] == 0 and not model.calls and not rows(binding)


@pytest.mark.parametrize("mismatch", ["missing_carrier", "question", "model", "depth", "language", "authority", "out_dir"])
def test_loaded_child_request_scope_denied_before_gateway(tmp_path, monkeypatch, mismatch):
    with run_authority(tmp_path, monkeypatch) as binding:
        output = Path(binding["root"]) / "app/backend/uploads/pipelines" / binding["pipeline_id"] / "handoff"
        output.mkdir(parents=True)
        prompt_file = output / "prompt.txt"
        prompt_file.write_text("What is official capacity?\n")
        args = types.SimpleNamespace(model=MODEL, depth="quick", target_language="English", no_actors=True,
                                     forecast_authority="target-first-v1", prompt_file=str(prompt_file))
        # Bootstrap validated the first bytes. The producer's later read is the
        # authoritative input to the linear engine and must be checked again.
        if mismatch == "question": prompt_file.write_text("A different unauthorized question\n")
        elif mismatch == "missing_carrier": (Path(binding["root"]) / "control/request.json").unlink()
        elif mismatch == "model": args.model = "unapproved-alias"
        elif mismatch == "depth": args.depth = "deep"
        elif mismatch == "language": args.target_language = None
        elif mismatch == "authority": args.forecast_authority = None
        elif mismatch == "out_dir": output = tmp_path / "wrong-handoff"
        loaded = prompt_file.read_text().strip()
        constructed = []
        def factory(*args):
            constructed.append(True)
            raise AssertionError("scope denial must precede gateway construction")
        meta = {"status": "running"}
        with pytest.raises(sp.SpendingStop):
            lr.run(loaded, output, args, meta, None, lambda: None, gateway_factory=factory)
        assert not constructed and not rows(binding)
        assert meta["status"] == "failed"
        assert not (output / "v3").exists()


def test_loaded_child_request_keeps_authorized_simulation_scope(tmp_path, monkeypatch):
    with run_authority(tmp_path, monkeypatch) as binding:
        output = Path(binding["root"]) / "app/backend/uploads/pipelines" / binding["pipeline_id"] / "handoff"
        args = types.SimpleNamespace(model=MODEL, depth="quick", target_language="English",
                                     forecast_authority="target-first-v1")
        before = sp.summary(binding)
        control = Path(binding["root"]) / "control/request.json"
        original = control.read_bytes()
        lr._validate_spending_request(" \nWhat is official capacity?\n", output, args, binding)
        assert control.read_bytes() == original
        assert sp.summary(binding) == before
        assert not rows(binding)
