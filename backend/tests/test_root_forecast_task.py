"""Task/calendar admission, not another prose-only deadline heuristic."""
from copy import deepcopy
from dataclasses import asdict
from datetime import date
import json
import asyncio
import subprocess
import sys
from pathlib import Path

import pytest

from app.config import Config
from app.services.forecast_task import KEY, ForecastTaskError, bind_task, validate_task_calendar
from app.services.simulation_config_generator import SimulationConfigGenerator
from app.services.simulation_manager import build_simulation_config_seal
from app.utils.sim_timeline import HorizonResult, build_timeline


QUESTION = "Forecast gold through December 31, 2027. Baseline: October 2026."


def config():
    calendar = asdict(build_timeline(date(2026, 10, 22), HorizonResult(
        "2027-12-31", "explicit_date", "December 31, 2027", False, 1.0), 36))
    return {"simulation_id": "sim_root_task", "simulation_requirement": QUESTION,
            "as_of_date": "2026-10-22", "temporal_config": calendar,
            "world_model": {"schema_version": "world-model-seed/v1", "state_variables": [], "actors": [],
                            "relationships": [], "settings": {},
                            "as_of_date": "2026-10-22", "horizon_date": "2027-12-31"},
            KEY: bind_task(QUESTION, calendar)}


@pytest.mark.parametrize("mutation", ["endpoint", "gap", "count", "question", "world", "world_type", "downgrade", "null"])
def test_native_child_rejects_task_calendar_drift_before_runtime(tmp_path, mutation):
    from scripts.run_parallel_simulation import load_config
    data = config()
    if mutation == "endpoint":
        data["temporal_config"]["horizon_date"] = "2026-10-31"
    elif mutation == "gap":
        data["temporal_config"]["round_dates"][1]["period_start"] = "2027-01-01"
    elif mutation == "count":
        data["temporal_config"]["n_rounds"] = 1
    elif mutation == "question":
        data["simulation_requirement"] = "Forecast until 2028."
    elif mutation == "world":
        data["world_model"]["horizon_date"] = "2026-10-31"
    elif mutation == "world_type":
        data["world_model"] = []
    elif mutation == "downgrade":
        del data["temporal_config"]
    else:
        data[KEY] = None
    path = tmp_path / "simulation_config.json"
    path.write_text(json.dumps(data))
    with pytest.raises(ForecastTaskError):
        load_config(str(path))


def test_native_seal_will_not_bless_inconsistent_task(tmp_path):
    data = config()
    data["temporal_config"]["horizon_date"] = "2026-10-31"
    (tmp_path / "simulation_config.json").write_text(json.dumps(data))
    with pytest.raises(ForecastTaskError):
        build_simulation_config_seal(str(tmp_path), simulation_id="sim_root_task",
                                     actor_cast_manifest_sha256=None,
                                     actor_context_manifest_sha256=None, actor_role_manifest_sha256={})
    assert not (tmp_path / "simulation_config_manifest.json").exists()


def test_calendar_preparation_failure_cannot_silently_become_hours(monkeypatch):
    generator = SimulationConfigGenerator.__new__(SimulationConfigGenerator)
    monkeypatch.setattr(Config, "SIM_TEMPORAL_MODE", "calendar")
    monkeypatch.setattr(generator, "_build_context", lambda **k: QUESTION)
    def broken(*args, **kwargs):
        raise ForecastTaskError("unresolved goal endpoint")
    monkeypatch.setattr(generator, "admit_forecast_task", broken)
    monkeypatch.setattr(generator, "_generate_time_config", lambda *a: pytest.fail("silent hours fallback"))
    with pytest.raises(ForecastTaskError, match="unresolved"):
        generator.generate_config("sim_task", "proj_task", "graph_task", QUESTION, "", [],
                                  actors={"as_of_date": "2026-10-22"})


def test_valid_task_survives_json_reopen_and_legacy_stays_explicit(tmp_path):
    from scripts.run_parallel_simulation import load_config
    data = config()
    path = tmp_path / "simulation_config.json"
    path.write_text(json.dumps(data))
    loaded = load_config(str(path))
    assert validate_task_calendar(loaded) == data[KEY]
    legacy = deepcopy(data)
    del legacy[KEY]
    assert validate_task_calendar(legacy) is None


