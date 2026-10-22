"""Shape contract of the Simulation After-Action Record (ADR 0003, design §4)."""
from __future__ import annotations

import json
import os

from app.services import sim_provenance as sp
from app.services import simulation_record_contract as rc


def minimal_record(language="en", committed=2):
    periods = []
    for r in range(1, committed + 1):
        periods.append({
            "round": r, "label": f"2026-W{40 + r}", "period_start": "2026-10-05", "period_end": "2026-10-11",
            "arbiter_status": "applied", "arbiter_problems": [], "narrative": "Talks stalled.",
            "moves": [], "held_position": [], "facts_changed": [], "events": [], "shocks_fired": [],
            "red_lines_crossed": [], "offers": [], "alliances": [], "behaviour": {}, "refs": [],
        })
    return {
        "schema": rc.SCHEMA, "record_class": rc.RECORD_CLASS, "epistemic_status": rc.EPISTEMIC_STATUS,
        "simulation_id": "sim_x", "pipeline_id": "pipe_x", "config_hash": "abc", "engine": "oasis-reflexive",
        "language": language, "as_of": "2026-10-01", "horizon_date": "2027-03-31", "calendar_unit": "week",
        "rounds_planned": committed, "rounds_committed": committed,
        "health": {"simulation_health": "ok", "validity": "valid", "arbiter_failed_rounds": 0,
                   "seed_gaps": 0, "organic_actions": 12},
        "banner": rc.banner_for(language),
        "setup": {"cast": [], "variables": [], "scenarios": [], "shocks": [], "seed_gaps": []},
        "periods": periods,
        "overall": {"final_variables": [], "shares": {}, "turning_points": [], "track_records": [],
                    "synthesis": {"generator": "deterministic", "text": "", "claims": []}},
        "limits": {}, "entities_declared": [], "generated_at": "2026-10-22T00:00:00Z",
        "generator_version": "test",
    }


def test_minimal_record_is_valid_in_both_languages():
    assert rc.validate_shape(minimal_record("en")) == []
    assert rc.validate_shape(minimal_record("zh")) == []
    assert rc.banner_for("en") == sp.SIM_BANNER_EN and rc.banner_for("zh-CN") == sp.SIM_BANNER_ZH


def test_shape_violations_are_named():
    rec = minimal_record()
    rec["record_class"] = "observed"
    rec["banner"] = "simulated, honest"
    rec["periods"].pop()                       # one fewer than committed
    rec["periods"][0]["shares"] = {"A": 0.5}   # shares in a period section
    rec["overall"]["synthesis"]["generator"] = "oracle"
    del rec["entities_declared"]
    problems = rc.validate_shape(rec)
    joined = "\n".join(problems)
    for needle in ("record_class", "banner", "committed rounds", "scenario shares",
                   "synthesis.generator", "entities_declared"):
        assert needle in joined, needle
    assert rc.validate_shape("nope") == ["record is not an object"]


def test_private_rationale_is_not_a_public_action_field():
    assert "private_rationale" not in rc.ACTION_PUBLIC_FIELDS
    assert "public_statement" in rc.ACTION_PUBLIC_FIELDS


def test_loaders_refuse_symlinks_and_garbage(tmp_path):
    sim_dir = tmp_path / "sim_a"
    sim_dir.mkdir()
    assert rc.load_record(str(sim_dir)) is None
    (sim_dir / rc.RECORD_JSON).write_text("not json", encoding="utf-8")
    assert rc.load_record(str(sim_dir)) is None
    (sim_dir / rc.RECORD_JSON).write_text(json.dumps(minimal_record()), encoding="utf-8")
    assert rc.load_record(str(sim_dir))["schema"] == rc.SCHEMA
    other = tmp_path / "sim_b"
    other.mkdir()
    os.symlink(sim_dir / rc.RECORD_JSON, other / rc.RECORD_JSON)
    assert rc.load_record(str(other)) is None


def test_is_published_requires_a_passed_audit(tmp_path):
    sim_dir = tmp_path / "sim_c"
    sim_dir.mkdir()
    assert rc.is_published(str(sim_dir)) is False
    (sim_dir / rc.RECORD_AUDIT_JSON).write_text(json.dumps(
        {"publication_status": "failed", "hard_issues": ["G2"]}), encoding="utf-8")
    assert rc.is_published(str(sim_dir)) is False
    (sim_dir / rc.RECORD_AUDIT_JSON).write_text(json.dumps(
        {"publication_status": "passed", "hard_issues": []}), encoding="utf-8")
    assert rc.is_published(str(sim_dir)) is True
