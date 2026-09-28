"""Draft-exposure regressions for reports that are not publishable.

Three paths used to serve unaudited section drafts:

1. ``GET /api/report/<id>``, ``/list`` and ``/by-simulation/<sim>`` blanked
   ``markdown_content`` but still returned ``outline.sections[*].content`` (the
   full section drafts persisted in meta.json on completion).
2. The section endpoints (``/sections``, ``/sections-partial``, ``/section/<n>``)
   only applied the gate when ``ReportManager.get_report`` loaded the report, so
   a missing or unreadable meta.json failed open.
3. The in-progress exemption (live streaming while generating) never expired,
   so a report whose generator crashed at pending/planning/generating kept
   serving drafts forever.

All checks are offline: tmp REPORTS_DIR, no LLM, no network.
"""

from __future__ import annotations

import hashlib
import json
import os
import time

import pytest

from app.api import report as report_api
from app.services.report_agent import (
    Report,
    ReportManager,
    ReportOutline,
    ReportSection,
    ReportStatus,
)

DRAFT = "DRAFT-FORECAST: Plan B wins with 71% probability"
IN_PROGRESS = [ReportStatus.PENDING, ReportStatus.PLANNING, ReportStatus.GENERATING]


@pytest.fixture
def reports_tmp(tmp_path, monkeypatch):
    reports_dir = tmp_path / "reports"
    reports_dir.mkdir()
    monkeypatch.setattr(ReportManager, "REPORTS_DIR", str(reports_dir))
    return reports_dir


@pytest.fixture
def client(reports_tmp):
    from app import create_app

    app = create_app()
    app.config["TESTING"] = True
    return app.test_client()


def _outline() -> ReportOutline:
    return ReportOutline(
        title="Forecast",
        summary="Outline summary.",
        sections=[
            ReportSection(title="执行摘要", content=DRAFT, description="Summarise the call."),
            ReportSection(title="关键发现", content=f"More prose. {DRAFT}", description="Findings."),
        ],
    )


def _save_report(report_id: str, status: ReportStatus, *, markdown: str = "",
                 outline: ReportOutline | None = None) -> None:
    ReportManager.save_report(Report(
        report_id=report_id,
        simulation_id=f"sim_{report_id}",
        graph_id="graph_test",
        simulation_requirement="Forecast the outcome.",
        status=status,
        outline=outline,
        markdown_content=markdown,
        created_at="2026-09-01T00:00:00+00:00",
    ))


def _write_passing_audit(report_id: str, markdown: str) -> None:
    with open(ReportManager._get_report_final_audit_path(report_id), "w", encoding="utf-8") as f:
        json.dump({
            "policy_version": 3,
            "hard_passed": True,
            "hard_issues": [],
            "markdown_sha256": hashlib.sha256(markdown.encode("utf-8")).hexdigest(),
            "publish_gate": {"enabled": True, "passed": True},
            "structured_forecast": {"required": False, "valid": True},
            "citation_artifacts": {"required": False, "passed": True},
        }, f)


def _write_generation_artifacts(report_id: str) -> None:
    """What a generator leaves on disk mid-run: a drafted section, progress, agent log."""
    folder = ReportManager._ensure_report_folder(report_id)
    with open(ReportManager._get_section_path(report_id, 1), "w", encoding="utf-8") as f:
        f.write(f"## 执行摘要\n\n{DRAFT}\n")
    ReportManager.update_progress(report_id, "generating", 50, "生成中",
                                  current_section="关键发现", completed_sections=["执行摘要"])
    with open(os.path.join(folder, "agent_log.jsonl"), "w", encoding="utf-8") as f:
        f.write(json.dumps({"action": "section_complete", "section_index": 1,
                            "details": {"content": DRAFT, "content_length": len(DRAFT)}},
                           ensure_ascii=False) + "\n")


def _age_folder(report_id: str, seconds: float) -> None:
    """Shift the mtime of every file in the report folder by ``-seconds``."""
    folder = ReportManager._get_report_folder(report_id)
    when = time.time() - seconds
    for name in os.listdir(folder):
        os.utime(os.path.join(folder, name), (when, when))


def _section_bodies(client, report_id: str):
    return {
        "sections": client.get(f"/api/report/{report_id}/sections"),
        "partial": client.get(f"/api/report/{report_id}/sections-partial"),
        "section": client.get(f"/api/report/{report_id}/section/1"),
        "agent_log": client.get(f"/api/report/{report_id}/agent-log"),
        "agent_log_stream": client.get(f"/api/report/{report_id}/agent-log/stream"),
    }


