"""Run-shape admission pin, drift diff and resume-lineage rules (INFRA-7).

A pipeline resumes by artifact: every completed stage whose outputs still
validate is reused.  Two things could silently mix configurations across
attempts:

* the result-affecting knobs (cast size, graph cap, temporal mode, forecast
  floors, ...) are read from the ambient ``Config`` of whichever process runs
  the attempt, so a resume after an env edit builds the remaining stages
  under different settings than the reused ones;
* a stage recomputed on resume does not by itself invalidate the downstream
  artifacts that were derived from its previous output (only PREPARE -> RUN
  cascaded).

This module is the pure half of the fix.  ``pin`` snapshots the knobs a run
was admitted with (the second admission snapshot next to the orchestrator's
``safety_policy_v1``; knobs pinned there are deliberately not repeated here),
``diff`` compares a pin with the current ambient values, and
``lineage_refusal`` decides whether a stage may reuse its artifact given what
was recomputed earlier in the same attempt.  The orchestrator owns the thin
hooks that call these helpers; nothing here does I/O.
"""

from __future__ import annotations

import copy
import math
from typing import Any, Iterable, Mapping, Optional

from ..utils.canonical_json import canonical_json_sha256

RUN_SHAPE_VERSION = "run-shape/v1"

ORIGIN_ADMISSION = "admission"
ORIGIN_RESUME_UNPINNED = "resume_unpinned"
ORIGIN_FORK = "fork"

# Result-affecting Config knobs.  A missing attribute is recorded as None so an
# older or trimmed Config never breaks capture.  SIM_GRAPH_FEEDBACK,
# N_FORECAST_SEEDS, ENSEMBLE_EXTREMIZE_A and the other containment flags are
# already pinned by ``safety_policy_v1`` and are intentionally absent.
IDENTITY_KNOBS: tuple[str, ...] = (
    "ACTOR_CAST_MAX",
    "ACTOR_EXCLUDE_MEDIA",
    "ONTOLOGY_TEMPLATE",
    "GRAPH_CHUNK_SOURCE",
    "GRAPH_MAX_ENTITIES",
    "GRAPH_PRUNE_ENABLED",
    "SIM_TEMPORAL_MODE",
    "SIM_CALENDAR_TARGET_MAX_ROUNDS",
    "SIM_CALENDAR_HARD_MAX_ROUNDS",
    "OASIS_DEFAULT_MAX_ROUNDS",
    "OASIS_MAX_AGENTS",
    "BINARY_FORECASTS_MIN_COUNT",
    "FORECAST_PROB_FLOOR",
    "REPORT_FORECAST_SPINE_FIRST",
)
# Per-run options pinned in ``state.options`` at admission.
IDENTITY_OPTIONS: tuple[str, ...] = ("depth", "max_rounds", "research_language")
# Provider/model identity is provenance: it is recorded and diffed, never a
# reason to refuse a resume (a provider outage must stay resumable elsewhere).
PROVENANCE_KNOBS: tuple[str, ...] = (
    "LLM_PROVIDER",
    "LLM_MODEL_NAME",
    "LLM_FAST_MODEL",
    "LLM_STRONG_MODEL",
)

DRIFT_POLICY_RECORD = "record"
DRIFT_POLICY_REFUSE = "refuse"
DRIFT_POLICIES: tuple[str, ...] = (DRIFT_POLICY_RECORD, DRIFT_POLICY_REFUSE)

DRIFT_HISTORY_CAP = 20
ATTEMPTS_CAP = 20
# Six stages per attempt across the ATTEMPTS_CAP most recent attempts.
STAGE_REUSE_LOG_CAP = 6 * ATTEMPTS_CAP
STAGE_NOTES_CAP = 20

# A stage's artifact is derived from these upstream stages' outputs; if one of
# them was recomputed earlier in the same attempt, the artifact is stale.
LINEAGE_UPSTREAM: dict[str, tuple[str, ...]] = {
    "ontology": ("research",),
    "graph": ("research", "ontology"),
    "prepare": ("graph",),
    "report": ("run",),
}
# The id each stage's reused artifact must be bound to, named for the refusal
# reason ("graph_id_mismatch", "simulation_id_mismatch").
_BOUND_ID_LABEL: dict[str, str] = {
    "prepare": "graph_id",
    "report": "simulation_id",
}
# Batch question forks (scripts/batch_runs.py::fork_question) regenerate the
# ontology around each question while intentionally keeping the anchor's graph
# ("same evidence, different question").  The fork declares that design choice
# in ``state.options[SHARED_GRAPH_OPTION]`` so the graph guard does not treat
# the per-question ontology as a stale upstream.
SHARED_GRAPH_OPTION = "graph_shared_from_base"

