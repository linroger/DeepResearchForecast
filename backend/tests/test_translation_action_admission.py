"""Resource-admitted actions and transactional revision fencing, offline only."""

import copy
import threading

from flask import Flask, request
import pytest

from app.api import translations as api
from app.config import Config
from app.services.translation import scheduler
from app.services.translation.contracts import TranslationError
from app.services.translation.store import Store, database_path, file_lock


KIND = "action-admission-fixture"
IDENTITY = {
    "kind": "report",
    "ref_id": "synthetic_report",
    "scope": "public",
    "target_lang": "zh",
    "source_sha256": "synthetic-current-source",
}
SELECTION = {"ref_id": "synthetic_report", "view": "public", "target_lang": "zh"}


@pytest.fixture
def setup(tmp_path, monkeypatch):
    monkeypatch.setattr(Config, "UPLOAD_FOLDER", str(tmp_path / "uploads"))
    monkeypatch.setattr(api, "_authorizers", {}, raising=False)
    dispatched = []
    monkeypatch.setattr(scheduler, "start_scheduler", lambda: dispatched.append(True))
    app = Flask(__name__)
    app.register_blueprint(api.translations_bp, url_prefix="/api/translations")
    return app.test_client(), dispatched


def make_task(action, identity=None):
    with Store(database_path()) as store:
        task = store.create_task(KIND, identity or IDENTITY, {"private": "synthetic payload"})
        if action == "retry":
            epoch = store.elect()
            store.claim_task(epoch, [KIND])
            store.finish_task(
                task, epoch, error={"code": "fixture", "message": "Synthetic failure"}
            )
        return store.task(task)


def admit_resource(monkeypatch, *, admitted_identity=None):
    """A bounded resource reader: authority comes from server state and principal.

    Production adapters register their existing resource/visibility readers through
    this same interface. A client-supplied identity is deliberately never read.
    """
    current = copy.deepcopy(admitted_identity or IDENTITY)
    calls = []

    def resolve(selection, action):
        calls.append((copy.deepcopy(selection), action))
        principal = request.headers.get("X-Review-Principal")
        expected = {
            "ref_id": current["ref_id"],
            "view": current["scope"],
            "target_lang": current["target_lang"],
        }
        if principal != "permitted" or selection != expected:
            return None
        return copy.deepcopy(current)

    api.register_resource_authorizer(KIND, resolve)
    return calls


def post(client, task, action, *, revision=None, resource=None, permitted=True):
    return client.post(
        f"/api/translations/jobs/{task['job_id']}/{action}",
        json={
            "job_revision": task["job_revision"] if revision is None else revision,
            "resource": copy.deepcopy(SELECTION) if resource is None else resource,
        },
        headers={"X-Review-Principal": "permitted" if permitted else "denied"},
    )


@pytest.mark.parametrize("action", ["retry", "cancel"])
def test_unregistered_actions_fail_closed(setup, action):
    client, dispatched = setup
    task = make_task(action)
    response = post(client, task, action)
    assert response.status_code == 403
    assert scheduler.status(task["job_id"]) == task
    assert not dispatched


@pytest.mark.parametrize("action", ["retry", "cancel"])
def test_valid_resource_admitted_action_and_public_response(setup, monkeypatch, action):
    client, dispatched = setup
    calls = admit_resource(monkeypatch)
    task = make_task(action)
    response = post(client, task, action)
    assert response.status_code == 200
    data = response.json["data"]
    assert data["job_state"] == ("queued" if action == "retry" else "cancelled")
    assert data["job_revision"] == task["job_revision"] + 1
    assert calls == [(SELECTION, action)]
    assert "identity" not in data and "result" not in data
    assert "synthetic payload" not in response.text
    assert dispatched == ([True] if action == "retry" else [])


@pytest.mark.parametrize(
    "resource",
    [
        {**SELECTION, "ref_id": "another_report"},
        {**SELECTION, "view": "private_actor"},
        {**SELECTION, "target_lang": "en"},
    ],
)
def test_wrong_resource_view_or_language_cannot_retry(setup, monkeypatch, resource):
    client, dispatched = setup
    admit_resource(monkeypatch)
    task = make_task("retry")
    response = post(client, task, "retry", resource=resource)
    assert response.status_code == 403
    assert scheduler.status(task["job_id"]) == task and not dispatched


