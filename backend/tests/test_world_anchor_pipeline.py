"""Real anchor producer, parent controller, target runtime and report publication.

Run only with main_offline_pytest.py. Research is an explicit in-process
transport over retained synthetic inputs, not a subprocess/launcher test.
Extraction/review use the real gateway and ledger with a scripted Model;
actor decisions use the real LLMClient/OpenAI SDK with scripted HTTP.
"""

from contextlib import contextmanager
from contextvars import copy_context
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import shutil
from types import SimpleNamespace

import httpx
import pytest

# Pin direct production and fixture dependencies before this module imports them.
# The parent still owns the external whole-command freeze, including conftest.
_REPOSITORY = Path(__file__).resolve().parents[2]
_PROOF_PATHS = (
    "deerflow_bridge/linear_research.py",
    "deerflow_bridge/target_research.py",
    "deerflow_bridge/world_anchor.py",
    "deerflow_bridge/world_anchor_binding.py",
    "deerflow_bridge/world_anchor_publication.py",
    "deerflow_bridge/world_anchor_case.py",
    "deerflow_bridge/run_spending.py",
    "backend/app/services/world_anchor.py",
    "backend/app/services/pipeline_orchestrator.py",
    "backend/app/services/target_pipeline.py",
    "backend/app/services/run_spending.py",
    "backend/app/api/research.py",
    "backend/app/api/sdk.py",
    "backend/app/services/official_data.py",
    "backend/app/services/target_simulation.py",
    "backend/app/services/target_actors.py",
    "backend/app/services/report_agent.py",
    "backend/app/services/target_report.py",
    "backend/app/services/simulation_record_contract.py",
    "backend/app/utils/llm_client.py",
    "backend/tests/test_world_anchor_target.py",
    "backend/tests/test_world_anchor.py",
    "backend/tests/test_world_anchor_binding.py",
    "backend/tests/test_world_anchor_admission.py",
    "backend/tests/test_world_anchor_pipeline.py",
    "deerflow_bridge/research_gateway.py",
    "deerflow_bridge/search_tools.py",
    "deerflow_bridge/cached_fetch.py",
    "deerflow_bridge/forecast_case.py",
    "deerflow_bridge/deerflow_research.py",
    "backend/app/services/target_mechanisms.py",
    "backend/tests/test_run_spending_child_transports.py",
    "backend/tests/test_run_spending_parent_transport.py",
    "backend/tests/test_target_pipeline.py",
    "backend/tests/test_world_anchor_spending.py",
    "backend/tests/fixtures/target_case.json",
    "backend/tests/conftest.py",
    "backend/scripts/main_offline_pytest.py",
    "backend/app/config.py",
    "backend/app/utils/logger.py",
    "backend/app/services/simulation_manager.py",
)


def _source_hashes(root=_REPOSITORY, paths=_PROOF_PATHS):
    return {path: hashlib.sha256((root / path).read_bytes()).hexdigest() for path in paths}


def _assert_source_snapshot(expected, actual):
    drift = sorted(path for path in expected.keys() | actual.keys() if expected.get(path) != actual.get(path))
    assert not drift, "World Anchor proof dependency drift: " + ", ".join(drift)


_BEFORE_PROOF_IMPORTS = _source_hashes()


from app.services import run_spending as spending, target_pipeline as pipeline
from app.services import world_anchor as host
from app.services.official_data import bridge_module, capture_research_generation
from app.utils import llm_client
from deerflow_bridge import linear_research, research_gateway, world_anchor_binding as binder
from deerflow_bridge import world_anchor as anchor
from test_run_spending_child_transports import (
    FakeModel,
    KEY,
    ai,
    rows,
    fake_model_runtime as _fake_model_runtime,
    isolated as _isolated,
)
from test_run_spending_parent_transport import configured as _configured
from test_target_pipeline import runtime as _runtime
from test_world_anchor_binding import control_for, script_review
from test_world_anchor_spending import make_authority, sp
from tests.test_world_anchor_target import _fixture, _bind

fake_model_runtime = _fake_model_runtime
isolated = _isolated
configured = _configured
runtime = _runtime
pytestmark = pytest.mark.guarded_runner


