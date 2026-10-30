"""Pure packing checks. These do not claim provider admission or semantic truth."""
import copy
import json

import pytest

from deerflow_bridge import world_anchor_binding as binder


def inputs(count=3):
    requirements = [{"requirement_id": f"requirement_{number:03d}", "kind": "baseline"} for number in range(count)]
    candidates = {row["requirement_id"]: [{"candidate_id": "candidate_" + row["requirement_id"],
        "ref_ids": ["ref_1"], "quote": "市场预计2026年为247.5亿美元。\r\nThis is a forecast, not an observation. 🌏"}]
        for row in requirements}
    return {"context": {key: "a" * 64 for key in ("input_hash", "requirements_hash", "contract_hash", "policy_hash")},
            "contract": {"target": "explicit reviewed fixture target"}, "requirements": requirements,
            "candidates": candidates, "response_schema": {"type": "object", "additionalProperties": False},
            "profile": binder.PromptProfile(8000, 2000), "remaining_attempts": 20,
            "remaining_tokens": 150000}


def shape_fit(maximum):
    # A deterministic packing oracle, not a token estimate/qualification proof.
    return lambda call: len(call.payload()["requirements"]) <= maximum


def test_pack_whole_requirements_preserves_natural_prose_and_exact_strings():
    data = inputs(5)
    plan = binder.pack_extraction_requests(**data, fits=shape_fit(2))
    assert [len(call.payload()["requirements"]) for call in plan.calls] == [2, 2, 1]
    assert plan.minimum_model_attempts == 6
    assert plan.minimum_token_envelopes == 60000
    assert not plan.unpacked
    first = plan.calls[0]
    assert first.payload()["candidates"]["requirement_000"] == data["candidates"]["requirement_000"]
    assert first.input_upper_bound == 8000 and first.max_output_tokens == 2000
    assert [message["content"].split("\n", 1)[0] for message in first.messages()] == [
        "CORE", "CONTEXT", "CONTRACT", "REQUIREMENTS", "CANDIDATES", "RESPONSE_SCHEMA"]
    assert "artificial entity=" in first.messages()[0]["content"]


def test_packing_is_deterministic_and_does_not_alias_mutable_inputs():
    data = inputs()
    plan = binder.pack_extraction_requests(**data, fits=shape_fit(12))
    reverse = {**data, "requirements": list(reversed(data["requirements"]))}
    assert binder.pack_extraction_requests(**reverse, fits=shape_fit(12)) == plan
    before = plan.calls[0].messages_json
    data["candidates"]["requirement_000"][0]["quote"] = "changed outside packet"
    detached = plan.calls[0].payload()
    detached["contract"].clear()
    assert plan.calls[0].messages_json == before
    assert plan.calls[0].payload()["contract"]


def test_max_twelve_requirements_and_six_candidates_without_silent_drop():
    data = inputs(13)
    plan = binder.pack_extraction_requests(**data, fits=shape_fit(100))
    assert [len(call.payload()["requirements"]) for call in plan.calls] == [12, 1]
    data["candidates"]["requirement_000"] *= 7
    with pytest.raises(binder.BindingPreparationError, match="candidate_limit"):
        binder.pack_extraction_requests(**data, fits=shape_fit(100))


def test_full_context_envelope_requires_room_for_independent_review():
    data = inputs()
    data["profile"] = binder.PromptProfile(128000, 2000)
    plan = binder.pack_extraction_requests(**data, fits=shape_fit(12))
    assert not plan.calls and plan.minimum_model_attempts == plan.minimum_token_envelopes == 0
    assert {gap.reason for gap in plan.unpacked} == {"pair_budget_unavailable"}
    data["profile"] = binder.PromptProfile(8000, 2000)
    data["remaining_attempts"] = 1
    assert not binder.pack_extraction_requests(**data, fits=shape_fit(12)).calls


def test_last_pair_capacity_leaves_unpacked_requirements_explicit():
    data = inputs(13)
    data["remaining_attempts"] = 2
    plan = binder.pack_extraction_requests(**data, fits=shape_fit(12))
    assert len(plan.calls) == 1 and len(plan.calls[0].payload()["requirements"]) == 12
    assert plan.unpacked == (binder.UnpackedRequirement("requirement_012", "pair_budget_unavailable"),)


def test_unfit_whole_requirement_never_truncates_a_source_or_schema():
    data = inputs(2)
    original = copy.deepcopy(data["candidates"])
    plan = binder.pack_extraction_requests(**data, fits=shape_fit(0))
    assert not plan.calls
    assert len(plan.unpacked) == 2 and all(g.reason == "request_does_not_fit" for g in plan.unpacked)
    assert data["candidates"] == original


def test_missing_contract_and_no_candidate_are_specific_not_blank_results():
    data = inputs()
    data["contract"] = None
    plan = binder.pack_extraction_requests(**data, fits=shape_fit(12))
    assert not plan.calls and all(g.reason == "missing_contract" for g in plan.unpacked)
    data = inputs()
    del data["candidates"]["requirement_000"]
    plan = binder.pack_extraction_requests(**data, fits=shape_fit(12))
    assert plan.unpacked == (binder.UnpackedRequirement("requirement_000", "no_candidate"),)
    assert len(plan.calls) == 1


def proposal():
    # Unadmitted typed fields only; the pure contract will validate full shape,
    # provenance, byte spans, review receipts and field-level semantic support.
    return [{"proposal_id": "proposal_1", "requirement_ids": ["requirement_000"],
             "value": {"kind": "number", "value": "247.5"}, "value_kind": "third_party_forecast",
             "ref_ids": ["ref_1"]}]


def test_review_is_distinct_and_retains_source_context_without_authority_labels():
    extracted = binder.pack_extraction_requests(**inputs(), fits=shape_fit(12)).calls[0]
    tuples = proposal()
    reviewed = binder.make_review_request(extracted, proposed_tuples=tuples,
        response_schema={"decisions": "closed review schema supplied by contract"}, fits=shape_fit(12))
    assert reviewed.phase == "semantic_review" and reviewed.prompt_sha256 != extracted.prompt_sha256
    assert reviewed.payload()["candidates"] == extracted.payload()["candidates"]
    assert reviewed.payload()["context"] == extracted.payload()["context"]
    assert reviewed.payload()["proposed_tuples"] == tuples
    assert "independently" in reviewed.messages()[0]["content"].lower()
    assert "not prove historical" in reviewed.messages()[0]["content"]
    assert "review_attempt_id" not in reviewed.payload()


@pytest.mark.parametrize("field", ["rationale", "confidence", "review_attempt_id", "note", "reasoning"])
def test_extractor_notes_or_self_approval_never_enter_review(field):
    extracted = binder.pack_extraction_requests(**inputs(), fits=shape_fit(12)).calls[0]
    tuples = proposal()
    tuples[0][field] = "untrusted extraction authority"
    with pytest.raises(binder.BindingPreparationError, match="review_contains_extractor_authority"):
        binder.make_review_request(extracted, proposed_tuples=tuples, response_schema={}, fits=shape_fit(12))


def test_review_checks_actual_packet_fit_and_requirement_scope():
    extracted = binder.pack_extraction_requests(**inputs(), fits=shape_fit(12)).calls[0]
    with pytest.raises(binder.BindingPreparationError, match="request_does_not_fit"):
        binder.make_review_request(extracted, proposed_tuples=proposal(), response_schema={}, fits=shape_fit(0))
    tuples = proposal(); tuples[0]["requirement_ids"] = ["foreign"]
    with pytest.raises(binder.BindingPreparationError, match="foreign_requirement"):
        binder.make_review_request(extracted, proposed_tuples=tuples, response_schema={}, fits=shape_fit(12))


