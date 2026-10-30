"""Source-only C5 classification and real config/seed/decision consumer checks."""

from copy import deepcopy
from dataclasses import asdict
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys

import pytest

from app.config import Config
from app.services.agency_classification import agency_classification_for, build_agency_classifications
from app.services.agent_decision import catalog_for, option_feasibility_problem
from app.services.simulation_config_generator import AgentActivityConfig, SimulationConfigGenerator, SimulationParameters
from app.services.world_model import WorldModel
from app.services.world_model_seed import build_world_model_seed, resolve_agency_class
from app.services.zep_entity_reader import EntityNode


def _entity(name="Acme", uuid="entity-1", labels=None, aliases=None):
    return EntityNode(uuid, name, labels or ["Organization"], "unrelated research FTC leader", {"aliases": aliases or []})


def _ontology(*rows):
    return {"entity_types": list(rows)}


def _type(name="Vendor", klass="firm", examples=None):
    return {"name": name, "agency_class": klass, "examples": examples or ["Acme"]}


def _result(ontology, actors=None, entity=None):
    return build_agency_classifications([entity or _entity()], actors, ontology)["entity-1"]


def test_explicit_canonical_dossier_class_precedes_ontology_and_invalid_ontology():
    actors = {"actors": [{"name": "Acme", "type": "Organization", "agency_class": "labor_union"}]}
    for ontology in (None, [], {"entity_types": "bad"}, _ontology(_type())):
        result = _result(ontology, actors)
        assert result["agency_class"] == "labor_union"
        assert result["basis"]["source"] == "dossier"
    actors["actors"][0]["agency_class"] = "other_actor"
    assert _result(_ontology(_type()), actors)["agency_class"] == "other_actor"


@pytest.mark.parametrize("bad", [None, "", "firm leader", "regulator", "FIRM", True, 7, [], {}])
def test_invalid_declared_class_never_grants_a_class(bad):
    actors = {"actors": [{"name": "Acme", "agency_class": bad, "description": "FTC research leader"}]}
    assert _result(None, actors)["agency_class"] is None
    assert _result(_ontology(_type(klass=bad)))["agency_class"] is None
    # An independent valid declaration still applies; the invalid value is never inferred.
    assert _result(_ontology(_type()), actors)["agency_class"] == "firm"


def test_specific_type_before_named_example_and_specific_example_before_generic_type():
    ontology = _ontology(_type("Organization", "firm"), _type("Insurer", "financial_institution"))
    result = _result(ontology)
    assert result["agency_class"] == "financial_institution"
    assert result["basis"]["type_names"] == ["Insurer"]
    assert result["basis"]["match_method"] == "exact_example_name_or_alias"
    ontology["entity_types"].append(_type("LaborBody", "labor_union", ["Someone Else"]))
    result = _result(ontology, entity=_entity(labels=["Organization", "LaborBody"]))
    assert result["agency_class"] == "labor_union"
    assert result["basis"]["match_method"] == "exact_type"


@pytest.mark.parametrize("aliases_source", ["entity", "dossier"])
def test_exact_alias_matches(aliases_source):
    entity = _entity("Acme Holdings", aliases=[" ACME  "] if aliases_source == "entity" else [])
    actors = {"actors": [{"name": "Acme Holdings", "aliases": ["Acme"]}]} if aliases_source == "dossier" else None
    assert _result(_ontology(_type()), actors, entity)["agency_class"] == "firm"


@pytest.mark.parametrize("name", ["Acme subsidiary", "Ac-me", "Acme Holdings", "Ac"])
def test_no_substring_punctuation_or_fuzzy_name_matching(name):
    result = _result(_ontology(_type()), entity=_entity(name))
    assert result["agency_class"] is None


@pytest.mark.parametrize("method", ["type", "example"])
def test_conflicting_specific_classes_remain_unresolved(method):
    ontology = _ontology(_type("Organization", "firm"), _type("Vendor", "firm"), _type("Insurer", "financial_institution"))
    entity = _entity(labels=["Vendor", "Insurer"] if method == "type" else ["Organization"])
    result = _result(ontology, entity=entity)
    assert result["agency_class"] is None
    assert result["basis"]["status"] == "unresolved"
    assert result["basis"]["reason"] == "conflicting_declared_classes"
    assert result["basis"]["type_names"] == ["Insurer", "Vendor"]
    assert len(result["basis"]["declarations"]) == 2


