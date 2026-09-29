"""Translated report views: fresh retries, forecast language, localized dashboard.

Regression context (report_d79a064bf5cc): the English report's forecast.json had a
Chinese headline/scenarios (the spine prompt had no output-language rule) and English
binary forecasts; the dashboard renders forecast.json in every view, so "Translate to
中文" looked like it translated the top and stopped at the binary-forecast table.  The
retry replayed cached model responses, so it could never succeed in-process.
"""

from __future__ import annotations

import hashlib
import json
import re

import pytest

from app.config import Config
from app.services import forecast_extractor as fe
from app.services.report_agent import Report, ReportAgent, ReportManager, ReportStatus
from app.utils.telemetry import LLMCache


@pytest.fixture
def reports_tmp(tmp_path, monkeypatch):
    reports_dir = tmp_path / "reports"
    reports_dir.mkdir()
    monkeypatch.setattr(ReportManager, "REPORTS_DIR", str(reports_dir))
    return reports_dir


# ────────────────────────────── cache bypass ──────────────────────────────
def test_llm_cache_bypass_neither_reads_nor_writes():
    LLMCache.put("bypass-probe", "cached")
    with LLMCache.bypass():
        assert LLMCache.bypassed() is True
        assert LLMCache.get("bypass-probe") is None
        LLMCache.put("bypass-probe-2", "written")
    assert LLMCache.bypassed() is False
    assert LLMCache.get("bypass-probe") == "cached"
    assert LLMCache.get("bypass-probe-2") is None


# ─────────────────────────── fake translator ───────────────────────────
def _cjk_word(word: str) -> str:
    return "".join(chr(0x4E00 + (ord(ch.lower()) - 97) % 40) for ch in word[:3]) or "词"


def _to_zh(value: str) -> str:
    parts = re.split(r"(⟦[^⟧]*⟧)", value)
    return "".join(
        part if part.startswith("⟦") else re.sub(
            r"(?<![A-Za-z0-9])[A-Za-z][A-Za-z'’-]*",
            lambda m: _cjk_word(re.sub(r"[^A-Za-z]", "", m.group(0))),
            part,
        )
        for part in parts
    )


def _to_en(value: str) -> str:
    parts = re.split(r"(⟦[^⟧]*⟧)", value)
    return "".join(
        part if part.startswith("⟦") else re.sub(
            r"[一-鿿]+", lambda m: " word" * len(m.group(0)) + " ", part
        )
        for part in parts
    )


class Translator:
    """Keyed-slot / whole-unit / fragment protocols; direction from the prompt."""

    model = "fake-translator"
    provider = "fake"

    def __init__(self):
        self.bypass_seen = []
        self.calls = 0

    def _translate(self, system: str, text: str) -> str:
        return _to_en(text) if "English" in system else _to_zh(text)

    def chat(self, messages=None, temperature=0.0, max_tokens=4096, tier="strong", **_kw):
        self.calls += 1
        self.bypass_seen.append(LLMCache.bypassed())
        system, user = messages[0]["content"], messages[-1]["content"]
        if "same alphabetic keys" in system:
            return json.dumps(
                {key: self._translate(system, core) for key, core in json.loads(user).items()},
                ensure_ascii=False,
            )
        return self._translate(system, user)

    def chat_json(self, messages=None, temperature=0.0, max_tokens=4096, tier="fast", **_kw):
        self.calls += 1
        self.bypass_seen.append(LLMCache.bypassed())
        out = {}
        for line in messages[-1]["content"].splitlines():
            match = re.match(r"^(\d+)\.\s+(.*)$", line)
            if match:
                out[match.group(1)] = self._translate(messages[0]["content"], match.group(2))
        return out


def _agent(llm):
    agent = ReportAgent.__new__(ReportAgent)
    agent.llm = llm
    agent.output_language = "English"
    agent.simulation_id = "sim_test"
    agent.graph_id = "graph_test"
    agent._forecast_spine = None
    return agent


# A forecast shaped like report_d79a064bf5cc's: Chinese spine, English binaries.
_FORECAST = {
    "headline": "到2040年美国可能率先实现早期容错量子计算",
    "horizon": "2040-12-31",
    "scenarios": [
        {"name": "稳步爬升", "probability": 0.6, "summary": "路线图大体兑现",
         "key_drivers": ["纠错突破"], "resolution_criteria": "到2033年验证100个逻辑比特"},
        {"name": "其它/未预期路径", "probability": 0.4, "summary": "其余路径",
         "key_drivers": ["混合结果"], "resolution_criteria": "不满足其他情景"},
    ],
    "key_uncertainties": ["纠错开销"],
    "confidence": "low",
    "confidence_rationale": "预测跨度长",
    "binary_forecasts": [{
        "id": "F1",
        "statement": "By December 31, 2033, a vendor runs 100 verified logical qubits.",
        "probability": 0.45,
        "adjustment_rationale": "Vendor roadmaps cluster earlier but usually slip.",
        "scenario_membership": {"derivable": True, "yes_scenarios": ["稳步爬升"]},
        "market_anchor": {"question": "Will IBM ship Starling by 2029?", "implied_yes_prob": 0.3},
    }],
    "market_comparison": {"comparisons": []},
}


