"""Research -> compiler -> actual observation regressions; offline guard only."""
from __future__ import annotations

from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

from app.services.world_simulation.compiler import build_compiler_messages, compile_world_spec
from app.services.world_simulation.contracts import WorldError, canonical_json, initial_snapshot
from app.services.world_simulation.examples import example_spec
from app.services.world_simulation.observations import build_observation


REPORT = "Acme seeks reliable deliveries. Beta preserves its reserves. The analyst projects a secret loss."
ASSUMPTION = {"kind": "scenario_assumption", "refs": ["scenario/v1"]}


def span(text, report=REPORT):
    start = report.index(text)
    return {"start": start, "end": start + len(text), "sha256": hashlib.sha256(text.encode()).hexdigest()}


def claim_basis(aid="a", cid="goals"):
    return {"kind": "source_claim", "refs": [{"actorId": aid, "claimId": cid}]}


def source_bundle(*, denied=False, analyst=False, private=False):
    claims = [
        {"claim_id": "goals", "claim": "Acme seeks reliable deliveries.", "evidence_type": "actor_stated_claim",
         "actor_knows": not denied, "visibility": "public", "report_ref": span("Acme seeks reliable deliveries.")},
        {"claim_id": "analyst", "claim": "The analyst projects a secret loss.", "evidence_type": "analyst_inference",
         "actor_knows": True, "visibility": "public", "report_ref": span("The analyst projects a secret loss.")},
    ]
    if analyst:
        claims[0]["evidence_type"] = "analyst_inference"
    if private:
        claims[0]["visibility"] = "modeler_only"
    return {"actors": [{"actor_id": "a", "name": "Acme", "claims": claims},
                       {"actor_id": "b", "name": "Beta", "claims": []}]}


def proposal():
    return {
        "periods": [{"start": "2030-01-01T00:00:00Z", "end": "2030-01-02T00:00:00Z"}],
        "actors": [{"actorId": "a", "name": "Acme", "basis": claim_basis(), "capabilities": ["wait"],
                    "objectives": [{"text": "Acme seeks reliable deliveries.", "basis": claim_basis()}]}],
        "initialState": {"accounts": {}, "metrics": {}, "rules": {}, "relations": {}},
        "actionCatalog": [{"templateId": "wait", "kind": "wait", "actorIds": ["a"],
                           "description": "Wait for the next decision time.", "parameters": {}, "inputs": {},
                           "basis": deepcopy(ASSUMPTION), "visibility": {"kind": "public"}}],
        "assumptions": [{"assumptionId": "scenario/v1", "description": "Timing, actions and behavioral priors are scenario stipulations."}],
    }


def compile_proposal(raw=None, *, bundle=None, report=REPORT, engine="v3"):
    return compile_world_spec(proposal() if raw is None else raw, simulation_id="sim", generation_id="world1",
                              research_report=report, research_generation_id="research1", research_engine=engine,
                              actor_bundle=source_bundle() if bundle is None else bundle)


def test_source_bound_v3_derivative_is_distinct_and_unsealed():
    raw, bundle = proposal(), source_bundle()
    originals = deepcopy((raw, bundle))
    raw["sourceBindings"] = {"researchGenerationId": "forged", "evidenceGrade": "sealed-legacy"}
    original_raw = deepcopy(raw)
    spec = compile_proposal(raw, bundle=bundle)
    assert raw == original_raw and bundle == originals[1]
    assert spec["sourceBindings"]["researchGenerationId"] == "research1"
    assert spec["sourceBindings"]["legacyContractSha256"] is None
    assert spec["actors"][0]["evidenceGrade"] == "unsealed-v3"
    assert spec["actors"][0]["values"] == []
    assert spec["actors"][0]["fieldStatus"]["values"] == "unknown"
    obs = build_observation(spec, initial_snapshot(spec), "a", 1)
    assert obs["actor"]["objectives"][0]["text"] == "Acme seeks reliable deliveries."
    assert "secret loss" not in canonical_json(obs)
    assert "legacyContractSha256" not in canonical_json(obs)


