"""Target-first production route using real engine/gateway/tools and paid-call-free fixtures."""
from __future__ import annotations

import copy
import json
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "deerflow_bridge"))
import forecast_case as fc
import target_research as tr
import test_research_engine_v3 as v3


@pytest.fixture
def bridge(monkeypatch):
    """Retain the existing network-free bridge lifecycle without import aliases."""
    yield from v3.bridge.__wrapped__(monkeypatch)


@pytest.fixture(autouse=True)
def _hermetic_env(monkeypatch):
    v3._hermetic_env.__wrapped__(monkeypatch)


@pytest.fixture
def restore_environ():
    yield from v3.restore_environ.__wrapped__()

QUESTION = "Will global data-centre capacity exceed 250 GW by the end of 2027?"
AS_OF = "2026-10-27"
QUOTE = "Installed capacity was 176 GW as of 2026-10-26."
URL = "https://statistics.example.test/release"


def planned_case():
    def node(nid, low, high):
        return {"nodeId": nid, "label": nid + " capacity", "units": "GW", "status": "unknown", "value": None,
                "range": {"low": low, "high": high}, "vintage": None, "sourceIds": [], "claimIds": [],
                "sensitivity": 1, "evidenceAvailability": 1, "retrievalCost": 1, "pivotal": True,
                "visibility": "public", "basis": "assumed", "gap": "Unmeasured planning bounds, not observed facts."}
    return {"schemaVersion": "forecast-case/v1", "authority": tr.AUTHORITY, "caseId": "capacity-test",
            "question": QUESTION, "asOf": AS_OF, "revision": 1,
            "resolution": {"targetNodeId": "target", "horizon": "2027-12-31", "units": "GW",
                           "settlementSource": {"name": "Statistics Agency", "url": URL, "releaseLagDays": 90},
                           "comparatorPolicy": "First official calendar-year capacity release; strictly greater than 250 GW."},
            "nodes": [node("base", 100, 250), node("target", 100, 400)], "sources": [], "claims": [],
            "mechanisms": [{"mechanismId": "capacity", "kind": "linear", "inputNodeIds": ["base"],
                            "outputNodeId": "target", "parameters": {"coefficients": [{"low": 1.2, "high": 1.8, "basis": "assumed", "gap": "Multiplier unmeasured."}],
                                           "intercept": {"low": 0, "high": 0, "basis": "assumed", "gap": "No separate offset modeled."}},
                            "basis": "assumed", "sourceIds": [], "gap": "Unobserved growth multiplier."}],
            "actors": [], "scenarios": [
                {"scenarioId": "below", "label": "At most 250", "predicate": {"nodeId": "target", "operator": "lte", "value": 250}},
                {"scenarioId": "above", "label": "Above 250", "predicate": {"nodeId": "target", "operator": "gt", "value": 250}}],
            "assessments": [{"assessmentId": "prior-1", "version": 1, "kind": "prior",
                             "scenarioWeights": {"below": 0.5, "above": 0.5}, "updates": []}], "binaries": []}


def source(**extra):
    return {"sourceId": "S1", "url": URL, "title": "Capacity release", "publishedAt": "2026-10-26",
            "retrievedAt": "2026-10-27T00:00:00Z", "originCluster": "official-statistics",
            "tier": "primary", "fetched": True, "passage": QUOTE, **extra}


def finding(**extra):
    return {"claimId": "C1", "nodeId": "base", "sourceIds": ["S1"], "passage": QUOTE,
            "status": "verified", "value": 176, "vintage": "2026-10-26", **extra}


def assessment():
    return {"assessmentId": "posterior-2", "version": 2, "kind": "posterior",
            "scenarioWeights": {"below": 0.3, "above": 0.7}, "updates": [
                {"evidenceId": "C1", "nodeId": "base", "scenarioId": sid, "direction": direction, "size": 0.2,
                 "oldWeight": 0.5, "newWeight": weight, "reason": "Dated capacity evidence changes the forecast."}
                for sid, direction, weight in [("below", "decrease", 0.3), ("above", "increase", 0.7)]]}


def test_build_case_grounding_posterior_and_immutability():
    plan = planned_case()
    original = copy.deepcopy(plan)
    case = tr.build_case({"forecastCase": plan}, {"findings": [finding()], "assessment": assessment()},
                         [source()], question=QUESTION, as_of=AS_OF)
    assert plan == original
    assert case["nodes"][0]["status"] == "settled"
    assert case["assessments"][0] == original["assessments"][0]
    assert case["assessments"][-1]["scenarioWeights"]["above"] == 0.7
    assert "0.7" in tr.render_case_research(case)
    assert fc.case_hash(case)


@pytest.mark.parametrize("mutate,match", [
    (lambda f: f.update(sourceIds=["S999"]), "passage"),
    (lambda f: f.update(passage="The number is 999."), "passage"),
    (lambda f: f.update(value=999), "numeric value"),
    (lambda f: f.update(vintage="2026-10-25"), "vintage"),
    (lambda f: f.update(nodeId="invented"), "unknown node"),
])
def test_rejects_fabricated_findings(mutate, match):
    f = finding()
    mutate(f)
    with pytest.raises(ValueError, match=match):
        tr.build_case({"forecastCase": planned_case()}, [f], [source()], question=QUESTION, as_of=AS_OF)


def test_undated_secondary_evidence_cannot_settle_and_origins_do_not_multiply():
    case = tr.build_case({"forecastCase": planned_case()}, [finding(vintage=None)],
                         [source(tier="secondary", publishedAt=None, originCluster="unknown")],
                         question=QUESTION, as_of=AS_OF)
    assert case["claims"][0]["status"] == "reported"
    assert case["nodes"][0]["status"] == "unknown"
    assert case["sources"][0]["publishedAt"] is None
    assert tr.research_priorities(case)[0]["independentOrigins"] == 0
    with pytest.raises(ValueError, match="no verified"):
        raw = planned_case()
        raw["nodes"][0].update(status="settled", value=176, vintage="2026-10-26")
        tr.build_case({"forecastCase": raw}, [], [source()], question=QUESTION, as_of=AS_OF)


def test_conflicting_numeric_evidence_remains_contested():
    first = tr.build_case({"forecastCase": planned_case()}, [finding()], [source()], question=QUESTION, as_of=AS_OF)
    other = source(sourceId="S2", passage="Installed capacity was 180 GW as of 2026-10-26.", originCluster="independent-survey")
    case = tr.build_case({"forecastCase": first}, [finding(claimId="C2", sourceIds=["S2"], passage=other["passage"], value=180)],
                         [source(), other], question=QUESTION, as_of=AS_OF)
    assert case["nodes"][0]["status"] == "contested"
    assert case["nodes"][0]["value"] is None
    assert case["nodes"][0]["range"] == {"low": 176, "high": 180}
    assert tr.research_priorities(case)[0]["reason"] == "numeric conflict"


