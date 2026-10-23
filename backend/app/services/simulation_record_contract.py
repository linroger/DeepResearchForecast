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
import hashlib
import stat
import tempfile
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
ARTIFACT_FILES: Final = (
    "world_state.json", "world_state_history.jsonl", "world_digest.jsonl", "world_actions.jsonl",
    "decisions.jsonl", "world_state_trajectory.json", "world_paths.json", "run_summary.json",
    "simulation_config.json", "simulation_config_manifest.json", "actor_cast_manifest.json",
    "state.json", "world_result.json", "world_spec.json", "world_input_manifest.json",
    "world_result_manifest.json",
)

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


def record_bytes(record: Dict[str, Any]) -> bytes:
    return (json.dumps(record, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8")


def record_sha256(record: Dict[str, Any]) -> str:
    return hashlib.sha256(record_bytes(record)).hexdigest()


def public_world_result(result: Dict[str, Any]) -> Dict[str, Any]:
    """Keep only explicit public rows of a public world-v1 export.

    Analyst/actor projections are never record inputs. Missing visibility is
    private, matching world_simulation.contracts.visible_to.
    """
    if result.get("view") != "public":
        return {}

    def visible(row):
        return isinstance(row, dict) and isinstance(row.get("visibility"), dict) and row["visibility"].get("kind") == "public"

    def snapshot(row):
        if not isinstance(row, dict):
            return {}
        out = {k: row[k] for k in ("round", "simulatedAt") if k in row}
        for bucket in ("metrics", "rules", "interactions", "commitments"):
            values = row.get(bucket)
            out[bucket] = {k: v for k, v in values.items() if visible(v)} if isinstance(values, dict) else {}
        return out

    out = {k: result[k] for k in ("schemaVersion", "engine", "simulationId", "completed", "round",
                                "committedRound", "totalRounds", "asOf", "horizon", "view") if k in result}
    out["world"] = snapshot(result.get("world"))
    out["trajectory"] = [snapshot(row) for row in result.get("trajectory", []) if isinstance(row, dict)]
    out["events"] = [row for row in result.get("events", []) if visible(row)]
    return out


def world_result_validity(result: Dict[str, Any]) -> str:
    if not result:
        return "unknown"
    committed, planned = result.get("committedRound"), result.get("totalRounds")
    rows = result.get("trajectory", [])
    if (type(committed) is not int or type(planned) is not int or not 0 <= committed <= planned
            or planned <= 0 or result.get("round") != committed
            or not isinstance(rows, list) or len(rows) != committed + 1
            or any(not isinstance(row, dict) or type(row.get("round")) is not int or row["round"] != i
                   for i, row in enumerate(rows))):
        return "invalid"
    if result.get("completed") is True:
        return "valid" if committed == planned else "invalid"
    return "inconclusive"


def validate_shape(record: Any) -> List[str]:
    """Structural checks only (the gate adds fidelity checks).  Returns a list of
    problems; an empty list means the shape is valid.  Never raises on bad input."""
    problems: List[str] = []
    if not isinstance(record, dict):
        return ["record is not an object"]
    for key in sorted(REQUIRED_TOP_LEVEL):
        if key not in record:
            problems.append(f"missing top-level key: {key}")
    if set(record) - set(TOP_LEVEL_KEYS):
        problems.append("unknown top-level record fields")
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
    for key in ("rounds_planned", "rounds_committed"):
        if type(record.get(key)) is not int or record[key] < 0:
            problems.append(f"{key} must be a nonnegative integer")
    if record.get("language") not in ("en", "zh"):
        problems.append("language must be en or zh")
    for key in ("setup", "limits"):
        if not isinstance(record.get(key), dict):
            problems.append(f"{key} must be an object")
    if not isinstance(periods, list):
        problems.append("periods must be a list")
    else:
        if isinstance(committed, int) and len(periods) != committed:
            problems.append(f"periods has {len(periods)} entries for {committed} committed rounds")
        rounds = [p.get("round") for p in periods if isinstance(p, dict)]
        ints = [r for r in rounds if type(r) is int and r > 0]
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
            for key in ("moves", "facts_changed", "events", "refs", "held_position", "offers", "alliances",
                        "shocks_fired", "red_lines_crossed", "arbiter_problems"):
                if key in p and not isinstance(p[key], list):
                    problems.append(f"periods[{i}].{key} must be a list")
    overall = record.get("overall")
    if not isinstance(overall, dict) or any(k not in overall for k in OVERALL_KEYS):
        problems.append(f"overall must carry {OVERALL_KEYS}")
    else:
        synth = overall.get("synthesis")
        if not isinstance(synth, dict) or synth.get("generator") not in GENERATORS:
            problems.append(f"overall.synthesis.generator must be one of {GENERATORS}")
        elif (set(synth) != {"generator", "text", "claims"} or not isinstance(synth.get("text"), str)
              or not isinstance(synth.get("claims"), list)):
            problems.append("overall.synthesis must carry generator, text and claims")
        if set(overall) != set(OVERALL_KEYS):
            problems.append("overall must contain only the contract fields")
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


def read_regular(path: str) -> bytes:
    """Read a regular file without following symlinks, including directory aliases."""
    absolute = os.path.abspath(path)
    if os.path.realpath(absolute) != absolute:
        raise OSError("symlinked artifact path")
    fd = os.open(absolute, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise OSError("artifact is not a regular file")
        with os.fdopen(fd, "rb", closefd=False) as stream:
            return stream.read()
    finally:
        os.close(fd)


def artifact_hashes(sim_dir: str) -> Dict[str, Optional[str]]:
    """Bind both present and absent inputs so additions invalidate old audits too."""
    result = {}
    for name in ARTIFACT_FILES:
        path = os.path.join(sim_dir, name)
        try:
            raw = read_regular(path)
            if name == "state.json":
                # Lifecycle/status/updated_at are written after finalization.
                # Only these three state fields are consumed by the compiler.
                state = json.loads(raw)
                if not isinstance(state, dict):
                    raise ValueError("invalid state object")
                raw = record_bytes({key: state.get(key) for key in
                                    ("simulation_id", "pipeline_id", "simulation_engine")})
            result[name] = hashlib.sha256(raw).hexdigest()
        except FileNotFoundError:
            if os.path.lexists(path):
                raise OSError("unreadable artifact")
            result[name] = None
    return result


def atomic_write(path: str, data: bytes) -> None:
    """Replace an artifact without opening a predictable, possibly linked temp file."""
    parent = os.path.abspath(os.path.dirname(path))
    if os.path.realpath(parent) != parent:
        raise OSError("symlinked simulation directory")
    fd, temporary = tempfile.mkstemp(prefix=".simulation-record-", dir=parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def load_published_record(sim_dir: str):
    """Return (verified JSON snapshot, status). All publication consumers share this check.

    An old, incomplete or stale receipt cannot publish. Markdown and source inputs
    are bound as well as canonical JSON; callers must use this returned snapshot.
    """
    paths = record_paths(sim_dir)
    try:
        audit = json.loads(read_regular(paths["audit"]))
    except (OSError, ValueError):
        return None, "not_audited"
    if not isinstance(audit, dict) or audit.get("publication_status") != "passed" or audit.get("hard_issues") != []:
        return None, "failed"
    try:
        raw = read_regular(paths["json"])
        record = json.loads(raw)
        canonical = record_bytes(record)
        if (validate_shape(record) or raw != canonical or hashlib.sha256(raw).hexdigest() != audit.get("sha256")
                or audit.get("schema") != "simulation-record-audit/v1"
                or audit.get("simulation_id") != record.get("simulation_id")
                or artifact_hashes(sim_dir) != audit.get("artifact_sha256")):
            return None, "stale_audit"
        markdown = audit.get("markdown_sha256")
        if not isinstance(markdown, dict) or set(markdown) != {RECORD_MD, RECORD_MD_ZH}:
            return None, "stale_audit"
        for name, digest in markdown.items():
            if hashlib.sha256(read_regular(os.path.join(sim_dir, name))).hexdigest() != digest:
                return None, "stale_audit"
        return record, "passed"
    except (OSError, ValueError, TypeError):
        return None, "stale_audit"


def is_published(sim_dir: str) -> bool:
    return load_published_record(sim_dir)[0] is not None
