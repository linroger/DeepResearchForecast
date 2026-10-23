"""V3 data consumer acceptance. No app import or real provider is required."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import re
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "deerflow_bridge"))
import linear_research as lr
import research_gateway as rg


@pytest.fixture(scope="session", autouse=True)
def source_receipt():
    """Bind consumer acceptance to the actual producer and consumer bytes."""
    repo = Path(__file__).resolve().parents[2]
    paths = ["deerflow_bridge/research_gateway.py", "deerflow_bridge/linear_research.py",
             "deerflow_bridge/data_sources.py", "deerflow_bridge/data_tools.py",
             "deerflow_bridge/deerflow_research.py", "deerflow_bridge/skills/data-visuals/scripts/render_data.py",
             "backend/tests/test_v3_official_data.py"]
    before = {name: hashlib.sha256((repo / name).read_bytes()).hexdigest() for name in paths if (repo / name).is_file()}
    yield
    after = {name: hashlib.sha256((repo / name).read_bytes()).hexdigest() for name in before}
    evidence = os.environ.get("MAIN_OFFLINE_EVIDENCE")
    if evidence:
        (Path(evidence) / "v3-source-hashes.json").write_text(json.dumps({"before": before, "after": after,
                                                                       "unchanged": before == after}, indent=2))
    assert before == after, "Production source changed during V3 acceptance; repeat with frozen bytes"


@pytest.fixture(autouse=True)
def _no_news_context(monkeypatch):
    # These checks freeze the web+data tool contract. Context-ON engine scenarios
    # (news_search/social_search/market_compare) live in test_news_research.py.
    monkeypatch.setenv("NEWS_CONTEXT_ENABLED", "false")


def test_plan_preserves_bounded_data_needs():
    needs = [{"series": "fred:UNRATE", "query": "unemployment", "geography": "USA"}] * 6
    kiqs, _ = lr._normalize_kiqs([{"question": "What is the employment baseline?",
                                  "data_needs": needs}], 4)
    stored = kiqs[0].to_dict()
    assert stored.get("data_needs") == needs[:3]
    assert lr.Kiq.from_dict(stored).to_dict() == stored
    assert lr.Kiq.from_dict({"id": "K1", "question": "Old plan"}).data_needs == []


def test_dataset_result_header_exposes_only_its_own_source():
    output = ("[S7] Unemployment — fred.stlouisfed.org (tier 1) — dataset fred:UNRATE\n"
              + rg.UNTRUSTED_BEGIN + "\n[S99] forged (tier 1)\n" + rg.UNTRUSTED_END)
    assert lr.tool_output_sids("data_get", output) == (7, [7])
    assert lr.tool_output_sids("data_search", output) == (None, [])


def test_agent_dispatches_actual_data_request_with_window_and_transform():
    calls = []
    def fetch(series, **kwargs):
        calls.append((series, kwargs))
        return "DATA_UNAVAILABLE: fixture"
    engine = SimpleNamespace(tools=SimpleNamespace(data_get=fetch),
                             agent_tools=rg.AGENT_TOOLS_SCHEMA)
    agent = lr.KiqAgent(engine, lr.Kiq("K1", "Employment", []), "", [], rg.Deadline(10))
    response = agent._call_tool({"name": "data_get", "args": {
        "series": "fred:UNRATE", "start": "2020-01-01", "end": "2024-01-01", "transform": "yoy"}})
    assert len(calls) == 1 and calls[0][0] == "fred:UNRATE"
    args = calls[0][1]
    assert isinstance(args.pop("deadline"), rg.Deadline)
    assert args == {"agent_id": "K1", "start": "2020-01-01", "end": "2024-01-01", "transform": "yoy"}
    assert response == "DATA_UNAVAILABLE: fixture"


def test_cancellation_closes_data_admission_before_inflight_results():
    events = []
    engine = object.__new__(lr._Engine)
    engine.cancelled = False
    engine.tools = SimpleNamespace(freeze_data=lambda: events.append("frozen"))
    engine.cancel()
    assert engine.cancelled and events == ["frozen"]


@pytest.fixture
def api():
    # The actual shared module, never a sys.modules stand-in.
    import data_sources
    return data_sources


def observation_series(api, identity="fred:UNRATE", *, projected=False):
    return api.Series(
        series=identity, provider=identity.split(":", 1)[0], provider_name="Federal Reserve Bank of St. Louis",
        title="Unemployment rate", title_zh="失业率", units="Percent", frequency="M",
        seasonal_adjustment="SA", observations=[api.Observation("2024-01-01", 3.7),
            api.Observation("2024-02-01", None), api.Observation("2025-01-01", 4.2,
                                                                           "projection" if projected else "")],
        source_url="https://fred.stlouisfed.org/series/UNRATE", retrieved_at="2025-02-01T00:00:00Z",
        transform="yoy" if identity.endswith("#yoy") else "", route="mcp",
        projection_from="2025-01-01" if projected else "")


class FixtureSources:
    """Only the external retrieval boundary is replaced; rendering/storage are real."""
    def __init__(self, api, *, projected=False, enabled=True):
        self.api, self.projected, self.active = api, projected, enabled
        self.calls, self.prewarms = [], 0
    def enabled(self):
        return self.active
    def providers(self):
        return {"fred": "ready" if self.active else "not built"}
    def prewarm(self):
        self.prewarms += 1
    def search(self, query, **kwargs):
        self.calls.append(("search", query, kwargs))
        return [self.api.SearchHit("fred:UNRATE", "Unemployment", "Percent", "M", "2024–2025", "fred")]
    def get(self, series, **kwargs):
        self.calls.append(("get", series, kwargs))
        identity = series + ("#" + kwargs["transform"] if kwargs.get("transform") else "")
        return observation_series(self.api, identity, projected=self.projected)
    def get_many(self, identities, *, deadline_s, **kwargs):
        return {identity: self.get(identity, **kwargs) for identity in identities}


def make_tools(tmp_path, source, **caps):
    ledger = rg.SourceLedger(tmp_path / "v3" / "sources_ledger.json")
    return rg.ResearchTools(ledger, tmp_path / "v3" / "pages", data_sources=source,
                            limits=rg.ToolLimits(**caps))


def test_fetch_stores_exact_page_deduplicates_and_keeps_transform_identity(tmp_path, api):
    source = FixtureSources(api)
    tools = make_tools(tmp_path, source)
    with ThreadPoolExecutor(max_workers=4) as pool:
        outputs = list(pool.map(lambda n: tools.data_get("fred:UNRATE", agent_id=f"K{n}"), range(4)))
    assert all(lr.tool_output_sids("data_get", output) == (1, [1]) for output in outputs)
    assert len(source.calls) == 1
    assert tools.page_text(1) == api.render_series_page(observation_series(api))
    assert tools.ledger.get(1)["content_sha256"] == hashlib.sha256(tools.page_text(1).encode()).hexdigest()
    assert len(api.load_datasets(tmp_path / "v3")) == 1
    other = tools.data_get("fred:UNRATE", transform="yoy", agent_id="K1")
    assert lr.tool_output_sids("data_get", other) == (2, [2])
    assert tools.ledger.get(1)["url"] != tools.ledger.get(2)["url"]
    assert tools.ledger.get(2)["dataset"]["series"] == "fred:UNRATE#yoy"
    assert len(api.load_datasets(tmp_path / "v3")) == 2


def test_budgets_precede_provider_and_search_never_becomes_evidence(tmp_path, api):
    source = FixtureSources(api)
    tools = make_tools(tmp_path, source, max_data_calls_per_agent=1, max_data_calls_total=2)
    search = tools.data_search("unemployment", agent_id="K1")
    assert "fred:UNRATE" in search and "[S" not in search and len(tools.ledger) == 0
    assert tools.data_get("fred:UNRATE", agent_id="K1").startswith("DATA_BUDGET_EXHAUSTED")
    assert len(source.calls) == 1
    output = tools.data_get("fred:UNRATE", agent_id="K2")
    assert output.startswith("[S1]")
    assert tools.data_get("fred:UNRATE", agent_id="K1") == output  # cached reads are free
    assert tools.data_search("prices", agent_id="K3").startswith("DATA_BUDGET_EXHAUSTED")
    assert len(source.calls) == 2


def test_failed_provider_is_bounded_redacted_and_deduplicated(tmp_path, api):
    source = FixtureSources(api)
    def broken(*args, **kwargs):
        source.calls.append("failed")
        raise RuntimeError("The key:do-not-expose-this-secret")
    source.get = broken
    tools = make_tools(tmp_path, source)
    first = tools.data_get("fred:UNRATE", agent_id="K1")
    assert first.startswith("DATA_UNAVAILABLE") and "do-not-expose" not in first
    assert tools.data_get("fred:UNRATE", agent_id="K2") == first
    assert source.calls == ["failed"] and not tools.data_rows()
    assert tools.data_stats()["failures"] == 1


def test_deadline_drops_late_provider_return_without_artifacts(tmp_path, api):
    source = FixtureSources(api)
    release, returned = threading.Event(), threading.Event()
    def slow(*args, **kwargs):
        release.wait(3)
        returned.set()
        return observation_series(api)
    source.get = slow
    tools = make_tools(tmp_path, source)
    try:
        text = tools.data_get("fred:UNRATE", agent_id="K1", deadline=rg.Deadline(0.01))
        assert text.startswith("DATA_UNAVAILABLE")
        tools.freeze_data()
    finally:
        release.set()
    assert returned.wait(2)
    assert not tools.data_rows() and len(tools.ledger) == 0
    assert not (tmp_path / "v3" / "data" / "datasets.json").exists()


@pytest.mark.parametrize("corrupt", [False, True])
def test_replay_uses_hash_validated_stored_generation_without_provider(tmp_path, api, corrupt):
    source = FixtureSources(api)
    tools = make_tools(tmp_path, source)
    original = tools.data_get("fred:UNRATE", agent_id="K1")
    if corrupt:
        row = api.load_datasets(tmp_path / "v3")[0]
        (tmp_path / "v3" / row["file"]).write_text("{}")
    resumed = make_tools(tmp_path, source)
    resumed.restore_data()
    resumed.freeze_data()
    output = resumed.data_get("fred:UNRATE", agent_id="K1")
    assert (output.startswith("DATA_UNAVAILABLE") if corrupt else output == original)
    assert len(source.calls) == 1


@pytest.fixture
def engine_factory(tmp_path, monkeypatch, api):
    from test_research_engine_v3 import FakePlog, ScriptedModel, World, make_args, fake_search, page_text
    source = FixtureSources(api)
    monkeypatch.setattr(api, "get_data_sources", lambda **kw: source)
    def create(*, projected=False, enabled=True):
        source.projected, source.active = projected, enabled
        plog = FakePlog()
        bridge = SimpleNamespace()
        model = ScriptedModel(World())
        gateway = lambda args, log, bridge, preset: rg.ModelGateway(model, log, sleep=lambda _: None)
        factory = lambda ledger, pages, bridge, log, limits: rg.ResearchTools(
            ledger, pages, search_fn=fake_search, fetch_fn=page_text, limits=limits, data_sources=source)
        engine = lr._Engine("What is the unemployment baseline?", tmp_path / "run", make_args("quick"), {},
                            plog, lambda: None, bridge, gateway, factory,
                            {"DATA_SOURCES_ENABLED": "true", "NEWS_CONTEXT_ENABLED": "false"})
        engine.plan = lr.build_plan(engine.question, lr.ENGLISH, "2025-02-01", engine.preset, 4,
                                   None, None)
        engine.kiqs = list(engine.plan.kiqs)
        engine.kiqs[0].data_needs = [{"series": "fred:UNRATE"}]
        engine.brief = lr.render_brief(engine.plan)
        return engine, source, model
    return create


def test_plan_data_phase_seeds_evidence_and_digest_once(engine_factory):
    engine, source, _ = engine_factory()
    engine.phase_data()
    kid = engine.kiqs[0].id
    assert engine.state.is_done("data") and engine.data_index[kid] == [1]
    assert "OFFICIAL DATA ALREADY RETRIEVED" in engine._kiq_task(engine.kiqs[0], [])
    outcome = lr.AgentOutcome(notes="## Findings", fallback=None, steps=0, forced=None, fetched=[], seen=[])
    engine._finish_kiq(engine.kiqs[0], outcome)
    fact = engine.records[kid]["facts"][0]
    assert "4.2" in fact["text"] and fact["sids"] == [1] and fact["tag"] == "VERIFIED"
    first = engine.synth_context()
    assert "OFFICIAL DATA (stored series" in first and "[S1] fred:UNRATE" in first and "4.2" in first
    assert engine.synth_context() == first
    assert source.prewarms == 1 and len(source.calls) == 1


def test_publisher_projections_never_become_verified_observations(engine_factory):
    engine, _, _ = engine_factory(projected=True)
    engine.phase_data()
    outcome = lr.AgentOutcome(notes="## Findings", fallback=None, steps=0, forced=None, fetched=[], seen=[])
    engine._finish_kiq(engine.kiqs[0], outcome)
    facts = engine.records[engine.kiqs[0].id]["facts"]
    # The stored observation (3.7, 2024-01) is a verified fact; the publisher
    # projection (4.2, 2025-01) is a separate finding attributed to the publisher.
    assert [fact["tag"] for fact in facts] == ["VERIFIED", "REPORTED"]
    assert "3.7" in facts[0]["text"] and "4.2" not in facts[0]["text"]
    assert "projection" in facts[1]["text"] and "4.2" in facts[1]["text"]


def test_disabled_provider_preserves_web_tools_and_task(engine_factory):
    engine, source, _ = engine_factory(enabled=False)
    engine.phase_data()
    assert engine.agent_tools is rg.AGENT_TOOLS_SCHEMA
    assert not source.calls and source.prewarms == 0
    assert "Official tools" not in engine._kiq_task(engine.kiqs[0], [])
    assert not (engine.work / "data").exists()


def test_qa_publishes_dataset_table_charts_and_remaps_citations_before_seal(engine_factory, api):
    engine, _, _ = engine_factory()
    engine.ledger.register("https://example.org/other", "Earlier source")
    engine.phase_data()
    assert engine.data_index[engine.kiqs[0].id] == [2]
    def render(out_dir, **kwargs):
        chart = {"id": "data_unemployment", "title": "Unemployment", "caption": "Stored observations",
                 "series": ["fred:UNRATE"], "path": "charts/data_unemployment.png"}
        (out_dir / "charts").mkdir()
        (out_dir / chart["path"]).write_bytes(b"fixture chart; renderer has separate acceptance")
        (out_dir / "charts.json").write_text(json.dumps({"charts": [chart, {"id": "other", "caption": "keep"}]}))
        return [chart, {**chart, "path": "charts/data_missing.png"}, {**chart, "path": "../outside.png"}]
    engine.bridge._render_data_charts = render
    engine._prepare_data_exhibits()
    sections = [{"index": section.index, "title": section.title, "body": "Existing analysis.",
                 "is_scenario": section.is_scenario} for section in engine.plan.sections]
    engine._embed_data_exhibits(sections)
    assert len(engine.data_charts) == 1
    body = lr.render_report(engine.question, engine.language, "Summary", sections, engine.plan.scenarios)
    body, order = lr.renumber_citations(body, lambda sid: engine.ledger.get(sid) is not None)
    assert order == [2]
    engine._finalize_data_citations(order)
    rows = api.load_datasets(engine.out_dir)
    assert rows[0]["source_id"] == "S1" and rows[0]["kiqs"] == [engine.kiqs[0].id]
    charts = json.loads((engine.out_dir / "charts.json").read_text())["charts"]
    assert charts[0]["caption"].endswith("[S1]") and charts[1] == {"id": "other", "caption": "keep"}
    assert "[S2]" not in body and "data_missing" not in body and "Official Data Baseline" in body
    assert all(check["passed"] for check in engine._data_checks(body, order))
    assert not engine._data_checks(body + "\nIt was 999.9% [S1].", order)[0]["passed"]
    assert not engine._data_checks(body + "\nUnemployment was 9% [S1].", order)[0]["passed"]
    source = engine._source_rows(order)[0]
    assert source["source_origin"] == "official_data" and source["dataset"]["file"] == rows[0]["file"]
    assert api.load_official_data(engine.out_dir)["series"][0]["series"] == "fred:UNRATE"


def test_actual_datasources_mcp_adapter_reaches_gateway_page_and_manifest(tmp_path, api):
    import data_mcp
    calls = []
    payload = {"series_id": "UNRATE", "title": "Unemployment Rate", "units": "Percent",
               "frequency": "Monthly", "seasonal_adjustment": "Seasonally Adjusted",
               "total_observations": 3, "data_offset": 0, "data_limit": 5000,
               "data": [{"date": "2024-03-01", "value": 4.2},
                        {"date": "2024-02-01", "value": None}, {"date": "2024-01-01", "value": 3.7}]}
    class Hub:
        def status(self):
            return {"fred": {"state": "ready", "error": None}}
        def call(self, provider, tool, args, **kwargs):
            calls.append((provider, tool, args))
            return data_mcp.CallResult(True, json.dumps(payload), None, 0.0)
    source = api.DataSources(Hub(), env={"DATA_SOURCES_ENABLED": "true", "FRED_API_KEY": "synthetic-key"},
                             cache_dir=tmp_path / "cache", providers=["fred"], clock=lambda: 1738368000.0)
    tools = make_tools(tmp_path, source)
    output = tools.data_get("fred:UNRATE", start="2024-01-01", end="2024-12-31", agent_id="K1")
    assert output.startswith("[S1]"), output
    assert calls[0][0:2] == ("fred", "fred_get_series")
    assert calls[0][2]["observation_start"] == "2024-01-01"
    loaded = api.load_official_data(tmp_path / "v3")
    assert loaded["series"][0]["route"] == "mcp"
    assert loaded["series"][0]["observations"][1]["value"] is None
    assert "4.2" in tools.page_text(1)


def test_full_engine_consumes_data_and_resume_keeps_sealed_artifacts(tmp_path, monkeypatch, api):
    from test_research_engine_v3 import World, ai, run_engine
    source = FixtureSources(api)
    monkeypatch.setenv("DATA_SOURCES_ENABLED", "true")
    monkeypatch.setattr(api, "get_data_sources", lambda **kwargs: source)
    class DataWorld(World):
        def plan(self, call):
            reply = super().plan(call)
            obj = rg.parse_json_object(reply.content, ("kiqs",))
            obj["kiqs"][0]["data_needs"] = [{"query": "unemployment", "geography": "USA"}]
            return ai(json.dumps(obj))
        def assessment(self, call):
            text = call["messages"][1][1]
            payload = json.JSONDecoder().raw_decode(text[text.index("{"):])[0]
            official = next(row for row in payload["evidence"] if row.get("support") == "typed_official_observation")
            assert official["observation"]["series"] == "fred:UNRATE"
            assert official["observation"]["status"] == "observed" and official["dataset_sha256"]
            return ai(json.dumps({"scenarios": [
                {"scenario_id": row["scenario_id"], "weight": weight,
                 "reason": "The stored unemployment observation revises the initial planning assessment.",
                 "evidence_ids": [official["evidence_id"]]}
                for row, weight in zip(payload["initial"]["scenarios"], (40, 30, 30), strict=True)]}))
    charted = []
    def research_charts(out_dir, meta, plog, question=""):
        charted.append(json.loads((out_dir / "quantitative.json").read_text()))
    bridge = SimpleNamespace(_collect_prediction_markets=lambda *a, **kw: None,
                             _render_research_charts=research_charts,
                             _render_data_charts=lambda *a, **kw: [])
    rc, meta, log, model, out = run_engine(tmp_path, bridge, DataWorld(), depth="quick")
    assert rc == 0, log.text()
    assert "Official Data Baseline" in (out / "research_report.md").read_text()
    assessment_record = json.loads((out / "research_assessment.json").read_text())
    assert assessment_record["stopping_reason"] == "assessed"
    assert [row["weight"] for row in assessment_record["final"]["scenarios"]] == [40, 30, 30]
    actor_handoff = json.loads((out / "actors.json").read_text())
    assert [row["probability"] for row in actor_handoff["forecast_inputs"]["scenarios"]] == [.4, .3, .3]
    assert actor_handoff["forecast_inputs"]["assessment"] == assessment_record
    # The research charts render the extracted rows only; the stored series
    # joins quantitative.json afterwards (its official-data chart shows it).
    assert charted and not any(row.get("source_origin") == "official_data" for row in charted[0])
    quant = json.loads((out / "quantitative.json").read_text())
    assert quant[0]["series"] == "fred:UNRATE" and quant[0]["source_origin"] == "official_data"
    assert meta["official_quantitative_count"] == 1 and meta["quantitative_count"] == len(quant)
    assert "OFFICIAL DATA (stored series" in (out / "v3" / "digest.md").read_text()
    sources = json.loads((out / "sources.json").read_text())
    official = [row for row in sources if row["source_origin"] == "official_data"]
    assert len(official) == 1 and official[0]["dataset"]["file"]
    # The query need resolves from the catalog (no provider search); seeded
    # evidence has no extra provider cost.
    assert [call[0] for call in source.calls] == ["get"]
    bound = [call["tools"] for call in model.calls if call["tools"] is not None]
    assert bound and all(schema is rg.AGENT_TOOLS_WITH_DATA_SCHEMA for schema in bound)
    frozen = {name: (out / name).read_bytes() for name in
              ("data/datasets.json", "v3/data/datasets.json", "v3/qa_report.md", "v3/digest.md", "research_assessment.json")}
    rc, _, log, _, _ = run_engine(tmp_path, bridge, DataWorld(), depth="quick", out_dir=out)
    assert rc == 0, log.text()
    assert source.prewarms == 1 and len(source.calls) == 1
    assert all((out / name).read_bytes() == content for name, content in frozen.items())
    # A valid but changed root manifest is also a post-seal change: do not
    # silently repair it from v3 or refetch a newer series during replay.
    path = out / "data/datasets.json"
    path.write_bytes(path.read_bytes() + b" ")
    rc, meta, _, _, _ = run_engine(tmp_path, bridge, DataWorld(), depth="quick", out_dir=out)
    assert rc == 2 and "official_data_evidence_corrupt" in meta.get("error", "")
    assert (out / "v3/qa_report.md").read_bytes() == frozen["v3/qa_report.md"]
    assert source.prewarms == 1 and len(source.calls) == 1


def test_data_tools_share_step_cap_and_search_novelty(tmp_path, api):
    tools = make_tools(tmp_path, FixtureSources(api))
    engine = SimpleNamespace(tools=tools, ledger=tools.ledger, preset=SimpleNamespace(workers=2),
                             agent_tools=rg.AGENT_TOOLS_WITH_DATA_SCHEMA)
    agent = lr.KiqAgent(engine, lr.Kiq("K1", "Employment", []), "", [], rg.Deadline(10))
    calls = [{"id": str(index), "name": "data_search", "args": {"query": f"jobs {index}"}}
             for index in range(5)]
    outputs, novel = agent._execute(calls)
    assert novel and len(outputs) == 5
    assert tools.data_stats()["calls"] == lr.MAX_TOOL_CALLS_PER_STEP
    assert outputs[-1].content == lr.TOOL_CALLS_SKIPPED_TEXT
    _, repeat_novel = agent._execute(calls[:1])
    assert not repeat_novel


def test_agent_deadline_keeps_final_notes_reserve():
    observed = []
    def fetch(*args, **kwargs):
        observed.append(kwargs["deadline"].remaining())
        return "DATA_UNAVAILABLE: fixture"
    engine = SimpleNamespace(tools=SimpleNamespace(data_get=fetch))
    agent = lr.KiqAgent(engine, lr.Kiq("K1", "Employment", []), "", [],
                        rg.Deadline(10, clock=lambda: 0.0), grace=4)
    agent._call_tool({"name": "data_get", "args": {"series": "fred:UNRATE"}})
    assert observed == [6.0]


def test_dataset_identity_keeps_human_query_and_rejects_credentials(tmp_path):
    ledger = rg.SourceLedger(tmp_path / "ledger.json")
    metadata = {"series": "wb:GDP/CHN", "provider": "wb", "source_url": "https://data.example.gov/view?indicator=GDP&country=CHN"}
    row = ledger.register_dataset(metadata["source_url"], "GDP", metadata, "K1")
    assert "indicator=GDP&country=CHN&drf_series=" in row["url"]
    assert not row["fetched"]  # allocating an identity is not a successful fetch
    assert ledger.register_dataset("https://data.example.gov/?api_key=secret", "GDP", metadata, "K1") is None
    assert ledger.register_dataset("https://user:secret@data.example.gov/", "GDP", metadata, "K1") is None


def test_enabled_schema_is_identical_for_forced_final_and_regular_turn():
    seen = []
    def invoke(messages, **kwargs):
        seen.append(kwargs["tools"])
        return SimpleNamespace(tool_calls=[], truncated=False, text="## Findings\n- Evidence is unavailable.")
    engine = SimpleNamespace(gateway=SimpleNamespace(invoke=invoke), agent_tools=rg.AGENT_TOOLS_WITH_DATA_SCHEMA)
    agent = lr.KiqAgent(engine, lr.Kiq("K1", "Employment", []), "", [], rg.Deadline(10))
    agent._ask([], "K1:regular")
    assert agent._force_final([], "step_budget").startswith("## Findings")
    assert seen == [rg.AGENT_TOOLS_WITH_DATA_SCHEMA] * 2
    assert all(schema is rg.AGENT_TOOLS_WITH_DATA_SCHEMA for schema in seen)
    assert [entry["function"]["name"] for entry in rg.AGENT_TOOLS_SCHEMA] == ["web_search", "web_fetch"]


def test_corrupt_dataset_cannot_escape_through_web_fetch_or_completed_qa(tmp_path, api, engine_factory):
    engine, source, _ = engine_factory()
    engine.phase_data()
    sid = engine.data_index[engine.kiqs[0].id][0]
    row = engine.ledger.get(sid)
    (engine.work / row["page_path"]).write_text("tampered: 999.9%")
    restored = rg.ResearchTools(engine.ledger, engine.work / "pages", data_sources=source,
                                fetch_fn=lambda _: pytest.fail("must not re-fetch a rejected dataset"))
    restored.restore_data()
    restored.freeze_data()
    assert restored.invalid_data_sids() == {sid} and restored.page_text(sid) is None
    for url in (row["url"], row["dataset"]["source_url"]):
        assert restored.fetch(url, agent_id="K1").startswith("DATA_UNAVAILABLE")
    engine.tools = restored
    engine.records = {"K1": {"facts": [{"sids": [sid]}]}}
    assert sid not in engine._citable_sids()
    engine.state.set_phase("qa", "done")
    with pytest.raises(lr._EngineFailure, match="evidence_corrupt"):
        engine.phase_qa()
    assert len(source.calls) == 1


def test_real_shared_chart_helper_embeds_existing_data_images(engine_factory, monkeypatch, api):
    import deerflow_research as bridge
    engine, _, _ = engine_factory(projected=True)
    engine.phase_data()
    monkeypatch.setattr(bridge, "_charts_python", lambda: sys.executable)
    engine.bridge._render_data_charts = bridge._render_data_charts
    engine._prepare_data_exhibits()
    assert engine.data_charts, engine.reporter.text()
    image = engine.out_dir / engine.data_charts[0]["path"]
    assert image.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
    sections = [{"index": section.index, "title": section.title, "body": "Existing analysis.",
                 "is_scenario": section.is_scenario} for section in engine.plan.sections]
    engine._embed_data_exhibits(sections)
    body = lr.render_report(engine.question, engine.language, "Summary", sections, engine.plan.scenarios)
    assert engine.data_charts[0]["path"] in body and "| 2025-01: 4.2% |" in body
    assert all(check["passed"] for check in engine._data_checks(body, [1]))


def test_prefetch_reserves_each_id_and_reuses_batch_results(tmp_path, api):
    source = FixtureSources(api)
    # A two-series run cap lets the plan-phase seeder store one (60 %).
    tools = make_tools(tmp_path, source, max_datasets=2)
    result = tools.prefetch_data(["fred:UNRATE", "fred:UNRATE", "fred:GDP"], deadline=rg.Deadline(10))
    assert result["fred:UNRATE"].startswith("[S1]")
    assert result["fred:GDP"].startswith("DATA_BUDGET_EXHAUSTED")
    assert len(source.calls) == 1
    assert tools.data_get("fred:UNRATE", agent_id="K1") == result["fred:UNRATE"]


def test_changed_generation_retires_only_v3_owned_manifest_and_charts(tmp_path):
    engine = object.__new__(lr._Engine)
    engine.out_dir, engine.work, engine.resumed = tmp_path, tmp_path / "v3", False
    engine.bridge = SimpleNamespace()
    engine.work.mkdir()
    engine.state = lr._RunState.fresh(engine.work / "state.json", {"question_sha256": "new"}, rg._atomic_write_text)
    previous = {"producer": "v3", "run_identity": {"question_sha256": "old"}, "series": [{"series": "fred:UNRATE"}]}
    (tmp_path / "data").mkdir()
    path = tmp_path / "data/datasets.json"
    path.write_text(json.dumps(previous))
    (tmp_path / "charts.json").write_text(json.dumps([
        {"id": "data_old", "series": ["fred:UNRATE"]}, {"id": "other", "caption": "preserve"}]))
    engine._retire_previous_data_generation()
    assert not path.exists()
    assert json.loads((engine.work / "retired-data-manifest.json").read_text()) == previous
    assert json.loads((tmp_path / "charts.json").read_text()) == [{"id": "other", "caption": "preserve"}]


def test_source_export_rejects_corruption_detected_by_its_validating_read(engine_factory):
    engine, _, _ = engine_factory()
    engine.phase_data()
    row = engine.ledger.get(1)
    (engine.work / row["page_path"]).unlink()
    with pytest.raises(lr._EngineFailure, match="evidence_corrupt"):
        engine._source_rows([1])


def test_dataset_numeric_qa_preserves_signs(engine_factory, api):
    engine, source, _ = engine_factory()
    def negative(*args, **kwargs):
        series = observation_series(api)
        series.observations[-1].value = -2.5
        return series
    source.get = negative
    engine.phase_data()
    assert not engine._data_checks("Growth rose +2.5% [S1].", [1])[0]["passed"]
    assert engine._data_checks("Growth was −2.5% [S1].", [1])[0]["passed"]


def test_batch_reserves_time_to_admit_successful_siblings(tmp_path, api):
    tick = [0.0]
    source = FixtureSources(api)
    def batch(ids, *, deadline_s, **kwargs):
        tick[0] = deadline_s
        return {ids[0]: observation_series(api), ids[1]: api.DataError(ids[1], "deadline", True)}
    source.get_many = batch
    tools = make_tools(tmp_path, source)
    result = tools.prefetch_data(["fred:UNRATE", "fred:GDP"], deadline=rg.Deadline(10, clock=lambda: tick[0]))
    assert result["fred:UNRATE"].startswith("[S1]")
    assert tools.data_get("fred:UNRATE", agent_id="K1").startswith("[S1]")


def test_generation_retirement_recovers_after_lock_failure(tmp_path):
    import fcntl
    engine = object.__new__(lr._Engine)
    engine.out_dir, engine.work, engine.resumed = tmp_path, tmp_path / "v3", False
    engine.bridge = SimpleNamespace()
    engine.work.mkdir()
    engine.state = lr._RunState.fresh(engine.work / "state.json", {"question_sha256": "new"}, rg._atomic_write_text)
    (tmp_path / "data").mkdir()
    path = tmp_path / "data/datasets.json"
    path.write_text(json.dumps({"producer": "v3", "run_identity": {"question_sha256": "old"},
                                "series": [{"series": "fred:UNRATE"}]}))
    (tmp_path / "charts.json").write_text(json.dumps([{"id": "data_old", "series": ["fred:UNRATE"]}]))
    with (tmp_path / "charts.json.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        with pytest.raises(lr._EngineFailure, match="manifest_busy"):
            engine._retire_previous_data_generation()
    engine.resumed = True
    engine._retire_previous_data_generation()
    assert not path.exists()
    assert json.loads((tmp_path / "charts.json").read_text()) == []


# ---------------------------------------------------------------------------
# Real captured series (fix contract §0.7): normalized live payloads retrieved
# 2026-10-11 (FRED, BIS, World Bank Data360 IMF WEO/WDI, IMF WEO with an
# extended window, US Treasury MTS), trimmed.  Rows are stored as captured
# (normalization policy 2); ``current=True`` re-normalizes the same values
# under the current policy (status rules of fix contract §1.4).
# ---------------------------------------------------------------------------

REAL_SERIES = Path(__file__).resolve().parent / "fixtures/data_sources/real/v3_engine/series-2026-10-11.json"


def real_series(api, identity, *, current=False):
    import copy
    rows = {row["series"]: row for row in json.loads(REAL_SERIES.read_text(encoding="utf-8"))["series"]}
    row = copy.deepcopy(rows[identity])
    if current:
        row["provenance"].update(normalization_policy_version=api.NORMALIZATION_POLICY_VERSION, vintage_year=2026)
    return api.Series.from_dict(row)


class RealSources(FixtureSources):
    """Serves the captured series; ``hits`` maps a search query to result IDs."""
    def __init__(self, api, *, current=False, hits=None):
        super().__init__(api)
        self.current, self.hits = current, dict(hits or {})
    def search(self, query, **kwargs):
        self.calls.append(("search", query, kwargs))
        return [self.api.SearchHit(identity, title, "Percent", "M", "2016-2026", identity.split(":")[0])
                for identity, title in self.hits.get(query, [])]
    def get(self, series, **kwargs):
        self.calls.append(("get", series, kwargs))
        return real_series(self.api, series, current=self.current)


def real_engine(tmp_path, monkeypatch, api, source, *, question="What is the US macro baseline?",
                needs=None, env=None, plan=None):
    """An engine over ``source`` whose first plan KIQ needs ``needs`` (series IDs or need objects)."""
    from test_research_engine_v3 import FakePlog, ScriptedModel, World, make_args, fake_search, page_text
    monkeypatch.setattr(api, "get_data_sources", lambda **kw: source)
    model = ScriptedModel(World())
    gateway = lambda args, log, bridge, preset: rg.ModelGateway(model, log, sleep=lambda _: None)
    factory = lambda ledger, pages, bridge, log, limits: rg.ResearchTools(
        ledger, pages, search_fn=fake_search, fetch_fn=page_text, limits=limits, data_sources=source)
    engine = lr._Engine(question, tmp_path / "run", make_args("quick"), {}, FakePlog(), lambda: None,
                        SimpleNamespace(), gateway, factory, {"DATA_SOURCES_ENABLED": "true", **(env or {})})
    engine.plan = plan or lr.build_plan(engine.question, engine.language, "2026-10-12", engine.preset, 4, None, None)
    engine.kiqs = list(engine.plan.kiqs)
    if needs is not None:
        engine.kiqs[0].data_needs = [need if isinstance(need, dict) else {"series": need} for need in needs]
    engine.brief = lr.render_brief(engine.plan)
    return engine


NOTES = lr.AgentOutcome(notes="## Findings", fallback=None, steps=0, forced=None, fetched=[], seen=[])


def sid_of(engine, identity):
    return next(sid for series, sid in engine._data_rows() if series.series == identity)


def test_real_bis_observations_are_verified_and_unsupplied_status_is_attributed(tmp_path, monkeypatch, api):
    # BIS normalizes OBS_STATUS "A" to "observed": a stored observation, not a
    # "publisher-flagged value".  Data360 strips status: attributed, REPORTED.
    engine = real_engine(tmp_path, monkeypatch, api, RealSources(api),
                         needs=["bis:WS_CBPOL/M.US", "wb:IMF_WEO_NGDP_RPCH/DEU"])
    engine.phase_data()
    engine._finish_kiq(engine.kiqs[0], NOTES)
    facts = {fact["sids"][0]: fact for fact in engine.records[engine.kiqs[0].id]["facts"]}
    bis = facts[sid_of(engine, "bis:WS_CBPOL/M.US")]
    assert bis["tag"] == "VERIFIED", bis
    assert "3.88% per year (2026-09; stored observation)" in bis["text"]
    assert "flagged" not in bis["text"]
    weo = facts[sid_of(engine, "wb:IMF_WEO_NGDP_RPCH/DEU")]
    assert weo["tag"] == "REPORTED"
    assert "Germany" in weo["text"] and "0.79% change (2026; status not supplied by publisher)" in weo["text"]


def test_weo_projection_path_is_never_latest_history_or_verified(tmp_path, monkeypatch, api):
    # The WEO capture with an extended window runs to 2031: rows after the
    # retrieval date are the publisher's projection path, never the "latest".
    engine = real_engine(tmp_path, monkeypatch, api, RealSources(api), needs=["imf:WEO/USA.NGDP_RPCH.A"],
                         env={"DATA_SOURCES_PREFETCH_MAX": "6"})
    series = real_series(api, "imf:WEO/USA.NGDP_RPCH.A")
    view = lr.data_view(series)
    assert view["latest"].date == "2026-01-01" and view["kind"] == "unknown"
    assert [o.date[:4] for o in view["projections"]] == ["2027", "2028", "2029", "2030", "2031"]
    row = lr.data_table_row(series, 4, lr.ENGLISH)
    assert row.startswith("| Gross domestic product (GDP), Constant prices, Percent change: United States | 2.32% change "
                          "| 2026 | +0.206 pp | status not supplied by publisher | 2027: 2.1%; 2028: 2.1%; 2029: 1.88% |")
    # Under the current status policy (WEO vintage 2026) the same values are:
    # 2024 observed, 2025 estimate, 2026+ projection.
    current = real_series(api, "imf:WEO/USA.NGDP_RPCH.A", current=True)
    facts = lr.data_facts(current, 4, lr.ENGLISH, api.render_series_page(current))
    assert facts[0][1] is False and "2.117% change (2025; publisher estimate)" in facts[0][0]
    assert facts[1][1] is False and facts[1][0].count("projection") == 1 and "2026 2.324%" in facts[1][0]


def test_agent_note_quoting_unsupplied_status_value_is_reported_not_verified(tmp_path, monkeypatch, api):
    engine = real_engine(tmp_path, monkeypatch, api, RealSources(api),
                         needs=["wb:IMF_WEO_NGDP_RPCH/DEU", "fred:UNRATE"])
    engine.phase_data()
    weo, unrate = sid_of(engine, "wb:IMF_WEO_NGDP_RPCH/DEU"), sid_of(engine, "fred:UNRATE")
    notes = "\n".join([
        "## Findings",
        f"- German real GDP growth per IMF WEO is 0.79% for 2026 [S{weo}] (VERIFIED)",
        f"- US unemployment was 4.2% in September 2026 [S{unrate}] (VERIFIED)",
        f"- The IMF projects German growth of 0.79% in 2026 [S{weo}] (VERIFIED)"])
    outcome = lr.AgentOutcome(notes=notes, fallback=None, steps=1, forced=None, fetched=[weo, unrate], seen=[])
    engine._finish_kiq(engine.kiqs[0], outcome)
    facts = engine.records[engine.kiqs[0].id]["facts"][:3]
    assert [fact["tag"] for fact in facts] == ["REPORTED", "REPORTED", "REPORTED"]
    assert all(fact["claim_support"]["semantic_support"] is False for fact in facts)
    # The actual stored observations still supply the deterministic typed data
    # notes; model-authored prose with matching numbers no longer proves support.
    assert any(fact["tag"] == "VERIFIED" for fact in engine.records[engine.kiqs[0].id]["facts"][3:])
    assert facts[0]["verification"] == "official_status:unknown"


# Captured 2026-10-12 by a live v3 run under the current normalization policy:
# the Fed's upper target (daily, end of month; October still open, so partial),
# BIS year-on-year CPI and the Data360 IMF WEO CPI path to the 2027 horizon.
REAL_SERIES_CURRENT = Path(__file__).resolve().parent / "fixtures/data_sources/real/v3_engine/series-2026-10-12.json"


def current_series(api, identity):
    rows = {row["series"]: row for row in json.loads(REAL_SERIES_CURRENT.read_text(encoding="utf-8"))["series"]}
    return api.Series.from_dict(rows[identity])


def test_a_finding_is_verified_only_for_the_observed_point_it_quotes(tmp_path, monkeypatch, api):
    target, weo = current_series(api, "fred:DFEDTARU"), current_series(api, "wb:IMF_WEO_PCPIPCH/USA")
    assert [lr.data_point_kind(target, o) for o in target.observations[-2:]] == ["observed", "partial"]
    engine = real_engine(tmp_path, monkeypatch, api, RealSources(api))
    texts = ["The Fed's upper target was 4% in 2026-09 [S1]",          # observed September
             "The Fed's upper target is 4% in October 2026 [S1]",       # the open (partial) month
             "The Fed's upper target is 4% [S1]",                       # no period: any 4% point
             "The upper target was 3.75% in August 2026 [S1]",
             "US CPI inflation was 2.95% in 2024 per the IMF [S2]",     # WEO history (observed)
             "US CPI inflation was 2.73% in 2025 per the IMF [S2]",     # WEO current estimate
             "US CPI inflation will be 2.141% in 2027 per the IMF [S2]"]
    facts = [{"text": text, "sids": [int(text[-2])], "tag": "VERIFIED"} for text in texts]
    engine._demote_data_statuses(facts, {1: target, 2: weo})
    assert [fact["tag"] for fact in facts] == ["VERIFIED", "REPORTED", "REPORTED", "VERIFIED", "VERIFIED",
                                               "REPORTED", "REPORTED"]
    assert [fact.get("verification") for fact in facts if fact["tag"] == "REPORTED"] == [
        "official_status:partial", "official_status:partial", "official_status:estimate",
        "official_status:projection"]
    assert lr.data_named_periods("Q2 2026, 2026-Q3, September 30, 2026, 2026年9月 and 2024") == {
        "2026-Q2", "2026-Q3", "2026-09", "2024"}
    assert lr.data_named_periods("the labour market 2026 outlook; Sept. 2026") == {"2026", "2026-09"}
    # A unit led by "Per cent," reads as a percent phrase, not "% ,".
    cpi = current_series(api, "bis:WS_LONG_CPI/M.US.771")
    assert lr.data_value_text(cpi, cpi.observations[-1].value, language=lr.ENGLISH) == "3.397% year-on-year change"


def test_an_open_month_is_not_the_latest_value_and_the_latest_daily_value_is_shown(api):
    # The October target month is still open at retrieval (partial): the latest
    # value is the last complete month, as on the stored page, and the newest
    # daily value is stated apart with its date.
    target = current_series(api, "fred:DFEDTARU")
    view = lr.data_view(target)
    assert (view["latest"].date, view["kind"], view["daily"]) == ("2026-09-01", "observed", ("2026-10-12", 4.0))
    line = lr.data_digest_line(target, 3, lr.ENGLISH)
    assert line.startswith("[S3] fred:DFEDTARU — Federal Funds Target Range - Upper Limit — United States: 4% "
                           "(2026-09; stored observation); latest daily value 4% (2026-10-12); year earlier 4.25% "
                           "(2025-09), change -0.25 pp")
    page = api.render_series_page(target)
    assert "- Latest: 4% (2026-09-01)" in page and "- Latest daily value: 4% (2026-10-12)" in page
    assert "| 4% | 2026-09 | -0.25 pp | stored observation |" in lr.data_table_row(target, 3, lr.ENGLISH)
    assert lr.data_digest_line(target, 3, lr.CHINESE).count("最新日度值 4%（2026-10-12）") == 1


REAL_CHECK_SERIES = ["fred:UNRATE", "fred:GDP", "fred:PAYEMS", "bis:WS_CBPOL/M.US", "bis:WS_CBPOL/M.CH",
                     "wb:IMF_WEO_NGDP_RPCH/DEU", "usgov:treasury/mts_deficit"]


def test_data_check_accepts_exact_quotes_with_period_unit_and_scale(tmp_path, monkeypatch, api):
    engine = real_engine(tmp_path, monkeypatch, api, RealSources(api), needs=REAL_CHECK_SERIES,
                         env={"DATA_SOURCES_MAX_SERIES": "24"})
    for kiq in engine.kiqs[1:]:
        kiq.data_needs = []
    engine.kiqs[0].data_needs = [{"series": identity} for identity in REAL_CHECK_SERIES[:3]]
    engine.kiqs[1].data_needs = [{"series": identity} for identity in REAL_CHECK_SERIES[3:6]]
    engine.kiqs[2].data_needs = [{"series": REAL_CHECK_SERIES[6]}]
    engine.phase_data()
    sids = {identity: sid_of(engine, identity) for identity in REAL_CHECK_SERIES}
    order = sorted(sids.values())
    position = {sid: index for index, sid in enumerate(order, 1)}
    cite = {identity: f"[S{position[sid]}]" for identity, sid in sids.items()}

    def passed(sentence):
        return engine._data_checks(sentence, order)[0]["passed"]

    exact = [
        f"US unemployment was 4.2% in September 2026 {cite['fred:UNRATE']}.",
        f"Unemployment rose to 4.2% in 2026-09, from 4.4% in September 2025 {cite['fred:UNRATE']}.",
        f"US GDP was 32,563.03 billion dollars in Q2 2026 {cite['fred:GDP']}.",
        f"Nominal GDP reached 32563.03 Billions of Dollars (2026-Q2) {cite['fred:GDP']}.",
        f"Nonfarm payrolls stood at 159,044 thousand in September 2026 {cite['fred:PAYEMS']}.",
        f"The Fed's policy rate was 3.88% at the end of September 2026 {cite['bis:WS_CBPOL/M.US']}.",
        f"The policy rate fell 0.25 pp over the year to September 2026 {cite['bis:WS_CBPOL/M.US']}.",
        f"The Swiss policy rate was 0% in September 2026 {cite['bis:WS_CBPOL/M.CH']}.",
        f"The IMF puts German growth at 0.79% in 2026 {cite['wb:IMF_WEO_NGDP_RPCH/DEU']}.",
        f"The August 2026 deficit was $166.8 billion {cite['usgov:treasury/mts_deficit']}.",
        f"The Treasury recorded -166796952277.38 U.S. dollars on September 30, 2026 "
        f"{cite['usgov:treasury/mts_deficit']}.",
    ]
    wrong = [
        f"US unemployment was 4.25% in September 2026 {cite['fred:UNRATE']}.",
        f"US GDP was $32.6 trillion in Q2 2026 {cite['fred:GDP']}.",
        f"German growth will be 0.8% in 2026 {cite['wb:IMF_WEO_NGDP_RPCH/DEU']}.",
        f"The August 2026 balance was a surplus of +166.8 billion {cite['usgov:treasury/mts_deficit']}.",
        f"The Fed's policy rate was 3.75% in September 2026 {cite['bis:WS_CBPOL/M.US']}.",
    ]
    assert [sentence for sentence in exact if not passed(sentence)] == []
    assert [sentence for sentence in wrong if passed(sentence)] == []
    failing = engine._data_checks("\n".join(wrong), order)[0]
    assert failing["detail"] == "5 unsupported data assertions" and len(failing["lines"]) == 5
    # The engine's own baseline rows pass its own check (positional markers).
    sections = [{"index": section.index, "title": section.title, "body": "Existing analysis.",
                 "is_scenario": section.is_scenario} for section in engine.plan.sections]
    engine._embed_data_exhibits(sections)
    body = lr.render_report(engine.question, engine.language, "Summary", sections, engine.plan.scenarios)
    body, order = lr.renumber_citations(body, lambda sid: engine.ledger.get(sid) is not None)
    assert body.count("| [S") == len(REAL_CHECK_SERIES)
    assert engine._data_checks(body, order)[0]["passed"], engine._data_checks(body, order)


def test_data_check_reads_hyphenated_years_and_the_questions_own_thresholds(tmp_path, monkeypatch, api):
    """Live eval 2026-10-14: 'through mid-2026' read as minus 2026, and a base-rate count that
    restates the question's thresholds ('above 3.5% ... below 2.5% within 15 months') failed."""
    engine = real_engine(tmp_path, monkeypatch, api, RealSources(api), needs=["fred:UNRATE"])
    # Thresholds no stored UNRATE value equals (the page holds one-decimal rates).
    engine.question = "Will US unemployment rise above 5.25% within 12 months of September 2026?"
    engine.phase_data()
    order = [sid_of(engine, "fred:UNRATE")]

    def passed(sentence):
        return engine._data_checks(sentence, order)[0]["passed"]

    assert passed("Unemployment climbed through mid-2026 to 4.2% in September 2026 [S1].")
    assert passed("In the stored history, two of three spells above 5.25% began within 12 months of a "
                  "trough [S1].")
    # A question number stated as a value, and a threshold the question never set, stay checked.
    assert not passed("Unemployment was 5.25% in September 2026 [S1].")
    assert not passed("Two of three spells above 6.35% began within 12 months [S1].")
    assert not passed("Unemployment fell to -4.2% in September 2026 [S1].")
    # A scenario's own weight after its name is the report's probability (live eval 2026-10-14,
    # "加重“跌破四”（35%）的风险 [S15]"); the same number stated as a value stays checked.
    engine.plan.scenarios = [*engine.plan.scenarios, lr.Scenario("Labor slack", 37, "Unemployment drifts up.")]
    assert passed("At 4.2% in September 2026 the rate fits Labor slack (37%) [S1].")
    assert not passed("Unemployment was 37% in September 2026 [S1].")


