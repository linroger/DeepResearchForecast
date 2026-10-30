"""Bounded offline acceptance of the private World Anchor launcher boundary.

Reuse the unchanged v1 synthetic source/interpreter fixture and real spending
store. No interpreter provisioning or model deployment is claimed. Child spies
observe pre-import ordering; admitted HTTP uses MockTransport through dispatch.
"""
from copy import deepcopy
from pathlib import Path
import json
import sys
import types

import httpx
import pytest

import test_run_spending_launcher as legacy


launcher, core = legacy.launcher, legacy.core
prepared = legacy.prepared
isolation = legacy.isolation
put = legacy.put
pytestmark = pytest.mark.guarded_runner

FROZEN_CORE = "d7691253c4f842b0355113f39930ec0ace4671ae35ed608b533daddbcd6322df"
LIMITS = {
    "model_attempt_limit": 20,
    "token_envelope_limit": 150000,
    "catalog_attempt_limit": 8,
    "followup_attempt_limit": 12,
    "catalog_lookups_per_gap": 1,
    "followup_round_limit": 1,
}


@pytest.fixture(autouse=True)
def isolate_v2_control_binding(isolation, monkeypatch):
    """Extend the reused v1 fixture without changing its shared source."""
    monkeypatch.setattr(core, "_V2_CONTROL_BINDING", None)


def anchor_request(request, budget):
    return {**deepcopy(request), "world_anchor": {
        "mode": "v1", "anchor_budget_scope_id": budget["scope_id"],
        "policy_version": budget["policy_version"],
        "source_policy_sha256": budget["source_policy_sha256"],
        **{name: budget[name] for name in LIMITS},
    }}


def candidate(prepared, tmp_path, **changes):
    spec = deepcopy(prepared.spec)
    budget = {
        "schema": "anchor-budget/v1", "scope_id": "synthetic-launcher-anchor",
        "policy_version": "world-anchor-budget/v1",
        "source_policy_sha256": core.hash_payload("offline source policy"),
        **LIMITS, "model_profile": {"route_id": "model", "max_output_tokens": 100},
        "catalog_route_ids": [], "followup_route_ids": ["search", "scrape"],
        "usage_policy": "provider_reported_required",
    }
    budget.update(changes)
    spec.update(schema="target-acceptance-prepare/v2", anchor_budget=budget)
    spec["request"] = anchor_request(spec["request"], budget)
    return types.SimpleNamespace(
        root=tmp_path / "anchor-runtime", source=prepared.source,
        harness=prepared.harness, dependencies=prepared.dependencies,
        spec_path=tmp_path / "anchor-spec.json", spec=spec,
    )


def prepare_anchor(value):
    put(value.spec_path, value.spec)
    value.checked = launcher.prepare(value.source, value.harness, value.root, value.spec_path)
    return value


@pytest.fixture
def v2_prepared(prepared, tmp_path):
    return prepare_anchor(candidate(prepared, tmp_path))


def manifest_for(value):
    manifest = legacy.manifest_for(value)
    manifest.update(schema="target-run-spending/v2", anchor_budget=deepcopy(value.spec["anchor_budget"]))
    route = manifest["routes"]["model"]
    route.update(input_ceiling=value.checked["model"]["input_ceiling"],
                 max_output_tokens=value.checked["model"]["max_output_tokens"])
    manifest["routes_sha256"] = core.hash_payload(manifest["routes"])
    return manifest


def authorize(value, tmp_path):
    manifest = manifest_for(value)
    assert launcher.qualify_manifest(core, value.checked, manifest) == manifest
    put(value.root / "spend/authorization.json", manifest)
    registry = tmp_path / "anchor-registry"
    registry.mkdir(mode=0o700)
    binding = core.create_authorization(value.root / "spend/authorization.json", registry_dir=registry)
    return manifest, binding


def session():
    return {
        "session_id": "launcher-session", "research_generation_id": "research-1",
        "input_manifest_sha256": core.hash_payload("inputs"),
        "requirement_registry_sha256": core.hash_payload("requirements"),
        "workers_quiesced_sha256": core.hash_payload("no workers yet"),
        "restart_of_session_id": None,
    }