def test_matching_specific_invalid_metadata_does_not_fall_back_to_generic_class():
    result = _result(_ontology(_type("Organization", "firm"), _type("Insurer", "financial company")))
    assert result["agency_class"] is None
    assert result["basis"]["reason"] == "invalid_declared_class"


@pytest.mark.parametrize("ontology", [None, [], "firm", {}, {"entity_types": {}}, {"entity_types": [None, "firm", {}]},
                                     {"entity_types": [{"name": [], "agency_class": "firm"}]},
                                     {"entity_types": [], "bad": float("nan")}])
def test_invalid_missing_ontology_and_incidental_words_do_not_grant_class(ontology):
    actors = {"actors": [{"name": "Acme", "role": "leader", "description": "FTC regulator research"}]}
    assert _result(ontology, actors)["agency_class"] is None


def test_incidental_words_cannot_override_a_declared_class():
    for description in ("industry leader", "FTC regulator", "research institute"):
        actors = {"actors": [{"name": "Acme", "description": description}]}
        result = _result(_ontology(_type()), actors)
        assert result["agency_class"] == "firm"
        assert description not in json.dumps(result)


def test_ambiguous_identity_duplicate_uuid_and_missing_uuid_are_not_silently_rebound():
    actors = {"actors": [{"name": "First", "aliases": ["Acme"], "agency_class": "firm"},
                         {"name": "Second", "aliases": ["Acme"], "agency_class": "labor_union"}]}
    assert _result(_ontology(_type()), actors)["basis"]["reason"] == "ambiguous_dossier_identity"
    rows = build_agency_classifications([_entity(), _entity("Other")], None, _ontology(_type()))
    assert rows["entity-1"]["agency_class"] is None
    assert rows["entity-1"]["basis"]["reason"] == "duplicate_entity_uuid"
    assert build_agency_classifications([_entity(uuid=""), {}], None, None) == {}
    rows = build_agency_classifications([_entity(aliases=["Shared"]), _entity("Other", "entity-2", aliases=["Shared"])],
                                      None, _ontology(_type(examples=["Shared"])))
    assert all(r["agency_class"] is None for r in rows.values())
    assert all(r["basis"]["reason"] == "ambiguous_example_identity" for r in rows.values())


def test_one_dossier_cannot_grant_class_or_aliases_to_multiple_entity_uuids():
    entities = [_entity("First", aliases=["Shared"]), _entity("Second", "entity-2", aliases=["Shared"])]
    actors = {"actors": [{"name": "Shared", "aliases": ["Acme"], "type": "Vendor", "agency_class": "regulator_agency"}]}
    rows = build_agency_classifications(entities, actors, _ontology(_type()))
    assert all(r["agency_class"] is None for r in rows.values())
    assert all(r["basis"]["reason"] == "ambiguous_dossier_identity" for r in rows.values())
    actors["actors"][0].pop("agency_class")
    assert all(r["agency_class"] is None for r in build_agency_classifications(entities, actors, _ontology(_type())).values())