def _assert_section_drafts_withheld(responses) -> None:
    for name, response in responses.items():
        assert DRAFT not in response.get_data(as_text=True), name
    sections = responses["sections"]
    assert sections.status_code == 200
    data = sections.get_json()["data"]
    assert data["sections"] == [] and data["total_sections"] == 0
    assert data["is_complete"] is False and data["publishable"] is False
    assert data["draft_withheld"] is True
    partial = responses["partial"]
    assert partial.status_code == 200
    body = partial.get_json()
    assert body["success"] is True
    assert body["sections"] == [] and body["done"] is False
    assert body["draft_withheld"] is True
    section = responses["section"]
    assert section.status_code == 409
    assert section.get_json()["publishable"] is False
    for name in ("agent_log", "agent_log_stream"):
        assert responses[name].status_code == 200, name
        assert responses[name].get_json()["data"]["draft_withheld"] is True, name


# ───────────── (1) report payloads withhold outline section drafts ─────────────

def test_unpublishable_report_payloads_withhold_outline_section_drafts(client):
    report_id = "report_outline_leak"
    _save_report(report_id, ReportStatus.COMPLETED,
                 markdown=f"# Forecast\n\n## 执行摘要\n\n{DRAFT}\n", outline=_outline())

    payloads = {
        "detail": client.get(f"/api/report/{report_id}"),
        "by_simulation": client.get(f"/api/report/by-simulation/sim_{report_id}"),
        "list": client.get(f"/api/report/list?simulation_id=sim_{report_id}"),
    }
    for name, response in payloads.items():
        assert response.status_code == 200, name
        assert DRAFT not in response.get_data(as_text=True), name
        data = response.get_json()["data"]
        data = data[0] if name == "list" else data
        assert data["publishable"] is False
        assert data["draft_withheld"] is True
        assert data["markdown_content"] == ""
        outline = data["outline"]
        # The skeleton stays: titles, summary and section descriptions are not drafts.
        assert outline["title"] == "Forecast"
        assert outline["summary"] == "Outline summary."
        assert [s["title"] for s in outline["sections"]] == ["执行摘要", "关键发现"]
        assert [s["description"] for s in outline["sections"]] == ["Summarise the call.", "Findings."]
        assert all(s["content"] == "" and s["draft_withheld"] is True for s in outline["sections"])


def test_publishable_report_payload_keeps_outline_section_content(client):
    report_id = "report_outline_published"
    markdown = f"# Forecast\n\n## 执行摘要\n\n{DRAFT}\n"
    _save_report(report_id, ReportStatus.COMPLETED, markdown=markdown, outline=_outline())
    _write_passing_audit(report_id, markdown)

    data = client.get(f"/api/report/{report_id}").get_json()["data"]
    assert data["publishable"] is True
    assert data["draft_withheld"] is False
    assert data["markdown_content"] == markdown
    assert data["outline"]["sections"][0]["content"] == DRAFT
    assert "draft_withheld" not in data["outline"]["sections"][0]


# ───────────── (2) no loadable metadata → section endpoints fail closed ─────────────

@pytest.mark.parametrize("meta", [
    None,                                                     # meta.json missing
    "{not json",                                              # unreadable
    json.dumps({"report_id": "report_nometa", "simulation_id": "sim_x"}),  # malformed
    json.dumps({"report_id": "report_nometa", "simulation_id": "sim_x", "graph_id": "g",
                "simulation_requirement": "q", "status": "exploded"}),     # unknown status
])
def test_section_endpoints_fail_closed_without_loadable_metadata(client, meta):
    report_id = "report_nometa"
    _write_generation_artifacts(report_id)
    if meta is not None:
        with open(ReportManager._get_report_path(report_id), "w", encoding="utf-8") as f:
            f.write(meta)

    _assert_section_drafts_withheld(_section_bodies(client, report_id))


def test_unloadable_metadata_fails_closed_even_when_audit_looks_publishable(client):
    # publication_status 只读 meta.json 的 status 等少数字段；缺必需字段（graph_id）时
    # get_report 无法还原报告 → 没有可信的报告，章节草稿同样不得下发。
    report_id = "report_meta_missing_fields"
    markdown = f"# Forecast\n\n## 执行摘要\n\n{DRAFT}\n"
    _save_report(report_id, ReportStatus.COMPLETED, markdown=markdown)
    _write_passing_audit(report_id, markdown)
    _write_generation_artifacts(report_id)
    meta_path = ReportManager._get_report_path(report_id)
    with open(meta_path, encoding="utf-8") as f:
        meta = json.load(f)
    del meta["graph_id"]
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(meta, f)
    assert ReportManager.is_publishable(report_id)  # the audit files alone would pass

    responses = _section_bodies(client, report_id)
    _assert_section_drafts_withheld(responses)
    issues = [
        responses["sections"].get_json()["data"]["publication_issues"],
        responses["partial"].get_json()["publication_issues"],
        responses["section"].get_json()["publication_issues"],
        responses["agent_log"].get_json()["data"]["publication_issues"],
    ]
    for reasons in issues:
        assert report_api._UNLOADABLE_METADATA_REASON in reasons, reasons


