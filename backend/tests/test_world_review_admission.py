"""Fresh world admission no longer forces review mode v4 (model-facing review M1).

Before the fix, admission required policy.decisionReview "actor-consistency-v4", under
which an unknown or inconsistent self-verdict ended the run; v4 has not passed a full
behaviour study. No review pin is now the fresh default and v4 stays an explicit opt-in.
SDK construction is real and HTTP is a MockTransport, so the guarded runner owns this.
"""
from copy import deepcopy

import pytest

from test_world_default_admission import (  # noqa: F401 -- fixtures
    assert_error, no_transport, offline_http, profile, raw_spec, resolve, write_profile,
)

pytestmark = pytest.mark.guarded_runner


def without_review(value):
    value = deepcopy(value)
    for key in ("decisionReview", "candidateRepair"):
        value["policy"].pop(key)
    return value


def kwargs_for(source, value, tmp_path):
    if source == "file":
        return {"profile_path": write_profile(tmp_path, value)}
    return {"world_spec" if source == "raw" else "world_policy_spec": value}


@pytest.mark.parametrize("source", ["request", "raw", "file"])
def test_fresh_world_admits_no_review_pin(source, tmp_path, offline_http):  # noqa: F811
    from app.services.world_simulation.review import candidate_repair_enabled, review_mode

    value = without_review(raw_spec() if source == "raw" else profile())
    result = resolve(mode="full", simulation_engine="world-v1", **kwargs_for(source, value, tmp_path))
    resolved = result["world_spec"] if source == "raw" else result["world_policy_spec"]
    assert "decisionReview" not in resolved["policy"] and "candidateRepair" not in resolved["policy"]
    assert review_mode(resolved) is None and candidate_repair_enabled(resolved) is False
    assert resolved["policy"]["responseFormat"] == "json_object"
    assert result["simulation_admission_v1"]["status"] == "ready"
    assert offline_http.sent == []


def test_v4_stays_an_explicit_opt_in(offline_http):  # noqa: F811
    from app.services.world_simulation.review import MODE_V4

    result = resolve(mode="full", simulation_engine="world-v1", world_policy_spec=profile())
    assert result["world_policy_spec"]["policy"]["decisionReview"] == MODE_V4


@pytest.mark.parametrize("review", ["actor-consistency-v1", "actor-consistency-v2", "actor-consistency-v3",
                                    "unknown", [], True])
def test_fresh_world_still_rejects_historical_and_unknown_review_pins(review, no_transport):  # noqa: F811
    value = profile()
    value["policy"]["decisionReview"] = review
    if review != "actor-consistency-v3":
        value["policy"].pop("candidateRepair")
    assert_error("invalid_policy_metadata", mode="full", simulation_engine="world-v1", world_policy_spec=value)


def test_candidate_repair_without_a_review_pin_is_rejected(no_transport):  # noqa: F811
    value = profile()
    value["policy"].pop("decisionReview")
    assert_error("invalid_policy_metadata", mode="full", simulation_engine="world-v1", world_policy_spec=value)


def test_research_only_still_defers_without_a_review_pin(no_transport):  # noqa: F811
    result = resolve(mode="research_only", simulation_engine="world-v1",
                     world_policy_spec={"policy": without_review(profile())["policy"]})
    assert result["simulation_admission_v1"]["status"] == "deferred"
