"""deerflow_bridge/extensions_config.json is a template rendered at deploy time.

The tracked file used to hard-code one developer's absolute paths
(/Users/<dev>/…/backend/.venv/bin/python), so the KG MCP server that fork,
continue and resume runs attach could not start on any other checkout. The
source now carries placeholders that _sync_deerflow_bridge_if_stale replaces
with this checkout's paths when it deploys the file into deer-flow/.
"""

import json
import re
import sys
from pathlib import Path

import pytest

from app.services.pipeline_orchestrator import (
    _render_bridge_extensions_config,
    _sync_deerflow_bridge_if_stale,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
TRACKED = REPO_ROOT / "deerflow_bridge" / "extensions_config.json"


def _isolated_repo(tmp_path, monkeypatch, ext_config_text):
    bridge = tmp_path / "deerflow_bridge"
    deployed = tmp_path / "deer-flow"
    for d in (bridge, deployed):
        d.mkdir(parents=True)
    (bridge / "deerflow_research.py").write_text("same\n", encoding="utf-8")
    (deployed / "deerflow_research.py").write_text("same\n", encoding="utf-8")
    (deployed / "skills").mkdir()
    for skill in ("actor-ontology-research", "deep-research", "forecast-visuals", "prediction-markets"):
        f = bridge / "skills" / skill / "SKILL.md"
        f.parent.mkdir(parents=True)
        f.write_text(f"---\nname: {skill}\n---\n", encoding="utf-8")
    (bridge / "extensions_config.json").write_text(ext_config_text, encoding="utf-8")
    monkeypatch.setattr(
        "app.services.pipeline_orchestrator.__file__",
        str(tmp_path / "backend" / "app" / "services" / "pipeline_orchestrator.py"),
    )
    return deployed


def test_tracked_template_has_no_machine_specific_paths():
    text = TRACKED.read_text(encoding="utf-8")
    assert not re.search(r"/Users/|/home/[^/\s\"]+/|[A-Za-z]:\\\\", text)
    servers = json.loads(text)["mcpServers"]
    for name in ("drf-kg", "drf-simulation"):
        assert servers[name]["command"] == "{{DRF_BACKEND_PYTHON}}"
        assert "{{DRF_REPO_ROOT}}/backend" in servers[name]["env"]["PYTHONPATH"]


def test_render_uses_this_checkout_and_backend_interpreter(tmp_path):
    rendered = json.loads(_render_bridge_extensions_config(str(TRACKED), str(tmp_path)))
    kg = rendered["mcpServers"]["drf-kg"]
    assert kg["command"] == sys.executable
    assert kg["env"]["PYTHONPATH"] == f"{tmp_path}/backend:{tmp_path}"
    assert kg["args"] == ["-m", "app.mcp.kg_server"]
    # $VAR passthroughs are resolved by the harness at spawn time, not by us.
    assert kg["env"]["DRF_MCP_KG_GRAPH_ID"] == "$DRF_MCP_KG_GRAPH_ID"
    assert "{{" not in json.dumps(rendered)


def test_render_keeps_json_valid_for_awkward_paths(tmp_path):
    root = str(tmp_path / 'we"ird\\dir')
    rendered = json.loads(_render_bridge_extensions_config(str(TRACKED), root))
    assert rendered["mcpServers"]["drf-simulation"]["env"]["PYTHONPATH"].startswith(root)


def test_render_rejects_unknown_placeholders(tmp_path):
    src = tmp_path / "ext.json"
    src.write_text(json.dumps({"mcpServers": {"x": {"command": "{{DRF_TYPO}}"}}}), encoding="utf-8")
    with pytest.raises(ValueError, match="DRF_TYPO"):
        _render_bridge_extensions_config(str(src), str(tmp_path))


def test_sync_deploys_rendered_config_and_is_idempotent(tmp_path, monkeypatch):
    deployed = _isolated_repo(tmp_path, monkeypatch, TRACKED.read_text(encoding="utf-8"))

    _sync_deerflow_bridge_if_stale(str(deployed))
    first = (deployed / "extensions_config.json").read_bytes()
    kg = json.loads(first)["mcpServers"]["drf-kg"]
    assert kg["command"] == sys.executable
    assert kg["env"]["PYTHONPATH"] == f"{tmp_path}/backend:{tmp_path}"

    mtime = (deployed / "extensions_config.json").stat().st_mtime_ns
    _sync_deerflow_bridge_if_stale(str(deployed))
    assert (deployed / "extensions_config.json").read_bytes() == first
    assert (deployed / "extensions_config.json").stat().st_mtime_ns == mtime


def test_sync_replaces_stale_hardcoded_deployment(tmp_path, monkeypatch):
    deployed = _isolated_repo(tmp_path, monkeypatch, TRACKED.read_text(encoding="utf-8"))
    stale = json.loads(TRACKED.read_text(encoding="utf-8"))
    stale["mcpServers"]["drf-kg"]["command"] = "/Users/someone/elsewhere/backend/.venv/bin/python"
    (deployed / "extensions_config.json").write_text(json.dumps(stale), encoding="utf-8")

    _sync_deerflow_bridge_if_stale(str(deployed))

    kg = json.loads((deployed / "extensions_config.json").read_text(encoding="utf-8"))["mcpServers"]["drf-kg"]
    assert kg["command"] == sys.executable


def test_broken_template_skips_mcp_but_still_syncs_bridge(tmp_path, monkeypatch):
    deployed = _isolated_repo(tmp_path, monkeypatch, "{not json")
    (deployed / "extensions_config.json").write_text("{}", encoding="utf-8")
    (tmp_path / "deerflow_bridge" / "deerflow_research.py").write_text("NEW\n", encoding="utf-8")

    _sync_deerflow_bridge_if_stale(str(deployed))

    assert not (deployed / "extensions_config.json").exists()
    assert (deployed / "deerflow_research.py").read_text(encoding="utf-8") == "NEW\n"
