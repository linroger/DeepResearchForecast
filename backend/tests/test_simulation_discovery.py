"""Bounded discovery exercises the existing record producer and published consumer."""
from __future__ import annotations

import copy
import hashlib
import json
import shutil
import sys
from pathlib import Path

import pytest

from app.services import simulation_record as sr
from app.services import simulation_record_contract as rc
from app.services import simulation_record_gate as gate
from app.services import simulation_diagnostics as sd
from test_world_report_consumers import world  # Reuse the real native-world fixture.


FIXTURE = Path(__file__).parent / "fixtures/sim_record/reflexive3"


@pytest.fixture(autouse=True, scope="module")
def _pin_tested_sources():
    guard = sys.modules.get("main_offline_guard")
    if guard is not None:
        for module in (sr, rc, gate, sd):
            path = Path(module.__file__)
            guard.source_hashes[str(path)] = hashlib.sha256(path.read_bytes()).hexdigest()


def _produce(tmp_path):
    directory = tmp_path / "simulation"
    shutil.copytree(FIXTURE, directory)
    record = sr.build_record(str(directory), language="en", synthesis=False)
    paths = sr.write_record(str(directory), record)
    return directory, record, paths


def test_record_producer_persists_bounded_question_artifact(tmp_path):
    directory, record, paths = _produce(tmp_path)
    path = directory / "simulation_discovery_questions.json"
    assert path.is_file(), "the real record producer must emit discovery questions"
    assert paths["discovery_json"] == str(path)
    artifact = json.loads(path.read_bytes())
    assert artifact == sd.build_discovery_questions(record)
    assert 0 < len(artifact["questions"]) <= sd.MAX_QUESTIONS
    assert gate.audit_record(str(directory), record)["publication_status"] == "passed"
    assert sd.load_discovery_questions(str(directory)) == artifact
    assert artifact["input_hashes"][rc.RECORD_JSON] == hashlib.sha256(
        (directory / rc.RECORD_JSON).read_bytes()).hexdigest()
    assert rc.validate_shape(record) == []
    assert {q["kind"] for q in artifact["questions"]} == {"simulated_turning_point", "modeling_gap"}
    assert artifact["as_of"] == record["as_of"]
    assert artifact["horizon_date"] == record["horizon_date"]
    for question in artifact["questions"]:
        assert question["evidence_admissible"] is False
        assert question["probability_input"] is False
        assert question["epistemic_status"] == "hypothetical_research_question"
        assert question["verification_status"] == "not_executed"
        assert "hypothetical" in question["question"] and question["question"].endswith("?")
        assert {q["purpose"] for q in question["query_suggestions"]} == {"support", "refutation"}
        origin = question["origin"]
        assert origin["sha256"] == artifact["input_hashes"][rc.RECORD_JSON]
        assert origin["role"] == "simulated_origin_not_evidence"
        node = record
        for token in origin["json_pointer"].split("/")[1:]:
            node = node[int(token)] if isinstance(node, list) else node[token]
        assert node == question["hypothetical_topic"] or node["why"] == question["hypothetical_topic"]
    (tmp_path / "producer-consumer-receipt.json").write_text(json.dumps({
        "producer": "simulation_record.build_record -> write_record",
        "consumer": "simulation_diagnostics.load_discovery_questions",
        "publication_status": "passed", "artifact": str(path),
        "input_hashes": artifact["input_hashes"], "question_count": len(artifact["questions"]),
        "execution": artifact["execution"], "stop": artifact["stop"],
    }, indent=2))


def test_determinism_dedup_and_explicit_cap(tmp_path):
    _, record, _ = _produce(tmp_path)
    record["overall"]["turning_points"] = []
    record["setup"]["seed_gaps"] = [" Funding covenant ", "funding   COVENANT", "Ｆｕｎｄｉｎｇ covenant"]
    first = sd.build_discovery_questions(record)
    assert len(first["questions"]) == 1
    assert first["selection_counts"]["duplicates"] == 2
    assert first["stop"]["reason"] == "queue_exhausted"
    assert sd.build_discovery_questions(copy.deepcopy(record)) == first
    record["setup"]["seed_gaps"] += [f"Unresolved prerequisite {i}" for i in range(sd.MAX_CANDIDATES * 2)]
    capped = sd.build_discovery_questions(record)
    assert len(capped["questions"]) == sd.MAX_QUESTIONS
    assert sum(len(q["query_suggestions"]) for q in capped["questions"]) == sd.MAX_QUESTIONS * 2
    assert capped["selection_counts"]["scanned"] == sd.MAX_CANDIDATES
    assert capped["selection_counts"]["unscanned"] > 0
    assert capped["stop"] == {"stopped": True, "reason": "candidate_cap", "resume_automatically": False}
    record["setup"]["seed_gaps"] = record["setup"]["seed_gaps"][:20]
    assert sd.build_discovery_questions(record)["stop"]["reason"] == "question_cap"


