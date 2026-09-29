"""EVAL-15: deterministic per-stage scorecard (``stage-scorecard/v1``).

DRF judges whole reports, so a regression in one stage shows up only as a
diffuse change in the final report.  This module projects the artifacts a
pipeline already wrote into one record per stage: counts, rates and stored
flags, plus contract checks against committed thresholds.  It recomputes
nothing and reuses the existing rule owners instead of copying their rules:

* per-stage artifact paths come from ``PipelineOrchestrator._stage_artifact_specs``
  (the single source the orchestrator uses for registration, reuse validation
  and partial-artifact discovery), and from the owners' path helpers
  (``PipelineManager``, ``ReportManager``) for files the specs do not list;
* binary conviction is the ``passed`` flag ``forecast_extractor._binary_quality``
  stored in ``forecast.json`` (``theme_cardinality`` likewise);
* the residual-scenario test is ``forecast_extractor._is_residual_scenario_name``;
* the degraded-simulation states are the ones ``drf2/driver/gates.py`` and
  ``PipelineOrchestrator._assess_run_health`` flag (parity is pinned by
  ``tests/test_stage_scorecard.py``).

The scorecard is observability, never a gate: it cannot change a pipeline's
``status`` or ``pipeline_health``, and it is written beside the pipeline state
(``<pipeline_dir>/stage_scorecard.json``), never into the report folder.

Metric record: ``{value, num, den, status, source}`` (+ ``threshold`` /
``detail`` where useful).  ``status`` is one of:

* ``measured``          the value was read from the artifact;
* ``not_applicable``    the metric does not apply to this run (e.g. pruning off);
* ``not_instrumented``  the producing engine does not record the field (legacy
                        research meta without ``kiqs``) - unevaluable, never a pass;
* ``artifact_missing``  the artifact the stage should have written is absent;
* ``unreadable``        the artifact exists but cannot be parsed, has the wrong
                        shape, or a rate whose numerator exceeds its denominator.

A required check fails on ``artifact_missing`` / ``unreadable`` (fail closed),
is unevaluable on ``not_instrumented`` and is skipped on ``not_applicable``.
Stage ``passed`` is False when any check fails, None when nothing failed but
something was unevaluable, and True only when every check was measured and
passed.  Stages after a failed/cancelled stage are ``not_reached``; in a
``research_only`` run every stage but research is ``not_applicable``.

``runtime_gates`` records the honesty-critical gate values of the scoring
process next to the suite thresholds.  run.json does not pin them, so for the
sidecar the values are the run's own process configuration
(``identity.scored_by == "pipeline"``) and for an offline backfill they are the
current configuration (``"backfill"``).  A relaxed publish-gate coverage
threshold therefore shows as ``relaxed: true`` next to a failed
``citation_coverage`` contract instead of hiding behind a passed publish gate.
Because the pipeline-authored sidecar is the only record of the gates a run
was published under, the backfill CLI never replaces it unless forced, and a
forced rewrite keeps it under ``identity.previous``.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
from typing import Any, Callable, Mapping, Optional

from ..config import Config
from .forecast_extractor import _is_residual_scenario_name

SCHEMA_VERSION = "stage-scorecard/v1"
SIDECAR_FILENAME = "stage_scorecard.json"
STAGES = ("research", "ontology", "graph", "prepare", "run", "report")

# Committed suite thresholds.  citation_coverage_min mirrors the code default of
# REPORT_PUBLISH_GATE_MIN_COVERAGE; prob_sum_tolerance is deliberately stricter
# than the publish gate's 0.05 (a scenario partition must close to 100%).
DEFAULT_THRESHOLDS: dict[str, float] = {
    "min_binaries": 10,
    "prob_sum_tolerance": 0.005,
    "citation_coverage_min": 0.75,
    "actor_cap": 20,
}

# The simulation_health values drf2/driver/gates.py (hollow_sim_gate) and
# PipelineOrchestrator._assess_run_health treat as a degraded simulation.
DEGRADED_SIMULATION_HEALTH = frozenset({"hollow", "errored", "llm_degraded", "truncated"})

MEASURED = "measured"
NOT_APPLICABLE = "not_applicable"
NOT_INSTRUMENTED = "not_instrumented"
ARTIFACT_MISSING = "artifact_missing"
UNREADABLE = "unreadable"

STAGE_SCORED = "scored"
STAGE_NOT_REACHED = "not_reached"
STAGE_NOT_APPLICABLE = "not_applicable"

# prediction_markets.json status.state / status.empty_reason → market_state.  An
# infrastructure label in either field wins; otherwise the specific status.state
# is mapped before the generic empty_reason (merge_market_snapshots stores
# state 'inflight_timeout' beside empty_reason 'no_equivalent_market').
_MARKET_INFRA_REASONS = frozenset({
    "transport_failure", "partial_transport_failure", "inflight_timeout"})
_MARKET_LABEL_STATES = {
    "all_candidates_irrelevant": "none_relevant",
    "no_equivalent_market": "none_relevant",
    "verified_empty": "none_relevant",
    "no_derivable_queries": "not_attempted",
    "no_queries": "not_attempted",
}

# Honesty-critical boolean gates recorded in runtime_gates (the suite expects each on).
_HONESTY_BOOLEAN_GATES = ("REPORT_PUBLISH_GATE", "REPORT_FINAL_READ_ONLY_AUDIT",
                          "PIPELINE_HEALTH_GATE")

_WORKDIR_RE = re.compile(r"\A[A-Za-z0-9_-][A-Za-z0-9_.-]{0,63}\Z")
_ABSENT = object()


# --------------------------------------------------------------------- readers
def _read_json(path: Any) -> tuple[str, Any]:
    """(status, payload): MEASURED + parsed JSON, ARTIFACT_MISSING or UNREADABLE."""
    if not isinstance(path, str) or not path:
        return ARTIFACT_MISSING, None
    if not os.path.exists(path):
        return ARTIFACT_MISSING, None
    try:
        with open(path, encoding="utf-8") as handle:
            return MEASURED, json.load(handle)
    except (OSError, ValueError, UnicodeDecodeError, RecursionError):
        return UNREADABLE, None


def _read_json_object(path: Any) -> tuple[str, Optional[dict]]:
    status, payload = _read_json(path)
    if status == MEASURED and not isinstance(payload, dict):
        return UNREADABLE, None
    return status, payload


def _sha256(path: Any) -> Optional[str]:
    if not isinstance(path, str) or not os.path.isfile(path):
        return None
    digest = hashlib.sha256()
    try:
        with open(path, "rb") as handle:
            for chunk in iter(lambda: handle.read(1 << 20), b""):
                digest.update(chunk)
    except OSError:
        return None
    return digest.hexdigest()


def _as_count(value: Any) -> Optional[int]:
    """A non-negative int (bools are not counts)."""
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


def _as_float(value: Any) -> Optional[float]:
    """A finite float (bools are not numbers)."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        number = float(value)
    except OverflowError:  # a JSON integer beyond float range
        return None
    return number if math.isfinite(number) else None


