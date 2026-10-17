"""Foglamp WP0 (slice 0B) — architecture characterization suite.

Each of the twelve confirmed failure paths (EXECPLAN_FOGLAMP §8) has a pair:

- ``test_characterizes_<name>``  — passes only while it faithfully describes
  CURRENT behavior (these are descriptions, not fixes);
- ``test_wp_<owner>_prevents_<name>`` — the paired future-regression test,
  strict-xfail until its owning work package lands and removes the mark.

WP1 (containment) already landed in this branch, so the four rows it owns are
green regression tests here; their characterization twins describe the
containment behavior that replaced the unsafe path.

Deviation from the plan recorded in handoff.md: slice 0A's owner-designated
read-only artifact-root capture was unavailable in this session, so these
characterizations use deterministic synthetic fixtures and source-shape
assertions instead of redacted copies of real run artifacts. They are offline
and network-free.
"""

import inspect
import re
import json
import os

import pytest

from app.config import Config
from app.services import decision_channel as dc
from app.services import forecast_extractor as fe
from app.services import forecast_ledger as fl
from app.services import report_agent as ra
from app.services.worldstate import WorldState
from tests.conftest import FakeLLMClient


def _src(obj) -> str:
    return inspect.getsource(obj)


# ───────────────────────── 1. shared_graph_feedback (owner: WP10) ─────────────
def test_characterizes_shared_graph_feedback():
    """Simulated activity, when feedback is (explicitly) enabled, is written to
    the SAME graph namespace as observed evidence, as plain factual prose with
    no simulation prefix and no epistemic/run/seed labels."""
    from app.services.zep_graph_memory_updater import AgentActivity

    act = AgentActivity(platform="twitter", agent_id=1, agent_name="监管者A",
                        action_type="CREATE_POST",
                        action_args={"content": "我们将于下季度批准该项目"},
                        round_num=3, timestamp="2026-07-17T00:00:00")
    text = act.to_episode_text()
    assert "监管者A" in text and "我们将于下季度批准该项目" in text
    for label in ("模拟", "simulation", "hypothetical", "seed", "run_id"):
        assert label not in text, "episode text carries no simulation provenance"


@pytest.mark.xfail(strict=True, reason="WP10: observed projection immutable; every "
                   "generated write lands in a run/seed/scenario-scoped overlay")
def test_wp_10_prevents_shared_graph_feedback():
    import importlib
    overlay = importlib.import_module("app.services.projections.graph_projection")
    assert hasattr(overlay, "ExperimentOverlay")


# ───────────────────── 2. market_descendant_reuse (owner: WP6) ────────────────
def test_characterizes_market_descendant_reuse():
    """A market observation can enter actor context, spine derivation, and
    binary extraction with no shared influence-cluster identity — the same
    market value can be counted through several paths."""
    sig = inspect.signature(fe.derive_forecast_spine)
    assert "market_block" in sig.parameters
    sig2 = inspect.signature(fe.extract_binary_forecasts)
    assert "market_pack" in sig2.parameters
    with pytest.raises(ImportError):
        import app.services.influence_lineage  # noqa: F401


@pytest.mark.xfail(strict=True, reason="WP6: one influence cluster per source family; "
                   "duplicate descendants cannot alter the aggregate")
def test_wp_6_prevents_market_descendant_reuse():
    import importlib
    mod = importlib.import_module("app.services.influence_lineage")
    assert hasattr(mod, "InfluenceCluster") or hasattr(mod, "assign_influence_cluster")


# ─────────────── 3. social_to_institutional_laundering (owner: WP11) ──────────
def test_characterizes_social_to_institutional_laundering():
    """The central decision prompt converts social behavior (posts) into
    institutional commitments (vote/order/side/allocate) with no typed action
    proposal or feasibility check in between."""
    prompt = dc._build_round_decision_prompt(
        ["S1", "S2"], [{"agent_id": 1, "name": "A", "stance": "pro",
                        "post": "我强烈支持这一方案"}], 1, None)
    assert "投票/下单/站队/分配" in prompt
    with pytest.raises(ImportError):
        import app.domain.contracts  # noqa: F401


@pytest.mark.xfail(strict=True, reason="WP11: ActionProposal → FeasibilityResult → "
                   "ExecutedAction gate before any institutional effect")
def test_wp_11_prevents_social_to_institutional_laundering():
    import importlib
    contracts = importlib.import_module("app.domain.contracts")
    for name in ("ActionProposal", "FeasibilityResult", "ExecutedAction"):
        assert hasattr(contracts, name)


