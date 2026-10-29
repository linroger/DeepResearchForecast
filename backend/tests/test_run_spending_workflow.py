"""SB-02/SB-08: actual parent producers and independently guarded processes.

Only external HTTP responses are synthetic in the parent. Child dependency
fidelity is explicit in its receipt. No full pipeline producer is replaced.
"""
from contextlib import contextmanager
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import subprocess
import sys
import tarfile
import time

import httpx
import openai
import pytest

from app.services import run_spending as lifecycle, target_pipeline as tp
from app.services.forecast_tournament import freeze_target_estimators
from app.services.target_report import build_target_report
from app.services.target_simulation import run_paths
from app.utils.llm_client import LLMClient
from tests import test_run_spending_store as store_cases, test_target_pipeline as target_cases
from tests.fixtures import run_spending_workflow_child as audit

pytestmark = pytest.mark.guarded_runner
isolated_latch = store_cases.isolated_latch
runtime = target_cases.runtime
case = target_cases.case
execution = target_cases.execution
sp = lifecycle.api()
REPO = Path(__file__).resolve().parents[2]
CHILD = Path(audit.__file__).resolve()
KEY = "offline-synthetic-credential"
ENDPOINT = "https://model.invalid/v1"
MODEL = "synthetic-model"
BUNDLE = REPO / ".pytest_cache/private-artifacts/run-spending-langchain-proof-20261029-01.tar.gz"
BUNDLE_SHA256 = "7ceb09fc03243140d3745c7008dab4aa04abd7dc22ce1b3707bd746f08b8e6cf"
SOURCES = ("deerflow_bridge/run_spending.py", "deerflow_bridge/research_gateway.py",
    "deerflow_bridge/search_tools.py", "deerflow_bridge/cached_fetch.py", "deerflow_bridge/linear_research.py",
    "backend/app/utils/llm_client.py", "backend/app/services/run_spending.py",
    "backend/app/services/target_pipeline.py", "backend/app/services/target_simulation.py",
    "backend/app/services/forecast_tournament.py", "backend/app/services/pipeline_orchestrator.py",
    "backend/tests/fixtures/target_case.json",
    "backend/tests/test_run_spending_child_transports.py", "backend/tests/test_run_spending_workflow.py",
    "backend/tests/fixtures/run_spending_workflow_child.py")


def _hashes():
    return {name: hashlib.sha256((REPO / name).read_bytes()).hexdigest() for name in SOURCES}


LOADED_SOURCE_HASHES = _hashes()


@pytest.fixture(scope="session")
def dependency_bundle(tmp_path_factory):
    """Read the approved ignored archive; extract verified regular files only."""
    assert hashlib.sha256(BUNDLE.read_bytes()).hexdigest() == BUNDLE_SHA256
    target = tmp_path_factory.mktemp("workflow-dependencies")
    seen, total = set(), 0
    with tarfile.open(BUNDLE, "r:gz") as archive:
        for member in archive:
            path = PurePosixPath(member.name)
            assert not path.is_absolute() and ".." not in path.parts
            assert path.parts and path.parts[0] == "run-spending-langchain-proof-20261029-01"
            assert str(path) not in seen and len(seen) < 5000
            seen.add(str(path))
            assert member.isdir() or member.isreg(), "links and special archive entries are forbidden"
            assert path.suffix not in {".pth", ".pyc"}
            destination = target.joinpath(*path.parts)
            assert destination.resolve().is_relative_to(target)
            if member.isdir():
                destination.mkdir(parents=True, exist_ok=True)
                continue
            total += member.size
            assert 0 <= member.size <= 20_000_000 and total <= 40_000_000
            data = archive.extractfile(member).read()
            assert len(data) == member.size
            destination.parent.mkdir(parents=True, exist_ok=True)
            with destination.open("xb") as output:
                output.write(data)
    root = target / "run-spending-langchain-proof-20261029-01"
    pins = json.loads((root / "package-pins.json").read_text())["files"]
    for name, digest in pins.items():
        assert hashlib.sha256((root / name).read_bytes()).hexdigest() == digest
    manifest = json.loads((root / "dependencies.json").read_text())
    files = {str(path.relative_to(root / "site-packages")) for path in (root / "site-packages").rglob("*") if path.is_file()}
    assert files == set(manifest["files"])
    for name, metadata in manifest["files"].items():
        data = (root / "site-packages" / name).read_bytes()
        assert hashlib.sha256(data).hexdigest() == metadata["sha256"]
    return root