def test_duplicate_query_topics_across_origin_types_are_selected_once(tmp_path):
    _, record, _ = _produce(tmp_path)
    record["overall"]["turning_points"] = [{"why": "Funding covenant", "round": 1}]
    record["setup"]["seed_gaps"] = [" FUNDING covenant "]
    artifact = sd.build_discovery_questions(record)
    assert len(artifact["questions"]) == 1
    assert artifact["selection_counts"]["duplicates"] == 1


def test_normalized_topic_still_obeys_output_bound(tmp_path):
    _, record, _ = _produce(tmp_path)
    record["overall"]["turning_points"] = []
    # NFKC expands this ligature to three ASCII characters.
    record["setup"]["seed_gaps"] = ["\ufb03" * sd.MAX_TOPIC_CHARS]
    artifact = sd.build_discovery_questions(record)
    assert artifact["questions"] == []
    assert artifact["selection_counts"]["invalid"] == 1


def test_only_allowed_diagnostic_inputs_select_questions(tmp_path):
    _, record, _ = _produce(tmp_path)
    first = sd.build_discovery_questions(record)
    changed = copy.deepcopy(record)
    changed["generated_at"] = "2040-01-01T00:00:00Z"
    changed["overall"]["shares"] = {"final": {"secret_scenario": 0.999999}}
    changed["overall"]["synthesis"]["text"] = "PRIVATE_SYNTHESIS_DO_NOT_USE"
    changed["periods"][0]["moves"][0]["private_rationale"] = "PRIVATE_RATIONALE_DO_NOT_USE"
    second = sd.build_discovery_questions(changed)
    assert first["input_hashes"]["selection_inputs"] == second["input_hashes"]["selection_inputs"]
    assert first["input_hashes"][rc.RECORD_JSON] != second["input_hashes"][rc.RECORD_JSON]
    for original, updated in zip(first["questions"], second["questions"], strict=True):
        assert {k: v for k, v in original.items() if k != "origin"} == {
            k: v for k, v in updated.items() if k != "origin"}
    assert "PRIVATE_" not in json.dumps(second) and "secret_scenario" not in json.dumps(second)
    assert "discovery" not in json.dumps(record)
    assert "Hypothesis to" not in sr.render_markdown(record)
    assert "Hypothesis to" not in json.dumps(sr._synthesis_prompt(record))


@pytest.mark.parametrize("health", ["hollow", "errored", "truncated"])
def test_actual_unusable_run_produces_explicit_empty_stop(tmp_path, health, monkeypatch):
    directory = tmp_path / "simulation"
    shutil.copytree(FIXTURE, directory)
    summary_path = directory / "run_summary.json"
    summary = json.loads(summary_path.read_text())
    summary["simulation_health"] = health
    summary_path.write_text(json.dumps(summary))
    monkeypatch.setattr(sr, "_default_llm", lambda: pytest.fail("discovery must not construct a provider"))
    record = sr.build_record(str(directory), synthesis=True)
    paths = sr.write_record(str(directory), record)
    artifact = json.loads(Path(paths["discovery_json"]).read_bytes())
    assert artifact["questions"] == [] and artifact["stop"]["reason"] == "unusable_simulation"
    assert artifact["execution"] == {"automatic_research": False, "paid_execution": False,
                                      "search_calls": 0, "llm_calls": 0}


def test_empty_invalid_and_oversized_topics_are_not_invented(tmp_path):
    _, record, _ = _produce(tmp_path)
    record["overall"]["turning_points"] = []
    record["setup"]["seed_gaps"] = [None, {}, "", "x" * (sd.MAX_TOPIC_CHARS + 1)]
    artifact = sd.build_discovery_questions(record)
    assert artifact["questions"] == [] and artifact["stop"]["reason"] == "no_eligible_questions"
    assert artifact["selection_counts"]["invalid"] == 4
    record["record_class"] = "evidence"
    assert sd.build_discovery_questions(record)["stop"]["reason"] == "invalid_record"


