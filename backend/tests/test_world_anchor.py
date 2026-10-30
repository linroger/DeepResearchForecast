"""Pure World Anchor scenarios. Run with main_offline_pytest.py; no providers."""

import base64
import copy
import os
import sys
import zlib
import hashlib
import json

import pytest

from deerflow_bridge import world_anchor as wa


def dump(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def digest(data):
    return hashlib.sha256(data).hexdigest()


def unknown():
    return {"value": None, "precision": "unknown", "basis_ref_ids": []}


def unit():
    return {
        "id": "usd_billion",
        "dimension": "currency",
        "scale": "1000000000",
        "currency": "USD",
        "price_basis": "nominal",
        "base_period": None,
    }


def identity(year=2026):
    return {
        "entity_id": "cybersecurity",
        "metric_id": "spending",
        "denominator_id": None,
        "geography_id": None,
        "unit": unit(),
        "reference_period": {"start": f"{year}-01-01", "end": f"{year}-12-31", "granularity": "year"},
    }


def scope():
    return {
        "run_id": "run-test",
        "research_generation_id": "research-input-1",
        "snapshot_id": "snapshot-1",
        "authority": "legacy-kiq-v1",
        "cutoff": "2026-10-27T23:59:59Z",
        "horizon": identity(2027)["reference_period"],
    }


def consumer(engine, role, obj, field):
    return {"engine": engine, "role": role, "object_id": obj, "field": field}


def make_fixture(root, *, with_contract=True, fetched_at="2026-10-26T09:29:13Z", page=None, target_year=2027):
    root.mkdir()
    scope_value = scope()
    scope_value["horizon"] = identity(target_year)["reference_period"]
    page = (
        page
        or "Préface. A secondary report forecasts global cybersecurity spending of 247.5 billion USD for 2026. This is a forecast, not an actual."
    )
    source_bytes = page.encode()
    ledger = [
        {
            "sid": 107,
            "url": "https://example.test/report",
            "title": "Source",
            "tier": "secondary",
            "fetched": True,
            "fetched_at": fetched_at,
            "page_path": "pages/page.txt",
            "content_sha256": digest(source_bytes),
        }
    ]
    target = {
        "origin_pointer": "/terms/0",
        "kind": "target_definition",
        "identity": identity(target_year),
        "actor_ref": None,
        "value_type": "text",
        "accepted_value_kinds": [],
        "accepted_evidence": ["contract"],
        "priority": 0,
        "required": True,
        "consumers": [consumer(e, "diagnostic", "target", "definition") for e in wa.ENGINES],
        "dependency_origins": [],
        "assumption_policy_id": None,
    }
    baseline = {
        **target,
        "origin_pointer": "/terms/1",
        "kind": "baseline",
        "identity": identity(),
        "value_type": "number",
        "accepted_value_kinds": ["third_party_forecast"],
        "accepted_evidence": ["page"],
        "consumers": [
            consumer("oasis-legacy", "initial_state", "baseline", "value"),
            consumer("world-v1", "compiler_parameter", "baseline", "/initialState/metrics/baseline/value"),
            consumer("target-first-v1", "initial_state", "baseline", "value"),
        ],
    }
    authority = {"settlement": identity(target_year), "terms": [target, baseline]}
    authority_bytes = dump(authority)
    contract = {
        "schema_version": "world-anchor-contract/v1",
        "scope": scope_value,
        "authority_artifact_id": "contract",
        "authority_artifact_hash": digest(authority_bytes),
        "authority_pointer": "",
        "authority_kind": "reviewed_fixture",
        "settlement": {
            "target_node_id": "target",
            "identity": identity(target_year),
            "authority_artifact_id": "contract",
            "pointer": "/settlement",
        },
        "aliases": [],
        "terms": [target, baseline],
        **{k: [] for k in wa.SPEC_FIELDS},
    }
    requirements = wa.requirements_from_contract(contract if with_contract else None, scope=scope_value)
    policy = {
        "schema_version": "world-anchor-policy/v1",
        "admission_version": "explicit-support/v1",
        "limits_version": "world-anchor-limits/v1",
        "selection_version": "exact-identity-lexical/v1",
        "prior_rules": [],
        "conversions": [],
        "review_profile": {
            "profile_id": "offline-scripted",
            "extraction_prompt_version": "extract/v1",
            "review_prompt_version": "review/v1",
            "qualification_artifact_id": "qualification",
            "qualification_artifact_hash": digest(dump({"offline": True})),
        },
        "consumer_rules": [
            {
                **c,
                "adapter_version": "world-anchor-reflexive/v1" if c["engine"] == "oasis-legacy" else "offline/v1",
                "template_versions": [],
            }
            for t in [target, baseline]
            for c in t["consumers"]
        ],
    }
    items = [
        ("ledger", "v3/sources_ledger.json", dump(ledger), "source_ledger"),
        ("page", "v3/pages/page.txt", source_bytes, "page"),
        (
            "kiq",
            "v3/kiq/K1.json",
            dump({"id": "K1", "facts": [{"kiq": "K1", "text": page, "sids": [107], "verified_numbers": None}]}),
            "legacy_kiq",
        ),
        ("contract", "contract.json", authority_bytes, "contract"),
        ("qualification", "qualification.json", dump({"offline": True}), "review"),
    ]
    artifacts = []
    for aid, path, raw, role in items:
        dest = root / path
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(raw)
        artifacts.append(
            {
                "artifact_id": aid,
                "track_id": "main",
                "path": path,
                "sha256": digest(raw),
                "bytes": len(raw),
                "encoding": "utf8_text" if role == "page" else "utf8_json",
                "role": role,
            }
        )
    manifest = {
        "schema_version": "world-anchor-input/v1",
        "scope": scope_value,
        "parent_manifest_hash": None,
        "artifacts": artifacts,
        "tracks": [
            {
                "track_id": "main",
                "adapter": "legacy-kiq/v1",
                "ledger_artifact_id": "ledger",
                "kiq_artifact_ids": ["kiq"],
                "quantitative_artifact_id": None,
                "timeline_artifact_id": None,
                "actor_artifact_id": None,
                "case_artifact_id": None,
                "supporting_artifact_ids": [],
            }
        ],
        "crosswalk": [],
        "omissions": [],
    }
    index = wa.index_snapshot(
        root,
        manifest,
        expected_manifest_hash=wa.anchor_hash(manifest),
        expected_scope=scope_value,
        requirements=requirements,
        policy=policy,
    )
    return {
        "root": root,
        "scope": scope_value,
        "requirements": requirements,
        "policy": policy,
        "manifest": manifest,
        "index": index,
        "page": page,
    }


def review_fixture(fixture, *, producer="secondary_report", audience=None, verdict="explicit_support"):
    index = fixture["index"]
    data = index.snapshot()
    source = data["sources"][0]
    claim = data["inventory"][0]
    raw = index.artifact_bytes("page")
    locator = fixture.get("span", {"kind": "text_span", "start_byte": 0, "end_byte": len(raw), "quote": raw.decode()})
    ref = {
        "ref_id": wa._id("ref", source["source_key"], digest(raw), locator),
        "source_key": source["source_key"],
        **{k: data["scope"][k] for k in ("run_id", "research_generation_id", "snapshot_id")},
        "track_id": "main",
        "claim_id": claim["claim_id"],
        "kiq_id": "K1",
        "fact_index": 0,
        "artifact_id": "page",
        "content_hash": digest(raw),
        "locator": locator,
    }
    fields = sorted(wa.NUMERIC_FIELDS | {"producer_class", "audience", "actor_basis", "visible_at"})
    support = [
        {"field": field, "ref_id": ref["ref_id"], "selector": locator, "expected": locator["quote"]} for field in fields
    ]
    row = {
        "proposal_id": "proposal-1",
        "requirement_ids": [
            r["requirement_id"] for r in fixture["requirements"]["requirements"] if r["kind"] == "baseline"
        ],
        "claim_id": claim["claim_id"],
        "identity": identity(),
        "value": {"kind": "number", "value": "247.5"},
        "source_value": {"kind": "number", "value": "247.5"},
        "value_kind": "third_party_forecast",
        "producer_class": producer,
        "subject_actor_ref": None,
        "owner_actor_ref": None,
        "audience": audience or {"kind": "public", "actor_refs": []},
        "actor_basis": "public_record",
        "ref_ids": [ref["ref_id"]],
        "support": support,
        "conversion_id": None,
        **{k: unknown() for k in ("published_at", "available_at", "retrieved_at", "effective_at", "vintage")},
        "visible_at": {"value": "2026-10-27T00:00:00Z", "precision": "second", "basis_ref_ids": [ref["ref_id"]]},
        "cadence": {
            "kind": "unknown",
            "interval_days": None,
            "release_lag_days": None,
            "uncertainty_days": None,
            "ref_ids": [],
        },
        "supersedes_observation_id": None,
    }
    proposal = {
        "schema_version": "world-anchor-evidence-proposal/v1",
        "input_hash": data["input_hash"],
        "requirements_hash": data["requirements_hash"],
        "extraction_attempt_id": "extract-1",
        "references": [ref],
        "rows": [row],
    }
    decisions = [
        {
            "proposal_id": "proposal-1",
            "verdict": verdict,
            "checks": [{"field": field, "verdict": verdict, "ref_ids": [ref["ref_id"]]} for field in fields],
        }
    ]
    review = {
        "schema_version": "world-anchor-semantic-review/v1",
        "review_id": "review-1",
        "input_hash": data["input_hash"],
        "requirements_hash": data["requirements_hash"],
        "proposal_hash": wa.anchor_hash(proposal),
        "policy_hash": wa.anchor_hash(fixture["policy"]),
        "profile_id": "offline-scripted",
        "review_prompt_version": "review/v1",
        "extraction_attempt_id": "extract-1",
        "review_attempt_id": "review-attempt-1",
        "transport_receipt_artifact_id": "review-transport",
        "transport_receipt_hash": "",
        "raw_response_artifact_id": "review-response",
        "raw_response_hash": wa.anchor_hash({"decisions": decisions}),
        "decisions": decisions,
    }
    return proposal, review


def receipt_fixture(f, proposal, review, *, pretty=False):
    root = f["root"] / "receipts"
    root.mkdir(exist_ok=True)
    raw_extraction = {"references": proposal["references"], "rows": proposal["rows"]}
    raw_review = {"decisions": review["decisions"]}
    base = {
        "schema_version": "world-anchor-transport/v1",
        "mode": "offline_scripted",
        "anchor_budget_scope_id": None,
        "profile_id": "offline-scripted",
        "input_hash": proposal["input_hash"],
        "requirements_hash": proposal["requirements_hash"],
        "request_hash": "a" * 64,
        "physical_attempts": 0,
        "reserved_tokens": 0,
        "outcome": "completed",
    }
    extraction = {
        **base,
        "attempt_id": proposal["extraction_attempt_id"],
        "role": "extraction",
        "prompt_version": "extract/v1",
        "proposal_hash": None,
        "response_artifact_id": "extract-response",
        "response_hash": wa.anchor_hash(raw_extraction),
    }
    checked = {
        **base,
        "attempt_id": review["review_attempt_id"],
        "role": "semantic_review",
        "prompt_version": "review/v1",
        "proposal_hash": wa.anchor_hash(proposal),
        "response_artifact_id": "review-response",
        "response_hash": wa.anchor_hash(raw_review),
    }
    if pretty:
        checked["response_hash"] = digest(json.dumps(raw_review, indent=2).encode())
    review["transport_receipt_hash"] = wa.anchor_hash(checked)
    review["raw_response_hash"] = checked["response_hash"]
    files = []
    for aid, value, role in [
        ("extract-response", raw_extraction, "raw_response"),
        ("review-response", raw_review, "raw_response"),
        ("extract-transport", extraction, "transport_receipt"),
        ("review-transport", checked, "transport_receipt"),
    ]:
        raw = json.dumps(value, indent=2).encode() if pretty and aid == "review-response" else dump(value)
        path = aid + ".json"
        (root / path).write_bytes(raw)
        files.append({"artifact_id": aid, "path": path, "sha256": digest(raw), "bytes": len(raw), "role": role})
    manifest = {
        "schema_version": "world-anchor-producer-receipts/v1",
        "scope": f["scope"],
        "policy_hash": wa.anchor_hash(f["policy"]),
        "files": files,
        "transport_artifact_ids": ["extract-transport", "review-transport"],
    }
    return wa.producer_receipts(
        root, manifest, expected_manifest_hash=wa.anchor_hash(manifest), expected_scope=f["scope"]
    )


def enrich(f, **kwargs):
    proposal, review = review_fixture(f, **kwargs)
    receipts = receipt_fixture(f, proposal, review)
    f["index"] = wa.admit_reviewed_evidence(
        f["index"], proposal, review, requirements=f["requirements"], policy=f["policy"], receipts=receipts
    )
    return f


def build_pack(f):
    candidates = wa.candidates_for_requirements(f["requirements"], f["index"])
    reqs = {r["requirement_id"]: r for r in f["requirements"]["requirements"]}
    rows = [
        {
            "requirement_id": r["requirement_id"],
            "decision": "bind",
            "candidate_ids": [r["ranked"][0]["candidate_id"]] if r["ranked"] else [],
            "prior_policy_id": None,
            "note": "",
        }
        for r in candidates["rows"]
        if reqs[r["requirement_id"]]["kind"] != "target_definition"
    ]
    proposal = {
        "schema_version": "world-anchor-proposal/v1",
        "requirements_hash": wa.anchor_hash(f["requirements"]),
        "input_hash": f["index"].snapshot()["input_hash"],
        "candidate_hash": wa.anchor_hash(candidates),
        "rows": rows,
    }
    metering = {
        "anchor_budget_scope_id": None,
        "receipt_artifact_id": None,
        "receipt_hash": None,
        "mode": "offline_deterministic",
        "physical_model_attempts": 0,
        "reserved_tokens": 0,
        "physical_catalog_attempts": 0,
    }
    return wa.admit_bindings(
        f["requirements"], f["index"], candidates, proposal, policy=f["policy"], attempts=[], metering=metering
    )


def args(f):
    return {k: f[k] for k in ("requirements", "index", "policy")}


def test_missing_contract_inventory_emits_blocked_pack_and_roundtrips(tmp_path):
    f = make_fixture(tmp_path / "source", with_contract=False)
    pack = build_pack(f)
    assert pack["coverage"]["inventory_total"] == 1
    assert {r["status"] for r in pack["readiness"]} == {"blocked"}
    assert any(g["code"] == "missing_contract" for g in pack["gaps"])
    out = tmp_path / "out"
    out.mkdir()
    receipt = wa.emit_pack(out, pack, **args(f))
    assert (
        wa.read_pack(
            out,
            receipt,
            expected_receipt_hash=wa.anchor_hash(receipt),
            expected_pack_hash=wa.anchor_hash(pack),
            **args(f),
        )
        == pack
    )
    assert wa.emit_pack(out, pack, **args(f)) == receipt
    with pytest.raises(wa.AnchorError, match="E_NOT_READY"):
        wa.engine_projection(pack, engine="world-v1", **args(f))


@pytest.mark.parametrize(
    "fetched,expected",
    [("2026-10-26T09:29:13Z", "known_by_cutoff"), ("2026-10-28T00:00:00Z", "after_cutoff"), (None, "unknown")],
)
def test_capture_known_by_without_invented_publication(tmp_path, fetched, expected):
    f = make_fixture(tmp_path / "source", fetched_at=fetched)
    result = wa.availability_from_receipts(
        f["index"].snapshot()["sources"][0], index=f["index"], cutoff=f["scope"]["cutoff"]
    )
    assert result["cutoff_status"] == expected
    assert result["published_at"] == unknown()


def test_natural_prose_independent_review_binding_and_parameter_projection(tmp_path):
    f = enrich(make_fixture(tmp_path / "source"))
    pack = build_pack(f)
    assert all(r["status"] == "ready" for r in pack["readiness"])
    assert pack["observations"][0]["value_kind"] == "third_party_forecast"
    assert pack["observations"][0]["identity"]["reference_period"]["start"] == "2026-01-01"
    assert pack["observations"][0]["published_at"] == unknown()
    projection = wa.engine_projection(pack, engine="oasis-legacy", **args(f))
    assert projection["variables"][0]["node_id"] == "baseline"
    assert "proposal" not in projection
    binding = next(b for b in pack["bindings"] if b["observation_ids"])
    request = {
        "request_id": "parameter-1",
        "requirement_id": binding["requirement_id"],
        "binding_id": binding["binding_id"],
        "observation_id": binding["observation_ids"][0],
        "field": "value",
        "target": "/initialState/metrics/baseline/value",
        "target_object_id": "baseline",
        "identity": identity(),
        "expected_value": {"kind": "number", "value": "247.5"},
    }
    prepared = wa.prepare_world_parameters(pack, [request], expected_pack_hash=wa.anchor_hash(pack), **args(f))
    assert prepared["schema_version"] == "prepared-typed-world/v1"
    assert prepared["parameters"][0]["source_bindings"]
    request["target"] = "/initialState/metrics/other/value"
    with pytest.raises(wa.AnchorError, match="parameter_consumer"):
        wa.prepare_world_parameters(pack, [request], expected_pack_hash=wa.anchor_hash(pack), **args(f))


def test_ambiguous_review_produces_gap_not_numeric_anchor(tmp_path):
    f = enrich(make_fixture(tmp_path / "source"), verdict="ambiguous")
    pack = build_pack(f)
    assert pack["observations"] == []
    assert any(g["code"] == "ambiguous_support" for g in pack["gaps"])
    assert all(r["status"] == "blocked" for r in pack["readiness"])


@pytest.mark.parametrize("tamper", ["self_review", "quote", "scope", "response", "missing_check", "numeric"])
def test_review_and_reference_forgeries_fail_closed(tmp_path, tamper):
    f = make_fixture(tmp_path / "source")
    proposal, review = review_fixture(f)
    receipts = receipt_fixture(f, proposal, review)
    if tamper == "self_review":
        review["review_attempt_id"] = review["extraction_attempt_id"]
    elif tamper == "quote":
        proposal["references"][0]["locator"]["quote"] = "Fabricated 247.5"
    elif tamper == "scope":
        proposal["references"][0]["snapshot_id"] = "sibling"
    elif tamper == "response":
        review["decisions"][0]["verdict"] = "unsupported"
    elif tamper == "missing_check":
        review["decisions"][0]["checks"].pop()
    else:
        proposal["rows"][0]["value"]["value"] = "999"
    with pytest.raises(wa.AnchorError):
        wa.admit_reviewed_evidence(
            f["index"], proposal, review, requirements=f["requirements"], policy=f["policy"], receipts=receipts
        )


def test_no_self_authenticating_receipt_dict(tmp_path):
    f = make_fixture(tmp_path / "source")
    proposal, review = review_fixture(f)
    with pytest.raises(wa.AnchorError, match="producer_receipts"):
        wa.admit_reviewed_evidence(
            f["index"],
            proposal,
            review,
            requirements=f["requirements"],
            policy=f["policy"],
            receipts={"sha256": wa.anchor_hash(review)},
        )


@pytest.mark.parametrize(
    "producer,audience,count",
    [
        ("secondary_report", {"kind": "public", "actor_refs": []}, 1),
        ("research_analyst", {"kind": "public", "actor_refs": []}, 0),
        ("secondary_report", {"kind": "actors", "actor_refs": ["rival"]}, 0),
    ],
)
def test_actor_privacy_and_producer_class_independent(tmp_path, producer, audience, count):
    f = enrich(make_fixture(tmp_path / "source"), producer=producer, audience=audience)
    result = wa.actor_projection(build_pack(f), actor_ref="self", at="2026-10-28T00:00:00Z", **args(f))
    assert len(result["items"]) == count
    assert set(result) == {"schema_version", "actor_ref", "at", "items"}
    assert "pack_hash" not in dump(result).decode()


def test_tampered_pack_and_companion_rejected(tmp_path):
    f = enrich(make_fixture(tmp_path / "source"))
    pack = build_pack(f)
    out = tmp_path / "out"
    out.mkdir()
    receipt = wa.emit_pack(out, pack, **args(f))
    corrupt = copy.deepcopy(pack)
    corrupt["observations"][0]["value"]["value"] = "999"
    with pytest.raises(wa.AnchorError, match="E_HASH"):
        wa.validate_pack(corrupt, **args(f))
    (out / "world_anchor_gaps.json").write_bytes(b"{}")
    with pytest.raises(wa.AnchorError, match="E_HASH"):
        wa.read_pack(
            out,
            receipt,
            expected_receipt_hash=wa.anchor_hash(receipt),
            expected_pack_hash=wa.anchor_hash(pack),
            **args(f),
        )
    with pytest.raises(wa.AnchorError, match="E_IMMUTABLE"):
        wa.emit_pack(out, pack, **args(f))


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -float("inf"), 2**90, {"a": object()}])
def test_finite_json_bounds(value):
    with pytest.raises(wa.AnchorError):
        wa.anchor_hash(value)


