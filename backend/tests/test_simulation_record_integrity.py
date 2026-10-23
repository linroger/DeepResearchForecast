"""Producer → compiler → gate regressions for ADR 0003 publication fidelity."""
import copy
import json
import os
from pathlib import Path

import pytest

from app.services import simulation_record as sr
from app.services import simulation_record_contract as rc
from app.services import simulation_record_gate as gate
from test_simulation_record import _copy_reflexive, _write_world_v1


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


def publish(directory):
    record = sr.build_record(str(directory), language="en", synthesis=False)
    sr.write_record(str(directory), record)
    audit = gate.audit_record(str(directory), record)
    assert audit["publication_status"] == "passed", audit["hard_issues"]
    assert rc.load_published_record(str(directory)) == (record, "passed")
    return record


@pytest.mark.parametrize("filename", [rc.RECORD_JSON, rc.RECORD_MD, rc.RECORD_MD_ZH,
                                     "world_state_history.jsonl", "world_actions.jsonl"])
def test_publication_seals_every_consumed_artifact(tmp_path, filename):
    directory = Path(_copy_reflexive(tmp_path))
    publish(directory)
    path = directory / filename
    path.write_bytes(path.read_bytes() + b"\n")
    assert rc.load_published_record(str(directory)) == (None, "stale_audit")
    assert not rc.is_published(str(directory))


@pytest.mark.parametrize("key", ["sha256", "markdown_sha256", "artifact_sha256"])
def test_missing_seal_is_not_a_published_record(tmp_path, key):
    directory = Path(_copy_reflexive(tmp_path))
    publish(directory)
    audit = read(directory / rc.RECORD_AUDIT_JSON)
    del audit[key]
    write(directory / rc.RECORD_AUDIT_JSON, audit)
    assert not rc.is_published(str(directory))


def test_state_lifecycle_is_not_an_input_but_identity_is(tmp_path):
    directory = Path(_copy_reflexive(tmp_path))
    record = publish(directory)
    state = read(directory / "state.json")
    state.update(status="completed", updated_at="2040-01-01", runner_status="stopped")
    write(directory / "state.json", state)
    assert rc.load_published_record(str(directory)) == (record, "passed")
    state["pipeline_id"] = "another_pipeline"
    write(directory / "state.json", state)
    assert not rc.is_published(str(directory))


def test_new_source_and_symlinked_directory_invalidate_seal(tmp_path):
    directory = Path(_copy_reflexive(tmp_path))
    publish(directory)
    alias = tmp_path / "alias"
    alias.symlink_to(directory, target_is_directory=True)
    assert rc.load_published_record(str(alias))[0] is None
    write(directory / "world_result.json", {"view": "analyst"})
    assert not rc.is_published(str(directory))


def test_audit_cannot_bless_unrelated_markdown(tmp_path):
    directory = Path(_copy_reflexive(tmp_path))
    record = publish(directory)
    (directory / rc.RECORD_MD).write_text("An invented outcome.", encoding="utf-8")
    audit = gate.audit_record(str(directory), record)
    assert audit["publication_status"] == "failed"
    assert any("deterministic rendering" in h for h in audit["hard_issues"])


def test_predictable_temp_symlink_is_never_followed(tmp_path):
    directory = Path(_copy_reflexive(tmp_path))
    victim = tmp_path / "victim"
    victim.write_text("preserve", encoding="utf-8")
    for name in (rc.RECORD_JSON, rc.RECORD_MD, rc.RECORD_MD_ZH, rc.RECORD_AUDIT_JSON):
        (directory / f"{name}.tmp-{os.getpid()}").symlink_to(victim)
    publish(directory)
    assert victim.read_text(encoding="utf-8") == "preserve"