# ──────────────── 4. failure_false_convergence (owner: WP1 — landed) ──────────
def test_characterizes_failure_false_convergence():
    """Post-WP1 behavior: provider failure freezes WorldState, is accounted as
    ``failed``, and can never decay into convergence (I-16). (Pre-WP1, an empty
    commitment list recorded delta=0, decayed the EWMA, and reported
    ``converged=True`` — a dead channel masqueraded as equilibrium.)"""
    ws = WorldState(["A", "B"], base_rates={"A": 0.6, "B": 0.4})
    for _ in range(30):
        ws.step([], round_status="failed")
    assert ws.converged() is False and ws.round_accounting()["failed_rounds"] == 30


def test_wp_1_prevents_failure_false_convergence():
    """WP1 regression (mark removed): injected provider failure ⇒ invalid,
    no_update, not converged."""
    class _Failing:
        def chat_json(self, *a, **k):
            raise RuntimeError("boom")

    res = dc.run_decision_channel(
        [{"round": r, "agent_id": 1, "agent_name": "A"} for r in range(1, 6)],
        [{"agent_id": 1}], {"scenarios": ["S1", "S2"]}, _Failing())
    assert res["validity"] == "invalid"
    assert res["forecast_effect"] == "no_update"
    assert res["outcome"]["converged"] is False


# ─────────────── 5. visibility_to_outcome_power (owner: WP1/WP11) ─────────────
def test_characterizes_visibility_to_outcome_power():
    """Post-WP1 behavior: an actor without declared outcome_power receives a
    declared-neutral 1.0 (outcome_power_known=False) — no longer its
    influence_weight. Full quantitative ineligibility of unknown power is WP11."""
    roster = dc._build_active_roster(
        [{"agent_id": 1, "influence": 9.0}], {1: 9.0}, {}, cap=5)
    assert roster[0]["outcome_power"] == 1.0
    assert roster[0]["outcome_power_known"] is False


def test_wp_1_prevents_visibility_to_outcome_power():
    """WP1 regression (mark removed): _outcome_power_map never falls back to
    influence_weight (I-15)."""
    assert dc._outcome_power_map(
        [{"agent_id": 2, "influence_weight": 5.0}]) == {}


@pytest.mark.xfail(strict=True, reason="WP11: unknown authority/power is "
                   "quantitatively ineligible, not neutrally weighted")
def test_wp_11_prevents_neutral_weight_for_unknown_power():
    # An unknown-power actor's commitment must contribute ZERO quantitative
    # outcome weight (today it contributes neutral 1.0 in the diagnostic lane).
    fake = FakeLLMClient(json_responses=[
        {"decisions": [{"agent_id": 1, "scenario": "S1", "magnitude": 1,
                        "confidence": 1}]}])
    res = dc.run_decision_channel(
        [{"round": 1, "agent_id": 1, "agent_name": "A"}],
        [{"agent_id": 1, "influence_weight": 50.0}],
        {"scenarios": ["S1", "S2"], "base_rates": {"S1": 0.5, "S2": 0.5}}, fake)
    assert res["outcome"]["shares"]["S1"] == 0.5  # no movement without known power


# ──────────────── 6. fork_seed_shared_mutation (owner: WP12) ──────────────────
def test_characterizes_fork_seed_shared_mutation():
    """Extra ensemble seeds run against the SAME graph_id with no overlay or
    snapshot isolation; WP1 contains this by defaulting N_FORECAST_SEEDS=1."""
    from app.services.pipeline_orchestrator import PipelineOrchestrator

    src = _src(PipelineOrchestrator._run_one_seed)
    # the OASIS seed path (world-v1 seeds are forks with child-owned stores) still creates a
    # fresh simulation on the SAME graph; indentation-insensitive since the engine branch
    assert re.search(r"create_simulation\(\s*project\.project_id, graph_id", src)
    assert "overlay" not in src.lower()
    assert int(getattr(Config, "N_FORECAST_SEEDS", 1)) >= 1  # containment default is 1


@pytest.mark.xfail(strict=True, reason="WP12: seeds/forks get isolated overlays, "
                   "checkpoint streams, and RNG state over one sealed snapshot")
def test_wp_12_prevents_fork_seed_shared_mutation():
    import importlib
    mod = importlib.import_module("app.services.experiment_service")
    assert hasattr(mod, "ExperimentService")