def test_duplicate_json_keys_and_cycles_rejected():
    with pytest.raises(wa.AnchorError, match="E_DUPLICATE_KEY"):
        wa._load(b'{"a":1,"a":2}')
    cyclic = []
    cyclic.append(cyclic)
    with pytest.raises(wa.AnchorError, match="cycle"):
        wa.anchor_hash(cyclic)
    assert wa.anchor_hash({"b": 2, "a": 1}) == wa.anchor_hash({"a": 1, "b": 2})


@pytest.mark.parametrize(
    "path", ["../outside", "/absolute", "pages/../outside", "pages\\outside", "./file", "pages//file"]
)
def test_paths_reject_before_read(tmp_path, path):
    with pytest.raises(wa.AnchorError, match="E_PATH"):
        wa._read(tmp_path, path, 100)


def test_symlink_and_changed_input_fail_closed(tmp_path):
    f = make_fixture(tmp_path / "source")
    page = f["root"] / "v3/pages/page.txt"
    page.unlink()
    page.symlink_to(f["root"] / "contract.json")
    with pytest.raises(wa.AnchorError, match="E_PATH"):
        wa.index_snapshot(
            f["root"],
            f["manifest"],
            expected_manifest_hash=wa.anchor_hash(f["manifest"]),
            expected_scope=f["scope"],
            requirements=f["requirements"],
            policy=f["policy"],
        )
    page.unlink()
    page.write_text("changed")
    with pytest.raises(wa.AnchorError, match="E_HASH"):
        wa.index_snapshot(
            f["root"],
            f["manifest"],
            expected_manifest_hash=wa.anchor_hash(f["manifest"]),
            expected_scope=f["scope"],
            requirements=f["requirements"],
            policy=f["policy"],
        )


def test_index_views_cannot_rewrite_admission(tmp_path):
    f = make_fixture(tmp_path / "source")
    view = f["index"].snapshot()
    view["sources"][0]["local_source_id"] = "999"
    assert f["index"].snapshot()["sources"][0]["local_source_id"] == "107"
    with pytest.raises(wa.AnchorError, match="E_IMMUTABLE"):
        f["index"]._data = b"{}"


def test_late_capture_cannot_admit_initial_state(tmp_path):
    f = enrich(make_fixture(tmp_path / "source", fetched_at="2026-10-28T00:00:00Z"))
    pack = build_pack(f)
    assert all(r["status"] == "blocked" for r in pack["readiness"])
    assert any(g["code"] == "after_cutoff" for g in pack["gaps"])


def test_pretty_raw_review_bytes_remain_valid(tmp_path):
    f = make_fixture(tmp_path / "source")
    proposal, review = review_fixture(f)
    receipts = receipt_fixture(f, proposal, review, pretty=True)
    enriched = wa.admit_reviewed_evidence(
        f["index"], proposal, review, requirements=f["requirements"], policy=f["policy"], receipts=receipts
    )
    assert len(enriched.snapshot()["observations"]) == 1


@pytest.mark.parametrize(
    "token,value",
    [("10.", "10"), ("10.5.", "10.5"), ("10,", "10"), ("10.5;", "10.5"), ("10。", "10"), ("10.5)", "10.5")],
)
def test_sentence_punctuation_numeric_admission(tmp_path, token, value):
    f = make_fixture(
        tmp_path / "source",
        page="A secondary report forecasts cybersecurity spending in billion USD for 2026: " + token,
    )
    proposal, review = review_fixture(f)
    proposal["rows"][0]["value"] = proposal["rows"][0]["source_value"] = {"kind": "number", "value": value}
    review["proposal_hash"] = wa.anchor_hash(proposal)
    receipts = receipt_fixture(f, proposal, review)
    admitted = wa.admit_reviewed_evidence(
        f["index"], proposal, review, requirements=f["requirements"], policy=f["policy"], receipts=receipts
    )
    assert admitted.snapshot()["observations"][0]["value"]["value"] == value


@pytest.mark.parametrize(
    "token,value",
    [
        ("1.2", "1"),
        ("x10", "10"),
        ("10units", "10"),
        ("1e3", "1"),
        ("1e-3", "3"),
        ("1.2e3", "1.2"),
        ("1.2.3", "3"),
        (".5", "5"),
    ],
)
def test_embedded_or_scientific_partial_numbers_rejected(tmp_path, token, value):
    f = make_fixture(
        tmp_path / "source",
        page="A secondary report forecasts cybersecurity spending in billion USD for 2026: " + token + " marker.",
    )
    proposal, review = review_fixture(f)
    proposal["rows"][0]["value"] = proposal["rows"][0]["source_value"] = {"kind": "number", "value": value}
    review["proposal_hash"] = wa.anchor_hash(proposal)
    receipts = receipt_fixture(f, proposal, review)
    with pytest.raises(wa.AnchorError, match="numeric_support"):
        wa.admit_reviewed_evidence(
            f["index"], proposal, review, requirements=f["requirements"], policy=f["policy"], receipts=receipts
        )


