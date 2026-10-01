"""EVAL-15: deterministic per-stage scorecard, its orchestrator hook and the offline CLI.

Offline and deterministic: every pipeline is a fixture under tmp_path (the
pipelines / simulations / reports roots are pointed there), the research child
in the ``_run`` tests is faked, and no network or LLM is touched.
"""

from __future__ import annotations

import copy
import json
import os
import re
import socket

import pytest

from app.config import Config
from app.services import pipeline_orchestrator as po
from app.services import stage_scorecard as sc
from scripts import stage_scorecard as cli

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

REPORT_ID = "report_eval15fixture"
SIM_ID = "sim_eval15fixture"


# --------------------------------------------------------------------- fixture
def _write(path, payload):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        if isinstance(payload, str):
            handle.write(payload)
        else:
            json.dump(payload, handle)


def _fact(tag, verified_numbers):
    return {"kiq": "K", "text": "a fact", "sids": [1], "tag": tag,
            "verified_numbers": verified_numbers}


def _binary(index, probability):
    return {"id": f"F{index}", "statement": f"claim {index}", "probability": probability,
            "criteria_sharp": True, "theme": "t"}


def _healthy_forecast(n_binaries=10, scenarios=None):
    return {
        "scenarios": scenarios or [
            {"name": "Base case", "probability": 0.5},
            {"name": "Upside", "probability": 0.3},
            {"name": "Other / Status Quo", "probability": 0.2},
        ],
        "binary_forecasts": [_binary(i, 0.8 if i % 2 else 0.2) for i in range(n_binaries)],
        "binary_quality": {"passed": True, "theme_cardinality": 3, "count": n_binaries},
        "market_comparison": {"anchored_count": 1, "comparisons": []},
    }


def _healthy_audit(coverage=0.9, hard_passed=True):
    return {
        "hard_passed": hard_passed,
        "publish_gate": {"enabled": True, "passed": True},
        "citation_grounding": {"quantitative_claims": 20, "cited": 19, "coverage": 0.95,
                               "resolved_cited": round(coverage * 20),
                               "resolved_coverage": coverage},
        "semantic_citations": {"checked": 10, "unverifiable": 1, "unverifiable_ratio": 0.1},
    }


V3_META = {
    "research_engine": "v3", "v3_workdir": "v3",
    "kiqs": {"planned": 2, "followups": 0, "completed": 2, "fallback": 0, "facts": 7,
             "verified": 3, "invalid_tool_calls": 0, "unknown_tool_calls": 0,
             "tool_exceptions": 0},
    "tools": {"searches": 10, "cached_searches": 2, "fetches": 6, "cached_fetches": 2, "failures": 1},
    "research_qa": {"passed": True, "failures": []},
    "plan_fallback": [], "synthesis_fallback_sections": [], "actors_count": 12,
}
KIQ_RECORDS = {
    "K1": [_fact("VERIFIED", True), _fact("VERIFIED", None), _fact("REPORTED", None),
           _fact("UNVERIFIED", False)],
    "K2": [_fact("VERIFIED", True), _fact("UNVERIFIED", False), _fact("REPORTED", None)],
}


@pytest.fixture
def roots(tmp_path, monkeypatch):
    """Point every artifact root DRF resolves at tmp_path."""
    sims = str(tmp_path / "simulations")
    monkeypatch.setattr(Config, "PIPELINE_DATA_DIR", str(tmp_path / "pipelines"), raising=False)
    monkeypatch.setattr(Config, "OASIS_SIMULATION_DATA_DIR", sims, raising=False)
    monkeypatch.setattr(po.SimulationRunner, "RUN_STATE_DIR", sims, raising=False)
    monkeypatch.setattr(po.ReportManager, "REPORTS_DIR", str(tmp_path / "reports"), raising=False)
    monkeypatch.setattr(Config, "REPORT_PUBLISH_GATE_MIN_COVERAGE", 0.75, raising=False)
    for name in ("REPORT_PUBLISH_GATE", "REPORT_FINAL_READ_ONLY_AUDIT", "PIPELINE_HEALTH_GATE"):
        monkeypatch.setattr(Config, name, True, raising=False)
    return tmp_path


def _make_pipeline(pid="pipe_eval15fixture", *, mode="full", status="completed",
                   stage_status=None, meta=V3_META, kiqs=KIQ_RECORDS, markets=None,
                   forecast=None, audit=None, options=None, task_id="task_eval15fixture"):
    """A complete full-mode pipeline on disk; every stage passes unless overridden."""
    stages = {stage: po.StageState(name=stage, status="completed") for stage in sc.STAGES}
    for stage, value in (stage_status or {}).items():
        if value is None:
            stages.pop(stage, None)
        else:
            stages[stage].status = value
    state = po.PipelineState(
        pipeline_id=pid, prompt="Will X happen by 2030?", mode=mode, status=status,
        task_id=task_id, report_id=REPORT_ID, simulation_id=SIM_ID, stages=stages,
        options=dict(options if options is not None else {"graph_prune": {"kept": 9}}),
    )
    state.handoff_dir = po.PipelineManager.handoff_dir(pid)
    po.PipelineManager.save(state)
    hd = state.handoff_dir
    if meta is not None:
        _write(os.path.join(hd, "meta.json"), meta)
    for kid, facts in (kiqs or {}).items():
        _write(os.path.join(hd, "v3", "kiq", f"{kid}.json"), {"id": kid, "facts": facts})
    _write(os.path.join(hd, "prediction_markets.json"), markets or {
        "markets": [{"market_id": "m1"}],
        "status": {"attempted": True, "selected_count": 1, "empty_reason": None}})
    _write(os.path.join(hd, "ontology.json"),
           {"entity_types": [{"name": "Organization"}, {"name": "Person"}], "edge_types": []})
    _write(os.path.join(hd, "graph_prune.json"), {
        "enabled": True, "postcondition_ok": True, "cap_satisfied": True,
        "core_actor_coverage": 0.9, "core_actor_matched": 9, "core_actor_expected": 10,
        "min_core_coverage": 0.8})
    sim_dir = os.path.join(Config.OASIS_SIMULATION_DATA_DIR, SIM_ID)
    _write(os.path.join(sim_dir, "actor_cast_manifest.json"), {"selected_actor_count": 12})
    _write(os.path.join(sim_dir, "run_summary.json"), {
        "simulation_health": "ok", "organic_action_count": 30, "seed_action_count": 10,
        "rounds_with_organic_actions": 4, "rounds_executed": 5})
    report_dir = po.ReportManager._get_report_folder(REPORT_ID)
    _write(os.path.join(report_dir, "forecast.json"), forecast or _healthy_forecast())
    _write(os.path.join(report_dir, "final_audit.json"), audit or _healthy_audit())
    _write(os.path.join(report_dir, "full_report.md"), "# Report\n")
    _write(os.path.join(report_dir, "agent_log.jsonl"), "".join(
        json.dumps({"action": action, "stage": "generating", "details": {}}) + "\n"
        for action in ("report_start", "tool_call", "tool_result")))
    # INFRA-5's tool_dispatch counters mark a log that writes tool_unknown rows (EVAL-16).
    _write(os.path.join(report_dir, "telemetry.json"), {"totals": {
        "tool_calls": 1, "tool_dispatch": {"dispatched": 1, "rejected_parse": 0, "rejected_params": 0,
                                           "rejected_unknown": 0, "repaired": 0}}})
    _write(po.PipelineManager.manifest_path(pid), {
        "repo_git_sha": "abc123",
        "resolved": {"research": {"model": "glm", "depth": "deep"},
                     "report": {"provider": "glm", "model_name": "glm-5.3"}}})
    return state


def _score(pid="pipe_eval15fixture", thresholds=None):
    return sc.build_stage_scorecard(sc.resolve_inputs(pid), thresholds)


def _metric(card, stage, name):
    return card["stages"][stage]["metrics"][name]


# ------------------------------------------------------------- happy baseline
def test_healthy_fixture_passes_every_stage_and_envelope_shape(roots):
    _make_pipeline()
    card = _score()
    assert card["schema_version"] == "stage-scorecard/v1"
    assert list(card["stages"]) == list(sc.STAGES) == list(card["checks"])
    assert sc.summarize_checks(card) == dict.fromkeys(sc.STAGES, True)
    identity = card["identity"]
    assert identity["pipeline_id"] == "pipe_eval15fixture"
    assert identity["task_id"] == "task_eval15fixture"
    assert identity["mode"] == "full" and identity["status"] == "completed"
    assert identity["repo_git_sha"] == "abc123" and identity["scored_by"] == "backfill"
    assert identity["backbone"] == {"report": {"provider": "glm", "model_name": "glm-5.3"},
                                    "research": {"model": "glm"}}
    assert set(card["artifacts"]) == {
        "research_meta", "research_kiq_facts", "prediction_markets", "ontology", "graph_prune",
        "actor_cast", "run_summary", "forecast", "final_audit", "agent_log", "report_telemetry",
        "run_manifest"}
    assert all(re.fullmatch(r"[0-9a-f]{64}", digest) for digest in card["artifacts"].values())
    record = _metric(card, "run", "organic_share")
    assert set(record) >= {"value", "num", "den", "status", "source"}
    assert (record["num"], record["den"], record["value"]) == (30, 40, 0.75)
    # Deterministic: the same inputs give byte-identical output.
    assert json.dumps(card, sort_keys=True) == json.dumps(_score(), sort_keys=True)
    json.dumps(card, allow_nan=False)