def _config():
    return {"LLM_PROVIDER": "openai", "LLM_API_KEY": KEY, "LLM_BASE_URL": ENDPOINT,
            "LLM_MODEL_NAME": MODEL, "LLM_HTTP2": False, "LLM_TIERED_ROUTING": False,
            "LLM_CACHE_ENABLED": False, "LLM_TELEMETRY_ENABLED": False,
            "LLM_RUN_BUDGET_TOKENS": 0, "LLM_RUN_BUDGET_USD": 0}


def _prepare(runtime, case, tmp_path, monkeypatch, *, cap, resume=False):
    root = tmp_path / "runtime"
    (root / "spend").mkdir(parents=True)
    registry = tmp_path / "registry"
    registry.mkdir()
    hashes = _hashes()
    assert hashes == LOADED_SOURCE_HASHES, "source changed after collection; obtain a frozen fresh run"
    for relative in hashes:
        destination = root / "source" / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes((REPO / relative).read_bytes())
    source_files = {"source/" + name: digest for name, digest in hashes.items()}
    common = {"account_sha256": hashlib.sha256(KEY.encode()).hexdigest(),
              "basis_sha256": sp.hash_payload("synthetic composed tariff, not provider evidence"),
              "coverage": "all_billable_dimensions"}
    routes = {"model": dict(common, kind="openai_chat", endpoint=ENDPOINT, model=MODEL,
        billing_class="external_model", input_bound="enforced_context_ceiling",
        input_ceiling=100 if resume else 1000, max_output_tokens=8192, max_tool_units=0,
        pricing={"input_usd_per_million": "1000" if resume else "1",
                 "output_usd_per_million": "1000" if resume else "2",
                 "tool_usd_per_unit": "0", "fixed_usd": "0", "surcharge_usd": "0"})}
    if not resume:
        for name, units in (("search", 5), ("scrape", 1)):
            routes[name] = dict(common, kind="firecrawl_" + name,
                endpoint="https://firecrawl.invalid/v2/" + name, model="", billing_class="external_tool",
                input_bound="not_applicable", input_ceiling=0, max_output_tokens=0, max_tool_units=units,
                pricing={"input_usd_per_million": "0", "output_usd_per_million": "0",
                         "tool_usd_per_unit": "0.01", "fixed_usd": "0", "surcharge_usd": "0"})
    request = {"prompt": case["question"], "mode": "full", "depth": "quick", "language": "English",
               "model": "openai", "forecast_authority": "target-first-v1",
               "target_simulation": {"paths": 1, "periods": 1, "seed": 7}}
    manifest = {"schema": "target-run-spending/v1", "authorization_id": "composed-workflow",
                "root": str(root), "currency": "USD", "cap_usd": cap,
                "request_sha256": sp.hash_payload(request), "source_files": source_files,
                "source_sha256": sp.hash_payload(source_files), "routes_sha256": sp.hash_payload(routes),
                "resume_policy": "explicit_clean_only", "routes": routes}
    manifest_path = root / "spend/authorization.json"
    manifest_path.write_text(json.dumps(manifest))
    binding = sp.create_authorization(manifest_path, registry_dir=registry)
    from app.models.project import ProjectManager
    from app.services.report_agent import ReportManager
    for key, value in {**_config(), "UPLOAD_FOLDER": str(root / "uploads"),
            "PIPELINE_DATA_DIR": str(root / "uploads/pipelines"),
            "OASIS_SIMULATION_DATA_DIR": str(root / "uploads/simulations"),
            "DEERFLOW_DIR": str(root / "deer-flow")}.items():
        monkeypatch.setattr(runtime.config, key, value)
    monkeypatch.setattr(ProjectManager, "PROJECTS_DIR", str(root / "uploads/projects"))
    monkeypatch.setattr(ReportManager, "REPORTS_DIR", str(root / "uploads/reports"))
    monkeypatch.setattr(openai._base_client, "platform_headers", lambda *a, **k: {})
    for key, value in sp.export_environment(binding).items():
        monkeypatch.setenv(key, value)
    return binding, request, manifest, hashes