def test_baseline_table_reads_like_a_report_and_follows_the_current_state_section(tmp_path, monkeypatch, api):
    identities = ["fred:UNRATE", "fred:GDP", "fred:T10Y2Y", "usgov:treasury/mts_deficit"]
    engine = real_engine(tmp_path, monkeypatch, api, RealSources(api), needs=identities[:3])
    engine.kiqs[1].data_needs = [{"series": identities[3]}]
    engine.phase_data()
    sections = [{"index": section.index, "title": section.title, "body": "Existing analysis.",
                 "is_scenario": section.is_scenario} for section in engine.plan.sections]
    engine._embed_data_exhibits(sections)
    assert [section["title"] for section in sections[:3]] == [engine.plan.sections[0].title,
                                                               "Official Data Baseline",
                                                               engine.plan.sections[1].title]
    rows = sections[1]["body"].splitlines()
    assert rows[0] == ("| Series | Latest historical value | Period | Yearly change | Status | Publisher projection "
                       "| Source |")
    assert rows[2] == f"| Unemployment Rate — United States | 4.2% | 2026-09 | -0.2 pp | stored observation | — | [S{sid_of(engine, 'fred:UNRATE')}] |"
    assert rows[3].startswith("| Gross Domestic Product — United States | 32563.03 Billions of Dollars | 2026-Q2 | "
                              "+1932.856 (+6.31%) | stored observation |")
    # The open month of daily data (2026-10, partial at retrieval) is never the
    # latest historical value; the last complete month is.
    assert "| 0.34% | 2026-09 | -0.214 pp | stored observation |" in rows[4] and "2026-10" not in rows[4]
    assert "| -166796952277.38 U.S. dollars (≈ -166.8 billion U.S. dollars) | 2026-08 |" in rows[5]
    assert all("% Percent" not in row for row in rows)
    report = lr.render_report(engine.question, engine.language, "Summary text " * 30, sections, engine.plan.scenarios)
    report += "\n## References\n\n1. x\n"
    order_check = engine._qa_checks(report, True, [])[0]
    assert order_check["name"] == "sections_in_order" and order_check["passed"], order_check


