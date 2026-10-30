"""Publish/reopen an immutable World Anchor generation without application imports."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import stat

if __package__:
    from . import world_anchor as wa
else:
    import world_anchor as wa

MANIFEST = "world_anchor_manifest.json"
INPUTS = "world_anchor_inputs.json"
CONTRACT = "world_anchor_contract.json"
POLICY = "world_anchor_policy.json"
_CONTROL = frozenset({INPUTS, CONTRACT, POLICY})
_LIMIT = 8 * 1024 * 1024


def _fail(path="publication"):
    raise wa.AnchorError("E_PUBLICATION", path)


def _canonical(value):
    wa.anchor_hash(value)
    return json.dumps(value, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def _parts(path):
    if (not isinstance(path, str) or not path or len(path) > 512
            or "\\" in path or "\x00" in path or ":" in path
            or any(p in {"", ".", ".."} for p in path.split("/"))):
        _fail("path")
    return path.split("/")


def read_bytes(root, path, *, limit=_LIMIT):
    parts = _parts(path)
    fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for part in parts[:-1]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = child
        child = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
        try:
            info = os.fstat(child)
            if not stat.S_ISREG(info.st_mode) or info.st_size > limit:
                _fail("file")
            chunks, count = [], 0
            while chunk := os.read(child, min(65536, limit + 1 - count)):
                chunks.append(chunk)
                count += len(chunk)
                if count > limit:
                    _fail("size")
            return b"".join(chunks)
        finally:
            os.close(child)
    finally:
        os.close(fd)


def decode_json(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                _fail("duplicate_key")
            result[key] = value
        return result

    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=pairs,
                           parse_constant=lambda _: _fail("nonfinite"))
        wa.anchor_hash(value)
        return value
    except (UnicodeError, ValueError, OverflowError, RecursionError) as exc:
        if isinstance(exc, wa.AnchorError):
            raise
        raise wa.AnchorError("E_SCHEMA", "json") from None


def write_once(root, path, data):
    """Create exact bytes or accept identical bytes; never replace a generation."""
    parts = _parts(path)
    fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    temp = None
    try:
        for part in parts[:-1]:
            try:
                os.mkdir(part, 0o700, dir_fd=fd)
            except FileExistsError:
                pass
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = child
        try:
            if read_bytes(root, path, limit=max(_LIMIT, len(data))) != data:
                raise wa.AnchorError("E_IMMUTABLE", path)
            return
        except FileNotFoundError:
            pass
        temp = ".anchor-publish-" + os.urandom(12).hex()
        out = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=fd)
        with os.fdopen(out, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temp, parts[-1], src_dir_fd=fd, dst_dir_fd=fd, follow_symlinks=False)
        except FileExistsError:
            if read_bytes(root, path, limit=max(_LIMIT, len(data))) != data:
                raise wa.AnchorError("E_IMMUTABLE", path) from None
        os.fsync(fd)
    finally:
        if temp is not None:
            os.unlink(temp, dir_fd=fd)
        os.close(fd)


def publish_completion(directory, pack, *, requirements, index, policy, receipts=()):
    """The producer supplies authenticated handles; the completion manifest is last."""
    directory = Path(directory)
    wa.validate_pack(pack, requirements=requirements, index=index, policy=policy)
    snapshot = index.snapshot()
    bundles = {}
    for bundle in receipts:
        if type(bundle) is not wa.ProducerReceipts or bundle.manifest_hash in bundles:
            _fail("producer_receipts")
        bundles[bundle.manifest_hash] = bundle
    if set(bundles) != set(pack["producer_manifest_hashes"]):
        _fail("producer_inventory")
    directory.mkdir(parents=True, exist_ok=True)
    for item in snapshot["manifest"]["artifacts"]:
        data = index.artifact_bytes(item["artifact_id"])
        write_once(directory, "world_anchor_inputs/" + item["path"], data)
    producer_manifests = []
    for digest, bundle in sorted(bundles.items()):
        manifest = bundle.manifest
        for item in manifest["files"]:
            write_once(directory, "world_anchor_producers/" + digest + "/" + item["path"],
                       bundle.artifact_bytes(item["artifact_id"]))
        producer_manifests.append({"manifest_hash": digest, "manifest": manifest})
    files = []
    for name, value in sorted(((INPUTS, snapshot["manifest"]),
                                (CONTRACT, requirements["contract"]), (POLICY, policy))):
        raw = _canonical(value)
        write_once(directory, name, raw)
        files.append({"path": name, "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)})
    emitted = wa.emit_pack(directory, pack, requirements=requirements, index=index, policy=policy)
    manifest = {"schema_version": "world-anchor-completion/v1", "scope": pack["scope"],
                "pack_hash": wa.anchor_hash(pack), "input_hash": pack["input_hash"],
                "contract_hash": pack["contract_hash"], "policy_hash": wa.anchor_hash(policy),
                "requirements_hash": wa.anchor_hash(requirements), "emission_receipt": emitted,
                "control_files": files, "producer_manifests": producer_manifests}
    raw = _canonical(manifest)
    write_once(directory, MANIFEST, raw)
    digest = hashlib.sha256(raw).hexdigest()
    # Exercise the persisted reconstruction before returning a completion pin.
    load_completion(directory, expected_manifest_sha256=digest, expected_scope=pack["scope"])
    return {"manifest": manifest, "manifest_sha256": digest}


def load_completion(directory, *, expected_manifest_sha256, expected_scope=None):
    """Reconstruct source and independent-review authority without any new calls."""
    directory = Path(directory)
    raw = read_bytes(directory, MANIFEST)
    if hashlib.sha256(raw).hexdigest() != expected_manifest_sha256:
        raise wa.AnchorError("E_HASH", "completion_manifest")
    manifest = decode_json(raw)
    keys = {"schema_version", "scope", "pack_hash", "input_hash", "contract_hash", "policy_hash",
            "requirements_hash", "emission_receipt", "control_files", "producer_manifests"}
    if (type(manifest) is not dict or set(manifest) != keys
            or manifest["schema_version"] != "world-anchor-completion/v1"
            or (expected_scope is not None and manifest["scope"] != expected_scope)):
        _fail("completion_manifest")
    controls = {}
    for item in manifest["control_files"]:
        if (type(item) is not dict or set(item) != {"path", "sha256", "bytes"}
                or item["path"] not in _CONTROL or item["path"] in controls):
            _fail("control_file")
        content = read_bytes(directory, item["path"])
        if len(content) != item["bytes"] or hashlib.sha256(content).hexdigest() != item["sha256"]:
            _fail("control_hash")
        controls[item["path"]] = decode_json(content)
    if set(controls) != _CONTROL:
        _fail("control_inventory")
    policy = controls[POLICY]
    requirements = wa.requirements_from_contract(controls[CONTRACT], scope=manifest["scope"])
    if (wa.anchor_hash(requirements) != manifest["requirements_hash"]
            or wa.anchor_hash(policy) != manifest["policy_hash"]
            or requirements["contract_hash"] != manifest["contract_hash"]):
        _fail("control_binding")
    index = wa.index_snapshot(directory / "world_anchor_inputs", controls[INPUTS],
        expected_manifest_hash=manifest["input_hash"], expected_scope=manifest["scope"],
        requirements=requirements, policy=policy)
    raw_pack = read_bytes(directory, "world_anchor.json")
    pack = decode_json(raw_pack)
    if wa.anchor_hash(pack) != manifest["pack_hash"]:
        _fail("pack_hash")
    bundles = {}
    for row in manifest["producer_manifests"]:
        if type(row) is not dict or set(row) != {"manifest_hash", "manifest"}:
            _fail("producer_manifest")
        digest = row["manifest_hash"]
        if not isinstance(digest, str) or len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
            _fail("producer_manifest_hash")
        if digest in bundles:
            _fail("duplicate_producer_manifest")
        bundles[digest] = wa.producer_receipts(directory / "world_anchor_producers" / digest,
            row["manifest"], expected_manifest_hash=digest, expected_scope=manifest["scope"])
    if set(bundles) != set(pack["producer_manifest_hashes"]):
        _fail("producer_inventory")
    # Accounting-only bundles still authenticate a bound stage that made no
    # model call. Reattach every pinned bundle before semantic replay; review
    # presence is not a prerequisite for retained budget authority.
    index = wa.attach_producer_receipts(index, receipts=list(bundles.values()))
    proposals = {wa.anchor_hash(p): p for p in pack["evidence_proposals"]}
    if len(proposals) != len(pack["evidence_proposals"]):
        _fail("duplicate_evidence_proposal")
    for review in pack["review_receipts"]:
        matches = [bundle for bundle in bundles.values() if any(
            item["artifact_id"] == review["transport_receipt_artifact_id"]
            and item["sha256"] == review["transport_receipt_hash"]
            for item in bundle.manifest["files"])]
        if len(matches) != 1 or review["proposal_hash"] not in proposals:
            _fail("review_receipt")
        index = wa.admit_reviewed_evidence(index, proposals[review["proposal_hash"]], review,
            requirements=requirements, policy=policy, receipts=matches[0])
    pack = wa.read_pack(directory, manifest["emission_receipt"],
        expected_receipt_hash=wa.anchor_hash(manifest["emission_receipt"]),
        expected_pack_hash=manifest["pack_hash"], requirements=requirements, index=index, policy=policy)
    return {"manifest": manifest, "manifest_sha256": expected_manifest_sha256,
            "pack": pack, "requirements": requirements, "policy": policy, "index": index,
            "producer_receipts": tuple(bundles.values())}


def validate_budget_completion(loaded, completion):
    """Join the selected pack meter to the ledger-authenticated final seal.

    Artifact SHA-256 authenticates the exact retained bytes. The canonical
    budget hash is a separate identity supplied by the committed scope exit.
    Merely retaining some matching budget elsewhere does not authorize the
    summary selected by the pack.
    """
    fields = {"session_id", "artifact_manifest_sha256", "budget_receipt_sha256", "result"}
    if (type(completion) is not dict or set(completion) != fields
            or completion["result"] not in {"sealed", "non_ready"}
            or not isinstance(completion["session_id"], str) or not completion["session_id"]
            or completion["artifact_manifest_sha256"] != loaded["manifest_sha256"]):
        _fail("scope_completion")
    expected = completion["budget_receipt_sha256"]
    if not isinstance(expected, str) or len(expected) != 64 or any(c not in "0123456789abcdef" for c in expected):
        _fail("scope_budget_hash")
    pack = loaded["pack"]
    meter = pack["metering"]
    if meter["mode"] != "metered":
        _fail("bound_scope_requires_metered")
    selected = []
    for handle in loaded["producer_receipts"]:
        if type(handle) is not wa.ProducerReceipts:
            _fail("producer_receipts")
        files = {row["artifact_id"]: row for row in handle.manifest["files"]}
        row = files.get(meter["receipt_artifact_id"])
        if row is None or row["sha256"] != meter["receipt_hash"]:
            continue
        if row["role"] != "metering_receipt":
            _fail("selected_meter_role")
        raw = handle.artifact_bytes(row["artifact_id"])
        if hashlib.sha256(raw).hexdigest() != meter["receipt_hash"]:
            _fail("selected_meter_hash")
        summary = decode_json(raw)
        if (summary.get("schema_version") != "world-anchor-metering/v1"
                or summary.get("anchor_budget_scope_id") != meter["anchor_budget_scope_id"]):
            _fail("selected_meter_identity")
        budget_row = files.get(summary.get("budget_receipt_artifact_id"))
        if (budget_row is None or budget_row["role"] != "metering_receipt"
                or budget_row["sha256"] != summary.get("budget_receipt_hash")):
            _fail("selected_budget_reference")
        budget_raw = handle.artifact_bytes(budget_row["artifact_id"])
        if hashlib.sha256(budget_raw).hexdigest() != summary["budget_receipt_hash"]:
            _fail("selected_budget_bytes")
        budget = decode_json(budget_raw)
        if (budget.get("schema") != "anchor-budget-receipt/v1"
                or wa.anchor_hash(budget) != expected
                or budget.get("pipeline_id") != pack["scope"]["run_id"]
                or budget.get("session_id") != completion["session_id"]
                or budget.get("scope_id") != meter["anchor_budget_scope_id"]):
            _fail("selected_budget_completion")
        selected.append(budget)
    if not selected or any(budget != selected[0] for budget in selected[1:]):
        _fail("selected_budget_missing_or_ambiguous")
    return selected[0]
