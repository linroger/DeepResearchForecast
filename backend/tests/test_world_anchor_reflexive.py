"""Guarded World Anchor config/seed/runtime/actual actor payload acceptance."""

from copy import deepcopy
import asyncio
import hashlib
import json
import os
from pathlib import Path
import random

import pytest

from app.services.world_model import WorldModel
from app.services.world_model_seed import build_world_model_seed
from test_agency_classification import _entity, _generate, _generator
from test_target_simulation import case as _target_case

target_case = _target_case


def _anchored_fixture(tmp_path, target_case, *, hidden="DENIED_ANALYST", temporal=True, mechanism_rule=True,
                      contract_edit=None, policy_edit=None, mechanism_kind="sum", bind_parameters=True):
    """Real index/review/binding/host-context APIs over explicitly scripted source bytes."""
    from test_world_anchor import make_fixture, review_fixture, receipt_fixture, build_pack, dump, digest, identity, consumer
    from app.services.official_data import bridge_module
    from app.services.world_anchor import load_research_anchor, bind_actor_cast
    # Host and bridge consumers must share the same opaque EvidenceIndex issuer.
    wa = bridge_module("world_anchor")
    import test_world_anchor as fixtures
    original_api = fixtures.wa
    fixtures.wa = wa
    try:
        page = ("Synthetic evidence: baseline 247.5 USD billion for 2026, a third-party forecast. "
                "Acme states ACTOR_KNOWN_EXPANSION. Scheduled rule starts 2026-11-01 and adds 10 units. "
                "Hazard process rate 0.01 per day; recurring false; effect adds 2 units. Indicator threshold 250 units. "
                "An alternative additive operand is 10 USD million. A dimensional multiplier is 2 USD billion. "
                "An admitted dimensionless multiplier is 2. "
                "Coefficient 1 is dimensionless; intercept 0 USD billion. "
                "The adopted baseline is 100 USD billion, and its adoption rate is 0.01 per period. " + hidden)
        f = make_fixture(tmp_path / "source", page=page)
        contract = deepcopy(f["requirements"]["contract"])
        contract["terms"][0]["consumers"] = [consumer("oasis-legacy", "initial_state", "target", "value")]
        contract["mechanisms"] = [{"mechanism_id": "sum", "template": mechanism_kind, "template_version": "v1",
            "input_node_ids": ["baseline"], "output_node_id": "target", "parameters": [],
            "lag_requirement_origin": None, "applicability_requirement_origins": [],
            "consumers": [consumer("oasis-legacy", "mechanism", "target", "value")]}]
        contract["actors"] = [{"actor_ref": "acme", "registry_artifact_id": "contract", "registry_pointer": "/actor_registry/0",
                               "statements": [], "authority": [], "plans": [], "red_lines": []}]
        values = [("statement", "actor_statement", {"kind": "text", "value": "ACTOR_KNOWN_EXPANSION"}, "actor_brief", "acme", "text"),
                  ("analyst", "actor_statement", {"kind": "text", "value": hidden}, "diagnostic", "acme", "text")]
        if mechanism_kind == "linear" and bind_parameters:
            values += [("coefficient", "mechanism_parameter", {"kind": "number", "value": "1"}, "mechanism", "sum", "coefficient:baseline"),
                       ("intercept", "mechanism_parameter", {"kind": "number", "value": "0"}, "mechanism", "sum", "intercept")]
        if mechanism_kind == "adoption":
            contract["mechanisms"][0]["input_node_ids"] = ["adopted", "baseline"]
            values.append(("adopted", "baseline", {"kind": "number", "value": "100"}, "initial_state", "adopted", "value"))
            if bind_parameters:
                values.append(("rate", "mechanism_parameter", {"kind": "number", "value": "0.01"}, "mechanism", "sum", "rate"))
        if temporal:
            values += [("event", "event", {"kind": "text", "value": "Scheduled rule"}, "calendar", "rule", "description"),
                       ("date", "event", {"kind": "text", "value": "2026-11-01T00:00:00Z"}, "calendar", "rule", "effective_at"),
                       ("effect", "event", {"kind": "number", "value": "10"}, "calendar", "baseline", "add"),
                       ("hazard", "hazard", {"kind": "number", "value": "0.01"}, "calendar", "risk", "hazard_per_day"),
                       ("recurring", "hazard", {"kind": "boolean", "value": False}, "calendar", "risk", "recurring"),
                       ("shock", "hazard", {"kind": "number", "value": "2"}, "calendar", "baseline", "add"),
                       ("indicator", "indicator", {"kind": "number", "value": "250"}, "observation", "target", "threshold")]
        origins = {}
        for metric, kind, value, role, obj, field in values:
            ident = identity()
            ident["metric_id"] = metric
            if metric == "hazard":
                ident["unit"] = {"id": "1/day", "dimension": "frequency", "scale": "1", "currency": None,
                                 "price_basis": "not_applicable", "base_period": None}
            if metric in {"coefficient", "rate"}:
                ident["unit"] = {"id": "1", "dimension": "dimensionless", "scale": "1", "currency": None,
                                 "price_basis": "not_applicable", "base_period": None}
            origin = f"/terms/{len(contract['terms'])}"
            origins[metric] = origin
            contract["terms"].append({**deepcopy(contract["terms"][1]), "origin_pointer": origin, "kind": kind,
                                      "identity": ident, "value_type": value["kind"],
                                      "accepted_value_kinds": ["analyst_inferred" if metric == "analyst" else "reported"],
                                      "consumers": [consumer("oasis-legacy", role, obj, field)]})
        if mechanism_kind == "linear" and bind_parameters:
            contract["mechanisms"][0]["parameters"] = [
                {"name": name, "requirement_origin": origins[metric],
                 "unit": deepcopy(next(t["identity"]["unit"] for t in contract["terms"] if t["origin_pointer"] == origins[metric]))}
                for name, metric in (("coefficient:baseline", "coefficient"), ("intercept", "intercept"))]
        if mechanism_kind == "adoption" and bind_parameters:
            contract["mechanisms"][0]["parameters"] = [{"name": "rate", "requirement_origin": origins["rate"],
                "unit": deepcopy(next(t["identity"]["unit"] for t in contract["terms"] if t["origin_pointer"] == origins["rate"]))}]
        if temporal:
            contract["calendar"] = [{"event_id": "rule", "requirement_origin": origins["event"],
                                      "classification": "scheduled", "time_requirement_origin": origins["date"],
                                      "effect_requirement_origins": [origins["effect"]]}]
            contract["hazards"] = [{"hazard_id": "risk", "trigger": None,
                "likelihood_requirement_origin": origins["hazard"], "effect_requirement_origins": [origins["shock"]],
                "recurrence_requirement_origin": origins["recurring"],
                "consumers": [consumer("oasis-legacy", "calendar", "risk", "hazard_per_day")]}]
            contract["indicators"] = [{"indicator_id": "target-signpost", "node_id": "target",
                "requirement_origin": origins["indicator"], "consumer": consumer("oasis-legacy", "observation", "target", "value"),
                "trigger": {"node_id": "target", "operator": "gte", "value": "250"}}]
        if contract_edit is not None:
            contract_edit(contract, values, origins)
        alias_bytes = dump(["Acme"])
        (f["root"] / "aliases.json").write_bytes(alias_bytes)
        f["manifest"]["artifacts"].append({"artifact_id": "aliases", "track_id": "main", "path": "aliases.json",
            "sha256": digest(alias_bytes), "bytes": len(alias_bytes), "encoding": "utf8_json", "role": "contract"})
        contract["aliases"] = [{"field": "entity", "canonical_id": "acme", "literal": "Acme",
                                "artifact_id": "aliases", "artifact_hash": digest(alias_bytes), "pointer": "/0"}]
        authority = {"settlement": identity(2027), "terms": contract["terms"], "mechanisms": contract["mechanisms"],
                     "actors": contract["actors"], "actor_registry": [{"name": "Acme"}], "aliases": contract["aliases"],
                     **{key: contract[key] for key in ("calendar", "hazards", "indicators")}}
        raw = dump(authority)
        (f["root"] / "contract.json").write_bytes(raw)
        art = next(a for a in f["manifest"]["artifacts"] if a["artifact_id"] == "contract")
        art.update(sha256=digest(raw), bytes=len(raw))
        contract["authority_artifact_hash"] = digest(raw)
        f["requirements"] = wa.requirements_from_contract(contract, scope=f["scope"])
        f["policy"]["consumer_rules"] = [{**c, "adapter_version": "world-anchor-reflexive/v1", "template_versions": ["v1"]}
                                           for t in contract["terms"] for c in t["consumers"]]
        if mechanism_rule:
            f["policy"]["consumer_rules"].extend(
                {**c, "adapter_version": "world-anchor-reflexive/v1", "template_versions": [m["template_version"]]}
                for m in contract["mechanisms"] for c in m["consumers"])
        if policy_edit is not None:
            policy_edit(f["policy"])
        f["index"] = wa.index_snapshot(f["root"], f["manifest"], expected_manifest_hash=wa.anchor_hash(f["manifest"]),
                                      expected_scope=f["scope"], requirements=f["requirements"], policy=f["policy"])
        proposal, review = review_fixture(f)
        prototype, review_row = deepcopy(proposal["rows"][0]), deepcopy(review["decisions"][0])
        for metric, _, value, _, _, _ in values:
            req = next(r for r in f["requirements"]["requirements"] if r["origin_pointer"] == origins[metric])
            row = deepcopy(prototype)
            row.update(proposal_id=metric, requirement_ids=[req["requirement_id"]], identity=req["identity"],
                       value=value, source_value=value,
                       value_kind="analyst_inferred" if metric == "analyst" else "reported",
                       producer_class="research_analyst" if metric == "analyst" else "primary_statement",
                       subject_actor_ref="acme", owner_actor_ref="acme")
            proposal["rows"].append(row)
            review["decisions"].append({**deepcopy(review_row), "proposal_id": metric})
        review["proposal_hash"] = wa.anchor_hash(proposal)
        receipts = receipt_fixture(f, proposal, review)
        f["index"] = wa.admit_reviewed_evidence(f["index"], proposal, review, requirements=f["requirements"],
                                               policy=f["policy"], receipts=receipts)
        pack = build_pack(f)
        output = tmp_path / "emission"
        output.mkdir()
        publication = bridge_module("world_anchor_publication")
        completion = publication.publish_completion(output, pack, requirements=f["requirements"], index=f["index"],
                                                     policy=f["policy"], receipts=[receipts])
        context = load_research_anchor(output, expected_manifest_sha256=completion["manifest_sha256"])
        cast_bytes = dump({"decisions": [{"status": "selected", "entity_uuid": "entity-1", "actor_name": "Acme"}]})
        cast_dir = tmp_path / "cast"
        cast_dir.mkdir()
        (cast_dir / "actor_cast_manifest.json").write_bytes(cast_bytes)
        context = bind_actor_cast(context, cast_dir)
    finally:
        fixtures.wa = original_api
    case = deepcopy(target_case)
    case["nodes"] = [case["nodes"][0], case["nodes"][2]]
    case["nodes"][0].update(nodeId="baseline", value=247.5, range={"low": 247.5, "high": 247.5}, units="usd_billion")
    case["nodes"][1]["units"] = "usd_billion"
    case["resolution"]["units"] = "usd_billion"
    case["resolution"]["horizon"] = "2027-12-31"
    case["claims"] = [case["claims"][0]]
    case["claims"][0].update(nodeId="baseline", passage=page)
    case["sources"][0]["passage"] = page
    case["mechanisms"] = [{**case["mechanisms"][0], "mechanismId": "sum", "kind": mechanism_kind, "inputNodeIds": ["baseline"],
                           "parameters": {"coefficients": [1], "intercept": 0} if mechanism_kind == "linear" else {}}]
    if mechanism_kind == "adoption":
        adopted = deepcopy(case["nodes"][0])
        adopted.update(nodeId="adopted", value=100, range={"low": 100, "high": 100}, claimIds=["C2"])
        case["nodes"].append(adopted)
        case["claims"].append({**deepcopy(case["claims"][0]), "claimId": "C2", "nodeId": "adopted"})
        case["mechanisms"][0].update(inputNodeIds=["adopted", "baseline"], parameters={"rate": 0.01})
    return context, case