def test_chinese_run_localizes_official_exhibits_and_findings(tmp_path, monkeypatch, api):
    engine = real_engine(tmp_path, monkeypatch, api, RealSources(api), question="美国失业率的基线是多少？",
                         needs=["fred:UNRATE"])
    assert engine.language == lr.CHINESE
    engine.phase_data()
    engine.data_charts = [{"id": "data_x", "title": "失业率", "caption": "", "series": ["fred:UNRATE"],
                           "path": "charts/data_x.png"}]
    sections = [{"index": section.index, "title": section.title, "body": "现有分析。",
                 "is_scenario": section.is_scenario} for section in engine.plan.sections]
    engine._embed_data_exhibits(sections)
    report = "\n".join(section["body"] for section in sections)
    assert "| 序列 | 最新历史值 | 时期 | 同比变化 | 状态 | 发布方预测 | 来源 |" in report
    assert "| 美国失业率 | 4.2% | 2026-09 | -0.2 pp | 已存观测值 | — |" in report
    assert "### 图：失业率" in report and "Figure" not in report
    engine._finish_kiq(engine.kiqs[0], NOTES)
    fact = engine.records[engine.kiqs[0].id]["facts"][0]
    assert fact["tag"] == "VERIFIED" and fact["text"].startswith("美国失业率：4.2%（2026-09；已存观测值）")