def test_unresolved_policy_default_is_not_a_forecast_objective():
    data = config()
    calendar = data["temporal_config"]
    calendar.update(horizon_source="default", horizon_text="", horizon_defaulted=True)
    with pytest.raises(ForecastTaskError, match="unresolved"):
        bind_task(QUESTION, calendar)


def test_wrong_date_evidence_is_not_blessed_by_a_checksum():
    data = config()
    calendar = data["temporal_config"]
    calendar["horizon_text"] = "October 2026"
    with pytest.raises(ForecastTaskError, match="quoted date"):
        bind_task(QUESTION, calendar)


@pytest.mark.parametrize("platform", ["twitter", "reddit"])
def test_direct_platform_cannot_dispatch_a_downgraded_task(platform, tmp_path, monkeypatch):
    import scripts.run_parallel_simulation as runtime
    data = config()
    del data["temporal_config"]
    monkeypatch.setattr(runtime, "create_model", lambda *a, **k: pytest.fail("invalid task reached provider construction"))
    with pytest.raises(ForecastTaskError):
        asyncio.run(getattr(runtime, f"run_{platform}_simulation")(data, str(tmp_path)))
    assert list(tmp_path.iterdir()) == []


def test_admitted_task_reaches_native_clock_trajectory_and_report(tmp_path, monkeypatch):
    import test_calendar_round_loop as native
    from app.services.report_agent import ReportAgent
    data = config()
    cfg = native._calendar_config()
    cfg.update({k: data[k] for k in ("simulation_id", "simulation_requirement", "as_of_date", KEY, "temporal_config")})
    cfg["world_state_seed"].update(as_of_date=data["as_of_date"], horizon_date="2027-12-31")
    cfg["time_config"]["total_simulation_hours"] = data["temporal_config"]["n_rounds"]
    cfg["event_config"]["scheduled_events"] = []
    directory = tmp_path / cfg["simulation_id"]
    envs, calls = [], []
    native._patch_runtime(monkeypatch, str(directory), envs)
    monkeypatch.setattr(native.dc, "elicit_round", native._fake_elicit(calls))
    (directory / "simulation_config.json").write_text(json.dumps(cfg))
    native._run(cfg, str(directory), max_rounds=1)
    assert calls[-1]["ctx"]["period"]["period_end"] == "2027-12-31"
    assert all("forecast horizon 2027-12-31" in note for note in native._world_clock_notes(envs[0]))
    monkeypatch.setattr(Config, "OASIS_SIMULATION_DATA_DIR", str(tmp_path))
    agent = ReportAgent.__new__(ReportAgent)
    agent.simulation_id = cfg["simulation_id"]
    assert agent._temporal_horizon_date() == "2027-12-31"
    trajectory = directory / "world_state_trajectory.json"
    changed = json.loads(trajectory.read_text())
    for mutation in ("endpoint", "baseline", "seed", "partial", "task", "config", "shares"):
        bad = deepcopy(changed)
        if mutation == "endpoint":
            bad["horizon_date"] = "2026-10-31"
        elif mutation == "baseline":
            bad["as_of_date"] = "2020-01-01"
        elif mutation == "seed":
            bad["trajectory"][0]["as_of"] = "2020-01-01"
        elif mutation == "partial":
            bad["trajectory"].pop()
        elif mutation == "config":
            bad["config_hash"] = "0" * 64
        elif mutation == "shares":
            bad["outcome"]["shares"] = {"A": 0.99, "B": 0.01}
        else:
            bad["forecast_task_sha256"] = "0" * 64
        trajectory.write_text(json.dumps(bad))
        with pytest.raises(ForecastTaskError, match="trajectory"):
            agent._temporal_horizon_date()
        with pytest.raises(ForecastTaskError, match="trajectory"):
            agent._simulation_anchor_inputs()
        with pytest.raises(RuntimeError, match="trajectory"):
            agent._enforce_final_publish_audit("report_task_changed", None)
    trajectory.write_text(json.dumps(changed))


