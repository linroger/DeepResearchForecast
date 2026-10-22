"""T11 — ``GET /api/simulation/<id>/record`` and ``/record.md`` (ADR 0003; design §3.6).

Only a gate-passed record is served: 404 while none exists, 409 with
``publication_status`` while the audit is missing or failed, and the world-state route's
containment posture (regular file only, symlinks refused, no traversal).
"""
from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

import pytest

from app.config import Config
from app.services import sim_provenance as sp
from app.services import simulation_record as sr
from app.services import simulation_record_contract as rc
from app.services import simulation_record_gate as gate

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "sim_record"


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(Config, "OASIS_SIMULATION_DATA_DIR", str(tmp_path))
    from app import create_app
    app = create_app()
    app.config["TESTING"] = True
    return app.test_client()


def _published_run(root: Path, name: str, language="en") -> Path:
    sim_dir = root / name
    shutil.copytree(FIXTURES / "reflexive3", sim_dir)
    record = sr.build_record(str(sim_dir), language=language, synthesis=False)
    sr.write_record(str(sim_dir), record)
    audit = gate.audit_record(str(sim_dir), record)
    assert audit["publication_status"] == "passed", audit["hard_issues"]
    return sim_dir


def test_record_routes_serve_a_gate_passed_record(client, tmp_path):
    sim_dir = _published_run(tmp_path, "sim_ok")
    res = client.get("/api/simulation/sim_ok/record")
    assert res.status_code == 200
    body = res.get_json()
    assert body["success"] is True and body["data"]["schema"] == rc.SCHEMA
    assert body["data"]["banner"] == sp.SIM_BANNER_EN and body["data"]["rounds_committed"] == 3
    assert body["data"] == json.loads(Path(sim_dir, rc.RECORD_JSON).read_text(encoding="utf-8"))
    en = client.get("/api/simulation/sim_ok/record.md")
    assert en.status_code == 200 and en.mimetype == "text/markdown"
    assert en.get_data(as_text=True) == Path(sim_dir, rc.RECORD_MD).read_text(encoding="utf-8")
    assert sp.SIM_BANNER_EN in en.get_data(as_text=True)
    assert en.headers["X-Content-Type-Options"] == "nosniff"
    zh = client.get("/api/simulation/sim_ok/record.md?lang=zh")
    assert zh.status_code == 200 and zh.mimetype == "text/markdown"
    assert zh.get_data(as_text=True) == Path(sim_dir, rc.RECORD_MD_ZH).read_text(encoding="utf-8")
    assert sp.SIM_BANNER_ZH in zh.get_data(as_text=True)
    assert client.get("/api/simulation/sim_ok/record.md?lang=zh-CN").get_data(as_text=True) == zh.get_data(as_text=True)
    assert client.get("/api/simulation/sim_ok/record.md?lang=fr").get_data(as_text=True) == en.get_data(as_text=True)


def test_english_rendering_of_a_chinese_record_is_rendered_from_the_json(client, tmp_path):
    sim_dir = _published_run(tmp_path, "sim_zh", language="zh")
    record = json.loads(Path(sim_dir, rc.RECORD_JSON).read_text(encoding="utf-8"))
    assert record["language"] == "zh"
    zh = client.get("/api/simulation/sim_zh/record.md?lang=zh").get_data(as_text=True)
    assert zh == Path(sim_dir, rc.RECORD_MD_ZH).read_text(encoding="utf-8") and sp.SIM_BANNER_ZH in zh
    en = client.get("/api/simulation/sim_zh/record.md?lang=en")
    assert en.status_code == 200
    assert en.get_data(as_text=True) == sr.render_markdown(record, "en")
    assert sp.SIM_BANNER_EN in en.get_data(as_text=True)


