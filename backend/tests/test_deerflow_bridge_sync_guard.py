"""Offline unit tests for the DeerFlow bridge/deployment drift guard.

Live-surfaced 2026-07-03: a forecast run on MiniMax completed its research
stage with a 28-actor cast (violating ACTOR_CAST_MAX=20) because the deployed
copy at $DEERFLOW_DIR/deerflow_research.py had not been re-synced from
deerflow_bridge/ since a whole session's worth of fixes landed there (setup.sh
line ~579 only performs this cp when explicitly re-run). _sync_deerflow_bridge_if_stale
closes that gap by hash-comparing the bridge source against the deployed copy
immediately before every research subprocess launch and auto-resyncing on drift.
"""

import hashlib
import os
from pathlib import Path
import runpy

import pytest

from app.services.pipeline_orchestrator import (
    _DeerFlowSafetyOverlayError,
    _DeerFlowSkillSyncError,
    _sync_deerflow_bridge_if_stale,
)


def _write(path, content):
    path = Path(path)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(content)
    # Most tests isolate a non-skill bridge behavior but the production guard now
    # requires the complete research skill set before any bridge work can launch.
    if path.name == "deerflow_research.py" and path.parent.name == "deerflow_bridge":
        for skill in (
            "actor-ontology-research",
            "deep-research",
            "forecast-visuals",
            "prediction-markets",
        ):
            skill_file = path.parent / "skills" / skill / "SKILL.md"
            if not skill_file.exists():
                skill_file.parent.mkdir(parents=True, exist_ok=True)
                skill_file.write_text(f"---\nname: {skill}\n---\n", encoding="utf-8")
    elif path.name == "deerflow_research.py":
        # The authoritative helper creates skills/public atomically but requires
        # the vendor's stable skills/ parent to exist.
        (path.parent / "skills").mkdir(parents=True, exist_ok=True)


def _digest(path):
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def test_syncs_stale_deployed_script(tmp_path, monkeypatch):
    repo_root = tmp_path
    bridge_dir = repo_root / "deerflow_bridge"
    deployed_dir = repo_root / "deer-flow"
    _write(bridge_dir / "deerflow_research.py", "# NEW content with enforce_actor_cast\n")
    _write(deployed_dir / "deerflow_research.py", "# OLD stale content\n")

    # _sync_deerflow_bridge_if_stale derives repo_root from this module's own
    # __file__ (three parents up); patch that instead of passing repo_root in.
    monkeypatch.setattr(
        "app.services.pipeline_orchestrator.__file__",
        str(repo_root / "backend" / "app" / "services" / "pipeline_orchestrator.py"),
    )

    _sync_deerflow_bridge_if_stale(str(deployed_dir))

    assert (deployed_dir / "deerflow_research.py").read_text() == "# NEW content with enforce_actor_cast\n"
    assert _digest(bridge_dir / "deerflow_research.py") == _digest(deployed_dir / "deerflow_research.py")


def test_noop_when_already_in_sync(tmp_path, monkeypatch):
    repo_root = tmp_path
    bridge_dir = repo_root / "deerflow_bridge"
    deployed_dir = repo_root / "deer-flow"
    same_content = "# identical content\n"
    _write(bridge_dir / "deerflow_research.py", same_content)
    _write(deployed_dir / "deerflow_research.py", same_content)
    deployed_script = deployed_dir / "deerflow_research.py"
    mtime_before = deployed_script.stat().st_mtime_ns

    monkeypatch.setattr(
        "app.services.pipeline_orchestrator.__file__",
        str(repo_root / "backend" / "app" / "services" / "pipeline_orchestrator.py"),
    )

    _sync_deerflow_bridge_if_stale(str(deployed_dir))

    # Content unchanged and file not rewritten (mtime stable) when already in sync.
    assert deployed_script.read_text() == same_content
    assert deployed_script.stat().st_mtime_ns == mtime_before