@pytest.mark.parametrize("field", ["fact", "event", "offer", "move", "period", "final", "shares", "held"])
def test_other_valid_values_do_not_prove_row_fidelity(tmp_path, field):
    directory = _copy_reflexive(tmp_path)
    record = sr.build_record(directory, language="en", synthesis=False)
    period = record["periods"][0]
    if field == "fact":
        period["facts_changed"][0]["to"] = period["facts_changed"][0]["from"]
    elif field == "event":
        period["events"][0]["text"] = record["periods"][1]["events"][0]["text"]
    elif field == "offer":
        period["offers"][0]["status"] = "accepted"
    elif field == "move":
        period["moves"][0]["option"] = "Hold position"
    elif field == "period":
        period["period_end"] = record["periods"][1]["period_end"]
    elif field == "final":
        record["overall"]["final_variables"][0]["final_value"] = 1
    elif field == "shares":
        record["overall"]["shares"]["final"].pop(next(iter(record["overall"]["shares"]["final"])))
    else:
        period["held_position"].append(period["moves"][0]["actor"])
    audit = gate.audit_record(directory, record, write=False)
    assert audit["publication_status"] == "failed"
    assert any("differs from the artifact projection" in h for h in audit["hard_issues"])


@pytest.mark.parametrize("status", ["abstained", "failed", "missing"])
def test_committed_world_period_survives_scenario_channel_status(tmp_path, status):
    directory = Path(_copy_reflexive(tmp_path))
    path = directory / "world_state_history.jsonl"
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    rows[1]["scenario_round_status"] = status
    path.write_text("".join(json.dumps(row) + "\n" for row in rows))
    record = sr.build_record(str(directory), language="en", synthesis=False)
    assert [p["round"] for p in record["periods"]] == [1, 2, 3]
    assert gate.audit_record(str(directory), record, write=False)["publication_status"] == "passed"


@pytest.mark.parametrize("damage", ["missing", "malformed"])
def test_corrupt_history_does_not_shrink_the_committed_run(tmp_path, damage):
    directory = Path(_copy_reflexive(tmp_path))
    path = directory / "world_state_history.jsonl"
    rows = path.read_text().splitlines()
    rows[1] = "{broken" if damage == "malformed" else ""
    path.write_text("\n".join(rows))
    class NeverCalled:
        def chat(self, **kwargs):
            pytest.fail("invalid artifacts reached synthesis")
    record = sr.build_record(str(directory), language="en", synthesis=True, llm=NeverCalled())
    audit = gate.audit_record(str(directory), record, write=False)
    assert audit["publication_status"] == "failed"
    assert any("committed world periods" in h for h in audit["hard_issues"])


def test_forged_hollow_run_cannot_keep_narrative(tmp_path):
    directory = Path(_copy_reflexive(tmp_path))
    record = sr.build_record(str(directory), language="en", synthesis=False)
    summary = read(directory / "run_summary.json")
    summary["simulation_health"] = "hollow"
    write(directory / "run_summary.json", summary)
    record["health"]["simulation_health"] = "hollow"
    record["limits"]["stub"] = True
    audit = gate.audit_record(str(directory), record, write=False)
    assert audit["publication_status"] == "failed"
    assert any("health stub" in h for h in audit["hard_issues"])


def test_world_adapter_uses_period_snapshots_and_separates_messages(tmp_path):
    directory = tmp_path / "world"
    _write_world_v1(directory)
    result = read(directory / "world_result.json")
    result["trajectory"][1]["interactions"]["i1"]["status"] = "pending"
    result["trajectory"][1]["commitments"]["c1"].update(status="open", createdAt="2030-01-01T00:00:00Z")
    message = copy.deepcopy(result["world"]["interactions"]["i1"])
    message.update(kind="message", templateId="communicate", terms={"text": "An intention only."})
    for snapshot in [result["world"], *result["trajectory"][1:]]:
        snapshot["interactions"]["message1"] = message
    write(directory / "world_result.json", result)
    record = publish(directory)
    first, second = record["periods"]
    assert [o["status"] for o in first["offers"]] == ["pending"]
    assert [o["status"] for o in second["offers"]] == ["accepted"]
    assert any(e["kind"] == "message" for e in first["events"])
    assert any(e["kind"] == "commitment" and "open" in e["text"] for e in first["events"])
    assert any(e["kind"] == "commitment" and "fulfilled" in e["text"] for e in second["events"])
    assert all(t["round"] == 2 for t in record["overall"]["turning_points"])
    assert any("capacity" in t["why"] for t in record["overall"]["turning_points"])


