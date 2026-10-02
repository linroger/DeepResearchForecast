"""Offline tests for EVAL-10: ReportAgent's binary_quality rescore keeps the extractor's keys.

_finalize_structured_forecast recomputes the binary scorecard after the forecast contract is
reconciled. The recomputed dict used to replace the extractor's binary_quality wholesale, so the
ITEM-12 ensemble diagnostics, provenance_downgrades, world_state_outcome and every other
extractor-only key and issue line never reached forecast.json (and so never reached the ensemble
footnote or the publish gate). The merge adds only missing keys, never overwrites a recomputed
scoring key, and appends only extractor-only issue lines (no stale base-scoring lines, no
duplicates). Offline: the extractor and reconcile are stubbed, no LLM, no network.
"""

import json
import os

import pytest

from app.config import Config
from app.services import forecast_extractor as fe
from app.services import forecast_ledger
from app.services.report_agent import ReportAgent, ReportManager

_STATEMENTS = (
    "US CPI inflation exceeds 3% in December 2027",
    "US unemployment rate exceeds 5% in December 2027",
    "Fed funds upper bound is below 3% in December 2027",
)
_HEDGED = (0.5, 0.52, 0.48)          # what the extractor scored: all coin-flips
_RESTORED = (0.8, 0.15, 0.25)        # what the (stubbed) contract reconcile restores
_ENSEMBLE = {"enabled_models": ["kimi"], "pooled_models": ["kimi"], "skipped": [],
             "low_agreement": ["F2"], "spread_threshold": 0.15}
_WORLD_STATE = {"scenario_shares": {"S1": 0.6, "S2": 0.4}, "converged": True, "converged_at": 12}
_PROVENANCE_LINE = ("1 forecast(s) claimed a simulation signal that was never injected into the "
                    "prompt — source downgraded to research-prior (see source_claimed)")
_ENSEMBLE_LINE = "1 forecast(s) show cross-model disagreement (spread > 0.15): F2"
_WINDOW_LINE = "1 forecast(s) anchored to a market whose window ended — excluded"


def _binaries(probs):
    return [{"id": f"F{i}", "statement": stmt, "probability": p,
             "resolution_criteria": "BLS CPI-U YoY above 3.0% for December 2027",
             "theme": theme, "horizon_year": 2027, "criteria_sharp": True,
             "ensemble": {"models": ["minimax", "kimi"], "spread": 0.2 if i == 2 else 0.05}}
            for i, (stmt, p, theme) in enumerate(
                zip(_STATEMENTS, probs, ("inflation", "labor", "rates"), strict=True), 1)]


class _SpineLLM:
    """chat_json stub: every call returns the same readable three-scenario spine."""

    def chat_json(self, messages=None, temperature=0.2, max_tokens=2048, **kw):
        names = ("Rapid adoption path", "Gradual adoption path", "Other / Status Quo")
        return {"headline": "h", "horizon": "2030", "confidence": "medium", "scenarios": [
            {"name": name, "probability": p, "summary": f"{name} summary",
             "key_drivers": ["driver"],
             "resolution_criteria": f"{name} resolves if the index is above {10 + i}% by 2030"}
            for i, (name, p) in enumerate(zip(names, (0.5, 0.3, 0.2), strict=True))]}


def _agent():
    a = ReportAgent.__new__(ReportAgent)
    defaults = {
        "graph_id": "g1", "simulation_id": "sim1", "llm": _SpineLLM(),
        "simulation_requirement": "Will adoption accelerate?",
        "situation_brief": "", "actors": None, "sources": [], "research_report": "",
        "output_language": "English", "scenario_label": "", "base_simulation_id": None,
        "_background_block": "", "_sources_index": "", "_signal_pack": "",
        "_market_pack": "", "_forecast_spine": None, "_forecast_spine_block": "",
        "_retrieval_query": None, "_outline_degraded": False, "_outline_summary": "",
        "_section_tool_calls": 0, "report_logger": None, "console_logger": None,
        "tools": {},
    }
    for key, value in defaults.items():
        setattr(a, key, value)
    return a


@pytest.fixture
def report_env(monkeypatch, tmp_path):
    monkeypatch.setattr(Config, "UPLOAD_FOLDER", str(tmp_path), raising=False)
    monkeypatch.setattr(ReportManager, "REPORTS_DIR", str(tmp_path / "reports"), raising=False)
    monkeypatch.setattr(Config, "FORECAST_LEDGER_DIR", str(tmp_path / "ledger"), raising=False)
    monkeypatch.setattr(Config, "REPORT_PUBLISH_GATE", False, raising=False)
    monkeypatch.setattr(Config, "REPORT_REPAIR_PASSES", False, raising=False)
    monkeypatch.setattr(Config, "REPORT_FORECAST_SELF_CRITIQUE", False, raising=False)
    monkeypatch.setattr(Config, "REPORT_SPINE_SELFCONSISTENCY_K", 1, raising=False)
    monkeypatch.setattr(Config, "FORECAST_EMIT_BINARY", True, raising=False)
    monkeypatch.setattr(Config, "PREDICTION_MARKETS_ENABLED", False, raising=False)
    monkeypatch.setattr(Config, "FORECAST_BINARY_THEMES", None, raising=False)
    monkeypatch.setattr(Config, "BINARY_FORECASTS_MIN_COUNT", 10, raising=False)
    monkeypatch.setattr(forecast_ledger, "append_forecast", lambda forecast, **kw: None)
    return tmp_path


