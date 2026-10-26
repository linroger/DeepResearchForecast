"""Real durable executor scenarios with controlled model transport only."""
import copy
import json
import threading
import time

import pytest

from app.services.model_translation import translate_entries, translate_document, valid_document_receipt
from app.services.translation.contracts import TranslationError
from app.services.translation.store import Store, database_path


class Model:
    model = "controlled-v2-model"

    def __init__(self, *, fail_review=False, omit_review=False, reject=False):
        self.calls = []
        self.fail_review, self.omit_review, self.reject = fail_review, omit_review, reject

    def chat(self, messages, **kwargs):
        payload = json.loads(messages[-1]["content"])
        self.calls.append(payload)
        if "entries" in payload:
            return json.dumps({"translations": {k: text.replace("Outlook", "展望").replace("Value remains unchanged.", "数值保持不变。")
                                                for k, text in payload["entries"].items()}})
        if self.fail_review:
            self.fail_review = False
            raise TimeoutError("secret provider headers must never persist")
        reviews = {k: {"faithful": not self.reject, "complete": True, "target_language": True,
                       "issues": ["changed meaning"] if self.reject else []} for k in payload["pairs"]}
        if self.omit_review:
            self.omit_review = False
            reviews.pop(next(iter(reviews)))
        return json.dumps({"reviews": reviews})


@pytest.fixture
def storage(tmp_path, monkeypatch):
    from app.config import Config
    monkeypatch.setattr(Config, "UPLOAD_FOLDER", str(tmp_path / "uploads"))
    yield database_path()
    from app.services.translation.scheduler import stop_schedulers
    stop_schedulers()


IDENTITY = {"kind": "test-report", "ref_id": "report_test", "scope": {"view": "public"}}
PAIRS = [("a", "Value remains unchanged."), ("b", "Value remains unchanged.")]


def test_missing_review_retries_only_review_and_retains_good_entry(storage):
    model = Model(omit_review=True)
    result = translate_entries(model, PAIRS, "zh", identity=IDENTITY)
    assert len(result) == 2
    assert ["entries" in call for call in model.calls] == [True, False, False]
    assert list(model.calls[-1]["pairs"]) == ["a"]
    assert result.job["coverage"]["accepted"] == 2


def test_durable_candidate_survives_review_provider_failure(storage):
    first = Model(fail_review=True)
    result = translate_entries(first, PAIRS, "zh", identity=IDENTITY)
    assert not result and result.calls_used == 2
    second = Model()
    resumed = translate_entries(second, PAIRS, "zh", identity=IDENTITY)
    assert len(resumed) == 2 and len(second.calls) == 1
    assert "pairs" in second.calls[0]
    assert resumed.job["calls_used"] == 3
    assert "secret" not in storage.read_bytes().decode("latin1")


def test_completed_job_replay_has_no_model_calls(storage):
    first = translate_entries(Model(), PAIRS, "zh", identity=IDENTITY)
    second_model = Model()
    second = translate_entries(second_model, PAIRS, "zh", identity=IDENTITY)
    assert second == first and not second_model.calls
    assert second.calls_used == 0 and second.job["coverage"]["reused"] == 2


def test_explicit_refresh_does_not_import_previous_accepted_receipts(storage):
    first = translate_entries(Model(), PAIRS, "zh", identity=IDENTITY)
    seed = {key: {"source": source, "target": first[key], "receipt": first.receipts[key]} for key, source in PAIRS}
    model = Model()
    refreshed = translate_entries(model, PAIRS, "zh", identity=IDENTITY, seed=seed, force=True)
    assert refreshed == first and len(model.calls) == 2
    assert refreshed.job["job_id"] != first.job["job_id"]


def test_document_seed_rejects_changed_whole_source_even_with_same_outline(storage):
    source = "## Outlook\n\nValue remains unchanged."
    _, proof = translate_document(Model(), source, "zh")
    model = Model()
    current_source = source + "\n\nValue remains unchanged."
    _, result = translate_document(model, current_source, "zh", identity=IDENTITY, previous_proof=proof)
    assert len(model.calls) == 2 and result["job"]["coverage"]["reused"] == 0