@pytest.fixture(autouse=True)
def source_receipt(tmp_path):
    """Fail on proof drift at collection, between scenarios, or during execution."""
    before = _source_hashes()
    record = {
        "before_imports": _BEFORE_PROOF_IMPORTS,
        "before": before,
        "drift": [path for path in before if _BEFORE_PROOF_IMPORTS[path] != before[path]],
    }
    _write(tmp_path / "source-state.json", record)
    _assert_source_snapshot(_BEFORE_PROOF_IMPORTS, before)
    try:
        yield
    finally:
        after = _source_hashes()
        record.update(after=after, drift=[path for path in before if before[path] != after[path]])
        _write(tmp_path / "source-state.json", record)
        _assert_source_snapshot(_BEFORE_PROOF_IMPORTS, after)


def _write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True), encoding="utf-8")


def _unknown_target(case):
    target = next(row for row in case["nodes"] if row["nodeId"] == "target")
    target.update(value=None, range={"low": 0, "high": 500})


_UNKNOWN_TIME = {"value": None, "precision": "unknown", "basis_ref_ids": []}
_VISIBLE_AT = "2026-10-27T00:00:00Z"
_VISIBILITY_SENTENCE = "Public statements in this synthetic record are visible to all actors from " + _VISIBLE_AT + "."


def _assert_scripted_temporal_support(row):
    # These dates are unknown in the retained prose. Retrieval and known-by are
    # later reconstructed by production admission from the captured ledger.
    for field in ("published_at", "available_at", "retrieved_at", "effective_at", "vintage"):
        assert row[field] == _UNKNOWN_TIME, (field, row[field])
    visible = row["visible_at"]
    assert visible["value"] == _VISIBLE_AT and visible["precision"] == "second"
    (support,) = [item for item in row["support"] if item["field"] == "visible_at"]
    assert visible["basis_ref_ids"] == [support["ref_id"]]
    assert support["selector"]["kind"] == "text_span"
    assert _VISIBILITY_SENTENCE in support["selector"]["quote"]
    assert support["expected"] == support["selector"]["quote"]


def _scripted_review(model):
    task = next(
        message["content"]
        for message in model.calls[-1]["payload"]["messages"]
        if message["content"].startswith("PROPOSED_TUPLES\n")
    )
    for row in json.loads(task.split("\n", 1)[1]):
        _assert_scripted_temporal_support(row)
    return script_review(model)


def _assert_admitted_temporal_provenance(produced):
    pack, index = produced["pack"], produced["index"]
    references = {ref["ref_id"]: ref for ref in pack["references"]}
    for observation in pack["observations"]:
        for field in ("published_at", "available_at", "effective_at", "vintage"):
            assert observation[field] == _UNKNOWN_TIME
        for field in ("retrieved_at", "known_by"):
            time = observation[field]
            (ref_id,) = time["basis_ref_ids"]
            ref = references[ref_id]
            assert ref["locator"]["kind"] == "json_value"
            assert ref["locator"]["pointer"].endswith("/fetched_at")
            raw = index.artifact_bytes(ref["artifact_id"])
            assert hashlib.sha256(raw).hexdigest() == ref["content_hash"]
            value = json.loads(raw)
            for component in ref["locator"]["pointer"].split("/")[1:]:
                value = value[int(component)] if isinstance(value, list) else value[component]
            assert value == time["value"] == "2026-10-26T09:29:13Z"
            assert anchor.anchor_hash(value) == ref["locator"]["value_hash"]
        (ref_id,) = observation["visible_at"]["basis_ref_ids"]
        ref = references[ref_id]
        locator = ref["locator"]
        raw = index.artifact_bytes(ref["artifact_id"])
        assert raw[locator["start_byte"] : locator["end_byte"]].decode() == locator["quote"]
        assert _VISIBILITY_SENTENCE in locator["quote"]
        assert observation["visible_at"]["value"] == _VISIBLE_AT


