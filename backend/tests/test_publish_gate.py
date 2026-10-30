"""NEXTSTEPS P2-3: forecast publish-gate (coherence + grounding) tests.

ReportAgent._apply_publish_gate is a pure staticmethod, so we test it directly
without constructing a (heavy) ReportAgent.
"""

from app.services.report_agent import ReportAgent


def _gate(forecast):
    return ReportAgent._apply_publish_gate(dict(forecast))


def test_publish_gate_passes_coherent_grounded_forecast():
    f = _gate({
        "confidence": "high",
        "citation_audit": {"coverage": 0.9},
        "scenarios": [
            {"name": "情景A", "probability": 0.6},
            {"name": "维持现状", "probability": 0.4},
        ],
    })
    assert f["quality"]["passed"] is True
    assert f["confidence"] == "high"  # not demoted


def test_publish_gate_demotes_on_low_coverage():
    """F1: coverage previously failed; now discloses grade B and lowers confidence."""
    f = _gate({
        "confidence": "high",
        "citation_audit": {"coverage": 0.1},
        "scenarios": [
            {"name": "情景A", "probability": 0.6},
            {"name": "维持现状", "probability": 0.4},
        ],
    })
    assert f["quality"]["passed"] is True
    assert f["quality"]["grade"] == "B"
    assert f["confidence"] == "medium"  # demoted exactly one level
    assert any("coverage" in i for i in f["quality"]["disclosures"])


def test_publish_gate_flags_missing_residual_and_bad_sum():
    f = _gate({
        "confidence": "medium",
        "citation_audit": {"coverage": 1.0},
        "scenarios": [{"name": "情景A", "probability": 0.6}],  # sum<1, no residual
    })
    issues = f["quality"]["issues"]
    assert any("兜底" in i for i in issues)
    assert any("偏离 1" in i for i in issues)
    assert f["quality"]["hard_passed"] is False
    assert len(f["quality"]["hard_issues"]) == 2
    # Structural artifact defects block publication; they are not evidence that
    # the world's outcome is less knowable.
    assert f["confidence"] == "medium"


def test_publish_gate_no_scenarios_is_vacuously_passing():
    f = _gate({"confidence": "medium", "scenarios": []})
    assert f["quality"]["passed"] is True
    assert f["confidence"] == "medium"


def test_publish_gate_prefers_resolved_citation_coverage():
    """F1 preserves measured resolved coverage while grading epistemic shortfalls."""
    f = _gate({
        "confidence": "high",
        "citation_audit": {
            "coverage": 1.0,          # a dangling/simulation marker can inflate this
            "resolved_coverage": 0.0,  # no marker resolves to the source index
        },
        "scenarios": [
            {"name": "Upside", "probability": 0.6},
            {"name": "Other / status quo", "probability": 0.4},
        ],
    })
    assert f["quality"]["passed"] is True
    assert f["quality"]["grade"] == "B"
    assert f["quality"]["citation_coverage"] == 0.0
    assert f["quality"]["citation_coverage_basis"] == "resolved_coverage"
    assert f["confidence"] == "medium"


def test_publish_gate_reaudit_is_idempotent_and_restores_clean_baseline():
    forecast = {
        "confidence": "high",
        "confidence_rationale": "Original calibrated rationale.",
        "citation_audit": {"resolved_coverage": 0.0},
        "scenarios": [
            {"name": "Upside", "probability": 0.6},
            {"name": "Other / status quo", "probability": 0.4},
        ],
    }
    first = ReportAgent._apply_publish_gate(forecast)
    assert first["confidence"] == "medium"
    assert first["quality"]["pre_publish_confidence"] == "high"
    second = ReportAgent._apply_publish_gate(first)
    assert second["confidence"] == "medium"  # never ratchets to low
    assert second["confidence_rationale"].count("证据/校准门：") == 1

    second["citation_audit"] = {"resolved_coverage": 1.0}
    clean = ReportAgent._apply_publish_gate(second)
    assert clean["quality"]["passed"] is True
    assert clean["confidence"] == "high"
    assert clean["confidence_rationale"] == "Original calibrated rationale."


def test_publish_gate_separates_hard_integrity_from_epistemic_demotion():
    forecast = {
        "confidence": "high",
        "confidence_rationale": "Calibrated evidence rationale.",
        "citation_audit": {"resolved_coverage": 1.0},
        "scenarios": [
            {"name": "Upside", "probability": 0.6},
            {"name": "Other / status quo", "probability": 0.4},
        ],
        "quality": {
            "final_audit": {
                "disk_matches_memory": False,
                "citation_markers": {"dangling": []},
                "lint": {"changed": False},
            }
        },
    }
    gated = ReportAgent._apply_publish_gate(forecast)
    assert gated["quality"]["hard_passed"] is False
    assert gated["quality"]["epistemic_issues"] == []
    assert gated["confidence"] == "high"
    assert gated["confidence_rationale"] == "Calibrated evidence rationale."
