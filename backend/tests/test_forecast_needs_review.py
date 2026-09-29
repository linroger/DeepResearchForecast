"""REPORT-1: unreadable probabilities become an explicit needs_review state.

Offline (FakeLLMClient / stub agents). Pins the three reproduced launderings
(percent strings -> uniform split, mixed scale -> manufactured partition,
binary 30/True -> 0.98), the flag-off legacy reproduction, byte identity for
well-formed numeric input, the cache-busting spine retry, critique salvage and
discard, and every consumer that must honour a null probability.
"""

import contextvars
import json
import logging
import os

import pytest

from app.config import Config
from app.services import forecast_extractor as fe
from app.services import forecast_ledger
from app.services.ensemble import aggregate_forecasts
from app.services.pipeline_orchestrator import PipelineOrchestrator, PipelineState
from app.services.report_agent import ReportAgent, ReportManager
from app.services.report_lint import check_scenario_probabilities
from app.utils.telemetry import LLMCache
from tests.conftest import FakeLLMClient

_NAMES = ("Rapid adoption path", "Gradual adoption path", "Other / Status Quo",
          "Reversal path")


def _rows(probs, names=_NAMES):
    return [
        {"name": name, "probability": p, "summary": f"{name} summary",
         "key_drivers": ["driver"],
         "resolution_criteria": f"{name} resolves if the index is above {10 + i}% by 2030"}
        for i, (name, p) in enumerate(zip(names, probs, strict=False))
    ]


def _strict(monkeypatch, on=True):
    monkeypatch.setattr(Config, "FORECAST_PROB_STRICT_PARSE", on, raising=False)


def _probs(forecast):
    return [s["probability"] for s in forecast["scenarios"]]


# ------------------------------------------------------------ scenarios / assemble
def test_percent_strings_not_laundered(monkeypatch):
    _strict(monkeypatch)
    monkeypatch.setattr(Config, "FORECAST_PROB_FLOOR", 0.03, raising=False)
    for probs in (["45%", "35%", "20%"], ["４５％", "35 percent", "20%"]):
        out = fe._assemble_forecast({"headline": "h", "scenarios": _rows(probs)})
        assert _probs(out) == [0.45, 0.35, 0.2]
        assert "probability_status" not in out
        assert "probability_review" not in out
        assert all("probability_status" not in s for s in out["scenarios"])
        assert fe.audit_scenario_contract(out)["valid"] is True


def test_unreadable_row_fails_closed(monkeypatch):
    _strict(monkeypatch)
    monkeypatch.setattr(Config, "FORECAST_PROB_FLOOR", 0.03, raising=False)
    out = fe._assemble_forecast({"headline": "h", "scenarios": _rows([0.45, "30-40%", 0.2])})
    assert out["probability_status"] == "needs_review"
    assert out["probability_review"] == {
        "stage": "assemble",
        "reason": "range",
        "rows": [{"name": _NAMES[1], "raw": "'30-40%'", "reason": "range"}],
    }
    bad = out["scenarios"][1]
    assert bad["probability"] is None
    assert bad["probability_status"] == "needs_review"
    assert bad["probability_raw"] == "'30-40%'"
    assert bad["probability_parse_reason"] == "range"
    # readable rows keep their canonical values: no renormalisation, no floor
    assert out["scenarios"][0]["probability"] == 0.45
    assert out["scenarios"][2]["probability"] == 0.2
    assert "probability_status" not in out["scenarios"][0]
    audit = fe.audit_scenario_contract(json.loads(json.dumps(out)))
    assert audit["valid"] is False
    assert any(e["code"] == "probability_not_numeric" for e in audit["examples"])

    mixed = fe._assemble_forecast({"headline": "h", "scenarios": _rows([0.45, 35, 0.2])})
    assert mixed["probability_status"] == "needs_review"
    assert mixed["probability_review"]["reason"] == "ambiguous_scale"
    assert _probs(mixed) == [None, None, None]
    assert {s["probability_parse_reason"] for s in mixed["scenarios"]} == {"ambiguous_scale"}
    assert len(mixed["probability_review"]["rows"]) == 3
    assert fe.audit_scenario_contract(mixed)["valid"] is False


def test_unreadable_row_flag_off_reproduces_legacy(monkeypatch):
    _strict(monkeypatch, False)
    monkeypatch.setattr(Config, "FORECAST_PROB_FLOOR", 0.03, raising=False)
    out = fe._assemble_forecast({"headline": "h", "scenarios": _rows([0.45, 35, 0.2])})
    # legacy: the mixed scale is silently renormalised into a plausible partition
    assert _probs(out) == [0.0288, 0.9424, 0.0288]
    assert "probability_status" not in out
    assert fe.audit_scenario_contract(out)["valid"] is True