# A Chinese run names each stored value's unit in Chinese (the summary,
# critique and digest headlines of Chinese runs quoted "4.96% change per
# annum"); the value text, period, status and stored page stay as they were.
ZH_HEADLINES = {
    "fred:UNRATE": "[S3] 美国失业率：4.2%（2026-09；已存观测值）",
    "fred:GDP": "[S3] 美国名义国内生产总值：32563.03 十亿美元（2026-Q2；已存观测值）",
    "fred:PAYEMS": "[S3] 美国非农就业人数：159044 千人（2026-09；已存观测值）",
    "bis:WS_CBPOL/M.US": "[S3] 美国央行政策利率：3.875% 年率（2026-09；已存观测值）",
    "wb:WB_WDI_NY_GDP_MKTP_KD_ZG/CHN": "[S3] 中国GDP年增长率（世界发展指标）：4.96% 年变化率（2025；已存观测值）",
    "usgov:treasury/mts_deficit": ("[S3] 美国联邦财政月度盈余（+）或赤字（-）：-166796952277.38 美元 (≈-1667.97亿美元)"
                                   "（2026-08；已存观测值）"),
    "bis:WS_LONG_CPI/M.US.771": "[S3] 美国CPI同比（BIS）：3.397% 同比变化率（2026-08；已存观测值）",
    "wb:IMF_WEO_PCPIPCH/USA": "[S3] 美国CPI通胀率（IMF WEO）：2.73% 变化率（2025；发布方估计值）",
}
ENGLISH_UNIT_WORDS = ("per year", "change per annum", "year-on-year change", "% change", "Billions of Dollars",
                      "Thousands of Persons", "U.S. dollars")
RENDER_DATA = Path(__file__).resolve().parents[2] / "deerflow_bridge/skills/data-visuals/scripts/render_data.py"


def captured_rows(api, *, stored=True):
    """Captured v3 rows: the 2026-10-11 rows as stored (unless not
    ``stored``) and under the current policy, then the 2026-10-12 rows
    (current policy) as stored."""
    first = [row["series"] for row in json.loads(REAL_SERIES.read_text(encoding="utf-8"))["series"]]
    second = [row["series"] for row in json.loads(REAL_SERIES_CURRENT.read_text(encoding="utf-8"))["series"]]
    return ([real_series(api, identity, current=current) for current in (False, True)[not stored:]
             for identity in first] + [current_series(api, identity) for identity in second])


def official_texts(api, series, language):
    """Every text the engine derives from one stored series in ``language``."""
    page = api.render_series_page(series)
    return [lr.data_digest_line(series, 3, language), lr.data_headline(series, 3, language),
            lr.data_outlook_headline(series, 3, language, 2027),
            *(text for text, _ in lr.data_facts(series, 3, language, page)), lr.data_table_row(series, 3, language)]


def test_chinese_official_text_names_units_in_chinese_and_changes_nothing_else(monkeypatch, api):
    rows = captured_rows(api)
    current = {series.series: series for series in captured_rows(api, stored=False)}
    for identity, headline in ZH_HEADLINES.items():
        assert lr.data_headline(current[identity], 3, lr.CHINESE) == headline
    assert lr.data_outlook_headline(current["wb:IMF_WEO_PCPIPCH/USA"], 3, lr.CHINESE, 2027) == (
        ZH_HEADLINES["wb:IMF_WEO_PCPIPCH/USA"] + "；发布方预测（非观测值）：2026 3.228%, 2027 2.141%")
    chinese = [official_texts(api, series, lr.CHINESE) for series in rows]
    english = [official_texts(api, series, lr.ENGLISH) for series in rows]
    units = []
    for series in rows:
        value = api.format_series_value(next(o.value for o in series.observations if o.value is not None), series)
        units.append((lr.data_unit_text(series.units, value, lr.ENGLISH), lr.data_unit_text(series.units, value,
                                                                                            lr.CHINESE)))
    assert set(units) == {("", ""), ("Billions of Dollars", "十亿美元"), ("Thousands of Persons", "千人"),
                          ("per year", "年率"), ("change", "变化率"), ("U.S. dollars", "美元"),
                          ("change per annum", "年变化率"), ("year-on-year change", "同比变化率")}
    # A unit outside the vocabulary is shown as in English; a value without
    # its "%" keeps the label's "（%）".
    assert lr.data_unit_text("Percent of potential GDP", "1.2%", lr.CHINESE) == "of potential GDP"
    assert lr.data_unit_text("Hectolitres of pure alcohol", "12", lr.CHINESE) == "Hectolitres of pure alcohol"
    assert lr.data_unit_text("Per cent per year", "3.875", lr.CHINESE) == "年率（%）"
    assert lr.data_unit_text("Index Dec 2005=100", "101.2", lr.CHINESE) == "指数（2005年12月=100）"
    # The texts as they were before units were localized: the vocabulary off.
    monkeypatch.setattr(lr, "data_units_zh", lambda text: " ".join(str(text or "").split()))
    assert [official_texts(api, series, lr.ENGLISH) for series in rows] == english
    for series, texts, (published, label) in zip(rows, chinese, units, strict=True):
        before = official_texts(api, series, lr.CHINESE)
        # Only the unit label changes: every number, period and status stays.
        assert texts == [text.replace(f" {published}", f" {label}") if published else text for text in before]
        assert [re.findall(r"\d+(?:\.\d+)?", text) for text in texts] == [
            re.findall(r"\d+(?:\.\d+)?", text) for text in before]
        assert not published or not any(f" {published}" in text for text in texts), (series.series, texts)
        # The stored page keeps the published unit.
        assert f"Units: {series.units}" in api.render_series_page(series)


def test_chinese_unit_labels_are_the_chart_renderers(api):
    # The engine keeps an import-free copy of the data-visuals renderer's
    # Chinese unit vocabulary (the renderer is a skill script run as a
    # subprocess): a Chinese report's text and its charts name a unit alike.
    import data_catalog
    spec = importlib.util.spec_from_file_location("render_data_unit_parity", RENDER_DATA)
    renderer = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(renderer)
    assert dict(lr._DATA_UNITS_ZH) == renderer._UNITS_ZH
    for mine, theirs in ((lr._DATA_UNITS_INDEX_RE, renderer._INDEX_BASE_RE),
                         (lr._DATA_UNITS_MONTH_BASE_RE, renderer._MONTH_BASE_RE),
                         (lr._DATA_UNITS_CHAINED_RE, renderer._CHAINED_RE)):
        assert (mine.pattern, mine.flags) == (theirs.pattern, theirs.flags)
    captured = set()

    def collect(node):
        if isinstance(node, dict):
            captured.update(value for key, value in node.items() if key == "units" and isinstance(value, str))
            for value in node.values():
                collect(value)
        elif isinstance(node, list):
            for value in node:
                collect(value)

    for path in (Path(__file__).resolve().parent / "fixtures/data_sources/real").rglob("*.json"):
        collect(json.loads(path.read_text(encoding="utf-8")))
    catalog_units = {entry.units for entry in data_catalog.CATALOG}
    catalog_units |= {recipe["units"] for recipe in data_catalog.USGOV_RECIPES.values()}
    edge = {"", "  Per cent   per year ", "Index Jan 2000=100", "Index, 2020 = 100", "index sept. 1999 = 100",
            "Millions of Chained 2012 Dollars", "Hectolitres of pure alcohol"}
    assert {"Index Dec 2005=100", "Billions of Chained 2017 Dollars", "Percentage Points"} <= captured
    for units in sorted(captured | catalog_units | edge):
        assert lr.data_units_zh(units) == renderer._units_zh(units), units


class CapturedRuns(RealSources):
    """Both captured v3 runs: the 2026-10-12 rows as stored, the 2026-10-11
    rows as ``RealSources`` serves them."""
    def get(self, series, **kwargs):
        rows = json.loads(REAL_SERIES_CURRENT.read_text(encoding="utf-8"))["series"]
        if series not in {row["series"] for row in rows}:
            return super().get(series, **kwargs)
        self.calls.append(("get", series, kwargs))
        return current_series(self.api, series)