def test_matching_client_identity_is_not_resource_authority(setup, monkeypatch):
    client, dispatched = setup
    admit_resource(monkeypatch)
    task = make_task("retry")
    response = client.post(
        f"/api/translations/jobs/{task['job_id']}/retry",
        json={
            "job_revision": task["job_revision"],
            "resource": SELECTION,
            "identity": IDENTITY,
        },
    )
    assert response.status_code == 403
    assert scheduler.status(task["job_id"]) == task and not dispatched


def test_changed_authoritative_source_cannot_requeue_old_job(setup, monkeypatch):
    client, dispatched = setup
    admit_resource(monkeypatch, admitted_identity={**IDENTITY, "source_sha256": "new-source"})
    task = make_task("retry")
    response = post(client, task, "retry")
    assert response.status_code == 403
    assert scheduler.status(task["job_id"]) == task and not dispatched


def test_valid_private_view_is_not_blanket_denied(setup, monkeypatch):
    client, dispatched = setup
    private = {**IDENTITY, "scope": "private_actor"}
    admit_resource(monkeypatch, admitted_identity=private)
    task = make_task("retry", private)
    response = post(client, task, "retry", resource={**SELECTION, "view": "private_actor"})
    assert response.status_code == 200 and dispatched == [True]


@pytest.mark.parametrize(
    "payload",
    [
        None,
        [],
        "bad",
        {},
        {"job_revision": True},
        {"job_revision": 0},
        {"job_revision": -1},
        {"job_revision": "3"},
        {"job_revision": 3.0},
    ],
)
def test_generic_actions_require_an_integer_revision(setup, monkeypatch, payload):
    client, dispatched = setup
    admit_resource(monkeypatch)
    task = make_task("retry")
    response = client.post(f"/api/translations/jobs/{task['job_id']}/retry", json=payload)
    assert response.status_code == 400
    assert scheduler.status(task["job_id"]) == task and not dispatched


@pytest.mark.parametrize("resource", [None, {}, [], "public"])
def test_generic_actions_require_a_resource_selection(setup, monkeypatch, resource):
    client, dispatched = setup
    admit_resource(monkeypatch)
    task = make_task("retry")
    response = client.post(
        f"/api/translations/jobs/{task['job_id']}/retry",
        json={
            "job_revision": task["job_revision"],
            "resource": resource,
        },
    )
    assert response.status_code == 403
    assert scheduler.status(task["job_id"]) == task and not dispatched


def test_cancel_revision_check_and_mutation_are_atomic(setup, monkeypatch):
    client, dispatched = setup
    admit_resource(monkeypatch)
    task = make_task("cancel")
    original_read = api._read

    def read_then_retry(job_id):
        old = original_read(job_id)
        scheduler.cancel(job_id)
        with Store(database_path()) as store:
            store.retry_task(job_id)
        return old

    monkeypatch.setattr(api, "_read", read_then_retry)
    response = post(client, task, "cancel")
    assert response.status_code == 409 and response.json["code"] == "stale_job"
    latest = scheduler.status(task["job_id"])
    assert latest["job_state"] == "queued" and latest["job_revision"] == task["job_revision"] + 2
    assert not dispatched


@pytest.mark.parametrize("action", ["retry", "cancel"])
def test_duplicate_generic_action_with_old_revision_is_rejected(setup, monkeypatch, action):
    client, dispatched = setup
    admit_resource(monkeypatch)
    task = make_task(action)
    assert post(client, task, action).status_code == 200
    after = scheduler.status(task["job_id"])
    response = post(client, task, action)
    assert response.status_code == 409
    assert scheduler.status(task["job_id"]) == after
    assert dispatched == ([True] if action == "retry" else [])