@pytest.mark.parametrize("floor", [0.0, 0.03])
def test_byte_identity_numeric(monkeypatch, floor):
    monkeypatch.setattr(Config, "FORECAST_PROB_FLOOR", floor, raising=False)
    cases = ([0.5, 0.3, 0.2], [3, 1], [0.97, 0.02, 0.01], [0.25] * 4, [1, 0], ["0.6", "0.4"])
    for probs in cases:
        raw = {"headline": "h", "horizon": "2030", "confidence": "high",
               "scenarios": _rows(probs), "key_uncertainties": ["u"]}
        _strict(monkeypatch, True)
        strict_out = json.dumps(fe._assemble_forecast(json.loads(json.dumps(raw))),
                                ensure_ascii=False)
        _strict(monkeypatch, False)
        legacy_out = json.dumps(fe._assemble_forecast(json.loads(json.dumps(raw))),
                                ensure_ascii=False)
        assert strict_out == legacy_out, probs
    _strict(monkeypatch, True)
    assert _probs(fe._assemble_forecast({"scenarios": _rows([3, 1])})) == [0.75, 0.25]


def test_flag_off_reproduces_legacy_uniform_split(monkeypatch):
    _strict(monkeypatch, False)
    monkeypatch.setattr(Config, "FORECAST_PROB_FLOOR", 0.03, raising=False)
    out = fe._assemble_forecast({"scenarios": _rows(["45%", "35%", "20%"])})
    assert _probs(out) == [0.3333, 0.3333, 0.3333]
    assert "probability_status" not in out


# ------------------------------------------------------------------------ binaries
def _binary(stmt, p, **extra):
    row = {"statement": stmt, "probability": p,
           "resolution_criteria": "BLS CPI-U YoY above 3.0% for December 2027",
           "theme": "inflation", "horizon_year": 2027,
           "resolution_source": "BLS"}
    row.update(extra)
    return row


_BIN_A = "US CPI inflation exceeds 3% in December 2027"
_BIN_B = "US unemployment rate exceeds 5% in December 2027"
_BIN_C = "Fed funds upper bound is below 3% in December 2027"
_BIN_D = "US real GDP growth exceeds 2% in calendar 2027"


def test_binaries(monkeypatch):
    _strict(monkeypatch)
    sink = []
    rows = fe._normalize_binaries([
        _binary(_BIN_A, 30),
        _binary(_BIN_B, "30%", horizon_year="2030年", resolution_source="N/A"),
        _binary(_BIN_C, True),
        _binary(_BIN_D, 0.64, horizon_year="FY2030"),
        _binary("Brent crude averages above $90 in 2031", 0.2, horizon_year="2030-2031"),
    ], review_sink=sink)
    by_stmt = {row["statement"]: row for row in rows}
    assert _BIN_A not in by_stmt and _BIN_C not in by_stmt
    assert all(row["probability"] not in (0.98, 0.02) for row in rows)
    assert by_stmt[_BIN_B]["probability"] == 0.3
    assert by_stmt[_BIN_B]["horizon_year"] == 2030
    assert by_stmt[_BIN_B]["resolution_source"] == ""
    assert by_stmt[_BIN_D]["horizon_year"] == 2030
    assert by_stmt[_BIN_D]["resolution_source"] == "BLS"
    assert by_stmt["Brent crude averages above $90 in 2031"]["horizon_year"] is None
    assert sink == [
        {"statement": _BIN_A, "raw": "30", "reason": "plain_gt1"},
        {"statement": _BIN_C, "raw": "True", "reason": "bool"},
    ]

    _strict(monkeypatch, False)
    legacy_sink = []
    legacy = fe._normalize_binaries([
        _binary(_BIN_A, 30), _binary(_BIN_B, "30%", horizon_year="2030年"),
        _binary(_BIN_C, True),
    ], review_sink=legacy_sink)
    # the legacy laundering the flag exists to stop: 30 and True clamp to 0.98, '30%' is lost
    assert [(r["statement"], r["probability"]) for r in legacy] == [
        (_BIN_A, 0.98), (_BIN_C, 0.98)]
    assert legacy_sink == []


def _binary_payload(extra):
    good = [_binary(_BIN_D, 0.8), _binary(_BIN_B, 0.15), _binary(_BIN_C, "25%")]
    return {"binary_forecasts": good + extra}


def _extract(llm, min_count=3):
    return fe.extract_binary_forecasts("dossier text", llm, min_count=min_count)


def test_extract_binary_forecasts_counts_withheld_rows(monkeypatch):
    monkeypatch.setattr(Config, "FORECAST_BINARY_CONTRARIAN", False, raising=False)
    monkeypatch.setattr(Config, "FORECAST_ENSEMBLE_MODELS", "", raising=False)
    extra = [_binary(_BIN_A, 30),
             _binary("Housing starts exceed 1.6m annualised in 2027", "30-40%"),
             _binary("S&P 500 closes 2027 above 7000", True)]

    _strict(monkeypatch)
    res = _extract(FakeLLMClient(json_responses=[_binary_payload(extra)]))
    probs = {b["statement"]: b["probability"] for b in res["binary_forecasts"]}
    assert probs == {_BIN_D: 0.8, _BIN_B: 0.15, _BIN_C: 0.25}
    bq = res["binary_quality"]
    assert bq["needs_review_count"] == 3
    assert bq["needs_review_reasons"] == {"plain_gt1": 1, "range": 1, "bool": 1}
    assert "3 binary probabilities unreadable — withheld, not clamped" in bq["issues"]

    _strict(monkeypatch, False)
    legacy = _extract(FakeLLMClient(json_responses=[_binary_payload(extra)]))
    assert "needs_review_count" not in legacy["binary_quality"]
    assert "needs_review_reasons" not in legacy["binary_quality"]
    assert sorted(b["probability"] for b in legacy["binary_forecasts"]) == [0.15, 0.8, 0.98, 0.98]


