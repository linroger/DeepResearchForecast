"""Numeric occurrence is not semantic support for a quantitative handoff."""
import json

import pytest

from tests import test_research_engine_v3 as base
bridge = base.bridge
_hermetic_env = base._hermetic_env

lr = base.lr
assessment = lr.assessment
TUPLE = {"entity": "Alpha", "metric": "operational capacity", "value": 10,
         "unit": "GW", "period_end": "2026-09-30", "value_type": "actual"}
QUOTE = json.dumps(TUPLE)
SOURCE = {"source_id": "src_alpha", "url": "https://agency.test/alpha", "reachable": True}


@pytest.mark.parametrize("field,value", [("entity", "Beta"), ("metric", "planned capacity"),
                                         ("unit", "MW"), ("period_end", "2025-09-30"),
                                         ("value_type", "target"), ("value", 11)])
def test_right_number_wrong_semantics_is_not_supported(field, value):
    row = {**TUPLE, "supporting_quote": QUOTE, field: value}
    result = assessment.typed_numeric_support(row, SOURCE, QUOTE)
    assert result["semantic_support"] is False
    assert result["status"] == "contradicted"
    assert field in result["mismatched_fields"]


def test_typed_source_tuple_preserves_modality_and_reference():
    row = {**TUPLE, "supporting_quote": QUOTE}
    result = assessment.typed_numeric_support(row, SOURCE, QUOTE)
    assert result["status"] == "supported_source_assertion"
    assert result["assertion"] == TUPLE and result["independent"] is None
    assert result["content_sha256"] and result["quote_sha256"]
    target = {**TUPLE, "value_type": "target"}
    quote = json.dumps(target)
    result = assessment.typed_numeric_support({**target, "supporting_quote": quote}, SOURCE, quote)
    assert result["assertion"]["value_type"] == "target"


def test_real_note_consumer_does_not_verify_scattered_matching_numbers():
    page = "Beta plans 10 GW in 2026. Alpha had 10 MW in 2025."
    notes = "## Findings\n- Alpha operational capacity was 10 GW in 2026 [S1] (VERIFIED)"
    _, parts = lr.postprocess_notes("K1", notes, lambda sid: {"fetched": True},
                                   lambda sid: lr.page_number_set(page), lambda sid: page)
    fact = parts["facts"][0]
    assert fact["verified_numbers"] is True
    assert fact["tag"] == "REPORTED" and fact["claim_support"]["semantic_support"] is False


@pytest.mark.parametrize("quantity", ["5 GW", "5GW", "0%"])
def test_single_digit_claim_cannot_bypass_semantic_support(quantity):
    page = f"Beta operational capacity is {quantity}."
    _, parts = lr.postprocess_notes("K1", f"## Findings\n- Alpha operational capacity is {quantity} [S1] (VERIFIED)",
                                   lambda sid: {"fetched": True}, lambda sid: lr.page_number_set(page), lambda sid: page)
    fact = parts["facts"][0]
    assert fact["tag"] == "REPORTED" and fact["claim_support"]["semantic_support"] is False


@pytest.mark.parametrize("quote", ["甲公司的实际运营容量达到5吉瓦，且这一能力已经投入运行。",
                                  "甲公司的实际运营容量达到10吉瓦，且这一能力已经投入运行。",
                                  "公司公告称项目计划新增装机容量5GW，目前仍处于审批阶段。",
                                  "Capacity increased by 2000 MW."])
def test_cjk_and_year_shaped_quantities_remain_unassessed_through_real_note_projection(quote):
    ledger = lambda sid: {"fetched": True, "url": "https://agency.test/claim"}
    _, parts = lr.postprocess_notes("K1", f"## Findings\n- {quote} [S1] (VERIFIED)",
                                   ledger, lambda sid: lr.page_number_set(quote), lambda sid: quote)
    fact = parts["facts"][0]
    assert fact["tag"] == "REPORTED" and fact["claim_support"]["semantic_support"] is False
    rows = assessment.evidence_rows({"K1": parts}, ledger, lambda sid: quote)
    assert rows and rows[0]["numeric_semantics"] == "unassessed"