@pytest.mark.parametrize("value", [float("nan"), float("inf"), 2**80, "\ud800"])
def test_noncanonical_input_rejected_with_no_private_payload_in_error(value):
    data = inputs(); data["contract"]["private-value"] = value
    with pytest.raises(binder.BindingPreparationError) as caught:
        binder.pack_extraction_requests(**data, fits=shape_fit(12))
    assert str(caught.value) == "invalid_json"


@pytest.mark.parametrize("attempts,tokens", [(True, 150000), (21, 150000), (20, 150001)])
def test_planning_cannot_expand_hard_stage_limits(attempts, tokens):
    data = inputs(); data.update(remaining_attempts=attempts, remaining_tokens=tokens)
    with pytest.raises(binder.BindingPreparationError, match="invalid_profile"):
        binder.pack_extraction_requests(**data, fits=shape_fit(12))


def test_fit_oracle_must_return_explicit_boolean():
    with pytest.raises(binder.BindingPreparationError, match="invalid_fit_verdict"):
        binder.pack_extraction_requests(**inputs(), fits=lambda call: 1)


def test_prompt_preparation_does_not_promote_a_quote_to_observation():
    plan = binder.pack_extraction_requests(**inputs(1), fits=shape_fit(12))
    body = json.loads(plan.calls[0].payload_json)
    assert "observations" not in body and "bindings" not in body and "producer_receipts" not in body
    assert "247.5" in body["candidates"]["requirement_000"][0]["quote"]


@pytest.mark.parametrize("field", ["value", "identity", "support"])
def test_nested_extractor_rationale_never_enters_review(field):
    extracted = binder.pack_extraction_requests(**inputs(), fits=shape_fit(12)).calls[0]
    rows = proposal()
    if field == "value": rows[0]["value"]["rationale"] = "already verified"
    elif field == "identity": rows[0]["identity"] = {"entity_id": "entity", "confidence": "high"}
    else: rows[0]["support"] = [{"field": "value", "note": "approve me"}]
    with pytest.raises(binder.BindingPreparationError, match="review_contains_extractor_authority"):
        binder.make_review_request(extracted, proposed_tuples=rows, response_schema={}, fits=shape_fit(12))


def test_serialized_size_splits_complete_requirements(monkeypatch):
    data = inputs(2)
    singles = binder.pack_extraction_requests(**data, fits=shape_fit(1))
    ceiling = max(len(call.messages_json.encode()) for call in singles.calls) + 20
    monkeypatch.setattr(binder, "MAX_PACKET_BYTES", ceiling)
    plan = binder.pack_extraction_requests(**data, fits=shape_fit(12))
    assert len(plan.calls) == 2 and not plan.unpacked


def test_oversized_singleton_does_not_discard_following_valid_requirement(monkeypatch):
    data = inputs(2)
    singles = binder.pack_extraction_requests(**data, fits=shape_fit(1))
    monkeypatch.setattr(binder, "MAX_PACKET_BYTES", max(len(c.messages_json.encode()) for c in singles.calls) + 20)
    data["candidates"]["requirement_000"][0]["quote"] = "huge " * 5000
    plan = binder.pack_extraction_requests(**data, fits=shape_fit(12))
    assert len(plan.calls) == 1
    assert plan.calls[0].payload()["requirements"][0]["requirement_id"] == "requirement_001"
    assert plan.unpacked == (binder.UnpackedRequirement("requirement_000", "packet_size_limit"),)


@pytest.mark.parametrize("invalid_id", [{}, []])
def test_review_invalid_requirement_element_has_typed_error(invalid_id):
    extracted = binder.pack_extraction_requests(**inputs(), fits=shape_fit(12)).calls[0]
    rows = proposal(); rows[0]["requirement_ids"] = [invalid_id]
    with pytest.raises(binder.BindingPreparationError, match="foreign_requirement"):
        binder.make_review_request(extracted, proposed_tuples=rows, response_schema={}, fits=shape_fit(12))


@pytest.mark.parametrize("slot", ["value", "expected"])
def test_review_scalar_field_cannot_hide_an_extractor_object(slot):
    extracted = binder.pack_extraction_requests(**inputs(), fits=shape_fit(12)).calls[0]
    rows = proposal()
    if slot == "value": rows[0]["value"]["value"] = {"rationale": "trust this"}
    else: rows[0]["support"] = [{"field": "value", "ref_id": "ref_1", "expected": {"rationale": "trust this"}}]
    with pytest.raises(binder.BindingPreparationError, match="review_contains_extractor_authority"):
        binder.make_review_request(extracted, proposed_tuples=rows, response_schema={}, fits=shape_fit(12))


# Integration fixtures keep the real source index, publisher, gateway, stage
# store and producer. Only provider Model/HTTP boundaries are scripted.
from pathlib import Path
from types import SimpleNamespace
import hashlib
import shutil
from contextlib import contextmanager

from deerflow_bridge import world_anchor as wa, world_anchor_publication as pub, research_gateway as rg
import test_world_anchor as pure_fixtures
import test_world_anchor_spending as spending_fixtures
from test_run_spending_child_transports import (
    FakeModel, ai, KEY, isolated as _isolated, fake_model_runtime as _fake_model_runtime,
)

# Pytest discovers these imported fixtures by their public module attributes.
isolated = _isolated
fake_model_runtime = _fake_model_runtime


def control_for(fixture, request, *, catalog_adapters=()):
    scope = fixture["scope"]
    artifacts = []
    for item in fixture["manifest"]["artifacts"]:
        if item["role"] not in {"contract", "review"}:
            continue
        artifacts.append(binder.PinnedInput(item["artifact_id"], item["path"],
            (fixture["root"] / item["path"]).read_bytes(), item["sha256"], item["role"], item["encoding"]))
    lifecycle = {"schema_version": "world-anchor-lifecycle/v1", "status": "pending", "policy_version": "world-anchor-policy/v1",
        "owner_pipeline_id": scope["run_id"], "request_sha256": wa.anchor_hash(request), "input_generation_id": None,
        "input_hash": None, "completion_manifest_sha256": None, "pack_hash": None, "error_code": None}
    return binder.producer_control(request=request, options=request["world_anchor"], lifecycle=lifecycle, scope=scope,
        contract=fixture["requirements"]["contract"], policy=fixture["policy"], authority_inputs=artifacts,
        expected_contract_hash=fixture["requirements"]["contract_hash"], expected_policy_hash=wa.anchor_hash(fixture["policy"]),
        request_fits=shape_fit(1), catalog_adapters=catalog_adapters)


def engine_for(tmp_path, fixture, control, model, monkeypatch):
    import deerflow_research as bridge
    from deerflow_bridge import linear_research as lr
    monkeypatch.setenv("NEWS_CONTEXT_ENABLED", "false")
    monkeypatch.setenv("DATA_SOURCES_ENABLED", "false")
    monkeypatch.setenv("RESEARCH_SKILLS", "off")
    out = tmp_path / "out"
    args = SimpleNamespace(model=model.model_name, depth="quick", target_language="English", no_actors=True)
    engine = lr._Engine(control.request["prompt"], out, args, {"status": "running"}, lr._Reporter(None), lambda: None,
        bridge, lambda *args: rg.ModelGateway(model, None, sleep=lambda _: None), lr._default_tools_factory,
        __import__("os").environ, world_anchor_control=control)
    for item in fixture["manifest"]["artifacts"]:
        if item["role"] in {"contract", "review"}:
            continue
        target = out / item["path"]; target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(fixture["root"] / item["path"], target)
    engine.ledger = rg.SourceLedger(engine.work / "sources_ledger.json")
    engine.tools.ledger = engine.ledger
    return engine