def test_extract_binary_forecasts_recovered_rows_are_not_withheld(monkeypatch):
    _strict(monkeypatch)
    monkeypatch.setattr(Config, "FORECAST_BINARY_CONTRARIAN", False, raising=False)
    monkeypatch.setattr(Config, "FORECAST_ENSEMBLE_MODELS", "", raising=False)
    first = {"binary_forecasts": [_binary(_BIN_D, 0.8), _binary(_BIN_B, 0.15),
                                  _binary(_BIN_A, 30)]}
    top_up = {"binary_forecasts": [_binary(_BIN_A, 0.3), _binary(_BIN_C, 0.1)]}
    res = _extract(FakeLLMClient(json_responses=[first, top_up]))
    assert {b["statement"] for b in res["binary_forecasts"]} == {_BIN_D, _BIN_B, _BIN_A, _BIN_C}
    assert "needs_review_count" not in res["binary_quality"]


# ------------------------------------------------------------ market restatement
def _anchored_binary():
    return {
        "id": "F1", "statement": _BIN_A, "probability": 0.6,
        "adjustment_rationale": "Base-rate view from the survey data.",
        "market_anchor": {
            "market_id": "m1", "question": "Will CPI exceed 3%?", "implied_yes_prob": 0.3,
            "divergence": 0.3, "match_confidence": 0.9, "resolution_equivalence": "exact",
        },
    }


def _restate(probability, rationale="The market implies 30%; our survey data disagree."):
    binaries = [_anchored_binary()]
    revision = {"id": "F1", "adjustment_rationale": rationale}
    if probability is not _MISSING:
        revision["probability"] = probability
    llm = FakeLLMClient(json_responses=[{"revisions": [revision]}])
    return fe.enforce_market_divergence(binaries, llm), binaries[0]


_MISSING = object()


def test_divergence_restatement(monkeypatch):
    _strict(monkeypatch)
    monkeypatch.setattr(Config, "FORECAST_MARKET_DIVERGENCE_REVISION", True, raising=False)
    monkeypatch.setattr(Config, "FORECAST_MARKET_DIVERGENCE_MIN_CONFIDENCE", 0.6, raising=False)
    original = _anchored_binary()
    for unreadable in ("30-40%", 30):
        n, b = _restate(unreadable)
        assert n == 0
        assert b["probability"] == 0.6  # never clamped to 0.98
        assert b["adjustment_rationale"] == original["adjustment_rationale"]
        assert "market_influence" not in b
        assert b["market_anchor"]["divergence"] == 0.3

    n, b = _restate("35%")
    assert n == 1
    assert b["probability"] == 0.35
    assert b["adjustment_rationale"].startswith("The market implies 30%")
    assert b["market_anchor"]["divergence"] == 0.05
    assert b["market_influence"]["prior_probability"] == 0.6
    assert b["market_influence"]["revised_probability"] == 0.35

    # absent probability keeps today's rationale-only "keep divergence" path
    n, b = _restate(_MISSING)
    assert n == 1
    assert b["probability"] == 0.6
    assert b["adjustment_rationale"].startswith("The market implies 30%")
    assert "market_influence" not in b

    _strict(monkeypatch, False)
    n, b = _restate(30)
    assert n == 1 and b["probability"] == 0.98  # legacy laundering reproduced


# ------------------------------------------------------------------- spine retry
def _spine(probs):
    return {"headline": "h", "horizon": "2030", "confidence": "medium", "scenarios": _rows(probs)}


def _user_message(llm, index):
    return llm.calls[index]["messages"][0]["content"]


def test_spine_retry(monkeypatch):
    _strict(monkeypatch)
    monkeypatch.setattr(Config, "REPORT_SPINE_SELFCONSISTENCY_K", 1, raising=False)
    monkeypatch.setattr(Config, "FORECAST_PROB_FLOOR", 0.03, raising=False)
    llm = FakeLLMClient(json_responses=[_spine([0.5, "30-40%", 0.2]), _spine([0.5, 0.3, 0.2])])
    out = fe.derive_forecast_spine(llm, central_question="Will adoption accelerate?")
    assert _probs(out) == [0.5, 0.3, 0.2]
    assert "probability_status" not in out
    assert out["derived_from"] == "spine"
    first, second = _user_message(llm, 0), _user_message(llm, 1)
    assert fe._SPINE_RETRY_NOTE not in first
    assert second == first + fe._SPINE_RETRY_NOTE
    # the changed message changes the LLMCache key, so the retry is never served the
    # cached unreadable reply of the first draw
    keys = {LLMCache.key("provider", "model", [{"role": "user", "content": text}],
                         0.2, 6144, None) for text in (first, second)}
    assert len(keys) == 2

    llm2 = FakeLLMClient(json_responses=[_spine([0.5, "30-40%", 0.2]),
                                         _spine(["45%", 0.35, 0.2])])
    out2 = fe.derive_forecast_spine(llm2, central_question="Will adoption accelerate?")
    assert len(llm2.calls) == 2
    assert out2["scenarios"] == []
    assert out2["derived_from"] == "spine"
    assert out2["probability_review"]["reason"] == "ambiguous_scale"

    # an unreadable first draw followed by an empty retry keeps the first draw's review,
    # so ReportAgent can still record why the spine was dropped
    llm3 = FakeLLMClient(json_responses=[_spine([0.5, "30-40%", 0.2]), {}])
    out3 = fe.derive_forecast_spine(llm3, central_question="Will adoption accelerate?")
    assert len(llm3.calls) == 2
    assert out3["scenarios"] == []
    assert out3["probability_status"] == "needs_review"
    assert out3["probability_review"]["reason"] == "range"
    assert out3["probability_review"]["rows"] == [
        {"name": _NAMES[1], "raw": "'30-40%'", "reason": "range"}]