def _anchor_config(monkeypatch, context, case):
    from app.services.agency_classification import build_agency_classifications
    actors = {"as_of_date": "2026-10-27", "actors": [{"name": "Acme", "agency_class": "firm",
        "goals": ["DENIED_OLD_GOAL"], "future_plans": ["DENIED_OLD_PLAN"], "description": "DENIED_OLD_DESCRIPTION"}]}
    entities = [_entity()]
    classes = build_agency_classifications(entities, actors, None)
    gen = _generator(monkeypatch)
    return gen.generate_config("sim_anchor_test", "fixture-project", "fixture-graph",
        "Will the target grow by 2027-12-31?", "DENIED_OLD_REPORT", entities, actors=actors,
        research_language="English", max_rounds=4, agency_classifications=classes,
        forecast_case=case, anchor_context=context)


def test_authenticated_anchor_config_seed_calendar_hazard_indicator_and_reload(tmp_path, monkeypatch, target_case):
    context, case = _anchored_fixture(tmp_path, target_case)
    params = _anchor_config(monkeypatch, context, case)
    config = params.to_dict()
    assert config["world_anchor"]["pack_hash"] == context.pack_hash
    assert config["world_model"]["state_variables"][0]["id"] == "target"
    assert config["event_config"]["scheduled_events"]
    assert "DENIED_OLD" not in json.dumps(config["agent_configs"])
    world = WorldModel.from_seed(config["world_model"], config["agent_configs"], anchor_context=context)
    world.start_round(1, {"period_start": "2026-10-28", "period_end": "2026-10-31"})
    assert world.variables["baseline"].value == 247.5
    world.evaluate_target_projection(1, random.Random(1))
    assert world.public_target_values()["target"] == 247.5
    world.start_round(2, {"period_start": "2026-11-01", "period_end": "2026-11-30"})
    assert world.variables["baseline"].value == 257.5
    world.evaluate_target_projection(2, random.Random(1))
    assert world.public_target_values()["target"] == 257.5
    assert world.anchor_signposts[-1]["triggered"] is True
    class AlwaysFire:
        def random(self):
            return 0
    assert world.fire_shocks(2, AlwaysFire())
    assert world.variables["baseline"].value == 259.5
    assert world.fire_shocks(3, AlwaysFire()) == []
    restored = WorldModel.from_dict(world.to_dict(), anchor_context=context)
    assert restored.to_dict() == world.to_dict()
    assert restored.actors[0].agency_class_basis == config["agent_configs"][0]["agency_class_basis"]
    restored.start_round(3, {"period_start": "2026-12-01", "period_end": "2026-12-31"})
    assert restored.variables["baseline"].value == 259.5
    assert restored.variables["baseline"].anchor_metadata["value_kind"] == "third_party_forecast"
    with pytest.raises(ValueError):
        WorldModel.from_dict(world.to_dict())
    corrupt = world.to_dict()
    corrupt["anchor_runtime"]["calendar"][0]["effects"][0]["value"] = 999
    with pytest.raises(ValueError, match="projection changed"):
        WorldModel.from_dict(corrupt, anchor_context=context)


