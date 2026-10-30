"""Offline v2 World Anchor scope admission; v1 tests remain unchanged."""
import contextvars
import hashlib
import json
import os
from pathlib import Path
from contextlib import contextmanager

import pytest
from app.services.official_data import bridge_module

sp = bridge_module("run_spending")


@pytest.fixture(autouse=True)
def isolated(monkeypatch):
    for key in list(os.environ):
        if key.startswith("DRF_RUN_SPENDING_"):
            monkeypatch.delenv(key)
    for name, value in (("_REQUIRED", False), ("_ACTIVE_AUTH", None), ("_ENV_PIN", None), ("_LOCAL_STOPS", {})):
        monkeypatch.setattr(sp, name, value)
    monkeypatch.setattr(sp, "_binding", contextvars.ContextVar("v2_binding", default=None))
    monkeypatch.setattr(sp, "_operation", contextvars.ContextVar("v2_operation", default=None))


def make_authority(tmp_path, **limits):
    root = tmp_path / "runtime"
    (root / "spend").mkdir(parents=True)
    (root / "app").mkdir()
    (root / "app/source.py").write_text("# synthetic offline source\n")
    registry = tmp_path / "registry"
    registry.mkdir()
    model = {"kind": "openai_chat", "endpoint": "https://synthetic.invalid/v1", "model": "model",
             "account_sha256": hashlib.sha256(b"synthetic-key").hexdigest(), "billing_class": "external_model",
             "basis_sha256": sp.hash_payload("synthetic-bound-evidence"), "coverage": "all_billable_dimensions",
             "input_bound": "enforced_context_ceiling", "input_ceiling": 100,
             "max_output_tokens": 2000, "max_tool_units": 0,
             "pricing": {"input_usd_per_million": "1000", "output_usd_per_million": "1000",
                         "tool_usd_per_unit": "0", "fixed_usd": "0", "surcharge_usd": "0"}}
    tool = {**model, "model": "", "billing_class": "external_tool", "input_bound": "not_applicable",
            "input_ceiling": 0, "max_output_tokens": 0, "max_tool_units": 1,
            "pricing": {"input_usd_per_million": "0", "output_usd_per_million": "0", "tool_usd_per_unit": "0.1", "fixed_usd": "0", "surcharge_usd": "0"}}
    routes = {"model": model,
              "search": {**tool, "kind": "firecrawl_search", "endpoint": "https://synthetic.invalid/search"},
              "scrape": {**tool, "kind": "firecrawl_scrape", "endpoint": "https://synthetic.invalid/scrape"},
              "catalog": {**tool, "kind": "catalog_lookup", "endpoint": "https://synthetic.invalid/catalog",
                          "catalog_contract": {"provider_id": "synthetic", "operation_id": "lookup",
                             **{k: sp.hash_payload(k) for k in ("catalog_sha256", "request_schema_sha256", "response_bound_sha256", "retry_policy_sha256")}}}}
    budget = {"schema": "anchor-budget/v1", "scope_id": "anchor-one", "policy_version": "world-anchor-budget/v1",
              "source_policy_sha256": sp.hash_payload("source-policy"), "model_attempt_limit": 20,
              "token_envelope_limit": 150000, "catalog_attempt_limit": 8, "followup_attempt_limit": 12,
              "catalog_lookups_per_gap": 1, "followup_round_limit": 1,
              "model_profile": {"route_id": "model", "max_output_tokens": 2000},
              "catalog_route_ids": ["catalog"], "followup_route_ids": ["search", "scrape"],
              "usage_policy": "provider_reported_required"}
    budget.update(limits)
    request = {"prompt": "synthetic anchor", "mode": "full", "depth": "deep", "language": "English", "model": "model",
               "forecast_authority": "target-first-v1", "target_simulation": {"paths": 1, "periods": 1, "seed": 7},
               "world_anchor": {"mode": "v1", "anchor_budget_scope_id": budget["scope_id"],
                   **{k: budget[k] for k in ("policy_version", "source_policy_sha256", "model_attempt_limit", "token_envelope_limit",
                                            "catalog_attempt_limit", "followup_attempt_limit", "catalog_lookups_per_gap", "followup_round_limit")}}}
    files = {"app/source.py": hashlib.sha256((root / "app/source.py").read_bytes()).hexdigest()}
    manifest = {"schema": "target-run-spending/v2", "authorization_id": "synthetic-v2", "root": str(root),
                "currency": "USD", "cap_usd": "100", "request_sha256": sp.hash_payload(request),
                "source_files": files, "source_sha256": sp.hash_payload(files), "routes": routes,
                "routes_sha256": sp.hash_payload(routes), "resume_policy": "explicit_clean_only", "anchor_budget": budget}
    path = root / "spend/authorization.json"
    path.write_text(json.dumps(manifest))
    return manifest, path, registry, request


def session(name="session-1", **kw):
    return {"session_id": name, "research_generation_id": "research-1", "input_manifest_sha256": sp.hash_payload("inputs"),
            "requirement_registry_sha256": sp.hash_payload("requirements"), "workers_quiesced_sha256": sp.hash_payload("joined"),
            "restart_of_session_id": None, **kw}


def model_request(output=500):
    return {"endpoint": "https://synthetic.invalid/v1", "model": "model", "input_tokens": 100,
            "max_output_tokens": output, "tool_units": 0, "payload_sha256": sp.hash_payload({"output": output})}