@pytest.mark.parametrize("change", ["denied", "analyst", "private"])
def test_rejects_denied_and_modeler_actor_profiles(change):
    with pytest.raises(WorldError) as error:
        compile_proposal(bundle=source_bundle(**{change: True}))
    assert error.value.code == "forbidden_actor_evidence"


def test_false_qualifier_overrides_public_and_true_top_level():
    bundle = source_bundle()
    bundle["actors"][0]["claims"][0]["qualifiers"] = {"actor_knows": False}
    with pytest.raises(WorldError, match="partition"):
        compile_proposal(bundle=bundle)


def test_report_span_never_admits_private_profile_text():
    raw = proposal()
    raw["actors"][0]["objectives"] = [{"text": "The analyst projects a secret loss.",
        "basis": {"kind": "report_excerpt", "refs": [span("The analyst projects a secret loss.")]}}]
    with pytest.raises(WorldError) as error:
        compile_proposal(raw)
    assert error.value.code == "forbidden_actor_evidence"


def test_assumption_cannot_launder_denied_duplicate_text():
    raw = proposal()
    raw["actors"][0]["objectives"] = [{"text": "Acme seeks reliable deliveries.", "basis": deepcopy(ASSUMPTION)}]
    with pytest.raises(WorldError) as error:
        compile_proposal(raw, bundle=source_bundle(denied=True))
    assert error.value.code == "forbidden_actor_evidence"


def test_other_actor_private_claim_cannot_become_objective():
    raw, bundle = proposal(), source_bundle()
    row = deepcopy(bundle["actors"][0]["claims"][0])
    row.update(visibility="actor_known", claim_id="beta_goal")
    bundle["actors"][1]["claims"] = [row]
    raw["actors"][0]["objectives"][0]["basis"] = claim_basis("b", "beta_goal")
    with pytest.raises(WorldError) as error:
        compile_proposal(raw, bundle=bundle)
    assert error.value.code == "forbidden_actor_evidence"


@pytest.mark.parametrize("change", ["name", "actor_basis", "claim", "report_hash", "source_text", "grade"])
def test_rejects_identity_provenance_and_grade_forgery(change):
    raw, bundle = proposal(), source_bundle()
    if change == "name":
        raw["actors"][0]["name"] = "Counterfeit Acme"
    elif change == "actor_basis":
        raw["actors"][0]["basis"] = claim_basis("b", "goals")
    elif change == "claim":
        raw["actors"][0]["objectives"][0]["basis"] = claim_basis("a", "invented")
    elif change == "report_hash":
        bundle["actors"][0]["claims"][0]["report_ref"]["sha256"] = "0" * 64
    elif change == "source_text":
        raw["actors"][0]["objectives"][0]["text"] = "Acme can create unlimited capital."
    else:
        raw["actors"][0]["evidenceGrade"] = "sealed-legacy"
    with pytest.raises(WorldError):
        compile_proposal(raw, bundle=bundle)


def test_report_only_identity_has_unknown_behaviors():
    raw = proposal()
    actor = raw["actors"][0]
    actor["basis"] = {"kind": "report_excerpt", "refs": [span("Acme seeks reliable deliveries.")]}
    del actor["objectives"]
    spec = compile_proposal(raw, bundle={"actors": []})
    assert spec["actors"][0]["evidenceGrade"] == "unsealed-v3"
    assert set(spec["actors"][0]["fieldStatus"].values()) == {"unknown"}


def test_declared_behavior_prior_remains_assumption():
    raw = proposal()
    raw["actors"][0]["values"] = [{"text": "Prefer reversible commitments.", "basis": deepcopy(ASSUMPTION)}]
    spec = compile_proposal(raw)
    item = spec["actors"][0]["values"][0]
    assert item["evidenceType"] == "scenario_assumption"
    assert item["basis"] == ASSUMPTION
    assert spec["actors"][0]["evidenceGrade"] == "unsealed-v3"


def test_unknown_nonrequired_metric_remains_unknown():
    raw = proposal()
    raw["initialState"]["metrics"]["capacity"] = {"kind": "rate", "value": None, "unit": "goods",
        "valueStatus": "unknown", "visibility": {"kind": "analyst"}, "basis": claim_basis()}
    spec = compile_proposal(raw)
    assert spec["initialState"]["metrics"]["capacity"]["value"] is None
    assert spec["initialState"]["metrics"]["capacity"]["valueStatus"] == "unknown"


