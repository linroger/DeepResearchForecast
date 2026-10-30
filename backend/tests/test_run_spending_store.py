"""Guarded synthetic acceptance of the durable spending authority (SB-01/06/11)."""
import asyncio
from contextlib import contextmanager
import contextvars
import hashlib
import importlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import threading
import time

import pytest

from app.services.official_data import bridge_module

sp = bridge_module("run_spending")
CHILD = Path(__file__).with_name("fixtures") / "run_spending_child.py"
_UNEXPECTED_SENDS = []


def unexpected_send():
    _UNEXPECTED_SENDS.append(True)
    return None


@pytest.fixture(autouse=True)
def isolated_latch(monkeypatch):
    _UNEXPECTED_SENDS.clear()
    for key in list(os.environ):
        if key.startswith("DRF_RUN_SPENDING_"):
            monkeypatch.delenv(key)
    monkeypatch.setattr(sp, "_REQUIRED", False)
    monkeypatch.setattr(sp, "_ACTIVE_AUTH", None)
    monkeypatch.setattr(sp, "_ENV_PIN", None)
    monkeypatch.setattr(sp, "_LOCAL_STOPS", {})
    monkeypatch.setattr(sp, "_binding", contextvars.ContextVar("test_binding", default=None))
    monkeypatch.setattr(sp, "_operation", contextvars.ContextVar("test_operation", default=None))
    yield
    assert not _UNEXPECTED_SENDS, "a denied transport was actually invoked"


def synthetic_manifest(tmp_path, *, cap="1.00", tool=False):
    root = tmp_path / "runtime"
    root.mkdir()
    (root / "spend").mkdir()
    (root / "app").mkdir()
    (root / "app/source.py").write_text("# synthetic source, no execution\n")
    registry = tmp_path / "registry"
    registry.mkdir()
    request = {"question": "synthetic only", "mode": "full", "paths": 1, "periods": 1, "seed": 7}
    source_files = {"app/source.py": hashlib.sha256((root / "app/source.py").read_bytes()).hexdigest()}
    route = {"kind": "openai_chat", "endpoint": "https://synthetic.invalid/v1", "model": "synthetic-model",
             "account_sha256": hashlib.sha256(b"synthetic-key").hexdigest(), "billing_class": "external_model",
             "basis_sha256": sp.hash_payload("synthetic-reviewed-tariff"), "input_bound": "enforced_context_ceiling",
             "input_ceiling": 100, "max_output_tokens": 1000, "max_tool_units": 0,
             "pricing": {"input_usd_per_million": "1000", "output_usd_per_million": "1000",
                         "tool_usd_per_unit": "0", "fixed_usd": "0", "surcharge_usd": "0"},
             "coverage": "all_billable_dimensions"}
    routes = {"model-main": route}
    if tool:
        routes["tool-search"] = {**route, "kind": "firecrawl_search", "model": "", "endpoint": "https://synthetic.invalid/search",
                                 "billing_class": "external_tool", "input_bound": "not_applicable", "input_ceiling": 0,
                                 "max_output_tokens": 0, "max_tool_units": 3,
                                 "pricing": {"input_usd_per_million": "0", "output_usd_per_million": "0", "tool_usd_per_unit": "0.2", "fixed_usd": "0", "surcharge_usd": "0"}}
    m = {"schema": "target-run-spending/v1", "authorization_id": "synthetic-auth", "root": str(root), "currency": "USD", "cap_usd": cap,
         "request_sha256": sp.hash_payload(request), "source_files": source_files, "source_sha256": sp.hash_payload(source_files),
         "routes_sha256": sp.hash_payload(routes), "resume_policy": "explicit_clean_only", "routes": routes}
    path = root / "spend/authorization.json"
    path.write_text(json.dumps(m))
    return m, path, registry, request


def envelope(*, output=500):
    return {"endpoint": "https://synthetic.invalid/v1", "model": "synthetic-model", "input_tokens": 100,
            "max_output_tokens": output, "tool_units": 0, "payload_sha256": sp.hash_payload({"synthetic_output": output})}


@contextmanager
def active(tmp_path, **kwargs):
    m, path, registry, request = synthetic_manifest(tmp_path, **kwargs)
    b = sp.create_authorization(path, registry_dir=registry)
    with sp.run_lock(b):
        b = sp.bind_pipeline(b, "pipe-synthetic", request)
        sp.activate_binding(b)
        with sp.operation("research", "synthetic-root"):
            yield b, m, request


def proof(b, m):
    return {"approval_sha256": sp.hash_payload("explicit later synthetic resume approval"),
            **{key: m[key] for key in ("request_sha256", "source_sha256", "routes_sha256")},
            "participants_sha256": sp.hash_payload(sp.summary(b)["participants"])}


def test_alias_and_legacy_context():
    assert importlib.import_module("run_spending") is sp
    assert importlib.import_module("deerflow_bridge.run_spending") is sp
    assert sp.required() is False and sp.current_binding() is None
    assert sp.qualify_route("unqualified", "anything") is None
    assert str(sp.SpendingStop("private credential text")) == "invalid_request"


def test_before_send_commit_and_no_refund(tmp_path):
    with active(tmp_path) as (b, _, _):
        def send():
            db = sqlite3.connect(Path(b["db_path"]).as_uri() + "?mode=ro", uri=True)
            assert db.execute("SELECT reserved,state FROM attempts").fetchall() == [(600_000, "unknown")]
            assert db.execute("SELECT created_utc FROM attempts").fetchone()[0].endswith("Z")
            assert db.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
            db.close()
            return "raw-response"
        assert sp.dispatch("model-main", envelope(), send, usage=lambda _: {"kind": "provider_reported", "input_tokens": 1, "output_tokens": 1, "provider_request_id": "private-id"}) == "raw-response"
        result = sp.summary(b)
        assert result["reserved_max_microusd"] == 600_000
        assert result["remaining_microusd"] == 400_000
        assert result["usage_kinds"] == {"missing": 0, "estimated": 0, "provider_reported": 1}
        assert "private-id" not in json.dumps(result)
        with pytest.raises(sp.SpendingStop, match="budget_exhausted"):
            sp.dispatch("model-main", envelope(), unexpected_send)
        assert sp.summary(b)["state"] == "halted_exhausted"