def test_spine_retry_on_empty_draw(monkeypatch):
    monkeypatch.setattr(Config, "REPORT_SPINE_SELFCONSISTENCY_K", 1, raising=False)
    _strict(monkeypatch)
    llm = FakeLLMClient(json_responses=[{}, _spine([0.5, 0.3, 0.2])])
    out = fe.derive_forecast_spine(llm, central_question="Q?")
    assert _probs(out) == [0.5, 0.3, 0.2]
    assert _user_message(llm, 1) == _user_message(llm, 0) + fe._SPINE_RETRY_NOTE

    _strict(monkeypatch, False)
    legacy = FakeLLMClient(json_responses=[{}, _spine([0.5, 0.3, 0.2])])
    fe.derive_forecast_spine(legacy, central_question="Q?")
    assert _user_message(legacy, 1) == _user_message(legacy, 0)  # legacy identical retry
    # legacy: an unreadable first draw is laundered, so no retry happens at all
    laundered = FakeLLMClient(json_responses=[_spine(["45%", "35%", "20%"])])
    assert _probs(fe.derive_forecast_spine(laundered, central_question="Q?")) == [0.3333] * 3
    assert len(laundered.calls) == 1


def test_spine_follow_up_draws_skip_needs_review(monkeypatch):
    _strict(monkeypatch)
    monkeypatch.setattr(Config, "REPORT_SPINE_SELFCONSISTENCY_K", 3, raising=False)
    llm = FakeLLMClient(json_responses=[
        _spine([0.5, 0.3, 0.2]), _spine([0.5, "N/A", 0.2]), _spine([0.4, 0.4, 0.2])])
    out = fe.derive_forecast_spine(llm, central_question="Q?")
    assert out["self_consistency_k"] == 2
    assert all(s["self_consistency_n"] == 2 for s in out["scenarios"])


# ---------------------------------------------------------------- self-critique
def _critique_input():
    return {"headline": "Adoption outlook", "horizon": "2030", "confidence": "medium",
            "scenarios": _rows([0.5, 0.3, 0.2])}


def test_critique_salvage_and_discard(monkeypatch):
    _strict(monkeypatch)
    forecast = _critique_input()
    critic = {"scenarios": _rows(["45%", "30%", "25%"])}
    out = fe.self_critique_forecast(forecast, FakeLLMClient(json_responses=[critic]))
    assert out["critiqued"] is True
    assert _probs(out) == [0.45, 0.3, 0.25]
    assert fe.audit_scenario_contract(out)["valid"] is True

    forecast = _critique_input()
    ranges = {"scenarios": _rows(["40-50%", "30%", "20%"])}
    out = fe.self_critique_forecast(forecast, FakeLLMClient(json_responses=[ranges]))
    assert out is forecast
    assert "critiqued" not in out
    assert out["quality"]["critique_discarded"] == {
        "reason": "unreadable_probabilities", "detail": "range"}
    assert _probs(out) == [0.5, 0.3, 0.2]


def test_critique_and_premortem_leave_needs_review_forecast_alone(monkeypatch):
    _strict(monkeypatch)
    monkeypatch.setattr(Config, "REPORT_PREMORTEM", True, raising=False)
    forecast = fe._assemble_forecast({"headline": "h", "scenarios": _rows([0.45, "N/A", 0.2])})
    llm = FakeLLMClient(json_responses=[
        {"scenarios": _rows([0.5, 0.3, 0.2])},
        {"overconfident_scenario": _NAMES[0], "underweighted_scenario": _NAMES[1]}])
    assert fe.self_critique_forecast(forecast, llm) is forecast
    assert fe.premortem_forecast(forecast, llm) is forecast
    assert llm.calls == []
    assert forecast["scenarios"][1]["probability"] is None


def _partition_binary(probability, yes_scenarios):
    return {"id": "F1", "statement": "Rapid adoption wins by 2030", "probability": probability,
            "scenario_membership": {"derivable": True, "yes_scenarios": yes_scenarios}}


