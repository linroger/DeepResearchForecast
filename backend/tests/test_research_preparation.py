"""Actual offline compiler -> persisted bundle -> public seed producer contracts."""
from copy import deepcopy
import hashlib
import json

import pytest

from app.services import actor_context as ac
from app.services import research_preparation as rp
from app.services.world_model_seed import build_world_model_seed
from app.services.world_model import WorldModel


def series(**overrides):
    row = {"series": "fred:GDP", "provider": "fred", "title": "GDP", "geography": "US",
           "units": "Billions of Dollars", "frequency": "Q", "source_id": "S1",
           "source_url": "https://fred.stlouisfed.org/series/GDP", "retrieved_at": "2026-07-01T00:00:00Z",
           "observations": [{"date": "2026-01-01", "value": 100, "flag": "observed"},
                            {"date": "2026-04-01", "value": 110, "flag": "preliminary"},
                            {"date": "2026-10-01", "value": 200, "flag": "projection"}], "provenance": {}}
    row.update(overrides)
    return row


def fact(**overrides):
    row = {"metric": "Revenue", "entity": "Alpha", "value": 2, "unit": "USD billion",
           "as_of_date": "2026-07-01", "period_end": "2026-06-30", "value_type": "actual",
           "source": "Annual report", "source_refs": ["S2"]}
    row.update(overrides)
    return row


def compile_bundle(**overrides):
    args = {"question": "Will capacity expand?", "research_report": "Exact research report.",
            "actors": {"as_of_date": "2026-07-01", "actors": [], "quantitative_facts": []},
            "source_binding": {"research_generation_id": "generation-1"}}
    args.update(overrides)
    return rp.compile_preparation_context(**args)


def reseal(bundle):
    bundle["content_sha256"] = ac.canonical_json_sha256({k: v for k, v in bundle.items() if k != "content_sha256"})


def canonical_fixture():
    from test_actor_context_runtime import _dossier, REPORT
    actors = _dossier()
    for actor in actors["actors"]:
        for dimension, rows in actor["intelligence"]["dimensions"].items():
            for row in rows:
                row["visibility"] = "public"
    plans = actors["actors"][0]["intelligence"]["dimensions"]["future_plans"]
    plans[0]["conditions"] = ["Only after a permit is granted"]
    plans += [{**deepcopy(plans[0]), "claim": "CANCELLED PUBLIC ACTION", "status": "cancelled"},
              {**deepcopy(plans[0]), "claim": "PRIVATE OWNER PLAN", "visibility": "private", "actor_knows": True},
              {**deepcopy(plans[0]), "claim": "DENIED SECRET", "actor_knows": False},
              {**deepcopy(plans[0]), "claim": "ANALYST GUESS", "evidence_type": "analyst_inference"}]
    actors["quantitative_facts"] = [
        fact(metric="Alpha Systems revenue", visibility="public", evidence_type="verified_fact"),
        fact(metric="Alpha Systems private budget", value=777, visibility="private", actor_knows=True, actor_id="actor_alpha",
             evidence_type="verified_fact")]
    packs = {a["actor_id"]: ac.build_actor_context_pack(actors, a, REPORT) for a in actors["actors"]}
    return actors, packs, REPORT


def test_actual_compiler_keeps_native_history_identity_and_guidance():
    bundle = compile_bundle(official_data={"series": [series()]}, report_artifacts={"quantitative.json": [fact(value=0)]})
    rows = bundle["quantitative"]["observations"]
    official = next(r for r in rows if r["source_kind"] == "official_observation")
    assert official["value"] == 110 and official["unit"] == "Billions of Dollars"
    assert official["period"] == "2026-04-01" and official["period_end"] == "2026-06-30"
    assert [p["status"] for p in official["history"]] == ["observed", "preliminary"]
    assert official["diagnostic_summary"]["change_native_units"] == 10
    assert official["diagnostic_summary"]["diagnostic_only"] is True
    assert next(r for r in rows if r["source_kind"] == "research_fact")["value"] == 0
    assert bundle["quantitative"]["guidance"][0]["value"] == 200
    assert bundle["source"]["source_binding"]["research_generation_id"] == "generation-1"
    assert compile_bundle(official_data={"series": [series()]}, report_artifacts={"quantitative.json": [fact(value=0)]}) == bundle