def child_environment(value, binding, monkeypatch):
    with core.operation("research", "launcher-root"):
        child = core.register_participant(binding, "launcher-child", spawn_receipt_sha256=core.hash_payload("spawn"))
        carriers = core.export_environment(child)
    assert set(carriers) == set(launcher.CARRIERS)
    for key, item in {**carriers, **legacy.credentials()}.items():
        monkeypatch.setenv(key, item)
    monkeypatch.setattr(launcher, "__file__", str(value.root / launcher.LAUNCHER))
    monkeypatch.setattr(launcher, "load_core", lambda *args, **kwargs: core)
    monkeypatch.setattr(sys, "argv", ["before-child"])
    return child


def test_frozen_core_and_provider_free_v2_preparation(v2_prepared, prepared):
    value = v2_prepared
    assert launcher.digest((legacy.REPO / "deerflow_bridge/run_spending.py").read_bytes()) == FROZEN_CORE
    assert launcher.verify(value.root) == value.checked
    assert value.checked["runtime"]["schema"] == "target-acceptance-runtime/v2"
    assert set(value.checked["runtime"]) == set(prepared.checked["runtime"])
    assert set(value.checked["request"]) == set(prepared.checked["request"]) | {"world_anchor"}
    budget_path = value.root / "control/anchor_budget.json"
    assert json.loads(budget_path.read_bytes()) == value.spec["anchor_budget"]
    assert value.checked["source_files"]["control/anchor_budget.json"] == launcher.digest(budget_path.read_bytes())
    assert (value.root / "control/runtime.json").read_bytes() == (value.root / "spend/runtime.json").read_bytes()
    assert {path.name for path in (value.root / "spend").iterdir()} == {"runtime.json"}
    assert set(launcher.controlled_environment(value.root, value.checked)) == set(
        launcher.controlled_environment(prepared.root, prepared.checked))
    for item in (value, prepared):
        environment = launcher.controlled_environment(item.root, item.checked)
        assert environment["FMP_ENABLED"] == "false" and "FMP_API_KEY" not in environment
    assert launcher.check_request(prepared.checked["request"]) == prepared.checked["request"]
    assert launcher.check_request(value.checked["request"]) == value.checked["request"]


@pytest.mark.parametrize("field", ["mode", "anchor_budget_scope_id", "policy_version", "source_policy_sha256", *LIMITS])
def test_private_request_requires_every_anchor_field(prepared, tmp_path, field):
    request = candidate(prepared, tmp_path).spec["request"]
    del request["world_anchor"][field]
    with pytest.raises(launcher.LauncherStop, match="invalid_request"):
        launcher.check_request(request)


@pytest.mark.parametrize("attack", ["extra_top", "missing_top", "extra_private", "public_only", "off", "not_object"])
def test_request_is_exact_v1_or_complete_private_v2(prepared, tmp_path, attack):
    request = candidate(prepared, tmp_path).spec["request"]
    if attack == "extra_top":
        request["scope_id"] = "mutable-selector"
    elif attack == "missing_top":
        del request["target_simulation"]
    elif attack == "extra_private":
        request["world_anchor"]["environment_scope"] = "mutable-selector"
    elif attack == "public_only":
        request["world_anchor"] = {"mode": "v1"}
    elif attack == "off":
        request["world_anchor"]["mode"] = "off"
    else:
        request["world_anchor"] = []
    with pytest.raises(launcher.LauncherStop, match="invalid_request"):
        launcher.check_request(request)


@pytest.mark.parametrize("field", list(LIMITS))
@pytest.mark.parametrize("invalid", [True, 1.0, "1", -1])
def test_request_budget_counts_are_strict_integers(prepared, tmp_path, field, invalid):
    request = candidate(prepared, tmp_path).spec["request"]
    request["world_anchor"][field] = invalid
    with pytest.raises(launcher.LauncherStop, match="invalid_request"):
        launcher.check_request(request)