def test_map_is_pure_deterministic_uuid_bound_and_digest_covers_source():
    entities, actors, ontology = [_entity()], {"actors": [{"name": "Acme"}]}, _ontology(_type())
    before = deepcopy((entities, actors, ontology))
    rows = build_agency_classifications(entities, actors, ontology)
    assert (entities, actors, ontology) == before
    assert rows == build_agency_classifications(entities, actors, ontology)
    digest = hashlib.sha256(json.dumps(ontology, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()
    assert rows["entity-1"]["basis"]["ontology_sha256"] == digest
    read = agency_classification_for(rows, "entity-1")
    assert read == rows["entity-1"]
    read["basis"]["type_names"].append("changed")
    assert rows["entity-1"]["basis"]["type_names"] == ["Vendor"]
    assert agency_classification_for(rows, "different-uuid") is None
    rows["different-uuid"] = rows["entity-1"]
    assert agency_classification_for(rows, "different-uuid") is None


@pytest.mark.parametrize("key,bad", [("entity_uuid", "other"), ("source", "inference"), ("status", "unknown"),
                                    ("ontology_sha256", "invalid"), ("type_names", []), ("declarations", []),
                                    ("match_method", "substring"), ("status", []), ("source", {})])
def test_malformed_map_entries_grant_no_override(key, bad):
    rows = build_agency_classifications([_entity()], None, _ontology(_type()))
    rows["entity-1"]["basis"][key] = bad
    assert agency_classification_for(rows, "entity-1") is None


def test_map_class_tampering_and_unresolved_grants_are_rejected():
    rows = build_agency_classifications([_entity()], None, _ontology(_type()))
    rows["entity-1"]["agency_class"] = "regulator_agency"
    assert agency_classification_for(rows, "entity-1") is None
    rows["entity-1"]["basis"]["status"] = "unresolved"
    assert agency_classification_for(rows, "entity-1") is None


def _generator(monkeypatch):
    class ScriptedModel:
        def __init__(self, **kwargs):
            pass

        def chat(self, **kwargs):
            from tests.forecast_task_fakes import task_protocol
            task = task_protocol(kwargs["messages"][-1]["content"])
            if task is not None:
                return json.dumps(task)
            return json.dumps({"hot_topics": [], "initial_posts": [], "agents": [], "reasoning": "offline fixture"})

    monkeypatch.setattr("app.services.simulation_config_generator.LLMClient", ScriptedModel)
    for key, value in {"SIM_TEMPORAL_MODE": "calendar", "SIM_WORLD_MODEL": True, "SIM_AUDIENCE_AGENTS": 0,
                       "SIM_CONFIG_USE_LLM": False}.items():
        monkeypatch.setattr(Config, key, value, raising=False)
    monkeypatch.setattr("app.services.official_data.load_for_simulation", lambda *a, **k: None)
    gen = SimulationConfigGenerator(provider="fixture", model_name="fixture")
    # This isolated producer test has no manager-owned consumed-research seal or
    # backtest policy; the real generator, seed and decision consumers still run.
    monkeypatch.setattr(gen, "_backtest_pressure_weight", lambda *a: None)
    return gen


def _generate(gen, entities, actors, **kwargs):
    return gen.generate_config("c5-offline", "fixture-project", "fixture-graph", "Will adoption increase by 2027-01-31?",
                               "Research facts.", entities, actors=actors, research_language="English", max_rounds=3, **kwargs)


def _assert_consumers(params, rows):
    payload = params.to_dict()
    assert payload["world_model"]["actors"]
    assert len(payload["agent_configs"]) == len(payload["world_model"]["actors"])
    assert {c["agent_id"] for c in payload["agent_configs"]} == {s["agent_id"] for s in payload["world_model"]["actors"]}
    world = WorldModel.from_seed(payload["world_model"], payload["agent_configs"])
    assert set(world.actors) == {c["agent_id"] for c in payload["agent_configs"]}
    for config, seed in zip(payload["agent_configs"], payload["world_model"]["actors"], strict=True):
        declared = rows[config["entity_uuid"]]
        assert config["agency_class"] == seed["agency_class"] == declared["agency_class"]
        assert config["agency_class_basis"] == seed["agency_class_basis"] == declared["basis"]
        actor = world.actors[config["agent_id"]]
        assert actor.agency_class == declared["agency_class"]
        option = catalog_for(declared["agency_class"])[0].to_option()
        assert option_feasibility_problem(actor, option) is None
    return payload


def test_real_generator_applies_map_before_downstream_consumers_and_seed(monkeypatch):
    entities = [_entity(), _entity("Beta", "entity-2")]
    actors = {"as_of_date": "2026-10-01", "actors": [{"name": "Acme", "type": "Organization", "description": "FTC regulator"},
                                                     {"name": "Beta", "type": "Organization", "description": "research leader"}]}
    rows = build_agency_classifications(entities, actors, _ontology(_type(), _type("Insurer", "financial_institution", ["Beta"])))
    original = deepcopy(rows)
    gen = _generator(monkeypatch)
    assign = gen._assign_initial_post_agents

    def observe(event_config, configs):
        assert [c.agency_class for c in configs] == ["firm", "financial_institution"]
        return assign(event_config, configs)

    monkeypatch.setattr(gen, "_assign_initial_post_agents", observe)
    _assert_consumers(_generate(gen, entities, actors, agency_classifications=rows), rows)
    assert rows == original


def test_seed_uses_uuid_map_over_conflicting_legacy_inputs_and_keeps_unresolved_basis():
    cfg = asdict(AgentActivityConfig(0, "entity-1", "Acme", "Organization", agency_class="regulator_agency"))
    actors = {"actors": [{"name": "Acme", "description": "FTC regulator"}]}
    rows = build_agency_classifications([_entity()], actors, _ontology(_type()))
    seed = build_world_model_seed(actors, [cfg], agency_classifications=rows, ontology_classes={"Organization": "central_bank"})
    assert seed["actors"][0]["agency_class"] == "firm"
    conflict = build_agency_classifications([_entity()], actors, _ontology(_type(), _type("Insurer", "financial_institution")))
    seed = build_world_model_seed(actors, [cfg], agency_classifications=conflict)
    assert seed["actors"][0]["agency_class"] == resolve_agency_class(actors["actors"][0], "Organization")
    assert seed["actors"][0]["agency_class_basis"]["status"] == "unresolved"
    assert build_world_model_seed(actors, [cfg], agency_classifications={"entity-1": {"agency_class": "firm"}}) == build_world_model_seed(actors, [cfg])


def test_resolved_seed_does_not_recompute_legacy_inference(monkeypatch):
    rows = build_agency_classifications([_entity()], None, _ontology(_type()))

    def forbidden(*args, **kwargs):
        pytest.fail("resolved source declaration must bypass legacy inference")

    monkeypatch.setattr("app.services.world_model_seed.resolve_agency_class", forbidden)
    seed = build_world_model_seed(None, [AgentActivityConfig(0, "entity-1", "Acme", "Organization")],
                                  agency_classifications=rows)
    assert seed["actors"][0]["agency_class"] == "firm"


def test_missing_map_class_key_preserves_generator_seed_and_actor_membership(monkeypatch):
    rows = build_agency_classifications([_entity()], None, None)
    rows["entity-1"].pop("agency_class")
    assert agency_classification_for(rows, "entity-1") is None
    actors = {"as_of_date": "2026-10-01", "actors": [{"name": "Acme", "description": "FTC regulator"}]}
    gen = _generator(monkeypatch)
    old = _generate(gen, [_entity()], actors).to_dict()
    new = _generate(gen, [_entity()], actors, agency_classifications=rows).to_dict()
    assert new["agent_configs"] == old["agent_configs"]
    assert new["world_model"]["actors"] == old["world_model"]["actors"]
    assert len(new["world_model"]["actors"]) == 1
    cfg = AgentActivityConfig(0, "entity-1", "Acme", "Organization")
    assert build_world_model_seed(actors, [cfg], agency_classifications=rows) == build_world_model_seed(actors, [cfg])


def test_consumer_assertion_rejects_missing_trailing_seed_actor(monkeypatch):
    entities = [_entity(), _entity("Beta", "entity-2")]
    rows = build_agency_classifications(entities, None, _ontology(_type(examples=["Acme", "Beta"])))
    params = _generate(_generator(monkeypatch), entities, {"as_of_date": "2026-10-01"}, agency_classifications=rows)
    _assert_consumers(params, rows)
    params.world_model["actors"].pop()
    with pytest.raises(AssertionError):
        _assert_consumers(params, rows)


def test_omitted_map_preserves_serialized_legacy_fields_and_seed(monkeypatch):
    gen = _generator(monkeypatch)
    actors = {"as_of_date": "2026-10-01", "actors": [{"name": "Acme", "description": "FTC regulator"}]}
    omitted = _generate(gen, [_entity()], actors).to_dict()
    explicit_none = _generate(gen, [_entity()], actors, agency_classifications=None).to_dict()
    omitted.pop("generated_at")
    explicit_none.pop("generated_at")
    assert json.dumps(omitted) == json.dumps(explicit_none)
    assert "agency_class_basis" not in json.dumps(omitted)
    assert omitted["agent_configs"][0]["agency_class"] == "regulator_agency"
    bare = AgentActivityConfig(0, "entity-1", "Acme", "Organization")
    old_shape = asdict(bare)
    old_shape.pop("agency_class_basis")
    assert SimulationParameters("s", "p", "g", "q", agent_configs=[bare]).to_dict()["agent_configs"] == [old_shape]


@pytest.mark.guarded_runner
def test_prechange_serialized_bytes_when_staged(monkeypatch):
    """Compare no-map output with hash-pinned pre-change source staged by the controller."""
    root = Path(os.environ["MAIN_OFFLINE_EVIDENCE"])
    baseline = root / "c5-baseline"
    if not baseline.is_dir():
        pytest.skip("pre-change sources not staged in this guard run")
    receipt = json.loads((baseline / "receipt.json").read_text())

    def load_old(name):
        path = baseline / f"{name}.py"
        assert hashlib.sha256(path.read_bytes()).hexdigest() == receipt["sha256"][name]
        spec = importlib.util.spec_from_file_location(f"app.services._c5_baseline_{name}", path)
        module = importlib.util.module_from_spec(spec)
        monkeypatch.setitem(sys.modules, spec.name, module)
        spec.loader.exec_module(module)
        return module

    entities = [_entity(), _entity("Beta", "entity-2")]
    actors = {"as_of_date": "2026-10-01", "actors": [{"name": "Acme", "description": "FTC regulator"},
                                                     {"name": "Beta", "description": "research leader"}]}
    current = _generate(_generator(monkeypatch), entities, actors)
    old_generator = load_old("simulation_config_generator")
    old_seed = load_old("world_model_seed")
    old_generator.LLMClient = sys.modules["app.services.simulation_config_generator"].LLMClient
    gen = old_generator.SimulationConfigGenerator(provider="fixture", model_name="fixture")
    monkeypatch.setattr(gen, "_backtest_pressure_weight", lambda *a: None)
    with monkeypatch.context() as scoped:
        scoped.setitem(sys.modules, "app.services.world_model_seed", old_seed)
        previous = _generate(gen, entities, actors)
    current.generated_at = previous.generated_at = "2026-10-28T00:00:00"
    assert current.world_model and previous.world_model
    assert current.to_json().encode("utf-8") == previous.to_json().encode("utf-8")
    (root / "c5-legacy-bytes-proof.json").write_text(json.dumps({
        "baseline_revision": receipt["revision"], "source_sha256": receipt["sha256"],
        "no_map_serialized_bytes_equal": True,
        "config_sha256": hashlib.sha256(current.to_json().encode("utf-8")).hexdigest(),
    }, indent=2) + "\n")


@pytest.mark.guarded_runner
def test_frozen_private_specimen_when_staged(monkeypatch):
    """Opt-in proof: controller stages immutable snapshot copies inside guard root.

    Normal suites skip without private fixtures. No raw actors or transcripts are
    bundled here; the staged file hashes must agree with the frozen manifest.
    """
    root = Path(os.environ["MAIN_OFFLINE_EVIDENCE"])
    staged = root / "c5-snapshot"
    if not staged.is_dir():
        pytest.skip("private frozen snapshot not staged in this guard run")
    receipt = json.loads((staged / "snapshot-receipt.json").read_text())
    manifest_bytes = (staged / "manifest.json").read_bytes()
    assert hashlib.sha256(manifest_bytes).hexdigest() == receipt["manifestSHA256"]
    manifest = json.loads(manifest_bytes)
    paths = {"actors": "pipelines/pipe_9d9b84efcd3d/handoff/actors.json",
             "ontology": "pipelines/pipe_9d9b84efcd3d/handoff/ontology.json",
             "config": "simulations/sim_2a4f7d0e73de/simulation_config.json"}
    hashes = {r["path"]: r["sha256"] for r in manifest["files"]}
    inputs = {}
    for name, rel in paths.items():
        raw = (staged / rel).read_bytes()
        assert hashlib.sha256(raw).hexdigest() == hashes[rel]
        inputs[name] = json.loads(raw)
    expected = {"Anthropic": "firm", "CrowdStrike": "firm", "Munich Re": "financial_institution"}
    configs = [r for r in inputs["config"]["agent_configs"] if r.get("entity_name") in expected]
    assert len(configs) == 3
    entities = [_entity(c["entity_name"], c["entity_uuid"], [c["entity_type"]]) for c in configs]
    assert {c["entity_type"] for c in configs} == {"Organization"}
    rows = build_agency_classifications(entities, inputs["actors"], inputs["ontology"])
    assert all(rows[c["entity_uuid"]]["agency_class"] == expected[c["entity_name"]] for c in configs)
    assert all(c["agency_class"] != expected[c["entity_name"]] for c in configs)
    payload = _assert_consumers(_generate(_generator(monkeypatch), entities, inputs["actors"], agency_classifications=rows), rows)
    # The stored config is never rewritten or used as the corrected source.
    for rel in paths.values():
        assert hashlib.sha256((staged / rel).read_bytes()).hexdigest() == hashes[rel]
    evidence = {"source_hashes": {rel: hashes[rel] for rel in paths.values()},
                "corrections": [{"name": c["entity_name"], "before": c["agency_class"], "after": expected[c["entity_name"]],
                                 "basis": rows[c["entity_uuid"]]["basis"]} for c in configs],
                "generator_seed_decision_verified": True, "original_copies_unchanged": True}
    (root / "c5-specimen-proof.json").write_text(json.dumps(evidence, indent=2) + "\n")
    assert len(payload["agent_configs"]) == 3