_PRIVATE_FIXTURE = None


def private_fixture_data():
    global _PRIVATE_FIXTURE
    if _PRIVATE_FIXTURE is None:
        encoded = os.environ.get("WORLD_ANCHOR_PRIVATE_FIXTURE")
        if not encoded and type(sys.stdin).__name__ != "DontReadFromInput":
            encoded = sys.stdin.read(5 * 1024 * 1024)
        if not encoded:
            pytest.skip("private source bytes supplied only by the explicit offline receipt launcher")
        _PRIVATE_FIXTURE = json.loads(zlib.decompress(base64.b64decode(encoded)))
    return _PRIVATE_FIXTURE


def test_private_s107_captured_bytes_with_separate_scripted_review(tmp_path):
    private = private_fixture_data()
    assert digest(private["page"].encode()) == private["content_hash"]
    f = make_fixture(tmp_path / "private", page=private["page"], fetched_at=private["fetched_at"], target_year=2026)
    f["span"] = {"kind": "text_span", **{k: private["span"][k] for k in ("start_byte", "end_byte", "quote")}}
    proposal, review = review_fixture(f)
    proposal["rows"][0]["visible_at"] = unknown()
    proposal["rows"][0]["support"] = [s for s in proposal["rows"][0]["support"] if s["field"] != "visible_at"]
    review["decisions"][0]["checks"] = [c for c in review["decisions"][0]["checks"] if c["field"] != "visible_at"]
    review["proposal_hash"] = wa.anchor_hash(proposal)
    receipts = receipt_fixture(f, proposal, review)
    f["index"] = wa.admit_reviewed_evidence(
        f["index"], proposal, review, requirements=f["requirements"], policy=f["policy"], receipts=receipts
    )
    pack = build_pack(f)
    obs = pack["observations"][0]
    assert obs["value"] == {"kind": "number", "value": "247.5"}
    assert obs["value_kind"] == "third_party_forecast"
    assert obs["identity"]["reference_period"] == identity(2026)["reference_period"]
    assert obs["published_at"] == unknown()
    assert obs["known_by"]["value"] == private["fetched_at"]
    assert all(v["history_observation_ids"] == [] for v in pack["variables"])
    assert all(o["value_kind"] != "observed" for o in pack["observations"])
    out = tmp_path / "out"
    out.mkdir()
    receipt = wa.emit_pack(out, pack, **args(f))
    assert (
        wa.read_pack(
            out,
            receipt,
            expected_receipt_hash=wa.anchor_hash(receipt),
            expected_pack_hash=wa.anchor_hash(pack),
            **args(f),
        )
        == pack
    )

    if "vintages" in private:
        vf = make_fixture(
            tmp_path / "vintages",
            with_contract=False,
            page=private["page"],
            fetched_at=private["fetched_at"],
            target_year=2026,
        )
        vf["span"] = {"kind": "text_span", **private["revision_span"]}
        vp, vr = review_fixture(vf)
        base_row, base_decision = vp["rows"][0], vr["decisions"][0]
        vp["rows"], vr["decisions"] = [], []
        for i, vintage in enumerate(private["vintages"]):
            row = copy.deepcopy(base_row)
            row.update(
                proposal_id="vintage-" + str(i),
                requirement_ids=[],
                value={"kind": "number", "value": vintage["value"]},
                source_value={"kind": "number", "value": vintage["value"]},
                visible_at=unknown(),
            )
            row["support"] = [v for v in row["support"] if v["field"] != "visible_at"]
            for support in row["support"]:
                if support["field"] == "value":
                    support["selector"] = {"kind": "text_span", **vintage["span"]}
                    support["expected"] = vintage["span"]["quote"]
            vp["rows"].append(row)
            decision = copy.deepcopy(base_decision)
            decision["proposal_id"] = row["proposal_id"]
            decision["checks"] = [c for c in decision["checks"] if c["field"] != "visible_at"]
            vr["decisions"].append(decision)
        vr["proposal_hash"] = wa.anchor_hash(vp)
        handles = receipt_fixture(vf, vp, vr)
        vf["index"] = wa.admit_reviewed_evidence(
            vf["index"], vp, vr, requirements=vf["requirements"], policy=vf["policy"], receipts=handles
        )
        vintage_pack = build_pack(vf)
        assert {o["value"]["value"] for o in vintage_pack["observations"]} == {
            "239.8",
            "244.2",
            "246.2",
            "248.2",
            "247.5",
        }
        assert all(
            o["value_kind"] == "third_party_forecast"
            and o["identity"]["reference_period"] == identity(2026)["reference_period"]
            for o in vintage_pack["observations"]
        )
        assert vintage_pack["variables"] == vintage_pack["requirements"] == []
        assert all(r["status"] == "blocked" for r in vintage_pack["readiness"])
        vout = tmp_path / "vintage-out"
        vout.mkdir()
        wa.emit_pack(vout, vintage_pack, **args(vf))


def test_equal_sid_in_another_track_cannot_authenticate_claim(tmp_path):
    f = make_fixture(tmp_path / "source")
    manifest = copy.deepcopy(f["manifest"])
    for artifact in list(manifest["artifacts"]):
        cloned = {**artifact, "artifact_id": artifact["artifact_id"] + "-rival", "track_id": "rival"}
        manifest["artifacts"].append(cloned)
    track = copy.deepcopy(manifest["tracks"][0])
    track.update(track_id="rival", ledger_artifact_id="ledger-rival", kiq_artifact_ids=["kiq-rival"])
    manifest["tracks"].append(track)
    f["index"] = wa.index_snapshot(
        f["root"],
        manifest,
        expected_manifest_hash=wa.anchor_hash(manifest),
        expected_scope=f["scope"],
        requirements=f["requirements"],
        policy=f["policy"],
    )
    proposal, review = review_fixture(f)
    rival = next(s for s in f["index"].snapshot()["sources"] if s["track_id"] == "rival")
    ref = proposal["references"][0]
    ref.update(source_key=rival["source_key"], track_id="rival", artifact_id="page-rival")
    ref["ref_id"] = wa._id("ref", ref["source_key"], ref["content_hash"], ref["locator"])
    for row in proposal["rows"]:
        row["ref_ids"] = [ref["ref_id"]]
        for support in row["support"]:
            support["ref_id"] = ref["ref_id"]
    for check in review["decisions"][0]["checks"]:
        check["ref_ids"] = [ref["ref_id"]]
    review["proposal_hash"] = wa.anchor_hash(proposal)
    receipts = receipt_fixture(f, proposal, review)
    with pytest.raises(wa.AnchorError, match="claim_track"):
        wa.admit_reviewed_evidence(
            f["index"], proposal, review, requirements=f["requirements"], policy=f["policy"], receipts=receipts
        )


def test_official_manifest_inventory_preserves_flags_and_rejects_missing_member(tmp_path):
    f = make_fixture(tmp_path / "source")
    manifest = copy.deepcopy(f["manifest"])
    native = {
        "series": "fred:TEST",
        "provider": "fred",
        "units": "USD",
        "frequency": "annual",
        "source_url": "https://example.test/official",
        "retrieved_at": "2026-10-26T00:00:00Z",
        "observations": [{"date": "2027-01-01", "value": 12.5, "flag": "forecast"}],
    }
    raw = dump(native)
    csv = b"date,value\n2027-01-01,12.5\n"
    entry = {k: v for k, v in native.items() if k not in ("observations", "retrieved_at")}
    entry.update(file="data/test.json", sha256=digest(raw), csv="data/test.csv", csv_sha256=digest(csv))
    for aid, path, data, role, encoding in [
        ("official", "data/test.json", raw, "official_series", "utf8_json"),
        ("official-csv", "data/test.csv", csv, "official_csv", "utf8_text"),
        (
            "official-manifest",
            "data/datasets.json",
            dump({"schema_version": 1, "series": [entry]}),
            "official_manifest",
            "utf8_json",
        ),
    ]:
        dest = f["root"] / path
        dest.parent.mkdir(exist_ok=True)
        dest.write_bytes(data)
        manifest["artifacts"].append(
            {
                "artifact_id": aid,
                "track_id": "main",
                "path": path,
                "sha256": digest(data),
                "bytes": len(data),
                "encoding": encoding,
                "role": role,
            }
        )
    indexed = wa.index_snapshot(
        f["root"],
        manifest,
        expected_manifest_hash=wa.anchor_hash(manifest),
        expected_scope=f["scope"],
        requirements=f["requirements"],
        policy=f["policy"],
    )
    record = next(r for r in indexed.snapshot()["inventory"] if r["origin"] == "official_observation")
    assert record["raw_hash"] == wa.anchor_hash(native["observations"][0])
    assert indexed.snapshot()["observations"] == []
    manifest["artifacts"] = [a for a in manifest["artifacts"] if a["artifact_id"] != "official-csv"]
    with pytest.raises(wa.AnchorError, match="official_member"):
        wa.index_snapshot(
            f["root"],
            manifest,
            expected_manifest_hash=wa.anchor_hash(manifest),
            expected_scope=f["scope"],
            requirements=f["requirements"],
            policy=f["policy"],
        )


def test_unused_engine_mechanism_does_not_block_or_enter_world_projection(tmp_path):
    f = make_fixture(tmp_path / "source")
    contract = f["requirements"]["contract"]
    contract["mechanisms"] = [
        {
            "mechanism_id": "sum-target",
            "template": "sum",
            "template_version": "v1",
            "input_node_ids": ["baseline"],
            "output_node_id": "target",
            "parameters": [],
            "lag_requirement_origin": None,
            "applicability_requirement_origins": [],
            "consumers": [consumer("target-first-v1", "mechanism", "sum-target", "output")],
        }
    ]
    authority = {"settlement": identity(2027), "terms": contract["terms"], "mechanisms": contract["mechanisms"]}
    raw = dump(authority)
    (f["root"] / "contract.json").write_bytes(raw)
    contract["authority_artifact_hash"] = digest(raw)
    item = next(a for a in f["manifest"]["artifacts"] if a["artifact_id"] == "contract")
    item.update(sha256=digest(raw), bytes=len(raw))
    f["requirements"] = wa.requirements_from_contract(contract, scope=f["scope"])
    f["index"] = wa.index_snapshot(
        f["root"],
        f["manifest"],
        expected_manifest_hash=wa.anchor_hash(f["manifest"]),
        expected_scope=f["scope"],
        requirements=f["requirements"],
        policy=f["policy"],
    )
    f = enrich(f)
    pack = build_pack(f)
    readiness = {r["engine"]: r["status"] for r in pack["readiness"]}
    assert readiness["target-first-v1"] == "blocked"
    assert readiness["world-v1"] == "ready"
    assert wa.engine_projection(pack, engine="world-v1", **args(f))["mechanisms"] == []


def test_diagnostic_only_engines_block_but_mapped_engine_remains_ready(tmp_path):
    f = make_fixture(tmp_path / "source")
    contract = f["requirements"]["contract"]
    contract["terms"][1]["consumers"] = [consumer("oasis-legacy", "initial_state", "baseline", "value")]
    raw = dump({"settlement": identity(2027), "terms": contract["terms"]})
    (f["root"] / "contract.json").write_bytes(raw)
    contract["authority_artifact_hash"] = digest(raw)
    item = next(a for a in f["manifest"]["artifacts"] if a["artifact_id"] == "contract")
    item.update(sha256=digest(raw), bytes=len(raw))
    f["requirements"] = wa.requirements_from_contract(contract, scope=f["scope"])
    f["index"] = wa.index_snapshot(
        f["root"],
        f["manifest"],
        expected_manifest_hash=wa.anchor_hash(f["manifest"]),
        expected_scope=f["scope"],
        requirements=f["requirements"],
        policy=f["policy"],
    )
    f = enrich(f)
    pack = build_pack(f)
    readiness = {r["engine"]: r["status"] for r in pack["readiness"]}
    assert readiness == {"oasis-legacy": "ready", "world-v1": "blocked", "target-first-v1": "blocked"}
    assert wa.engine_projection(pack, engine="oasis-legacy", **args(f))["variables"]
    with pytest.raises(wa.AnchorError, match="E_NOT_READY"):
        wa.engine_projection(pack, engine="world-v1", **args(f))
    out = tmp_path / "out"
    out.mkdir()
    assert wa.emit_pack(out, pack, **args(f))["pack_hash"] == wa.anchor_hash(pack)