@pytest.mark.parametrize("field", list(LIMITS))
@pytest.mark.parametrize("coercion", ["float", "bool"])
def test_budget_count_types_cannot_hide_behind_numeric_equality(prepared, tmp_path, field, coercion):
    value = candidate(prepared, tmp_path, model_attempt_limit=1, token_envelope_limit=200,
                      catalog_attempt_limit=1, followup_attempt_limit=1)
    budget, request, model = (value.spec[key] for key in ("anchor_budget", "request", "model"))
    launcher.check_anchor_budget(budget, request, model)
    budget[field] = float(budget[field]) if coercion == "float" else True
    with pytest.raises(launcher.LauncherStop):
        launcher.check_anchor_budget(budget, request, model)


@pytest.mark.parametrize("field", list(LIMITS))
def test_request_and_budget_refuse_higher_than_frozen_limits(prepared, tmp_path, field):
    value = candidate(prepared, tmp_path, **{field: LIMITS[field] + 1})
    with pytest.raises(launcher.LauncherStop):
        launcher.check_request(value.spec["request"])
    with pytest.raises(launcher.LauncherStop):
        launcher.check_anchor_budget(value.spec["anchor_budget"], value.spec["request"], value.spec["model"])


@pytest.mark.parametrize("field", ["schema", "scope_id", "policy_version", "source_policy_sha256", *LIMITS,
                                    "model_profile", "catalog_route_ids", "followup_route_ids", "usage_policy"])
def test_budget_requires_exact_closed_schema(prepared, tmp_path, field):
    value = candidate(prepared, tmp_path)
    del value.spec["anchor_budget"][field]
    with pytest.raises(launcher.LauncherStop):
        launcher.check_anchor_budget(value.spec["anchor_budget"], value.spec["request"], value.spec["model"])


@pytest.mark.parametrize("change", [
    {"extra": 1}, {"schema": "anchor-budget/v2"}, {"policy_version": "different-policy"},
    {"source_policy_sha256": "A" * 64}, {"scope_id": ""},
    {"model_attempt_limit": 0}, {"token_envelope_limit": 0},
    {"catalog_lookups_per_gap": 0}, {"followup_round_limit": 0},
    {"usage_policy": "estimated_allowed"}, {"catalog_route_ids": "catalog"},
    {"catalog_route_ids": ["catalog", "catalog"]}, {"followup_route_ids": ["search", "search"]},
    {"model_profile": {"route_id": "model", "max_output_tokens": True}},
    {"model_profile": {"route_id": "model", "max_output_tokens": 2001}},
    {"model_profile": {"route_id": "model", "max_output_tokens": 101}},
    {"model_profile": {"route_id": "model", "max_output_tokens": 0}},
    {"model_profile": {"route_id": "model", "max_output_tokens": 100, "headroom": 1}},
])
def test_budget_rejects_invalid_policy_and_output_profile(prepared, tmp_path, change):
    value = candidate(prepared, tmp_path)
    value.spec["anchor_budget"].update(change)
    with pytest.raises(launcher.LauncherStop):
        launcher.check_anchor_budget(value.spec["anchor_budget"], value.spec["request"], value.spec["model"])


@pytest.mark.parametrize("field", ["scope_id", "source_policy_sha256", "model_attempt_limit"])
def test_budget_and_request_must_agree_exactly(prepared, tmp_path, field):
    value = candidate(prepared, tmp_path)
    value.spec["anchor_budget"][field] = {
        "scope_id": "different-scope", "source_policy_sha256": core.hash_payload("different policy"),
        "model_attempt_limit": 19,
    }[field]
    with pytest.raises(launcher.LauncherStop):
        launcher.check_anchor_budget(value.spec["anchor_budget"], value.spec["request"], value.spec["model"])


@pytest.mark.parametrize("change", [{"policy_version": "different-policy"},
                                     {"source_policy_sha256": "A" * 64}, {"scope_id": ""}])
def test_matching_invalid_policy_cannot_pass_by_agreement(prepared, tmp_path, change):
    value = candidate(prepared, tmp_path, **change)
    budget, request = value.spec["anchor_budget"], value.spec["request"]
    assert request == anchor_request(prepared.spec["request"], budget)
    with pytest.raises(launcher.LauncherStop, match="invalid_request"):
        launcher.check_request(request)
    with pytest.raises(launcher.LauncherStop, match="invalid_request"):
        launcher.check_anchor_budget(budget, request, value.spec["model"])
    with pytest.raises(launcher.LauncherStop, match="invalid_request"):
        prepare_anchor(value)
    assert not value.root.exists()


