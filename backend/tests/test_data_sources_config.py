"""Official-data sources: configuration, deployment wiring and test isolation.

design.md §12 / §1.7: the DATA_SOURCES_* + REPORT_DATA_CHARTS knobs live in
Config (documented in .env.example); the orchestrator forwards them to the
research subprocess with absolute paths; the four bridge modules deploy through
the launch-time drift guard, setup.sh and init.sh alike; the vendored servers
are built by scripts/setup_datamcps.sh; build outputs never reach git; and the
pytest process never talks to a real data server or sees a developer key.
Everything here is hermetic: no network, no node, no built servers.
"""

from __future__ import annotations

import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import types
from pathlib import Path

import pytest

from app.config import Config
from app.services import pipeline_orchestrator as po

REPO_ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = REPO_ROOT / "backend" / "app" / "config.py"
SETUP_DATAMCPS = REPO_ROOT / "scripts" / "setup_datamcps.sh"

DATA_MODULES = ("data_mcp.py", "data_catalog.py", "data_sources.py", "data_tools.py")
KNOBS = (
    "DATA_SOURCES_ENABLED", "DATA_SOURCES", "DATA_SOURCES_DIR", "DATA_SOURCES_NODE",
    "DATA_SOURCES_CACHE_DIR", "DATA_SOURCES_CALL_TIMEOUT", "DATA_SOURCES_PREFETCH_MAX",
    "DATA_SOURCES_CHARTS_MAX", "REPORT_DATA_CHARTS",
)
KEY_NAMES = (
    "FRED_API_KEY", "BLS_API_KEY", "EIA_API_KEY", "BEA_API_KEY", "CENSUS_API_KEY",
    "DATA_GOV_API_KEY", "SEC_CONTACT_EMAIL",
)
REQUIRED_SKILLS = (
    "actor-ontology-research", "data-sources", "data-visuals",
    "deep-research", "forecast-visuals", "prediction-markets",
)