@pytest.mark.parametrize("identity", [
    {**IDENTITY, "ref_id": "report_other"},
    {**IDENTITY, "scope": {"view": "actor", "actor_id": "private"}},
])
def test_changed_resource_or_visibility_never_reuses(storage, identity):
    first = translate_entries(Model(), PAIRS, "zh", identity=IDENTITY)
    model = Model()
    second = translate_entries(model, PAIRS, "zh", identity=identity)
    assert second.job["job_id"] != first.job["job_id"] and len(model.calls) == 2


@pytest.mark.parametrize("failed", [[12, 17], [16]])
def test_original_twenty_two_section_retry_reuses_valid_receipts(storage, failed):
    source = "\n\n".join(f"## Outlook {i}\n\nValue remains unchanged." for i in range(22))
    _, proof = translate_document(Model(), source, "zh")
    for index in failed:
        proof["sections"][index]["receipt"] = None
        proof["sections"][index]["target"] = proof["sections"][index]["source"]
    proof["complete"] = False
    from app.services.translation.contracts import trusted_import
    model = Model()
    target, resumed = translate_document(model, source, "zh", identity=IDENTITY, previous_proof=trusted_import(proof, IDENTITY))
    translated_keys = [key for call in model.calls if "entries" in call for key in call["entries"]]
    assert translated_keys == [f"section:{i}" for i in failed]
    assert resumed["job"]["coverage"]["reused"] == 22 - len(failed)
    assert valid_document_receipt(source, target, "zh", resumed)


def test_negative_review_stays_negative_after_bounded_repair(storage):
    model = Model(reject=True)
    result = translate_entries(model, PAIRS, "zh", identity=IDENTITY)
    assert not result and len(model.calls) == 4
    assert model.calls[2]["repair"] is True
    assert all("semantic review rejected" in str(x) for x in result.issues.values())


def test_explicit_retry_grants_bounded_new_window_without_resetting_cost(storage):
    first = translate_entries(Model(omit_review=True), PAIRS, "zh", max_calls=2, identity=IDENTITY)
    assert len(first) == 1
    second_model = Model()
    second = translate_entries(second_model, PAIRS, "zh", max_calls=2, identity=IDENTITY)
    assert len(second) == 2 and len(second_model.calls) == 1
    assert second.job["calls_used"] == 3 and second.job["call_budget"] == 4


def test_store_fences_old_owner_and_retains_unknown_call(storage):
    with Store(storage) as store:
        job = store.create_job(IDENTITY, PAIRS, "zh", "", 8)
        first = store.claim(job)
        attempt = store.reserve(job, first, "translating", ["a"])
        second = store.claim(job)
        assert second > first
        with pytest.raises(TranslationError, match="no longer owns"):
            store.checkpoint(job, first, {})
        row = store.db.execute("SELECT state FROM attempts WHERE id=?", (attempt,)).fetchone()
        assert row[0] == "unknown" and store.job(job)["calls"] == 1


def test_restart_after_candidate_checkpoint_does_not_translate(storage):
    from app.services.translation.contracts import SCHEMA
    # Simulate termination at the exact persisted candidate-before-validator boundary.
    with Store(storage) as store:
        identity = {"resource": IDENTITY, "engine": "model-translation/v1", "policy": "staged-review/v2"}
        job = store.create_job(identity, PAIRS, "zh", "", 48)
        fence = store.claim(job)
        units = store.units(job)
        for unit in units.values():
            unit.update(stage="validate", candidate="数值保持不变。")
        store.checkpoint(job, fence, units)
    model = Model()
    result = translate_entries(model, PAIRS, "zh", identity=IDENTITY)
    assert len(result) == 2 and len(model.calls) == 1 and "pairs" in model.calls[0]


def test_tampered_receipt_is_retranslated_not_admitted(storage):
    first = translate_entries(Model(), PAIRS, "zh", identity=IDENTITY)
    with Store(storage) as store:
        units = store.units(first.job["job_id"])
        units["a"]["candidate"] = "伪造文本。"
        store.checkpoint(first.job["job_id"], first.job["job_revision"], units)
    model = Model()
    result = translate_entries(model, PAIRS, "zh", identity=IDENTITY)
    assert result["a"] == "数值保持不变。"
    assert list(model.calls[0]["entries"]) == ["a"]


