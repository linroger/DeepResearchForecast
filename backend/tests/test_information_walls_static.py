"""REPORT-10 (C14): static pins for the information walls that hold today only by construction.

Each wall below is true on the current code but nothing asserted it, so a refactor could
breach it silently:

- simulation/persona modules never import the forecast plane (report_agent,
  forecast_extractor, forecast_ledger, exec_brief, ensemble) nor read forecast.json, and
  never reach it through pipeline_orchestrator (which re-exports ReportAgent/ReportManager
  and reads forecast.json in PipelineOrchestrator): from that module they may take only the
  pipeline-state store PipelineManager, and the forecast-plane class names are refused from
  any module;
- the probability authors (spine draw, binary extraction, spine self-critique, the premortem
  pass and the ReportAgent spine hook) never read the ledger, historical calibration or a
  prior run's forecast (historical calibration is applied after drafting, in
  _finalize_structured_forecast, which is deliberately not inspected here);
- the multi-seed scenario pin carries names and resolution criteria only, never the
  primary run's probabilities;
- v3 research agents are market-blind (their only tools are web_search/web_fetch, and the
  structured actors/facts extraction runs before the market table is appended);
- forecast_inputs_block never renders v3's plan-time numeric scenario ``probability``.

Offline: AST/source inspection and pure renderers only; no LLM, no network.
"""

from __future__ import annotations

import ast
import inspect
import json
import re
import sys
from pathlib import Path

import pytest

from app.services import forecast_extractor as fe
from app.services.pipeline_orchestrator import PipelineOrchestrator, seed_scenario_pin
from app.services.report_agent import ReportAgent
from app.utils.actors import forecast_inputs_block

_BACKEND = Path(__file__).resolve().parents[1]
_BRIDGE = _BACKEND.parent / "deerflow_bridge"

_SIM_MODULES = [
    *(_BACKEND / "app" / "services" / f"{name}.py" for name in (
        "oasis_profile_generator", "simulation_config_generator", "actor_role_prompt",
        "actor_context", "decision_channel", "simulation_manager", "worldstate",
        "world_delta", "agent_dynamics")),
    _BACKEND / "scripts" / "run_parallel_simulation.py",
]
_FORECAST_PLANE = frozenset(
    {"report_agent", "forecast_extractor", "forecast_ledger", "exec_brief", "ensemble"})
# Transitive gateways: modules that import the forecast plane at module level, mapped to the
# only names a sim module may take from them. pipeline_orchestrator re-exports ReportAgent and
# ReportManager and its PipelineOrchestrator reads forecast.json (_read_report_forecast); the
# persona/config generators lazily take its pipeline-state store PipelineManager, nothing else.
_FORECAST_GATEWAYS = {"pipeline_orchestrator": frozenset({"PipelineManager"})}
_FORECAST_REACH = _FORECAST_PLANE | frozenset(_FORECAST_GATEWAYS)
# Forecast-plane classes, refused whichever module (re-)exports them.
_FORECAST_PLANE_NAMES = frozenset({"ReportAgent", "ReportManager", "PipelineOrchestrator"})
_DOTTED_MODULE_RE = re.compile(r"\.*[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*")
_PRIOR_RUN_READS = ("calibration_summary", "read_ledger", "historical_calibration",
                    "scenario_spine", "_check_binary_sim_sensitivity", "_read_report_forecast",
                    "forecast_ledger", "recalibration_param", "read_market_resolutions")


def _import_from_leaks(node: ast.ImportFrom) -> bool:
    module_parts = set((node.module or "").split("."))
    names = {alias.name for alias in node.names}
    if _FORECAST_PLANE & module_parts or (_FORECAST_REACH | _FORECAST_PLANE_NAMES) & names:
        return True
    return any(names - allowed for gateway, allowed in _FORECAST_GATEWAYS.items()
               if gateway in module_parts)


def _forecast_plane_violations(source: str) -> list[str]:
    """Forecast-plane imports (absolute, relative, ``from pkg import module``), forecast-plane
    class names from any module, anything but the allowed names from a transitive gateway,
    and string constants naming forecast.json or a dotted forecast-plane/gateway module path
    (importlib targets such as ``'app.services.report_agent'`` or ``'.report_agent'``)."""
    found: list[str] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if _FORECAST_REACH & set(alias.name.split(".")):
                    found.append(f"import {alias.name}")
        elif isinstance(node, ast.ImportFrom):
            if _import_from_leaks(node):
                found.append(f"from {'.' * node.level}{node.module or ''} import "
                             f"{', '.join(alias.name for alias in node.names)}")
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            if "forecast.json" in node.value:
                found.append(f"str constant {node.value[:60]!r}")
            elif ("." in node.value and _DOTTED_MODULE_RE.fullmatch(node.value)
                  and _FORECAST_REACH & set(node.value.split("."))):
                found.append(f"module string {node.value!r}")
    return found