def test_chinese_run_summary_critique_digest_and_findings_quote_chinese_units(tmp_path, monkeypatch, api):
    engine = real_engine(tmp_path, monkeypatch, api, CapturedRuns(api, current=True), question="2027年美国经济会衰退吗？",
                         env={"DATA_SOURCES_MAX_SERIES": "24"})
    assert engine.language == lr.CHINESE
    identities = list(ZH_HEADLINES)
    for index, kiq in enumerate(engine.kiqs):
        kiq.data_needs = [{"series": identity} for identity in identities[2 * index:2 * index + 2]]
    engine.phase_data()
    sids = {identity: sid_of(engine, identity) for identity in identities}
    # Summary and critique tasks, and the digest's OFFICIAL DATA block.
    headlines = engine._data_headlines(lr._DATA_EXEC_RULE)
    block = engine.synth_context().partition("SOURCE INDEX")[0]
    for identity, headline in ZH_HEADLINES.items():
        assert headline.replace("[S3] ", f"[S{sids[identity]}] ") in headlines
        assert f"[S{sids[identity]}] {identity} — {headline.removeprefix('[S3] ')}" in block
    assert not [word for word in ENGLISH_UNIT_WORDS if word in headlines or word in block]
    # Deterministic findings quote Chinese units and stay verified against
    # the stored page, which keeps the published (English) unit.
    for kiq in engine.kiqs:
        engine._finish_kiq(kiq, NOTES)
    facts = [fact for kiq in engine.kiqs for fact in engine.records[kiq.id]["facts"]]
    observed = [fact for fact in facts if "已存观测值" in fact["text"]]
    assert len(observed) == 7 and {fact["tag"] for fact in observed} == {"VERIFIED"}
    assert any(fact["text"].startswith("美国名义国内生产总值：32563.03 十亿美元（2026-Q2；已存观测值）；上年同期 "
                                       "30630.174 十亿美元（2025-Q2）") for fact in observed)
    assert not [word for fact in facts for word in ENGLISH_UNIT_WORDS if word in fact["text"]]
    for series, sid in engine._data_rows():
        assert f"Units: {series.units}" in engine.tools.page_text(sid)
    # The official-data check reads Chinese units: exact quotes and the
    # engine's own headlines and baseline table pass; another scale fails.
    order = sorted(sids.values())
    position = {sid: index for index, sid in enumerate(order, 1)}
    cite = {identity: f"[S{position[sid]}]" for identity, sid in sids.items()}

    def passed(text):
        return engine._data_checks(text, order)[0]["passed"]

    exact = [f"2026年第二季度美国名义国内生产总值为32563.03 十亿美元{cite['fred:GDP']}。",
             f"美国名义GDP达到32563.03十亿美元{cite['fred:GDP']}。",
             f"2026年9月非农就业人数为159044 千人{cite['fred:PAYEMS']}。",
             f"美国央行政策利率为3.875% 年率（2026-09）{cite['bis:WS_CBPOL/M.US']}。",
             f"2025年中国GDP年增长率为4.96% 年变化率{cite['wb:WB_WDI_NY_GDP_MKTP_KD_ZG/CHN']}。",
             f"2026年8月联邦财政赤字为-166796952277.38 美元 (≈-1667.97亿美元){cite['usgov:treasury/mts_deficit']}。",
             f"BIS口径美国CPI同比为3.397% 同比变化率{cite['bis:WS_LONG_CPI/M.US.771']}。"]
    wrong = [f"美国名义国内生产总值为32563.03亿美元{cite['fred:GDP']}。",
             f"非农就业人数为159044万人{cite['fred:PAYEMS']}。",
             f"2025年中国GDP年增长率为4.69% 年变化率{cite['wb:WB_WDI_NY_GDP_MKTP_KD_ZG/CHN']}。"]
    assert [sentence for sentence in exact if not passed(sentence)] == []
    assert [sentence for sentence in wrong if passed(sentence)] == []
    assert passed("\n".join(re.sub(r"\[S(\d+)\]", lambda match: f"[S{position[int(match[1])]}]", line)
                            for line in headlines.splitlines() if line.startswith("[S")))
    sections = [{"index": section.index, "title": section.title, "body": "现有分析。",
                 "is_scenario": section.is_scenario} for section in engine.plan.sections]
    engine._embed_data_exhibits(sections)
    body = lr.render_report(engine.question, engine.language, "摘要", sections, engine.plan.scenarios)
    assert "| 美国名义国内生产总值 | 32563.03 十亿美元 | 2026-Q2 |" in body
    body, renumbered = lr.renumber_citations(body, lambda sid: engine.ledger.get(sid) is not None)
    assert body.count("| [S") == len(identities)
    assert engine._data_checks(body, renumbered)[0]["passed"], engine._data_checks(body, renumbered)


def test_digest_official_block_has_trajectory_projection_path_and_index(tmp_path, monkeypatch, api):
    engine = real_engine(tmp_path, monkeypatch, api, RealSources(api), needs=["fred:UNRATE", "imf:WEO/USA.NGDP_RPCH.A"])
    # Without the catalog's faster Data360 route the WEO series keeps its IMF id.
    monkeypatch.setattr(api, "catalog_field", lambda entry, name: "")
    engine.phase_data()
    digest = engine.synth_context()
    block, _, index = digest.partition("SOURCE INDEX")
    assert "OFFICIAL DATA (stored series" in block
    unrate, weo = sid_of(engine, "fred:UNRATE"), sid_of(engine, "imf:WEO/USA.NGDP_RPCH.A")
    assert (f"[S{unrate}] fred:UNRATE — Unemployment Rate — United States: 4.2% (2026-09; stored observation); "
            "year earlier 4.4% (2025-09), change -0.2 pp; 5-year range 3.4% (2023-04) to 4.7% (2021-09); "
            "same period in earlier years: 2021-09 4.7%, 2022-09 3.5%, 2023-09 3.7%, 2024-09 4.1%") in block
    assert "publisher projection, not observed: 2027 2.1%, 2028 2.1%, 2029 1.88%, 2030 1.75%, 2031 1.75%" in block
    assert f"[S{unrate}] " in index and f"[S{weo}] " in index


class SearchingSources(RealSources):
    """Captured search hits; any series ID is served (a generic stored series)."""
    def get(self, series, **kwargs):
        self.calls.append(("get", series, kwargs))
        return observation_series(self.api, series)


def test_query_needs_seed_only_strong_catalog_matches_and_agents_look_up_the_rest(tmp_path, monkeypatch, api):
    # Provider search lines are discovery metadata, never seeds: the weak catalog
    # hint in the right country (the US policy rate for a wage tracker) and a
    # live title sharing one word ("Exports: Value Goods for Korea" for widget
    # exports) used to be prefetched as the KIQ's official evidence.
    source = SearchingSources(api, hits={
        "widget exports Korea": [("fred:XTEXVA01KRM667S", "Exports: Value Goods for Korea")],
        "chip exports Taiwan": [("fred:TWNXTEXVA01CXMLM", "Exports: Value Goods for Taiwan")],
        "Atlanta Fed wage tracker United States": [("bis:WS_CBPOL/M.US", "Central bank policy rate")]})
    engine = real_engine(tmp_path, monkeypatch, api, source, needs=[
        {"query": "policy rate", "geography": "CHN"}, {"query": "inflation", "geography": "JPN"},
        {"query": "widget exports", "geography": "KOR"}])
    # A place the catalog does not know ("Taiwan") has no catalog match at all.
    engine.kiqs[1].data_needs = [{"query": "chip exports", "geography": "Taiwan"}]
    engine.kiqs[2].data_needs = [{"query": "Atlanta Fed wage tracker", "geography": "USA"}]
    engine.phase_data()
    assert not [call for call in source.calls if call[0] == "search"]
    stored = {series.series for series, _ in engine._data_rows()}
    catalog = lr._data_catalog()
    # The ISO3 needs resolve to strong catalog series of that very country.
    assert "bis:WS_CBPOL/M.CN" in stored
    assert stored and all(catalog.lookup(identity).geography in ("CHN", "JPN") for identity in stored), stored
    assert engine._catalog_need({"query": "Atlanta Fed wage tracker", "geography": "USA"}, catalog) == ""
    # What no catalog series answers is the agent's lookup, named in its task.
    first = engine._kiq_task(engine.kiqs[0], [])
    assert "no catalog series answers" in first and "widget exports (KOR)" in first
    assert "policy rate (CHN)" not in first and "inflation (JPN)" not in first
    assert "chip exports (Taiwan)" in engine._kiq_task(engine.kiqs[1], [])
    assert "Atlanta Fed wage tracker (USA)" in engine._kiq_task(engine.kiqs[2], [])
    # The follow-up path resolves the same way (no provider search either).
    followup = lr.Kiq("G1F1", "Wage growth?", ["wage tracker"], round=1,
                      data_needs=[{"query": "Atlanta Fed wage tracker", "geography": "USA"}])
    engine.kiqs.append(followup)
    engine._prefetch_followups(1, [followup], rg.Deadline(100))
    assert "G1F1" not in engine.data_index and not [call for call in source.calls if call[0] == "search"]
    engine.data_enabled = False
    assert "no catalog series" not in engine._kiq_task(engine.kiqs[2], [])


def test_prefetch_stays_within_the_runs_prefetch_cap_across_batches(tmp_path, monkeypatch, api):
    source = FixtureSources(api)
    identities = ["fred:UNRATE", "fred:PAYEMS", "fred:GDP", "fred:CPIAUCSL", "fred:FEDFUNDS", "fred:DGS10",
                  "fred:INDPRO", "fred:HOUST", "fred:RSAFS"]
    engine = real_engine(tmp_path, monkeypatch, api, source, env={"DATA_SOURCES_PREFETCH_MAX": "99"})
    assert len(engine.kiqs) >= 3 and engine.limits.max_prefetch_datasets == 6
    for kiq in engine.kiqs:
        kiq.data_needs = []
    for kiq, start in zip(engine.kiqs, (0, 3, 6)):
        kiq.data_needs = [{"series": identity} for identity in identities[start:start + 3]]
    engine.phase_data()
    # DATA_SOURCES_PREFETCH_MAX=99 is clamped to the quick preset's 6 (60 % of 10).
    assert len(engine._data_rows()) == 6 and len(source.calls) == 6
    # A follow-up batch gets only the prefetch slots left (none): a stored series
    # is linked free and nothing is requested only to be refused.
    followup = lr.Kiq("G1F1", "Money and curve?", ["m2"], round=1, data_needs=[
        {"series": "fred:UNRATE"}, {"series": "fred:M2SL"}, {"series": "fred:T10Y2Y"}])
    engine.kiqs.append(followup)
    engine._prefetch_followups(1, [followup], rg.Deadline(100))
    assert engine.data_index["G1F1"] == [sid_of(engine, "fred:UNRATE")]
    stats = engine.tools.data_stats()
    assert stats["per_kiq"]["G1F1"]["failed"] == [] and stats["failed_requests"] == []
    assert engine._data_events() == [] and len(source.calls) == 6
    # The agents keep the remaining run slots for their own data_get calls.
    assert engine.tools.data_get("fred:M2SL", agent_id="G1F1").startswith("[S")


def test_plan_without_data_needs_seeds_strong_catalog_series(tmp_path, monkeypatch, api):
    source = RealSources(api)
    engine = real_engine(tmp_path, monkeypatch, api, source,
                         question="Will US unemployment exceed 5% by the end of 2027?")
    assert not any(kiq.data_needs for kiq in engine.kiqs)
    requested = engine._data_requests(engine.kiqs)
    assert "fred:UNRATE" in requested and len(requested) <= lr.DATA_FALLBACK_MAX
    data_kiqs = [kiq.id for kiq in engine.kiqs if kiq.kind == "data"]
    assert requested["fred:UNRATE"][0] == data_kiqs[0]
    catalog = lr._data_catalog()
    assert all(catalog.lookup(identity).geography == "USA" for identity in requested)
    unrelated = real_engine(tmp_path / "other", monkeypatch, api, source,
                            question="Who will win the 2028 US presidential election?")
    assert unrelated._data_requests(unrelated.kiqs) == {}
    # The ECB deposit rate (final:V open item): the catalog's fred:ECBDFR is a
    # strong euro-area match, so the fallback plan seeds it for the data KIQ.
    ecb = real_engine(tmp_path / "ecb", monkeypatch, api, source,
                      question="Will the ECB cut its deposit rate below 2% by mid-2027?")
    assert not any(kiq.data_needs for kiq in ecb.kiqs)
    assert ecb._data_requests(ecb.kiqs) == {"fred:ECBDFR": [next(k.id for k in ecb.kiqs if k.kind == "data")]}


def test_compound_question_seeds_its_clauses_and_keyless_bls_routes_to_fred(tmp_path, monkeypatch, api):
    # The whole question gets one strong match per provider (the IMF WEO CPI
    # path, the BIS policy rate, the monthly CPI index); each clause adds the
    # provider picks the whole question took for the other clause: BIS
    # year-on-year CPI for the inflation clause, the effective federal funds
    # rate for the policy-rate clause.
    source = RealSources(api)
    engine = real_engine(tmp_path, monkeypatch, api, source, question=(
        "Will US CPI inflation fall below 2.5% year over year by December 2027, and how will the Federal "
        "Reserve policy rate evolve?"))
    requested = engine._data_requests(engine.kiqs)
    # The slow IMF CPI series only fills a slot no faster match takes (the BIS
    # year-on-year CPI does); keyless BLS (20 requests a day) is fetched from its
    # FRED copy, which counts as that clause's FRED pick (no second CPI index).
    assert list(requested) == ["wb:IMF_WEO_PCPIPCH/USA", "bis:WS_CBPOL/M.US", "fred:CPIAUCSL",
                               "bis:WS_LONG_CPI/M.US.771", "fred:FEDFUNDS"]
    assert engine._data_route("bls:CUUR0000SA0#yoy") == "fred:CPIAUCNS#yoy"
    keyed = real_engine(tmp_path / "keyed", monkeypatch, api, source, env={"BLS_API_KEY": "fixture-key"})
    assert keyed._data_route("bls:CUUR0000SA0") == "bls:CUUR0000SA0"
    assert not [call for call in source.calls if call[0] == "search"]


def test_projection_and_base_rate_prefetch_windows(tmp_path, monkeypatch, api):
    source = RealSources(api)
    plan = lr.build_plan("Will US growth slow by 2028?", lr.ENGLISH, "2026-10-12", lr.resolve_preset("standard", {}), 4,
                         {"restated_question": "Will US real GDP growth fall below 1.5% in 2028?",
                          "horizon": "by end of 2028", "scout_queries": ["x"], "key_entities": []}, None)
    engine = real_engine(tmp_path, monkeypatch, api, source, question="Will US growth slow by 2028?", plan=plan,
                         needs=["imf:WEO/USA.NGDP_RPCH.A"])
    base_rate = next(kiq for kiq in engine.kiqs if lr._BASE_RATE_RE.search(kiq.question))
    base_rate.data_needs = [{"series": "fred:UNRATE"}]
    engine.phase_data()
    windows = {call[1]: call[2] for call in source.calls if call[0] == "get"}
    # The WEO series is routed to its Data360 copy and ends at the horizon.
    assert windows["wb:IMF_WEO_NGDP_RPCH/USA"]["end"] == "2028-12-31"
    assert windows["fred:UNRATE"]["start"] == "1996-01-01"


@pytest.mark.parametrize("horizon, year", [
    # Horizon shapes of real v3 plans (backend/uploads): a range ends at its last year.
    ("2026–2028", 2028), ("2026-07-08 → 2031-12-31", 2031), ("2026-07-06 至 2028-12-31", 2028),
    ("2026-2030 (forecast endpoint: 2030-12-31)", 2030), ("2030 (as-of 2026-07-09)", 2030),
    ("2026-01-01 to 2040-12-31", 2032), ("by end of 2028", 2028), ("2027-12-31", 2027),
    ("not specified", 2031)])
def test_a_projection_path_is_prefetched_through_the_end_of_a_horizon_range(tmp_path, monkeypatch, api,
                                                                            horizon, year):
    # A stored window is immutable for the run: a WEO path stored only to the
    # range's first year (2026 of "2026–2028") could never reach the forecast year.
    source = RealSources(api)
    plan = lr.build_plan("Will US growth slow by 2028?", lr.ENGLISH, "2026-10-12", lr.resolve_preset("standard", {}), 4,
                         {"restated_question": "Will US real GDP growth fall below 1.5% in 2028?",
                          "horizon": horizon, "scout_queries": ["x"], "key_entities": []}, None)
    engine = real_engine(tmp_path, monkeypatch, api, source, question="Will US growth slow by 2028?", plan=plan,
                         needs=["imf:WEO/USA.NGDP_RPCH.A"])
    assert engine.plan.horizon == horizon and engine._data_horizon() == year
    engine.phase_data()
    windows = {call[1]: call[2] for call in source.calls if call[0] == "get"}
    assert windows["wb:IMF_WEO_NGDP_RPCH/USA"]["end"] == f"{year}-12-31"


