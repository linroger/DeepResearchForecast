"""EVAL-18: slim cost card, config fingerprint / ledger config_hash, compute-matched norm.

Offline and deterministic: every pipeline lives under tmp_path (the pipelines /
simulations / reports roots are pointed there), the research child of the ``_run``
tests is faked and meters a synthetic call, and no network or LLM is touched.
"""

from __future__ import annotations

import copy
import json
import os
import re
import socket
from types import SimpleNamespace

import pytest

from app.config import Config
from app.services import ledger_commit as lc
from app.services import pipeline_orchestrator as po
from app.services import run_shape
from app.services.report_agent import Report, ReportManager, ReportStatus
from app.utils import cost_accounting as ca
from app.utils.security import redact_secrets
from app.utils.telemetry import LLMMeter
from scripts import cost_card as cli
from tests.test_forecast_ledger_commit import QUESTION, _Agent, _forecast, _publish, _rows, \
    _write_report

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_HASH_RE = re.compile(r"\Asha256:[0-9a-f]{64}\Z")
_CFG = SimpleNamespace(FORECAST_ENSEMBLE_MODELS="", FORECAST_MARKET_ANCHORING=True,
                       PREDICTION_MARKETS_ENABLED=True)


# --------------------------------------------------------------------- fixtures
def _counter(calls, tok_in, tok_out, usd=0.0, cache_read=0):
    return {"calls": calls, "cached": 0, "prompt_tokens": tok_in, "completion_tokens": tok_out,
            "total_tokens": tok_in + tok_out, "latency_ms": 10.0 * calls, "cost_usd": usd,
            "prompt_cache_read_tokens": cache_read}


def _telemetry(**over):
    by_stage = {
        "research": _counter(4, 10_000, 2_000, 0.1, cache_read=6_000),
        "ontology": _counter(1, 500, 100, 0.2),
        "graph": _counter(30, 40_000, 5_000, 0.3),
        "run": _counter(12, 9_000, 1_500, 0.05),
        "report": _counter(20, 60_000, 15_000, 0.7),
        "_unstaged": _counter(1, 10, 5, 0.000001),
    }
    tel = {
        "run_id": "pipe_eval18unit", "pipeline_id": "pipe_eval18unit", "status": "completed",
        "total": _counter(68, 119_510, 23_605, 1.350001),
        "by_stage": by_stage,
        "by_model": {"glm:glm-5": _counter(64, 110_000, 22_000),
                     "claude-cli:claude": _counter(4, 9_510, 1_605)},
        "cost_estimated": False, "cost_basis": "mixed",
        "fallback_attributed": _counter(0, 0, 0),
        "unattributed_process": _counter(3, 300, 30),
    }
    tel.update(over)
    return tel


WALLS = {"research": 300.04, "ontology": 12.0, "graph": 1_800.26, "prepare": 95.5,
         "run": 600.0, "report": 900.11}
STAGE_STATUS = dict.fromkeys(("research", "ontology", "graph", "prepare", "run", "report"),
                             "completed")


def _options(**over):
    opts = {
        "max_rounds": 9, "research_language": "English",
        "safety_policy_v1": {"version": "safety-policy/v1", "origin": "admission",
                             "pinned_at": "2026-09-30T00:00:00+00:00",
                             "n_forecast_seeds": 1, "report_spine_selfconsistency_k": 1,
                             "ensemble_extremize_a": 1.0,
                             "simulation_forecast_effect": "diagnostic_only"},
        "run_shape_v1": {"version": "run-shape/v1", "sha256": "a" * 64,
                         "provenance": {"research_engine": "v3"}},
        "stage_reuse_v1": [{"stage": s, "reused": False, "at": "t"}
                           for s in ("research", "ontology", "graph", "prepare", "run", "report")],
    }
    opts.update(over)
    return opts


MANIFEST = {"repo_git_sha": "abc123",
            "resolved": {"research": {"model": "glm", "depth": "deep"},
                         "ontology": {"provider": "glm", "model_name": "glm-5"},
                         "graph": {"provider": "glm", "model_name": "glm-5-air"},
                         "report": {"provider": "glm", "model_name": "glm-5"}}}


def _card(tel=None, *, options=None, walls=None, stage_status=None, baseline=3, manifest=None):
    return ca.build_cost_card(
        pipeline_id="pipe_eval18unit", mode="full", status="completed",
        run_telemetry=_telemetry() if tel is None else tel,
        stage_walls=WALLS if walls is None else walls,
        run_manifest=MANIFEST if manifest is None else manifest,
        options=_options() if options is None else options,
        stage_status=STAGE_STATUS if stage_status is None else stage_status,
        unattributed_calls_at_start=baseline, created_at="2026-09-30T00:00:00+00:00",
        config=_CFG)


def _all_keys(obj):
    if isinstance(obj, dict):
        for key, value in obj.items():
            yield key
            yield from _all_keys(value)
    elif isinstance(obj, list):
        for value in obj:
            yield from _all_keys(value)


