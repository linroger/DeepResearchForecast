"""RESEARCH-9: citation-surgery telemetry of the report publish stabilizer.

REPORT_FINALIZATION_TELEMETRY (default true) persists what
``_stabilize_publish_markdown`` did to citations before the read-only final
audit (dangling / semantic / overuse strips, removed quotes and the FIRST,
repairing quantitative-grounding call of every pass) as final_audit.json
``pre_audit_repairs`` (report-citation-finalization/1) and forecast.json
``quality.citation_finalization``.  Telemetry only: the published Markdown,
full_report.md and every gate are identical with the flag on or off.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.config import Config
from app.services import citation_finalization_telemetry as cft
from app.services.report_agent import ReportAgent, ReportManager

BACKEND = Path(__file__).resolve().parents[1]

# Three sources: S1 supports the first claim verbatim, S2 and S3 support nothing
# in the report, and [S246] names no source at all (dangling).
SOURCES = [
    {
        "title": "Official revenue outlook",
        "url": "https://example.gov/revenue-outlook",
        "content": "Audited revenue evidence shows the official outlook improved across the region.",
    },
    {
        "title": "Grid operator bulletin",
        "url": "https://example.org/grid-bulletin",
        "content": "Transformer shortages delayed coastal substation upgrades this winter.",
    },
    {
        "title": "Shipping digest",
        "url": "https://example.net/shipping-digest",
        "content": "Container schedules stabilised after the canal reopened to traffic.",
    },
]
SUPPORTED = "Audited revenue evidence shows the official outlook improved across the region."
UNSUPPORTED = "The lunar authority secretly seized every terrestrial data center."
DANGLING = "Martian colonists voted to abolish gravity."
INITIAL = (
    "# Forecast\n\n"
    f"{SUPPORTED} [S1]\n\n"
    f"{UNSUPPORTED} [S2]\n\n"
    f"{DANGLING} [S246]\n"
)


def _forecast() -> dict:
    return {
        "headline": "Base case leads",
        "confidence": "high",
        "confidence_rationale": "Evidence is broad.",
        "scenarios": [
            {"name": "Base case", "probability": 0.6,
             "resolution_criteria": "The audited 2030 filing records the base-case outcome."},
            {"name": "Other / status quo", "probability": 0.4,
             "resolution_criteria": "Any other measurable outcome in the audited 2030 filing."},
        ],
        "binary_forecasts": [{
            "id": "F1", "statement": "Revenue reaches 65% by 2030.", "probability": 0.65,
            "resolution_criteria": "The audited 2030 filing reports revenue at 65%.",
        }],
        "quality": {},
    }


def _agent(sources: list[dict]) -> ReportAgent:
    agent = ReportAgent.__new__(ReportAgent)
    agent.output_language = "English"
    agent.research_report = "Revenue evidence from the official source."
    agent._outline_summary = ""
    agent.sources = [dict(source) for source in sources]
    agent._citation_index = {f"S{i}": source for i, source in enumerate(agent.sources, 1)}
    agent._forecast_spine = None
    return agent


def _publish(monkeypatch, root: Path, *, telemetry: bool, report_id: str = "report_r9",
             markdown: str = INITIAL, sources: list[dict] = SOURCES) -> tuple[dict, dict, str, dict]:
    """Stabilize then audit one report under ``root`` (the generate() order):
    returns (audit, final_audit.json, full_report.md, forecast.json)."""
    monkeypatch.setattr(Config, "REPORT_FINALIZATION_TELEMETRY", telemetry, raising=False)
    monkeypatch.setattr(Config, "REPORT_PUBLISH_GATE", True, raising=False)
    reports = root / "reports"
    folder = reports / report_id
    folder.mkdir(parents=True)
    monkeypatch.setattr(ReportManager, "REPORTS_DIR", str(reports), raising=False)
    (folder / "full_report.md").write_text(markdown, encoding="utf-8")
    (folder / "meta.json").write_text(json.dumps({
        "report_id": report_id, "status": "completed", "failed_sections": [], "partial": False,
    }), encoding="utf-8")
    (folder / "forecast.json").write_text(json.dumps(_forecast()), encoding="utf-8")
    report = SimpleNamespace(markdown_content=markdown)
    agent = _agent(sources)
    result = agent._stabilize_publish_markdown(report_id, report)
    assert result["stable"] is True
    audit = agent._audit_final_published_markdown(report_id, report)
    final_audit = json.loads((folder / "final_audit.json").read_text(encoding="utf-8"))
    full_report = (folder / "full_report.md").read_text(encoding="utf-8")
    assert full_report == report.markdown_content
    forecast = json.loads((folder / "forecast.json").read_text(encoding="utf-8"))
    return audit, final_audit, full_report, forecast


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _gate_view(audit: dict) -> dict:
    """Everything the publish decision reads."""
    return {"hard_issues": audit["hard_issues"], "hard_passed": audit["hard_passed"],
            "publish_gate": audit["publish_gate"]}


# ================================================================ end to end

@pytest.fixture
def report_warnings():
    """mirofish loggers do not propagate to root (caplog misses them): attach a probe."""
    records: list[logging.LogRecord] = []

    class _Probe(logging.Handler):
        def emit(self, record):
            records.append(record)

    probe = _Probe(level=logging.WARNING)
    target = logging.getLogger("mirofish.report_agent")
    target.addHandler(probe)
    try:
        yield records
    finally:
        target.removeHandler(probe)


def test_pre_audit_repairs_persisted(monkeypatch, tmp_path, report_warnings):
    _, _, off_report, off_forecast = _publish(monkeypatch, tmp_path / "off", telemetry=False)
    assert not any("stripped most markers" in record.getMessage() for record in report_warnings)
    audit, final_audit, on_report, forecast = _publish(monkeypatch, tmp_path / "on", telemetry=True)

    repairs = final_audit["pre_audit_repairs"]
    assert repairs == audit["pre_audit_repairs"]
    assert repairs["schema"] == "report-citation-finalization/1"
    assert repairs["markers_before"] == 3
    assert repairs["dangling"] == {"kept_verified": 0, "remapped": 0, "stripped": 1}
    assert repairs["semantic"]["stripped"] == 1 and repairs["semantic"]["remapped"] == 0
    # The last pass re-checked the one surviving marker and kept it.
    assert repairs["semantic"]["kept"] == 1 and repairs["semantic"]["unverifiable"] == 0
    assert repairs["markers_final"] == 1 == final_audit["citation_body_markers"]["total_markers"]
    assert repairs["marker_strip_ratio"] == pytest.approx(2 / 3, abs=1e-3)
    assert repairs["overuse_stripped"] == 0 and repairs["quotes_removed"] == 0
    assert repairs["machine_added_citations"] == repairs["quantitative"]["citations_added"] == 0
    assert repairs["markers_lost_with_removed_text"] == 0
    assert repairs["passes"] >= 1
    assert "checked" not in repairs["semantic"]

    # forecast.json carries the same record, inside the bytes the audit sealed.
    assert forecast["quality"]["citation_finalization"] == repairs
    assert forecast["quality"]["final_audit"]["pre_audit_repairs"] == repairs
    forecast_path = tmp_path / "on" / "reports" / "report_r9" / "forecast.json"
    assert audit["forecast_sha256"] == hashlib.sha256(forecast_path.read_bytes()).hexdigest()
    assert "citation_finalization" not in off_forecast["quality"]

    # Telemetry never touches the published Markdown.
    assert _sha(on_report) == _sha(off_report)
    assert UNSUPPORTED in on_report and "[S2]" not in on_report and "[S246]" not in on_report

    # A strip ratio >= 0.5 is logged, not gated.
    assert any("stripped most markers" in record.getMessage() and "ratio=0.667" in record.getMessage()
               for record in report_warnings)


def test_quantitative_first_call_counted(monkeypatch, tmp_path, report_warnings):
    """The probe after each pass re-runs on repaired text and reports zeros:
    only the repairing call's diagnostics may reach the record."""
    extra = ["Regional revenue audits covered every coastal province.",
             "Revenue auditors flagged delayed filings in inland districts."]
    source = dict(SOURCES[0], content=" ".join([SOURCES[0]["content"], *extra]))
    # Two supported, cited sentences the fake repair deletes, and two supported,
    # uncited ones it attributes to S1 (a machine-added citation each).
    markdown = (
        "# Forecast\n\n"
        f"{SUPPORTED} [S1]\n\n"
        f"{extra[0]} [S1]\n\n"
        f"{extra[1]} [S1]\n\n"
        f"Analysts agree that {extra[0][0].lower()}{extra[0][1:]}\n\n"
        f"Analysts agree that {extra[1][0].lower()}{extra[1][1:]}\n"
    )
    deleted = re.compile(rf"^(?:{re.escape(extra[0])}|{re.escape(extra[1])}) \[S1\]\n\n", re.M)
    uncited = re.compile(r"^(Analysts agree that .+\.)$", re.M)
    calls: list[str] = []

    def fake_repair(self, md):
        calls.append(md)
        diagnostics = {"passed": True, "citations_added": 0, "sentences_removed": 0,
                       "table_rows_removed": 0, "table_cells_cleared": 0,
                       "before": {"resolved_coverage": 1.0}, "after": {"resolved_coverage": 1.0}}
        if not deleted.search(md):
            return md, diagnostics                      # the probe: already repaired
        repaired = uncited.sub(r"\1 [S1]", deleted.sub("", md))
        return repaired, dict(diagnostics, citations_added=2, sentences_removed=5,
                              table_rows_removed=1, table_cells_cleared=3,
                              before={"resolved_coverage": 0.2}, after={"resolved_coverage": 0.95})

    monkeypatch.setattr(ReportAgent, "_repair_final_quantitative_grounding", fake_repair)
    # Three markers of one source: the concentration cap must not strip any.
    monkeypatch.setattr(Config, "REPORT_MAX_CITATIONS_PER_SOURCE", 20, raising=False)
    audit, final_audit, report, forecast = _publish(monkeypatch, tmp_path, telemetry=True, markdown=markdown,
                                                    sources=[source, *SOURCES[1:]])

    assert len(calls) >= 2 and deleted.search(calls[0])     # the repair, then probe(s) on repaired text
    assert all(not deleted.search(md) for md in calls[1:])
    repairs = final_audit["pre_audit_repairs"]
    assert repairs["quantitative"] == {"citations_added": 2, "sentences_removed": 5, "table_rows_removed": 1,
                                       "table_cells_cleared": 3, "coverage_before": 0.2,
                                       "coverage_after": 0.95}
    assert repairs["machine_added_citations"] == 2
    assert repairs["markers_before"] == 3 and repairs["markers_final"] == 3
    stripped = repairs["dangling"]["stripped"] + repairs["semantic"]["stripped"] + repairs["overuse_stripped"]
    assert stripped == 0 and repairs["marker_strip_ratio"] == 0.0
    # 3 before + 2 machine-added - 3 final - 0 stripped: the two markers deleted
    # with their sentences.  Without citations_added the balance would read 0.
    assert repairs["markers_lost_with_removed_text"] == 2
    assert forecast["quality"]["citation_finalization"] == repairs
    body = report.split("\n## References\n", 1)[0]
    assert body.count("[S1]") == 3 and not deleted.search(report)
    assert not report_warnings                              # nothing stripped: no strip-ratio warning


