"""Controller admission persists enabled intent under the immutable v2 request."""

from contextlib import contextmanager
from copy import deepcopy
import json
from pathlib import Path

from flask import Flask
import pytest

from app.services import world_anchor as anchor, run_spending as lifecycle
from test_target_pipeline import runtime as _runtime
from test_world_anchor_spending import isolated as _isolated, make_authority, sp

runtime = _runtime
isolated = _isolated


@contextmanager
def prepared(tmp_path, monkeypatch, runtime):
    manifest, path, registry, request = make_authority(tmp_path)
    request["model"] = "glm"
    manifest["request_sha256"] = sp.hash_payload(request)
    path.write_text(json.dumps(manifest))
    binding = sp.create_authorization(path, registry_dir=registry)
    root = Path(binding["root"])
    from app.models.project import ProjectManager
    from app.services.report_agent import ReportManager

    for key, value in {
        "UPLOAD_FOLDER": root / "uploads",
        "PIPELINE_DATA_DIR": root / "uploads/pipelines",
        "OASIS_SIMULATION_DATA_DIR": root / "uploads/simulations",
        "DEERFLOW_DIR": root / "deer-flow",
    }.items():
        monkeypatch.setattr(runtime.config, key, str(value))
    monkeypatch.setattr(ProjectManager, "PROJECTS_DIR", str(root / "uploads/projects"))
    monkeypatch.setattr(ReportManager, "REPORTS_DIR", str(root / "uploads/reports"))
    for key, value in sp.export_environment(binding).items():
        monkeypatch.setenv(key, value)
    with sp.run_lock(binding):
        yield binding, request


def test_v2_start_preflights_and_saves_pending_before_worker(runtime, tmp_path, monkeypatch):
    checks = []
    real = sp.preflight_anchor_profile

    def checked(binding):
        assert binding["pipeline_id"]
        assert not runtime.launched
        checks.append(binding["pipeline_id"])
        return real(binding)

    monkeypatch.setattr(sp, "preflight_anchor_profile", checked)
    with prepared(tmp_path, monkeypatch, runtime) as (_, request):
        state = runtime.po.PipelineOrchestrator.start(**request)
        saved = runtime.po.PipelineManager.load(state.pipeline_id)
        pending = saved["options"][anchor.LIFECYCLE_KEY]
        assert checks == [state.pipeline_id]
        assert saved["options"][anchor.CONFIG_KEY] == request["world_anchor"]
        assert pending["status"] == "pending" and pending["completion_manifest_sha256"] is None
        assert pending["request_sha256"] == sp.hash_payload(request)
        assert anchor.enabled(saved["options"])
        assert len(runtime.launched) == 1


def _public_route(monkeypatch, surface):
    from app.api import research, sdk

    monkeypatch.setattr(research, "preflight_pipeline", lambda **kw: [])
    monkeypatch.setattr(sdk, "preflight_pipeline", lambda **kw: [])
    app = Flask(__name__)
    app.register_blueprint(research.research_bp, url_prefix="/api/research")
    app.register_blueprint(sdk.sdk_bp, url_prefix="/api/v1")
    return app.test_client(), "/api/research/run" if surface == "spa" else "/api/v1/run"


@pytest.mark.parametrize("surface", ["spa", "sdk"])
def test_public_mode_selector_reaches_authorized_pending_before_worker(runtime, tmp_path, monkeypatch, surface):
    client, path = _public_route(monkeypatch, surface)
    events = []
    original_preflight = sp.preflight_anchor_profile
    original_thread = runtime.po.threading.Thread

    def preflight(binding):
        assert binding["pipeline_id"] and not runtime.launched
        assert sp.summary(binding)["pipeline_id"] == binding["pipeline_id"]
        events.append("preflight")
        return original_preflight(binding)

    class ObservedWorker(original_thread):
        def start(self):
            (state,) = self.kwargs["args"]
            saved = runtime.po.PipelineManager.load(state.pipeline_id)
            assert events == ["preflight"]
            assert saved["options"][lifecycle.REQUEST_KEY] == request
            assert saved["options"][anchor.CONFIG_KEY] == request["world_anchor"]
            pending = saved["options"][anchor.LIFECYCLE_KEY]
            assert pending["status"] == "pending" and pending["completion_manifest_sha256"] is None
            assert pending["request_sha256"] == sp.hash_payload(request)
            events.append("worker")
            super().start()

    monkeypatch.setattr(sp, "preflight_anchor_profile", preflight)
    monkeypatch.setattr(runtime.po.threading, "Thread", ObservedWorker)
    with prepared(tmp_path, monkeypatch, runtime) as (_, request):
        public = {**request, "world_anchor": {"mode": "v1"}}
        result = client.post(path, json=public)
        assert result.status_code == 200, result.json
        state = runtime.po.PipelineManager.load(result.json["data"]["pipeline_id"])
        assert state["options"][lifecycle.REQUEST_KEY] == request
        assert state["options"][anchor.CONFIG_KEY] == request["world_anchor"]
        assert state["options"][anchor.LIFECYCLE_KEY]["status"] == "pending"
        assert events == ["preflight", "worker"]
        assert public["world_anchor"] == {"mode": "v1"}


