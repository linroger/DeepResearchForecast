"""Context propagation probes over the real v3 engine and gateway.

Only model/search/fetch responses and external finalization services are scripted.
Run through backend/scripts/main_offline_pytest.py from a private source mirror.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
import sys

import pytest

import test_research_engine_v3 as base

lr, rg = base.lr, base.rg
bridge = base.bridge
_hermetic_env = base._hermetic_env


@pytest.fixture(scope="session", autouse=True)
def _attribute_blocked_operations():
    """Record code locations for denied probes without changing admission.

    The unchanged guard runs first and retains every denial. Only code
    filenames/functions/line numbers are captured, never arguments or locals.
    """
    guard = sys.modules.get("main_offline_guard")
    if guard is None:
        yield
        return
    original = guard.record
    events = []

    def record(kind, **details):
        original(kind, **details)
        if kind.startswith("blocked:") and len(events) < 100:
            stack = []
            frame = sys._getframe(1)
            while frame is not None and len(stack) < 16:
                stack.append({"file": frame.f_code.co_filename, "function": frame.f_code.co_name,
                              "line": frame.f_lineno})
                frame = frame.f_back
            events.append({"event": kind, "program": details.get("program"), "stack": stack})

    guard.record = record
    try:
        yield
    finally:
        guard.record = original
        (guard.root / "blocked-operation-stacks.json").write_text(json.dumps(events, indent=2))


def _trace(out, model):
    (out / "context-audit-prompts.json").write_text(
        json.dumps(model.calls, ensure_ascii=False, indent=2, default=str))


class ScopedWorld(base.World):
    formulation = "Which capacity additions can pass the Aurora transmission constraint?"
    horizon = "31 December 2029 (Aurora resolution window)"
    entity = "Aurora interconnection authority"

    def scope(self, call):
        return base.ai(json.dumps({"restated_question": self.formulation, "horizon": self.horizon,
                                   "key_entities": [self.entity],
                                   "scout_queries": ["capacity 2023", "grid queue"]}))


def test_scope_fields_reach_real_planning_and_downstream_prompts(tmp_path, bridge, monkeypatch):
    monkeypatch.setenv("RESEARCH_SKILLS", "off")
    world = ScopedWorld()
    rc, meta, log, model, out = base.run_engine(tmp_path, bridge, world, depth="quick")
    _trace(out, model)
    assert rc == 0, log.text()
    plan = json.loads((out / "v3/plan.json").read_text())
    assert plan["restated_question"] == world.formulation
    assert plan["horizon"] == world.horizon
    for role in ("PLANNING TASK", "agent", "SECTION WRITING TASK", "EXECUTIVE SUMMARY TASK",
                 "ACTOR EXTRACTION TASK", "FACT EXTRACTION TASK"):
        calls = base.calls_of(model, role)
        assert calls, role
        for call in calls:
            prompt = "\n".join(text for _, text in call["messages"])
            for field in (world.formulation, world.horizon, world.entity):
                assert field in prompt, (role, field)


def test_historical_cutoff_survives_model_extraction_to_final_actors(tmp_path, bridge, monkeypatch):
    import backtest_cutoff as bt

    policy = bt.BacktestPolicy(dt.date(2024, 12, 31), archive="off")
    monkeypatch.setenv("DRF_BACKTEST_POLICY", policy.to_env())
    monkeypatch.setenv("RESEARCH_SKILLS", "off")
    original_search = base.fake_search

    def historical_search(query, n):
        payload = json.loads(original_search(query, n))
        for row in payload["results"]:
            row["published_at"] = "2023-12-31"
        return json.dumps(payload)

    monkeypatch.setattr(base, "fake_search", historical_search)
    rc, meta, log, model, out = base.run_engine(tmp_path, bridge, base.World(), depth="quick")
    _trace(out, model)
    assert rc == 0, log.text()
    assert json.loads((out / "v3/plan.json").read_text())["as_of"] == policy.as_of_iso
    for role in ("SCOPE TASK", "PLANNING TASK", "agent", "SECTION WRITING TASK",
                 "EXECUTIVE SUMMARY TASK", "ACTOR EXTRACTION TASK", "FACT EXTRACTION TASK"):
        assert all(policy.as_of_iso in "\n".join(text for _, text in call["messages"])
                   for call in base.calls_of(model, role)), role
    # The scripted extractor returns a valid but wrong 2026 date. The admitted
    # historical cutoff, not generated text, owns the artifact identity.
    actors = json.loads((out / "actors.json").read_text())
    assert actors["as_of_date"] == policy.as_of_iso
    assert meta["as_of_date"] == actors["as_of_date"]
    path = out / "v3/plan.json"
    saved = json.loads(path.read_text())
    saved["as_of"] = "2030-01-01"
    path.write_text(json.dumps(saved))
    rc2, meta2, _, model2, _ = base.run_engine(tmp_path, bridge, base.World(), depth="quick", out_dir=out)
    assert rc2 == 2 and "research_plan_identity_mismatch" in meta2.get("error", "")
    assert not model2.calls


@pytest.mark.parametrize("metadata", [{}, {"verdict": "before", "date": "2020-01-01"},
                                     {"verdict": "after", "date": "2030-01-01"}])
def test_historical_gateway_rechecks_prelabelled_search_rows(tmp_path, metadata):
    import backtest_cutoff as bt

    policy = bt.BacktestPolicy(dt.date(2024, 12, 31), archive="off")
    ledger = rg.SourceLedger(tmp_path / "ledger.json")
    payload = {"results": [
        {"title": "Future release", "url": "https://agency.example/future", "content": "Future-only 999 GW",
         "published_at": "2026-01-01", "backtest": metadata},
        {"title": "Historical release", "url": "https://agency.example/history", "content": "Historical 176 GW",
         "published_at": "2023-12-31", "backtest": metadata},
    ]}
    tools = rg.ResearchTools(ledger, tmp_path / "pages", backtest=policy,
                             search_fn=lambda query, n: json.dumps(payload))
    output = tools.search("capacity", agent_id="K1")
    assert "Historical 176 GW" in output
    assert "Future-only" not in output
    assert "dated 2023-12-31" in output
    assert ledger.find("https://agency.example/future") is None
    # The cached replay retains the same cutoff-filtered answer.
    assert "Future-only" not in tools.search("capacity", agent_id="K2")


@pytest.mark.parametrize("mutation", ["changed", "missing", "symlink"])
def test_web_page_replay_rejects_changed_bytes_without_refetch(tmp_path, mutation):
    ledger = rg.SourceLedger(tmp_path / "ledger.json")
    fetched = []

    def fetch(url):
        fetched.append(url)
        return base.page_text(url)

    tools = rg.ResearchTools(ledger, tmp_path / "pages", fetch_fn=fetch)
    url = "https://agency.example/capacity"
    original = tools.fetch(url, focus="capacity", kiq_text="Capacity baseline", agent_id="K1")
    assert "176 GW" in original
    row = ledger.find(url)
    path = tools.pages_dir / row["page_path"].split("/")[-1]
    assert hashlib.sha256(path.read_bytes()).hexdigest() == row["content_sha256"]
    ledger.flush()
    if mutation == "changed":
        path.write_text(base.page_text(url).replace("176 GW", "999 GW"))
    elif mutation == "missing":
        path.unlink()
    else:
        target = tmp_path / "foreign-page.txt"
        target.write_text(path.read_text())
        path.unlink()
        path.symlink_to(target)
    restored = rg.ResearchTools(rg.SourceLedger(ledger.path), tools.pages_dir, fetch_fn=fetch)
    replay = restored.fetch(url, focus="capacity", agent_id="K2")
    assert replay.startswith("FETCH_FAILED(stored_evidence_corrupt)"), replay
    assert restored.page_text(row["sid"]) is None
    assert fetched == [url]


def test_web_page_hash_replay_preserves_original_line_endings(tmp_path):
    url = "https://agency.example/capacity"
    page = base.page_text(url).replace("\n", "\r\n")
    calls = []
    ledger = rg.SourceLedger(tmp_path / "ledger.json")
    tools = rg.ResearchTools(ledger, tmp_path / "pages", fetch_fn=lambda url: calls.append(url) or page)
    assert "176 GW" in tools.fetch(url, agent_id="K1")
    ledger.flush()
    restored = rg.ResearchTools(rg.SourceLedger(ledger.path), tools.pages_dir,
                                fetch_fn=lambda url: calls.append(url) or page)
    assert "176 GW" in restored.fetch(url, agent_id="K2")
    assert restored.page_text(1) == page.strip()
    assert calls == [url]


def test_finalizer_refuses_corrupt_web_generation_on_resume(tmp_path, bridge, monkeypatch):
    monkeypatch.setenv("RESEARCH_SKILLS", "off")
    rc, _, log, model, out = base.run_engine(tmp_path, bridge, base.World(), depth="quick")
    assert rc == 0, log.text()
    ledger = json.loads((out / "v3/sources_ledger.json").read_text())
    row = next(row for row in ledger if row.get("fetched"))
    page = out / "v3/pages" / row["page_path"].split("/")[-1]
    page.write_text(page.read_text().replace("176 GW", "999 GW"))
    calls = []

    def forbidden_fetch(url):
        calls.append(url)
        raise AssertionError("corrupt evidence must not reacquire")

    rc2, meta2, log2, model2, _ = base.run_engine(
        tmp_path, bridge, base.World(), depth="quick", out_dir=out, fetch=forbidden_fetch)
    _trace(out, model2)
    assert rc2 == 2, log2.text()
    assert "web_evidence_corrupt" in meta2.get("error", "")
    assert not calls and not model2.calls


@pytest.mark.parametrize("summary_outage", [False, True])
def test_qa_rewrite_reaches_executive_summary_and_final_extraction(tmp_path, bridge, monkeypatch, summary_outage):
    monkeypatch.setenv("RESEARCH_SKILLS", "off")
    monkeypatch.setenv("RESEARCH_LINEAR_CRITIQUE", "true")
    summaries = []

    class RevisedWorld(base.World):
        def writer(self, call):
            result = super().writer(call)
            if "## Demand Drivers" in result.content and "Problem to fix:" not in call["messages"][-1][1]:
                result.content = result.content.replace("176 GW", "999 GW")
            return result

        def critique(self, call):
            return base.ai(json.dumps({"issues": [{"section_title": "Demand Drivers",
                "issue": "The baseline is 176 GW, not 999 GW", "fix": "Use the admitted baseline"}]}))

        def exec_summary(self, call):
            summaries.append(call)
            if summary_outage and len(summaries) > 1:
                raise Exception("Error code: 401 - synthetic unavailable summary")
            result = super().exec_summary(call)
            leads = call["messages"][2][1]
            if "999 GW" in leads:
                result.content = result.content.replace("176 GW", "999 GW")
            return result

    rc, meta, log, model, out = base.run_engine(tmp_path, bridge, RevisedWorld())
    _trace(out, model)
    assert rc == 0, log.text()
    qa = json.loads((out / "v3/qa.json").read_text())
    assert any(row.get("section") == "Demand Drivers" and row.get("action") == "rewritten"
               for row in qa["repaired"]), qa
    assert "999 GW" in (out / "v3/synth_report.md").read_text()
    report = (out / "research_report.md").read_text()
    assert "999 GW" not in report
    assert len(summaries) == 2
    for call in base.calls_of(model, "ACTOR EXTRACTION TASK") + base.calls_of(model, "FACT EXTRACTION TASK"):
        assert "999 GW" not in "\n".join(text for _, text in call["messages"])


def test_context_rows_actually_in_kiq_prompt_are_citable(tmp_path, bridge, monkeypatch):
    import news_signals as api
    from test_news_research import context_item

    monkeypatch.setenv("RESEARCH_SKILLS", "off")
    monkeypatch.setenv("NEWS_CONTEXT_ENABLED", "true")
    monkeypatch.setattr(rg, "_context_api", lambda: api)

    def search_news(self, query, *, deadline=None):
        return self.record_result("newsapi", query, {
            "provider": "newsapi", "query": query, "status": {"state": "ok", "attempted": True},
            "items": [dict(context_item(n), query=query) for n in range(1, 6)],
            "retrieved_at": "2026-10-18T10:00:00Z"})

    monkeypatch.setattr(api.ContextClient, "search_news", search_news)

    class ContextWorld(base.World):
        def agent(self, call):
            task = call["messages"][2][1]
            marker = re.search(r"\[S(\d+)\] Publisher capacity release 5", task)
            assert marker, "fifth publisher is actually in the KIQ prompt"
            return base.ai("## Findings\n- Publisher five's discovery snippet needs a publisher fetch "
                           f"before establishing the baseline [S{marker[1]}] (REPORTED)\n"
                           "## Conflicts\n## Open questions\n- Need full publisher page\n## Discovered")

    rc, meta, log, model, out = base.run_engine(tmp_path, bridge, ContextWorld(), depth="quick")
    _trace(out, model)
    assert rc == 0, log.text()
    ledger = json.loads((out / "v3/sources_ledger.json").read_text())
    sid = next(row["sid"] for row in ledger if row.get("context_id") == context_item(5)["id"])
    for path in (out / "v3/kiq").glob("*.json"):
        record = json.loads(path.read_text())
        assert any(sid in row["sids"] for row in record["facts"]), record
        assert record["stats"]["fallback"] is None


def test_valid_web_replay_and_identity_change_keep_owned_evidence(tmp_path, bridge, monkeypatch):
    monkeypatch.setenv("RESEARCH_SKILLS", "off")
    rc, _, log, _, out = base.run_engine(tmp_path, bridge, base.World(), depth="quick")
    assert rc == 0, log.text()
    before = {str(path.relative_to(out)): path.read_bytes() for path in (out / "v3/pages").glob("*.txt")}
    rc2, _, log2, model2, _ = base.run_engine(tmp_path, bridge, base.World(), depth="quick", out_dir=out)
    assert rc2 == 0, log2.text()
    assert not model2.calls
    assert before == {str(path.relative_to(out)): path.read_bytes() for path in (out / "v3/pages").glob("*.txt")}
    old_identity = json.loads((out / "v3/state.json").read_text())["identity"]
    rc3, _, log3, model3, _ = base.run_engine(tmp_path, bridge, base.World(), depth="quick", out_dir=out,
                                           question="Will European capacity exceed 200 GW by 2029?")
    assert rc3 == 0, log3.text()
    assert base.calls_of(model3, "PLANNING TASK") and base.calls_of(model3, "agent")
    assert json.loads((out / "v3/state.json").read_text())["identity"] != old_identity
    archives = list(out.glob("v3.stale-*"))
    assert len(archives) == 1
    assert before == {"v3/pages/" + path.name: path.read_bytes() for path in (archives[0] / "pages").glob("*.txt")}


def test_summary_cache_replays_only_its_actual_inputs_and_body(tmp_path, bridge, monkeypatch):
    monkeypatch.setenv("RESEARCH_SKILLS", "off")
    captured = []
    original_init = lr._Engine.__init__

    def capture(self, *args, **kwargs):
        original_init(self, *args, **kwargs)
        captured.append(self)

    monkeypatch.setattr(lr._Engine, "__init__", capture)
    rc, _, log, model, out = base.run_engine(tmp_path, bridge, base.World(), depth="quick")
    assert rc == 0, log.text()
    engine = captured[0]
    before = len(base.calls_of(model, "EXECUTIVE SUMMARY TASK"))
    engine._exec_summary(engine.synth["sections"], rg.Deadline(400))
    assert len(base.calls_of(model, "EXECUTIVE SUMMARY TASK")) == before
    path = out / "v3/sections/00.md"
    path.write_text(path.read_text().replace("176 GW", "999 GW"))
    body, _ = engine._exec_summary(engine.synth["sections"], rg.Deadline(400))
    assert "999 GW" not in body
    assert len(base.calls_of(model, "EXECUTIVE SUMMARY TASK")) == before + 1
    changed = [dict(section) for section in engine.synth["sections"]]
    changed[0]["body"] = "New permitted lead with Aurora constraint [S1].\n\n" + changed[0]["body"]
    engine._exec_summary(changed, rg.Deadline(400))
    assert len(base.calls_of(model, "EXECUTIVE SUMMARY TASK")) == before + 2
    assert "New permitted lead" in base.calls_of(model, "EXECUTIVE SUMMARY TASK")[-1]["messages"][2][1]
    _trace(out, model)


@pytest.mark.parametrize("field,value", [("question", "Foreign forecast question"),
                                         ("language", "Foreign language")])
def test_foreign_saved_plan_cannot_rebind_a_matching_state(tmp_path, bridge, monkeypatch, field, value):
    monkeypatch.setenv("RESEARCH_SKILLS", "off")
    rc, _, log, _, out = base.run_engine(tmp_path, bridge, base.World(), depth="quick")
    assert rc == 0, log.text()
    path = out / "v3/plan.json"
    plan = json.loads(path.read_text())
    plan[field] = value
    path.write_text(json.dumps(plan))
    (out / "v3/brief.md").write_text(lr.render_brief(lr.Plan.from_dict(plan)))
    rc2, meta2, log2, model2, _ = base.run_engine(tmp_path, bridge, base.World(), depth="quick", out_dir=out)
    assert rc2 == 2, log2.text()
    assert "research_plan_identity_mismatch" in meta2.get("error", "")
    assert not model2.calls


def test_foreign_kiq_record_is_researched_before_digest_reuse(tmp_path, bridge, monkeypatch):
    monkeypatch.setenv("RESEARCH_SKILLS", "off")
    rc, _, log, _, out = base.run_engine(tmp_path, bridge, base.World(), depth="quick")
    assert rc == 0, log.text()
    path = out / "v3/kiq/K1.json"
    record = json.loads(path.read_text())
    record["question"] = "Foreign industrial context"
    record["facts"][0]["text"] = "Foreign-only evidence must never enter this digest [S1]"
    path.write_text(json.dumps(record))
    # Require the actual downstream writer to consume a reconstructed digest.
    state_path = out / "v3/state.json"
    state = json.loads(state_path.read_text())
    for phase in ("synthesize", "qa", "finalize"):
        state["phases"].pop(phase, None)
    state_path.write_text(json.dumps(state))
    (out / "v3/digest.md").unlink()
    for artifact in (out / "v3/sections").iterdir():
        artifact.unlink()
    rc2, _, log2, model2, _ = base.run_engine(tmp_path, bridge, base.World(), depth="quick", out_dir=out)
    _trace(out, model2)
    assert rc2 == 0, log2.text()
    assert base.calls_of(model2, "agent"), "foreign K1 must reach the real research producer again"
    assert "Foreign-only" not in (out / "v3/digest.md").read_text()
    assert "Foreign-only" not in json.dumps(model2.calls)


def test_cached_qa_report_requires_its_recorded_hash(tmp_path, bridge, monkeypatch):
    monkeypatch.setenv("RESEARCH_SKILLS", "off")
    rc, _, log, _, out = base.run_engine(tmp_path, bridge, base.World(), depth="quick")
    assert rc == 0, log.text()
    path = out / "v3/qa_report.md"
    path.write_text(path.read_text().replace("176 GW", "999 GW"))
    rc2, meta2, log2, model2, _ = base.run_engine(tmp_path, bridge, base.World(), depth="quick", out_dir=out)
    assert rc2 == 2, log2.text()
    assert "research_qa_evidence_corrupt" in meta2.get("error", "")
    assert not model2.calls
