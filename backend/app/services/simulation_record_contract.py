"""Contract for the Simulation After-Action Record (``simulation-record/v1``).

ADR 0003 makes simulation output a ``simulated`` record class that reaches the
forecast report only through one deterministic, fenced bridge section.  This
module is the shared anchor for the three parties that must agree on the
record's shape without seeing each other's code:

* the Stage 5 compiler (``simulation_record.py``) that writes it,
* the deterministic gate (``simulation_record_gate.py``) that audits it, and
* the Stage 6 bridge renderer in ``report_agent`` that reads it.

It deliberately contains no I/O beyond locating and loading the files, no
LLM calls and no imports from the research or report planes.  Field-level
semantics are in docs/handoff/simulation-after-action-record/design.md §4;
the gate's checks G1–G9 are in §3.2.

Invariants the compiler MUST honour (the gate checks them):

* ``record_class == "simulated"`` and ``epistemic_status == "elicited_model_projection"``.
* ``banner`` is byte-equal to ``sim_provenance.SIM_BANNER_EN`` or ``SIM_BANNER_ZH``
  according to ``language``.
* ``periods`` has exactly one entry per committed round, in round order.
* No ``[S#]`` / ``【S#】`` citation marker anywhere in the record text.
* No text taken from ``world_actions.jsonl``'s ``private_rationale`` field.
* Per-period sections carry no scenario shares; shares live only under ``overall``.
* Every quoted statement is a substring of a stored ``public_statement``.
"""
from __future__ import annotations

import json
import os
from typing import Any, Dict, Final, List, Optional

from . import sim_provenance as _sp

SCHEMA: Final = _sp.RECORD_SCHEMA                      # "simulation-record/v1"
RECORD_CLASS: Final = _sp.RECORD_CLASS                 # "simulated"
EPISTEMIC_STATUS: Final = _sp.EPISTEMIC_STATUS         # "elicited_model_projection"

# File names under uploads/simulations/<sim_id>/
RECORD_JSON: Final = "simulation_record.json"
RECORD_MD: Final = "simulation_record.md"
RECORD_MD_ZH: Final = "simulation_record.zh.md"
RECORD_AUDIT_JSON: Final = "simulation_record_audit.json"

ENGINES: Final = ("oasis-reflexive", "world-v1", "oasis-inband", "oasis-hours")
HEALTH_STUB_VALUES: Final = frozenset({"hollow", "errored", "truncated"})
GENERATORS: Final = ("deterministic", "llm")
PUBLICATION_STATUSES: Final = ("passed", "failed", "not_audited")

# Fields the compiler may read from a world_actions.jsonl row.  ``private_rationale``
# is excluded by allowlist, never filtered after the fact.
ACTION_PUBLIC_FIELDS: Final = frozenset({
    "round", "period_end", "period_label", "agent_id", "actor_name", "option", "targets",
    "magnitude", "public_statement", "terms", "commitment", "alliance_moves",
    "expected_reactions", "scenario", "scenario_confidence", "status",
})

# Top-level keys, in the order the renderer emits them.
TOP_LEVEL_KEYS: Final = (
    "schema", "record_class", "epistemic_status", "simulation_id", "pipeline_id",
    "config_hash", "engine", "language", "as_of", "horizon_date", "calendar_unit",
    "rounds_planned", "rounds_committed", "health", "banner", "setup", "periods",
    "overall", "limits", "entities_declared", "generated_at", "generator_version",
)
_OPTIONAL_TOP_LEVEL: Final = ("pipeline_id", "config_hash", "as_of", "horizon_date", "calendar_unit")
REQUIRED_TOP_LEVEL: Final = frozenset(k for k in TOP_LEVEL_KEYS if k not in _OPTIONAL_TOP_LEVEL)

PERIOD_KEYS: Final = (
    "round", "label", "period_start", "period_end", "arbiter_status", "arbiter_problems",
    "narrative", "moves", "held_position", "facts_changed", "events", "shocks_fired",
    "red_lines_crossed", "offers", "alliances", "behaviour", "refs",
)
REQUIRED_PERIOD_KEYS: Final = frozenset({"round", "label", "arbiter_status", "narrative",
                                        "moves", "facts_changed", "events", "refs"})

HEALTH_KEYS: Final = ("simulation_health", "validity", "arbiter_failed_rounds",
                      "seed_gaps", "organic_actions")
