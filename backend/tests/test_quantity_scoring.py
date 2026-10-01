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
    assert qs.ape50(110, 100, "USD billion") == pytest.approx(0.1)
    assert qs.ape50(110, 100, "million units") == pytest.approx(0.1)
    # every spelling of a rate unit, not just the canonical symbols
    for unit in ("%", "pp", "bp", "percent", "pct", "percentage", "percentage points",
                 "bps", "basis points", "% of GDP", "pp YoY", "百分点", "基点"):
        assert qs.ape50(4.5, 4.0, unit) is None, unit
    # a unit that cannot be read is not known to be a level
    for unit in (None, "", "% billion", 42):
        assert qs.ape50(4.5, 4.0, unit) is None, unit
    assert qs.ape50(1.0, 0.0, "GW") is None


def test_huge_integers_raise_value_error_not_overflow():
    huge = 10 ** 400
    for call in (lambda: qs.pinball(huge, 1.0, 0.5), lambda: qs.interval_score80(0, huge, 1),
                 lambda: qs.ape50(1.0, huge, "GW"), lambda: qs.rel_to_persistence(1.0, 2.0, huge),
                 lambda: qs.threshold_ladder_brier([(huge, ">", 0.5)], 1.0)):
        with pytest.raises(ValueError):
            call()


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


def _module_imports(module):
    """(stdlib top-level modules, relative sibling modules) imported anywhere in ``module``."""
    import ast
    import inspect
    absolute, relative = set(), set()
    for node in ast.walk(ast.parse(inspect.getsource(module))):
        if isinstance(node, ast.Import):
            absolute |= {alias.name.split(".")[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom):
            (relative if node.level else absolute).add((node.module or "").split(".")[0])
    return absolute, relative


def test_scoring_is_pure_stdlib():
    import sys
    from app.services import binary_targets
    stdlib = set(sys.stdlib_module_names) | {"__future__"}
    absolute, relative = _module_imports(qs)
    assert absolute <= stdlib and relative == {"binary_targets"}
    # the one sibling it uses is pure too: stdlib at module level, and its only relative
    # import (the extractor, for the criteria cross-check) is lazy, inside a function
    import ast
    import inspect
    tree = ast.parse(inspect.getsource(binary_targets))
    top_level = {alias.name.split(".")[0] for node in tree.body
                 if isinstance(node, ast.Import) for alias in node.names}
    top_level |= {node.module.split(".")[0] for node in tree.body
                  if isinstance(node, ast.ImportFrom) and node.module and not node.level}
    assert top_level <= stdlib
    assert not [node for node in tree.body if isinstance(node, ast.ImportFrom) and node.level]
    assert math.isfinite(qs.interval_score80(1, 2, 3))