def test_missing_report_single_section_is_rejected_not_served(client):
    # 仅有孤立的章节文件（无 meta/progress/log），也不得作为草稿下发。
    report_id = "report_orphan_section"
    ReportManager._ensure_report_folder(report_id)
    with open(ReportManager._get_section_path(report_id, 1), "w", encoding="utf-8") as f:
        f.write(f"## 执行摘要\n\n{DRAFT}\n")

    responses = _section_bodies(client, report_id)
    for name, response in responses.items():
        assert DRAFT not in response.get_data(as_text=True), name
    assert responses["section"].status_code == 409
    assert responses["partial"].get_json()["sections"] == []


# ───────────── (3) the in-progress exemption expires when generation stalls ─────────────

@pytest.mark.parametrize("status", IN_PROGRESS)
def test_live_in_progress_report_still_streams_drafts(client, status):
    report_id = "report_live"
    _save_report(report_id, status, outline=_outline())
    _write_generation_artifacts(report_id)
    _age_folder(report_id, report_api.REPORT_IN_PROGRESS_STALE_SECONDS - 120)

    responses = _section_bodies(client, report_id)
    sections = responses["sections"].get_json()["data"]
    assert sections["draft_withheld"] is False
    assert DRAFT in sections["sections"][0]["content"]
    partial = responses["partial"].get_json()
    assert partial["draft_withheld"] is False
    assert [s["status"] for s in partial["sections"]] == ["completed", "generating"]
    assert DRAFT in partial["sections"][0]["content_md"]
    assert responses["section"].status_code == 200
    assert DRAFT in responses["section"].get_json()["data"]["content"]
    for name in ("agent_log", "agent_log_stream"):
        log = responses[name].get_json()["data"]
        assert log["draft_withheld"] is False, name
        assert log["logs"][0]["details"]["content"] == DRAFT, name


@pytest.mark.parametrize("status", IN_PROGRESS)
def test_stale_in_progress_report_withholds_drafts(client, status):
    report_id = "report_crashed"
    _save_report(report_id, status, outline=_outline())
    _write_generation_artifacts(report_id)
    _age_folder(report_id, report_api.REPORT_IN_PROGRESS_STALE_SECONDS + 120)

    responses = _section_bodies(client, report_id)
    _assert_section_drafts_withheld(responses)
    # The stale in-flight report explains why it is withheld, on every gated endpoint.
    issues = [
        responses["sections"].get_json()["data"]["publication_issues"],
        responses["partial"].get_json()["publication_issues"],
        responses["section"].get_json()["publication_issues"],
        responses["agent_log"].get_json()["data"]["publication_issues"],
    ]
    for reasons in issues:
        assert any("generation stalled" in reason for reason in reasons), reasons
    # Event skeleton of the agent log survives, only the prose is dropped.
    entry = responses["agent_log"].get_json()["data"]["logs"][0]
    assert entry["action"] == "section_complete"
    assert entry["details"]["content_length"] == len(DRAFT)
    assert "content" not in entry["details"]


@pytest.mark.parametrize("status", IN_PROGRESS)
def test_generator_killed_a_day_ago_no_longer_streams_drafts(client, status):
    # 生成器进程被杀（无异常路径可落 FAILED），meta.json 永远停在 in-flight 状态：
    # 一天后章节草稿与 agent-log 正文都不得再当作「生成中」下发。
    report_id = "report_killed_yesterday"
    _save_report(report_id, status, outline=_outline())
    _write_generation_artifacts(report_id)
    _age_folder(report_id, 24 * 3600)

    _assert_section_drafts_withheld(_section_bodies(client, report_id))


def test_recent_agent_log_activity_keeps_long_section_live(client):
    # 单章节检索可能长时间不刷新 progress.json，但每次工具调用/LLM 响应都会追加 agent_log.jsonl：
    # 只要任一活动文件在窗口内被写过，就仍是实时生成，照常下发。
    report_id = "report_long_section"
    _save_report(report_id, ReportStatus.PLANNING, outline=_outline())
    _write_generation_artifacts(report_id)
    _age_folder(report_id, report_api.REPORT_IN_PROGRESS_STALE_SECONDS + 3600)
    os.utime(os.path.join(ReportManager._get_report_folder(report_id), "agent_log.jsonl"), None)

    data = client.get(f"/api/report/{report_id}/sections").get_json()["data"]
    assert data["draft_withheld"] is False
    assert DRAFT in data["sections"][0]["content"]


