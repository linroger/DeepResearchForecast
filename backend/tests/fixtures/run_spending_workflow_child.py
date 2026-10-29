"""Registered SB-02/SB-08 fixture; no work occurs merely by importing this file.

Production gateway/store/tool code and staged LangChain/SDK dependencies are
real. Only HTTP responses are synthetic. Bootstrap/path acceptance is separate.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sqlite3
import sys
import threading
import time

_AUDIT_LOCK = threading.RLock()


def read_rows(binding):
    with sqlite3.connect(Path(binding["db_path"]).as_uri() + "?mode=ro", uri=True) as db:
        db.row_factory = sqlite3.Row
        return [dict(row) for row in db.execute("SELECT * FROM attempts ORDER BY rowid")]


def read_events(path):
    return [json.loads(line) for line in Path(path).read_text().splitlines()] if Path(path).exists() else []


def write_json(path, value):
    path = Path(path)
    temporary = path.with_suffix(".writing")
    temporary.write_text(json.dumps(value, sort_keys=True))
    temporary.replace(path)


def audit_send(sp, binding, path, kind, body, *, request):
    """Count entry first; record assertion failures outside SDK normalization."""
    path = Path(path)
    with _AUDIT_LOCK:
        prior = read_events(path)
        sequence = sum(row["event"] == "entry" for row in prior)

        def append(value):
            with path.open("a") as output:
                output.write(json.dumps({"pid": os.getpid(), "sequence": sequence, **value}) + "\n")
                output.flush()
                os.fsync(output.fileno())

        append({"event": "entry", "kind": kind})
        try:
            body = body() if callable(body) else body
            rows = read_rows(binding)
            row = rows[-1]
            envelope = json.loads(row["envelope"])
            route = json.loads(Path(binding["manifest_path"]).read_text())["routes"][row["route_id"]]
            expected_url = route["endpoint"].rstrip("/")
            if route["kind"] == "openai_chat":
                expected_url += "/chat/completions"
            assert request.method == "POST" and str(request.url) == expected_url
            assert envelope["endpoint"].rstrip("/") == route["endpoint"].rstrip("/")
            assert row["state"] == "unknown"
            assert row["participant_id"] == binding["participant_id"]
            assert row["generation"] == binding["generation"]
            stage = sp.current_operation()["stage"]
            assert row["stage_hash"] == sp.hash_payload(stage)
            assert row["request_sha256"] == sp.hash_payload(body)
            assert row["attempt_id"] not in {item.get("attempt_id") for item in prior}
            assert row["reserved"] > 0
            with sqlite3.connect(Path(binding["db_path"]).as_uri() + "?mode=ro", uri=True) as db:
                cap, pipeline = db.execute("SELECT cap,pipeline_id FROM run_authorization").fetchone()
                participant_pid = db.execute("SELECT pid FROM participants WHERE generation=? AND participant_id=?",
                                             (binding["generation"], binding["participant_id"])).fetchone()[0]
            assert participant_pid == os.getpid() and pipeline == binding["pipeline_id"]
            assert sum(item["reserved"] for item in rows) <= cap
            if kind.endswith("model") or kind in {"estimator", "actor", "resume-parent"}:
                assert envelope["max_output_tokens"] == body.get("max_completion_tokens", body.get("max_tokens"))
            append({"event": "verified", "kind": kind, "attempt_id": row["attempt_id"],
                    "reserved": row["reserved"], "row_count": len(rows),
                    "retained": sum(item["reserved"] for item in rows),
                    "payload_sha256": row["request_sha256"], "generation": row["generation"],
                    "participant_id": row["participant_id"], "pipeline_id": pipeline, "stage": stage,
                    "destination_sha256": sp.hash_payload(str(request.url)), "method": request.method})
        except BaseException as exc:
            append({"event": "violation", "error_type": type(exc).__name__})
            raise


def _research(control):
    import types

    # Reuse Poincare's staged, individually hashed dependency package. The
    # existing registered-child Guard is already installed; add no permission.
    bundle = Path(control["dependency_bundle"])
    site = bundle / "site-packages"
    guard = sys.modules["main_offline_guard"]
    assert guard.configured and sys.flags.isolated and sys.flags.no_site
    repo = Path(__file__).resolve().parents[3]
    sys.path[:] = [str(site), str(repo / "deerflow_bridge")] + [p for p in sys.path if p not in guard.site_paths]
    spec = importlib.util.spec_from_file_location("composed_dependency_proof", bundle / "proof.py")
    proof = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(proof)
    import httpx
    from langchain_openai import ChatOpenAI

    sp, rg, lr = proof.sp, proof.rg, proof.lr
    binding = sp.binding_from_environment()
    sp.activate_binding(binding)
    event_path = control["events"]
    manifest = json.loads(Path(binding["manifest_path"]).read_text())
    route = next(value for value in manifest["routes"].values() if value["kind"] == "openai_chat")

    def response(request):
        path = request.url.path
        kind = "child-model" if path.endswith("/chat/completions") else "child-" + path.rsplit("/", 1)[-1]
        audit_send(sp, binding, event_path, kind, lambda: json.loads(request.content), request=request)
        if kind == "child-model":
            return httpx.Response(200, json={"id": "synthetic-child", "object": "chat.completion", "created": 0,
                "model": route["model"], "choices": [{"index": 0, "finish_reason": "stop",
                "message": {"role": "assistant", "content": "fixture child result"}}],
                "usage": {"prompt_tokens": 12, "completion_tokens": 2, "total_tokens": 14}})
        if control["mode"] == "child_unknown":
            raise httpx.ReadTimeout("synthetic ambiguous tool outcome")
        if kind == "child-search":
            return httpx.Response(200, json={"creditsUsed": 1, "data": {"web": [{"title": "Synthetic official evidence",
                "url": "https://agency.example/composed", "description": "Audited capacity reached 176 GW."}]}})
        assert kind == "child-scrape"
        return httpx.Response(200, json={"creditsUsed": 1, "data": {"markdown": "# Synthetic official evidence\n\n" +
            "Audited capacity reached 176 GW. Official source reporting is available. " * 15}})

    def transport(**kwargs):
        assert kwargs == {"retries": 0}
        mock = httpx.MockTransport(response)
        # Same explicit MockTransport inspection shape used by Poincare's proof;
        # MockTransport has no retry loop and no production check is bypassed.
        mock._pool = types.SimpleNamespace(_retries=0)
        return mock

    original_sync, original_async = httpx.HTTPTransport, httpx.AsyncHTTPTransport
    model = None
    httpx.HTTPTransport = httpx.AsyncHTTPTransport = transport
    try:
        config = types.SimpleNamespace(use="langchain_openai:ChatOpenAI", model=route["model"],
                                        base_url=route["endpoint"], api_key="$LLM_API_KEY")
        app_config = types.SimpleNamespace(get_model_config=lambda alias: config if alias == "glm" else None)
        model = lr._bound_chat_model(types.SimpleNamespace(model="glm"), app_config)
        assert type(model) is ChatOpenAI
        gateway = rg.ModelGateway(model, None, sleep=lambda _: None)
        work = Path(control["work"])
        tools = rg.ResearchTools(rg.SourceLedger(work / "sources.json"), work / "pages")
        calls = [
            ("model", lambda: gateway.invoke(rg.build_messages("synthetic core", ["synthetic brief"], "composed child"),
                kind="agent", label="composed-child", max_tokens=8, tools=rg.AGENT_TOOLS_SCHEMA)),
            ("search", lambda: tools.search("composed synthetic capacity", agent_id="KIQ1")),
            ("scrape", lambda: tools.fetch("https://agency.example/composed", agent_id="KIQ1")),
        ]
        outcome = "completed"
        for _, call in calls:
            try:
                call()
            except sp.SpendingStop as exc:
                outcome = exc.code
                break
        report = {"pid": os.getpid(), "participant_id": binding["participant_id"], "outcome": outcome,
                  "generation": binding["generation"], "pipeline_id": binding["pipeline_id"],
                  "db_path": binding["db_path"], "isolated": sys.flags.isolated, "no_site": sys.flags.no_site,
                  "actual_chatopenai": True, "fake_layers": ["HTTP MockTransport only"],
                  "fidelity": "actual staged ChatOpenAI/SDK/gateway/Firecrawl/store",
                  "archive_sha256": control["archive_sha256"],
                  "module_sha256": hashlib.sha256(Path(sp.__file__).read_bytes()).hexdigest()}
        from deerflow_bridge import cached_fetch, search_tools
        report["production_sources"] = {
            str(Path(module.__file__).resolve().relative_to(repo)): hashlib.sha256(Path(module.__file__).read_bytes()).hexdigest()
            for module in (sp, rg, lr, cached_fetch, search_tools)}
        write_json(control["ready"], report)
        deadline = time.monotonic() + 30
        while not Path(control["probe"]).exists():
            if time.monotonic() >= deadline:
                raise RuntimeError("workflow parent did not release probe")
            time.sleep(0.01)
        probes = {}
        for name, call in calls:
            try:
                call()
                probes[name] = "unexpected_success"
            except sp.SpendingStop as exc:
                probes[name] = exc.code
        report.update(probes=probes, summary=sp.summary(binding),
                      dependency_imports=proof.pin_loaded_dependencies(site),
                      dependency_manifest_sha256=hashlib.sha256((bundle / "dependencies.json").read_bytes()).hexdigest())
        write_json(control["result"], report)
    finally:
        httpx.HTTPTransport, httpx.AsyncHTTPTransport = original_sync, original_async
        if model is not None:
            model.root_client.close()
            import asyncio
            asyncio.run(model.root_async_client.close())


def _resume(control):
    """Store-level takeover and real parent raw adapter, not backend resume eligibility."""
    import httpx
    import pytest
    import openai

    root = Path(__file__).resolve().parents[3]
    sys.path.insert(0, str(root / "backend"))
    from app.config import Config
    from app.services.official_data import bridge_module
    from app.utils.llm_client import LLMClient

    sp = bridge_module("run_spending")
    binding = sp.binding_from_environment()
    sp.activate_binding(binding)
    with pytest.MonkeyPatch.context() as patch, sp.run_lock(binding):
        binding = sp.resume_existing(binding, control["proof"])
        sp.activate_binding(binding)
        for key, value in control["config"].items():
            patch.setattr(Config, key, value)
        patch.setattr(openai._base_client, "platform_headers", lambda *a, **k: {})

        def send(request):
            audit_send(sp, binding, control["events"], "resume-parent", lambda: json.loads(request.content), request=request)
            return httpx.Response(200, json={"id": "fixture", "object": "chat.completion", "created": 0,
                "model": Config.LLM_MODEL_NAME, "choices": [{"index": 0, "finish_reason": "stop",
                "message": {"role": "assistant", "content": "unexpected"}}]})

        with httpx.Client(transport=httpx.MockTransport(send), follow_redirects=False, trust_env=False) as http:
            patch.setattr(LLMClient, "_build_http_client", staticmethod(lambda: http))
            with sp.operation("resume-parent", "same-allowance-second-attempt"):
                client = LLMClient()
                try:
                    client.chat([{"role": "user", "content": "synthetic resumed attempt"}], max_tokens=500)
                    outcome = "unexpected_success"
                except sp.SpendingStop as exc:
                    outcome = exc.code
        write_json(control["result"], {"pid": os.getpid(), "outcome": outcome, "binding": binding,
            "proof_scope": "core_resume_with_real_parent_transport",
            "summary": sp.summary(binding), "isolated": sys.flags.isolated, "no_site": sys.flags.no_site,
            "module_sha256": hashlib.sha256(Path(sp.__file__).read_bytes()).hexdigest()})


def _backend_resume(control):
    """Actual backend resume/_run after real, validated research sealing."""
    import httpx
    import openai
    import pytest
    import types

    repo = Path(__file__).resolve().parents[3]
    sys.path.insert(0, str(repo / "backend"))
    from app.config import Config
    from app.models.project import ProjectManager
    from app.services import pipeline_orchestrator as po, run_spending as lifecycle, target_pipeline as tp
    from app.services.report_agent import ReportManager
    from app.utils.llm_client import LLMClient

    sp = lifecycle.api()
    binding = sp.binding_from_environment()
    sp.activate_binding(binding)
    root = Path(binding["root"])
    launches, unexpected = [], []

    class ParkedThread:
        def __init__(self, **kwargs):
            self.kwargs = kwargs
        def start(self):
            launches.append(self.kwargs["name"])
        def is_alive(self):
            return False

    def forbidden_research(*args, **kwargs):
        unexpected.append("research")
        raise AssertionError("sealed research must be reused")

    def forbidden_method():
        unexpected.append("method")
        raise AssertionError("sealed estimators must be reused")

    with pytest.MonkeyPatch.context() as patch, sp.run_lock(binding):
        for key, value in {**control["config"], "UPLOAD_FOLDER": str(root / "uploads"),
                "PIPELINE_DATA_DIR": str(root / "uploads/pipelines"),
                "OASIS_SIMULATION_DATA_DIR": str(root / "uploads/simulations"),
                "DEERFLOW_DIR": str(root / "deer-flow")}.items():
            patch.setattr(Config, key, value)
        patch.setattr(ProjectManager, "PROJECTS_DIR", str(root / "uploads/projects"))
        patch.setattr(ReportManager, "REPORTS_DIR", str(root / "uploads/reports"))
        patch.setattr(po.PipelineOrchestrator, "_threads", {})
        patch.setattr(po.PipelineOrchestrator, "_cancel_events", {})
        patch.setattr(po, "threading", types.SimpleNamespace(Thread=ParkedThread, Event=threading.Event, Lock=threading.Lock))
        # Same observation-only harness controls as target_pipeline.execution.
        for name in ("_write_run_manifest", "_init_telemetry_flush", "_flush_run_telemetry"):
            patch.setattr(po.PipelineOrchestrator, name, lambda *a, **k: None)
        patch.setattr(po.PipelineOrchestrator, "_start_heartbeat", lambda *a, **k: threading.Event())
        patch.setattr(po, "_register_outage_breaker", lambda *a: None)
        patch.setattr(po.DeerFlowResearchRunner, "run", forbidden_research)
        patch.setattr(tp, "_method_gateway", forbidden_method)
        patch.setattr(openai._base_client, "platform_headers", lambda *a, **k: {})
        patch.setenv("DRF_RUN_SPENDING_RESUME_PROOF", json.dumps(control["proof"]))
        original = po.PipelineState.from_dict(po.PipelineManager.load(binding["pipeline_id"]))
        assert original.status == "failed"
        assert tp.validate_stage(original, "research") and tp.validate_stage(original, "prepare")

        def artifacts(state):
            return {name: hashlib.sha256(Path(filename).read_bytes()).hexdigest()
                    for stage in ("research", "prepare") for name, filename in tp.stage_specs(state, stage)}

        before_artifacts = artifacts(original)
        state = original

        def send(request):
            audit_send(sp, sp.current_binding(), control["events"], "resume-parent",
                       lambda: json.loads(request.content), request=request)
            return httpx.Response(200, json={"id": "synthetic-resumed-actor", "object": "chat.completion", "created": 0,
                "model": Config.LLM_MODEL_NAME, "choices": [{"index": 0, "finish_reason": "stop",
                "message": {"role": "assistant", "content": '{"actions":[]}'}}],
                "usage": {"prompt_tokens": 12, "completion_tokens": 2, "total_tokens": 14}})

        with httpx.Client(transport=httpx.MockTransport(send), follow_redirects=False, trust_env=False) as http:
            patch.setattr(LLMClient, "_build_http_client", staticmethod(lambda: http))
            try:
                state = po.PipelineOrchestrator.resume(binding["pipeline_id"])
                binding = state.options[lifecycle.BINDING_KEY]
                po.PipelineOrchestrator._run(state)
                outcome = ("completed" if state.status == "completed" else
                           (state.options.get("spending_stop_v1") or {}).get("code", "missing_spending_stop"))
            except sp.SpendingStop as exc:
                outcome = exc.code
        assert unexpected == [], "a sealed producer was called during resume"
        assert artifacts(state) == before_artifacts
        write_json(control["result"], {"proof_scope": "backend_resume_after_sealed_research",
            "pid": os.getpid(), "binding": binding, "outcome": outcome, "status": state.status,
            "summary": sp.summary(binding), "research_valid": tp.validate_stage(state, "research"),
            "prepare_valid": tp.validate_stage(state, "prepare"), "artifact_sha256": before_artifacts,
            "unexpected_producers": unexpected, "scheduled_workers": len(launches),
            "decision_usage": state.options.get("target_decision_usage"), "report_id": state.report_id,
            "publication": ReportManager.publication_status(state.report_id) if state.report_id else None,
            "report_stage_valid": tp.validate_stage(state, "report") if state.report_id else False,
            "stage_statuses": {name: stage.status for name, stage in state.stages.items()},
            "isolated": sys.flags.isolated, "no_site": sys.flags.no_site,
            "module_sha256": hashlib.sha256(Path(sp.__file__).read_bytes()).hexdigest()})


def main():
    control = json.loads(Path(sys.argv[1]).read_text())
    if control["mode"] == "resume":
        _resume(control)
    elif control["mode"] == "backend_resume":
        _backend_resume(control)
    else:
        _research(control)


if __name__ == "__main__":
    main()