def test_invented_initial_number_needs_declared_assumption():
    raw = proposal()
    raw["initialState"]["accounts"]["cash"] = {"ownerId": "a", "unit": "currency", "balance": "100",
        "visibility": {"kind": "actors", "actorIds": ["a"]}, "basis": claim_basis()}
    with pytest.raises(WorldError) as error:
        compile_proposal(raw)
    assert error.value.code == "undeclared_numeric_assumption"
    raw["initialState"]["accounts"]["cash"]["basis"] = deepcopy(ASSUMPTION)
    assert compile_proposal(raw)["initialState"]["accounts"]["cash"]["balance"] == "100"


def test_exact_typed_numeric_claim_field_and_unit_required():
    raw, bundle = proposal(), source_bundle()
    report = REPORT + '\n{"balance":"12","unit":"currency","claim":"Acme seeks reliable deliveries."}'
    bundle["actors"][0]["claims"][0]["report_ref"] = span(report.splitlines()[-1], report)
    bundle["actors"][0]["claims"][0]["qualifiers"] = {"balance": "12", "unit": "currency"}
    basis = claim_basis()
    basis["refs"][0].update(field="qualifiers.balance", target="balance")
    raw["initialState"]["accounts"]["cash"] = {"ownerId": "a", "unit": "currency", "balance": "12",
        "visibility": {"kind": "actors", "actorIds": ["a"]}, "basis": basis}
    assert compile_proposal(raw, bundle=bundle, report=report)["initialState"]["accounts"]["cash"]["balance"] == "12"
    raw["initialState"]["accounts"]["cash"]["unit"] = "assets"
    with pytest.raises(WorldError) as error:
        compile_proposal(raw, bundle=bundle, report=report)
    assert error.value.code == "unsupported_quantity_mapping"


def test_v3_cannot_inject_unverified_source_support_for_quantity():
    raw, bundle = proposal(), source_bundle()
    claim = bundle["actors"][0]["claims"][0]
    claim["qualifiers"] = {"balance": "12", "unit": "currency"}
    claim["source_support"] = [{"supporting_quote": '{"balance":"12","unit":"currency"}'}]
    basis = claim_basis()
    basis["refs"][0].update(field="qualifiers.balance", target="balance")
    raw["initialState"]["accounts"]["cash"] = {"ownerId": "a", "unit": "currency", "balance": "12",
        "visibility": {"kind": "actors", "actorIds": ["a"]}, "basis": basis}
    with pytest.raises(WorldError) as error:
        compile_proposal(raw, bundle=bundle)
    assert error.value.code == "unsupported_quantity_mapping"


@pytest.mark.parametrize("location", ["qualifiers.evidence_type", "epistemic_status", "qualifiers.epistemic_status", "conflict"])
def test_analyst_classification_aliases_cannot_grant_actor_knowledge(location):
    bundle = source_bundle()
    claim = bundle["actors"][0]["claims"][0]
    if location != "conflict":
        claim.pop("evidence_type")
    if location.startswith("qualifiers."):
        claim["qualifiers"] = {location.split(".")[1]: "analyst_inference"}
    else:
        claim["epistemic_status"] = "analyst_inference"
    with pytest.raises(WorldError) as error:
        compile_proposal(bundle=bundle)
    assert error.value.code == "forbidden_actor_evidence"


def test_nested_menu_text_is_checked_before_json_escaping():
    raw = proposal()
    raw["actionCatalog"][0]["inputs"] = {"choice": {"type": "string", "enum": ["The analyst\nprojects a secret loss."]}}
    with pytest.raises(WorldError) as error:
        compile_proposal(raw)
    assert error.value.code == "forbidden_actor_evidence"


def test_initial_assumption_cannot_claim_verified_fact_status():
    raw = proposal()
    raw["initialState"]["rules"]["permit"] = {"value": True, "basis": deepcopy(ASSUMPTION),
        "visibility": {"kind": "public"}, "evidenceType": "verified_fact", "valueStatus": "specified"}
    result = compile_proposal(raw)
    assert result["initialState"]["rules"]["permit"]["evidenceType"] == "scenario_assumption"