@pytest.fixture
def roots(tmp_path, monkeypatch):
    """Point every artifact root DRF resolves at tmp_path; the cost card on."""
    sims = str(tmp_path / "simulations")
    monkeypatch.setattr(Config, "UPLOAD_FOLDER", str(tmp_path / "uploads"), raising=False)
    monkeypatch.setattr(Config, "PIPELINE_DATA_DIR", str(tmp_path / "pipelines"), raising=False)
    monkeypatch.setattr(Config, "OASIS_SIMULATION_DATA_DIR", sims, raising=False)
    monkeypatch.setattr(po.SimulationRunner, "RUN_STATE_DIR", sims, raising=False)
    monkeypatch.setattr(ReportManager, "REPORTS_DIR", str(tmp_path / "reports"), raising=False)
    monkeypatch.setattr(Config, "COST_CARD_ENABLED", True, raising=False)
    monkeypatch.setattr(Config, "REPORT_FORECAST_LEDGER", True, raising=False)
    monkeypatch.setattr(Config, "FORECAST_LEDGER_COMMIT_MODE", "published", raising=False)
    monkeypatch.setattr(Config, "FORECAST_LEDGER_RECORD_UNPUBLISHED", True, raising=False)
    monkeypatch.setattr(po, "_repo_git_sha", lambda: "gitsha")
    monkeypatch.setattr(po, "_deerflow_ref", lambda: None)
    return tmp_path


# ------------------------------------------------------------ card arithmetic
def test_totals_equal_sum_of_stages():
    card = _card()
    assert card["schema"] == ca.COST_CARD_SCHEMA == "drf-cost-card/v1"
    stages = card["stages"]
    # Pipeline order first, unknown stages after; prepare has a wall but no metered call.
    assert list(stages) == ["research", "ontology", "graph", "prepare", "run", "report",
                            "_unstaged"]
    for field in ca.STAGE_FIELDS:
        total = sum(row[field] for row in stages.values())
        if isinstance(total, int):
            assert card["totals"][field] == total, field
        else:
            assert card["totals"][field] == pytest.approx(total, abs=1e-6), field
    for row in stages.values():
        assert row["tok_total"] == row["tok_in"] + row["tok_out"]
    assert card["totals"]["calls"] == 68 and card["totals"]["tok_total"] == 143_115
    assert card["totals"]["usd"] == pytest.approx(1.350001)
    assert card["totals"]["wall_s"] == pytest.approx(3707.9)
    assert stages["prepare"] == {"calls": 0, "tok_in": 0, "tok_in_cache_read": 0, "tok_out": 0,
                                 "tok_total": 0, "wall_s": 95.5, "usd": 0.0, "cost_basis": None}
    assert stages["report"]["cost_basis"] == card["totals"]["cost_basis"] == "mixed"
    # Tokens, calls and wall first; USD second.
    assert list(stages["report"]) == ["calls", "tok_in", "tok_in_cache_read", "tok_out",
                                      "tok_total", "wall_s", "usd", "cost_basis"]
    assert card["research_cache_hit_ratio"] == 0.6
    assert card["repo_git_sha"] == "abc123" and card["attempts"] == {
        "scope": "cumulative", "resumed": False}
    assert card["completeness"] == {"complete": True, "reasons": [],
                                    "estimated_cost_share": 0.0}
    json.dumps(card, allow_nan=False)


def test_stage_numbers_come_from_cumulative_by_stage():
    """EVAL-17: a resumed run's cumulative_by_stage beats the last attempt's by_stage."""
    tel = _telemetry(previous_attempt={"total": _counter(40, 1, 1)},
                     cumulative_by_stage={"research": _counter(9, 20_000, 4_000, 0.2, 5_000),
                                          "report": _counter(41, 120_000, 30_000, 1.4),
                                          "run": _counter(12, 9_000, 1_500)})
    card = _card(tel)
    assert card["attempts"] == {"scope": "cumulative", "resumed": True}
    assert card["stages"]["research"]["calls"] == 9
    assert card["stages"]["report"]["tok_total"] == 150_000
    assert card["stages"]["graph"]["calls"] == 0          # absent from the cumulative map
    assert card["research_cache_hit_ratio"] == 0.25
    assert card["completeness"]["complete"] is True


def test_malformed_inputs_never_raise():
    card = ca.build_cost_card(pipeline_id="pipe_x", mode=None, run_telemetry="garbage",
                              stage_walls={"run": float("nan"), "report": -3, "graph": "x"},
                              run_manifest=[1], options=None, config=_CFG)
    assert card["totals"]["calls"] == 0 and card["totals"]["wall_s"] == 0.0
    assert card["config"]["source"] == ca.CONFIG_SOURCE_RECOMPUTED
    assert card["completeness"]["reasons"] == ["run_telemetry_missing"]
    json.dumps(card, allow_nan=False)
    bad = _telemetry(by_stage={"report": {"calls": "many", "prompt_tokens": float("inf"),
                                          "completion_tokens": None, "cost_usd": "nan"}})
    row = _card(bad)["stages"]["report"]
    assert (row["calls"], row["tok_in"], row["tok_out"], row["usd"]) == (0, 0, 0, 0.0)