def _fresh_config(monkeypatch, **env):
    """Execute config.py into a throwaway module under a controlled environment
    (DRF_TEST_PROCESS=1 keeps the developer .env out), leaving app.config alone."""
    for name in KNOBS:
        monkeypatch.delenv(name, raising=False)
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    spec = importlib.util.spec_from_file_location("drf_data_sources_config_probe", CONFIG_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module.Config


# ----------------------------------------------------------------- Config knobs

def test_config_defaults_match_the_design(monkeypatch):
    cfg = _fresh_config(monkeypatch)
    assert cfg.DATA_SOURCES_ENABLED is True
    assert cfg.DATA_SOURCES == "fred,bls,bis,imf,wb,usgov"
    assert cfg.DATA_SOURCES_DIR == ""
    assert cfg.DATA_SOURCES_NODE == ""
    assert cfg.DATA_SOURCES_CACHE_DIR == ""
    assert cfg.DATA_SOURCES_CALL_TIMEOUT == 60
    assert cfg.DATA_SOURCES_PREFETCH_MAX == 12
    assert cfg.DATA_SOURCES_CHARTS_MAX == 8
    assert cfg.REPORT_DATA_CHARTS is True


@pytest.mark.parametrize(("raw", "expected"), [
    (" FRED, ,Bls ,", "fred,bls"),
    ("wb", "wb"),
    (" , ", "fred,bls,bis,imf,wb,usgov"),
    ("", "fred,bls,bis,imf,wb,usgov"),
])
def test_provider_allowlist_is_normalised(monkeypatch, raw, expected):
    assert _fresh_config(monkeypatch, DATA_SOURCES=raw).DATA_SOURCES == expected


def test_switches_paths_and_numeric_clamps(monkeypatch):
    cfg = _fresh_config(
        monkeypatch,
        DATA_SOURCES_ENABLED=" FALSE ",
        REPORT_DATA_CHARTS="false",
        DATA_SOURCES_DIR="  vendor/servers  ",
        DATA_SOURCES_NODE=" /opt/node/bin/node ",
        DATA_SOURCES_CACHE_DIR=" /var/cache/drf ",
        DATA_SOURCES_CALL_TIMEOUT="1",
        DATA_SOURCES_PREFETCH_MAX="-4",
        DATA_SOURCES_CHARTS_MAX="0",
    )
    assert cfg.DATA_SOURCES_ENABLED is False
    assert cfg.REPORT_DATA_CHARTS is False
    assert cfg.DATA_SOURCES_DIR == "vendor/servers"
    assert cfg.DATA_SOURCES_NODE == "/opt/node/bin/node"
    assert cfg.DATA_SOURCES_CACHE_DIR == "/var/cache/drf"
    assert cfg.DATA_SOURCES_CALL_TIMEOUT == 5
    assert cfg.DATA_SOURCES_PREFETCH_MAX == 0
    assert cfg.DATA_SOURCES_CHARTS_MAX == 0
    # An empty numeric value falls back to the documented default.
    assert _fresh_config(monkeypatch, DATA_SOURCES_CALL_TIMEOUT="").DATA_SOURCES_CALL_TIMEOUT == 60


def test_api_keys_are_not_config_attributes():
    """Keys follow the SERPER precedent: inherited through os.environ by the
    research subprocess and handed to each server only via its env allowlist."""
    source = CONFIG_PATH.read_text(encoding="utf-8")
    for key in KEY_NAMES:
        assert not hasattr(Config, key), key
        assert f"os.environ.get('{key}'" not in source, key


def test_env_example_documents_knobs_keys_and_defaults(monkeypatch):
    sys.path.insert(0, str(REPO_ROOT / "backend" / "scripts"))
    try:
        import check_env_drift as drift
    finally:
        sys.path.remove(str(REPO_ROOT / "backend" / "scripts"))
    documented = drift.documented_env_vars()
    assert not (set(KNOBS) | set(KEY_NAMES)) - documented
    # Every Config env var stays documented (the doctor / CI --strict gate).
    assert not drift.config_env_vars() - documented - drift._IGNORE

    # The section documents every knob as a commented "# KEY=default   # note"
    # line (the .env.example convention), so read the commented value directly.
    text = (REPO_ROOT / ".env.example").read_text(encoding="utf-8")
    examples = {}
    for name in KNOBS + KEY_NAMES:
        match = re.search(rf"^\s*#?\s*{name}=(\S*)", text, re.M)
        assert match, name
        examples[name] = match.group(1)
    defaults = _fresh_config(monkeypatch)
    assert examples["DATA_SOURCES_ENABLED"] == "true"
    assert examples["DATA_SOURCES"] == defaults.DATA_SOURCES
    assert examples["DATA_SOURCES_CALL_TIMEOUT"] == str(defaults.DATA_SOURCES_CALL_TIMEOUT)
    assert examples["DATA_SOURCES_PREFETCH_MAX"] == str(defaults.DATA_SOURCES_PREFETCH_MAX)
    assert examples["DATA_SOURCES_CHARTS_MAX"] == str(defaults.DATA_SOURCES_CHARTS_MAX)
    assert examples["REPORT_DATA_CHARTS"] == "true"
    for name in ("DATA_SOURCES_DIR", "DATA_SOURCES_NODE", "DATA_SOURCES_CACHE_DIR"):
        assert examples[name] == "", f"{name} defaults to empty (resolved at run time)"
    for key in KEY_NAMES:
        assert examples[key] == "", f"{key} must be documented without a value"


# ------------------------------------------------------- research subprocess env

def _set_data_config(monkeypatch, **values):
    defaults = {
        "DATA_SOURCES_ENABLED": True,
        "DATA_SOURCES": "fred,bls,bis,imf,wb,usgov",
        "DATA_SOURCES_DIR": "",
        "DATA_SOURCES_NODE": "",
        "DATA_SOURCES_CACHE_DIR": "",
        "DATA_SOURCES_CALL_TIMEOUT": 60,
        "DATA_SOURCES_PREFETCH_MAX": 12,
        "DATA_SOURCES_CHARTS_MAX": 8,
    }
    defaults.update(values)
    for name, value in defaults.items():
        monkeypatch.setattr(Config, name, value, raising=False)


def _executable(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("#!/bin/sh\necho v22.0.0\n", encoding="utf-8")
    path.chmod(0o755)
    return path


def test_subprocess_env_resolves_defaults_to_absolute_paths(monkeypatch, tmp_path):
    node = _executable(tmp_path / "bin" / "node")
    _set_data_config(monkeypatch)
    monkeypatch.setattr(Config, "UPLOAD_FOLDER", str(tmp_path / "uploads"))
    monkeypatch.setattr(po.shutil, "which", lambda name, *a, **k: str(node) if name == "node" else None)

    env = po._data_sources_subprocess_env()

    assert env == {
        "DATA_SOURCES_ENABLED": "true",
        "DATA_SOURCES": "fred,bls,bis,imf,wb,usgov",
        "DATA_SOURCES_DIR": str(REPO_ROOT / "datamcps"),
        "DATA_SOURCES_NODE": str(node),
        "DATA_SOURCES_CACHE_DIR": str(tmp_path / "uploads" / ".data_cache"),
        "DATA_SOURCES_CALL_TIMEOUT": "60",
        "DATA_SOURCES_PREFETCH_MAX": "12",
        "DATA_SOURCES_CHARTS_MAX": "8",
    }
    assert all(isinstance(value, str) for value in env.values())


def test_subprocess_env_resolves_relative_and_user_paths(monkeypatch, tmp_path):
    _set_data_config(
        monkeypatch,
        DATA_SOURCES_DIR="vendor/datamcps",
        DATA_SOURCES_CACHE_DIR="~/drf-data-cache",
        DATA_SOURCES_NODE="tools/node",
    )
    env = po._data_sources_subprocess_env()
    assert env["DATA_SOURCES_DIR"] == str(REPO_ROOT / "vendor" / "datamcps")
    assert env["DATA_SOURCES_CACHE_DIR"] == os.path.expanduser("~/drf-data-cache")
    # An explicit node is forwarded as configured (absolutised, never swapped):
    # data_mcp then reports a wrong setting instead of silently using another node.
    assert env["DATA_SOURCES_NODE"] == str(REPO_ROOT / "tools" / "node")

    _set_data_config(monkeypatch, DATA_SOURCES_DIR=str(tmp_path / "abs"))
    assert po._data_sources_subprocess_env()["DATA_SOURCES_DIR"] == str(tmp_path / "abs")


def test_node_resolution_order(monkeypatch, tmp_path):
    repo = str(tmp_path)
    found = _executable(tmp_path / "path-bin" / "node22")
    fallback = _executable(tmp_path / "home" / ".local" / "bin" / "node")

    # Bare command names are looked up on PATH; unknown ones pass through verbatim.
    monkeypatch.setattr(po.shutil, "which", lambda name, *a, **k: str(found) if name == "node22" else None)
    assert po._resolve_data_sources_node("node22", repo) == str(found)
    assert po._resolve_data_sources_node("nodeX", repo) == "nodeX"

    # Unset: PATH first, then the per-user / Homebrew fallbacks, else "".
    monkeypatch.setattr(po, "_DATA_SOURCES_NODE_FALLBACKS", (
        str(tmp_path / "missing" / "node"), str(fallback)))
    assert po._resolve_data_sources_node("", repo) == str(fallback)
    monkeypatch.setattr(po.shutil, "which", lambda name, *a, **k: str(found) if name == "node" else None)
    assert po._resolve_data_sources_node("", repo) == str(found)
    monkeypatch.setattr(po.shutil, "which", lambda name, *a, **k: None)
    monkeypatch.setattr(po, "_DATA_SOURCES_NODE_FALLBACKS", (str(tmp_path / "missing" / "node"),))
    assert po._resolve_data_sources_node("", repo) == ""


def _run_research_capturing_env(monkeypatch, tmp_path) -> dict:
    deerflow_dir = tmp_path / "deer-flow"
    deerflow_dir.mkdir()
    (deerflow_dir / "deerflow_research.py").write_text("# test entrypoint\n", encoding="utf-8")
    handoff_dir = tmp_path / "handoff"
    handoff_dir.mkdir()
    (handoff_dir / "research_report.md").write_text("research evidence " * 40, encoding="utf-8")
    captured = {}

    class CompletedProcess:
        pid = 4321
        stdout = []

        @staticmethod
        def poll():
            return 0

        @staticmethod
        def wait(timeout=None):
            return 0

    def fake_popen(*args, **kwargs):
        captured["env"] = kwargs["env"]
        return CompletedProcess()

    monkeypatch.setattr(po.Config, "DEERFLOW_DIR", str(deerflow_dir))
    monkeypatch.setattr(po.Config, "UPLOAD_FOLDER", str(tmp_path / "uploads"))
    monkeypatch.setattr(po, "_sync_deerflow_bridge_if_stale", lambda _path: None)
    monkeypatch.setattr(po.subprocess, "Popen", fake_popen)

    po.DeerFlowResearchRunner.run(
        "forecast question",
        str(handoff_dir),
        on_progress=lambda _pct, _message: None,
        timeout=10,
    )
    return captured["env"]


def test_research_runner_forwards_data_sources_env(monkeypatch, tmp_path):
    node = _executable(tmp_path / "node-bin" / "node")
    _set_data_config(
        monkeypatch,
        DATA_SOURCES="fred,wb",
        DATA_SOURCES_DIR=str(tmp_path / "servers"),
        DATA_SOURCES_NODE=str(node),
        DATA_SOURCES_CACHE_DIR=str(tmp_path / "data-cache"),
        DATA_SOURCES_CALL_TIMEOUT=75,
        DATA_SOURCES_PREFETCH_MAX=3,
        DATA_SOURCES_CHARTS_MAX=2,
    )
    # Keys are not Config attributes: they ride along from os.environ untouched.
    monkeypatch.setenv("FRED_API_KEY", "test-not-a-real-key")
    # A stale ambient value never beats Config (the parent is the single source).
    monkeypatch.setenv("DATA_SOURCES_PREFETCH_MAX", "99")

    env = _run_research_capturing_env(monkeypatch, tmp_path)

    assert env["DATA_SOURCES_ENABLED"] == "true"
    assert env["DATA_SOURCES"] == "fred,wb"
    assert env["DATA_SOURCES_DIR"] == str(tmp_path / "servers")
    assert env["DATA_SOURCES_NODE"] == str(node)
    assert env["DATA_SOURCES_CACHE_DIR"] == str(tmp_path / "data-cache")
    assert env["DATA_SOURCES_CALL_TIMEOUT"] == "75"
    assert env["DATA_SOURCES_PREFETCH_MAX"] == "3"
    assert env["DATA_SOURCES_CHARTS_MAX"] == "2"
    assert env["FRED_API_KEY"] == "test-not-a-real-key"


def test_research_runner_forwards_disabled_switch(monkeypatch, tmp_path):
    _set_data_config(monkeypatch, DATA_SOURCES_ENABLED=False)
    env = _run_research_capturing_env(monkeypatch, tmp_path)
    assert env["DATA_SOURCES_ENABLED"] == "false"
    assert env["DATA_SOURCES_CACHE_DIR"] == str(tmp_path / "uploads" / ".data_cache")


# ------------------------------------------------------------ deployment parity

def test_data_modules_deploy_everywhere():
    assert set(DATA_MODULES) <= set(po._DEPLOYED_BRIDGE_MODULES)

    setup_text = (REPO_ROOT / "setup.sh").read_text(encoding="utf-8")
    loops = [line.strip() for line in setup_text.splitlines()
             if line.strip().startswith("for _tool_mod in ")]
    assert len(loops) == 1
    setup_modules = loops[0][len("for _tool_mod in "):].split(";", 1)[0].split()
    assert set(po._DEPLOYED_BRIDGE_MODULES) <= set(setup_modules)

    init_text = (REPO_ROOT / "init.sh").read_text(encoding="utf-8")
    for module in DATA_MODULES:
        assert f'"$project_root/deerflow_bridge/{module}"' in init_text, module


def test_drift_guard_syncs_the_data_modules(tmp_path, monkeypatch):
    bridge_dir = tmp_path / "deerflow_bridge"
    deployed_dir = tmp_path / "deer-flow"
    (deployed_dir / "skills").mkdir(parents=True)
    for skill in REQUIRED_SKILLS:
        skill_file = bridge_dir / "skills" / skill / "SKILL.md"
        skill_file.parent.mkdir(parents=True)
        skill_file.write_text(f"---\nname: {skill}\n---\n", encoding="utf-8")
    for root in (bridge_dir, deployed_dir):
        (root / "deerflow_research.py").write_text("same\n", encoding="utf-8")
    for module in DATA_MODULES:
        (bridge_dir / module).write_text(f"# NEW {module}\n", encoding="utf-8")
    # One stale deployed copy, three never deployed.
    (deployed_dir / "data_sources.py").write_text("# OLD data_sources\n", encoding="utf-8")
    monkeypatch.setattr(
        "app.services.pipeline_orchestrator.__file__",
        str(tmp_path / "backend" / "app" / "services" / "pipeline_orchestrator.py"),
    )

    po._sync_deerflow_bridge_if_stale(str(deployed_dir))

    for module in DATA_MODULES:
        assert (deployed_dir / module).read_text(encoding="utf-8") == f"# NEW {module}\n"
    for skill in ("data-sources", "data-visuals"):
        assert (deployed_dir / "skills" / "public" / skill / "SKILL.md").is_file()


def test_npm_and_setup_wiring():
    scripts = json.loads((REPO_ROOT / "package.json").read_text(encoding="utf-8"))["scripts"]
    assert scripts["setup:datamcps"] == "bash scripts/setup_datamcps.sh"
    assert SETUP_DATAMCPS.is_file() and os.access(SETUP_DATAMCPS, os.X_OK)

    setup_text = (REPO_ROOT / "setup.sh").read_text(encoding="utf-8")
    deerflow_venv = setup_text.index('ok "DeerFlow venv ready')
    datamcps_step = setup_text.index('bash "$ROOT_DIR/scripts/setup_datamcps.sh"')
    drf2_block = setup_text.index("# 5b) OPTIONAL — DRF-2 preview")
    assert deerflow_venv < datamcps_step < drf2_block
    assert 'if [ "${SETUP_DATAMCPS:-1}" = "0" ]; then' in setup_text

    doctor_text = (REPO_ROOT / "scripts" / "doctor.sh").read_text(encoding="utf-8")
    assert (doctor_text.index('sect "DeerFlow research engine"')
            < doctor_text.index('sect "Data-source MCP servers"')
            < doctor_text.index('sect "Configuration (.env)"'))
    for key in KEY_NAMES:
        assert key in doctor_text


@pytest.mark.skipif(shutil.which("bash") is None, reason="bash unavailable")
@pytest.mark.parametrize("script", ["setup.sh", "init.sh", "scripts/doctor.sh",
                                    "scripts/setup_datamcps.sh"])
def test_shell_scripts_parse(script):
    result = subprocess.run(["bash", "-n", str(REPO_ROOT / script)],
                            capture_output=True, text=True, timeout=30, check=False)
    assert result.returncode == 0, result.stderr


# ---------------------------------------------------- setup_datamcps.sh behavior

def _run_setup_datamcps(tmp_path, *args, **env) -> subprocess.CompletedProcess:
    child_env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": str(tmp_path / "home"),
    }
    child_env.update(env)
    return subprocess.run(["bash", str(SETUP_DATAMCPS), *args], capture_output=True,
                          text=True, timeout=60, env=child_env, check=False)


def _built_bls_layout(root: Path) -> Path:
    server = root / "bls_mcp-main"
    for relative in ("package.json", "package-lock.json", "tsconfig.json", "src/index.ts"):
        (server / relative).parent.mkdir(parents=True, exist_ok=True)
        (server / relative).write_text("{}\n", encoding="utf-8")
    old = 1_700_000_000
    for path in server.rglob("*"):
        if path.is_file():
            os.utime(path, (old, old))
    for relative in ("node_modules/.package-lock.json", "dist/index.js"):
        (server / relative).parent.mkdir(parents=True, exist_ok=True)
        (server / relative).write_text("{}\n", encoding="utf-8")
    return server


@pytest.mark.skipif(shutil.which("bash") is None, reason="bash unavailable")
def test_setup_datamcps_check_mode_is_idempotent_and_detects_staleness(tmp_path):
    node = _executable(tmp_path / "toolchain" / "node")
    _executable(tmp_path / "toolchain" / "npm")
    servers = tmp_path / "servers"
    bls = _built_bls_layout(servers)
    env = {"DATA_SOURCES_DIR": str(servers), "DATA_SOURCES_NODE": str(node)}

    fresh = _run_setup_datamcps(tmp_path, "--check", "bls", **env)
    assert fresh.returncode == 0, fresh.stdout + fresh.stderr
    assert "bls    up-to-date" in fresh.stdout

    newer = 1_800_000_000
    os.utime(bls / "src" / "index.ts", (newer, newer))
    stale = _run_setup_datamcps(tmp_path, "--check", "bls", **env)
    assert stale.returncode == 1
    assert "bls    stale" in stale.stdout

    missing = _run_setup_datamcps(tmp_path, "--check", "fred", **env)
    assert missing.returncode == 1
    assert "fred   skipped" in missing.stdout and "sources missing" in missing.stdout


@pytest.mark.skipif(shutil.which("bash") is None, reason="bash unavailable")
def test_setup_datamcps_gates_old_node_and_opt_out(tmp_path):
    old_node = tmp_path / "toolchain" / "node"
    old_node.parent.mkdir(parents=True)
    old_node.write_text("#!/bin/sh\necho v20.11.0\n", encoding="utf-8")
    old_node.chmod(0o755)
    _executable(tmp_path / "toolchain" / "npm")
    servers = tmp_path / "servers"
    (servers / "us-gov-open-data-mcp-main").mkdir(parents=True)
    (servers / "us-gov-open-data-mcp-main" / "package.json").write_text("{}\n", encoding="utf-8")

    gated = _run_setup_datamcps(tmp_path, "--check", "usgov",
                                DATA_SOURCES_DIR=str(servers), DATA_SOURCES_NODE=str(old_node))
    assert gated.returncode == 1
    assert "node >= 22 required (found v20.11.0)" in gated.stdout

    opted_out = _run_setup_datamcps(tmp_path, SETUP_DATAMCPS="0", DATA_SOURCES_DIR=str(servers))
    assert opted_out.returncode == 0
    assert "SETUP_DATAMCPS=0" in opted_out.stdout

    bad = _run_setup_datamcps(tmp_path, "--bogus")
    assert bad.returncode == 64


# ------------------------------------------------------------------ git hygiene

@pytest.mark.skipif(shutil.which("git") is None, reason="git unavailable")
def test_datamcps_build_outputs_are_ignored_and_sources_are_not():
    def ignored(relative: str) -> bool:
        result = subprocess.run(
            ["git", "-C", str(REPO_ROOT), "check-ignore", "-q", "--no-index", relative],
            capture_output=True, timeout=30, check=False)
        if result.returncode not in (0, 1):
            pytest.skip(f"git check-ignore unusable here: {result.stderr!r}")
        return result.returncode == 0

    for output in (
        "datamcps/fred-mcp-server-main/build/index.js",
        "datamcps/fred-mcp-server-main/node_modules/x/index.js",
        "datamcps/bls_mcp-main/dist/index.js",
        "datamcps/mcp-bis-main/node_modules/tsx/package.json",
        "datamcps/us-gov-open-data-mcp-main/dist/server.js",
        "datamcps/imf-data-mcp-main/.venv/bin/imf-data-mcp",
        "datamcps/data360-mcp-dev/.venv/pyvenv.cfg",
        "datamcps/data360-mcp-dev/static/viz_specs/spec_vega.json",
        "datamcps/imf-data-mcp-main/imf_data_mcp/__pycache__/m.cpython-312.pyc",
        "datamcps/imf-data-mcp-main/imf_data_mcp.egg-info/PKG-INFO",
        "datamcps/bls_mcp-main/logs/pre_tool_use.json",
        "datamcps/bls_mcp-main/.claude/data/sessions/s.json",
    ):
        assert ignored(output), f"build output / litter not ignored: {output}"
    for source in (
        "datamcps/fred-mcp-server-main/src/index.ts",
        "datamcps/fred-mcp-server-main/package.json",
        "datamcps/fred-mcp-server-main/pnpm-lock.yaml",
        "datamcps/bls_mcp-main/package-lock.json",
        "datamcps/mcp-bis-main/package-lock.json",
        "datamcps/mcp-bis-main/bin/cli.js",
        "datamcps/us-gov-open-data-mcp-main/src/server.ts",
        "datamcps/imf-data-mcp-main/uv.lock",
        "datamcps/imf-data-mcp-main/imf_data_mcp/__init__.py",
        "datamcps/data360-mcp-dev/uv.lock",
        "datamcps/data360-mcp-dev/static/index.html",
        "datamcps/data360-mcp-dev/README.md",
        "datamcps/data360-mcp-dev/LICENSE",
    ):
        assert not ignored(source), f"vendored source would be ignored: {source}"


# --------------------------------------------------------------- test isolation

def test_pytest_process_never_sees_ambient_data_settings():
    assert os.environ["DATA_SOURCES_ENABLED"] == "false"
    assert Config.DATA_SOURCES_ENABLED is False
    for name in KEY_NAMES + ("DATA_SOURCES", "DATA_SOURCES_DIR", "DATA_SOURCES_NODE",
                             "DATA_SOURCES_CACHE_DIR"):
        assert name not in os.environ, name


def test_conftest_resets_any_loaded_data_mcp_hub(monkeypatch):
    import conftest

    calls = []
    for alias in ("data_mcp", "drf_test_data_mcp"):
        fake = types.ModuleType(alias)
        fake.reset_hub_for_tests = lambda alias=alias: calls.append(alias)
        monkeypatch.setitem(sys.modules, alias, fake)
    unrelated = types.ModuleType("data_mcp_helpers")
    unrelated.reset_hub_for_tests = lambda: calls.append("data_mcp_helpers")
    monkeypatch.setitem(sys.modules, "data_mcp_helpers", unrelated)

    conftest._reset_data_mcp_hubs()

    assert sorted(calls) == ["data_mcp", "drf_test_data_mcp"]