class TargetWorld(v3.World):
    def __init__(self, bad_plan=False, bad_evidence=False):
        super().__init__()
        self.bad_plan = bad_plan
        self.bad_evidence = bad_evidence

    def __call__(self, call):
        task = call["messages"][-1][1]
        if task.startswith("TARGET CASE PLANNING TASK"):
            case = planned_case()
            if self.bad_plan:
                case["resolution"]["targetNodeId"] = "invented"
            return v3.ai(json.dumps({"forecastCase": case}))
        if task.startswith("TARGET FINDINGS TASK"):
            # Repeated gaps emit no duplicate facts. Sources must be the actual
            # canonical ledger identities delivered by real tools, not stubs.
            assert "Installed capacity was 176 GW" in task
            if '"claimId": "C1"' in task:
                return v3.ai(json.dumps({"findings": []}))
            f = finding(value=999) if self.bad_evidence else finding()
            return v3.ai(json.dumps({"findings": [f]}))
        if task.startswith("TARGET MECHANISM BINDING TASK"):
            return v3.ai(json.dumps({"mechanisms": planned_case()["mechanisms"], "mechanismEvidence": []}))
        if task.startswith("TARGET ASSESSMENT TASK"):
            assert '"claimId": "C1"' in task
            return v3.ai(json.dumps({"assessment": assessment(), "binaries": [{
                "binaryId": "B1", "question": QUESTION,
                "predicate": {"nodeId": "target", "operator": "gt", "value": 250},
                "probability": 0.7, "sourceIds": ["S1"]}]}))
        return super().__call__(call)


def install_target_fixture(monkeypatch, *, gaps=1, retrieval_date=AS_OF):
    monkeypatch.setattr(v3.lr, "_utc_date", lambda: AS_OF)
    # SourceLedger stamps both registration and fetch through this module's
    # wall clock. Keep the real tools/ledger and monotonic budgets; replacing
    # the module reference avoids changing the shared stdlib time module.
    fixed_utc = time.strptime(retrieval_date, "%Y-%m-%d")
    gateway_time = SimpleNamespace(**vars(v3.rg.time))
    gateway_time.gmtime = lambda seconds=None: fixed_utc if seconds is None else time.gmtime(seconds)
    monkeypatch.setattr(v3.rg, "time", gateway_time)
    monkeypatch.setenv("RESEARCH_SKILLS", "off")
    monkeypatch.setenv("RESEARCH_LINEAR_GAP_ROUNDS", str(gaps))
    def search(query, n):
        return json.dumps({"results": [{"title": "Capacity release", "url": URL, "content": QUOTE,
            "published_at": "2026-10-26", "original_origin": "official-statistics", "publication_type": "official_statistics"}]})
    monkeypatch.setattr(v3, "fake_search", search)
    def fetch(url):
        return {"text": "# Capacity statistics\n\n" + QUOTE + "\n\n" + v3.page_text(url),
                "metadata": {"published_at": "2026-10-26", "original_origin": "official-statistics",
                             "publication_type": "official_statistics"}}
    return fetch


@pytest.mark.parametrize("wall_date", ["2026-10-28", "2030-01-01"])
@pytest.mark.parametrize("retrieval_date", [AS_OF, "2026-10-28"])
def test_real_engine_retrieval_clock_preserves_asof_validation(
        tmp_path, bridge, monkeypatch, wall_date, retrieval_date):
    # A later ambient gateway date must neither leak into valid fixtures nor
    # make future retrievals admissible against the fixed historical cutoff.
    ambient_time = SimpleNamespace(**vars(v3.rg.time))
    ambient_utc = time.strptime(wall_date, "%Y-%m-%d")
    ambient_time.gmtime = lambda seconds=None: ambient_utc if seconds is None else time.gmtime(seconds)
    monkeypatch.setattr(v3.rg, "time", ambient_time)
    assert v3.rg.time.strftime("%Y-%m-%d", v3.rg.time.gmtime()) == wall_date
    original_gmtime = time.gmtime
    fetch = install_target_fixture(monkeypatch, gaps=0, retrieval_date=retrieval_date)
    assert time.gmtime is original_gmtime
    assert v3.rg.time.monotonic is time.monotonic
    assert v3.rg.time.gmtime(0) == time.gmtime(0)
    rc, meta, _, _, out = v3.run_engine(tmp_path, bridge, TargetWorld(),
        args=v3.make_args(forecast_authority=tr.AUTHORITY), fetch=fetch)
    rows = json.loads((out / "v3/sources_ledger.json").read_text())
    expected = retrieval_date + "T00:00:00Z"
    assert rows and all(row["retrieved_at"] == expected for row in rows)
    fetched = [row for row in rows if row["fetched"]]
    assert all(row["fetched_at"] == expected for row in fetched)
    if retrieval_date == AS_OF:
        assert rc == 0, meta
        assert fetched, "The valid control must reach the real fetch boundary."
        case = fc.read_case(out / "forecast_case.json", expected_hash=meta["forecast_case_hash"])
        assert case["asOf"] == AS_OF
        assert all(row["retrievedAt"] == expected for row in case["sources"])
        assert case["nodes"][0]["value"] == 176
    else:
        assert rc == 2 and meta["status"] == "failed", meta
        assert "S1: source is unavailable at asOf or publication follows retrieval" in meta["error"]
        assert not (out / "forecast_case.json").exists()
        assert not (out / "research_report.md").exists()


def test_real_engine_target_producer_and_resume(tmp_path, bridge, monkeypatch):
    fetch = install_target_fixture(monkeypatch)
    args = v3.make_args(forecast_authority=tr.AUTHORITY)
    rc, meta, log, model, out = v3.run_engine(tmp_path, bridge, TargetWorld(), args=args, fetch=fetch)
    assert rc == 0, (meta, log.text())
    case = fc.read_case(out / "forecast_case.json", expected_hash=meta["forecast_case_hash"])
    assert case["nodes"][0]["value"] == 176
    assert case["assessments"][-1]["scenarioWeights"]["above"] == 0.7
    assert case["sources"][0]["passage"] and case["sources"][0]["publishedAt"] == "2026-10-26"
    assert len((out / "research_report.md").read_text()) >= 400
    state = json.loads((out / "v3/state.json").read_text())
    assert state["identity"]["forecast_authority"] == tr.AUTHORITY
    assert state["targetResearch"]["finalCaseHash"] == fc.case_hash(case)
    agent_tasks = [c["messages"][2][1] for c in model.calls if c["tools"] is not None]
    assert any("resolution node" in task for task in agent_tasks)
    assert any("Adversarial evidence" in task for task in agent_tasks)
    assert any("G1F" in task for task in agent_tasks), "Unresolved nodes must drive a follow-up even with zero new facts."
    for call in model.calls:
        if call["messages"][-1][1].startswith("TARGET ") or call["tools"] is not None:
            assert "never change a probability" not in call["messages"][0][1]
    assert not any(c["messages"][-1][1].startswith(("SECTION WRITING", "FACT EXTRACTION", "FORECAST FRAME", "CRITIQUE")) for c in model.calls)
    assert not bridge._v3_test_calls["markets"] and not bridge._v3_test_calls["charts"]
    assert json.loads((out / "forecast_inputs.json").read_text())["assessment"] == case["assessments"][-1]
    rc2, meta2, _, model2, _ = v3.run_engine(tmp_path, bridge, TargetWorld(), args=args, fetch=fetch, out_dir=out)
    assert rc2 == 0, meta2
    assert model2.calls == [], "A complete restart must reuse the immutable case without paid calls."
    assert meta2["forecast_case_hash"] == meta["forecast_case_hash"]