@pytest.mark.parametrize("value,unit,expected", [("US$2 billion", "USD billion", 2),
                                               ("2.75", "million metric tonnes per annum", 2.75),
                                               ("2%", "%", 2), (0, "basis points", 0)])
def test_complete_native_values_never_scale_twice(value, unit, expected):
    bundle = compile_bundle(report_artifacts={"quantitative.json": [fact(value=value, unit=unit)]})
    row = bundle["quantitative"]["observations"][0]
    assert row["value"] == expected and row["unit"] == unit


@pytest.mark.parametrize("value,unit", [(True, "USD"), ("2 billion", "USD"), ("2 to 4", "USD"),
                                       ("about 2", "USD"), ("2%", "USD"), (3, "")])
def test_ambiguous_or_boolean_values_are_gaps(value, unit):
    bundle = compile_bundle(report_artifacts={"quantitative.json": [fact(value=value, unit=unit)]})
    assert not bundle["quantitative"]["observations"]
    assert bundle["gaps"][0]["kind"] == "quantitative_not_admitted"


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -float("inf")])
def test_nonfinite_inputs_cannot_be_hashed_or_compiled(value):
    with pytest.raises(ValueError):
        compile_bundle(report_artifacts={"quantitative.json": [fact(value=value)]})


def test_estimates_targets_unknown_and_projections_never_initial_state():
    facts = [fact(metric=status, value_type=status) for status in ("estimate", "target", "forecast", "unknown")]
    bundle = compile_bundle(report_artifacts={"quantitative.json": facts})
    assert not bundle["quantitative"]["observations"]
    assert {r["status"] for r in bundle["quantitative"]["guidance"]} == {"estimate", "target", "projection", "unknown"}


def test_identical_names_units_different_entities_or_series_never_merge():
    facts = [fact(entity="Alpha"), fact(entity="Beta"), fact(entity="Alpha", series="company:other")]
    bundle = compile_bundle(report_artifacts={"quantitative.json": facts})
    assert len({r["id"] for r in bundle["quantitative"]["observations"]}) == 3


def test_conflicting_values_are_excluded_without_choosing_a_winner():
    bundle = compile_bundle(report_artifacts={"quantitative.json": [fact(value=2), fact(value=3)]})
    assert not bundle["quantitative"]["observations"]
    assert bundle["gaps"][0]["kind"] == "conflicting_values"


def test_official_cutoff_is_exact_and_window_pinned():
    official = {"series": [series(retrieved_at="2026-07-02T01:00:00Z")]}
    strict = compile_bundle(official_data=official, as_of="2026-07-01")
    assert not strict["quantitative"]["observations"]
    window = {"started_at": "2026-07-01T20:00:00Z", "finished_at": "2026-07-02T02:00:00Z"}
    live = compile_bundle(official_data=official, as_of={"as_of": "2026-07-01", "research_window": window})
    assert live["quantitative"]["observations"]
    window["finished_at"] = "2030-01-01"
    assert live["scope"]["research_window"]["finished_at"] == "2026-07-02T02:00:00Z"
    intraday = compile_bundle(official_data=official, as_of="2026-07-02T00:00:00Z")
    assert not intraday["quantitative"]["observations"]


def test_official_partial_unsafe_and_future_observation_are_not_state():
    raw = series(provenance={"resolution_safe": False})
    bundle = compile_bundle(official_data={"series": [raw]})
    assert not bundle["quantitative"]["observations"]
    assert {r["status"] for r in bundle["quantitative"]["guidance"]} == {"unknown", "projection"}
    raw = series(observations=[{"date": "2026-07-01", "value": 5, "flag": "observed"}])
    bundle = compile_bundle(official_data={"series": [raw]})
    assert not bundle["quantitative"]["observations"]
    assert bundle["gaps"][0]["kind"] == "period_after_cutoff"


def test_official_restated_sidecar_cannot_bypass_carrier_status():
    raw = series(retrieved_at="2027-01-01")
    bundle = compile_bundle(official_data={"series": [raw]}, report_artifacts={"quantitative.json": [
        fact(series="fred:GDP", source_origin="official_data")]})
    assert not bundle["quantitative"]["observations"]