@contextmanager
def _parent_http(binding, path, monkeypatch):
    def send(request):
        audit.audit_send(sp, binding, path, "parent-model", lambda: json.loads(request.content), request=request)
        stage = sp.current_operation()["stage"]
        content = ({"scenario_distribution": {"below": 0.45, "above": 0.55}, "binaries": [],
                    "rationale": "Synthetic independent method response", "cruxes": ["Synthetic next release"]}
                   if stage == "estimator" else {"actions": []})
        return httpx.Response(200, json={"id": "synthetic-completion", "object": "chat.completion",
            "created": 0, "model": MODEL, "choices": [{"index": 0, "finish_reason": "stop",
            "message": {"role": "assistant", "content": json.dumps(content)}}],
            "usage": {"prompt_tokens": 12, "completion_tokens": 2, "total_tokens": 14}})

    with httpx.Client(transport=httpx.MockTransport(send), follow_redirects=False, trust_env=False) as http:
        monkeypatch.setattr(LLMClient, "_build_http_client", staticmethod(lambda: http))
        yield


def _wait_file(path, process):
    deadline = time.monotonic() + 25
    while not path.exists():
        if process.poll() is not None:
            stdout, stderr = process.communicate(timeout=1)
            pytest.fail(f"workflow child exited {process.returncode}: {stdout[-1000:]} {stderr[-3000:]}")
        assert time.monotonic() < deadline, "workflow child readiness timed out"
        time.sleep(0.02)
    return json.loads(path.read_text())


def _assert_events(paths, rows):
    events = [event for path in paths for event in audit.read_events(path)]
    assert not [event for event in events if event["event"] == "violation"]
    entries = [event for event in events if event["event"] == "entry"]
    verified = [event for event in events if event["event"] == "verified"]
    assert len(entries) == len(verified) == len(rows)
    assert {event["attempt_id"] for event in verified} == {row["attempt_id"] for row in rows}
    assert len({event["attempt_id"] for event in verified}) == len(rows)
    return verified


def _spawn(control, env, tmp_path):
    path = tmp_path / (control["mode"] + "-control.json")
    audit.write_json(path, control)
    return subprocess.Popen([sys.executable, "-B", str(CHILD), str(path)],
                            cwd=tmp_path, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)