# --------------------------------------------------------------------- records
def _metric(value: Any = None, *, status: str = MEASURED, source: str,
            num: Optional[int] = None, den: Optional[int] = None, **extra: Any) -> dict:
    """One metric record; optional extras (threshold, detail, ...) are kept only when set."""
    record = {"value": value, "num": num, "den": den, "status": status, "source": source}
    record.update({key: item for key, item in extra.items() if item is not None})
    return record


def _unavailable(status: str, source: str, detail: Optional[str] = None) -> dict:
    return _metric(None, status=status, source=source, detail=detail)


def _rate(num: Any, den: Any, source: str, **extra: Any) -> dict:
    """A num/den rate; the numerator may never exceed the denominator."""
    n, d = _as_count(num), _as_count(den)
    if n is None or d is None:
        return _unavailable(UNREADABLE, source, "counts are not non-negative integers")
    if n > d:
        return _metric(None, status=UNREADABLE, source=source, num=n, den=d,
                       detail="numerator exceeds denominator")
    return _metric(round(n / d, 4) if d else None, source=source, num=n, den=d, **extra)


def _stored_rate(value: Any, num: Any, den: Any, source: str, **extra: Any) -> dict:
    """A rate the producer already stored: keep its value, validate its counts when both exist."""
    stored = _as_float(value)
    if stored is None:
        return _unavailable(UNREADABLE, source, "stored value is not a finite number")
    if num is None or den is None:
        return _metric(stored, source=source, **extra)
    rate = _rate(num, den, source)
    if rate["status"] != MEASURED:
        return rate
    return _metric(stored, source=source, num=rate["num"], den=rate["den"], **extra)


def _field(payload: Optional[dict], status: str, key: str, source: str) -> tuple[Optional[dict], Any]:
    """(error record, value): an error record when the artifact or the field is unavailable."""
    if status != MEASURED:
        return _unavailable(status, source), None
    value = payload.get(key, _ABSENT)
    if value is _ABSENT:
        return _unavailable(NOT_INSTRUMENTED, source, f"artifact has no '{key}' field"), None
    return None, value


# -------------------------------------------------------------------- research
def _research_metrics(paths: Mapping[str, Any], digests: dict) -> dict:
    meta_status, meta = _read_json_object(paths.get("research_meta"))
    if meta_status == MEASURED:
        digests["research_meta"] = _sha256(paths.get("research_meta"))
    metrics: dict[str, dict] = {}

    src = "handoff/meta.json:kiqs"
    fsrc = "handoff/meta.json:kiqs.fallback/completed"
    err, kiqs = _field(meta, meta_status, "kiqs", src)
    if err is None and not isinstance(kiqs, dict):
        err = _unavailable(UNREADABLE, src, "kiqs is not an object")
    if err is not None:
        metrics["kiq_completion"] = err
        metrics["kiq_fallback_rate"] = _unavailable(err["status"], fsrc, err.get("detail"))
    else:
        planned, followups = _as_count(kiqs.get("planned")), _as_count(kiqs.get("followups"))
        total = planned + followups if planned is not None and followups is not None else None
        # ``completed`` counts every KIQ with a record, including investigations whose
        # agent failed and fell back to deterministic notes; kiq_fallback_rate gates those.
        metrics["kiq_completion"] = _rate(kiqs.get("completed"), total, src)
        if "fallback" in kiqs:
            metrics["kiq_fallback_rate"] = _rate(kiqs.get("fallback"), kiqs.get("completed"), fsrc)
        else:
            metrics["kiq_fallback_rate"] = _unavailable(
                NOT_INSTRUMENTED, fsrc, "kiqs has no 'fallback' field")

    metrics.update(_kiq_fact_metrics(paths, meta, err, digests))

    src = "handoff/meta.json:tools"
    err, tools = _field(meta, meta_status, "tools", src)
    if err is None and not isinstance(tools, dict):
        err = _unavailable(UNREADABLE, src, "tools is not an object")
    if err is not None:
        metrics["tool_failure_rate"] = err
    else:
        calls = [_as_count(tools.get(k)) for k in
                 ("searches", "cached_searches", "fetches", "cached_fetches")]
        metrics["tool_failure_rate"] = _rate(
            tools.get("failures"), None if None in calls else sum(calls), src)

    src = "handoff/meta.json:research_qa.passed"
    err, qa = _field(meta, meta_status, "research_qa", src)
    if err is None:
        passed = qa.get("passed") if isinstance(qa, dict) else None
        err = None if isinstance(passed, bool) else _unavailable(
            UNREADABLE, src, "research_qa.passed is not a boolean")
        qa = passed
    metrics["research_qa_passed"] = err or _metric(qa, source=src)

    for name in ("plan_fallback", "synthesis_fallback_sections"):
        src = f"handoff/meta.json:{name}"
        err, items = _field(meta, meta_status, name, src)
        if err is None and not isinstance(items, list):
            err = _unavailable(UNREADABLE, src, f"{name} is not a list")
        metrics[name] = err or _metric(len(items), source=src,
                                       detail=[str(item)[:120] for item in items[:10]])

    metrics["actor_count"] = _actor_count(paths, meta_status, meta, digests)
    metrics["market_state"] = _market_state(paths, digests)
    return metrics


