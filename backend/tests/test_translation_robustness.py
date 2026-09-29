"""Translation robustness: residual tolerance, last-resort line repair, orphaned jobs.

A single untranslated line used to withhold an entire otherwise-verified translation,
and a backend restart during a translation left "generating" on disk, blocking the
retry for the full 15-minute heartbeat timeout.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys

import pytest

from app.config import Config
from app.services.report_agent import Report, ReportAgent, ReportManager, ReportStatus


def _worker(llm=None):
    worker = ReportAgent.__new__(ReportAgent)
    worker.llm = llm
    worker.output_language = "English"
    worker._forecast_spine = None
    return worker


_ENGLISH_LINE = "The committee kept this sentence in English because the model refused it."
_ENGLISH_LINES = (
    _ENGLISH_LINE,
    "A second paragraph also stayed in English after every repair attempt failed.",
    "The third paragraph likewise remained untranslated despite the retry ladder.",
)
_SOURCE = (
    "# 标题\n\n## 第一部分\n\n"
    "First paragraph of the source report.\n\n"
    "Second paragraph of the source report.\n\n"
    "Third paragraph of the source report.\n"
)


def _variant(residual_lines: int) -> str:
    body = ["# 标题", "", "## 第一部分", ""]
    chinese = ["第一段落的译文内容。", "第二段落的译文内容。", "第三段落的译文内容。"]
    for index, sentence in enumerate(chinese):
        body.append(_ENGLISH_LINES[index] if index < residual_lines else sentence)
        body.append("")
    return "\n".join(body).rstrip() + "\n"


def test_residual_tolerance_scales_with_length_and_can_be_strict(monkeypatch):
    long_body = "\n".join(f"line {index}" for index in range(700))
    assert ReportAgent._translation_residual_tolerance(long_body) == 3
    assert ReportAgent._translation_residual_tolerance("a\nb\nc") == 1
    monkeypatch.setattr(Config, "REPORT_TRANSLATION_RESIDUAL_LINES", 0)
    assert ReportAgent._translation_residual_tolerance(long_body) == 0


def test_one_residual_line_publishes_with_a_warning_not_a_withheld_report():
    audit, _citations = _worker()._audit_translation_variant(
        "report_residual", _SOURCE, _variant(1), "en", "zh", {}, enforce_citations=False
    )
    assert audit["hard_passed"] is True, audit["issues"]
    assert audit["residual_source_lines"]["count"] == 1
    assert audit["warnings"] and "source-language" in audit["warnings"][0]


def test_residual_lines_beyond_tolerance_or_strict_mode_still_fail(monkeypatch):
    audit, _ = _worker()._audit_translation_variant(
        "report_residual", _SOURCE, _variant(2), "en", "zh", {}, enforce_citations=False
    )
    assert audit["hard_passed"] is False
    assert any("target-language contamination" in issue for issue in audit["issues"])

    monkeypatch.setattr(Config, "REPORT_TRANSLATION_RESIDUAL_LINES", 0)
    audit, _ = _worker()._audit_translation_variant(
        "report_residual", _SOURCE, _variant(1), "en", "zh", {}, enforce_citations=False
    )
    assert audit["hard_passed"] is False


class _LastResortTranslator:
    """Refuses (echoes) until the last-resort retry prompt appears."""

    model = "fake"
    provider = "fake"

    def __init__(self, succeed=True):
        self.succeed = succeed
        self.prompts = []

    def chat(self, messages=None, temperature=0.0, max_tokens=4096, tier="strong", **_kw):
        system, user = messages[0]["content"], messages[-1]["content"]
        self.prompts.append(system)
        if self.succeed and "LAST-RESORT" in system:
            return "委员会保留了这句话。"
        if "same alphabetic keys" in system:
            return json.dumps(json.loads(user), ensure_ascii=False)
        return user

    def chat_json(self, messages=None, **_kw):
        return {}


def test_last_resort_translates_the_whole_residual_line():
    llm = _LastResortTranslator()
    markdown = "# 标题\n\n" + _ENGLISH_LINE + "\n\n## References\n\n- [S1] An English source title that stays verbatim in references\n"
    repaired = _worker(llm)._retranslate_residual_lines(
        markdown, True, "简体中文（Simplified Chinese）"
    )
    assert "委员会保留了这句话。" in repaired
    assert _ENGLISH_LINE not in repaired
    # The References appendix is provenance, never retranslated.
    assert "An English source title that stays verbatim in references" in repaired


def test_last_resort_keeps_the_line_when_no_candidate_is_clean():
    llm = _LastResortTranslator(succeed=False)
    markdown = "# 标题\n\n" + _ENGLISH_LINE + "\n"
    repaired = _worker(llm)._retranslate_residual_lines(
        markdown, True, "简体中文（Simplified Chinese）"
    )
    assert _ENGLISH_LINE in repaired


@pytest.fixture
def reports_tmp(tmp_path, monkeypatch):
    reports_dir = tmp_path / "reports"
    reports_dir.mkdir()
    monkeypatch.setattr(ReportManager, "REPORTS_DIR", str(reports_dir))
    return reports_dir


def _dead_pid() -> int:
    proc = subprocess.Popen([sys.executable, "-c", "pass"])
    proc.wait()
    return proc.pid


def test_translation_owned_by_a_dead_process_is_retryable_immediately(reports_tmp):
    import hashlib

    assert ReportManager._translation_owner_alive(f"pid:{os.getpid()}") is True
    assert ReportManager._translation_owner_alive("worker-7") is True
    dead = _dead_pid()
    assert ReportManager._translation_owner_alive(f"pid:{dead}") is False

    rid = "report_orphaned_translation"
    markdown = "# EV Forecast\n\nEnglish report body for translation.\n"
    ReportManager.save_report(Report(
        report_id=rid, simulation_id="sim", graph_id="graph",
        simulation_requirement="req", status=ReportStatus.COMPLETED,
        markdown_content=markdown,
    ))
    with open(ReportManager._get_report_final_audit_path(rid), "w", encoding="utf-8") as f:
        json.dump({
            "policy_version": 3, "hard_passed": True, "hard_issues": [],
            "markdown_sha256": hashlib.sha256(markdown.encode("utf-8")).hexdigest(),
            "publish_gate": {"enabled": True, "passed": True},
            "structured_forecast": {"required": False, "valid": True},
            "citation_artifacts": {"required": False, "passed": True},
        }, f)
    source_sha = hashlib.sha256(markdown.encode("utf-8")).hexdigest()
    ReportManager._set_translation_runtime_status(
        rid, "zh", "generating", source_markdown_sha256=source_sha,
        owner=f"pid:{dead}", progress=40, message="translated 5/19 report sections",
    )
    state = ReportManager.translation_status(rid, "zh")
    assert state["status"] == "interrupted"
    assert state["can_generate"] is True

    ReportManager._set_translation_runtime_status(
        rid, "zh", "generating", source_markdown_sha256=source_sha,
        owner=f"pid:{os.getpid()}", progress=40, message="translated 5/19 report sections",
    )
    assert ReportManager.translation_status(rid, "zh")["status"] == "generating"


def test_dossier_translation_owned_by_a_dead_process_reports_interrupted(tmp_path, monkeypatch):
    from app import create_app
    from app.api import research as research_api

    handoff = tmp_path / "handoff"
    handoff.mkdir()
    (handoff / "research_report.md").write_text("# Report\n\nEnglish body.\n", encoding="utf-8")
    monkeypatch.setattr(
        research_api.PipelineManager, "resolve_handoff_dir",
        classmethod(lambda cls, _pipeline_id: str(handoff)),
    )
    status_path = handoff / "research_report.translation.zh.json"
    client = create_app().test_client()

    status_path.write_text(json.dumps({
        "status": "generating", "available": False, "owner": f"pid:{_dead_pid()}",
    }), encoding="utf-8")
    data = client.get("/api/research/pipe_test/dossier/translations/zh").get_json()["data"]
    assert data["status"] == "interrupted" and data["issues"]

    status_path.write_text(json.dumps({
        "status": "generating", "available": False, "owner": f"pid:{os.getpid()}",
    }), encoding="utf-8")
    data = client.get("/api/research/pipe_test/dossier/translations/zh").get_json()["data"]
    assert data["status"] == "generating"


def test_rejected_translation_names_provider_failures():
    class Down:
        model = "fake"
        provider = "fake"

        def chat(self, *args, **kwargs):
            raise RuntimeError("Connection error.")

        def chat_json(self, *args, **kwargs):
            raise RuntimeError("Connection error.")

    source = "# Title\n\n## Part\n\nThe committee published the whole outlook in English only.\n"
    result = _worker(Down()).translate_research_markdown(source)
    assert result["available"] is False
    assert "translation model call(s) failed" in result["issues"][0]


def test_translation_calls_carry_a_bounded_request_timeout(monkeypatch):
    from types import SimpleNamespace

    from app.utils import llm_client as lc

    captured = []

    class _Completions:
        @staticmethod
        def create(**kwargs):
            captured.append(kwargs)
            message = SimpleNamespace(content="好")
            choice = SimpleNamespace(message=message, finish_reason="stop")
            return SimpleNamespace(choices=[choice], usage=None)

    client = object.__new__(lc.LLMClient)
    client.provider = "glm"
    client.model = "glm-5.3"
    client._openai_client = SimpleNamespace(chat=SimpleNamespace(completions=_Completions()))
    client._fast_openai_client = None
    client._is_fallback = False
    client._last_usage = None
    monkeypatch.setattr(Config, "LLM_TIERED_ROUTING", False, raising=False)

    client._chat_openai([{"role": "user", "content": "hi"}], 0.0, 16)
    with lc.llm_call_timeout(240):
        client._chat_openai([{"role": "user", "content": "hi"}], 0.0, 16)
    client._chat_openai([{"role": "user", "content": "hi"}], 0.0, 16)
    assert "timeout" not in captured[0]
    assert captured[1]["timeout"] == 240.0
    assert "timeout" not in captured[2]


def test_integrity_retries_run_concurrently(reports_tmp, monkeypatch):
    """Sections that need an integrity retry are retried in parallel: two retry calls
    must meet at a barrier, which would time out if they ran one after another."""
    import threading

    monkeypatch.setattr(Config, "REPORT_TRANSLATION_CONCURRENCY", 4)
    barrier = threading.Barrier(2, timeout=5)
    met = []

    class RetryNeedsPeers:
        model = "fake"
        provider = "fake"

        def chat(self, messages=None, temperature=0.0, max_tokens=4096, tier="strong", **_kw):
            system, user = messages[0]["content"], messages[-1]["content"]
            if "INTEGRITY RETRY" in system:
                try:
                    barrier.wait()
                    met.append(True)
                except threading.BrokenBarrierError:
                    met.append(False)
                return "## 第一部分\n\n这一节已经完整翻译成中文了。"
            if "same alphabetic keys" in system:
                return json.dumps(json.loads(user), ensure_ascii=False)  # refuse → English
            return user

        def chat_json(self, messages=None, **_kw):
            return {}

    sections = "".join(
        f"## Part {name}\n\nThis section stays in English because the model refused it here.\n\n"
        for name in ("One", "Two")
    )
    report = Report(
        report_id="report_parallel_retries", simulation_id="sim", graph_id="graph",
        simulation_requirement="req", status=ReportStatus.COMPLETED,
        markdown_content="# Title\n\n" + sections,
    )
    ReportManager.save_report(report)
    _worker(RetryNeedsPeers())._generate_bilingual_report("report_parallel_retries", report)
    assert met and all(met), "integrity retries did not overlap"
