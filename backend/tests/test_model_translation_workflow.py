"""Public-consumer acceptance for the model-led translation engine.

Only configured model transport responses are scripted. Publication, source
binding, parser validation, review receipts, persistence and API reads stay real.
These tests prove the exercised contract, not live model translation quality.
"""

from __future__ import annotations

from copy import deepcopy
import hashlib
import importlib
import json
from pathlib import Path
import subprocess
import sys
import threading
import time

import pytest

from test_forecast_feedback_sdk import published  # native audit + ledger fixture


SOURCE = (
    "# Investment outlook\n\n"
    "## Capacity and funding\n\n"
    "On October 22, 2026, the company allocated $3.7 billion. "
    "It will not commission 25 MW before December 31, 2027 [S1].\n\n"
    "| Measure | Value |\n|---|---:|\n| Planned capacity | 25 MW |\n\n"
    "```python\n# ## not a section\ncapacity = 25  # MW\n```\n\n"
    "## References\n\n"
    "1. [S1] [Capacity filing](https://example.test/filing?id=25)\n\n"
    "## Visual Annex\n\n"
    "The timeline shows conditional milestones.\n"
)
TARGET = (
    "# 投资展望\n\n"
    "## 产能与资金\n\n"
    "2026年10月22日，公司拨出37亿美元。"
    "在2027年12月31日之前，公司不会投运25 MW产能 [S1]。\n\n"
    "| 指标 | 数值 |\n|---|---:|\n| 规划产能 | 25 MW |\n\n"
    "```python\n# ## not a section\ncapacity = 25  # MW\n```\n\n"
    "## 参考来源\n\n"
    "1. [S1] [产能申报文件](https://example.test/filing?id=25)\n\n"
    "## 视觉附录\n\n"
    "时间线显示附带条件的里程碑。\n"
)

# Exact fixture prose translations. This is an explicit transport script, not a
# replacement implementation of production extraction, validation or review.
_TEXT = {
    "## References": "## 参考来源",
    "# Investment outlook": "# 投资展望",
    "## Capacity and funding": "## 产能与资金",
    "On October 22, 2026, the company allocated $3.7 billion. "
    "It will not commission 25 MW before December 31, 2027 [S1].":
        "2026年10月22日，公司拨出37亿美元。"
        "在2027年12月31日之前，公司不会投运25 MW产能 [S1]。",
    "| Measure | Value |": "| 指标 | 数值 |",
    "| Planned capacity | 25 MW |": "| 规划产能 | 25 MW |",
    "[Capacity filing]": "[产能申报文件]",
    "## Visual Annex": "## 视觉附录",
    "The timeline shows conditional milestones.": "时间线显示附带条件的里程碑。",
    "# Committee outlook": "# 委员会展望",
    "Committee outlook": "委员会展望",
    "## Decision": "## 决策",
    "The committee could approve the proposal. Other outcomes remain possible.":
        "委员会可能批准该提案。其他结果仍有可能。",
    "## Historical forecasting track record": "## 历史预测记录",
    "These scores describe retained forecasts with recorded outcomes. "
    "A limited record does not establish calibration.":
        "这些分数描述已保存预测的实际判定记录；样本有限时不能据此声称模型已校准。",
    "| Forecast type | Forecasts | Resolved | Outstanding | Mean Brier |":
        "| 类型 | 预测数 | 已判定 | 待判定 | 平均 Brier |",
    "Scenarios (multiclass)": "情景预测（多类别）",
    "Market binaries": "市场二元预测",
    "Official-data binaries": "官方数据二元预测",
    "Unanchored binaries": "无锚定二元预测",
    "Scenario and binary scores have separate denominators. "
    "This report is excluded from its own history.":
        "情景分数与二元分数分别统计；本报告不计入自身的历史记录。",
    "Committee decision": "委员会决策",
    "Base case": "基准情景",
    "Other": "其他",
    "The committee approves the proposal by the deadline.": "委员会在截止日期前批准该提案。",
    "All other committee outcomes at the deadline.": "截止日期时委员会作出的其他所有结果。",
    "The committee records approval by the deadline.": "委员会在截止日期前记录批准决定。",
    "Will capacity increase?": "产能会增加吗？",
    "Supplies infrastructure.": "供应基础设施。",
    "Supply is constrained.": "供应受到约束。",
    "Future growth.": "未来增长。",
    "Economic output": "经济产出",
    "North America": "北美洲",
    "Expected supply trend.": "预期供应趋势。",
    "A private decision with 25 MW.": "涉及25 MW的私下决策。",
    "The next decision.": "下一项决策。",
    "The company will not commission 25 MW.": "公司不会投运25 MW产能。",
    "The baseline remains uncertain.": "基准情景仍不确定。",
}