# run.json ``resolved`` block owned by each pipeline stage, and the blocks whose
# only content is the provider/model pair that produced the stage.
RESOLVED_BLOCK_FOR_STAGE: dict[str, str] = {
    "research": "research",
    "ontology": "ontology",
    "graph": "graph",
    "run": "simulation",
    "report": "report",
}
PROVIDER_STAMPED_STAGES: tuple[str, ...] = ("ontology", "graph", "report")
# Filled while RUN executes (not at attempt start); a restamp keeps them.
SIM_RUNTIME_FIELDS: tuple[str, ...] = (
    "total_rounds", "calendar_unit", "n_rounds", "horizon_date",
)


def _plain(value: Any) -> Any:
    """Coerce a knob value into canonical-JSON-safe form deterministically."""
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else repr(value)
    return str(value)


def capture(
    config: Any,
    options: Optional[Mapping[str, Any]],
    *,
    research_engine: Optional[str] = None,
) -> dict[str, Any]:
    """Snapshot the run shape: identity knobs/options plus provenance.

    ``research_engine`` is the effective engine the orchestrator resolved for
    this run; without it the raw ``RESEARCH_ENGINE`` value is recorded.  The
    ``sha256`` covers the identity section only, so provenance drift (a
    provider switch) never changes the run's shape fingerprint.
    """
    opts = options if isinstance(options, Mapping) else {}
    identity: dict[str, Any] = {
        name: _plain(getattr(config, name, None)) for name in IDENTITY_KNOBS
    }
    for name in IDENTITY_OPTIONS:
        identity[name] = _plain(opts.get(name))
    provenance: dict[str, Any] = {
        name: _plain(getattr(config, name, None)) for name in PROVENANCE_KNOBS
    }
    provenance["research_model"] = _plain(
        opts.get("research_model") or getattr(config, "DEERFLOW_MODEL", None))
    if research_engine is None:
        raw_engine = str(getattr(config, "RESEARCH_ENGINE", "") or "").strip().lower()
        research_engine = raw_engine or None
    provenance["research_engine"] = _plain(research_engine)
    return {
        "version": RUN_SHAPE_VERSION,
        "identity": identity,
        "provenance": provenance,
        "sha256": canonical_json_sha256(identity),
    }


def pin(
    config: Any,
    options: Optional[Mapping[str, Any]],
    *,
    origin: str,
    pinned_at: str,
    research_engine: Optional[str] = None,
) -> dict[str, Any]:
    """``capture`` plus how and when the pin came to exist."""
    shape = capture(config, options, research_engine=research_engine)
    shape["origin"] = str(origin)
    shape["pinned_at"] = str(pinned_at)
    return shape


def _section_diff(pinned: Any, current: Any) -> dict[str, list[Any]]:
    """Changed keys as ``{key: [pinned, current]}``.

    Only keys present on both sides are compared: a key the pin lacks has no
    admission value to drift from, and a key no longer captured is no longer
    a knob.
    """
    if not isinstance(pinned, Mapping) or not isinstance(current, Mapping):
        return {}
    return {
        key: [pinned[key], current[key]]
        for key in sorted(pinned)
        if key in current and pinned[key] != current[key]
    }


def diff(pinned: Any, current: Any) -> dict[str, dict[str, list[Any]]]:
    """Identity and provenance drift between a pin and a fresh capture."""
    pinned_map = pinned if isinstance(pinned, Mapping) else {}
    current_map = current if isinstance(current, Mapping) else {}
    return {
        "identity": _section_diff(pinned_map.get("identity"), current_map.get("identity")),
        "provenance": _section_diff(
            pinned_map.get("provenance"), current_map.get("provenance")),
    }


def has_drift(drift: Any) -> bool:
    if not isinstance(drift, Mapping):
        return False
    return bool(drift.get("identity") or drift.get("provenance"))


def drifted_knobs(drift: Any) -> list[str]:
    """Sorted names of every drifted identity and provenance entry."""
    if not isinstance(drift, Mapping):
        return []
    names: set[str] = set()
    for section in ("identity", "provenance"):
        block = drift.get(section)
        if isinstance(block, Mapping):
            names.update(str(key) for key in block)
    return sorted(names)


def resolve_drift_policy(raw: Any) -> tuple[str, bool]:
    """Normalise RUN_SHAPE_DRIFT_POLICY; unknown values fall back to record.

    Returns ``(policy, valid)`` so the caller can warn about a typo instead of
    silently refusing (or silently accepting) every resume.
    """
    text = str(raw if raw is not None else "").strip().lower()
    if text in DRIFT_POLICIES:
        return text, True
    return DRIFT_POLICY_RECORD, False


def refuses(policy: str, drift: Any) -> bool:
    """Only identity drift under the refuse policy blocks an attempt."""
    if policy != DRIFT_POLICY_REFUSE or not isinstance(drift, Mapping):
        return False
    return bool(drift.get("identity"))