def test_strict_entire_actual_actor_request_excludes_old_inference_and_private_cache(tmp_path, monkeypatch, target_case):
    from app.services.agent_decision import elicit_decision, build_option_menu, DECISION_SYSTEM_PROMPT
    context, case = _anchored_fixture(tmp_path, target_case, temporal=False)
    params = _anchor_config(monkeypatch, context, case)
    world = WorldModel.from_seed(params.world_model, params.to_dict()["agent_configs"], anchor_context=context)
    world.start_round(1, {"period_start": "2026-10-28", "period_end": "2026-10-31"})
    actor = world.actors[0]
    actor.goals = actor.documented_plans = ["DENIED_POISONED_CACHE"]
    actor.incentives = {"gains_if": "DENIED_OLD_INFERENCE"}
    class Model:
        calls = []
        def chat_json(self, **kw):
            self.calls.append(kw)
            return {"option_id": "hold_position"}
    model = Model()
    result = elicit_decision(model, system_message="BEGIN UNTRUSTED DOSSIER DATA DENIED_ROLE END UNTRUSTED DOSSIER DATA",
                            user_prompt="DENIED_BRIEF DENIED_PRIVATE_CACHE", actor=actor, world=world,
                            options=build_option_menu(actor, world, 1), scenarios=[], round_num=1,
                            anchor_context=context, entity_uuid="entity-1")
    assert result.ok
    prompt = json.dumps(model.calls)
    assert "DENIED_" not in prompt and "ACTOR_KNOWN_EXPANSION" in prompt
    assert context.pack_hash not in prompt and "gap_ids" not in prompt
    assert model.calls[0]["messages"][0]["content"].startswith(DECISION_SYSTEM_PROMPT)
    from app.services.actor_context import build_anchor_actor_payload
    payload = build_anchor_actor_payload(context, entity_uuid="entity-1", at="2026-10-28T00:00:00Z")
    world.variables["baseline"].value = 999  # Same metric identity cannot authorize a hidden different value.
    assert not any(row["value"] == 999 for row in world.anchor_actor_observations(payload))


@pytest.mark.parametrize("bad", [{}, {"pack": {}, "pack_hash": "a" * 64}, "invalid"])
def test_invalid_anchor_cannot_be_swallowed_by_seed_or_generator(monkeypatch, target_case, bad):
    with pytest.raises(ValueError):
        build_world_model_seed({}, [], anchor_context=bad, forecast_case=target_case)
    with pytest.raises(ValueError):
        _generate(_generator(monkeypatch), [_entity()], {}, anchor_context=bad, forecast_case=target_case)


def test_private_only_anchor_and_legacy_payload_perturbations_do_not_change_actual_request(tmp_path, monkeypatch, target_case):
    from app.services.agent_decision import elicit_decision, build_option_menu
    calls, results, hashes = [], [], []
    class Model:
        def chat_json(self, **kw):
            calls.append(kw)
            return {"option_id": "hold_position"}
    for name in ("left", "right"):
        root = tmp_path / name
        root.mkdir()
        context, case = _anchored_fixture(root, target_case, hidden="PRIVATE_ONLY_" + name, temporal=False)
        hashes.append(context.pack_hash)
        params = _anchor_config(monkeypatch, context, case)
        world = WorldModel.from_seed(params.world_model, params.to_dict()["agent_configs"], anchor_context=context)
        world.scenario_shares = {"A": 0.99 if name == "left" else 0.01}
        world.start_round(1, {"period_start": "2026-10-28", "period_end": "2026-10-31"})
        actor = world.actors[0]
        actor.posture = "INFERRED_POSTURE_" + name
        results.append(elicit_decision(Model(), system_message="RAW_ROLE_" + name, user_prompt="CACHE_" + name,
            actor=actor, world=world, options=build_option_menu(actor, world, 1), scenarios=[], round_num=1,
            anchor_context=context, entity_uuid="entity-1").to_dict())
    assert hashes[0] != hashes[1]
    assert calls[0] == calls[1]
    assert results[0] == results[1]