@pytest.mark.parametrize("kind", ["final", "checkpoint"])
def test_target_restart_rejects_tampering(tmp_path, bridge, monkeypatch, kind):
    fetch = install_target_fixture(monkeypatch, gaps=0)
    args = v3.make_args(forecast_authority=tr.AUTHORITY)
    rc, meta, _, _, out = v3.run_engine(tmp_path, bridge, TargetWorld(), args=args, fetch=fetch)
    assert rc == 0, meta
    path = out / ("forecast_case.json" if kind == "final" else "v3/target/assessed.json")
    raw = json.loads(path.read_text())
    raw["question"] = "A different target"
    path.write_text(json.dumps(raw))
    rc, meta, _, _, _ = v3.run_engine(tmp_path, bridge, TargetWorld(), args=args, fetch=fetch, out_dir=out)
    assert rc == 2 and meta["status"] == "failed"
    assert "changed" in meta["error"] or "hash mismatch" in meta["error"]


@pytest.mark.parametrize("options", [{"bad_plan": True}, {"bad_evidence": True}])
def test_target_failures_never_fall_back_to_prose(tmp_path, bridge, monkeypatch, options):
    fetch = install_target_fixture(monkeypatch, gaps=0)
    rc, meta, _, model, out = v3.run_engine(tmp_path, bridge, TargetWorld(**options),
                           args=v3.make_args(forecast_authority=tr.AUTHORITY), fetch=fetch)
    assert rc == 2 and meta["status"] == "failed"
    assert not (out / "forecast_case.json").exists()
    assert not (out / "research_report.md").exists()
    assert not any("EXTRACTION TASK" in c["messages"][-1][1] for c in model.calls)


def test_cli_rejects_legacy_only_target_flags_before_writes(tmp_path, monkeypatch):
    for flag in ("--extract-only", "--evidence-only", "--synthesis-manifest"):
        out = tmp_path / flag[2:]
        argv = ["deerflow_research.py", "--prompt", QUESTION, "--out-dir", str(out),
                "--forecast-authority", tr.AUTHORITY, flag]
        if flag == "--synthesis-manifest":
            argv.append(str(tmp_path / "manifest.json"))
        monkeypatch.setattr(sys, "argv", argv)
        with pytest.raises(SystemExit) as exc:
            v3.dr.main()
        assert exc.value.code == 2
        assert not out.exists()


def test_no_citation_laundering_or_projection_settlement():
    unrelated = source(sourceId="S2", passage="No data on capacity here.", originCluster="independent")
    with pytest.raises(ValueError, match="passage"):
        tr.build_case({"forecastCase": planned_case()}, [finding(sourceIds=["S1", "S2"])],
                      [source(), unrelated], question=QUESTION, as_of=AS_OF)
    quote = "The agency projects capacity of 176 GW as of 2026-10-26."
    case = tr.build_case({"forecastCase": planned_case()}, [finding(passage=quote)],
                         [source(passage=quote)], question=QUESTION, as_of=AS_OF)
    assert case["claims"][0]["status"] == "reported"
    assert case["nodes"][0]["status"] == "unknown"


def test_resume_freezes_evidence_metadata_and_does_not_reopen_gap_budget(tmp_path, bridge, monkeypatch):
    fetch = install_target_fixture(monkeypatch, gaps=0)
    args = v3.make_args(forecast_authority=tr.AUTHORITY)
    rc, meta, _, _, out = v3.run_engine(tmp_path, bridge, TargetWorld(), args=args, fetch=fetch)
    assert rc == 0, meta
    monkeypatch.setenv("RESEARCH_LINEAR_GAP_ROUNDS", "3")
    rc, meta, _, model, _ = v3.run_engine(tmp_path, bridge, TargetWorld(), args=args, fetch=fetch, out_dir=out)
    assert rc == 0 and model.calls == [], meta
    ledger_path = out / "v3/sources_ledger.json"
    rows = json.loads(ledger_path.read_text())
    rows[0]["origin_cluster"] = "invented-independent-origin"
    ledger_path.write_text(json.dumps(rows))
    rc, meta, _, model, _ = v3.run_engine(tmp_path, bridge, TargetWorld(), args=args, fetch=fetch, out_dir=out)
    assert rc == 2 and "evidence identity changed" in meta["error"]
    assert model.calls == []


def test_cli_target_dispatch_and_authority_pin(tmp_path, bridge, monkeypatch, restore_environ):
    fetch = install_target_fixture(monkeypatch, gaps=0)
    monkeypatch.setenv("RESEARCH_ENGINE", "legacy")
    monkeypatch.setenv("MINIMAX_API_KEY", "test-key-not-used")
    model = v3.ScriptedModel(TargetWorld())
    monkeypatch.setattr(v3.lr, "_default_gateway_factory", lambda args, log, bridge, preset:
        v3.rg.ModelGateway(model, log, max_concurrency=preset.workers, budget_units=preset.budget_units,
                           reserve_share=v3.lr.RESERVE_SHARE, sleep=lambda seconds: None))
    monkeypatch.setattr(v3.lr, "_default_tools_factory", lambda ledger, pages, bridge, log, limits:
        v3.rg.ResearchTools(ledger, pages, search_fn=v3.fake_search, fetch_fn=fetch, bridge=bridge, plog=log, limits=limits))
    out = tmp_path / "handoff"
    argv = ["deerflow_research.py", "--prompt", QUESTION, "--out-dir", str(out), "--model", "minimax"]
    monkeypatch.setattr(sys, "argv", [*argv, "--forecast-authority", tr.AUTHORITY])
    assert v3.dr.main() == 0
    meta = json.loads((out / "meta.json").read_text())
    assert meta["forecast_authority"] == tr.AUTHORITY and meta["research_engine"] == "v3"
    fc.read_case(out / "forecast_case.json", expected_hash=meta["forecast_case_hash"])
    original = {p.name: p.read_bytes() for p in out.iterdir() if p.is_file()}
    monkeypatch.setattr(sys, "argv", argv)
    with pytest.raises(SystemExit) as exc:
        v3.dr.main()
    assert exc.value.code == 2
    assert original == {p.name: p.read_bytes() for p in out.iterdir() if p.is_file()}


def test_raw_plan_cannot_launder_retained_passages():
    raw = planned_case()
    raw["sources"] = [source(passage="Installed capacity was 999 GW as of 2026-10-26.")]
    with pytest.raises(ValueError, match="passage"):
        tr.build_case({"forecastCase": raw}, [finding(value=999, passage=raw["sources"][0]["passage"])],
                      [source()], question=QUESTION, as_of=AS_OF)