def refusal_message(drift: Mapping[str, Any]) -> str:
    identity = drift.get("identity") if isinstance(drift, Mapping) else None
    changes = "; ".join(
        f"{name}: {pair[0]!r} -> {pair[1]!r}"
        for name, pair in sorted((identity or {}).items())
    )
    return (
        "run-shape drift refused (RUN_SHAPE_DRIFT_POLICY=refuse): identity knobs "
        f"changed since admission [{changes}]. Restore the admission values, or set "
        "RUN_SHAPE_DRIFT_POLICY=record to resume with the drift disclosed."
    )


def lineage_refusal(
    stage: str,
    recomputed: Iterable[str],
    *,
    bound_ids: Optional[tuple[Any, Any]] = None,
    exempt: Iterable[str] = (),
) -> Optional[str]:
    """Why ``stage`` must not reuse its artifact this attempt, or None.

    ``bound_ids`` is ``(id the artifact was built against, current id)`` for
    PREPARE (simulation graph vs pipeline graph) and REPORT (report
    simulation vs pipeline simulation); an unset bound id cannot prove lineage
    and refuses.  ``exempt`` lists upstream stages whose recompute is a
    declared design choice rather than staleness.
    """
    if bound_ids is not None:
        bound, current = bound_ids
        if not bound or bound != current:
            return f"{_BOUND_ID_LABEL.get(stage, 'artifact_id')}_mismatch"
    recomputed_set = set(recomputed or ())
    skipped = set(exempt or ())
    for upstream in LINEAGE_UPSTREAM.get(stage, ()):
        if upstream in recomputed_set and upstream not in skipped:
            return f"{upstream}_recomputed"
    return None


def graph_lineage_exempt(options: Any) -> tuple[str, ...]:
    """Upstream stages the GRAPH guard ignores for this run."""
    if isinstance(options, Mapping) and options.get(SHARED_GRAPH_OPTION):
        return ("ontology",)
    return ()


def carry_forward_resolved(prior: Any, fresh: Any) -> dict[str, Any]:
    """Start an attempt's ``resolved`` section from the previous run.json.

    Every stage block the previous attempt wrote is kept, so a stage that is
    reused this attempt keeps the provider/model stamp of the attempt that
    produced it.  Blocks the previous manifest lacks come from ``fresh``.
    Stages recomputed this attempt are restamped by ``stamp_resolved_stage``.
    """
    out = copy.deepcopy(fresh) if isinstance(fresh, Mapping) else {}
    if not isinstance(prior, Mapping):
        return dict(out)
    for block_name in RESOLVED_BLOCK_FOR_STAGE.values():
        block = prior.get(block_name)
        if isinstance(block, Mapping):
            out[block_name] = copy.deepcopy(dict(block))
    return dict(out)


def stamp_resolved_stage(
    resolved: dict[str, Any],
    stage: str,
    *,
    fresh: Any,
    provider: Mapping[str, Any],
) -> bool:
    """Restamp the ``resolved`` block of a stage recomputed this attempt.

    Provider-stamped stages take the provider pair current at completion;
    research and simulation take the attempt's fresh block (the simulation
    block keeps the runtime fields RUN wrote this attempt).  Returns whether a
    block was written.
    """
    block_name = RESOLVED_BLOCK_FOR_STAGE.get(stage)
    if block_name is None:
        return False
    if stage in PROVIDER_STAMPED_STAGES:
        resolved[block_name] = dict(provider)
        return True
    fresh_map = fresh if isinstance(fresh, Mapping) else {}
    fresh_block = fresh_map.get(block_name)
    block = copy.deepcopy(dict(fresh_block)) if isinstance(fresh_block, Mapping) else {}
    if block_name == "simulation":
        existing = resolved.get("simulation")
        if isinstance(existing, Mapping):
            for key in SIM_RUNTIME_FIELDS:
                if existing.get(key) is not None:
                    block[key] = existing[key]
    resolved[block_name] = block
    return True


def attempt_record(started_at: str, pinned: Any, drift: Any) -> dict[str, Any]:
    """One run.json ``attempts`` entry.

    The drifted names live under ``drift_knobs``: run.json passes through
    ``redact_secrets``, which masks any key ending in ``_keys``.
    """
    sha = pinned.get("sha256") if isinstance(pinned, Mapping) else None
    return {
        "started_at": started_at,
        "run_shape_sha256": sha,
        "drift_knobs": drifted_knobs(drift),
    }


def append_capped(items: Any, entry: Any, cap: int) -> list[Any]:
    """Append to a list-valued record, keeping only the newest ``cap`` rows."""
    rows = list(items) if isinstance(items, list) else []
    rows.append(entry)
    return rows[-cap:] if cap > 0 else rows