# ─────────────── 7. structured_spine_omissions (owner: WP6) ───────────────────
def test_characterizes_structured_spine_omissions(monkeypatch):
    """derive_forecast_spine supports base_distribution and quantitative_facts.
    The production caller never passes base_distribution — that structured input
    is silently absent from probability generation. Since the official-data
    integration it does pass quantitative_facts: the stored official-data pack
    (empty when no official data is bound, so the spine prompt is unchanged)."""
    sig = inspect.signature(fe.derive_forecast_spine)
    assert "base_distribution" in sig.parameters
    assert "quantitative_facts" in sig.parameters
    call_src = _src(ra.ReportAgent._derive_and_pin_forecast_spine)
    assert "base_distribution=" not in call_src
    assert "quantitative_facts=" in call_src

    seen = []

    def capture(llm, **kwargs):
        seen.append(kwargs)
        return None  # no spine: the caller falls back to post-prose extraction

    monkeypatch.setattr(fe, "derive_forecast_spine", capture)
    monkeypatch.setattr(ra.ReportAgent, "_define_tools", lambda self: {})
    monkeypatch.setattr(ra.ReportAgent, "_locate_timeline", lambda self: None)
    monkeypatch.setattr(ra.ReportAgent, "_locate_handoff_dir", lambda self: None)
    official = {"schema_version": 1, "series": [{
        "series": "fred:UNRATE", "provider": "fred", "provider_name": "FRED",
        "title": "Unemployment Rate", "title_zh": "失业率", "units": "Percent",
        "frequency": "M", "seasonal_adjustment": "SA", "geography": "USA",
        "transform": "", "vintage": "", "projection_from": "",
        "source_url": "https://fred.stlouisfed.org/series/UNRATE", "source_id": "S7",
        "retrieved_at": "2025-06-01T00:00:00Z", "sha256": "a" * 64, "csv_sha256": "b" * 64,
        "observations": [{"date": "2025-03-01", "value": 4.2, "flag": ""},
                         {"date": "2025-04-01", "value": 4.25, "flag": ""}]}]}
    for carrier in (official, None):
        agent = ra.ReportAgent(
            "fixture_graph", "fixture_simulation", "Forecast unemployment in 2026",
            llm_client=FakeLLMClient(), zep_tools=object(), official_data=carrier,
            sources=[{"title": "Unemployment Rate",
                      "url": "https://fred.stlouisfed.org/series/UNRATE"}])
        agent._derive_and_pin_forecast_spine("fixture_report")
    assert len(seen) == 2 and all("base_distribution" not in call for call in seen)
    with_data, without_data = (call["quantitative_facts"] for call in seen)
    assert "4.25" in with_data and "[S1]" in with_data  # stored value + its source marker
    assert without_data == ""


@pytest.mark.xfail(strict=True, reason="WP6: every enabled input flows through a "
                   "hash-bound ForecastEvidencePack or fails the run visibly (I-18)")
def test_wp_6_prevents_structured_spine_omissions():
    import importlib
    mod = importlib.import_module("app.services.forecast_evidence_pack")
    assert hasattr(mod, "ForecastEvidencePack") or hasattr(mod, "build_evidence_pack")


# ─────────── 8. dormant_typed_worldstate_anchor (owner: WP6) ──────────────────
def test_characterizes_dormant_typed_worldstate_anchor():
    """REPORT_SPINE_ANCHOR_WORLDSTATE defaults on, yet the typed anchor is
    dormant (production passes no base_distribution). WP1 additionally gated
    the implicit signal-pack path to legacy_prompt only."""
    assert bool(getattr(Config, "REPORT_SPINE_ANCHOR_WORLDSTATE", False)) is True
    call_src = _src(ra.ReportAgent._derive_and_pin_forecast_spine)
    assert "base_distribution=" not in call_src            # anchor stays dormant
    assert "legacy_prompt" in call_src                     # WP1 gate present


@pytest.mark.xfail(strict=True, reason="WP6: the legacy base_distribution stays "
                   "diagnostic; only a promoted registered contrast may move probability")
def test_wp_6_prevents_dormant_typed_worldstate_anchor():
    import importlib
    mod = importlib.import_module("app.services.forecast_evidence_pack")
    assert hasattr(mod, "ForecastEvidencePack") or hasattr(mod, "build_evidence_pack")