def test_reconcile_skips_unreadable_partition(monkeypatch):
    _strict(monkeypatch)
    forecast = fe._assemble_forecast({"headline": "h",
                                      "scenarios": _rows([0.45, "30-40%", 0.2])})
    forecast["binary_forecasts"] = [_partition_binary(0.7, [_NAMES[0]])]
    diagnostics = fe.reconcile_forecast_contract(forecast)
    binary = forecast["binary_forecasts"][0]
    # the readable row of an unreadable partition is not a canonical probability
    assert binary["probability"] == 0.7
    assert "pre_reconciliation_probability" not in binary
    assert binary.get("source") != "scenario-partition"
    assert diagnostics["corrected_count"] == 0
    after = diagnostics["after"]
    assert after["mismatch_count"] == 0  # unverifiable, not a contradiction
    assert after["unverifiable_count"] == 1
    assert after["unverifiable"][0]["reason"] == "scenario partition probabilities need review"
    assert after["passed"] is False and diagnostics["passed"] is False

    # a readable partition still reconciles exactly as before, with no new keys
    readable = fe._assemble_forecast({"headline": "h", "scenarios": _rows([0.45, 0.35, 0.2])})
    readable["binary_forecasts"] = [_partition_binary(0.7, [_NAMES[0]])]
    fixed = fe.reconcile_forecast_contract(readable)
    assert readable["binary_forecasts"][0]["probability"] == 0.45
    assert readable["binary_forecasts"][0]["source"] == "scenario-partition"
    assert "unverifiable" not in fixed["after"] and "unverifiable_count" not in fixed["after"]
    assert fixed["after"]["passed"] is True


# -------------------------------------------------------------------- consumers
def _needs_review_forecast():
    forecast = fe._assemble_forecast({"headline": "h", "horizon": "2030",
                                      "scenarios": _rows([0.45, "30-40%", 0.2])})
    forecast["citation_audit"] = {"coverage": 1.0, "quantitative_claims": 0}
    return forecast


def test_consumers(monkeypatch):
    _strict(monkeypatch)
    gated = ReportAgent._apply_publish_gate(_needs_review_forecast())
    hard = gated["quality"]["hard_issues"]
    assert any("NEEDS_REVIEW" in issue for issue in hard)
    assert "1 个情景概率无法解析（NEEDS_REVIEW，未以 0/均匀分布代替）" in hard
    assert not any("偏离 1" in issue for issue in hard)
    assert gated["quality"]["hard_passed"] is False
    assert gated["quality"]["probability_sum"] == 0.65

    zh_block = fe.render_resolution_block(_needs_review_forecast(), language="Chinese")
    assert f"**[待复核] {_NAMES[1]}**" in zh_block
    assert "[0%]" not in zh_block
    assert "**[45%]" in zh_block
    en_block = fe.render_resolution_block(_needs_review_forecast(), language="English")
    assert f"**[needs review] {_NAMES[1]}**" in en_block

    run = fe._assemble_forecast({"headline": "h", "scenarios": _rows([0.5, 0.3, 0.2])})
    agg = aggregate_forecasts([run, dict(run), _needs_review_forecast()])
    assert agg["n_runs"] == 2
    assert agg["n_runs_excluded"] == 1
    assert "n_runs_excluded" not in aggregate_forecasts([run, dict(run)])
    assert aggregate_forecasts([_needs_review_forecast()]) == {
        "n_runs": 0, "scenarios": [], "agreement": None, "schema_version": 1,
        "n_runs_excluded": 1}

    agent = ReportAgent.__new__(ReportAgent)
    forecast = {"scenarios": [{"name": _NAMES[0], "probability": None},
                              {"name": _NAMES[1], "probability": 0.5}]}
    md = f"{_NAMES[0]} sits at 35% today. {_NAMES[1]} is 20% in the prose."
    nc = agent._audit_numeric_consistency(md, forecast)
    assert nc["mismatch_count"] == 1  # only the numeric scenario is cross-checked
    assert _NAMES[0] not in " ".join(nc["scenario_prob_mismatches"])
    lint = check_scenario_probabilities(md, forecast)
    assert len(lint) == 1 and _NAMES[1] in lint[0]


def test_ensemble_single_readable_run_reports_no_agreement():
    run = fe._assemble_forecast({"headline": "h", "scenarios": _rows([0.5, 0.3, 0.2])})
    agg = aggregate_forecasts([run, _needs_review_forecast()])
    assert agg["n_runs"] == 1 and agg["n_runs_excluded"] == 1
    # one readable run cannot agree with anything: never a fabricated 1.0 / "high"
    assert agg["agreement"] is None
    assert agg["agreement_spread"] is None
    assert PipelineOrchestrator._agreement_to_confidence(agg["agreement"]) != "high"
    # with two readable runs the agreement is computed exactly as before
    pooled = aggregate_forecasts([run, dict(run), _needs_review_forecast()])
    plain = aggregate_forecasts([run, dict(run)])
    assert pooled["agreement"] == plain["agreement"] is not None
    assert pooled["agreement_spread"] == plain["agreement_spread"]