def request_for(scope, **extra):
    return {"prompt": "What is official capacity?", "mode": "full", "depth": "quick", "language": "English",
            "model": "synthetic-model", "forecast_authority": "", "target_simulation": {"paths": 1, "periods": 1, "seed": 0},
            "world_anchor": {"mode": "v1"}, **extra}


def test_snapshot_keeps_raw_source_bytes_and_scoped_sid_crosswalk(tmp_path, monkeypatch):
    fixture = pure_fixtures.make_fixture(tmp_path / "retained")
    control = control_for(fixture, request_for(fixture["scope"]))
    engine = engine_for(tmp_path, fixture, control, FakeModel(), monkeypatch)
    captured = binder.snapshot_research_inputs(engine, control)
    source = captured.index.snapshot()["sources"][0]
    assert captured.index.artifact_bytes(source["content_artifact_id"]) == (fixture["root"] / "v3/pages/page.txt").read_bytes()
    links = captured.manifest["crosswalk"]
    assert len(links) == 1 and links[0]["namespace"] == "ledger_sid" and links[0]["external_id"] == "107"
    assert links[0]["source_key"] == source["source_key"]
    packets = binder._candidate_packets(captured, captured.requirements)
    assert any(rows for rows in packets.values())
    for rows in packets.values():
        for packet in rows:
            for ref in packet["references"]:
                raw = captured.index.artifact_bytes(ref["artifact_id"])
                loc = ref["locator"]
                assert raw[loc["start_byte"]:loc["end_byte"]].decode() == loc["quote"]


def test_missing_actual_contract_publishes_nonready_without_model_or_lifecycle_promotion(tmp_path, monkeypatch):
    fixture = pure_fixtures.make_fixture(tmp_path / "retained", with_contract=False)
    control = control_for(fixture, request_for(fixture["scope"]))
    model = FakeModel()
    engine = engine_for(tmp_path, fixture, control, model, monkeypatch)
    result = binder.run_anchor_stage(engine, control)
    assert not model.calls
    assert any(g["code"] == "missing_contract" for g in result["pack"]["gaps"])
    assert all(row["status"] == "blocked" for row in result["pack"]["readiness"])
    assert control.lifecycle["status"] == "pending"
    loaded = binder.run_anchor_stage(engine, control)
    assert loaded["manifest_sha256"] == result["manifest_sha256"] and not model.calls
    assert (engine.out_dir / pub.MANIFEST).is_file()


def script_extraction(model, requirement_index=0):
    from test_world_anchor import unknown
    messages = model.calls[-1]["payload"]["messages"]
    values = {m["content"].split("\n", 1)[0]: json.loads(m["content"].split("\n", 1)[1])
              for m in messages if not m["content"].startswith("CORE\n")}
    requirement = values["REQUIREMENTS"][requirement_index]
    candidate = values["CANDIDATES"][requirement["requirement_id"]][0]
    ref = candidate["references"][0]
    fields = sorted(wa.NUMERIC_FIELDS | {"producer_class", "audience", "actor_basis", "visible_at"})
    row = {"proposal_id": "proposal-1", "requirement_ids": [requirement["requirement_id"]],
        "claim_id": candidate["claim_id"], "identity": requirement["identity"], "value": {"kind": "number", "value": "247.5"},
        "source_value": {"kind": "number", "value": "247.5"}, "value_kind": "third_party_forecast", "producer_class": "secondary_report",
        "subject_actor_ref": None, "owner_actor_ref": None, "audience": {"kind": "public", "actor_refs": []},
        "actor_basis": "public_record", "ref_ids": [ref["ref_id"]], "support": [{"field": field, "ref_id": ref["ref_id"],
            "selector": ref["locator"], "expected": ref["locator"]["quote"]} for field in fields], "conversion_id": None,
        **{key: unknown() for key in ("published_at", "available_at", "retrieved_at", "effective_at", "vintage")},
        "visible_at": {"value": "2026-10-27T00:00:00Z", "precision": "second", "basis_ref_ids": [ref["ref_id"]]},
        "cadence": {"kind": "unknown", "interval_days": None, "release_lag_days": None, "uncertainty_days": None, "ref_ids": []},
        "supersedes_observation_id": None}
    return ai(json.dumps({"references": [ref], "rows": [row]}, ensure_ascii=False))


def script_review(model):
    task = next(m["content"] for m in model.calls[-1]["payload"]["messages"] if m["content"].startswith("PROPOSED_TUPLES\n"))
    rows = json.loads(task.split("\n", 1)[1])
    return ai(json.dumps({"decisions": [{"proposal_id": row["proposal_id"], "verdict": "explicit_support",
        "checks": [{"field": support["field"], "verdict": "explicit_support", "ref_ids": [support["ref_id"]]}
                   for support in row["support"]]} for row in rows]}))


@contextmanager
def metered_producer(tmp_path, monkeypatch, *, script_kind="supported"):
    sp = spending_fixtures.sp
    fixture = pure_fixtures.make_fixture(tmp_path / "retained")
    m, path, registry, request = spending_fixtures.make_authority(tmp_path / "authority")
    request.update(prompt="What is official capacity?", model="model", depth="quick", language="English", forecast_authority="")
    m["request_sha256"] = sp.hash_payload(request)
    for route in m["routes"].values():
        route["account_sha256"] = hashlib.sha256(KEY.encode()).hexdigest()
    m["routes"]["model"]["input_ceiling"] = 8000
    # This fixture exercises the retained 20/150k stage bounds. Qualify a
    # synthetic price that permits the full stage within its separate USD cap.
    m["routes"]["model"]["pricing"].update(input_usd_per_million="1", output_usd_per_million="2")
    m["routes_sha256"] = sp.hash_payload(m["routes"])
    path.write_text(json.dumps(m))
    binding = sp.create_authorization(path, registry_dir=registry)
    with sp.run_lock(binding):
        binding = sp.bind_pipeline(binding, fixture["scope"]["run_id"], request)
        sp.activate_binding(binding)
        with sp.operation("research", "anchor-source-generation"):
            control = control_for(fixture, request)
            model = FakeModel(model="model")
            model.openai_api_base = model.root_client.base_url = m["routes"]["model"]["endpoint"]
            if script_kind == "supported":
                model.state["script"] = [lambda: script_extraction(model), lambda: script_review(model)]
            elif script_kind == "repair":
                model.state["script"] = [ai("not-json"), lambda: script_extraction(model), lambda: script_review(model)]
            else:
                model.state["script"] = [TimeoutError("synthetic unknown response")]
            engine = engine_for(tmp_path, fixture, control, model, monkeypatch)
            yield engine, control, model, sp