def test_private_full_inventory_without_contract_emits_blocked_pack(tmp_path):
    private = private_fixture_data()
    if "files" not in private:
        pytest.skip("full private corpus not supplied by this launcher")
    root = tmp_path / "corpus"
    root.mkdir()
    artifacts = []
    ids = {}
    assert sum(record["path"].startswith("raw/") for record in private["files"]) == 95
    for record in private["files"]:
        relative = record["path"]
        assert not relative.startswith("/") and ".." not in relative.split("/")
        raw = base64.b64decode(record["data"])
        assert digest(raw) == record["sha256"]
        dest = root / relative
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(raw)
        aid = "input_" + digest(relative.encode())
        ids[relative] = aid
        artifacts.append(
            {
                "artifact_id": aid,
                "track_id": private["track"],
                "path": relative,
                "sha256": record["sha256"],
                "bytes": len(raw),
                "encoding": "utf8_json" if relative.endswith(".json") else "utf8_text",
                "role": record["role"],
            }
        )
    snapshot_scope = private["scope"]
    requirements = wa.requirements_from_contract(None, scope=snapshot_scope)
    settings = make_fixture(tmp_path / "settings", with_contract=False)
    policy = settings["policy"]
    manifest = {
        "schema_version": "world-anchor-input/v1",
        "scope": snapshot_scope,
        "parent_manifest_hash": private["manifest_hash"],
        "artifacts": artifacts,
        "tracks": [
            {
                "track_id": private["track"],
                "adapter": "legacy-kiq/v1",
                "ledger_artifact_id": ids["raw/handoff/v3/sources_ledger.json"],
                "kiq_artifact_ids": [a["artifact_id"] for a in artifacts if a["role"] == "legacy_kiq"],
                "quantitative_artifact_id": ids["raw/handoff/quantitative.json"],
                "timeline_artifact_id": ids["raw/handoff/timeline.json"],
                "actor_artifact_id": ids["raw/handoff/actors.json"],
                "case_artifact_id": None,
                "supporting_artifact_ids": [],
            }
        ],
        "crosswalk": [],
        "omissions": [],
    }
    index = wa.index_snapshot(
        root,
        manifest,
        expected_manifest_hash=wa.anchor_hash(manifest),
        expected_scope=snapshot_scope,
        requirements=requirements,
        policy=policy,
    )
    view = index.snapshot()
    assert len(view["sources"]) == 201
    assert sum(s["retention"] == "fetched_page" for s in view["sources"]) == 34
    assert sum(s["retention"] == "snippet_only" for s in view["sources"]) == 167
    assert sum(r["origin"] == "kiq_fact" for r in view["inventory"]) == 116
    assert sum(r["origin"] == "legacy_quant" for r in view["inventory"]) == 52
    assert sum(r["origin"] == "legacy_timeline" for r in view["inventory"]) == 24
    context = {"requirements": requirements, "index": index, "policy": policy}
    pack = build_pack(context)
    assert pack["variables"] == pack["observations"] == pack["requirements"] == []
    assert all(row["status"] == "blocked" for row in pack["readiness"])
    assert any(gap["code"] == "missing_contract" for gap in pack["gaps"])
    out = tmp_path / "out"
    out.mkdir()
    receipt = wa.emit_pack(out, pack, **context)
    assert (
        wa.read_pack(
            out,
            receipt,
            expected_receipt_hash=wa.anchor_hash(receipt),
            expected_pack_hash=wa.anchor_hash(pack),
            **context,
        )
        == pack
    )


@pytest.mark.parametrize(
    "fetched_at,visible_at,at,expected_count",
    [
        ("2026-10-26T09:29:13Z", "2026-10-25T00:00:00Z", "2026-10-25T12:00:00Z", 0),
        ("2026-10-26T09:29:13Z", "2026-10-25T00:00:00Z", "2026-10-26T09:29:12Z", 0),
        ("2026-10-26T09:29:13Z", "2026-10-25T00:00:00Z", "2026-10-26T09:29:13Z", 1),
        ("2026-10-26T09:29:13Z", "2026-10-27T00:00:00Z", "2026-10-26T10:00:00Z", 0),
        ("2026-10-26T09:29:13Z", "2026-10-27T00:00:00Z", "2026-10-28T00:00:00Z", 1),
        ("2026-10-28T00:00:00Z", "2026-10-25T00:00:00Z", "2026-10-29T00:00:00Z", 0),
        (None, "2026-10-25T00:00:00Z", "2026-10-29T00:00:00Z", 0),
        ("2026-10-27T23:59:59Z", "2026-10-25T00:00:00Z", "2026-10-27T23:59:59Z", 1),
        ("2026-10-27T23:59:59Z", "2026-10-25T00:00:00Z", "2026-10-27T23:59:58Z", 0),
    ],
)
def test_actor_time_requires_capture_by_cutoff_and_requested_time(tmp_path, fetched_at, visible_at, at, expected_count):
    f = make_fixture(tmp_path / "source", fetched_at=fetched_at)
    proposal, review = review_fixture(f)
    # Deliberately grant early visibility in a pinned scripted review. It must
    # never override the independently authenticated capture/known-by bound.
    proposal["rows"][0]["visible_at"]["value"] = visible_at
    review["proposal_hash"] = wa.anchor_hash(proposal)
    receipts = receipt_fixture(f, proposal, review)
    f["index"] = wa.admit_reviewed_evidence(
        f["index"],
        proposal,
        review,
        requirements=f["requirements"],
        policy=f["policy"],
        receipts=receipts,
    )
    projection = wa.actor_projection(build_pack(f), actor_ref="self", at=at, **args(f))
    assert len(projection["items"]) == expected_count
    if expected_count:
        assert projection["items"][0]["known_by"] == fetched_at


def test_unreviewed_visible_at_cannot_grant_actor_knowledge(tmp_path):
    f = make_fixture(tmp_path / "source")
    proposal, review = review_fixture(f)
    proposal["rows"][0]["visible_at"]["value"] = "2026-10-25T00:00:00Z"
    review["decisions"][0]["checks"] = [
        check for check in review["decisions"][0]["checks"] if check["field"] != "visible_at"
    ]
    review["proposal_hash"] = wa.anchor_hash(proposal)
    receipts = receipt_fixture(f, proposal, review)
    f["index"] = wa.admit_reviewed_evidence(
        f["index"],
        proposal,
        review,
        requirements=f["requirements"],
        policy=f["policy"],
        receipts=receipts,
    )
    pack = build_pack(f)
    assert any(gap["code"] == "ambiguous_support" for gap in pack["gaps"])
    assert wa.actor_projection(pack, actor_ref="self", at="2026-10-28T00:00:00Z", **args(f))["items"] == []


def anchor_sheet_fixture(tmp_path):
    statement = "Analysts infer that Example agency may delay the filing."
    page = (
        "A secondary report forecasts cybersecurity spending of 247.5 billion USD for 2026. "
        "The forecast vintage is 2026-10-26. " + statement
    )
    f = make_fixture(tmp_path / "source", page=page)
    contract = f["requirements"]["contract"]
    labels = {
        "entity": "Cyber | security <script>alert(1)</script> ![trap](https://invalid.test/image)\n## injected",
        "metric": "Annual spending",
        "unit": "USD billions",
    }
    registry = {
        "actors": [
            {"name": "Example agency", "role_class": "government"},
            {"name": "Unclassified actor"},
        ]
    }

    def add_artifact(aid, path, value, role="contract"):
        raw = dump(value)
        (f["root"] / path).write_bytes(raw)
        f["manifest"]["artifacts"].append(
            {
                "artifact_id": aid,
                "track_id": "main",
                "path": path,
                "sha256": digest(raw),
                "bytes": len(raw),
                "encoding": "utf8_json",
                "role": role,
            }
        )
        return digest(raw)

    labels_hash = add_artifact("labels", "labels.json", labels)
    add_artifact("registry", "registry.json", registry, "actor_bundle")
    f["manifest"]["tracks"][0]["actor_artifact_id"] = "registry"
    contract["aliases"] = [
        {
            "field": field,
            "canonical_id": canonical,
            "literal": labels[key],
            "artifact_id": "labels",
            "artifact_hash": labels_hash,
            "pointer": "/" + key,
        }
        for field, canonical, key in [
            ("entity", "cybersecurity", "entity"),
            ("metric", "spending", "metric"),
            ("unit", "usd_billion", "unit"),
        ]
    ]
    ratio = {
        "id": "ratio",
        "dimension": "ratio",
        "scale": "1",
        "currency": None,
        "price_basis": "not_applicable",
        "base_period": None,
    }

    def term(kind, value_type, metric=None, consumer_role="diagnostic", actor_ref=None):
        origin = "/terms/" + str(len(contract["terms"]))
        ident = None
        if metric:
            ident = identity()
            ident["metric_id"] = metric
            if metric in {"coefficient", "hazard_rate"}:
                ident["unit"] = copy.deepcopy(ratio)
        item = {
            **copy.deepcopy(contract["terms"][1]),
            "origin_pointer": origin,
            "kind": kind,
            "identity": ident,
            "value_type": value_type,
            "actor_ref": actor_ref,
            "required": False,
            "accepted_value_kinds": ["reported", "assumed", "analyst_inferred"],
            "consumers": [consumer("oasis-legacy", consumer_role, kind, "value")],
        }
        contract["terms"].append(item)
        return origin

    coefficient = term("mechanism_parameter", "number", "coefficient", "mechanism")
    contract["terms"][-1]["assumption_policy_id"] = "prior-coefficient"
    actor_statement = term("actor_statement", "text", consumer_role="actor_brief", actor_ref="agency")
    event = term("event", "text", consumer_role="calendar")
    event_time = term("event", "text", consumer_role="calendar")
    likelihood = term("hazard", "number", "hazard_rate", "calendar")
    effect = term("hazard", "number", "shock_delta", "calendar")
    recurrence = term("hazard", "boolean", consumer_role="calendar")
    contract["mechanisms"] = [
        {
            "mechanism_id": "forecast-linear",
            "template": "linear",
            "template_version": "v1",
            "input_node_ids": ["baseline"],
            "output_node_id": "target",
            "parameters": [
                {"name": "coefficient:baseline", "requirement_origin": coefficient, "unit": ratio},
                {"name": "intercept", "requirement_origin": "/terms/1", "unit": unit()},
            ],
            "lag_requirement_origin": None,
            "applicability_requirement_origins": [],
            "consumers": [consumer("oasis-legacy", "mechanism", "forecast-linear", "output")],
        }
    ]
    contract["actors"] = [
        {
            "actor_ref": "agency",
            "registry_artifact_id": "registry",
            "registry_pointer": "/actors/0",
            "statements": [actor_statement],
            "authority": [],
            "plans": [],
            "red_lines": [],
        },
        {
            "actor_ref": "unclassified",
            "registry_artifact_id": "registry",
            "registry_pointer": "/actors/1",
            "statements": [],
            "authority": [],
            "plans": [],
            "red_lines": [],
        },
    ]
    contract["calendar"] = [
        {
            "event_id": "filing-intention",
            "requirement_origin": event,
            "classification": "intention",
            "time_requirement_origin": event_time,
            "effect_requirement_origins": [],
        }
    ]
    predicate = {"node_id": "baseline", "operator": "gt", "value": "250"}
    contract["hazards"] = [
        {
            "hazard_id": "supply-shock",
            "trigger": predicate,
            "likelihood_requirement_origin": likelihood,
            "effect_requirement_origins": [effect],
            "recurrence_requirement_origin": recurrence,
            "consumers": [consumer("oasis-legacy", "calendar", "baseline", "add")],
        }
    ]
    contract["indicators"] = [
        {
            "indicator_id": "spending-signpost",
            "node_id": "baseline",
            "requirement_origin": "/terms/1",
            "consumer": consumer("oasis-legacy", "observation", "baseline", "signpost"),
            "trigger": predicate,
        }
    ]
    contract["reference_classes"] = [
        {
            "reference_class_id": "forecast-revisions",
            "membership_requirement_origins": ["/terms/1"],
            "observation_ids": [],
            "purpose": "diagnostic",
        }
    ]
    contract["identities"] = [
        {
            "identity_id": "spending-identity",
            "lhs_node_id": "baseline",
            "rhs_mechanism_id": "forecast-linear",
            "absolute_tolerance": "0",
            "relative_tolerance": "0",
            "scale_unit": unit(),
            "basis_requirement_origin": "/terms/1",
        }
    ]
    prior = {"value": {"kind": "number", "value": "0.5"}, "library_version": "fixture-prior/v1"}
    prior_hash = add_artifact("prior", "prior.json", prior, "policy")
    f["policy"]["prior_rules"] = [
        {
            "policy_id": "prior-coefficient",
            "artifact_id": "prior",
            "artifact_hash": prior_hash,
            "pointer": "",
            "requirement_origins": [coefficient],
            "value": prior["value"],
            "identity": contract["terms"][2]["identity"],
            "rationale": "Explicit fixture modeling assumption",
            "library_version": prior["library_version"],
        }
    ]
    all_consumers = [c for t in contract["terms"] for c in t["consumers"]] + contract["mechanisms"][0]["consumers"]
    f["policy"]["consumer_rules"] = [
        {**c, "adapter_version": "world-anchor-reflexive/v1", "template_versions": ["v1"]} for c in all_consumers
    ]
    f["manifest"]["omissions"] = [
        {
            "artifact_id": "missing-native-series",
            "track_id": "main",
            "pointer": "/observations",
            "reason": "not_retained",
            "declared_count": None,
        }
    ]
    authority = {
        "settlement": identity(2027),
        "terms": contract["terms"],
        "aliases": contract["aliases"],
        **{k: contract[k] for k in wa.SPEC_FIELDS},
    }
    raw = dump(authority)
    (f["root"] / "contract.json").write_bytes(raw)
    contract["authority_artifact_hash"] = digest(raw)
    next(a for a in f["manifest"]["artifacts"] if a["artifact_id"] == "contract").update(
        sha256=digest(raw), bytes=len(raw)
    )
    f["requirements"] = wa.requirements_from_contract(contract, scope=f["scope"])
    f["index"] = wa.index_snapshot(
        f["root"],
        f["manifest"],
        expected_manifest_hash=wa.anchor_hash(f["manifest"]),
        expected_scope=f["scope"],
        requirements=f["requirements"],
        policy=f["policy"],
    )
    proposal, review = review_fixture(f)
    row = proposal["rows"][0]
    row["vintage"] = {"value": "2026-10-26T00:00:00Z", "precision": "day", "basis_ref_ids": row["ref_ids"]}
    row["support"].append({**row["support"][0], "field": "vintage"})
    review["decisions"][0]["checks"].append(
        {"field": "vintage", "verdict": "explicit_support", "ref_ids": row["ref_ids"]}
    )
    actor_row = copy.deepcopy(row)
    actor_requirement = next(r for r in f["requirements"]["requirements"] if r["origin_pointer"] == actor_statement)
    actor_row.update(
        proposal_id="actor-statement",
        requirement_ids=[actor_requirement["requirement_id"]],
        identity=None,
        value={"kind": "text", "value": statement},
        source_value={"kind": "text", "value": statement},
        value_kind="analyst_inferred",
        producer_class="research_analyst",
        subject_actor_ref="agency",
        audience={"kind": "analyst", "actor_refs": []},
        actor_basis="none",
    )
    proposal["rows"].append(actor_row)
    review["decisions"].append({**copy.deepcopy(review["decisions"][0]), "proposal_id": "actor-statement"})
    review["proposal_hash"] = wa.anchor_hash(proposal)
    receipts = receipt_fixture(f, proposal, review)
    f["index"] = wa.admit_reviewed_evidence(
        f["index"], proposal, review, requirements=f["requirements"], policy=f["policy"], receipts=receipts
    )
    f["sheet_proposal"], f["sheet_review"], f["sheet_receipts"] = proposal, review, receipts
    pack = build_pack(f)
    binding_proposal = pack["proposal"]
    parameter_id = next(
        r["requirement_id"] for r in f["requirements"]["requirements"] if r["origin_pointer"] == coefficient
    )
    for item in binding_proposal["rows"]:
        if item["requirement_id"] == parameter_id:
            item.update(decision="assume", candidate_ids=[], prior_policy_id="prior-coefficient")
    pack = wa.admit_bindings(
        f["requirements"],
        f["index"],
        pack["candidates"],
        binding_proposal,
        policy=f["policy"],
        attempts=[],
        metering=pack["metering"],
    )
    return f, pack, statement