def _kiq_dir(paths: Mapping[str, Any], meta: dict) -> Optional[str]:
    handoff = paths.get("handoff_dir")
    if not isinstance(handoff, str) or not handoff:
        return None
    workdir = meta.get("v3_workdir")
    if not isinstance(workdir, str) or not _WORKDIR_RE.fullmatch(workdir):
        workdir = "v3"  # a path-like or missing value never escapes the handoff dir
    return os.path.join(handoff, workdir, "kiq")


def _kiq_fact_metrics(paths: Mapping[str, Any], meta: Optional[dict],
                      kiqs_error: Optional[dict], digests: dict) -> dict:
    """verified_share and number_verification_pass_rate from handoff/<v3>/kiq/*.json facts."""
    names = {"verified_share": "handoff/v3/kiq/*.json:facts[].tag",
             "number_verification_pass_rate": "handoff/v3/kiq/*.json:facts[].verified_numbers"}
    if kiqs_error is not None:
        # Missing/unreadable meta or an engine without meta.kiqs: same status for the facts.
        return {name: _unavailable(kiqs_error["status"], src, kiqs_error.get("detail"))
                for name, src in names.items()}
    kiq_dir = _kiq_dir(paths, meta or {})
    try:
        files = sorted(f for f in os.listdir(kiq_dir) if f.endswith(".json")) if kiq_dir else []
    except OSError:
        files = []
    if not files:
        return {name: _unavailable(ARTIFACT_MISSING, src, "no KIQ records on disk")
                for name, src in names.items()}
    facts: list[dict] = []
    combined = hashlib.sha256()
    for filename in files:
        path = os.path.join(kiq_dir, filename)
        status, record = _read_json_object(path)
        rows = record.get("facts") if isinstance(record, dict) else None
        if status != MEASURED or not isinstance(rows, list) or not all(
                isinstance(row, dict) for row in rows):
            return {name: _unavailable(UNREADABLE, src, f"unreadable KIQ record {filename}")
                    for name, src in names.items()}
        facts.extend(rows)
        combined.update(f"{filename}\0{_sha256(path)}\n".encode("utf-8"))
    digests["research_kiq_facts"] = combined.hexdigest()
    verified = sum(1 for fact in facts if fact.get("tag") == "VERIFIED")
    checked = [fact.get("verified_numbers") for fact in facts
               if isinstance(fact.get("verified_numbers"), bool)]
    return {
        "verified_share": _rate(verified, len(facts), names["verified_share"]),
        "number_verification_pass_rate": _rate(
            sum(1 for ok in checked if ok), len(checked), names["number_verification_pass_rate"]),
    }


def _actor_count(paths: Mapping[str, Any], meta_status: str, meta: Optional[dict],
                 digests: dict) -> dict:
    if meta_status == MEASURED and "actors_count" in meta:
        count = _as_count(meta.get("actors_count"))
        src = "handoff/meta.json:actors_count"
        return _metric(count, source=src) if count is not None else _unavailable(
            UNREADABLE, src, "actors_count is not a count")
    src = "handoff/actors.json:actors"
    status, dossier = _read_json_object(paths.get("dossier"))
    if status == ARTIFACT_MISSING:
        return _unavailable(NOT_INSTRUMENTED, src, "no actors_count and no actors.json")
    if status != MEASURED or not isinstance(dossier.get("actors"), list):
        return _unavailable(UNREADABLE, src, "actors.json has no actors list")
    digests["dossier"] = _sha256(paths.get("dossier"))
    return _metric(len(dossier["actors"]), source=src)


def _market_state(paths: Mapping[str, Any], digests: dict) -> dict:
    """found | none_relevant | infra_failure | not_attempted from prediction_markets.json.

    Reads both ``status.state`` and ``status.empty_reason`` (an infrastructure
    label in either wins) and records both in ``detail``.
    """
    src = "handoff/prediction_markets.json:status"
    status, payload = _read_json_object(paths.get("prediction_markets"))
    if status == ARTIFACT_MISSING:
        return _metric("not_attempted", source=src, detail="prediction_markets.json absent")
    if status != MEASURED:
        return _unavailable(status, src)
    digests["prediction_markets"] = _sha256(paths.get("prediction_markets"))
    markets = payload.get("markets")
    pm_status = payload.get("status") if isinstance(payload.get("status"), dict) else {}
    selected = _as_count(pm_status.get("selected_count")) or 0
    labels = {key: str(pm_status.get(key) or "").strip() for key in ("state", "empty_reason")}
    failures = _as_count(pm_status.get("transport_failure_count")) or 0
    candidates = _as_count(pm_status.get("candidate_count")) or 0
    if (isinstance(markets, list) and markets) or selected > 0:
        state = "found"
    elif pm_status.get("attempted") is False:
        state = "not_attempted"
    elif _MARKET_INFRA_REASONS & set(labels.values()):
        state = "infra_failure"
    elif failures and not candidates and "all_candidates_irrelevant" not in labels.values():
        # The owners' ladder (merge_market_snapshots, market_tools): no candidate
        # plus a failed query is a (partial) transport failure, even where a
        # single-snapshot producer stored the generic 'no_equivalent_market'.
        state = "infra_failure"
    else:
        state = (_MARKET_LABEL_STATES.get(labels["state"])
                 or _MARKET_LABEL_STATES.get(labels["empty_reason"])
                 or ("none_relevant" if payload.get("no_relevant_markets") is True
                     else "not_attempted"))
    detail: dict[str, Any] = {key: label for key, label in labels.items() if label}
    if failures:
        detail["transport_failure_count"] = failures
    return _metric(state, source=src, detail=detail or None)