def test_status_read_does_not_create_store_or_acquire_provider(storage):
    from app.services.translation.scheduler import status
    assert status("tj_" + "a" * 32) is None
    assert not storage.exists()


def test_unavailable_store_returns_typed_error_without_rewriting_it(storage):
    storage.parent.mkdir(parents=True)
    storage.write_bytes(b"corrupt-store-preserve-for-recovery")
    before = storage.read_bytes()
    with pytest.raises(TranslationError, match="storage is unavailable") as error:
        Store(storage)
    assert error.value.code == "store_unavailable" and storage.read_bytes() == before


def test_scheduler_duplicate_submit_runs_one_handler(storage):
    from app.services.translation.scheduler import register_handler, submit, status
    entered, release = threading.Event(), threading.Event()
    calls = []

    def handler(payload):
        calls.append(payload)
        entered.set()
        assert release.wait(3)
        return {"available": True}

    register_handler("controlled-task", handler)
    one = submit("controlled-task", IDENTITY, {"source": "sealed"})
    assert entered.wait(3)
    two = submit("controlled-task", IDENTITY, {"source": "sealed"})
    assert one["job_id"] == two["job_id"]
    release.set()
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline and status(one["job_id"])["job_state"] == "running":
        time.sleep(.01)
    assert status(one["job_id"])["job_state"] == "completed" and len(calls) == 1


def test_scheduler_takeover_marks_abandoned_operation_interrupted(storage):
    with Store(storage) as store:
        task = store.create_task("controlled-task", IDENTITY, {})
        epoch = store.elect()
        assert store.claim_task(epoch, ["controlled-task"])[0] == task
        store.elect()
        assert store.task(task)["job_state"] == "interrupted"
        with pytest.raises(TranslationError):
            store.finish_task(task, epoch, result={"available": True})
        assert store.retry_task(task)["job_state"] == "queued"


@pytest.mark.guarded_runner
def test_two_process_submit_has_one_owner_and_one_effect(tmp_path):
    import pathlib
    import sqlite3
    import subprocess
    import sys
    script = pathlib.Path(__file__).parent / "fixtures" / "translation_job_v2_child.py"
    guard = sys.modules["main_offline_guard"]
    guard.allow_python_script(script)
    args = [sys.executable, str(script), str(tmp_path)]
    first = subprocess.Popen(args, cwd=tmp_path, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    second = subprocess.Popen(args, cwd=tmp_path, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    one, err_one = first.communicate(timeout=20)
    two, err_two = second.communicate(timeout=20)
    assert first.returncode == second.returncode == 0, (err_one, err_two)
    # App logging may precede the fixture's final JSON line.
    one, two = json.loads(one.strip().splitlines()[-1]), json.loads(two.strip().splitlines()[-1])
    assert one == two and one["state"] == "completed"
    with sqlite3.connect(tmp_path / "effects.sqlite3") as db:
        assert db.execute("SELECT COUNT(*) FROM effects").fetchone()[0] == 1


def test_generic_status_never_exposes_private_result(storage):
    from flask import Flask
    from app.api.translations import translations_bp
    with Store(storage) as store:
        task = store.create_task("private-view", {**IDENTITY, "scope": {"actor": "private"}}, {})
        epoch = store.elect()
        store.claim_task(epoch, ["private-view"])
        store.finish_task(task, epoch, result={"text": "actor-private source"})
    app = Flask(__name__)
    app.register_blueprint(translations_bp, url_prefix="/api/translations")
    response = app.test_client().get("/api/translations/jobs/" + task)
    assert response.status_code == 200
    assert "actor-private" not in response.text and "result" not in response.json["data"]
    assert "identity" not in response.json["data"]


def test_cancel_and_publication_share_ownership_boundary(storage):
    from app.services.translation.scheduler import register_handler, submit, status, cancel, publication_guard
    entered, release = threading.Event(), threading.Event()
    published = []

    def handler(payload):
        entered.set()
        assert release.wait(3)
        with publication_guard():
            published.append(True)
        return {"complete": True}

    register_handler("cancel-fixture", handler)
    task = submit("cancel-fixture", IDENTITY, {})
    assert entered.wait(3)
    cancel(task["job_id"])
    release.set()
    time.sleep(.05)
    assert status(task["job_id"])["job_state"] == "cancelled" and not published
