"""Cancelled partial context reaches the native producer, never a sealed reader.

Exercise the real parent _run and the existing bridge validator. External
research dispatch stops at an explicit sentinel: no model, service or forecast
is run. Final evidence keeps the strict sealed path, including short/broken
report markers. All artifacts are synthetic and confined by the offline guard.
"""

import hashlib
import json
from pathlib import Path

import pytest

from app.services import news_market_context, pipeline_orchestrator as po
from tests.test_news_context_pipeline import actual_parent_case


def _capture(case, monkeypatch, *, sealed=False):
    monkeypatch.setenv("NEWS_CONTEXT_ENABLED", "true")
    news = news_market_context._bridge_api()
    client = news.ContextClient(case.hd, question=case.state.prompt, language="en",
                                as_of="2026-10-18", news_enabled=False, social_enabled=False,
                                max_news_requests=0,
                                transport=lambda *a, **kw: pytest.fail("unexpected provider transport"))
    client.record_result("newsapi", "retained query", {
        "provider": "newsapi", "query": "retained query",
        "status": {"state": "verified_empty", "attempted": False}, "items": [],
    })
    if sealed:
        client.seal()
    path = case.hd / "news_market_context.json"
    return news, path, client.snapshot()


@pytest.fixture
def partial_case(actual_parent_case, monkeypatch):
    case = actual_parent_case
    # The shared fixture's final handoff is unrelated. Use a fresh partial root;
    # do not erase a report or alter any completed capture to manufacture reuse.
    case.hd = case.tmp_path / "partial-handoff"
    case.hd.mkdir()
    case.state.handoff_dir = str(case.hd)
    for stage in case.state.stages.values():
        stage.status = "pending"
        stage.progress = 0
        stage.started_at = stage.finished_at = None
    case.state.status = "running"
    case.state.current_stage = po.STAGE_RESEARCH
    case.state.options["resume_count"] = 1
    news, path, capture = _capture(case, monkeypatch)
    case.news, case.context_path, case.capture = news, path, capture
    return case


@pytest.mark.parametrize("stage_status,default_path_alias", [
    ("pending", False), ("running", False), ("failed", False), ("cancelled", False), ("pending", True),
], ids=["pending", "running", "failed", "cancelled", "default-config-dotdot-path"])
def test_real_run_valid_partial_reaches_native_producer_probe(partial_case, monkeypatch, stage_status, default_path_alias):
    case = partial_case
    case.state.stages[po.STAGE_RESEARCH].status = stage_status
    if default_path_alias:
        app = case.hd.parent / "app"
        app.mkdir()
        case.state.handoff_dir = str(app / ".." / case.hd.name)
        assert "/app/../" in case.state.handoff_dir
    before = case.context_path.read_bytes()
    assert case.news.load_context(case.hd, require_sealed=False) == case.capture
    with pytest.raises(case.news.ContextIntegrityError, match="^unsealed_context$"):
        case.news.load_context(case.hd, require_sealed=True)
    observed = []

    def producer(prompt, handoff_dir, **kwargs):
        observed.append(kwargs["research_engine"])
        assert prompt == case.state.prompt and Path(handoff_dir).resolve() == case.hd
        if default_path_alias:
            assert handoff_dir == case.state.handoff_dir  # exercise the real alias at _run admission
        assert case.context_path.read_bytes() == before
        # This is the actual acquisition owner's reopen/identity validation,
        # not a mocked unsealed exception or a newly resealed empty capture.
        reopened = case.news.ContextClient(case.hd, question=prompt, language="en", as_of="2026-10-18",
                                            news_enabled=False, social_enabled=False, max_news_requests=0)
        assert reopened.snapshot() == case.capture
        assert reopened.snapshot()["sealed"] is False
        raise RuntimeError("offline native producer boundary reached")

    monkeypatch.setattr(po.DeerFlowResearchRunner, "run", producer)
    po.PipelineOrchestrator._run(case.state)
    assert observed == ["v3"]
    assert case.state.status == "failed" and case.state.error == "offline native producer boundary reached"
    assert case.state.stages[po.STAGE_RESEARCH].started_at is not None
    assert case.context_path.read_bytes() == before
    assert case.news.load_context(case.hd, require_sealed=False) == case.capture
    assert not (case.hd / "research_report.md").exists()
    assert not (case.hd / "research_contract_manifest.json").exists()


@pytest.mark.parametrize("marker", ["completed", "short_report", "malformed_report", "broken_report_link",
                                    "contract", "evidence_manifest"])
def test_real_run_final_evidence_still_requires_sealed_context(partial_case, marker):
    case = partial_case
    if marker == "completed":
        case.state.stages[po.STAGE_RESEARCH].status = "completed"
    elif marker == "short_report":
        (case.hd / "research_report.md").write_text("Unfinished report")
    elif marker == "malformed_report":
        (case.hd / "research_report.md").write_bytes(b"\xff")
    elif marker == "broken_report_link":
        (case.hd / "research_report.md").symlink_to(case.hd / "absent-report")
    else:
        name = "research_contract_manifest.json" if marker == "contract" else "evidence_synthesis_manifest.json"
        (case.hd / name).write_text("{}")
    before = case.context_path.read_bytes()
    po.PipelineOrchestrator._run(case.state)
    assert case.calls == []
    assert case.state.status == "failed" and case.state.error == "unsealed_context"
    assert case.context_path.read_bytes() == before


@pytest.mark.parametrize("damage", ["digest", "schema", "symlink"])
def test_real_run_partial_capture_integrity_is_not_bypassed(partial_case, damage):
    case = partial_case
    if damage == "symlink":
        original = case.hd / "retained-original.json"
        case.context_path.rename(original)
        case.context_path.symlink_to(original)
    else:
        value = json.loads(case.context_path.read_bytes())
        if damage == "digest":
            value["generation_id"] = "different-generation"
        else:
            value["queries"] = {}
        case.context_path.write_text(json.dumps(value))
    before = case.context_path.read_bytes()
    # require_sealed=False must still validate the entire envelope, digest and
    # no-follow path. Catching only unsealed_context would miss these failures.
    with pytest.raises(case.news.ContextIntegrityError) as invalid:
        case.news.load_context(case.hd, require_sealed=False)
    po.PipelineOrchestrator._run(case.state)
    assert case.calls == []
    assert case.state.status == "failed" and case.state.error == str(invalid.value)
    assert case.context_path.read_bytes() == before


def test_real_run_missing_declared_context_remains_fail_closed(partial_case):
    case = partial_case
    case.state.artifacts["news_market_context"] = str(case.context_path)
    case.context_path.unlink()  # synthetic missing-proof negative control only
    po.PipelineOrchestrator._run(case.state)
    assert case.calls == []
    assert case.state.status == "failed"
    assert case.state.error == "Declared news context capture is missing before research reuse"
    assert not case.context_path.exists()


def test_real_run_valid_sealed_research_is_reused_without_dispatch(actual_parent_case, monkeypatch):
    case = actual_parent_case
    news, path, capture = _capture(case, monkeypatch, sealed=True)
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    stage = case.state.stages[po.STAGE_RESEARCH]
    stage.started_at, stage.finished_at = "2026-10-18T00:00:00Z", "2026-10-18T00:05:00Z"
    po.PipelineOrchestrator._run(case.state)
    assert case.state.status == "completed", case.state.error
    assert case.calls == []
    assert (stage.started_at, stage.finished_at) == ("2026-10-18T00:00:00Z", "2026-10-18T00:05:00Z")
    assert news.load_context(case.hd, require_sealed=True) == capture
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before