def _zh(source):
    result = source
    for text, translated in sorted(_TEXT.items(), key=lambda pair: -len(pair[0])):
        result = result.replace(text, translated)
    return result


class ScriptedModel:
    """Strict new-protocol transport; it rejects legacy prose-slot requests."""

    model = "offline-model-led-acceptance"
    provider = "scripted-transport-only"

    def __init__(self, mutate=None, after_generation=None):
        self.trace = []
        self.mutate = mutate
        self.after_generation = after_generation
        self._lock = threading.Lock()

    def chat_json(self, messages=None, **_kwargs):
        assert messages and len(messages) == 2
        payload = json.loads(messages[-1]["content"])
        assert payload.get("target_language") in {"en", "zh"}, payload
        assert isinstance(payload.get("context"), str), payload
        assert "⟦" not in messages[-1]["content"], "Opaque tokens reached the model"
        if "entries" in payload:
            entries = payload["entries"]
            assert isinstance(entries, dict) and entries
            values = {}
            for key, source in entries.items():
                assert isinstance(source, str)
                target = _zh(source) if payload["target_language"] == "zh" else source
                values[key] = self.mutate(source, target, bool(payload.get("repair"))) \
                    if self.mutate else target
            response = {"translations": values}
            stage = "repair" if payload.get("repair") else "translate"
        else:
            pairs = payload.get("pairs")
            assert isinstance(pairs, dict) and pairs, payload
            response = {"reviews": {}}
            for key, pair in pairs.items():
                source, target = pair["source"], pair["translation"]
                expected = _zh(source) if payload["target_language"] == "zh" else source
                good = target == expected and (
                    payload["target_language"] == "en" or target != source or source == "NVIDIA"
                )
                response["reviews"][key] = {
                    "faithful": good, "complete": good, "target_language": good,
                    "issues": [] if good else ["Fixture fidelity mismatch: altered or missing meaning"],
                }
            stage = "review"
        with self._lock:
            self.trace.append({"stage": stage, "payload": deepcopy(payload), "response": deepcopy(response)})
            callback, self.after_generation = self.after_generation, None
        if callback and stage in {"translate", "repair"}:
            callback()
        return response

    def chat(self, messages=None, **kwargs):
        return json.dumps(self.chat_json(messages=messages, **kwargs), ensure_ascii=False)


def _sha(value):
    return hashlib.sha256(value if isinstance(value, bytes) else value.encode()).hexdigest()


def _proof(tmp_path, name, value):
    (tmp_path / (name + ".json")).write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


@pytest.fixture(autouse=True)
def isolated_translation_store(tmp_path, monkeypatch):
    from app.config import Config
    from app.services.translation import scheduler
    monkeypatch.setattr(Config, "UPLOAD_FOLDER", str(tmp_path / "uploads"))
    yield
    scheduler.stop_schedulers()


@pytest.fixture
def forbid_legacy(monkeypatch):
    from app.services.report_agent import ReportAgent
    from app.services import translation_tools

    def blocked(*_args, **_kwargs):
        raise AssertionError("Legacy translation protection/repair entered by new default")

    for name in (
        "_protect_translation_tokens", "_restore_translation_tokens", "_resolve_prose_slots",
        "_repair_variant_contamination", "_repair_translation_numeric_boundaries",
        "_lint_variant_to_audit_fixed_point",
    ):
        monkeypatch.setattr(ReportAgent, name, blocked)
    for name in ("_protect_pair", "_restore_pair"):
        if hasattr(translation_tools, name):
            monkeypatch.setattr(translation_tools, name, blocked)


