"""Bounded world facts that still let an actor's own announced setting land (pure, offline).

Before 2026-10-20 the arbiter's changes were clamped to ``max_change_ratio`` of a fact's magnitude
per period, but a delayed effect it scheduled was applied without any bound, while an actor's own
announced instrument setting (a tariff raised from 20% to 145% in one month) was clamped and took
several periods to land.  Now delayed effects are clamped like immediate changes, and a change the
arbiter attributes (``caused_by``) to the actor whose move this period stated the figure applies in
full — never across zero.
"""

import pytest

from app.services import world_update as wu
from app.services.world_model import (
    DEFAULT_MAX_CHANGE_RATIO, DEFAULT_MAX_DRIFT_RATIO, DEFAULT_REVERSION_KAPPA,
    PendingEffect, WorldModel, announced_figures,
)


def _expected_damped_numeric(current, requested, *, anchor=None, ratio=DEFAULT_MAX_CHANGE_RATIO):
    """Independent arithmetic oracle for the positive numeric fixtures, not a kernel call.

    First bound the requested step, then retain (1-kappa) of its distance from
    the research anchor, then intersect with the anchor's cumulative drift band.
    """
    anchor = current if anchor is None else anchor
    step = requested if ratio is None else max(
        current - abs(current) * ratio, min(requested, current + abs(current) * ratio))
    reverted = anchor + (step - anchor) * (1 - DEFAULT_REVERSION_KAPPA)
    return max(anchor * (1 - DEFAULT_MAX_DRIFT_RATIO),
               min(reverted, anchor * (1 + DEFAULT_MAX_DRIFT_RATIO)))


def _world(ratio: float | None = 0.5):
    seed = {
        "question": "Will the tariff truce hold through 2026?",
        "scenarios": ["Truce holds", "Escalation"],
        "state_variables": [
            {"name": "US tariff on Chinese goods", "value": "20%", "provenance": "official"},
            {"name": "Rare earth export volume", "value": 4000, "unit": "tonnes", "provenance": "official"},
            {"name": "Trade balance", "value": 120, "unit": "USD bn", "provenance": "official"},
        ],
        "actors": [
            {"agent_id": 0, "name": "United States Government", "agency_class": "sovereign_government"},
            {"agent_id": 1, "name": "China Ministry of Commerce", "agency_class": "sovereign_government"},
            {"agent_id": 2, "name": "Market Analysts", "agency_class": "media_outlet"},
        ],
        "settings": {"max_change_ratio": ratio},
    }
    cfgs = [{"agent_id": i, "entity_name": n} for i, n in
            enumerate(["United States Government", "China Ministry of Commerce", "Market Analysts"])]
    return WorldModel.from_seed(seed, cfgs)


def _move(agent_id, name, option_id, kind, statement, terms=""):
    return {"agent_id": agent_id, "actor_name": name,
            "option": {"id": option_id, "label": option_id.replace("_", " "), "kind": kind, "cost": 1, "lag": 0},
            "targets": [], "magnitude": 0.9, "public_statement": statement, "terms": terms, "status": "ok"}


def _apply(world, change):
    return world.apply_arbiter_update(1, {"variable_changes": [change]})


def test_announced_figures_are_scaled_like_researched_values():
    assert announced_figures("We raise the tariff to 145% effective 10 April") == [145.0, 10.0]
    assert announced_figures("a US$2 billion fund and 1.5 million barrels") == [2e9, 1.5e6]
    assert announced_figures("") == []


def test_an_announced_tariff_lands_in_full_and_says_who_set_it():
    world = _world()
    world.start_round(1, {"label": "2026-04"})
    world.register_decisions(1, [_move(0, "United States Government", "impose_measure", "policy",
                                       "Tariffs on Chinese goods rise to 145% from Thursday.")])
    summary = _apply(world, {"variable_id": "us_tariff_on_chinese_goods", "new_value": 145,
                             "caused_by": "United States Government", "rationale": "executive order"})
    var = world.variables["us_tariff_on_chinese_goods"]
    assert var.value == 145.0
    assert var.provenance == "action" and var.history[-1]["source"] == "action"
    assert var.history[-1]["cause"].startswith("United States Government announced it")
    assert summary["variables_changed"][0]["announced_by"] == "United States Government"


def test_the_size_of_an_announced_change_counts_as_announcing_it():
    world = _world()
    world.start_round(1, None)
    world.register_decisions(1, [_move(0, "United States Government", "impose_measure", "policy",
                                       "We add 125 percentage points to the tariff.")])
    _apply(world, {"variable_id": "us_tariff_on_chinese_goods", "delta": 125, "caused_by": "United States Government"})
    assert world.variables["us_tariff_on_chinese_goods"].value == 145.0


def test_unannounced_or_misattributed_jumps_stay_clamped():
    world = _world()
    world.start_round(1, None)
    world.register_decisions(1, [
        _move(0, "United States Government", "impose_measure", "policy", "We will raise tariffs sharply."),
        _move(2, "Market Analysts", "publish_report", "communication", "Tariffs could reach 145%."),
    ])
    _apply(world, {"variable_id": "us_tariff_on_chinese_goods", "new_value": 145, "caused_by": "United States Government"})
    expected = pytest.approx(_expected_damped_numeric(20, 145))
    assert world.variables["us_tariff_on_chinese_goods"].value == expected     # no figure stated: damp
    assert world.variables["us_tariff_on_chinese_goods"].provenance == "arbiter"
    world = _world()
    world.start_round(1, None)
    world.register_decisions(1, [_move(2, "Market Analysts", "publish_report", "communication",
                                       "Tariffs could reach 145%.")])
    _apply(world, {"variable_id": "us_tariff_on_chinese_goods", "new_value": 145, "caused_by": "Market Analysts"})
    assert world.variables["us_tariff_on_chinese_goods"].value == expected     # commentary sets nothing
    assert world.variables["us_tariff_on_chinese_goods"].provenance == "arbiter"
    world = _world()
    world.start_round(1, None)
    _apply(world, {"variable_id": "us_tariff_on_chinese_goods", "new_value": 145})
    assert world.variables["us_tariff_on_chinese_goods"].value == expected     # no attribution
    assert world.variables["us_tariff_on_chinese_goods"].provenance == "arbiter"


