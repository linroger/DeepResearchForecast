"""EVAL-18: slim per-pipeline cost card, config fingerprint and the compute-matched norm.

Pure helpers (no file, network or LLM access); the orchestrator and
``scripts/cost_card.py`` gather the durable inputs and write the card.

Config fingerprint
    :func:`config_fingerprint` describes the configuration that produced a run from
    pinned state only: the INFRA-7 run-shape hash (``options['run_shape_v1']['sha256']``,
    which already covers the result-affecting knobs and the depth / max_rounds /
    research_language options, so those knobs are not re-read here), the result-affecting
    fields of ``safety_policy_v1``, the research model/depth/engine and the ontology/graph
    provider pairs stamped in run.json, the report's producing provider pair (handed in by
    the report stage, never read from run.json: INFRA-7 restamps ``resolved.report`` only
    when the stage completes), the run options max_rounds / research_language, and the
    three forecast knobs no pin covers (FORECAST_ENSEMBLE_MODELS, FORECAST_MARKET_ANCHORING,
    PREDICTION_MARKETS_ENABLED). ``config_hash = 'sha256:' + canonical_json_sha256(fp)``.
    The report stage computes it exactly once, pins ``{config_hash, fingerprint}`` in
    ``options['config_hash_v1']`` and stamps the same hash on its ledger commit rows;
    :func:`build_cost_card` reuses that pin (``config.source == 'report_stage'``) and only
    recomputes it for runs that ended before the report stage or predate the pin
    (``config.source == 'recomputed'``). A ledger row and its pipeline's cost card
    therefore always join on the same hash, and the cost-quality join accrues
    prospectively as ledger rows resolve.

Cost card (``drf-cost-card/v1``)
    Tokens, calls and wall time first, USD secondary (list-price estimates; flat-rate plans
    are labelled through ``cost_basis``). Per-stage numbers come from run_telemetry.json's
    ``cumulative_by_stage`` (EVAL-17, summed across resumed attempts), else its ``by_stage``;
    the latter covers only the latest attempt when the file records a previous one
    (``attempts.scope == 'last_attempt_only'``). ``totals`` is the sum of the stage rows.
    ``completeness.reasons`` names every known gap in the metering; the card is complete
    only when there is none. No key contains the substring 'token': security.redact_secrets
    masks such keys, so token counts use a ``tok_`` prefix.

Compute-matched norm (the rule for any A/B)
    Compare two methods only at matched stage-level spend. A variant that wins while it
    spends more tokens in the stage under test has shown that it is more expensive, not
    that it is better. Before crediting a variant, check
    ``compute_matched(variant_card, control_card, stage)['matched']``: the variant's
    ``tok_total`` in that stage is within ``tol`` (default 15%) of the control's. When it is
    not matched, either equalise the budget (for example give the control as many samples
    as the variant) or report the result as a cost-quality trade-off, never as a win.
"""

from __future__ import annotations

import copy
import math
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping, Optional

from .canonical_json import canonical_json_sha256
from .telemetry import cost_is_estimated

COST_CARD_SCHEMA = "drf-cost-card/v1"
COST_CARD_FILENAME = "cost_card.json"
CONFIG_FINGERPRINT_VERSION = "drf-config-fingerprint/v1"
# ``state.options`` key of ``{"config_hash", "fingerprint"}``, pinned by the report stage.
CONFIG_HASH_OPTION = "config_hash_v1"
CONFIG_HASH_PREFIX = "sha256:"
CONFIG_SOURCE_PINNED = "report_stage"
CONFIG_SOURCE_RECOMPUTED = "recomputed"

# safety_policy_v1 fields that change a forecast (origin / pinned_at are provenance).
SAFETY_POLICY_FIELDS = ("n_forecast_seeds", "report_spine_selfconsistency_k",
                        "ensemble_extremize_a", "simulation_forecast_effect")
# (fingerprint key, Config attribute): forecast knobs neither admission pin covers.
FORECAST_KNOBS = (("ensemble_models", "FORECAST_ENSEMBLE_MODELS"),
                  ("market_anchoring", "FORECAST_MARKET_ANCHORING"),
                  ("prediction_markets_enabled", "PREDICTION_MARKETS_ENABLED"))