@pytest.mark.parametrize("baseline", ["2026-02-30", "2026-02", "2026", "2026-13-01"])
def test_invalid_complete_or_partial_baseline_is_rejected_before_models(baseline, monkeypatch):
    generator = SimulationConfigGenerator.__new__(SimulationConfigGenerator)
    monkeypatch.setattr(Config, "SIM_TEMPORAL_MODE", "calendar")
    monkeypatch.setattr(generator, "_call_llm_with_retry", lambda *a: pytest.fail("bad baseline reached model"))
    with pytest.raises(ForecastTaskError, match="baseline"):
        generator.admit_forecast_task(QUESTION, {"as_of_date": baseline})


def test_present_invalid_report_config_cannot_select_old_trajectory(tmp_path, monkeypatch):
    from app.services.report_agent import ReportAgent
    directory = tmp_path / "sim_root_task"
    directory.mkdir()
    (directory / "simulation_config.json").write_text("[]")
    (directory / "world_state_trajectory.json").write_text(json.dumps(
        {"mode": "calendar", "horizon_date": "2030-12-31", "outcome": {"shares": {"A": 1.0}}}))
    monkeypatch.setattr(Config, "OASIS_SIMULATION_DATA_DIR", str(tmp_path))
    agent = ReportAgent.__new__(ReportAgent)
    agent.simulation_id = directory.name
    for consumer in (agent._temporal_horizon_date, agent._simulation_anchor_inputs):
        with pytest.raises(ForecastTaskError, match="not an object"):
            consumer()


def test_real_prepare_seals_task_and_child_report_use_same_endpoint(prepare_env, monkeypatch):
    from tests.test_context_audit_prepare import _dossier, _prepare, _config
    from scripts.run_parallel_simulation import load_config
    from app.services.report_agent import ReportAgent
    dossier = _dossier()
    dossier["forecast_horizon"] = "through 2029"
    manager, state = _prepare(dossier)
    directory, data = _config(manager, state)
    assert data[KEY]["horizon_date"] == "2029-12-31"
    assert manager.validate_prepared_simulation_config(state.simulation_id)
    loaded = load_config(str(directory / "simulation_config.json"), state.simulation_config_sha256)
    assert loaded[KEY] == data[KEY]
    monkeypatch.setattr(Config, "OASIS_SIMULATION_DATA_DIR", str(directory.parent))
    agent = ReportAgent.__new__(ReportAgent)
    agent.simulation_id = state.simulation_id
    assert agent._temporal_horizon_date() == "2029-12-31"


def test_unresolved_goal_fails_before_graph_or_persona_work(prepare_env, monkeypatch):
    from app.services.simulation_manager import SimulationManager, SimulationStatus
    monkeypatch.setattr("app.services.simulation_manager.ZepEntityReader",
                        lambda: pytest.fail("unresolved task reached graph/persona preparation"))
    manager = SimulationManager()
    created = manager.create_simulation("root-project", "root-graph")
    with pytest.raises(ForecastTaskError, match="unresolved"):
        manager.prepare_simulation(created.simulation_id, "What happens next?", "")
    assert manager.get_simulation(created.simulation_id).status == SimulationStatus.FAILED


def test_model_task_resolution_requires_exact_iso_date_and_source_quote(monkeypatch):
    generator = SimulationConfigGenerator.__new__(SimulationConfigGenerator)
    source = "Forecast through the end of the following calendar year."
    good = {"horizon_date": "2027-12-31", "source_quote": "the end of the following calendar year"}
    monkeypatch.setattr(generator, "_call_llm_with_retry", lambda *a: good)
    assert generator._llm_extract_horizon(source, date(2026, 10, 22)).matched_text == good["source_quote"]
    for bad in [{"horizon_date": "2027", "source_quote": good["source_quote"]},
                {"horizon_date": "2027-02-30", "source_quote": good["source_quote"]},
                {"horizon_date": "2027-12-31", "source_quote": "invented unrelated date"},
                {"horizon_date": "2027-12-31"}]:
        monkeypatch.setattr(generator, "_call_llm_with_retry", lambda *a: bad)
        assert generator._llm_extract_horizon(source, date(2026, 10, 22)) is None