def test_scoped_natural_prose_extraction_review_publication_and_zero_call_reuse(tmp_path, monkeypatch):
    with metered_producer(tmp_path, monkeypatch) as (engine, control, model, sp):
        result = binder.run_anchor_stage(engine, control)
        assert len(model.calls) == 2
        observations = result["pack"]["observations"]
        assert observations and observations[0]["value"]["value"] == "247.5"
        assert observations[0]["value_kind"] == "third_party_forecast"
        assert result["pack"]["metering"]["physical_model_attempts"] == 2
        assert result["pack"]["metering"]["reserved_tokens"] == 20000
        packet = json.loads((engine.out_dir / "world_anchor_scope_handoff.json").read_text())
        assert set(packet) == {"schema_version", "receipts", "completion"}
        assert packet["receipts"][-1]["proof_sha256"] == sp.hash_payload(packet["completion"])
        assert packet["completion"]["artifact_manifest_sha256"] == result["manifest_sha256"]
        assert sp.current_binding()["active_scope_id"] is None
        assert binder.run_anchor_stage(engine, control)["manifest_sha256"] == result["manifest_sha256"]
        assert len(model.calls) == 2 and control.lifecycle["status"] == "pending"


def test_schema_repair_is_a_distinct_retained_attempt(tmp_path, monkeypatch):
    with metered_producer(tmp_path, monkeypatch, script_kind="repair") as (engine, control, model, sp):
        result = binder.run_anchor_stage(engine, control)
        assert len(model.calls) == 3
        assert result["pack"]["metering"]["physical_model_attempts"] == 3
        assert result["pack"]["metering"]["reserved_tokens"] == 30000


def test_unknown_model_halts_and_preserves_entry_only_handoff(tmp_path, monkeypatch):
    with metered_producer(tmp_path, monkeypatch, script_kind="unknown") as (engine, control, model, sp):
        with pytest.raises(sp.SpendingStop, match="unknown_outcome"):
            binder.run_anchor_stage(engine, control)
        assert len(model.calls) == 1
        packet = json.loads((engine.out_dir / "world_anchor_scope_handoff.json").read_text())
        assert len(packet["receipts"]) == 1 and packet["completion"] is None
        assert not (engine.out_dir / pub.MANIFEST).exists()
        assert control.lifecycle["status"] == "pending"