def test_syncs_skill_files_too(tmp_path, monkeypatch):
    repo_root = tmp_path
    bridge_dir = repo_root / "deerflow_bridge"
    deployed_dir = repo_root / "deer-flow"
    _write(bridge_dir / "deerflow_research.py", "same\n")
    _write(deployed_dir / "deerflow_research.py", "same\n")
    _write(bridge_dir / "skills" / "actor-ontology-research" / "SKILL.md", "NEW cast-cap rule\n")
    _write(deployed_dir / "skills" / "public" / "actor-ontology-research" / "SKILL.md", "OLD rule\n")
    _write(
        deployed_dir / "skills" / "public" / "actor-ontology-research"
        / "references" / "destination-only.md",
        "must be pruned\n",
    )
    _write(
        bridge_dir / "skills" / "actor-ontology-research" / "references" / "details.md",
        "lazy reference\n",
    )
    _write(
        bridge_dir / "skills" / "actor-ontology-research"
        / "assets" / "templates" / "contract.json",
        '{"schema": 1}\n',
    )

    monkeypatch.setattr(
        "app.services.pipeline_orchestrator.__file__",
        str(repo_root / "backend" / "app" / "services" / "pipeline_orchestrator.py"),
    )

    sync_result = _sync_deerflow_bridge_if_stale(str(deployed_dir))

    deployed_skill = deployed_dir / "skills" / "public" / "actor-ontology-research" / "SKILL.md"
    assert deployed_skill.read_text() == "NEW cast-cap rule\n"
    assert (
        deployed_dir / "skills" / "public" / "actor-ontology-research"
        / "references" / "details.md"
    ).read_text() == "lazy reference\n"
    assert (
        deployed_dir / "skills" / "public" / "actor-ontology-research"
        / "assets" / "templates" / "contract.json"
    ).read_text() == '{"schema": 1}\n'
    assert not (
        deployed_dir / "skills" / "public" / "actor-ontology-research"
        / "references" / "destination-only.md"
    ).exists()
    assert sync_result["source_manifest_hash"] == sync_result["deployed_manifest_hash"]
    assert sync_result["deployed_path"] == str(
        (deployed_dir / "skills" / "public").resolve()
    )
    assert sync_result["skills"]["actor-ontology-research"][
        "lazy_resource_hashes"
    ]["references/details.md"] == _digest(
        bridge_dir / "skills" / "actor-ontology-research"
        / "references" / "details.md"
    )


def test_syncs_config_reflected_tool_modules(tmp_path, monkeypatch):
    """Bridge tool modules are imported from deployed bare-module paths.
    module names and imported via sys.path[0]==deer-flow/; a bridge-only edit must
    re-sync them to the deployed dir or web_search/web_fetch/prediction_market tools
    fail to import at runtime (regression: search_tools/cached_fetch were absent from
    deer-flow/ entirely while config.yaml referenced them)."""
    repo_root = tmp_path
    bridge_dir = repo_root / "deerflow_bridge"
    deployed_dir = repo_root / "deer-flow"
    _write(bridge_dir / "deerflow_research.py", "same\n")
    _write(deployed_dir / "deerflow_research.py", "same\n")
    # market_tools already deployed but stale; search_tools/cached_fetch missing entirely.
    _write(bridge_dir / "market_tools.py", "# NEW market_tools\n")
    _write(deployed_dir / "market_tools.py", "# OLD market_tools\n")
    _write(bridge_dir / "search_tools.py", "# search_tools body\n")
    _write(bridge_dir / "cached_fetch.py", "# cached_fetch body\n")
    _write(bridge_dir / "research_budget.py", "# research_budget body\n")

    monkeypatch.setattr(
        "app.services.pipeline_orchestrator.__file__",
        str(repo_root / "backend" / "app" / "services" / "pipeline_orchestrator.py"),
    )

    _sync_deerflow_bridge_if_stale(str(deployed_dir))

    assert (deployed_dir / "market_tools.py").read_text() == "# NEW market_tools\n"
    assert (deployed_dir / "search_tools.py").read_text() == "# search_tools body\n"
    assert (deployed_dir / "cached_fetch.py").read_text() == "# cached_fetch body\n"
    assert (deployed_dir / "research_budget.py").read_text() == "# research_budget body\n"