OVERALL_KEYS: Final = ("final_variables", "shares", "turning_points", "track_records", "synthesis")


class RecordContractError(ValueError):
    """The record does not satisfy the structural contract."""


def record_paths(sim_dir: str) -> Dict[str, str]:
    """Absolute paths of the record files for a simulation directory."""
    return {
        "json": os.path.join(sim_dir, RECORD_JSON),
        "md": os.path.join(sim_dir, RECORD_MD),
        "md_zh": os.path.join(sim_dir, RECORD_MD_ZH),
        "audit": os.path.join(sim_dir, RECORD_AUDIT_JSON),
    }


def banner_for(language: str) -> str:
    return _sp.SIM_BANNER_ZH if str(language or "").lower().startswith("zh") else _sp.SIM_BANNER_EN


def validate_shape(record: Any) -> List[str]:
    """Structural checks only (the gate adds fidelity checks).  Returns a list of
    problems; an empty list means the shape is valid.  Never raises on bad input."""
    problems: List[str] = []
    if not isinstance(record, dict):
        return ["record is not an object"]
    for key in sorted(REQUIRED_TOP_LEVEL):
        if key not in record:
            problems.append(f"missing top-level key: {key}")
    if record.get("schema") != SCHEMA:
        problems.append(f"schema must be {SCHEMA!r}")
    if record.get("record_class") != RECORD_CLASS:
        problems.append(f"record_class must be {RECORD_CLASS!r}")
    if record.get("epistemic_status") != EPISTEMIC_STATUS:
        problems.append(f"epistemic_status must be {EPISTEMIC_STATUS!r}")
    if record.get("engine") not in ENGINES:
        problems.append(f"engine must be one of {ENGINES}")
    lang = str(record.get("language") or "")
    if record.get("banner") != banner_for(lang):
        problems.append("banner is not byte-equal to the sim_provenance banner for its language")
    health = record.get("health")
    if not isinstance(health, dict) or any(k not in health for k in HEALTH_KEYS):
        problems.append(f"health must carry {HEALTH_KEYS}")
    periods = record.get("periods")
    committed = record.get("rounds_committed")
    if not isinstance(periods, list):
        problems.append("periods must be a list")
    else:
        if isinstance(committed, int) and len(periods) != committed:
            problems.append(f"periods has {len(periods)} entries for {committed} committed rounds")
        rounds = [p.get("round") for p in periods if isinstance(p, dict)]
        ints = [r for r in rounds if isinstance(r, int)]
        if len(ints) != len(rounds) or ints != sorted(ints) or len(set(ints)) != len(ints):
            problems.append("periods must carry integer rounds in order without duplicates")
        for i, p in enumerate(periods):
            if not isinstance(p, dict):
                problems.append(f"periods[{i}] is not an object")
                continue
            for key in sorted(REQUIRED_PERIOD_KEYS):
                if key not in p:
                    problems.append(f"periods[{i}] missing {key}")
            if "shares" in p:
                problems.append(f"periods[{i}] carries scenario shares (allowed only under overall)")
    overall = record.get("overall")
    if not isinstance(overall, dict) or any(k not in overall for k in OVERALL_KEYS):
        problems.append(f"overall must carry {OVERALL_KEYS}")
    else:
        synth = overall.get("synthesis")
        if not isinstance(synth, dict) or synth.get("generator") not in GENERATORS:
            problems.append(f"overall.synthesis.generator must be one of {GENERATORS}")
    if not isinstance(record.get("entities_declared"), list):
        problems.append("entities_declared must be a list")
    return problems


def load_record(sim_dir: str) -> Optional[Dict[str, Any]]:
    """Load ``simulation_record.json`` from a regular file, or None when absent or
    unreadable.  Symbolic links are refused, matching the world-state route."""
    path = record_paths(sim_dir)["json"]
    try:
        if os.path.islink(path) or not os.path.isfile(path):
            return None
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def load_audit(sim_dir: str) -> Optional[Dict[str, Any]]:
    """Load ``simulation_record_audit.json`` the same way."""
    path = record_paths(sim_dir)["audit"]
    try:
        if os.path.islink(path) or not os.path.isfile(path):
            return None
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def is_published(sim_dir: str) -> bool:
    """True only when an audit exists and passed; the report bridge links the record
    only in that case, and the API serves it only in that case."""
    audit = load_audit(sim_dir)
    return bool(audit) and audit.get("publication_status") == "passed" and not audit.get("hard_issues")