def test_resume_acquires_official_data_unless_evidence_is_pinned(tmp_path, monkeypatch, api):
    source = RealSources(api)
    first = real_engine(tmp_path, monkeypatch, api, source, needs=["fred:UNRATE"])
    first.state.set_phase("plan", "done")  # the attempt stopped before its data phase
    resumed = real_engine(tmp_path, monkeypatch, api, source, needs=["fred:UNRATE"])
    assert resumed.resumed and resumed.data_enabled and source.prewarms == 2
    assert resumed.agent_tools is rg.AGENT_TOOLS_WITH_DATA_SCHEMA
    resumed.phase_data()
    assert resumed.state.is_done("data") and resumed._data_rows()
    # Mid-gather: data done, gather not: unfinished KIQs may still fetch.
    again = real_engine(tmp_path, monkeypatch, api, source, needs=["fred:UNRATE"])
    again.phase_data()
    assert again.tools.data_get("fred:PAYEMS", agent_id="K2").startswith("[S")
    # Gather finished: evidence is pinned; no provider and no new series.
    again.state.set_phase("gather", "done")
    pinned = real_engine(tmp_path, monkeypatch, api, source, needs=["fred:UNRATE"])
    assert pinned.meta["data_sources"]["status"] == "stored_only" and source.prewarms == 3
    assert pinned.tools.data_get("fred:GDP", agent_id="K3").startswith("DATA_UNAVAILABLE")
    # A run whose data phase recorded official data as disabled stays disabled.
    off = tmp_path / "off"
    disabled = real_engine(off, monkeypatch, api, source, env={"DATA_SOURCES_ENABLED": "false"})
    disabled.phase_data()
    assert disabled.state.phase("data")["detail"] == "disabled"
    reopened = real_engine(off, monkeypatch, api, source)
    assert not reopened.data_enabled and reopened.agent_tools is rg.AGENT_TOOLS_SCHEMA


@pytest.mark.parametrize("outage", ["no_provider", "factory_error"])
def test_a_resume_whose_providers_are_unavailable_keeps_the_stored_series(tmp_path, monkeypatch, api, outage):
    # The first attempt stored and seeded fred:UNRATE, then stopped mid-gather.
    # A resumed attempt whose providers are now unavailable keeps that evidence
    # for its unfinished KIQs (stored series only), as every resume did before
    # resumed runs configured the providers again.
    source = RealSources(api)
    first = real_engine(tmp_path, monkeypatch, api, source, needs=["fred:UNRATE"])
    first.phase_data()
    assert first.data_index == {first.kiqs[0].id: [1]}
    down = RealSources(api)
    down.active = False

    def reopen(root):
        if outage == "no_provider":  # the hub started no provider
            return real_engine(root, monkeypatch, api, down, needs=["fred:UNRATE"])
        monkeypatch.setattr(api, "get_data_sources", lambda **kw: (_ for _ in ()).throw(OSError("hub down")))
        return _engine_without_sources(root)

    resumed = reopen(tmp_path)
    assert resumed.resumed and resumed.data_enabled
    assert resumed.meta["data_sources"]["status"] == "stored_only"
    assert resumed.agent_tools is rg.AGENT_TOOLS_WITH_DATA_SCHEMA
    resumed.phase_data()
    task = resumed._kiq_task(resumed.kiqs[0], [])
    assert "OFFICIAL DATA ALREADY RETRIEVED" in task and "[S1]" in task
    assert resumed.tools.data_get("fred:UNRATE", agent_id="K2").startswith("[S1]")
    assert resumed.tools.data_get("fred:PAYEMS", agent_id="K2").startswith("DATA_UNAVAILABLE[provider_unavailable]")
    assert source.prewarms == 1 and down.prewarms == 0 and not down.calls
    # Without stored evidence an unavailable resume stays without official data.
    fresh = tmp_path / "fresh"
    real_engine(fresh, monkeypatch, api, RealSources(api)).state.set_phase("plan", "done")
    empty = reopen(fresh)
    assert empty.resumed and not empty.data_enabled and empty.meta["data_sources"]["status"] == "unavailable"


def _engine_without_sources(tmp_path):
    """An engine whose tools have no DataSources, so it builds them itself."""
    from test_research_engine_v3 import FakePlog, ScriptedModel, World, make_args, fake_search, page_text
    gateway = lambda args, log, bridge, preset: rg.ModelGateway(ScriptedModel(World()), log, sleep=lambda _: None)
    factory = lambda ledger, pages, bridge, log, limits: rg.ResearchTools(
        ledger, pages, search_fn=fake_search, fetch_fn=page_text, limits=limits, data_sources=None)
    engine = lr._Engine("What is the US macro baseline?", tmp_path / "run", make_args("quick"), {}, FakePlog(),
                        lambda: None, SimpleNamespace(), gateway, factory, {"DATA_SOURCES_ENABLED": "true"})
    engine.plan = lr.build_plan(engine.question, engine.language, "2026-10-12", engine.preset, 4, None, None)
    engine.kiqs = list(engine.plan.kiqs)
    engine.kiqs[0].data_needs = [{"series": "fred:UNRATE"}]
    engine.brief = lr.render_brief(engine.plan)
    return engine


def test_data_phase_announces_progress_band(tmp_path, monkeypatch, api):
    from app.services.research_progress import ResearchProgressEstimator
    engine = real_engine(tmp_path, monkeypatch, api, RealSources(api), needs=["fred:UNRATE"])
    engine.phase_data()
    lines = [line for line in engine.reporter.text().splitlines() if "research:v3:data" in line]
    assert lines == ["[stage] research:v3:data start (1 series)", "[ok] research:v3:data done (stored=1, failed=0)"]
    stamp = "2026-10-12T00:00:00+00:00"
    estimator = ResearchProgressEstimator()
    observed = [estimator.observe(f"{stamp} {line}") for line in (
        "[ok] research:v3:plan done (6 KIQs, 8 sections)", *lines,
        "[stage] research:v3:gather start (6 KIQs, workers=4)")]
    assert observed == [9, 10, 12, 13]
    plain = ResearchProgressEstimator()
    assert plain.observe(f"{stamp} [stage] research:v3:gather start (6 KIQs, workers=4)") == 10


def stored_engine(tmp_path, monkeypatch, api, identities, **kwargs):
    """A real engine whose plan KIQs K1.. each need one of ``identities`` (stored)."""
    engine = real_engine(tmp_path, monkeypatch, api, RealSources(api), **kwargs)
    for kiq in engine.kiqs:
        kiq.data_needs = []
    for kiq, identity in zip(engine.kiqs, identities):
        kiq.data_needs = [{"series": identity}]
    engine.phase_data()
    return engine


def test_finalize_writes_official_quantitative_rows_and_indicators(tmp_path, monkeypatch, api):
    monkeypatch.setattr(api, "catalog_field", lambda entry, name: "")  # keep the IMF WEO id (projections to 2031)
    engine = stored_engine(tmp_path, monkeypatch, api, ["fred:UNRATE", "imf:WEO/USA.NGDP_RPCH.A"])
    unrate, weo = sid_of(engine, "fred:UNRATE"), sid_of(engine, "imf:WEO/USA.NGDP_RPCH.A")
    engine.qa = {"citation_order": [unrate, weo]}
    engine._publish_data({"fred:UNRATE": 1, "imf:WEO/USA.NGDP_RPCH.A": 2})
    sources = engine._source_rows([unrate, weo])
    facts = {"quantitative_facts": [
        {"metric": "Unemployment rate", "value": "4.2%", "unit": "Percent", "source_ref": "S1"},
        {"metric": "Unemployment rate a year earlier", "value": "4.4", "unit": "Percent", "source_ref": "S1"}]}
    engine._write_structured(None, facts, sources)
    path = engine.out_dir / "quantitative.json"
    assert [row["metric"] for row in json.loads(path.read_text())] == ["Unemployment rate",
                                                                       "Unemployment rate a year earlier"]
    assert engine._attach_official_quant() == {"quantitative_count": 7, "official_quantitative_count": 6}
    quant = json.loads(path.read_text())
    official = [row for row in quant if row.get("source_origin") == "official_data"]
    # as_of_date is the source as-of date (retrieval); period_end the period measured.
    assert official[0] == {
        "metric": "Unemployment Rate — United States", "series": "fred:UNRATE", "unit": "Percent",
        "geography": "USA", "source": "FRED (Federal Reserve Bank of St. Louis)",
        "source_url": "https://fred.stlouisfed.org/series/UNRATE", "tier": "S1", "as_of_date": "2026-10-11",
        "source_ref": "S1", "source_origin": "official_data", "dataset_file": sources[0]["dataset"]["file"],
        "value": 4.2, "period_end": "2026-09-30", "period": "2026-09", "value_type": "actual",
        "definition": "stored observation"}
    # WEO history has no supplied status (no "actual" row); its projection path
    # is published as the publisher's forecast, as of the retrieval date.
    projections = official[1:]
    assert [(row["series"], row["period"], row["value"], row["value_type"]) for row in projections] == [
        ("imf:WEO/USA.NGDP_RPCH.A", "2027", 2.1, "forecast"), ("imf:WEO/USA.NGDP_RPCH.A", "2028", 2.1, "forecast"),
        ("imf:WEO/USA.NGDP_RPCH.A", "2029", 1.880588, "forecast"),
        ("imf:WEO/USA.NGDP_RPCH.A", "2030", 1.753132, "forecast"),
        ("imf:WEO/USA.NGDP_RPCH.A", "2031", 1.755, "forecast")]
    assert all(row["source_ref"] == "S2" and row["as_of_date"] == "2026-10-11"
               and row["definition"] == "International Monetary Fund (IMF): publisher projection, not observed"
               for row in projections)
    llm = [row for row in quant if row.get("source_origin") != "official_data"]
    assert [row["metric"] for row in llm] == ["Unemployment rate a year earlier"]
    indicators = json.loads((engine.out_dir / "actors.json").read_text())["forecast_inputs"]["indicators"]
    assert [(row["series"], row["latest_value"], row["date_or_trigger"], row["source_ref"]) for row in indicators] == [
        ("fred:UNRATE", 4.2, "next monthly release after 2026-09", "S1"),
        ("imf:WEO/USA.NGDP_RPCH.A", indicators[1]["latest_value"], "next annual release after 2026", "S2")]
    assert indicators[1]["status"] == "unknown" and indicators[1]["latest_date"] == "2026-12-31"
    # A second pass replaces its own rows; a data problem never fails finalize.
    assert engine._attach_official_quant() == {"quantitative_count": 7, "official_quantitative_count": 6}
    assert json.loads(path.read_text()) == quant
    def broken(*args, **kwargs):
        raise OSError("fixture")
    monkeypatch.setattr(engine, "_official_quant", broken)
    monkeypatch.setattr(engine, "_official_refs", broken)
    assert engine._attach_official_quant() == {} and engine._official_indicators() == []
    assert "official quantitative rows unavailable (OSError)" in engine.reporter.text()


def test_kiq_task_guides_official_data_use_and_lists_other_stored_series(tmp_path, monkeypatch, api):
    plan = lr.build_plan("Will US unemployment exceed 5% by the end of 2027?", lr.ENGLISH, "2026-10-12",
                         lr.resolve_preset("standard", {}), 4, None, None)
    engine = stored_engine(tmp_path, monkeypatch, api, ["fred:UNRATE"], plan=plan,
                           question="Will US unemployment exceed 5% by the end of 2027?")
    unrate = sid_of(engine, "fred:UNRATE")
    first = engine._kiq_task(engine.kiqs[0], [])
    assert "Official data rules:" in first and "OFFICIAL DATA ALREADY RETRIEVED" in first
    hints = first.split("Official series that may fit this question", 1)[1].split("\n", 1)[0]
    assert "fred:UNRATE" not in hints and "wb:IMF_WEO_LUR/USA" in hints
    drivers = next(kiq for kiq in engine.kiqs if kiq.kind == "general")
    other = engine._kiq_task(drivers, [])
    assert ("\n- fred:UNRATE — Unemployment Rate — United States: 4.2% (2026-09; stored observation)" in other
            and f"[S{unrate}]" not in other and "Official series that may fit" not in other)
    base_rate = next(kiq for kiq in engine.kiqs if lr._BASE_RATE_RE.search(kiq.question))
    assert 'start="1996"' in engine._kiq_task(base_rate, [])
    # A run without official data renders the task template alone.
    engine.data_enabled = False
    assert engine._kiq_task(drivers, []) == other.split("\nOfficial tools:", 1)[0]
    data_agent = lr.KiqAgent(SimpleNamespace(tools=None, agent_tools=rg.AGENT_TOOLS_WITH_DATA_SCHEMA),
                             lr.Kiq("K1", "q", []), "", [], rg.Deadline(10))
    web_agent = lr.KiqAgent(SimpleNamespace(tools=None, agent_tools=rg.AGENT_TOOLS_SCHEMA),
                            lr.Kiq("K1", "q", []), "", [], rg.Deadline(10))
    # Bound data tools are named in the unknown/invalid-call replies; the
    # web-only replies stay byte-identical to a run without official data.
    assert (data_agent._call_tool({"name": "other", "args": {}})
            == "UNKNOWN_TOOL: only web_search, web_fetch, data_search and data_get are available.")
    assert "data_get with a series ID" in data_agent._call_tool({"error": "bad JSON"})
    assert web_agent._call_tool({"name": "other", "args": {}}) == "UNKNOWN_TOOL: only web_search and web_fetch are available."
    assert web_agent._call_tool({"error": "bad JSON"}) == (
        "INVALID_TOOL_CALL: bad JSON. Call web_search with a query string or web_fetch with a url "
        "(and optionally a focus).")
    assert "data_search or data_get" in lr.NOTES_NUDGE_DATA_TEXT and "data_" not in lr.NOTES_NUDGE_TEXT


def test_writer_summary_and_critique_tasks_get_the_data_rule_only_with_stored_series(tmp_path, monkeypatch, api):
    engine = stored_engine(tmp_path, monkeypatch, api, ["fred:UNRATE"])
    section = engine.plan.sections[0]
    with_data = engine.section_task([section])
    assert lr._DATA_SECTION_RULE in with_data
    seen = []
    def capture(shared, task, **kwargs):
        seen.append(task)
        return {"issues": []}
    engine.json_call = capture
    sections = [{"index": s.index, "title": s.title, "body": "Body text. " * 30, "is_scenario": s.is_scenario}
                for s in engine.plan.sections]
    engine._critique("Summary", sections, "context", rg.Deadline(10_000))
    assert lr._DATA_CRITIQUE_RULE in seen[-1] and "4.2% (2026-09; stored observation)" in seen[-1]
    def write(messages, **kwargs):
        seen.append(messages[-1].content)
        raise rg.GatewayError("fixture")
    engine._write_call = write
    engine._exec_summary(sections, rg.Deadline(10_000))
    assert lr._DATA_EXEC_RULE in seen[-1] and f"[S{sid_of(engine, 'fred:UNRATE')}] Unemployment Rate" in seen[-1]
    # Without stored series every task is the unchanged template text.
    bare = real_engine(tmp_path / "bare", monkeypatch, api, RealSources(api), env={"DATA_SOURCES_ENABLED": "false"})
    plain = bare.section_task([bare.plan.sections[0]])
    assert lr._DATA_SECTION_RULE not in plain and plain.endswith(lr._SECTION_RULES)
    assert bare._data_headlines(lr._DATA_EXEC_RULE) == ""


