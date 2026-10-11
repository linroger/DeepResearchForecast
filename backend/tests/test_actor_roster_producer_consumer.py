"""Offline producer -> parent -> actor-context roster contract regressions."""

from __future__ import annotations

import hashlib
import json
import socket
from copy import deepcopy

import httpx
import pytest

from app.services import pipeline_orchestrator as po
from app.services.actor_context import (
    build_actor_context_artifacts,
    build_actor_context_pack,
    canonical_json_sha256,
    text_sha256,
    validate_actor_context_artifacts,
)
from app.utils.llm_client import LLMClient

# Reuse the established, source-grounded parent fixture inputs. The digest under
# test is produced by the real finalizer, never synthesized by these fixtures.
from test_pipeline_actor_contract import (
    _parent_errors,
    _producer_dossier,
    _producer_raw_actor,
    _producer_source,
    dr as _producer_bridge_fixture,
)

# Expose the shared pytest fixture under its injection name.
dr = _producer_bridge_fixture


def _unexpected_external_call(*_args, **_kwargs):
    raise AssertionError("actor roster regression must not invoke LLM/network")


@pytest.fixture(autouse=True)
def _mock_external_calls(monkeypatch):
    monkeypatch.setattr(LLMClient, "chat", _unexpected_external_call)
    monkeypatch.setattr(LLMClient, "chat_json", _unexpected_external_call)
    monkeypatch.setattr(httpx.Client, "send", _unexpected_external_call)
    monkeypatch.setattr(httpx.AsyncClient, "send", _unexpected_external_call)
    monkeypatch.setattr(socket, "create_connection", _unexpected_external_call)
    monkeypatch.setattr(socket, "getaddrinfo", _unexpected_external_call)


@pytest.fixture
def produce_bundle(tmp_path, dr, monkeypatch):
    """Finalize and promote synthetic evidence with production helpers only."""
    def produce(names=("Acme", "Beta")):
        producer_dir = tmp_path / "producer"
        handoff_dir = tmp_path / "handoff"
        producer_dir.mkdir()
        report = "# Forecast dossier\n\n" + "\n\n".join(
            f"## {name}: current actions, plans and capabilities\n"
            f"{name} is executing its capacity plan now. Its operating team can "
            "expand capacity in 2027, subject to permit approval. Its board "
            "decides the investment schedule after the September 2026 permit."
            for name in names
        )
        dossier = _producer_dossier(names)
        actors = {
            "as_of_date": "2026-07-22",
            "actors": [
                _producer_raw_actor(name, 1 if index == 0 else 2)
                for index, name in enumerate(names)
            ],
            "relationships": [],
        }
        for filename, value in (
            ("research_report.md", report),
            ("actor_dossier.md", dossier),
            ("actors.json", json.dumps(actors, ensure_ascii=False)),
            ("sources.json", json.dumps([_producer_source(names)], ensure_ascii=False)),
        ):
            (producer_dir / filename).write_text(value, encoding="utf-8")
        monkeypatch.setenv("RESEARCH_BUDGET_RUN_ID", "pipe_roster_context")
        monkeypatch.setenv("RESEARCH_BUDGET_EPOCH", "task-roster-context")
        monkeypatch.setenv("RESEARCH_BUDGET_LANE_ID", "outer-track-1")
        meta = {
            "question": "Will the capacity permit unlock deployment?",
            "depth": "standard",
            "thread_id": "research-actor-thread",
        }
        log = dr.ProgressLog(producer_dir / "producer.log")
        try:
            dr.persist_final_actor_intelligence_contract(
                producer_dir, report=report, dossier=dossier, meta=meta,
                plog=log, required=True,
            )
        finally:
            log.close()
        sources = json.loads((producer_dir / "sources.json").read_text(encoding="utf-8"))
        coverage = dr.actor_dossier_coverage_audit(
            dossier, sources, require_source_binding=True,
            required_receipt_purpose="track-b",
        )
        assert coverage["accountable"] is True
        assert meta["actor_intelligence"]["dossier_coverage"] == coverage
        for filename, value in (
            ("actor_dossier_coverage.json", coverage), ("meta.json", meta),
        ):
            (producer_dir / filename).write_text(json.dumps(value), encoding="utf-8")
        po._promote_research_contract(str(producer_dir), str(handoff_dir))
        bundle = {
            "handoff_dir": str(handoff_dir), "report": report, "dossier": dossier,
            "actors": json.loads((handoff_dir / "actors.json").read_text(encoding="utf-8")),
            "sources": json.loads((handoff_dir / "sources.json").read_text(encoding="utf-8")),
            "question": meta["question"], "depth": meta["depth"],
            "run_id": "pipe_roster_context", "attempt_ids": {"task-roster-context"},
        }
        assert _parent_errors(bundle) == []
        return bundle

    return produce