@pytest.mark.parametrize("mutation", ["label", "question", "hash", "schema", "missing", "unpublished", "source", "symlink"])
def test_published_consumer_rejects_tamper_missing_and_stale(tmp_path, mutation):
    directory, record, _ = _produce(tmp_path)
    assert gate.audit_record(str(directory), record)["publication_status"] == "passed"
    assert sd.load_discovery_questions(str(directory)) is not None
    path = directory / sd.ARTIFACT_FILE
    artifact = json.loads(path.read_bytes())
    if mutation == "missing":
        path.unlink()
    elif mutation == "symlink":
        other = directory / "sidecar-copy.json"
        other.write_bytes(path.read_bytes())
        path.unlink()
        path.symlink_to(other)
    elif mutation == "unpublished":
        (directory / rc.RECORD_AUDIT_JSON).unlink()
    elif mutation == "source":
        with (directory / "world_state_history.jsonl").open("a") as stream:
            stream.write("\n")
    else:
        if mutation == "label":
            artifact["questions"][0]["evidence_admissible"] = True
        elif mutation == "question":
            artifact["questions"][0]["question"] = "Invented replacement?"
        elif mutation == "hash":
            artifact["input_hashes"][rc.RECORD_JSON] = "0" * 64
        else:
            artifact["schema"] = "simulation-discovery-questions/v99"
        path.write_bytes(rc.record_bytes(artifact))
    assert sd.load_discovery_questions(str(directory)) is None


def test_changed_source_reconstructs_and_partial_sidecar_write_fails_closed(tmp_path, monkeypatch):
    directory, original_record, _ = _produce(tmp_path)
    assert gate.audit_record(str(directory), original_record)["publication_status"] == "passed"
    original = sd.load_discovery_questions(str(directory))
    path = directory / sd.ARTIFACT_FILE
    original_bytes = path.read_bytes()
    sibling = directory / "parent-owned.txt"
    sibling.write_text("preserved")
    source = directory / "world_state.json"
    state = json.loads(source.read_text())
    state["world"]["seed_gaps"].insert(0, "Need independent records of financing covenant limits")
    source.write_text(json.dumps(state))
    updated_record = sr.build_record(str(directory), language="en", synthesis=False)
    real_write = sr._atomic_write

    def fail_sidecar(target, data):
        if Path(target).name == sd.ARTIFACT_FILE:
            raise OSError("synthetic sidecar write failure")
        real_write(target, data)

    monkeypatch.setattr(sr, "_atomic_write", fail_sidecar)
    with pytest.raises(OSError, match="sidecar write failure"):
        sr.write_record(str(directory), updated_record)
    assert path.read_bytes() == original_bytes
    # Even a refreshed record audit cannot validate the stale question sidecar.
    assert gate.audit_record(str(directory), updated_record)["publication_status"] == "passed"
    assert sd.load_discovery_questions(str(directory)) is None
    monkeypatch.setattr(sr, "_atomic_write", real_write)
    sr.write_record(str(directory), updated_record)
    assert gate.audit_record(str(directory), updated_record)["publication_status"] == "passed"
    updated = sd.load_discovery_questions(str(directory))
    assert updated is not None and updated["input_hashes"] != original["input_hashes"]
    assert updated["questions"] != original["questions"]
    assert sibling.read_text() == "preserved"


def test_world_v1_actual_public_producer_and_consumer(tmp_path):
    from test_simulation_record import _write_world_v1
    directory = tmp_path / "world"
    _write_world_v1(directory)
    record = sr.build_record(str(directory), synthesis=False)
    paths = sr.write_record(str(directory), record)
    assert Path(paths["discovery_json"]).is_file()
    assert gate.audit_record(str(directory), record)["publication_status"] == "passed"
    artifact = sd.load_discovery_questions(str(directory))
    assert artifact is not None and artifact["questions"]
    assert all(q["kind"] == "simulated_turning_point" for q in artifact["questions"])


def test_thin_run_explicitly_has_no_discovery_model(tmp_path):
    directory = tmp_path / "thin"
    directory.mkdir()
    for name in ("world_digest.jsonl", "world_state_trajectory.json", "run_summary.json",
                 "simulation_config.json", "state.json"):
        shutil.copy(FIXTURE / name, directory / name)
    record = sr.build_record(str(directory), synthesis=False)
    paths = sr.write_record(str(directory), record)
    artifact = json.loads(Path(paths["discovery_json"]).read_bytes())
    assert artifact["questions"] == []
    assert artifact["stop"]["reason"] == "no_world_model"