def test_history_is_bounded_with_diagnostic_omission_count():
    observations = [{"date": f"{year}-01-01", "value": year, "flag": "observed"} for year in range(1950, 2026)]
    bundle = compile_bundle(official_data={"series": [series(frequency="A", observations=observations)]})
    row = bundle["quantitative"]["observations"][0]
    assert len(row["history"]) == rp.HISTORY_LIMIT
    assert row["diagnostic_summary"]["omitted_history"] == 16
    assert not {"lower_bound", "upper_bound", "coefficient"}.intersection(row)


def test_legacy_actor_without_pack_compiles_empty_projection():
    actors = {"as_of_date": "2026-07-01", "actors": [{"name": "Alpha", "goals": ["Develop capacity"]}]}
    bundle = compile_bundle(actors=actors)
    assert bundle["qualitative"]["actors"] == {ac.actor_id_for(actors["actors"][0]): []}


def test_canonical_public_private_denied_and_modeler_projections():
    actors, packs, report = canonical_fixture()
    bundle = compile_bundle(actors=actors, actor_context_packs=packs, research_report=report)
    public = rp.render_preparation_context(bundle, max_chars=100000)
    alpha = rp.render_preparation_context(bundle, audience="actor", actor_id="actor_alpha", max_chars=100000)
    beta = rp.render_preparation_context(bundle, audience="actor", actor_id="actor_beta", max_chars=100000)
    modeler = rp.render_preparation_context(bundle, audience="modeler", max_chars=100000)
    assert all(s not in public for s in ("PRIVATE OWNER PLAN", "DENIED SECRET", "ANALYST GUESS", "private budget"))
    assert "PRIVATE OWNER PLAN" in alpha and "private budget" in alpha
    assert "PRIVATE OWNER PLAN" not in beta and "private budget" not in beta
    assert "DENIED SECRET" not in alpha and "ANALYST GUESS" not in alpha
    assert all(s in modeler for s in ("DENIED SECRET", "ANALYST GUESS", "PRIVATE OWNER PLAN"))
    assert len(bundle["quantitative"]["observations"]) == 1


def test_packs_from_changed_input_generation_fail_closed():
    actors, packs, report = canonical_fixture()
    actors["as_of_date"] = "2026-07-02"
    with pytest.raises(ValueError, match="generation"):
        compile_bundle(actors=actors, actor_context_packs=packs, research_report=report)


def test_public_seed_actual_world_preserves_metadata_and_qualifiers():
    actors, packs, report = canonical_fixture()
    bundle = compile_bundle(actors=actors, actor_context_packs=packs, research_report=report,
                            official_data={"series": [series()]})
    cfgs = [{"agent_id": 0, "entity_name": "Alpha Systems", "entity_type": "Actor", "gains_if": "PRIVATE CONFIG"}]
    seed = build_world_model_seed(actors, cfgs, question="Will capacity expand?", preparation_context=bundle)
    encoded = json.dumps(seed)
    assert all(s not in encoded for s in ("PRIVATE OWNER PLAN", "PRIVATE CONFIG", "DENIED SECRET", "ANALYST GUESS", "private budget"))
    plans = seed["actors"][0]["documented_plans"]
    assert any("Only after a permit" in plan for plan in plans)
    assert not any("CANCELLED PUBLIC ACTION" in p or "likely" in p for p in plans)
    assert "CANCELLED PUBLIC ACTION" in json.dumps(seed["actors"][0]["research_claims"])
    world = WorldModel.from_seed(seed, cfgs)
    reloaded = WorldModel.from_dict(world.to_dict())
    for row in seed["state_variables"]:
        assert reloaded.variables[row["id"]].to_dict()["research_evidence"] == row["research_evidence"]
        assert reloaded.variables[row["id"]].unit == row["unit"]
    assert seed["quantitative_guidance"][0]["status"] == "projection"


def test_seed_rejects_stale_dossier_and_bad_preparation():
    actors = {"as_of_date": "2026-07-01", "actors": []}
    bundle = compile_bundle(actors=actors)
    actors["as_of_date"] = "2026-07-02"
    with pytest.raises(ValueError, match="generation"):
        build_world_model_seed(actors, [], preparation_context=bundle)


def test_whole_row_render_budget_never_splits_units_or_conditions():
    bundle = compile_bundle(report_artifacts={"quantitative.json": [fact(unit="Very long native unit " * 8)]})
    rendered = rp.render_preparation_context(bundle, max_chars=300)
    assert len(rendered) <= 300 and "Omitted rows: 1." in rendered
    assert '"value"' not in rendered
    assert rp.render_preparation_context(bundle, max_chars=0) == ""