def test_anchored_case_mismatch_fails_without_incidental_fallback(tmp_path, monkeypatch, target_case):
    context, case = _anchored_fixture(tmp_path, target_case, temporal=False)
    case["nodes"][0]["value"] = 999
    case["nodes"][0]["range"] = {"low": 999, "high": 999}
    with pytest.raises(ValueError, match="value mismatch"):
        _anchor_config(monkeypatch, context, case)


def test_actual_decision_consequence_propagates_bound_input_but_cannot_write_derived_target(tmp_path, monkeypatch, target_case):
    from app.services.agent_decision import build_option_menu, parse_decision
    from app.services.world_update import run_world_round
    from test_world_announced_settings import _expected_damped_numeric
    context, case = _anchored_fixture(tmp_path, target_case, temporal=False)
    params = _anchor_config(monkeypatch, context, case)
    world = WorldModel.from_seed(params.world_model, params.to_dict()["agent_configs"], anchor_context=context)
    period = {"label": "P1", "period_start": "2026-10-28", "period_end": "2026-10-31"}
    world.start_round(1, period)
    decision = parse_decision({"option_id": "invest_capex", "public_statement": "Acme invests in capacity."},
        actor=world.actors[0], world=world, options=build_option_menu(world.actors[0], world, 1), scenarios=[], round_num=1)
    assert decision.ok
    class Arbiter:
        def chat_json(self, **kwargs):
            assert "Acme invests in capacity" in json.dumps(kwargs)
            return {"narrative": "A scripted simulated investment consequence, not an observed fact.",
                    "variable_changes": [{"variable_id": "baseline", "delta": 5},
                                         {"variable_id": "target", "new_value": 999}],
                    "events": [], "action_resolutions": [{"actor": "Acme", "outcome": "success"}]}
    record = run_world_round(world, 1, period, [decision], [], llm=Arbiter(), rng=random.Random(42),
                             scenarios=[], arbiter_repair="field")
    assert record["arbiter_status"] in {"applied", "applied_partial"}
    expected = _expected_damped_numeric(247.5, 252.5)
    assert world.variables["baseline"].value == expected
    assert world.evaluate_target_projection(1, random.Random(42))["status"] == "ready"
    assert world.public_target_values()["target"] == expected
    assert world.variables["target"].read_only
    assert world.variables["baseline"].anchor_metadata["value_kind"] == "third_party_forecast"


def test_missing_mechanism_consumer_policy_stays_blocked(tmp_path, monkeypatch, target_case):
    context, case = _anchored_fixture(tmp_path, target_case, temporal=False, mechanism_rule=False)
    readiness = next(r for r in context.pack["readiness"] if r["engine"] == "oasis-legacy")
    assert readiness["status"] == "blocked"
    assert any(g["code"] == "modeling_gap" and "sum" in g["related_ids"] for g in context.pack["gaps"])
    with pytest.raises(ValueError, match="anchor_not_ready"):
        _anchor_config(monkeypatch, context, case)


def test_unjoined_audience_fill_fails_during_preparation(tmp_path, monkeypatch, target_case):
    from app.services.simulation_config_generator import AgentActivityConfig, SimulationConfigGenerator
    context, case = _anchored_fixture(tmp_path, target_case, temporal=False)
    monkeypatch.setattr(SimulationConfigGenerator, "_generate_audience_agent_configs", lambda *a, **k: [
        AgentActivityConfig(99, "unjoined-audience", "Synthetic audience", "Audience")])
    with pytest.raises(ValueError, match="anchor_actor_missing"):
        _anchor_config(monkeypatch, context, case)


def _published_coordinator(tmp_path, monkeypatch, target_case, **fixture_options):
    """Build the real publication, official binding, external seal and loader chain."""
    from app.services import world_anchor as host
    from app.services import official_data
    from app.services.simulation_manager import SimulationManager, build_simulation_config_seal
    from test_world_model_loop import _patch_world, rps
    context, case = _anchored_fixture(tmp_path, target_case, temporal=False, **fixture_options)
    simulations = tmp_path / "simulations"
    directory = simulations / "sim_anchor_test"
    directory.mkdir(parents=True)
    monkeypatch.setattr(SimulationManager, "SIMULATION_DATA_DIR", str(simulations))
    _patch_world(monkeypatch, str(directory), [])
    config = _anchor_config(monkeypatch, context, case).to_dict()
    for name, content in (("research_report.md", "Public synthetic research."), ("actors.json", '{"actors": []}'),
                          ("sources.json", "[]"), ("actor_dossier.md", "Synthetic actor registry.")):
        (tmp_path / "emission" / name).write_text(content)
    official_data.bind_simulation_research(config["simulation_id"], tmp_path / "emission", pipeline_id="pipe_anchor_test")
    (directory / "actor_cast_manifest.json").write_bytes(context._cast_bytes)
    (directory / "world_anchor_join.json").write_bytes(context._join_bytes)
    (directory / "simulation_config.json").write_text(json.dumps(config))
    config_hash, seal_hash = build_simulation_config_seal(str(directory), simulation_id=config["simulation_id"],
        actor_cast_manifest_sha256=hashlib.sha256(context._cast_bytes).hexdigest(),
        actor_context_manifest_sha256=None, actor_role_manifest_sha256={})
    (directory / "state.json").write_text(json.dumps({"simulation_id": config["simulation_id"],
        "simulation_config_sha256": config_hash, "simulation_config_manifest_sha256": seal_hash}))
    assert host.load_runtime_anchor(config, directory).pack_hash == context.pack_hash
    coordinator = rps._ReflexiveWorldCoordinator(config, str(directory), 1, lambda _: None)
    return coordinator, config, context, directory


