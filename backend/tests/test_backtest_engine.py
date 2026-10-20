"""Backtest mode through the whole v3 research engine (design §3–§5).

Uses the offline harness of ``test_research_engine_v3`` (scripted model, the real
bridge with network-bound finalize steps stubbed).  Search and fetch are injected
fakes carrying dates; the archive lookup answers "no capture".
"""

from __future__ import annotations

import datetime as _dt
import json

import pytest

import test_research_engine_v3 as v3

_hermetic_env = v3._hermetic_env
bridge = v3.bridge
lr = v3.lr
rg = v3.rg

POLICY_ENV = "DRF_BACKTEST_POLICY"


@pytest.fixture(autouse=True)
def _closed_archive_circuit():
    rg._backtest_api().reset_archive_circuit()
    yield
    rg._backtest_api().reset_archive_circuit()


def dated_search(query: str, n: int) -> str:
    rows = json.loads(v3.fake_search(query, n))["results"]
    for row in rows:
        row["date"] = "2024-10-20"
    rows.append({"title": "Outcome recap", "url": "https://late.example/recap",
                 "content": "The result was known on 2024-11-06.", "date": "2024-11-06"})
    return json.dumps({"query": query, "results": rows})


def dated_page(url: str) -> str:
    return v3.page_text(url).replace("\n\n", "\n\nPublished Time: 2024-10-20T08:00:00Z\n\n", 1)


def _run(tmp_path, bridge, *, tools_factory=None):
    out_dir = tmp_path / "out"
    out_dir.mkdir(parents=True, exist_ok=True)
    model = v3.ScriptedModel(v3.World())
    plog = v3.FakePlog()
    question = "Will global data-centre capacity exceed 250 GW by the end of 2027?"
    meta = {"status": "running", "question": question, "research_engine": "v3"}

    def write_meta():
        (out_dir / "meta.json").write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")

    def gateway_factory(args, plog_arg, bridge_arg, preset):
        return rg.ModelGateway(model, plog_arg, max_concurrency=preset.workers, budget_units=preset.budget_units,
                               reserve_share=lr.RESERVE_SHARE, sleep=lambda seconds: None)

    def default_tools(ledger, pages_dir, bridge_arg, plog_arg, limits):
        return rg.ResearchTools(ledger, pages_dir, search_fn=dated_search, fetch_fn=dated_page,
                                bridge=bridge_arg, plog=plog_arg, limits=limits,
                                archive_get=lambda lookup, timeout: "[]")

    rc = lr.run(question, out_dir, v3.make_args("standard"), meta, plog, write_meta, bridge=bridge,
                gateway_factory=gateway_factory, tools_factory=tools_factory or default_tools)
    return rc, meta, plog, model, out_dir


def _policy_env(tmp_path, **extra):
    return json.dumps({"as_of": "2024-11-01", "strict": True, "archive": "wayback",
                       "audit_path": str(tmp_path / "out" / "backtest_audit.jsonl"), **extra})


def test_backtest_run_is_dated_at_the_cutoff_and_never_cites_late_sources(tmp_path, bridge, monkeypatch):
    monkeypatch.setenv(POLICY_ENV, _policy_env(tmp_path))
    rc, meta, plog, model, out = _run(tmp_path, bridge)
    assert rc == 0, meta.get("error")
    plan = json.loads((out / lr.WORK_DIRNAME / "plan.json").read_text(encoding="utf-8"))
    brief = (out / lr.WORK_DIRNAME / "brief.md").read_text(encoding="utf-8")
    today = _dt.datetime.now(_dt.timezone.utc).date().isoformat()
    assert plan["as_of"] == "2024-11-01" and meta["as_of_date"] == "2024-11-01"
    assert "As-of date (UTC): 2024-11-01" in brief and today not in brief
    state = json.loads((out / lr.WORK_DIRNAME / lr.STATE_FILENAME).read_text(encoding="utf-8"))
    assert state["identity"]["backtest"] == "backtest:2024-11-01:strict"
    assert {key: meta["backtest"][key] for key in ("as_of", "strict", "archive")} == {
        "as_of": "2024-11-01", "strict": True, "archive": "wayback"}
    assert "audit_path" not in meta["backtest"]
    audit = meta["backtest"]["audit"]
    assert audit["search"]["action:dropped"] >= 1 and audit["search"]["verdict:after"] >= 1
    sources = json.loads((out / "sources.json").read_text(encoding="utf-8"))
    assert sources and all("late.example" not in row["url"] for row in sources)
    prompts = json.dumps([call["messages"] for call in model.calls], ensure_ascii=False, default=str)
    assert "late.example" not in prompts and "Outcome recap" not in prompts
    assert any("backtest mode as of 2024-11-01" in line for line in plog.of("stage"))


def test_unusable_policy_fails_the_run(tmp_path, bridge, monkeypatch):
    monkeypatch.setenv(POLICY_ENV, '{"as_of": "2024-11-31"}')
    rc, meta, _, model, _ = _run(tmp_path, bridge)
    assert rc == 2 and meta["status"] == "failed"
    assert meta["error"].startswith("backtest policy unusable")
    assert model.calls == []


def test_tools_without_the_cutoff_are_refused(tmp_path, bridge, monkeypatch):
    monkeypatch.setenv(POLICY_ENV, _policy_env(tmp_path))

    class LegacyTools:
        def __init__(self, ledger, pages_dir, *args):
            self.ledger = ledger

    rc, meta, _, model, _ = _run(tmp_path, bridge, tools_factory=lambda *args: LegacyTools(*args))
    assert rc == 2 and "apply the cutoff" in meta["error"] and model.calls == []


def test_live_run_identity_has_no_backtest_tag(tmp_path, bridge, monkeypatch):
    monkeypatch.delenv(POLICY_ENV, raising=False)
    rc, meta, *_, out = _run(tmp_path, bridge)
    assert rc == 0, meta.get("error")
    state = json.loads((out / lr.WORK_DIRNAME / lr.STATE_FILENAME).read_text(encoding="utf-8"))
    assert "backtest" not in state["identity"] and "backtest" not in meta