# -------------------------------------------------------------------- research
def test_research_rates_from_v3_kiq_fixture(roots):
    _make_pipeline()
    card = _score()
    verified = _metric(card, "research", "verified_share")
    assert (verified["num"], verified["den"], verified["value"]) == (3, 7, 0.4286)
    assert verified["status"] == "measured"
    # The files agree with meta.kiqs (7 facts, 3 VERIFIED), so the disk projection stands.
    assert verified["source"] == "handoff/v3/kiq/*.json:facts[].tag"
    numbers = _metric(card, "research", "number_verification_pass_rate")
    # Only facts whose numbers were checked (True/False) count; None is "no number".
    assert (numbers["num"], numbers["den"], numbers["value"]) == (2, 4, 0.5)
    completion = _metric(card, "research", "kiq_completion")
    assert (completion["num"], completion["den"], completion["value"]) == (2, 2, 1.0)
    fallback = _metric(card, "research", "kiq_fallback_rate")
    assert (fallback["num"], fallback["den"], fallback["value"]) == (0, 2, 0.0)
    tools = _metric(card, "research", "tool_failure_rate")
    assert (tools["num"], tools["den"], tools["value"]) == (1, 20, 0.05)
    assert _metric(card, "research", "actor_count")["value"] == 12


@pytest.mark.parametrize("case", ["demoted-in-memory", "stale-record-on-disk", "meta-garbage"])
def test_kiq_facts_cross_checked_against_meta(roots, case):
    """The files never outvote the producer's own meta.kiqs counts."""
    meta, kiqs = V3_META, KIQ_RECORDS
    if case == "demoted-in-memory":
        # A resumed v3 run demoted one shell-verified fact in memory only: the file
        # still says VERIFIED, meta.kiqs.verified does not.
        meta = dict(V3_META, kiqs=dict(V3_META["kiqs"], verified=2))
    elif case == "stale-record-on-disk":
        # A follow-up record the run no longer counts is still in kiq/.
        kiqs = dict(KIQ_RECORDS, K9=[_fact("VERIFIED", True), _fact("VERIFIED", True)])
    else:
        meta = dict(V3_META, kiqs=dict(V3_META["kiqs"], verified=9))  # 9 of 7
    _make_pipeline(meta=meta, kiqs=kiqs)
    card = _score()
    share = _metric(card, "research", "verified_share")
    numbers = _metric(card, "research", "number_verification_pass_rate")
    assert share["source"] == "handoff/meta.json:kiqs.verified/facts"
    if case == "meta-garbage":
        assert share["status"] == "unreadable" and share["value"] is None
        assert share["detail"] == "numerator exceeds denominator"
    else:
        expected = (2, 7, 0.2857) if case == "demoted-in-memory" else (3, 7, 0.4286)
        assert (share["num"], share["den"], share["value"]) == expected
        assert share["status"] == "measured"
        assert share["detail"].startswith("disk facts disagree with meta.kiqs")
    # The per-fact number checks have no producer count to validate them against.
    assert numbers["status"] == "unreadable" and numbers["value"] is None
    assert numbers["detail"].startswith("disk facts disagree with meta.kiqs")
    # Both metrics are descriptive: the research contract itself is unaffected.
    assert card["checks"]["research"]["passed"] is True
    json.dumps(card, allow_nan=False)


def test_rate_numerator_never_exceeds_denominator(roots):
    meta = dict(V3_META, kiqs={"planned": 2, "followups": 1, "completed": 5},
                tools={"searches": 1, "cached_searches": 0, "fetches": 1, "cached_fetches": 0,
                       "failures": 9})
    _make_pipeline(meta=meta)
    card = _score()
    for name in ("kiq_completion", "tool_failure_rate"):
        record = _metric(card, "research", name)
        assert record["status"] == "unreadable" and record["value"] is None
        assert record["detail"] == "numerator exceeds denominator"
    assert "kiq_completion" in card["checks"]["research"]["failed"]
    assert card["checks"]["research"]["passed"] is False


def test_missing_unreadable_never_scored(roots):
    state = _make_pipeline()
    report_dir = po.ReportManager._get_report_folder(REPORT_ID)
    os.remove(os.path.join(report_dir, "final_audit.json"))
    _write(os.path.join(report_dir, "forecast.json"), "{not json")
    os.remove(os.path.join(state.handoff_dir, "meta.json"))
    card = _score()
    for name in ("final_audit_hard_passed", "publish_gate_passed", "citation_coverage"):
        record = _metric(card, "report", name)
        assert record["value"] is None and record["status"] == "artifact_missing", name
    for name in ("binary_count", "binary_quality_passed", "probability_sum_ok",
                 "has_residual_scenario"):
        record = _metric(card, "report", name)
        assert record["value"] is None and record["status"] == "unreadable", name
    report = card["checks"]["report"]
    assert report["passed"] is False
    assert set(report["failed"]) == {
        "final_audit_hard_passed", "publish_gate_passed", "binary_count",
        "binary_quality_passed", "probability_sum_ok", "has_residual_scenario",
        "citation_coverage"}
    research = card["checks"]["research"]
    assert _metric(card, "research", "kiq_completion")["status"] == "artifact_missing"
    assert _metric(card, "research", "verified_share")["status"] == "artifact_missing"
    assert {"kiq_completion", "research_qa_passed"} <= set(research["failed"])
    assert "forecast" not in card["artifacts"] and "final_audit" not in card["artifacts"]


def test_research_only_and_failed_stage_status(roots):
    _make_pipeline("pipe_eval15ro", mode="research_only",
                   stage_status=dict.fromkeys(sc.STAGES[1:]))
    card = _score("pipe_eval15ro")
    assert card["stages"]["research"]["status"] == "scored"
    assert card["checks"]["research"]["passed"] is True
    for stage in sc.STAGES[1:]:
        assert card["stages"][stage]["status"] == "not_applicable"
        assert card["stages"][stage]["metrics"] == {}
        assert card["checks"][stage] == {"passed": None, "failed": [], "unevaluable": []}

    _make_pipeline("pipe_eval15fail", status="failed",
                   stage_status={"graph": "failed", "prepare": None, "run": None, "report": None})
    card = _score("pipe_eval15fail")
    assert [card["stages"][s]["status"] for s in sc.STAGES] == [
        "scored", "scored", "scored", "not_reached", "not_reached", "not_reached"]
    assert card["checks"]["graph"]["passed"] is False
    assert card["checks"]["graph"]["failed"] == ["stage_status"]
    assert card["checks"]["ontology"]["passed"] is True

    _make_pipeline("pipe_eval15cancel", status="cancelled",
                   stage_status={"run": "cancelled", "report": "pending"})
    card = _score("pipe_eval15cancel")
    assert card["stages"]["run"]["status"] == "scored"
    assert card["checks"]["run"]["failed"] == ["stage_status"]
    assert card["stages"]["report"]["status"] == "not_reached"


def test_legacy_meta_not_instrumented(roots):
    legacy = {"actors_count": 19, "research_quality": {"score": 0.7}}
    _make_pipeline(meta=legacy, kiqs={})
    card = _score()
    for name in ("kiq_completion", "kiq_fallback_rate", "verified_share",
                 "number_verification_pass_rate", "tool_failure_rate", "research_qa_passed",
                 "plan_fallback", "synthesis_fallback_sections"):
        record = _metric(card, "research", name)
        assert record["status"] == "not_instrumented" and record["value"] is None, name
    research = card["checks"]["research"]
    assert research["passed"] is None  # unevaluable, never a pass
    assert research["failed"] == []
    assert research["unevaluable"] == ["kiq_completion", "kiq_fallback_rate", "research_qa_passed",
                                       "plan_fallback", "synthesis_fallback_sections"]