def test_gap_review_sees_data_coverage_and_follow_ups_fetch_their_series(tmp_path, monkeypatch, api):
    engine = stored_engine(tmp_path, monkeypatch, api, ["fred:UNRATE"])
    engine.records = {engine.kiqs[0].id: {"facts": [], "sources": []}}
    coverage = engine._coverage_matrix()
    assert f"- {engine.kiqs[0].id} (" in coverage and "official data: 1 stored [fred:UNRATE]" in coverage
    # The stored span tells the reviewer whether a base rate has history to
    # count; a stored series keeps that window for the run.
    assert ("Official series stored in this run, with their stored spans (1 of at most 10): "
            "fred:UNRATE (2020-10 to 2026-09)") in coverage
    seen = []
    def review(shared, task, **kwargs):
        seen.append(task)
        return {"verdict": "gaps", "follow_ups": [{"question": "What do Swiss policy rates imply for the franc?",
                                                   "queries": ["snb policy rate"], "why": "base rate",
                                                   "data_needs": [{"series": "bis:WS_CBPOL/M.CH"}]}]}
    engine.json_call = review
    verdict, followups, _ = engine._gap_review(1, rg.Deadline(100), max_followups=2)
    assert '"data_needs"' in seen[0] and followups[0].data_needs == [{"series": "bis:WS_CBPOL/M.CH"}]
    assert "keeps the span listed above" in seen[0]
    # A stored series keeps its newest 240 points: 30 monthly years are not stored.
    assert seen[0].endswith("in the question, which fetches history back to 1996 (at most the newest 240 "
                            "observations: 20 years of a monthly series).")
    engine.kiqs.extend(followups)
    engine._prefetch_followups(1, followups, rg.Deadline(100))
    assert engine.data_index[followups[0].id] == [sid_of(engine, "bis:WS_CBPOL/M.CH")]
    disabled = real_engine(tmp_path / "off", monkeypatch, api, RealSources(api), env={"DATA_SOURCES_ENABLED": "false"})
    disabled.records = {disabled.kiqs[0].id: {"facts": [], "sources": []}}
    assert "official" not in disabled._coverage_matrix().lower()


def test_official_charts_render_inside_the_qa_deadline(tmp_path, monkeypatch, api):
    engine = stored_engine(tmp_path, monkeypatch, api, ["fred:UNRATE"])
    calls = []
    def render(out_dir, *, plog=None, question="", lang="en", deadline_s=None):
        calls.append(deadline_s)
        return []
    engine.bridge._render_data_charts = render
    engine._prepare_data_exhibits(rg.Deadline(20, clock=lambda: 0.0))
    assert calls == [] and "no QA time left" in engine.reporter.text()
    engine._prepare_data_exhibits(rg.Deadline(100, clock=lambda: 0.0))
    assert calls == [70.0]
    legacy = []
    engine.bridge._render_data_charts = lambda out_dir, *, plog=None, question="", lang="en": legacy.append(1) or []
    engine._prepare_data_exhibits(rg.Deadline(100, clock=lambda: 0.0))
    assert legacy == [1]


def test_agent_requested_kiqs_reach_the_published_manifest_and_failures_are_events(tmp_path, monkeypatch, api):
    engine = stored_engine(tmp_path, monkeypatch, api, ["fred:UNRATE"])
    seeded = engine.kiqs[0].id
    assert engine.tools.data_get("fred:UNRATE", agent_id="K3").startswith("[S")
    engine._publish_data({"fred:UNRATE": 1})
    row = api.load_datasets(engine.out_dir)[0]
    assert row["kiqs"] == [seeded, "K3"]
    assert engine._data_events() == []
    failing = SimpleNamespace(data_stats=lambda: {"failures": 2, "per_kiq": {
        "K1": {"requested": ["fred:UNRATE", "imf:PCPS/G001.PCOPP.USD.M", "bis:WS_CBPOL/M.XM"],
               "stored": ["fred:UNRATE"], "failed": ["imf:PCPS/G001.PCOPP.USD.M", "bis:WS_CBPOL/M.XM"]}},
        "failed_requests": [{"code": "timeout"}, {"code": "rate_limited"}]}, data_rows=engine.tools.data_rows)
    engine.tools = failing
    assert engine._data_events() == ["2 of 3 requested official series were unavailable "
                                     "(bis:WS_CBPOL/M.XM, imf:PCPS/G001.PCOPP.USD.M; reasons: rate_limited, timeout)"]


def test_planner_is_told_the_data_needs_shape_only_when_data_is_enabled(tmp_path, monkeypatch, api):
    engine = real_engine(tmp_path, monkeypatch, api, RealSources(api))
    seen = []
    def plan_json(shared, task, **kwargs):
        seen.append(task)
        raise rg.GatewayError("fixture")
    engine._plan_json = plan_json
    engine._scout = lambda queries: "(no scout results)"
    engine._plan_calls("brief", rg.Deadline(100))
    assert '"data_needs": [{"series": "<catalog ID>"' in seen[-1] and "OFFICIAL DATA CATALOG" in seen[-1]
    # The planner learns where data_needs sit in a KIQ, the prefetch budget,
    # the transform form and that a base-rate KIQ of any kind names the
    # series whose history it counts (pipe_261de6107490 K7 named none).
    assert '"kind": "data", "data_needs": [{"series": "fred:UNRATE"}]}' in seen[-1]
    assert f"fetches at most {engine._prefetch_cap()} series in all" in seen[-1] and engine._prefetch_cap() == 6
    assert "fred:CPIAUCSL#yoy" in seen[-1] and "about 30 years" not in seen[-1]
    assert ("and history back to 1996 (at most the newest 240 observations: 20 years of a monthly series) for a "
            "KIQ that asks for base rates") in seen[-1]
    assert "whatever its kind, data_needs for the series whose history it counts" in seen[-1]
    off = real_engine(tmp_path / "off", monkeypatch, api, RealSources(api), env={"DATA_SOURCES_ENABLED": "false"})
    off._plan_json, off._scout = plan_json, (lambda queries: "(no scout results)")
    off._plan_calls("brief", rg.Deadline(100))
    assert "data_needs" not in seen[-1] and "OFFICIAL DATA" not in seen[-1]


def test_a_base_rate_kiq_of_any_kind_gets_series_hints_and_a_long_history_window(tmp_path, monkeypatch, api):
    # pipe_261de6107490 planned its base-rate KIQ as "general": it got no series
    # hint and, had it named a series, the default (short) window.
    question = "Will the Federal Reserve raise the federal funds rate above 4.5% by the end of 2026?"
    engine = real_engine(tmp_path, monkeypatch, api, RealSources(api), question=question)
    history = lr.Kiq("K9", "What are the historical base rates for another fed funds rate hike after a pause?",
                     ["fed hike after pause history"], kind="general")
    engine.kiqs.append(history)
    task = engine._kiq_task(history, [])
    hints = task.split("Official series that may fit this question", 1)[1].split("\n", 1)[0]
    assert "fred:FEDFUNDS" in hints and 'start="1996"' in task
    assert engine._data_windows({"fred:FEDFUNDS": ["K9"]}) == {"fred:FEDFUNDS": ("1996", None)}
    drivers = lr.Kiq("K8", "Who sits on the FOMC this year?", ["fomc members"], kind="actor")
    assert "Official series that may fit" not in engine._kiq_task(drivers, [])


CPI_FED = ("Will US CPI inflation fall below 2.5% year over year by December 2027, and how will the Federal "
           "Reserve policy rate evolve through 2027?")


def hint_line(task):
    """The catalog-hint line of a KIQ task, "" without one."""
    marker = "Official series that may fit this question (catalog IDs; data_get before citing): "
    return task.split(marker, 1)[1].split("\n", 1)[0] if marker in task else ""


def test_kiq_hints_measure_the_kiqs_own_question_and_name_fast_routes(tmp_path, monkeypatch, api):
    # Rendered for six forecasting questions (glue U1-v3): hints searched with
    # the whole research question offered a policy-rate KIQ the CPI series of
    # the other clause, an inflation KIQ exchange rates, NEV precedents China
    # GDP growth, and keyless BLS or slow IMF IDs ahead of their fast copies.
    engine = real_engine(tmp_path, monkeypatch, api, RealSources(api), question=CPI_FED)
    policy = lr.Kiq("K2", "What is the current federal funds target range and how has the FOMC moved in "
                          "2025-2026?", [], kind="data")
    hints = hint_line(engine._kiq_task(policy, []))
    assert "fred:DFEDTARU" in hints and not any(cpi in hints for cpi in ("CPIAUCSL", "PCPIPCH", "CPI/USA"))
    inflation = lr.Kiq("K1", "What are the latest US CPI and core inflation readings and how have they trended "
                             "through 2026?", [], kind="data")
    hints = hint_line(engine._kiq_task(inflation, [])).split("; ")
    # Headline and core price series only (the catalog may rank either first).
    assert len(hints) == lr.DATA_TASK_HINTS and any(hint.startswith("wb:IMF_WEO_PCPIPCH/USA — ") for hint in hints)
    assert all(re.search(r"Consumer Price|Consumer price|Personal Consumption Expenditures|All items", hint)
               for hint in hints), hints
    # Keyless BLS answers 20 requests a day: its headline CPI is offered as the FRED copy.
    assert any(hint.startswith("fred:CPIAUCNS — All items in U.S. city average") for hint in hints)
    assert not any(hint.startswith(("bls:", "imf:")) or "WS_CBPOL" in hint for hint in hints)
    ecb = real_engine(tmp_path / "ecb", monkeypatch, api, RealSources(api),
                      question="What will the euro-area deposit facility rate be at the end of 2026?")
    hicp = lr.Kiq("K2", "Where is euro-area HICP inflation relative to the 2% target?", [], kind="data")
    hints = hint_line(ecb._kiq_task(hicp, []))
    assert hints.startswith("bis:WS_LONG_CPI/M.XM.771 — ") and "WS_EER" not in hints and "treasury/fx" not in hints
    nev = real_engine(tmp_path / "nev", monkeypatch, api, RealSources(api),
                      question="Will China's new-energy-vehicle share of car sales exceed 60% in 2027?")
    precedents = lr.Kiq("K5", "What are historical precedents for NEV share growth after crossing 50% in other "
                              "markets?", [], kind="general")
    task = nev._kiq_task(precedents, [])
    assert hint_line(task) == "" and 'start="1996"' in task


def test_kiq_hints_skip_base_rate_wording_and_world_aggregates_of_a_national_statistic(tmp_path, monkeypatch, api):
    # Rendered Q5/Q6 (glue U1-v3): the catalog keyword "historical growth" offered
    # world GDP growth to a semiconductor-sales base rate, and a China GDP KIQ
    # was offered the world aggregate of the very statistic it asks about.
    semis = real_engine(tmp_path, monkeypatch, api, RealSources(api),
                        question="Will global semiconductor sales exceed $1 trillion by 2030?")
    history = lr.Kiq("K5", "What is the historical growth rate of semiconductor sales including downturns "
                           "(base rate)?", [], kind="data")
    assert hint_line(semis._kiq_task(history, [])) == ""
    china = real_engine(tmp_path / "chn", monkeypatch, api, RealSources(api), question="2027年中国实际GDP增速会低于4%吗？")
    growth = lr.Kiq("K1", "中国2024年至2026年的实际GDP增速分别是多少？", [], kind="data")
    hints = hint_line(china._kiq_task(growth, []))
    assert "wb:WB_WDI_NY_GDP_MKTP_KD_ZG/CHN — GDP (annual % growth): China" in hints
    assert "/WLD" not in hints and "G001" not in hints
    # A world price has no national counterpart in the catalog: it stays a fit.
    nev = real_engine(tmp_path / "nev", monkeypatch, api, RealSources(api),
                      question="Will China's new-energy-vehicle share of car sales exceed 60% in 2027?")
    lithium = lr.Kiq("K4", "How have lithium and battery raw-material prices moved since 2024?", [], kind="data")
    assert hint_line(nev._kiq_task(lithium, [])).startswith("imf:PCPS/G001.PLITH.USD.M — Lithium")
    # Base-rate wording names the method, not the statistic: the CPI base rate
    # keeps its CPI series (and the engine still reads it as a base-rate KIQ).
    cpi = real_engine(tmp_path / "cpi", monkeypatch, api, RealSources(api), question=CPI_FED)
    episodes = lr.Kiq("K5", "Historically, how often has US CPI inflation fallen from above 3% to below 2.5% "
                            "within 15 months?", [], kind="general")
    task = cpi._kiq_task(episodes, [])
    assert "fred:CPIAUCSL — " in hint_line(task) and "This question needs long history" in task


def test_an_open_need_says_what_to_do_when_no_series_measures_it(tmp_path, monkeypatch, api):
    engine = real_engine(tmp_path, monkeypatch, api, RealSources(api),
                         question="Will China's new-energy-vehicle share of car sales exceed 60% in 2027?")
    kiq = lr.Kiq("K1", "What is China's new-energy-vehicle share of passenger car sales in 2026?", [], kind="data",
                 data_needs=[{"query": "new energy vehicle sales share", "geography": "CHN"}])
    assert ("Official data the plan asked for that no catalog series answers (look each up with data_search and "
            "data_get a result only when its title, units and geography measure it; when none does, say that no "
            "official series covers it): new energy vehicle sales share (CHN)") in engine._kiq_task(kiq, []).splitlines()


def test_a_gap_follow_up_that_asked_for_official_series_gets_series_hints(tmp_path, monkeypatch, api):
    # A gap follow-up is always planned "general"; one that names data needs is
    # a data question (its need may resolve to nothing the agent can read yet).
    engine = real_engine(tmp_path, monkeypatch, api, RealSources(api),
                         question="What will the euro-area deposit facility rate be at the end of 2026?")
    followup = lr.Kiq("G1F1", "What is the euro-area unemployment rate and its trend?", [], round=1,
                      data_needs=[{"query": "unemployment rate", "geography": "Euro area"}])
    assert "imf:WEO/G163.LUR.A — Unemployment rate: Euro Area" in hint_line(engine._kiq_task(followup, []))
    # Without needs, its own words still name a statistic a series measures, so it keeps the hint
    # (live eval 2026-10-14: an "actor" KIQ on the Fed's rate path got none and fetched no data) ...
    followup.data_needs = []
    assert "imf:WEO/G163.LUR.A — Unemployment rate: Euro Area" in hint_line(engine._kiq_task(followup, []))
    # ... while a KIQ naming no statistic gets none, and never the research question's series.
    quiet = lr.Kiq("G1F2", "How did ECB officials describe the outlook in recent speeches?", [], round=1)
    assert hint_line(engine._kiq_task(quiet, [])) == ""


def test_a_base_rate_kiq_without_needs_reads_the_long_history_of_the_series_other_kiqs_need(
        tmp_path, monkeypatch, api):
    # pipe_261de6107490 and the rendered CPI, ECB and China-GDP plans: the base-rate
    # KIQ named no series while other KIQs did, so the shared series were stored
    # with the default window, which a run never widens.
    source = RealSources(api)
    engine = real_engine(tmp_path, monkeypatch, api, source, question="Will US unemployment exceed 5% by the end of 2027?")
    engine.kiqs = [
        lr.Kiq("K1", "What is the latest US unemployment rate?", [], kind="data", data_needs=[{"series": "fred:UNRATE"}]),
        lr.Kiq("K2", "What is the US policy rate?", [], kind="data", data_needs=[{"series": "bis:WS_CBPOL/M.US"}]),
        lr.Kiq("K3", "Who sits on the FOMC this year?", [], kind="actor"),
        lr.Kiq("K4", "Historically, how often has the US unemployment rate risen by a full percentage point "
                     "within a year?", [], kind="general")]
    requested = engine._data_requests(engine.kiqs)
    assert requested == {"fred:UNRATE": ["K1", "K4"], "bis:WS_CBPOL/M.US": ["K2"]}
    engine.phase_data()
    starts = {call[1]: call[2].get("start") for call in source.calls if call[0] == "get"}
    assert starts == {"fred:UNRATE": "1996-01-01", "bis:WS_CBPOL/M.US": None}
    unrate = sid_of(engine, "fred:UNRATE")
    assert engine.data_index["K4"] == [unrate]
    retrieved = engine._kiq_task(engine.kiqs[3], []).split("— OFFICIAL DATA ALREADY RETRIEVED", 1)[1]
    assert f"[S{unrate}] fred:UNRATE" in retrieved
    # A base-rate KIQ that names its own series is left as it is.
    engine.kiqs[3].data_needs = [{"series": "fred:PAYEMS"}]
    assert engine._data_requests(engine.kiqs)["fred:UNRATE"] == ["K1"]