def _stub_extraction(monkeypatch, extra_keys, *, lead=(), tail=(), restore=True):
    """Stub the extractor (scored on hedged probabilities, like the real one) and the reconcile.

    The extractor's binary_quality is the real base scorecard plus ``extra_keys``, with the
    extractor-only issue lines ``lead`` before and ``tail`` after the base-scoring lines. With
    ``restore`` the stub reconcile restores committed probabilities, so the extractor's
    base-scoring lines (spread / midband / conviction) are stale when ReportAgent rescores.
    """
    seen = {}

    def fake_extract(*args, **kwargs):
        binaries = _binaries(_HEDGED)
        quality = fe._binary_quality(binaries, min_count=kwargs["min_count"],
                                     themes_expected=kwargs.get("themes"))
        seen["base_issues"] = list(quality["issues"])
        quality.update(extra_keys)
        quality["issues"] = [*lead, *seen["base_issues"], *tail]
        seen["extracted"] = json.loads(json.dumps(quality))
        return {"binary_forecasts": binaries, "binary_quality": quality}

    def fake_reconcile(forecast, *args, **kwargs):
        if restore:
            for binary, p in zip(forecast["binary_forecasts"], _RESTORED, strict=True):
                binary["probability"] = p
        return {"checked": 0, "stub": True}

    monkeypatch.setattr(fe, "extract_binary_forecasts", fake_extract)
    monkeypatch.setattr(fe, "reconcile_forecast_contract", fake_reconcile)
    return seen


def _finalize(report_id):
    _agent()._finalize_structured_forecast(report_id, "# T\n\nBody.")


def _forecast(tmp_path, report_id):
    with open(os.path.join(str(tmp_path), "reports", report_id, "forecast.json"),
              encoding="utf-8") as handle:
        return json.load(handle)


def test_binary_quality_extractor_keys_survive_rescore(monkeypatch, report_env):
    seen = _stub_extraction(monkeypatch, {
        "ensemble": _ENSEMBLE,
        "provenance_downgrades": 1,
        "world_state_outcome": _WORLD_STATE,
        "market_window_ended_excluded": 1,
        "needs_review_count": 2,
        "needs_review_reasons": {"range": 2},
    }, lead=[fe._binary_withheld_issue(2)], tail=[_PROVENANCE_LINE, _ENSEMBLE_LINE, _WINDOW_LINE])
    _finalize("report_rescore")
    fc = _forecast(report_env, "report_rescore")
    bq = fc["binary_quality"]

    # extractor-only keys reach forecast.json unchanged
    assert bq["ensemble"] == _ENSEMBLE
    assert bq["provenance_downgrades"] == 1
    assert bq["world_state_outcome"] == _WORLD_STATE
    assert bq["market_window_ended_excluded"] == 1
    assert bq["needs_review_count"] == 2 and bq["needs_review_reasons"] == {"range": 2}

    # recomputed scoring keys are never overwritten by the extractor's stale values
    extracted = seen["extracted"]
    assert extracted["passed"] is False and extracted["midband_share"] == 1.0
    assert bq["midband_share"] == 0.0 and bq["conviction_count"] == 3
    assert bq["prob_stdev"] != extracted["prob_stdev"]
    assert bq["proposition_consistency"] == {"checked": 0, "stub": True}

    # issues: withheld line first (REPORT-1), the base line that is still true exactly once,
    # extractor-only lines appended once and in order, and none of the stale hedging lines
    stale = [issue for issue in seen["base_issues"] if issue != "only 3 binaries (< 10)"]
    assert len(stale) == 3, seen["base_issues"]
    assert bq["issues"] == [fe._binary_withheld_issue(2), "only 3 binaries (< 10)",
                            _PROVENANCE_LINE, _ENSEMBLE_LINE, _WINDOW_LINE]
    assert not set(stale) & set(bq["issues"])

    # the ITEM-12 footnote now finds the ensemble block on the published forecast
    table = fe.render_binary_forecasts_block(fc, language="English")
    assert "Multi-model ensemble (kimi): F2 show cross-model disagreement" in table
    assert "±20% ⚠" in table


def test_rescore_keeps_a_base_line_that_is_still_true_exactly_once(monkeypatch, report_env):
    # no probability restore: the extractor's base lines are still accurate after the rescore
    seen = _stub_extraction(monkeypatch, {"provenance_downgrades": 0}, restore=False)
    _finalize("report_still_hedged")
    bq = _forecast(report_env, "report_still_hedged")["binary_quality"]
    assert bq["issues"] == seen["base_issues"]  # recomputed once, never duplicated
    assert bq["provenance_downgrades"] == 0 and bq["passed"] is False
    assert "ensemble" not in bq  # nothing invented when the extractor wrote no block


def test_rescored_issue_reaches_the_publish_gate(monkeypatch, report_env):
    _stub_extraction(monkeypatch, {"provenance_downgrades": 1}, tail=[_PROVENANCE_LINE])
    _finalize("report_gate")
    fc = _forecast(report_env, "report_gate")
    # restored probabilities leave one base line (too few binaries); the extractor's
    # provenance line follows it, so the gate's two-issue summary now carries it
    assert fc["binary_quality"]["issues"] == ["only 3 binaries (< 10)", _PROVENANCE_LINE]
    gated = ReportAgent._apply_publish_gate(dict(fc, citation_audit={"coverage": 1.0}))
    assert any("二元预测信心/客观性门未过" in issue and _PROVENANCE_LINE in issue
               for issue in gated["quality"]["epistemic_issues"])