def test_syncs_research_engine_v3_modules(tmp_path, monkeypatch):
    """Engine v3 = linear_research.py (phases) + research_gateway.py (gateway and
    research tools), both imported by bare name from the deployed dir.  A missing
    or stale copy would make the default RESEARCH_ENGINE=v3 dispatch fail with
    ImportError (or silently run old engine code) after a bridge-only edit."""
    repo_root = tmp_path
    bridge_dir = repo_root / "deerflow_bridge"
    deployed_dir = repo_root / "deer-flow"
    _write(bridge_dir / "deerflow_research.py", "same\n")
    _write(deployed_dir / "deerflow_research.py", "same\n")
    # linear_research.py deployed but stale; research_gateway.py never deployed.
    _write(bridge_dir / "linear_research.py", "# NEW v3 engine phases\n")
    _write(deployed_dir / "linear_research.py", "# OLD linear v2 engine\n")
    _write(bridge_dir / "research_gateway.py", "# v3 gateway + research tools\n")

    monkeypatch.setattr(
        "app.services.pipeline_orchestrator.__file__",
        str(repo_root / "backend" / "app" / "services" / "pipeline_orchestrator.py"),
    )

    _sync_deerflow_bridge_if_stale(str(deployed_dir))

    assert (deployed_dir / "linear_research.py").read_text() == "# NEW v3 engine phases\n"
    assert (deployed_dir / "research_gateway.py").read_text() == (
        "# v3 gateway + research tools\n")
    assert _digest(bridge_dir / "research_gateway.py") == _digest(
        deployed_dir / "research_gateway.py")


def _setup_sh_bridge_module_list() -> list[str]:
    """The module list of setup.sh's bridge-overlay copy loop."""
    setup_sh = Path(__file__).resolve().parents[2] / "setup.sh"
    loops = [
        line.strip() for line in setup_sh.read_text(encoding="utf-8").splitlines()
        if line.strip().startswith("for _tool_mod in ")
    ]
    assert len(loops) == 1, f"expected exactly one bridge copy loop in setup.sh, got {loops}"
    return loops[0][len("for _tool_mod in "):].split(";", 1)[0].split()


def test_setup_sh_deploys_every_bare_imported_bridge_module():
    """setup.sh (fresh install) and the launch-time drift guard must deploy the
    same bare-imported modules; RT-15: setup.sh once omitted linear_research.py,
    so a standalone run after ./setup.sh hit ImportError."""
    from app.services.pipeline_orchestrator import _DEPLOYED_BRIDGE_MODULES

    setup_modules = _setup_sh_bridge_module_list()
    assert "linear_research.py" in setup_modules
    assert "research_gateway.py" in setup_modules
    # RESEARCH-7: linear_research imports evidence_spans by bare name too.
    assert "evidence_spans.py" in setup_modules
    # TIME-2: cached_fetch and research_gateway import source_dates by bare name.
    assert "source_dates.py" in setup_modules
    # TIME-10: the official-data vendor tools, bare-imported once the engine binds them.
    assert "data_tools.py" in setup_modules
    assert {"linear_research.py", "research_gateway.py", "evidence_spans.py",
            "source_dates.py", "data_tools.py"} <= set(_DEPLOYED_BRIDGE_MODULES)
    missing = sorted(set(_DEPLOYED_BRIDGE_MODULES) - set(setup_modules))
    assert not missing, f"setup.sh does not deploy drift-guarded modules: {missing}"


def test_syncs_tracked_middleware_overlay(tmp_path, monkeypatch):
    repo_root = tmp_path
    bridge_dir = repo_root / "deerflow_bridge"
    deployed_dir = repo_root / "deer-flow"
    _write(bridge_dir / "deerflow_research.py", "same\n")
    _write(deployed_dir / "deerflow_research.py", "same\n")
    _write(
        bridge_dir / "patches" / "middlewares" / "model_concurrency_middleware.py",
        "# tracked exact-call lease\n",
    )
    deployed_mw = (
        deployed_dir / "backend" / "packages" / "harness" / "deerflow"
        / "agents" / "middlewares")
    _write(deployed_mw / "model_concurrency_middleware.py", "# stale\n")

    monkeypatch.setattr(
        "app.services.pipeline_orchestrator.__file__",
        str(repo_root / "backend" / "app" / "services" / "pipeline_orchestrator.py"),
    )

    _sync_deerflow_bridge_if_stale(str(deployed_dir))

    assert (deployed_mw / "model_concurrency_middleware.py").read_text() == (
        "# tracked exact-call lease\n")