# -------------------------------------------------------------------- ontology
def _ontology_metrics(paths: Mapping[str, Any], digests: dict) -> dict:
    status, ontology = _read_json_object(paths.get("ontology"))
    if status != MEASURED:
        return {"present": _unavailable(status, "handoff/ontology.json"),
                "entity_type_count": _unavailable(status, "handoff/ontology.json:entity_types")}
    digests["ontology"] = _sha256(paths.get("ontology"))
    types = ontology.get("entity_types")
    src = "handoff/ontology.json:entity_types"
    return {
        "present": _metric(True, source="handoff/ontology.json"),
        "entity_type_count": _metric(len(types), source=src) if isinstance(types, list)
        else _unavailable(UNREADABLE, src, "entity_types is not a list"),
    }


# ----------------------------------------------------------------------- graph
def _graph_metrics(paths: Mapping[str, Any], expected: bool, digests: dict) -> dict:
    names = ("postcondition_ok", "cap_satisfied", "core_actor_coverage")
    src = "handoff/graph_prune.json"
    status, audit = _read_json_object(paths.get("graph_prune"))
    if status == ARTIFACT_MISSING and not expected:
        # Pruning is flag-gated (GRAPH_PRUNE_ENABLED); no audit and no record of a prune.
        return {name: _unavailable(NOT_INSTRUMENTED, f"{src}:{name}", "graph pruning did not run")
                for name in names}
    if status != MEASURED:
        return {name: _unavailable(status, f"{src}:{name}") for name in names}
    digests["graph_prune"] = _sha256(paths.get("graph_prune"))
    if audit.get("enabled") is False:
        return {name: _unavailable(NOT_APPLICABLE, f"{src}:{name}", "graph pruning disabled")
                for name in names}
    metrics: dict[str, dict] = {}
    for name in ("postcondition_ok", "cap_satisfied"):
        err, value = _field(audit, status, name, f"{src}:{name}")
        if err is None and value is not None and not isinstance(value, bool):
            err = _unavailable(UNREADABLE, f"{src}:{name}", f"{name} is not a boolean")
        metrics[name] = err or _metric(value, source=f"{src}:{name}")
    csrc = f"{src}:core_actor_coverage"
    err, coverage = _field(audit, status, "core_actor_coverage", csrc)
    # The pass threshold is the one the pruner applied, read from the artifact itself.
    metrics["core_actor_coverage"] = err or _stored_rate(
        coverage, audit.get("core_actor_matched"), audit.get("core_actor_expected"), csrc,
        threshold=_as_float(audit.get("min_core_coverage")))
    return metrics


# --------------------------------------------------------------------- prepare
def _prepare_metrics(paths: Mapping[str, Any], digests: dict) -> dict:
    src = "simulation/actor_cast_manifest.json:selected_actor_count"
    status, manifest = _read_json_object(paths.get("actor_cast"))
    if status == MEASURED:
        digests["actor_cast"] = _sha256(paths.get("actor_cast"))
    err, count = _field(manifest, status, "selected_actor_count", src)
    if err is None and _as_count(count) is None:
        err = _unavailable(UNREADABLE, src, "selected_actor_count is not a count")
    return {"selected_actor_count": err or _metric(count, source=src)}


# ------------------------------------------------------------------------- run
def _run_metrics(paths: Mapping[str, Any], digests: dict) -> dict:
    src = "simulation/run_summary.json"
    status, summary = _read_json_object(paths.get("run_summary"))
    if status == MEASURED:
        digests["run_summary"] = _sha256(paths.get("run_summary"))
    metrics: dict[str, dict] = {}
    err, health = _field(summary, status, "simulation_health", f"{src}:simulation_health")
    if err is None and not isinstance(health, str):
        err = _unavailable(UNREADABLE, f"{src}:simulation_health", "simulation_health is not a string")
    metrics["simulation_health"] = err or _metric(health, source=f"{src}:simulation_health")

    # organic / (organic + seed): the denominator is every recorded action.
    metrics["organic_share"] = _count_ratio(
        summary, status, "organic_action_count", ("organic_action_count", "seed_action_count"),
        f"{src}:organic_action_count/(organic_action_count+seed_action_count)")
    metrics["organic_round_coverage"] = _count_ratio(
        summary, status, "rounds_with_organic_actions", ("rounds_executed",),
        f"{src}:rounds_with_organic_actions/rounds_executed")
    return metrics


def _count_ratio(payload: Optional[dict], status: str, num_key: str,
                 den_keys: tuple[str, ...], source: str) -> dict:
    """num_key / sum(den_keys) over one artifact's count fields."""
    values: dict[str, Any] = {}
    for key in (num_key, *den_keys):
        err, values[key] = _field(payload, status, key, source)
        if err is not None:
            return err
    parts = [_as_count(values[key]) for key in den_keys]
    return _rate(values[num_key], None if None in parts else sum(parts), source)