@pytest.mark.parametrize("surface", ["spa", "sdk"])
@pytest.mark.parametrize(
    "private_key",
    ["anchor_budget_scope_id", "token_envelope_limit", "policy_version", "source_policy_sha256", "full_authorized"],
)
def test_public_private_anchor_fields_are_rejected_even_when_authorized(
    runtime, tmp_path, monkeypatch, surface, private_key
):
    client, path = _public_route(monkeypatch, surface)
    with prepared(tmp_path, monkeypatch, runtime) as (binding, request):
        public = {**request, "world_anchor": {"mode": "v1"}}
        if private_key == "full_authorized":
            public["world_anchor"] = deepcopy(request["world_anchor"])
        else:
            public["world_anchor"][private_key] = request["world_anchor"][private_key]
        result = client.post(path, json=public)
        assert result.status_code == 409, result.json
        assert result.json["error_code"] == "invalid_request"
        assert not runtime.launched
        assert sp.summary(binding)["pipeline_id"] == ""
        assert sp.summary(binding)["attempt_count"] == 0


@pytest.mark.parametrize("surface", ["spa", "sdk"])
@pytest.mark.parametrize("changed", ["prompt", "paths", "seed", "scope", "limit"])
def test_changed_public_request_never_creates_worker(runtime, tmp_path, monkeypatch, surface, changed):
    client, path = _public_route(monkeypatch, surface)
    with prepared(tmp_path, monkeypatch, runtime) as (binding, request):
        public = deepcopy(request)
        public["world_anchor"] = {"mode": "v1"}
        if changed == "prompt":
            public["prompt"] += " Another question."
        elif changed in {"paths", "seed"}:
            public["target_simulation"][changed] += 1
        elif changed == "scope":
            public["world_anchor"]["anchor_budget_scope_id"] = "caller-scope"
        else:
            public["world_anchor"]["token_envelope_limit"] = 149999
        result = client.post(path, json=public)
        assert result.status_code == 409, result.json
        assert result.json["error_code"] == ("invalid_request" if changed in {"scope", "limit"} else "binding_conflict")
        assert not runtime.launched
        assert sp.summary(binding)["pipeline_id"] == ""
        assert sp.summary(binding)["attempt_count"] == 0


@pytest.mark.parametrize("surface", ["spa", "sdk"])
@pytest.mark.parametrize("selector", [None, False, True, {}, {"mode": "v2"}, {"mode": "v1", "unknown": 1}])
def test_public_anchor_selector_is_closed(runtime, tmp_path, monkeypatch, surface, selector):
    client, path = _public_route(monkeypatch, surface)
    with prepared(tmp_path, monkeypatch, runtime) as (_, request):
        result = client.post(path, json={**request, "world_anchor": selector})
        assert result.status_code == 409, result.json
        assert result.json["error_code"] == "invalid_request"
        assert not runtime.launched