def test_sync_applies_tracked_lead_agent_summarization_overlay(tmp_path, monkeypatch):
    repo_root = tmp_path
    bridge_dir = repo_root / "deerflow_bridge"
    deployed_dir = repo_root / "deer-flow"
    _write(bridge_dir / "deerflow_research.py", "same\n")
    _write(deployed_dir / "deerflow_research.py", "same\n")

    real_overlay = (
        Path(__file__).resolve().parents[2]
        / "deerflow_bridge" / "patches" / "apply_lead_agent_overlays.py"
    )
    _write(
        bridge_dir / "patches" / "apply_lead_agent_overlays.py",
        real_overlay.read_text(encoding="utf-8"),
    )
    lead_agent = (
        deployed_dir / "backend" / "packages" / "harness" / "deerflow"
        / "agents" / "lead_agent" / "agent.py"
    )
    _write(
        lead_agent,
        '''def _create_summarization_middleware(*, app_config: AppConfig | None = None) -> DeerFlowSummarizationMiddleware | None:
    resolved_app_config = app_config or get_app_config()
    config = resolved_app_config.summarization
    if config.model_name:
        model = create_chat_model(name=config.model_name, thinking_enabled=False, app_config=resolved_app_config, attach_tracing=False)
    else:
        model = create_chat_model(thinking_enabled=False, app_config=resolved_app_config, attach_tracing=False)
    kwargs = {
        "model": model,
        "trigger": trigger,
        "keep": keep,
    }

    if config.trim_tokens_to_summarize is not None:
        kwargs["trim_tokens_to_summarize"] = config.trim_tokens_to_summarize
    return kwargs

def build_middlewares(config, model_name, resolved_app_config):
    summarization_middleware = _create_summarization_middleware(app_config=resolved_app_config)
    return summarization_middleware
''',
    )

    monkeypatch.setattr(
        "app.services.pipeline_orchestrator.__file__",
        str(repo_root / "backend" / "app" / "services" / "pipeline_orchestrator.py"),
    )

    _sync_deerflow_bridge_if_stale(str(deployed_dir))

    deployed = lead_agent.read_text(encoding="utf-8")
    assert '"trim_tokens_to_summarize": config.trim_tokens_to_summarize' in deployed
    assert "if config.trim_tokens_to_summarize is not None" not in deployed
    assert "summary_model_name = config.model_name or model_name" in deployed
    assert "model_name=model_name" in deployed


def test_sync_fails_closed_when_required_lead_overlay_drifts(tmp_path, monkeypatch):
    repo_root = tmp_path
    bridge_dir = repo_root / "deerflow_bridge"
    deployed_dir = repo_root / "deer-flow"
    _write(bridge_dir / "deerflow_research.py", "same\n")
    _write(deployed_dir / "deerflow_research.py", "same\n")

    real_overlay = (
        Path(__file__).resolve().parents[2]
        / "deerflow_bridge" / "patches" / "apply_lead_agent_overlays.py"
    )
    _write(
        bridge_dir / "patches" / "apply_lead_agent_overlays.py",
        real_overlay.read_text(encoding="utf-8"),
    )
    lead_agent = (
        deployed_dir / "backend" / "packages" / "harness" / "deerflow"
        / "agents" / "lead_agent" / "agent.py"
    )
    _write(lead_agent, "# unexpected upstream factory shape\n")

    monkeypatch.setattr(
        "app.services.pipeline_orchestrator.__file__",
        str(repo_root / "backend" / "app" / "services" / "pipeline_orchestrator.py"),
    )

    with pytest.raises(
        _DeerFlowSafetyOverlayError,
        match="required DeerFlow lead-agent safety overlay failed",
    ):
        _sync_deerflow_bridge_if_stale(str(deployed_dir))