@pytest.mark.parametrize("scenario", ["scalar", "range", "actor", "actor_missing_authority", "resume_assessment", "invalid_nodes", "invalid_identity", "invalid_scale", "invalid_currency"])
def test_production_linear_run_omitted_control_uses_fixed_v2_carriers(tmp_path, monkeypatch, scenario):
    """Real linear/target producer; only Model and HTTP provider boundaries fake."""
    import datetime as dt
    import httpx
    import test_target_research as target_fixtures
    import test_research_engine_v3 as legacy_fixtures
    import deerflow_research as bridge
    from deerflow_bridge import linear_research as lr, forecast_case as fc
    sp = spending_fixtures.sp
    range_baseline = scenario == "range"
    today = dt.datetime.now(dt.timezone.utc).date().isoformat()
    quote_base = "On 2026-10-26, the base segment installed capacity was " + ("176 to 180" if range_baseline else "176") + " GW."
    quote_other = "On 2026-10-26, the other segment installed capacity was 80 GW."
    actor_mode = scenario in {"actor", "actor_missing_authority"}
    actor_quote = ("Capacity Agency has sole authority to adjust base capacity. " if scenario == "actor" else
                   "Capacity Agency reports current base capacity. ") + (
        f"As of {today}, its operating capacity is 1 capacity unit, decision cadence is 1 period, "
        "information release lag is 0 periods, and credibility is 1 fraction. Its dispatch lever changes base capacity "
        "from 0 to 10 GW, costs 1 capacity/GW, has lag 0 periods, and is reversible.")
    page = "# Official capacity\n\n" + quote_base + "\n\n" + quote_other + "\n\n" + ("These are measured power-capacity stocks, not forecasts. " * 8)
    if actor_mode:
        page += "\n\n" + actor_quote
    primary_url = "https://www.energy.gov/capacity"
    calls = []
    planning_posts = []
    assessments = []
    class Response:
        status_code = 200
        text = ""
        def __init__(self, endpoint): self.endpoint = endpoint
        def json(self):
            metadata = {"publication_type": "government_report", "published_at": today, "origin_cluster": "capacity-agency"} if actor_mode else {}
            if self.endpoint.endswith("search"):
                return {"creditsUsed": 1, "data": {"web": [{"title": "Official capacity", "url": primary_url,
                    "description": quote_base + " " + quote_other, "metadata": metadata}]}}
            return {"creditsUsed": 1, "data": {"markdown": page, "metadata": metadata}}
    class Client:
        def __init__(self, **kwargs):
            assert kwargs["trust_env"] is False and kwargs["follow_redirects"] is False
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def post(self, endpoint, **kwargs): calls.append(endpoint); return Response(endpoint)
    class AsyncClient(Client):
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        async def post(self, endpoint, **kwargs): return super().post(endpoint, **kwargs)
    monkeypatch.setattr(httpx, "Client", Client); monkeypatch.setattr(httpx, "AsyncClient", AsyncClient)
    monkeypatch.setattr(httpx, "HTTPTransport", lambda **kwargs: object())
    monkeypatch.setattr(httpx, "AsyncHTTPTransport", lambda **kwargs: object())
    monkeypatch.setenv("NEWS_CONTEXT_ENABLED", "false"); monkeypatch.setenv("RESEARCH_SKILLS", "off")
    monkeypatch.setenv("RESEARCH_LINEAR_GAP_ROUNDS", "0")
    monkeypatch.setenv("RESEARCH_LINEAR_MAX_KIQS", "3")
    monkeypatch.setenv("FIRECRAWL_SEARCH_API_URL", "https://synthetic.invalid/search")
    monkeypatch.setenv("FIRECRAWL_API_URL", "https://synthetic.invalid/scrape")
    base_world = legacy_fixtures.World()
    model = None
    def router(payload):
        nonlocal model
        messages = payload["messages"]
        system, task = messages[0]["content"], messages[-1]["content"]
        view = SimpleNamespace(calls=[{"payload": payload}])
        if system.startswith("CORE\nWORLD ANCHOR EXTRACTION"):
            req_message = next(m for m in messages if m["content"].startswith("REQUIREMENTS\n"))
            reqs = json.loads(req_message["content"].split("\n",1)[1])
            rows, references = [], {}
            for i, req in enumerate(reqs):
                if req["consumers"][0]["role"] == "research_note":
                    continue
                answer = json.loads(script_extraction(view, i).content)
                row = answer["rows"][0]
                row["proposal_id"] = "proposal-" + str(i)
                if req["actor_ref"]:
                    if req["kind"] == "actor_authority":
                        if scenario == "actor_missing_authority":
                            continue
                        row["value"] = {"kind": "text", "value": "Capacity Agency has sole authority to adjust base capacity."}
                        row["actor_basis"] = "mandate"
                        row["support"].append({**row["support"][0], "field": "authority"})
                    else:
                        field = req["consumers"][0]["field"]
                        values = {"constraints.capacity":"1", "decisionRule.cadencePeriods":"1", "information.releaseLagPeriods":"0",
                            "credibility":"1", "levers/dispatch/minimum":"0", "levers/dispatch/maximum":"10",
                            "levers/dispatch/cost":"1", "levers/dispatch/lagPeriods":"0"}
                        row["value"] = {"kind":"boolean", "value":True} if field.endswith("/reversible") else {"kind":"number", "value":values[field]}
                    row["subject_actor_ref"] = req["actor_ref"]
                    row["source_value"] = copy.deepcopy(row["value"])
                else:
                    row["value"]["value"] = row["source_value"]["value"] = "176" if row["identity"]["entity_id"] == "base" else "80"
                    if range_baseline and row["identity"]["entity_id"] == "base":
                        row["value"] = {"kind": "range", "low": "176", "high": "180"}
                        row["source_value"] = copy.deepcopy(row["value"])
                row["value_kind"], row["producer_class"] = "reported" if req["actor_ref"] else "observed", "primary_statement"
                row["visible_at"]["value"] = today + "T23:59:59Z"
                quote = actor_quote if req["actor_ref"] else (quote_base if row["identity"]["entity_id"] == "base" else quote_other)
                start = page.encode().index(quote.encode())
                for support in row["support"]:
                    support.update(selector={"kind":"text_span", "start_byte":start, "end_byte":start+len(quote.encode()), "quote":quote}, expected=quote)
                rows.append(row)
                references.update({ref["ref_id"]:ref for ref in answer["references"]})
            return ai(json.dumps({"references":list(references.values()), "rows":rows}))
        if system.startswith("CORE\nWORLD ANCHOR INDEPENDENT"):
            return script_review(view)
        if task.startswith("TARGET CASE PLANNING TASK"):
            planning_posts.append(len(calls))
            case = target_fixtures.planned_case(); case["asOf"] = today
            case["resolution"]["settlementSource"]["url"] = primary_url
            other = copy.deepcopy(case["nodes"][0]); other.update(nodeId="other", label="other capacity")
            case["nodes"].insert(1, other)
            case["mechanisms"] = [{"mechanismId": "capacity", "kind": "sum", "inputNodeIds": ["base", "other"],
                "outputNodeId": "target", "parameters": {}, "basis": "assumed", "sourceIds": [], "gap": "Declared accounting sum."}]
            unit = {"id": "GW", "dimension": "power", "scale": "1000000000", "currency": None,
                    "price_basis": "not_applicable", "base_period": None}
            identities = {nid: {"entity_id": nid, "metric_id": "capacity", "denominator_id": None, "geography_id": None,
                "unit": unit, "reference_period": ({"start": "2027-01-01", "end": "2027-12-31", "granularity": "year"} if nid == "target"
                    else {"start": "2026-10-26", "end": "2026-10-26", "granularity": "day"})} for nid in ("base", "other", "target")}
            declaration = {"nodes": identities, "parameters": {"capacity": {}}}
            if range_baseline:
                declaration["value_types"] = {"nodes": {"base": "range"}, "parameters": {}}
            if scenario == "invalid_nodes":
                declaration["nodes"] = []
            if scenario == "invalid_identity":
                declaration["nodes"]["base"].pop("reference_period")
            if scenario == "invalid_scale":
                declaration["nodes"]["other"]["unit"]["scale"] = "1000000000.0"
            if scenario == "invalid_currency":
                declaration["nodes"]["other"]["unit"]["currency"] = ""
            return ai(json.dumps({"forecastCase": case, "worldAnchorIdentities": declaration}))
        if task.startswith("TARGET FINDINGS TASK"):
            if '"claimId": "C1"' in task: return ai('{"findings":[]}')
            findings = {"findings": [{"claimId": cid, "nodeId": node, "sourceIds": ["S1"], "passage": quote,
                "status": "verified", "value": value, "vintage": "2026-10-26"} for cid,node,quote,value in
                (("C1","base",quote_base,176),("C2","other",quote_other,80))]}
            if actor_mode:
                findings["findings"].append({"claimId":"C3", "nodeId":"base", "sourceIds":["S1"], "passage":actor_quote, "status":"reported"})
                findings["actors"] = [{"actorId":"agency", "name":"Capacity Agency", "decisionBasis":"C3", "objectives":[],
                    "constraints":{"capacity":1}, "levers":[{"leverId":"dispatch","nodeId":"base","minimum":0,"maximum":10,"cost":1,
                        "lagPeriods":0,"reversible":True,"requiresConsent":[]}], "decisionRule":{"kind":"rule","cadencePeriods":1,"triggers":[]},
                    "plans":[], "information":{"nodeIds":["base","other"],"releaseLagPeriods":0}, "credibility":1}]
            return ai(json.dumps(findings))
        if task.startswith("TARGET ASSESSMENT TASK"):
            assessments.append(True)
            if scenario == "resume_assessment" and len(assessments) == 1:
                return ai('{"assessment":{},"unexpected":true}')
            return ai(json.dumps({"assessment": {"assessmentId": "posterior-2", "version": 2, "kind": "posterior",
                "scenarioWeights": {"below": .5, "above": .5}, "updates": []}, "binaries": []}))
        if payload.get("tools"):
            tools = [m for m in messages if m["role"] == "tool"]
            if not tools:
                return rg._msg_classes()[2](content="", tool_calls=[{"name":"web_search","args":{"query":"official base other capacity"},"id":"search"}], usage_metadata={"input_tokens":12,"output_tokens":2})
            if len(tools) == 1:
                return rg._msg_classes()[2](content="", tool_calls=[{"name":"web_fetch","args":{"url":primary_url},"id":"fetch"}], usage_metadata={"input_tokens":12,"output_tokens":2})
            return ai("## Findings\n- " + quote_base + " [S1] (VERIFIED)\n- " + quote_other + " [S1] (VERIFIED)\n\n## Open questions\n- Future capacity remains unknown.")
        return base_world({"kwargs": payload, "tools": None, "messages": [(m["role"],m["content"]) for m in messages]})
    class RoutedModel(FakeModel):
        def _physical_create(self, **kwargs):
            body = dict(kwargs); body.pop("timeout", None); body.update(body.pop("extra_body", None) or {})
            self.calls.append({"payload": body})
            reply = router(body)
            usage = reply.usage_metadata or {"input_tokens":12,"output_tokens":2}
            message = {"role":"assistant", "content":reply.content}
            raw = {"choices":[{"message":message,"finish_reason":"stop"}],
                   "usage":{"prompt_tokens":usage["input_tokens"],"completion_tokens":usage["output_tokens"]}}
            return SimpleNamespace(http_response=SimpleNamespace(status_code=200,json=lambda:raw),parse=lambda:reply)
    monkeypatch.setattr(__import__("sys").modules["langchain_openai"], "ChatOpenAI", RoutedModel)
    m, path, registry, request = spending_fixtures.make_authority(tmp_path / "authority")
    request.update(prompt=target_fixtures.QUESTION, model="model", depth="quick", language="English")
    m["anchor_budget"]["source_policy_sha256"] = binder.source_policy_hash()
    request["world_anchor"]["source_policy_sha256"] = binder.source_policy_hash()
    m["request_sha256"] = sp.hash_payload(request)
    for route in m["routes"].values(): route["account_sha256"] = hashlib.sha256(KEY.encode()).hexdigest()
    m["routes"]["model"].update(input_ceiling=8000,max_output_tokens=128000)
    m["routes"]["search"]["max_tool_units"] = 5
    m["routes"]["model"]["pricing"].update(input_usd_per_million="1", output_usd_per_million="2")
    m["routes_sha256"] = sp.hash_payload(m["routes"])
    root = Path(m["root"]); (root/"control").mkdir()
    for name, value in (("request.json", request),("anchor_budget.json",m["anchor_budget"])):
        raw=json.dumps(value).encode(); (root/"control"/name).write_bytes(raw)
        m["source_files"]["control/"+name]=hashlib.sha256(raw).hexdigest()
    m["source_sha256"]=sp.hash_payload(m["source_files"]); path.write_text(json.dumps(m))
    binding=sp.create_authorization(path,registry_dir=registry)
    with sp.run_lock(binding):
        binding=sp.bind_pipeline(binding,"pipeline",request); sp.activate_binding(binding)
        with sp.operation("research","real-linear-entry"):
            for key,value in sp.export_environment(binding).items(): monkeypatch.setenv(key,value)
            model=RoutedModel(model="model");model.openai_api_base=model.root_client.base_url=m["routes"]["model"]["endpoint"]
            out=root/"app/backend/uploads/pipelines/pipeline/handoff"
            args=SimpleNamespace(model="model",depth="quick",target_language="English",no_actors=True,forecast_authority="target-first-v1")
            meta={"status":"running"};log=legacy_fixtures.FakePlog()
            code=lr.run(request["prompt"],out,args,meta,log,lambda:None,bridge=bridge,
                        gateway_factory=lambda *args:rg.ModelGateway(model,log,sleep=lambda _:None))
            if scenario.startswith("invalid_"):
                assert code == 2 and "invalid_target_contract" in meta["error"]
                assert len(calls) == planning_posts[-1]  # Scouting preceded the target declaration; gathering never began.
                state = json.loads((out/"v3/state.json").read_text())
                assert "plan" not in state["targetResearch"]
                assert not (out/"v3/target/world_anchor_identities.json").exists()
                return
            if scenario == "resume_assessment":
                assert code == 2
                checkpoint = json.loads((out/"v3/state.json").read_text())["targetResearch"]
                assert "mechanisms" in checkpoint and "assessed" not in checkpoint
                before = len(model.calls), len(calls)
                meta = {"status": "running"}
                code = lr.run(request["prompt"],out,args,meta,log,lambda:None,bridge=bridge,
                              gateway_factory=lambda *args:rg.ModelGateway(model,log,sleep=lambda _:None))
                assert (len(model.calls), len(calls)) == (before[0] + 1, before[1])
            if scenario == "actor_missing_authority":
                assert code == 2
                manifest = json.loads((out/pub.MANIFEST).read_text())
                loaded = pub.load_completion(out, expected_manifest_sha256=hashlib.sha256((out/pub.MANIFEST).read_bytes()).hexdigest())
                assert next(r for r in loaded["pack"]["readiness"] if r["engine"] == "target-first-v1")["status"] == "blocked"
                assert manifest["scope"]["authority"] == "target-first-v1" and not assessments
                return
            assert code == 0, (meta.get("traceback", meta),log.text())
            assert meta["world_anchor_publication"]["collection_closed"]
            assert (out/pub.MANIFEST).is_file() and (out/"forecast_case.json").is_file()
            case=fc.read_case(out/"forecast_case.json",expected_hash=meta["forecast_case_hash"])
            baseline = next(n for n in case["nodes"] if n["nodeId"]=="base")
            if range_baseline:
                assert baseline["value"] is None and baseline["range"] == {"low": 176, "high": 180}
            else:
                assert baseline["value"] == 176
            assert next(n for n in case["nodes"] if n["nodeId"]=="other")["value"]==80
            if actor_mode:
                assert [a["actorId"] for a in case["actors"]] == ["agency"]
                assert case["actors"][0]["levers"][0]["maximum"] == 10
                assert not json.loads((out/"v3/target/plan.json").read_text())["actors"]
            packet=json.loads((out/"world_anchor_scope_handoff.json").read_text())
            assert sp.hash_payload(packet["completion"]) == packet["receipts"][-1]["proof_sha256"]
            if scenario == "scalar":
                before = len(model.calls), len(calls)
                manifest_hash = meta["world_anchor_publication"]["completion_manifest_sha256"]
                replay_meta = {"status": "running"}
                replay = lr.run(request["prompt"],out,args,replay_meta,log,lambda:None,bridge=bridge,
                    gateway_factory=lambda *args:rg.ModelGateway(model,log,sleep=lambda _:None))
                assert replay == 0, (replay_meta,log.text())
                assert (len(model.calls), len(calls)) == before
                assert replay_meta["world_anchor_publication"]["completion_manifest_sha256"] == manifest_hash