def test_conflicting_news_window_needs_source_bound_resolution(monkeypatch):
    generator = SimulationConfigGenerator.__new__(SimulationConfigGenerator)
    question = "Using October 2026 as baseline, forecast through the end of the following calendar year."
    actors = {"as_of_date": "2026-10-22", "central_question": "What happens by end of 2027?"}
    from tests.forecast_task_fakes import task_protocol
    expected = {"horizon_date": "2027-12-31", "source_field": "requirement",
                "source_quote": "the end of the following calendar year"}
    seen = []
    def model(prompt, system):
        seen.append(prompt)
        return task_protocol(prompt, expected)
    monkeypatch.setattr(generator, "_call_task_json", model)
    task = generator.admit_forecast_task(question, actors)
    assert task["horizon_date"] == "2027-12-31"
    assert task["resolution"]["method"] == "llm"
    assert task["resolution"]["source_quote"] in question
    assert len(seen) == 2 and seen[1].startswith("FORECAST TASK REVIEW")
    assert task["resolution"]["semantic_review"]["faithful"] is True
    monkeypatch.setattr(generator, "_call_task_json", lambda *a: {})
    with pytest.raises(ForecastTaskError, match="unresolved"):
        generator.admit_forecast_task(question, actors)


def test_separate_interpreter_reopens_task_then_rejects_corrupt_calendar(tmp_path):
    data = config()
    path, output = tmp_path / "simulation_config.json", tmp_path / "child-task.json"
    path.write_text(json.dumps(data))
    command = [sys.executable, "-B", str(Path(__file__).resolve()), "--task-read", str(path), str(output)]
    child = subprocess.run(command, capture_output=True, text=True, timeout=60, check=False)
    assert child.returncode == 0, child.stderr
    assert json.loads(output.read_text())[KEY] == data[KEY]
    output.unlink()
    data["temporal_config"]["unit"] = "day"
    path.write_text(json.dumps(data))
    child = subprocess.run(command, capture_output=True, text=True, timeout=60, check=False)
    assert child.returncode == 0
    assert json.loads(output.read_text()) == {"status": "rejected", "error_type": "ForecastTaskError"}


@pytest.mark.parametrize("case", json.loads((Path(__file__).parent / "fixtures/forecast_horizon_prompts.json").read_text()),
                         ids=lambda case: case["case"])
def test_actual_forecast_task_is_reviewed_once_then_reused_in_config(case, monkeypatch):
    from tests.forecast_task_fakes import task_protocol
    from app.services.simulation_config_generator import SimulationParameters
    generator = SimulationConfigGenerator.__new__(SimulationConfigGenerator)
    generator.provider, generator.model_name, generator.base_url = "fixture", "fixture", ""
    expected = {"horizon_date": "2027-12-31", "source_field": "requirement", "source_quote": "December 31, 2027"}
    calls = []
    def model(prompt, system):
        calls.append(prompt)
        return task_protocol(prompt, expected)
    monkeypatch.setattr(generator, "_call_task_json", model)
    monkeypatch.setattr(generator, "_build_temporal_timeline", lambda *a, **k: pytest.fail("prose date guessing reached default admission"))
    monkeypatch.setattr(generator, "_build_context", lambda **k: "bounded context")
    monkeypatch.setattr(generator, "_generate_event_config", lambda *a, **k: {})
    monkeypatch.setattr(Config, "SIM_TEMPORAL_MODE", "calendar")
    monkeypatch.setattr(Config, "SIM_WORLD_MODEL", False)
    monkeypatch.setattr(Config, "SIM_WORLD_BRIEF", False)
    actors = {"as_of_date": case["as_of_date"]}
    admitted = generator.admit_forecast_task(case["prompt"], actors, 9)
    produced = generator.generate_config("sim_goal", "proj_goal", "graph_goal", case["prompt"], "", [],
                                        actors=actors, max_rounds=9)
    assert isinstance(produced, SimulationParameters)
    data = produced.to_dict()
    assert data[KEY] == admitted
    assert data["temporal_config"]["horizon_date"] == "2027-12-31"
    assert data["temporal_config"]["n_rounds"] <= 9
    assert len(calls) == 2  # Admission reused, not a second model interpretation.
    assert case["prompt"] in json.loads(calls[0].split("\n", 1)[1].split("\n\nReturn", 1)[0])["requirement"]