def test_missing_record_is_404_and_unpublished_record_is_409(client, tmp_path):
    assert client.get("/api/simulation/sim_absent/record").status_code == 404
    assert client.get("/api/simulation/sim_absent/record.md").status_code == 404
    sim_dir = tmp_path / "sim_norecord"
    shutil.copytree(FIXTURES / "reflexive3", sim_dir)
    assert client.get("/api/simulation/sim_norecord/record").status_code == 404
    # record written, audit missing → 409 not_audited
    record = sr.build_record(str(sim_dir), language="en", synthesis=False)
    sr.write_record(str(sim_dir), record)
    for route in ("/api/simulation/sim_norecord/record", "/api/simulation/sim_norecord/record.md?lang=zh"):
        res = client.get(route)
        assert res.status_code == 409, route
        body = res.get_json()
        assert body["success"] is False and body["publication_status"] == "not_audited" and body["error"]
    # audit failed → 409 failed
    Path(sim_dir, rc.RECORD_AUDIT_JSON).write_text(json.dumps(
        {"publication_status": "failed", "hard_issues": ["G2: numeric token 37.5% does not trace to any artifact row"]}),
        encoding="utf-8")
    res = client.get("/api/simulation/sim_norecord/record")
    assert res.status_code == 409 and res.get_json()["publication_status"] == "failed"
    # a "passed" audit that still lists hard issues is not published either
    Path(sim_dir, rc.RECORD_AUDIT_JSON).write_text(json.dumps(
        {"publication_status": "passed", "hard_issues": ["G5: citation marker"]}), encoding="utf-8")
    res = client.get("/api/simulation/sim_norecord/record")
    assert res.status_code == 409 and res.get_json()["publication_status"] == "failed"
    # the real gate flips it to 200
    gate.audit_record(str(sim_dir), record)
    assert client.get("/api/simulation/sim_norecord/record").status_code == 200


def test_symlinked_record_and_traversal_identifiers_are_refused(client, tmp_path):
    real = _published_run(tmp_path, "sim_real")
    linked = tmp_path / "sim_link"
    linked.mkdir()
    os.symlink(real / rc.RECORD_JSON, linked / rc.RECORD_JSON)
    shutil.copy(real / rc.RECORD_AUDIT_JSON, linked / rc.RECORD_AUDIT_JSON)
    assert client.get("/api/simulation/sim_link/record").status_code == 404
    assert client.get("/api/simulation/sim_link/record.md").status_code == 404
    # a symlinked audit does not publish a real record
    unaudited = tmp_path / "sim_linkaudit"
    shutil.copytree(real, unaudited)
    os.unlink(unaudited / rc.RECORD_AUDIT_JSON)
    os.symlink(real / rc.RECORD_AUDIT_JSON, unaudited / rc.RECORD_AUDIT_JSON)
    res = client.get("/api/simulation/sim_linkaudit/record")
    assert res.status_code == 409 and res.get_json()["publication_status"] == "not_audited"
    # the identifiers the world-state route refuses are refused here
    for bad in ("..%2F..%2Fetc", "%2E%2E", ".", "sim_real%2F..%2Fsim_real", "sim%00real"):
        assert client.get(f"/api/simulation/{bad}/record").status_code == 404, bad
        assert client.get(f"/api/simulation/{bad}/record.md").status_code == 404, bad
    # a symlinked markdown rendering is not read: the route renders from the JSON instead
    md_link = tmp_path / "sim_mdlink"
    shutil.copytree(real, md_link)
    os.unlink(md_link / rc.RECORD_MD)
    (tmp_path / "evil.md").write_text("# not the record\n", encoding="utf-8")
    os.symlink(tmp_path / "evil.md", md_link / rc.RECORD_MD)
    res = client.get("/api/simulation/sim_mdlink/record.md")
    assert res.status_code == 200 and "not the record" not in res.get_data(as_text=True)
    assert sp.SIM_BANNER_EN in res.get_data(as_text=True)


def test_oversized_rewritten_or_unparsable_record_is_not_served(client, tmp_path):
    sim_dir = _published_run(tmp_path, "sim_big")
    from app.api import simulation as api
    with pytest.MonkeyPatch.context() as cap:
        cap.setattr(api, "WORLD_STATE_MAX_BYTES", 10)
        assert client.get("/api/simulation/sim_big/record").status_code == 413
        assert client.get("/api/simulation/sim_big/record.md").status_code == 413
    assert client.get("/api/simulation/sim_big/record").status_code == 200
    # a record rewritten after its audit is unaudited bytes: 409 stale_audit, never 200
    record = json.loads(Path(sim_dir, rc.RECORD_JSON).read_text(encoding="utf-8"))
    record["overall"]["synthesis"]["text"] += "\n\nAdded after the audit (2026-10-25)."
    sr.write_record(str(sim_dir), record)
    res = client.get("/api/simulation/sim_big/record")
    assert res.status_code == 409 and res.get_json()["publication_status"] == "stale_audit"
    assert client.get("/api/simulation/sim_big/record.md").status_code == 409
    gate.audit_record(str(sim_dir), record)
    assert client.get("/api/simulation/sim_big/record").status_code == 200
    Path(sim_dir, rc.RECORD_JSON).write_text("{not json", encoding="utf-8")
    res = client.get("/api/simulation/sim_big/record")
    assert res.status_code == 409 and res.get_json()["success"] is False