def _seal_forecast(report_id: str, forecast: dict, markdown: str) -> str:
    report = Report(
        report_id=report_id,
        simulation_id="sim_test",
        graph_id="graph_test",
        simulation_requirement="Forecast quantum computing by 2040.",
        status=ReportStatus.COMPLETED,
        markdown_content=markdown,
    )
    ReportManager.save_report(report)
    text = json.dumps(forecast, ensure_ascii=False, indent=2)
    folder = ReportManager._get_report_folder(report_id)
    with open(f"{folder}/forecast.json", "w", encoding="utf-8") as handle:
        handle.write(text)
    audit = {
        "policy_version": 3,
        "hard_passed": True,
        "hard_issues": [],
        "markdown_sha256": hashlib.sha256(markdown.encode("utf-8")).hexdigest(),
        "publish_gate": {"enabled": True, "passed": True},
        "forecast_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "structured_forecast": {"required": True, "present": True, "valid": True},
        "scenario_contract": {"valid": True, "issue_count": 0},
        "citation_artifacts": {"required": False, "passed": True},
    }
    with open(ReportManager._get_report_final_audit_path(report_id), "w", encoding="utf-8") as h:
        json.dump(audit, h)
    return audit["forecast_sha256"]


_MARKDOWN = (
    "# Quantum Outlook\n\n"
    "## Executive Forecast\n\n"
    "The base case holds at 60% while other paths share 40%.\n"
)


# ───────────────────────── forecast localization ─────────────────────────
def test_localize_forecast_translates_only_foreign_reader_strings():
    zh, summary = _agent(Translator())._localize_forecast(_FORECAST, "zh")
    binary = zh["binary_forecasts"][0]
    assert not re.search(r"[A-Za-z]{4,}", binary["statement"])
    assert "2033年12月31日" in binary["statement"]
    assert binary["probability"] == 0.45
    # Chinese strings were already in the target language and are byte-identical.
    assert zh["scenarios"] == _FORECAST["scenarios"]
    assert zh["headline"] == _FORECAST["headline"]
    # External market questions are provenance, not translated.
    assert binary["market_anchor"] == _FORECAST["binary_forecasts"][0]["market_anchor"]
    assert summary["complete"] is True and summary["unresolved"] == []

    en, summary = _agent(Translator())._localize_forecast(_FORECAST, "en")
    assert not re.search(r"[一-鿿]", json.dumps(
        [en["headline"], en["scenarios"], en["key_uncertainties"], en["confidence_rationale"]],
        ensure_ascii=False,
    ))
    assert [s["probability"] for s in en["scenarios"]] == [0.6, 0.4]
    assert "2033" in en["scenarios"][0]["resolution_criteria"]
    # Scenario names referenced by value follow their translation.
    assert en["binary_forecasts"][0]["scenario_membership"]["yes_scenarios"] == [
        en["scenarios"][0]["name"]
    ]
    assert summary["complete"] is True


def test_localized_forecast_is_bound_to_the_sealed_bytes(reports_tmp):
    rid = "report_forecast_localized"
    sha = _seal_forecast(rid, _FORECAST, _MARKDOWN)
    llm = Translator()
    meta = _agent(llm)._ensure_localized_forecast(rid, "zh")
    assert meta and meta["source_forecast_sha256"] == sha and meta["complete"] is True
    forecast, info = ReportManager.load_localized_forecast(rid, "zh")
    assert info == {"requested_lang": "zh", "localized": True, "complete": True}
    assert "2033年12月31日" in forecast["binary_forecasts"][0]["statement"]

    # A fresh, complete copy is reused without model calls.
    calls = llm.calls
    _agent(llm)._ensure_localized_forecast(rid, "zh")
    assert llm.calls == calls

    # Once forecast.json changes, the copy is stale and the sealed original wins.
    _seal_forecast(rid, {**_FORECAST, "headline": "新的结论"}, _MARKDOWN)
    forecast, info = ReportManager.load_localized_forecast(rid, "zh")
    assert info["localized"] is False and forecast["headline"] == "新的结论"


def test_forecast_without_foreign_strings_needs_no_copy(reports_tmp):
    rid = "report_forecast_native"
    english = {
        "headline": "The US likely leads early fault tolerance.",
        "scenarios": [{"name": "Steady Climb", "probability": 1.0}],
    }
    _seal_forecast(rid, english, _MARKDOWN)
    llm = Translator()
    assert _agent(llm)._ensure_localized_forecast(rid, "en") is None
    assert llm.calls == 0
    forecast, info = ReportManager.load_localized_forecast(rid, "en")
    assert forecast == english and info["localized"] is False


