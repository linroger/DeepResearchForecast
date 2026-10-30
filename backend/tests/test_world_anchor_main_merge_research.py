"""Merged main FMP consumers against the real v1/v2 private spending authority.

Use main_offline_pytest.py. Existing fixtures retain the real ledger and MCP
SDK; only provider HTTP replies are scripted. No paid providers are contacted.
"""
from contextlib import contextmanager
from types import SimpleNamespace
import sys

import pytest

import test_fmp_research as fmp_cases
from test_fmp_research import call, make_tools
from test_run_spending_child_transports import isolated, run_authority  # noqa: F401
from test_world_anchor_spending import anchor

import deerflow_research as dr
import fmp_research as fr
import linear_research as lr
import research_gateway as rg
import run_spending as sp

protocol = fmp_cases.protocol


@contextmanager
def authority(version, tmp_path, monkeypatch):
    if version == 1:
        with run_authority(tmp_path, monkeypatch) as binding:
            yield binding
    else:
        with anchor(tmp_path) as (binding, _manifest, _request):
            yield binding


@pytest.mark.parametrize("version", [1, 2])
def test_private_fmp_configuration_never_constructs_capture_store(tmp_path, monkeypatch, version):
    engine = lr._Engine.__new__(lr._Engine)
    engine.meta = {}
    engine.fmp_enabled = False
    monkeypatch.setenv("FMP_ENABLED", "true")
    monkeypatch.setenv("FMP_API_KEY", "offline-synthetic-key")
    monkeypatch.setattr(fr, "CaptureStore", lambda *a, **kw: pytest.fail("Unqualified FMP store constructed"))
    with authority(version, tmp_path, monkeypatch) as binding:
        before = sp.summary(binding)
        engine._configure_fmp()
        assert engine.meta == {"fmp_research": {"status": "disabled_spending_profile"}}
        assert not engine.fmp_enabled
        assert rg.agent_tools_schema(False, (), engine.fmp_enabled) == rg.AGENT_TOOLS_SCHEMA
        assert sp.summary(binding) == before


@pytest.mark.parametrize("version", [1, 2])
@pytest.mark.parametrize("entry", ["discover", "call", "kiq"])
def test_private_fmp_dispatch_refuses_before_mcp_acquisition(tmp_path, monkeypatch, protocol, version, entry):
    server, created = protocol
    tools = make_tools(tmp_path / "research")
    with authority(version, tmp_path, monkeypatch):
        with pytest.raises(sp.SpendingStop, match="unsupported_route"):
            if entry == "discover":
                tools.fmp_query("fmp_search_tools", query="statements", agent_id="planner")
            elif entry == "call":
                call(tools)
            else:
                agent = lr.KiqAgent.__new__(lr.KiqAgent)
                agent.engine = SimpleNamespace(tools=tools)
                agent.agent_tools = fr.SCHEMAS
                agent.deadline = rg.Deadline(10)
                agent.grace = 0
                agent.kiq = SimpleNamespace(id="K1")
                agent._call_tool({"name": "fmp_search_tools", "args": {"query": "statements"}})
        assert not created and not server.requests
        assert tools.fmp_store.data["captures"] == {}
        assert tools.ledger.rows() == []


@pytest.mark.parametrize("version", [1, 2])
def test_private_tools_reject_injected_fmp_store(tmp_path, monkeypatch, version):
    ledger = rg.SourceLedger(tmp_path / "ledger.json")
    with authority(version, tmp_path, monkeypatch):
        with pytest.raises(sp.SpendingStop, match="unsupported_route"):
            rg.ResearchTools(ledger, tmp_path / "pages", fmp_store=object())
    assert not (tmp_path / "pages").exists()


@pytest.mark.parametrize("version", [1, 2])
def test_private_legacy_fmp_preparation_refuses_before_capture_work(tmp_path, monkeypatch, version):
    monkeypatch.setattr(dr, "_close_legacy_fmp", lambda: pytest.fail("Legacy FMP setup started"))
    with authority(version, tmp_path, monkeypatch):
        with pytest.raises(sp.SpendingStop, match="unsupported_route"):
            dr._prepare_legacy_fmp(tmp_path / "research", "NVDA outlook", SimpleNamespace(), meta={})


def test_required_unbound_fmp_refuses_before_mcp_acquisition(tmp_path, monkeypatch, protocol):
    server, created = protocol
    tools = make_tools(tmp_path / "research")
    monkeypatch.setenv("DRF_RUN_SPENDING_REQUIRED", "1")
    with pytest.raises(sp.SpendingStop, match="missing_context"):
        call(tools)
    assert not created and not server.requests


def test_private_legacy_cli_refuses_before_context_and_provider_setup(tmp_path, monkeypatch):
    monkeypatch.setenv("DRF_RUN_SPENDING_REQUIRED", "1")
    monkeypatch.setenv("RESEARCH_ENGINE", "legacy")
    monkeypatch.setattr(dr, "runtime_skill_sync_telemetry", lambda: {})
    monkeypatch.setattr(dr, "_reset_fetched_sources", lambda *a, **kw: pytest.fail("Legacy setup started"))
    monkeypatch.setattr(sys, "argv", ["deerflow_research.py", "--model", "synthetic", "--depth", "quick",
                                    "--out-dir", str(tmp_path / "legacy"), "--prompt", "NVDA outlook"])
    with pytest.raises(sp.SpendingStop, match="unsupported_route"):
        dr.main()


def test_kiq_preserves_fatal_fmp_integrity_error(monkeypatch):
    def corrupt(*args, **kwargs):
        raise fr.CaptureIntegrityError("fmp_capture_corrupt: citation ledger changed")
    agent = lr.KiqAgent.__new__(lr.KiqAgent)
    agent.engine = SimpleNamespace(tools=SimpleNamespace(fmp_query=corrupt))
    agent.agent_tools = fr.SCHEMAS
    agent.deadline = rg.Deadline(10)
    agent.grace = 0
    agent.kiq = SimpleNamespace(id="K1")
    with pytest.raises(lr._EngineFailure, match="fmp_capture_corrupt"):
        agent._call_tool({"name": "fmp_search_tools", "args": {"query": "statements"}})


def test_nonprivate_fmp_capture_replay_remains_usable_after_merge(tmp_path, protocol):
    server, created = protocol
    tools = make_tools(tmp_path / "research")
    assert "FINANCIAL_CAPTURE_SENTINEL" in call(tools)
    assert created == [True] and server.requests
    before = fr.capture_artifacts(tools.fmp_store.root)
    tools.fmp_store.freeze()
    count = len(server.requests)
    replay = make_tools(tmp_path / "research", replay=True)
    assert "FINANCIAL_CAPTURE_SENTINEL" in call(replay)
    assert len(server.requests) == count and created == [True]
    assert fr.capture_artifacts(tools.fmp_store.root) == before
    tools.fmp_store.close()
    replay.fmp_store.close()