def _extraction(model, native):
    """Script tuples from the existing fixture, rebinding exact captured spans."""
    payload = model.calls[-1]["payload"]
    blocks = {
        message["content"].split("\n", 1)[0]: json.loads(message["content"].split("\n", 1)[1])
        for message in payload["messages"]
        if not message["content"].startswith("CORE\n")
    }
    (requirement,) = blocks["REQUIREMENTS"]
    rid = requirement["requirement_id"]
    candidate = blocks["CANDIDATES"][rid][0]
    reference = candidate["references"][0]
    binding = next(item for item in native["pack"]["bindings"] if item["requirement_id"] == rid)
    (observation_id,) = binding["observation_ids"]
    observation = next(item for item in native["pack"]["observations"] if item["observation_id"] == observation_id)
    row = {key: deepcopy(observation[key]) for key in anchor.EXTRACT_FIELDS.split() if key in observation}
    row.update(
        proposal_id="script-" + rid,
        requirement_ids=[rid],
        claim_id=candidate["claim_id"],
        ref_ids=[reference["ref_id"]],
    )
    for support in row["support"]:
        support.update(
            ref_id=reference["ref_id"], selector=deepcopy(reference["locator"]), expected=reference["locator"]["quote"]
        )
    # Never relabel a ledger-derived retrieval timestamp as a prose assertion.
    # Production admission owns retrieval and known-by reconstruction.
    for key in ("published_at", "available_at", "effective_at", "vintage"):
        assert row[key] == _UNKNOWN_TIME, (key, row[key])
    row["retrieved_at"] = deepcopy(_UNKNOWN_TIME)
    row["visible_at"]["basis_ref_ids"] = [reference["ref_id"]]
    _assert_scripted_temporal_support(row)
    return ai(json.dumps({"references": [reference], "rows": [row]}))