def reported(_):
    return {"kind": "provider_reported", "input_tokens": 1, "output_tokens": 1}


@contextmanager
def anchor(tmp_path, **limits):
    m, path, registry, req = make_authority(tmp_path, **limits)
    b = sp.create_authorization(path, registry_dir=registry)
    with sp.run_lock(b):
        b = sp.bind_pipeline(b, "pipeline", req)
        sp.activate_binding(b)
        with sp.operation("research", "root"):
            entered = sp.begin_anchor_scope(b, session=session())
            yield entered["binding"], m, req


def test_v2_atomic_retained_dimensions(tmp_path):
    with anchor(tmp_path) as (b, _, _):
        seen = []
        def send():
            seen.append(sp.scope_summary(b))
            return "response"
        assert sp.dispatch("model", model_request(), send, usage=reported) == "response"
        assert seen[0]["retained"] == {"model_attempts": 1, "token_envelope_units": 600,
                                        "catalog_attempts": 0, "followup_attempts": 0, "reserved_max_microusd": 600000}
        assert sp.scope_summary(b)["retained"] == seen[0]["retained"]


def test_v2_model_attempt_limit_denies_without_send(tmp_path):
    with anchor(tmp_path, model_attempt_limit=1) as (b, _, _):
        sp.dispatch("model", model_request(), lambda: "ok", usage=reported)
        called = []
        with pytest.raises(sp.SpendingStop, match="stage_model_attempts_exhausted"):
            sp.dispatch("model", model_request(), lambda: called.append(True), usage=reported)
        assert called == [] and sp.summary(b)["attempt_count"] == 1


def test_v2_missing_usage_halts_without_refund(tmp_path):
    with anchor(tmp_path) as (b, _, _):
        with pytest.raises(sp.SpendingStop, match="stage_usage_unverifiable"):
            sp.dispatch("model", model_request(), lambda: "response-without-usage")
        assert sp.scope_summary(b)["retained"]["token_envelope_units"] == 600
        assert sp.summary(b)["state"] == "halted_unknown"


def setup_bound(tmp_path, **limits):
    m, path, registry, req = make_authority(tmp_path, **limits)
    return sp.create_authorization(path, registry_dir=registry), m, req


def end_scope(b):
    receipt = sp.seal_anchor_budget(b, seal={"session_id": sp.scope_summary(b)["active_session_id"],
        "participants_exited_sha256": sp.hash_payload(sp.summary(b)["participants"]), "workers_joined_sha256": sp.hash_payload("workers-joined")})
    return sp.finish_anchor_scope(b, completion={"session_id": receipt["session_id"],
        "artifact_manifest_sha256": sp.hash_payload("sealed-pack"), "budget_receipt_sha256": sp.hash_payload(receipt), "result": "sealed"})


def gaps(b, m, count=1):
    records = [{"requirement_id": f"req-{i}", "constraint_identity_sha256": sp.hash_payload({"metric": i})} for i in range(count)]
    for r in records:
        r["gap_key"] = sp.hash_payload({"schema": "anchor-gap-budget-key/v1", "request_sha256": m["request_sha256"],
                                      "constraint_identity_sha256": r["constraint_identity_sha256"]})
    records.sort(key=lambda r: r["gap_key"])
    return records, sp.register_anchor_gaps(b, gap_manifest_sha256=sp.hash_payload(records), gaps=records)


def tool_request(route, query):
    return {"endpoint": f"https://synthetic.invalid/{route}", "model": "", "input_tokens": 0,
            "max_output_tokens": 0, "tool_units": 1, "payload_sha256": sp.hash_payload(query)}


def tool_usage(_):
    return {"kind": "provider_reported", "tool_units": 1}


def resume_proof(b, m, recovery=None):
    return {"approval_sha256": sp.hash_payload("explicit-synthetic-resume"),
            **{k: m[k] for k in ("request_sha256", "source_sha256", "routes_sha256")},
            "participants_sha256": sp.hash_payload(sp.summary(b)["participants"]),
            "scope_state_sha256": sp.hash_payload(sp.scope_summary(b)), "anchor_recovery": recovery}


def test_token_limit_and_no_usage_refund(tmp_path):
    with anchor(tmp_path, token_envelope_limit=600, model_profile={"route_id": "model", "max_output_tokens": 500}) as (b, _, _):
        sp.dispatch("model", model_request(), lambda: None, usage=reported)
        sent = []
        with pytest.raises(sp.SpendingStop, match="stage_tokens_exhausted"):
            sp.dispatch("model", model_request(1), lambda: sent.append(1), usage=reported)
        assert not sent
        assert sp.scope_summary(b)["retained"]["token_envelope_units"] == 600
        assert sp.scope_summary(b)["retained"]["model_attempts"] == 1


def test_oversized_profile_refused_before_construction(tmp_path):
    m, path, registry, req = make_authority(tmp_path)
    m["routes"]["model"]["input_ceiling"] = 200000
    m["routes_sha256"] = sp.hash_payload(m["routes"])
    path.write_text(json.dumps(m))
    b = sp.create_authorization(path, registry_dir=registry)
    with sp.run_lock(b):
        b = sp.bind_pipeline(b, "pipeline", req)
        sp.activate_binding(b)
        with sp.operation("research", "root"):
            with pytest.raises(sp.SpendingStop, match="stage_profile_oversize"):
                sp.begin_anchor_scope(b, session=session())
            assert sp.summary(b)["attempt_count"] == 0
            assert sp.scope_summary(b)["active_scope_id"] is None