def test_kiq_fallback_fails_even_when_every_kiq_completed(roots):
    """completed counts KIQs whose agent fell back to deterministic notes; the fallback is gated."""
    _make_pipeline(meta=dict(V3_META, kiqs=dict(V3_META["kiqs"], fallback=2)))
    card = _score()
    assert _metric(card, "research", "kiq_completion")["value"] == 1.0
    fallback = _metric(card, "research", "kiq_fallback_rate")
    assert (fallback["num"], fallback["den"], fallback["value"]) == (2, 2, 1.0)
    assert card["checks"]["research"]["failed"] == ["kiq_fallback_rate"]
    assert card["checks"]["research"]["passed"] is False
    # A kiqs block that never recorded fallbacks is unevaluable, never a pass.
    kiqs = {key: value for key, value in V3_META["kiqs"].items() if key != "fallback"}
    _make_pipeline("pipe_eval15nofb", meta=dict(V3_META, kiqs=kiqs))
    card = _score("pipe_eval15nofb")
    assert _metric(card, "research", "kiq_fallback_rate")["status"] == "not_instrumented"
    assert card["checks"]["research"] == {"passed": None, "failed": [],
                                          "unevaluable": ["kiq_fallback_rate"]}


def test_research_fallbacks_fail_their_contracts(roots):
    _make_pipeline(meta=dict(V3_META, plan_fallback=["kiqs"],
                             synthesis_fallback_sections=["Outlook"],
                             research_qa={"passed": False}))
    card = _score()
    assert _metric(card, "research", "plan_fallback")["detail"] == ["kiqs"]
    assert card["checks"]["research"]["failed"] == [
        "research_qa_passed", "plan_fallback", "synthesis_fallback_sections"]


# ---------------------------------------------------------------------- report
def test_report_contract_checks(roots):
    forecast = _healthy_forecast(n_binaries=9, scenarios=[
        {"name": "Base case", "probability": 0.5},
        {"name": "Upside", "probability": 0.47},
    ])
    _make_pipeline(forecast=forecast, audit=_healthy_audit(hard_passed=False))
    card = _score()
    report = card["checks"]["report"]
    assert report["passed"] is False
    assert sorted(report["failed"]) == sorted([
        "final_audit_hard_passed", "binary_count", "probability_sum_ok",
        "has_residual_scenario"])
    assert report["unevaluable"] == []
    total = _metric(card, "report", "probability_sum_ok")
    assert total["sum"] == pytest.approx(0.97) and total["tolerance"] == 0.005
    assert _metric(card, "report", "binary_count")["value"] == 9
    assert _metric(card, "report", "binary_count")["threshold"] == 10
    # Descriptive report metrics are projected, never gated.
    assert _metric(card, "report", "market_anchor_count")["value"] == 1
    assert _metric(card, "report", "theme_cardinality")["value"] == 3
    ratio = _metric(card, "report", "semantic_citation_unverifiable_ratio")
    assert (ratio["num"], ratio["den"], ratio["value"]) == (1, 10, 0.1)


def test_probability_sum_overflow_stays_serialisable(roots, capsys):
    """Finite probabilities whose sum leaves float range fail the check without an inf sum."""
    forecast = _healthy_forecast(scenarios=[
        {"name": "Base case", "probability": 1e308},
        {"name": "Other", "probability": 1e308}])
    state = _make_pipeline(forecast=forecast)
    card = _score()
    total = _metric(card, "report", "probability_sum_ok")
    assert total["status"] == "measured" and total["value"] is False
    assert "sum" not in total
    assert total["detail"] == "the scenario probability sum is not finite"
    assert card["checks"]["report"]["failed"] == ["probability_sum_ok"]
    json.dumps(card, allow_nan=False)
    # The sidecar writer and the CLI both serialise it.
    written = sc.write_stage_scorecard(state.pipeline_id, state=state.to_dict())
    with open(sc.sidecar_path(state.pipeline_id), encoding="utf-8") as handle:
        assert json.load(handle) == written
    assert cli.main(["score", "--pipeline", state.pipeline_id]) == 0
    assert json.loads(capsys.readouterr().out)["checks"]["report"]["failed"] == [
        "probability_sum_ok"]


@pytest.mark.parametrize("semantic,expected", [
    # Older final audits stored only the counts (e.g. report_1b70ace5c9e8).
    ({"checked": 288, "unverifiable": 0, "unsupported": 0, "passed": True, "examples": []},
     {"status": "measured", "value": 0.0, "num": 0, "den": 288,
      "source": "report/final_audit.json:semantic_citations.unverifiable/checked"}),
    ({"checked": 119, "unverifiable": 8, "unsupported": 0, "passed": True},
     {"status": "measured", "value": 0.0672, "num": 8, "den": 119}),
    ({"unsupported": 0, "passed": True},
     {"status": "not_instrumented", "value": None}),
    ({"checked": 10, "unverifiable": 1, "unverifiable_ratio": None},
     {"status": "unreadable", "value": None, "detail": "stored value is not a finite number"}),
], ids=["legacy-counts", "legacy-counts-nonzero", "no-fields", "present-not-finite"])
def test_semantic_unverifiable_ratio_legacy_shapes(roots, semantic, expected):
    _make_pipeline(audit=dict(_healthy_audit(), semantic_citations=semantic))
    record = _metric(_score(), "report", "semantic_citation_unverifiable_ratio")
    assert {key: record.get(key) for key in expected} == expected


def test_residual_detection_reuses_forecast_extractor_and_thresholds_override(roots):
    forecast = _healthy_forecast(n_binaries=9, scenarios=[
        {"name": "情景一", "probability": 0.6}, {"name": "其它 / 维持现状", "probability": 0.4}])
    _make_pipeline(forecast=forecast)
    card = _score()
    assert _metric(card, "report", "has_residual_scenario")["value"] is True
    assert card["checks"]["report"]["failed"] == ["binary_count"]
    relaxed = _score(thresholds={"min_binaries": 9, "unknown": 1, "actor_cap": "x"})
    assert relaxed["thresholds"]["min_binaries"] == 9
    assert relaxed["thresholds"]["actor_cap"] == 20  # an invalid override keeps the default
    assert relaxed["checks"]["report"]["passed"] is True


def test_relaxed_runtime_gate_recorded(roots, monkeypatch):
    monkeypatch.setattr(Config, "REPORT_PUBLISH_GATE_MIN_COVERAGE", 0.05, raising=False)
    # The run's publish gate passed at the relaxed 0.05 threshold with 0.07 coverage.
    _make_pipeline(audit=_healthy_audit(coverage=0.07))
    card = _score()
    gate = card["runtime_gates"]["REPORT_PUBLISH_GATE_MIN_COVERAGE"]
    assert gate == {"effective": 0.05, "suite_threshold": 0.75, "relaxed": True,
                    "source": "process_config"}
    coverage = _metric(card, "report", "citation_coverage")
    assert coverage["value"] == 0.07 and coverage["threshold"] == 0.75
    assert coverage["source"].endswith("citation_grounding.resolved_coverage")
    assert card["checks"]["report"]["failed"] == ["citation_coverage"]
    assert _metric(card, "report", "publish_gate_passed")["value"] is True
    assert card["runtime_gates"]["REPORT_PUBLISH_GATE"] == {
        "effective": True, "suite_threshold": True, "relaxed": False,
        "source": "report/final_audit.json:publish_gate.enabled"}
    for name in ("REPORT_FINAL_READ_ONLY_AUDIT", "PIPELINE_HEALTH_GATE"):
        assert card["runtime_gates"][name] == {
            "effective": True, "suite_threshold": True, "relaxed": False,
            "source": "process_config"}


def test_publish_gate_disabled_fails_its_contract(roots, monkeypatch):
    monkeypatch.setattr(Config, "REPORT_PUBLISH_GATE", False, raising=False)
    audit = dict(_healthy_audit(), publish_gate={"enabled": False})
    _make_pipeline(audit=audit)
    card = _score()
    assert card["runtime_gates"]["REPORT_PUBLISH_GATE"]["relaxed"] is True
    assert _metric(card, "report", "publish_gate_passed")["detail"] == (
        "publish gate disabled at runtime")
    assert card["checks"]["report"]["failed"] == ["publish_gate_passed"]


