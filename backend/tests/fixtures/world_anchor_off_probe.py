"""Same synthetic probe for archived main and the merge; requires the offline guard."""
import hashlib
import importlib.util
import json
from pathlib import Path
import random
import sys

from app.config import Config
from app.services import agent_decision as decisions
from app.services.simulation_config_generator import SimulationConfigGenerator
from app.services.world_model import WorldModel
from app.services.zep_entity_reader import EntityNode


def capture_off_snapshot(monkeypatch, *, task_reply_transform=None):
    import app
    repo = Path(app.__file__).resolve().parents[2]
    guard = sys.modules.get("main_offline_guard")
    source_paths = [*sorted((repo / "backend/app").rglob("*.py")),
                    *sorted((repo / "deerflow_bridge").rglob("*.py")),
                    repo / "backend/tests/forecast_task_fakes.py", Path(__file__).resolve()]
    for path in source_paths:
        if guard is not None:
            guard.source_hashes.setdefault(str(path), hashlib.sha256(path.read_bytes()).hexdigest())
    spec = importlib.util.spec_from_file_location("off_task_fake", repo / "backend/tests/forecast_task_fakes.py")
    fake = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fake)
    generator_calls = []
    generator_instances = []

    class ScriptedModel:
        def __init__(self, **kwargs):
            generator_instances.append(kwargs)

        def chat(self, **kwargs):
            generator_calls.append(kwargs)
            task = fake.task_protocol(kwargs["messages"][-1]["content"])
            if task is not None:
                if task_reply_transform is not None:
                    task = task_reply_transform(kwargs["messages"][-1]["content"], task)
                return json.dumps(task)
            return json.dumps({"hot_topics": [], "initial_posts": [], "agents": [], "reasoning": "offline fixture"})

    monkeypatch.setattr("app.services.simulation_config_generator.LLMClient", ScriptedModel)
    for key, value in {"SIM_TEMPORAL_MODE": "calendar", "SIM_WORLD_MODEL": True, "SIM_AUDIENCE_AGENTS": 0,
                       "SIM_CONFIG_USE_LLM": False}.items():
        monkeypatch.setattr(Config, key, value, raising=False)
    monkeypatch.setattr("app.services.official_data.load_for_simulation", lambda *a, **k: None)
    gen = SimulationConfigGenerator(provider="fixture", model_name="fixture")
    monkeypatch.setattr(gen, "_backtest_pressure_weight", lambda *a: None)
    actors = {"as_of_date": "2026-10-27", "actors": [{"name": "Acme", "agency_class": "firm",
               "goals": ["LEGACY_ANALYST_INFERENCE"], "future_plans": ["Build the legacy facility"]}]}
    entity = EntityNode("entity-1", "Acme", ["Organization"], "unrelated research FTC leader", {"aliases": []})
    params = gen.generate_config("c5-offline", "fixture-project", "fixture-graph",
        "Will adoption increase by 2027-01-31?", "Research facts.", [entity], actors=actors,
        research_language="English", max_rounds=3)
    params.generated_at = "fixed-off-probe"
    config = params.to_dict()
    world = WorldModel.from_seed(config["world_model"], config["agent_configs"])
    rng = random.Random(42)
    rng_before = repr(rng.getstate())
    world.start_round(1, {"label": "P1", "period_start": "2026-10-28", "period_end": "2026-10-31"})
    world.fire_shocks(1, rng)
    assert repr(rng.getstate()) == rng_before
    menu = decisions.build_option_menu(world.actors[0], world, 1)
    prompt = decisions.build_decision_prompt(world.actors[0], world_clock="CLOCK", public_brief=world.render_public_brief(),
        private_brief=world.render_private_brief(0), options=menu, scenarios=[], cast_names=["Acme"])

    class Model:
        def __init__(self):
            self.calls = []

        def chat_json(self, **kwargs):
            self.calls.append(kwargs)
            return {"option_id": "hold_position"}

    model = Model()
    decision = decisions.elicit_decision(model,
        system_message="BEGIN UNTRUSTED DOSSIER DATA LEGACY_ROLE END UNTRUSTED DOSSIER DATA",
        user_prompt=prompt, actor=world.actors[0], world=world, options=menu, scenarios=[], round_num=1)
    assert decision.ok
    assert len(model.calls) == 1
    assert "LEGACY_ANALYST_INFERENCE" in json.dumps(model.calls)
    assert repr(rng.getstate()) == rng_before
    payload = {"config": config, "world": world.to_dict(), "calls": model.calls, "rng": repr(rng.getstate())}
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    receipt = {"sha256": hashlib.sha256(raw.encode()).hexdigest(), "payload": payload,
               "generator_calls": generator_calls, "rng_before": rng_before,
               "generator_instance_count": len(generator_instances)}
    return receipt