# ---------------------------------------------------------------------- report
def _report_metrics(paths: Mapping[str, Any], thresholds: Mapping[str, float],
                    digests: dict) -> dict:
    fa_status, audit = _read_json_object(paths.get("final_audit"))
    if fa_status == MEASURED:
        digests["final_audit"] = _sha256(paths.get("final_audit"))
    fc_status, forecast = _read_json_object(paths.get("forecast"))
    if fc_status == MEASURED:
        digests["forecast"] = _sha256(paths.get("forecast"))
    metrics: dict[str, dict] = {}

    src = "report/final_audit.json:hard_passed"
    err, hard = _field(audit, fa_status, "hard_passed", src)
    metrics["final_audit_hard_passed"] = err or _metric(hard is True, source=src)

    src = "report/final_audit.json:publish_gate"
    err, gate = _field(audit, fa_status, "publish_gate", src)
    if err is None and not isinstance(gate, dict):
        err = _unavailable(UNREADABLE, src, "publish_gate is not an object")
    if err is None:
        disabled = gate.get("enabled") is False
        metrics["publish_gate_passed"] = _metric(
            gate.get("passed") is True and not disabled, source=src,
            detail="publish gate disabled at runtime" if disabled else None)
    else:
        metrics["publish_gate_passed"] = err

    src = "report/forecast.json:binary_forecasts"
    binaries = forecast.get("binary_forecasts", []) if fc_status == MEASURED else None
    if fc_status != MEASURED:
        metrics["binary_count"] = _unavailable(fc_status, src)
    elif not isinstance(binaries, list):
        metrics["binary_count"] = _unavailable(UNREADABLE, src, "binary_forecasts is not a list")
    else:
        metrics["binary_count"] = _metric(len(binaries), source=src,
                                          threshold=thresholds["min_binaries"])

    src = "report/forecast.json:binary_quality"
    err, quality = _field(forecast, fc_status, "binary_quality", src)
    if err is None and not isinstance(quality, dict):
        err = _unavailable(UNREADABLE, src, "binary_quality is not an object")
    if err is None:
        passed = quality.get("passed")
        metrics["binary_quality_passed"] = _metric(passed, source=f"{src}.passed") if isinstance(
            passed, bool) else _unavailable(UNREADABLE, f"{src}.passed", "passed is not a boolean")
        cardinality = _as_count(quality.get("theme_cardinality"))
        metrics["theme_cardinality"] = _metric(
            cardinality, source=f"{src}.theme_cardinality") if cardinality is not None else (
            _unavailable(NOT_INSTRUMENTED if "theme_cardinality" not in quality else UNREADABLE,
                         f"{src}.theme_cardinality"))
    else:
        metrics["binary_quality_passed"] = err
        metrics["theme_cardinality"] = dict(err, source=f"{src}.theme_cardinality")

    metrics.update(_scenario_metrics(forecast, fc_status, thresholds))
    metrics["citation_coverage"] = _citation_coverage(audit, fa_status, thresholds)

    metrics["semantic_citation_unverifiable_ratio"] = _semantic_unverifiable_ratio(audit, fa_status)

    src = "report/forecast.json:market_comparison.anchored_count"
    err, comparison = _field(forecast, fc_status, "market_comparison", src)
    if err is None:
        anchored = _as_count(comparison.get("anchored_count")) if isinstance(
            comparison, dict) else None
        err = None if anchored is not None else _unavailable(
            UNREADABLE, src, "anchored_count is not a count")
        comparison = anchored
    metrics["market_anchor_count"] = err or _metric(comparison, source=src)
    return metrics


def _scenario_metrics(forecast: Optional[dict], status: str,
                      thresholds: Mapping[str, float]) -> dict:
    tolerance = thresholds["prob_sum_tolerance"]
    psrc = "report/forecast.json:scenarios[].probability"
    rsrc = "report/forecast.json:scenarios[].name"
    if status != MEASURED:
        return {"probability_sum_ok": _unavailable(status, psrc),
                "has_residual_scenario": _unavailable(status, rsrc)}
    scenarios = forecast.get("scenarios", [])
    if not isinstance(scenarios, list) or not all(isinstance(row, dict) for row in scenarios):
        return {"probability_sum_ok": _unavailable(UNREADABLE, psrc, "scenarios is not a list of objects"),
                "has_residual_scenario": _unavailable(UNREADABLE, rsrc, "scenarios is not a list of objects")}
    probabilities = [_as_float(row.get("probability")) for row in scenarios]
    if not scenarios or None in probabilities:
        total = None
        ok = False
        detail = "no scenarios" if not scenarios else "a scenario probability is not a finite number"
    else:
        total = round(sum(probabilities), 6)
        ok = abs(total - 1.0) <= tolerance + 1e-9
        detail = None
    residual = forecast.get("residual_scenario_added") is True or any(
        _is_residual_scenario_name(row.get("name")) for row in scenarios)
    return {
        "probability_sum_ok": _metric(ok, source=psrc, sum=total, tolerance=tolerance,
                                      detail=detail),
        "has_residual_scenario": _metric(residual, source=rsrc),
    }


def _citation_coverage(audit: Optional[dict], status: str, thresholds: Mapping[str, float]) -> dict:
    src = "report/final_audit.json:citation_grounding"
    err, grounding = _field(audit, status, "citation_grounding", src)
    if err is None and not isinstance(grounding, dict):
        err = _unavailable(UNREADABLE, src, "citation_grounding is not an object")
    if err is not None:
        return err
    # Same basis rule as the publish gate: the strict resolved metric when recorded.
    basis = "resolved_coverage" if "resolved_coverage" in grounding else "coverage"
    cited = grounding.get("resolved_cited" if basis == "resolved_coverage" else "cited")
    return _stored_rate(grounding.get(basis), cited, grounding.get("quantitative_claims"),
                        f"{src}.{basis}", threshold=thresholds["citation_coverage_min"])