def test_runtime_gates_prefer_values_the_final_audit_recorded(roots, monkeypatch):
    """A backfill reads the gate values the report was audited under, not today's config."""
    audit_src = "report/final_audit.json:publish_gate.enabled"
    # The run published with the gate off; the backfill process has it on.
    _make_pipeline(audit=dict(_healthy_audit(), publish_gate={"enabled": False, "passed": True},
                              read_only=True))
    monkeypatch.setattr(Config, "REPORT_FINAL_READ_ONLY_AUDIT", False, raising=False)
    gates = _score()["runtime_gates"]
    assert gates["REPORT_PUBLISH_GATE"] == {"effective": False, "suite_threshold": True,
                                            "relaxed": True, "source": audit_src}
    assert gates["REPORT_FINAL_READ_ONLY_AUDIT"] == {
        "effective": True, "suite_threshold": True, "relaxed": False,
        "source": "report/final_audit.json:read_only"}
    assert gates["PIPELINE_HEALTH_GATE"]["source"] == "process_config"
    assert gates["REPORT_PUBLISH_GATE_MIN_COVERAGE"]["source"] == "process_config"

    # The run published with the gate on; the backfill process has it off.
    monkeypatch.setattr(Config, "REPORT_PUBLISH_GATE", False, raising=False)
    _make_pipeline("pipe_eval15gateon")
    gates = _score("pipe_eval15gateon")["runtime_gates"]
    assert gates["REPORT_PUBLISH_GATE"] == {"effective": True, "suite_threshold": True,
                                            "relaxed": False, "source": audit_src}
    assert gates["REPORT_FINAL_READ_ONLY_AUDIT"] == {
        "effective": False, "suite_threshold": True, "relaxed": True, "source": "process_config"}

    # No audit, or a report stage this attempt never reached: process configuration.
    process = {"effective": False, "suite_threshold": True, "relaxed": True,
               "source": "process_config"}
    _make_pipeline("pipe_eval15noaudit")
    os.remove(os.path.join(po.ReportManager._get_report_folder(REPORT_ID), "final_audit.json"))
    assert _score("pipe_eval15noaudit")["runtime_gates"]["REPORT_PUBLISH_GATE"] == process
    _make_pipeline("pipe_eval15unreached", status="failed",
                   stage_status={"run": "failed", "report": "pending"})
    assert os.path.exists(os.path.join(po.ReportManager._get_report_folder(REPORT_ID),
                                       "final_audit.json"))
    assert _score("pipe_eval15unreached")["runtime_gates"]["REPORT_PUBLISH_GATE"] == process


# ---------------------------------------------------------------------- markets
def _track(state, *, queries=2, successful=0, failures=0, timeouts=0, empty_reason=None):
    """One research track's prediction_markets snapshot (market_tools status shape)."""
    return {"as_of": "2026-09-01T00:00:00Z", "markets": [], "queries": [f"q-{state}"],
            "status": {"state": state, "attempted": True, "attempted_query_count": queries,
                       "query_count": queries, "successful_query_count": successful,
                       "transport_failure_count": failures, "inflight_timeout_count": timeouts,
                       "raw_candidate_count": 0, "candidate_count": 0,
                       "empty_reason": empty_reason or state}}


# The orchestrator's real multi-track merge keeps the specific infra state in
# status.state beside the generic empty_reason 'no_equivalent_market' (a partial
# transport failure has carried its own empty_reason since RESEARCH-3).
_MERGED_TIMEOUT = po.merge_market_snapshots(
    [_track("inflight_timeout", timeouts=2), _track("inflight_timeout", timeouts=2)])
_MERGED_PARTIAL = po.merge_market_snapshots(
    [_track("partial_transport_failure", successful=1, failures=1),
     _track("verified_empty", successful=2, empty_reason="no_equivalent_market")])
_MERGED_EMPTY = po.merge_market_snapshots(
    [_track("verified_empty", successful=2, empty_reason="no_equivalent_market")] * 2)


def test_merged_market_fixtures_have_the_ambiguous_shape():
    assert _MERGED_TIMEOUT["status"]["state"] == "inflight_timeout"
    assert _MERGED_PARTIAL["status"]["state"] == "partial_transport_failure"
    assert _MERGED_EMPTY["status"]["state"] == "verified_empty"
    for merged in (_MERGED_TIMEOUT, _MERGED_EMPTY):
        assert merged["status"]["empty_reason"] == "no_equivalent_market"
    assert _MERGED_PARTIAL["status"]["empty_reason"] == "partial_transport_failure"


@pytest.mark.parametrize("payload,state,verdict", [
    ({"markets": [{"market_id": "m"}], "status": {"selected_count": 1}}, "found", "pass"),
    ({"markets": [], "no_relevant_markets": True,
      "status": {"attempted": True, "empty_reason": "all_candidates_irrelevant"}},
     "none_relevant", "pass"),
    ({"markets": [], "status": {"attempted": True, "empty_reason": "no_equivalent_market"}},
     "none_relevant", "pass"),
    ({"markets": [], "status": {"attempted": True, "state": "verified_empty",
                                "empty_reason": None}}, "none_relevant", "pass"),
    ({"markets": [], "status": {"attempted": True, "empty_reason": "transport_failure",
                                "query_count": 16, "successful_query_count": 35}},
     "infra_failure", "fail"),
    ({"markets": [], "status": {"attempted": True, "empty_reason": "inflight_timeout"}},
     "infra_failure", "fail"),
    ({"markets": [], "status": {"attempted": True, "empty_reason": "no_derivable_queries"}},
     "not_attempted", "unevaluable"),
    ({"markets": [], "status": {"attempted": False}}, "not_attempted", "unevaluable"),
    (None, "not_attempted", "unevaluable"),
    (_MERGED_TIMEOUT, "infra_failure", "fail"),
    (_MERGED_PARTIAL, "infra_failure", "fail"),
    (_MERGED_EMPTY, "none_relevant", "pass"),
    ({"markets": [], "status": {"attempted": True, "state": "inflight_timeout",
                                "empty_reason": "no_equivalent_market"}}, "infra_failure", "fail"),
    ({"markets": [], "status": {"attempted": True, "state": "partial_transport_failure",
                                "empty_reason": "no_equivalent_market"}}, "infra_failure", "fail"),
    # A single-snapshot producer labels a partly failed, candidate-free search
    # 'no_equivalent_market'; the owners' ladder calls that a transport failure.
    ({"markets": [], "no_relevant_markets": True,
      "status": {"attempted": True, "query_count": 16, "successful_query_count": 15,
                 "transport_failure_count": 1, "candidate_count": 0,
                 "empty_reason": "no_equivalent_market"}}, "infra_failure", "fail"),
    ({"markets": [], "status": {"attempted": True, "transport_failure_count": 1,
                                "candidate_count": 20,
                                "empty_reason": "all_candidates_irrelevant"}},
     "none_relevant", "pass"),
    # no_relevant_markets alone never makes an unlabelled empty result a pass.
    ({"markets": [], "no_relevant_markets": True, "status": {"attempted": True}},
     "not_attempted", "unevaluable"),
    # Without a status block: markets are direct evidence, a transport reason is infra.
    ({"markets": [{"market_id": "m"}]}, "found", "pass"),
    ({"markets": [], "no_relevant_markets": True, "reason": "pre-pass transport circuit open"},
     "infra_failure", "fail"),
], ids=["found", "irrelevant", "no-equivalent", "verified-empty", "transport", "timeout",
        "no-queries", "not-attempted", "file-absent", "merged-timeout", "merged-partial",
        "merged-empty", "state-timeout", "state-partial", "single-partial",
        "irrelevant-with-failures", "unlabelled-empty", "statusless-found",
        "statusless-transport"])
def test_market_states(roots, payload, state, verdict):
    pipeline = _make_pipeline()
    path = os.path.join(pipeline.handoff_dir, "prediction_markets.json")
    if payload is None:
        os.remove(path)
    else:
        _write(path, payload)
    card = _score()
    record = _metric(card, "research", "market_state")
    assert record["value"] == state and record["status"] == "measured"
    research = card["checks"]["research"]
    assert ("market_state" in research["failed"]) is (verdict == "fail")
    assert ("market_state" in research["unevaluable"]) is (verdict == "unevaluable")
    # Both status fields are recorded, so a reader sees what the classification read.
    pm_status = (payload or {}).get("status") or {}
    for key in ("state", "empty_reason"):
        if pm_status.get(key):
            assert record["detail"][key] == pm_status[key]


def test_market_state_unreadable_fails(roots):
    pipeline = _make_pipeline()
    _write(os.path.join(pipeline.handoff_dir, "prediction_markets.json"), "[1, 2")
    card = _score()
    assert _metric(card, "research", "market_state")["status"] == "unreadable"
    assert "market_state" in card["checks"]["research"]["failed"]


@pytest.mark.parametrize("payload,status,verdict", [
    ({"markets": [], "no_relevant_markets": True, "status": "transport_failure"},
     "unreadable", "fail"),
    ({"markets": [], "status": None}, "unreadable", "fail"),
    ({"markets": {"m1": {}}, "status": {"attempted": True, "selected_count": 1}},
     "unreadable", "fail"),
    ({"markets": None, "status": {"attempted": True, "empty_reason": "no_equivalent_market"}},
     "unreadable", "fail"),
    ({"markets": [], "no_relevant_markets": True}, "not_instrumented", "unevaluable"),
    ({"markets": [], "no_relevant_markets": True, "reason": "no derivable queries"},
     "not_instrumented", "unevaluable"),
], ids=["status-string", "status-null", "markets-object", "markets-null", "statusless-empty",
        "statusless-no-queries"])
