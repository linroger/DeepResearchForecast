"""Standalone skill behavior and self-contained installation, no provider calls."""
from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import sys

import pytest

REPO = Path(__file__).resolve().parents[2]


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def cli(monkeypatch):
    for key in ("FMP_API_KEY", "FMP_ENABLED", "FMP_TIMEOUT_SECONDS", "FMP_MAX_CALLS"):
        monkeypatch.delenv(key, raising=False)
    return load(REPO / "deerflow_bridge/skills/fmp-research/scripts/fmp.py", "fmp_skill_test_cli")


def test_explicit_env_is_narrow_and_process_takes_precedence(tmp_path, monkeypatch, cli):
    dotenv = tmp_path / "fmp-settings.fixture"
    dotenv.write_text('FMP_API_KEY="synthetic-local"\nOTHER_KEY=never-import\nFMP_ENABLED=true\n')
    monkeypatch.setenv("FMP_API_KEY", "synthetic-process")
    assert cli._environment(str(dotenv)) == {"FMP_API_KEY": "synthetic-process", "FMP_ENABLED": "true"}


@pytest.mark.parametrize("value", ['"unclosed', "${OTHER_KEY}", "$(command)"])
def test_environment_file_is_data_not_shell(tmp_path, cli, value):
    dotenv = tmp_path / "fmp-settings.fixture"
    dotenv.write_text("FMP_API_KEY=" + value + "\n")
    with pytest.raises(ValueError):
        cli._environment(str(dotenv))


def test_cli_discovery_and_call_preserve_capture_and_hide_credential(tmp_path, cli, monkeypatch, capsys):
    class Client:
        def __init__(self, env):
            self.key = env["FMP_API_KEY"]
        def discover(self, query):
            assert query == "statements"
            return {"status": {"state": "ok"}, "tools": [{"name": "example"}]}
        def call(self, tool, arguments):
            assert tool == "example" and arguments == {"symbol": "AAA"}
            return {"status": {"state": "ok", "reason": self.key},
                    "data": {"revenue": 125.5, "currency": "JPY"}}
        def close(self):
            pass
    monkeypatch.setattr(cli, "_client_type", lambda: Client)
    monkeypatch.setenv("FMP_API_KEY", "synthetic-no-log-key")
    assert cli.main(["discover", "--query", "statements"]) == 0
    assert json.loads(capsys.readouterr().out)["tools"][0]["name"] == "example"
    request = tmp_path / "request.json"
    request.write_text('{"symbol":"AAA"}')
    output = tmp_path / "capture.json"
    assert cli.main(["call", "--tool", "example", "--arguments-file", str(request),
                     "--output", str(output)]) == 0
    text = output.read_text() + capsys.readouterr().out
    assert "synthetic-no-log-key" not in text
    assert json.loads(output.read_text())["data"] == {"revenue": 125.5, "currency": "JPY"}
    assert output.stat().st_mode & 0o777 == 0o600
    previous = output.read_bytes()
    monkeypatch.setattr(cli, "_client_type", lambda: pytest.fail("existing output must reject before provider"))
    assert cli.main(["discover", "--output", str(output)]) == 2
    assert output.read_bytes() == previous


def test_nonfinite_request_rejected_before_acquisition(tmp_path, cli, monkeypatch, capsys):
    request = tmp_path / "request.json"
    request.write_text('{"limit":NaN}')
    monkeypatch.setattr(cli, "_client_type", lambda: pytest.fail("no acquisition for invalid input"))
    assert cli.main(["call", "--tool", "example", "--arguments-file", str(request)]) == 2
    assert json.loads(capsys.readouterr().out)["status"]["state"] == "unavailable"


def test_install_contains_canonical_client_and_refuses_existing_bundle(tmp_path):
    installer = load(REPO / "scripts/install_fmp_skill.py", "fmp_skill_installer_test")
    repo = tmp_path / "repo"
    skill = repo / "deerflow_bridge/skills/fmp-research"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text("fixture skill")
    client = repo / "deerflow_bridge/fmp_mcp.py"
    client.write_text("class FmpMcpClient: pass\n")
    skills = tmp_path / "skills"
    result = installer.install(repo, skills)
    installed = skills / "fmp-research"
    assert (installed / "scripts/fmp_mcp.py").read_bytes() == client.read_bytes()
    for name, digest in result["files"].items():
        assert hashlib.sha256((installed / name).read_bytes()).hexdigest() == digest
    with pytest.raises(FileExistsError):
        installer.install(repo, skills)
    assert (installed / "SKILL.md").read_text() == "fixture skill"


def test_canonical_client_loads_without_environment_or_network(cli):
    # Importing the actual packaged implementation must not acquire credentials
    # or start a session; its disabled result is meaningful to Codex.
    client = cli._client_type()(env={})
    try:
        result = client.discover("news")
        assert result["status"]["state"] in {"disabled", "unavailable"}
        assert not result.get("tools")
    finally:
        client.close()