def _seed_ensemble_env(monkeypatch, tmp_path, seed_forecast):
    from app.services import pipeline_orchestrator as po

    monkeypatch.setattr(Config, "N_FORECAST_SEEDS", 2, raising=False)
    monkeypatch.setattr(Config, "ENSEMBLE_SEED_CONCURRENCY", 1, raising=False)
    monkeypatch.setattr(Config, "REPORT_STRUCTURED_FORECAST", True, raising=False)
    monkeypatch.setattr(po.PipelineManager, "save", classmethod(lambda cls, state: None))
    monkeypatch.setattr(po.PipelineManager, "touch_heartbeat",
                        classmethod(lambda cls, pipeline_id, pid=None: True))
    monkeypatch.setattr(ReportManager, "_get_report_folder",
                        classmethod(lambda cls, report_id: str(tmp_path / "reports" / report_id)))
    primary = fe._assemble_forecast({"headline": "h", "scenarios": _rows([0.5, 0.3, 0.2])})
    monkeypatch.setattr(PipelineOrchestrator, "_read_report_forecast",
                        staticmethod(lambda report_id: primary if report_id == "report_main"
                                     else None))
    orchestrator = PipelineOrchestrator.__new__(PipelineOrchestrator)
    monkeypatch.setattr(orchestrator, "_run_one_seed",
                        lambda *args, **kwargs: ("sim_seed2", "report_seed2", seed_forecast))
    monkeypatch.setattr(orchestrator, "_flush_run_telemetry", lambda *args, **kwargs: None)
    handoff = tmp_path / "handoff"
    handoff.mkdir()
    (tmp_path / "reports" / "report_main").mkdir(parents=True)
    state = PipelineState(pipeline_id="pipe_r1_ensemble", prompt="q", mode="full",
                          report_id="report_main", handoff_dir=str(handoff))
    # a copied context keeps the run/stage telemetry context the method sets out of later tests
    contextvars.copy_context().run(orchestrator._maybe_run_seed_ensemble,
                                   state, object(), "graph_1", None, {}, "# report")
    return state, handoff / "ensemble_forecast.json"


def test_seed_ensemble_needs_two_readable_runs(monkeypatch, tmp_path):
    state, path = _seed_ensemble_env(monkeypatch, tmp_path, _needs_review_forecast())
    # one readable run plus one needs_review run is not an ensemble: nothing is written
    assert not path.exists()
    assert state.options["ensemble_done"] is True
    assert "ensemble" not in state.options


def test_seed_ensemble_two_readable_runs_still_written(monkeypatch, tmp_path):
    seed = fe._assemble_forecast({"headline": "h", "scenarios": _rows([0.4, 0.4, 0.2])})
    state, path = _seed_ensemble_env(monkeypatch, tmp_path, seed)
    agg = json.loads(path.read_text(encoding="utf-8"))
    assert agg["n_runs"] == 2 and "n_runs_excluded" not in agg
    assert state.options["ensemble"]["n_runs"] == 2


def test_renderers_numeric_output_unchanged():
    forecast = {"headline": "h", "scenarios": _rows([0.456, 0.3, 0.244, 1, 0])[:4]}
    forecast["scenarios"].append({"name": "Tail path", "probability": 0,
                                  "resolution_criteria": "c"})
    spine = fe.render_forecast_spine_block(forecast)
    for pct, name in (("46%", _NAMES[0]), ("30%", _NAMES[1]), ("24%", _NAMES[2]),
                      ("100%", _NAMES[3]), ("0%", "Tail path")):
        assert f"· [{pct}] {name}" in spine
    resolution = fe.render_resolution_block(forecast, language="English")
    assert f"- **[46%] {_NAMES[0]}**: " in resolution
    assert "- **[0%] Tail path**: c" in resolution
    binaries = {"binary_forecasts": [
        {"id": "F1", "statement": "s1", "probability": 0.73, "resolution_criteria": "r",
         "theme": "t"},
        {"id": "F2", "statement": "s2", "probability": None, "resolution_criteria": "r",
         "theme": "t"}]}
    table = fe.render_binary_forecasts_block(binaries, language="English")
    assert "| F1 | s1 | 73% | r | t |" in table
    assert "| F2 | s2 | needs review | r | t |" in table
    assert "| F2 | s2 | 待复核 | r | t |" in fe.render_binary_forecasts_block(
        binaries, language="Chinese")


# ------------------------------------------------------------- report agent hooks
class _RouterLLM:
    """chat_json stub routed by prompt marker; records every prompt."""

    def __init__(self, router):
        self.router = router
        self.prompts = []

    def chat_json(self, messages=None, temperature=0.2, max_tokens=2048, **kw):
        content = messages[-1]["content"]
        self.prompts.append(content)
        return self.router(content)


def _agent(**over):
    a = ReportAgent.__new__(ReportAgent)
    defaults = {
        "graph_id": "g1", "simulation_id": "sim1",
        "simulation_requirement": "Will adoption accelerate?",
        "situation_brief": "", "actors": None, "sources": [], "research_report": "",
        "output_language": "English", "scenario_label": "", "base_simulation_id": None,
        "_background_block": "", "_sources_index": "", "_signal_pack": "",
        "_market_pack": "", "_forecast_spine": None, "_forecast_spine_block": "",
        "_retrieval_query": None, "_outline_degraded": False, "_outline_summary": "",
        "_section_tool_calls": 0, "report_logger": None, "console_logger": None,
        "tools": {},
    }
    defaults.update(over)
    for key, value in defaults.items():
        setattr(a, key, value)
    return a