def _forbid_provider(*_args, **_kwargs):
    raise AssertionError("Read-only consumer must not acquire a translation model")


def _wait(client, url, *, query_string=None):
    for _ in range(400):
        response = client.get(url, query_string=query_string)
        assert response.status_code == 200, response.json
        data = response.json["data"]
        if data["status"] != "generating":
            return data
        time.sleep(.01)
    raise AssertionError("Actual translation worker did not settle within bounded polling")


def _client():
    from app import create_app
    app = create_app()
    app.config["TESTING"] = True
    return app.test_client()


def test_raw_document_equivalent_formats_have_bound_review_receipts(tmp_path, forbid_legacy):
    from app.services import model_translation as core

    model = ScriptedModel()
    target, receipt = core.translate_document(model, SOURCE, "zh")
    _proof(tmp_path, "document-review-proof", {"source": SOURCE, "target": target, "receipt": receipt, "trace": model.trace})
    assert target == TARGET
    assert core.valid_document_receipt(SOURCE, target, "zh", receipt)
    assert not core.valid_document_receipt(SOURCE + " changed", target, "zh", receipt)
    assert not core.valid_document_receipt(SOURCE, target.replace("37亿美元", "3.7亿美元"), "zh", receipt)
    assert not core.valid_document_receipt(SOURCE, target, "en", receipt)
    generated = [event for event in model.trace if event["stage"] == "translate"]
    assert any("$3.7 billion" in text and "October 22, 2026" in text
               for event in generated for text in event["payload"]["entries"].values())
    assert all(event["payload"]["context"].startswith("Document outline:") for event in model.trace)
    assert any(event["stage"] == "review" for event in model.trace)
    assert all(row["receipt"]["engine"] == core.ENGINE for row in receipt["sections"])


@pytest.mark.parametrize("corruption", ["unit", "negation"])
def test_semantic_rejection_is_bounded_to_one_repair(corruption, tmp_path, forbid_legacy):
    from app.services import model_translation as core

    source = "The company will not commission 25 MW."

    def corrupt(_source, target, _repair):
        return target.replace("25 MW", "25 kW") if corruption == "unit" else target.replace("不会", "会")

    model = ScriptedModel(mutate=corrupt)
    result = core.translate_entries(model, [("promise", source)], "zh", context="capacity decision", max_calls=20)
    assert "promise" not in result and "promise" not in result.receipts
    assert result.issues.get("promise")
    assert [event["stage"] for event in model.trace] == ["translate", "review", "repair", "review"]
    assert result.calls_used == 4
    assert all(event["payload"].get("entries", {}).get("promise", source) == source for event in model.trace)
    _proof(tmp_path, "semantic-rejection-" + corruption, {"trace": model.trace, "issues": result.issues})


def test_structural_repair_retries_only_the_failing_entry(tmp_path, forbid_legacy):
    from app.services import model_translation as core

    bad = "## Capacity and funding\n\n| Measure | Value |\n|---|---:|\n| Planned capacity | 25 MW |"
    good = "The baseline remains uncertain."

    def break_first(source, target, repair):
        return "产能与资金" if source == bad and not repair else target

    model = ScriptedModel(mutate=break_first)
    result = core.translate_entries(model, [("table", bad), ("baseline", good)], "zh", max_calls=8)
    assert dict(result) == {"table": _zh(bad), "baseline": _zh(good)}
    repairs = [event for event in model.trace if event["stage"] == "repair"]
    assert len(repairs) == 1 and set(repairs[0]["payload"]["entries"]) == {"table"}
    assert repairs[0]["payload"]["issues"]["table"]
    for key, source in (("table", bad), ("baseline", good)):
        assert core.valid_receipt(source, result[key], "zh", result.receipts[key])
        assert not core.valid_receipt(source, result[key], "zh", result.receipts[key], context="changed")
    assert result.calls_used <= 4
    _proof(tmp_path, "structural-repair", {"trace": model.trace, "receipts": result.receipts})