def test_equality_boundary_and_per_attempt_round_up(tmp_path):
    with active(tmp_path) as (b, _, _):
        sp.dispatch("model-main", envelope(output=400), lambda: None)
        sp.dispatch("model-main", envelope(output=400), lambda: None)
        assert sp.summary(b)["remaining_microusd"] == 0


@pytest.mark.parametrize("cap", [1.0, True, "NaN", "Infinity", "-1", "0", "0.0000001", "9223372036854.775808", "1e2"])
def test_invalid_currency_never_initializes(tmp_path, cap):
    _, path, registry, _ = synthetic_manifest(tmp_path, cap=cap)
    with pytest.raises(sp.SpendingStop):
        sp.create_authorization(path, registry_dir=registry)
    assert not (path.parent / "run.sqlite3").exists()
    assert not list(registry.iterdir())


@pytest.mark.parametrize("mutation", ["subscription", "empty_sources", "false_source", "zero_price", "nan_price", "float_price", "overflow", "unknown_dimension"])
def test_unverified_manifest_denied(tmp_path, mutation):
    m, path, registry, _ = synthetic_manifest(tmp_path)
    route = m["routes"]["model-main"]
    if mutation == "subscription":
        route["billing_class"] = "subscription_unverified"
    elif mutation == "empty_sources":
        m["source_files"] = {}
        m["source_sha256"] = sp.hash_payload({})
    elif mutation == "false_source":
        m["source_files"]["app/source.py"] = "0"*64
        m["source_sha256"] = sp.hash_payload(m["source_files"])
    elif mutation == "unknown_dimension":
        route["pricing"]["unpriced_cache"] = "0"
    elif mutation == "overflow":
        route["max_output_tokens"] = 2**63
    else:
        route["pricing"]["input_usd_per_million"] = {"zero_price": "0", "nan_price": "NaN", "float_price": 0.1}[mutation]
    m["routes_sha256"] = sp.hash_payload(m["routes"])
    path.write_text(json.dumps(m))
    with pytest.raises(sp.SpendingStop):
        sp.create_authorization(path, registry_dir=registry)
    assert not (path.parent / "run.sqlite3").exists()


def test_quote_upward_and_overflow(tmp_path):
    m, path, registry, request = synthetic_manifest(tmp_path)
    p = m["routes"]["model-main"]["pricing"]
    p["input_usd_per_million"] = "0.00000001"
    p["output_usd_per_million"] = "0.00000001"
    m["routes_sha256"] = sp.hash_payload(m["routes"])
    path.write_text(json.dumps(m))
    b = sp.create_authorization(path, registry_dir=registry)
    assert sp.quote_request("model-main", envelope(), b)["reserved_max_microusd"] == 1
    with sp.run_lock(b):
        b = sp.bind_pipeline(b, "pipe-synthetic", request)
        sp.activate_binding(b)
        with sp.operation("research", "round"):
            sp.dispatch("model-main", envelope(), lambda: None)
            sp.dispatch("model-main", envelope(), lambda: None)
            assert sp.summary(b)["reserved_max_microusd"] == 2


def test_duplicate_attempt_and_immutable_observation(tmp_path):
    with active(tmp_path) as (b, _, _):
        claim = sp.reserve_and_claim(b, "model-main", envelope(), stage="s", logical_key="k", attempt_id="stable")
        with pytest.raises(sp.SpendingStop, match="attempt_reused"):
            sp.reserve_and_claim(b, "model-main", envelope(), stage="s", logical_key="k", attempt_id="stable")
        first = sp.record_observation(claim)
        assert sp.record_observation(claim) == first
        with pytest.raises(sp.SpendingStop, match="observation_conflict"):
            sp.record_observation(claim, {"kind": "estimated", "input_tokens": 1})
        assert sp.summary(b)["reserved_max_microusd"] == 600_000
        db = sqlite3.connect(b["db_path"])
        with pytest.raises(sqlite3.IntegrityError):
            db.execute("UPDATE attempts SET reserved=0")
        with pytest.raises(sqlite3.IntegrityError):
            db.execute("DELETE FROM attempts")
        db.close()


def test_unknown_halts_and_late_evidence_does_not_resume(tmp_path):
    with active(tmp_path) as (b, _, _):
        claim = sp.reserve_and_claim(b, "model-main", envelope(), stage="s", logical_key="k")
        sp.halt(b, "unknown_outcome")
        sp.record_observation(claim, {"kind": "provider_reported", "output_tokens": 2})
        assert sp.summary(b)["state"] == "halted_unknown"
        with pytest.raises(sp.SpendingStop, match="unknown_outcome"):
            sp.check_active(b)


@pytest.mark.parametrize("kind", ["raised", "returned", "extractor", "overbound", "invoice"])
def test_unknown_and_integrity_classification(tmp_path, kind):
    with active(tmp_path) as (b, _, _):
        def send():
            if kind == "raised":
                raise TimeoutError("secret raw provider body")
            return None
        def usage(_):
            if kind == "extractor":
                raise ValueError("secret parsing body")
            if kind == "returned":
                return {"kind": "missing", "outcome": "unknown"}
            if kind == "overbound":
                return {"kind": "provider_reported", "output_tokens": 501}
            return {"kind": "estimated", "verified_billed_usd": "0"}
        with pytest.raises(sp.SpendingStop) as exc:
            sp.dispatch("model-main", envelope(), send, usage=usage)
        assert "secret" not in str(exc.value)
        assert exc.value.code in {"unknown_outcome", "usage_integrity"}
        assert sp.summary(b)["reserved_max_microusd"] == 600_000
        assert sp.summary(b)["state"].startswith("halted_")