def test_persist_load_and_expected_input_hashes(tmp_path):
    bundle = compile_bundle(official_data={"series": [series()]})
    manifest = rp.write_preparation_context(tmp_path, bundle)
    assert manifest["sha256"] == hashlib.sha256((tmp_path / rp.BUNDLE_FILE).read_bytes()).hexdigest()
    assert rp.load_preparation_context(tmp_path, bundle["content_sha256"], bundle["source"]) == bundle
    assert rp.write_preparation_context(tmp_path, bundle) == manifest
    with pytest.raises(ValueError, match="generation"):
        rp.load_preparation_context(tmp_path, expected_sources={"actors_sha256": "0" * 64})
    changed = compile_bundle(question="Different question")
    before = (tmp_path / rp.BUNDLE_FILE).read_bytes()
    with pytest.raises(ValueError):
        rp.write_preparation_context(tmp_path, changed)
    assert (tmp_path / rp.BUNDLE_FILE).read_bytes() == before


@pytest.mark.parametrize("which", [rp.BUNDLE_FILE, rp.MANIFEST_FILE])
def test_missing_or_tampered_completion_artifacts_reject(tmp_path, which):
    bundle = compile_bundle()
    rp.write_preparation_context(tmp_path, bundle)
    original = (tmp_path / which).read_bytes()
    (tmp_path / which).write_text("{}")
    with pytest.raises(ValueError):
        rp.load_preparation_context(tmp_path)
    (tmp_path / which).write_bytes(original)
    (tmp_path / which).unlink()
    with pytest.raises(ValueError):
        rp.load_preparation_context(tmp_path)


def test_completion_write_failure_never_validates(tmp_path, monkeypatch):
    original = rp.write_text_atomic
    def fail_manifest(path, text):
        if path.endswith(rp.MANIFEST_FILE):
            raise OSError("injected completion failure")
        original(path, text)
    monkeypatch.setattr(rp, "write_text_atomic", fail_manifest)
    with pytest.raises(OSError):
        rp.write_preparation_context(tmp_path, compile_bundle())
    with pytest.raises(ValueError):
        rp.load_preparation_context(tmp_path)


def test_resealed_invalid_numeric_schema_rejects():
    bundle = compile_bundle(report_artifacts={"quantitative.json": [fact()]})
    bundle["quantitative"]["observations"][0]["value"] = True
    reseal(bundle)
    with pytest.raises(ValueError):
        rp.validate_preparation_context(bundle)


@pytest.mark.parametrize("value,unit", [("10 万元", "亿元"), ("10 €", "¥"), ("2 billion", "million"),
                                       ("10 USD per tonne", "tonne per USD")])
def test_unicode_and_scale_unit_mismatches_never_rescale(value, unit):
    bundle = compile_bundle(report_artifacts={"quantitative.json": [fact(value=value, unit=unit)]})
    assert not bundle["quantitative"]["observations"]


@pytest.mark.parametrize("qualifiers", [{"status": "projection"}, {"value_type": "forecast"}, {"status": "contested"},
                                       {"status": "retracted"}, {"status": "denied"}])
def test_nested_guidance_status_overrides_observed(qualifiers):
    bundle = compile_bundle(report_artifacts={"quantitative.json": [fact(qualifiers=qualifiers)]})
    assert not bundle["quantitative"]["observations"]
    assert bundle["quantitative"]["guidance"]


def test_release_date_after_cutoff_rejects_fact_and_qualitative_bypass():
    bundle = compile_bundle(report_artifacts={"quantitative.json": [fact(release_date="2026-07-02")]})
    assert not bundle["quantitative"]["observations"]
    actors, packs, report = canonical_fixture()
    actors["quantitative_facts"][0].update(as_of_date="2026-07-01", release_date="2026-07-02", metric="Alpha Systems FUTURE NUMBER")
    packs = {a["actor_id"]: ac.build_actor_context_pack(actors, a, report) for a in actors["actors"]}
    bundle = compile_bundle(actors=actors, research_report=report, actor_context_packs=packs)
    assert not bundle["quantitative"]["observations"]
    assert "FUTURE NUMBER" not in json.dumps(bundle["qualitative"])