def test_real_report_generation_publication_get_download_and_persisted_reader(
    published, tmp_path, monkeypatch, forbid_legacy,
):
    from app.services import report_agent as module
    from app.services import model_translation as core
    from app.config import Config

    manager = module.ReportManager
    rid, folder, client = published["report"].report_id, published["folder"], published["client"]
    monkeypatch.setattr(Config, "REPORT_BILINGUAL", True)
    sealed = {name: (folder / name).read_bytes() for name in ("full_report.md", "forecast.json", "final_audit.json", "citations.json")}
    model = ScriptedModel()
    status = manager.generate_translation_variant(rid, "zh", llm_client=model)
    assert status["available"] is True, status
    assert manager.publication_status(rid, "zh")["publishable"]
    snapshot = manager.resolve_translation(rid, "zh")
    translated = snapshot.markdown.encode("utf-8")
    audit = snapshot.audit
    assert audit["hard_passed"] is True and core.ENGINE in json.dumps(audit)
    assert "委员会可能批准该提案" in translated.decode()
    assert audit["source_markdown_sha256"] == _sha(sealed["full_report.md"])
    assert audit["markdown_sha256"] == _sha(translated)
    assert all((folder / name).read_bytes() == before for name, before in sealed.items())
    localized, localization = manager.load_localized_forecast(rid, "zh")
    assert localization["complete"] is True, localization
    assert localized["scenarios"][0]["name"] == "基准情景"
    assert [row["probability"] for row in localized["scenarios"]] == [.7, .3]
    assert localized["binary_forecasts"][0]["id"] == "F1"
    assert localized["binary_forecasts"][0]["probability"] == .7
    assert localized["horizon"] == "2026-12-31"
    # The normal available-body POST repairs only the outstanding report display.
    # Keep the actual asynchronous job, native forecast reader and GET contract.
    monkeypatch.setattr("app.utils.llm_client.LLMClient", lambda: model)
    sidecar_proof = {path: path.read_bytes() for path in Path(snapshot.path).iterdir()}
    repaired = client.post(f"/api/report/{rid}/translations/zh")
    assert repaired.status_code == 200, repaired.json
    for _ in range(400):
        forecast_response = client.get(f"/api/report/{rid}/forecast?lang=zh")
        if forecast_response.status_code == 409:
            # A final generation switch can overlap polling. The public reader
            # fails closed on mixed snapshots; a fresh poll reconnects safely.
            assert forecast_response.json["code"] == "stale_artifact", forecast_response.json
            time.sleep(.01)
            continue
        assert forecast_response.status_code == 200, forecast_response.json
        forecast_view = forecast_response.json["data"]
        if forecast_view["structured_translation"]["status"] != "generating":
            break
        time.sleep(.01)
    assert forecast_view["structured_translation"]["complete"], forecast_view
    assert forecast_view["display"]["title"] == "委员会展望"
    assert forecast_view["forecast"]["scenarios"][0]["probability"] == .7
    assert all(path.read_bytes() == value for path, value in sidecar_proof.items())
    assert manager.resolve_translation(rid, "zh").markdown.encode() == translated
    assert any(event["stage"] == "review" for event in model.trace)
    metadata = client.get(f"/api/report/{rid}")
    assert metadata.status_code == 200, metadata.json
    assert any(row["lang"] == "zh" and row["available"] for row in metadata.json["data"]["translations"])
    assert client.get(f"/api/report/{rid}/full_report.zh.md").data == translated
    canonical_download = client.get(f"/api/report/{rid}/download")
    assert canonical_download.status_code == 200 and canonical_download.data == sealed["full_report.md"]
    # A freshly loaded manager class reads the persisted artifacts. Do not reload
    # the shared module in place and pollute other suites' class/exception aliases.
    spec = importlib.util.spec_from_file_location("app.services._model_acceptance_reader", module.__file__)
    reader = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, reader)
    spec.loader.exec_module(reader)
    monkeypatch.setattr(reader.ReportManager, "REPORTS_DIR", manager.REPORTS_DIR)
    monkeypatch.setattr(reader, "LLMClient", _forbid_provider)
    monkeypatch.setattr("app.utils.llm_client.LLMClient", _forbid_provider)
    assert reader.ReportManager.translation_status(rid, "zh")["available"]
    assert reader.ReportManager.publication_status(rid, "zh")["publishable"]
    assert client.get(f"/api/report/{rid}/full_report.zh.md").data == translated
    before_tamper = translated
    current_snapshot = manager.resolve_translation(rid, "zh")
    (Path(current_snapshot.path) / "document.md").write_bytes(translated + b"TAMPER")
    assert not manager.publication_status(rid, "zh")["publishable"]
    assert client.get(f"/api/report/{rid}/full_report.zh.md").status_code == 409
    assert client.get(f"/api/report/{rid}/download").status_code == 200
    _proof(tmp_path, "report-consumer-proof", {"status": status, "audit": audit, "trace": model.trace,
        "canonical": {key: _sha(value) for key, value in sealed.items()}, "translated_sha256": _sha(before_tamper)})