def test_market_state_fails_closed_on_malformed_or_statusless_files(roots, payload, status,
                                                                    verdict):
    """A wrong shape is unreadable (fails); a status-less empty result is unevaluable."""
    pipeline = _make_pipeline()
    _write(os.path.join(pipeline.handoff_dir, "prediction_markets.json"), payload)
    card = _score()
    record = _metric(card, "research", "market_state")
    assert record["status"] == status and record["value"] is None
    research = card["checks"]["research"]
    assert ("market_state" in research["failed"]) is (verdict == "fail")
    assert ("market_state" in research["unevaluable"]) is (verdict == "unevaluable")
    assert research["passed"] is (False if verdict == "fail" else None)


# ------------------------------------------------------------ graph/prepare/run
def test_graph_prepare_run_contracts(roots):
    pipeline = _make_pipeline()
    _write(os.path.join(pipeline.handoff_dir, "graph_prune.json"), {
        "enabled": True, "postcondition_ok": None, "degraded": True,
        "core_actor_coverage": 0.5, "core_actor_matched": 5, "core_actor_expected": 10,
        "min_core_coverage": 0.8, "skipped_reason": "core actor coverage below threshold"})
    sim_dir = os.path.join(Config.OASIS_SIMULATION_DATA_DIR, SIM_ID)
    _write(os.path.join(sim_dir, "actor_cast_manifest.json"), {"selected_actor_count": 21})
    _write(os.path.join(sim_dir, "run_summary.json"), {
        "simulation_health": "hollow", "organic_action_count": 0, "seed_action_count": 40,
        "rounds_with_organic_actions": 0, "rounds_executed": 5})
    card = _score()
    graph = card["checks"]["graph"]
    # The skipped-prune audit has no cap_satisfied field: unevaluable, not a pass.
    assert graph["failed"] == ["postcondition_ok", "core_actor_coverage"]
    assert graph["unevaluable"] == ["cap_satisfied"] and graph["passed"] is False
    assert _metric(card, "graph", "core_actor_coverage")["threshold"] == 0.8
    assert card["checks"]["prepare"]["failed"] == ["selected_actor_count"]
    assert card["checks"]["run"]["failed"] == ["simulation_health"]
    assert _metric(card, "run", "organic_share")["value"] == 0.0


def test_graph_prune_absent_is_not_instrumented_unless_recorded(roots):
    pipeline = _make_pipeline(options={})
    os.remove(os.path.join(pipeline.handoff_dir, "graph_prune.json"))
    card = _score()
    assert _metric(card, "graph", "postcondition_ok")["status"] == "not_instrumented"
    assert card["checks"]["graph"]["passed"] is None
    # The run recorded a prune but the audit is gone: fail closed.
    _make_pipeline("pipe_eval15gp")
    os.remove(os.path.join(po.PipelineManager.handoff_dir("pipe_eval15gp"), "graph_prune.json"))
    card = _score("pipe_eval15gp")
    assert _metric(card, "graph", "postcondition_ok")["status"] == "artifact_missing"
    assert card["checks"]["graph"]["passed"] is False


def test_degraded_simulation_states_match_drf2_and_orchestrator(roots, monkeypatch):
    """The scorecard's hollow set is the one drf2's gate and the orchestrator flag."""
    monkeypatch.syspath_prepend(_REPO_ROOT)
    from drf2.driver import gates

    candidates = sorted(sc.DEGRADED_SIMULATION_HEALTH | {"ok", "unknown_state"})
    drf2_flagged = {
        health for health in candidates
        if gates.hollow_sim_gate(summary={"simulation_health": health,
                                          "organic_action_count": 5}, run_state={}).issues}
    orchestrator_flagged = set()
    for health in candidates:
        sim_id = f"sim_parity_{health}"
        _write(os.path.join(po.SimulationRunner.RUN_STATE_DIR, sim_id, "run_summary.json"),
               {"simulation_health": health, "organic_action_count": 5})
        _status, issues, _meta = po.PipelineOrchestrator()._assess_run_health(sim_id)
        if any("simulation_health=" in issue for issue in issues):
            orchestrator_flagged.add(health)
    assert drf2_flagged == orchestrator_flagged == set(sc.DEGRADED_SIMULATION_HEALTH)


# --------------------------------------------------------------- never raises
_GARBAGE = [b"\xff\xfe\x00garbage", "{not json", "[]", "null", "42", '"text"',
            json.dumps({"kiqs": "x", "tools": [], "research_qa": 5, "plan_fallback": "y",
                        "synthesis_fallback_sections": 3, "actors_count": True}),
            json.dumps({"hard_passed": "yes", "publish_gate": [], "citation_grounding": {
                "coverage": "NaN", "cited": -1, "quantitative_claims": True},
                "semantic_citations": {"checked": 1.5}}),
            json.dumps({"scenarios": [{"probability": "0.5"}, 7], "binary_forecasts": {},
                        "binary_quality": [], "market_comparison": {"anchored_count": -2}}),
            json.dumps({"entity_types": "many", "selected_actor_count": "12",
                        "simulation_health": 3, "organic_action_count": 1e400,
                        "postcondition_ok": "maybe", "core_actor_coverage": float("nan")},
                       allow_nan=True),
            # Integers beyond float range must not overflow a rate or a threshold comparison.
            json.dumps({"kiqs": {"planned": 10 ** 400, "followups": 0, "completed": 10 ** 399},
                        "core_actor_coverage": 10 ** 400, "min_core_coverage": 10 ** 400,
                        "citation_grounding": {"resolved_coverage": 10 ** 400},
                        "scenarios": [{"name": "Other", "probability": 10 ** 400}],
                        "selected_actor_count": 10 ** 400, "organic_action_count": 10 ** 400,
                        "seed_action_count": 1, "hard_passed": True}),
            # Finite floats whose sum overflows must not write an inf probability sum.
            json.dumps({"scenarios": [{"probability": 1e308}, {"name": "Other", "probability": 1e308}],
                        "kiqs": {"planned": 1, "followups": 0, "completed": 1,
                                 "facts": [], "verified": {}},
                        "status": "transport_failure", "markets": {}}),
            "DIRECTORY"]
_TARGETS = ["meta", "kiq", "markets", "ontology", "graph_prune", "actor_cast", "run_summary",
            "forecast", "final_audit", "run_manifest"]


def _target_path(pipeline, target):
    report_dir = po.ReportManager._get_report_folder(REPORT_ID)
    sim_dir = os.path.join(Config.OASIS_SIMULATION_DATA_DIR, SIM_ID)
    return {
        "meta": os.path.join(pipeline.handoff_dir, "meta.json"),
        "kiq": os.path.join(pipeline.handoff_dir, "v3", "kiq", "K1.json"),
        "markets": os.path.join(pipeline.handoff_dir, "prediction_markets.json"),
        "ontology": os.path.join(pipeline.handoff_dir, "ontology.json"),
        "graph_prune": os.path.join(pipeline.handoff_dir, "graph_prune.json"),
        "actor_cast": os.path.join(sim_dir, "actor_cast_manifest.json"),
        "run_summary": os.path.join(sim_dir, "run_summary.json"),
        "forecast": os.path.join(report_dir, "forecast.json"),
        "final_audit": os.path.join(report_dir, "final_audit.json"),
        "run_manifest": po.PipelineManager.manifest_path(pipeline.pipeline_id),
    }[target]


@pytest.mark.parametrize("target", _TARGETS)
@pytest.mark.parametrize("garbage", range(len(_GARBAGE)))
def test_builder_never_raises_parametrized_garbage(roots, target, garbage):
    pipeline = _make_pipeline()
    path = _target_path(pipeline, target)
    os.remove(path)
    content = _GARBAGE[garbage]
    if content == "DIRECTORY":
        os.makedirs(path)
    elif isinstance(content, bytes):
        with open(path, "wb") as handle:
            handle.write(content)
    else:
        _write(path, content)
    card = _score()
    assert list(card["stages"]) == list(sc.STAGES)
    json.dumps(card, allow_nan=False)
    for stage, check in card["checks"].items():
        assert check["passed"] in (True, False, None)
        for record in card["stages"][stage]["metrics"].values():
            assert record["status"] in {"measured", "not_applicable", "not_instrumented",
                                        "artifact_missing", "unreadable"}
            if record["status"] != "measured":
                assert record["value"] is None


@pytest.mark.parametrize("inputs", [None, [], "pipe_x", 7, {"paths": 5, "stage_status": "x"},
                                    {"mode": ["full"], "paths": {"research_meta": 3}},
                                    {"stage_status": {"research": 1}}])
def test_builder_never_raises_on_garbage_inputs(inputs):
    card = sc.build_stage_scorecard(inputs, thresholds=["not", "a", "mapping"])
    assert list(card["stages"]) == list(sc.STAGES)
    assert card["thresholds"] == sc.DEFAULT_THRESHOLDS
    json.dumps(card, allow_nan=False)