def test_nonnumeric_authority_requires_typed_evidence_or_assumption():
    raw = proposal()
    raw["initialState"]["rules"]["permit"] = {"value": True, "basis": claim_basis(), "visibility": {"kind": "public"}}
    with pytest.raises(WorldError) as error:
        compile_proposal(raw)
    assert error.value.code == "undeclared_model_assumption"


@pytest.mark.parametrize("target", ["scheduled", "policy", "agreement", "vote"])
def test_future_effects_cannot_publish_modeler_text_through_target_state(target):
    secret = "The analyst projects a secret loss."
    if target == "scheduled":
        raw = proposal()
        raw["initialState"]["rules"]["permit"] = {"value": True, "basis": deepcopy(ASSUMPTION), "visibility": {"kind": "public"}}
        raw["scheduledEvents"] = [{"eventId": "change", "kind": "rule_set", "at": "2030-01-01T12:00:00Z",
            "parameters": {"ruleId": "permit", "value": secret}, "visibility": {"kind": "analyst"}, "basis": deepcopy(ASSUMPTION)}]
    else:
        raw = example_spec("trade" if target == "policy" else "coalition", simulation_id="sim", generation_id="world1")
        template = next(t for t in raw["actionCatalog"] if t["kind"] == target)
        template["parameters"][{"policy": "value", "agreement": "relationValue", "vote": "ruleValue"}[target]] = secret
        template["visibility"] = {"kind": "analyst"}
    with pytest.raises(WorldError) as error:
        compile_proposal(raw)
    assert error.value.code == "forbidden_actor_evidence"


def test_scheduled_delta_requires_known_initial_metric_before_launch():
    raw = proposal()
    raw["initialState"]["metrics"]["stock"] = {"kind": "stock", "unit": "goods", "value": None,
        "valueStatus": "unknown", "basis": deepcopy(ASSUMPTION), "visibility": {"kind": "public"}}
    raw["scheduledEvents"] = [{"eventId": "delivery", "kind": "metric_delta", "at": "2030-01-01T12:00:00Z",
        "parameters": {"targetMetric": "stock", "delta": "3"}, "visibility": {"kind": "public"}, "basis": deepcopy(ASSUMPTION)}]
    with pytest.raises(WorldError) as error:
        compile_proposal(raw)
    assert error.value.code == "modeling_gap"


def test_profile_reference_cannot_carry_extra_private_metadata():
    raw = proposal()
    raw["actors"][0]["objectives"][0]["basis"]["refs"][0]["field"] = "The analyst projects a secret loss."
    with pytest.raises(WorldError) as error:
        compile_proposal(raw)
    assert error.value.code == "unresolved_source"


def test_agreement_condition_cannot_disclose_denied_modeler_text():
    raw = example_spec("coalition", simulation_id="sim", generation_id="world1")
    secret = "The analyst projects a secret loss."
    basis = deepcopy(raw["actionCatalog"][0]["basis"])
    raw["initialState"]["rules"]["secret_condition"] = {"value": secret, "visibility": {"kind": "analyst"}, "basis": basis}
    template = next(t for t in raw["actionCatalog"] if t["kind"] == "agreement")
    template["parameters"].update(requiresRule="secret_condition", requiredRuleValue=secret)
    template["visibility"] = {"kind": "analyst"}
    with pytest.raises(WorldError) as error:
        compile_proposal(raw)
    assert error.value.code == "forbidden_actor_evidence"


@pytest.mark.parametrize("basis_kind", ["report_excerpt", "scenario_assumption"])
def test_existing_actor_name_cannot_be_rebound_to_invented_id(basis_kind):
    raw = proposal()
    actor = raw["actors"][0]
    actor.update(actorId="impostor", basis=deepcopy(ASSUMPTION) if basis_kind == "scenario_assumption"
                 else {"kind": "report_excerpt", "refs": [span("Acme seeks reliable deliveries.")]})
    actor.pop("objectives")
    raw["actionCatalog"][0]["actorIds"] = ["impostor"]
    with pytest.raises(WorldError) as error:
        compile_proposal(raw)
    assert error.value.code == "actor_basis_mismatch"