@pytest.mark.parametrize("corruption", ["null_receipt", "unreviewed_complete", "missing_engine"])
def test_forecast_api_does_not_trust_forged_completeness_or_null_receipts(
    published, tmp_path, monkeypatch, forbid_legacy, corruption,
):
    from app.services.report_agent import ReportManager
    from app.config import Config

    monkeypatch.setattr(Config, "REPORT_BILINGUAL", True)
    rid, folder, client = published["report"].report_id, published["folder"], published["client"]
    model = ScriptedModel()
    status = ReportManager.generate_translation_variant(rid, "zh", llm_client=model)
    assert status["available"], status
    localized, info = ReportManager.load_localized_forecast(rid, "zh")
    assert info["complete"] and localized["localization"]["receipts"], info
    canonical = ReportManager.load_structured_forecast(rid)
    path = folder / "forecast.zh.json"
    forged = json.loads(path.read_text())
    metadata = forged["localization"]
    metadata["complete"] = True
    if corruption == "null_receipt":
        metadata["receipts"][next(iter(metadata["receipts"]))] = None
    elif corruption == "unreviewed_complete":
        # The unchanged source is a permitted partial fallback; an asserted
        # complete flag alone must never upgrade it into reviewed Mandarin.
        metadata["receipts"] = {}
        forged = {**deepcopy(canonical), "localization": metadata}
    else:
        metadata.pop("engine")
    path.write_text(json.dumps(forged, ensure_ascii=False))
    # Hash-valid generation assets still need semantic field receipts. Seal the
    # forged display fixture so the actual immutable consumer, not an ignored
    # mutable sidecar, reaches its negative admission check.
    from app.services.translation.artifacts import publish_generation
    snapshot = ReportManager.resolve_translation(rid, "zh")
    snapshot = publish_generation(snapshot.root, kind=snapshot.kind, ref_id=rid, lang="zh",
        source_sha256=snapshot.source_sha256, markdown=snapshot.markdown, audit=snapshot.audit,
        source_path=folder / "full_report.md", assets={**snapshot.assets,
            "forecast.json": json.dumps(forged, ensure_ascii=False).encode()})
    proof_paths = [folder / name for name in ("full_report.md", "forecast.json", "final_audit.json")]
    proof_paths += [Path(snapshot.path) / name for name in ("document.md", "audit.json", "forecast.json")]
    sealed = {path: path.read_bytes() for path in proof_paths}
    calls = len(model.trace)
    monkeypatch.setattr("app.utils.llm_client.LLMClient", _forbid_provider)
    response = client.get(f"/api/report/{rid}/forecast?lang=zh")
    assert response.status_code == 200, response.json
    data = response.json["data"]
    assert data["localization"]["complete"] is False, data
    assert data["structured_translation"]["complete"] is False, data
    assert data["forecast"]["scenarios"] == canonical["scenarios"]
    assert data["forecast"]["binary_forecasts"] == canonical["binary_forecasts"]
    assert data["forecast"]["horizon"] == canonical["horizon"]
    assert ReportManager.is_publishable(rid, "zh")
    assert client.get(f"/api/report/{rid}/full_report.zh.md").data == snapshot.markdown.encode()
    assert all(path.read_bytes() == value for path, value in sealed.items())
    assert len(model.trace) == calls
    _proof(tmp_path, "forged-forecast-" + corruption, {"data": data, "forged_metadata": metadata,
        "canonical_sha256": _sha(json.dumps(canonical, sort_keys=True))})


