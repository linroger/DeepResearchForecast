"""Publication crash recovery from authenticated retained source/review handles."""
from pathlib import Path

import pytest

from app.services.official_data import bridge_module
from test_world_anchor_lifecycle import wired as _wired, target_case as _target_case

wired = _wired
target_case = _target_case


def _publication_args(wired):
    context = wired["context"]
    wa = bridge_module("world_anchor")
    # Reopen public, externally pinned producer manifests; do not reach into the
    # EvidenceIndex's private proof storage or construct a model-issued receipt.
    bundles = tuple(wa.producer_receipts(
        Path(wired["handoff"]) / "world_anchor_producers" / row["manifest_hash"],
        row["manifest"], expected_manifest_hash=row["manifest_hash"],
        expected_scope=context.pack["scope"])
        for row in wired["publication"]["manifest"]["producer_manifests"])
    return {"requirements": context.requirements, "index": context.index,
            "policy": context.policy, "receipts": bundles}


def test_publication_crash_never_admits_a_partial_generation_and_exact_retry_recovers(wired, tmp_path, monkeypatch):
    pub = bridge_module("world_anchor_publication")
    directory = tmp_path / "interrupted-publication"
    arguments = _publication_args(wired)
    write_once = pub.write_once

    def fail_manifest(root, name, data):
        if name == pub.MANIFEST:
            raise OSError("scripted completion-write failure")
        return write_once(root, name, data)

    with monkeypatch.context() as patch:
        patch.setattr(pub, "write_once", fail_manifest)
        with pytest.raises(OSError, match="completion-write failure"):
            pub.publish_completion(directory, wired["context"].pack, **arguments)
    assert (directory / "world_anchor.json").is_file()
    assert not (directory / pub.MANIFEST).exists()
    with pytest.raises(FileNotFoundError):
        pub.load_completion(directory,
            expected_manifest_sha256=wired["publication"]["manifest_sha256"])
    before = {p.relative_to(directory): p.read_bytes() for p in directory.rglob("*") if p.is_file()}
    completed = pub.publish_completion(directory, wired["context"].pack, **arguments)
    assert completed == wired["publication"]
    assert all((directory / name).read_bytes() == data for name, data in before.items())
    loaded = pub.load_completion(directory,
        expected_manifest_sha256=completed["manifest_sha256"])
    assert loaded["pack"] == wired["context"].pack


def test_changed_partial_output_is_not_overwritten_or_sealed(wired, tmp_path):
    pub = bridge_module("world_anchor_publication")
    directory = tmp_path / "changed-partial-publication"
    directory.mkdir()
    damaged = directory / "world_anchor.md"
    damaged.write_text("Unbound replacement sheet.")
    with pytest.raises(bridge_module("world_anchor").AnchorError, match="E_IMMUTABLE"):
        pub.publish_completion(directory, wired["context"].pack, **_publication_args(wired))
    assert damaged.read_text() == "Unbound replacement sheet."
    assert not (directory / pub.MANIFEST).exists()