@contextmanager
def _composed(runtime, tmp_path, monkeypatch, *, actor_free=False, surface="private", malformed_second=False):
    """Keep real controller admission, external manifests and ledger ownership."""
    po = runtime.po
    manifest, authorization, registry, request = make_authority(tmp_path / "authority")
    request.update(
        prompt="What is 2027 spending?",
        model="glm",
        depth="quick",
        target_simulation={"paths": 1, "periods": 2, "seed": 7},
    )
    manifest["routes"]["model"].update(model="glm-4.7", input_ceiling=8000, max_output_tokens=8192)
    for route in manifest["routes"].values():
        route["account_sha256"] = hashlib.sha256(KEY.encode()).hexdigest()
    manifest["routes"]["model"]["pricing"].update(input_usd_per_million="1", output_usd_per_million="2")
    # Use the native fixture's explicit question before the immutable request is admitted.
    from tests.test_world_anchor_target import _case

    request["prompt"] = _case()["question"]
    manifest["request_sha256"] = sp.hash_payload(request)
    manifest["routes_sha256"] = sp.hash_payload(manifest["routes"])
    _write(authorization, manifest)
    binding = sp.create_authorization(authorization, registry_dir=registry)
    root = Path(binding["root"])
    for key, value in {
        "UPLOAD_FOLDER": root / "uploads",
        "PIPELINE_DATA_DIR": root / "uploads/pipelines",
        "OASIS_SIMULATION_DATA_DIR": root / "uploads/simulations",
        "DEERFLOW_DIR": root / "deer-flow",
    }.items():
        monkeypatch.setattr(runtime.config, key, str(value))
    monkeypatch.setattr(po.ProjectManager, "PROJECTS_DIR", str(root / "uploads/projects"))
    monkeypatch.setattr(po.ReportManager, "REPORTS_DIR", str(root / "uploads/reports"))
    monkeypatch.setattr(runtime.config, "LLM_API_KEY", KEY)
    monkeypatch.setattr(runtime.config, "REPORT_TOURNAMENT", False)
    monkeypatch.setattr(runtime.config, "REPORT_PUBLISH_GATE", True)
    monkeypatch.setenv("NEWS_CONTEXT_ENABLED", "false")
    monkeypatch.setenv("DATA_SOURCES_ENABLED", "false")
    monkeypatch.setenv("RESEARCH_SKILLS", "off")
    for key, value in sp.export_environment(binding).items():
        monkeypatch.setenv(key, value)
    observations, http_calls, research_calls, checkpoints, transport_errors = [], [], [], [], []
    model = FakeModel(model="glm-4.7")
    model.openai_api_base = model.root_client.base_url = manifest["routes"]["model"]["endpoint"]

    def actor_http(request):
        http_calls.append(json.loads(request.content))
        try:
            committed = rows(sp.current_binding())[-1]
            assert committed["state"] == "unknown"
            wire = http_calls[-1]
            envelope = json.loads(committed["envelope"])
            assert envelope["payload_sha256"] == sp.hash_payload(wire)
            observation = json.loads(wire["messages"][-1]["content"])
            observations.append(observation)
            (lever,) = observation["levers"]
            action = {"kind": "lever", "actorId": observation["actorId"], "leverId": lever["leverId"], "value": 20}
            if malformed_second and observation["period"] == 2:
                action["value"] = "MALFORMED_SECOND_TURN"
        except Exception as error:
            transport_errors.append(str(error))
            raise
        return httpx.Response(
            200,
            json={
                "id": "offline-decision",
                "object": "chat.completion",
                "created": 0,
                "model": "glm-4.7",
                "choices": [
                    {
                        "index": 0,
                        "finish_reason": "stop",
                        "message": {"role": "assistant", "content": json.dumps({"actions": [action]})},
                    }
                ],
                "usage": {"prompt_tokens": 12, "completion_tokens": 20, "total_tokens": 32},
            },
        )

    http = httpx.Client(transport=httpx.MockTransport(actor_http), trust_env=False, follow_redirects=False)
    monkeypatch.setattr(llm_client.LLMClient, "_build_http_client", staticmethod(lambda: http))
    with sp.run_lock(binding):
        if surface == "private":
            state = po.PipelineOrchestrator.start(**request)
        else:
            from test_world_anchor_admission import _public_route

            client, route = _public_route(monkeypatch, surface)
            response = client.post(route, json={**request, "world_anchor": {"mode": "v1"}})
            assert response.status_code == 200, response.json
            state = po.PipelineState.from_dict(po.PipelineManager.load(response.json["data"]["pipeline_id"]))
            assert state.options[spending.REQUEST_KEY] == request
            assert state.options[host.CONFIG_KEY] == request["world_anchor"]
        # Freeze synthetic source identities only after the real controller has its ID.
        native = _fixture(
            root / "retained",
            run_id=state.pipeline_id,
            mutation=_unknown_target,
            research_dossiers=True,
            actor_free=actor_free,
        )
        assert _bind(native)["nodes"]
        # Real target capture joins KIQ SIDs through the case's retained sources.
        # The lower-level fixture has an external crosswalk instead; supply the
        # equivalent case source before the producer takes its own snapshot.
        page = (native["root"] / "v3/pages/page.txt").read_text()
        research_case = deepcopy(native["case"])
        research_case["sources"] = [
            {
                "sourceId": "S107",
                "url": "https://example.test/report",
                "title": "Synthetic records",
                "publishedAt": None,
                "retrievedAt": "2026-10-26T09:29:13Z",
                "originCluster": "synthetic-records",
                "tier": "secondary",
                "fetched": True,
                "passage": page,
            }
        ]
        control = control_for(native, request)
        required = [r for r in native["requirements"]["requirements"] if r["kind"] != "target_definition"]
        model.state["script"] = [
            call for _ in required for call in (lambda: _extraction(model, native), lambda: _scripted_review(model))
        ]
        produced = {}
        research_generation = {}

        def research(prompt, folder, **kwargs):
            research_calls.append(kwargs)
            assert prompt == state.prompt and kwargs["budget_run_id"] == state.pipeline_id
            assert host.enabled(state.options)
            assert state.options[host.LIFECYCLE_KEY]["status"] == "pending"
            output = Path(folder)
            import deerflow_research as bridge

            args = SimpleNamespace(
                model="glm",
                depth="quick",
                target_language="English",
                no_actors=False,
                forecast_authority="target-first-v1",
            )
            engine = linear_research._Engine(
                prompt,
                output,
                args,
                {"status": "running"},
                linear_research._Reporter(None),
                lambda: None,
                bridge,
                lambda *args: research_gateway.ModelGateway(model, None, sleep=lambda _: None),
                linear_research._default_tools_factory,
                __import__("os").environ,
                world_anchor_control=control,
            )
            for artifact in native["manifest"]["artifacts"]:
                if artifact["role"] in {"contract", "review"}:
                    continue
                destination = output / artifact["path"]
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(native["root"] / artifact["path"], destination)
            engine.ledger = research_gateway.SourceLedger(engine.work / "sources_ledger.json")
            engine.tools.ledger = engine.ledger

            def produce():
                with sp.operation("research", "composed-retained-generation"):
                    return binder.run_anchor_stage(engine, control, case=research_case)

            # A copied context models the child's independent admission descriptor;
            # the parent must adopt real transition receipts, never the child's mutable binding.
            produced.update(copy_context().run(produce))
            _assert_admitted_temporal_provenance(produced)
            parent_binding = spending.state_binding(state)
            spending._adopt_research_scope_handoff(parent_binding, output)
            checkpoints.append(deepcopy(state.options[host.LIFECYCLE_KEY]))
            attempts_before_replay = rows(sp.current_binding())
            replay = binder.run_anchor_stage(engine, control, case=research_case)
            assert replay["manifest_sha256"] == produced["manifest_sha256"]
            assert rows(sp.current_binding()) == attempts_before_replay
            case_api = bridge_module("forecast_case")
            case = bridge_module("world_anchor_case").apply_anchors_to_case(
                native["case"], **{key: produced[key] for key in ("pack", "requirements", "index", "policy")}
            )
            case_api.write_case(output / "forecast_case.json", case)
            (output / "research_report.md").write_text(bridge_module("target_research").render_case_research(case))
            _write(output / "actors.json", {"actors": case["actors"]})
            _write(output / "sources.json", case["sources"])
            (output / "actor_dossier.md").write_text("Synthetic admitted regulator registry.")
            research_generation.update(capture_research_generation(output, sources=case["sources"]))
            return {"meta": {}, "actors": {"actors": case["actors"]}, "sources": case["sources"]}

        monkeypatch.setattr(po.DeerFlowResearchRunner, "run", research)
        try:
            yield SimpleNamespace(
                state=state,
                owner=po.PipelineOrchestrator(),
                po=po,
                produced=produced,
                native=native,
                model=model,
                observations=observations,
                http_calls=http_calls,
                research_calls=research_calls,
                checkpoints=checkpoints,
                transport_errors=transport_errors,
                research_generation=research_generation,
            )
        finally:
            _write(root / "scripted-actor-requests.json", http_calls)
            http.close()
            assert not transport_errors, transport_errors