@pytest.fixture
def research_source(tmp_path, monkeypatch):
    from app.api import research as api

    handoff = tmp_path / "handoff"
    handoff.mkdir()
    (handoff / "research_report.md").write_text(SOURCE, encoding="utf-8")
    (handoff / "actors.json").write_text(json.dumps({"central_question": "Will capacity increase?",
        "actors": [{"id": "A1", "name": "NVIDIA", "role": "Supplies infrastructure."}],
        "situation_brief": {"overview": "Supply is constrained."}, "hot_topics": ["Future growth."]}))
    (handoff / "data").mkdir()
    datasets = {"series": [{"series": "fred_UNRATE", "series_id": "GDP_USD", "label": "Economic output",
        "geography": "North America", "frequency": "Q", "first": "2026-01-01", "last": "2026-10-22",
        "latest": {"value": "1e-3", "date": "2026-10-22"}, "unit": "MW", "csv": "series/GDP_USD.csv"}]}
    (handoff / "data/datasets.json").write_text(json.dumps(datasets))
    monkeypatch.setattr(api.PipelineManager, "resolve_handoff_dir", lambda _pid: str(handoff))
    return api, handoff, datasets


def test_research_actual_worker_equivalent_formats_typed_projection_and_readonly_get(
    research_source, tmp_path, monkeypatch, forbid_legacy,
):
    api, handoff, datasets = research_source
    model = ScriptedModel()
    monkeypatch.setattr("app.utils.llm_client.LLMClient", lambda: model)
    client = _client()
    canonical = {str(path.relative_to(handoff)): path.read_bytes() for path in handoff.rglob("*") if path.is_file()}
    url = "/api/research/pipe_model_acceptance/dossier/translations/zh"
    response = client.post(url)
    assert response.status_code == 202, response.json
    data = _wait(client, url)
    _proof(tmp_path, "research-attempt", {"data": data, "trace": model.trace})
    assert data["available"] and data["structured_translation"]["complete"], data
    assert data["report"] == TARGET
    projected = data["dossier"]["datasets"]["series"][0]
    assert projected["label"] == "经济产出" and projected["geography"] == "北美洲"
    for key in ("series", "series_id", "frequency", "first", "last", "latest", "unit", "csv"):
        assert projected[key] == datasets["series"][0][key], (key, projected)
    assert data["dossier"]["actors"]["actors"][0]["id"] == "A1"
    assert all((handoff / name).read_bytes() == value for name, value in canonical.items())
    _, _, snapshot, audit = api._research_artifact(str(handoff), "zh", "pipe_model_acceptance")
    assert snapshot is not None
    assert audit["hard_passed"] and "model-translation/v1" in json.dumps(audit)
    calls = len(model.trace)
    monkeypatch.setattr("app.utils.llm_client.LLMClient", _forbid_provider)
    assert client.get(url).json["data"]["report"] == TARGET
    assert client.get("/api/research/pipe_model_acceptance/dossier?lang=zh").json["data"]["dossier"] == data["dossier"]
    assert len(model.trace) == calls
    (Path(snapshot.path) / "document.md").write_text(TARGET + "TAMPER")
    assert not client.get(url).json["data"]["available"]
    assert client.get("/api/research/pipe_model_acceptance/dossier/pdf?lang=zh").status_code == 409
    _proof(tmp_path, "research-consumer-proof", {"data": data, "audit": audit, "trace": model.trace,
        "canonical": {key: _sha(value) for key, value in canonical.items()}})


