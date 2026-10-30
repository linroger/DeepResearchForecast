"""Real pure-anchor -> native compiler/seal/observation acceptance; offline only."""
from copy import deepcopy
import hashlib
import importlib
import importlib.util
import json
from pathlib import Path, PurePosixPath
import sys
import tarfile
from types import SimpleNamespace

import pytest

from app.config import Config
from app.services import world_anchor as host
from app.services.official_data import bind_simulation_research, bridge_module
from app.services.simulation_manager import SimulationManager
from app.services.world_simulation import compiler, service
from app.services.world_simulation.artifacts import load_inputs, seal_inputs
from app.services.world_simulation.contracts import WorldError, canonical_json, initial_snapshot
from app.services.world_simulation.observations import build_observation
from tests import test_world_anchor as anchor_cases, test_world_compiler as world_cases

pytestmark = pytest.mark.guarded_runner
wa = bridge_module("world_anchor")


@pytest.fixture(autouse=True)
def _private_roots(tmp_path, monkeypatch):
    monkeypatch.setattr(SimulationManager, "SIMULATION_DATA_DIR", str(tmp_path / "simulations"))
    monkeypatch.setattr(Config, "OASIS_SIMULATION_DATA_DIR", str(tmp_path / "simulations"))
    monkeypatch.setattr(Config, "PIPELINE_DATA_DIR", str(tmp_path / "pipelines"))


def _write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(anchor_cases.dump(value))


def _fixture(tmp_path, *, hidden="PRIVATE_SELF_INFERENCE", parameter_targets=None, producer="secondary_report",
             extra_parameters=()):
    """Actual source index, distinct scripted review, completion and host loader."""
    tmp_path.mkdir(parents=True, exist_ok=True)
    report = world_cases.REPORT
    bundle = world_cases.source_bundle()
    bundle["actors"][0]["goals"] = [hidden]
    page = "A secondary report forecasts global cybersecurity spending of 247.5 billion USD for 2026."
    for item in extra_parameters:
        page += " Synthetic parameter statement: " + json.dumps(item, sort_keys=True) + "."
    f = anchor_cases.make_fixture(tmp_path / "source", page=page)
    contract = deepcopy(f["requirements"]["contract"])
    contract["terms"][0]["consumers"] = [anchor_cases.consumer("world-v1", "diagnostic", "target", "definition")]
    targets = parameter_targets or [("baseline", "/initialState/metrics/baseline/value")]
    contract["terms"][1]["consumers"] = [anchor_cases.consumer("world-v1", "compiler_parameter", obj, field)
                                          for obj, field in targets]
    for item in extra_parameters:
        identity = deepcopy(contract["terms"][1]["identity"])
        identity["metric_id"] = item["metric"]
        if "unit" in item:
            identity["unit"] = deepcopy(item["unit"])
        contract["terms"].append({**deepcopy(contract["terms"][1]), "origin_pointer": f"/terms/{len(contract['terms'])}",
            "kind": "mechanism_parameter", "identity": identity, "value_type": item.get("value_type", "number"),
            "consumers": [anchor_cases.consumer("world-v1", item.get("role", "compiler_parameter"), item["object"], item["target"])]})
    contract["actors"] = [{"actor_ref": row["actor_id"], "registry_artifact_id": "contract",
        "registry_pointer": f"/native_actor_registry/{i}", "statements": [], "authority": [], "plans": [], "red_lines": []}
        for i, row in enumerate(bundle["actors"])]
    authority = {"settlement": contract["settlement"]["identity"], "terms": contract["terms"],
                 "native_actor_registry": bundle["actors"], **{key: contract[key] for key in (*wa.SPEC_FIELDS, "aliases")}}
    raw = anchor_cases.dump(authority)
    (f["root"] / "contract.json").write_bytes(raw)
    next(row for row in f["manifest"]["artifacts"] if row["artifact_id"] == "contract").update(
        sha256=anchor_cases.digest(raw), bytes=len(raw))
    contract["authority_artifact_hash"] = anchor_cases.digest(raw)
    f["requirements"] = wa.requirements_from_contract(contract, scope=f["scope"])
    f["policy"]["consumer_rules"] = [{**row, "adapter_version": compiler.ANCHOR_ADAPTER_VERSION, "template_versions": []}
        for term in contract["terms"] for row in term["consumers"]]
    f["index"] = wa.index_snapshot(f["root"], f["manifest"], expected_manifest_hash=wa.anchor_hash(f["manifest"]),
        expected_scope=f["scope"], requirements=f["requirements"], policy=f["policy"])
    proposal, review = anchor_cases.review_fixture(f, producer=producer)
    prototype, review_row = deepcopy(proposal["rows"][0]), deepcopy(review["decisions"][0])
    for index, item in enumerate(extra_parameters):
        requirement = next(row for row in f["requirements"]["requirements"] if row["origin_pointer"] == f"/terms/{index + 2}")
        row = deepcopy(prototype)
        row.update(proposal_id=f"parameter-{index}", requirement_ids=[requirement["requirement_id"]],
                   identity=requirement["identity"], value={"kind": item.get("value_type", "number"), "value": item["value"]},
                   source_value={"kind": item.get("value_type", "number"), "value": item["value"]})
        proposal["rows"].append(row)
        review["decisions"].append({**deepcopy(review_row), "proposal_id": row["proposal_id"]})
    review["proposal_hash"] = wa.anchor_hash(proposal)
    receipts = anchor_cases.receipt_fixture(f, proposal, review)
    f["index"] = wa.admit_reviewed_evidence(f["index"], proposal, review, requirements=f["requirements"],
                                           policy=f["policy"], receipts=receipts)
    pack = anchor_cases.build_pack(f)
    handoff = tmp_path / "pipelines" / "run-test" / "handoff"
    publication = bridge_module("world_anchor_publication").publish_completion(handoff, pack,
        requirements=f["requirements"], index=f["index"], policy=f["policy"], receipts=[receipts])
    (handoff / "research_report.md").write_text(report)
    _write(handoff / "actors.json", bundle)
    _write(handoff / "sources.json", [])
    (handoff / "actor_dossier.md").write_text("Synthetic native actor source registry.")
    context = host.load_research_anchor(handoff, expected_manifest_sha256=publication["manifest_sha256"])
    source_holder = SimulationManager().create_simulation("source-fixture", "source-graph", simulation_engine="world-v1")
    bind_simulation_research(source_holder.simulation_id, handoff, pipeline_id="run-test")
    context = host.bind_context_sources(context, simulation_id=source_holder.simulation_id)
    def basis(obj="baseline", target="/initialState/metrics/baseline/value"):
        requirement = next(row for row in f["requirements"]["requirements"] if any(
            consumer["object_id"] == obj and consumer["field"] == target for consumer in row["consumers"]))
        binding = next(row for row in pack["bindings"] if row["requirement_id"] == requirement["requirement_id"])
        return {"kind": "anchor_evidence", "refs": [{"pack_hash": context.pack_hash,
            "requirement_id": binding["requirement_id"], "binding_id": binding["binding_id"],
            "observation_id": binding["observation_ids"][0], "field": "value", "target": target,
            "target_object_id": obj}]}

    raw_spec = world_cases.proposal()
    raw_spec["actors"][0].pop("objectives")  # Existing derived dossier channel must not become strict actor knowledge.
    raw_spec["periods"] = [{"start": "2026-10-28T00:00:00Z", "end": "2026-10-29T00:00:00Z"},
                           {"start": "2026-10-29T00:00:00Z", "end": "2026-10-30T00:00:00Z"}]
    raw_spec["initialState"]["metrics"]["baseline"] = {"kind": "quantity", "unit": "usd_billion", "value": "247.5",
        "visibility": {"kind": "public"}, "basis": basis(), "structuralBasis": deepcopy(world_cases.ASSUMPTION)}
    return SimpleNamespace(context=context, report=report, bundle=bundle, raw=raw_spec, basis=basis,
                           handoff=handoff, publication=publication)


