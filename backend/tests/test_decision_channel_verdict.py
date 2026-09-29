"""SIM-1 — the shared decision-channel validity verdict (``decision_channel_verdict``).

Pins that the extracted helper reproduces the legacy inline Foglamp WP1 rules
(validity + forecast_effect) exactly, adds typed ``validity_reasons``, and books
``unaccounted_rounds`` (rounds executed but never stepped) as ``missing`` so a lossy
resume can no longer be judged ``valid``. ``run_decision_channel`` output on the
Foglamp containment fixtures is unchanged except for the additive
``validity_reasons`` key, and ``CONVERGENCE_POLICY_V1`` stays frozen.

Offline and deterministic: WorldState accounting fixtures plus FakeLLMClient.
"""

import copy

import pytest

from app.config import Config
from app.services import decision_channel as dc
from app.services.decision_channel import decision_channel_verdict, run_decision_channel
from app.services.worldstate import (
    CONVERGENCE_POLICY_V1,
    ROUND_STATUS_ABSTAINED,
    ROUND_STATUS_COMMITTED,
    ROUND_STATUS_FAILED,
    ROUND_STATUS_SILENT,
    WorldState,
)
from tests.conftest import FakeLLMClient

_FROZEN_POLICY = {
    "version": "foglamp-convergence-policy/v1",
    "min_valid_transitions": 3,
    "min_valid_coverage": 0.5,
    "max_failed_rounds": 0,
}

_LEGACY_RESULT_KEYS = {
    "outcome", "trajectory", "decisions", "converged_at", "n_rounds", "scenarios",
    "schema_version", "round_accounting", "validity", "forecast_effect", "epistemic_status",
}


def _legacy_verdict(accounting):
    """The pre-SIM-1 inline block of run_decision_channel, verbatim in behaviour."""
    if accounting["valid_transitions"] <= 0:
        validity = "invalid"
    elif (accounting["failed_rounds"] > 0
          or accounting["valid_coverage"] < float(
              CONVERGENCE_POLICY_V1["min_valid_coverage"])):
        validity = "inconclusive"
    else:
        validity = "valid"
    if validity != "valid":
        forecast_effect = "no_update"
    else:
        effect_policy = str(getattr(Config, "SIMULATION_FORECAST_EFFECT", "diagnostic_only")
                            or "diagnostic_only").strip().lower()
        forecast_effect = ("diagnostic_only" if effect_policy != "no_update"
                           else "no_update")
    return validity, forecast_effect


def _accounting(*statuses):
    ws = WorldState(["A", "B"], base_rates={"A": 0.5, "B": 0.5})
    for s in statuses:
        commits = ([{"scenario": "A", "magnitude": 1.0, "weight": 1.0}]
                   if s == ROUND_STATUS_COMMITTED else [])
        ws.step(commits, round_status=s)
    return ws.round_accounting()


_FIXTURES = [
    # (statuses, validity, forecast_effect, reasons)
    ((ROUND_STATUS_FAILED, ROUND_STATUS_SILENT), "invalid", "no_update", ["no_valid_rounds"]),
    ((ROUND_STATUS_COMMITTED,) * 3 + (ROUND_STATUS_FAILED,),
     "inconclusive", "no_update", ["failed_rounds"]),
    ((ROUND_STATUS_COMMITTED,) * 2 + (ROUND_STATUS_SILENT,) * 3,
     "inconclusive", "no_update", ["low_valid_coverage"]),
    ((ROUND_STATUS_COMMITTED, ROUND_STATUS_ABSTAINED, ROUND_STATUS_COMMITTED),
     "valid", "diagnostic_only", []),
]


@pytest.fixture(autouse=True)
def _default_effect_policy(monkeypatch):
    monkeypatch.setattr(Config, "SIMULATION_FORECAST_EFFECT", "diagnostic_only", raising=False)


@pytest.mark.parametrize(("statuses", "validity", "effect", "reasons"), _FIXTURES)
def test_verdict_matches_legacy_inline_rules(statuses, validity, effect, reasons):
    acct = _accounting(*statuses)
    before = copy.deepcopy(acct)
    verdict = decision_channel_verdict(acct)
    assert (verdict["validity"], verdict["forecast_effect"]) == _legacy_verdict(acct)
    assert verdict["validity"] == validity
    assert verdict["forecast_effect"] == effect
    assert verdict["validity_reasons"] == reasons
    assert set(verdict) == {"round_accounting", "validity", "validity_reasons",
                            "forecast_effect"}
    # n == 0: the accounting comes back equal (a copy), never mutated, no new key
    assert verdict["round_accounting"] == acct == before
    assert verdict["round_accounting"] is not acct
    assert verdict["round_accounting"]["counts"] is not acct["counts"]
    assert "unaccounted_rounds" not in verdict["round_accounting"]


def test_coverage_fixture_is_exactly_point_four():
    assert _accounting(*_FIXTURES[2][0])["valid_coverage"] == pytest.approx(0.4)


def test_unaccounted_rounds_widen_the_denominator_as_missing():
    acct = _accounting(ROUND_STATUS_COMMITTED)
    assert acct["counts"] == {"committed": 1}
    before = copy.deepcopy(acct)
    verdict = decision_channel_verdict(acct, unaccounted_rounds=2)
    out = verdict["round_accounting"]
    assert out["counts"]["missing"] == 2
    assert out["counts"]["committed"] == 1
    assert out["rounds_accounted"] == 3
    assert out["missing_rounds"] == 2
    assert out["valid_transitions"] == 1
    assert out["valid_coverage"] == 0.333333
    assert out["unaccounted_rounds"] == 2
    assert verdict["validity"] == "inconclusive"
    assert verdict["validity_reasons"] == ["low_valid_coverage"]
    assert verdict["forecast_effect"] == "no_update"
    assert acct == before  # the caller's accounting (and its counts) is untouched