def test_a_move_from_an_earlier_period_or_a_hold_announces_nothing():
    world = _world()
    world.start_round(1, None)
    world.register_decisions(1, [_move(0, "United States Government", "impose_measure", "policy",
                                       "Tariffs rise to 145%.")])
    world.start_round(2, None)
    world.apply_arbiter_update(2, {"variable_changes": [{"variable_id": "us_tariff_on_chinese_goods",
                                                         "new_value": 145, "caused_by": "United States Government"}]})
    assert world.variables["us_tariff_on_chinese_goods"].value == pytest.approx(
        _expected_damped_numeric(20, 145))
    assert world.variables["us_tariff_on_chinese_goods"].provenance == "arbiter"


def test_an_announced_setting_never_crosses_zero():
    world = _world()
    world.start_round(1, None)
    world.register_decisions(1, [_move(1, "China Ministry of Commerce", "impose_measure", "policy",
                                       "The balance will swing to -40 within the month.")])
    _apply(world, {"variable_id": "trade_balance", "new_value": -40, "caused_by": "China Ministry of Commerce"})
    assert world.variables["trade_balance"].value == pytest.approx(
        _expected_damped_numeric(120, -40))                                   # falls back to damping
    assert world.variables["trade_balance"].value > 0
    assert world.variables["trade_balance"].provenance == "arbiter"


def test_an_acceptance_announces_the_figures_of_the_offer_it_adopts():
    world = _world()
    world.start_round(1, None)
    world.register_decisions(1, [{**_move(0, "United States Government", "open_talks", "coalition",
                                          "We propose a truce.", terms="Cut the tariff to 10% for 90 days"),
                                  "targets": ["China Ministry of Commerce"]}])
    (offer_id,) = list(world.interactions)
    world.start_round(2, None)
    world.register_decisions(2, [{**_move(1, "China Ministry of Commerce", f"accept:{offer_id}", "coalition",
                                          "Agreed."), "targets": ["United States Government"]}])
    world.apply_arbiter_update(2, {"variable_changes": [{"variable_id": "us_tariff_on_chinese_goods",
                                                         "new_value": 10, "caused_by": "China Ministry of Commerce"}]})
    assert world.variables["us_tariff_on_chinese_goods"].value == 10.0


def test_delayed_effects_are_clamped_like_immediate_changes():
    world = _world()
    world.start_round(1, None)
    world.pending_effects.append(PendingEffect("fx1", due_round=1, description="Export licences frozen",
                                               variable_id="rare_earth_export_volume", op="add", value=-3900,
                                               source="arbiter"))
    world.fire_due_effects(1, None)
    expected = _expected_damped_numeric(4000, 4000 - 3900)
    var = world.variables["rare_earth_export_volume"]
    assert var.value == pytest.approx(expected)
    assert var.provenance == "effect" and "damped" in var.history[-1]["cause"]
    immediate = _world()
    immediate.start_round(1, None)
    _apply(immediate, {"variable_id": "rare_earth_export_volume", "delta": -3900})
    assert immediate.variables["rare_earth_export_volume"].value == var.value

    # Turning off only the per-step clamp leaves anchor/drift controls active.
    step_unbounded = _world(ratio=None)
    step_unbounded.start_round(1, None)
    step_unbounded.pending_effects.append(PendingEffect("fx1", due_round=1, description="Freeze",
                                                       variable_id="rare_earth_export_volume", op="add",
                                                       value=-3900, source="arbiter"))
    step_unbounded.fire_due_effects(1, None)
    assert step_unbounded.variables["rare_earth_export_volume"].value == pytest.approx(
        _expected_damped_numeric(4000, 100, ratio=None))

    # Explicit all-controls-off compatibility is confined to this pure unit control.
    unbounded = _world(ratio=None)
    unbounded.settings.update(reversion_kappa=None, max_drift_ratio=None)
    unbounded.start_round(1, None)
    unbounded.pending_effects.append(PendingEffect("fx1", due_round=1, description="Freeze",
                                                   variable_id="rare_earth_export_volume", op="add",
                                                   value=-3900, source="arbiter"))
    unbounded.fire_due_effects(1, None)
    assert unbounded.variables["rare_earth_export_volume"].value == 100.0


def test_validation_keeps_a_cast_attribution_and_drops_an_unknown_one():
    world = _world()
    update, problems = wu.validate_arbiter_update({"variable_changes": [
        {"variable_id": "us_tariff_on_chinese_goods", "new_value": 145, "caused_by": "the united states government"},
        {"variable_id": "rare_earth_export_volume", "delta": -100, "caused_by": "Nobody Inc"},
    ]}, world)
    assert update["variable_changes"][0]["caused_by"] == "United States Government"
    assert "caused_by" not in update["variable_changes"][1]
    assert any("caused_by" in p for p in problems)


def test_the_arbiter_is_told_the_rule():
    prompt = wu.build_arbiter_prompt(_world(), 1, None, [], {}, ["Truce holds", "Escalation"])
    assert '"caused_by"' in prompt
    assert "a stated figure takes effect in full" in prompt
    assert "limited to about ±50% of the current value per period" in prompt
    assert "limited to about" not in wu.build_arbiter_prompt(_world(ratio=None), 1, None, [], {}, [])