@pytest.mark.parametrize("output,accepted", [(2000, True), (2001, False)])
def test_inclusive_output_hard_limit_independent_of_route_ceiling(prepared, tmp_path, output, accepted):
    value = candidate(prepared, tmp_path, model_profile={"route_id": "model", "max_output_tokens": output})
    value.spec["model"]["max_output_tokens"] = 4000
    assert value.spec["model"]["input_ceiling"] + output < value.spec["anchor_budget"]["token_envelope_limit"]
    if accepted:
        prepare_anchor(value)
        assert value.checked["anchor_budget"]["model_profile"]["max_output_tokens"] == 2000
    else:
        with pytest.raises(launcher.LauncherStop, match="invalid_request"):
            prepare_anchor(value)
        assert not value.root.exists()


@pytest.mark.parametrize("input_ceiling,accepted", [(148000, True), (148001, False), (200000, False)])
def test_full_input_and_inclusive_output_fit_before_runtime_or_imports(prepared, tmp_path, monkeypatch,
                                                                     input_ceiling, accepted):
    value = candidate(prepared, tmp_path, model_profile={"route_id": "model", "max_output_tokens": 2000})
    value.spec["model"].update(input_ceiling=input_ceiling, max_output_tokens=2000)
    for name in ("load_core", "setup_execution"):
        monkeypatch.setattr(launcher, name, lambda *a, **kw: pytest.fail("execution import during preparation"))
    if accepted:
        prepare_anchor(value)
        assert value.checked["model"]["input_ceiling"] == 148000
    else:
        with pytest.raises(launcher.LauncherStop):
            prepare_anchor(value)
        assert not value.root.exists()


def test_lower_limits_and_structural_catalog_ids_are_valid_at_prepare(prepared, tmp_path):
    value = candidate(prepared, tmp_path, model_attempt_limit=1, token_envelope_limit=200,
                      catalog_attempt_limit=0, followup_attempt_limit=0,
                      catalog_route_ids=["reviewed-later"], followup_route_ids=[])
    prepare_anchor(value)
    assert value.checked["request"]["world_anchor"]["token_envelope_limit"] == 200
    assert json.loads((value.root / "control/anchor_budget.json").read_bytes())["catalog_route_ids"] == ["reviewed-later"]


@pytest.mark.parametrize("attack", ["v1_with_v2", "v2_without_budget", "v2_with_v1_request", "v1_with_budget", "extra_field"])
def test_prepare_versions_do_not_cross_pair(prepared, tmp_path, attack):
    value = candidate(prepared, tmp_path)
    if attack == "v1_with_v2":
        value.spec["schema"] = "target-acceptance-prepare/v1"
        del value.spec["anchor_budget"]
    elif attack == "v2_without_budget":
        del value.spec["anchor_budget"]
    elif attack == "v2_with_v1_request":
        del value.spec["request"]["world_anchor"]
    elif attack == "v1_with_budget":
        value.spec["schema"] = "target-acceptance-prepare/v1"
        del value.spec["request"]["world_anchor"]
    else:
        value.spec["scope_selector"] = "not-authority"
    with pytest.raises(launcher.LauncherStop):
        prepare_anchor(value)
    assert not value.root.exists()


@pytest.mark.parametrize("relative", ["control/request.json", "control/anchor_budget.json", "control/runtime.json", "spend/runtime.json"])
def test_v2_control_tamper_fails_verification(v2_prepared, relative):
    path = v2_prepared.root / relative
    put(path, path.read_bytes() + b"\n")
    with pytest.raises(launcher.LauncherStop, match="source_drift"):
        launcher.verify(v2_prepared.root)


@pytest.mark.parametrize("schema", ["target-acceptance-runtime/v1", "target-acceptance-runtime/v3"])
def test_matching_runtime_copies_cannot_downgrade_v2(v2_prepared, schema):
    runtime = deepcopy(v2_prepared.checked["runtime"])
    runtime["schema"] = schema
    for relative in ("control/runtime.json", "spend/runtime.json"):
        put(v2_prepared.root / relative, runtime)
    with pytest.raises(launcher.LauncherStop):
        launcher.verify(v2_prepared.root)