@pytest.fixture
def _report_env(monkeypatch, tmp_path):
    monkeypatch.setattr(Config, "UPLOAD_FOLDER", str(tmp_path), raising=False)
    monkeypatch.setattr(ReportManager, "REPORTS_DIR", str(tmp_path / "reports"), raising=False)
    monkeypatch.setattr(Config, "FORECAST_LEDGER_DIR", str(tmp_path / "ledger"), raising=False)
    monkeypatch.setattr(Config, "REPORT_PUBLISH_GATE", False, raising=False)
    monkeypatch.setattr(Config, "REPORT_REPAIR_PASSES", False, raising=False)
    monkeypatch.setattr(Config, "REPORT_FORECAST_SELF_CRITIQUE", True, raising=False)
    monkeypatch.setattr(Config, "REPORT_CRITIQUE_BEFORE_PROSE", False, raising=False)
    monkeypatch.setattr(Config, "REPORT_SPINE_SELFCONSISTENCY_K", 1, raising=False)
    monkeypatch.setattr(Config, "REPORT_FORECAST_LEDGER", True, raising=False)
    appended = []
    monkeypatch.setattr(forecast_ledger, "append_forecast",
                        lambda forecast, **kw: appended.append(kw["report_id"]))
    return tmp_path, appended


def _load_forecast(tmp_path, report_id):
    path = os.path.join(str(tmp_path), "reports", report_id, "forecast.json")
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def test_spine_review_pinned_and_finalize_not_ledgered(monkeypatch, _report_env):
    tmp_path, appended = _report_env
    _strict(monkeypatch)
    monkeypatch.setattr(Config, "FORECAST_EMIT_BINARY", False, raising=False)
    unreadable = _spine([0.45, "30-40%", 0.2])

    def router(content):
        return {"scenarios": _rows([0.5, 0.3, 0.2])} if "红队评审" in content else unreadable

    llm = _RouterLLM(router)
    agent = _agent(llm=llm)
    agent._derive_and_pin_forecast_spine("report_nr")
    assert agent._forecast_spine is None
    assert agent._spine_probability_review["reason"] == "range"
    assert len(llm.prompts) == 2  # first draw + cache-busting retry

    agent._finalize_structured_forecast("report_nr", "# T\n\nBody text.")
    fc = _load_forecast(tmp_path, "report_nr")
    assert fc["probability_status"] == "needs_review"
    assert fc["scenarios"][1]["probability"] is None
    assert fc["quality"]["probability_parse"] == {"spine": agent._spine_probability_review}
    contract = fe.audit_scenario_contract(fc)
    assert contract["valid"] is False
    integrity = ReportAgent._final_audit_integrity_issues({
        "structured_forecast": {"required": True, "valid": True},
        "scenario_contract": contract,
    })
    assert "结构化情景契约缺失或未通过" in integrity  # the final audit blocks publication
    assert all("红队评审" not in p for p in llm.prompts)  # critic never repairs nulls
    assert appended == []
    gated = ReportAgent._apply_publish_gate(dict(fc))
    assert any("NEEDS_REVIEW" in issue for issue in gated["quality"]["hard_issues"])


def test_finalize_ledger_append_for_readable_or_flag_off(monkeypatch, _report_env):
    tmp_path, appended = _report_env
    monkeypatch.setattr(Config, "FORECAST_EMIT_BINARY", False, raising=False)
    monkeypatch.setattr(Config, "REPORT_FORECAST_SELF_CRITIQUE", False, raising=False)

    _strict(monkeypatch)
    readable = _RouterLLM(lambda content: _spine([0.5, 0.3, 0.2]))
    _agent(llm=readable)._finalize_structured_forecast("report_ok", "# T\n\nBody.")
    assert "probability_status" not in _load_forecast(tmp_path, "report_ok")

    _strict(monkeypatch, False)
    legacy = _RouterLLM(lambda content: _spine([0.45, "30-40%", 0.2]))
    _agent(llm=legacy)._finalize_structured_forecast("report_legacy", "# T\n\nBody.")
    assert "probability_status" not in _load_forecast(tmp_path, "report_legacy")
    assert appended == ["report_ok", "report_legacy"]


def test_retry_parse_publishes_normally(monkeypatch, _report_env):
    _strict(monkeypatch)
    draws = [_spine([0.45, "30-40%", 0.2]), _spine([0.5, 0.3, 0.2])]
    agent = _agent(llm=_RouterLLM(lambda content: draws.pop(0)))
    agent._derive_and_pin_forecast_spine("report_retry")
    assert _probs(agent._forecast_spine) == [0.5, 0.3, 0.2]
    assert agent._spine_probability_review is None
    spine = dict(agent._forecast_spine, citation_audit={"coverage": 1.0})
    gated = ReportAgent._apply_publish_gate(spine)
    assert gated["quality"]["hard_issues"] == []
    assert fe.audit_scenario_contract(agent._forecast_spine)["valid"] is True