def test_world_zero_round_incomplete_export_has_only_health_stub(tmp_path):
    directory = tmp_path / "world"
    _write_world_v1(directory)
    result = read(directory / "world_result.json")
    result.update(completed=False, round=0, committedRound=0, events=[])
    result["trajectory"] = result["trajectory"][:1]
    result["world"] = result["trajectory"][0]
    write(directory / "world_result.json", result)
    (directory / "run_summary.json").unlink()
    record = publish(directory)
    assert record["limits"]["stub"] and record["periods"] == []
    assert record["overall"]["shares"] == {}


@pytest.mark.parametrize("view", ["actor", "analyst", None])
def test_nonpublic_world_export_never_becomes_a_record(tmp_path, view):
    directory = tmp_path / "world"
    _write_world_v1(directory)
    result = read(directory / "world_result.json")
    result["view"] = view
    result["events"][0]["description"] = "PRIVATE_EXPORT_SENTINEL"
    write(directory / "world_result.json", result)
    record = sr.build_record(str(directory), language="en", synthesis=False)
    assert "PRIVATE_EXPORT_SENTINEL" not in json.dumps(record)
    assert gate.audit_record(str(directory), record, write=False)["publication_status"] == "failed"


def test_private_rows_in_public_export_are_excluded_at_load(tmp_path):
    directory = tmp_path / "world"
    _write_world_v1(directory)
    result = read(directory / "world_result.json")
    result["events"][0].update(visibility={"kind": "actors", "actorIds": ["buyer"]}, description="PRIVATE_EVENT")
    for snapshot in [result["world"], *result["trajectory"]]:
        snapshot["metrics"]["PRIVATE_METRIC"] = {"value": "123456.78", "visibility": {"kind": "analyst"}}
    write(directory / "world_result.json", result)
    record = publish(directory)
    assert "PRIVATE_" not in json.dumps(record)
    leak = copy.deepcopy(record)
    leak["overall"]["synthesis"]["text"] += "\n\nPRIVATE_EVENT (2030-01-02)."
    assert any(h.startswith("G6") for h in gate.audit_record(str(directory), leak, write=False)["hard_issues"])
    record["overall"]["synthesis"]["text"] += "\n\nOutput was 123456.78 (2030-01-02)."
    audit = gate.audit_record(str(directory), record, write=False)
    assert any(h.startswith("G2") for h in audit["hard_issues"])


@pytest.mark.parametrize("key,value", [("rounds_committed", True), ("rounds_committed", "3"),
                                      ("rounds_planned", -1), ("rounds_planned", 10**15),
                                      ("unexpected_prose", "An invented conclusion.")])
def test_invalid_structure_is_rejected_without_unbounded_count_expansion(tmp_path, key, value):
    directory = _copy_reflexive(tmp_path)
    record = sr.build_record(directory, language="en", synthesis=False)
    record[key] = value
    assert gate.audit_record(directory, record, write=False)["publication_status"] == "failed"


@pytest.mark.parametrize("flag", ["stub", "mechanical_only_rounds", "arbiter_failed_rounds", "seed_gaps"])
def test_limits_cannot_disagree_with_health_or_periods(tmp_path, flag):
    directory = _copy_reflexive(tmp_path)
    record = sr.build_record(directory, language="en", synthesis=False)
    record["limits"][flag] = True if flag == "stub" else "forged"
    audit = gate.audit_record(directory, record, write=False)
    assert audit["publication_status"] == "failed"
    assert any(h.startswith("G7") for h in audit["hard_issues"])