def test_research_source_change_during_real_model_transport_cannot_publish(
    research_source, monkeypatch, forbid_legacy,
):
    _api, handoff, _datasets = research_source
    model = ScriptedModel(after_generation=lambda: (handoff / "research_report.md").write_text(
        "# Replacement source\n\nA different current claim.\n"))
    monkeypatch.setattr("app.utils.llm_client.LLMClient", lambda: model)
    client = _client()
    url = "/api/research/pipe_model_race/dossier/translations/zh"
    response = client.post(url)
    assert response.status_code == 202
    job_id = response.json["data"]["translation_job"]["job_id"]
    from app.services.translation import scheduler
    for _ in range(400):
        job = scheduler.status(job_id)
        if job["job_state"] not in {"queued", "running"}:
            break
        time.sleep(.01)
    assert job["job_state"] == "failed", job
    data = _wait(client, url)
    assert data["status"] == "unavailable" and not data["available"], data
    # The new source must not inherit the old operation's authority or content.
    assert not data.get("translation_job")
    assert not (handoff / "research_report.zh.md").exists()
    assert not list(handoff.rglob("current.json"))
    assert model.trace and model.trace[0]["stage"] == "translate"


@pytest.mark.parametrize("corruption", ["unit", "negation"])
def test_research_public_consumer_cannot_publish_semantically_rejected_body(
    research_source, tmp_path, monkeypatch, forbid_legacy, corruption,
):
    _api, handoff, _datasets = research_source

    def corrupt(source, target, _repair):
        if "$3.7 billion" not in source:
            return target
        return target.replace("25 MW", "25 kW") if corruption == "unit" else target.replace("不会", "会")

    model = ScriptedModel(mutate=corrupt)
    monkeypatch.setattr("app.utils.llm_client.LLMClient", lambda: model)
    client = _client()
    url = "/api/research/pipe_model_rejected/dossier/translations/zh"
    assert client.post(url).status_code == 202
    data = _wait(client, url)
    assert not data["available"] and data["status"] == "failed", data
    assert not (handoff / "research_report.zh.md").exists()
    assert (handoff / "research_report.md").read_text() == SOURCE
    reviews = [event for event in model.trace if event["stage"] == "review"]
    assert any(not verdict["faithful"] for event in reviews for verdict in event["response"]["reviews"].values())
    repairs = [event for event in model.trace if event["stage"] == "repair"]
    assert len(repairs) == 1 and len(repairs[0]["payload"]["entries"]) == 1
    # There is no admitted publication to export. A missing translation is404;
    # an existing stale/corrupt generation is409 (covered by the tamper scenario).
    assert client.get("/api/research/pipe_model_rejected/dossier/pdf?lang=zh").status_code == 404
    _proof(tmp_path, "research-rejected-" + corruption, {"data": data, "trace": model.trace})