def test_sync_fails_closed_when_required_lead_overlay_is_missing(tmp_path, monkeypatch):
    repo_root = tmp_path
    bridge_dir = repo_root / "deerflow_bridge"
    deployed_dir = repo_root / "deer-flow"
    _write(bridge_dir / "deerflow_research.py", "same\n")
    _write(deployed_dir / "deerflow_research.py", "same\n")
    _write(
        deployed_dir / "backend" / "packages" / "harness" / "deerflow"
        / "agents" / "lead_agent" / "agent.py",
        "# unpatched lead-agent runtime\n",
    )

    monkeypatch.setattr(
        "app.services.pipeline_orchestrator.__file__",
        str(repo_root / "backend" / "app" / "services" / "pipeline_orchestrator.py"),
    )

    with pytest.raises(
        _DeerFlowSafetyOverlayError,
        match="required tracked DeerFlow lead-agent safety overlay is missing",
    ):
        _sync_deerflow_bridge_if_stale(str(deployed_dir))


def test_sync_applies_model_factory_metadata_overlay(tmp_path, monkeypatch):
    repo_root = tmp_path
    bridge_dir = repo_root / "deerflow_bridge"
    deployed_dir = repo_root / "deer-flow"
    _write(bridge_dir / "deerflow_research.py", "same\n")
    _write(deployed_dir / "deerflow_research.py", "same\n")
    real_overlay = (
        Path(__file__).resolve().parents[2]
        / "deerflow_bridge" / "patches" / "apply_model_factory_overlays.py"
    )
    _write(
        bridge_dir / "patches" / "apply_model_factory_overlays.py",
        real_overlay.read_text(encoding="utf-8"),
    )
    factory = (
        deployed_dir / "backend" / "packages" / "harness" / "deerflow"
        / "models" / "factory.py"
    )
    _write(
        factory,
        '''def create(model_config):
    return model_config.model_dump(
        exclude={
            "supports_vision",
        },
    )
''',
    )

    monkeypatch.setattr(
        "app.services.pipeline_orchestrator.__file__",
        str(
            repo_root / "backend" / "app" / "services"
            / "pipeline_orchestrator.py"
        ),
    )

    _sync_deerflow_bridge_if_stale(str(deployed_dir))

    deployed = factory.read_text(encoding="utf-8")
    assert '"context_window_tokens"' in deployed
    once = deployed
    _sync_deerflow_bridge_if_stale(str(deployed_dir))
    assert factory.read_text(encoding="utf-8") == once