def test_stage_epochs_block_old_workers_but_not_next_phase(tmp_path):
    old, m, req = setup_bound(tmp_path)
    with sp.run_lock(old):
        old = sp.bind_pipeline(old, "pipeline", req)
        sp.activate_binding(old)
        with sp.operation("research", "root"):
            scoped = sp.begin_anchor_scope(old, session=session())["binding"]
            with pytest.raises(sp.SpendingStop, match="stale_admission_epoch"):
                sp.reserve_and_claim(old, "model", model_request(), stage="old", logical_key="old")
            sp.dispatch("model", model_request(), lambda: None, usage=reported)
            finished = end_scope(scoped)["binding"]
            assert finished["active_scope_id"] is None
            with pytest.raises(sp.SpendingStop, match="stale_admission_epoch"):
                sp.reserve_and_claim(scoped, "model", model_request(), stage="late", logical_key="late")
            assert sp.summary(finished)["state"] == "active"
            sp.dispatch("model", model_request(), lambda: None)  # unscoped v2 preserves v1 missing usage
            assert sp.summary(finished)["attempt_count"] == 2
            assert sp.scope_summary(finished)["retained"]["model_attempts"] == 1
            assert sp.current_binding() == finished
            assert m["anchor_budget"]["scope_id"] == "anchor-one"


def test_nested_repairs_keep_scope_and_count_each_attempt(tmp_path):
    with anchor(tmp_path) as (b, _, _):
        for label in ("bind", "repair", "followup-model"):
            with sp.operation(label, "varying-stage"):
                sp.dispatch("model", model_request(100), lambda: None, usage=reported)
        assert sp.scope_summary(b)["retained"]["model_attempts"] == 3
        assert sp.scope_summary(b)["retained"]["token_envelope_units"] == 600


def test_registered_search_scrape_http_followup_and_cache_no_debit(tmp_path):
    import httpx
    with anchor(tmp_path) as (b, m, _):
        records, followup = gaps(b, m)
        sends = []
        def handler(request):
            sends.append(request.url.path)
            # A second DB connection is opened by summary during physical send.
            assert sp.scope_summary(b)["retained"]["followup_attempts"] == len(sends)
            return httpx.Response(200, json={"units": 1, "result": "synthetic"})
        with httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=False, trust_env=False) as client:
            for route in ("search", "scrape"):
                body = {"gap": records[0]["gap_key"], "operation": route}
                envelope = tool_request(route, body)
                op = sp.open_followup_operation(b, followup_id=followup["followup_id"], gap_key=records[0]["gap_key"],
                                                route_id=route, query_sha256=envelope["payload_sha256"])
                response = sp.dispatch(route, envelope, lambda endpoint=envelope["endpoint"], body=body: client.post(endpoint, json=body),
                    usage=lambda response: {"kind": "provider_reported", "tool_units": response.json()["units"]},
                    followup_operation_id=op["operation_id"])
                sp.complete_catalog_lookup(b, op["operation_id"], result_sha256=sp.hash_payload(response.json()))
            before = sp.scope_summary(b)
            cached = response.json()  # cache replay has no dispatch
            assert cached["result"] == "synthetic" and sp.scope_summary(b) == before
        assert sends == ["/search", "/scrape"]
        assert before["retained"]["catalog_attempts"] == 0
        assert before["retained"]["followup_attempts"] == 2
        assert before["retained"]["reserved_max_microusd"] == 200000


def test_known_tool_retries_consume_followup_cap(tmp_path):
    with anchor(tmp_path, followup_attempt_limit=2) as (b, m, _):
        records, followup = gaps(b, m)
        request = tool_request("search", {"gap": records[0]["gap_key"]})
        op = sp.open_followup_operation(b, followup_id=followup["followup_id"], gap_key=records[0]["gap_key"],
                                       route_id="search", query_sha256=request["payload_sha256"])
        sent = []
        for _ in range(2):
            sp.dispatch("search", request, lambda: sent.append(1), followup_operation_id=op["operation_id"],
                        usage=lambda _: {"kind": "provider_reported", "tool_units": 1, "tool_result": "retryable_known"})
        with pytest.raises(sp.SpendingStop, match="stage_followup_attempts_exhausted"):
            sp.dispatch("search", request, lambda: sent.append(1), followup_operation_id=op["operation_id"], usage=tool_usage)
        assert len(sent) == 2 and sp.summary(b)["attempt_count"] == 2
        assert sp.scope_summary(b)["retained"]["followup_attempts"] == 2


def test_catalog_limit_is_separate_and_lookup_binds_exact_wire(tmp_path):
    with anchor(tmp_path, catalog_attempt_limit=1) as (b, m, _):
        records, followup = gaps(b, m, 2)
        requests = []
        for record in records:
            envelope = tool_request("catalog", {"gap": record["gap_key"]})
            op = sp.open_catalog_lookup(b, followup_id=followup["followup_id"], gap_key=record["gap_key"],
                                        catalog_route_id="catalog", query_sha256=envelope["payload_sha256"])
            requests.append((envelope, op))
        sent = []
        first, op = requests[0]
        sp.dispatch("catalog", first, lambda: sent.append(1), usage=tool_usage, catalog_lookup_id=op["operation_id"])
        with pytest.raises(sp.SpendingStop, match="stage_tool_attempts_exhausted"):
            sp.dispatch("catalog", requests[1][0], lambda: sent.append(1), usage=tool_usage, catalog_lookup_id=requests[1][1]["operation_id"])
        assert len(sent) == 1 and sp.scope_summary(b)["retained"]["catalog_attempts"] == 1
        assert sp.scope_summary(b)["retained"]["followup_attempts"] == 0