def test_canonical_sidecar_subset_cannot_drop_forecast_qualifier():
    actors, packs, report = canonical_fixture()
    actors["quantitative_facts"][0].update(status="actual", value_type="forecast")
    packs = {a["actor_id"]: ac.build_actor_context_pack(actors, a, report) for a in actors["actors"]}
    sidecar = deepcopy(actors["quantitative_facts"][0])
    del sidecar["value_type"]
    bundle = compile_bundle(actors=actors, actor_context_packs=packs, research_report=report,
                            report_artifacts={"quantitative.json": [sidecar]})
    assert not bundle["quantitative"]["observations"]
    assert bundle["quantitative"]["guidance"][0]["status"] == "projection"


def test_rejected_official_identity_cannot_be_reintroduced_as_research():
    bundle = compile_bundle(official_data={"series": [series(retrieved_at="2027-01-01")]},
                            report_artifacts={"quantitative.json": [fact(series="fred:GDP")]})
    assert not bundle["quantitative"]["observations"]


def test_resealed_public_private_or_history_boundary_mismatch_rejects():
    actors, packs, report = canonical_fixture()
    bundle = compile_bundle(actors=actors, actor_context_packs=packs, research_report=report)
    private = next(r for r in bundle["qualitative"]["actors"]["actor_alpha"] if r.get("visibility") == "private")
    forged = deepcopy(bundle)
    forged["qualitative"]["public"].append(private)
    reseal(forged)
    with pytest.raises(ValueError, match="nonpublic"):
        rp.validate_preparation_context(forged)
    forged = deepcopy(bundle)
    forged["quantitative"]["observations"][0]["period_end"] = "2030-12-31"
    reseal(forged)
    with pytest.raises(ValueError, match="history"):
        rp.validate_preparation_context(forged)


def test_all_shared_seed_side_fields_obey_public_admission():
    actors = {"as_of_date": "2026-07-01", "actors": [],
              "forecast_inputs": {"scenarios": [{"name": "PRIVATE SCENARIO", "visibility": "private"},
                                                   {"name": "FUTURE SCENARIO", "visibility": "public", "source": "S1", "released_at": "2026-08-01"}],
                                  "risks": [{"event": "PRIVATE RISK", "visibility": "private", "source": "S1",
                                             "probability": .1, "window": "year"}]},
              "wild_cards": [{"event": "PRIVATE WILDCARD", "source": "S1", "probability": .1, "window": "year"}]}
    bundle = compile_bundle(actors=actors)
    seed = build_world_model_seed(actors, [], preparation_context=bundle)
    assert "PRIVATE" not in json.dumps(seed)
    assert "FUTURE" not in json.dumps(seed)


def test_resealed_early_private_history_and_forecast_status_reject():
    bundle = compile_bundle(official_data={"series": [series()]})
    bundle["quantitative"]["observations"][0]["history"][0]["provenance"] = {"visibility": "private", "conditions": ["SECRET"]}
    reseal(bundle)
    with pytest.raises(ValueError, match="history provenance"):
        rp.validate_preparation_context(bundle)
    bundle = compile_bundle(report_artifacts={"quantitative.json": [fact(value_type="forecast")]})
    row = bundle["quantitative"]["guidance"].pop()
    row["status"] = row["history"][0]["status"] = "observed"
    bundle["quantitative"]["observations"].append(row)
    reseal(bundle)
    with pytest.raises(ValueError, match="source status"):
        rp.validate_preparation_context(bundle)


def test_annual_fact_cannot_treat_period_start_as_period_end():
    bundle = compile_bundle(report_artifacts={"quantitative.json": [fact(
        period="2026-01-01", period_start="2026-01-01", period_end="", frequency="A")]})
    assert not bundle["quantitative"]["observations"]


def test_renderer_keeps_latest_long_history_and_question_in_small_budget():
    observations = [{"date": f"{year}-01-01", "value": year, "flag": "observed"} for year in range(1950, 2026)]
    bundle = compile_bundle(question="How does GDP change?", official_data={"series": [series(frequency="A", observations=observations)]})
    rendered = rp.render_preparation_context(bundle, max_chars=1500)
    assert len(rendered) <= 1500
    assert '"value":2025' in rendered and '"unit":"Billions of Dollars"' in rendered
    assert '"history_omitted":60' in rendered and "History points omitted: 60" in rendered
    assert "Question: How does GDP change?" in rendered and "As of: 2026-07-01" in rendered
    assert len(bundle["quantitative"]["observations"][0]["history"]) == 60