def test_actual_coordinator_and_oasis_request_replacement_with_admitted_host_context(tmp_path, monkeypatch, target_case):
    from app.services import world_anchor as host
    from test_world_model_loop import _WorldLLM, rps
    from test_calendar_round_loop import _FakeAgent
    coordinator, config, context, directory = _published_coordinator(tmp_path, monkeypatch, target_case)
    coordinator._brief = "DENIED_SHARED_CACHE"
    coordinator._recent_discourse = "DENIED_OLD_DISCOURSE"
    period = config["temporal_config"]["round_dates"][0]
    async def decide():
        await coordinator.begin_round("twitter", 0, period)
        return await coordinator.decide("twitter", 0, period, [0], lambda _: "DENIED_RAW_ROLE", [])
    assert asyncio.run(decide())[0].ok
    captured = [call for call in _WorldLLM.calls if call["kind"] == "decision"]
    assert captured and "ACTOR_KNOWN_EXPANSION" in json.dumps(captured)
    assert "DENIED_" not in json.dumps(captured)
    class ResettableAgent(_FakeAgent):
        def init_messages(self):
            self.memory_notes.clear()
    agent = ResettableAgent(0, "Acme")
    agent.memory_notes.append(("DENIED_SUMMARY_CACHE", "user"))
    rps._install_anchor_actor_payloads(coordinator, [(0, agent)], period)
    assert not agent.memory_notes
    assert "ACTOR_KNOWN_EXPANSION" in agent._system_message.content
    assert "DENIED_" not in agent._system_message.content
    assert context.pack_hash not in agent._system_message.content
    coordinator._write_world_state()
    restored = rps._ReflexiveWorldCoordinator(config, str(directory), 1, lambda _: None)
    assert restored.world.to_dict() == coordinator.world.to_dict()
    before = len(_WorldLLM.calls)
    broken = deepcopy(config)
    broken["world_anchor"]["pack_hash"] = "a" * 64
    with pytest.raises(host.WorldAnchorIntegrationError):
        rps._get_world_coordinator(broken, str(directory), 1, lambda _: None)
    assert len(_WorldLLM.calls) == before


def test_host_case_reaches_real_generator_seed_and_mechanism(monkeypatch, target_case):
    actors = {"as_of_date": "2026-10-27", "actors": [{"name": "Acme", "agency_class": "firm"}],
              "quantitative_facts": [{"metric": "INCIDENTAL", "value": 9000, "unit": "USD"}]}
    params = _generate(_generator(monkeypatch), [_entity()], actors, forecast_case=target_case)
    block = params.world_model
    assert block["state_variables"][0]["id"] == "target"
    assert not any(row["id"] == "incidental" for row in block["state_variables"])
    world = WorldModel.from_seed(block, params.to_dict()["agent_configs"])
    world.start_round(1, {"period_start": "2026-10-28", "period_end": "2026-11-27"})
    assert world.evaluate_target_projection(1, random.Random(7))["status"] == "ready"
    assert world.public_target_values()["target"] == pytest.approx(110)
    assert world.variables["target"].read_only


def test_off_mode_config_prompt_state_and_rng_snapshot(monkeypatch):
    from app.services import agent_decision as decisions
    actors = {"as_of_date": "2026-10-27", "actors": [{"name": "Acme", "agency_class": "firm",
               "goals": ["LEGACY_ANALYST_INFERENCE"], "future_plans": ["Build the legacy facility"]}]}
    params = _generate(_generator(monkeypatch), [_entity()], actors)
    params.generated_at = "fixed-off-probe"
    config = params.to_dict()
    world = WorldModel.from_seed(config["world_model"], config["agent_configs"])
    rng = random.Random(42)
    rng_before = repr(rng.getstate())
    world.start_round(1, {"label": "P1", "period_start": "2026-10-28", "period_end": "2026-10-31"})
    world.fire_shocks(1, rng)
    assert repr(rng.getstate()) == rng_before
    menu = decisions.build_option_menu(world.actors[0], world, 1)
    prompt = decisions.build_decision_prompt(world.actors[0], world_clock="CLOCK", public_brief=world.render_public_brief(),
        private_brief=world.render_private_brief(0), options=menu, scenarios=[], cast_names=["Acme"])
    class Model:
        calls = []
        def chat_json(self, **kwargs):
            self.calls.append(kwargs)
            return {"option_id": "hold_position"}
    model = Model()
    decisions.elicit_decision(model, system_message="BEGIN UNTRUSTED DOSSIER DATA LEGACY_ROLE END UNTRUSTED DOSSIER DATA",
        user_prompt=prompt, actor=world.actors[0], world=world, options=menu, scenarios=[], round_num=1)
    assert "LEGACY_ANALYST_INFERENCE" in json.dumps(model.calls)
    payload = {"config": config, "world": world.to_dict(), "calls": model.calls, "rng": repr(rng.getstate())}
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    receipt = {"sha256": hashlib.sha256(raw.encode()).hexdigest(), "payload": payload}
    # Retain the complete 9916b3be receipt and its historical pin. The merged
    # payload must equal archived f773 main plus the exact reviewed C11 deltas,
    # and independently equal 9916b3be plus the exact reviewed main deltas.
    from test_world_anchor_main_merge_off import assert_off_mode_compatible
    assert_off_mode_compatible(receipt, historical_sha256=
        "960d2466fff5be6edc329df3972728dbbac5600280252479999b22e91e478e92")
    root = os.environ.get("MAIN_OFFLINE_EVIDENCE")
    if root:
        (Path(root) / "off-mode-snapshot.json").write_text(json.dumps(receipt, ensure_ascii=False, indent=2))


def test_omitted_case_preserves_old_generator_and_seed(monkeypatch):
    gen = _generator(monkeypatch)
    actors = {"as_of_date": "2026-10-27", "actors": [{"name": "Acme", "agency_class": "firm"}]}
    before = _generate(gen, [_entity()], actors).to_dict()
    after = _generate(gen, [_entity()], actors, forecast_case=None).to_dict()
    before.pop("generated_at")
    after.pop("generated_at")
    assert before == after
    assert "world_anchor" not in before
    seed = build_world_model_seed(actors, before["agent_configs"])
    assert seed == build_world_model_seed(deepcopy(actors), before["agent_configs"], forecast_case=None)


@pytest.mark.parametrize("mutation", ["shock_rate", "shock_effect", "shock_trigger", "variable_metadata",
                                     "derived_flag", "derived_identity", "extra_variable", "fixed_parameter",
                                     "provenance", "derived_cached_value", "derived_current_value", "fired_rounds", "extra_parameter"])