def test_official_observation_adapter_preserves_status_native_units_and_cutoff(tmp_path):
    api = base.rg._data_api()
    series = api.Series(series="fred:UNRATE", title="Unemployment", units="Percent", frequency="M",
                        retrieved_at="2026-10-22T10:00:00Z", source_url="https://fred.test/UNRATE",
                        observations=[api.Observation("2026-07-01", 4.0),
                                      api.Observation("2026-08-01", 4.2, "preliminary"),
                                      api.Observation("2026-09-01", 4.3, "estimate"),
                                      api.Observation("2026-10-01", 4.5, "projection")])
    api.write_dataset_files([series], tmp_path, citations={series.series: 1})
    rows = api.load_datasets(tmp_path, strict=True)
    assert not assessment.official_observations(rows, {series.series: 1}, api, "2026-10-22T09:59:00Z")
    evidence = assessment.official_observations(rows, {series.series: 1}, api, "2026-10-22T10:00:00Z")
    point = evidence[0]["observation"]
    assert point["period"] == "2026-07-01" and point["value"] == 4.0
    assert point["unit"] == "Percent" and point["status"] == "observed"
    assert evidence[0]["dataset_sha256"] == rows[0]["sha256"]


def test_capture_before_period_completion_cannot_become_complete_later(tmp_path):
    api = base.rg._data_api()
    series = api.Series(series="fred:UNRATE", title="Unemployment", units="Percent", frequency="M",
                        retrieved_at="2026-09-15T12:00:00Z", source_url="https://fred.test/UNRATE",
                        observations=[api.Observation("2026-09-01", 4.2)])
    api.write_dataset_files([series], tmp_path, citations={series.series: 1})
    assert not assessment.official_observations(api.load_datasets(tmp_path, strict=True),
                                               {series.series: 1}, api, "2026-10-23")
    series.retrieved_at = "2026-10-01T12:00:00Z"
    api.write_dataset_files([series], tmp_path, citations={series.series: 1})
    assert assessment.official_observations(api.load_datasets(tmp_path, strict=True),
                                          {series.series: 1}, api, "2026-10-23")[0]["observation"]["value"] == 4.2


def test_assessment_rejects_valid_dataset_replacement_after_gather_page(tmp_path, monkeypatch):
    from tests.test_v3_official_data import FixtureSources, real_engine
    api = base.rg._data_api()
    engine = real_engine(tmp_path, monkeypatch, api, FixtureSources(api), needs=["fred:UNRATE"])
    engine.phase_data()
    rows = api.load_datasets(engine.work, strict=True)
    assert rows
    replacement = api.Series.from_dict(rows[0])
    replacement.observations[-1].value = 99.0
    api.write_dataset_files([replacement], engine.work, citations={replacement.series: rows[0]["source_id"]})
    assert api.load_datasets(engine.work, strict=True)[0]["observations"][-1]["value"] == 99.0
    with pytest.raises(lr._EngineFailure, match="official evidence"):
        engine.phase_assess()
    assert not (engine.out_dir / "research_assessment.json").exists()


class TypedWorld(base.World):
    def facts(self, call):
        return base.ai(json.dumps({"key_events": [], "contested_claims": [],
                                  "quantitative_facts": [{**TUPLE, "source_ref": "S1", "supporting_quote": QUOTE}]}))


def test_typed_support_survives_real_quantitative_and_actor_handoff(tmp_path, bridge):
    result = base.run_engine(tmp_path, bridge, TypedWorld(), fetch=lambda url: base.page_text(url) + "\n" + QUOTE)
    rc, meta, _, _, out = result
    assert rc == 0, meta.get("error")
    quant = json.loads((out / "quantitative.json").read_text())
    actors = json.loads((out / "actors.json").read_text())
    assert quant[0]["source_ref"] == "S1"
    assert quant[0]["claim_support"]["semantic_support"] is True
    assert actors["quantitative_facts"][0]["claim_support"] == quant[0]["claim_support"]