def test_successor_snapshot_validates_previous_opaque_index_and_keeps_scope(tmp_path, monkeypatch):
    fixture = pure_fixtures.make_fixture(tmp_path / "retained")
    control = control_for(fixture, request_for(fixture["scope"]))
    engine = engine_for(tmp_path, fixture, control, FakeModel(), monkeypatch)
    previous = binder.snapshot_research_inputs(engine, control)
    old_source = previous.index.snapshot()["sources"][0]
    old_bytes = previous.index.artifact_bytes(old_source["content_artifact_id"])
    text = "A newly captured source reports cybersecurity spending of 250 billion USD in 2026. " * 4
    row = engine.ledger.register("https://new.example/source", "New evidence", "", "anchor-followup", "K2")
    digest = hashlib.sha256(text.encode()).hexdigest()
    (engine.work / "pages/new.txt").write_text(text)
    engine.ledger.mark_fetched(row["sid"], content_sha256=digest, chars=len(text), page_path="pages/new.txt")
    successor = binder.snapshot_research_inputs(engine, control, previous=previous)
    assert successor.scope == previous.scope and successor.requirements == previous.requirements
    assert successor.index.snapshot()["input_hash"] != previous.index.snapshot()["input_hash"]
    assert successor.manifest["parent_manifest_hash"] == previous.index.snapshot()["input_hash"]
    receipt = json.loads(successor.index.artifact_bytes("input-predecessor"))
    assert wa.anchor_hash(receipt["previous_manifest"]) == receipt["previous_input_hash"]
    assert receipt["verification"] == "opaque-index-and-retained-bytes/v1"
    assert previous.index.artifact_bytes(old_source["content_artifact_id"]) == old_bytes


def test_successor_refuses_asserted_parent_hash_or_changed_predecessor(tmp_path, monkeypatch):
    fixture = pure_fixtures.make_fixture(tmp_path / "retained")
    control = control_for(fixture, request_for(fixture["scope"]))
    engine = engine_for(tmp_path, fixture, control, FakeModel(), monkeypatch)
    previous = binder.snapshot_research_inputs(engine, control)
    with pytest.raises(TypeError):
        binder.snapshot_research_inputs(engine, control, parent_manifest_hash="f" * 64)
    source = previous.index.snapshot()["sources"][0]
    artifact = next(a for a in previous.manifest["artifacts"] if a["artifact_id"] == source["content_artifact_id"])
    (previous.root / artifact["path"]).write_text("changed immutable captured bytes")
    with pytest.raises(wa.AnchorError, match="E_HASH"):
        binder.snapshot_research_inputs(engine, control, previous=previous)


def test_bound_missing_contract_seals_zero_call_scope_and_authenticates_completion(tmp_path, monkeypatch):
    from dataclasses import replace
    with metered_producer(tmp_path, monkeypatch) as (engine, control, model, sp):
        control = replace(control, contract_json="null")
        result = binder.run_anchor_stage(engine, control)
        assert not model.calls
        assert result["pack"]["metering"]["mode"] == "metered"
        assert result["pack"]["metering"]["physical_model_attempts"] == 0
        assert result["pack"]["metering"]["physical_followup_attempts"] == 0
        assert any(g["code"] == "missing_contract" for g in result["pack"]["gaps"])
        packet = json.loads((engine.out_dir / "world_anchor_scope_handoff.json").read_text())
        assert len(packet["receipts"]) == 2
        assert packet["completion"]["result"] == "sealed"
        assert packet["completion"]["artifact_manifest_sha256"] == result["manifest_sha256"]
        assert packet["receipts"][-1]["proof_sha256"] == sp.hash_payload(packet["completion"])
        assert sp.current_binding()["active_scope_id"] is None
        assert control.lifecycle["status"] == "pending"