# ---------------------------------------------------------------- the _run hook
def _drive_run(monkeypatch, tmp_path, *, outcome, pid, flag=True, options=None,
               mode="research_only", overrides=None, probe=None, task_id=None):
    """Run the real ``_run`` with a faked research child.

    outcome: completed (research_only run finishes), failed (the research child
    raises) or cancelled (the research child is cancelled).  ``overrides``
    replaces further PipelineOrchestrator methods after the default stubs;
    ``probe`` is called when the research child starts (mid-attempt).
    """
    for name, value in {
        "UPLOAD_FOLDER": str(tmp_path / "uploads"),
        "RESEARCH_ENGINE": "v3",
        "RESEARCH_PARALLEL_TRACKS": 1,
        "DEERFLOW_RESEARCH_LANGUAGE": None,
        "REPORT_LINT": False,
        "CAST_RECONCILE": False,
        "EMBED_WARM_AT_RESEARCH": False,
        "PIPELINE_VIZ_ARTIFACTS": False,
        "STAGE_SCORECARD_ENABLED": flag,
    }.items():
        monkeypatch.setattr(Config, name, value, raising=False)
    for name, replacement in {
        "_start_heartbeat": lambda self, state: None,
        "_init_telemetry_flush": lambda self, state: None,
        "_write_run_manifest": lambda self, state: None,
        "_update_manifest": lambda self, state, stage, **kwargs: None,
        "_record_research_telemetry": lambda self, state, value: None,
        "_maybe_warm_embedder": lambda self, state, actors: None,
        "_surface_research_quality": lambda self, state, handoff_dir: {},
        "_surface_forecast_confidence_penalty": lambda self, state, handoff_dir: None,
        "_flush_run_telemetry": lambda self, state, **kwargs: None,
        **(overrides or {}),
    }.items():
        monkeypatch.setattr(po.PipelineOrchestrator, name, replacement)
    monkeypatch.setattr(po, "_finalize_research_contract", lambda handoff_dir, research: None)
    report = "# Research\n\n" + ("Capacity reached 176 GW in 2023 [S1]. " * 20) + "\n"

    def fake_research(prompt, handoff_dir, **kwargs):
        if probe is not None:
            probe()
        if outcome == "failed":
            raise RuntimeError("research child exploded")
        if outcome == "cancelled":
            raise po.PipelineCancelled("cancelled by the user")
        path = os.path.join(handoff_dir, "research_report.md")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(report)
        _write(os.path.join(handoff_dir, "meta.json"), V3_META)
        _write(os.path.join(handoff_dir, "prediction_markets.json"),
               {"markets": [], "no_relevant_markets": True,
                "status": {"attempted": True, "empty_reason": "no_equivalent_market"}})
        for kid, facts in KIQ_RECORDS.items():
            _write(os.path.join(handoff_dir, "v3", "kiq", f"{kid}.json"), {"facts": facts})
        return {"report": report, "report_path": path, "evidence_pack": None,
                "actor_dossier": "", "actors": None, "sources": None, "timeline": None,
                "exit_code": 0, "research_telemetry": {"tokens_in": 0, "tokens_out": 0}}

    monkeypatch.setattr(po.DeerFlowResearchRunner, "run", staticmethod(fake_research))
    po.PipelineManager.ensure_dirs(pid)
    state = po.PipelineState(pipeline_id=pid, prompt="Will capacity exceed 250 GW by 2027?",
                             mode=mode, status="running", task_id=task_id,
                             options=dict(options or {"research_language": None}))
    state.handoff_dir = po.PipelineManager.handoff_dir(pid)
    os.makedirs(state.handoff_dir, exist_ok=True)
    po.PipelineManager.save(state)  # start()/resume() persist the state before the thread runs
    po.PipelineOrchestrator._run(state)
    return state


@pytest.mark.parametrize("outcome,mode", [("completed", "research_only"), ("failed", "full"),
                                          ("cancelled", "full")])
def test_hook_writes_on_completed_failed_cancelled(roots, monkeypatch, outcome, mode):
    pid = f"pipe_eval15hook_{outcome}"
    state = _drive_run(monkeypatch, roots, outcome=outcome, pid=pid, mode=mode)
    assert state.status == outcome, state.error
    path = os.path.join(po.PipelineManager._dir(pid), "stage_scorecard.json")
    with open(path, encoding="utf-8") as handle:
        card = json.load(handle)
    assert list(card["stages"]) == list(sc.STAGES)
    assert card["identity"]["status"] == outcome and card["identity"]["scored_by"] == "pipeline"
    summary = sc.summarize_checks(card)
    assert state.options["stage_scorecard_summary"] == summary
    assert po.PipelineManager.load(pid)["options"]["stage_scorecard_summary"] == summary
    if outcome == "completed":
        assert summary["research"] is True
        assert all(card["stages"][s]["status"] == "not_applicable" for s in sc.STAGES[1:])
    else:
        assert card["stages"]["research"]["stage_status"] == outcome
        assert summary["research"] is False
        assert all(card["stages"][s]["status"] == "not_reached" for s in sc.STAGES[1:])


def test_flag_off_writes_nothing(roots, monkeypatch):
    health = {"status": "degraded", "issues": ["pre-existing"], "stages": {}}
    on = _drive_run(monkeypatch, roots, outcome="completed", pid="pipe_eval15on",
                    options={"research_language": None, "pipeline_health": dict(health)})
    off = _drive_run(monkeypatch, roots, outcome="completed", pid="pipe_eval15off", flag=False,
                     options={"research_language": None, "pipeline_health": dict(health)})
    assert not os.path.exists(os.path.join(po.PipelineManager._dir("pipe_eval15off"),
                                           "stage_scorecard.json"))
    assert "stage_scorecard_summary" not in off.options
    assert "stage_scorecard_summary" not in po.PipelineManager.load("pipe_eval15off")["options"]
    assert os.path.exists(os.path.join(po.PipelineManager._dir("pipe_eval15on"),
                                       "stage_scorecard.json"))
    # status and pipeline_health are identical with the flag on or off.
    assert on.status == off.status == "completed"
    assert on.options["pipeline_health"] == off.options["pipeline_health"] == health
    on_disk = po.PipelineManager.load("pipe_eval15on")
    off_disk = po.PipelineManager.load("pipe_eval15off")
    assert on_disk["status"] == off_disk["status"]
    assert on_disk["options"]["pipeline_health"] == off_disk["options"]["pipeline_health"]
    assert set(on_disk["options"]) - set(off_disk["options"]) == {"stage_scorecard_summary"}


def test_builder_exception_does_not_change_status(roots, monkeypatch):
    resets = []
    from app.utils import telemetry

    real_reset = telemetry.LLMMeter.reset
    monkeypatch.setattr(telemetry.LLMMeter, "reset",
                        classmethod(lambda cls, run_id=None: (resets.append(run_id),
                                                              real_reset(run_id))))

    def explode(*_args, **_kwargs):
        raise RuntimeError("scorecard exploded")

    monkeypatch.setattr(sc, "build_stage_scorecard", explode)
    stale = dict.fromkeys(sc.STAGES, True)
    # A previous attempt's sidecar is on disk: it must not pass for this attempt's.
    _write(sc.sidecar_path("pipe_eval15boom"), {"schema_version": sc.SCHEMA_VERSION,
                                                "identity": {"scored_by": "pipeline"}})
    state = _drive_run(monkeypatch, roots, outcome="completed", pid="pipe_eval15boom",
                       options={"research_language": None, "stage_scorecard_summary": stale})
    assert state.status == "completed" and state.error is None
    assert not os.path.exists(sc.sidecar_path("pipe_eval15boom"))
    # A previous attempt's summary never masquerades as this attempt's result.
    assert "stage_scorecard_summary" not in state.options
    persisted = po.PipelineManager.load("pipe_eval15boom")
    assert persisted["status"] == "completed"
    assert "stage_scorecard_summary" not in persisted["options"]
    assert resets == ["pipe_eval15boom"]  # the finally block still reset the meter


def test_failed_write_removes_previous_sidecar_and_summary(roots, monkeypatch):
    """The finally hook's failure branch: nothing from an earlier attempt survives."""
    monkeypatch.setattr(Config, "STAGE_SCORECARD_ENABLED", True, raising=False)
    state = _make_pipeline("pipe_eval15stale")
    sc.write_stage_scorecard(state.pipeline_id, state=state.to_dict())
    state.options["stage_scorecard_summary"] = dict.fromkeys(sc.STAGES, True)
    po.PipelineManager.save(state)

    def explode(*_args, **_kwargs):
        raise ValueError("Out of range float values are not JSON compliant")

    monkeypatch.setattr(sc, "build_stage_scorecard", explode)
    po.PipelineOrchestrator._write_stage_scorecard_sidecar(state)
    assert not os.path.exists(sc.sidecar_path(state.pipeline_id))
    assert "stage_scorecard_summary" not in state.options
    assert "stage_scorecard_summary" not in po.PipelineManager.load(state.pipeline_id)["options"]
    assert state.status == "completed"