def test_crossed_constraint_from_actual_history_reaches_question_consumer(tmp_path):
    directory = tmp_path / "simulation"
    shutil.copytree(FIXTURE, directory)
    initial = sr.build_record(str(directory), synthesis=False)
    actor = next(row for row in initial["setup"]["cast"] if row["red_lines"])
    history_path = directory / "world_state_history.jsonl"
    history = [json.loads(line) for line in history_path.read_text().splitlines() if line.strip()]
    history[0].setdefault("arbiter", {})["red_lines_crossed"] = [
        {"actor": actor["actor"], "red_line": actor["red_lines"][0]}]
    history_path.write_text("".join(json.dumps(row) + "\n" for row in history))
    record = sr.build_record(str(directory), language="en", synthesis=False)
    sr.write_record(str(directory), record)
    audit = gate.audit_record(str(directory), record)
    assert audit["publication_status"] == "passed", audit["hard_issues"]
    artifact = sd.load_discovery_questions(str(directory))
    questions = artifact["questions"]
    assert any("red line crossed" in q["hypothetical_topic"] and actor["actor"] in q["question"] for q in questions)
    assert any(q["kind"] == "modeling_gap" for q in questions)
    assert all(q["evidence_admissible"] is False for q in questions)


def test_terminal_publisher_emits_consumable_queue_without_provider(tmp_path, monkeypatch):
    from app.config import Config
    from app.services.simulation_runner import SimulationRunner
    directory = tmp_path / "sim_discovery"
    shutil.copytree(FIXTURE, directory)
    monkeypatch.setattr(Config, "SIM_RECORD_ENABLED", True)
    monkeypatch.setattr(SimulationRunner, "RUN_STATE_DIR", str(tmp_path))
    monkeypatch.setattr(sr, "_default_llm", lambda: pytest.fail("no provider allowed"))
    assert SimulationRunner.publish_simulation_record(
        directory.name, language="en", engine_hint="oasis-reflexive", synthesis=False)
    artifact = sd.load_discovery_questions(str(directory))
    assert artifact is not None and artifact["questions"]
    path = directory / sd.ARTIFACT_FILE
    original = path.read_bytes()
    assert SimulationRunner.publish_simulation_record(
        directory.name, language="en", engine_hint="oasis-reflexive", synthesis=False)
    assert path.read_bytes() == original
    (tmp_path / "terminal-publisher-receipt.json").write_text(json.dumps({
        "producer": "SimulationRunner.publish_simulation_record",
        "consumer": "simulation_diagnostics.load_discovery_questions",
        "artifact": str(path), "artifact_sha256": hashlib.sha256(original).hexdigest(),
        "questions": len(artifact["questions"]), "replay_bytes_identical": True,
        "input_hashes": artifact["input_hashes"], "provider_calls": 0,
    }, indent=2))


def test_generated_sidecars_preserve_effective_forecast_requests(tmp_path, monkeypatch, world):
    from test_world_report_consumers import test_forecast_model_bytes_invariant_to_trajectory_including_fallbacks
    receipts = []

    def world_with_questions(**kwargs):
        directory = world(**kwargs)
        record = sr.build_record(str(directory), language="en", synthesis=False)
        sr.write_record(str(directory), record)
        audit = gate.audit_record(str(directory), record)
        assert audit["publication_status"] == "passed", audit["hard_issues"]
        artifact = sd.load_discovery_questions(str(directory))
        assert artifact is not None and artifact["questions"]
        receipts.append({"simulation_id": directory.name,
                         "artifact_sha256": hashlib.sha256((directory / sd.ARTIFACT_FILE).read_bytes()).hexdigest(),
                         "topics": [q["hypothetical_topic"] for q in artifact["questions"]]})
        return directory

    # The established scenario captures real forecast-extractor/top-up/critique
    # request bytes with scripted model responses and compares the two worlds.
    test_forecast_model_bytes_invariant_to_trajectory_including_fallbacks(
        tmp_path, monkeypatch, world_with_questions, spine=True, effect="diagnostic_only", research=True)
    assert len(receipts) == 2 and receipts[0]["topics"] != receipts[1]["topics"]
    (tmp_path / "forecast-isolation-receipt.json").write_text(json.dumps({
        "worlds": receipts, "same_external_evidence": True, "different_discovery_questions": True,
        "effective_forecast_request_bytes_identical": True, "model_boundary": "scripted responses",
    }, indent=2))