def test_rehashing_mutable_descriptor_cannot_reauthorize_anchor_budget(v2_prepared):
    value = v2_prepared
    approved = manifest_for(value)
    budget = deepcopy(value.spec["anchor_budget"])
    budget["model_attempt_limit"] = 19
    request = anchor_request(value.spec["request"], budget)
    runtime = deepcopy(value.checked["runtime"])
    for name, data in (("control/anchor_budget.json", budget), ("control/request.json", request)):
        put(value.root / name, data)
        runtime["files"][name] = launcher.digest((value.root / name).read_bytes())
    for name in ("control/runtime.json", "spend/runtime.json"):
        put(value.root / name, runtime)
    checked = launcher.verify(value.root)
    with pytest.raises(launcher.LauncherStop):
        launcher.qualify_manifest(core, checked, approved)


@pytest.mark.parametrize("attack", ["v1_manifest", "budget_limit", "budget_scope", "budget_policy", "request", "source"])
def test_manifest_must_match_prepared_v2_authority(v2_prepared, attack):
    manifest = manifest_for(v2_prepared)
    if attack == "v1_manifest":
        manifest["schema"] = "target-run-spending/v1"
        del manifest["anchor_budget"]
    elif attack == "budget_limit":
        manifest["anchor_budget"]["model_attempt_limit"] = 19
    elif attack == "budget_scope":
        manifest["anchor_budget"]["scope_id"] = "other-scope"
    elif attack == "budget_policy":
        manifest["anchor_budget"]["source_policy_sha256"] = core.hash_payload("other-policy")
    elif attack == "request":
        changed = deepcopy(v2_prepared.checked["request"])
        changed["prompt"] = "Another question"
        manifest["request_sha256"] = core.hash_payload(changed)
    else:
        manifest["source_files"] = {**manifest["source_files"], "app/unapproved.py": core.hash_payload("source")}
        manifest["source_sha256"] = core.hash_payload(manifest["source_files"])
    # All variants are legal core manifests; rejection must occur at the
    # launcher/preparation agreement boundary, not malformed fixture setup.
    core.validate_manifest(manifest)
    with pytest.raises(launcher.LauncherStop):
        launcher.qualify_manifest(core, v2_prepared.checked, manifest)


def test_v1_runtime_cannot_take_v2_authorization(prepared, tmp_path):
    value = candidate(prepared, tmp_path)
    manifest = legacy.manifest_for(prepared)
    manifest.update(schema="target-run-spending/v2", anchor_budget=value.spec["anchor_budget"])
    core.validate_manifest(manifest)
    with pytest.raises(launcher.LauncherStop):
        launcher.qualify_manifest(core, prepared.checked, manifest)


@pytest.mark.parametrize("followup_routes", [[], ["search"], ["scrape"], ["search", "scrape"]])
def test_initial_closed_routes_allow_followup_subset(prepared, tmp_path, followup_routes):
    value = prepare_anchor(candidate(prepared, tmp_path, followup_route_ids=followup_routes))
    manifest = manifest_for(value)
    assert launcher.qualify_manifest(core, value.checked, manifest) == core.validate_manifest(manifest)


@pytest.mark.parametrize("attack", ["duplicate_model", "duplicate_search", "missing_scrape",
                                    "unmapped_catalog", "unallowlisted_catalog"])
