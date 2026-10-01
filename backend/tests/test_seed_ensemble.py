"""NEXTSTEPS P0-3: seed-ensemble pure helpers (offline)."""

import pytest

from app.services.pipeline_orchestrator import PipelineOrchestrator


def test_agreement_to_confidence_buckets():
    f = PipelineOrchestrator._agreement_to_confidence
    assert f(0.95) == "high"
    assert f(0.75) == "high"          # boundary inclusive
    assert f(0.6) == "medium"
    assert f(0.45) == "medium"        # boundary inclusive
    assert f(0.2) == "low"
    assert f(None) == "medium"        # invalid → safe default
    assert f("nope") == "medium"


def test_read_report_forecast_missing_returns_none():
    assert PipelineOrchestrator._read_report_forecast(None) is None
    assert PipelineOrchestrator._read_report_forecast("report_does_not_exist_xyz") is None


def test_extra_seed_derivation_is_pinned():
    """SIM-4 (C30): the ensemble members' seeds, extracted from _maybe_run_seed_ensemble
    with unchanged behaviour (base + k * 7919 for members 2..n)."""
    derive = PipelineOrchestrator._derive_extra_seeds
    assert derive(0, 4) == [(2, 15838), (3, 23757), (4, 31676)]
    assert derive(5, 2) == [(2, 15843)]
    assert derive(5, 1) == []
    seeds = [seed for _k, seed in derive(11, 30)]
    assert len(seeds) == len(set(seeds)) == 29


def test_seed_ensemble_takes_its_member_seeds_from_the_pinned_helper(monkeypatch, tmp_path):
    """SIM-4: _maybe_run_seed_ensemble derives the members from _derive_extra_seeds
    (Config.SIM_SEED as the base, the run's seed count as n), so the pin above covers it."""
    from app.config import Config
    from app.services import pipeline_orchestrator as po

    class _Derived(Exception):
        pass

    calls = []

    def _derive(base_seed, n_seeds):
        calls.append((base_seed, n_seeds))
        raise _Derived

    monkeypatch.setattr(PipelineOrchestrator, "_derive_extra_seeds", staticmethod(_derive))
    monkeypatch.setattr(PipelineOrchestrator, "_read_report_forecast",
                        staticmethod(lambda report_id: {"scenarios": [{"name": "A"}]}))
    monkeypatch.setattr(Config, "N_FORECAST_SEEDS", 3, raising=False)
    monkeypatch.setattr(Config, "SIM_SEED", 5, raising=False)
    monkeypatch.setattr(Config, "REPORT_STRUCTURED_FORECAST", True, raising=False)
    state = po.PipelineState(pipeline_id="pipe_seeds", prompt="q", mode="full",
                             report_id="report_seeds", handoff_dir=str(tmp_path))
    orch = PipelineOrchestrator.__new__(PipelineOrchestrator)
    with pytest.raises(_Derived):
        orch._maybe_run_seed_ensemble(state, object(), "graph_seeds", None, {}, "")
    assert calls == [(5, 3)]