def test_gateway_actual_selected_passages_and_metadata(tmp_path):
    ledger = v3.rg.SourceLedger(tmp_path / "ledger.json", capture_evidence=True)
    text = ("Navigation and history.\n\n" * 200 + QUOTE + "\n\n" +
            "Capacity survey explanation.\n\n" * 200)
    tools = v3.rg.ResearchTools(ledger, tmp_path / "pages", search_fn=lambda q, n: "[]",
        fetch_fn=lambda url: {"content": text, "metadata": {"published_at": "2026-10-26",
            "original_origin": "official-statistics", "publication_type": "statistical_release"}})
    shown = tools.fetch(URL, focus="installed capacity 176", agent_id="K1")
    assert QUOTE in shown
    rows = tr._engine_sources(type("Engine", (), {"ledger": ledger, "tools": tools})())
    assert QUOTE in rows[0]["passage"] and rows[0]["tier"] == "primary"
    assert rows[0]["originCluster"] == "official-statistics" and rows[0]["publishedAt"] == "2026-10-26"
    assert len(rows[0]["passage"]) < len(text)
    assert ledger.rows()[0]["passages"]


class BrokenAssessmentWorld(TargetWorld):
    def __call__(self, call):
        if call["messages"][-1][1].startswith("TARGET ASSESSMENT TASK"):
            return v3.ai(json.dumps({"assessment": {"assessmentId": "bad", "version": 999}}))
        return super().__call__(call)


@pytest.mark.parametrize("tamper", [False, True])
def test_partial_restart_pins_consumed_sources_before_model_calls(tmp_path, bridge, monkeypatch, tamper):
    fetch = install_target_fixture(monkeypatch, gaps=0)
    args = v3.make_args(forecast_authority=tr.AUTHORITY)
    rc, meta, _, _, out = v3.run_engine(tmp_path, bridge, BrokenAssessmentWorld(), args=args, fetch=fetch)
    assert rc == 2 and "posterior" in meta["error"]
    assert (out / "v3/target/gather-0.json").exists()
    if tamper:
        path = out / "v3/sources_ledger.json"
        rows = json.loads(path.read_text())
        rows[0]["origin_cluster"] = "laundered-origin"
        path.write_text(json.dumps(rows))
    rc, meta, _, model, _ = v3.run_engine(tmp_path, bridge, TargetWorld(), args=args, fetch=fetch, out_dir=out)
    if tamper:
        assert rc == 2 and "evidence identity changed" in meta["error"]
        assert model.calls == []
    else:
        assert rc == 0, meta
        assert len(model.calls) == 1
        assert model.calls[0]["messages"][-1][1].startswith("TARGET ASSESSMENT TASK")


def test_target_producer_preserves_official_dataset_evidence(tmp_path, bridge, monkeypatch):
    import data_sources
    import test_research_gateway_official_data as official
    fetch = install_target_fixture(monkeypatch, gaps=0)
    monkeypatch.setenv("DATA_SOURCES_ENABLED", "true")
    captured = {row["series"]: row for row in json.loads(official.FIXTURE.read_text())["series"]}
    provider = official.Sources(data_sources, captured)
    provider.enabled = lambda: True
    provider.providers = lambda: {"fred": {"status": "available"}}
    provider.prewarm = lambda: None
    monkeypatch.setattr(data_sources, "get_data_sources", lambda **kw: provider)
    # Inject the chosen official series at the route-selection boundary; data
    # fetch, normalization, persisted manifest/page, gather and case stay real.
    monkeypatch.setattr(v3.lr._Engine, "_data_requests", lambda self, kiqs, **kw:
                        {"fred:UNRATE": [kiqs[0].id]})
    rc, meta, log, _, out = v3.run_engine(tmp_path, bridge, TargetWorld(),
        args=v3.make_args(forecast_authority=tr.AUTHORITY), fetch=fetch)
    assert rc == 0, (meta, log.text())
    case = fc.read_case(out / "forecast_case.json")
    datasets = [s for s in case["sources"] if "drf_series=" in s["url"]]
    assert datasets and datasets[0]["tier"] == "primary" and datasets[0]["fetched"]
    assert datasets[0]["passage"] and "UNRATE" in datasets[0]["passage"]
    assert datasets[0]["publishedAt"] is None, "Retrieval time is not publication time."


def test_kiq_records_pin_evidence_before_round_completion(tmp_path, bridge, monkeypatch):
    fetch = install_target_fixture(monkeypatch, gaps=0)
    args = v3.make_args(forecast_authority=tr.AUTHORITY)
    original = v3.lr._Engine.gather_kiqs
    def interrupted_after_kiqs(self, *a, **kw):
        original(self, *a, **kw)
        raise RuntimeError("interrupted before round checkpoint")
    monkeypatch.setattr(v3.lr._Engine, "gather_kiqs", interrupted_after_kiqs)
    rc, meta, _, _, out = v3.run_engine(tmp_path, bridge, TargetWorld(), args=args, fetch=fetch)
    assert rc == 2 and "before round checkpoint" in meta["error"]
    state = json.loads((out / "v3/state.json").read_text())
    assert state["targetResearch"]["sourceBindings"]
    assert not (out / "v3/target/gather-0.json").exists()
    assert any(row["status"] == "done" for row in state["kiqs"].values())
    path = out / "v3/sources_ledger.json"
    rows = json.loads(path.read_text())
    rows[0]["origin_cluster"] = "altered-after-individual-kiq"
    path.write_text(json.dumps(rows))
    monkeypatch.setattr(v3.lr._Engine, "gather_kiqs", original)
    rc, meta, _, model, _ = v3.run_engine(tmp_path, bridge, TargetWorld(), args=args, fetch=fetch, out_dir=out)
    assert rc == 2 and "evidence identity changed" in meta["error"]
    assert model.calls == []


def test_source_metadata_does_not_invent_publication_or_independence(tmp_path):
    ledger = v3.rg.SourceLedger(tmp_path / "ledger.json", capture_evidence=True)
    rows = [ledger.register(f"https://publisher{n}.example.test/story", "Story", "Capacity 176 GW",
                            metadata={"tier": "primary", "evidence_tier": "primary", "published_at": "last week"})
            for n in range(2)]
    sources = tr.source_rows(rows)
    assert all(row["publishedAt"] is None and row["tier"] == "unknown" for row in sources)
    assert {row["originCluster"] for row in sources} == {"unknown"}
    assert all(row["retrievedAt"] for row in sources)