def test_review_f1_restored_executable_state_cannot_diverge_from_admission(tmp_path, monkeypatch, target_case, mutation):
    context, case = _anchored_fixture(tmp_path, target_case, mechanism_kind="linear")
    params = _anchor_config(monkeypatch, context, case)
    world = WorldModel.from_seed(params.world_model, params.to_dict()["agent_configs"], anchor_context=context)
    world.start_round(1, {"period_start": "2026-10-28", "period_end": "2026-10-31"})
    assert world.evaluate_target_projection(1, random.Random(5))["status"] == "ready"
    saved = world.to_dict()
    assert WorldModel.from_dict(saved, anchor_context=context).to_dict() == saved
    altered = deepcopy(saved)
    baseline = next(v for v in altered["variables"] if v["id"] == "baseline")
    target = next(v for v in altered["variables"] if v["id"] == "target")
    if mutation == "shock_rate": altered["shocks"][0]["hazard_per_day"] = 10
    elif mutation == "shock_effect": altered["shocks"][0]["effects"][0]["value"] = 999
    elif mutation == "shock_trigger": altered["shocks"][0]["trigger"] = {"node_id": "baseline", "operator": "gte", "value": "999"}
    elif mutation == "variable_metadata": baseline["anchor_metadata"]["value_kind"] = "observed"
    elif mutation == "derived_flag": target["read_only"] = False
    elif mutation == "derived_identity": target["identity"]["mechanismId"] = "foreign"
    elif mutation == "extra_variable": altered["variables"].append({**deepcopy(baseline), "id": "foreign", "history": [{"round": 1, "value": 999, "source": "mechanism"}]})
    elif mutation == "fixed_parameter": altered["target_projection_state"]["parameters"]["sum"]["intercept"] = 999
    elif mutation == "provenance": baseline["provenance"] = "official"
    elif mutation == "derived_cached_value": altered["target_projection_state"]["values"]["target"] = 999
    elif mutation == "derived_current_value":
        target["value"] = target["history"][-1]["value"] = 999
    elif mutation == "fired_rounds": altered["shocks"][0]["fired_rounds"] = [2]
    elif mutation == "extra_parameter": altered["target_projection_state"]["parameters"]["sum"]["foreign"] = 7
    # The trusted pack, pin and executable adapter projection remain untouched.
    assert altered["anchor_runtime"] == saved["anchor_runtime"]
    with pytest.raises(ValueError):
        WorldModel.from_dict(altered, anchor_context=context)


@pytest.mark.parametrize("mutation", ["target_projection", "agency_class"])
def test_review_f1_sibling_target_projection_must_match_sealed_case(tmp_path, monkeypatch, target_case, mutation):
    from app.services.world_paths import WORLD_PATHS_FILE, WORLD_PATHS_VERSION
    coordinator, config, _, directory = _published_coordinator(tmp_path, monkeypatch, target_case)
    saved = coordinator.world.to_dict()
    if mutation == "target_projection":
        saved["target_projection"]["caseId"] = "foreign-case"
    else:
        saved["actors"][0]["agency_class"] = "regulator_agency"
    (directory / WORLD_PATHS_FILE).write_text(json.dumps({"schema_version": WORLD_PATHS_VERSION,
        "committed_round": 1, "paths": [{"path": 1, "world": saved}]}))
    coordinator._resumed_round, coordinator._k = 1, 2
    with pytest.raises(ValueError):
        coordinator._init_paths()


@pytest.mark.parametrize("mutation", ["future_template", "future_adapter", "missing_parameters", "lag", "applicability"])
def test_review_f2_runtime_rejects_unimplemented_mechanism_contracts(tmp_path, monkeypatch, target_case, mutation):
    def edit(contract, values, origins):
        mechanism = contract["mechanisms"][0]
        if mutation == "future_template": mechanism["template_version"] = "v99"
        if mutation == "lag": mechanism["lag_requirement_origin"] = origins["statement"]
        if mutation == "applicability": mechanism["applicability_requirement_origins"] = [origins["statement"]]
    def policy_edit(policy):
        if mutation == "future_adapter":
            for rule in policy["consumer_rules"]: rule["adapter_version"] = "world-anchor-reflexive/v99"
    context, case = _anchored_fixture(tmp_path, target_case, temporal=False, contract_edit=edit,
        policy_edit=policy_edit, mechanism_kind="linear" if mutation == "missing_parameters" else "sum", bind_parameters=False)
    assert next(r for r in context.pack["readiness"] if r["engine"] == "oasis-legacy")["status"] == "ready"
    with pytest.raises(ValueError, match="modeling_gap"):
        _anchor_config(monkeypatch, context, case)


@pytest.mark.parametrize("mutation", ["million_add", "scale_add", "dimensioned_mul"])
def test_review_f3_effect_units_and_scales_are_not_discarded(tmp_path, monkeypatch, target_case, mutation):
    def edit(contract, values, origins):
        requirement = next(t for t in contract["terms"] if t["origin_pointer"] == origins["effect"])
        if mutation == "million_add": requirement["identity"]["unit"].update(id="usd_million", scale="1000000")
        elif mutation == "scale_add": requirement["identity"]["unit"]["scale"] = "1000000"
        else: requirement["consumers"][0]["field"] = "mul"
    context, case = _anchored_fixture(tmp_path, target_case, contract_edit=edit)
    with pytest.raises(ValueError, match="modeling_gap"):
        _anchor_config(monkeypatch, context, case)


@pytest.mark.parametrize("mutation", ["unknown_hazard_node", "unknown_indicator_node", "unsupported_operator",
                                     "reversed_interval", "threshold_mismatch", "null_indicator", "consumer_mismatch"])
def test_review_f4_invalid_predicates_cannot_become_silent_unknowns(tmp_path, monkeypatch, target_case, mutation):
    def edit(contract, values, origins):
        indicator = contract["indicators"][0]
        if mutation == "unknown_hazard_node": contract["hazards"][0]["trigger"] = {"node_id": "unknown", "operator": "gte", "value": "250"}
        elif mutation == "unknown_indicator_node": indicator["trigger"]["node_id"] = "unknown"
        elif mutation == "unsupported_operator": indicator["trigger"]["operator"] = "equals_or_maybe"
        elif mutation == "reversed_interval": indicator["trigger"] = {"node_id": "target", "operator": "between", "low": "300", "high": "250"}
        elif mutation == "threshold_mismatch": indicator["trigger"]["value"] = "300"
        elif mutation == "null_indicator": indicator["trigger"] = None
        elif mutation == "consumer_mismatch": indicator["consumer"]["field"] = "unimplemented_output"
    context, case = _anchored_fixture(tmp_path, target_case, contract_edit=edit)
    with pytest.raises(ValueError, match="modeling_gap"):
        _anchor_config(monkeypatch, context, case)


def test_review_f5_fifth_hazard_effect_cannot_be_silently_truncated(tmp_path, monkeypatch, target_case):
    def edit(contract, values, origins):
        source = next(t for t in contract["terms"] if t["origin_pointer"] == origins["shock"])
        for number in range(2, 6):
            metric = f"shock_{number}"
            origin = f"/terms/{len(contract['terms'])}"
            row = deepcopy(source)
            row["origin_pointer"], row["identity"]["metric_id"] = origin, metric
            contract["terms"].append(row)
            origins[metric] = origin
            values.append((metric, "hazard", {"kind": "number", "value": "2"}, "calendar", "baseline", "add"))
            contract["hazards"][0]["effect_requirement_origins"].append(origin)
    context, case = _anchored_fixture(tmp_path, target_case, contract_edit=edit)
    with pytest.raises(ValueError, match="modeling_gap"):
        _anchor_config(monkeypatch, context, case)