# Summed into ``totals``; ``cost_basis`` is a label, not a sum.
STAGE_FIELDS = ("calls", "tok_in", "tok_in_cache_read", "tok_out", "tok_total", "wall_s", "usd")
STAGE_ORDER = ("research", "ontology", "graph", "prepare", "run", "report",
               "ensemble", "ensemble_sim")
# LLM stages whose execution must leave metered calls (the RUN stage's calls happen in the
# simulation subprocess and are folded in from its sim_llm_telemetry.json).
METERED_STAGES = ("research", "run", "report")
# pipeline_orchestrator.SIM_METER_STAGE_ENSEMBLE: the stage seed simulations are metered on.
SEED_SIM_STAGE = "ensemble_sim"
ESTIMATED_COST_SHARE_LIMIT = 0.2
COMPUTE_MATCH_TOL = 0.15

SCOPE_CUMULATIVE = "cumulative"
SCOPE_LAST_ATTEMPT_ONLY = "last_attempt_only"


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _plain(value: Any) -> Any:
    """A canonical-JSON-safe scalar: None/bool/int/str as is, a finite float as is, else str."""
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else repr(value)
    return str(value)


def _provider_pair(block: Any) -> dict[str, Any]:
    pair = _mapping(block)
    return {"provider": _plain(pair.get("provider")), "model_name": _plain(pair.get("model_name"))}


def _count(value: Any) -> int:
    """A non-negative integer counter; anything unreadable counts as 0."""
    try:
        number = int(value or 0)
    except (TypeError, ValueError, OverflowError):
        return 0
    return max(0, number)


def _amount(value: Any) -> float:
    """A non-negative finite amount (USD, seconds); anything unreadable counts as 0.0."""
    try:
        number = float(value or 0.0)
    except (TypeError, ValueError, OverflowError):
        return 0.0
    return number if math.isfinite(number) and number > 0 else 0.0


def _default_config() -> Any:
    from ..config import Config
    return Config


def config_fingerprint(options: Any, run_manifest: Any, *, report_producer: Any = None,
                       config: Any = None) -> dict[str, Any]:
    """The configuration fingerprint of one run (see the module docstring).

    ``options`` is ``state.options``; ``run_manifest`` the parsed run.json (None when
    missing); ``report_producer`` the ``{provider, model_name}`` pair producing the report
    (None: no report, or an unknown producer); ``config`` defaults to ``app.config.Config``.
    Missing inputs are recorded as None, so a fingerprint is always produced.
    """
    opts = _mapping(options)
    resolved = _mapping(_mapping(run_manifest).get("resolved"))
    research = _mapping(resolved.get("research"))
    shape = _mapping(opts.get("run_shape_v1"))
    safety = _mapping(opts.get("safety_policy_v1"))
    engine = (research.get("engine")
              or _mapping(shape.get("provenance")).get("research_engine")
              or _mapping(opts.get("actor_intelligence_policy_v1")).get("research_engine"))
    cfg = config if config is not None else _default_config()
    return {
        "version": CONFIG_FINGERPRINT_VERSION,
        "run_shape_sha256": _plain(shape.get("sha256")),
        "safety_policy": {name: _plain(safety.get(name)) for name in SAFETY_POLICY_FIELDS},
        "research": {
            "model": _plain(research.get("model")),
            "depth": _plain(research.get("depth")),
            "engine": _plain(engine),
        },
        "ontology": _provider_pair(resolved.get("ontology")),
        "graph": _provider_pair(resolved.get("graph")),
        "report": _provider_pair(report_producer),
        "options": {
            "max_rounds": _plain(opts.get("max_rounds")),
            "research_language": _plain(opts.get("research_language")),
        },
        "forecast": {key: _plain(getattr(cfg, attr, None)) for key, attr in FORECAST_KNOBS},
    }


def config_hash(fingerprint: Mapping[str, Any]) -> str:
    """``'sha256:' + canonical_json_sha256(fingerprint)`` (order-invariant)."""
    return CONFIG_HASH_PREFIX + canonical_json_sha256(fingerprint)