def test_syncs_tracked_embedded_subagent_overlay(tmp_path, monkeypatch):
    repo_root = tmp_path
    bridge_dir = repo_root / "deerflow_bridge"
    deployed_dir = repo_root / "deer-flow"
    _write(bridge_dir / "deerflow_research.py", "same\n")
    _write(deployed_dir / "deerflow_research.py", "same\n")
    real_overlay = (
        Path(__file__).resolve().parents[2]
        / "deerflow_bridge" / "patches" / "apply_subagent_overlays.py"
    )
    _write(
        bridge_dir / "patches" / "apply_subagent_overlays.py",
        real_overlay.read_text(encoding="utf-8"),
    )
    deployed_harness = (
        deployed_dir / "backend" / "packages" / "harness" / "deerflow"
    )
    _write(
        deployed_harness / "client.py",
        '''class DeerFlowClient:
    def stream(self, thread_id):
        context = {"thread_id": thread_id}
        # The same message id carries identical cumulative ``usage_metadata``
        # in both the final ``messages`` chunk and the values snapshot —
        # count it only on whichever arrives first.
        counted_usage_ids: set[str] = set()
        cumulative_usage = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}

        def _account_usage(msg_id, usage):
            if not usage:
                return None
            if msg_id and msg_id in counted_usage_ids:
                return None
            if msg_id:
                counted_usage_ids.add(msg_id)
            input_tokens = usage.get("input_tokens", 0) or 0
            output_tokens = usage.get("output_tokens", 0) or 0
            total_tokens = usage.get("total_tokens", 0) or 0
            cumulative_usage["input_tokens"] += input_tokens
            cumulative_usage["output_tokens"] += output_tokens
            cumulative_usage["total_tokens"] += total_tokens
            return {
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "total_tokens": total_tokens,
            }

        return context, _account_usage
''',
    )
    _write(
        deployed_harness / "tools" / "builtins" / "task_tool.py",
        '''def task_tool(runtime):
    metadata = runtime.config.get("metadata", {})
    if runtime is not None:
        parent_model = metadata.get("model_name")
    return parent_model
''',
    )
    _write(
        deployed_harness / "subagents" / "executor.py",
        '''import asyncio

logger = logging.getLogger(__name__)

class SubagentExecutor:
    tracing_and_session_behavior = "preserve-me"

    async def _aexecute(self, task: str, result_holder: SubagentResult | None = None) -> SubagentResult:
        """Upstream body remains byte-for-byte after its signature."""
        try:
            final_state = {}
            ai_messages = []
            logger.info(f"[trace={self.trace_id}] Subagent {self.config.name} completed async execution")
            result.try_set_terminal(
                SubagentStatus.COMPLETED,
                result=final_result,
            )
            return self.tracing_and_session_behavior
''',
    )

    monkeypatch.setattr(
        "app.services.pipeline_orchestrator.__file__",
        str(
            repo_root / "backend" / "app" / "services"
            / "pipeline_orchestrator.py"
        ),
    )

    _sync_deerflow_bridge_if_stale(str(deployed_dir))

    client_source = (deployed_harness / "client.py").read_text()
    task_source = (
        deployed_harness / "tools" / "builtins" / "task_tool.py"
    ).read_text()
    executor_source = (deployed_harness / "subagents" / "executor.py").read_text()
    assert '"app_config": self._app_config' in client_source
    assert "counted_usage_by_id" in client_source
    assert "counted_usage_ids" not in client_source
    assert 'configurable.get("model_name")' in task_source
    assert "async_subagent_lifecycle_lease" in executor_source
    assert "async def _aexecute_under_lease" in executor_source
    assert "provider fallback messages are failed tasks" in executor_source
    assert "classify typed blocked outcomes" in executor_source
    assert "Subagent evidence tools exhausted before any usable result" in executor_source
    assert 'tracing_and_session_behavior = "preserve-me"' in executor_source
    assert "Upstream body remains byte-for-byte" in executor_source

    # Idempotence: the drift guard may run before every outer lane.
    once = (client_source, task_source, executor_source)
    _sync_deerflow_bridge_if_stale(str(deployed_dir))
    assert (
        (deployed_harness / "client.py").read_text(),
        (deployed_harness / "tools" / "builtins" / "task_tool.py").read_text(),
        (deployed_harness / "subagents" / "executor.py").read_text(),
    ) == once


@pytest.mark.skipif(
    not (
        Path(__file__).resolve().parents[2]
        / "deer-flow-2.0.0"
        / "backend"
        / "packages"
        / "harness"
        / "deerflow"
        / "client.py"
    ).is_file(),
    reason="vendored deer-flow harness snapshot is not present in this checkout",
)
def test_subagent_overlay_preserves_current_vendor_observability(tmp_path):
    repo_root = Path(__file__).resolve().parents[2]
    vendor_root = repo_root / "deer-flow-2.0.0"
    vendor_harness = (
        vendor_root / "backend" / "packages" / "harness" / "deerflow"
    )
    overlay = (
        repo_root / "deerflow_bridge" / "patches"
        / "apply_subagent_overlays.py"
    )
    deployed_harness = (
        tmp_path / "backend" / "packages" / "harness" / "deerflow"
    )
    for relative in (
        Path("client.py"),
        Path("tools/builtins/task_tool.py"),
        Path("subagents/executor.py"),
    ):
        _write(
            deployed_harness / relative,
            (vendor_harness / relative).read_text(encoding="utf-8"),
        )

    module = runpy.run_path(str(overlay))
    assert module["apply"](tmp_path) == "applied"
    assert module["apply"](tmp_path) == "already_applied"

    client_source = (deployed_harness / "client.py").read_text(encoding="utf-8")
    task_source = (
        deployed_harness / "tools" / "builtins" / "task_tool.py"
    ).read_text(encoding="utf-8")
    executor_source = (
        deployed_harness / "subagents" / "executor.py"
    ).read_text(encoding="utf-8")
    assert '"app_config": self._app_config' in client_source
    assert 'configurable.get("model_name")' in task_source
    assert "async_subagent_lifecycle_lease" in executor_source
    assert "provider fallback messages are failed tasks" in executor_source
    for preserved in (
        "build_tracing_callbacks",
        "inject_langfuse_metadata",
        "checkpointer=False",
        "user_id=self.user_id",
    ):
        assert preserved in executor_source