# ------------------------------------------------------------ completeness
def test_completeness_reasons():
    # RUN completed with a simulation but no metered call.
    tel = _telemetry()
    del tel["by_stage"]["run"]
    assert _card(tel)["completeness"]["reasons"] == ["unmetered_stage:run"]
    # A reused stage (INFRA-7 decision reused=True) spent nothing legitimately.
    reused = _options(stage_reuse_v1=[{"stage": "run", "reused": True}])
    assert _card(tel, options=reused)["completeness"]["complete"] is True
    # Without INFRA-7 decisions a completed stage counts as executed.
    no_decisions = _options(stage_reuse_v1=None)
    assert _card(tel, options=no_decisions)["completeness"]["reasons"] == ["unmetered_stage:run"]
    # Seeds > 1 whose ensemble ran without any metered seed simulation.
    seeds = _options(ensemble_wall={"started_at": "t0", "finished_at": "t1"})
    seeds["safety_policy_v1"]["n_forecast_seeds"] = 3
    assert _card(options=seeds)["completeness"]["reasons"] == [
        "seeds_without_ensemble_sim:n_forecast_seeds=3"]
    metered = _telemetry()
    metered["by_stage"]["ensemble_sim"] = _counter(5, 10, 10)
    assert _card(metered, options=seeds)["completeness"]["complete"] is True
    not_entered = _options()
    not_entered["safety_policy_v1"]["n_forecast_seeds"] = 3
    assert _card(options=not_entered)["completeness"]["complete"] is True
    # A resumed run without cumulative_by_stage: only the latest attempt is covered, and the
    # zero-call check is skipped (earlier attempts' calls are simply not in by_stage).
    last = _telemetry(previous_attempt={"total": _counter(1, 1, 1)})
    del last["by_stage"]["run"]
    card = _card(last)
    assert card["attempts"] == {"scope": "last_attempt_only", "resumed": True}
    assert card["completeness"] == {"complete": False, "reasons": ["last_attempt_only"],
                                    "estimated_cost_share": 0.0}
    # Unattributed process-wide spend that grew during the attempt / an unknown baseline.
    assert _card(baseline=1)["completeness"]["reasons"] == ["unattributed_process_growth:+2"]
    assert _card(baseline=None)["completeness"]["reasons"] == [
        "unattributed_process_unknown_baseline:3"]
    assert _card(_telemetry(unattributed_process=_counter(0, 0, 0)),
                 baseline=None)["completeness"]["complete"] is True
    # More than 20% of the volume priced at an estimated / unknown rate.
    proxied = _telemetry(by_model={"proxy:gemini-pro": _counter(1, 300, 0),
                                   "glm:glm-5": _counter(1, 700, 0)})
    assert _card(proxied)["completeness"]["reasons"] == ["estimated_cost_share:0.3"]
    # The final flush never landed / no telemetry at all / a partial legacy split.
    assert _card(_telemetry(in_flight=True))["completeness"]["reasons"] == [
        "run_telemetry_in_flight"]
    partial = _telemetry(cumulative_by_stage=_telemetry()["by_stage"],
                         cumulative_by_stage_partial=True)
    assert _card(partial)["completeness"]["reasons"] == ["cumulative_by_stage_partial"]


def test_missing_run_telemetry_is_incomplete():
    card = ca.build_cost_card(pipeline_id="pipe_x", mode="full", run_telemetry=None,
                              stage_walls=WALLS, run_manifest=MANIFEST, options=_options(),
                              stage_status=STAGE_STATUS, config=_CFG)
    assert card["completeness"]["reasons"] == [
        "run_telemetry_missing", "unmetered_stage:research", "unmetered_stage:run",
        "unmetered_stage:report"]
    assert card["unattributed_process"] == {"calls_at_attempt_start": None, "calls_at_end": None}


def test_no_key_contains_token():
    options = _options(base_pipeline_id="pipe_base", ensemble_wall={"started_at": "t"})
    options["safety_policy_v1"]["n_forecast_seeds"] = 2
    options[ca.CONFIG_HASH_OPTION] = ca.config_hash_record(
        options, MANIFEST, report_producer={"provider": "glm", "model_name": "glm-5"},
        config=_CFG)
    tel = _telemetry(previous_attempt={"total": _counter(1, 1, 1)},
                     by_model={"proxy:x": _counter(1, 900, 0), "glm:y": _counter(1, 100, 0)},
                     in_flight=True)
    card = _card(tel, options=options, baseline=0)
    assert len(card["completeness"]["reasons"]) >= 4
    assert card["lineage"] == {"base_pipeline_id": "pipe_base"}
    keys = list(_all_keys(card))
    assert keys and not [key for key in keys if "token" in key.lower()]
    assert redact_secrets(card) == card
    assert redact_secrets(options[ca.CONFIG_HASH_OPTION]) == options[ca.CONFIG_HASH_OPTION]


# ------------------------------------------------------------ config hash
def test_config_hash_order_invariant_and_changes_with_pinned_seeds(monkeypatch):
    producer = {"provider": "glm", "model_name": "glm-5"}
    base = ca.config_hash_record(_options(), MANIFEST, report_producer=producer, config=_CFG)
    assert _HASH_RE.fullmatch(base["config_hash"])
    assert base["config_hash"] == ca.config_hash(base["fingerprint"])
    # Key order is irrelevant (canonical JSON).
    reordered_opts = dict(reversed(list(_options().items())))
    reordered_manifest = {"resolved": dict(reversed(list(MANIFEST["resolved"].items()))),
                          "repo_git_sha": "other"}
    same = ca.config_hash_record(reordered_opts, reordered_manifest,
                                 report_producer=dict(reversed(list(producer.items()))),
                                 config=_CFG)
    assert same == base
    # A pinned seed count is part of the configuration...
    seeds = _options()
    seeds["safety_policy_v1"]["n_forecast_seeds"] = 3
    assert ca.config_hash_record(seeds, MANIFEST, report_producer=producer,
                                 config=_CFG)["config_hash"] != base["config_hash"]
    # ...the ambient knob is not re-read, nor is provenance (origin / pinned_at).
    monkeypatch.setattr(Config, "N_FORECAST_SEEDS", 7, raising=False)
    stamped = _options()
    stamped["safety_policy_v1"].update(origin="resume_reconstructed_safe", pinned_at="later")
    assert ca.config_hash_record(stamped, MANIFEST, report_producer=producer,
                                 config=_CFG) == base
    # run.json's report stamp is never read: INFRA-7 restamps it only at stage completion.
    restamped = copy.deepcopy(MANIFEST)
    restamped["resolved"]["report"] = {"provider": "other", "model_name": "other-model"}
    assert ca.config_hash_record(_options(), restamped, report_producer=producer,
                                 config=_CFG) == base
    # The report's own producer, the run shape and the forecast knobs are.
    for changed in (
        ca.config_hash_record(_options(), MANIFEST, config=_CFG),
        ca.config_hash_record(_options(run_shape_v1={"sha256": "b" * 64}), MANIFEST,
                              report_producer=producer, config=_CFG),
        ca.config_hash_record(_options(), MANIFEST, report_producer=producer,
                              config=SimpleNamespace(**{**vars(_CFG),
                                                        "FORECAST_MARKET_ANCHORING": False})),
    ):
        assert changed["config_hash"] != base["config_hash"]
    fp = base["fingerprint"]
    assert fp["research"] == {"model": "glm", "depth": "deep", "engine": "v3"}
    assert fp["report"] == producer and fp["graph"]["model_name"] == "glm-5-air"
    assert fp["options"] == {"max_rounds": 9, "research_language": "English"}
    assert fp["forecast"] == {"ensemble_models": "", "market_anchoring": True,
                              "prediction_markets_enabled": True}