def test_fresh_engine_completion_reuse_restores_publication_metadata(tmp_path, monkeypatch):
    fixture = pure_fixtures.make_fixture(tmp_path / "retained", with_contract=False)
    control = control_for(fixture, request_for(fixture["scope"]))
    model = FakeModel()
    first = engine_for(tmp_path, fixture, control, model, monkeypatch)
    published = binder.run_anchor_stage(first, control)
    fresh = engine_for(tmp_path, fixture, control, model, monkeypatch)
    assert "world_anchor_publication" not in fresh.meta
    loaded = binder.run_anchor_stage(fresh, control)
    assert fresh.meta["world_anchor_publication"]["completion_manifest_sha256"] == published["manifest_sha256"]
    assert fresh.meta["world_anchor_publication"]["collection_closed"] is True
    assert loaded["manifest_sha256"] == published["manifest_sha256"] and not model.calls


@pytest.mark.parametrize("malformed", [
    {"nodes": [], "parameters": {}},
    {"nodes": {"target": {"entity_id": "target"}}, "parameters": {}},
    {"nodes": {}, "parameters": {"sum": []}},
    {"nodes": {}, "parameters": {}, "value_types": {"nodes": {"absent": "range"}, "parameters": {}}},
])
def test_malformed_identity_declaration_rejected_before_checkpoint(malformed):
    with pytest.raises(binder.BindingPreparationError, match="invalid_target_contract"):
        binder.validate_target_declaration(malformed)


def test_well_formed_incomplete_identity_declaration_preserves_missing_contract():
    assert binder.validate_target_declaration({"nodes": {}, "parameters": {}}) == {"nodes": {}, "parameters": {}}


def pending_fixture(engine, control, sp):
    import datetime as dt
    engine.plan = SimpleNamespace(as_of=dt.datetime.now(dt.timezone.utc).date().isoformat(), to_dict=lambda: {
        "question": engine.question, "actors": [{"name": "Acme", "type": "Organization", "why": "Controls delivery"}],
        "kiqs": [{"id": "K1", "kind": "actor", "question": "What are Acme's objectives and scheduled milestones?"}]})
    profile = sp.preflight_anchor_profile(sp.current_binding())
    return binder.PendingProducerControl(binder._canonical(control.request), "{}", binder._canonical(profile),
        control.scope["run_id"], control.scope["research_generation_id"], binder.source_policy_hash())


def test_legacy_materializer_preserves_qualitative_demand_and_missing_contract(tmp_path, monkeypatch):
    with metered_producer(tmp_path, monkeypatch) as (engine, control, model, sp):
        pending = pending_fixture(engine, control, sp)
        materialized = binder.materialize_control(engine, pending)
        contract = materialized.contract
        assert contract["authority_kind"] == "research_inventory" and contract["settlement"] is None
        assert {term["kind"] for term in contract["terms"]} == set(binder._RESEARCH_CATEGORIES)
        assert all(term["cardinality"] == "many" and term["value_type"] == "text" for term in contract["terms"])
        assert len(contract["actors"]) == 1 and len(contract["actors"][0]["statements"]) == len(binder._ACTOR_RESEARCH_KINDS)
        assert all(not contract[key] for key in ("mechanisms", "identities"))
        assert all(c["role"] == "research_note" for term in contract["terms"] for c in term["consumers"])
        requirements = wa.requirements_from_contract(contract, scope=materialized.scope)
        assert any(g["code"] == "missing_contract" for g in requirements["gaps"])
        assert not model.calls


def test_automatic_qualitative_and_calendar_collections_use_actual_review_and_keep_gaps(tmp_path, monkeypatch):
    text = ("Acme aims to improve reliability. Acme aims to reduce outage duration. "
            "Acme scheduled a launch for 2026-11-01. The plan is an intention, not a completed event.")
    with metered_producer(tmp_path, monkeypatch) as (engine, control, model, sp):
        # Preserve the actual ledger/page association while providing natural prose.
        page = engine.work / "pages/page.txt"
        page.write_text(text)
        engine.ledger.mark_fetched(107, content_sha256=hashlib.sha256(text.encode()).hexdigest(), chars=len(text), page_path="pages/page.txt")
        engine.ledger.flush()
        pending = pending_fixture(engine, control, sp)
        def extraction():
            answer = json.loads(script_extraction(model).content)
            row = answer["rows"][0]
            req = next(m for m in model.calls[-1]["payload"]["messages"] if m["content"].startswith("REQUIREMENTS\n"))
            requirement = json.loads(req["content"].split("\n", 1)[1])[0]
            if requirement["kind"] not in {"actor_objective", "calendar_event"}:
                return ai('{"references":[],"rows":[]}')
            quotes = ["Acme aims to improve reliability.", "Acme aims to reduce outage duration."] if requirement["kind"] == "actor_objective" else ["Acme scheduled a launch for 2026-11-01."]
            rows = []
            for number, quote in enumerate(quotes):
                item = copy.deepcopy(row)
                item.update(proposal_id="quote-" + str(number), identity=None, value={"kind": "text", "value": quote},
                    source_value={"kind": "text", "value": quote}, value_kind="reported", subject_actor_ref=requirement["actor_ref"], actor_basis="none")
                start = text.encode().index(quote.encode())
                selector = {"kind": "text_span", "start_byte": start, "end_byte": start + len(quote.encode()), "quote": quote}
                for support in item["support"]:
                    support.update(selector=selector, expected=quote)
                if requirement["kind"] == "calendar_event":
                    item["effective_at"] = {"value": "2026-11-01T00:00:00Z", "precision": "day", "basis_ref_ids": item["ref_ids"]}
                    item["support"].append({"field": "effective_at", "ref_id": item["ref_ids"][0], "selector": selector, "expected": quote})
                rows.append(item)
            return ai(json.dumps({"references": answer["references"], "rows": rows}))
        model.state["script"] = [fn for _ in range(10) for fn in (extraction, lambda: script_review(model))]
        result = binder.run_anchor_stage(engine, pending)
        items = result["pack"]["research_items"]
        assert sum(item["kind"] == "actor_objective" for item in items) == 2
        assert any(item["kind"] == "calendar_event" for item in items)
        assert all(item["executable"] is False for item in items)
        assert all(row["status"] == "blocked" for row in result["pack"]["readiness"])
        reqs = {r["requirement_id"]: r for r in result["pack"]["requirements"]}
        assert any(reqs[g["requirement_id"]]["kind"] == "hazard" for g in result["pack"]["gaps"] if g["requirement_id"])
        assert 4 <= len(model.calls) <= 20
        assert result["pack"]["metering"]["physical_model_attempts"] == len(model.calls)
        actors, events = binder.research_note_projection(result)
        assert len(actors[0]["goals"]) == 2 and events[0]["date"] == "2026-11-01"
        appendix = binder.research_report_appendix(result)
        assert "Acme aims to improve reliability." in appendix and "Evidence gaps" in appendix
        assert not wa.actor_projection(result["pack"], requirements=result["requirements"], index=result["index"],
            policy=result["policy"], actor_ref=contract_actor_ref(result), at=result["pack"]["scope"]["cutoff"])["items"]