# ─────────── 9. edit_without_research_generation (owner: WP4) ─────────────────
def test_characterizes_edit_without_research_generation():
    """PipelineState carries no research-generation identity: a human dossier
    edit mutates artifacts in place with no new sealed generation or explicit
    downstream invalidation."""
    from app.services.pipeline_orchestrator import PipelineState

    fields = set(PipelineState.__dataclass_fields__.keys())
    assert "research_generation_id" not in fields
    assert "case_id" not in fields and "run_spec_id" not in fields


@pytest.mark.xfail(strict=True, reason="WP4: edits create a new sealed "
                   "ResearchGeneration with explicit downstream invalidation")
def test_wp_4_prevents_edit_without_research_generation():
    import importlib
    mod = importlib.import_module("app.services.research_generation_service")
    assert hasattr(mod, "ResearchGenerationService")


# ──────── 10. write_only_quality_and_late_health (owner: WP6) ─────────────────
def test_characterizes_write_only_quality_and_late_health():
    """Pipeline health enforcement runs AFTER report construction — a polished
    report can be produced from degraded inputs, then flagged."""
    from app.services.pipeline_orchestrator import PipelineOrchestrator

    src = _src(PipelineOrchestrator._run)
    i_report = src.find("self._maybe_run_seed_ensemble(")
    i_health = src.find("self._enforce_pipeline_health(")
    assert i_report != -1 and i_health != -1 and i_health > i_report


@pytest.mark.xfail(strict=True, reason="WP6: pre-forecast RunQualityAssessment gate "
                   "runs before forecast/report construction")
def test_wp_6_prevents_write_only_quality_and_late_health():
    import importlib
    mod = importlib.import_module("app.services.run_quality")
    assert hasattr(mod, "RunQualityAssessment") or hasattr(mod, "assess_run_quality")


# ─────────── 11. disconnected_resolution_lifecycle (owner: WP13) ──────────────
def test_characterizes_disconnected_resolution_lifecycle(tmp_path):
    """Market resolutions land in resolutions.jsonl but never flip the matching
    scenario entry in ledger.jsonl — the lifecycle is disconnected."""
    d = str(tmp_path)
    fl.append_forecast(
        {"scenarios": [{"name": "YES", "probability": 0.7},
                       {"name": "NO", "probability": 0.3}]},
        report_id="r1", horizon="2027", d=d)
    fl.append_market_resolution(
        report_id="r1", forecast_id="F1", market_id="m1",
        resolved_outcome="YES", resolved_yes_price=1.0, model_p=0.7,
        market_p_at_research=0.6, brier_contribution=0.09,
        resolved_at="2027-01-01T00:00:00Z", d=d)
    rows = fl.read_ledger(d)
    assert rows and rows[0]["resolved"] is False, (
        "market resolution does not close the scenario ledger entry")


@pytest.mark.xfail(strict=True, reason="WP13: one idempotent resolution service "
                   "closes the same target/revision that was published")
def test_wp_13_prevents_disconnected_resolution_lifecycle():
    import importlib
    mod = importlib.import_module("app.services.resolution_service")
    assert hasattr(mod, "ResolutionService")


# ─────────── 12. answer_bearing_golden_harness (owner: WP14) ──────────────────
def test_characterizes_answer_bearing_golden_harness():
    """The historical golden fixture exposes outcomes inline and the offline
    scorer has no as-of pipeline enforcement. WP1 contains the ledger side
    (evaluation rows isolated from production calibration); the sealed,
    outcome-blind evaluation harness is WP14."""
    fixture = os.path.join(os.path.dirname(__file__), "eval", "golden_questions.json")
    with open(fixture, encoding="utf-8") as f:
        data = json.load(f)
    questions = data.get("questions") if isinstance(data, dict) else data
    assert any("resolved_outcome" in q for q in questions)
    import importlib.util
    try:
        spec = importlib.util.find_spec("app.evaluation.case_registry")
    except ModuleNotFoundError:
        spec = None  # parent package absent — same conclusion
    assert spec is None, "sealed evaluation registry does not exist yet (WP14)"


@pytest.mark.xfail(strict=True, reason="WP14: sealed EvaluationCase registry with "
                   "hidden outcome store and leak canary")
def test_wp_14_prevents_answer_bearing_golden_harness():
    import importlib
    mod = importlib.import_module("app.evaluation.case_registry")
    assert hasattr(mod, "EvaluationCaseRegistry") or hasattr(mod, "CaseRegistry")