@pytest.mark.skipif(
    not (
        Path(__file__).resolve().parents[2]
        / "deer-flow-2.0.0"
        / "backend"
        / "packages"
        / "harness"
        / "deerflow"
        / "client.py"
    ).is_file(),
    reason="vendored deer-flow harness snapshot is not present in this checkout",
)
def test_subagent_overlay_fails_closed_on_model_inheritance_drift(tmp_path):
    repo_root = Path(__file__).resolve().parents[2]
    vendor_harness = (
        repo_root / "deer-flow-2.0.0" / "backend" / "packages"
        / "harness" / "deerflow"
    )
    deployed_harness = (
        tmp_path / "backend" / "packages" / "harness" / "deerflow"
    )
    for relative in (
        Path("client.py"),
        Path("tools/builtins/task_tool.py"),
        Path("subagents/executor.py"),
    ):
        source = (vendor_harness / relative).read_text(encoding="utf-8")
        if relative.name == "task_tool.py":
            source = source.replace(
                '        parent_model = metadata.get("model_name")\n',
                "        parent_model = vendor_changed_this_contract()\n",
                1,
            )
        _write(deployed_harness / relative, source)

    overlay = (
        repo_root / "deerflow_bridge" / "patches"
        / "apply_subagent_overlays.py"
    )
    module = runpy.run_path(str(overlay))
    with pytest.raises(RuntimeError, match="context drifted"):
        module["apply"](tmp_path)


def test_fails_closed_when_required_bridge_skill_source_is_missing(tmp_path, monkeypatch):
    """A run without authoritative skill sources cannot prove executable bytes."""
    repo_root = tmp_path
    deployed_dir = repo_root / "deer-flow"
    _write(deployed_dir / "deerflow_research.py", "whatever\n")

    monkeypatch.setattr(
        "app.services.pipeline_orchestrator.__file__",
        str(repo_root / "backend" / "app" / "services" / "pipeline_orchestrator.py"),
    )

    with pytest.raises(
        _DeerFlowSkillSyncError,
        match="required DeerFlow bridge source/deployed entry point is missing",
    ):
        _sync_deerflow_bridge_if_stale(str(deployed_dir))
    assert (deployed_dir / "deerflow_research.py").read_text() == "whatever\n"


def test_copy_failure_fails_closed_before_bridge_or_research_launch(tmp_path, monkeypatch):
    """A shared shutil failure must not leave a partial bundle eligible to run."""
    repo_root = tmp_path
    bridge_dir = repo_root / "deerflow_bridge"
    deployed_dir = repo_root / "deer-flow"
    _write(bridge_dir / "deerflow_research.py", "x\n")
    _write(deployed_dir / "deerflow_research.py", "y\n")

    monkeypatch.setattr(
        "app.services.pipeline_orchestrator.__file__",
        str(repo_root / "backend" / "app" / "services" / "pipeline_orchestrator.py"),
    )

    def _boom(*a, **kw):
        raise OSError("simulated disk failure")

    monkeypatch.setattr("app.services.pipeline_orchestrator.shutil.copyfile", _boom)

    with pytest.raises(
        _DeerFlowSkillSyncError,
        match="required runtime skill deployment failed.*simulated disk failure",
    ):
        _sync_deerflow_bridge_if_stale(str(deployed_dir))
    assert (deployed_dir / "deerflow_research.py").read_text() == "y\n"
