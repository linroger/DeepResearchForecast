"""Durable report adapter acceptance through the production manager and resolver."""
import copy
import hashlib
import json
from pathlib import Path

import pytest

from app.services import model_translation
from app.services.report_agent import ReportAgent, ReportManager
from tests.test_report_bilingual import _publish_primary, _TransLLM
from model_translation_fakes import raw_fixture_zh


@pytest.fixture
def report_root(tmp_path, monkeypatch):
    from app.config import Config
    root = tmp_path / "reports"
    root.mkdir()
    monkeypatch.setattr(ReportManager, "REPORTS_DIR", str(root))
    monkeypatch.setattr(Config, "UPLOAD_FOLDER", str(tmp_path / "uploads"))
    return root


@pytest.mark.parametrize("missing", [1, 2])
def test_failed_v1_22_section_audit_imports_only_valid_sections(report_root, missing):
    source = "\n\n".join(("#" if i == 0 else "##") + f" Chapter {i}\n\n"
                         f"The projected demand increases by {i + 1}% in this scenario."
                         for i in range(22)) + "\n"
    rid = "report_resume_" + str(missing)
    _publish_primary(rid, source)
    _translated, proof = model_translation.translate_document(_TransLLM(raw_fixture_zh), source, "zh")
    assert proof["complete"] and len(proof["sections"]) == 22
    incomplete = copy.deepcopy(proof)
    incomplete["complete"] = False
    incomplete["issues"] = {f"section:{i}": ["review transport interrupted"] for i in range(22-missing,22)}
    for row in incomplete["sections"][-missing:]:
        row["receipt"] = None
        row["target"] = row["source"]
    audit_path = Path(ReportManager._get_report_final_audit_path(rid, "zh"))
    audit_path.write_text(json.dumps({"hard_passed": False, "model_translation": incomplete,
                                    "report_id": rid, "language": "zh", "source_language": "en",
                                    "source_markdown_sha256": hashlib.sha256(source.encode()).hexdigest()}))
    llm = _TransLLM(raw_fixture_zh)
    result = ReportManager.generate_translation_variant(rid, "zh", llm_client=llm)
    assert result["available"] and ReportManager.is_publishable(rid, "zh")
    requests = [json.loads(call["messages"][-1]["content"]) for call in llm.calls]
    translated_keys = [key for payload in requests for key in payload.get("entries", {})]
    assert translated_keys == [f"section:{i}" for i in range(22-missing,22)]
    assert len(requests) == 2  # one focused translation plus its independent review
    snapshot = ReportManager.resolve_translation(rid, "zh")
    assert snapshot.audit["model_translation"]["job"]["coverage"]["reused"] == 22-missing
    assert Path(ReportManager._get_report_markdown_path(rid)).read_text() == source


@pytest.mark.parametrize("defect", ["report_id", "source_hash", "language", "context", "foreign_scope"])
def test_trusted_report_import_rejects_foreign_or_unbound_resource_claims(report_root, defect):
    from app.services.translation.contracts import scope_digest
    source = "# Demand forecast\n\nThe projected demand increases by 20% in this scenario.\n"
    rid = "report_seed_owner"
    _publish_primary(rid, source)
    _, proof = model_translation.translate_document(_TransLLM(raw_fixture_zh), source, "zh")
    identity = {"kind": "forecast_report", "ref_id": rid, "scope": "public_body",
                "source_markdown_sha256": hashlib.sha256(source.encode()).hexdigest()}
    audit = {"report_id": rid, "language": "zh", "source_language": "en",
             "source_markdown_sha256": identity["source_markdown_sha256"], "model_translation": proof}
    if defect == "report_id":
        audit["report_id"] = "another_report"
    elif defect == "source_hash":
        audit["source_markdown_sha256"] = "0" * 64
    elif defect == "language":
        audit["language"] = "en"
    elif defect == "context":
        proof["context"] = "foreign outline"
    else:
        foreign = scope_digest({**identity, "ref_id": "another_report"})
        proof["resource_scope_sha256"] = foreign
        proof["sections"][0]["receipt"]["resource_scope_sha256"] = foreign
    Path(ReportManager._get_report_final_audit_path(rid, "zh")).write_text(json.dumps(audit))
    assert ReportManager.previous_translation_proof(rid, "zh", identity=identity, source_document=source) is None
    llm = _TransLLM(raw_fixture_zh)
    assert ReportManager.generate_translation_variant(rid, "zh", llm_client=llm)["available"]
    assert any("entries" in json.loads(call["messages"][-1]["content"]) for call in llm.calls)