def test_forecast_plane_detector_flags_every_import_shape():
    """The detector itself must catch each import shape, or the wall test is vacuous."""
    for snippet in ("from .report_agent import ReportAgent",
                    "from ..services.forecast_extractor import extract_binary_forecasts",
                    "import app.services.forecast_ledger",
                    "from app.services import ensemble",
                    "from . import exec_brief",
                    "def f():\n    from .report_agent import ReportManager\n",
                    "import importlib\nm = importlib.import_module('app.services.report_agent')",
                    "m = importlib.import_module('.forecast_ledger', 'app.services')",
                    "path = os.path.join(d, 'forecast.json')",
                    # transitive: pipeline_orchestrator re-exports the forecast plane
                    "from .pipeline_orchestrator import ReportManager",
                    "def f():\n    from .pipeline_orchestrator import PipelineOrchestrator\n",
                    "from .pipeline_orchestrator import PipelineManager, ReportAgent",
                    "from .pipeline_orchestrator import PipelineManager, StageState",
                    "from .pipeline_orchestrator import *",
                    "import app.services.pipeline_orchestrator",
                    "from app.services import pipeline_orchestrator",
                    "m = importlib.import_module('app.services.pipeline_orchestrator')",
                    "from .some_reexporter import ReportAgent"):
        assert _forecast_plane_violations(snippet), snippet
    # prose naming a module (the sim modules' docstrings do) and a bare dict key are not imports
    assert _forecast_plane_violations(
        '"""与 report_agent._load_prediction_markets 同模式。"""\nimport os\n') == []
    assert _forecast_plane_violations("cfg = {'ensemble': 1}\nfrom .worldstate import X\n") == []
    # the persona/config generators' lazy pipeline-state import stays allowed
    assert _forecast_plane_violations(
        "def f():\n    from .pipeline_orchestrator import PipelineManager\n") == []


@pytest.mark.parametrize("path", _SIM_MODULES, ids=lambda p: p.name)
def test_sim_modules_never_import_forecast_plane(path):
    assert path.is_file(), f"simulation module moved: {path}"
    violations = _forecast_plane_violations(path.read_text(encoding="utf-8"))
    assert violations == [], (
        f"{path.name} reaches the forecast plane (personas/simulation must stay blind to "
        f"forecasts): {violations}")


@pytest.mark.parametrize("author", [
    fe.derive_forecast_spine, fe.extract_binary_forecasts, fe.self_critique_forecast,
    fe.premortem_forecast, ReportAgent._derive_and_pin_forecast_spine,
], ids=lambda f: f.__name__)
def test_probability_authors_never_read_prior_runs(author):
    src = inspect.getsource(author)
    leaks = [name for name in _PRIOR_RUN_READS if name in src]
    assert leaks == [], (
        f"{author.__name__} drafts probabilities and must not read the ledger, historical "
        f"calibration or a prior run's forecast: {leaks}")


def test_seed_scenario_pin_carries_no_probabilities():
    primary = {"scenarios": [
        {"name": "Rapid build-out", "probability": 0.61, "probability_band": "55-65%",
         "resolution_criteria": "Capex above $500B by 2030", "summary": "fast",
         "adjustment_rationale": "market at 0.58", "base_rate_anchor": "0.4"},
        {"name": "Stall", "probability": 0.39, "resolution_criteria": "Capex below $300B"},
    ]}
    pin = seed_scenario_pin(primary)
    assert pin == [{"name": "Rapid build-out", "resolution_criteria": "Capex above $500B by 2030"},
                   {"name": "Stall", "resolution_criteria": "Capex below $300B"}]
    serialized = json.dumps(pin)
    assert "0.61" not in serialized and "0.39" not in serialized and "0.58" not in serialized
    # the ensemble hands the seeds exactly this pin
    src = inspect.getsource(PipelineOrchestrator._maybe_run_seed_ensemble)
    assert "_spine = seed_scenario_pin(primary_fc)" in src
    assert "scenario_spine=_spine" in src


def _bridge_modules():
    if str(_BRIDGE) not in sys.path:
        sys.path.insert(0, str(_BRIDGE))
    import linear_research as lr
    import research_gateway as rg
    return lr, rg


def test_v3_research_is_market_blind():
    lr, rg = _bridge_modules()
    names = {(tool.get("function") or {}).get("name") or tool.get("name")
             for tool in rg.AGENT_TOOLS_SCHEMA}
    assert names == {"web_search", "web_fetch"}
    finalize = inspect.getsource(lr._Engine.phase_finalize)
    assert "self._structured(" in finalize and "_collect_prediction_markets" in finalize
    assert finalize.index("self._structured(") < finalize.index("_collect_prediction_markets"), (
        "structured actors/facts extraction must run before the market table is appended")


def test_forecast_inputs_block_does_not_render_v3_probability():
    v3 = {"forecast_inputs": {"scenarios": [
        {"name": "Grid-constrained build-out", "probability": 0.4,
         "narrative": "Utilities ration interconnection capacity"}]}}
    block = forecast_inputs_block(v3)
    assert "grid-constrained build-out" in block
    assert "Utilities ration interconnection capacity" in block
    assert "0.4" not in block and "40%" not in block
    legacy = {"forecast_inputs": {"scenarios": [
        {"name": "base", "probability_band": "35-45%", "narrative": "Steady growth"}]}}
    assert "（概率 35-45%）" in forecast_inputs_block(legacy)