def _assert_successful_actor_turns(run, result):
    assert [(item["actorId"], item["period"]) for item in run.observations] == [("actor-0001", 1), ("actor-0001", 2)], (
        "The actual actor request sequence changed"
    )
    assert len(run.http_calls) == 2
    assert result["decisionBudget"] == {"maximumRequests": 128, "requests": 2, "cacheHits": 0, "exhausted": False}
    expected = [
        {
            "period": 1,
            "actorId": "regulator",
            "status": "applied",
            "reason": "lever",
            "kind": "lever",
            "leverId": "mandate",
            "value": 20,
            "effectivePeriod": 1,
            "cost": 10,
            "remainingCapacity": 90.0,
        },
        {
            "period": 2,
            "actorId": "regulator",
            "status": "applied",
            "reason": "lever",
            "kind": "lever",
            "leverId": "mandate",
            "value": 20,
            "effectivePeriod": 2,
            "cost": 0,
            "remainingCapacity": 90.0,
        },
    ]
    assert result["paths"][0]["decisions"] == expected, "Every expected actor decision must be applied"
    assert result["paths"][0]["trajectory"] == [
        {"period": 0, "values": {"baseline": 247.5, "control": 10, "target": 257.5}},
        {"period": 1, "values": {"baseline": 247.5, "control": 20, "target": 267.5}},
        {"period": 2, "values": {"baseline": 247.5, "control": 20, "target": 267.5}},
    ]
    assert result["paths"][0]["pendingEffects"] == []
    assert result["paths"][0]["plans"] == {"regulator": []}