def test_accepted_generation_survives_failed_refresh_and_restart(report_root, monkeypatch):
    rid = "report_refresh_generation"
    source = "# Demand forecast\n\nThe projected demand increases by 20% in this scenario.\n"
    _publish_primary(rid, source)
    accepted = ReportManager.generate_translation_variant(rid, "zh", llm_client=_TransLLM(raw_fixture_zh))
    assert accepted["available"]
    snapshot = ReportManager.resolve_translation(rid, "zh")
    previous_files = {str(path): path.read_bytes() for path in Path(snapshot.path).iterdir()}
    failed = ReportManager.generate_translation_variant(rid, "zh", llm_client=_TransLLM(lambda value: value), force=True)
    assert failed["available"] and failed["updated"] is False
    assert ReportManager.resolve_translation(rid, "zh").generation == snapshot.generation
    assert all(Path(path).read_bytes() == data for path, data in previous_files.items())
    # Publication is independently readable even if the coordinator DB is unavailable.
    monkeypatch.setattr("app.services.translation.store.Store.__init__",
                        lambda *a, **kw: pytest.fail("artifact read opened coordinator DB"))
    assert ReportManager.read_translation_markdown(rid, "zh") == snapshot.markdown
    assert ReportManager.publication_status(rid, "zh")["publishable"]


def test_ordinary_retry_and_display_refresh_keep_accepted_body(report_root):
    rid = "report_refresh_display"
    _publish_primary(rid, "# Demand forecast\n\nThe projected demand increases by 20% in this scenario.\n")
    ReportManager.generate_translation_variant(rid, "zh", llm_client=_TransLLM(raw_fixture_zh))
    snapshot = ReportManager.resolve_translation(rid, "zh")
    transport = _TransLLM(raises=True)
    assert ReportManager.generate_translation_variant(rid, "zh", llm_client=transport)["available"]
    assert transport.calls == []
    updated = ReportManager.refresh_translation_assets(rid, "zh", {"display.json": {"title": "预测"}})
    assert updated.generation != snapshot.generation
    assert updated.markdown == snapshot.markdown and updated.audit == snapshot.audit
    assert json.loads(updated.assets["display.json"])["title"] == "预测"


def test_explicit_forecast_refresh_reexecutes_but_failed_replacement_preserves_accepted(report_root):
    from test_report_forecast_localization import _seal_forecast, _FORECAST, _MARKDOWN, Translator, _agent
    from app.services.translation.contracts import TranslationError
    rid = "report_forecast_refresh"
    _seal_forecast(rid, _FORECAST, _MARKDOWN)
    llm = Translator()
    worker = _agent(llm)
    assert worker._ensure_localized_forecast(rid, "zh")["complete"]
    initial_calls = llm.calls
    worker._ensure_localized_forecast(rid, "zh")
    assert llm.calls == initial_calls
    assert worker._ensure_localized_forecast(rid, "zh", force=True)["complete"]
    assert llm.calls > initial_calls
    path = Path(ReportManager._get_report_localized_forecast_path(rid, "zh"))
    accepted = path.read_bytes()
    worker.llm = _TransLLM(raises=True)
    with pytest.raises(TranslationError) as caught:
        worker._ensure_localized_forecast(rid, "zh", force=True)
    assert caught.value.code == "forecast_translation_incomplete"
    assert path.read_bytes() == accepted
    assert ReportManager.load_localized_forecast(rid, "zh")[1]["complete"]


def test_legacy_forecast_seed_is_admitted_only_through_matching_local_metadata(report_root):
    from test_report_forecast_localization import _seal_forecast, _FORECAST, _MARKDOWN, Translator, _agent
    rid = "report_legacy_forecast_seed"
    source_sha = _seal_forecast(rid, _FORECAST, _MARKDOWN)
    legacy, metadata = _agent(Translator())._localize_forecast(_FORECAST, "zh")
    fields = ReportAgent._forecast_text_fields(_FORECAST)
    field_path, source = fields[-1]
    key = "/".join(str(step) for step in field_path)
    metadata["receipts"].pop(key)
    metadata.update(complete=False, unresolved=[key], lang="zh", schema_version=2,
                    source_forecast_sha256=source_sha)
    ReportAgent._set_forecast_path(legacy, field_path, source)
    legacy["localization"] = metadata
    Path(ReportManager._get_report_localized_forecast_path(rid, "zh")).write_text(json.dumps(legacy))
    llm = Translator()
    result = _agent(llm)._ensure_localized_forecast(rid, "zh")
    assert result["complete"] and result["job"]["coverage"]["reused"] == len(fields) - 1
    assert llm.calls == 2


def test_forecast_reader_rejects_a_foreign_bound_receipt(report_root):
    from test_report_forecast_localization import _seal_forecast, _FORECAST, _MARKDOWN, Translator, _agent
    from app.services.translation.contracts import scope_digest
    rid = "report_forecast_foreign_receipt"
    source_sha = _seal_forecast(rid, _FORECAST, _MARKDOWN)
    _agent(Translator())._ensure_localized_forecast(rid, "zh")
    path = Path(ReportManager._get_report_localized_forecast_path(rid, "zh"))
    localized = json.loads(path.read_text())
    receipt = next(iter(localized["localization"]["receipts"].values()))
    receipt["resource_scope_sha256"] = scope_digest({"kind": "report_forecast", "ref_id": "foreign",
        "scope": "public_display", "source_forecast_sha256": source_sha})
    path.write_text(json.dumps(localized))
    actual, state = ReportManager.load_localized_forecast(rid, "zh")
    assert not state["localized"] and not state["complete"] and actual == _FORECAST