def test_quantitative_coverage_after_is_the_last_repairing_call():
    """coverage_before is pass 1's 'before', coverage_after the latest 'after'."""
    log = cft.new_log("r", 4)
    cft.record(log, "quantitative", {"citations_added": 1, "sentences_removed": 2,
                                     "before": {"resolved_coverage": 0.1}, "after": {"resolved_coverage": 0.5}},
               first_pass=True)
    cft.record(log, "quantitative", {"citations_added": 3, "table_cells_cleared": 4,
                                     "before": {"resolved_coverage": 0.5}, "after": {"resolved_coverage": 0.9}})
    record = cft.pre_audit_repairs(log, 6)
    assert record["quantitative"] == {"citations_added": 4, "sentences_removed": 2, "table_rows_removed": 0,
                                      "table_cells_cleared": 4, "coverage_before": 0.1, "coverage_after": 0.9}
    assert record["markers_lost_with_removed_text"] == 4 + 4 - 6


def test_flag_off(monkeypatch, tmp_path):
    off_audit, off_final, off_report, off_forecast = _publish(monkeypatch, tmp_path / "off", telemetry=False)
    on_audit, on_final, on_report, on_forecast = _publish(monkeypatch, tmp_path / "on", telemetry=True)

    assert "pre_audit_repairs" not in off_audit and "pre_audit_repairs" not in off_final
    assert "citation_finalization" not in off_forecast["quality"]
    assert "pre_audit_repairs" not in off_forecast["quality"]["final_audit"]
    # The same gate verdict either way: the record is never a gate input.
    assert _gate_view(off_audit) == _gate_view(on_audit)
    assert off_forecast["quality"]["passed"] == on_forecast["quality"]["passed"]
    assert off_forecast["quality"].get("issues") == on_forecast["quality"].get("issues")
    assert off_report == on_report
    # Off adds no key anywhere; on adds exactly the two telemetry keys.
    assert set(on_final) - set(off_final) == {"pre_audit_repairs"}
    assert set(on_forecast["quality"]) - set(off_forecast["quality"]) == {"citation_finalization"}
    assert on_audit["policy_version"] == off_audit["policy_version"] == Config.REPORT_FINAL_AUDIT_POLICY_VERSION


