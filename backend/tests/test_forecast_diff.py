"""Tech-debt fix: scheduled_rerun.forecast_diff was written offline-testable but had
zero tests. forecast_diff is pure; the rest of scheduled_rerun imports lazily."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))

import scheduled_rerun as sr  # noqa: E402


def _fc(scenarios):
    return {"scenarios": scenarios}


def test_no_drift_below_threshold():
    prev = _fc([{"name": "A", "probability": 0.6}, {"name": "B", "probability": 0.4}])
    curr = _fc([{"name": "A", "probability": 0.65}, {"name": "B", "probability": 0.35}])
    d = sr.forecast_diff(prev, curr, threshold=0.15)
    assert d["drift"] is False
    assert d["max_prob_delta"] == 0.05
    assert d["summary"] == "无实质性漂移"


def test_flags_probability_shift():
    prev = _fc([{"name": "A", "probability": 0.6}, {"name": "B", "probability": 0.4}])
    curr = _fc([{"name": "A", "probability": 0.3}, {"name": "B", "probability": 0.7}])
    d = sr.forecast_diff(prev, curr, threshold=0.15)
    assert d["drift"] is True
    assert any(c["name"] == "A" for c in d["scenario_changes"])
    assert d["max_prob_delta"] == 0.3


def test_new_and_dropped_scenarios_are_drift():
    d = sr.forecast_diff(_fc([{"name": "A", "probability": 1.0}]),
                         _fc([{"name": "B", "probability": 1.0}]), threshold=0.5)
    assert d["drift"] is True
    assert "B" in d["new_scenarios"] and "A" in d["dropped_scenarios"]


def test_null_probability_is_unscoreable_never_zero():
    """A needs_review forecast's null probability is not read as 0.0 (a fabricated shift)."""
    prev = _fc([{"name": "A", "probability": 0.6}, {"name": "B", "probability": 0.4}])
    curr = _fc([{"name": "A", "probability": None}, {"name": "B", "probability": 0.45}])
    d = sr.forecast_diff(prev, curr, threshold=0.15)
    assert d["drift"] is False
    assert d["scenario_changes"] == []
    assert d["max_prob_delta"] == 0.05
    assert d["unscoreable_scenarios"] == ["A"]
    assert "概率待复核" in d["summary"]
    # Unscoreable on the previous side, unparseable or non-finite values: same treatment.
    for bad in (None, "", "n/a", float("nan"), "inf"):
        d = sr.forecast_diff(_fc([{"name": "A", "probability": bad}]),
                             _fc([{"name": "A", "probability": 0.9}]), threshold=0.15)
        assert d["scenario_changes"] == [] and d["unscoreable_scenarios"] == ["A"], bad


def test_null_probability_new_and_dropped_scenarios():
    d = sr.forecast_diff(_fc([{"name": "A", "probability": None}]),
                         _fc([{"name": "B", "probability": None}]), threshold=0.5)
    assert d["drift"] is True
    assert d["new_scenarios"] == ["B"] and d["dropped_scenarios"] == ["A"]
    assert d["max_prob_delta"] == 0.0


def test_all_scoreable_diff_has_no_unscoreable_key():
    d = sr.forecast_diff(_fc([{"name": "A", "probability": 0.5}]),
                         _fc([{"name": "A", "probability": 0.5}]), threshold=0.15)
    assert "unscoreable_scenarios" not in d


def test_name_matching_is_normalized():
    prev = _fc([{"name": "Samsung leads", "probability": 0.5}, {"name": "其它", "probability": 0.5}])
    curr = _fc([{"name": "samsung  leads.", "probability": 0.52}, {"name": "其它", "probability": 0.48}])
    d = sr.forecast_diff(prev, curr, threshold=0.15)
    assert d["drift"] is False                     # matched by normalized name; small delta
    assert d["new_scenarios"] == [] and d["dropped_scenarios"] == []


def test_new_actors_flag_drift():
    d = sr.forecast_diff(
        _fc([{"name": "A", "probability": 1.0}]),
        _fc([{"name": "A", "probability": 1.0}]),
        threshold=0.15,
        prev_actors={"actors": [{"name": "X"}]},
        curr_actors={"actors": [{"name": "X"}, {"name": "Y"}]},
    )
    assert d["drift"] is True and "Y" in d["new_actors"]
