"""ITEM-17 backend: GET /<report_id>/sections-partial 渐进式发布契约 + ITEM-16 图表 HTML 服务。

覆盖：
  · sections-partial 在「仍生成中」报告上返回已完成章节（status='completed'）+ 正在生成占位
    （status='generating'），done=false；full_report.md 落盘后 done=true。
  · title 从章节正文首个 markdown 标题解析。
  · /api/report/{id}/charts/<file>.html 以 text/html 服务（离线自包含 HTML 图，ITEM-16）。
全部离线、无 LLM、纯文件读写。"""

import hashlib
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.report_agent import (  # noqa: E402
    Report, ReportManager, ReportStatus,
)


@pytest.fixture
def reports_tmp(tmp_path, monkeypatch):
    """把 ReportManager.REPORTS_DIR 重定向到 tmp，隔离测试产物。"""
    d = tmp_path / "reports"
    d.mkdir()
    monkeypatch.setattr(ReportManager, "REPORTS_DIR", str(d))
    return str(d)


@pytest.fixture
def client(reports_tmp, monkeypatch):
    from app import create_app
    app = create_app()
    app.config["TESTING"] = True
    return app.test_client()


def _write_section(report_id: str, idx: int, body: str):
    ReportManager._ensure_report_folder(report_id)
    with open(ReportManager._get_section_path(report_id, idx), "w", encoding="utf-8") as f:
        f.write(body)


def _start_generating(report_id: str) -> None:
    """真实生成器先落 meta.json（status=generating）再写章节；无可读元信息的章节草稿一律不下发。"""
    ReportManager.save_report(Report(
        report_id=report_id,
        simulation_id=f"sim_{report_id}",
        graph_id="graph_test",
        simulation_requirement="Forecast the outcome.",
        status=ReportStatus.GENERATING,
    ))


def _publish(report_id: str, markdown: str) -> None:
    ReportManager.save_report(Report(
        report_id=report_id,
        simulation_id=f"sim_{report_id}",
        graph_id="graph_test",
        simulation_requirement="Forecast the outcome.",
        status=ReportStatus.COMPLETED,
        markdown_content=markdown,
    ))
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


# ─────────────────────────── sections-partial ───────────────────────────

def test_sections_partial_in_progress(client):
    rid = "report_partial_ip"
    _start_generating(rid)
    _write_section(rid, 1, "## 执行摘要\n\n这是执行摘要正文。\n")
    _write_section(rid, 2, "## 关键发现\n\n关键发现正文。\n")
    # 进度记录当前正在生成第三章
    ReportManager.update_progress(rid, status="generating", progress=60,
                                  message="生成中", current_section="预测场景",
                                  completed_sections=["执行摘要", "关键发现"])

    resp = client.get(f"/api/report/{rid}/sections-partial")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["success"] is True
    assert data["done"] is False

    secs = data["sections"]
    completed = [s for s in secs if s["status"] == "completed"]
    generating = [s for s in secs if s["status"] == "generating"]
    assert len(completed) == 2
    # 标题从正文解析
    assert completed[0]["title"] == "执行摘要"
    assert completed[0]["index"] == 1
    assert "执行摘要正文" in completed[0]["content_md"]
    assert completed[1]["title"] == "关键发现"
    # 正在生成占位（无正文）
    assert len(generating) == 1
    assert generating[0]["title"] == "预测场景"
    assert generating[0]["content_md"] == ""
    assert generating[0]["index"] == 3


def test_sections_partial_done_when_full_report(client):
    rid = "report_partial_done"
    _write_section(rid, 1, "## 执行摘要\n\n正文。\n")
    # 终稿组装完成
    _publish(rid, "# 报告\n\n## 执行摘要\n\n正文。\n")
    # 终态进度
    ReportManager.update_progress(rid, status="completed", progress=100,
                                  message="完成", current_section=None,
                                  completed_sections=["执行摘要"])

    resp = client.get(f"/api/report/{rid}/sections-partial")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["done"] is True
    # 终态不追加 generating 占位
    assert all(s["status"] == "completed" for s in data["sections"])
    assert len(data["sections"]) == 1


def test_sections_partial_no_generating_when_current_already_done(client):
    # current_section 已在已完成集合 → 不追加重复占位
    rid = "report_partial_nodup"
    _start_generating(rid)
    _write_section(rid, 1, "## 执行摘要\n\n正文。\n")
    ReportManager.update_progress(rid, status="generating", progress=30,
                                  message="生成中", current_section="执行摘要",
                                  completed_sections=["执行摘要"])
    resp = client.get(f"/api/report/{rid}/sections-partial")
    data = resp.get_json()
    assert all(s["status"] == "completed" for s in data["sections"])
    assert len(data["sections"]) == 1


def test_sections_partial_missing_report(client):
    # 不存在的报告 → 空 sections、done=false、200（轮询友好，不 404/500）
    resp = client.get("/api/report/report_does_not_exist/sections-partial")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["sections"] == []
    assert data["done"] is False


def test_sections_partial_title_fallback(client):
    # 章节正文无 markdown 标题 → 回退 'Section N'
    rid = "report_partial_notitle"
    _start_generating(rid)
    _write_section(rid, 1, "纯正文，没有标题行。\n")
    resp = client.get(f"/api/report/{rid}/sections-partial")
    data = resp.get_json()
    assert data["sections"][0]["title"] == "Section 1"


# ─────────────────────── ITEM-16: /charts 服务 HTML ───────────────────────

def test_charts_route_serves_html_mimetype(client):
    rid = "report_html_serve"
    _publish(rid, "# 报告\n\n已审计正文。\n")
    charts_dir = os.path.join(ReportManager._get_report_folder(rid), "charts")
    os.makedirs(charts_dir, exist_ok=True)
    with open(os.path.join(charts_dir, "scenario_probabilities.html"), "w", encoding="utf-8") as f:
        f.write("<html><body><div>chart</div></body></html>")

    resp = client.get(f"/api/report/{rid}/charts/scenario_probabilities.html")
    assert resp.status_code == 200
    assert resp.mimetype == "text/html"
    assert "chart" in resp.get_data(as_text=True)