def config_hash_record(options: Any, run_manifest: Any, *, report_producer: Any = None,
                       config: Any = None) -> dict[str, Any]:
    """The ``options['config_hash_v1']`` value: ``{"config_hash", "fingerprint"}``."""
    fingerprint = config_fingerprint(options, run_manifest, report_producer=report_producer,
                                     config=config)
    return {"config_hash": config_hash(fingerprint), "fingerprint": fingerprint}


def pinned_config_hash(options: Any) -> Optional[str]:
    """The config_hash pinned in ``options['config_hash_v1']``, or None.

    None when there is no pin, or when the stored hash does not match its stored
    fingerprint (a damaged pin is never stamped or reused). Never raises.
    """
    record = _mapping(_mapping(options).get(CONFIG_HASH_OPTION))
    stored = record.get("config_hash")
    fingerprint = record.get("fingerprint")
    if not isinstance(stored, str) or not isinstance(fingerprint, dict):
        return None
    try:
        return stored if config_hash(fingerprint) == stored else None
    except (TypeError, ValueError):
        return None


def resolve_config(options: Any, run_manifest: Any, *,
                   config: Any = None) -> tuple[dict[str, Any], str]:
    """``(card config block, config_hash)``: the report stage's pin when present, else a
    recomputation without a report producer (the run never reached the report stage)."""
    pinned = pinned_config_hash(options)
    if pinned is not None:
        fingerprint = copy.deepcopy(options[CONFIG_HASH_OPTION]["fingerprint"])
        return {"source": CONFIG_SOURCE_PINNED, "fingerprint": fingerprint}, pinned
    fingerprint = config_fingerprint(options, run_manifest, config=config)
    return ({"source": CONFIG_SOURCE_RECOMPUTED, "fingerprint": fingerprint},
            config_hash(fingerprint))


def _ordered_stages(names: Iterable[str]) -> list[str]:
    present = set(names)
    known = [name for name in STAGE_ORDER if name in present]
    return known + sorted(name for name in present if name not in STAGE_ORDER)


def _stage_counters(run_telemetry: Mapping[str, Any]) -> tuple[Mapping[str, Any], str]:
    """(per-stage counters, attempts scope) from a parsed run_telemetry.json."""
    cumulative = run_telemetry.get("cumulative_by_stage")
    if isinstance(cumulative, Mapping):
        return cumulative, SCOPE_CUMULATIVE
    resumed = isinstance(run_telemetry.get("previous_attempt"), Mapping)
    return (_mapping(run_telemetry.get("by_stage")),
            SCOPE_LAST_ATTEMPT_ONLY if resumed else SCOPE_CUMULATIVE)


def _stage_row(counter: Any, wall_s: float, cost_basis: Optional[str]) -> dict[str, Any]:
    c = _mapping(counter)
    calls = _count(c.get("calls"))
    tok_in = _count(c.get("prompt_tokens"))
    tok_out = _count(c.get("completion_tokens"))
    return {
        "calls": calls,
        "tok_in": tok_in,
        "tok_in_cache_read": _count(c.get("prompt_cache_read_tokens")),
        "tok_out": tok_out,
        "tok_total": tok_in + tok_out,
        "wall_s": round(wall_s, 1),
        "usd": round(_amount(c.get("cost_usd")), 6),
        # The meter keeps providers per model, not per stage: the attempt-level basis.
        "cost_basis": cost_basis if calls else None,
    }


