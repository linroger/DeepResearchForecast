"""Bounded investigation questions from the public simulation record.

This is a deterministic diagnostic experiment, not a research executor. Origins
are simulated turning points or modeling gaps, never external evidence. The
separate sidecar cannot enter the record/report schema or probability prompts.
The verified reader binds it to the existing record publication gate and checks
the entire deterministic output, including labels, limits and source pointers.
"""
from __future__ import annotations

import hashlib
import itertools
import json
import os
import unicodedata
from typing import Any

from . import simulation_record_contract as rc

SCHEMA = "simulation-discovery-questions/v1"
ARTIFACT_FILE = "simulation_discovery_questions.json"
MAX_QUESTIONS = 6
MAX_CANDIDATES = 128
MAX_TOPIC_CHARS = 600
QUERIES_PER_QUESTION = 2


def _canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def _sha(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def build_discovery_questions(record: dict[str, Any]) -> dict[str, Any]:
    """Compile one terminal queue; no calls, retries, follow-up rounds or mutation.

    Alternate existing turning points and seed gaps in their recorded order so
    a long gap list cannot exclude every simulated dynamic. Turning points are
    already bounded by the record producer's red-line/offer/large-change rule;
    'surprising' here is that diagnostic rule, not statistical significance.
    Deduplicate normalized topics across categories, retaining the first
    source pointer. Scan at most MAX_CANDIDATES and emit at most MAX_QUESTIONS,
    each with one support and one refutation query. Invalid/oversized topics
    are counted and skipped, never truncated into misleading new propositions.
    """
    if not isinstance(record, dict):
        raise ValueError("discovery requires a simulation record object")
    record_hash = rc.record_sha256(record)
    overall = record.get("overall") if isinstance(record.get("overall"), dict) else {}
    setup = record.get("setup") if isinstance(record.get("setup"), dict) else {}
    health = record.get("health") if isinstance(record.get("health"), dict) else {}
    limits = record.get("limits") if isinstance(record.get("limits"), dict) else {}
    turns = overall.get("turning_points")
    gaps = setup.get("seed_gaps")
    selection = {
        "engine": record.get("engine"), "as_of": record.get("as_of"),
        "horizon_date": record.get("horizon_date"), "health": health,
        "stub": limits.get("stub"), "turning_points": turns, "seed_gaps": gaps,
    }
    artifact = {
        "schema": SCHEMA,
        "record_class": "simulated",
        "epistemic_status": "hypothetical_research_questions",
        "evidence_admissible": False,
        "probability_input": False,
        "simulation_id": record.get("simulation_id"),
        "as_of": record.get("as_of"),
        "horizon_date": record.get("horizon_date"),
        "input_hashes": {rc.RECORD_JSON: record_hash, "selection_inputs": _sha(selection)},
        "policy": {
            "version": "bounded-discovery/v1",
            "selection": "alternate_recorded_turning_points_and_seed_gaps_first_unique",
            "max_candidates": MAX_CANDIDATES, "max_questions": MAX_QUESTIONS,
            "max_query_suggestions": MAX_QUESTIONS * QUERIES_PER_QUESTION,
            "max_generation_rounds": 1,
        },
        "boundary": (
            "Hypothetical questions only. Source links identify simulated origins, not "
            "external corroboration. No simulation output is evidence or a probability input. "
            "Only separately retrieved and admitted external sources may revise research. "
            "Respect the original information cutoff and source-origin dependence; seek "
            "support and refutation. Failure to find evidence is not evidence of absence."
        ),
        "execution": {"automatic_research": False, "paid_execution": False,
                      "search_calls": 0, "llm_calls": 0},
        "questions": [],
        "selection_counts": {"available": 0, "scanned": 0, "duplicates": 0,
                             "invalid": 0, "unique": 0, "omitted_by_question_cap": 0,
                             "unscanned": 0},
        "stop": {"stopped": True, "reason": "no_eligible_questions", "resume_automatically": False},
    }
    if rc.validate_shape(record) or not isinstance(turns, list) or not isinstance(gaps, list):
        artifact["stop"]["reason"] = "invalid_record"
        return artifact
    if (limits.get("stub") is not False or health.get("validity") != "valid"
            or health.get("simulation_health") not in ("ok", "llm_degraded")):
        artifact["stop"]["reason"] = "unusable_simulation"
        return artifact
    if record.get("engine") not in ("oasis-reflexive", "world-v1"):
        artifact["stop"]["reason"] = "no_world_model"
        return artifact

    counts = artifact["selection_counts"]
    counts["available"] = len(turns) + len(gaps)
    turning_rows = (("simulated_turning_point", row.get("why") if isinstance(row, dict) else None,
                     f"/overall/turning_points/{i}") for i, row in enumerate(turns))
    gap_rows = (("modeling_gap", row, f"/setup/seed_gaps/{i}") for i, row in enumerate(gaps))
    rows = (row for pair in itertools.zip_longest(turning_rows, gap_rows)
            for row in pair if row is not None)
    seen = set()
    for kind, topic, pointer in itertools.islice(rows, MAX_CANDIDATES):
        counts["scanned"] += 1
        if not isinstance(topic, str) or not topic.strip() or len(topic) > MAX_TOPIC_CHARS:
            counts["invalid"] += 1
            continue
        topic = " ".join(unicodedata.normalize("NFKC", topic).split())
        if not topic or len(topic) > MAX_TOPIC_CHARS:
            counts["invalid"] += 1
            continue
        identity = topic.casefold()
        if identity in seen:
            counts["duplicates"] += 1
            continue
        seen.add(identity)
        counts["unique"] += 1
        if len(artifact["questions"]) >= MAX_QUESTIONS:
            counts["omitted_by_question_cap"] += 1
            continue
        question = (
            f"For the hypothetical simulation topic “{topic}”, which external observations "
            "would support or refute the assumed mechanism, constraint or missing premise?"
        )
        artifact["questions"].append({
            "id": "discovery-" + _sha([identity, record.get("as_of"), record.get("horizon_date")])[:24],
            "kind": kind, "epistemic_status": "hypothetical_research_question",
            "evidence_admissible": False, "probability_input": False,
            "hypothetical_topic": topic, "question": question,
            "origin": {"file": rc.RECORD_JSON, "json_pointer": pointer,
                       "sha256": record_hash, "role": "simulated_origin_not_evidence"},
            "query_suggestions": [
                {"purpose": "support", "query": f"Hypothesis to verify: {topic} — primary sources supporting feasibility and prerequisites"},
                {"purpose": "refutation", "query": f"Hypothesis to challenge: {topic} — primary sources contradicting feasibility and alternative explanations"},
            ],
            "verification_status": "not_executed",
        })
    counts["unscanned"] = counts["available"] - counts["scanned"]
    if counts["unscanned"]:
        artifact["stop"]["reason"] = "candidate_cap"
    elif counts["omitted_by_question_cap"]:
        artifact["stop"]["reason"] = "question_cap"
    elif artifact["questions"]:
        artifact["stop"]["reason"] = "queue_exhausted"
    return artifact


def load_discovery_questions(sim_dir: str) -> dict[str, Any] | None:
    """Return only the exact current sidecar of a published record; fail closed.

    The publication gate establishes simulation-record fidelity, not real-world
    truth. Recompilation checks the sidecar's entire schema and hashes and rejects
    a partial write, stale generation, weakened label or invented question.
    """
    record, status = rc.load_published_record(sim_dir)
    if record is None or status != "passed":
        return None
    try:
        raw = rc.read_regular(os.path.join(sim_dir, ARTIFACT_FILE))
        expected = build_discovery_questions(record)
        return expected if raw == rc.record_bytes(expected) else None
    except (OSError, ValueError, TypeError):
        return None