def test_integrity_issues_ignore_the_record():
    audit = {"disk_matches_memory": True, "structured_forecast": {"required": False}}
    before = ReportAgent._final_audit_integrity_issues(dict(audit))
    audit["pre_audit_repairs"] = cft.pre_audit_repairs(dict(cft.new_log("r", 100), overuse_stripped=99), 1)
    assert ReportAgent._final_audit_integrity_issues(audit) == before == []


def test_audit_without_a_stabilizer_log_writes_no_record(monkeypatch, tmp_path):
    """An audit outside the stabilizer (or of another report) has no log: no key."""
    monkeypatch.setattr(Config, "REPORT_FINALIZATION_TELEMETRY", True, raising=False)
    reports = tmp_path / "reports"
    (reports / "report_a").mkdir(parents=True)
    monkeypatch.setattr(ReportManager, "REPORTS_DIR", str(reports), raising=False)
    md = f"# Forecast\n\n{SUPPORTED} [S1]\n"
    (reports / "report_a" / "full_report.md").write_text(md, encoding="utf-8")
    agent = _agent(SOURCES)
    audit = agent._audit_final_published_markdown("report_a", SimpleNamespace(markdown_content=md))
    assert audit and "pre_audit_repairs" not in audit
    agent._finalization_log = cft.new_log("report_b", 1)
    audit = agent._audit_final_published_markdown("report_a", SimpleNamespace(markdown_content=md))
    assert "pre_audit_repairs" not in audit