@pytest.mark.parametrize("action", ["retry", "cancel"])
def test_resource_specific_call_without_revision_intentionally_uses_latest_state(setup, action):
    _, dispatched = setup
    task = make_task(action)
    with Store(database_path()) as store:
        with store.transaction():
            store.db.execute("UPDATE tasks SET revision=revision+1 WHERE id=?", (task["job_id"],))
    result = getattr(scheduler, action)(task["job_id"])
    assert result["job_revision"] == task["job_revision"] + 2
    assert result["job_state"] == ("queued" if action == "retry" else "cancelled")
    assert dispatched == ([True] if action == "retry" else [])


@pytest.mark.parametrize("action", ["retry", "cancel"])
def test_mutation_waits_for_publication_lock_then_checks_revision(setup, monkeypatch, action):
    _, dispatched = setup
    task = make_task(action)
    entered, finished = threading.Event(), threading.Event()
    original_lock = scheduler.file_lock
    outcome = []

    def observed_lock(*args, **kwargs):
        entered.set()
        return original_lock(*args, **kwargs)

    monkeypatch.setattr(scheduler, "file_lock", observed_lock)

    def mutate():
        try:
            getattr(scheduler, action)(task["job_id"], expected_revision=task["job_revision"])
        except TranslationError as exc:
            outcome.append(exc.code)
        finally:
            finished.set()

    lock_path = database_path().parent / "locks" / (task["job_id"] + ".publish.lock")
    with file_lock(lock_path):
        thread = threading.Thread(target=mutate)
        thread.start()
        assert entered.wait(2)
        assert not finished.wait(0.05)
        with Store(database_path()) as store:
            with store.transaction():
                store.db.execute(
                    "UPDATE tasks SET revision=revision+1 WHERE id=?", (task["job_id"],)
                )
    thread.join(2)
    assert not thread.is_alive() and outcome == ["stale_job"]
    assert scheduler.status(task["job_id"])["job_state"] == task["job_state"]
    assert not dispatched


def test_missing_task_has_no_mutation_or_dispatch(setup):
    _, dispatched = setup
    assert scheduler.retry("tj_" + "0" * 32, expected_revision=1) is None
    assert scheduler.cancel("tj_" + "0" * 32, expected_revision=1) is None
    assert not dispatched


def test_status_read_remains_redacted_and_read_only(setup):
    client, dispatched = setup
    task = make_task("retry")
    response = client.get(f"/api/translations/jobs/{task['job_id']}")
    assert response.status_code == 200
    assert "identity" not in response.json["data"] and "result" not in response.json["data"]
    assert scheduler.status(task["job_id"]) == task and not dispatched


@pytest.mark.parametrize("action", ["retry", "cancel"])
def test_two_simultaneous_actions_with_same_revision_have_one_winner(setup, action):
    _, dispatched = setup
    task = make_task(action)
    ready = threading.Barrier(2)
    outcomes = []

    def mutate():
        ready.wait(2)
        try:
            result = getattr(scheduler, action)(
                task["job_id"],
                expected_revision=task["job_revision"],
            )
            outcomes.append(result["job_state"])
        except TranslationError as exc:
            outcomes.append(exc.code)

    threads = [threading.Thread(target=mutate) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(3)
    assert all(not thread.is_alive() for thread in threads)
    assert sorted(outcomes) == sorted(["stale_job", "queued" if action == "retry" else "cancelled"])
    assert scheduler.status(task["job_id"])["job_revision"] == task["job_revision"] + 1
    assert dispatched == ([True] if action == "retry" else [])


@pytest.mark.parametrize("action", ["retry", "cancel"])
def test_completed_task_is_an_idempotent_noop_without_dispatch(setup, action):
    _, dispatched = setup
    task = make_task("cancel")
    with Store(database_path()) as store:
        epoch = store.elect()
        store.claim_task(epoch, [KIND])
        store.finish_task(task["job_id"], epoch, result={"available": True})
        complete = store.task(task["job_id"])
    result = getattr(scheduler, action)(
        task["job_id"],
        expected_revision=complete["job_revision"],
    )
    assert result == complete and not dispatched


def test_resolver_boolean_is_not_a_server_identity(setup):
    client, dispatched = setup
    api.register_resource_authorizer(KIND, lambda selection, action: True)
    task = make_task("retry")
    assert post(client, task, "retry").status_code == 403
    assert scheduler.status(task["job_id"]) == task and not dispatched