def _compile(f, raw=None, **kwargs):
    return compiler.compile_world_spec(f.raw if raw is None else raw, simulation_id="sim_anchor", generation_id="world1",
        research_report=f.report, research_generation_id="final-report-consumed-hash", research_engine="v3",
        actor_bundle=f.bundle, anchor_context=f.context, **kwargs)


def _public_prepare(f, tmp_path, monkeypatch):
    sims = tmp_path / "simulations"
    monkeypatch.setattr(SimulationManager, "SIMULATION_DATA_DIR", str(sims))
    monkeypatch.setattr(Config, "OASIS_SIMULATION_DATA_DIR", str(sims))
    monkeypatch.setattr(Config, "PIPELINE_DATA_DIR", str(tmp_path / "pipelines"))
    manager = SimulationManager()
    state = manager.create_simulation("project-fixture", "graph-fixture", simulation_engine="world-v1")
    bind_simulation_research(state.simulation_id, f.handoff, pipeline_id="run-test")
    state = manager.prepare_world_simulation(state.simulation_id, raw_spec=f.raw, research_report=f.report,
        research_generation_id="final-report-consumed-hash", research_engine="v3", actor_bundle=f.bundle,
        anchor_context=f.context)
    directory = sims / state.simulation_id
    return manager, state, directory


def test_real_anchor_value_and_two_generation_schemes_reach_compiler(tmp_path):
    f = _fixture(tmp_path)
    before = deepcopy(f.raw)
    spec = _compile(f)
    assert f.raw == before
    assert spec["initialState"]["metrics"]["baseline"]["value"] == "247.5"
    binding = spec["sourceBindings"]["worldAnchor"]
    assert binding["researchGenerationId"] == "final-report-consumed-hash"
    assert binding["anchorResearchGenerationId"] == f.context.pack["scope"]["research_generation_id"]
    assert binding["researchGenerationId"] != binding["anchorResearchGenerationId"]
    assert binding["candidateHash"] == wa.anchor_hash(f.raw)
    assert binding["pin"]["actor_join_sha256"] is None
    assert binding["consumedSources"]["reportSha256"] == hashlib.sha256(f.report.encode()).hexdigest()


@pytest.mark.parametrize("change", ["target", "object", "field", "observation", "value", "unit", "legacy_claim", "structure"])
def test_parameter_forgery_or_unadmitted_structure_denies(tmp_path, change):
    f = _fixture(tmp_path)
    row = f.raw["initialState"]["metrics"]["baseline"]
    ref = row["basis"]["refs"][0]
    if change == "target": ref["target"] = "/initialState/metrics/other/value"
    elif change == "object": ref["target_object_id"] = "other"
    elif change == "field": ref["field"] = "range.low"
    elif change == "observation": ref["observation_id"] = "observation_foreign"
    elif change == "value": row["value"] = "248.5"
    elif change == "unit": row["unit"] = "usd_million"
    elif change == "legacy_claim": row["basis"] = world_cases.claim_basis()
    else: row.pop("structuralBasis")
    with pytest.raises(WorldError):
        _compile(f)