def test_private_anchor_sheet_has_useful_domain_tables(tmp_path):
    import html

    f, pack, statement = anchor_sheet_fixture(tmp_path)
    original_hash = wa.anchor_hash(pack)
    actor_before = wa.actor_projection(pack, actor_ref="agency", at="2026-10-28T00:00:00Z", **args(f))
    out = tmp_path / "sheet"
    out.mkdir()
    receipt = wa.emit_pack(out, pack, **args(f))
    sheet = (out / "world_anchor.md").read_text()
    for title in [
        "Variables",
        "Mechanisms",
        "Parameter bases",
        "Actor items",
        "Calendar",
        "Hazards",
        "Indicators",
        "Reference classes",
        "Identities",
        "Sources",
        "Gaps",
        "Coverage",
        "Input omissions",
    ]:
        assert "## " + title + "\n" in sheet
    human = html.unescape(sheet)
    for value in [
        "247.5",
        "USD billions",
        "Annual spending",
        "2026-10-26",
        "third_party_forecast",
        "main:S107",
        "forecast-linear",
        "coefficient:baseline",
        "0.5",
        "assumed",
        "fixture-prior/v1",
        "Example agency",
        "government",
        "research_analyst",
        "analyst_inferred",
        statement,
        "filing-intention",
        "intention",
        "supply-shock",
        "spending-signpost",
        "forecast-revisions",
    ]:
        assert value in human
    assert wa.anchor_hash(pack) == original_hash
    assert (out / "world_anchor.json").read_bytes() == dump(pack)
    assert wa.actor_projection(pack, actor_ref="agency", at="2026-10-28T00:00:00Z", **args(f)) == actor_before
    assert statement not in dump(actor_before).decode()
    assert receipt["pack_hash"] == original_hash


def test_private_anchor_sheet_escapes_metadata_and_preserves_typed_omissions(tmp_path):
    f, pack, _ = anchor_sheet_fixture(tmp_path)
    # Rendering must read authenticated in-memory bytes, not this changed file.
    (f["root"] / "labels.json").write_text('{"entity":"untrusted ambient label"}')
    out = tmp_path / "sheet"
    out.mkdir()
    wa.emit_pack(out, pack, **args(f))
    sheet = (out / "world_anchor.md").read_text()
    assert "<script>" not in sheet and "![trap]" not in sheet
    assert "\n## injected" not in sheet
    assert "untrusted ambient label" not in sheet
    import html

    human = html.unescape(sheet)
    assert "missing_registry_class" in human
    assert "Unclassified actor" in sheet
    assert "missing-native-series" in human and "not_retained" in human
    assert "unknown" in sheet
    assert "no_candidate" in human
    assert "empty" not in sheet.lower() or "No " in sheet


def test_private_anchor_sheet_fresh_replay_is_byte_identical(tmp_path):
    f, pack, _ = anchor_sheet_fixture(tmp_path)
    out = tmp_path / "sheet"
    out.mkdir()
    receipt = wa.emit_pack(out, pack, **args(f))
    original = (out / "world_anchor.md").read_bytes()
    fresh_index = wa.index_snapshot(
        f["root"],
        f["manifest"],
        expected_manifest_hash=wa.anchor_hash(f["manifest"]),
        expected_scope=f["scope"],
        requirements=f["requirements"],
        policy=f["policy"],
    )
    manifest = f["sheet_receipts"].manifest
    fresh_receipts = wa.producer_receipts(
        f["root"] / "receipts", manifest, expected_manifest_hash=wa.anchor_hash(manifest), expected_scope=f["scope"]
    )
    fresh_index = wa.admit_reviewed_evidence(
        fresh_index,
        f["sheet_proposal"],
        f["sheet_review"],
        requirements=f["requirements"],
        policy=f["policy"],
        receipts=fresh_receipts,
    )
    replay = {"requirements": f["requirements"], "index": fresh_index, "policy": f["policy"]}
    assert (
        wa.read_pack(
            out,
            receipt,
            expected_receipt_hash=wa.anchor_hash(receipt),
            expected_pack_hash=wa.anchor_hash(pack),
            **replay,
        )
        == pack
    )
    assert wa.emit_pack(out, pack, **replay) == receipt
    assert (out / "world_anchor.md").read_bytes() == original


def qualitative_fixture(tmp_path, cardinality=None, numeric_conflict=False):
    page = (
        "The 2026 cybersecurity spending forecast is 247.5 billion USD. Another estimate is 239.8 billion USD. "
        "Agency A supports policy one. Agency A files quarterly. Agency B waits. The filing date is 2026-11-01."
    )
    f = make_fixture(tmp_path / "source", page=page)
    contract = f["requirements"]["contract"]
    origins = {}
    for name, actor_ref in [
        ("statements-a", "agency-a"),
        ("statements-b", "agency-b"),
        ("filing-date", None),
        ("missing", "agency-a"),
    ]:
        origin = "/terms/" + str(len(contract["terms"]))
        item = {
            **copy.deepcopy(contract["terms"][1]),
            "origin_pointer": origin,
            "kind": "event" if name == "filing-date" else "actor_statement",
            "identity": None,
            "actor_ref": actor_ref,
            "value_type": "text",
            "accepted_value_kinds": ["reported"],
            "required": False,
            "consumers": [
                consumer("oasis-legacy", "calendar" if name == "filing-date" else "actor_brief", name, "value")
            ],
        }
        if name in {"statements-a", "missing"} and cardinality is not None:
            item["cardinality"] = cardinality
        contract["terms"].append(item)
        origins[name] = origin
    raw = dump({"settlement": identity(2027), "terms": contract["terms"]})
    (f["root"] / "contract.json").write_bytes(raw)
    contract["authority_artifact_hash"] = digest(raw)
    next(a for a in f["manifest"]["artifacts"] if a["artifact_id"] == "contract").update(
        sha256=digest(raw), bytes=len(raw)
    )
    f["policy"]["consumer_rules"].extend(
        {**c, "adapter_version": "world-anchor-reflexive/v1", "template_versions": ["v1"]}
        for t in contract["terms"][2:]
        for c in t["consumers"]
    )
    f["requirements"] = wa.requirements_from_contract(contract, scope=f["scope"])
    f["index"] = wa.index_snapshot(
        f["root"],
        f["manifest"],
        expected_manifest_hash=wa.anchor_hash(f["manifest"]),
        expected_scope=f["scope"],
        requirements=f["requirements"],
        policy=f["policy"],
    )
    ids = {
        name: next(r["requirement_id"] for r in f["requirements"]["requirements"] if r["origin_pointer"] == origin)
        for name, origin in origins.items()
    }
    proposal, review = review_fixture(f)
    for number, (name, text, actor_ref) in enumerate(
        [
            ("statements-a", "Agency A supports policy one.", "agency-a"),
            ("statements-a", "Agency A files quarterly.", "agency-a"),
            ("statements-b", "Agency B waits.", "agency-b"),
            ("filing-date", "2026-11-01", None),
        ]
    ):
        row = copy.deepcopy(proposal["rows"][0])
        row.update(
            proposal_id="qual-" + str(number),
            requirement_ids=[ids[name]],
            identity=None,
            value={"kind": "text", "value": text},
            source_value={"kind": "text", "value": text},
            value_kind="reported",
            subject_actor_ref=actor_ref,
        )
        proposal["rows"].append(row)
        review["decisions"].append({**copy.deepcopy(review["decisions"][0]), "proposal_id": row["proposal_id"]})
    if numeric_conflict:
        row = copy.deepcopy(proposal["rows"][0])
        # Omitting the true numeric requirement nomination cannot hide a
        # conflicting qualified observation with that same numeric identity.
        row.update(
            proposal_id="other-numeric",
            requirement_ids=[ids["missing"]],
            value={"kind": "number", "value": "239.8"},
            source_value={"kind": "number", "value": "239.8"},
        )
        proposal["rows"].append(row)
        review["decisions"].append({**copy.deepcopy(review["decisions"][0]), "proposal_id": row["proposal_id"]})
    review["proposal_hash"] = wa.anchor_hash(proposal)
    receipts = receipt_fixture(f, proposal, review)
    f["index"] = wa.admit_reviewed_evidence(
        f["index"], proposal, review, requirements=f["requirements"], policy=f["policy"], receipts=receipts
    )
    pack = build_pack(f)
    for row in pack["proposal"]["rows"]:
        if row["requirement_id"] == ids["statements-a"]:
            choice = next(c for c in pack["candidates"]["rows"] if c["requirement_id"] == row["requirement_id"])
            row["candidate_ids"] = [c["candidate_id"] for c in choice["ranked"]]
    pack = wa.admit_bindings(
        f["requirements"],
        f["index"],
        pack["candidates"],
        pack["proposal"],
        policy=f["policy"],
        attempts=[],
        metering=pack["metering"],
    )
    return f, pack, ids