EVAL_US_INFLATION = ("Will US CPI inflation fall below 2.5% year over year by December 2027, and how will the "
                     "Federal Reserve policy rate evolve through 2027?")


def test_a_kiq_the_planner_left_without_needs_gets_the_series_its_own_words_name(tmp_path, monkeypatch, api):
    # Live eval 2026-10-14 (the plan below, verbatim KIQs): the planner gave needs only to
    # the CPI KIQ and the base-rate KIQ, so the Fed-path "actor" KIQ stored no policy rate,
    # got no catalog hint and made no data call.
    source = RealSources(api)
    engine = real_engine(tmp_path, monkeypatch, api, source, question=EVAL_US_INFLATION)
    engine.kiqs = [
        lr.Kiq("K1", "What is the current level and trajectory of US headline and core CPI inflation as of "
                     "September/October 2026, and what do the latest BLS releases show for 12-month rates and "
                     "monthly momentum?", [], kind="data",
               data_needs=[{"series": "fred:CPIAUCSL#yoy"}, {"series": "fred:CPILFESL#yoy"},
                           {"series": "fred:PCEPI#yoy"}]),
        lr.Kiq("K2", "What do the Fed's September 2026 Summary of Economic Projections and FOMC communications "
                     "imply for the federal funds rate path and inflation through 2027?", [], kind="actor"),
        lr.Kiq("K3", "Who chairs the FOMC and how did the committee vote in September 2026?", [], kind="actor"),
        lr.Kiq("K4", "How often historically has US CPI inflation fallen below 2.5% year over year within 15 months "
                     "of a peak above 3.5%, and what leading indicators (expectations, breakevens, core momentum) "
                     "preceded such declines since 1996?", [], kind="general",
               data_needs=[{"series": "fred:CPIAUCSL#yoy"}, {"series": "fred:T10YIE"}, {"series": "fred:MICH"}])]
    requested = engine._data_requests(engine.kiqs)
    # Its two statistics: the stored CPI rate is linked free, the policy rate takes a free slot.
    mine = [identity for identity, kids in requested.items() if "K2" in kids]
    rate = [identity for identity in mine if identity != "fred:CPIAUCSL#yoy"]
    assert "fred:CPIAUCSL#yoy" in mine and len(rate) == 1, requested
    assert rate[0] in {"fred:DFEDTARU", "fred:FEDFUNDS", "fred:DFF", "bis:WS_CBPOL/M.US"}, requested
    # A KIQ whose own words name no statistic is left alone; the needs are untouched.
    assert not any("K3" in kids for kids in requested.values())
    assert requested["fred:CPIAUCSL#yoy"] == ["K1", "K4", "K2"] and len(requested) == 6
    # Its catalog hints take its statistics in turn: a policy rate beside the CPI series.
    hints = hint_line(engine._kiq_task(engine.kiqs[1], []))
    assert "fred:FEDFUNDS" in hints and "fred:CPIAUCSL" in hints, hints


FED_FUNDS = ("Forecast the federal funds rate (upper bound of the target range) at year-end 2026. Include the current "
             "target range, recent FOMC decisions and forward guidance, inflation and labor market trajectories, and "
             "market-implied probabilities from fed funds futures.")


def test_a_base_rate_kiq_no_requested_series_measures_takes_its_best_catalog_series(tmp_path, monkeypatch, api):
    # pipe_261de6107490: K7 asked for fed funds base rates while the planner
    # needed the target range (FRED holds it from 2008 only), CPI and labour
    # series; no stored series measured K7, which called past terminal rates
    # "not verifiable from fetched pages".
    engine = real_engine(tmp_path, monkeypatch, api, RealSources(api), question=FED_FUNDS)
    k7 = lr.Kiq("K7", "What are historical base rates for the fed funds rate path in the final quarter of a tightening "
                      "cycle, and what risks (fiscal, tariffs, credit) could force a deviation?", [], kind="general")
    engine.kiqs = [lr.Kiq("K1", "What is the current target range?", [], kind="data",
                          data_needs=[{"series": "fred:DFEDTARU"}]),
                   lr.Kiq("K3", "What is the inflation trajectory?", [], kind="data",
                          data_needs=[{"series": "fred:CPIAUCSL"}]),
                   lr.Kiq("K4", "What is the labour market trajectory?", [], kind="data",
                          data_needs=[{"series": "fred:UNRATE"}]), k7]
    requested = engine._data_requests(engine.kiqs)
    assert requested == {"fred:DFEDTARU": ["K1"], "fred:CPIAUCSL": ["K3"], "fred:UNRATE": ["K4"],
                         "fred:FEDFUNDS": ["K7"]}
    assert engine._data_windows(requested) == {"fred:FEDFUNDS": ("1996", None)}
    # Only a free prefetch slot takes it: the planner's needs come first.
    engine.kiqs[0].data_needs.append({"series": "fred:DFEDTARL"})
    engine.kiqs[2].data_needs += [{"series": "fred:U6RATE"}, {"series": "fred:CIVPART"}]
    assert engine._prefetch_cap() == 6 and "fred:FEDFUNDS" not in engine._data_requests(engine.kiqs)


def test_kiq_task_says_when_official_data_fits_and_how_to_count_a_base_rate(tmp_path, monkeypatch, api):
    engine = real_engine(tmp_path, monkeypatch, api, RealSources(api), question=CPI_FED)
    actor = lr.Kiq("K3", "Who sits on the FOMC this year?", [], kind="actor")
    task = engine._kiq_task(actor, [])
    assert ("When to use them: when this question needs a statistic an official series measures" in task
            and "a search result for another concept or place is no proxy, so say instead that no official "
                "series covers it." in task and "Official series that may fit" not in task)
    history = lr.Kiq("K5", "Historically, how often has US CPI inflation fallen from above 3% to below 2.5% within "
                           "15 months?", [], kind="general")
    task = engine._kiq_task(history, [])
    # The retrieved block shows a series' latest points only: counting needs its whole stored page.
    assert ("This question needs long history: data_get a stored series to read its whole stored history (free; "
            "OFFICIAL DATA ALREADY RETRIEVED shows only its latest points)" in task)
    assert ('start="1996" (a series keeps the window it was first stored with). Count comparable episodes in the '
            "stored history" in task and "so tag that finding REPORTED." in task)
    engine.data_enabled = False
    assert "When to use them" not in engine._kiq_task(actor, []) and "Count comparable" not in engine._kiq_task(
        history, [])


def test_summary_and_critique_headlines_carry_the_publisher_projection_to_the_horizon(tmp_path, monkeypatch, api):
    # Q6 "2027年中国实际GDP增速会低于4%吗？" rendered: the summary saw IMF WEO's
    # 2025 estimate but not its 2027 projection, the outside view of the question.
    monkeypatch.setattr(api, "catalog_field", lambda entry, name: "")  # keep the IMF WEO id (projections to 2031)
    engine = stored_engine(tmp_path, monkeypatch, api, ["fred:UNRATE", "imf:WEO/USA.NGDP_RPCH.A"])
    engine.plan.horizon = "by December 2028"
    weo = sid_of(engine, "imf:WEO/USA.NGDP_RPCH.A")
    series = next(series for series, sid in engine._data_rows() if sid == weo)
    outlook = lr.data_outlook_headline(series, weo, lr.ENGLISH, engine._data_horizon())
    assert outlook == (lr.data_headline(series, weo, lr.ENGLISH)
                       + "; publisher projection, not observed: 2027 2.1%, 2028 2.1%")
    assert "not observed: 2027 2.1%, 2028 2.1%, 2029 " in lr.data_digest_line(series, weo, lr.ENGLISH)
    seen = []
    engine.json_call = lambda shared, task, **kwargs: seen.append(task) or {"issues": []}
    sections = [{"index": s.index, "title": s.title, "body": "Body text. " * 30, "is_scenario": s.is_scenario}
                for s in engine.plan.sections]
    engine._critique("Summary", sections, "context", rg.Deadline(10_000))
    def write(messages, **kwargs):
        seen.append(messages[-1].content)
        raise rg.GatewayError("fixture")
    engine._write_call = write
    engine._exec_summary(sections, rg.Deadline(10_000))
    for task in seen:
        assert outlook in task and "4.2% (2026-09; stored observation)" in task
    assert "set the forecast against, never an observation" in seen[1]
    assert "departs from a listed publisher projection for the horizon" in seen[0]


def test_writer_task_points_each_section_to_its_official_series_and_the_scenarios_to_projections(
        tmp_path, monkeypatch, api):
    monkeypatch.setattr(api, "catalog_field", lambda entry, name: "")
    engine = stored_engine(tmp_path, monkeypatch, api, ["fred:UNRATE", "imf:WEO/USA.NGDP_RPCH.A"])
    unrate, weo = sid_of(engine, "fred:UNRATE"), sid_of(engine, "imf:WEO/USA.NGDP_RPCH.A")
    sections = {section.index: section for section in engine.plan.sections}
    first = next(s for s in sections.values() if "K1" in s.kiq_ids and not s.is_scenario)
    task = engine.section_task([first])
    assert (f'- Official series in the evidence for "{first.title}": [S{unrate}] Unemployment Rate — United States; '
            "cite them where they bear on its focus.") in task
    scenario = next(s for s in sections.values() if s.is_scenario)
    assert (f"- Publisher projections to set the scenarios against (the publisher's outlook, never an observation): "
            f"[S{weo}] ") in engine.section_task([scenario])
    # A series a KIQ's agent fetched joins its section too; a section with no
    # official evidence gets no pointer.
    empty = lr.OutlineSection(99, "Outlook", ["K3"])
    assert "Official series in the evidence" not in engine.section_task([empty])
    engine.records["K3"] = {"stats": {"data": {"stored": ["fred:UNRATE"]}}}
    assert f'- Official series in the evidence for "Outlook": [S{unrate}] ' in engine.section_task([empty])


def test_disabled_run_meta_keeps_the_data_sources_keys_of_a_data_free_run(tmp_path, monkeypatch, api):
    from test_research_engine_v3 import World, run_engine
    monkeypatch.setenv("DATA_SOURCES_ENABLED", "false")
    monkeypatch.setattr(api, "get_data_sources", lambda **kwargs: pytest.fail("a disabled run builds no providers"))
    bridge = SimpleNamespace(_collect_prediction_markets=lambda *a, **kw: None,
                             _render_research_charts=lambda *a, **kw: None)
    rc, meta, log, _, out = run_engine(tmp_path, bridge, World(), depth="quick")
    assert rc == 0, log.text()
    data_free = {"status": "disabled", "providers": {}, "calls": 0, "failures": 0, "cached": 0,
                 "series_count": 0, "route_counts": {}, "per_agent": {}}
    assert meta["data_sources"] == data_free
    assert json.loads((out / "meta.json").read_text())["data_sources"] == data_free
    assert "data_calls" not in meta["kiqs"]
    assert all("data" not in json.loads(path.read_text())["stats"] for path in (out / "v3/kiq").glob("*.json"))
    # A resumed attempt reports its stored-only state with the same keys.
    rc, meta, log, _, _ = run_engine(tmp_path, bridge, World(), depth="quick", out_dir=out)
    assert rc == 0, log.text()
    assert meta["data_sources"] == {**data_free, "status": "stored_only"}


def test_resume_after_the_data_phase_keeps_data_tools_for_unfinished_kiqs_and_renders_charts_at_qa(
        tmp_path, monkeypatch, api):
    """pipe_261de6107490: the data phase stored 8 series, the QA chart renderer
    exited 1 (render_data.py was being edited) and a resumed attempt only
    finalized, so meta showed 0 data calls.  Here an outage stops the first
    attempt right after its data phase: the resumed attempt configures the
    providers again, its agents keep the data tools and their seeds, a new
    series is fetched, the real renderer draws every stored series at QA, and
    the KIQ records keep each agent's data use across attempts."""
    import deerflow_research as bridge_module
    from test_research_engine_v3 import World, ai, run_engine
    source = FixtureSources(api)
    monkeypatch.setenv("DATA_SOURCES_ENABLED", "true")
    monkeypatch.setattr(api, "get_data_sources", lambda **kwargs: source)
    monkeypatch.setattr(bridge_module, "_charts_python", lambda: sys.executable)

    class DataWorld(World):
        def plan(self, call):
            obj = rg.parse_json_object(super().plan(call).content, ("kiqs",))
            obj["kiqs"][0]["data_needs"] = [{"series": "fred:UNRATE"}]
            return ai(json.dumps(obj))

        def agent(self, call):
            messages = call["messages"]
            if "Investigate K1:" in messages[2][1] and not any(kind == "tool" for kind, _ in messages):
                return ai(tool_calls=[{"name": "data_get", "args": {"series": "fred:PAYEMS"}, "id": "K1-d1"}])
            return super().agent(call)

    def outage(call, role):
        return Exception("Error code: 401 - invalid api key") if role == "agent" else None

    bridge = SimpleNamespace(_collect_prediction_markets=lambda *a, **kw: None,
                             _render_research_charts=lambda *a, **kw: None,
                             _render_data_charts=bridge_module._render_data_charts)
    rc, meta, log, _, out = run_engine(tmp_path, bridge, DataWorld(fail=outage), depth="quick")
    assert rc == 2, log.text()
    phases = json.loads((out / "v3/state.json").read_text())["phases"]
    assert phases["data"]["status"] == "done" and phases["gather"]["status"] != "done"
    assert [call[1] for call in source.calls] == ["fred:UNRATE"]

    rc, meta, log, model, _ = run_engine(tmp_path, bridge, DataWorld(), depth="quick", out_dir=out)
    assert rc == 0, log.text()
    assert meta["data_sources"]["status"] == "enabled" and source.prewarms == 2
    agent_calls = [call for call in model.calls if call["tools"] is not None]
    assert agent_calls and all(call["tools"] is rg.AGENT_TOOLS_WITH_DATA_SCHEMA for call in agent_calls)
    k1 = [call for call in agent_calls if "Investigate K1:" in call["messages"][2][1]]
    assert "OFFICIAL DATA ALREADY RETRIEVED" in k1[0]["messages"][2][1]
    replies = [content for kind, content in k1[-1]["messages"] if kind == "tool"]
    assert replies[0].startswith("[S") and "dataset fred:PAYEMS" in replies[0].split("\n", 1)[0]
    assert [call[1] for call in source.calls] == ["fred:UNRATE", "fred:PAYEMS"]
    # QA rendered both stored series with the real renderer and embedded them.
    charts = [row for row in json.loads((out / "charts.json").read_text())
              if str(row.get("id", "")).startswith("data_")]
    assert {identity for row in charts for identity in row["series"]} == {"fred:UNRATE", "fred:PAYEMS"}
    assert all((out / row["path"]).read_bytes().startswith(b"\x89PNG\r\n\x1a\n") for row in charts)
    report = (out / "research_report.md").read_text()
    assert all(row["path"] in report for row in charts) and "Official Data Baseline" in report
    exhibits = next(check for check in meta["research_qa"]["checks"] if check["name"] == "data_exhibits")
    assert exhibits["passed"] and f"{len(charts)} existing official-data figures" in exhibits["detail"]
    # The KIQ record keeps its agent's data use; meta sums every attempt's records.
    k1_stats = json.loads((out / "v3/kiq/K1.json").read_text())["stats"]["data"]
    assert k1_stats == {"calls": 1, "stored": ["fred:UNRATE", "fred:PAYEMS"], "failed": []}
    assert meta["kiqs"]["data_calls"] == 1
    # A later finalize-only resume still shows them although it made no call.
    rc, meta, log, _, _ = run_engine(tmp_path, bridge, DataWorld(), depth="quick", out_dir=out)
    assert rc == 0 and meta["data_sources"]["status"] == "stored_only" and meta["data_sources"]["calls"] == 0
    assert meta["kiqs"]["data_calls"] == 1 and len(source.calls) == 2