def test_caller_bindings_discarded_and_prepared_candidate_cannot_be_reused_for_changed_structure(tmp_path):
    f = _fixture(tmp_path)
    f.raw["sourceBindings"] = {"worldAnchor": {"packHash": "forged"}}
    spec = _compile(f)
    assert spec["sourceBindings"]["worldAnchor"]["packHash"] == f.context.pack_hash
    changed = deepcopy(spec)
    changed["actionCatalog"][0]["description"] = "Unrelated changed action"
    with pytest.raises(WorldError, match="recompiled"):
        seal_inputs(tmp_path / "changed", changed, anchor_context=f.context)
    # Even an exact JSON copy with copied self-hashes is not compiler-issued.
    with pytest.raises(WorldError, match="Caller JSON"):
        seal_inputs(tmp_path / "json-copy", json.loads(canonical_json(spec)), anchor_context=f.context)


def test_public_prepare_and_fresh_loader_reconstruct_real_anchor_without_context_stub(tmp_path, monkeypatch):
    f = _fixture(tmp_path)
    manager, state, directory = _public_prepare(f, tmp_path, monkeypatch)
    spec, manifest = load_inputs(directory, simulation_id=state.simulation_id,
        expected_manifest_sha256=state.world_input_manifest_sha256)
    restored = host.load_runtime_anchor({"simulation_id": state.simulation_id, "world_anchor": manifest["worldAnchor"]}, directory)
    assert restored.pack_hash == f.context.pack_hash and restored.join is None
    assert manifest["worldAnchorPreparation"]["sha256"] == spec["sourceBindings"]["worldAnchor"]["preparationSha256"]
    assert (directory / "world_anchor_preparation.json").is_file()
    fresh_manager = SimulationManager()
    fresh_manager.validate_prepared_simulation_config(state.simulation_id)
    assert canonical_json(spec) == canonical_json(load_inputs(directory, anchor_context=restored)[0])


def test_enabled_actor_payload_rejects_old_self_inference_and_private_hash_channels(tmp_path):
    f = _fixture(tmp_path / "first", hidden="PRIVATE_SELF_INFERENCE_A")
    g = _fixture(tmp_path / "second", hidden="PRIVATE_SELF_INFERENCE_B")
    first, second = _compile(f), _compile(g)
    a = build_observation(first, initial_snapshot(first), "a", 1)
    b = build_observation(second, initial_snapshot(second), "a", 1)
    assert canonical_json(a) == canonical_json(b)
    text = canonical_json(a)
    assert "247.5" in text and "third_party_forecast" in text
    assert "PRIVATE_SELF" not in text and "Acme seeks reliable" not in text
    assert f.context.pack_hash not in text and "preparedParametersHash" not in text
    assert a["privateState"]["beliefs"] == [] and a["actor"]["objectives"] == []


def test_off_none_compile_seal_and_observation_bytes_are_identical(tmp_path, monkeypatch):
    monkeypatch.setattr(host, "validate_anchor_context", lambda *a, **k: pytest.fail("off invoked anchor API"))
    raw, bundle = world_cases.proposal(), world_cases.source_bundle()
    options = dict(simulation_id="sim", generation_id="world1", research_report=world_cases.REPORT,
                   research_generation_id="research1", research_engine="v3", actor_bundle=bundle)
    implicit = compiler.compile_world_spec(raw, **options)
    explicit = compiler.compile_world_spec(raw, anchor_context=None, **options)
    assert canonical_json(implicit) == canonical_json(explicit)
    assert "worldAnchor" not in canonical_json(implicit)
    assert canonical_json(build_observation(implicit, initial_snapshot(implicit), "a", 1)) == canonical_json(
        build_observation(explicit, initial_snapshot(explicit), "a", 1))
    seal_inputs(tmp_path / "implicit", implicit)
    seal_inputs(tmp_path / "explicit", explicit, anchor_context=None)
    for name in ("world_spec.json", "world_input_manifest.json"):
        assert (tmp_path / "implicit" / name).read_bytes() == (tmp_path / "explicit" / name).read_bytes()


def _accounts(raw):
    raw["initialState"]["accounts"] = {
        name: {"ownerId": owner, "unit": "usd_billion", "balance": balance,
               "visibility": {"kind": "public"}, "basis": deepcopy(world_cases.ASSUMPTION)}
        for name, owner, balance in (("cash", "a", "1000"), ("sink", "external", "0"))}
    raw["actors"][0]["controlledAccounts"] = ["cash"]


def _investment(f):
    _accounts(f.raw)
    f.raw["actors"][0]["capabilities"].append("boost")
    f.raw["actionCatalog"].append({"templateId": "boost", "kind": "investment", "actorIds": ["a"],
        "description": "Synthetic investment structure", "visibility": {"kind": "public"}, "inputs": {},
        "parameters": {"fromAccount": "cash", "toAccount": "sink", "cost": "0", "durationDays": "0",
                       "targetMetric": "baseline", "delta": "2"},
        "basis": f.basis("boost", "/actionCatalog/1/parameters/delta"),
        "structuralBasis": deepcopy(world_cases.ASSUMPTION)})