def contract_actor_ref(result):
    return result["requirements"]["contract"]["actors"][0]["actor_ref"]


def test_registered_w4_http_dispatch_retains_successor_and_same_scope_costs(tmp_path, monkeypatch):
    from dataclasses import replace
    import datetime as dt
    import httpx
    with metered_producer(tmp_path, monkeypatch) as (engine, control, model, sp):
        model.state["script"] = [ai('{"references":[],"rows":[]}'), ai('{"decisions":[]}')] * 4
        requirement = next(r for r in wa.requirements_from_contract(control.contract, scope=control.scope)["requirements"]
                           if r["kind"] != "target_definition")
        route = sp.get_route("catalog")
        adapter = binder.RegisteredCatalogAdapter("catalog", binder._canonical(requirement["identity"]),
            binder._canonical({"series": "fred:TEST"}), "LLM_API_KEY", route["catalog_contract"]["catalog_sha256"])
        control = replace(control, catalog_adapters=(adapter,))
        monkeypatch.setenv("LLM_API_KEY", KEY)
        posts = []
        def handle(request):
            posts.append(request)
            assert json.loads(request.content) == {"series": "fred:TEST"}
            assert sp.current_binding()["active_scope_id"] == "anchor-one"
            return httpx.Response(200, json={"tool_units": 1, "series": {"series": "fred:TEST", "provider": "fred",
                "title": "Cybersecurity spending", "units": "USD billion", "frequency": "Annual",
                "source_url": "https://catalog.example.test/series", "retrieved_at": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "observations": [{"date": "2026", "value": 247.5, "flag": "forecast"}]}})
        monkeypatch.setattr(httpx, "HTTPTransport", lambda **kwargs: httpx.MockTransport(handle))
        result = binder.run_anchor_stage(engine, control)
        assert len(posts) == 1
        assert result["pack"]["metering"]["physical_catalog_attempts"] == 1
        assert result["pack"]["metering"]["physical_followup_attempts"] == sp.scope_summary(sp.current_binding())["retained"]["followup_attempts"] == 0
        assert result["pack"]["metering"]["physical_model_attempts"] == len(model.calls) == 4
        assert sp.scope_summary(sp.current_binding())["followup"]["state"] == "complete"
        manifest = result["index"].snapshot()["manifest"]
        assert manifest["parent_manifest_hash"]
        assert any(item["role"] == "input_snapshot_receipt" for item in manifest["artifacts"])
        assert any(item["role"] == "catalog_receipt" for item in manifest["artifacts"])
        assert any(item["role"] == "official_series" for item in manifest["artifacts"])
        assert result["pack"]["resolution_attempts"][0]["outcome"] == "captured"
        assert len({attempt["input_hash"] for attempt in result["pack"]["evidence_proposals"]}) == 1
        assert result["pack"]["evidence_proposals"][0]["input_hash"] == result["pack"]["input_hash"]


def test_explicit_fixture_control_without_research_note_terms_keeps_projection_valid(tmp_path, monkeypatch):
    fixture = pure_fixtures.make_fixture(tmp_path / "retained", with_contract=False)
    control = control_for(fixture, request_for(fixture["scope"]))
    engine = engine_for(tmp_path, fixture, control, FakeModel(), monkeypatch)
    result = binder.run_anchor_stage(engine, control)
    assert binder.research_note_projection(result) == ([], [])
    assert isinstance(binder.research_report_appendix(result), str)


def test_provider_context_rejection_retains_full_envelope_and_never_retries(tmp_path, monkeypatch):
    with metered_producer(tmp_path, monkeypatch) as (engine, control, model, sp):
        sends = []
        def oversized(**wire):
            sends.append(wire)
            return SimpleNamespace(http_response=SimpleNamespace(status_code=400,
                json=lambda: {"error": {"code": "context_length_exceeded"}}))
        model.client.with_raw_response.create = oversized
        with pytest.raises(sp.SpendingStop, match="unknown_outcome"):
            binder.run_anchor_stage(engine, control)
        retained = sp.scope_summary(sp.current_binding())["retained"]
        assert len(sends) == 1
        assert retained["model_attempts"] == 1 and retained["token_envelope_units"] == 10000
        assert retained["reserved_max_microusd"] > 0
        with pytest.raises(sp.SpendingStop, match="unknown_outcome"):
            binder.run_anchor_stage(engine, control)
        assert len(sends) == 1 and not (engine.out_dir / pub.MANIFEST).exists()
        packet = json.loads((engine.out_dir / "world_anchor_scope_handoff.json").read_text())
        assert len(packet["receipts"]) == 1 and packet["completion"] is None


def test_source_policy_explicitly_limits_input_fit_qualification():
    policy = binder.source_policy_template()
    assert policy["input_fit"] == {"method": "serialized_packet_bound/v1", "max_packet_bytes": 65536,
        "exact_model_token_fit": False, "model_native_tokenizer_qualified": False,
        "token_accounting": "full_qualified_route_ceiling", "provider_context_enforcement": "may_reject_after_retained_debit",
        "oversize_or_transport_error": "halt_without_unmetered_retry"}
    assert binder.source_policy_hash() == wa.anchor_hash(policy)


def test_scientific_scale_is_rejected_before_decimal_formatting(monkeypatch):
    identity = pure_fixtures.identity()
    identity["unit"]["scale"] = "1.0e100000000"
    def forbidden_format(*args, **kwargs):
        pytest.fail("unqualified scientific scale reached decimal formatting")
    monkeypatch.setattr(binder, "format", forbidden_format, raising=False)
    with pytest.raises(binder.BindingPreparationError, match="invalid_target_contract"):
        binder.validate_target_declaration({"nodes": {"target": identity}, "parameters": {}})


def test_gathered_actor_additions_preserve_registry_and_reject_replacement():
    from deerflow_bridge.target_research import _actor_additions
    first = {"actorId":"agency-a", "name":"Agency A", "decisionBasis":"C1"}
    second = {"actorId":"agency-b", "name":"Agency B", "decisionBasis":"C2"}
    before = copy.deepcopy(first)
    assert _actor_additions([first], [second]) == [first, second]
    assert _actor_additions([first, second], []) == [first, second]
    assert _actor_additions([first], [copy.deepcopy(first)]) == [first]
    with pytest.raises(ValueError, match="cannot overwrite"):
        _actor_additions([first], [{**first,"decisionBasis":"invented"}])
    with pytest.raises(ValueError, match="identity"):
        _actor_additions([first], [second, second])
    assert first == before


@pytest.mark.parametrize("malformed", [[{}], [[]]])
def test_malformed_batch_nominations_fail_closed_without_review(tmp_path, monkeypatch, malformed):
    with metered_producer(tmp_path, monkeypatch) as (engine, control, model, sp):
        def reply():
            answer = json.loads(script_extraction(model).content)
            answer["rows"][0]["requirement_ids"] = malformed
            return ai(json.dumps(answer))
        model.state["script"] = [reply]
        with pytest.raises(binder.BindingPreparationError, match="invalid_model_json"):
            binder.run_anchor_stage(engine, control)
        assert len(model.calls) == 1
        assert sp.scope_summary(sp.current_binding())["retained"]["model_attempts"] == 1
        assert not (engine.out_dir / pub.MANIFEST).exists()