@pytest.mark.parametrize("attack", ["different_wire", "no_registration", "different_gap_set", "second_query"])
def test_tool_operation_denials_precede_send(tmp_path, attack):
    with anchor(tmp_path) as (b, m, _):
        records, followup = gaps(b, m)
        request = tool_request("catalog", {"series": "A"})
        op = sp.open_catalog_lookup(b, followup_id=followup["followup_id"], gap_key=records[0]["gap_key"],
                                    catalog_route_id="catalog", query_sha256=request["payload_sha256"])
        sent = []
        with pytest.raises(sp.SpendingStop):
            if attack == "different_gap_set":
                gaps(b, m, 2)
            elif attack == "second_query":
                sp.open_catalog_lookup(b, followup_id=followup["followup_id"], gap_key=records[0]["gap_key"],
                                       catalog_route_id="catalog", query_sha256=sp.hash_payload({"series": "B"}))
            else:
                if attack == "different_wire":
                    request["payload_sha256"] = sp.hash_payload({"series": "B"})
                sp.dispatch("catalog", request, lambda: sent.append(1), usage=tool_usage,
                            catalog_lookup_id=None if attack == "no_registration" else op["operation_id"])
        assert sent == [] and sp.summary(b)["attempt_count"] == 0


def test_inflight_lookup_cannot_be_claimed_as_retry(tmp_path):
    with anchor(tmp_path) as (b, m, _):
        records, followup = gaps(b, m)
        request = tool_request("catalog", {"series": "A"})
        op = sp.open_catalog_lookup(b, followup_id=followup["followup_id"], gap_key=records[0]["gap_key"],
                                    catalog_route_id="catalog", query_sha256=request["payload_sha256"])
        first = sp.reserve_and_claim(b, "catalog", request, stage="catalog", logical_key="lookup", catalog_lookup_id=op["operation_id"])
        with pytest.raises(sp.SpendingStop, match="tool_operation_conflict"):
            sp.reserve_and_claim(b, "catalog", request, stage="retry", logical_key="lookup", catalog_lookup_id=op["operation_id"])
        sp.record_observation(first, tool_usage(None))
        assert sp.summary(b)["attempt_count"] == 1


def test_nested_participant_inheritance_and_direct_exit(tmp_path):
    with anchor(tmp_path) as (parent, _, _):
        child = sp.register_participant(parent, "research-child", spawn_receipt_sha256=sp.hash_payload("spawn"))
        sp.participant_started(child)
        assert child["active_scope_id"] == parent["active_scope_id"]
        grandchild = sp.register_participant(child, "tool-child", spawn_receipt_sha256=sp.hash_payload("grandchild"))
        sp.participant_started(grandchild)
        sp.participant_exited(child, "tool-child", exit_receipt_sha256=sp.hash_payload("joined-grandchild"))
        sp.participant_exited(parent, "research-child", exit_receipt_sha256=sp.hash_payload("joined-child"))
        assert end_scope(parent)["binding"]["active_scope_id"] is None


def test_scope_seal_prevents_more_sends_and_receipt_matches_debits(tmp_path):
    with anchor(tmp_path) as (b, _, _):
        sp.dispatch("model", model_request(), lambda: None, usage=reported)
        receipt = sp.seal_anchor_budget(b, seal={"session_id": "session-1", "participants_exited_sha256": sp.hash_payload("exits"),
                                               "workers_joined_sha256": sp.hash_payload("joins")})
        assert receipt["retained"]["model_attempts"] == 1
        called = []
        with pytest.raises(sp.SpendingStop, match="budget_scope_missing"):
            sp.dispatch("model", model_request(), lambda: called.append(1), usage=reported)
        assert not called and sp.summary(b)["attempt_count"] == 1


def test_new_research_session_retains_old_scope_debits(tmp_path):
    with anchor(tmp_path, model_attempt_limit=1) as (b, _, _):
        sp.dispatch("model", model_request(), lambda: None, usage=reported)
        unscoped = end_scope(b)["binding"]
        new = sp.begin_anchor_scope(unscoped, session=session("session-2", research_generation_id="research-2"))["binding"]
        called = []
        with pytest.raises(sp.SpendingStop, match="stage_model_attempts_exhausted"):
            sp.dispatch("model", model_request(), lambda: called.append(1), usage=reported)
        assert not called and sp.scope_summary(new)["retained"]["model_attempts"] == 1


def test_same_scope_restart_retains_attempts_and_reassigns_owner(tmp_path):
    with anchor(tmp_path, model_attempt_limit=1) as (b, m, _):
        sp.dispatch("model", model_request(), lambda: None, usage=reported)
        sp.mark_recoverable(b)
        recovery = {"kind": "restart_from_inputs", "previous_session_id": "session-1",
                    **{k: session()[k] for k in ("research_generation_id", "input_manifest_sha256", "requirement_registry_sha256")}}
        fresh = sp.resume_existing(b, resume_proof(b, m, recovery))
        sp.activate_binding(fresh)
        new = sp.begin_anchor_scope(fresh, session=session("restart-2", restart_of_session_id="session-1"))["binding"]
        assert new["generation"] == 2 and new["active_scope_id"] == b["active_scope_id"]
        assert sp.scope_summary(new)["sessions"][0]["state"] == "interrupted"
        with pytest.raises(sp.SpendingStop, match="stale_generation"):
            sp.check_active(b)
        called = []
        with pytest.raises(sp.SpendingStop, match="stage_model_attempts_exhausted"):
            sp.dispatch("model", model_request(), lambda: called.append(1), usage=reported)
        assert not called and sp.scope_summary(new)["retained"]["model_attempts"] == 1