class _Policy:
    external = False

    def __init__(self, act=False):
        self.act, self.observations = act, []

    def decide(self, observation):
        self.observations.append(deepcopy(observation))
        intents = [{"templateId": "boost"}] if self.act and observation["round"] == 1 else []
        return {"actorId": observation["actorId"], "observationId": observation["observationId"],
                "intents": intents, "rationale": "Synthetic offline action."}


def test_actual_controller_action_store_replay_and_later_actor_view(tmp_path, monkeypatch):
    from app.services.world_simulation.controller import run_to_horizon
    from app.services.world_simulation.store import WorldStore

    f = _fixture(tmp_path, extra_parameters=[{"object": "boost", "target": "/actionCatalog/1/parameters/delta",
                                             "metric": "spending_delta", "value": "2"}])
    _investment(f)
    _, state, directory = _public_prepare(f, tmp_path, monkeypatch)
    spec, _ = load_inputs(directory)
    policy = _Policy(act=True)
    with WorldStore(directory / "world.sqlite3", spec) as store:
        fence = store.acquire_writer("anchor-case")
        final = run_to_horizon(store, policy, fence)
        assert final["metrics"]["baseline"]["value"] == "249.5"
    assert policy.observations[0]["world"]["metrics"]["baseline"]["value"] == "247.5"
    assert policy.observations[1]["world"]["metrics"]["baseline"]["value"] == "249.5"
    assert policy.observations[1]["world"]["metrics"]["baseline"]["evidenceType"] == "simulated"
    assert f.context.pack_hash not in canonical_json(policy.observations)
    with WorldStore(directory / "world.sqlite3", spec, read_only=True) as store:
        assert store.head()["metrics"]["baseline"]["value"] == "249.5"


def test_actual_anchored_flow_uses_per_day_units_and_retains_record_provenance(tmp_path, monkeypatch):
    from app.services.world_simulation.controller import run_to_horizon
    from app.services.world_simulation.store import WorldStore

    unit = {**anchor_cases.unit(), "id": "usd_billion_per_day", "dimension": "currency/time"}
    f = _fixture(tmp_path, extra_parameters=[{"object": "flow1", "target": "/flows/0/ratePerDay",
        "metric": "cash_flow", "value": "2", "unit": unit}])
    _accounts(f.raw)
    f.raw["flows"] = [{"flowId": "flow1", "sourceAccount": "cash", "targetAccount": "sink", "ratePerDay": "2",
        "visibility": {"kind": "public"}, "basis": f.basis("flow1", "/flows/0/ratePerDay"),
        "structuralBasis": deepcopy(world_cases.ASSUMPTION)}]
    _, _, directory = _public_prepare(f, tmp_path, monkeypatch)
    spec, _ = load_inputs(directory)
    with WorldStore(directory / "world.sqlite3", spec) as store:
        final = run_to_horizon(store, _Policy(), store.acquire_writer("flow-case"))
        assert final["accounts"]["cash"]["balance"] == "996"
        assert final["accounts"]["sink"]["balance"] == "4"
    assert spec["flows"][0]["basis"]["kind"] == "anchor_evidence"


def test_prepared_candidate_binds_nonparameter_structure_and_index_order(tmp_path):
    f = _fixture(tmp_path, extra_parameters=[{"object": "boost", "target": "/actionCatalog/1/parameters/delta",
                                             "metric": "spending_delta", "value": "2"}])
    _investment(f)
    spec = _compile(f)
    changed = deepcopy(spec)
    changed["actionCatalog"].reverse()
    with pytest.raises(WorldError):
        seal_inputs(tmp_path / "reordered", changed, anchor_context=f.context)
    newer = deepcopy(f.raw)
    newer["actionCatalog"][1]["parameters"]["cost"] = "1"
    fresh = _compile(f, newer)
    assert fresh["sourceBindings"]["worldAnchor"]["candidateHash"] != spec["sourceBindings"]["worldAnchor"]["candidateHash"]
    assert fresh["sourceBindings"]["worldAnchor"]["preparedParametersHash"] != spec["sourceBindings"]["worldAnchor"]["preparedParametersHash"]


@pytest.mark.parametrize("value,value_type", [(True, "boolean"), ("announced", "text")])
def test_nonnumeric_rules_keep_exact_types(tmp_path, value, value_type):
    f = _fixture(tmp_path, extra_parameters=[{"object": "rule1", "target": "/initialState/rules/rule1/value",
        "metric": "rule_state", "value": value, "value_type": value_type}])
    f.raw["initialState"]["rules"]["rule1"] = {"value": value, "visibility": {"kind": "public"},
        "basis": f.basis("rule1", "/initialState/rules/rule1/value"), "structuralBasis": deepcopy(world_cases.ASSUMPTION)}
    spec = _compile(f)
    assert type(spec["initialState"]["rules"]["rule1"]["value"]) is type(value)
    assert spec["initialState"]["rules"]["rule1"]["value"] == value