def test_card_reuses_the_report_stage_pin_else_recomputes():
    options = _options()
    options[ca.CONFIG_HASH_OPTION] = ca.config_hash_record(
        options, MANIFEST, report_producer={"provider": "glm", "model_name": "glm-5"},
        config=_CFG)
    pinned = _card(options=options)
    assert pinned["config"]["source"] == ca.CONFIG_SOURCE_PINNED == "report_stage"
    assert pinned["config_hash"] == options[ca.CONFIG_HASH_OPTION]["config_hash"]
    assert pinned["config"]["fingerprint"] == options[ca.CONFIG_HASH_OPTION]["fingerprint"]
    assert pinned["config"]["fingerprint"] is not options[ca.CONFIG_HASH_OPTION]["fingerprint"]
    # A run that ended before the report stage: recomputed without a report producer.
    recomputed = _card()
    assert recomputed["config"]["source"] == ca.CONFIG_SOURCE_RECOMPUTED == "recomputed"
    assert recomputed["config"]["fingerprint"]["report"] == {"provider": None,
                                                             "model_name": None}
    assert recomputed["config_hash"] == ca.config_hash(recomputed["config"]["fingerprint"])
    # A damaged pin is neither stamped nor reused.
    damaged = copy.deepcopy(options)
    damaged[ca.CONFIG_HASH_OPTION]["fingerprint"]["options"]["max_rounds"] = 99
    assert ca.pinned_config_hash(damaged) is None
    assert _card(options=damaged)["config"]["source"] == "recomputed"
    for junk in (None, {}, {ca.CONFIG_HASH_OPTION: "x"},
                 {ca.CONFIG_HASH_OPTION: {"config_hash": 1, "fingerprint": {}}}):
        assert ca.pinned_config_hash(junk) is None


# ------------------------------------------------------------ compute-matched norm
def test_compute_matched_tolerance():
    def card(report_tok, **stages):
        rows = {"report": {"tok_total": report_tok}} if report_tok is not None else {}
        rows.update({name: {"tok_total": tok} for name, tok in stages.items()})
        return {"schema": ca.COST_CARD_SCHEMA, "stages": rows}

    control = card(1000)
    assert ca.compute_matched(card(1150), control, "report") == {
        "matched": True, "variant_tok": 1150, "control_tok": 1000, "rel_gap": 0.15}
    assert ca.compute_matched(card(1151), control, "report")["matched"] is False
    assert ca.compute_matched(card(850), control, "report") == {
        "matched": True, "variant_tok": 850, "control_tok": 1000, "rel_gap": -0.15}
    assert ca.compute_matched(card(849), control, "report")["matched"] is False
    assert ca.compute_matched(card(1250), control, "report", tol=0.3)["matched"] is True
    assert ca.compute_matched(card(1001), control, "report", tol=0)["matched"] is False
    # Stage-level: other stages' spend never enters the comparison; a missing stage spent 0.
    assert ca.compute_matched(card(1000, graph=10), card(1000, graph=99_999), "report")[
        "matched"] is True
    assert ca.compute_matched(card(None), card(None), "report") == {
        "matched": True, "variant_tok": 0, "control_tok": 0, "rel_gap": 0.0}
    assert ca.compute_matched(card(10), card(None), "report") == {
        "matched": False, "variant_tok": 10, "control_tok": 0, "rel_gap": None}
    real = _card()
    assert ca.compute_matched(real, real, "report")["matched"] is True
    for bad_tol in (-0.1, float("nan"), float("inf"), "x"):
        with pytest.raises(ValueError):
            ca.compute_matched(control, control, "report", tol=bad_tol)
    with pytest.raises(ValueError, match="variant_card"):
        ca.compute_matched({"stages": {}}, control, "report")
    with pytest.raises(ValueError, match="control_card"):
        ca.compute_matched(control, None, "report")
    assert "compute_matched" in (ca.__doc__ or "") and "A/B" in (ca.__doc__ or "")


