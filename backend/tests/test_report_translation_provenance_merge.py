"""Reviewed prose plus deterministic envelopes through persisted public readers.

Only model responses are scripted. Generation, semantic receipts, deterministic
renderers, audits, storage and public Markdown downloads use production code.
"""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pytest

from app.config import Config
from app.services import model_translation as core
from app.services import report_agent as ra
from app.services import sim_provenance as sp
from tests.test_model_translation_workflow import forbid_legacy  # noqa: F401
from tests.test_report_forecast_localization import Translator
from tests.test_sim_bridge_isolation import (
    ScriptedModel, TOKENS, make_agent, write_sim,
    report_config as sim_report_config,  # noqa: F401
)
from tests.test_world_report_consumers import (
    generate, world,  # noqa: F401
    report_config as world_report_config,  # noqa: F401
)


def _sha(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class RecordingTranslator(Translator):
    def __init__(self):
        super().__init__()
        self.prompts = []

    def chat(self, messages=None, **kwargs):
        self.prompts.append(deepcopy(messages))
        return super().chat(messages=messages, **kwargs)


@pytest.fixture(params=["simulation", "world", "world_no_update"])
def translated_report(request, world, monkeypatch, forbid_legacy):
    if request.param == "simulation":
        request.getfixturevalue("sim_report_config")
        write_sim(Path(Config.OASIS_SIMULATION_DATA_DIR), "sim_merge_translation",
                  shares={"Expansion": .44, "Status quo": .56}, token=TOKENS[0])
        agent = make_agent("sim_merge_translation", ScriptedModel())
        report = agent.generate_report(report_id="report_merge_translation")
    else:
        request.getfixturevalue("world_report_config")
        directory = world(effect="no_update" if request.param == "world_no_update" else "diagnostic_only")
        agent, report, _ = generate(directory, report_id="report_merge_translation")
    assert report.status.value == "completed", report.error
    rid = report.report_id
    folder = Path(ra.ReportManager._get_report_folder(rid))
    sealed = {path.name: path.read_bytes() for path in folder.iterdir() if path.is_file()}
    monkeypatch.setattr(Config, "REPORT_BILINGUAL", True)
    monkeypatch.setattr(ra.ReportAgent, "_start_dashboard_localization", lambda *a, **k: None)
    model = RecordingTranslator()
    status = ra.ReportManager.generate_translation_variant(rid, "zh", llm_client=model)
    assert status["available"], status
    # meta.json gains translation metadata; every canonical content artifact stays sealed.
    assert all((folder / name).read_bytes() == data for name, data in sealed.items() if name != "meta.json")
    assert model.calls > 0
    assert sp.BRIDGE_START not in json.dumps(model.prompts)
    assert "<!-- world-pathway:" not in json.dumps(model.prompts)
    assert TOKENS[0] not in json.dumps(model.prompts)
    assert "goods_per_day" not in json.dumps(model.prompts)

    def no_provider(*args, **kwargs):
        raise AssertionError("persisted translation reads must not call a provider")

    monkeypatch.setattr(ra, "LLMClient", no_provider)
    monkeypatch.setattr(core, "translate_document", no_provider)
    from app import create_app
    app = create_app()
    app.config["TESTING"] = True
    return agent, report, folder, app.test_client()


def test_reviewed_prose_receipt_and_delivered_envelope_are_independently_bound(translated_report):
    agent, report, folder, client = translated_report
    rid = report.report_id
    source = (folder / "full_report.md").read_text()
    target = (folder / "full_report.zh.md").read_text()
    audit = json.loads((folder / "final_audit.zh.json").read_text())
    citations = json.loads((folder / "citations.zh.json").read_text())
    proof = audit["model_translation"]
    world = ra.ReportManager.load_world_result(rid)
    source_prose = ra._world_prose(source, ra.render_world_pathway(world["result"], chinese=False)) if world else source
    source_prose = ra._sim_prose(source_prose)
    reviewed_target = "\n\n".join(row["target"] for row in proof["sections"]).strip() + "\n"
    assert core.valid_document_receipt(source_prose, reviewed_target, "zh", proof)
    expected = (ra._insert_world_appendix(reviewed_target, ra.render_world_pathway(world["result"], chinese=True))
                if world else agent._insert_sim_bridge_variant(rid, source, reviewed_target, chinese=True))
    assert target == expected
    assert all(part["bytes_match"] for part in audit["simulation_bridge"].values())
    assert audit["markdown_chars"] == len(target)
    for carrier in (audit, citations):
        assert carrier["source_markdown_sha256"] == _sha(source)
        assert carrier["markdown_sha256"] == _sha(target)
    assert ra.ReportManager.publication_status(rid, "zh")["publishable"]
    response = client.get(f"/api/report/{rid}/full_report.zh.md")
    assert response.status_code == 200 and response.data == target.encode("utf-8")


@pytest.mark.parametrize("mutation", ["prose", "whitespace", "envelope", "receipt", "malformed_proof_issues", "source"])
def test_public_reader_rejects_tamper_even_when_outer_hashes_are_refreshed(translated_report, mutation):
    _, report, folder, client = translated_report
    rid = report.report_id
    target_path = folder / "full_report.zh.md"
    target = target_path.read_text()
    audit_path = folder / "final_audit.zh.json"
    audit = json.loads(audit_path.read_text())
    if mutation == "receipt":
        audit["model_translation"]["sections"][0]["receipt"] = None
    elif mutation == "malformed_proof_issues":
        audit["model_translation"]["issues"] = ["corrupt diagnostic payload"]
    elif mutation == "source":
        source_path = folder / "full_report.md"
        source = source_path.read_text() + "\nAn added unreviewed source claim.\n"
        source_path.write_text(source)
        audit["source_markdown_sha256"] = _sha(source)
        primary_path = folder / "final_audit.json"
        primary = json.loads(primary_path.read_text())
        primary["markdown_sha256"] = _sha(source)
        primary_path.write_text(json.dumps(primary))
    else:
        if mutation == "prose":
            target += "\n未经审阅的新增断言。\n"
        elif mutation == "whitespace":
            target += "\n"
        elif sp.BRIDGE_START in target:
            target = target.replace(sp.SIM_BANNER_ZH, "这是已经观察到的事实。")
        elif "<!-- world-pathway:start -->" in target:
            target = target.replace("<!-- world-pathway:end -->", "未经验证的变化\n<!-- world-pathway:end -->")
        else:
            target += "\n<!-- world-pathway:start -->\n虚构的路径\n<!-- world-pathway:end -->\n"
        assert target != target_path.read_text()
        target_path.write_text(target)
    audit["markdown_sha256"] = _sha(target)
    audit_path.write_text(json.dumps(audit))
    citations_path = folder / "citations.zh.json"
    citations = json.loads(citations_path.read_text())
    citations["markdown_sha256"] = _sha(target)
    citations["source_markdown_sha256"] = audit["source_markdown_sha256"]
    citations_path.write_text(json.dumps(citations))
    # Rehashing outer metadata cannot manufacture a new model review.
    status = ra.ReportManager.publication_status(rid, "zh")
    assert not status["publishable"], status
    assert any("semantic review" in reason for reason in status["reasons"]), status
    assert client.get(f"/api/report/{rid}/full_report.zh.md").status_code == 409


def test_persisted_reader_rejects_lost_envelope_provenance(translated_report):
    _, report, folder, client = translated_report
    rid = report.report_id
    world = ra.ReportManager.load_world_result(rid)
    if world:
        (folder / "world_result.json").unlink()
    else:
        sim_dir = Path(Config.OASIS_SIMULATION_DATA_DIR) / report.simulation_id
        # Neither a gate-passed record nor its raw-artifact fallback remains.
        sim_dir.rename(sim_dir.with_name(sim_dir.name + "_retired"))
    status = ra.ReportManager.publication_status(rid, "zh")
    assert not status["publishable"], status
    assert client.get(f"/api/report/{rid}/full_report.zh.md").status_code == 409