def _assert_actor_payloads(run):
    forbidden_fields = {
        "assessments",
        "scenarioWeights",
        "simulationWeight",
        "caseHash",
        "packHash",
        "pack_hash",
        "input_hash",
        "requirements_hash",
        "source_key",
        "ref_ids",
        "decisionBasis",
        "sources",
        "claims",
        "binaries",
        "forecasts",
        "probability",
    }

    def inspect(value):
        if isinstance(value, dict):
            assert not forbidden_fields.intersection(value), forbidden_fields.intersection(value)
            for item in value.values():
                inspect(item)
        elif isinstance(value, list):
            for item in value:
                inspect(item)

    assert run.native["case"]["actors"][0]["objectives"], "Keep the excluded-objective negative control present"
    assert run.native["case"]["actors"][0]["plans"], "Keep the unadmitted-plan negative control present"
    for wire, observation in zip(run.http_calls, run.observations, strict=True):
        assert [message["role"] for message in wire["messages"]] == ["system", "user"]
        assert json.loads(wire["messages"][1]["content"]) == observation
        inspect(observation)
        whole_payload = json.dumps(wire, sort_keys=True)
        for excluded in (
            "PRIVATE_SELF_INFERENCE",
            "unsafe-plan",
            "plan-0001",
            "node-0003",
            "research-only",
            "0.76",
            run.produced["manifest_sha256"],
            run.produced["manifest"]["pack_hash"],
            run.produced["pack"]["input_hash"],
        ):
            assert excluded not in whole_payload
        assert set(observation) == {
            "schemaVersion",
            "actorId",
            "period",
            "values",
            "observedPeriods",
            "beliefs",
            "signals",
            "levers",
            "plans",
            "objectives",
            "capacity",
            "decisionRule",
            "anchorItems",
        }
        assert observation["schemaVersion"] == "target-actor-observation/v1"
        assert observation["actorId"] == "actor-0001"
        assert observation["objectives"] == observation["plans"] == observation["signals"] == []
        # The actor sees its later legitimate lever state. The future settlement
        # stays out of current knowledge even after the model computes it.
        values = {"node-0001": 247.5, "node-0002": 10 if observation["period"] == 1 else 20}
        assert observation["values"] == observation["beliefs"] == values
        assert observation["observedPeriods"] == dict.fromkeys(values, observation["period"])
        assert observation["capacity"] == (100 if observation["period"] == 1 else 90)
        assert observation["decisionRule"] == {"kind": "llm", "cadencePeriods": 1, "triggers": []}
        assert observation["levers"] == [
            {
                "leverId": "lever-0001",
                "nodeId": "node-0002",
                "minimum": 0,
                "maximum": 20,
                "cost": 1,
                "lagPeriods": 0,
                "reversible": True,
                "requiresConsent": [],
            }
        ]
        items = observation["anchorItems"]
        assert len(items) == 6
        expected_values = {
            "spending": {"kind": "number", "value": "247.5"},
            "control": {"kind": "number", "value": "10"},
            "coefficient:baseline": {"kind": "number", "value": "1"},
            "coefficient:control": {"kind": "number", "value": "1"},
            "intercept": {"kind": "number", "value": "0"},
            "regulator:authority": {"kind": "text", "value": "Regulator has sole authority."},
        }
        assert {item["identity"]["metric_id"]: item["value"] for item in items} == expected_values
        admitted_identities = {
            item["identity"]["metric_id"]: item["identity"] for item in run.produced["pack"]["observations"]
        }
        assert any(
            item["value"] == {"kind": "number", "value": "247.5"} and item["identity"]["metric_id"] == "spending"
            for item in items
        )
        assert any(item["value"] == {"kind": "text", "value": "Regulator has sole authority."} for item in items)
        for item in items:
            assert set(item) == {
                "item_id",
                "text",
                "value",
                "value_kind",
                "identity",
                "public_source_url",
                "known_by",
                "effective_at",
            }
            assert item["value_kind"] == "reported"
            assert item["identity"] == admitted_identities[item["identity"]["metric_id"]]
            assert item["public_source_url"] is None
            assert item["known_by"] == "2026-10-26T09:29:13Z" and item["effective_at"] is None
            assert json.loads(item["text"]) == item["value"]