def test_observed_empty_refusal_and_async_tools(tmp_path):
    with active(tmp_path, cap="2.00", tool=True) as (b, _, _):
        assert sp.dispatch("model-main", envelope(), lambda: "observed-400", usage=lambda _: None) == "observed-400"
        assert sp.dispatch("model-main", envelope(), lambda: "") == ""
        request = {"endpoint": "https://synthetic.invalid/search", "model": "", "input_tokens": 0,
                   "max_output_tokens": 0, "tool_units": 3, "payload_sha256": sp.hash_payload({"limit": 1})}
        async def send():
            assert sp.summary(b)["reserved_max_microusd"] == 1_800_000
            return {"credits": 1}
        assert asyncio.run(sp.dispatch_async("tool-search", request, send, usage=lambda _: {"kind": "provider_reported", "tool_units": 1})) == {"credits": 1}
        result = sp.summary(b)
        assert result["attempt_count"] == 3
        assert result["usage_kinds"]["missing"] == 2
        assert result["route_reserved_microusd"]["tool-search"] == 600_000


def test_missing_thread_context_is_required_not_legacy(tmp_path):
    with active(tmp_path) as (b, _, _):
        copied = contextvars.copy_context()
        results = []
        t = threading.Thread(target=lambda: copied.run(lambda: results.append(sp.check_context())))
        t.start()
        t.join()
        assert results == [b]
        errors = []
        def worker():
            try:
                sp.check_context()
            except sp.SpendingStop as exc:
                errors.append(exc.code)
        t = threading.Thread(target=worker)
        t.start()
        t.join()
        assert errors == ["missing_context"]
        assert sp.current_binding() == b
        with pytest.raises(sp.SpendingStop, match="missing_context"):
            sp.check_active(b)


def test_env_latch_and_child_operation_hash(tmp_path, monkeypatch):
    with active(tmp_path) as (b, _, _):
        child = sp.register_participant(b, "child", spawn_receipt_sha256=sp.hash_payload("spawn"))
        env = sp.export_environment(child)
        for k, v in env.items():
            monkeypatch.setenv(k, v)
        assert sp.binding_from_environment() == child
        monkeypatch.setenv("DRF_RUN_SPENDING_OPERATION", json.dumps({"stage": "tampered", "logical_key": "tampered"}))
        with pytest.raises(sp.SpendingStop, match="missing_context"):
            sp.binding_from_environment()
        for k in env:
            monkeypatch.delenv(k)
        assert sp.required()
        with pytest.raises(sp.SpendingStop, match="missing_context"):
            sp.binding_from_environment()


def test_clean_resume_never_resets_and_late_fence(tmp_path):
    with active(tmp_path) as (b, m, _):
        claim = sp.reserve_and_claim(b, "model-main", envelope(), stage="s", logical_key="k")
        sp.record_observation(claim)
        sp.mark_recoverable(b)
        fresh = sp.resume_existing(b, proof(b, m))
        assert fresh["generation"] == 2
        with pytest.raises(sp.SpendingStop, match="stale_generation"):
            sp.record_observation(claim)
        sp.activate_binding(fresh)
        with pytest.raises(sp.SpendingStop, match="budget_exhausted"):
            sp.dispatch("model-main", envelope(), unexpected_send)
        assert sp.summary(fresh)["reserved_max_microusd"] == 600_000


def test_children_must_exit_before_resume(tmp_path):
    with active(tmp_path) as (b, m, _):
        sp.register_participant(b, "child", spawn_receipt_sha256=sp.hash_payload("spawn"))
        sp.mark_recoverable(b)
        with pytest.raises(sp.SpendingStop, match="resume_denied"):
            sp.resume_existing(b, proof(b, m))
        sp.participant_exited(b, "child", exit_receipt_sha256=sp.hash_payload("joined-owned-child"))
        fresh = sp.resume_existing(b, proof(b, m))
        assert fresh["generation"] == 2


@pytest.mark.parametrize("reason", ["unknown_outcome", "budget_exhausted", "halted_cancelled", "closed"])
def test_terminal_state_cannot_reopen(tmp_path, reason):
    with active(tmp_path) as (b, m, _):
        sp.halt(b, reason)
        sp.mark_recoverable(b)
        with pytest.raises(sp.SpendingStop, match="resume_denied"):
            sp.resume_existing(b, proof(b, m))
        if reason == "closed":
            sp.close_run(b)


@pytest.mark.parametrize("drift", ["source", "cap", "route", "db_missing", "db_replaced", "db_corrupt", "symlink"])
def test_drift_fails_closed_and_no_recreation(tmp_path, drift):
    with active(tmp_path) as (b, m, _):
        dbpath = Path(b["db_path"])
        if drift == "source":
            (Path(b["root"]) / "app/source.py").write_text("changed")
        elif drift in {"cap", "route"}:
            if drift == "cap":
                m["cap_usd"] = "5.00"
            else:
                m["routes"]["model-main"]["pricing"]["output_usd_per_million"] = "1"
                m["routes_sha256"] = sp.hash_payload(m["routes"])
            Path(b["manifest_path"]).write_text(json.dumps(m))
        elif drift == "db_corrupt":
            dbpath.write_bytes(b"invalid database")
        else:
            old = dbpath.with_name("preserved.sqlite3")
            dbpath.rename(old)
            if drift == "db_replaced":
                dbpath.write_bytes(old.read_bytes())
            elif drift == "symlink":
                dbpath.symlink_to(old)
        with pytest.raises(sp.SpendingStop):
            sp.dispatch("model-main", envelope(), unexpected_send)
        if drift == "db_missing":
            assert not dbpath.exists()