@pytest.mark.parametrize("flag", [True, False], ids=["on", "off"])
def test_attempt_start_clears_previous_attempt_scorecard(roots, monkeypatch, flag):
    """A resumed attempt that later dies as an orphan (no finally block) must not keep the
    previous attempt's sidecar or summary; with the flag off both are left untouched."""
    pid = f"pipe_eval15attempt_{'on' if flag else 'off'}"
    previous = {"schema_version": sc.SCHEMA_VERSION,
                "identity": {"pipeline_id": pid, "scored_by": "pipeline", "status": "completed"}}
    _write(sc.sidecar_path(pid), previous)
    stale = dict.fromkeys(sc.STAGES, True)
    seen = {}

    def probe():
        seen["sidecar"] = os.path.exists(sc.sidecar_path(pid))
        seen["summary"] = "stage_scorecard_summary" in po.PipelineManager.load(pid)["options"]

    state = _drive_run(monkeypatch, roots, outcome="completed", pid=pid, flag=flag,
                       options={"research_language": None, "stage_scorecard_summary": stale},
                       probe=probe)
    assert state.status == "completed"
    with open(sc.sidecar_path(pid), encoding="utf-8") as handle:
        on_disk = json.load(handle)
    if flag:
        assert seen == {"sidecar": False, "summary": False}
        assert on_disk["identity"]["scored_by"] == "pipeline"
        assert state.options["stage_scorecard_summary"] == sc.summarize_checks(on_disk) != stale
    else:
        assert seen == {"sidecar": True, "summary": True}
        assert on_disk == previous
        assert state.options["stage_scorecard_summary"] == stale


def test_telemetry_failure_still_writes_fresh_scorecard(roots, monkeypatch):
    """The sidecar hook is a sibling of the telemetry block: a telemetry error never skips it."""
    def flush(self, state, *, final=False, extra=None):
        if final:
            raise RuntimeError("final telemetry flush exploded")

    stale = dict.fromkeys(sc.STAGES, True)
    pid = "pipe_eval15telboom"
    state = _drive_run(monkeypatch, roots, outcome="completed", pid=pid,
                       options={"research_language": None, "stage_scorecard_summary": stale},
                       overrides={"_flush_run_telemetry": flush})
    assert state.status == "completed" and state.error is None
    with open(sc.sidecar_path(pid), encoding="utf-8") as handle:
        card = json.load(handle)
    summary = sc.summarize_checks(card)
    assert summary == {"research": True, **dict.fromkeys(sc.STAGES[1:])}
    assert state.options["stage_scorecard_summary"] == summary != stale
    assert po.PipelineManager.load(pid)["options"]["stage_scorecard_summary"] == summary


def test_flag_on_off_identical_after_real_pipeline_health(roots, monkeypatch):
    """Full-mode terminal state with a really computed pipeline_health: the hook changes
    nothing but the sidecar and options.stage_scorecard_summary."""
    pid = "pipe_eval15health"
    _make_pipeline(pid, options={"graph_prune": {"kept": 9, "degraded": True,
                                                 "skipped_reason": "core coverage below 0.8"}})
    sim_dir = os.path.join(Config.OASIS_SIMULATION_DATA_DIR, SIM_ID)
    _write(os.path.join(sim_dir, "run_summary.json"), {
        "simulation_health": "llm_degraded", "organic_action_count": 30, "seed_action_count": 10,
        "rounds_with_organic_actions": 4, "rounds_executed": 5})
    base = po.PipelineState.from_dict(po.PipelineManager.load(pid))
    orch = po.PipelineOrchestrator()
    # The _run tail on a real assessment: the 9-byte fixture report hard-fails the
    # deliverable gate, so the run ends failed with the computed health block kept.
    with pytest.raises(RuntimeError, match="deliverable is broken"):
        orch._enforce_pipeline_health(base)
    base.status, base.error = "failed", "deliverable is broken"
    health = base.options["pipeline_health"]
    assert health["status"] == "failed"
    assert {stage: block["health"] for stage, block in health["stages"].items()} == {
        "report": "failed", "run": "degraded", "graph": "degraded"}
    po.PipelineManager.save(base)

    def finish(flag):
        monkeypatch.setattr(Config, "STAGE_SCORECARD_ENABLED", flag, raising=False)
        state = copy.deepcopy(base)
        orch._write_stage_scorecard_sidecar(state)
        return state

    off = finish(False)
    assert not os.path.exists(sc.sidecar_path(pid))
    on = finish(True)
    assert os.path.exists(sc.sidecar_path(pid))
    assert on.status == off.status == base.status
    assert on.options["pipeline_health"] == off.options["pipeline_health"] == health
    assert set(on.options) - set(off.options) == {"stage_scorecard_summary"}

    def comparable(state):
        data = state.to_dict()
        data.pop("updated_at")
        data["options"].pop("stage_scorecard_summary", None)
        return data

    assert comparable(on) == comparable(off) == comparable(base)
    on_disk = po.PipelineManager.load(pid)
    assert on_disk["status"] == base.status
    assert on_disk["options"]["pipeline_health"] == health


def test_report_folder_untouched(roots):
    state = _make_pipeline()
    report_dir = po.ReportManager._get_report_folder(REPORT_ID)

    def snapshot():
        out = {}
        for name in sorted(os.listdir(report_dir)):
            path = os.path.join(report_dir, name)
            with open(path, "rb") as handle:
                out[name] = (handle.read(), os.stat(path).st_mtime_ns)
        return out

    before = snapshot()
    card = sc.write_stage_scorecard(state.pipeline_id, state=state.to_dict())
    assert snapshot() == before
    path = sc.sidecar_path(state.pipeline_id)
    assert os.path.dirname(path) == po.PipelineManager._dir(state.pipeline_id)
    with open(path, encoding="utf-8") as handle:
        assert json.load(handle) == card
    assert card["identity"]["scored_by"] == "pipeline"


# ------------------------------------------------------------------------ CLI
def test_cli_score_runs_offline_and_reports_relaxed_gate(roots, monkeypatch, capsys):
    from app.utils import llm_client

    def refuse(*_args, **_kwargs):
        raise AssertionError("the offline scorer must not open a socket or build an LLM client")

    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(llm_client.LLMClient, "__init__", refuse)
    monkeypatch.setattr(Config, "REPORT_PUBLISH_GATE_MIN_COVERAGE", 0.05, raising=False)
    _make_pipeline(audit=_healthy_audit(coverage=0.07))
    assert cli.main(["score", "--pipeline", "pipe_eval15fixture"]) == 0
    card = json.loads(capsys.readouterr().out)
    assert card["runtime_gates"]["REPORT_PUBLISH_GATE_MIN_COVERAGE"]["relaxed"] is True
    assert card["checks"]["report"] == {"passed": False, "failed": ["citation_coverage"],
                                        "unevaluable": []}
    assert not os.path.exists(sc.sidecar_path("pipe_eval15fixture"))  # no -o: print only