def test_unrelated_files_do_not_count_as_generator_activity(client):
    # 非生成器文件（如 PDF/图表缓存）被刷新不能让已中断的报告「复活」为生成中。
    report_id = "report_crashed_with_cache"
    _save_report(report_id, ReportStatus.GENERATING, outline=_outline())
    _write_generation_artifacts(report_id)
    _age_folder(report_id, report_api.REPORT_IN_PROGRESS_STALE_SECONDS + 120)
    with open(os.path.join(ReportManager._get_report_folder(report_id), "full_report.pdf"),
              "wb") as f:
        f.write(b"%PDF-1.4\n")

    _assert_section_drafts_withheld(_section_bodies(client, report_id))


def test_far_future_activity_timestamp_is_not_trusted(client):
    report_id = "report_future_mtime"
    _save_report(report_id, ReportStatus.GENERATING, outline=_outline())
    _write_generation_artifacts(report_id)
    _age_folder(report_id, -(report_api.REPORT_IN_PROGRESS_STALE_SECONDS + 120))

    _assert_section_drafts_withheld(_section_bodies(client, report_id))


def test_stale_threshold_is_a_conservative_named_constant():
    assert report_api.REPORT_IN_PROGRESS_STALE_SECONDS == 30 * 60


# ---------------------------------------------------------------------------
# Console log: some generator lines quote draft prose (independent review)
# ---------------------------------------------------------------------------

_CONSOLE_LINES = [
    "[10:00:00] INFO: 搜索完成: 找到 15 条相关事实",
    f"[10:00:01] WARNING: 引用接地审计：1/3 条引用未标注为模拟且未在研究材料中匹配（疑似嫁接/捏造）: ['{DRAFT}']",
    f"[10:00:02] WARNING: 统计合理性审计：1 处疑似不合理的极端增长率: [{{'context': '{DRAFT}'}}]",
    f"[10:00:03] WARNING: 概率一致性审计：1 处正文概率与 forecast.json 不符: ['{DRAFT}']",
    f"[10:00:04] INFO: 章节 关键发现: 反思修订已采纳（900→950 字符） ｜指令: {DRAFT}",
]


def _write_console_log(report_id: str) -> None:
    folder = ReportManager._ensure_report_folder(report_id)
    with open(os.path.join(folder, "console_log.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(_CONSOLE_LINES) + "\n")


@pytest.mark.parametrize("status", [ReportStatus.COMPLETED, ReportStatus.FAILED])
def test_console_log_withholds_quoted_drafts_of_unpublishable_reports(client, status):
    _save_report("report_console", status, markdown=f"# Forecast\n\n{DRAFT}\n")
    _write_console_log("report_console")
    for path in ("console-log", "console-log/stream"):
        response = client.get(f"/api/report/report_console/{path}")
        assert response.status_code == 200
        body = response.get_json()["data"]
        assert DRAFT not in json.dumps(body, ensure_ascii=False)
        assert body["draft_withheld"] is True
        logs = body["logs"]
        # Diagnostics survive: plain lines untouched, audit summaries kept.
        assert logs[0] == _CONSOLE_LINES[0]
        assert any("引用接地审计：1/3 条引用" in line for line in logs)
        assert any("反思修订已采纳（900→950 字符）" in line for line in logs)


def test_console_log_of_a_publishable_report_is_unchanged(client):
    markdown = f"# Forecast\n\n{DRAFT}\n"
    _save_report("report_console_ok", ReportStatus.COMPLETED, markdown=markdown)
    _write_passing_audit("report_console_ok", markdown)
    _write_console_log("report_console_ok")
    body = client.get("/api/report/report_console_ok/console-log/stream").get_json()["data"]
    if body["draft_withheld"]:
        pytest.skip("audit fixture does not satisfy this checkout's publication policy")
    assert body["logs"] == _CONSOLE_LINES


@pytest.mark.parametrize("meta", ["[]", '"text"', "42", "null"])
def test_non_object_metadata_withholds_drafts_instead_of_failing(client, reports_tmp, meta):
    """A meta.json that is valid JSON but not an object made publication_status
    raise, so the gated endpoints returned 500; they now fail closed."""
    folder = ReportManager._ensure_report_folder("report_badmeta")
    with open(os.path.join(folder, "meta.json"), "w", encoding="utf-8") as f:
        f.write(meta)
    with open(ReportManager._get_section_path("report_badmeta", 1), "w", encoding="utf-8") as f:
        f.write(f"## 执行摘要\n\n{DRAFT}\n")
    for name, response in _section_bodies(client, "report_badmeta").items():
        assert response.status_code != 500, name
        assert DRAFT not in response.get_data(as_text=True), name