def market_fixture(tmp_path, monkeypatch):
    d = v3.dr
    clock = {"now": "2026-10-20T00:00:00+00:00", "failed": False, "empty": False, "calls": 0}
    monkeypatch.setenv("PREDICTION_MARKETS_ENABLED", "true")
    monkeypatch.setenv("PREDICTION_MARKETS_CACHE", "on")
    monkeypatch.setenv("PREDICTION_MARKETS_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("PREDICTION_MARKETS_HORIZON_RETRY", "false")
    monkeypatch.setenv("PREDICTION_MARKETS_PRICE_HISTORY", "false")
    monkeypatch.setattr(d, "_PM_TRANSPORT_UNAVAILABLE", False)
    monkeypatch.setattr(d, "_PM_TRANSPORT_ERROR_CLASSES", {})
    monkeypatch.setattr(d, "_utcnow", lambda: clock["now"])
    monkeypatch.setattr(d, "_pm_resolve_queries", lambda *a: ["capacity 2027"])
    monkeypatch.setattr(d, "score_market_relevance", lambda *a: {"m1": 9})
    monkeypatch.setattr(d, "_pm_backtest_policy", lambda: None)
    def snapshot(queries, **kwargs):
        clock["calls"] += 1
        kwargs["diagnostics"].update(attempted_query_count=len(queries),
            successful_query_count=0 if clock["failed"] else len(queries),
            transport_failure_count=len(queries) if clock["failed"] else 0)
        if clock["failed"] or clock["empty"]:
            return []
        return [{"market_id": "m1", "question": QUESTION, "implied_yes_prob": 0.65, "volume": 10000,
                 "exchange": "Polymarket", "url": "https://polymarket.com/event/capacity"}]
    monkeypatch.setattr(d, "_pm_snapshot", snapshot)
    def collect(name, question=QUESTION):
        out = tmp_path / name
        out.mkdir(exist_ok=True)
        report = "# Research\n\nEvidence for capacity.\n"
        (out / d.REPORT_FILENAME).write_text(report)
        meta = {}
        d._collect_prediction_markets(out, question, report, meta, v3.FakePlog(), model_name="test")
        return json.loads((out / d.PREDICTION_MARKETS_FILENAME).read_text()), meta, out
    return clock, collect


def test_evidence_snapshot_is_not_reread_during_source_conversion(tmp_path, monkeypatch):
    ledger = v3.rg.SourceLedger(tmp_path / "ledger.json", capture_evidence=True)
    tools = v3.rg.ResearchTools(ledger, tmp_path / "pages", search_fn=lambda q, n: "[]",
                              fetch_fn=lambda url: (QUOTE + "\n\n") * 12)
    tools.fetch(URL, agent_id="K1")
    snapshot = ledger.rows()
    ledger.register("https://late.example.test/new-source", "Late sibling result")
    monkeypatch.setattr(ledger, "rows", lambda: pytest.fail("source conversion must use its immutable snapshot"))
    result = tr._engine_sources(type("Engine", (), {"ledger": ledger, "tools": tools})(), snapshot)
    assert len(result) == 1 and result[0]["sourceId"] == "S1"
    assert snapshot[0]["content_sha256"]


@pytest.mark.parametrize("stamp", ["yesterday", "2026-10-26T12:00:00", "2026-02-30", "20261026"])
def test_source_dates_without_calendar_or_timezone_proof_stay_unknown(tmp_path, stamp):
    ledger = v3.rg.SourceLedger(tmp_path / "ledger.json", capture_evidence=True)
    row = ledger.register(URL, metadata={"published_at": stamp, "retrieved_at": stamp})
    converted = tr.source_rows([row])[0]
    assert converted["publishedAt"] is None
    assert converted["retrievedAt"] != stamp


def test_market_last_good_is_query_bound_stale_and_does_not_refresh_its_age(tmp_path, monkeypatch):
    clock, collect = market_fixture(tmp_path, monkeypatch)
    fresh, _, _ = collect("fresh")
    assert fresh["status"]["state"] == "fresh"
    files = list((tmp_path / "cache").glob("*.json"))
    assert len(files) == 1
    original = files[0].read_bytes()
    clock.update(now="2026-10-22T00:00:00+00:00", failed=True)
    stale, meta, out = collect("outage")
    assert stale["markets"] and stale["status"]["state"] == "stale"
    assert stale["as_of"] == fresh["as_of"]
    assert stale["fetched_at"] == fresh["fetched_at"]
    assert stale["cache"]["age_seconds"] == 2 * 86400
    assert "stale" in (out / v3.dr.REPORT_FILENAME).read_text().lower()
    assert files[0].read_bytes() == original, "A failed attempt must not overwrite the last-good generation."
    assert meta["prediction_markets_as_of"] == fresh["as_of"]
    mismatch, _, _ = collect("another-target", question=QUESTION.replace("250", "350"))
    assert not mismatch["markets"]


@pytest.mark.parametrize("mode", ["expired", "future", "corrupt", "off", "reachable-empty", "nonfinite"])
def test_market_cache_rejects_unusable_or_inappropriate_fallback(tmp_path, monkeypatch, mode):
    clock, collect = market_fixture(tmp_path, monkeypatch)
    collect("fresh")
    path, = (tmp_path / "cache").glob("*.json")
    clock.update(now="2026-10-22T00:00:00+00:00", failed=True)
    if mode == "expired":
        clock["now"] = "2026-10-28T00:00:00+00:00"
    elif mode == "future":
        clock["now"] = "2026-10-19T00:00:00+00:00"
    elif mode == "corrupt":
        path.write_text("{broken")
    elif mode == "off":
        monkeypatch.setenv("PREDICTION_MARKETS_CACHE", "off")
    elif mode == "reachable-empty":
        clock.update(failed=False, empty=True)
    elif mode == "nonfinite":
        raw = json.loads(path.read_text())
        def corrupt(obj):
            if isinstance(obj, dict):
                if "implied_yes_prob" in obj:
                    obj["implied_yes_prob"] = float("nan")
                for value in obj.values():
                    corrupt(value)
            elif isinstance(obj, list):
                for value in obj:
                    corrupt(value)
        corrupt(raw)
        path.write_text(json.dumps(raw))
    result, _, _ = collect("second")
    assert result["markets"] == []
    assert result["status"]["state"] != "fresh" and result["status"]["state"] != "stale"


def test_market_circuit_fallback_uses_no_query_model_or_transport(tmp_path, monkeypatch):
    clock, collect = market_fixture(tmp_path, monkeypatch)
    first, _, _ = collect("fresh")
    calls = clock["calls"]
    clock.update(now="2026-10-21T00:00:00+00:00", failed=True)
    monkeypatch.setattr(v3.dr, "_PM_TRANSPORT_UNAVAILABLE", True)
    monkeypatch.setattr(v3.dr, "_pm_resolve_queries", lambda *a: pytest.fail("circuit fallback must not call query model"))
    result, _, _ = collect("circuit")
    assert result["markets"] and result["status"]["state"] == "stale"
    assert result["as_of"] == first["as_of"] and clock["calls"] == calls


def test_market_backtests_never_read_live_last_good_cache(tmp_path, monkeypatch):
    from datetime import datetime
    from types import SimpleNamespace
    clock, collect = market_fixture(tmp_path, monkeypatch)
    collect("fresh")
    clock.update(now="2026-10-22T00:00:00+00:00", failed=True)
    monkeypatch.setattr(v3.dr, "_pm_backtest_policy", lambda: SimpleNamespace(
        cutoff=datetime.fromisoformat("2026-10-21T00:00:00+00:00"), as_of_iso="2026-10-21"))
    result, _, _ = collect("historical")
    assert result["markets"] == []
    assert result["status"]["state"] != "stale"


@pytest.mark.parametrize("mixed,dated", [(False, True), (False, False), (True, True)])
def test_carried_market_rows_are_never_stamped_as_current_fetches(tmp_path, monkeypatch, mixed, dated):
    clock, collect = market_fixture(tmp_path, monkeypatch)
    clock["now"] = "2026-10-22T00:00:00+00:00"
    carried = {"market_id": "old", "question": "Capacity constraints", "implied_yes_prob": 0.4,
               "volume": 50000, "exchange": "Polymarket", "captured_via": "prediction_market_search"}
    if dated:
        carried["captured_at"] = "2026-10-20T00:00:00+00:00"
    monkeypatch.setattr(v3.dr, "_load_tool_market_candidates", lambda out: [carried])
    monkeypatch.setattr(v3.dr, "score_market_relevance", lambda *a: {"old": 9, "m1": 9})
    monkeypatch.setenv("PREDICTION_MARKETS_REFRESH_WITH_TOOL_CANDIDATES", "true" if mixed else "false")
    result, _, out = collect("carried")
    assert result["markets"]
    assert result["status"]["state"] != "fresh"
    assert result["fetched_at"] != clock["now"]
    if dated:
        assert result["as_of"] == carried["captured_at"]
    else:
        assert result["as_of"] is None
    assert not list((tmp_path / "cache").glob("*.json"))
    text = (out / v3.dr.REPORT_FILENAME).read_text().lower()
    assert "stale" in text or "unknown" in text or "undated" in text


def test_market_cache_recursive_json_is_a_cache_miss(tmp_path, monkeypatch):
    clock, collect = market_fixture(tmp_path, monkeypatch)
    collect("fresh")
    path, = (tmp_path / "cache").glob("*.json")
    path.write_text("[" * 2000 + "0" + "]" * 2000)
    clock.update(failed=True, now="2026-10-22T00:00:00+00:00")
    result, _, _ = collect("recursive-cache")
    assert result["markets"] == [] and result["status"]["state"] == "unavailable"


def test_known_future_tool_market_observations_are_rejected(tmp_path, monkeypatch):
    clock, collect = market_fixture(tmp_path, monkeypatch)
    monkeypatch.setattr(v3.dr, "_load_tool_market_candidates", lambda out: [{
        "market_id": "future", "question": QUESTION, "implied_yes_prob": 0.7, "volume": 20000,
        "captured_at": "2026-10-25T00:00:00+00:00", "captured_via": "prediction_market_search"}])
    monkeypatch.setattr(v3.dr, "score_market_relevance", lambda *a: {"future": 9})
    clock.update(empty=True)
    result, _, _ = collect("future-observation")
    assert result["markets"] == []
    assert result["status"]["state"] == "unavailable"


def test_market_refresh_carries_only_provenance_from_duplicate_old_rows(tmp_path, monkeypatch):
    _, collect = market_fixture(tmp_path, monkeypatch)
    monkeypatch.setenv("PREDICTION_MARKETS_REFRESH_WITH_TOOL_CANDIDATES", "true")
    monkeypatch.setattr(v3.dr, "_load_tool_market_candidates", lambda out: [{
        "market_id": "m1", "question": QUESTION, "implied_yes_prob": 0.4, "volume": 20000,
        "best_bid": 0.39, "best_ask": 0.41, "one_day_price_change": -0.2,
        "captured_at": "2026-10-19T00:00:00+00:00", "captured_via": "prediction_market_search",
        "tool_queries": ["capacity"]}])
    result, _, _ = collect("duplicate-refresh")
    row, = result["markets"]
    assert row["implied_yes_prob"] == 0.65
    assert not {"best_bid", "best_ask", "one_day_price_change"} & row.keys()
    assert row["captured_via"] == "prediction_market_search" and row["tool_queries"] == ["capacity"]


class ForgedPlannerWorld(TargetWorld):
    def __call__(self, call):
        task = call["messages"][-1][1]
        if task.startswith("TARGET CASE PLANNING TASK"):
            case = planned_case()
            case["sources"] = [source(passage="Installed capacity was 999 GW as of 2026-10-26.",
                                      tier="unknown", originCluster="unknown", publishedAt=None)]
            return v3.ai(json.dumps({"forecastCase": case}))
        if task.startswith("TARGET FINDINGS TASK"):
            return v3.ai(json.dumps({"findings": [finding(value=999,
                passage="Installed capacity was 999 GW as of 2026-10-26.")]}))
        return super().__call__(call)


def test_engine_rejects_fabricated_planner_evidence_before_gather(tmp_path, bridge, monkeypatch):
    fetch = install_target_fixture(monkeypatch, gaps=0)
    rc, meta, _, model, out = v3.run_engine(tmp_path, bridge, ForgedPlannerWorld(),
        args=v3.make_args(forecast_authority=tr.AUTHORITY), fetch=fetch)
    assert rc == 2 and "fresh target planning cannot supply evidence" in meta["error"]
    assert not (out / "forecast_case.json").exists()
    assert not (out / "research_report.md").exists()
    assert not any(c["messages"][-1][1].startswith("TARGET FINDINGS") for c in model.calls)


def test_authenticated_checkpoint_retains_rotated_actual_passages(tmp_path, bridge, monkeypatch):
    fetch = install_target_fixture(monkeypatch, gaps=0)
    args = v3.make_args(forecast_authority=tr.AUTHORITY)
    rc, meta, _, _, out = v3.run_engine(tmp_path, bridge, BrokenAssessmentWorld(), args=args, fetch=fetch)
    assert rc == 2 and "posterior" in meta["error"]
    path = out / "v3/sources_ledger.json"
    rows = json.loads(path.read_text())
    rows[0]["passages"] = ["Operators reported capital expenditure of 1,234 million dollars in the first half."]
    path.write_text(json.dumps(rows))
    rc, meta, _, model, _ = v3.run_engine(tmp_path, bridge, TargetWorld(), args=args, fetch=fetch, out_dir=out)
    assert rc == 0, meta
    case = fc.read_case(out / "forecast_case.json")
    assert QUOTE in case["sources"][0]["passage"]
    assert len(model.calls) == 1


def test_case_ids_are_producer_random_and_resume_pinned(tmp_path, bridge, monkeypatch):
    import re
    fetch = install_target_fixture(monkeypatch, gaps=0)
    args = v3.make_args(forecast_authority=tr.AUTHORITY)
    ids = []
    for name in ("one", "two"):
        rc, meta, _, model, out = v3.run_engine(tmp_path, bridge, TargetWorld(), args=args, fetch=fetch,
                                              out_dir=tmp_path / name)
        assert rc == 0, meta
        case = fc.read_case(out / "forecast_case.json")
        state = json.loads((out / "v3/state.json").read_text())
        assert re.fullmatch(r"case_[a-f0-9]{32}", case["caseId"])
        assert case["caseId"] == state["targetResearch"]["caseId"] != planned_case()["caseId"]
        task = next(c["messages"][-1][1] for c in model.calls if c["messages"][-1][1].startswith("TARGET CASE PLANNING"))
        assert case["caseId"] in task
        ids.append(case["caseId"])
    assert ids[0] != ids[1]
    rc, meta, _, model, out = v3.run_engine(tmp_path, bridge, TargetWorld(), args=args, fetch=fetch,
                                         out_dir=tmp_path / "one")
    assert rc == 0 and model.calls == []
    assert fc.read_case(out / "forecast_case.json")["caseId"] == ids[0]
    state_path = out / "v3/state.json"
    state = json.loads(state_path.read_text())
    del state["targetResearch"]["caseId"]
    state_path.write_text(json.dumps(state))
    accepted = (out / "forecast_case.json").read_bytes()
    rc, meta, _, model, _ = v3.run_engine(tmp_path, bridge, TargetWorld(), args=args, fetch=fetch, out_dir=out)
    assert rc == 2 and "cannot relabel accepted case" in meta["error"] and model.calls == []
    assert (out / "forecast_case.json").read_bytes() == accepted


MECHANISM_QUOTE = "The observed calibration coefficient is 2.0 as of 2026-10-26."


def bound_mechanisms():
    mechanisms = copy.deepcopy(planned_case()["mechanisms"])
    mechanisms[0].update(basis="estimated", sourceIds=["S1"])
    mechanisms[0]["parameters"]["coefficients"] = [2.0]
    return {"mechanisms": mechanisms, "mechanismEvidence": [{"mechanismId": "capacity", "parameter": "coefficients.0",
            "claimIds": ["C2"], "sourceIds": ["S1"], "method": "quoted"}]}


class MechanismWorld(TargetWorld):
    def __call__(self, call):
        task = call["messages"][-1][1]
        if task.startswith("TARGET FINDINGS TASK"):
            return v3.ai(json.dumps({"findings": [finding(), finding(claimId="C2", passage=MECHANISM_QUOTE,
                                                                      value=None, status="reported")]}))
        if task.startswith("TARGET MECHANISM BINDING TASK"):
            assert MECHANISM_QUOTE in task
            return v3.ai(json.dumps(bound_mechanisms()))
        return super().__call__(call)


def test_evidence_updates_mechanism_through_persistence_runtime_and_report(tmp_path, bridge, monkeypatch):
    from app.services.target_simulation import run_paths
    from app.services.target_report import build_target_report
    fetch = install_target_fixture(monkeypatch, gaps=0)
    def with_mechanism(url):
        payload = fetch(url)
        payload["text"] += "\n\n" + MECHANISM_QUOTE
        return payload
    rc, meta, _, _, out = v3.run_engine(tmp_path, bridge, MechanismWorld(),
        args=v3.make_args(forecast_authority=tr.AUTHORITY), fetch=with_mechanism)
    assert rc == 0, meta
    case = fc.read_case(out / "forecast_case.json", expected_hash=meta["forecast_case_hash"])
    assert case["mechanisms"][0]["parameters"]["coefficients"] == [2.0]
    assert json.loads((out / "v3/target/mechanism-bindings.json").read_text())["mechanismEvidence"]
    simulation = run_paths(case, paths=2, periods=2, seed=4)
    assert all(path["targetValue"] == 352 for path in simulation["paths"])
    rendered = build_target_report(case, simulation)
    assert rendered["record"]["parameterBases"][0]["parameters"]["coefficients"] == [2.0]
    assert '2.0' in (out / "research_report.md").read_text()
    assert case["assessments"][-1]["scenarioWeights"]["above"] == 0.7


@pytest.mark.parametrize("change,match", [
    (lambda payload: payload.update(typoMechanisms=[]), "unknown target evidence"),
    (lambda payload: payload.pop("mechanismEvidence"), "lacks evidence binding"),
    (lambda payload: payload["mechanisms"][0]["parameters"].update(coefficients=[999]), "number absent"),
    (lambda payload: payload["mechanismEvidence"][0].update(claimIds=["library-only"]), "admitted primary"),
    (lambda payload: payload["mechanisms"][0]["parameters"].update(intercept=0), "number absent|lacks evidence"),
])
def test_mechanism_update_rejects_unbound_or_unknown_payloads(change, match):
    case = tr.build_case({"forecastCase": planned_case()}, [finding(), finding(claimId="C2", passage=MECHANISM_QUOTE,
                value=None, status="reported")], [source(passage=QUOTE + "\n\n" + MECHANISM_QUOTE)], question=QUESTION, as_of=AS_OF)
    payload = bound_mechanisms()
    change(payload)
    with pytest.raises(ValueError, match=match):
        tr.build_case({"forecastCase": case}, payload, case["sources"], question=QUESTION, as_of=AS_OF)


def test_library_context_is_pinned_filtered_and_never_current_evidence(tmp_path, bridge, monkeypatch):
    fetch = install_target_fixture(monkeypatch, gaps=0)
    context = {"schemaVersion": "target-library-context/v1", "authority": "prior_context_only", "entries": [
        {"entryId": "past", "availableAt": "2026-10-25", "asOf": "2026-10-24", "title": "PAST-LIBRARY-ONLY-999",
         "sources": [source(passage="Library-only imaginary capacity 999 GW.")], "gaps": ["Historical context only"]},
        {"entryId": "future", "availableAt": "2026-10-28", "asOf": "2026-10-24", "title": "FUTURE-LIBRARY-EXCLUDED"}]}
    args = v3.make_args(forecast_authority=tr.AUTHORITY)
    ids = []
    for name in ("initial", "repeated"):
        out = tmp_path / name
        out.mkdir()
        (out / "target_library.json").write_text(json.dumps(context))
        rc, meta, _, model, _ = v3.run_engine(tmp_path, bridge, TargetWorld(), args=args, fetch=fetch, out_dir=out)
        assert rc == 0, meta
        prompts = [c["messages"][-1][1] for c in model.calls if c["messages"][-1][1].startswith(
            ("TARGET CASE PLANNING TASK", "TARGET MECHANISM BINDING TASK"))]
        assert len(prompts) == 2 and all("PAST-LIBRARY-ONLY-999" in p and "FUTURE-LIBRARY-EXCLUDED" not in p for p in prompts)
        case = fc.read_case(out / "forecast_case.json")
        assert all("Library-only imaginary" not in s["passage"] for s in case["sources"])
        assert case["nodes"][0]["value"] == 176
        ids.append(case["caseId"])
    assert ids[0] != ids[1]
    before = (out / "forecast_case.json").read_bytes()
    (out / "target_library.json").write_text(json.dumps(context, indent=2))  # Same values, changed complete bytes.
    rc, meta, _, model, _ = v3.run_engine(tmp_path, bridge, TargetWorld(), args=args, fetch=fetch, out_dir=out)
    assert rc == 2 and "library context changed" in meta["error"] and model.calls == []
    assert (out / "forecast_case.json").read_bytes() == before


def test_mechanism_ratio_is_reproduced_and_unbounded_assumption_rejected():
    second_quote = "The comparison capacity is 352 GW as of 2026-10-26."
    case = tr.build_case({"forecastCase": planned_case()}, [finding(), finding(claimId="C2", passage=second_quote,
                     nodeId="target", value=352, status="reported")],
                     [source(passage=QUOTE + "\n\n" + second_quote)], question=QUESTION, as_of=AS_OF)
    payload = bound_mechanisms()
    payload["mechanismEvidence"][0].update(claimIds=["C2", "C1"], method="ratio",
         operands=[{"claimId": "C2", "value": 352}, {"claimId": "C1", "value": 176}])
    updated = tr.build_case({"forecastCase": case}, payload, case["sources"], question=QUESTION, as_of=AS_OF)
    assert updated["mechanisms"][0]["parameters"]["coefficients"] == [2.0]
    payload["mechanisms"][0]["parameters"]["coefficients"] = [3.0]
    with pytest.raises(ValueError, match="does not reproduce"):
        tr.build_case({"forecastCase": case}, payload, case["sources"], question=QUESTION, as_of=AS_OF)
    payload = {"mechanisms": copy.deepcopy(planned_case()["mechanisms"])}
    payload["mechanisms"][0]["parameters"]["coefficients"] = [1.5]
    with pytest.raises(ValueError, match="bounded assumptions"):
        tr.build_case({"forecastCase": case}, payload, case["sources"], question=QUESTION, as_of=AS_OF)


def test_case_identity_survives_failed_target_planning(tmp_path, bridge, monkeypatch):
    fetch = install_target_fixture(monkeypatch, gaps=0)
    args = v3.make_args(forecast_authority=tr.AUTHORITY)
    rc, _, _, _, out = v3.run_engine(tmp_path, bridge, TargetWorld(bad_plan=True), args=args, fetch=fetch)
    assert rc == 2
    initial_id = json.loads((out / "v3/state.json").read_text())["targetResearch"]["caseId"]
    rc, meta, _, _, _ = v3.run_engine(tmp_path, bridge, TargetWorld(), args=args, fetch=fetch, out_dir=out)
    assert rc == 0, meta
    assert fc.read_case(out / "forecast_case.json")["caseId"] == initial_id


def test_market_rejects_future_tool_row_then_can_publish_fresh_refresh(tmp_path, monkeypatch):
    _, collect = market_fixture(tmp_path, monkeypatch)
    monkeypatch.setattr(v3.dr, "_load_tool_market_candidates", lambda out: [{
        "market_id": "future", "question": QUESTION, "implied_yes_prob": 0.7, "volume": 20000,
        "captured_at": "2026-10-25T00:00:00+00:00", "captured_via": "prediction_market_search"}])
    result, _, _ = collect("future-then-fresh")
    assert [row["market_id"] for row in result["markets"]] == ["m1"]
    assert result["status"]["state"] == "fresh" and isinstance(result["as_of"], str)


def test_mechanism_evidence_sidecar_is_pinned_on_resume(tmp_path, bridge, monkeypatch):
    fetch = install_target_fixture(monkeypatch, gaps=0)
    args = v3.make_args(forecast_authority=tr.AUTHORITY)
    rc, meta, _, _, out = v3.run_engine(tmp_path, bridge, TargetWorld(), args=args, fetch=fetch)
    assert rc == 0, meta
    case_before = (out / "forecast_case.json").read_bytes()
    proof = out / "v3/target/mechanism-bindings.json"
    raw = json.loads(proof.read_text())
    raw["mechanisms"][0]["gap"] = "Modified proof after acceptance"
    proof.write_text(json.dumps(raw))
    rc, meta, _, model, _ = v3.run_engine(tmp_path, bridge, TargetWorld(), args=args, fetch=fetch, out_dir=out)
    assert rc == 2 and "mechanism evidence binding changed" in meta["error"]
    assert model.calls == [] and (out / "forecast_case.json").read_bytes() == case_before


def test_library_mutation_during_research_stops_before_next_model_phase(tmp_path, bridge, monkeypatch):
    fetch = install_target_fixture(monkeypatch, gaps=0)
    out = tmp_path / "out"
    out.mkdir()
    path = out / "target_library.json"
    path.write_text(json.dumps({"schemaVersion": "target-library-context/v1", "authority": "prior_context_only", "entries": []}))
    class MutatingWorld(TargetWorld):
        def __call__(self, call):
            if call["messages"][-1][1].startswith("TARGET FINDINGS TASK"):
                path.write_text(path.read_text() + "\n")
            return super().__call__(call)
    rc, meta, _, model, _ = v3.run_engine(tmp_path, bridge, MutatingWorld(),
        args=v3.make_args(forecast_authority=tr.AUTHORITY), fetch=fetch, out_dir=out)
    assert rc == 2 and "library context changed" in meta["error"]
    assert not (out / "forecast_case.json").exists()
    assert not any(c["messages"][-1][1].startswith("TARGET MECHANISM BINDING") for c in model.calls)


def test_assessment_cannot_replace_bound_mechanisms(tmp_path, bridge, monkeypatch):
    fetch = install_target_fixture(monkeypatch, gaps=0)
    class ReplacingAssessmentWorld(TargetWorld):
        def __call__(self, call):
            if call["messages"][-1][1].startswith("TARGET ASSESSMENT TASK"):
                mechanisms = copy.deepcopy(planned_case()["mechanisms"])
                mechanisms[0]["parameters"]["coefficients"] = [{"low": 999, "high": 999,
                    "basis": "assumed", "gap": "Attempted post-binding overwrite"}]
                return v3.ai(json.dumps({"assessment": assessment(), "mechanisms": mechanisms}))
            return super().__call__(call)
    rc, meta, _, _, out = v3.run_engine(tmp_path, bridge, ReplacingAssessmentWorld(),
        args=v3.make_args(forecast_authority=tr.AUTHORITY), fetch=fetch)
    assert rc == 2 and "assessment response fields" in meta["error"]
    assert not (out / "forecast_case.json").exists()
    proof = json.loads((out / "v3/target/mechanism-bindings.json").read_text())
    assert proof["mechanisms"] == planned_case()["mechanisms"]


def test_bound_mechanism_partial_resume_does_not_reopen_gaps(tmp_path, bridge, monkeypatch):
    fetch = install_target_fixture(monkeypatch, gaps=0)
    args = v3.make_args(forecast_authority=tr.AUTHORITY)
    rc, meta, _, _, out = v3.run_engine(tmp_path, bridge, BrokenAssessmentWorld(), args=args, fetch=fetch)
    assert rc == 2 and "posterior" in meta["error"]
    snapshot = (out / "v3/target/mechanisms.json").read_bytes()
    monkeypatch.setenv("RESEARCH_LINEAR_GAP_ROUNDS", "3")
    class BoundResumeWorld(TargetWorld):
        def __call__(self, call):
            if call["messages"][-1][1].startswith(("TARGET FINDINGS", "TARGET MECHANISM", "KIQ INVESTIGATION")):
                pytest.fail("A bound generation must not gather new conflicting evidence on assessment retry")
            return super().__call__(call)
    rc, meta, _, model, _ = v3.run_engine(tmp_path, bridge, BoundResumeWorld(), args=args, fetch=fetch, out_dir=out)
    assert rc == 0, meta
    assert len(model.calls) == 1 and model.calls[0]["messages"][-1][1].startswith("TARGET ASSESSMENT")
    assert (out / "v3/target/mechanisms.json").read_bytes() == snapshot