def test_simulation_actual_visible_post_poll_cache_restart_and_tamper(
    tmp_path, monkeypatch, forbid_legacy,
):
    from app.services import artifact_translation as at
    from app.config import Config

    root = tmp_path / "simulations"
    folder = root / "sim_restarted"
    folder.mkdir(parents=True)
    monkeypatch.setattr(Config, "OASIS_SIMULATION_DATA_DIR", str(root))
    model = ScriptedModel()
    monkeypatch.setattr("app.utils.llm_client.LLMClient", lambda: model)
    client = _client()
    from app.services.simulation_manager import SimulationManager, SimulationState
    from app.services.world_simulation.examples import example_spec, ExamplePolicy
    from app.services.world_simulation.service import run_child
    from app.services.world_simulation.results import read_result
    monkeypatch.setattr(Config, "UPLOAD_FOLDER", str(tmp_path / "uploads"))
    manager = SimulationManager()
    manager.SIMULATION_DATA_DIR = str(root)
    manager._save_simulation_state(SimulationState(simulation_id="sim_restarted",
        project_id="project_fixture", graph_id="graph_fixture", simulation_engine="world-v1"))
    raw = example_spec()
    raw.pop("simulationId")
    raw.pop("generationId")
    raw["actors"][0]["beliefs"] = ["A private decision with 25 MW.", "The next decision."]
    state = manager.prepare_world_simulation("sim_restarted", raw_spec=raw,
        research_report="Synthetic source fixture.", research_generation_id="research_fixture", research_engine="v3")
    assert run_child(folder, policy=ExamplePolicy("investment")) == 0
    actual = read_result(folder, view="actor", actor_id="producer")
    context = {"engine": "world-v1", "view": "actor", "actor_id": "producer",
        "round": actual["round"], "revision": actual["revision"], "generation_id": state.world_generation_id}
    base = "/api/simulation/sim_restarted/translations/zh"
    response = client.post(base, json={"texts": ["A private decision with 25 MW."], "context": context})
    assert response.status_code in (200, 202), response.json
    query = {"request_digest": response.json["data"]["request_digest"], "context": json.dumps(context)}
    data = _wait(client, base, query_string=query)
    assert data["status"] == "available" and data["context"] == context, data
    assert data["translations"][0]["text"] == _zh("A private decision with 25 MW.")
    assert {event["stage"] for event in model.trace} == {"translate", "review"}
    calls = len(model.trace)
    response = client.post(base, json={"texts": ["A private decision with 25 MW.", "The next decision."], "context": context})
    grown_query = {"request_digest": response.json["data"]["request_digest"], "context": json.dumps(context)}
    grown = _wait(client, base, query_string=grown_query)
    assert grown["status"] == "available" and len(grown["translations"]) == 2
    assert len(model.trace) == calls + 2, model.trace
    for event in model.trace[calls:]:
        sources = event["payload"].get("entries") or {key: pair["source"] for key, pair in event["payload"]["pairs"].items()}
        assert list(sources.values()) == ["The next decision."], sources
    monkeypatch.setattr("app.utils.llm_client.LLMClient", _forbid_provider)
    assert client.get(base).json["data"]["translations"] == []
    assert client.get(base, query_string={"request_digest": query["request_digest"]}).status_code == 400
    assert client.get(base, query_string={"request_digest": query["request_digest"], "context": json.dumps({"view": "public"})}).status_code == 400
    assert client.get(base, query_string=query).json["data"]["translations"] == data["translations"]
    # Reuse the existing admitted restart reader rather than registering a new
    # child test entrypoint. It exercises the actual Flask GET with no provider.
    output = tmp_path / "restart-reader.json"
    child = Path(__file__).with_name("test_artifact_translation_restart.py")
    completed = subprocess.run([sys.executable, "-B", str(child), "--read", str(root),
        data["request_digest"], json.dumps(context), str(output), str(Config.UPLOAD_FOLDER)],
        capture_output=True, text=True, timeout=60, check=False)
    assert completed.returncode == 0, completed.stderr[-5000:]
    restarted = json.loads(output.read_text())
    assert restarted["status"] == 200 and restarted["data"]["translations"] == data["translations"]
    assert restarted["default_count"] == 0 and restarted["wrong_context_status"] == 400
    assert client.post(base, json={"texts": ["A private decision with 25 MW."],
        "context": {**context, "view": "public"}}).status_code == 400
    cache_path = Path(at._inventory("simulation", "sim_restarted", "zh",
        texts=["A private decision with 25 MW."], context=context)[0])
    cache = json.loads(cache_path.read_text())
    row = next(iter(cache["entries"].values()))
    row["text"] = "遭到篡改的25 kW决策。"
    # A matching superficial checksum cannot substitute for the source/target
    # semantic receipt retained by the new cache.
    row["text_sha256"] = _sha(row["text"])
    cache_path.write_text(json.dumps(cache, ensure_ascii=False))
    tampered = client.get(base, query_string=query).json["data"]
    assert tampered["status"] != "available" and not tampered["translations"], tampered
    _proof(tmp_path, "simulation-consumer-proof", {"initial": data, "grown": grown,
        "restart": restarted, "tamper": tampered, "trace": model.trace})