@pytest.mark.parametrize("surface", ["private", "spa", "sdk"])
def test_real_producer_controller_target_runtime_and_publication(
    runtime,
    tmp_path,
    monkeypatch,
    configured,
    isolated,
    fake_model_runtime,
    surface,
):
    with _composed(runtime, tmp_path, monkeypatch, surface=surface) as run:
        with spending.pipeline_scope(run.state):
            pipeline.run_target_pipeline(run.owner, run.state)
        state = run.state
        assert state.status == "completed", state.error
        assert len(run.research_calls) == 1
        assert run.checkpoints[0]["status"] == "pending"
        assert run.checkpoints[0]["completion_manifest_sha256"] == run.produced["manifest_sha256"]
        assert all(pipeline.validate_stage(state, stage) for stage in state.stages)
        assert run.po.ReportManager.publication_status(state.report_id)["publishable"]
        assert capture_research_generation(state.handoff_dir) == run.research_generation
        context = host.load_target_anchor(Path(runtime.config.OASIS_SIMULATION_DATA_DIR) / state.simulation_id)
        assert context.pack_hash == state.options[host.LIFECYCLE_KEY]["pack_hash"]
        result = json.loads(Path(state.artifacts["target_simulation"]).read_text())
        assert result["baseline"]["targetValue"] == 257.5
        assert result["paths"][0]["targetValue"] == 267.5
        assert result["simulationWeight"] == 0
        _assert_successful_actor_turns(run, result)
        _assert_actor_payloads(run)
        forecast = json.loads(Path(state.artifacts["target_forecast"]).read_text())
        assert [row["probability"] for row in forecast["scenarios"]] == [0.5, 0.5]
        report_folder = Path(run.po.ReportManager._get_report_folder(state.report_id))
        report = (report_folder / "full_report.md").read_text()
        public_record = json.loads((report_folder / "target_report.json").read_text())
        final_audit = json.loads((report_folder / "final_audit.json").read_text())
        assert final_audit["target_report"]["valid"]
        assert final_audit["target_report"]["issues"] == []
        assert public_record["worldAnchor"]["target_node_id"] == "target"
        assert "World Anchor diagnostics" in report and "267.5" in report
        assert "PRIVATE_SELF_INFERENCE" not in report and "unsafe-plan" not in report
        assert context.pack_hash not in json.dumps(public_record)
        attempts = rows(sp.current_binding())
        assert len(attempts) == len(run.model.calls) + len(run.http_calls)
        scoped = [row for row in attempts if row["scope_id"] == "anchor-one"]
        assert len(scoped) == len(run.model.calls) == 12
        assert sum(row["token_envelope_units"] for row in scoped) == 120000
        assert run.produced["pack"]["metering"]["physical_model_attempts"] == len(scoped)
        assert all(row["state"] == "response_observed" for row in attempts)
        for call in run.model.calls:
            committed = call["committed"][-1]
            assert committed["request_sha256"] == sp.hash_payload(call["payload"])
        assert state.options["spending_summary_v1"]["state"] == "closed"


def test_malformed_second_turn_cannot_pass_unchanged_final_value(
    runtime,
    tmp_path,
    monkeypatch,
    configured,
    isolated,
    fake_model_runtime,
):
    with _composed(runtime, tmp_path, monkeypatch, malformed_second=True) as run:
        with spending.pipeline_scope(run.state):
            pipeline.run_target_pipeline(run.owner, run.state)
        result = json.loads(Path(run.state.artifacts["target_simulation"]).read_text())
        assert result["paths"][0]["targetValue"] == 267.5
        assert result["paths"][0]["decisions"][1] == {
            "period": 2,
            "actorId": "regulator",
            "status": "blocked",
            "reason": "invalid_action",
        }
        with pytest.raises(AssertionError, match="Every expected actor decision must be applied"):
            _assert_successful_actor_turns(run, result)
        _assert_actor_payloads(run)


def test_source_drift_gate_rejects_changed_imported_fixture(tmp_path):
    helper = "backend/tests/test_run_spending_child_transports.py"
    assert helper in _PROOF_PATHS
    copied = tmp_path / helper
    copied.parent.mkdir(parents=True)
    copied.write_bytes((_REPOSITORY / helper).read_bytes())
    before = _source_hashes(tmp_path, (helper,))
    _assert_source_snapshot(before, _source_hashes(tmp_path, (helper,)))
    copied.write_bytes(copied.read_bytes() + b"\n# Synthetic source drift\n")
    with pytest.raises(AssertionError, match="proof dependency drift.*test_run_spending_child_transports"):
        _assert_source_snapshot(before, _source_hashes(tmp_path, (helper,)))