def test_finalize_keeps_binary_needs_review_count(monkeypatch, _report_env):
    tmp_path, _appended = _report_env
    _strict(monkeypatch)
    monkeypatch.setattr(Config, "FORECAST_EMIT_BINARY", True, raising=False)
    monkeypatch.setattr(Config, "REPORT_FORECAST_SELF_CRITIQUE", False, raising=False)
    binaries = [dict(_binary(stmt, p), id=f"F{i}") for i, (stmt, p) in
                enumerate(((_BIN_A, 0.8), (_BIN_B, 0.15), (_BIN_C, 0.25)), 1)]
    seen = {}

    def fake_extract(*args, **kwargs):
        seen["called"] = True
        return {"binary_forecasts": binaries,
                "binary_quality": {"count": 3, "needs_review_count": 2,
                                   "needs_review_reasons": {"range": 2}, "issues": []}}

    monkeypatch.setattr(fe, "extract_binary_forecasts", fake_extract)
    agent = _agent(llm=_RouterLLM(lambda content: _spine([0.5, 0.3, 0.2])))
    agent._finalize_structured_forecast("report_bin", "# T\n\nBody.")
    assert seen.get("called") is True
    bq = _load_forecast(tmp_path, "report_bin")["binary_quality"]
    assert bq["needs_review_count"] == 2
    assert bq["needs_review_reasons"] == {"range": 2}
    assert bq["count"] == 3 and "proposition_consistency" in bq
    # the recomputed scorecard carries the withheld line first (gates show two issues)
    assert bq["issues"][0] == "2 binary probabilities unreadable — withheld, not clamped"


def _hermetic_binary_extraction(monkeypatch, tmp_path):
    monkeypatch.setattr(Config, "FORECAST_EMIT_BINARY", True, raising=False)
    monkeypatch.setattr(Config, "REPORT_FORECAST_SELF_CRITIQUE", False, raising=False)
    monkeypatch.setattr(Config, "FORECAST_BINARY_CONTRARIAN", False, raising=False)
    monkeypatch.setattr(Config, "FORECAST_SIM_SENSITIVITY", False, raising=False)
    monkeypatch.setattr(Config, "FORECAST_ENSEMBLE_MODELS", "", raising=False)
    monkeypatch.setattr(Config, "OASIS_SIMULATION_DATA_DIR", str(tmp_path / "sims"),
                        raising=False)


def test_finalize_all_binaries_withheld_keeps_review_counts(monkeypatch, _report_env, caplog):
    tmp_path, _appended = _report_env
    _hermetic_binary_extraction(monkeypatch, tmp_path)
    # the systemic defect: every binary probability written as a percent integer
    percent_ints = {"binary_forecasts": [
        _binary(_BIN_A, 30), _binary(_BIN_B, 45), _binary(_BIN_C, 70)]}

    def router(content):
        return percent_ints if '"binary_forecasts"' in content else _spine([0.5, 0.3, 0.2])

    _strict(monkeypatch)
    llm = _RouterLLM(router)
    with caplog.at_level(logging.WARNING, logger="app.services.forecast_extractor"):
        _agent(llm=llm)._finalize_structured_forecast("report_withheld", "# T\n\nBody.")
    assert any('"binary_forecasts"' in prompt for prompt in llm.prompts)
    fc = _load_forecast(tmp_path, "report_withheld")
    assert "binary_forecasts" not in fc
    bq = fc["binary_quality"]
    assert bq["needs_review_count"] == 3
    assert bq["needs_review_reasons"] == {"plain_gt1": 3}
    assert bq["issues"][0] == "3 binary probabilities unreadable — withheld, not clamped"
    assert bq["count"] == 0 and bq["passed"] is False
    assert any("3 条概率不可读" in record.getMessage() for record in caplog.records)
    gated = ReportAgent._apply_publish_gate(dict(fc, citation_audit={"coverage": 1.0}))
    assert any("withheld, not clamped" in issue
               for issue in gated["quality"]["epistemic_issues"])

    # flag off: the legacy clamp publishes 0.98 rows and records no review counts
    _strict(monkeypatch, False)
    _agent(llm=_RouterLLM(router))._finalize_structured_forecast("report_legacy_bin",
                                                                 "# T\n\nBody.")
    legacy = _load_forecast(tmp_path, "report_legacy_bin")
    assert [b["probability"] for b in legacy["binary_forecasts"]] == [0.98, 0.98, 0.98]
    assert "needs_review_count" not in legacy["binary_quality"]


def test_extract_secondary_model_reviews_counted_separately(monkeypatch):
    _strict(monkeypatch)
    monkeypatch.setattr(Config, "FORECAST_BINARY_CONTRARIAN", False, raising=False)
    monkeypatch.setattr(Config, "FORECAST_ENSEMBLE_MODELS", "other", raising=False)
    primary = {"binary_forecasts": [
        _binary(_BIN_D, 0.8), _binary(_BIN_B, 0.15), _binary(_BIN_C, 0.25)]}
    # the secondary model only pools matched primary rows; its unreadable row for a
    # statement the primary never produced could never have been published
    secondary = {"binary_forecasts": [
        _binary(_BIN_D, 0.7), _binary(_BIN_B, 0.2), _binary(_BIN_A, 30)]}
    res = fe.extract_binary_forecasts(
        "dossier text", FakeLLMClient(json_responses=[primary]), min_count=3,
        ensemble_client_factory=lambda name: FakeLLMClient(json_responses=[secondary],
                                                           provider=name))
    assert {b["statement"] for b in res["binary_forecasts"]} == {_BIN_D, _BIN_B, _BIN_C}
    assert any(b.get("ensemble") for b in res["binary_forecasts"])
    bq = res["binary_quality"]
    assert "needs_review_count" not in bq
    assert not any("withheld" in issue for issue in bq["issues"])
    assert bq["needs_review_secondary_count"] == 1