def test_telemetry_failure_never_blocks_publication(monkeypatch, tmp_path):
    def boom(*args, **kwargs):
        raise RuntimeError("telemetry exploded")

    _, off_final, off_report, _ = _publish(monkeypatch, tmp_path / "off", telemetry=False)
    # The log cannot even start (markers_before), then events and the record fail.
    with monkeypatch.context() as patched:
        patched.setattr(cft, "new_log", boom)
        audit, final_audit, report, forecast = _publish(monkeypatch, tmp_path / "start", telemetry=True)
    assert report == off_report and _gate_view(audit) == _gate_view(off_final)
    assert "pre_audit_repairs" not in final_audit and "citation_finalization" not in forecast["quality"]
    monkeypatch.setattr(cft, "record", boom)
    monkeypatch.setattr(cft, "pre_audit_repairs", boom)
    audit, final_audit, report, forecast = _publish(monkeypatch, tmp_path / "on", telemetry=True)
    assert report == off_report and _gate_view(audit) == _gate_view(off_final)
    assert "pre_audit_repairs" not in final_audit and "citation_finalization" not in forecast["quality"]


# ================================================================ pure record

def test_record_sums_events_and_keeps_the_latest_semantic_state():
    log = cft.new_log("r", 10)
    cft.record(log, "dangling", {"kept_verified": 1, "remapped": 2, "stripped": 3})
    cft.record(log, "dangling", {"stripped": 1})
    cft.record(log, "semantic", {"checked": 30, "kept": 12, "unverifiable": 6, "remapped": 1, "stripped": 2},
               state={"checked": 5, "kept": 4, "unverifiable": 1})
    cft.record(log, "semantic", {"checked": 9, "kept": 3, "unverifiable": 1, "stripped": 1},
               state={"checked": 4, "kept": 3, "unverifiable": 1})
    cft.record(log, "totals", {"overuse_stripped": 2, "quotes_removed": 1, "passes": 2, "lint_rewrites": 7})
    record = cft.pre_audit_repairs(log, 3)
    assert record["dangling"] == {"kept_verified": 1, "remapped": 2, "stripped": 4}
    assert record["semantic"] == {"kept": 3, "unverifiable": 1, "remapped": 1, "stripped": 3}
    assert (record["overuse_stripped"], record["quotes_removed"], record["passes"]) == (2, 1, 2)
    assert record["marker_strip_ratio"] == round((4 + 3 + 2) / 10, 4)
    assert record["markers_lost_with_removed_text"] == 0          # 10 + 0 - 3 - 9 < 0 clamps
    assert set(record) == {"schema", "markers_before", "markers_final", "dangling", "semantic",
                           "overuse_stripped", "quotes_removed", "passes", "quantitative",
                           "machine_added_citations", "marker_strip_ratio", "markers_lost_with_removed_text"}