@pytest.mark.parametrize("evidence_type", ["unknown", "contested"])
def test_unresolved_cash_cannot_fund_actions_without_resolving_assumption(evidence_type):
    raw, bundle = proposal(), source_bundle()
    report = REPORT + '\n{"balance":"12","unit":"currency","claim":"Acme seeks reliable deliveries."}'
    claim = bundle["actors"][0]["claims"][0]
    claim.update(report_ref=span(report.splitlines()[-1], report), evidence_type=evidence_type,
                 qualifiers={"balance": "12", "unit": "currency"})
    basis = claim_basis()
    basis["refs"][0].update(field="qualifiers.balance", target="balance")
    raw["initialState"]["accounts"] = {
        "cash": {"ownerId": "a", "unit": "currency", "balance": "12", "visibility": {"kind": "public"}, "basis": basis},
        "sink": {"ownerId": "external", "unit": "currency", "balance": "0", "visibility": {"kind": "public"}, "basis": deepcopy(ASSUMPTION)}}
    raw["actors"][0]["capabilities"].append("pay")
    raw["actionCatalog"].append({"templateId": "pay", "kind": "transfer", "actorIds": ["a"],
        "description": "Pay the declared cost.", "parameters": {"fromAccount": "cash", "toAccount": "sink", "amount": "3"},
        "inputs": {}, "visibility": {"kind": "public"}, "basis": deepcopy(ASSUMPTION)})
    with pytest.raises(WorldError) as error:
        compile_proposal(raw, bundle=bundle, report=report)
    assert error.value.code == "modeling_gap"
    raw["initialState"]["accounts"]["cash"]["basis"] = deepcopy(ASSUMPTION)
    result = compile_proposal(raw, bundle=bundle, report=report)
    assert result["initialState"]["accounts"]["cash"]["evidenceType"] == "scenario_assumption"
    assert result["actors"][0]["objectives"][0]["valueStatus"] == evidence_type


@pytest.mark.parametrize("key", ["reserved", "basis"])
def test_nested_metadata_names_do_not_bypass_value_provenance(key):
    raw = proposal()
    raw["initialState"]["rules"]["coefficient"] = {"value": {key: "999"}, "basis": claim_basis(), "visibility": {"kind": "public"}}
    with pytest.raises(WorldError) as error:
        compile_proposal(raw)
    assert error.value.code == "undeclared_numeric_assumption"


def test_explicit_pinned_policy_survives_compilation_without_defaults_or_mutation():
    raw = proposal()
    raw["policy"] = {
        "provider": "openai", "model": "fixture-model-v1", "baseUrl": "https://fixture.invalid/v1",
        "timeoutSeconds": 17, "maxInputTokens": 30000,
        "pricing": {"provider": "openai", "model": "fixture-model-v1", "baseUrl": "https://fixture.invalid/v1",
                    "inputUsdPerMillion": "2", "outputUsdPerMillion": "9", "contextWindowTokens": 32768,
                    "maxOutputTokens": 2048, "inputOverheadTokens": 256,
                    "outputTokenParameter": "max_completion_tokens", "maxOutputIncludesReasoning": True,
                    "source": {"reference": "fixture://synthetic-tariff", "asOf": "2026-10-16T00:00:00Z"}}}
    before = canonical_json(raw["policy"])
    result = compile_proposal(raw)
    assert canonical_json(result["policy"]) == before == canonical_json(raw["policy"])
    assert result["policy"] is not raw["policy"]
    assert "policy" not in compile_proposal()
    observation = build_observation(result, initial_snapshot(result), "a", 1)
    assert "fixture-model-v1" not in canonical_json(observation)


@pytest.mark.parametrize("policy", [
    {"apiKey": "fixture-only"}, {"provider": {"apiKey": "fixture-only"}},
    {"baseUrl": "https://user:fixture-only@fixture.invalid/v1"},
    {"pricing": {"apiKey": "fixture-only"}},
    {"pricing": {"inputUsdPerMillion": 0.25}},
])
def test_policy_cannot_carry_credentials_or_noncanonical_quantities(policy):
    raw = proposal()
    raw["policy"] = policy
    with pytest.raises(WorldError):
        compile_proposal(raw)