# ------------------------------------------------------------ the _run hook
def _drive_run(monkeypatch, tmp_path, *, pid, flag=True, outcome="completed",
               unattributed_mid_run=0):
    """Run the real ``_run`` (research_only) with a faked research child that meters one
    research call; telemetry flushes and run.json are real."""
    for name, value in {
        "RESEARCH_ENGINE": "v3",
        "RESEARCH_PARALLEL_TRACKS": 1,
        "DEERFLOW_RESEARCH_LANGUAGE": None,
        "REPORT_LINT": False,
        "CAST_RECONCILE": False,
        "EMBED_WARM_AT_RESEARCH": False,
        "PIPELINE_VIZ_ARTIFACTS": False,
        "STAGE_SCORECARD_ENABLED": False,
        "COST_CARD_ENABLED": flag,
    }.items():
        monkeypatch.setattr(Config, name, value, raising=False)
    for name, replacement in {
        "_start_heartbeat": lambda self, state: None,
        "_record_research_telemetry": lambda self, state, value: None,
        "_maybe_warm_embedder": lambda self, state, actors: None,
        "_surface_research_quality": lambda self, state, handoff_dir: {},
        "_surface_forecast_confidence_penalty": lambda self, state, handoff_dir: None,
    }.items():
        monkeypatch.setattr(po.PipelineOrchestrator, name, replacement)
    monkeypatch.setattr(po, "_finalize_research_contract", lambda handoff_dir, research: None)
    report = "# Research\n\n" + ("Capacity reached 176 GW in 2023 [S1]. " * 20) + "\n"

    def fake_research(prompt, handoff_dir, **kwargs):
        LLMMeter.record("glm", "glm-5", 1_200, 300, 50.0, stage="research", run_id=pid,
                        prompt_cache_read_tokens=400)
        for _ in range(unattributed_mid_run):
            LLMMeter.record("glm", "glm-5", 10, 1, 1.0, run_id="_global")
        if outcome == "failed":
            raise RuntimeError("research child exploded")
        if outcome == "cancelled":
            raise po.PipelineCancelled("cancelled by the user")
        path = os.path.join(handoff_dir, "research_report.md")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(report)
        return {"report": report, "report_path": path, "evidence_pack": None,
                "actor_dossier": "", "actors": None, "sources": None, "timeline": None,
                "exit_code": 0, "research_telemetry": {"tokens_in": 0, "tokens_out": 0}}

    monkeypatch.setattr(po.DeerFlowResearchRunner, "run", staticmethod(fake_research))
    po.PipelineManager.ensure_dirs(pid)
    loaded = po.PipelineManager.load(pid)
    state = (po.PipelineState.from_dict(loaded) if loaded else
             po.PipelineState(pipeline_id=pid, prompt="Will capacity exceed 250 GW by 2027?",
                              mode="research_only", options={"research_language": None}))
    state.status = "running"
    state.stages = {}
    state.handoff_dir = po.PipelineManager.handoff_dir(pid)
    os.makedirs(state.handoff_dir, exist_ok=True)
    po.PipelineManager.save(state)
    po.PipelineOrchestrator._run(state)
    return state


def _cost_cards(root):
    return sorted(os.path.join(dirpath, name) for dirpath, _dirs, files in os.walk(root)
                  for name in files if name == ca.COST_CARD_FILENAME)


def _load(path):
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


@pytest.mark.parametrize("outcome", ["completed", "failed", "cancelled"])
def test_hook_writes_pipeline_dir_only(roots, monkeypatch, outcome):
    pid = f"pipe_eval18hook_{outcome}"
    state = _drive_run(monkeypatch, roots, pid=pid, outcome=outcome, unattributed_mid_run=2)
    assert state.status == outcome, state.error
    path = os.path.join(po.PipelineManager._dir(pid), ca.COST_CARD_FILENAME)
    assert _cost_cards(roots) == [path]            # the pipeline dir, nowhere else
    card = _load(path)
    assert card["schema"] == "drf-cost-card/v1" and card["status"] == outcome
    assert (card["pipeline_id"], card["mode"], card["repo_git_sha"]) == (
        pid, "research_only", "gitsha")
    research = card["stages"]["research"]
    assert (research["calls"], research["tok_in"], research["tok_out"],
            research["tok_in_cache_read"]) == (1, 1_200, 300, 400)
    assert card["research_cache_hit_ratio"] == 0.3333
    for field in ca.STAGE_FIELDS:
        assert card["totals"][field] == pytest.approx(
            sum(row[field] for row in card["stages"].values()))
    # No report stage ran: the config is recomputed, never a report producer.
    assert card["config"]["source"] == "recomputed"
    assert card["config"]["fingerprint"]["report"] == {"provider": None, "model_name": None}
    assert "unattributed_process_growth:+2" in card["completeness"]["reasons"]
    assert redact_secrets(card) == card
    assert state.artifacts["cost_card"] == path
    assert po.PipelineManager.load(pid)["artifacts"]["cost_card"] == path


def test_hook_card_is_cumulative_across_attempts(roots, monkeypatch):
    pid = "pipe_eval18attempts"
    _drive_run(monkeypatch, roots, pid=pid, outcome="failed")
    state = _drive_run(monkeypatch, roots, pid=pid)
    assert state.status == "completed"
    card = _load(os.path.join(po.PipelineManager._dir(pid), ca.COST_CARD_FILENAME))
    assert card["attempts"] == {"scope": "cumulative", "resumed": True}
    assert card["stages"]["research"]["calls"] == 2
    assert card["stages"]["research"]["tok_total"] == 3_000
    assert card["completeness"]["complete"] is True, card["completeness"]