def test_qualitative_matching_uses_reviewed_requirement_associations(tmp_path):
    _, pack, ids = qualitative_fixture(tmp_path)
    bindings = {b["requirement_id"]: b for b in pack["bindings"]}
    assert bindings[ids["filing-date"]]["status"] == "bound"
    assert bindings[ids["statements-b"]]["status"] == "bound"
    assert bindings[ids["missing"]]["status"] == "gap"


def test_explicit_text_collection_keeps_distinct_sourced_members(tmp_path):
    f, pack, ids = qualitative_fixture(tmp_path, cardinality="many")
    binding = next(b for b in pack["bindings"] if b["requirement_id"] == ids["statements-a"])
    assert binding["status"] == "bound"
    assert len(binding["observation_ids"]) == 2
    values = {o["value"]["value"] for o in pack["observations"] if o["observation_id"] in binding["observation_ids"]}
    assert values == {"Agency A supports policy one.", "Agency A files quarterly."}
    assert next(b for b in pack["bindings"] if b["requirement_id"] == ids["missing"])["status"] == "gap"
    assert wa.validate_pack(pack, **args(f)) == pack


def test_scalar_text_and_numeric_conflicts_stay_strict(tmp_path):
    _, pack, ids = qualitative_fixture(tmp_path, numeric_conflict=True)
    bindings = {b["requirement_id"]: b for b in pack["bindings"]}
    assert bindings[ids["statements-a"]]["status"] == "conflict"
    baseline = next(r for r in pack["requirements"] if r["kind"] == "baseline")
    assert bindings[baseline["requirement_id"]]["status"] == "conflict"


@pytest.mark.parametrize("value_type", ["number", "range", "boolean"])
def test_collection_cardinality_cannot_weaken_scalar_types(tmp_path, value_type):
    f = make_fixture(tmp_path / "source")
    contract = f["requirements"]["contract"]
    contract["terms"][1].update(cardinality="many", value_type=value_type)
    with pytest.raises(wa.AnchorError, match="E_CONTRACT"):
        wa.requirements_from_contract(contract, scope=f["scope"])


def budget_receipts_fixture(f, counts=(0, 0, 0, 0), *, corrupt=None, limits=None, reserved_usd=0):
    root = f["root"] / "budget-receipts"
    root.mkdir(exist_ok=True)
    models, tokens, catalogs, followups = counts
    budget = {
        "schema": "anchor-budget-receipt/v1",
        "authorization_sha256": "a" * 64,
        "pipeline_id": f["scope"]["run_id"],
        "scope_id": "budget-scope",
        "session_id": "session-1",
        "generation": 1,
        "policy_sha256": "b" * 64,
        "source_sha256": "c" * 64,
        "routes_sha256": "d" * 64,
        "barrier_sha256": "e" * 64,
        "retained": {
            "model_attempts": models,
            "token_envelope_units": tokens,
            "catalog_attempts": catalogs,
            "followup_attempts": followups,
            "reserved_max_microusd": reserved_usd,
        },
        "limits": {
            "model_attempt_limit": 20,
            "token_envelope_limit": 150000,
            "catalog_attempt_limit": 8,
            "followup_attempt_limit": 12,
        },
    }
    if limits is not None:
        budget["limits"] = limits
    if corrupt == "pipeline":
        budget["pipeline_id"] = "foreign"
    summary = {
        "schema_version": "world-anchor-metering/v1",
        "anchor_budget_scope_id": "budget-scope",
        "physical_model_attempts": models,
        "reserved_tokens": tokens,
        "physical_catalog_attempts": catalogs,
        "physical_followup_attempts": followups,
        "budget_receipt_artifact_id": "stage-budget",
        "budget_receipt_hash": wa.anchor_hash(budget),
    }
    if corrupt == "counter":
        summary["physical_catalog_attempts"] += 1
    if corrupt == "hash":
        summary["budget_receipt_hash"] = "f" * 64
    files = []
    for aid, payload in [("stage-budget", budget), ("stage-metering", summary)]:
        if corrupt == "missing" and aid == "stage-budget":
            continue
        raw = dump(payload)
        path = aid + ".json"
        (root / path).write_bytes(raw)
        files.append(
            {"artifact_id": aid, "path": path, "sha256": digest(raw), "bytes": len(raw), "role": "metering_receipt"}
        )
    manifest = {
        "schema_version": "world-anchor-producer-receipts/v1",
        "scope": f["scope"],
        "policy_hash": wa.anchor_hash(f["policy"]),
        "files": files,
        "transport_artifact_ids": [],
    }
    handle = wa.producer_receipts(
        root, manifest, expected_manifest_hash=wa.anchor_hash(manifest), expected_scope=f["scope"]
    )
    meter = {
        key: summary[key]
        for key in (
            "anchor_budget_scope_id",
            "physical_model_attempts",
            "reserved_tokens",
            "physical_catalog_attempts",
            "physical_followup_attempts",
        )
    }
    meter.update(mode="metered", receipt_artifact_id="stage-metering", receipt_hash=wa.anchor_hash(summary))
    return handle, meter


@pytest.mark.parametrize("counts", [(0, 0, 0, 0), (0, 0, 2, 1), (3, 10000, 0, 0), (20, 150000, 8, 12)])
def test_accounting_attachment_without_semantic_reviews(tmp_path, counts):
    f = make_fixture(tmp_path / "source", with_contract=False)
    old_view = f["index"].snapshot()
    candidates = wa.candidates_for_requirements(f["requirements"], f["index"])
    handle, metering = budget_receipts_fixture(f, counts)
    f["index"] = wa.attach_producer_receipts(f["index"], receipts=[handle, handle])
    view = f["index"].snapshot()
    assert view["producer_manifest_hashes"] == [handle.manifest_hash]
    for key in ("evidence_hash", "observations", "evidence_proposals", "review_receipts", "inventory"):
        assert view[key] == old_view[key]
    assert wa.candidates_for_requirements(f["requirements"], f["index"]) == candidates
    proposal = {
        "schema_version": "world-anchor-proposal/v1",
        "requirements_hash": wa.anchor_hash(f["requirements"]),
        "input_hash": view["input_hash"],
        "candidate_hash": wa.anchor_hash(candidates),
        "rows": [],
    }
    pack = wa.admit_bindings(
        f["requirements"], f["index"], candidates, proposal, policy=f["policy"], attempts=[], metering=metering
    )
    assert pack["metering"]["mode"] == "metered"
    assert pack["metering"]["physical_followup_attempts"] == counts[3]
    out = tmp_path / "out"
    out.mkdir()
    receipt = wa.emit_pack(out, pack, **args(f))
    assert (
        wa.read_pack(
            out,
            receipt,
            expected_receipt_hash=wa.anchor_hash(receipt),
            expected_pack_hash=wa.anchor_hash(pack),
            **args(f),
        )
        == pack
    )
    with pytest.raises(wa.AnchorError, match="bound_scope_requires_metered"):
        build_pack(f)


@pytest.mark.parametrize("corrupt", ["pipeline", "counter", "hash", "missing"])
def test_accounting_attachment_rejects_invalid_budget_authority(tmp_path, corrupt):
    f = make_fixture(tmp_path / "source", with_contract=False)
    handle, _ = budget_receipts_fixture(f, corrupt=corrupt)
    with pytest.raises(wa.AnchorError):
        wa.attach_producer_receipts(f["index"], receipts=[handle])


def test_accounting_attachment_preserves_existing_semantic_candidate_hash(tmp_path):
    f = enrich(make_fixture(tmp_path / "source"))
    before = wa.candidates_for_requirements(f["requirements"], f["index"])
    handles_before = set(f["index"].snapshot()["producer_manifest_hashes"])
    handle, _ = budget_receipts_fixture(f)
    attached = wa.attach_producer_receipts(f["index"], receipts=[handle])
    assert wa.candidates_for_requirements(f["requirements"], attached) == before
    assert set(attached.snapshot()["producer_manifest_hashes"]) == handles_before | {handle.manifest_hash}
    assert attached.snapshot()["observations"] == f["index"].snapshot()["observations"]


def test_budget_attachment_honors_lower_immutable_caps(tmp_path):
    f = make_fixture(tmp_path / "source", with_contract=False)
    limits = {
        "model_attempt_limit": 2,
        "token_envelope_limit": 5000,
        "catalog_attempt_limit": 1,
        "followup_attempt_limit": 2,
    }
    handle, meter = budget_receipts_fixture(f, (1, 3000, 1, 2), limits=limits)
    f["index"] = wa.attach_producer_receipts(f["index"], receipts=[handle])
    candidates = wa.candidates_for_requirements(f["requirements"], f["index"])
    proposal = {
        "schema_version": "world-anchor-proposal/v1",
        "requirements_hash": wa.anchor_hash(f["requirements"]),
        "input_hash": f["index"].snapshot()["input_hash"],
        "candidate_hash": wa.anchor_hash(candidates),
        "rows": [],
    }
    pack = wa.admit_bindings(
        f["requirements"], f["index"], candidates, proposal, policy=f["policy"], attempts=[], metering=meter
    )
    assert pack["metering"] == meter


@pytest.mark.parametrize("limit,retained", [(21, 0), (2, 3)])
def test_budget_attachment_rejects_limits_or_retention_above_bounds(tmp_path, limit, retained):
    f = make_fixture(tmp_path / "source", with_contract=False)
    limits = {
        "model_attempt_limit": limit,
        "token_envelope_limit": 5000,
        "catalog_attempt_limit": 1,
        "followup_attempt_limit": 2,
    }
    handle, _ = budget_receipts_fixture(f, (retained, 0, 0, 0), limits=limits)
    with pytest.raises(wa.AnchorError):
        wa.attach_producer_receipts(f["index"], receipts=[handle])


def test_research_inventory_collects_quotes_without_settlement_or_execution(tmp_path):
    f = make_fixture(tmp_path / "source", page="Agency A states its objective. Agency A describes its constraint.")
    contract = f["requirements"]["contract"]
    original = copy.deepcopy(contract["terms"][1])
    terms = []
    for i, kind in enumerate(("actor_objective", "actor_constraint", "calendar_event", "indicator", "reference_class")):
        terms.append(
            {
                **copy.deepcopy(original),
                "origin_pointer": "/terms/" + str(i),
                "kind": kind,
                "identity": None,
                "actor_ref": "agency-a" if kind.startswith("actor_") else None,
                "value_type": "text",
                "cardinality": "many",
                "required": False,
                "accepted_value_kinds": ["reported"],
                "consumers": [consumer("oasis-legacy", "research_note", kind, kind)],
            }
        )
    contract.update(authority_kind="research_inventory", settlement=None, terms=terms)
    raw = dump({"settlement": None, "terms": terms})
    (f["root"] / "contract.json").write_bytes(raw)
    contract["authority_artifact_hash"] = digest(raw)
    next(a for a in f["manifest"]["artifacts"] if a["artifact_id"] == "contract").update(
        sha256=digest(raw), bytes=len(raw)
    )
    f["policy"]["consumer_rules"] = [
        {**c, "adapter_version": "research-notes/v1", "template_versions": []} for t in terms for c in t["consumers"]
    ]
    f["requirements"] = wa.requirements_from_contract(contract, scope=f["scope"])
    assert any(g["code"] == "missing_contract" for g in f["requirements"]["gaps"])
    f["index"] = wa.index_snapshot(
        f["root"],
        f["manifest"],
        expected_manifest_hash=wa.anchor_hash(f["manifest"]),
        expected_scope=f["scope"],
        requirements=f["requirements"],
        policy=f["policy"],
    )
    proposal, review = review_fixture(f)
    for i, (kind, sentence) in enumerate(
        (
            ("actor_objective", "Agency A states its objective."),
            ("actor_constraint", "Agency A describes its constraint."),
        )
    ):
        row = copy.deepcopy(proposal["rows"][0])
        req = next(r for r in f["requirements"]["requirements"] if r["kind"] == kind)
        row.update(
            proposal_id="note-" + str(i),
            requirement_ids=[req["requirement_id"]],
            identity=None,
            value={"kind": "text", "value": sentence},
            source_value={"kind": "text", "value": sentence},
            value_kind="reported",
            subject_actor_ref="agency-a",
        )
        if i == 0:
            proposal["rows"] = [row]
            review["decisions"][0]["proposal_id"] = row["proposal_id"]
        else:
            proposal["rows"].append(row)
            review["decisions"].append({**copy.deepcopy(review["decisions"][0]), "proposal_id": row["proposal_id"]})
    review["proposal_hash"] = wa.anchor_hash(proposal)
    receipts = receipt_fixture(f, proposal, review)
    f["index"] = wa.admit_reviewed_evidence(
        f["index"], proposal, review, requirements=f["requirements"], policy=f["policy"], receipts=receipts
    )
    pack = build_pack(f)
    assert len(pack["research_items"]) == 2
    assert {r["kind"] for r in pack["research_items"]} == {"actor_objective", "actor_constraint"}
    assert all(r["executable"] is False and r["quote"] in f["page"] for r in pack["research_items"])
    assert all(r["status"] == "blocked" for r in pack["readiness"])
    assert any(b["status"] == "gap" for b in pack["bindings"])
    assert pack["variables"] == []
    assert wa.actor_projection(pack, actor_ref="agency-a", at="2026-10-28T00:00:00Z", **args(f))["items"] == []
    for engine in wa.ENGINES:
        with pytest.raises(wa.AnchorError, match="E_NOT_READY"):
            wa.engine_projection(pack, engine=engine, **args(f))