def _sum_stages(stages: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    totals: dict[str, Any] = {field: sum(row[field] for row in stages.values())
                              for field in STAGE_FIELDS}
    totals["wall_s"] = round(totals["wall_s"], 1)
    totals["usd"] = round(totals["usd"], 6)
    return totals


def _executed_stages(options: Mapping[str, Any], stage_status: Any) -> set[str]:
    """Stages that ran (not reused) in some attempt.

    INFRA-7's ``stage_reuse_v1`` decides for every stage it recorded (an execution is a
    ``reused: false`` row); a stage with no recorded decision counts as executed when its
    status is ``completed``.
    """
    decided: set[str] = set()
    executed: set[str] = set()
    decisions = options.get("stage_reuse_v1")
    for row in decisions if isinstance(decisions, list) else []:
        if isinstance(row, Mapping) and isinstance(row.get("stage"), str):
            decided.add(row["stage"])
            if row.get("reused") is False:
                executed.add(row["stage"])
    for stage, status in _mapping(stage_status).items():
        if status == "completed" and stage not in decided:
            executed.add(str(stage))
    return executed


def _estimated_cost_share(by_model: Any) -> Optional[float]:
    """Share of metered tokens priced by an estimated or unknown rate (latest attempt's
    by_model; the meter keeps no cross-attempt per-model split). None without volume."""
    total = estimated = 0
    for key, counter in _mapping(by_model).items():
        tokens = _count(_mapping(counter).get("total_tokens"))
        total += tokens
        if cost_is_estimated(str(key).split(":", 1)[0]):
            estimated += tokens
    return round(estimated / total, 4) if total else None


def _seed_count(safety: Mapping[str, Any]) -> Optional[int]:
    seeds = safety.get("n_forecast_seeds")
    if isinstance(seeds, bool) or not isinstance(seeds, int):
        return None
    return seeds


def _completeness_reasons(*, run_telemetry: Mapping[str, Any], stages: Mapping[str, Any],
                          scope: str, walls: Mapping[str, float], options: Mapping[str, Any],
                          stage_status: Any, unattributed: Mapping[str, Optional[int]],
                          estimated_share: Optional[float]) -> list[str]:
    reasons: list[str] = []
    if not run_telemetry:
        reasons.append("run_telemetry_missing")
    elif run_telemetry.get("in_flight"):
        # The final flush never landed: the file is a mid-attempt snapshot.
        reasons.append("run_telemetry_in_flight")
    if scope == SCOPE_LAST_ATTEMPT_ONLY:
        reasons.append(SCOPE_LAST_ATTEMPT_ONLY)
    else:
        # Under last_attempt_only a stage executed in an earlier attempt shows no calls
        # without being unmetered, so this check needs cumulative numbers.
        executed = _executed_stages(options, stage_status)
        for stage in METERED_STAGES:
            if stage in executed and not _mapping(stages.get(stage)).get("calls"):
                reasons.append(f"unmetered_stage:{stage}")
    if run_telemetry.get("cumulative_by_stage_partial"):
        reasons.append("cumulative_by_stage_partial")
    seeds = _seed_count(_mapping(options.get("safety_policy_v1")))
    ensemble_entered = (bool(_mapping(options.get("ensemble_wall")).get("started_at"))
                        or "ensemble" in walls)
    if (ensemble_entered and (seeds is None or seeds > 1)
            and not _mapping(stages.get(SEED_SIM_STAGE)).get("calls")):
        reasons.append(f"seeds_without_ensemble_sim:n_forecast_seeds={seeds}")
    start, end = unattributed.get("calls_at_attempt_start"), unattributed.get("calls_at_end")
    if end is not None:
        if start is not None:
            if end > start:
                reasons.append(f"unattributed_process_growth:+{end - start}")
        elif end > 0:
            reasons.append(f"unattributed_process_unknown_baseline:{end}")
    if estimated_share is not None and estimated_share > ESTIMATED_COST_SHARE_LIMIT:
        reasons.append(f"estimated_cost_share:{estimated_share}")
    return reasons


def _baseline_calls(value: Any) -> Optional[int]:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


def build_cost_card(*, pipeline_id: str, mode: Optional[str], run_telemetry: Any,
                    stage_walls: Any, run_manifest: Any, options: Any,
                    status: Optional[str] = None, stage_status: Any = None,
                    unattributed_calls_at_start: Optional[int] = None,
                    created_at: Optional[str] = None, config: Any = None) -> dict[str, Any]:
    """The ``drf-cost-card/v1`` card of one pipeline.

    ``run_telemetry`` / ``run_manifest`` are the parsed run_telemetry.json / run.json (None
    when missing), ``stage_walls`` ``{stage: seconds}``, ``options`` the pipeline's options,
    ``stage_status`` ``{stage: status}`` and ``unattributed_calls_at_start`` the process-wide
    unattributed LLM calls when the attempt started (None: unknown). Never raises on
    malformed inputs: unreadable numbers count as 0 and gaps become completeness reasons.
    """
    tel = _mapping(run_telemetry)
    opts = _mapping(options)
    config_block, chash = resolve_config(opts, run_manifest, config=config)
    counters, scope = _stage_counters(tel)
    walls: dict[str, float] = {str(name): _amount(seconds)
                               for name, seconds in _mapping(stage_walls).items()}
    basis = tel.get("cost_basis") if isinstance(tel.get("cost_basis"), str) else None
    stages = {name: _stage_row(counters.get(name), walls.get(name, 0.0), basis)
              for name in _ordered_stages(set(counters) | set(walls))}
    totals = _sum_stages(stages)
    totals["cost_basis"] = basis if totals["calls"] else None
    research = stages.get("research") or {}
    cache_ratio = (round(research["tok_in_cache_read"] / research["tok_in"], 4)
                   if research.get("tok_in") else None)
    unattributed_process = tel.get("unattributed_process")
    unattributed = {
        "calls_at_attempt_start": _baseline_calls(unattributed_calls_at_start),
        "calls_at_end": (_count(unattributed_process.get("calls"))
                         if isinstance(unattributed_process, Mapping) else None),
    }
    estimated_share = _estimated_cost_share(tel.get("by_model"))
    reasons = _completeness_reasons(
        run_telemetry=tel, stages=stages, scope=scope, walls=walls, options=opts,
        stage_status=stage_status, unattributed=unattributed, estimated_share=estimated_share)
    return {
        "schema": COST_CARD_SCHEMA,
        "pipeline_id": str(pipeline_id),
        "mode": mode,
        "status": status,
        "repo_git_sha": _plain(_mapping(run_manifest).get("repo_git_sha")),
        "created_at": created_at or datetime.now(timezone.utc).isoformat(),
        "config": config_block,
        "config_hash": chash,
        "stages": stages,
        "totals": totals,
        "research_cache_hit_ratio": cache_ratio,
        "attempts": {"scope": scope,
                     "resumed": isinstance(tel.get("previous_attempt"), Mapping)},
        "lineage": {"base_pipeline_id": _plain(opts.get("base_pipeline_id")) or None},
        "unattributed_process": unattributed,
        "completeness": {"complete": not reasons, "reasons": reasons,
                         "estimated_cost_share": estimated_share},
    }


def _stage_spend(card: Any, stage: str, label: str) -> int:
    if not isinstance(card, Mapping) or card.get("schema") != COST_CARD_SCHEMA:
        raise ValueError(f"{label} is not a {COST_CARD_SCHEMA} card")
    return _count(_mapping(_mapping(card.get("stages")).get(stage)).get("tok_total"))


def compute_matched(variant_card: Any, control_card: Any, stage: str,
                    tol: float = COMPUTE_MATCH_TOL) -> dict[str, Any]:
    """Whether two runs spent comparable tokens in ``stage`` (the A/B norm, module docstring).

    Returns ``{matched, variant_tok, control_tok, rel_gap}`` where ``rel_gap`` is the signed
    ``(variant - control) / control`` (None when only the variant spent anything) and
    ``matched`` is ``|variant - control| <= tol * control``; two runs that spent nothing in
    the stage are matched. A stage missing from a card spent 0. Raises ValueError for a
    negative or non-finite ``tol`` or an input that is not a cost card.
    """
    try:
        tolerance = float(tol)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"tol must be a number, got {tol!r}") from exc
    if not math.isfinite(tolerance) or tolerance < 0:
        raise ValueError(f"tol must be finite and >= 0, got {tol!r}")
    variant = _stage_spend(variant_card, stage, "variant_card")
    control = _stage_spend(control_card, stage, "control_card")
    if control:
        rel_gap: Optional[float] = round((variant - control) / control, 4)
        matched = abs(variant - control) <= tolerance * control
    else:
        rel_gap = None if variant else 0.0
        matched = not variant
    return {"matched": matched, "variant_tok": variant, "control_tok": control,
            "rel_gap": rel_gap}