def test_native_modeler_builds_anchor_messages_and_public_service_seals_real_candidate(tmp_path, monkeypatch):
    from app.services.world_simulation import policy as policy_module
    from tests.test_world_modeler_repair import Scripted, policy_spec

    f = _fixture(tmp_path)
    transport = Scripted(f.raw)
    monkeypatch.setattr(policy_module, "StrictHTTPModeler", lambda _: transport)
    prepared = service.WorldSimulationService.prepare_model("sim_modeler", raw_spec=None,
        root=tmp_path / "simulations", research_report=f.report, research_generation_id="final-report-consumed-hash",
        research_engine="v3", actor_bundle=f.bundle, anchor_context=f.context, policy_spec=policy_spec())
    assert len(transport.requests) == 1
    body = json.loads(transport.requests[0][1]["content"])
    assert body["worldAnchor"]["pack_hash"] == f.context.pack_hash
    assert body["worldAnchorRequirements"] and "structuralBasis" in transport.requests[0][0]["content"]
    assert prepared["spec"]["initialState"]["metrics"]["baseline"]["value"] == "247.5"
    spec, _ = load_inputs(tmp_path / "simulations/sim_modeler", anchor_context=f.context,
                         expected_manifest_sha256=prepared["manifest_sha256"])
    assert spec["sourceBindings"]["worldAnchor"]["packHash"] == f.context.pack_hash


def test_complete_actual_policy_messages_and_review_remain_private_invariant(tmp_path):
    import httpx
    from openai import OpenAI
    from app.services.world_simulation.policy import StrictHTTPPolicy
    from app.services.world_simulation.review import MODE_V3
    from tests.test_world_modeler_repair import POLICY

    worlds = [_fixture(tmp_path / suffix, hidden="PRIVATE_" + suffix) for suffix in ("one", "two")]
    requests = []
    for f in worlds:
        f.raw["policy"] = {**deepcopy(POLICY), "decisionReview": MODE_V3}
        spec = _compile(f)
        observation = build_observation(spec, initial_snapshot(spec), "a", 1)
        http = httpx.Client(transport=httpx.MockTransport(lambda _: pytest.fail("request inspection sent HTTP")),
                            follow_redirects=False, trust_env=False)
        sdk = OpenAI(api_key="synthetic-no-provider-key", base_url=POLICY["baseUrl"], http_client=http, max_retries=0)
        try:
            policy = StrictHTTPPolicy(spec, client=sdk)
            candidate = {"actorId": "a", "observationId": observation["observationId"], "intents": []}
            requests.append([policy._request(observation)[0],
                             policy._request(observation, feedback={"code": "invalid_intent", "message": "Synthetic repair."})[0],
                             policy._request(observation, review=candidate)[0]])
        finally:
            policy.close()
            sdk.close()
    assert requests[0] == requests[1]
    text = json.dumps(requests[0], ensure_ascii=False)
    assert "247.5" in text and "PRIVATE_" not in text
    assert all(f.context.pack_hash not in text for f in worlds)


@pytest.mark.parametrize("value", [False, True])
@pytest.mark.parametrize("boundary", ["seal", "restore"])
def test_postcompile_boolean_cannot_be_replaced_by_equal_integer(tmp_path, value, boundary):
    f = _fixture(tmp_path, extra_parameters=[{"object": "rule1", "target": "/initialState/rules/rule1/value",
        "metric": "rule_state", "value": value, "value_type": "boolean"}])
    f.raw["initialState"]["rules"]["rule1"] = {"value": value, "visibility": {"kind": "public"},
        "basis": f.basis("rule1", "/initialState/rules/rule1/value"), "structuralBasis": deepcopy(world_cases.ASSUMPTION)}
    spec = _compile(f)
    changed = deepcopy(spec)
    changed["initialState"]["rules"]["rule1"]["value"] = int(value)
    with pytest.raises(WorldError):
        if boundary == "seal":
            seal_inputs(tmp_path / "changed", changed, anchor_context=f.context)
        else:
            compiler.restore_anchor_preparation(dict(changed), compiler.anchor_preparation_bytes(spec), f.context)


@pytest.mark.parametrize("kind,fixed", [("string", True), ("decimal", True)])
def test_anchor_currency_bounds_cannot_admit_string_length_or_unused_input(tmp_path, kind, fixed):
    f = _fixture(tmp_path, extra_parameters=[{"object": "pay", "target": "/actionCatalog/1/inputs/amount/max",
                                             "metric": "amount_limit", "value": "3"}])
    _accounts(f.raw)
    f.raw["actors"][0]["capabilities"].append("pay")
    parameters = {"fromAccount": "cash", "toAccount": "sink"}
    if fixed:
        parameters["amount"] = "1"
    f.raw["actionCatalog"].append({"templateId": "pay", "kind": "transfer", "actorIds": ["a"],
        "description": "Synthetic transfer", "parameters": parameters,
        "inputs": {"amount": {"type": kind, "max": "3", "required": True}},
        "visibility": {"kind": "public"}, "basis": f.basis("pay", "/actionCatalog/1/inputs/amount/max"),
        "structuralBasis": deepcopy(world_cases.ASSUMPTION)})
    with pytest.raises(WorldError, match="mapping|input"):
        _compile(f)


def test_modified_report_cannot_use_an_unchanged_external_research_binding(tmp_path, monkeypatch):
    f = _fixture(tmp_path)
    f.report += " Unrelated changed report text, with all earlier claim spans preserved."
    with pytest.raises((WorldError, host.WorldAnchorIntegrationError)):
        _public_prepare(f, tmp_path, monkeypatch)