def test_one_good_claim_reference_does_not_exempt_a_fabricated_reference(tmp_path):
    directory = _copy_reflexive(tmp_path)
    record = sr.build_record(directory, language="en", synthesis=False)
    record["overall"]["synthesis"]["claims"][0]["refs"].append(
        {"file": "world_state_history.jsonl", "round": 800, "id": "round:800"})
    assert gate.audit_record(directory, record, write=False)["publication_status"] == "failed"


@pytest.mark.parametrize("location", ["health", "limits", "period", "overall"])
def test_boolean_cannot_impersonate_an_artifact_number(tmp_path, location):
    directory = _copy_reflexive(tmp_path)
    record = sr.build_record(directory, language="en", synthesis=False)
    if location in ("health", "limits"):
        record[location]["arbiter_failed_rounds"] = False
    elif location == "period":
        record["periods"][0]["behaviour"]["held"] = False
    else:
        fact = next(v for v in record["overall"]["final_variables"] if type(v["final_value"]) is bool)
        fact["final_value"] = int(fact["final_value"])
    assert gate.audit_record(directory, record, write=False)["publication_status"] == "failed"


def test_rejected_private_prose_is_not_echoed_in_other_gate_diagnostics(tmp_path):
    directory = Path(_copy_reflexive(tmp_path))
    path = directory / "world_actions.jsonl"
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    secret = "PRIVATE_SECRET [S7] We secretly intend to abandon our commitments tomorrow."
    rows[0]["private_rationale"] = secret
    path.write_text("".join(json.dumps(row) + "\n" for row in rows))
    record = sr.build_record(str(directory), language="en", synthesis=False)
    record["overall"]["synthesis"]["text"] += "\n\n" + secret + " (2026-10-23)"
    audit = gate.audit_record(str(directory), record, write=False)
    assert audit["publication_status"] == "failed"
    assert any(h.startswith("G6") for h in audit["hard_issues"])
    assert "PRIVATE_SECRET" not in json.dumps(audit)
    assert "abandon our commitments" not in json.dumps(audit)


@pytest.mark.parametrize("domain", ["investment", "trade", "coalition"])
def test_real_world_producer_compiles_without_oasis_summary(tmp_path, domain):
    from test_world_service_results import prepare
    from app.services.world_simulation.examples import ExamplePolicy
    from app.services.world_simulation.service import run_child
    _, _, directory = prepare(tmp_path, domain)
    assert run_child(directory, policy=ExamplePolicy(domain)) == 0
    assert not (directory / "run_summary.json").exists()
    record = publish(directory)
    assert not record["limits"]["stub"]
    assert record["rounds_committed"] == 4
    assert record["health"]["simulation_health"] == "ok"
    for lang in ("en", "zh"):
        assert sr.render_markdown(record, lang) == sr.render_markdown(record, lang)
        assert rc.banner_for(lang) in sr.render_markdown(record, lang)


@pytest.mark.parametrize("damage", ["changed", "missing", "symlink", "unsealed"])
def test_native_world_result_manifest_remains_sealed_after_publication(tmp_path, damage):
    from test_world_service_results import prepare
    from app.services.world_simulation.examples import ExamplePolicy
    from app.services.world_simulation.service import run_child
    _, _, directory = prepare(tmp_path, "investment")
    assert run_child(directory, policy=ExamplePolicy("investment")) == 0
    publish(directory)
    path = directory / "world_result_manifest.json"
    if damage == "changed":
        manifest = read(path)
        manifest["resultSha256"] = "0" * 64
        write(path, manifest)
    elif damage == "missing":
        path.unlink()
    elif damage == "symlink":
        copy_path = tmp_path / "same_manifest.json"
        copy_path.write_bytes(path.read_bytes())
        path.unlink()
        path.symlink_to(copy_path)
    else:
        audit_path = directory / rc.RECORD_AUDIT_JSON
        audit = read(audit_path)
        del audit["artifact_sha256"][path.name]
        write(audit_path, audit)
    assert rc.load_published_record(str(directory)) == (None, "stale_audit")
    assert not rc.is_published(str(directory))