def test_review_f3_dimensionless_multiplier_retains_its_numeric_meaning(tmp_path, monkeypatch, target_case):
    def edit(contract, values, origins):
        requirement = next(t for t in contract["terms"] if t["origin_pointer"] == origins["effect"])
        requirement["identity"]["unit"] = {"id": "1", "dimension": "dimensionless", "scale": "1", "currency": None,
                                            "price_basis": "not_applicable", "base_period": None}
        requirement["consumers"][0]["field"] = "mul"
        for index, row in enumerate(values):
            if row[0] == "effect": values[index] = (row[0], row[1], {"kind": "number", "value": "2"}, *row[3:])
    context, case = _anchored_fixture(tmp_path, target_case, contract_edit=edit)
    params = _anchor_config(monkeypatch, context, case)
    world = WorldModel.from_seed(params.world_model, params.to_dict()["agent_configs"], anchor_context=context)
    world.start_round(1, {"period_start": "2026-11-01", "period_end": "2026-11-30"})
    assert world.variables["baseline"].value == 495
    assert world.evaluate_target_projection(1, random.Random(0))["status"] == "ready"
    assert world.public_target_values()["target"] == 495


def test_review_f5_all_four_supported_hazard_effects_execute(tmp_path, monkeypatch, target_case):
    def edit(contract, values, origins):
        source = next(t for t in contract["terms"] if t["origin_pointer"] == origins["shock"])
        for number in range(2, 5):
            metric = f"shock_{number}"
            origin = f"/terms/{len(contract['terms'])}"
            row = deepcopy(source)
            row["origin_pointer"], row["identity"]["metric_id"] = origin, metric
            contract["terms"].append(row)
            origins[metric] = origin
            values.append((metric, "hazard", {"kind": "number", "value": "2"}, "calendar", "baseline", "add"))
            contract["hazards"][0]["effect_requirement_origins"].append(origin)
    context, case = _anchored_fixture(tmp_path, target_case, contract_edit=edit)
    params = _anchor_config(monkeypatch, context, case)
    world = WorldModel.from_seed(params.world_model, params.to_dict()["agent_configs"], anchor_context=context)
    world.start_round(1, {"period_start": "2026-10-28", "period_end": "2026-10-31"})
    class AlwaysFire:
        def random(self): return 0
    fired = world.fire_shocks(1, AlwaysFire())
    assert len(fired[0]["variables_changed"]) == 4
    assert world.variables["baseline"].value == 255.5
    world.evaluate_target_projection(1, random.Random(0))
    assert world.public_target_values()["target"] == 255.5


def test_review_f6_self_owned_commitment_ids_reach_strict_and_native_requests(tmp_path, monkeypatch, target_case):
    from app.services.agent_decision import build_option_menu, elicit_decision, parse_decision
    from app.services.world_model import ActorState
    from test_world_model_loop import rps
    from camel.agents import ChatAgent
    from camel.messages import BaseMessage
    from camel.models.stub_model import StubModel
    from camel.types import ModelType, OpenAIBackendRole
    coordinator, config, context, _ = _published_coordinator(tmp_path, monkeypatch, target_case)
    world = coordinator.world
    world.start_round(1, config["temporal_config"]["round_dates"][0])
    actor = world.actors[0]
    promise = parse_decision({"option_id": "public_statement", "public_statement": "We will publish the schedule.",
        "commitment": {"description": "Publish the schedule", "due_periods": 1}}, actor=actor, world=world,
        options=build_option_menu(actor, world, 1), scenarios=[], round_num=1)
    assert promise.ok
    world.register_decisions(1, [promise.to_dict()])
    own_id = actor.commitments[0]["id"]
    rival = ActorState(7, "Rival")
    rival.add_commitment("DENIED_RIVAL_PROMISE", made_round=1, due_round=2)
    world.add_actor(rival)
    period = config["temporal_config"]["round_dates"][1]
    world.start_round(2, period)
    class Model:
        calls = []
        def chat_json(self, **kwargs):
            self.calls.append(kwargs)
            assert own_id in json.dumps(kwargs), "The strict request lost its owned delivery ID."
            assert "DENIED_RIVAL_PROMISE" not in json.dumps(kwargs)
            return {"option_id": "hold_position", "deliveries": [own_id], "public_statement": "The schedule has been published."}
    model = Model()
    result = elicit_decision(model, system_message="DENIED_OLD_ROLE", user_prompt="DENIED_OLD_CACHE",
        actor=actor, world=world, options=build_option_menu(actor, world, 2), scenarios=[], round_num=2,
        anchor_context=context, entity_uuid="entity-1")
    assert model.calls and own_id in json.dumps(model.calls)
    assert result.ok and result.deliveries == [own_id]
    class NativeCapture(StubModel):
        calls = []
        async def _arun(self, messages, response_format=None, tools=None):
            self.calls.append(deepcopy(messages))
            return await super()._arun(messages, response_format, tools)
    backend = NativeCapture(ModelType.STUB)
    agent = ChatAgent(system_message="DENIED_NATIVE_ROLE", model=backend, agent_id="0")
    agent.update_memory(BaseMessage.make_user_message("user", "DENIED_NATIVE_CACHE"), OpenAIBackendRole.USER)
    rps._install_anchor_actor_payloads(coordinator, [(0, agent)], period)
    asyncio.run(agent.astep("Discuss your own open commitments."))
    reaction = rps._make_reaction_agent(agent, [])
    asyncio.run(reaction.astep("Respond about your own delivery duties."))
    assert len(backend.calls) == 2
    for native_messages in backend.calls:
        assert own_id in json.dumps(native_messages)
        assert "DENIED_" not in json.dumps(native_messages)