def test_public_native_fork_has_authenticated_child_research_and_fresh_reload(tmp_path, monkeypatch):
    f = _fixture(tmp_path)
    manager, state, directory = _public_prepare(f, tmp_path, monkeypatch)
    originals = {path.name: path.read_bytes() for path in directory.glob("*.json")}
    child = manager.fork_world_simulation(state.simulation_id, seed=17)
    child_dir = Path(manager.SIMULATION_DATA_DIR) / child.simulation_id
    spec, manifest = load_inputs(child_dir)
    assert spec["seed"] == 17 and spec["simulationId"] == child.simulation_id
    assert spec["generationId"] != state.world_generation_id
    assert manifest["worldAnchor"]["pack_hash"] == f.context.pack_hash
    SimulationManager().validate_prepared_simulation_config(child.simulation_id)
    assert {path.name: path.read_bytes() for path in directory.glob("*.json")} == originals


def test_consumed_decimal_amount_bounds_reach_actual_transfer(tmp_path, monkeypatch):
    from app.services.world_simulation.controller import run_to_horizon
    from app.services.world_simulation.store import WorldStore

    f = _fixture(tmp_path, extra_parameters=[{"object": "pay", "target": "/actionCatalog/1/inputs/amount/max",
                                             "metric": "amount_limit", "value": "3"}])
    _accounts(f.raw)
    f.raw["actors"][0]["capabilities"].append("pay")
    f.raw["actionCatalog"].append({"templateId": "pay", "kind": "transfer", "actorIds": ["a"],
        "description": "Synthetic transfer", "parameters": {"fromAccount": "cash", "toAccount": "sink"},
        "inputs": {"amount": {"type": "decimal", "max": "3", "required": True}},
        "visibility": {"kind": "public"}, "basis": f.basis("pay", "/actionCatalog/1/inputs/amount/max"),
        "structuralBasis": deepcopy(world_cases.ASSUMPTION)})
    _, _, directory = _public_prepare(f, tmp_path, monkeypatch)
    spec, _ = load_inputs(directory)

    class Pay(_Policy):
        def decide(self, obs):
            result = super().decide(obs)
            if obs["round"] == 1:
                result["intents"] = [{"templateId": "pay", "parameters": {"amount": "2"}}]
            return result

    policy = Pay()
    with WorldStore(directory / "world.sqlite3", spec) as store:
        final = run_to_horizon(store, policy, store.acquire_writer("pay"))
    assert final["accounts"]["cash"]["balance"] == "998"
    assert final["accounts"]["sink"]["balance"] == "2"
    assert next(o for o in policy.observations[0]["options"] if o["templateId"] == "pay")["inputs"]["amount"]["max"] == "3"


def _beta(raw):
    raw["actors"].append({"actorId": "b", "name": "Beta", "basis": deepcopy(world_cases.ASSUMPTION), "capabilities": []})


def test_recipient_only_response_menu_and_opaque_offer_terms_survive_counter_and_accept(tmp_path):
    from app.services.world_simulation.contracts import validate_decision
    from app.services.world_simulation.kernel import initialize_world, stage_interactions, resolve_round

    f = _fixture(tmp_path)
    _beta(f.raw)
    f.raw["actors"][0]["capabilities"].append("deal")
    fields = ("description", "conditions", "effects", "basis")
    f.raw["actionCatalog"].append({"templateId": "deal", "kind": "agreement", "actorIds": ["a"],
        "description": "Synthetic agreement", "parameters": {"recipientIds": ["b"], "transfers": [],
            "durationDays": "2", "messageDelayDays": "0", "offerTtlDays": "3"},
        "inputs": {name: {"type": "string", "required": True} for name in fields},
        "basis": deepcopy(world_cases.ASSUMPTION), "visibility": {"kind": "public"}})
    f.raw["periods"].append({"start": "2026-10-30T00:00:00Z", "end": "2026-10-31T00:00:00Z"})
    spec = _compile(f)
    initial = initialize_world(spec)
    terms = {name: "original " + name for name in fields}

    def decision(snapshot, aid, round_index, phase, intents):
        obs = build_observation(spec, snapshot, aid, round_index, phase)
        raw = {"actorId": aid, "observationId": obs["observationId"], "intents": intents}
        return obs, validate_decision(spec, raw, aid, obs, phase=phase)

    _, propose = decision(initial, "a", 1, "proposal", [{"templateId": "deal", "operation": "propose", "parameters": terms}])
    b_proposal, wait = decision(initial, "b", 1, "proposal", [])
    assert all(option["templateId"] != "deal" for option in b_proposal["options"])
    staged = stage_interactions(spec, initial, [propose, wait], 1)
    b = build_observation(spec, staged, "b", 1, "response")
    assert b["inbox"][0]["terms"] == terms
    assert "counter" in next(o for o in b["options"] if o["templateId"] == "deal")["operations"]
    offer = b["inbox"][0]
    counter_terms = {name: "counter " + name for name in fields}
    _, counter = decision(staged, "b", 1, "response", [{"templateId": "deal", "operation": "counter",
        "interactionId": offer["interactionId"], "termsVersion": offer["termsVersion"], "parameters": counter_terms}])
    after = resolve_round(spec, initial, [propose, wait, counter], 1)["snapshot"]
    a = build_observation(spec, after, "a", 2, "response")
    assert a["inbox"][0]["terms"] == counter_terms
    stored = after["interactions"][a["inbox"][0]["interactionId"]]
    assert a["inbox"][0]["terms"] == stored["terms"] and a["inbox"][0]["termsVersion"] == stored["termsVersion"]
    _, wa = decision(after, "a", 2, "proposal", [])
    _, wb = decision(after, "b", 2, "proposal", [])
    _, accept = decision(after, "a", 2, "response", [{"templateId": "deal", "operation": "accept",
        "interactionId": stored["interactionId"], "termsVersion": stored["termsVersion"]}])
    final = resolve_round(spec, after, [wa, wb, accept], 2)["snapshot"]
    view = build_observation(spec, final, "a", 3)
    assert any(row["kind"] == "agreement" and row["status"] == "pending" for row in view["world"]["commitments"].values())
    assert all(row["basis"]["kind"] == "simulation_event" for row in view["world"]["commitments"].values())
    assert f.context.pack_hash not in canonical_json(view)