def test_capture_uses_committed_ids_and_transport_hashes(tmp_path):
    with anchor(tmp_path) as (b, _, _):
        response = {"content": "synthetic proposal", "usage": {"input": 1, "output": 1}}
        with sp.capture_dispatch_receipts() as capture:
            sp.dispatch("model", model_request(), lambda: response, usage=reported,
                        response_fingerprint=lambda raw: {"basis": "provider_json/v1", "sha256": sp.hash_payload(raw)})
        opaque = capture.receipt()
        receipt = sp.inspect_dispatch_receipt(opaque)
        attempt = receipt["attempts"][0]
        assert attempt["request_sha256"] == model_request()["payload_sha256"]
        assert attempt["response_fingerprint"]["sha256"] == sp.hash_payload(response)
        assert attempt["reserved_max_microusd"] == 600000 and attempt["token_envelope_units"] == 600
        assert sp.summary(b)["attempt_count"] == 1
        with pytest.raises(sp.SpendingStop, match="transport_receipt_missing"):
            sp.inspect_dispatch_receipt(receipt)


def test_capture_refuses_missing_fingerprint(tmp_path):
    with anchor(tmp_path):
        with sp.capture_dispatch_receipts() as capture:
            sp.dispatch("model", model_request(), lambda: "known response", usage=reported)
        with pytest.raises(sp.SpendingStop, match="transport_receipt_missing"):
            capture.receipt()