def _semantic_unverifiable_ratio(audit: Optional[dict], status: str) -> dict:
    src = "report/final_audit.json:semantic_citations"
    err, semantic = _field(audit, status, "semantic_citations", src)
    if err is None and not isinstance(semantic, dict):
        err = _unavailable(UNREADABLE, src, "semantic_citations is not an object")
    if err is not None:
        return err
    if "unverifiable_ratio" in semantic:
        return _stored_rate(semantic.get("unverifiable_ratio"), semantic.get("unverifiable"),
                            semantic.get("checked"), f"{src}.unverifiable_ratio")
    if "unverifiable" in semantic and "checked" in semantic:
        # Older audits stored only the counts: schema drift, not a corrupt artifact.
        return _rate(semantic.get("unverifiable"), semantic.get("checked"),
                     f"{src}.unverifiable/checked")
    return _unavailable(NOT_INSTRUMENTED, f"{src}.unverifiable_ratio",
                        "audit records neither unverifiable_ratio nor its counts")


# ---------------------------------------------------------------------- checks
Predicate = Callable[[dict, Mapping[str, float]], Optional[bool]]


def _stage_completed(record: dict, _t: Mapping[str, float]) -> bool:
    return record["value"] == "completed"


def _is_true(record: dict, _t: Mapping[str, float]) -> bool:
    return record["value"] is True


def _is_zero(record: dict, _t: Mapping[str, float]) -> bool:
    return record["value"] == 0


def _market_ok(record: dict, _t: Mapping[str, float]) -> Optional[bool]:
    if record["value"] == "not_attempted":
        return None
    return record["value"] in ("found", "none_relevant")


def _core_coverage_ok(record: dict, _t: Mapping[str, float]) -> Optional[bool]:
    threshold = _as_float(record.get("threshold"))
    if threshold is None:
        return None
    return record["value"] is not None and record["value"] >= threshold


# Required contract checks per stage (metric name → predicate).  Metrics not
# listed here (rates, counts) are descriptive until per-replicate baselines exist.
_CHECKS: dict[str, tuple[tuple[str, Predicate], ...]] = {
    "research": (
        ("stage_status", _stage_completed),
        ("kiq_completion", lambda r, _t: bool(r["den"]) and r["num"] == r["den"]),
        ("kiq_fallback_rate", lambda r, _t: r["num"] == 0),
        ("research_qa_passed", _is_true),
        ("plan_fallback", _is_zero),
        ("synthesis_fallback_sections", _is_zero),
        ("market_state", _market_ok),
    ),
    "ontology": (
        ("stage_status", _stage_completed),
        ("present", _is_true),
        ("entity_type_count", lambda r, _t: r["value"] >= 1),
    ),
    "graph": (
        ("stage_status", _stage_completed),
        ("postcondition_ok", _is_true),
        ("cap_satisfied", _is_true),
        ("core_actor_coverage", _core_coverage_ok),
    ),
    "prepare": (
        ("stage_status", _stage_completed),
        ("selected_actor_count", lambda r, t: 1 <= r["value"] <= t["actor_cap"]),
    ),
    "run": (
        ("stage_status", _stage_completed),
        ("simulation_health", lambda r, _t: r["value"] not in DEGRADED_SIMULATION_HEALTH),
    ),
    "report": (
        ("stage_status", _stage_completed),
        ("final_audit_hard_passed", _is_true),
        ("publish_gate_passed", _is_true),
        ("binary_count", lambda r, t: r["value"] >= t["min_binaries"]),
        ("binary_quality_passed", _is_true),
        ("probability_sum_ok", _is_true),
        ("has_residual_scenario", _is_true),
        ("citation_coverage", lambda r, t: r["value"] >= t["citation_coverage_min"]),
    ),
}


def _evaluate(stage: str, metrics: Mapping[str, dict], thresholds: Mapping[str, float]) -> dict:
    failed: list[str] = []
    unevaluable: list[str] = []
    for name, predicate in _CHECKS[stage]:
        record = metrics.get(name)
        status = record.get("status") if isinstance(record, dict) else UNREADABLE
        if status == NOT_APPLICABLE:
            continue
        if status == NOT_INSTRUMENTED:
            unevaluable.append(name)
            continue
        if status != MEASURED:
            failed.append(name)
            continue
        try:
            verdict = predicate(record, thresholds)
        except Exception:  # noqa: BLE001 — a malformed value fails its contract
            verdict = False
        if verdict is None:
            unevaluable.append(name)
        elif not verdict:
            failed.append(name)
    passed = False if failed else (None if unevaluable else True)
    return {"passed": passed, "failed": failed, "unevaluable": unevaluable}


def _unscored_check() -> dict:
    return {"passed": None, "failed": [], "unevaluable": []}


# ---------------------------------------------------------------- the envelope
def effective_thresholds(thresholds: Any = None) -> dict[str, float]:
    """DEFAULT_THRESHOLDS overlaid with every valid (finite, non-negative number) override."""
    out = dict(DEFAULT_THRESHOLDS)
    if isinstance(thresholds, Mapping):
        for key in DEFAULT_THRESHOLDS:
            value = _as_float(thresholds.get(key))
            if value is not None and value >= 0:
                out[key] = value
    return out