@pytest.mark.parametrize("kind", ["investment", "vote"])
def test_native_generated_commitments_remain_visible(tmp_path, kind):
    from app.services.world_simulation.contracts import validate_decision
    from app.services.world_simulation.kernel import initialize_world, resolve_round

    extra = [{"object": "boost", "target": "/actionCatalog/1/parameters/delta", "metric": "spending_delta", "value": "2"}]
    f = _fixture(tmp_path, extra_parameters=extra if kind == "investment" else ())
    if kind == "investment":
        _investment(f)
        f.raw["actionCatalog"][1]["parameters"]["durationDays"] = "2"
        intent = {"templateId": "boost"}
    else:
        _accounts(f.raw)
        f.raw["actors"][0]["capabilities"].append("vote")
        f.raw["actionCatalog"].append({"templateId": "vote", "kind": "vote", "actorIds": ["a"],
            "description": "Synthetic vote", "parameters": {"motionId": "motion", "weights": {"a": "1"},
                "threshold": "2", "fromAccount": "cash", "toAccount": "sink", "cost": "0"},
            "inputs": {"support": {"type": "boolean", "required": True}},
            "basis": deepcopy(world_cases.ASSUMPTION), "visibility": {"kind": "public"}})
        intent = {"templateId": "vote", "parameters": {"support": True}}
    spec = _compile(f)
    first = initialize_world(spec)
    obs = build_observation(spec, first, "a", 1)
    decision = validate_decision(spec, {"actorId": "a", "observationId": obs["observationId"], "intents": [intent]}, "a", obs, phase="proposal")
    after = resolve_round(spec, first, [decision], 1)["snapshot"]
    visible = build_observation(spec, after, "a", 2)["world"]["commitments"]
    assert len(visible) == 1
    row = next(iter(visible.values()))
    assert row["kind"] == kind and row["status"] == ("voting" if kind == "vote" else "pending")
    assert row["commitmentId"] in after["commitments"] and row["sourceIntentId"]
    assert row["basis"]["kind"] == "simulation_event"


@pytest.fixture(scope="session")
def legacy_world_package(tmp_path_factory):
    repo = Path(__file__).resolve().parents[2]
    archive = repo / ".pytest_cache/private-artifacts/world-v1-baseline-9916b3be.tar"
    expected = "e2e61da08d1e04068541833acaa31660a57a775a9c155b5e9238241213f6648e"
    assert hashlib.sha256(archive.read_bytes()).hexdigest() == expected
    root = tmp_path_factory.mktemp("world-v1-baseline")
    seen, total = set(), 0
    with tarfile.open(archive, "r:") as stream:
        for member in stream:
            relative = PurePosixPath(member.name)
            assert not relative.is_absolute() and ".." not in relative.parts and relative.parts[:1] == ("backend",)
            assert str(relative) not in seen and len(seen) < 256
            seen.add(str(relative))
            assert member.isdir() or member.isreg()
            destination = root.joinpath(*relative.parts)
            assert destination.resolve().is_relative_to(root)
            if member.isdir():
                destination.mkdir(parents=True, exist_ok=True)
                continue
            assert relative.parts[:4] == ("backend", "app", "services", "world_simulation") and relative.suffix == ".py"
            total += member.size
            assert total <= 2 * 1024 * 1024
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(stream.extractfile(member).read())
    package_dir = root / "backend/app/services/world_simulation"
    name = "app.services._world_anchor_baseline"
    spec = importlib.util.spec_from_file_location(name, package_dir / "__init__.py", submodule_search_locations=[str(package_dir)])
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return SimpleNamespace(root=root, archive_hash=expected, **{key: importlib.import_module(name + "." + key)
        for key in ("compiler", "contracts", "observations", "kernel", "service")})