def launch_child(tmp_path, b, name, mode, *, route="model", request=None, **extra):
    import subprocess
    import sys
    script = Path(__file__).with_name("fixtures") / "world_anchor_spending_child.py"
    child = sp.register_participant(b, name, spawn_receipt_sha256=sp.hash_payload({"mode": mode, "name": name}))
    control = {"mode": mode, "route": route, "request": request or model_request(),
               "ready": str(tmp_path / (name + ".ready")), "go": str(tmp_path / "go"),
               "sent": str(tmp_path / (name + ".sent")), **extra}
    cp = tmp_path / (name + ".json")
    cp.write_text(json.dumps(control))
    process = subprocess.Popen([sys.executable, "-B", str(script), str(cp)],
        env={**os.environ, **sp.export_environment(child)}, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    return process, control


@pytest.mark.parametrize("dimension", ["model", "tokens", "catalog", "followup"])
def test_independent_process_final_slot_contention(tmp_path, dimension):
    import time
    limits = {}
    if dimension == "tokens":
        limits = {"token_envelope_limit": 600, "model_profile": {"route_id": "model", "max_output_tokens": 500}}
    with anchor(tmp_path, **limits) as (b, m, _):
        operations = []
        if dimension == "model":
            for _ in range(19):
                sp.dispatch("model", model_request(1), lambda: None, usage=reported)
        if dimension in {"catalog", "followup"}:
            count = 9 if dimension == "catalog" else 13
            records, followup = gaps(b, m, count)
            route = "catalog" if dimension == "catalog" else "search"
            for record in records:
                req = tool_request(route, {"gap": record["gap_key"]})
                if dimension == "catalog":
                    op = sp.open_catalog_lookup(b, followup_id=followup["followup_id"], gap_key=record["gap_key"], catalog_route_id=route, query_sha256=req["payload_sha256"])
                else:
                    op = sp.open_followup_operation(b, followup_id=followup["followup_id"], gap_key=record["gap_key"], route_id=route, query_sha256=req["payload_sha256"])
                operations.append((req, op))
            key = "catalog_lookup_id" if dimension == "catalog" else "followup_operation_id"
            for req, op in operations[:-2]:
                sp.dispatch(route, req, lambda: None, usage=tool_usage, **{key: op["operation_id"]})
            children = [launch_child(tmp_path, b, f"child-{i}", "race", route=route, request=req, **{key: op["operation_id"]}) for i, (req, op) in enumerate(operations[-2:])]
        else:
            children = [launch_child(tmp_path, b, f"child-{i}", "race") for i in range(2)]
        deadline = time.monotonic() + 15
        try:
            while not all(Path(c["ready"]).exists() for _, c in children):
                assert time.monotonic() < deadline
                time.sleep(0.01)
            (tmp_path / "go").write_text("go")
            results = []
            for i, (process, _) in enumerate(children):
                out, err = process.communicate(timeout=20)
                assert process.returncode == 0, err
                results.append(json.loads(out)["outcome"])
                sp.participant_exited(b, f"child-{i}", exit_receipt_sha256=sp.hash_payload({"pid": process.pid, "exit": process.returncode}))
        finally:
            for process, _ in children:
                if process.poll() is None:
                    process.kill()
                    process.communicate(timeout=5)
        code = {"model": "stage_model_attempts_exhausted", "tokens": "stage_tokens_exhausted",
                "catalog": "stage_tool_attempts_exhausted", "followup": "stage_followup_attempts_exhausted"}[dimension]
        assert sorted(results) == sorted(["sent", code])
        assert sum(Path(c["sent"]).exists() for _, c in children) == 1
        summary = sp.scope_summary(b)
        assert summary["retained"][{"model": "model_attempts", "tokens": "token_envelope_units", "catalog": "catalog_attempts", "followup": "followup_attempts"}[dimension]] == {"model": 20, "tokens": 600, "catalog": 8, "followup": 12}[dimension]


@pytest.mark.parametrize("mode,code,total,tokens", [("before-commit", 81, 0, 0), ("after-commit", 82, 600000, 600), ("after-send", 83, 600000, 600)])
def test_v2_process_crash_preserves_all_dimensions(tmp_path, mode, code, total, tokens):
    with anchor(tmp_path) as (b, _, _):
        process, control = launch_child(tmp_path, b, "crasher", mode)
        try:
            _, err = process.communicate(timeout=20)
            assert process.returncode == code, err
        finally:
            if process.poll() is None:
                process.kill()
                process.communicate(timeout=5)
        sp.participant_exited(b, "crasher", exit_receipt_sha256=sp.hash_payload({"pid": process.pid, "exit": code}))
        assert Path(control["sent"]).exists() is (mode == "after-send")
        retained = sp.scope_summary(b)["retained"]
        assert retained["reserved_max_microusd"] == total and retained["token_envelope_units"] == tokens
        assert retained["model_attempts"] == int(total > 0)
        assert sp.summary(b)["state"] == ("halted_unknown" if total else "active")


def test_v2_fresh_pid_restart_cannot_renew_scope(tmp_path):
    import subprocess
    import sys
    initial, m, req = setup_bound(tmp_path, model_attempt_limit=1)
    with sp.run_lock(initial):
        initial = sp.bind_pipeline(initial, "pipeline", req)
        sp.activate_binding(initial)
        with sp.operation("research", "root"):
            old = sp.begin_anchor_scope(initial, session=session())["binding"]
            sp.dispatch("model", model_request(), lambda: None, usage=reported)
            sp.mark_recoverable(old)
            recovery = {"kind": "restart_from_inputs", "previous_session_id": "session-1",
                        **{k: session()[k] for k in ("research_generation_id", "input_manifest_sha256", "requirement_registry_sha256")}}
            approval = resume_proof(old, m, recovery)
    control = {"mode": "resume", "route": "model", "request": model_request(), "sent": str(tmp_path / "resumed.sent"),
               "proof": approval, "session": session("session-2", restart_of_session_id="session-1")}
    cp = tmp_path / "resume.json"
    cp.write_text(json.dumps(control))
    script = Path(__file__).with_name("fixtures") / "world_anchor_spending_child.py"
    env = {**os.environ, **sp.export_environment(old, operation_context={"stage": "research", "logical_key": "resume"})}
    process = subprocess.Popen([sys.executable, "-B", str(script), str(cp)], env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        out, err = process.communicate(timeout=20)
        assert process.returncode == 0, err
    finally:
        if process.poll() is None:
            process.kill()
            process.communicate(timeout=5)
    result = json.loads(out)
    assert result["outcome"] == "stage_model_attempts_exhausted"
    assert result["binding"]["generation"] == 2
    assert result["summary"]["retained"]["reserved_max_microusd"] == 600000
    assert not Path(control["sent"]).exists()
    with pytest.raises(sp.SpendingStop, match="stale_generation"):
        sp.check_active(old)


def test_one_followup_cannot_reopen_in_later_research_session(tmp_path):
    with anchor(tmp_path) as (b, m, _):
        records, followup = gaps(b, m)
        req = tool_request("search", {"query": "allowed"})
        op = sp.open_followup_operation(b, followup_id=followup["followup_id"], gap_key=records[0]["gap_key"],
                                       route_id="search", query_sha256=req["payload_sha256"])
        sp.dispatch("search", req, lambda: None, usage=tool_usage, followup_operation_id=op["operation_id"])
        sp.complete_tool_operation(b, op["operation_id"], result_sha256=sp.hash_payload("accepted"))
        sp.complete_anchor_followup(b, followup["followup_id"], result_sha256=sp.hash_payload("round-complete"))
        outside = end_scope(b)["binding"]
        new = sp.begin_anchor_scope(outside, session=session("revision-2", research_generation_id="research-2"))["binding"]
        assert gaps(new, m)[1]["state"] == "complete"
        with pytest.raises(sp.SpendingStop, match="tool_operation_conflict"):
            sp.open_followup_operation(new, followup_id=followup["followup_id"], gap_key=records[0]["gap_key"],
                                       route_id="search", query_sha256=sp.hash_payload("new-round-query"))
        assert sp.scope_summary(new)["retained"]["followup_attempts"] == 1


def test_usd_denial_does_not_partially_debit_stage(tmp_path):
    m, path, registry, req = make_authority(tmp_path)
    m["cap_usd"] = "1"
    path.write_text(json.dumps(m))
    b = sp.create_authorization(path, registry_dir=registry)
    with sp.run_lock(b):
        b = sp.bind_pipeline(b, "pipeline", req)
        sp.activate_binding(b)
        with sp.operation("research", "before-anchor"):
            sp.dispatch("model", model_request(), lambda: None)  # retained unscoped0.60
            b = sp.begin_anchor_scope(b, session=session())["binding"]
            sent = []
            with pytest.raises(sp.SpendingStop, match="budget_exhausted"):
                sp.dispatch("model", model_request(), lambda: sent.append(1), usage=reported)
            assert not sent and sp.summary(b)["reserved_max_microusd"] == 600000
            assert sp.scope_summary(b)["retained"]["model_attempts"] == 0
            assert sp.scope_summary(b)["retained"]["token_envelope_units"] == 0


@pytest.mark.parametrize("change", ["drop_scope", "change_scope", "float_epoch", "v1_downgrade"])
def test_scope_carrier_tampering_cannot_escape_budget(tmp_path, change):
    with anchor(tmp_path) as (b, _, _):
        altered = dict(b)
        if change == "drop_scope":
            altered.pop("active_scope_id")
        elif change == "change_scope":
            altered["active_scope_id"] = None
        elif change == "float_epoch":
            altered["admission_epoch"] = 1.0
        else:
            altered["schema"] = "target-run-spending-binding/v1"
            altered.pop("admission_epoch")
            altered.pop("active_scope_id")
        with pytest.raises(sp.SpendingStop):
            sp.reserve_and_claim(altered, "model", model_request(), stage="research", logical_key="escape")
        assert sp.summary(b)["attempt_count"] == 0


@pytest.mark.parametrize("kind", ["timeout", "cancel", "missing", "estimate", "overrun"])
def test_scoped_unknown_and_usage_integrity_keep_all_dimensions(tmp_path, kind):
    import asyncio
    with anchor(tmp_path) as (b, _, _):
        async def send():
            if kind == "timeout":
                raise TimeoutError("private provider text")
            if kind == "cancel":
                raise asyncio.CancelledError()
            return "response"
        def usage(_):
            if kind == "missing":
                return None
            if kind == "estimate":
                return {"kind": "estimated", "input_tokens": 1, "output_tokens": 1}
            return {"kind": "provider_reported", "input_tokens": 100, "output_tokens": 501}
        with pytest.raises(sp.SpendingStop) as error:
            asyncio.run(sp.dispatch_async("model", model_request(), send, usage=usage))
        assert "private" not in str(error.value)
        assert sp.scope_summary(b)["retained"]["reserved_max_microusd"] == 600000
        assert sp.scope_summary(b)["retained"]["token_envelope_units"] == 600
        assert sp.summary(b)["state"].startswith("halted_")


def test_scope_metadata_and_child_epoch_are_environment_pinned(tmp_path, monkeypatch):
    initial, _, req = setup_bound(tmp_path)
    for key, value in sp.export_environment(initial).items():
        monkeypatch.setenv(key, value)
    sp.activate_binding(sp.binding_from_environment())
    with sp.run_lock(initial):
        b = sp.bind_pipeline(initial, "pipeline", req)
        with sp.operation("research", "root"):
            entered = sp.begin_anchor_scope(b, session=session())["binding"]
            assert sp.check_context() == entered
            assert json.loads(os.environ["DRF_RUN_SPENDING_BINDING"])["active_scope_id"] == "anchor-one"
            assert os.environ.get("DRF_RUN_SPENDING_OPERATION") is None
            finished = end_scope(entered)["binding"]
            assert sp.check_context() == finished
            assert json.loads(os.environ["DRF_RUN_SPENDING_BINDING"])["active_scope_id"] is None
            assert os.environ.get("DRF_RUN_SPENDING_OPERATION") is None


def test_child_owned_scope_handoff_requires_committed_receipts(tmp_path):
    parent, _, req = setup_bound(tmp_path)
    with sp.run_lock(parent):
        parent = sp.bind_pipeline(parent, "pipeline", req)
        sp.activate_binding(parent)
        with sp.operation("research", "root"):
            child = sp.register_participant(parent, "root-research", spawn_receipt_sha256=sp.hash_payload("spawn"), scope_entry_ids=["anchor-one"])
            sp.participant_started(child)
            sp.activate_binding(child)
            enter = sp.begin_anchor_scope(child, session=session())
            sp.dispatch("model", model_request(), lambda: None, usage=reported)
            exit_result = end_scope(enter["binding"])
            sp.participant_exited(parent, "root-research", exit_receipt_sha256=sp.hash_payload("joined"))
            # Parent's admission carrier predates the child's entry and exit.
            adopted = sp.adopt_scope_handoff(parent, [enter["transition_receipt"], exit_result["transition_receipt"]])
            assert adopted["admission_epoch"] == 2 and adopted["active_scope_id"] is None
            sp.activate_binding(adopted)
            assert sp.check_context() == adopted
            assert sp.scope_summary(adopted)["retained"]["model_attempts"] == 1


def test_v2_authorization_policy_cannot_reset_cap_or_scope(tmp_path):
    with anchor(tmp_path) as (b, m, _):
        sp.dispatch("model", model_request(), lambda: None, usage=reported)
        m["anchor_budget"]["scope_id"] = "fresh-scope"
        Path(b["manifest_path"]).write_text(json.dumps(m))
        with pytest.raises(sp.SpendingStop):
            sp.check_context()
        with pytest.raises(sp.SpendingStop):
            sp.create_authorization(b["manifest_path"], registry_dir=b["registry_dir"])


def test_capture_survives_copied_thread_context(tmp_path):
    import threading
    with anchor(tmp_path):
        errors = []
        with sp.capture_dispatch_receipts() as capture:
            copied = contextvars.copy_context()
            def worker():
                try:
                    copied.run(lambda: sp.dispatch("model", model_request(), lambda: {"content": "reply"}, usage=reported,
                        response_fingerprint=lambda body: {"basis": "provider_json/v1", "sha256": sp.hash_payload(body)}))
                except BaseException as exc:
                    errors.append(type(exc).__name__)
            thread = threading.Thread(target=worker)
            thread.start()
            thread.join(5)
            assert not thread.is_alive() and not errors
        assert len(sp.inspect_dispatch_receipt(capture.receipt())["attempts"]) == 1


def test_pending_restart_can_resume_again_without_renewal(tmp_path):
    with anchor(tmp_path, model_attempt_limit=1) as (b, m, _):
        sp.dispatch("model", model_request(), lambda: None, usage=reported)
        recovery = {"kind": "restart_from_inputs", "previous_session_id": "session-1",
                    **{k: session()[k] for k in ("research_generation_id", "input_manifest_sha256", "requirement_registry_sha256")}}
        sp.mark_recoverable(b)
        second = sp.resume_existing(b, resume_proof(b, m, recovery))
        sp.activate_binding(second)
        sp.mark_recoverable(second)  # no replacement session or send occurred
        third = sp.resume_existing(second, resume_proof(second, m, recovery))
        sp.activate_binding(third)
        scoped = sp.begin_anchor_scope(third, session=session("third", restart_of_session_id="session-1"))["binding"]
        assert scoped["generation"] == 3
        assert sp.scope_summary(scoped)["retained"]["model_attempts"] == 1
        assert sp.scope_summary(scoped)["retained"]["reserved_max_microusd"] == 600000


def test_exited_old_epoch_participant_cannot_poison_next_phase(tmp_path):
    with anchor(tmp_path) as (b, _, _):
        child = sp.register_participant(b, "old-worker", spawn_receipt_sha256=sp.hash_payload("spawn"))
        sp.participant_started(child)
        sp.participant_exited(b, "old-worker", exit_receipt_sha256=sp.hash_payload("joined"))
        outside = end_scope(b)["binding"]
        with pytest.raises(sp.SpendingStop, match="stale_admission_epoch"):
            sp.reserve_and_claim(child, "model", model_request(), stage="late", logical_key="late")
        assert sp.check_active(outside) == outside
        assert sp.summary(outside)["state"] == "active"


def test_opaque_receipt_manifest_cannot_be_truncated(tmp_path):
    with anchor(tmp_path):
        with sp.capture_dispatch_receipts() as capture:
            sp.dispatch("model", model_request(), lambda: {"content": "real-response"}, usage=reported,
                        response_fingerprint=lambda raw: {"basis": "provider_json/v1", "sha256": sp.hash_payload(raw)})
        receipt = capture.receipt()
        receipt._manifest["attempts"].clear()  # only a detached inspection copy may change
        assert len(sp.inspect_dispatch_receipt(receipt)["attempts"]) == 1


def test_parent_lost_context_halts_independent_scoped_child(tmp_path):
    import time
    with anchor(tmp_path) as (b, _, _):
        process, control = launch_child(tmp_path, b, "alive-child", "race")
        deadline = time.monotonic() + 15
        try:
            while not Path(control["ready"]).exists():
                assert time.monotonic() < deadline
                time.sleep(0.01)
            token = sp._binding.set(None)
            try:
                with pytest.raises(sp.SpendingStop, match="missing_context"):
                    sp.check_context()
            finally:
                sp._binding.reset(token)
            Path(control["go"]).write_text("go")
            out, err = process.communicate(timeout=20)
            assert process.returncode == 0, err
            assert json.loads(out)["outcome"] == "missing_context"
            assert not Path(control["sent"]).exists()
            assert sp.summary(b)["attempt_count"] == 0
        finally:
            if process.poll() is None:
                process.kill()
                process.communicate(timeout=5)
            sp.participant_exited(b, "alive-child", exit_receipt_sha256=sp.hash_payload({"pid": process.pid, "exit": process.returncode}))


def test_optional_sqlite_sidecar_unlinked_after_stat_is_absence(tmp_path, monkeypatch):
    import os
    sidecar = tmp_path / "run.sqlite3-wal"
    sidecar.write_bytes(b"synthetic sidecar")
    original = Path.lstat
    def unlinked_stat(path, *args, **kwargs):
        result = original(path, *args, **kwargs)
        if path == sidecar:
            sidecar.unlink()
            fields = list(result)
            fields[3] = 0  # st_nlink after the final SQLite connection unlinks it
            return os.stat_result(fields)
        return result
    with monkeypatch.context() as patch:
        patch.setattr(Path, "lstat", unlinked_stat)
        assert sp._path(sidecar, optional=True) is None
    assert not sidecar.exists()


def test_capture_claim_view_cannot_erase_actual_dispatch(tmp_path):
    with anchor(tmp_path):
        with sp.capture_dispatch_receipts() as capture:
            sp.dispatch("model", model_request(), lambda: {"content": "response"}, usage=reported,
                        response_fingerprint=lambda raw: {"basis": "provider_json/v1", "sha256": sp.hash_payload(raw)})
        capture._claims.clear()
        assert len(sp.inspect_dispatch_receipt(capture.receipt())["attempts"]) == 1


@pytest.mark.parametrize("replica", range(4))
def test_unchanged_v1_process_admission_under_repeated_roots(tmp_path, replica):
    # Reuse the original scenario without modifying its source. The repeated
    # roots exercise the transient sidecar lifecycle seen in the full gate.
    from test_run_spending_store import test_independent_process_060_plus_060_under_100
    test_independent_process_060_plus_060_under_100(tmp_path)