def test_review_rejects_baseline_as_endpoint_and_invalidates_prior_admission(monkeypatch):
    from tests.forecast_task_fakes import task_protocol
    generator = SimulationConfigGenerator.__new__(SimulationConfigGenerator)
    good = {"horizon_date": "2027-12-31", "source_field": "requirement", "source_quote": "December 31, 2027"}
    monkeypatch.setattr(generator, "_call_task_json", lambda p, s: task_protocol(p, good))
    monkeypatch.setattr(Config, "SIM_TEMPORAL_MODE", "calendar")
    generator.admit_forecast_task(QUESTION, {"as_of_date": "2026-10-22"})
    bad = {"horizon_date": "2026-10-31", "source_field": "requirement", "source_quote": "October 2026"}
    def model(prompt, system):
        return bad if prompt.startswith("FORECAST TASK EXTRACTION") else task_protocol(prompt, good)
    monkeypatch.setattr(generator, "_call_task_json", model)
    with pytest.raises(ForecastTaskError, match="semantic review"):
        generator.admit_forecast_task(QUESTION, {"as_of_date": "2026-10-22"})
    assert generator._admitted_forecast is None


def test_failed_reprepare_cannot_reuse_old_ready_task(prepare_env, monkeypatch):
    from tests.test_context_audit_prepare import _dossier, _prepare, _config
    from app.services.simulation_runner import SimulationRunner
    from app.services.simulation_manager import SimulationStatus
    from scripts.run_parallel_simulation import validate_direct_child_config_seal
    manager, state = _prepare(_dossier())
    directory, old = _config(manager, state)
    saved = (directory / "simulation_config.json").read_bytes()
    # Removing this prepared run's research now fails before task-model work,
    # and still must revoke the previous task's execution authority.
    before_calls = len(prepare_env)
    with pytest.raises(ValueError, match="prepared research generation cannot be removed"):
        manager.prepare_simulation(state.simulation_id, "What happens next?", "")
    assert len(prepare_env) == before_calls
    after = manager.get_simulation(state.simulation_id)
    assert after.status == SimulationStatus.FAILED and after.config_generated is False
    assert (directory / "simulation_config.json").read_bytes() == saved
    monkeypatch.setattr(SimulationRunner, "RUN_STATE_DIR", str(directory.parent))
    with pytest.raises(ForecastTaskError, match="not completed"):
        SimulationRunner.start_simulation(state.simulation_id)
    with pytest.raises(ForecastTaskError, match="not completed"):
        validate_direct_child_config_seal(str(directory / "simulation_config.json"))
    with pytest.raises(ForecastTaskError, match="not completed"):
        manager.validate_prepared_simulation_config(state.simulation_id)


@pytest.mark.parametrize("platform", ["twitter", "reddit"])
def test_single_platform_calendar_uses_the_calendar_engine(platform, sim_env, no_subprocess):
    from tests.test_temporal_mode_contract import _prepare_sim
    from app.services.simulation_runner import SimulationRunner
    data = config()
    _prepare_sim(sim_env, data["simulation_id"], data)
    state = SimulationRunner.start_simulation(data["simulation_id"], platform=platform)
    command = no_subprocess[0].cmd
    assert command[1].endswith("run_parallel_simulation.py")
    assert f"--{platform}-only" in command
    assert state.total_rounds == data["temporal_config"]["n_rounds"]
    assert state.options["terminal_artifacts_token"]
    assert no_subprocess[0].kwargs["env"]["SIM_TERMINAL_ARTIFACTS_TOKEN"] == state.options["terminal_artifacts_token"]


