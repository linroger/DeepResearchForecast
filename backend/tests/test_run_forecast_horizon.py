"""Reported end-2027 prompts must reach the native calendar without truncation."""
from dataclasses import asdict
from datetime import date, timedelta
import json
from pathlib import Path

import pytest

from app.config import Config
from app.services.simulation_config_generator import SimulationConfigGenerator
from app.utils.sim_timeline import extract_horizon


CASES = json.loads((Path(__file__).parent / "fixtures/forecast_horizon_prompts.json").read_text())


@pytest.mark.parametrize("case", CASES, ids=lambda case: case["case"])
@pytest.mark.parametrize("cap", [None, 9, 3])
def test_actual_prompt_reaches_full_calendar_and_persisted_periods(case, cap, monkeypatch, tmp_path):
    generator = SimulationConfigGenerator.__new__(SimulationConfigGenerator)
    monkeypatch.setattr(generator, "_llm_extract_horizon", lambda *a: pytest.fail("explicit target needs no model"))
    monkeypatch.setattr(Config, "OASIS_DEFAULT_MAX_ROUNDS", 0)
    timeline = generator._build_temporal_timeline(
        case["prompt"], {"as_of_date": case["as_of_date"], "forecast_horizon": "October 2026"}, "", cap,
    )
    path = tmp_path / "simulation_config.json"
    path.write_text(json.dumps({"temporal_config": asdict(timeline)}))
    saved = json.loads(path.read_text())["temporal_config"]
    assert saved["horizon_date"] == case["expected_horizon"]
    assert saved["horizon_source"] == "explicit_date"
    assert saved["horizon_text"] == "December 31, 2027"
    assert saved["round_dates"][-1]["period_end"] == case["expected_horizon"]
    assert saved["unit"] != "day"
    assert saved["n_rounds"] == len(saved["round_dates"])
    if cap:
        assert saved["n_rounds"] <= cap
    day = date.fromisoformat(case["as_of_date"]) + timedelta(days=1)
    for period in saved["round_dates"]:
        assert date.fromisoformat(period["period_start"]) == day
        day = date.fromisoformat(period["period_end"]) + timedelta(days=1)
    assert day == date(2028, 1, 1)


@pytest.mark.parametrize("text,endpoint,source", [
    ("Forecast through December 31, 2027. Baseline October 2026.", "2027-12-31", "explicit_date"),
    ("Forecast as of 31 December 2027. Baseline October 2026.", "2027-12-31", "explicit_date"),
    ("Forecast through Dec. 31st, 2027. Baseline October 2026.", "2027-12-31", "explicit_date"),
    ("Forecast as of 31st Dec 2027. Baseline October 2026.", "2027-12-31", "explicit_date"),
    ("Forecast through February 29, 2028.", "2028-02-29", "explicit_date"),
    ("Forecast at end-2027. Baseline October 2026.", "2027-12-31", "anchored_period"),
    ("Forecast at year-end 2027. Baseline October 2026.", "2027-12-31", "anchored_period"),
    ("Forecast at end of 2027. Baseline October 2026.", "2027-12-31", "anchored_period"),
    ("Forecast by November 2, 2026. Background end-2027.", "2026-11-02", "explicit_date"),
    ("Forecast by 2026-11-02. Background December 31, 2027.", "2026-11-02", "explicit_date"),
    ("预测截至2027年12月31日，基准2026年10月。", "2027-12-31", "explicit_date"),
])
def test_date_spellings_keep_target_and_short_user_windows(text, endpoint, source):
    horizon = extract_horizon(text, date(2026, 10, 22))
    assert horizon.horizon_date == endpoint
    assert horizon.source == source


@pytest.mark.parametrize("text", [
    "Forecast through February 30, 2027, not a valid date; deadline 2027-06-30.",
    "Forecast through April 31, 2027, not a valid date; deadline 2027-06-30.",
])
def test_impossible_named_date_does_not_override_real_endpoint(text):
    assert extract_horizon(text, date(2026, 10, 22)).horizon_date == "2027-06-30"