@pytest.mark.parametrize("surface", ["spa", "sdk"])
@pytest.mark.parametrize(
    "mutation",
    ["duplicate", "nested_duplicate", "oversized", "nonfinite", "foreign_field", "hash", "source", "symlink"],
)
def test_manifest_change_during_public_expansion_cannot_bind(runtime, tmp_path, monkeypatch, surface, mutation):
    """Mutate after real core validation, before the adapter's separate read."""
    client, route = _public_route(monkeypatch, surface)
    with prepared(tmp_path, monkeypatch, runtime) as (binding, request):
        original_expand = lifecycle._authorized_anchor_option
        original_open = sp.open_existing
        original_bind = sp.bind_pipeline
        reached, binds = [], []
        path = Path(binding["manifest_path"])
        original = path.read_bytes()
        source = Path(binding["root"]) / "app/source.py"
        original_source = source.read_bytes()

        def mutate():
            text = original.decode()
            if mutation == "duplicate":
                path.write_text(text[:-1] + ', "currency": "USD"}')
            elif mutation == "nested_duplicate":
                path.write_text(
                    text.replace('"scope_id": "anchor-one"', '"scope_id": "anchor-one", "scope_id": "anchor-one"', 1)
                )
            elif mutation == "oversized":
                path.write_bytes(original + b" " * (4_000_001 - len(original)))
            elif mutation == "nonfinite":
                path.write_text(text.replace('"cap_usd": "100"', '"cap_usd": NaN', 1))
            elif mutation == "symlink":
                other = path.with_name("alternate.json")
                other.write_bytes(original)
                path.unlink()
                path.symlink_to(other)
            elif mutation == "source":
                source.write_bytes(original_source + b"# changed after manifest admission\n")
            else:
                changed = json.loads(original)
                if mutation == "foreign_field":
                    changed["anchor_budget"]["caller_override"] = True
                else:
                    changed["anchor_budget"]["token_envelope_limit"] -= 1
                path.write_text(json.dumps(changed))

        def expand_after_validation(value):
            def validated_then_changed(candidate):
                validated = original_open(candidate)
                reached.append(True)
                mutate()
                return validated

            with monkeypatch.context() as scoped:
                scoped.setattr(sp, "open_existing", validated_then_changed)
                return original_expand(value)

        def bind(*args, **kwargs):
            binds.append(True)
            return original_bind(*args, **kwargs)

        monkeypatch.setattr(lifecycle, "_authorized_anchor_option", expand_after_validation)
        monkeypatch.setattr(sp, "bind_pipeline", bind)
        try:
            result = client.post(route, json={**request, "world_anchor": {"mode": "v1"}})
            assert result.status_code == 409, result.json
            expected = "source_drift" if mutation in {"hash", "source"} else "invalid_manifest"
            assert result.json["error_code"] == expected
            assert reached == [True]
            assert binds == ([True] if mutation == "source" else [])
            assert not runtime.launched
        finally:
            if path.is_symlink():
                path.unlink()
            path.write_bytes(original)
            source.write_bytes(original_source)
        assert sp.summary(binding)["pipeline_id"] == ""
        assert sp.summary(binding)["attempt_count"] == 0


@pytest.mark.parametrize("mutation", ["scope", "tokens", "remove"])
def test_changed_anchor_request_does_not_launch(runtime, tmp_path, monkeypatch, mutation):
    with prepared(tmp_path, monkeypatch, runtime) as (binding, request):
        changed = deepcopy(request)
        if mutation == "scope":
            changed["world_anchor"]["anchor_budget_scope_id"] = "another-scope"
        elif mutation == "tokens":
            changed["world_anchor"]["token_envelope_limit"] += 1
        else:
            changed.pop("world_anchor")
        with pytest.raises(sp.SpendingStop):
            runtime.po.PipelineOrchestrator.start(**changed)
        assert not runtime.launched
        assert sp.summary(binding)["attempt_count"] == 0


def test_pending_or_failed_intent_never_becomes_off(monkeypatch):
    monkeypatch.setenv("SIM_WORLD_ANCHOR", "false")
    for status in ("pending", "failed"):
        options = {
            anchor.CONFIG_KEY: {"mode": "v1"},
            anchor.LIFECYCLE_KEY: {"schema_version": "world-anchor-lifecycle/v1", "status": status},
        }
        assert anchor.enabled(options)
        options.pop(anchor.LIFECYCLE_KEY)
        with pytest.raises(anchor.WorldAnchorIntegrationError):
            anchor.enabled(options)
    monkeypatch.setenv("SIM_WORLD_ANCHOR", "true")
    assert anchor.enabled({}) is False


def test_new_enabled_request_needs_qualified_private_profile(runtime, monkeypatch):
    monkeypatch.setattr(runtime.config, "SIM_WORLD_ANCHOR", False, raising=False)
    with pytest.raises(anchor.WorldAnchorIntegrationError, match="anchor_profile_required"):
        runtime.po.PipelineOrchestrator.start(prompt="A question", world_anchor=True)
    assert not runtime.launched