def test_research_registry_superset_does_not_create_executable_actors(
    runtime,
    tmp_path,
    monkeypatch,
    configured,
    isolated,
    fake_model_runtime,
):
    with _composed(runtime, tmp_path, monkeypatch, actor_free=True) as run:
        with spending.pipeline_scope(run.state):
            pipeline.run_target_pipeline(run.owner, run.state)
        assert run.state.status == "completed"
        assert run.produced["pack"]["actor_dossiers"], "The research-only dossier must reach publication."
        case = json.loads(Path(run.state.artifacts["forecast_case"]).read_text())
        assert case["actors"] == []
        assert run.http_calls == run.observations == []
        result = json.loads(Path(run.state.artifacts["target_simulation"]).read_text())
        assert result["paths"][0]["targetValue"] == 257.5
        assert run.po.ReportManager.publication_status(run.state.report_id)["publishable"]


class _InterruptedAfterRun(RuntimeError):
    pass


def _interrupt_after_real_run(run, monkeypatch):
    complete = run.owner._complete_stage

    def interrupt(state, stage, *args, **kwargs):
        complete(state, stage, *args, **kwargs)
        if stage == "run":
            raise _InterruptedAfterRun("Scripted interruption after the real run seal")

    with monkeypatch.context() as patch:
        patch.setattr(run.owner, "_complete_stage", interrupt)
        with spending.pipeline_scope(run.state), pytest.raises(_InterruptedAfterRun):
            pipeline.run_target_pipeline(run.owner, run.state)
    assert run.state.stages["run"].status == "completed"
    assert pipeline.validate_stage(run.state, "run")


def test_report_retry_reuses_produced_anchor_and_saved_paths_without_dispatch(
    runtime,
    tmp_path,
    monkeypatch,
    configured,
    isolated,
    fake_model_runtime,
):
    with _composed(runtime, tmp_path, monkeypatch) as run:
        _interrupt_after_real_run(run, monkeypatch)
        state = run.state
        paths = [
            path
            for stage in ("research", "ontology", "graph", "prepare", "run")
            for _, path in pipeline.stage_specs(state, stage)
        ]
        protected = {path: Path(path).read_bytes() for path in paths}
        attempts = rows(sp.current_binding())
        counts = (len(run.research_calls), len(run.model.calls), len(run.http_calls))
        with spending.pipeline_scope(state):
            pipeline.run_target_pipeline(run.owner, state)
        assert state.status == "completed"
        assert run.po.ReportManager.publication_status(state.report_id)["publishable"]
        assert (len(run.research_calls), len(run.model.calls), len(run.http_calls)) == counts
        assert rows(sp.current_binding()) == attempts
        assert {path: Path(path).read_bytes() for path in paths} == protected


@pytest.mark.parametrize("changed", ["pack", "retained_source", "prepared_case"])
def test_report_retry_rejects_changed_generation_before_any_new_dispatch(
    runtime,
    tmp_path,
    monkeypatch,
    configured,
    isolated,
    fake_model_runtime,
    changed,
):
    with _composed(runtime, tmp_path, monkeypatch) as run:
        _interrupt_after_real_run(run, monkeypatch)
        state = run.state
        if changed == "pack":
            path = Path(state.handoff_dir) / "world_anchor.json"
        elif changed == "retained_source":
            path = next((Path(state.handoff_dir) / "world_anchor_inputs").rglob("page.txt"))
        else:
            path = Path(state.artifacts["target_case"])
        path.write_bytes(path.read_bytes() + b"\n")
        attempts = rows(sp.current_binding())
        counts = (len(run.research_calls), len(run.model.calls), len(run.http_calls))
        with (
            spending.pipeline_scope(state),
            pytest.raises(
                (pipeline.TargetPipelineError, host.WorldAnchorIntegrationError, anchor.AnchorError)
            ) as failure,
        ):
            pipeline.run_target_pipeline(run.owner, state)
        if changed == "retained_source":
            assert str(failure.value).startswith("E_HASH:"), str(failure.value)
        assert state.stages["report"].status != "completed" and state.report_id is None
        assert (len(run.research_calls), len(run.model.calls), len(run.http_calls)) == counts
        assert rows(sp.current_binding()) == attempts