@pytest.mark.parametrize("text", [
    "Forecast the state of the Russia-Ukraine war as of end of 2027. Deliver a binary forecast: a ceasefire enters into force before July 1, 2027.",
    "Forecast gold at end-2027. Include milestones: exceeds $5,000 by July 1, 2027.",
    "Forecast US policy through end of 2027.\n\nResearch the July 1, 2027 deadline.",
    "预测2027年底的局势。例如，预测停火能否于2027年7月1日前生效。",
])
def test_primary_objective_outranks_secondary_binary_dates(text):
    assert extract_horizon(text, date(2026, 10, 22)).horizon_date == "2027-12-31"


def test_explicit_cap_equal_to_soft_default_is_still_enforced(monkeypatch):
    generator = SimulationConfigGenerator.__new__(SimulationConfigGenerator)
    monkeypatch.setattr(Config, "SIM_CALENDAR_TARGET_MAX_ROUNDS", 36)
    monkeypatch.setattr(Config, "SIM_CALENDAR_HARD_MAX_ROUNDS", 48)
    monkeypatch.setattr(Config, "OASIS_DEFAULT_MAX_ROUNDS", 0)
    args = ("Forecast until 2026-12-09", {"as_of_date": "2026-10-22"}, "")
    soft = generator._build_temporal_timeline(*args)
    capped = generator._build_temporal_timeline(*args, max_rounds=36)
    assert soft.n_rounds == 48  # Default anti-sawtooth policy remains compatible.
    assert capped.n_rounds <= 36
    assert soft.horizon_date == capped.horizon_date == "2026-12-09"
    assert capped.round_dates[-1].period_end == "2026-12-09"
    assert capped.round_cap_coarsened["cap"] == 36


@pytest.mark.parametrize("case", CASES, ids=lambda case: case["case"])
def test_generated_calendar_reaches_actor_clock_and_native_round_loop(case, monkeypatch, tmp_path):
    # Reuse the established real-loop harness: only model/platform responses are
    # scripted. Calendar iteration, clock injection and durable outputs are real.
    import test_calendar_round_loop as native
    generator = SimulationConfigGenerator.__new__(SimulationConfigGenerator)
    monkeypatch.setattr(generator, "_llm_extract_horizon", lambda *a: pytest.fail("unneeded model"))
    monkeypatch.setattr(Config, "OASIS_DEFAULT_MAX_ROUNDS", 0)
    timeline = generator._build_temporal_timeline(case["prompt"], {"as_of_date": case["as_of_date"]}, "", 9)
    config = native._calendar_config()
    config["simulation_id"] = "sim_horizon_" + case["case"]
    config["temporal_config"] = asdict(timeline)
    config["time_config"]["total_simulation_hours"] = timeline.n_rounds
    config["world_state_seed"].update(as_of_date=case["as_of_date"], horizon_date=timeline.horizon_date)
    config["event_config"]["scheduled_events"] = []
    envs, calls = [], []
    native._patch_runtime(monkeypatch, str(tmp_path), envs)
    monkeypatch.setattr(native.dc, "elicit_round", native._fake_elicit(calls))
    native._run(config, str(tmp_path), max_rounds=1)
    assert len(calls) == timeline.n_rounds
    assert calls[-1]["ctx"]["period"]["period_end"] == "2027-12-31"
    assert all(call["ctx"]["horizon_date"] == "2027-12-31" for call in calls)
    clocks = native._world_clock_notes(envs[0])
    assert clocks and all("forecast horizon 2027-12-31" in note for note in clocks)
    assert any(f"round {timeline.n_rounds}/{timeline.n_rounds}" in note for note in clocks)
    events = native._read_events(str(tmp_path))
    ends = [e for e in events if e.get("event_type") == "round_end" and e.get("round")]
    assert ends[-1]["period_end"] == "2027-12-31"
    trajectory = json.loads((tmp_path / "world_state_trajectory.json").read_text())
    assert trajectory["horizon_date"] == "2027-12-31"
    assert trajectory["trajectory"][-1]["period_end"] == "2027-12-31"