def test_flag_off_no_file(roots, monkeypatch):
    on = _drive_run(monkeypatch, roots, pid="pipe_eval18on")
    off = _drive_run(monkeypatch, roots, pid="pipe_eval18off", flag=False)
    assert on.status == off.status == "completed"
    on_dir, off_dir = po.PipelineManager._dir("pipe_eval18on"), po.PipelineManager._dir(
        "pipe_eval18off")
    assert _cost_cards(roots) == [os.path.join(on_dir, ca.COST_CARD_FILENAME)]
    assert set(os.listdir(on_dir)) - set(os.listdir(off_dir)) == {ca.COST_CARD_FILENAME}
    assert set(os.listdir(off_dir)) <= set(os.listdir(on_dir))
    off_disk, on_disk = po.PipelineManager.load("pipe_eval18off"), po.PipelineManager.load(
        "pipe_eval18on")
    assert "cost_card" not in off.artifacts and "cost_card" not in off_disk["artifacts"]
    assert set(on_disk["artifacts"]) - set(off_disk["artifacts"]) == {"cost_card"}
    assert set(on_disk["options"]) == set(off_disk["options"])
    assert ca.CONFIG_HASH_OPTION not in off_disk["options"]

    def normalized(pid):
        with open(os.path.join(po.PipelineManager._dir(pid), "run_telemetry.json"),
                  encoding="utf-8") as handle:
            return json.loads(handle.read().replace(pid, "PID"))

    assert normalized("pipe_eval18on") == normalized("pipe_eval18off")


def test_flag_off_hook_is_byte_identical(roots, monkeypatch):
    state = _drive_run(monkeypatch, roots, pid="pipe_eval18offhook", flag=False)
    pdir = po.PipelineManager._dir(state.pipeline_id)

    def snapshot():
        out = {}
        for name in sorted(os.listdir(pdir)):
            path = os.path.join(pdir, name)
            if os.path.isfile(path):
                with open(path, "rb") as handle:
                    out[name] = (handle.read(), os.stat(path).st_mtime_ns)
        return out

    before, state_before = snapshot(), copy.deepcopy(state.to_dict())
    orch = po.PipelineOrchestrator()
    orch._capture_unattributed_baseline(state)
    orch._write_cost_card(state)
    po.PipelineOrchestrator._pin_config_hash(state, report_producer={"provider": "p"})
    assert orch._unattributed_calls_at_start is None
    assert snapshot() == before and state.to_dict() == state_before


def test_write_failure_removes_stale_card_and_keeps_status(roots, monkeypatch):
    pid = "pipe_eval18boom"
    first = _drive_run(monkeypatch, roots, pid=pid)
    assert first.artifacts["cost_card"]

    def explode(*_args, **_kwargs):
        raise RuntimeError("cost card exploded")

    monkeypatch.setattr(ca, "build_cost_card", explode)
    resets = []
    real_reset = LLMMeter.reset
    monkeypatch.setattr(LLMMeter, "reset", classmethod(
        lambda cls, run_id=None: (resets.append(run_id), real_reset(run_id))))
    state = _drive_run(monkeypatch, roots, pid=pid)
    assert state.status == "completed" and state.error is None
    assert _cost_cards(roots) == []                 # the previous attempt's card is gone
    assert "cost_card" not in state.artifacts
    assert "cost_card" not in po.PipelineManager.load(pid)["artifacts"]
    assert resets == [pid]                          # the finally block still reset the meter


def test_telemetry_failure_still_writes_the_card(roots, monkeypatch):
    def flush(self, state, *, final=False, extra=None):
        if final:
            raise RuntimeError("final telemetry flush exploded")

    monkeypatch.setattr(po.PipelineOrchestrator, "_flush_run_telemetry", flush)
    state = _drive_run(monkeypatch, roots, pid="pipe_eval18telboom")
    assert state.status == "completed"
    card = _load(os.path.join(po.PipelineManager._dir(state.pipeline_id),
                              ca.COST_CARD_FILENAME))
    assert "run_telemetry_missing" in card["completeness"]["reasons"]


# ------------------------------------------------------------ ledger stamp
class _PublishingAgent(_Agent):
    """A ReportAgent stand-in whose generate_report seals a bundle and runs the real
    post-publication ledger step with the context the orchestrator gave it."""

    def __init__(self, **over):
        super().__init__(**over)
        self.ledger_receipt = None

    def generate_report(self, progress_callback=None, report_id=None):
        _write_report(report_id, _forecast())
        self.ledger_receipt = _publish(self, report_id)
        return SimpleNamespace(report_id=report_id, status=ReportStatus.COMPLETED)


def _report_state(pid, **options):
    state = po.PipelineState(pipeline_id=pid, prompt=QUESTION, mode="full", status="running")
    state.options.update(_options(**options))
    po.PipelineManager.ensure_dirs(pid)
    po.PipelineManager.save(state)
    return state


def test_commit_row_carries_config_hash(roots, monkeypatch):
    monkeypatch.setattr(Config, "LLM_PROVIDER", "glm", raising=False)
    monkeypatch.setattr(Config, "LLM_MODEL_NAME", "glm-5", raising=False)
    state = _report_state("pipe_eval18ledger")
    orch = po.PipelineOrchestrator()
    orch._generate_stage_report(state, _PublishingAgent(simulation_id="sim_l"), "sim_l",
                                report_id="r_eval18", progress_callback=None)
    pin = state.options[ca.CONFIG_HASH_OPTION]
    assert _HASH_RE.fullmatch(pin["config_hash"])
    assert pin["fingerprint"]["report"] == {"provider": "glm", "model_name": "glm-5"}
    assert state.options["forecast_ledger"]["status"] == "committed"
    (row,) = _rows("commit")
    assert row["record_class"] == "production" and row["config_hash"] == pin["config_hash"]
    # Seed-ensemble members of the same pipeline carry the same configuration hash.
    member = po.PipelineOrchestrator._report_ledger_context(
        state, "sim_m", run_kind="seed_ensemble", seed=7919, record_class="ensemble_member")
    assert member["config_hash"] == pin["config_hash"]
    # The hash is provenance, never identity: the commit/target keys do not change.
    assert set(row) >= {"commit_id", "target_key"}