def test_forecast_endpoint_serves_the_requested_language(reports_tmp):
    from app import create_app

    rid = "report_forecast_endpoint_lang"
    _seal_forecast(rid, _FORECAST, _MARKDOWN)
    _agent(Translator())._ensure_localized_forecast(rid, "en")
    client = create_app().test_client()

    original = client.get(f"/api/report/{rid}/forecast").get_json()["data"]
    assert original["forecast"]["headline"] == _FORECAST["headline"]
    assert original["localization"]["localized"] is False

    english = client.get(f"/api/report/{rid}/forecast?lang=en").get_json()["data"]
    assert english["localization"]["localized"] is True
    assert not re.search(r"[一-鿿]", english["forecast"]["headline"])

    # No zh copy exists: the sealed original is served, flagged as not localized.
    chinese = client.get(f"/api/report/{rid}/forecast?lang=zh").get_json()["data"]
    assert chinese["forecast"]["headline"] == _FORECAST["headline"]
    assert chinese["localization"]["localized"] is False

    assert client.get(f"/api/report/{rid}/forecast?lang=fr").status_code == 400


def test_bilingual_run_localizes_dashboards_under_a_cache_bypass(reports_tmp, monkeypatch):
    rid = "report_bilingual_dashboard"
    _seal_forecast(rid, _FORECAST, _MARKDOWN)
    report = ReportManager.get_report(rid)
    llm = Translator()
    agent = _agent(llm)
    order = []
    original_status = ReportManager._set_translation_runtime_status.__func__

    def _status(cls, report_id, lang, status, **kwargs):
        order.append(("status", lang, status))
        return original_status(cls, report_id, lang, status, **kwargs)

    original_ensure = ReportAgent._ensure_localized_forecast

    def _ensure(self, report_id, lang, progress=None):
        order.append(("localize", lang))
        return original_ensure(self, report_id, lang, progress=progress)

    monkeypatch.setattr(ReportManager, "_set_translation_runtime_status", classmethod(_status))
    monkeypatch.setattr(ReportAgent, "_ensure_localized_forecast", _ensure)
    monkeypatch.setattr(Config, "REPORT_TRANSLATION_CONCURRENCY", 1)

    agent._generate_bilingual_report(rid, report)

    assert llm.bypass_seen and all(llm.bypass_seen)
    assert LLMCache.bypassed() is False
    assert ("status", "zh", "available") in order
    assert order.index(("localize", "zh")) < order.index(("status", "zh", "available"))
    assert ("localize", "en") in order
    zh, zh_info = ReportManager.load_localized_forecast(rid, "zh")
    en, en_info = ReportManager.load_localized_forecast(rid, "en")
    assert zh_info["localized"] and en_info["localized"]
    assert not re.search(r"[一-鿿]", en["headline"])
    assert "2033年12月31日" in zh["binary_forecasts"][0]["statement"]


# ─────────────────────────── forecast language ───────────────────────────
class _PromptSpy:
    def __init__(self, reply):
        self.prompts = []
        self._reply = reply

    def chat_json(self, messages=None, **_kw):
        self.prompts.append(messages[-1]["content"])
        return json.loads(json.dumps(self._reply))


_SPINE_REPLY = {
    "headline": "The US likely leads.",
    "scenarios": [
        {"name": "Steady Climb", "probability": 0.7, "resolution_criteria": "x"},
        {"name": "Other / Status Quo", "probability": 0.3, "resolution_criteria": "y"},
    ],
    "confidence": "low",
}


def test_forecast_language_rule_reaches_every_forecast_prompt(monkeypatch):
    spy = _PromptSpy(_SPINE_REPLY)
    fe.derive_forecast_spine(spy, central_question="q", language="English")
    fe.extract_structured_forecast("# Report", spy, language="English")
    fe.self_critique_forecast(dict(_SPINE_REPLY), spy, language="English")
    monkeypatch.setattr(Config, "REPORT_PREMORTEM", True, raising=False)
    fe.premortem_forecast(dict(_SPINE_REPLY), spy, language="English")
    assert len(spy.prompts) == 4
    assert all("[OUTPUT LANGUAGE]" in prompt and "in English" in prompt for prompt in spy.prompts)

    chinese = _PromptSpy(_SPINE_REPLY)
    fe.derive_forecast_spine(chinese, central_question="q", language="Chinese")
    assert "【输出语言】" in chinese.prompts[0]

    legacy = _PromptSpy(_SPINE_REPLY)
    fe.derive_forecast_spine(legacy, central_question="q")
    assert "[OUTPUT LANGUAGE]" not in legacy.prompts[0]
    assert "【输出语言】" not in legacy.prompts[0]


def test_report_agent_passes_its_output_language_to_the_spine(reports_tmp, monkeypatch):
    captured = {}

    def _spine(llm, **kwargs):
        captured.update(kwargs)
        return {}

    monkeypatch.setattr(fe, "derive_forecast_spine", _spine)
    agent = _agent(Translator())
    agent.actors = {}
    agent.simulation_requirement = "Forecast quantum computing by 2040."
    agent.situation_brief = ""
    agent._signal_pack = ""
    agent._market_pack = "none"
    agent._temporal_horizon_date = lambda: "2040-12-31"
    agent._derive_and_pin_forecast_spine("report_spine_language")
    assert captured["language"] == "English"
