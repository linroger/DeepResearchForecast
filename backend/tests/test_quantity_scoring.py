"""EVAL-14 (P14): pure quantity-forecast scoring rules (quantity_scoring.py), against
hand-computed values."""

import math

import pytest

from app.services import quantity_scoring as qs


def test_pinball_known():
    # q10 = 10, y = 12: under-forecast by 2 -> tau * 2
    assert qs.pinball(10, 12, 0.1) == pytest.approx(0.2)
    assert qs.pinball(10, 12, 0.9) == pytest.approx(1.8)
    # over-forecast by 2 -> (1 - tau) * 2
    assert qs.pinball(14, 12, 0.1) == pytest.approx(1.8)
    assert qs.pinball(12, 12, 0.5) == 0.0
    with pytest.raises(ValueError):
        qs.pinball(10, 12, 1.0)
    with pytest.raises(ValueError):
        qs.pinball(float("nan"), 12, 0.5)


def test_constant_forecast_qs_equals_abs_error():
    for q, y in ((10.0, 13.0), (13.0, 10.0), (5.0, 5.0)):
        assert qs.quantile_score({0.1: q, 0.5: q, 0.9: q}, y) == pytest.approx(abs(q - y))
    assert qs.quantile_score({0.5: 7.0}, 10.0) == pytest.approx(3.0)


def test_quantile_score_known():
    # {0.1: 8, 0.5: 10, 0.9: 14}, y = 12: pinballs 0.4, 1.0, 0.2 -> (2/3) * 1.6
    assert qs.quantile_score({0.1: 8, 0.5: 10, 0.9: 14}, 12) == pytest.approx(2 / 3 * 1.6)


def test_interval_score_120_and_boundary_covered():
    assert qs.interval_score80(0, 100, 102) == pytest.approx(120.0)     # width 100 + 10 * 2
    assert qs.interval_score80(0, 100, -3) == pytest.approx(130.0)      # width 100 + 10 * 3
    assert qs.interval_score80(0, 100, 50) == pytest.approx(100.0)
    assert qs.covered80(0, 100, 100) and qs.covered80(0, 100, 0) and not qs.covered80(0, 100, 100.01)
    with pytest.raises(ValueError):
        qs.interval_score80(5, 4, 4.5)


def test_ape_disabled_for_rate_units():
    assert qs.ape50(110, 100, "GW") == pytest.approx(0.1)
    assert qs.ape50(110, 100, "USD") == pytest.approx(0.1)
    for unit in ("%", "pp", "bp"):
        assert qs.ape50(4.5, 4.0, unit) is None
    assert qs.ape50(1.0, 0.0, "GW") is None


def test_rel_to_persistence():
    assert qs.rel_to_persistence(2.0, 12.0, 8.0) == (0.5, None)
    assert qs.rel_to_persistence(2.0, 12.0, None) == (None, "no_persistence_anchor")
    assert qs.rel_to_persistence(2.0, 12.0, 12.0) == (None, "baseline_exact")


def test_threshold_ladder_brier_known():
    rungs = [(170, ">=", 0.57), (230, ">", 0.12)]
    # y = 200: rung 1 YES (0.43^2), rung 2 NO (0.12^2)
    assert qs.threshold_ladder_brier(rungs, 200) == pytest.approx((0.43 ** 2 + 0.12 ** 2) / 2)
    assert qs.threshold_ladder_brier([(5.0, "<", 0.8)], 4.0) == pytest.approx(0.04)
    with pytest.raises(ValueError):
        qs.threshold_ladder_brier([], 1.0)
    with pytest.raises(ValueError):
        qs.threshold_ladder_brier([(1.0, ">", 1.5)], 2.0)


def test_scoring_is_pure_stdlib():
    import ast
    import inspect
    tree = ast.parse(inspect.getsource(qs))
    imported = {alias.name.split(".")[0] for node in ast.walk(tree)
                if isinstance(node, (ast.Import, ast.ImportFrom))
                for alias in getattr(node, "names", [])}
    modules = {node.module.split(".")[0] for node in ast.walk(tree)
               if isinstance(node, ast.ImportFrom) and node.module}
    assert (imported | modules) <= {"__future__", "math", "typing", "annotations", "Any", "Dict",
                                    "Optional", "Sequence", "Tuple"}
    assert math.isfinite(qs.interval_score80(1, 2, 3))