def test_off_bytes_equal_actual_9916_world_package(tmp_path, monkeypatch, legacy_world_package):
    from app.services.world_simulation import contracts, kernel

    old = legacy_world_package
    monkeypatch.setenv("SIM_WORLD_ANCHOR", "true")
    monkeypatch.setattr(host, "validate_anchor_context", lambda *a, **k: pytest.fail("off consulted anchor API"))
    raw, bundle = world_cases.proposal(), world_cases.source_bundle()
    kwargs = dict(simulation_id="sim", generation_id="world1", research_report=world_cases.REPORT,
                  research_generation_id="research1", research_engine="v3", actor_bundle=bundle)
    before = old.compiler.compile_world_spec(raw, **kwargs)
    after = compiler.compile_world_spec(raw, anchor_context=None, **kwargs)
    assert canonical_json(before) == canonical_json(after)
    message_args = {k: kwargs[k] for k in ("research_report", "research_generation_id", "research_engine", "actor_bundle")}
    assert old.compiler.build_compiler_messages(**message_args) == compiler.build_compiler_messages(**message_args)
    snapshots, observations, rounds = [], [], []
    for api, spec in ((old, before), (SimpleNamespace(contracts=contracts, kernel=kernel,
                     observations=importlib.import_module(build_observation.__module__)), after)):
        snapshot = api.kernel.initialize_world(spec)
        observation = api.observations.build_observation(spec, snapshot, "a", 1)
        decision = api.contracts.validate_decision(spec, {"actorId": "a", "observationId": observation["observationId"],
            "intents": []}, "a", observation, phase="proposal")
        snapshots.append(canonical_json(snapshot)); observations.append(canonical_json(observation))
        rounds.append(canonical_json(api.kernel.resolve_round(spec, snapshot, [decision], 1)))
    assert snapshots[0] == snapshots[1] and observations[0] == observations[1] and rounds[0] == rounds[1]
    monkeypatch.setattr(service.uuid, "uuid4", lambda: SimpleNamespace(hex="golden"))
    prepare_args = {key: kwargs[key] for key in message_args}
    for prefix, api in (("old", old.service), ("new", service)):
        api.WorldSimulationService.prepare_model("sim", raw_spec=raw, root=tmp_path / prefix, **prepare_args)
    for filename in ("world_spec.json", "world_input_manifest.json"):
        assert (tmp_path / "old/sim" / filename).read_bytes() == (tmp_path / "new/sim" / filename).read_bytes()
    repo = Path(__file__).resolve().parents[2]
    shared = ("backend/app/config.py", "backend/app/services/actor_context.py", "backend/app/services/actor_role_prompt.py",
              "backend/app/services/pipeline_orchestrator.py")
    _write(tmp_path / "baseline-comparison.json", {"baseline_commit": "9916b3beff6753cd07f2407f36428ca2030127fd",
        "archive_sha256": old.archive_hash, "equal": ["compiler", "modeler_messages", "initial_snapshot", "observation", "round", "sealed_files"],
        "shared_current_parent_dependencies": {name: hashlib.sha256((repo / name).read_bytes()).hexdigest() for name in shared},
        "scope": "world_simulation package comparison; parent dependencies are current in both branches"})


def test_scheduled_anchor_effect_executes_once_at_its_declared_boundary(tmp_path, monkeypatch):
    from app.services.world_simulation.controller import run_round
    from app.services.world_simulation.store import WorldStore

    f = _fixture(tmp_path, extra_parameters=[{"object": "event1", "target": "/scheduledEvents/0/parameters/delta",
                                             "metric": "scheduled_delta", "value": "2"}])
    f.raw["scheduledEvents"] = [{"eventId": "event1", "kind": "metric_delta", "at": "2026-10-29T00:00:00Z",
        "parameters": {"targetMetric": "baseline", "delta": "2"}, "visibility": {"kind": "public"},
        "basis": f.basis("event1", "/scheduledEvents/0/parameters/delta"), "structuralBasis": deepcopy(world_cases.ASSUMPTION)}]
    _, _, directory = _public_prepare(f, tmp_path, monkeypatch)
    spec, _ = load_inputs(directory)
    with WorldStore(directory / "world.sqlite3", spec) as store:
        fence = store.acquire_writer("calendar")
        assert store.head()["metrics"]["baseline"]["value"] == "247.5"
        first = run_round(store, _Policy(), fence)
        assert first["metrics"]["baseline"]["value"] == "249.5"
        applied = list(first["appliedEvents"])
        second = run_round(store, _Policy(), fence)
        assert second["metrics"]["baseline"]["value"] == "249.5" and second["appliedEvents"] == applied


@pytest.mark.parametrize("kind", ["changed", "missing", "symlink"])
def test_private_preparation_tamper_never_loads_as_a_valid_world(tmp_path, monkeypatch, kind):
    f = _fixture(tmp_path)
    _, _, directory = _public_prepare(f, tmp_path, monkeypatch)
    path = directory / "world_anchor_preparation.json"
    if kind == "changed":
        value = json.loads(path.read_text())
        value["candidate"]["initialState"]["metrics"]["baseline"]["value"] = "999"
        _write(path, value)
    else:
        path.unlink()
        if kind == "symlink":
            path.symlink_to(directory / "world_spec.json")
    with pytest.raises((WorldError, host.WorldAnchorIntegrationError)):
        load_inputs(directory)


def test_unsupported_anchor_menu_and_unavailable_source_fail_before_modeler(tmp_path, monkeypatch):
    from app.services.world_simulation import policy as policy_module

    f = _fixture(tmp_path)
    f.raw["actionCatalog"][0]["inputs"] = {"choice": {"type": "string", "enum": ["private choice"]}}
    with pytest.raises(WorldError, match="enumerated"):
        _compile(f)
    called = []
    monkeypatch.setattr(policy_module, "StrictHTTPModeler", lambda *a: called.append(True))
    with pytest.raises((WorldError, host.WorldAnchorIntegrationError)):
        service.WorldSimulationService.prepare_model("sim_bad_source", raw_spec=None, root=tmp_path / "simulations",
            research_report=f.report + " changed", research_generation_id="research", research_engine="v3",
            actor_bundle=f.bundle, anchor_context=f.context)
    assert called == []


def test_unimplemented_required_consumer_role_is_not_silently_ignored(tmp_path):
    f = _fixture(tmp_path, extra_parameters=[{"object": "baseline", "target": "threshold",
        "metric": "required_unimplemented_indicator", "value": "1", "role": "observation"}])
    assert host.validate_anchor_context(f.context, engine="world-v1") is f.context
    with pytest.raises(WorldError, match="consumer role"):
        _compile(f)