@pytest.mark.parametrize("visibility", [{"kind": "public"}, {"kind": "actors", "actorIds": ["a"]}])
def test_visible_assumption_cannot_disclose_denied_text(visibility):
    raw = proposal()
    raw["assumptions"][0].update(description="The analyst projects a secret loss.", visibility=visibility)
    with pytest.raises(WorldError) as error:
        compile_proposal(raw)
    assert error.value.code == "forbidden_actor_evidence"


def test_assumption_visibility_is_normalized_after_actor_roster_and_defaults_private():
    raw = proposal()
    raw["assumptions"][0]["description"] = "The analyst projects a secret loss."
    result = compile_proposal(raw)
    assert result["assumptions"][0]["visibility"] == {"kind": "analyst"}
    raw["assumptions"][0].update(description="Timing is a declared assumption.", visibility={"kind": "actors", "actorIds": ["a", "a"]})
    result = compile_proposal(raw)
    assert result["assumptions"][0]["visibility"] == {"kind": "actors", "actorIds": ["a"]}
    raw["assumptions"][0]["visibility"]["actorIds"] = ["not-admitted"]
    with pytest.raises(WorldError) as error:
        compile_proposal(raw)
    assert error.value.code == "invalid_visibility"


def test_source_mechanism_numbers_require_typed_support():
    raw = proposal()
    raw["actionCatalog"][0].update(kind="message", parameters={"messageDelayDays": "3"},
        inputs={"text": {"type": "string", "required": True}}, basis=claim_basis(),
        description="Acme seeks reliable deliveries.")
    with pytest.raises(WorldError) as error:
        compile_proposal(raw)
    assert error.value.code == "undeclared_numeric_assumption"


@pytest.mark.parametrize("domain", ["investment", "trade", "coalition"])
def test_existing_synthetic_examples_compile_without_fake_sources(domain):
    raw = example_spec(domain, simulation_id="sim", generation_id="world1")
    spec = compile_proposal(raw)
    assert all(a["evidenceGrade"] == "scenario-assumption" for a in spec["actors"])
    assert spec["assumptions"][0]["assumptionId"] == "synthetic-example/v1"
    assert spec["sourceBindings"]["legacyContractSha256"] is None


def test_missing_required_parameter_uses_kernel_validator_before_launch():
    raw = example_spec("trade", simulation_id="sim", generation_id="world1")
    del raw["actionCatalog"][0]["parameters"]["durationDays"]
    with pytest.raises(WorldError) as error:
        compile_proposal(raw)
    assert error.value.code == "modeling_gap"
    assert error.value.details["cause"] == "invalid_mechanism"


def test_missing_required_physical_value_blocks_instead_of_using_zero():
    raw = proposal()
    raw["initialState"]["accounts"] = {
        "supply": {"ownerId": "external", "unit": "goods", "balance": "20", "visibility": {"kind": "public"}, "basis": deepcopy(ASSUMPTION)},
        "stock": {"ownerId": "a", "unit": "goods", "balance": "0", "visibility": {"kind": "public"}, "basis": deepcopy(ASSUMPTION)}}
    raw["initialState"]["metrics"]["rate"] = {"kind": "rate", "unit": "goods", "value": None,
        "visibility": {"kind": "analyst"}, "basis": deepcopy(ASSUMPTION)}
    raw["flows"] = [{"flowId": "production", "sourceAccount": "supply", "targetAccount": "stock", "rateMetric": "rate",
                     "visibility": {"kind": "public"}, "basis": deepcopy(ASSUMPTION)}]
    with pytest.raises(WorldError) as error:
        compile_proposal(raw)
    assert error.value.code == "modeling_gap"


@pytest.mark.parametrize("value", [None, [], {"actors": None}, {"actors": [None]}, {"actors": [{"actorId": []}]}])
def test_malformed_input_returns_world_error(value):
    with pytest.raises(WorldError):
        compile_proposal(value if value is not None else {"bad": None})


def test_arbitrary_python_and_explicit_gaps_are_not_launchable():
    raw = proposal()
    raw["gaps"] = [{"code": "unknown_authority", "description": "No admitted authority."}]
    with pytest.raises(WorldError) as error:
        compile_proposal(raw)
    assert error.value.code == "modeling_gap"
    raw.pop("gaps")
    raw["python"] = "import os"
    with pytest.raises(WorldError) as error:
        compile_proposal(raw)
    assert error.value.code == "invalid_spec"


