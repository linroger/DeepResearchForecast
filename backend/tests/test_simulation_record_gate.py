"""T4 — the record gate's negatives and its clean pass (ADR 0003; design §3.2 G1–G9).

Each negative mutates the clean, live-derived record and must produce the expected hard
issue code; the clean record passes.  The fixture directory is
``tests/fixtures/sim_record/reflexive3`` (see test_simulation_record.py).
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
import shutil
from pathlib import Path

import pytest

from app.services import sim_provenance as sp
from app.services import simulation_record as sr
from app.services import simulation_record_contract as rc
from app.services import simulation_record_gate as gate

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "sim_record"


@pytest.fixture
def run(tmp_path):
    sim_dir = tmp_path / "sim_3ec25e64209e"
    shutil.copytree(FIXTURES / "reflexive3", sim_dir)
    record = sr.build_record(str(sim_dir), language="en", synthesis=False)
    return str(sim_dir), record


def _codes(audit):
    return sorted({issue.split(":", 1)[0] for issue in audit["hard_issues"]})


def _audit(sim_dir, record):
    return gate.audit_record(sim_dir, record, write=False)


def test_clean_record_passes_and_the_audit_file_is_written(run):
    sim_dir, record = run
    sr.write_record(sim_dir, record)
    audit = gate.audit_record(sim_dir, record)
    assert audit["publication_status"] == "passed" and audit["hard_issues"] == [], audit["hard_issues"]
    assert audit["schema"] == gate.AUDIT_SCHEMA and audit["simulation_id"] == record["simulation_id"]
    on_disk = json.loads(Path(sim_dir, rc.RECORD_AUDIT_JSON).read_text(encoding="utf-8"))
    assert on_disk["sha256"] == audit["sha256"] == hashlib.sha256(Path(sim_dir, rc.RECORD_JSON).read_bytes()).hexdigest()
    assert rc.is_published(sim_dir) is True
    # write=False leaves the directory alone
    os.unlink(os.path.join(sim_dir, rc.RECORD_AUDIT_JSON))
    gate.audit_record(sim_dir, record, write=False)
    assert not os.path.exists(os.path.join(sim_dir, rc.RECORD_AUDIT_JSON))


def test_invented_actor_is_a_hard_issue(run):
    sim_dir, record = run
    bad = copy.deepcopy(record)
    period = bad["periods"][0]
    move = copy.deepcopy(period["moves"][0])
    move["actor"] = "Zorblax Prime"                     # not in the cast, points at a real row
    period["moves"].append(move)
    audit = _audit(sim_dir, bad)
    assert audit["publication_status"] == "failed"
    assert "G3" in _codes(audit) and "G4" in _codes(audit)
    assert any("Zorblax Prime" in h and h.startswith("G3") for h in audit["hard_issues"])
    # declaring the invented name does not help: declared entities must exist in the artifacts
    bad["entities_declared"].append("Zorblax Prime")
    audit = _audit(sim_dir, bad)
    assert any(h.startswith("G3") and "declared entity" in h for h in audit["hard_issues"])
    # an invented holder of a position, an offer party and a track record are caught too
    for mutate in (
        lambda r: r["periods"][0]["held_position"].append("Zorblax Prime"),
        lambda r: r["periods"][0]["offers"].append({"from_actor": "Zorblax Prime", "to_actor": "US Government",
                                                    "kind": "proposal", "status": "opened", "terms": ""}),
        lambda r: r["overall"]["track_records"].append({"actor": "Zorblax Prime", "kept": 0, "lapsed": 0, "broken": 0}),
    ):
        candidate = copy.deepcopy(record)
        mutate(candidate)
        assert "G3" in _codes(_audit(sim_dir, candidate))


def test_number_absent_from_the_rows_is_a_hard_issue(run):
    sim_dir, record = run
    bad = copy.deepcopy(record)
    bad["overall"]["synthesis"]["text"] += "\n\nOutput rose by 37.5% to 9,870 units (2026-10-23)."
    audit = _audit(sim_dir, bad)
    assert "G2" in _codes(audit)
    assert any("37.5%" in h for h in audit["hard_issues"]) and any("9870" in h for h in audit["hard_issues"])
    # a numeric field that traces to nothing
    bad = copy.deepcopy(record)
    bad["periods"][0]["facts_changed"][0]["to"] = 123456.789
    assert "G2" in _codes(_audit(sim_dir, bad))
    # a share that disagrees with the trajectory beyond the rendered precision
    bad = copy.deepcopy(record)
    name = next(iter(bad["overall"]["shares"]["final"]))
    bad["overall"]["shares"]["final"][name] = round(bad["overall"]["shares"]["final"][name] + 0.05, 4)
    audit = _audit(sim_dir, bad)
    assert any(h.startswith("G2") and "differs from the trajectory" in h for h in audit["hard_issues"])
    # a date that no artifact carries
    bad = copy.deepcopy(record)
    bad["overall"]["synthesis"]["text"] += "\n\nBy 2031-07-04 nothing had changed (2026-10-23)."
    assert any("2031-07-04" in h for h in _audit(sim_dir, bad)["hard_issues"])
    # rounding and percent forms of real values are fine
    ok = copy.deepcopy(record)
    ok["overall"]["synthesis"]["text"] += "\n\nThe leading share was 50.6% and Brent sat at 24.8 (2026-10-25)."
    assert _audit(sim_dir, ok)["publication_status"] == "passed"


def test_citation_marker_is_a_hard_issue(run):
    sim_dir, record = run
    for marker in ("[S3]", "【S12】", "[S1-a]"):
        bad = copy.deepcopy(record)
        bad["overall"]["synthesis"]["text"] += f"\n\nThe talks stalled {marker} (2026-10-23)."
        audit = _audit(sim_dir, bad)
        assert "G5" in _codes(audit), marker
    # anywhere in the record, including verbatim fields
    bad = copy.deepcopy(record)
    bad["periods"][0]["moves"][0]["public_statement"] += " [S7]"
    assert "G5" in _codes(_audit(sim_dir, bad))
    # evidence verbs applied to simulated content
    bad = copy.deepcopy(record)
    bad["overall"]["synthesis"]["text"] += "\n\nThe evidence shows the talks stalled (2026-10-23)."
    assert any(h.startswith("G5") and "evidence verb" in h for h in _audit(sim_dir, bad)["hard_issues"])
    bad = copy.deepcopy(record)
    bad["overall"]["turning_points"][0]["why"] += "；证据表明如此"
    assert any(h.startswith("G5") and "evidence verb" in h for h in _audit(sim_dir, bad)["hard_issues"])


def test_private_rationale_substring_is_a_hard_issue(tmp_path):
    sim_dir = tmp_path / "sim_private"
    shutil.copytree(FIXTURES / "reflexive3", sim_dir)
    path = sim_dir / "world_actions.jsonl"
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    secret = ("Privately the ministry expects the talks to collapse before Thursday. "
              "It will blame Kyiv's sequencing demand when they do.")
    rows[0]["private_rationale"] = secret
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    record = sr.build_record(str(sim_dir), language="en", synthesis=False)
    assert secret not in json.dumps(record)
    assert _audit(str(sim_dir), record)["publication_status"] == "passed"
    bad = copy.deepcopy(record)
    bad["overall"]["synthesis"]["text"] += "\n\nIt will blame Kyiv's sequencing demand when they do. (2026-10-23)"
    audit = _audit(str(sim_dir), bad)
    assert "G6" in _codes(audit) and audit["publication_status"] == "failed"
    # the private text itself never reaches the audit file
    gate.audit_record(str(sim_dir), bad)
    assert "Thursday" not in Path(sim_dir, rc.RECORD_AUDIT_JSON).read_text(encoding="utf-8")


def test_missing_or_extra_period_is_a_hard_issue(run):
    sim_dir, record = run
    bad = copy.deepcopy(record)
    bad["periods"].pop(1)
    bad["rounds_committed"] = 2                 # shape-consistent, artifact-inconsistent
    audit = _audit(sim_dir, bad)
    assert "G1" in _codes(audit) and any("without a period section: [2]" in h for h in audit["hard_issues"])
    bad = copy.deepcopy(record)
    extra = copy.deepcopy(bad["periods"][-1])
    extra["round"] = 4
    extra["label"] = "2026-10-26"
    extra["refs"] = [{"file": "world_state_history.jsonl", "round": 4, "id": "round:4"}]
    bad["periods"].append(extra)
    bad["rounds_committed"] = 4
    audit = _audit(sim_dir, bad)
    assert "G1" in _codes(audit) and any("not committed: [4]" in h for h in audit["hard_issues"])
    # a period count that disagrees with its own rounds_committed is a shape problem as well
    bad = copy.deepcopy(record)
    bad["periods"].pop()
    assert "shape" in _codes(_audit(sim_dir, bad))


def test_altered_banner_is_a_hard_issue(run):
    sim_dir, record = run
    bad = copy.deepcopy(record)
    bad["banner"] = record["banner"].replace("not a calibrated probability", "a rough probability")
    audit = _audit(sim_dir, bad)
    assert "G7" in _codes(audit) and audit["publication_status"] == "failed"
    bad["banner"] = sp.SIM_BANNER_ZH               # the other language's banner is not this record's
    assert "G7" in _codes(_audit(sim_dir, bad))
    bad["banner"] = sp.SIM_BANNER_EN
    assert _audit(sim_dir, bad)["publication_status"] == "passed"
    # health that disagrees with run_summary
    bad = copy.deepcopy(record)
    bad["health"]["simulation_health"] = "hollow"
    assert any(h.startswith("G7") and "run_summary" in h for h in _audit(sim_dir, bad)["hard_issues"])
    bad = copy.deepcopy(record)
    bad["health"]["validity"] = "invalid"
    assert any(h.startswith("G7") and "trajectory" in h for h in _audit(sim_dir, bad)["hard_issues"])


def test_probability_applied_to_a_share_is_a_hard_issue(run):
    sim_dir, record = run
    bad = copy.deepcopy(record)
    bad["overall"]["synthesis"]["text"] += "\n\nThe probability of a stalemate reached 50.6% (2026-10-25)."
    audit = _audit(sim_dir, bad)
    assert "G8" in _codes(audit) and audit["publication_status"] == "failed"
    bad = copy.deepcopy(record)
    bad["overall"]["turning_points"][0]["why"] += "（概率上升）"
    assert "G8" in _codes(_audit(sim_dir, bad))
    bad = copy.deepcopy(record)
    bad["overall"]["shares"]["probability"] = 0.51
    assert any(h.startswith("G8") and "probability" in h for h in _audit(sim_dir, bad)["hard_issues"])
    bad = copy.deepcopy(record)
    bad["overall"]["shares"]["final"]["Probability of talks"] = 0.5
    assert any(h.startswith("G8") for h in _audit(sim_dir, bad)["hard_issues"])
    # shares in a period section are refused by the shape contract and by G8
    bad = copy.deepcopy(record)
    bad["periods"][0]["shares"] = {"Stalemate with fragile talks": 0.5}
    codes = _codes(_audit(sim_dir, bad))
    assert "shape" in codes and "G8" in codes
    # a seeded shock's base rate is not a share and is not flagged
    ok = copy.deepcopy(record)
    ok["setup"]["shocks"].append({"name": "Port closure", "base_rate": "0.2 per quarter", "window": None, "fired_rounds": []})
    assert "G8" not in _codes(_audit(sim_dir, ok))


def test_unresolved_refs_tampered_narratives_and_foreign_quotes_are_hard_issues(run):
    sim_dir, record = run
    bad = copy.deepcopy(record)
    bad["periods"][0]["moves"][0]["ref"] = {"file": "world_actions.jsonl", "round": 1, "id": "agent:999"}
    assert any(h.startswith("G4") and "does not resolve" in h for h in _audit(sim_dir, bad)["hard_issues"])
    bad = copy.deepcopy(record)
    bad["periods"][0]["refs"] = [{"file": "sources.json", "round": 1, "id": "round:1"}]
    assert any(h.startswith("G4") and "unknown artifact file" in h for h in _audit(sim_dir, bad)["hard_issues"])
    bad = copy.deepcopy(record)
    bad["periods"][1]["narrative"] = "The arbiter never wrote this sentence about Hormuz."
    assert any(h.startswith("G4") and "narrative" in h for h in _audit(sim_dir, bad)["hard_issues"])
    bad = copy.deepcopy(record)
    bad["periods"][0]["moves"][0]["public_statement"] = "We will never negotiate under any circumstances."
    assert any(h.startswith("G4") and "public_statement" in h for h in _audit(sim_dir, bad)["hard_issues"])
    bad = copy.deepcopy(record)
    bad["overall"]["synthesis"]["text"] += "\n\nOne minister said “the talks are a sham and will fail” (2026-10-23)."
    assert any(h.startswith("G4") and "quoted statement" in h for h in _audit(sim_dir, bad)["hard_issues"])
    # a quote copied from a stored public statement, or an exact entity, is fine
    ok = copy.deepcopy(record)
    statement = record["periods"][0]["moves"][0]["public_statement"]
    ok["overall"]["synthesis"]["text"] += f"\n\nIran said “{statement[:70]}” (2026-10-23)."
    ok["overall"]["synthesis"]["text"] += "\n\nThe exercise favoured “Stalemate with fragile talks” (2026-10-25)."
    assert _audit(sim_dir, ok)["publication_status"] == "passed", _audit(sim_dir, ok)["hard_issues"]
    # a synthesis paragraph with neither a claim nor a period label cannot be grounded
    bad = copy.deepcopy(record)
    bad["overall"]["synthesis"]["text"] += "\n\nSomething happened at some point."
    assert any(h.startswith("G4") and "paragraph" in h for h in _audit(sim_dir, bad)["hard_issues"])


def test_language_contamination_in_authored_prose_is_hard_in_narratives_a_warning(run):
    sim_dir, record = run
    bad = copy.deepcopy(record)
    bad["overall"]["synthesis"]["text"] += "\n\n各方在程序上向会谈靠拢，而实质分歧未见弥合。 (2026-10-23)"
    audit = _audit(sim_dir, bad)
    assert "G9" in _codes(audit)
    # the arbiter narrative is verbatim artifact text: a mismatch there is a G4 issue, not G9
    zh_record = sr.build_record(sim_dir, language="zh", synthesis=False)
    zh_audit = _audit(sim_dir, zh_record)
    assert "G9" not in _codes(zh_audit)
    assert any(w.startswith("G9") and "narrative" in w for w in zh_audit["warnings"])


def test_undeclared_capitalised_tokens_are_warnings_not_hard_issues(run):
    sim_dir, record = run
    candidate = copy.deepcopy(record)
    candidate["overall"]["synthesis"]["text"] += "\n\nThe Grand Council of Elders watched (2026-10-23)."
    audit = _audit(sim_dir, candidate)
    assert audit["publication_status"] == "passed"
    assert any(w.startswith("G3") and "Grand Council" in w for w in audit["warnings"])


def test_written_file_must_match_the_audited_record(run):
    sim_dir, record = run
    sr.write_record(sim_dir, record)
    tampered = copy.deepcopy(record)
    tampered["overall"]["synthesis"]["text"] += "\n\nNothing else happened (2026-10-25)."
    audit = gate.audit_record(sim_dir, tampered)          # the file on disk is the untampered one
    assert any(h.startswith("G7") and "differs from the audited record" in h for h in audit["hard_issues"])
    assert rc.is_published(sim_dir) is False
    sr.write_record(sim_dir, tampered)
    assert gate.audit_record(sim_dir, tampered)["publication_status"] == "passed"


def test_gate_never_raises_and_fails_closed_on_garbage(tmp_path, run):
    sim_dir, record = run
    audit = gate.audit_record(sim_dir, "not a record")
    assert audit["publication_status"] == "failed" and audit["hard_issues"] == ["shape: record is not an object"]
    audit = gate.audit_record(str(tmp_path / "nowhere"), record)
    assert audit["publication_status"] == "failed" and any(h.startswith("G1") for h in audit["hard_issues"])
    # an artifact directory that lost its history: every period is extra
    empty = tmp_path / "sim_empty"
    empty.mkdir()
    audit = gate.audit_record(str(empty), record, write=False)
    assert any(h.startswith("G1") and "not committed" in h for h in audit["hard_issues"])
    # the private-rationale comparison follows a symlink nowhere
    os.symlink(FIXTURES / "reflexive3" / "world_actions.jsonl", empty / "world_actions.jsonl")
    assert gate._Sources(str(empty)).actions == []


def test_thin_and_world_v1_records_are_gated_against_their_own_engines(tmp_path):
    sim_dir = tmp_path / "sim_thin"
    sim_dir.mkdir()
    for name in ("world_digest.jsonl", "run_summary.json", "simulation_config.json", "state.json"):
        shutil.copy(FIXTURES / "reflexive3" / name, sim_dir / name)
    record = sr.build_record(str(sim_dir), language="en", synthesis=False)
    assert _audit(str(sim_dir), record)["publication_status"] == "passed"
    bad = copy.deepcopy(record)
    bad["periods"][0]["narrative"] = "A narrative this engine cannot have produced."
    assert any(h.startswith("G4") and "no arbiter narrative" in h for h in _audit(str(sim_dir), bad)["hard_issues"])
    bad = copy.deepcopy(record)
    bad["engine"] = "oasis-reflexive"                   # claims a world model that did not run
    assert "G1" in _codes(_audit(str(sim_dir), bad))