def test_registry_prevents_deleted_db_cap_reset(tmp_path):
    m, path, registry, _ = synthetic_manifest(tmp_path)
    b = sp.create_authorization(path, registry_dir=registry)
    Path(b["db_path"]).unlink()
    with pytest.raises(sp.SpendingStop, match="authorization_consumed"):
        sp.create_authorization(path, registry_dir=registry)
    assert not Path(b["db_path"]).exists()


def test_busy_database_denies_without_send(tmp_path):
    with active(tmp_path) as (b, _, _):
        db = sqlite3.connect(b["db_path"], isolation_level=None)
        db.execute("BEGIN IMMEDIATE")
        try:
            with pytest.raises(sp.SpendingStop, match="storage_unavailable"):
                sp.dispatch("model-main", envelope(), unexpected_send)
        finally:
            db.execute("ROLLBACK")
            db.close()


def launch_child(tmp_path, b, name, mode, **extra):
    child = sp.register_participant(b, name, spawn_receipt_sha256=sp.hash_payload({"child": name, "mode": mode}))
    control = {"request": envelope(), "marker": str(tmp_path / (name + ".send")),
               "ready": str(tmp_path / (name + ".ready")), "go": str(tmp_path / "go"),
               "claim_path": str(tmp_path / (name + ".claim.json")), **extra}
    path = tmp_path / (name + ".control.json")
    path.write_text(json.dumps(control))
    env = {**os.environ, **sp.export_environment(child)}
    p = subprocess.Popen([sys.executable, "-B", str(CHILD), mode, str(path)], env=env,
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    return p, control


def test_independent_process_060_plus_060_under_100(tmp_path):
    with active(tmp_path) as (b, _, _):
        a, ca = launch_child(tmp_path, b, "worker-a", "race")
        c, cc = launch_child(tmp_path, b, "worker-b", "race")
        deadline = time.monotonic() + 15
        while not all(Path(x["ready"]).exists() for x in (ca, cc)):
            assert time.monotonic() < deadline, "children did not reach race barrier"
            time.sleep(0.01)
        Path(ca["go"]).write_text("go")
        outputs = []
        for p, name in ((a, "worker-a"), (c, "worker-b")):
            out, err = p.communicate(timeout=15)
            assert p.returncode == 0, err
            outputs.append(json.loads(out)["outcome"])
            sp.participant_exited(b, name, exit_receipt_sha256=sp.hash_payload({"pid": p.pid, "returncode": p.returncode}))
        assert sorted(outputs) == ["budget_exhausted", "sent"]
        assert sum(Path(x["marker"]).exists() for x in (ca, cc)) == 1
        result = sp.summary(b)
        assert result["reserved_max_microusd"] == 600_000 and result["attempt_count"] == 1


@pytest.mark.parametrize("mode,exit_code,total,sent", [("before-commit", 71, 0, False), ("after-commit", 72, 600_000, False), ("after-send", 73, 600_000, True)])
def test_process_crash_retains_only_committed_maxima(tmp_path, mode, exit_code, total, sent):
    with active(tmp_path) as (b, m, _):
        p, control = launch_child(tmp_path, b, "crash-child", mode)
        _, err = p.communicate(timeout=15)
        assert p.returncode == exit_code, err
        sp.participant_exited(b, "crash-child", exit_receipt_sha256=sp.hash_payload({"pid": p.pid, "returncode": p.returncode}))
        assert Path(control["marker"]).exists() is sent
        assert sp.summary(b)["reserved_max_microusd"] == total
        if total:
            sp.mark_recoverable(b)  # cannot overwrite the participant-exit halt
            assert sp.summary(b)["state"] == "halted_unknown"
            with pytest.raises(sp.SpendingStop, match="resume_denied"):
                sp.resume_existing(b, proof(b, m))
        else:
            sp.dispatch("model-main", envelope(), lambda: "new admitted response")
            assert sp.summary(b)["reserved_max_microusd"] == 600_000


def test_known_child_exit_immediately_halts_unknown(tmp_path):
    with active(tmp_path) as (b, _, _):
        child = sp.register_participant(b, "lost", spawn_receipt_sha256=sp.hash_payload("spawn-lost"))
        sp.participant_started(child)
        sp.reserve_and_claim(child, "model-main", envelope(), stage="research", logical_key="lost")
        sp.participant_exited(b, "lost", exit_receipt_sha256=sp.hash_payload("joined-lost"))
        assert sp.summary(b)["state"] == "halted_unknown"
        with pytest.raises(sp.SpendingStop, match="unknown_outcome"):
            sp.dispatch("model-main", envelope(output=100), unexpected_send)


def test_removed_binding_thread_cannot_silently_restore_dispatch(tmp_path):
    with active(tmp_path) as (b, _, _):
        token = sp._binding.set(None)
        try:
            with pytest.raises(sp.SpendingStop, match="missing_context"):
                sp.check_context()
        finally:
            sp._binding.reset(token)
        with pytest.raises(sp.SpendingStop, match="missing_context"):
            sp.dispatch("model-main", envelope(), unexpected_send)


@pytest.mark.parametrize("change", [{"routes": []}, {"root": []}, {"cap_usd": {}}, {"routes": {"a": {}}}])
def test_malformed_manifest_sanitized(tmp_path, change):
    m, _, _, _ = synthetic_manifest(tmp_path)
    m.update(change)
    with pytest.raises(sp.SpendingStop):
        sp.validate_manifest(m)


def test_removed_imported_environment_denies_even_retained_context(tmp_path, monkeypatch):
    with active(tmp_path) as (b, _, _):
        child = sp.register_participant(b, "env-child", spawn_receipt_sha256=sp.hash_payload("env-spawn"))
        env = sp.export_environment(child)
        for k, v in env.items():
            monkeypatch.setenv(k, v)
        sp.activate_binding(sp.binding_from_environment())
        assert sp.check_context()["participant_id"] == "env-child"
        monkeypatch.delenv("DRF_RUN_SPENDING_BINDING")
        with pytest.raises(sp.SpendingStop, match="missing_context"):
            sp.check_context()


def test_nested_operation_preserves_root_ancestry(tmp_path):
    with active(tmp_path, cap="2.00") as (b, _, _):
        with sp.operation("branch", "root-a"):
            with sp.operation("model", "same-label-and-payload"):
                sp.dispatch("model-main", envelope(), lambda: None)
        with sp.operation("branch", "root-b"):
            with sp.operation("model", "same-label-and-payload"):
                sp.dispatch("model-main", envelope(), lambda: None)
        db = sqlite3.connect(b["db_path"])
        assert db.execute("SELECT count(DISTINCT logical_hash) FROM attempts").fetchone()[0] == 2
        db.close()


def test_source_drift_cannot_self_clear_when_bytes_restored(tmp_path):
    with active(tmp_path) as (b, _, _):
        source = Path(b["root"]) / "app/source.py"
        original = source.read_bytes()
        source.write_bytes(b"changed")
        with pytest.raises(sp.SpendingStop, match="source_drift"):
            sp.check_active()
        source.write_bytes(original)
        with pytest.raises(sp.SpendingStop, match="source_drift"):
            sp.dispatch("model-main", envelope(), unexpected_send)


def test_integrity_breach_retains_sanitized_usage_evidence(tmp_path):
    with active(tmp_path) as (b, _, _):
        with pytest.raises(sp.SpendingStop, match="usage_integrity"):
            sp.dispatch("model-main", envelope(), lambda: None,
                        usage=lambda _: {"kind": "provider_reported", "output_tokens": 501, "provider_request_id": "private-breach-id"})
        db = sqlite3.connect(b["db_path"])
        row = db.execute("SELECT observation,state FROM attempts").fetchone()
        db.close()
        assert row[0] is not None
        assert json.loads(row[0])["output_tokens"] == 501
        assert "private-breach-id" not in row[0]
        assert row[1] == "integrity_breach"
        assert sp.summary(b)["usage_kinds"]["provider_reported"] == 1


def test_manifest_unhashable_kind_is_fixed_code(tmp_path):
    m, _, _, _ = synthetic_manifest(tmp_path)
    m["routes"]["model-main"]["kind"] = []
    with pytest.raises(sp.SpendingStop):
        sp.validate_manifest(m)


def test_lock_permission_failure_is_sanitized(tmp_path):
    _, path, registry, _ = synthetic_manifest(tmp_path)
    b = sp.create_authorization(path, registry_dir=registry)
    lock = path.parent / "run.lock"
    lock.chmod(0)
    try:
        with pytest.raises(sp.SpendingStop) as exc:
            with sp.run_lock(b):
                pytest.fail("unreadable lock must refuse")
        assert str(tmp_path) not in str(exc.value)
    finally:
        lock.chmod(0o600)


def test_repeated_trailing_slash_is_not_same_route(tmp_path):
    with active(tmp_path):
        with pytest.raises(sp.SpendingStop, match="unsupported_route"):
            sp.qualify_route("openai_chat", "https://synthetic.invalid/v1//", "synthetic-model",
                             account_sha256=hashlib.sha256(b"synthetic-key").hexdigest())


def test_required_qualification_demands_exact_credential_fingerprint(tmp_path):
    with active(tmp_path):
        assert sp.qualify_route("openai_chat", "https://synthetic.invalid/v1/", "synthetic-model",
                                account_sha256=hashlib.sha256(b"synthetic-key").hexdigest()) == "model-main"
        with pytest.raises(sp.SpendingStop, match="billing_class_unverified"):
            sp.qualify_route("openai_chat", "https://synthetic.invalid/v1", "synthetic-model")


def test_fork_hook_closes_inherited_locks_without_unlock(monkeypatch):
    # The unchanged guard forbids actual fork. Exercise the registered hook's
    # descriptor rule directly; independent process tests use approved exec.
    closed = []
    monkeypatch.setattr(sp, "_LOCK_FDS", {123, 456})
    monkeypatch.setattr(sp, "_FORKED_PROCESS", False)
    monkeypatch.setattr(sp.os, "close", closed.append)
    monkeypatch.setattr(sp.fcntl, "flock", lambda *_: pytest.fail("fork hook must never LOCK_UN"))
    sp._after_fork()
    assert set(closed) == {123, 456}
    assert sp._LOCK_FDS == set() and sp._FORKED_PROCESS
    with pytest.raises(sp.SpendingStop, match="invalid_binding"):
        sp.open_existing({})


def test_optional_sidecar_can_disappear_but_symlink_denies(tmp_path, monkeypatch):
    optional = tmp_path / "run.sqlite3-wal"
    assert sp._path(optional, optional=True) is None
    real = tmp_path / "real"
    real.write_text("synthetic")
    optional.symlink_to(real)
    with pytest.raises(sp.SpendingStop, match="invalid_binding"):
        sp._path(optional, optional=True)
    optional.unlink()
    optional.mkdir()
    with pytest.raises(sp.SpendingStop, match="storage_unavailable"):
        sp._path(optional, optional=True)


def test_cancel_after_claim_retains_and_blocks_later_claim(tmp_path):
    with active(tmp_path) as (b, _, _):
        claim = sp.reserve_and_claim(b, "model-main", envelope(), stage="s", logical_key="cancel")
        sp.halt(b, "halted_cancelled")
        sp.record_observation(claim, {"kind": "missing"})
        assert sp.summary(b)["reserved_max_microusd"] == 600_000
        with pytest.raises(sp.SpendingStop, match="halted_cancelled"):
            sp.dispatch("model-main", envelope(output=100), unexpected_send)
        assert sp.summary(b)["attempt_count"] == 1


def test_initialization_race_consumes_authorization_once(tmp_path):
    _, path, registry, _ = synthetic_manifest(tmp_path)
    processes = []
    for name in ("creator-a", "creator-b"):
        control = {"manifest_path": str(path), "registry_dir": str(registry),
                   "ready": str(tmp_path / (name + ".ready")), "go": str(tmp_path / "go")}
        cp = tmp_path / (name + ".json")
        cp.write_text(json.dumps(control))
        processes.append((subprocess.Popen([sys.executable, "-B", str(CHILD), "create", str(cp)],
                                           stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True), control))
    deadline = time.monotonic() + 15
    while not all(Path(c["ready"]).exists() for _, c in processes):
        assert time.monotonic() < deadline
        time.sleep(0.01)
    (tmp_path / "go").write_text("go")
    outcomes = []
    for p, _ in processes:
        out, err = p.communicate(timeout=15)
        assert p.returncode == 0, err
        outcomes.append(json.loads(out)["outcome"])
    assert sorted(outcomes) == ["authorization_consumed", "created"]
    db = sqlite3.connect(str(path.parent / "run.sqlite3"))
    assert db.execute("SELECT count(*),cap FROM run_authorization").fetchone() == (1, 1_000_000)
    db.close()


def test_partial_creation_registry_is_not_reusable(tmp_path, monkeypatch):
    _, path, registry, _ = synthetic_manifest(tmp_path)
    def fail(*_):
        raise OSError("private path or provider data")
    with monkeypatch.context() as patch:
        patch.setattr(sp.os, "link", fail)
        with pytest.raises(sp.SpendingStop, match="storage_unavailable"):
            sp.create_authorization(path, registry_dir=registry)
    assert not (path.parent / "run.sqlite3").exists()
    with pytest.raises(sp.SpendingStop, match="authorization_consumed"):
        sp.create_authorization(path, registry_dir=registry)


def test_second_pipeline_binding_cannot_mint_allowance(tmp_path):
    with active(tmp_path) as (b, _, request):
        assert sp.bind_pipeline(b, b["pipeline_id"], request) == b
        with pytest.raises(sp.SpendingStop, match="binding_conflict"):
            sp.bind_pipeline(b, "different-pipeline", request)
        assert sp.summary(b)["cap_microusd"] == 1_000_000
        assert sp.summary(b)["pipeline_id"] == b["pipeline_id"]


def test_foreign_module_collision_uses_original_typed_stop(tmp_path):
    from importlib.util import spec_from_file_location, module_from_spec
    with active(tmp_path):
        copied = tmp_path / "foreign_module.py"
        copied.write_bytes(Path(sp.__file__).read_bytes())
        spec = spec_from_file_location("foreign_spending", copied)
        module = module_from_spec(spec)
        sys.modules[spec.name] = module
        try:
            with pytest.raises(sp.SpendingStop, match="source_drift"):
                spec.loader.exec_module(module)
        finally:
            sys.modules.pop(spec.name, None)
        assert importlib.import_module("run_spending") is sp
        with pytest.raises(sp.SpendingStop, match="source_drift"):
            sp.check_active()


def test_first_activation_cannot_erase_imported_environment_pin(tmp_path, monkeypatch):
    m, path, registry, request = synthetic_manifest(tmp_path)
    b = sp.create_authorization(path, registry_dir=registry)
    with sp.run_lock(b):
        b = sp.bind_pipeline(b, "pipe-synthetic", request)
        env = sp.export_environment(b)
        for key, value in env.items():
            monkeypatch.setenv(key, value)
        imported = sp.binding_from_environment()
        assert sp._ACTIVE_AUTH is None
        monkeypatch.delenv("DRF_RUN_SPENDING_BINDING")
        with pytest.raises(sp.SpendingStop, match="missing_context"):
            sp.activate_binding(imported)


def test_explicit_binding_admission_checks_environment_pin(tmp_path, monkeypatch):
    with active(tmp_path) as (b, _, _):
        for key, value in sp.export_environment(b).items():
            monkeypatch.setenv(key, value)
        sp.binding_from_environment()
        monkeypatch.delenv("DRF_RUN_SPENDING_BINDING")
        with pytest.raises(sp.SpendingStop, match="missing_context"):
            sp.reserve_and_claim(b, "model-main", envelope(), stage="s", logical_key="bypass")
        assert sp.summary(b)["attempt_count"] == 0


def test_corrupt_registry_repair_does_not_restore_dispatch(tmp_path):
    with active(tmp_path) as (b, _, _):
        path = sp._registry_path(b, ".json")
        original = path.read_bytes()
        path.write_text("{}")
        with pytest.raises(sp.SpendingStop):
            sp.check_active()
        path.write_bytes(original)
        with pytest.raises(sp.SpendingStop):
            sp.dispatch("model-main", envelope(), unexpected_send)


def test_symlink_loop_sidecar_is_fixed_code_and_permanent(tmp_path, monkeypatch):
    with active(tmp_path) as (b, _, _):
        path = Path(b["db_path"] + "-wal")
        assert not path.exists()
        # Real symlinks are covered separately. The guard resolves deletion
        # targets and cannot clean a self-loop; inject that resolution failure
        # on a regular temporary file without relaxing the guard.
        path.write_text("synthetic sidecar")
        original = Path.resolve
        def fail_resolve(self, *args, **kwargs):
            if self == path:
                raise RuntimeError("Symlink loop from private path")
            return original(self, *args, **kwargs)
        try:
            with monkeypatch.context() as patch:
                patch.setattr(Path, "resolve", fail_resolve)
                with pytest.raises(sp.SpendingStop):
                    sp.check_active()
        finally:
            path.unlink()
        with pytest.raises(sp.SpendingStop):
            sp.check_active()


def test_parent_environment_binding_upgrade_is_verified(tmp_path, monkeypatch):
    _, path, registry, request = synthetic_manifest(tmp_path)
    b = sp.create_authorization(path, registry_dir=registry)
    with sp.run_lock(b):
        for key, value in sp.export_environment(b).items():
            monkeypatch.setenv(key, value)
        imported = sp.binding_from_environment()
        bound = sp.bind_pipeline(imported, "pipe-synthetic", request)
        sp.activate_binding(bound)
        for key, value in sp.export_environment(bound).items():
            monkeypatch.setenv(key, value)
        with sp.operation("pipeline", "root"):
            assert sp.check_context() == bound


def test_initial_activation_binding_and_resume_adopt_only_committed_env(tmp_path, monkeypatch):
    m, path, registry, request = synthetic_manifest(tmp_path)
    b = sp.create_authorization(path, registry_dir=registry)
    for key, value in sp.export_environment(b).items():
        monkeypatch.setenv(key, value)
    sp.activate_binding(sp.binding_from_environment())
    with sp.run_lock(b):
        bound = sp.bind_pipeline(b, "pipe-synthetic", request)
        assert json.loads(os.environ["DRF_RUN_SPENDING_BINDING"]) == bound
        sp.activate_binding(bound)
        with sp.operation("pipeline", "root"):
            sp.dispatch("model-main", envelope(), lambda: None)
            sp.mark_recoverable(bound)
            fresh = sp.resume_existing(bound, proof(bound, m))
            assert json.loads(os.environ["DRF_RUN_SPENDING_BINDING"]) == fresh
            sp.activate_binding(fresh)
            assert sp.check_context() == fresh
            assert sp.summary(fresh)["reserved_max_microusd"] == 600_000
        # No direct caller environment mutation is authorized by a transition.
        monkeypatch.setenv("DRF_RUN_SPENDING_BINDING", json.dumps(bound))
        with pytest.raises(sp.SpendingStop, match="missing_context"):
            sp.check_active(fresh)


def test_concurrent_pin_reader_cannot_poison_committed_resume(tmp_path, monkeypatch):
    with active(tmp_path) as (b, m, _):
        for key, value in sp.export_environment(b).items():
            monkeypatch.setenv(key, value)
        sp.binding_from_environment()
        sp.mark_recoverable(b)
        resume_proof = proof(b, m)
        assigned, release, entered, finished = (threading.Event() for _ in range(4))
        original = type(os.environ).__setitem__
        adopted, failures, reads = [], [], []
        def pause_assignment(env, key, value):
            original(env, key, value)
            if key == "DRF_RUN_SPENDING_BINDING" and json.loads(value)["generation"] == 2:
                assigned.set()
                assert release.wait(5)
        monkeypatch.setattr(type(os.environ), "__setitem__", pause_assignment)
        def writer():
            try:
                adopted.append(sp.resume_existing(b, resume_proof))
            except BaseException as exc:
                failures.append(type(exc).__name__)
        def reader():
            entered.set()
            try:
                sp.check_active(b)
                reads.append("incorrectly-active")
            except sp.SpendingStop as exc:
                reads.append(exc.code)
            finally:
                finished.set()
        wt = threading.Thread(target=writer)
        wt.start()
        assert assigned.wait(5)
        rt = threading.Thread(target=reader)
        rt.start()
        try:
            assert entered.wait(5)
            assert not finished.wait(0.2), "reader observed a half-adopted environment pin"
        finally:
            release.set()
            wt.join(5)
            rt.join(5)
        assert failures == [] and reads == ["stale_generation"]
        sp.activate_binding(adopted[0])
        assert sp.check_context()["generation"] == 2
        assert sp.summary(adopted[0])["state"] == "active"


def test_parent_bind_preserves_absent_environment_operation(tmp_path, monkeypatch):
    _, path, registry, request = synthetic_manifest(tmp_path)
    initial = sp.create_authorization(path, registry_dir=registry)
    parent_env = sp.export_environment(initial)
    assert "DRF_RUN_SPENDING_OPERATION" not in parent_env
    for key, value in parent_env.items():
        monkeypatch.setenv(key, value)
    sp.activate_binding(sp.binding_from_environment())
    with sp.run_lock(initial):
        with sp.operation("pipeline", sp.hash_payload(request)):
            bound = sp.bind_pipeline(initial, "pipe-synthetic", request)
            sp.activate_binding(bound)
            assert sp.check_context() == bound
            assert sp.qualify_route("openai_chat", "https://synthetic.invalid/v1", "synthetic-model",
                                    account_sha256=hashlib.sha256(b"synthetic-key").hexdigest()) == "model-main"
            assert os.environ.get("DRF_RUN_SPENDING_OPERATION") is None
            assert sp._ENV_PIN["current"]["DRF_RUN_SPENDING_OPERATION"] is None
            assert json.loads(os.environ["DRF_RUN_SPENDING_BINDING"]) == bound
            for key in parent_env.keys() - {"DRF_RUN_SPENDING_BINDING"}:
                assert os.environ[key] == parent_env[key]
            root_operation = sp.current_operation()
            child = sp.register_participant(bound, "operation-child", spawn_receipt_sha256=sp.hash_payload("synthetic-spawn"),
                                             operation_context=root_operation)
            child_env = sp.export_environment(child, operation_context=root_operation)
            assert json.loads(child_env["DRF_RUN_SPENDING_OPERATION"]) == root_operation
            assert os.environ.get("DRF_RUN_SPENDING_OPERATION") is None
            assert sp.check_context() == bound
            sp.participant_exited(bound, "operation-child", exit_receipt_sha256=sp.hash_payload("not-started"))


def test_prepared_parent_operation_cannot_dispatch_before_bind(tmp_path, monkeypatch):
    _, path, registry, _ = synthetic_manifest(tmp_path)
    initial = sp.create_authorization(path, registry_dir=registry)
    for key, value in sp.export_environment(initial).items():
        monkeypatch.setenv(key, value)
    sp.activate_binding(sp.binding_from_environment())
    with sp.run_lock(initial):
        with sp.operation("pipeline", "synthetic-root"):
            assert sp.summary(initial)["state"] == "prepared"
            with pytest.raises(sp.SpendingStop):
                sp.dispatch("model-main", envelope(), unexpected_send)
            assert sp.summary(initial)["attempt_count"] == 0
            assert os.environ.get("DRF_RUN_SPENDING_OPERATION") is None


def test_prepared_parent_operation_requires_owned_lock(tmp_path):
    _, path, registry, _ = synthetic_manifest(tmp_path)
    initial = sp.create_authorization(path, registry_dir=registry)
    sp.activate_binding(initial)
    with pytest.raises(sp.SpendingStop):
        with sp.operation("pipeline", "synthetic-root"):
            pytest.fail("unowned preparation must not acquire operation context")
    assert sp.summary(initial)["attempt_count"] == 0


@pytest.mark.parametrize("paused", [False, True])
def test_validate_bound_request_matches_immutable_manifest_without_mutation(tmp_path, paused):
    with active(tmp_path) as (b, m, request):
        sp.dispatch("model-main", envelope(), lambda: None)
        if paused:
            sp.mark_recoverable(b)
        before = sp.summary(b)
        assert sp.validate_bound_request(b, dict(request)) == m["request_sha256"]
        assert sp.summary(b) == before
        assert before["reserved_max_microusd"] == 600_000
        assert before["generation"] == 1


@pytest.mark.parametrize("paused", [False, True])
def test_validate_bound_request_rejects_changed_mutable_state_and_saved_copy(tmp_path, paused):
    with active(tmp_path) as (b, m, request):
        sp.dispatch("model-main", envelope(), lambda: None)
        if paused:
            sp.mark_recoverable(b)
        changed_actual = {**request, "question": "changed question"}
        changed_saved_copy = dict(changed_actual)
        assert changed_actual == changed_saved_copy
        with pytest.raises(sp.SpendingStop, match="binding_conflict"):
            sp.validate_bound_request(b, changed_actual)
        stopped = sp.summary(b)
        assert stopped["state"] == "halted_error" and stopped["stop_code"] == "binding_conflict"
        assert stopped["generation"] == 1 and stopped["cap_microusd"] == 1_000_000
        assert stopped["attempt_count"] == 1 and stopped["reserved_max_microusd"] == 600_000
        with pytest.raises(sp.SpendingStop, match="binding_conflict"):
            sp.dispatch("model-main", envelope(output=100), unexpected_send)
        with pytest.raises(sp.SpendingStop, match="resume_denied"):
            sp.resume_existing(b, proof(b, m))
        assert sp.summary(b)["generation"] == 1


def test_validate_bound_request_does_not_bind_prepared_authorization(tmp_path):
    _, path, registry, request = synthetic_manifest(tmp_path)
    b = sp.create_authorization(path, registry_dir=registry)
    with pytest.raises(sp.SpendingStop, match="binding_conflict"):
        sp.validate_bound_request(b, request)
    result = sp.summary(b)
    assert result["pipeline_id"] == "" and result["attempt_count"] == 0
    assert result["cap_microusd"] == 1_000_000


def test_validate_bound_request_stale_generation_cannot_poison_resume(tmp_path):
    with active(tmp_path) as (b, m, request):
        sp.mark_recoverable(b)
        fresh = sp.resume_existing(b, proof(b, m))
        with pytest.raises(sp.SpendingStop, match="stale_generation"):
            sp.validate_bound_request(b, request)
        assert sp.validate_bound_request(fresh, request) == m["request_sha256"]
        assert sp.summary(fresh)["state"] == "active"
        assert sp.summary(fresh)["generation"] == 2


@pytest.mark.parametrize("malformed", ["object", "surrogate", "serializer_recursion"])
@pytest.mark.parametrize("paused", [False, True])
def test_validate_bound_request_malformed_request_has_fixed_persisted_stop(tmp_path, monkeypatch, malformed, paused):
    with active(tmp_path) as (b, _, _):
        sp.dispatch("model-main", envelope(), lambda: None)
        if paused:
            sp.mark_recoverable(b)
        value = {"object": object(), "surrogate": "\ud800", "serializer_recursion": []}[malformed]
        request = {"question": value}
        if malformed == "serializer_recursion":
            # Encoder recursion limits differ by runtime. Inject precisely
            # this serialization failure; leave guard/ledger JSON untouched.
            original_dumps = sp.json.dumps
            def recursion_failure(value, *args, **kwargs):
                if value is request:
                    raise RecursionError("synthetic serializer depth failure")
                return original_dumps(value, *args, **kwargs)
            monkeypatch.setattr(sp.json, "dumps", recursion_failure)
        with pytest.raises(sp.SpendingStop, match="^binding_conflict$"):
            sp.validate_bound_request(b, request)
        stopped = sp.summary(b)
        assert stopped["stop_code"] == "binding_conflict"
        assert stopped["state"] == "halted_error"
        assert stopped["attempt_count"] == 1 and stopped["reserved_max_microusd"] == 600_000
        assert stopped["cap_microusd"] == 1_000_000 and stopped["generation"] == 1