def test_bounded_modeler_prompt_uses_actual_research_and_partition_metadata():
    bundle = source_bundle(denied=True)
    original = deepcopy(bundle)
    messages = build_compiler_messages(research_report=REPORT, research_generation_id="research1",
        research_engine="v3", actor_bundle=bundle, ontology={"entityTypes": ["Organization"]},
        simulation_requirement="Test a single delivery decision.")
    assert [m["role"] for m in messages] == ["system", "user"]
    assert "no Python" in messages[0]["content"]
    data = json.loads(messages[1]["content"])
    assert data["report"] == REPORT and data["ontology"]["entityTypes"] == ["Organization"]
    # Claims are grouped by actor; a supplied (non-derived) claim keeps its full record.
    assert data["claims"][0]["actorId"] == "a"
    assert data["claims"][0]["claims"][0]["actorAllowed"] is False
    assert data["claims"][0]["claims"][0]["claim"]["claim_id"] == "goals"
    assert bundle == original
    with pytest.raises(WorldError) as error:
        build_compiler_messages(research_report="x" * 240001, research_generation_id="research1", research_engine="v3")
    assert error.value.code == "compiler_context_limit"


@pytest.fixture(scope="module")
def producer():
    path = Path(__file__).resolve().parents[2] / "deerflow_bridge" / "deerflow_research.py"
    spec = importlib.util.spec_from_file_location("world_compiler_producer_fixture", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def sealed_bundle(tmp_path, monkeypatch, producer):
    # Reuse the real producer-to-parent fixture; do not hand-fabricate seals.
    from test_pipeline_actor_contract import _write_producer_valid_bundle
    return _write_producer_valid_bundle(tmp_path, producer, monkeypatch)


def sealed_proposal(bundle):
    raw = proposal()
    actor = bundle["actors"]["actors"][0]
    aid = actor["actor_id"]
    claim = actor["intelligence"]["dimensions"]["identity_history"][0]
    raw["actors"] = [{"actorId": aid, "name": actor["name"], "basis": claim_basis(aid, claim["claim_id"]), "capabilities": ["wait"]}]
    raw["actionCatalog"][0]["actorIds"] = [aid]
    return raw


def test_real_legacy_seals_preserved_in_separate_derivative(sealed_bundle):
    bundle = {key: sealed_bundle[key] for key in ("actors", "sources", "dossier")}
    original = deepcopy(bundle)
    spec = compile_proposal(sealed_proposal(sealed_bundle), bundle=bundle, report=sealed_bundle["report"], engine="legacy")
    assert spec["actors"][0]["evidenceGrade"] == "sealed-legacy"
    assert spec["sourceBindings"]["legacyContractSha256"]
    assert bundle == original
    # The real fixture has no actor-knowledge grants; evidence is not copied as beliefs.
    assert spec["actors"][0]["beliefs"] == []


@pytest.mark.parametrize("mutation", ["report", "dossier", "sources", "claim", "missing_seal", "v3_upgrade"])
def test_invalid_legacy_cannot_downgrade_or_reseal(sealed_bundle, mutation):
    bundle = {key: deepcopy(sealed_bundle[key]) for key in ("actors", "sources", "dossier")}
    report, engine = sealed_bundle["report"], "legacy"
    raw = sealed_proposal(sealed_bundle)
    if mutation == "report":
        report += "tamper"
    elif mutation == "dossier":
        bundle["dossier"] += "tamper"
    elif mutation == "sources":
        bundle["sources"][0]["excerpt"] += "tamper"
    elif mutation == "claim":
        bundle["actors"]["actors"][0]["intelligence"]["dimensions"]["identity_history"][0]["claim"] += "tamper"
    elif mutation == "missing_seal":
        bundle["actors"].pop("actor_intelligence_contract")
    else:
        engine = "v3"
    original = deepcopy(bundle)
    with pytest.raises(WorldError):
        compile_proposal(raw, bundle=bundle, report=report, engine=engine)
    assert bundle == original