def test_cli_backfill_all_terminal_pipelines(roots, capsys):
    _make_pipeline("pipe_eval15a")
    _make_pipeline("pipe_eval15b", status="failed", stage_status={
        "report": "failed"})
    _make_pipeline("pipe_eval15live", status="running", stage_status={"report": "running"})
    assert cli.main(["score", "--all", "-o"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert [row["pipeline_id"] for row in payload["pipelines"]] == ["pipe_eval15a", "pipe_eval15b"]
    assert payload["skipped"] == [{"pipeline_id": "pipe_eval15live", "reason": "status 'running'"}]
    assert payload["pipelines"][1]["failed"] == {"report": ["stage_status"]}
    for pid in ("pipe_eval15a", "pipe_eval15b"):
        with open(sc.sidecar_path(pid), encoding="utf-8") as handle:
            assert json.load(handle)["identity"]["scored_by"] == "backfill"
    assert not os.path.exists(sc.sidecar_path("pipe_eval15live"))


def test_cli_backfill_keeps_pipeline_authored_sidecar(roots, monkeypatch, capsys):
    """-o is a backfill: the run's own sidecar is the only record of its relaxed gate."""
    pid = "pipe_eval15authored"
    monkeypatch.setattr(Config, "REPORT_PUBLISH_GATE_MIN_COVERAGE", 0.05, raising=False)
    state = _make_pipeline(pid, audit=_healthy_audit(coverage=0.07))
    authored = sc.write_stage_scorecard(pid, state=state.to_dict())
    relaxed_gate = {"effective": 0.05, "suite_threshold": 0.75, "relaxed": True,
                    "source": "process_config"}
    assert authored["runtime_gates"]["REPORT_PUBLISH_GATE_MIN_COVERAGE"] == relaxed_gate
    with open(sc.sidecar_path(pid), "rb") as handle:
        original = handle.read()
    _make_pipeline("pipe_eval15orphan")
    # The .env pin is gone by the time the backfill runs.
    monkeypatch.setattr(Config, "REPORT_PUBLISH_GATE_MIN_COVERAGE", 0.75, raising=False)

    assert cli.main(["score", "--all", "-o"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert [row["pipeline_id"] for row in payload["pipelines"]] == ["pipe_eval15orphan"]
    assert payload["skipped"] == [{"pipeline_id": pid, "reason": "pipeline-authored sidecar"}]
    assert cli.main(["score", "--pipeline", pid, "-o"]) == 0
    captured = capsys.readouterr()
    assert json.loads(captured.out) == {"pipeline_id": pid, "skipped": "pipeline-authored sidecar"}
    assert "--force" in captured.err
    with open(sc.sidecar_path(pid), "rb") as handle:
        assert handle.read() == original
    # Printing without -o never writes, so it needs no protection.
    assert cli.main(["score", "--pipeline", pid]) == 0
    assert json.loads(capsys.readouterr().out)["identity"]["scored_by"] == "backfill"

    assert cli.main(["score", "--all", "--force"]) == 2  # --force needs -o
    capsys.readouterr()
    assert cli.main(["score", "--all", "-o", "--force"]) == 0
    capsys.readouterr()
    with open(sc.sidecar_path(pid), encoding="utf-8") as handle:
        forced = json.load(handle)
    assert forced["identity"]["scored_by"] == "backfill"
    assert forced["runtime_gates"]["REPORT_PUBLISH_GATE_MIN_COVERAGE"]["relaxed"] is False
    previous = forced["identity"]["previous"]
    assert previous == {"scored_by": "pipeline", "task_id": "task_eval15fixture",
                        "status": "completed", "runtime_gates": authored["runtime_gates"]}
    # A later plain backfill may rewrite a backfill sidecar but carries the evidence forward.
    assert cli.main(["score", "--all", "-o"]) == 0
    capsys.readouterr()
    with open(sc.sidecar_path(pid), encoding="utf-8") as handle:
        assert json.load(handle)["identity"]["previous"] == previous
    with open(sc.sidecar_path("pipe_eval15orphan"), encoding="utf-8") as handle:
        assert "previous" not in json.load(handle)["identity"]


@pytest.mark.parametrize("change", ["task", "status", "both"])
def test_cli_backfill_replaces_stale_pipeline_authored_sidecar(roots, capsys, change):
    """A pipeline-authored sidecar from an earlier attempt no longer describes the pipeline:
    -o rewrites it (no --force needed) and keeps the old record under identity.previous."""
    pid = "pipe_eval15stalecli"
    state = _make_pipeline(pid)
    authored = sc.write_stage_scorecard(pid, state=state.to_dict())
    if change in ("task", "both"):
        state.task_id = "task_eval15later"
    if change in ("status", "both"):
        state.status = "failed"
    po.PipelineManager.save(state)

    assert cli.main(["score", "--pipeline", pid, "-o"]) == 0
    row = json.loads(capsys.readouterr().out)
    assert row["written"] == sc.sidecar_path(pid) and row["status"] == state.status
    with open(sc.sidecar_path(pid), encoding="utf-8") as handle:
        rewritten = json.load(handle)
    identity = rewritten["identity"]
    assert identity["scored_by"] == "backfill"
    assert (identity["task_id"], identity["status"]) == (state.task_id, state.status)
    assert identity["previous"] == {"scored_by": "pipeline", "task_id": "task_eval15fixture",
                                    "status": "completed",
                                    "runtime_gates": authored["runtime_gates"]}


def test_flag_off_later_attempt_leaves_a_sidecar_the_backfill_replaces(roots, monkeypatch,
                                                                         capsys):
    """End to end on the real _run: the hook's sidecar is current for its own attempt; a later
    attempt with the flag off leaves it behind, and the backfill sees it is stale."""
    pid = "pipe_eval15attempts"
    _drive_run(monkeypatch, roots, outcome="completed", pid=pid, task_id="task_eval15a1")
    assert cli.main(["score", "--pipeline", pid, "-o"]) == 0
    assert json.loads(capsys.readouterr().out) == {"pipeline_id": pid,
                                                   "skipped": "pipeline-authored sidecar"}
    with open(sc.sidecar_path(pid), encoding="utf-8") as handle:
        first = json.load(handle)
    assert first["identity"]["task_id"] == "task_eval15a1"

    later = _drive_run(monkeypatch, roots, outcome="failed", pid=pid, mode="full", flag=False,
                       task_id="task_eval15a2")
    assert later.status == "failed"
    with open(sc.sidecar_path(pid), encoding="utf-8") as handle:
        assert json.load(handle) == first  # flag off: the old attempt's sidecar is untouched
    assert cli.main(["score", "--pipeline", pid, "-o"]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "failed"
    with open(sc.sidecar_path(pid), encoding="utf-8") as handle:
        identity = json.load(handle)["identity"]
    assert identity["scored_by"] == "backfill" and identity["task_id"] == "task_eval15a2"
    assert identity["previous"] == {"scored_by": "pipeline", "task_id": "task_eval15a1",
                                    "status": "completed", "runtime_gates": first["runtime_gates"]}


def test_cli_unserialisable_card_is_cannot_score(roots, monkeypatch, capsys):
    """Rendering sits inside the error handling: exit 1 with a message, never a traceback."""
    _make_pipeline()
    monkeypatch.setattr(sc, "build_stage_scorecard",
                        lambda inputs, thresholds=None: {"value": float("nan")})
    assert cli.main(["score", "--pipeline", "pipe_eval15fixture"]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "cannot score pipe_eval15fixture: ValueError" in captured.err


def test_cli_all_reports_corrupt_states_without_aborting(roots, capsys):
    _make_pipeline("pipe_eval15good")
    for pid, payload in {
        "pipe_eval15bad": json.dumps({"pipeline_id": "pipe_eval15bad", "status": "completed",
                                      "schema_version": 2, "stages": "not-a-mapping"}),
        "pipe_eval15ver": json.dumps({"status": "completed", "schema_version": [2]}),
        "pipe_eval15junk": "{not json",
    }.items():
        _write(po.PipelineManager.state_path(pid), payload)
    assert cli.main(["score", "--all", "-o"]) == 1
    result = json.loads(capsys.readouterr().out)
    assert [row["pipeline_id"] for row in result["pipelines"]] == ["pipe_eval15good"]
    assert [row["pipeline_id"] for row in result["errors"]] == ["pipe_eval15bad", "pipe_eval15ver"]
    assert "unreadable pipeline state" in result["errors"][0]["error"]
    assert result["skipped"] == [{"pipeline_id": "pipe_eval15junk",
                                  "reason": "no readable pipeline_state.json"}]
    assert os.path.exists(sc.sidecar_path("pipe_eval15good"))
    assert not os.path.exists(sc.sidecar_path("pipe_eval15bad"))
    assert cli.main(["score", "--pipeline", "pipe_eval15bad"]) == 1
    assert "unreadable pipeline state" in capsys.readouterr().err


def test_cli_thresholds_file_and_errors(roots, tmp_path, capsys):
    _make_pipeline(forecast=_healthy_forecast(n_binaries=9))
    good = tmp_path / "thresholds.json"
    good.write_text(json.dumps({"min_binaries": 9}), encoding="utf-8")
    assert cli.main(["score", "--pipeline", "pipe_eval15fixture", "--thresholds", str(good)]) == 0
    card = json.loads(capsys.readouterr().out)
    assert card["thresholds"]["min_binaries"] == 9 and card["checks"]["report"]["passed"] is True
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"min_binaries": 9, "typo_key": 1}), encoding="utf-8")
    assert cli.main(["score", "--pipeline", "pipe_eval15fixture", "--thresholds", str(bad)]) == 2
    assert "typo_key" in capsys.readouterr().err
    with pytest.raises(ValueError):
        sc.load_thresholds(str(bad))
    with pytest.raises(OSError):
        sc.load_thresholds(str(tmp_path / "absent.json"))
    assert cli.main(["score", "--pipeline", "pipe_does_not_exist"]) == 1
    assert "pipeline not found" in capsys.readouterr().err


# ----------------------------------------------------------------------- knob
def test_stage_scorecard_knob_default_on_and_documented():
    assert Config.STAGE_SCORECARD_ENABLED is True
    with open(os.path.join(_REPO_ROOT, ".env.example"), encoding="utf-8") as handle:
        assert re.search(r"^#?\s*STAGE_SCORECARD_ENABLED=true\b", handle.read(), re.M)
