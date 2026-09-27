"""/api/report/<id>/agent-log must not leak drafts of reports that failed the gate.

agent_log.jsonl records every section's full draft (section_content /
section_complete), raw LLM responses and ReACT thoughts. While a report is
still generating these stream live, like sections-partial. Once it is finished
but not publishable, the endpoints withhold the draft-bearing fields and keep
only the event skeleton, the same gate the sections/section endpoints apply.
"""

import json
from types import SimpleNamespace

import pytest

from app.services.report_agent import ReportManager, ReportStatus

DRAFT = "DRAFT-FORECAST: Plan B wins with 71% probability"

ENTRIES = [
    {"action": "report_start", "stage": "pending", "details": {"message": "start"}},
    {"action": "react_thought", "stage": "generating", "section_index": 1,
     "details": {"iteration": 1, "thought": DRAFT, "message": "think"}},
    {"action": "tool_result", "stage": "generating", "section_index": 1,
     "details": {"tool_name": "insight_forge", "result": "graph facts", "result_length": 11}},
    {"action": "llm_response", "stage": "generating", "section_index": 1,
     "details": {"response": f"Final Answer: {DRAFT}", "response_length": 40, "has_final_answer": True}},
    {"action": "section_content", "stage": "generating", "section_index": 1,
     "details": {"content": DRAFT, "content_length": len(DRAFT)}},
    {"action": "section_complete", "stage": "generating", "section_title": "执行摘要", "section_index": 1,
     "details": {"content": DRAFT, "content_length": len(DRAFT), "telemetry": {"llm_calls": 3}}},
    {"action": "report_complete", "stage": "completed", "details": {"total_sections": 1}},
]


@pytest.fixture
def client_for(tmp_path, monkeypatch):
    reports = tmp_path / "reports"
    reports.mkdir()
    monkeypatch.setattr(ReportManager, "REPORTS_DIR", str(reports))

    def _make(status, publishable, report_exists=True):
        folder = reports / "report_gate"
        folder.mkdir(exist_ok=True)
        (folder / "agent_log.jsonl").write_text(
            "".join(json.dumps(e, ensure_ascii=False) + "\n" for e in ENTRIES), encoding="utf-8")
        report = SimpleNamespace(report_id="report_gate", status=status) if report_exists else None
        monkeypatch.setattr(ReportManager, "get_report", classmethod(lambda cls, rid: report))
        monkeypatch.setattr(
            ReportManager, "publication_status",
            classmethod(lambda cls, rid, lang=None: {
                "publishable": publishable,
                "reasons": [] if publishable else ["final audit failed"],
            }))
        from app import create_app
        app = create_app()
        app.config["TESTING"] = True
        return app.test_client()

    return _make


def _fetch_both(client):
    incremental = client.get("/api/report/report_gate/agent-log").get_json()["data"]
    full = client.get("/api/report/report_gate/agent-log/stream").get_json()["data"]
    return incremental, full


@pytest.mark.parametrize("status,report_exists", [
    (ReportStatus.COMPLETED, True),
    (ReportStatus.FAILED, True),
    (None, False),
])
def test_finished_unpublishable_report_withholds_drafts(client_for, status, report_exists):
    client = client_for(status, publishable=False, report_exists=report_exists)
    for data in _fetch_both(client):
        body = json.dumps(data, ensure_ascii=False)
        assert DRAFT not in body
        assert data["draft_withheld"] is True
        assert data["publishable"] is False
        assert data["publication_issues"] == ["final audit failed"]
        # The event skeleton stays: same entries, same order, lengths/telemetry intact.
        assert [e["action"] for e in data["logs"]] == [e["action"] for e in ENTRIES]
        complete = data["logs"][5]
        assert complete["section_title"] == "执行摘要"
        assert complete["details"]["content_length"] == len(DRAFT)
        assert complete["details"]["telemetry"] == {"llm_calls": 3}
        assert complete["details"]["draft_withheld"] is True
        # Tool evidence is not report prose and stays visible.
        assert data["logs"][2]["details"]["result"] == "graph facts"


def test_published_report_returns_full_log(client_for):
    client = client_for(ReportStatus.COMPLETED, publishable=True)
    for data in _fetch_both(client):
        assert data["draft_withheld"] is False
        assert data["publishable"] is True
        assert data["logs"] == ENTRIES


@pytest.mark.parametrize("status", [ReportStatus.PENDING, ReportStatus.PLANNING, ReportStatus.GENERATING])
def test_in_progress_report_streams_live(client_for, status):
    client = client_for(status, publishable=False)
    for data in _fetch_both(client):
        assert data["draft_withheld"] is False
        assert data["logs"] == ENTRIES


def test_incremental_reads_keep_their_offsets(client_for):
    client = client_for(ReportStatus.FAILED, publishable=False)
    data = client.get("/api/report/report_gate/agent-log?from_line=4").get_json()["data"]
    assert data["from_line"] == 4
    assert data["total_lines"] == len(ENTRIES)
    assert [e["action"] for e in data["logs"]] == ["section_content", "section_complete", "report_complete"]
    assert DRAFT not in json.dumps(data, ensure_ascii=False)