def _reap(process):
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.communicate(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.communicate(timeout=5)


@pytest.mark.parametrize("mode,cap,expected", [
    ("budget", "0.090000", "budget_exhausted"),
    ("context", "1.000000", "missing_context"),
    ("actor_budget", "0.080000", "budget_exhausted"),
    ("child_unknown", "1.000000", "unknown_outcome"),
])
def test_parent_methods_actors_and_registered_child_share_one_authority(runtime, case, tmp_path, monkeypatch, dependency_bundle,
                                                                        mode, cap, expected):
    case = deepcopy(case)
    for actor in case["actors"]:
        actor["decisionRule"].update(kind="llm", cadencePeriods=1)
        actor["plans"] = []
    original, request, manifest, source_hashes = _prepare(runtime, case, tmp_path, monkeypatch, cap=cap)
    parent_events, child_events = tmp_path / "parent-http.jsonl", tmp_path / "child-http.jsonl"
    with sp.run_lock(original):
        state = runtime.po.PipelineOrchestrator.start(**request)
        binding = state.options[lifecycle.BINDING_KEY]
        with lifecycle.pipeline_scope(state), _parent_http(binding, parent_events, monkeypatch):
            forecast = build_target_report(case, None)["forecast"]

            def methods():
                return freeze_target_estimators(case, forecast, state.options.get("aggregation_policy_v1"),
                                                llm=tp._method_gateway(), enabled=True)

            lanes = methods()
            assert sum(row["status"] == "ok" and row["source"] in {"reference_class", "trend", "adversarial"}
                       for row in lanes["estimators"]) == 3
            assert len(audit.read_rows(binding)) == 3
            with sp.operation("research", "composed-independent-child"):
                child = sp.register_participant(binding, "research-composed", spawn_receipt_sha256=sp.hash_payload("synthetic spawn"))
                child_env = dict(os.environ, **sp.export_environment(child))
            child_env.update(LLM_API_KEY=KEY, FIRECRAWL_API_KEY=KEY,
                FIRECRAWL_SEARCH_API_URL="https://firecrawl.invalid/v2/search",
                FIRECRAWL_API_URL="https://firecrawl.invalid/v2/scrape",
                RESEARCH_SEARCH_CACHE_DIR=str(tmp_path / "search-cache"),
                RESEARCH_SOURCE_CACHE_DIR=str(tmp_path / "fetch-cache"),
                RESEARCH_FIRECRAWL_CALLS_PER_MINUTE="0", RESEARCH_BUDGET_ENABLED="false")
            control = {"mode": mode, "events": str(child_events), "work": str(tmp_path / "child-work"),
                       "ready": str(tmp_path / "ready.json"), "probe": str(tmp_path / "probe.json"),
                       "result": str(tmp_path / "child-result.json"), "dependency_bundle": str(dependency_bundle),
                       "archive_sha256": BUNDLE_SHA256}
            process = _spawn(control, child_env, tmp_path)
            try:
                ready = _wait_file(Path(control["ready"]), process)
                assert ready["pid"] == process.pid != os.getpid()
                assert ready["db_path"] == binding["db_path"] and ready["pipeline_id"] == state.pipeline_id
                assert ready["isolated"] == ready["no_site"] == 1
                assert ready["actual_chatopenai"] and ready["fake_layers"] == ["HTTP MockTransport only"]
                assert ready["module_sha256"] == source_hashes["deerflow_bridge/run_spending.py"]
                assert ready["production_sources"] == {name: source_hashes[name] for name in (
                    "deerflow_bridge/run_spending.py", "deerflow_bridge/research_gateway.py",
                    "deerflow_bridge/linear_research.py", "deerflow_bridge/cached_fetch.py", "deerflow_bridge/search_tools.py")}
                assert ready["outcome"] == (expected if mode == "child_unknown" else "completed")
                callback = tp._decision_provider(runtime.po.PipelineOrchestrator, state)

                def actors():
                    return run_paths(case, paths=1, periods=1, seed=7, decision_provider=callback)

                if mode in {"budget", "context"}:
                    result = actors()
                    assert len(result["paths"]) == 1 and state.options["target_decision_usage"]["requests"] == 2
                    if mode == "context":
                        token = sp._operation.set(None)  # Inject a lost caller context, never synthesize one.
                        try:
                            with pytest.raises(sp.SpendingStop, match=expected):
                                methods()
                        finally:
                            sp._operation.reset(token)
                    else:
                        with pytest.raises(sp.SpendingStop, match=expected):
                            methods()
                else:
                    with pytest.raises(sp.SpendingStop, match=expected):
                        actors()
                stopped_rows = audit.read_rows(binding)
                for call in (methods, actors):
                    with pytest.raises(sp.SpendingStop, match=expected):
                        call()
                audit.write_json(control["probe"], {"continue": True})
                stdout, stderr = process.communicate(timeout=25)
                assert process.returncode == 0, (stdout[-1000:], stderr[-3000:])
                report = json.loads(Path(control["result"]).read_text())
                assert set(report["probes"].values()) == {expected}
                assert report["dependency_imports"] and "langchain_openai" in report["dependency_imports"]
                sp.participant_exited(binding, child["participant_id"],
                    exit_receipt_sha256=sp.hash_payload({"pid": process.pid, "exit": process.returncode}))
                assert audit.read_rows(binding) == stopped_rows
                expected_total = 66016 if mode == "child_unknown" else 76016 if mode == "actor_budget" else 85216
                assert sp.summary(binding)["reserved_max_microusd"] == expected_total
                stopped_summary = sp.summary(binding)
                with pytest.raises(sp.SpendingStop):
                    sp.resume_existing(binding, store_cases.proof(binding, manifest))
                with pytest.raises(sp.SpendingStop):
                    sp.create_authorization(binding["manifest_path"], registry_dir=binding["registry_dir"])
                launches = len(runtime.launched)
                with pytest.raises(sp.SpendingStop):
                    runtime.po.PipelineOrchestrator.start(**request)
                assert len(runtime.launched) == launches and audit.read_rows(binding) == stopped_rows
                for field in ("cap_microusd", "reserved_max_microusd", "remaining_microusd", "pipeline_id", "generation"):
                    assert sp.summary(binding)[field] == stopped_summary[field]
                # Reconcile AFTER every negative probe so an unreserved call
                # cannot disappear into the expected spending-stop wrapper.
                entries = _assert_events([parent_events, child_events], stopped_rows)
                assert {event["pid"] for event in entries} == {os.getpid(), process.pid}
                assert sum(event["stage"] == "estimator" for event in entries) == 3
                assert sum(event["stage"] == "actor" for event in entries) == (2 if mode in {"budget", "context"} else 0)
                assert _hashes() == source_hashes
                audit.write_json(tmp_path / "workflow-receipt.json", {
                    "mode": mode, "parent_pid": os.getpid(), "child_pid": process.pid,
                    "source_sha256": source_hashes, "spending": sp.summary(binding),
                    "raw_entries": len(entries), "parent_method_calls": 3,
                    "actual_parent_method_actor_producers": True, "child": report})
            finally:
                _reap(process)


def test_fresh_parent_process_core_resume_retains_maximum_and_fences_old_generation(runtime, case, tmp_path, monkeypatch):
    """Store-level SB-08 only; no claim about completed-research backend eligibility."""
    original, request, manifest, source_hashes = _prepare(runtime, case, tmp_path, monkeypatch, cap="1.00", resume=True)
    parent_events, resumed_events = tmp_path / "parent-http.jsonl", tmp_path / "resumed-http.jsonl"
    with sp.run_lock(original):
        state = runtime.po.PipelineOrchestrator.start(**request)
        binding = state.options[lifecycle.BINDING_KEY]
        with lifecycle.pipeline_scope(state), _parent_http(binding, parent_events, monkeypatch):
            client = LLMClient()
            client.chat([{"role": "user", "content": "synthetic first attempt"}], max_tokens=500)
            assert sp.summary(binding)["reserved_max_microusd"] == 600000
            sp.mark_recoverable(binding)
            proof = store_cases.proof(binding, manifest)
    # The old parent still exists, but has released the OS lock. A new PID must
    # acquire it and advance the same durable generation, never create a ledger.
    before = audit.read_rows(binding)
    control = {"mode": "resume", "proof": proof, "config": _config(),
               "events": str(resumed_events), "result": str(tmp_path / "resume-result.json")}
    child_env = dict(os.environ, **sp.export_environment(binding))
    process = _spawn(control, child_env, tmp_path)
    try:
        stdout, stderr = process.communicate(timeout=25)
    finally:
        _reap(process)
    assert process.returncode == 0, (stdout[-1000:], stderr[-3000:])
    report = json.loads(Path(control["result"]).read_text())
    assert report["pid"] == process.pid != os.getpid()
    assert report["isolated"] == report["no_site"] == 1
    assert report["module_sha256"] == source_hashes["deerflow_bridge/run_spending.py"]
    assert report["outcome"] == "budget_exhausted"
    assert report["proof_scope"] == "core_resume_with_real_parent_transport"
    assert report["binding"]["generation"] == binding["generation"] + 1
    for key in ("db_path", "root", "pipeline_id", "authorization_id", "manifest_sha256"):
        assert report["binding"][key] == binding[key]
    assert report["summary"]["reserved_max_microusd"] == 600000
    assert report["summary"]["remaining_microusd"] == 400000
    assert audit.read_events(resumed_events) == []
    with pytest.raises(sp.SpendingStop, match="stale_generation"):
        client.chat([{"role": "user", "content": "old generation"}], max_tokens=500)
    assert audit.read_rows(report["binding"]) == before
    _assert_events([parent_events, resumed_events], before)
    assert _hashes() == source_hashes
    audit.write_json(tmp_path / "workflow-resume-receipt.json", {
        "proof_scope": "core_resume_with_real_parent_transport",
        "old_pid": os.getpid(), "new_pid": process.pid, "old_generation": binding["generation"],
        "source_sha256": source_hashes, "resume": report, "old_parent_fenced": True,
        "retained_before_microusd": 600000, "additional_raw_calls": 0})


@pytest.mark.parametrize("cap,tamper,funded", [("2.00", False, False), ("5.00", False, True), ("2.00", True, False)],
                         ids=["remaining-denial", "funded-publication", "tampered-request"])
def test_fresh_pid_backend_resume_requires_sealed_research_and_retains_cap(execution, tmp_path, monkeypatch,
                                                                         cap, tamper, funded):
    """The unchanged actor quote fits a fresh cap but fails retained balance; a funded twin publishes."""
    from app.services import target_simulation

    execution.case["actors"][0]["decisionRule"]["kind"] = "llm"
    original, request, manifest, source_hashes = _prepare(execution, execution.case, tmp_path, monkeypatch,
                                                        cap=cap, resume=True)
    parent_events, resumed_events = tmp_path / "parent-http.jsonl", tmp_path / "resumed-http.jsonl"
    with sp.run_lock(original):
        state = execution.po.PipelineOrchestrator.start(**request)
        binding = state.options[lifecycle.BINDING_KEY]
        with lifecycle.pipeline_scope(state), _parent_http(binding, parent_events, monkeypatch):
            old_client = LLMClient()
            old_client.chat([{"role": "user", "content": "synthetic initial physical attempt"}], max_tokens=500)
        assert sp.summary(binding)["reserved_max_microusd"] == 600000
        reached = []

        def recoverable_compute_failure(*args, **kwargs):
            assert tp.validate_stage(state, "research") and tp.validate_stage(state, "prepare")
            reached.append("after-sealed-research-and-prepare")
            raise RuntimeError("synthetic recoverable compute failure")

        with monkeypatch.context() as patch:
            patch.setattr(target_simulation, "run_paths", recoverable_compute_failure)
            execution.po.PipelineOrchestrator._run(state)
        assert reached == ["after-sealed-research-and-prepare"]
        assert len(execution.calls) == 1
        assert state.status == "failed" and state.current_stage == "run"
        assert sp.summary(binding)["state"] == "paused_recoverable"
        assert state.stages["research"].status == state.stages["prepare"].status == "completed"
        assert tp.validate_stage(state, "research") and tp.validate_stage(state, "prepare")
        artifact_hashes = {name: hashlib.sha256(Path(filename).read_bytes()).hexdigest()
            for stage in ("research", "prepare") for name, filename in tp.stage_specs(state, stage)}
        proof = store_cases.proof(binding, manifest)
        if tamper:
            # Real saved-state mutation of both copies must fail against the
            # immutable manifest. Never fake a completed-stage flag/receipt.
            saved = execution.po.PipelineState.from_dict(execution.po.PipelineManager.load(state.pipeline_id))
            saved.prompt = "Different synthetic target"
            saved.options[lifecycle.REQUEST_KEY]["prompt"] = saved.prompt
            execution.po.PipelineManager.save(saved)
    before = audit.read_rows(binding)
    control = {"mode": "backend_resume", "proof": proof, "config": _config(),
               "events": str(resumed_events), "result": str(tmp_path / "backend-resume-result.json")}
    process = _spawn(control, dict(os.environ, **sp.export_environment(binding)), tmp_path)
    try:
        stdout, stderr = process.communicate(timeout=25)
    finally:
        _reap(process)
    assert process.returncode == 0, (stdout[-1000:], stderr[-4000:])
    report = json.loads(Path(control["result"]).read_text())
    assert report["proof_scope"] == "backend_resume_after_sealed_research"
    assert report["pid"] == process.pid != os.getpid()
    assert report["isolated"] == report["no_site"] == 1
    assert report["module_sha256"] == source_hashes["deerflow_bridge/run_spending.py"]
    assert report["outcome"] == ("binding_conflict" if tamper else "completed" if funded else "budget_exhausted")
    assert report["binding"]["generation"] == (1 if tamper else 2)
    assert report["scheduled_workers"] == (0 if tamper else 1)
    assert report["research_valid"] and report["prepare_valid"]
    assert report["artifact_sha256"] == artifact_hashes and report["unexpected_producers"] == []
    assert report["status"] == ("completed" if funded else "failed")
    if funded:
        assert report["report_id"] and report["publication"]["publishable"]
        assert report["report_stage_valid"] and set(report["stage_statuses"].values()) == {"completed"}
        assert report["summary"]["state"] == "closed"
    else:
        assert report["report_id"] is None
    if not tamper:
        assert report["decision_usage"]["requests"] == 1
    for field in ("pipeline_id", "authorization_id", "root", "db_path", "source_sha256", "manifest_sha256"):
        assert report["binding"][field] == binding[field]
    original_cap = 5000000 if funded else 2000000
    actor_quote = 1900000  # Full input ceiling 100 + production output maximum 1800, at $1000/M each.
    remaining_before_resume = original_cap - 600000
    assert report["summary"]["cap_microusd"] == original_cap
    assert report["summary"]["reserved_max_microusd"] == (2500000 if funded else 600000)
    assert report["summary"]["remaining_microusd"] == (2500000 if funded else 1400000)
    if not funded:
        assert remaining_before_resume < actor_quote <= original_cap
        assert audit.read_events(resumed_events) == []
    else:
        assert actor_quote <= remaining_before_resume
        observed = [event for event in audit.read_events(resumed_events) if event["event"] == "verified"]
        assert len(observed) == 1 and observed[0]["reserved"] == actor_quote and observed[0]["stage"] == "actor"
    with pytest.raises(sp.SpendingStop, match="binding_conflict" if tamper else "stale_generation"):
        old_client.chat([{"role": "user", "content": "old parent attempt"}], max_tokens=500)
    after = audit.read_rows(report["binding"])
    assert after[:1] == before and len(after) == (2 if funded else 1)
    if funded:
        assert json.loads(after[-1]["envelope"])["max_output_tokens"] == 1800
        assert after[-1]["reserved"] == actor_quote
    _assert_events([parent_events, resumed_events], after)
    assert _hashes() == source_hashes
    audit.write_json(tmp_path / "workflow-backend-resume-receipt.json", {
        "proof_scope": "backend_resume_after_sealed_research", "tampered_request": tamper,
        "funded_publication": funded, "original_cap_microusd": original_cap,
        "remaining_before_resume_microusd": remaining_before_resume, "actor_quote_microusd": actor_quote,
        "initial_producer_fidelity": "existing scripted research/method fixture; real pipeline artifact sealing",
        "old_pid": os.getpid(), "new_pid": process.pid, "source_sha256": source_hashes,
        "resume": report, "retained_before_microusd": 600000, "additional_raw_calls": 1 if funded else 0})