@pytest.mark.parametrize("bad", ["numeric", "executable_role", "target", "mechanism"])
def test_research_inventory_cannot_create_executable_authority(tmp_path, bad):
    f = make_fixture(tmp_path / "source")
    contract = f["requirements"]["contract"]
    term = copy.deepcopy(contract["terms"][1])
    term.update(
        kind="research_note",
        identity=None,
        value_type="text",
        cardinality="many",
        required=False,
        consumers=[consumer("oasis-legacy", "research_note", "notes", "notes")],
    )
    contract.update(authority_kind="research_inventory", settlement=None, terms=[term])
    if bad == "numeric":
        term.update(value_type="number", identity=identity(), cardinality="one")
    if bad == "executable_role":
        term["consumers"][0]["role"] = "initial_state"
    if bad == "target":
        term["kind"] = "target_definition"
    if bad == "mechanism":
        contract["identities"] = [
            {
                "identity_id": "bad",
                "lhs_node_id": "n",
                "rhs_mechanism_id": "m",
                "absolute_tolerance": "0",
                "relative_tolerance": "0",
                "scale_unit": unit(),
                "basis_requirement_origin": term["origin_pointer"],
            }
        ]
    with pytest.raises(wa.AnchorError, match="E_CONTRACT"):
        wa.requirements_from_contract(contract, scope=f["scope"])


def note_projection_fixture(tmp_path, engine, *, dependency=False, descriptors=False, executable_dependency=False):
    text = "Agency A states its research-only intention."
    f = make_fixture(tmp_path / "source", page=(
        "The 2026 cybersecurity spending forecast is 247.5 billion USD. " + text
    ))
    contract = f["requirements"]["contract"]
    baseline = contract["terms"][1]
    other_engine = next(e for e in wa.ENGINES if e != engine)
    note = {
        **copy.deepcopy(baseline), "origin_pointer": "/terms/2",
        "kind": "actor_plan", "identity": None, "value_type": "text",
        "cardinality": "many", "required": False, "accepted_value_kinds": ["reported"],
        "consumers": [consumer(other_engine if dependency else engine, "research_note", "note", "intention")],
        "dependency_origins": ["/terms/3"],
    }
    hidden = {
        **copy.deepcopy(baseline), "origin_pointer": "/terms/3",
        "kind": "baseline", "consumers": [consumer(other_engine, "diagnostic", "hidden", "value")],
    }
    if dependency:
        baseline["dependency_origins"] = [note["origin_pointer"]]
    if executable_dependency:
        baseline["dependency_origins"] = [hidden["origin_pointer"]]
    contract["terms"].extend([note, hidden])
    if descriptors:
        base, research = baseline["origin_pointer"], note["origin_pointer"]
        mechanism = {
            "mechanism_id": "valid", "template": "linear", "template_version": "v1",
            "input_node_ids": ["baseline"], "output_node_id": "output-valid",
            "parameters": [{"name": "intercept", "requirement_origin": base, "unit": unit()}],
            "lag_requirement_origin": None, "applicability_requirement_origins": [],
            "consumers": [consumer(engine, "mechanism", "valid", "output")],
        }
        contract["mechanisms"] = [mechanism]
        for fault in ("parameter", "lag", "applicability", "role"):
            row = copy.deepcopy(mechanism)
            row.update(mechanism_id=fault, output_node_id="output-" + fault)
            if fault == "parameter":
                row["parameters"][0]["requirement_origin"] = research
            elif fault == "lag":
                row["lag_requirement_origin"] = research
            elif fault == "applicability":
                row["applicability_requirement_origins"] = [research]
            else:
                row["consumers"][0]["role"] = "research_note"
            contract["mechanisms"].append(row)
        contract["identities"] = [
            {"identity_id": name, "lhs_node_id": "baseline", "rhs_mechanism_id": rhs,
             "absolute_tolerance": "0", "relative_tolerance": "0", "scale_unit": unit(),
             "basis_requirement_origin": origin}
            for name, rhs, origin in [("valid", "valid", base), ("note-basis", "valid", research),
                                      ("note-mechanism", "parameter", base)]
        ]
        event = {"event_id": "valid", "requirement_origin": base, "classification": "scheduled",
                 "time_requirement_origin": base, "effect_requirement_origins": [base]}
        hazard = {"hazard_id": "valid", "trigger": None, "likelihood_requirement_origin": base,
                  "effect_requirement_origins": [base], "recurrence_requirement_origin": base,
                  "consumers": [consumer(engine, "calendar", "baseline", "add")]}
        for key, prototype, fields in [
            ("calendar", event, ("requirement_origin", "time_requirement_origin", "effect_requirement_origins")),
            ("hazards", hazard, ("likelihood_requirement_origin", "effect_requirement_origins", "recurrence_requirement_origin")),
        ]:
            contract[key] = [prototype]
            id_key = "event_id" if key == "calendar" else "hazard_id"
            for field in fields:
                row = copy.deepcopy(prototype)
                row[id_key] = field
                row[field] = [research] if type(row[field]) is list else research
                contract[key].append(row)
        contract["hazards"].append({**copy.deepcopy(hazard), "hazard_id": "note-role",
                                  "consumers": [consumer(engine, "research_note", "hazard", "note")]})
        contract["indicators"] = [
            {"indicator_id": name, "node_id": "baseline", "requirement_origin": origin,
             "consumer": consumer(engine, role, "baseline", "signpost"), "trigger": None}
            for name, origin, role in [("valid", base, "observation"), ("note-basis", research, "observation"),
                                       ("note-role", base, "research_note")]
        ]
    raw = dump({"settlement": identity(2027), "terms": contract["terms"],
                **{k: contract[k] for k in wa.SPEC_FIELDS}})
    (f["root"] / "contract.json").write_bytes(raw)
    contract["authority_artifact_hash"] = digest(raw)
    next(a for a in f["manifest"]["artifacts"] if a["artifact_id"] == "contract").update(
        sha256=digest(raw), bytes=len(raw)
    )
    f["policy"]["consumer_rules"].extend(
        {**c, "adapter_version": "offline/v1", "template_versions": ["v1"]}
        for row in [*contract["terms"][2:], *contract["mechanisms"]] for c in row["consumers"]
    )
    f["requirements"] = wa.requirements_from_contract(contract, scope=f["scope"])
    f["index"] = wa.index_snapshot(
        f["root"], f["manifest"], expected_manifest_hash=wa.anchor_hash(f["manifest"]),
        expected_scope=f["scope"], requirements=f["requirements"], policy=f["policy"]
    )
    proposal, review = review_fixture(f)
    row = copy.deepcopy(proposal["rows"][0])
    ref = copy.deepcopy(proposal["references"][0])
    start = f["page"].encode().index(text.encode())
    ref["locator"] = {"kind": "text_span", "start_byte": start, "end_byte": start + len(text.encode()), "quote": text}
    ref["ref_id"] = wa._id("ref", ref["source_key"], ref["content_hash"], ref["locator"])
    rid = next(r["requirement_id"] for r in f["requirements"]["requirements"] if r["kind"] == "actor_plan")
    row.update(proposal_id="note", requirement_ids=[rid], identity=None, value={"kind": "text", "value": text},
               source_value={"kind": "text", "value": text}, value_kind="reported", ref_ids=[ref["ref_id"]])
    row["support"] = [{**s, "ref_id": ref["ref_id"], "selector": ref["locator"], "expected": text} for s in row["support"]]
    row["visible_at"]["basis_ref_ids"] = [ref["ref_id"]]
    proposal["references"].append(ref)
    proposal["rows"].append(row)
    decision = copy.deepcopy(review["decisions"][0])
    decision["proposal_id"] = "note"
    for check in decision["checks"]:
        check["ref_ids"] = [ref["ref_id"]]
    review["decisions"].append(decision)
    review["proposal_hash"] = wa.anchor_hash(proposal)
    receipts = receipt_fixture(f, proposal, review)
    f["index"] = wa.admit_reviewed_evidence(
        f["index"], proposal, review, requirements=f["requirements"], policy=f["policy"], receipts=receipts
    )
    return f, build_pack(f)


@pytest.mark.parametrize("engine", wa.ENGINES)
@pytest.mark.parametrize("dependency", [False, True])
def test_engine_projection_excludes_research_notes_and_their_dependencies(tmp_path, engine, dependency):
    f, pack = note_projection_fixture(tmp_path, engine, dependency=dependency)
    original = copy.deepcopy(pack)
    projection = wa.engine_projection(pack, engine=engine, **args(f))
    selected = {b["requirement_id"] for b in projection["bindings"]}
    origins = {r["origin_pointer"] for r in pack["requirements"] if r["requirement_id"] in selected}
    assert origins == {"/terms/0", "/terms/1"}
    assert len(pack["research_items"]) == 1
    note = pack["research_items"][0]
    assert note["executable"] is False
    assert note["observation_id"] not in {o["observation_id"] for o in projection["observations"]}
    assert not set(note["ref_ids"]) & {r["ref_id"] for r in projection["references"]}
    assert projection["variables"][0]["node_id"] == "baseline"
    assert projection["observations"][0]["value"] == {"kind": "number", "value": "247.5"}
    assert pack == original


@pytest.mark.parametrize("engine", wa.ENGINES)
def test_engine_projection_preserves_independently_required_executable_dependency(tmp_path, engine):
    f, pack = note_projection_fixture(tmp_path, engine, executable_dependency=True)
    projection = wa.engine_projection(pack, engine=engine, **args(f))
    selected = {b["requirement_id"] for b in projection["bindings"]}
    assert {r["origin_pointer"] for r in pack["requirements"] if r["requirement_id"] in selected} == {
        "/terms/0", "/terms/1", "/terms/3"
    }
    assert pack["research_items"][0]["requirement_id"] not in selected


@pytest.mark.parametrize("engine", wa.ENGINES)
def test_engine_projection_excludes_descriptors_with_research_note_bases(tmp_path, engine):
    f, pack = note_projection_fixture(tmp_path, engine, descriptors=True)
    projection = wa.engine_projection(pack, engine=engine, **args(f))
    for section, key in [("mechanisms", "mechanism_id"), ("identities", "identity_id"),
                         ("calendar", "event_id"), ("hazards", "hazard_id"), ("indicators", "indicator_id")]:
        assert {r[key] for r in projection[section]} == {"valid"}, section
    assert len(pack["research_items"]) == 1


def target_sid_fixture(tmp_path, raw_sid=107, valid_crosswalk=True):
    f = make_fixture(tmp_path / "source", with_contract=False)
    f["scope"]["authority"] = "target-first-v1"
    f["requirements"] = wa.requirements_from_contract(None, scope=f["scope"])
    manifest = f["manifest"]
    manifest["scope"] = f["scope"]
    track = manifest["tracks"][0]
    track["adapter"] = "target-case/v1"
    kiq = json.loads((f["root"] / "v3/kiq/K1.json").read_bytes())
    kiq["facts"][0]["sids"] = [raw_sid]
    raw = dump(kiq)
    (f["root"] / "v3/kiq/K1.json").write_bytes(raw)
    next(a for a in manifest["artifacts"] if a["artifact_id"] == "kiq").update(sha256=digest(raw), bytes=len(raw))
    case = {"schemaVersion": "forecast-case/v1", "claims": [{"claimId": "case-claim", "sourceIds": ["S107"]}]}
    join = {"sourceId": "S107", "url": "https://example.test/report", "content_sha256": digest(f["page"].encode())}
    for aid, value in [("case", case), ("join", [join])]:
        raw = dump(value)
        (f["root"] / (aid + ".json")).write_bytes(raw)
        manifest["artifacts"].append(
            {
                "artifact_id": aid,
                "track_id": "main",
                "path": aid + ".json",
                "sha256": digest(raw),
                "bytes": len(raw),
                "encoding": "utf8_json",
                "role": "target_case" if aid == "case" else "target_checkpoint",
            }
        )
    track["case_artifact_id"] = "case"
    source_key = wa._id("source", f["scope"], "main", "ledger", "/0")
    if valid_crosswalk:
        manifest["crosswalk"] = [
            {
                "crosswalk_id": "case-source",
                "source_key": source_key,
                "namespace": "target_source_id",
                "external_id": "S107",
                "track_id": "main",
                "artifact_id": "join",
                "pointer": "/0",
                "proof_ref_ids": [],
            }
        ]
    f["index"] = wa.index_snapshot(
        f["root"],
        manifest,
        expected_manifest_hash=wa.anchor_hash(manifest),
        expected_scope=f["scope"],
        requirements=f["requirements"],
        policy=f["policy"],
    )
    return f