@pytest.mark.parametrize("names", [("Acme", "Beta"), ("Beta", "Acme")])
def test_real_producer_roster_passes_parent_and_context(produce_bundle, tmp_path, names):
    bundle = produce_bundle(names)
    actors = bundle["actors"]
    ids = [actor["actor_id"] for actor in actors["actors"]]
    incoming_digest = actors["actor_intelligence_contract"]["actor_ids_sha256"]
    assert incoming_digest == po._actor_multiset_sha256(ids)
    assert incoming_digest != hashlib.sha256("\n".join(sorted(ids)).encode("utf-8")).hexdigest()

    packs, manifest, manifest_sha = build_actor_context_artifacts(
        str(tmp_path / "context"), actors, actors["actors"], bundle["report"],
    )
    assert set(packs) == set(ids)
    assert all(pack["source"]["actor_ids_sha256"] == incoming_digest for pack in packs.values())
    assert manifest["actor_ids_sha256"] == canonical_json_sha256(ids)
    validated, loaded = validate_actor_context_artifacts(
        str(tmp_path / "context"), expected_count=len(ids),
        expected_manifest_sha256=manifest_sha,
        expected_report_sha256=text_sha256(bundle["report"]),
        expected_actors_sha256=canonical_json_sha256(actors),
        expected_actor_ids=ids,
    )
    assert validated == manifest
    assert loaded == packs


@pytest.mark.parametrize("selection", [(1,), (1, 0)])
def test_context_manifest_keeps_its_selected_ordered_list_digest(
    produce_bundle, tmp_path, selection,
):
    bundle = produce_bundle()
    actors = bundle["actors"]
    selected = [actors["actors"][index] for index in selection]
    ids = [actor["actor_id"] for actor in selected]
    root = tmp_path / "context"
    packs, manifest, manifest_sha = build_actor_context_artifacts(
        str(root), actors, selected, bundle["report"],
    )
    incoming_digest = actors["actor_intelligence_contract"]["actor_ids_sha256"]
    assert manifest["actor_ids_sha256"] == canonical_json_sha256(ids)
    assert manifest["actor_ids_sha256"] != incoming_digest
    assert all(pack["source"]["actor_ids_sha256"] == incoming_digest for pack in packs.values())
    validate_actor_context_artifacts(
        str(root), expected_manifest_sha256=manifest_sha, expected_actor_ids=ids,
    )

    # Omit the outer byte seal so this reaches the independent manifest roster
    # check, proving the incoming multiplicity digest cannot replace its list.
    manifest["actor_ids_sha256"] = incoming_digest
    (root / "actor_context_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValueError, match="actor context roster fingerprint mismatch"):
        validate_actor_context_artifacts(str(root))


@pytest.mark.parametrize("mutation", ["change", "remove", "append", "digest", "legacy", "list"])
def test_producer_roster_tampering_still_fails_closed(produce_bundle, mutation):
    bundle = produce_bundle()
    actors = deepcopy(bundle["actors"])
    rows = actors["actors"]
    contract = actors["actor_intelligence_contract"]
    if mutation == "change":
        rows[1]["actor_id"] = "actor_other_identity"
    elif mutation == "remove":
        rows.pop()
    elif mutation == "append":
        extra = deepcopy(rows[1])
        extra["actor_id"] = "actor_extra_identity"
        rows.append(extra)
    elif mutation == "digest":
        contract["actor_ids_sha256"] = "0" * 64
    elif mutation == "legacy":
        contract["actor_ids_sha256"] = hashlib.sha256(
            "\n".join(sorted(row["actor_id"] for row in rows)).encode("utf-8")
        ).hexdigest()
    else:
        contract["actor_ids_sha256"] = canonical_json_sha256([row["actor_id"] for row in rows])

    assert "actor_ids_sha256_mismatch" in _parent_errors(bundle, actors=actors)
    with pytest.raises(ValueError, match="actor roster fingerprint mismatch"):
        build_actor_context_pack(actors, rows[0], bundle["report"])


@pytest.mark.parametrize("missing_id", [None, "", "   "])
def test_missing_roster_identity_still_fails_closed(produce_bundle, missing_id):
    bundle = produce_bundle()
    actors = deepcopy(bundle["actors"])
    actors["actors"][1]["actor_id"] = missing_id
    with pytest.raises(ValueError, match="missing or duplicate actor identities"):
        build_actor_context_pack(actors, actors["actors"][0], bundle["report"])


def test_duplicate_identity_cannot_be_admitted_by_resealing_multiplicity(produce_bundle):
    bundle = produce_bundle()
    actors = deepcopy(bundle["actors"])
    actors["actors"].append(deepcopy(actors["actors"][0]))
    ids = [row["actor_id"] for row in actors["actors"]]
    contract = actors["actor_intelligence_contract"]
    contract["actor_count"] = len(ids)
    contract["actor_ids_sha256"] = po._actor_multiset_sha256(ids)
    with pytest.raises(ValueError, match="missing or duplicate actor identities"):
        build_actor_context_pack(actors, actors["actors"][0], bundle["report"])


def test_real_producer_context_still_binds_the_exact_selected_actor(produce_bundle):
    bundle = produce_bundle()
    actor = deepcopy(bundle["actors"]["actors"][0])
    actor["name"] = "Impersonated principal"
    with pytest.raises(ValueError, match="differs from the top-level intelligence roster"):
        build_actor_context_pack(bundle["actors"], actor, bundle["report"])


def test_real_producer_context_still_binds_report_and_actor_count(produce_bundle):
    bundle = produce_bundle()
    actors = bundle["actors"]
    with pytest.raises(ValueError, match="report fingerprint mismatch"):
        build_actor_context_pack(actors, actors["actors"][0], bundle["report"] + " changed")
    actors["actor_intelligence_contract"]["actor_count"] += 1
    with pytest.raises(ValueError, match="actor_count binding mismatch"):
        build_actor_context_pack(actors, actors["actors"][0], bundle["report"])