@pytest.mark.parametrize("platform", ["twitter", "reddit"])
def test_old_hourly_entrypoint_rejects_bound_calendar(platform, tmp_path):
    import importlib
    module = importlib.import_module(f"scripts.run_{platform}_simulation")
    path = tmp_path / "simulation_config.json"
    path.write_text(json.dumps(config()))
    runner = getattr(module, platform.title() + "SimulationRunner")
    with pytest.raises(ForecastTaskError, match="run_parallel_simulation"):
        runner(str(path))


@pytest.mark.parametrize("body", ['{"horizon_date":"2027-12-31","horizon_date":"2026-10-31"}',
                                 '{"horizon_date":"2027-12-', '{"horizon_date":NaN}', '[]'])
def test_task_json_is_not_repaired_or_retried(body):
    generator = SimulationConfigGenerator.__new__(SimulationConfigGenerator)
    class Model:
        calls = 0
        def chat(self, **kwargs):
            self.calls += 1
            return body
    generator.llm = Model()
    with pytest.raises(ForecastTaskError):
        generator._call_task_json("FORECAST TASK EXTRACTION", "task")
    assert generator.llm.calls == 1


@pytest.mark.parametrize("version", [None, "", False, "forecast-task/v999"])
def test_invalid_present_task_version_cannot_round_trip_to_legacy(prepare_env, version):
    from app.services.simulation_manager import SimulationManager
    manager = SimulationManager()
    state = manager.create_simulation("root-project", "root-graph")
    path = Path(manager._get_simulation_dir(state.simulation_id)) / "state.json"
    changed = json.loads(path.read_text())
    changed["forecast_task_version"] = version
    path.write_text(json.dumps(changed))
    with pytest.raises(ForecastTaskError, match="version"):
        manager.get_simulation(state.simulation_id)


def test_pre_upgrade_researched_calendar_requires_reprepare_not_silent_reexecution(prepare_env, monkeypatch):
    from tests.test_context_audit_prepare import _dossier, _prepare, _config
    from app.services.simulation_runner import SimulationRunner
    from scripts.run_parallel_simulation import validate_direct_child_config_seal
    manager, state = _prepare(_dossier())
    directory, data = _config(manager, state)
    # Represent an already-sealed pre-upgrade artifact. Reads/history remain
    # available, but a new researched execution needs reviewed task authority.
    data.pop(KEY)
    config_path = directory / "simulation_config.json"
    config_path.write_text(json.dumps(data))
    config_sha, manifest_sha = build_simulation_config_seal(
        str(directory), simulation_id=state.simulation_id,
        actor_cast_manifest_sha256=state.actor_cast_manifest_sha256,
        actor_context_manifest_sha256=state.actor_context_manifest_sha256,
        actor_role_manifest_sha256=state.actor_role_manifest_sha256)
    path = directory / "state.json"
    legacy = json.loads(path.read_text())
    legacy.pop("forecast_task_version")
    legacy.update(simulation_config_sha256=config_sha, simulation_config_manifest_sha256=manifest_sha)
    path.write_text(json.dumps(legacy))
    before = config_path.read_bytes()
    assert manager.get_simulation(state.simulation_id) is not None
    monkeypatch.setattr(SimulationRunner, "RUN_STATE_DIR", str(directory.parent))
    for admission in (lambda: manager.validate_prepared_simulation_config(state.simulation_id),
                      lambda: SimulationRunner.start_simulation(state.simulation_id),
                      lambda: validate_direct_child_config_seal(str(config_path))):
        with pytest.raises(ForecastTaskError):
            admission()
    assert config_path.read_bytes() == before


if __name__ != "__main__":
    from tests.test_context_audit_prepare import prepare_env  # noqa: E402,F401
    from tests.test_temporal_mode_contract import sim_env, no_subprocess  # noqa: E402,F401


if __name__ == "__main__":
    from scripts.run_parallel_simulation import load_config
    assert sys.argv[1] == "--task-read"
    try:
        loaded = load_config(sys.argv[2])
        result = {KEY: loaded[KEY]}
    except ForecastTaskError:
        result = {"status": "rejected", "error_type": "ForecastTaskError"}
    Path(sys.argv[3]).write_text(json.dumps(result))