def test_target_track_kiq_and_case_use_separate_sid_namespaces(tmp_path):
    f = target_sid_fixture(tmp_path)
    rows = {r["origin"]: r for r in f["index"].snapshot()["inventory"]}
    assert rows["kiq_fact"]["source_keys"] and rows["case_claim"]["source_keys"]
    assert json.loads(f["index"].artifact_bytes("kiq"))["facts"][0]["sids"] == [107]
    assert json.loads(f["index"].artifact_bytes("case"))["claims"][0]["sourceIds"] == ["S107"]


def test_missing_target_crosswalk_does_not_block_raw_kiq_join(tmp_path):
    f = target_sid_fixture(tmp_path, valid_crosswalk=False)
    rows = {r["origin"]: r for r in f["index"].snapshot()["inventory"]}
    assert rows["kiq_fact"]["source_keys"]
    assert rows["case_claim"]["source_keys"] == []


@pytest.mark.parametrize("raw_sid", [True, False, 0, -1, 107.0, "107", "S107"])
def test_non_integer_kiq_ids_cannot_borrow_target_crosswalk(tmp_path, raw_sid):
    f = target_sid_fixture(tmp_path, raw_sid=raw_sid)
    rows = {r["origin"]: r for r in f["index"].snapshot()["inventory"]}
    assert rows["kiq_fact"]["source_keys"] == []
    assert rows["kiq_fact"]["reason_code"] == "unsupported_shape"
    assert rows["case_claim"]["source_keys"]


def test_selected_meter_cannot_understate_attached_retained_maximum(tmp_path):
    f = make_fixture(tmp_path / "source", with_contract=False)
    old_handle, old_meter = budget_receipts_fixture(f, (1, 1000, 0, 0))
    later = {**f, "root": tmp_path / "later"}
    later["root"].mkdir()
    new_handle, new_meter = budget_receipts_fixture(later, (3, 3000, 2, 1))
    f["index"] = wa.attach_producer_receipts(f["index"], receipts=[old_handle, new_handle])
    candidates = wa.candidates_for_requirements(f["requirements"], f["index"])
    proposal = {
        "schema_version": "world-anchor-proposal/v1",
        "requirements_hash": wa.anchor_hash(f["requirements"]),
        "input_hash": f["index"].snapshot()["input_hash"],
        "candidate_hash": wa.anchor_hash(candidates),
        "rows": [],
    }
    with pytest.raises(wa.AnchorError, match="E_BUDGET_RECEIPT"):
        wa.admit_bindings(
            f["requirements"], f["index"], candidates, proposal, policy=f["policy"], attempts=[], metering=old_meter
        )
    assert (
        wa.admit_bindings(
            f["requirements"], f["index"], candidates, proposal, policy=f["policy"], attempts=[], metering=new_meter
        )["metering"]
        == new_meter
    )


def test_attached_budget_caps_cannot_change_and_counters_cannot_cross(tmp_path):
    f = make_fixture(tmp_path / "source", with_contract=False)
    first, _ = budget_receipts_fixture(f, (1, 3000, 0, 0))
    later = {**f, "root": tmp_path / "later"}
    later["root"].mkdir()
    crossing, _ = budget_receipts_fixture(later, (2, 1000, 0, 0))
    with pytest.raises(wa.AnchorError, match="E_BUDGET_RECEIPT"):
        wa.attach_producer_receipts(f["index"], receipts=[first, crossing])
    limits = {
        "model_attempt_limit": 2,
        "token_envelope_limit": 5000,
        "catalog_attempt_limit": 1,
        "followup_attempt_limit": 2,
    }
    changed, _ = budget_receipts_fixture(later, (1, 3000, 0, 0), limits=limits)
    with pytest.raises(wa.AnchorError, match="E_BUDGET_RECEIPT"):
        wa.attach_producer_receipts(f["index"], receipts=[first, changed])


def test_official_only_requirement_cannot_bind_page_evidence(tmp_path):
    f = make_fixture(tmp_path / "source")
    contract = f["requirements"]["contract"]
    contract["terms"][1]["accepted_evidence"] = ["official_row"]
    raw = dump({"settlement": identity(2027), "terms": contract["terms"]})
    (f["root"] / "contract.json").write_bytes(raw)
    contract["authority_artifact_hash"] = digest(raw)
    next(a for a in f["manifest"]["artifacts"] if a["artifact_id"] == "contract").update(
        sha256=digest(raw), bytes=len(raw)
    )
    f["requirements"] = wa.requirements_from_contract(contract, scope=f["scope"])
    f["index"] = wa.index_snapshot(
        f["root"],
        f["manifest"],
        expected_manifest_hash=wa.anchor_hash(f["manifest"]),
        expected_scope=f["scope"],
        requirements=f["requirements"],
        policy=f["policy"],
    )
    f = enrich(f)
    pack = build_pack(f)
    baseline = next(r for r in pack["requirements"] if r["kind"] == "baseline")
    assert next(b for b in pack["bindings"] if b["requirement_id"] == baseline["requirement_id"])["status"] == "gap"
    assert any(g["code"] == "evidence_class_not_allowed" for g in pack["gaps"])


def test_prior_requires_retained_basis_and_required_value_type(tmp_path):
    f, _, _ = anchor_sheet_fixture(tmp_path)
    prior = f["policy"]["prior_rules"][0]
    prior.update(artifact_id="unretained-prior", artifact_hash="f" * 64, pointer="/does-not-exist")
    f["index"] = wa.index_snapshot(
        f["root"],
        f["manifest"],
        expected_manifest_hash=wa.anchor_hash(f["manifest"]),
        expected_scope=f["scope"],
        requirements=f["requirements"],
        policy=f["policy"],
    )
    pack = build_pack(f)
    rid = next(r["requirement_id"] for r in f["requirements"]["requirements"] if r["kind"] == "mechanism_parameter")
    for row in pack["proposal"]["rows"]:
        if row["requirement_id"] == rid:
            row.update(decision="assume", candidate_ids=[], prior_policy_id=prior["policy_id"])
    with pytest.raises(wa.AnchorError):
        wa.admit_bindings(
            f["requirements"],
            f["index"],
            pack["candidates"],
            pack["proposal"],
            policy=f["policy"],
            attempts=[],
            metering=pack["metering"],
        )


def test_selected_meter_covers_retained_currency_maximum_too(tmp_path):
    f = make_fixture(tmp_path / "source", with_contract=False)
    old, old_meter = budget_receipts_fixture(f, (1, 1000, 0, 0), reserved_usd=0)
    later = {**f, "root": tmp_path / "later"}
    later["root"].mkdir()
    new, new_meter = budget_receipts_fixture(later, (1, 1000, 0, 0), reserved_usd=100)
    f["index"] = wa.attach_producer_receipts(f["index"], receipts=[old, new])
    candidates = wa.candidates_for_requirements(f["requirements"], f["index"])
    proposal = {
        "schema_version": "world-anchor-proposal/v1",
        "requirements_hash": wa.anchor_hash(f["requirements"]),
        "input_hash": f["index"].snapshot()["input_hash"],
        "candidate_hash": wa.anchor_hash(candidates),
        "rows": [],
    }
    with pytest.raises(wa.AnchorError, match="stale_metering"):
        wa.admit_bindings(
            f["requirements"], f["index"], candidates, proposal, policy=f["policy"], attempts=[], metering=old_meter
        )
    assert (
        wa.admit_bindings(
            f["requirements"], f["index"], candidates, proposal, policy=f["policy"], attempts=[], metering=new_meter
        )["metering"]
        == new_meter
    )


@pytest.mark.parametrize("bad", ["hash", "pointer", "projection", "library", "type", "epistemic"])
def test_prior_basis_and_type_controls(tmp_path, bad):
    f, _, _ = anchor_sheet_fixture(tmp_path)
    prior = f["policy"]["prior_rules"][0]
    if bad == "hash":
        prior["artifact_hash"] = "f" * 64
    elif bad == "pointer":
        prior["pointer"] = "/missing"
    elif bad == "projection":
        prior["value"] = {"kind": "number", "value": "0.75"}
    elif bad == "library":
        prior["library_version"] = "unretained/v2"
    elif bad == "type":
        prior["value"] = {"kind": "text", "value": "not a coefficient"}
        raw = dump({"value": prior["value"], "library_version": prior["library_version"]})
        (f["root"] / "prior.json").write_bytes(raw)
        prior["artifact_hash"] = digest(raw)
        next(a for a in f["manifest"]["artifacts"] if a["artifact_id"] == "prior").update(
            sha256=digest(raw), bytes=len(raw)
        )
    else:
        contract = f["requirements"]["contract"]
        next(t for t in contract["terms"] if t["kind"] == "mechanism_parameter")["accepted_value_kinds"] = ["reported"]
        raw = dump(
            {
                "settlement": identity(2027),
                "terms": contract["terms"],
                "aliases": contract["aliases"],
                **{k: contract[k] for k in wa.SPEC_FIELDS},
            }
        )
        (f["root"] / "contract.json").write_bytes(raw)
        contract["authority_artifact_hash"] = digest(raw)
        next(a for a in f["manifest"]["artifacts"] if a["artifact_id"] == "contract").update(
            sha256=digest(raw), bytes=len(raw)
        )
        f["requirements"] = wa.requirements_from_contract(contract, scope=f["scope"])
    f["index"] = wa.index_snapshot(
        f["root"],
        f["manifest"],
        expected_manifest_hash=wa.anchor_hash(f["manifest"]),
        expected_scope=f["scope"],
        requirements=f["requirements"],
        policy=f["policy"],
    )
    pack = build_pack(f)
    rid = next(r["requirement_id"] for r in f["requirements"]["requirements"] if r["kind"] == "mechanism_parameter")
    for row in pack["proposal"]["rows"]:
        if row["requirement_id"] == rid:
            row.update(decision="assume", candidate_ids=[], prior_policy_id=prior["policy_id"])

    def admit():
        return wa.admit_bindings(
            f["requirements"],
            f["index"],
            pack["candidates"],
            pack["proposal"],
            policy=f["policy"],
            attempts=[],
            metering=pack["metering"],
        )

    if bad in {"type", "epistemic"}:
        binding = next(b for b in admit()["bindings"] if b["requirement_id"] == rid)
        assert binding["status"] == "gap" and binding["assumption"] is None
    else:
        with pytest.raises(wa.AnchorError):
            admit()


@pytest.mark.parametrize(
    "metadata,expected",
    [
        ({}, "primary"),
        ({"source_metadata_status": "conflict"}, "unknown"),
        ({"source_metadata_status": "unknown"}, "unknown"),
        ({"source_metadata_status": "consistent", "source_metadata_overflow": True}, "unknown"),
        ({"evidence_tier": "unknown"}, "unknown"),
        ({"evidence_tier": "secondary"}, "secondary"),
    ],
)
def test_source_metadata_uncertainty_cannot_regain_legacy_primary(tmp_path, metadata, expected):
    f = make_fixture(tmp_path / "source", with_contract=False)
    ledger = json.loads((f["root"] / "v3/sources_ledger.json").read_bytes())
    ledger[0].update(tier="primary", **metadata)
    raw = dump(ledger)
    (f["root"] / "v3/sources_ledger.json").write_bytes(raw)
    next(a for a in f["manifest"]["artifacts"] if a["artifact_id"] == "ledger").update(
        sha256=digest(raw), bytes=len(raw)
    )
    index = wa.index_snapshot(
        f["root"],
        f["manifest"],
        expected_manifest_hash=wa.anchor_hash(f["manifest"]),
        expected_scope=f["scope"],
        requirements=f["requirements"],
        policy=f["policy"],
    )
    assert index.snapshot()["sources"][0]["tier"] == expected
    assert index.artifact_bytes("ledger") == raw


def test_human_sheet_keeps_every_selected_qualitative_member(tmp_path):
    import html

    f, pack, _ = qualitative_fixture(tmp_path, cardinality="many")
    out = tmp_path / "out"
    out.mkdir()
    wa.emit_pack(out, pack, **args(f))
    sheet = html.unescape((out / "world_anchor.md").read_text())
    actor_section = sheet.split("## Actor items\n", 1)[1].split("\n## Calendar", 1)[0]
    assert "Agency A supports policy one." in actor_section
    assert "Agency A files quarterly." in actor_section
    assert "collection; 2 selected" in actor_section