def load_thresholds(path: str) -> dict[str, float]:
    """Read a thresholds override file; raise ValueError on any unknown key or bad value."""
    with open(path, encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError("thresholds file must hold a JSON object")
    unknown = sorted(set(payload) - set(DEFAULT_THRESHOLDS))
    if unknown:
        raise ValueError(f"unknown threshold(s): {', '.join(unknown)}")
    for key, value in payload.items():
        number = _as_float(value)
        if number is None or number < 0:
            raise ValueError(f"threshold {key} must be a finite non-negative number")
    return effective_thresholds(payload)


def runtime_gates(thresholds: Mapping[str, float]) -> dict[str, dict]:
    """Honesty-critical gate values of this process next to the suite expectation."""
    coverage = _as_float(getattr(Config, "REPORT_PUBLISH_GATE_MIN_COVERAGE", None))
    suite = thresholds["citation_coverage_min"]
    gates = {"REPORT_PUBLISH_GATE_MIN_COVERAGE": {
        "effective": coverage, "suite_threshold": suite,
        "relaxed": coverage is None or coverage < suite}}
    for name in _HONESTY_BOOLEAN_GATES:
        effective = getattr(Config, name, None)
        effective = effective if isinstance(effective, bool) else None
        gates[name] = {"effective": effective, "suite_threshold": True,
                       "relaxed": effective is not True}
    return gates


def _identity(inputs: Mapping[str, Any], digests: dict) -> dict:
    status, manifest = _read_json_object(inputs["paths"].get("run_manifest"))
    manifest = manifest if status == MEASURED else {}
    if status == MEASURED:
        digests["run_manifest"] = _sha256(inputs["paths"].get("run_manifest"))
    sha = manifest.get("repo_git_sha")
    resolved = manifest.get("resolved")
    backbone: Optional[dict] = None
    if isinstance(resolved, dict):
        backbone = {}
        for stage, block in sorted(resolved.items()):
            if isinstance(block, dict):
                picked = {k: block[k] for k in ("provider", "model", "model_name")
                          if isinstance(block.get(k), str) and block[k]}
                if picked:
                    backbone[str(stage)] = picked
    return {
        "pipeline_id": inputs["pipeline_id"],
        "mode": inputs["mode"],
        "status": inputs["status"],
        "report_id": inputs["report_id"],
        "simulation_id": inputs["simulation_id"],
        "scored_by": inputs["scored_by"],
        "repo_git_sha": sha if isinstance(sha, str) and sha else None,
        "backbone": backbone,
    }


def _clean_str(value: Any) -> Optional[str]:
    return value if isinstance(value, str) and value else None


def _normalize_inputs(inputs: Any) -> dict:
    raw = inputs if isinstance(inputs, Mapping) else {}
    paths = raw.get("paths") if isinstance(raw.get("paths"), Mapping) else {}
    stage_status = raw.get("stage_status") if isinstance(raw.get("stage_status"), Mapping) else {}
    return {
        "pipeline_id": _clean_str(raw.get("pipeline_id")),
        "mode": "research_only" if raw.get("mode") == "research_only" else "full",
        "status": _clean_str(raw.get("status")),
        "report_id": _clean_str(raw.get("report_id")),
        "simulation_id": _clean_str(raw.get("simulation_id")),
        "scored_by": _clean_str(raw.get("scored_by")),
        "graph_prune_expected": raw.get("graph_prune_expected") is True,
        "stage_status": {stage: _clean_str(stage_status.get(stage)) for stage in STAGES},
        "paths": {str(k): v for k, v in paths.items() if isinstance(v, str) and v},
    }


def _stage_metrics(stage: str, inputs: Mapping[str, Any], thresholds: Mapping[str, float],
                   digests: dict) -> dict:
    paths = inputs["paths"]
    if stage == "research":
        return _research_metrics(paths, digests)
    if stage == "ontology":
        return _ontology_metrics(paths, digests)
    if stage == "graph":
        return _graph_metrics(paths, inputs["graph_prune_expected"], digests)
    if stage == "prepare":
        return _prepare_metrics(paths, digests)
    if stage == "run":
        return _run_metrics(paths, digests)
    return _report_metrics(paths, thresholds, digests)


def build_stage_scorecard(inputs: Any, thresholds: Any = None) -> dict:
    """Project one pipeline's artifacts into a ``stage-scorecard/v1`` envelope.

    ``inputs`` is what :func:`resolve_inputs` returns.  Pure projection over
    files already on disk: no network, no LLM, no writes, and it never raises -
    a malformed input or artifact becomes an ``unreadable`` / ``artifact_missing``
    record instead.
    """
    limits = effective_thresholds(thresholds)
    norm = _normalize_inputs(inputs)
    digests: dict[str, Optional[str]] = {}
    stages: dict[str, dict] = {}
    checks: dict[str, dict] = {}
    reached = True
    for stage in STAGES:
        stage_status = norm["stage_status"][stage]
        block: dict[str, Any] = {"status": STAGE_SCORED, "stage_status": stage_status,
                                 "metrics": {}}
        if norm["mode"] == "research_only" and stage != "research":
            block["status"] = STAGE_NOT_APPLICABLE
        elif not reached or stage_status in (None, "pending"):
            block["status"] = STAGE_NOT_REACHED
            reached = False
        else:
            metrics = {"stage_status": _metric(
                stage_status, source=f"pipeline_state.json:stages.{stage}.status")}
            try:
                metrics.update(_stage_metrics(stage, norm, limits, digests))
            except Exception as exc:  # noqa: BLE001 — never raise: the stage is unreadable
                for name, _predicate in _CHECKS[stage][1:]:
                    metrics.setdefault(name, _unavailable(
                        UNREADABLE, stage, f"projection failed: {type(exc).__name__}"))
            block["metrics"] = metrics
            if stage_status != "completed":
                reached = False
        stages[stage] = block
        checks[stage] = (_evaluate(stage, block["metrics"], limits)
                         if block["status"] == STAGE_SCORED else _unscored_check())
    try:
        identity = _identity(norm, digests)
    except Exception:  # noqa: BLE001 — identity is descriptive; never raise
        identity = {key: norm[key] for key in
                    ("pipeline_id", "mode", "status", "report_id", "simulation_id", "scored_by")}
        identity.update(repo_git_sha=None, backbone=None)
    try:
        gates = runtime_gates(limits)
    except Exception:  # noqa: BLE001 — an unreadable config records no gate values
        gates = {}
    return {
        "schema_version": SCHEMA_VERSION,
        "identity": identity,
        "thresholds": limits,
        "runtime_gates": gates,
        "artifacts": {name: digest for name, digest in sorted(digests.items()) if digest},
        "stages": stages,
        "checks": checks,
    }


def summarize_checks(scorecard: Mapping[str, Any]) -> dict[str, Optional[bool]]:
    """{stage: passed} - the compact summary the orchestrator stores in state.options."""
    checks = scorecard.get("checks") if isinstance(scorecard, Mapping) else None
    checks = checks if isinstance(checks, Mapping) else {}
    return {stage: (checks.get(stage) or {}).get("passed") for stage in STAGES}


# ------------------------------------------------------------ resolve + write
def resolve_inputs(pipeline_id: str, state: Optional[Mapping[str, Any]] = None) -> dict:
    """Resolve a pipeline's identity and artifact paths for :func:`build_stage_scorecard`.

    ``state`` is the orchestrator's live state dict (the ``_run`` finally block
    passes it so the sidecar never reads a stale state file); without it the
    persisted state is read through ``PipelineManager.load``.  Paths come from
    ``PipelineOrchestrator._stage_artifact_specs`` and the owners' path helpers.
    Raises ValueError for an invalid, unknown or newer-schema pipeline.
    """
    from .pipeline_orchestrator import PipelineManager, PipelineOrchestrator, PipelineState
    from .report_agent import ReportManager

    data = dict(state) if isinstance(state, Mapping) else PipelineManager.load(pipeline_id)
    if not isinstance(data, dict):
        raise ValueError(f"pipeline not found: {pipeline_id}")
    if PipelineManager.is_incompatible(data) is not None:
        raise ValueError(f"pipeline {pipeline_id} has a newer state schema")
    try:
        pipeline_state = PipelineState.from_dict({**data, "pipeline_id": pipeline_id})
    except Exception as exc:  # noqa: BLE001 — a malformed state file is unreadable, not a crash
        raise ValueError(f"unreadable pipeline state for {pipeline_id}: "
                         f"{type(exc).__name__}: {exc}") from exc
    handoff = pipeline_state.handoff_dir or PipelineManager.handoff_dir(pipeline_id)
    specs: dict[str, str] = {}
    for stage in STAGES:
        try:
            stage_specs = PipelineOrchestrator._stage_artifact_specs(pipeline_state, stage)
        except ValueError:  # an unsafe id resolves to "artifact missing", not a crash
            continue
        for name, path in stage_specs:
            specs.setdefault(name, path)
    artifacts = pipeline_state.artifacts if isinstance(pipeline_state.artifacts, dict) else {}
    options = pipeline_state.options if isinstance(pipeline_state.options, dict) else {}
    paths: dict[str, Optional[str]] = {
        "handoff_dir": handoff,
        "research_meta": os.path.join(handoff, "meta.json"),
        "prediction_markets": specs.get("prediction_markets"),
        "dossier": specs.get("dossier"),
        "ontology": specs.get("ontology"),
        "graph_prune": artifacts.get("graph_prune") or os.path.join(handoff, "graph_prune.json"),
        "actor_cast": specs.get("actor_cast"),
        "run_summary": specs.get("run_summary"),
        "run_manifest": PipelineManager.manifest_path(pipeline_id),
    }
    if pipeline_state.report_id:
        try:
            paths["forecast"] = os.path.join(
                ReportManager._get_report_folder(pipeline_state.report_id), "forecast.json")
            paths["final_audit"] = ReportManager._get_report_final_audit_path(
                pipeline_state.report_id)
        except ValueError:  # an unsafe report id resolves to "artifact missing"
            pass
    return {
        "pipeline_id": pipeline_id,
        "mode": pipeline_state.mode,
        "status": pipeline_state.status,
        "report_id": pipeline_state.report_id,
        "simulation_id": pipeline_state.simulation_id,
        "scored_by": "pipeline" if state is not None else "backfill",
        "graph_prune_expected": bool(options.get("graph_prune")) or "graph_prune" in artifacts,
        "stage_status": {stage: (pipeline_state.stages[stage].status
                                 if stage in pipeline_state.stages else None)
                         for stage in STAGES},
        "paths": {name: path for name, path in paths.items() if path},
    }


def sidecar_path(pipeline_id: str) -> str:
    from .pipeline_orchestrator import PipelineManager

    return os.path.join(PipelineManager._dir(pipeline_id), SIDECAR_FILENAME)


def write_stage_scorecard(pipeline_id: str, state: Optional[Mapping[str, Any]] = None,
                          thresholds: Any = None) -> dict:
    """Resolve, build and atomically write ``<pipeline_dir>/stage_scorecard.json``.

    Returns the scorecard.  Unlike the builder this may raise (unknown pipeline,
    I/O failure); callers on the run path must catch.
    """
    from ..utils.atomic import write_json_atomic

    scorecard = build_stage_scorecard(resolve_inputs(pipeline_id, state=state), thresholds)
    write_json_atomic(sidecar_path(pipeline_id), scorecard, allow_nan=False)
    return scorecard
