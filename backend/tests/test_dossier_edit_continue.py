"""Dossier edits must never be silently discarded by Continue (T5.4).

Editing research_report.md used to succeed and then vanish: Continue re-validated
the research, saw bytes that no longer matched what was recorded, and re-ran
research/synthesis over the edit.

* Sealed research binds the report bytes elsewhere: the multi-lane contract
  (research_contract_manifest.json, plus the judge prose binding) and/or a v1
  actor contract whose report hash actor reception and actor-context
  re-verify. The edit API now refuses it explicitly (409, ``sealed: true``) and
  the dossier payload reports ``sealed`` so the UI can hide the Edit button.
* Unsealed (legacy) research is reused on resume via handoff/manifest.json; the
  edit now refreshes the edited entries so that reuse check accepts the edit.
"""

from __future__ import annotations

import hashlib
import json

import pytest
from flask import Flask

from app.api import research_bp
from app.config import Config
import app.services.pipeline_orchestrator as po
from app.services.pipeline_orchestrator import (
    STAGE_RESEARCH,
    PipelineManager,
    PipelineOrchestrator,
    PipelineState,
)

PID = "pipe_edit0a1b2c3d"
ORIGINAL = "# Research\n\n" + ("Original machine-written finding. " * 30)
EDITED = "# Research (human-reviewed)\n\n" + ("Corrected finding after review. " * 30)


@pytest.fixture()
def pipeline(tmp_path, monkeypatch):
    monkeypatch.setattr(Config, "PIPELINE_DATA_DIR", str(tmp_path), raising=False)
    monkeypatch.setattr(Config, "PIPELINE_VALIDATE_ARTIFACTS", True, raising=False)
    root = tmp_path / PID
    handoff = root / "handoff"
    handoff.mkdir(parents=True)
    (handoff / "research_report.md").write_text(ORIGINAL, encoding="utf-8")
    state = {
        "pipeline_id": PID,
        "prompt": "Will X happen by 2030?",
        "mode": "research_only",
        "status": "completed",
        "schema_version": po.PIPELINE_SCHEMA_VERSION,
        "artifacts": {},
        "stages": {STAGE_RESEARCH: {"name": STAGE_RESEARCH, "status": "completed", "progress": 100}},
    }
    (root / "pipeline_state.json").write_text(json.dumps(state), encoding="utf-8")
    return handoff


@pytest.fixture()
def client():
    app = Flask(__name__)
    app.register_blueprint(research_bp, url_prefix="/api/research")
    return app.test_client()


def _record_research_manifest(handoff):
    entry = po._manifest_entry_for("report", str(handoff / "research_report.md"), STAGE_RESEARCH)
    PipelineManager.write_artifact_manifest(PID, {"report": entry})


def _reuse_accepted():
    state = PipelineState(pipeline_id=PID, prompt="", handoff_dir=PipelineManager.handoff_dir(PID))
    return PipelineOrchestrator()._validate_reuse(state, STAGE_RESEARCH)


def _seal_with_contract_manifest(handoff):
    (handoff / po._RESEARCH_CONTRACT_FILENAME).write_text(
        json.dumps({"version": 1, "files": {}}), encoding="utf-8")


def _seal_with_actor_contract(handoff):
    # Single-lane runs have no contract manifest, but a v1 actor contract binds
    # report_sha256 that actor reception and actor-context re-verify.
    (handoff / "actors.json").write_text(json.dumps({
        "actors": [],
        "actor_intelligence_contract": {"schema_version": "actor-intelligence/v1",
                                        "report_sha256": "0" * 64},
    }), encoding="utf-8")


def _seal_with_actor_lineage(handoff):
    (handoff / po.ACTOR_INTELLIGENCE_LINEAGE_FILENAME).write_text("{}", encoding="utf-8")


@pytest.mark.parametrize("seal", [
    _seal_with_contract_manifest, _seal_with_actor_contract, _seal_with_actor_lineage,
])
def test_sealed_research_edit_is_refused_and_untouched(pipeline, client, seal):
    seal(pipeline)

    resp = client.put(f"/api/research/{PID}/dossier", json={"report": EDITED})

    assert resp.status_code == 409
    body = resp.get_json()
    assert body["sealed"] is True and body["success"] is False
    assert "sealed" in body["error"]
    assert (pipeline / "research_report.md").read_text(encoding="utf-8") == ORIGINAL


def test_dossier_payload_reports_sealed_state(pipeline, client):
    assert client.get(f"/api/research/{PID}/dossier").get_json()["data"]["sealed"] is False
    (pipeline / po._RESEARCH_CONTRACT_FILENAME).write_text("{}", encoding="utf-8")
    assert client.get(f"/api/research/{PID}/dossier").get_json()["data"]["sealed"] is True


def test_legacy_edit_survives_resume_reuse_check(pipeline, client):
    _record_research_manifest(pipeline)
    manifest = PipelineManager.load_artifact_manifest(PID)
    manifest["report"]["produced_at"] = "2026-01-01T00:00:00+00:00"
    PipelineManager.write_artifact_manifest(PID, manifest)
    assert _reuse_accepted()

    resp = client.put(f"/api/research/{PID}/dossier", json={"report": EDITED})

    assert resp.status_code == 200, resp.get_json()
    assert (pipeline / "research_report.md").read_text(encoding="utf-8") == EDITED
    entry = PipelineManager.load_artifact_manifest(PID)["report"]
    assert entry["sha256"] == hashlib.sha256(EDITED.encode("utf-8")).hexdigest()
    # When research produced it is kept; the edit gets its own (current) stamp.
    assert entry["produced_at"] == "2026-01-01T00:00:00+00:00"
    assert entry["human_edited_at"] > entry["produced_at"]
    # Continue/resume reuses the edited research instead of re-running it.
    assert _reuse_accepted()


def test_unrefreshed_edit_would_have_been_rejected(pipeline):
    """Guard the premise: a raw write alone fails the reuse check (the old bug)."""
    _record_research_manifest(pipeline)
    (pipeline / "research_report.md").write_text(EDITED, encoding="utf-8")
    assert not _reuse_accepted()


def test_legacy_edit_without_manifest_needs_no_refresh(pipeline, client):
    resp = client.put(f"/api/research/{PID}/dossier", json={"report": EDITED})
    assert resp.status_code == 200
    assert PipelineManager.load_artifact_manifest(PID) == {}
    assert _reuse_accepted()