def test_closed_route_profile_rejects_extra_or_unmapped_authority(prepared, tmp_path, attack):
    changes = {"catalog_route_ids": ["catalog"]} if attack == "unmapped_catalog" else {}
    if attack == "missing_scrape":
        changes["followup_route_ids"] = ["search"]
    value = prepare_anchor(candidate(prepared, tmp_path, **changes))
    manifest = manifest_for(value)
    routes = manifest["routes"]
    if attack.startswith("duplicate_"):
        routes["extra"] = deepcopy(routes[attack.removeprefix("duplicate_")])
    elif attack == "missing_scrape":
        del routes["scrape"]
    else:
        routes["catalog"] = {**deepcopy(routes["search"]), "kind": "catalog_lookup",
            "endpoint": "https://synthetic.invalid/catalog", "catalog_contract": {
                "provider_id": "synthetic", "operation_id": "lookup",
                **{key: core.hash_payload(key) for key in (
                    "catalog_sha256", "request_schema_sha256", "response_bound_sha256", "retry_policy_sha256")},
            }}
    manifest["routes_sha256"] = core.hash_payload(routes)
    if not attack.startswith("duplicate_"):
        core.validate_manifest(manifest)
    with pytest.raises((launcher.LauncherStop, core.SpendingStop)) as error:
        launcher.qualify_manifest(core, value.checked, manifest)
    if attack in {"unmapped_catalog", "unallowlisted_catalog"}:
        assert error.value.code == "unsupported_route"


def test_qualification_calls_real_core_manifest_validation(v2_prepared, monkeypatch):
    calls = []
    validate = core.validate_manifest

    def observed(manifest):
        calls.append(manifest["schema"])
        return validate(manifest)

    monkeypatch.setattr(core, "validate_manifest", observed)
    manifest = manifest_for(v2_prepared)
    assert launcher.qualify_manifest(core, v2_prepared.checked, manifest) == manifest
    assert calls == ["target-run-spending/v2"]


@pytest.mark.parametrize("relative", ["control/request.json", "control/anchor_budget.json"])
def test_child_control_tamper_denies_before_core_or_execution_imports(v2_prepared, tmp_path, monkeypatch, relative):
    _, binding = authorize(v2_prepared, tmp_path)
    with core.run_lock(binding):
        binding = core.bind_pipeline(binding, "pipe-synthetic", v2_prepared.checked["request"])
        core.activate_binding(binding)
        child_environment(v2_prepared, binding, monkeypatch)
        argv = legacy.child_args(v2_prepared)
        path = v2_prepared.root / relative
        put(path, path.read_bytes() + b"\n")
        for name in ("load_core", "setup_execution"):
            monkeypatch.setattr(launcher, name, lambda *a, **kw: pytest.fail("imports reached after control tamper"))
        monkeypatch.setattr(launcher.runpy, "run_path", lambda *a, **kw: pytest.fail("script reached after control tamper"))
        with pytest.raises(launcher.LauncherStop, match="source_drift"):
            launcher.child(argv)
        # No core call follows tampering: source validation rejects the fixed
        # control bytes before the child can rewrite argv or load execution.
        assert sys.argv == ["before-child"]


@pytest.mark.parametrize("gate", ["validate_bound_request", "preflight_anchor_profile"])
def test_child_core_veto_precedes_execution_imports(v2_prepared, tmp_path, monkeypatch, gate):
    _, binding = authorize(v2_prepared, tmp_path)
    with core.run_lock(binding):
        binding = core.bind_pipeline(binding, "pipe-synthetic", v2_prepared.checked["request"])
        core.activate_binding(binding)
        child_environment(v2_prepared, binding, monkeypatch)
        events = []
        activate = core.activate_binding

        def activation(bound):
            result = activate(bound)
            events.append("activate")
            return result

        def veto(*args, **kwargs):
            assert core.current_binding()["participant_id"] == "launcher-child"
            events.append(gate)
            raise core.SpendingStop("stage_profile_oversize" if gate == "preflight_anchor_profile" else "binding_conflict")

        monkeypatch.setattr(core, "activate_binding", activation)
        monkeypatch.setattr(core, gate, veto)
        monkeypatch.setattr(launcher, "setup_execution", lambda *a, **kw: pytest.fail("execution imports before veto"))
        monkeypatch.setattr(launcher.runpy, "run_path", lambda *a, **kw: pytest.fail("script before veto"))
        with pytest.raises(core.SpendingStop):
            launcher.child(legacy.child_args(v2_prepared))
        assert events == ["activate", gate]
        assert core.summary(binding)["attempt_count"] == 0
        assert sys.argv == ["before-child"]


@pytest.mark.parametrize("dimension,code", [("model_attempt_limit", "stage_model_attempts_exhausted"),
                                           ("token_envelope_limit", "stage_tokens_exhausted")])