@pytest.mark.parametrize("path", ["primary", "sibling", "sibling_gather"])
def test_review_f7_enabled_projection_failure_cannot_complete_a_round(tmp_path, monkeypatch, target_case, path):
    coordinator, config, context, directory = _published_coordinator(tmp_path, monkeypatch, target_case)
    coordinator._arbiter_on = False
    period = config["temporal_config"]["round_dates"][0]
    def fail(*args, **kwargs):
        raise ValueError("required anchor projection failed")
    if path == "primary":
        monkeypatch.setattr(coordinator.world, "evaluate_target_projection", fail)
        operation = coordinator._commit_round(0, {"period": period, "events": []})
    else:
        sibling = WorldModel.from_dict(coordinator.world.to_dict(), anchor_context=context)
        monkeypatch.setattr(sibling, "evaluate_target_projection", fail)
        branch = {"path": 1, "world": sibling, "ws": None, "arbiter_failed": 0}
        coordinator._paths = [branch]
        operation = (coordinator._sibling_round(branch, 1, period, [], []) if path == "sibling"
                     else coordinator._commit_round(0, {"period": period, "events": []}))
    with pytest.raises(ValueError, match="required anchor projection failed"):
        asyncio.run(operation)
    assert coordinator._max_round == 0
    assert not (directory / "world_state.json").exists()
    with pytest.raises(ValueError, match="required anchor projection failed"):
        asyncio.run(coordinator.finalize())
    assert not (directory / "world_state_trajectory.json").exists()


def test_review_f7_off_mode_retains_unavailable_projection_fallback(tmp_path, monkeypatch):
    from test_world_model_loop import _patch_world, _world_config, rps
    _patch_world(monkeypatch, str(tmp_path), [])
    config = _world_config()
    coordinator = rps._ReflexiveWorldCoordinator(config, str(tmp_path), 1, lambda _: None)
    coordinator._arbiter_on = False
    world = coordinator.world
    world._target_projection = {"invalid_legacy_projection": True}
    period = config["temporal_config"]["round_dates"][0]
    world.start_round(1, period)
    record = {}
    coordinator._evaluate_share_target(world, 1, random.Random(0), record)
    assert record["target_projection_status"] == "unavailable"
    assert record["target_values"] == {}
    branch = {"path": 1, "world": world, "ws": None, "arbiter_failed": 0}
    result = asyncio.run(coordinator._sibling_round(branch, 1, period, [], []))
    assert result["target_projection_status"] == "unavailable"
    assert coordinator._anchor_context is None


@pytest.mark.parametrize("kind", ["linear", "adoption"])
def test_review_supported_complete_parameter_bindings_remain_executable(tmp_path, monkeypatch, target_case, kind):
    context, case = _anchored_fixture(tmp_path, target_case, temporal=False, mechanism_kind=kind)
    params = _anchor_config(monkeypatch, context, case)
    world = WorldModel.from_seed(params.world_model, params.to_dict()["agent_configs"], anchor_context=context)
    world.start_round(1, {"period_start": "2026-10-28", "period_end": "2026-10-31"})
    assert world.evaluate_target_projection(1, random.Random(42))["status"] == "ready"
    assert world.public_target_values()["target"] == pytest.approx(247.5 if kind == "linear" else 101.475)
    assert WorldModel.from_dict(world.to_dict(), anchor_context=context).to_dict() == world.to_dict()


def test_review_f2_missing_adoption_rate_is_not_implicitly_accepted(tmp_path, monkeypatch, target_case):
    context, case = _anchored_fixture(tmp_path, target_case, temporal=False, mechanism_kind="adoption", bind_parameters=False)
    with pytest.raises(ValueError, match="parameter slots"):
        _anchor_config(monkeypatch, context, case)


def test_review_f2_parameter_unit_mismatch_is_not_a_numeric_match(tmp_path, monkeypatch, target_case):
    def edit(contract, values, origins):
        slot = contract["mechanisms"][0]["parameters"][0]
        slot["unit"] = deepcopy(contract["terms"][1]["identity"]["unit"])
        next(t for t in contract["terms"] if t["origin_pointer"] == origins["coefficient"])["identity"]["unit"] = deepcopy(slot["unit"])
    context, case = _anchored_fixture(tmp_path, target_case, temporal=False, mechanism_kind="linear", contract_edit=edit)
    with pytest.raises(ValueError, match="coefficient units"):
        _anchor_config(monkeypatch, context, case)


def test_review_f4_private_trigger_node_is_not_a_runtime_unknown(tmp_path, monkeypatch, target_case):
    def edit(contract, values, origins):
        contract["hazards"][0]["trigger"] = {"node_id": "baseline", "operator": "gte", "value": "250"}
        contract["calendar"] = []
        contract["hazards"][0]["effect_requirement_origins"] = []
    context, case = _anchored_fixture(tmp_path, target_case, contract_edit=edit)
    case["nodes"][0].update(visibility="private", ownerActorId="acme")
    case["actors"] = [{"actorId": "acme", "name": "Acme", "decisionBasis": "Synthetic owner mandate.",
        "objectives": [], "constraints": {"capacity": 2},
        "levers": [{"leverId": "capacity", "nodeId": "baseline", "minimum": -1, "maximum": 1,
                    "cost": 1, "lagPeriods": 0, "reversible": True, "requiresConsent": []}],
        "decisionRule": {"kind": "rule", "cadencePeriods": 1, "triggers": []}, "plans": [],
        "information": {"nodeIds": ["baseline"], "releaseLagPeriods": 0}, "credibility": 1}]
    # Remove the public effects, so the negative reaches the private trigger check itself.
    from app.services.world_model_seed import build_anchor_runtime_projection
    with pytest.raises(ValueError, match="predicate requires a mapped public"):
        build_anchor_runtime_projection(context, case)


@pytest.mark.parametrize("threshold", ["NaN", "Infinity", "-Infinity"])
def test_review_f4_nonfinite_predicate_threshold_is_rejected(tmp_path, monkeypatch, target_case, threshold):
    def edit(contract, values, origins):
        contract["indicators"][0]["trigger"]["value"] = threshold
    context, case = _anchored_fixture(tmp_path, target_case, contract_edit=edit)
    with pytest.raises(ValueError, match="predicate threshold"):
        _anchor_config(monkeypatch, context, case)


def test_review_f4_valid_predicate_preserves_unknown_observation(tmp_path, monkeypatch, target_case):
    context, case = _anchored_fixture(tmp_path, target_case)
    params = _anchor_config(monkeypatch, context, case)
    world = WorldModel.from_seed(params.world_model, params.to_dict()["agent_configs"], anchor_context=context)
    world.start_round(1, {"period_start": "2026-10-28", "period_end": "2026-10-31"})
    assert world.variables["target"].value is None
    world.evaluate_anchor_indicators()
    assert world.anchor_signposts[-1]["value"] is None
    assert world.anchor_signposts[-1]["triggered"] is None