def test_record_reads_malformed_counts_as_zero_and_rejects_unknown_events():
    log = cft.new_log("r", "x")
    cft.record(log, "dangling", {"stripped": "many", "remapped": None, "kept_verified": -3})
    cft.record(log, "quantitative", "not a mapping", first_pass=True)
    cft.record(log, "semantic", None, state="nope")
    record = cft.pre_audit_repairs(log, None)
    assert record["markers_before"] == 0 and record["markers_final"] == 0
    assert record["dangling"] == {"kept_verified": 0, "remapped": 0, "stripped": 0}
    assert record["quantitative"]["coverage_before"] is None and record["marker_strip_ratio"] == 0.0
    with pytest.raises(ValueError):
        cft.record(log, "lint", {})


# ================================================================ knob

def test_knob_defaults_on_and_is_documented():
    env = {key: value for key, value in os.environ.items() if key != "REPORT_FINALIZATION_TELEMETRY"}
    env["DRF_TEST_PROCESS"] = "1"
    probe = subprocess.run([sys.executable, "-c", "from app.config import Config; "
                            "print(repr(Config.REPORT_FINALIZATION_TELEMETRY))"],
                           cwd=BACKEND, env=env, capture_output=True, text=True, timeout=60, check=True)
    assert probe.stdout.strip().splitlines()[-1] == "True"
    env_example = (BACKEND.parent / ".env.example").read_text(encoding="utf-8")
    assert re.search(r"^# REPORT_FINALIZATION_TELEMETRY=true\s+# ", env_example, re.M)