def test_ledger_row_joins_cost_card_after_report_stage_restamp(roots, monkeypatch):
    """Critic amendment: run.json's report block is stale at report-stage construction and
    restamped by _complete_stage (INFRA-7); the row and the card still share one hash."""
    monkeypatch.setattr(Config, "RUN_SHAPE_PIN", True, raising=False)
    monkeypatch.setattr(Config, "RECORD_RUN_MANIFEST", True, raising=False)
    monkeypatch.setattr(Config, "LLM_PROVIDER", "provider-now", raising=False)
    monkeypatch.setattr(Config, "LLM_MODEL_NAME", "model-now", raising=False)
    pid = "pipe_eval18join"
    state = _report_state(pid)
    stale = copy.deepcopy(MANIFEST)
    stale["resolved"]["report"] = {"provider": "provider-old", "model_name": "model-old"}
    with open(po.PipelineManager.manifest_path(pid), "w", encoding="utf-8") as handle:
        json.dump(stale, handle)
    orch = po.PipelineOrchestrator()
    orch._record_report_mint(state, "r_join")
    report = orch._generate_stage_report(state, _PublishingAgent(simulation_id="sim_j"),
                                         "sim_j", report_id="r_join", progress_callback=None)
    assert report.status == ReportStatus.COMPLETED
    state.report_id = "r_join"
    orch._complete_stage(state, po.STAGE_REPORT, "done")
    assert _load(po.PipelineManager.manifest_path(pid))["resolved"]["report"] == {
        "provider": "provider-now", "model_name": "model-now"}   # restamped at completion
    state.status = "completed"
    orch._write_cost_card(state)
    card = _load(os.path.join(po.PipelineManager._dir(pid), ca.COST_CARD_FILENAME))
    (row,) = _rows("commit")
    assert row["config_hash"] == card["config_hash"] == state.options[
        ca.CONFIG_HASH_OPTION]["config_hash"]
    assert card["config"]["source"] == "report_stage"
    assert card["config"]["fingerprint"]["report"] == {"provider": "provider-now",
                                                       "model_name": "model-now"}
    # Nothing lands in the report folder.
    assert _cost_cards(roots) == [os.path.join(po.PipelineManager._dir(pid),
                                               ca.COST_CARD_FILENAME)]
    assert not os.path.exists(os.path.join(ReportManager._get_report_folder("r_join"),
                                           ca.COST_CARD_FILENAME))
    # The offline rebuild joins on the same hash.
    assert cli.rebuild(pid)["config_hash"] == row["config_hash"]


def test_reused_report_repair_keeps_the_producing_pin(roots):
    state = _report_state("pipe_eval18reuse")
    pinned = ca.config_hash_record(state.options, MANIFEST,
                                   report_producer={"provider": "a", "model_name": "b"})
    state.options[ca.CONFIG_HASH_OPTION] = copy.deepcopy(pinned)
    _write_report("r_reused18", _forecast())
    reused = Report(report_id="r_reused18", simulation_id="sim_1", graph_id="g1",
                    simulation_requirement=QUESTION, status=ReportStatus.COMPLETED)
    po.PipelineOrchestrator()._repair_reused_report_ledger(
        state, reused, "sim_1", {"as_of_date": "2026-07-06"}, "research")
    assert state.options[ca.CONFIG_HASH_OPTION] == pinned
    (row,) = _rows("commit")
    assert row["report_id"] == "r_reused18" and row["config_hash"] == pinned["config_hash"]
    # A report produced before the pin existed gets one (producer from its pending mint).
    legacy = _report_state("pipe_eval18legacy")
    legacy.options[run_shape.REPORT_PRODUCER_OPTION] = run_shape.producer_record(
        "r_legacy18", {"provider": "p", "model_name": "m"})
    po.PipelineOrchestrator._pin_config_hash(
        legacy, keep_existing=True,
        report_producer=run_shape.reused_report_stamp(
            legacy.options[run_shape.REPORT_PRODUCER_OPTION], "r_legacy18"))
    assert legacy.options[ca.CONFIG_HASH_OPTION]["fingerprint"]["report"] == {
        "provider": "p", "model_name": "m"}


def test_flag_off_no_ledger_stamp(roots, monkeypatch):
    monkeypatch.setattr(Config, "COST_CARD_ENABLED", False, raising=False)
    state = _report_state("pipe_eval18nostamp")
    stale = ca.config_hash_record(state.options, MANIFEST)
    state.options[ca.CONFIG_HASH_OPTION] = stale      # a pin from an earlier flag-on attempt
    orch = po.PipelineOrchestrator()
    orch._generate_stage_report(state, _PublishingAgent(simulation_id="sim_n"), "sim_n",
                                report_id="r_nostamp", progress_callback=None)
    assert state.options[ca.CONFIG_HASH_OPTION] == stale   # untouched, and not stamped
    (row,) = _rows("commit")
    assert "config_hash" not in row
    assert "config_hash" not in po.PipelineOrchestrator._report_ledger_context(
        state, "sim_n", run_kind="pipeline", seed=0)