def test_renderer_actor_leads_own_plans_and_public_prioritizes_question():
    actors, packs, report = canonical_fixture()
    bundle = compile_bundle(question="What does Alpha Systems plan for Project Aurora?", actors=actors,
                            actor_context_packs=packs, research_report=report, official_data={"series": [series()]})
    rendered = rp.render_preparation_context(bundle, audience="actor", actor_id="actor_alpha", max_chars=1800)
    assert "Project Aurora" in rendered and '"actor_id":"actor_alpha"' in rendered
    # Full conditions accompany any admitted plan; no partial row is emitted.
    if "multi-site" in rendered:
        assert "Only after a permit is granted" in rendered
    bundle = compile_bundle(question="Will Beta revenue rise?", report_artifacts={"quantitative.json": [
        fact(entity="Alpha", metric="Alpha unrelated"), fact(entity="Beta", metric="Beta revenue")]})
    rendered = rp.render_preparation_context(bundle, max_chars=1500)
    assert "Beta revenue" in rendered
    if "Alpha unrelated" in rendered:
        assert rendered.index("Beta revenue") < rendered.index("Alpha unrelated")


def test_denied_phrase_in_bad_numeric_gap_never_reaches_public_actor_or_seed():
    actors = {"as_of_date": "2026-07-01", "actors": [{"actor_id": "a", "name": "Alpha"}],
              "quantitative_facts": [fact(metric="The analyst projects a secret loss.", value="bad", visibility="public")]}
    bundle = compile_bundle(actors=actors)
    assert "secret loss" in json.dumps(bundle["gaps"])  # retained modeler audit detail
    for audience in ("public", "actor"):
        assert "secret loss" not in rp.render_preparation_context(bundle, audience=audience, actor_id="a")
    assert "secret loss" not in json.dumps(build_world_model_seed(actors, [], preparation_context=bundle))


@pytest.mark.parametrize("verdict", ["unassessed", "contradicted", "supported_source_assertion"])
def test_real_typed_numeric_support_producer_controls_compiler_and_seed(verdict):
    from app.services.official_data import bridge_module
    producer = bridge_module("research_assessment")
    row = fact(entity="Alpha", value=10, unit="GW")
    assertion = {key: row[key] for key in producer.FIELDS}
    if verdict == "contradicted":
        assertion["entity"] = "Beta"
    quote = json.dumps(assertion)
    row["supporting_quote"] = quote
    page = quote if verdict != "unassessed" else "Alpha has 10 GW, but the complete semantics are unassessed."
    row["claim_support"] = producer.typed_numeric_support(
        row, {"source_id": "S2", "url": "https://fixture.invalid/alpha", "reachable": True}, page)
    assert row["claim_support"]["status"] == verdict
    actors = {"as_of_date": "2026-07-01", "actors": [], "quantitative_facts": [row]}
    bundle = compile_bundle(actors=actors)
    seed = build_world_model_seed(actors, [], preparation_context=bundle)
    if verdict == "supported_source_assertion":
        assert seed["state_variables"][0]["value"] == 10
    else:
        assert seed["state_variables"] == []
        assert bundle["quantitative"]["guidance"][0]["status"] == "unknown"
        assert seed["quantitative_guidance"][0]["provenance"]["claim_support"] == row["claim_support"]


def test_unassessed_official_restatement_cannot_change_valid_carrier_authority():
    unsupported = {"schema_version": "numeric-claim-support/v1", "semantic_support": False, "status": "unassessed"}
    bundle = compile_bundle(official_data={"series": [series()]}, report_artifacts={"quantitative.json": [
        fact(series="fred:GDP", source_origin="official_data", claim_support=unsupported)]})
    assert bundle["quantitative"]["observations"][0]["source_kind"] == "official_observation"
    assert bundle["quantitative"]["observations"][0]["value"] == 110


@pytest.fixture(scope="module", autouse=True)
def source_bytes_are_frozen_in_guard_receipt():
    """The runner tracks imported app sources only selectively; pin our producer bytes."""
    import sys
    from pathlib import Path
    guard = sys.modules.get("main_offline_guard")
    if guard is not None:
        for filename in ("research_preparation.py", "world_model_seed.py", "actor_context.py", "world_model.py"):
            path = Path(rp.__file__).with_name(filename)
            guard.source_hashes.setdefault(str(path), hashlib.sha256(path.read_bytes()).hexdigest())