def test_unaccounted_rounds_add_to_existing_missing_and_keep_valid_coverage():
    acct = _accounting(ROUND_STATUS_COMMITTED, ROUND_STATUS_COMMITTED, "missing")
    verdict = decision_channel_verdict(acct, unaccounted_rounds=1)
    out = verdict["round_accounting"]
    assert out["counts"]["missing"] == 2 and out["missing_rounds"] == 2
    assert out["rounds_accounted"] == 4 and out["valid_coverage"] == 0.5
    assert verdict["validity"] == "valid"  # 2/4 meets min_valid_coverage exactly
    assert verdict["validity_reasons"] == []


@pytest.mark.parametrize("n", [0, -3])
def test_zero_or_negative_unaccounted_returns_input_accounting(n):
    acct = _accounting(ROUND_STATUS_COMMITTED)
    verdict = decision_channel_verdict(acct, unaccounted_rounds=n)
    assert verdict["round_accounting"] == acct
    assert "unaccounted_rounds" not in verdict["round_accounting"]


def test_failed_and_low_coverage_reasons_accumulate():
    verdict = decision_channel_verdict(
        _accounting(ROUND_STATUS_COMMITTED, ROUND_STATUS_FAILED, ROUND_STATUS_SILENT))
    assert verdict["validity"] == "inconclusive"
    assert verdict["validity_reasons"] == ["failed_rounds", "low_valid_coverage"]


@pytest.mark.parametrize("policy", ["no_update", " NO_UPDATE "])
def test_no_update_effect_policy_applies_to_valid_runs(monkeypatch, policy):
    monkeypatch.setattr(Config, "SIMULATION_FORECAST_EFFECT", policy, raising=False)
    verdict = decision_channel_verdict(_accounting(ROUND_STATUS_COMMITTED))
    assert verdict["validity"] == "valid"
    assert verdict["forecast_effect"] == "no_update"


@pytest.mark.parametrize("policy", ["validated_update", "legacy_prompt", "diagnostic_only"])
def test_validated_update_is_never_emitted(monkeypatch, policy):
    monkeypatch.setattr(Config, "SIMULATION_FORECAST_EFFECT", policy, raising=False)
    verdict = decision_channel_verdict(_accounting(ROUND_STATUS_COMMITTED))
    assert verdict["forecast_effect"] == "diagnostic_only"


# ---------------------------------------------------------------- run_decision_channel
class _FailingLLM:
    def chat_json(self, *a, **k):
        raise RuntimeError("injected decision-provider failure")


def _containment_runs():
    """The Foglamp 1C fixtures of test_foglamp_containment (failure / abstain /
    silent / committed equilibrium)."""
    seed = {"scenarios": ["S1", "S2"], "base_rates": {"S1": 0.5, "S2": 0.5}}
    actions = [{"round": r, "agent_id": r, "agent_name": f"A{r}"} for r in range(1, 6)]
    cfgs = [{"agent_id": r, "influence_weight": 1.0} for r in range(1, 6)]
    fail_actions = [{"round": r, "agent_id": 1, "agent_name": "A"} for r in range(1, 7)]
    yield "failure", run_decision_channel(
        fail_actions, [{"agent_id": 1, "influence_weight": 1.0}], dict(seed),
        _FailingLLM(), inertia=0.5)
    yield "abstain", run_decision_channel(actions, cfgs, dict(seed), FakeLLMClient(
        json_responses=[{"decisions": [{"agent_id": r, "scenario": dc.ABSTAIN_TOKEN}]}
                        for r in range(1, 6)]), inertia=0.5)
    yield "silent", run_decision_channel(actions, cfgs, dict(seed), FakeLLMClient(
        json_responses=[{"decisions": []} for _ in range(5)]), inertia=0.5)
    yield "commit", run_decision_channel(actions, cfgs, dict(seed), FakeLLMClient(
        json_responses=[{"decisions": [{"agent_id": r, "scenario": "S1", "magnitude": 1,
                                        "confidence": 1}]} for r in range(1, 6)]),
        inertia=0.9)


def test_run_decision_channel_unchanged_plus_validity_reasons():
    expected = {
        "failure": ("invalid", "no_update", ["no_valid_rounds"]),
        "abstain": ("valid", "diagnostic_only", []),
        "silent": ("invalid", "no_update", ["no_valid_rounds"]),
        "commit": ("valid", "diagnostic_only", []),
    }
    for name, res in _containment_runs():
        assert set(res) == _LEGACY_RESULT_KEYS | {"validity_reasons"}, name
        acct = res["round_accounting"]
        # the post-hoc producer never adds unaccounted rounds: accounting is the raw
        # WorldState view, identical to the nested outcome copy
        assert acct == res["outcome"]["round_accounting"], name
        assert "unaccounted_rounds" not in acct, name
        assert (res["validity"], res["forecast_effect"]) == _legacy_verdict(acct), name
        assert (res["validity"], res["forecast_effect"],
                res["validity_reasons"]) == expected[name], name
        assert isinstance(res["validity_reasons"], list), name
        assert res["epistemic_status"] == "elicited_model_projection", name


def test_convergence_policy_is_not_modified():
    decision_channel_verdict(_accounting(ROUND_STATUS_COMMITTED), unaccounted_rounds=5)
    list(_containment_runs())
    assert CONVERGENCE_POLICY_V1 == _FROZEN_POLICY