def test_pin_failure_drops_a_stale_pin(roots, monkeypatch):
    state = _report_state("pipe_eval18pinboom")
    state.options[ca.CONFIG_HASH_OPTION] = ca.config_hash_record(state.options, MANIFEST)

    def explode(*_args, **_kwargs):
        raise RuntimeError("fingerprint exploded")

    monkeypatch.setattr(ca, "config_hash_record", explode)
    po.PipelineOrchestrator._pin_config_hash(state, report_producer=None)
    assert ca.CONFIG_HASH_OPTION not in state.options
    assert "config_hash" not in po.PipelineOrchestrator._report_ledger_context(
        state, "sim_x", run_kind="pipeline", seed=0)


# ------------------------------------------------------------------------ CLI
def _terminal_fixture(pid, *, status="completed"):
    state = po.PipelineState(pipeline_id=pid, prompt=QUESTION, mode="full", status=status)
    state.options.update(_options())
    state.options[ca.CONFIG_HASH_OPTION] = ca.config_hash_record(
        state.options, MANIFEST, report_producer={"provider": "glm", "model_name": "glm-5"})
    for stage, seconds in (("research", 300), ("report", 900)):
        state.stages[stage] = po.StageState(
            name=stage, status="completed", started_at="2026-09-30T00:00:00+00:00",
            finished_at=f"2026-09-30T00:{seconds // 60:02d}:00+00:00")
    po.PipelineManager.ensure_dirs(pid)
    po.PipelineManager.save(state)
    pdir = po.PipelineManager._dir(pid)
    with open(os.path.join(pdir, "run_telemetry.json"), "w", encoding="utf-8") as handle:
        json.dump(_telemetry(run_id=pid, pipeline_id=pid), handle)
    with open(po.PipelineManager.manifest_path(pid), "w", encoding="utf-8") as handle:
        json.dump(MANIFEST, handle)
    return state


def test_cli_rebuild_offline(roots, monkeypatch, capsys):
    from app.utils import llm_client

    def refuse(*_args, **_kwargs):
        raise AssertionError("the offline rebuild must not open a socket or build an LLM client")

    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(llm_client.LLMClient, "__init__", refuse)
    pid = "pipe_eval18cli"
    state = _terminal_fixture(pid)
    path = os.path.join(po.PipelineManager._dir(pid), ca.COST_CARD_FILENAME)
    assert cli.main(["build", pid]) == 0
    card = json.loads(capsys.readouterr().out)
    assert not os.path.exists(path)                    # printing never writes
    assert card["schema"] == "drf-cost-card/v1" and card["repo_git_sha"] == "abc123"
    assert card["config_hash"] == state.options[ca.CONFIG_HASH_OPTION]["config_hash"]
    assert card["config"]["source"] == "report_stage"
    assert (card["stages"]["research"]["wall_s"], card["stages"]["report"]["wall_s"]) == (
        300.0, 900.0)
    assert card["totals"]["calls"] == 68
    # No card on disk to carry the in-memory baseline from: an unknown baseline.
    assert card["completeness"]["reasons"] == ["unattributed_process_unknown_baseline:3"]
    assert cli.main(["build", pid, "-o"]) == 0
    captured = capsys.readouterr()
    written = _load(path)
    assert json.loads(captured.out) == written and "wrote" in captured.err
    # A rewrite carries the baseline of the card already on disk.
    written["unattributed_process"]["calls_at_attempt_start"] = 1
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(written, handle)
    assert cli.main(["build", pid, "-o"]) == 0
    capsys.readouterr()
    assert _load(path)["completeness"]["reasons"] == ["unattributed_process_growth:+2"]
    # A live pipeline is printed but never written; a bad id is an error.
    _terminal_fixture("pipe_eval18live", status="running")
    assert cli.main(["build", "pipe_eval18live", "-o"]) == 1
    assert "running" in capsys.readouterr().err
    assert not os.path.exists(os.path.join(po.PipelineManager._dir("pipe_eval18live"),
                                           ca.COST_CARD_FILENAME))
    assert cli.main(["build", "pipe_eval18missing"]) == 1
    assert cli.main(["build", "../etc"]) == 1
    assert "cannot build" in capsys.readouterr().err


def test_cli_rebuild_matches_the_hook_card(roots, monkeypatch):
    pid = "pipe_eval18parity"
    _drive_run(monkeypatch, roots, pid=pid, unattributed_mid_run=1)
    hook = _load(os.path.join(po.PipelineManager._dir(pid), ca.COST_CARD_FILENAME))
    rebuilt = cli.rebuild(pid)
    hook.pop("created_at")
    rebuilt.pop("created_at")
    assert rebuilt == hook
    assert "unattributed_process_growth:+1" in rebuilt["completeness"]["reasons"]


# ------------------------------------------------------------------------ knob
def test_knob_default_on_and_documented():
    assert Config.COST_CARD_ENABLED is True
    with open(os.path.join(_REPO_ROOT, "backend", "app", "config.py"), encoding="utf-8") as fh:
        assert "os.environ.get('COST_CARD_ENABLED', 'true').strip().lower() == 'true'" in fh.read()
    with open(os.path.join(_REPO_ROOT, ".env.example"), encoding="utf-8") as fh:
        assert re.search(r"^#?\s*COST_CARD_ENABLED=true\b", fh.read(), re.M)
    assert ca.SEED_SIM_STAGE == po.SIM_METER_STAGE_ENSEMBLE