def test_scoped_child_admits_fake_http_only_after_retained_debit(prepared, tmp_path, monkeypatch, dimension, code):
    """Real authorization, registered child, scope, preflight and dispatch.

    Setup/script spies do not stand in for an SDK or deployed interpreter.
    Both attempts cross dispatch; only the admitted one reaches fake HTTP.
    """
    value = prepare_anchor(candidate(prepared, tmp_path, **{dimension: 1 if dimension == "model_attempt_limit" else 200}))
    manifest, binding = authorize(value, tmp_path)
    events, posts = [], []
    with core.run_lock(binding):
        binding = core.bind_pipeline(binding, "pipe-synthetic", value.checked["request"])
        core.activate_binding(binding)
        with core.operation("research", "launcher-root"):
            binding = core.begin_anchor_scope(binding, session=session())["binding"]
        child = child_environment(value, binding, monkeypatch)
        assert child["active_scope_id"] == value.spec["anchor_budget"]["scope_id"]
        assert child["admission_epoch"] == binding["admission_epoch"]
        originals = {name: getattr(core, name) for name in ("activate_binding", "validate_bound_request", "preflight_anchor_profile")}

        def watch(name):
            def observed(*args, **kwargs):
                result = originals[name](*args, **kwargs)
                events.append(name)
                return result
            return observed

        for name in originals:
            monkeypatch.setattr(core, name, watch(name))

        def setup(*args, **kwargs):
            assert events == ["activate_binding", "validate_bound_request", "preflight_anchor_profile"]
            assert core.check_context() == child
            events.append("setup_execution")

        def handler(request):
            posts.append(request.url.path)
            assert request.method == "POST"
            assert core.scope_summary(child)["retained"]["model_attempts"] == 1
            return httpx.Response(200, json={"choices": [{"message": {"content": "synthetic"}}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1}})

        run_path = launcher.runpy.run_path
        def script(path, run_name):
            assert events[-1] == "setup_execution"
            events.append("script")
            assert core.check_context() == child
            assert Path(path) == value.root / launcher.CHILD
            route = manifest["routes"]["model"]
            payload = {"model": route["model"], "messages": [{"role": "user", "content": "synthetic"}], "max_tokens": 100}
            request = {"endpoint": route["endpoint"], "model": route["model"], "input_tokens": 100,
                "max_output_tokens": 100, "tool_units": 0, "payload_sha256": core.hash_payload(payload)}
            with httpx.Client(transport=httpx.MockTransport(handler), trust_env=False, follow_redirects=False) as client:
                def send():
                    # Inspect through a new DB connection before client.post.
                    retained = core.scope_summary(child)["retained"]
                    assert retained == {"model_attempts": 1, "token_envelope_units": 200,
                        "catalog_attempts": 0, "followup_attempts": 0, "reserved_max_microusd": 300}
                    events.append("post")
                    return client.post(route["endpoint"] + "/chat/completions", json=payload)

                def usage(response):
                    reported = response.json()["usage"]
                    return {"kind": "provider_reported", "input_tokens": reported["prompt_tokens"],
                            "output_tokens": reported["completion_tokens"]}

                response = core.dispatch("model", request, send, usage=usage)
                assert response.json()["choices"][0]["message"]["content"] == "synthetic"
                before = core.scope_summary(child)["retained"]
                assert before["token_envelope_units"] == 200  # small reported usage never refunds the envelope
                with pytest.raises(core.SpendingStop, match=code):
                    core.dispatch("model", request, send, usage=usage)
                assert core.scope_summary(child)["retained"] == before
            return run_path(path, run_name=run_name)

        monkeypatch.setattr(launcher, "setup_execution", setup)
        monkeypatch.setattr(launcher.runpy, "run_path", script)
        argv = legacy.child_args(value)
        launcher.child(argv)
        assert events == ["activate_binding", "validate_bound_request", "preflight_anchor_profile", "setup_execution", "script", "post"]
        assert posts == ["/v1/chat/completions"]
        assert sys.argv == argv[1:]
        assert core.summary(binding)["attempt_count"] == 1
        assert core.summary(binding)["stop_code"] == code
        assert core.scope_summary(binding)["retained"]["model_attempts"] == 1
