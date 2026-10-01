"""EVAL-16: tool-call counters and the cross-run stage-scorecard aggregate.

* the v3 KIQ agents count the calls answered with INVALID_TOOL_CALL /
  UNKNOWN_TOOL / TOOL_ERROR (the strings the model sees are unchanged), each KIQ
  record's stats carry them and meta.kiqs sums them (a record written before the
  counters counts 0);
* ReportAgent's tool_unknown agent_log rows (INFRA-5) on every path, and the
  scorecard contracts research invalid/unknown_tool_calls and report
  unknown_tool_calls (== 0; not instrumented without an INFRA-5 marker, torn
  log lines fail closed only when they may hide a row);
* ``scripts/stage_scorecard.py aggregate``: grouping by code sha and backbone
  (partial backbones of runs that stopped early), per-run distributions, pooled
  Wilson regression flags against the same backbone gated on a minimum run
  count, and the exit codes judged on the current code.

Offline: fake search/fetch/LLM doubles, fixtures under tmp_path, no network.
"""

from __future__ import annotations

import copy
import datetime as dt
import json
import os
import socket
import threading
import types

import pytest

import test_report_tool_args as rt
import test_research_engine_v3 as v3
import test_stage_scorecard as ts
from app.services import pipeline_orchestrator as po
from app.services import stage_scorecard as sc
from app.services.eval_stats import wilson_interval
from scripts import stage_scorecard as cli

lr = v3.lr

# Shared fixtures: hermetic research env, the real bridge with network steps
# stubbed, the scorecard's tmp artifact roots and the report folder root.
_hermetic_env = v3._hermetic_env
bridge = v3.bridge
roots = ts.roots
report_dir = rt.report_dir

UTC = dt.timezone.utc


# ============================================================ KiqAgent counters
class _FakeTools:
    def __init__(self):
        self.calls = []
        self._lock = threading.Lock()

    def search(self, query, *, agent_id):
        with self._lock:
            self.calls.append(("search", query))
        if query == "boom":
            raise ConnectionResetError("search backend down")
        return f"[S1] result for {query}"

    def fetch(self, url, *, focus, agent_id, kiq_text):
        with self._lock:
            self.calls.append(("fetch", url))
        if url == "https://boom.example":
            raise TimeoutError("fetch timed out")
        return f"[S2] page {url}"


class _FakeLedger:
    def get(self, sid):
        return None

    def find(self, url):
        return None


def _agent(workers=4):
    engine = types.SimpleNamespace(tools=_FakeTools(), ledger=_FakeLedger(),
                                   preset=types.SimpleNamespace(workers=workers))
    kiq = lr.Kiq(id="K1", question="How large is the grid connection queue?", queries=["q"])
    return lr.KiqAgent(engine, kiq, "Investigate K1: task", [], deadline=None)


# The exact model-visible answers before EVAL-16 (the counters must not change them).
INVALID_PARSE = ("INVALID_TOOL_CALL: bad JSON. Call web_search with a query string or web_fetch "
                 "with a url (and optionally a focus).")
INVALID_SEARCH = "INVALID_TOOL_CALL: web_search needs a 'query' string."
INVALID_FETCH = "INVALID_TOOL_CALL: web_fetch needs a 'url' string."
UNKNOWN = "UNKNOWN_TOOL: only web_search and web_fetch are available."


def test_call_tool_counters_and_strings_unchanged():
    agent = _agent()
    assert agent.call_counts() == {"invalid_tool_calls": 0, "unknown_tool_calls": 0,
                                   "tool_exceptions": 0}
    assert lr.AgentOutcome(notes="").invalid_tool_calls == 0
    assert (lr.AgentOutcome(notes="").unknown_tool_calls, lr.AgentOutcome(notes="").tool_exceptions) == (0, 0)

    # Every branch of _call_tool answers exactly what it answered before.
    assert agent._call_tool({"name": "web_fetch", "args": "{x", "error": "bad JSON"}) == INVALID_PARSE
    assert agent._call_tool({"name": "web_search", "args": {}}) == INVALID_SEARCH
    assert agent._call_tool({"name": "web_fetch", "args": {"url": 7}}) == INVALID_FETCH
    assert agent._call_tool({"name": "web_teleport", "args": {}}) == UNKNOWN
    assert agent._call_tool({"name": "web_search", "args": {"query": "boom"}}) == (
        "TOOL_ERROR(ConnectionResetError): try another source.")
    assert agent._call_tool({"name": "web_fetch", "args": {"url": "https://boom.example"}}) == (
        "TOOL_ERROR(TimeoutError): try another source.")
    assert agent._call_tool({"name": "web_search", "args": {"query": "grid queue"}}) == (
        "[S1] result for grid queue")
    assert agent.call_counts() == {"invalid_tool_calls": 3, "unknown_tool_calls": 1,
                                   "tool_exceptions": 2}

    # One step with several runnable calls runs them on a thread pool: the counts
    # are exact, and calls answered without running (_execute) are not counted.
    agent = _agent(workers=8)
    calls = [{"name": "web_teleport", "args": {}, "id": f"u{i}"} for i in range(40)]
    calls += [
        {"name": "web_fetch", "args": "{x", "id": "bad", "error": "bad JSON"},
        {"name": "web_search", "args": {}, "id": "noq"},
        {"name": "web_search", "args": {"query": "boom"}, "id": "boom"},
        {"name": "web_fetch", "args": {}, "id": "nourl"},
        {"name": "web_search", "args": {"query": "over the per-step cap"}, "id": "skip"},
    ]
    messages, _novel = agent._execute(calls)
    by_id = {m.tool_call_id: m.content for m in messages}
    assert [m.tool_call_id for m in messages] == [c["id"] for c in calls]
    assert {by_id[f"u{i}"] for i in range(40)} == {UNKNOWN}
    assert by_id["bad"] == INVALID_PARSE and by_id["noq"] == INVALID_SEARCH
    assert by_id["nourl"] == INVALID_FETCH
    assert by_id["boom"] == "TOOL_ERROR(ConnectionResetError): try another source."
    assert by_id["skip"] == lr.TOOL_CALLS_SKIPPED_TEXT
    assert agent.call_counts() == {"invalid_tool_calls": 3, "unknown_tool_calls": 40,
                                   "tool_exceptions": 1}


def _kiq_records(out):
    return {path.stem: json.loads(path.read_text(encoding="utf-8"))
            for path in sorted((out / "v3" / "kiq").glob("*.json"))}


def test_meta_kiqs_sums(tmp_path, bridge, monkeypatch):
    """Every KIQ of ProtocolWorld makes one unknown and one unparseable call in its first step."""
    monkeypatch.setenv("RESEARCH_LINEAR_WORKERS", "1")
    out = tmp_path / "out"
    rc, meta, _plog, _model, _ = v3.run_engine(tmp_path, bridge, v3.ProtocolWorld(), depth="quick",
                                                out_dir=out)
    assert rc == 0, meta.get("error")
    records = _kiq_records(out)
    assert records and len(records) == meta["kiqs"]["completed"]
    for record in records.values():
        stats = record["stats"]
        assert (stats["invalid_tool_calls"], stats["unknown_tool_calls"], stats["tool_exceptions"]) == (1, 1, 0)
    kiqs = meta["kiqs"]
    assert kiqs["invalid_tool_calls"] == kiqs["unknown_tool_calls"] == len(records)
    assert kiqs["tool_exceptions"] == 0
    disk = json.loads((out / "meta.json").read_text(encoding="utf-8"))
    assert disk["kiqs"]["unknown_tool_calls"] == disk["kiqs"]["invalid_tool_calls"] == len(records)

    # A record kept by a resumed run that predates the counters counts 0 (every
    # phase is reused, so no model call is made).
    first = sorted(records)[0]
    path = out / "v3" / "kiq" / f"{first}.json"
    stale = records[first]
    for name in lr.TOOL_CALL_COUNTERS:
        del stale["stats"][name]
    path.write_text(json.dumps(stale), encoding="utf-8")
    silent = v3.ScriptedModel(lambda call: pytest.fail(f"unexpected model call: {v3.role_of(call)}"))
    rc, meta, _plog, model, _ = v3.run_engine(tmp_path, bridge, v3.ProtocolWorld(), depth="quick",
                                               out_dir=out, model=silent)
    assert rc == 0 and model.calls == []
    assert meta["kiqs"]["unknown_tool_calls"] == meta["kiqs"]["invalid_tool_calls"] == len(records) - 1
    assert lr._record_stat_count({"stats": {"unknown_tool_calls": True}}, "unknown_tool_calls") == 0
    assert lr._record_stat_count({"stats": "garbage"}, "unknown_tool_calls") == 0
    assert lr._record_stat_count({}, "unknown_tool_calls") == 0


# ====================================================== report tool_unknown rows
def test_report_tool_unknown_logged_both_paths(report_dir):
    """INFRA-5 writes one tool_unknown row per missing tool name (ReAct, dispatch and
    native); the scorecard counts exactly those rows, never the tool_call rows."""
    report_id = "r_eval16_unknown"
    agent = rt._agent()
    agent.report_logger = rt.ReportLogger(report_id)
    agent.llm = rt._ScriptLLM([
        '<tool_call>{"name": "interview_agents", "parameters": {"interview_topic": "t"}}</tool_call>',
        '<tool_call>{"name": "quick_search", "parameters": {"query": "q"}}</tool_call>',
        "Final Answer: " + rt.BODY,
    ])
    rt._recording_executor(agent)
    rt._run_react(agent)

    dispatcher = rt._agent()
    dispatcher.report_logger = agent.report_logger
    assert "未知工具" in dispatcher._execute_tool("no_such_tool", {})

    native = rt._agent()
    native.report_logger = agent.report_logger
    native.llm = rt._NativeLLM([{"content": "", "tool_calls": [
        {"id": "u1", "name": "simulate_market", "arguments": {}},
        {"id": "ok", "name": "insight_forge", "arguments": {"query": "q"}}]}])
    rt._recording_executor(native)
    rt._run_native(native)

    rows = rt._read_agent_log(report_dir, report_id)
    assert [r["details"] for r in rows if r["action"] == "tool_unknown"] == [
        {"tool_name": "interview_agents", "path": "react"},
        {"tool_name": "no_such_tool", "path": "dispatch"},
        {"tool_name": "simulate_market", "path": "native"}]
    path = rt.ReportManager._get_agent_log_path(report_id)
    digests: dict = {}
    record = sc._tool_unknown_rows({"agent_log": path}, digests)
    assert (record["status"], record["value"]) == ("measured", 3)
    assert record["source"] == "report/agent_log.jsonl:action=tool_unknown"
    assert set(digests) == {"agent_log"}


def test_scorecard_reads_a_generated_report_as_instrumented(monkeypatch, report_dir, tmp_path):
    """A report generate_report wrote carries INFRA-5's tool_dispatch counters in its
    report_complete row and telemetry.json: its zero is measured.  Without any marker
    (a report written before INFRA-5) the zero is not evidence: not_instrumented."""
    # INFRA-5's concurrent-sections harness: a real generate_report, valid tool calls only.
    rt.test_concurrent_sections_report_tool_calls_and_dispatch_counters(monkeypatch, report_dir)
    report_id = "r_concurrent_tools"
    log = rt.ReportManager._get_agent_log_path(report_id)
    telemetry = os.path.join(rt.ReportManager._get_report_folder(report_id), "telemetry.json")
    digests: dict = {}
    record = sc._tool_unknown_rows({"agent_log": log, "report_telemetry": telemetry}, digests)
    assert (record["status"], record["value"]) == ("measured", 0)
    assert "detail" not in record and set(digests) == {"agent_log", "report_telemetry"}
    # Either marker alone is enough: the report_complete row...
    assert sc._tool_unknown_rows({"agent_log": log}, {})["status"] == "measured"
    # ...or telemetry.json beside a log without that row.
    rows = rt._read_agent_log(report_dir, report_id)
    assert not {"tool_unknown", "tool_rejected"} & {row["action"] for row in rows}
    legacy = tmp_path / "legacy_agent_log.jsonl"
    legacy.write_text("".join(json.dumps(row) + "\n" for row in rows
                              if row["action"] != "report_complete"), encoding="utf-8")
    paths = {"agent_log": str(legacy), "report_telemetry": telemetry}
    assert sc._tool_unknown_rows(paths, {})["status"] == "measured"
    for missing in (str(tmp_path / "no_telemetry.json"), None):
        record = sc._tool_unknown_rows({"agent_log": str(legacy), "report_telemetry": missing}, {})
        assert (record["status"], record["value"]) == ("not_instrumented", None)


# ================================================================ scorecard
def _write_agent_log(rows, raw_tail=""):
    path = po.ReportManager._get_agent_log_path(ts.REPORT_ID)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write("".join(json.dumps(row) + "\n" for row in rows) + raw_tail)


def _log_row(action, **details):
    """An agent_log row as ReportLogger writes it (action after timestamp, elapsed and report id)."""
    return {"timestamp": "2026-09-30T10:00:00", "elapsed_seconds": 1.5, "report_id": ts.REPORT_ID,
            "action": action, "stage": "generating", "section_title": None, "section_index": None,
            "details": details}


def _kiqs(**counts):
    return dict(ts.V3_META, kiqs=dict(ts.V3_META["kiqs"], **counts))


def test_scorecard_counts_tool_unknown(roots):
    # Healthy: every counter measured at 0 and every contract passes.
    ts._make_pipeline()
    card = ts._score()
    assert sc.summarize_checks(card) == dict.fromkeys(sc.STAGES, True)
    for stage, name in (("research", "invalid_tool_calls"), ("research", "unknown_tool_calls"),
                        ("report", "unknown_tool_calls")):
        record = ts._metric(card, stage, name)
        assert (record["status"], record["value"]) == ("measured", 0), (stage, name)
    assert ts._metric(card, "research", "unknown_tool_calls")["source"] == (
        "handoff/meta.json:kiqs.unknown_tool_calls")

    # Report: only action == tool_unknown rows count (a native tool_call row naming a
    # missing tool is an ordinary call row), and any row fails the contract.
    _write_agent_log([
        {"action": "report_start", "details": {}},
        {"action": "tool_unknown", "details": {"tool_name": "a", "path": "react"}},
        {"action": "tool_call", "details": {"tool_name": "no_such_tool"}},
        {"action": "tool_unknown", "details": {"tool_name": "b", "path": "native"}},
    ], raw_tail="\n")
    card = ts._score()
    assert ts._metric(card, "report", "unknown_tool_calls")["value"] == 2
    assert card["checks"]["report"]["failed"] == ["unknown_tool_calls"]
    assert card["checks"]["report"]["passed"] is False

    # A torn line (a killed write, maybe with a resumed attempt's row appended) may
    # hide a row when it names tool_unknown or was cut before its action field:
    # unreadable, fails closed.
    appended = json.dumps(_log_row("section_start")) + "\n"
    row = json.dumps(_log_row("llm_response", response="x" * 40))
    for tail in ('{"action": "tool_unkn\n',  # cut inside its action value
                 row[:-10] + json.dumps(_log_row("tool_unknown")) + "\n",  # a tool_unknown row appended
                 row[:row.index('"action"')] + appended,  # cut before its action: any row
                 # torn twice: the second torn row was cut before its action
                 row[:-10] + row[:row.index('"action"')] + appended):
        _write_agent_log([_log_row("report_start")], raw_tail=tail)
        card = ts._score()
        record = ts._metric(card, "report", "unknown_tool_calls")
        assert (record["status"], record["value"]) == ("unreadable", None), tail
        assert record["detail"] == "1 line(s) that are not JSON objects may hide a tool_unknown row"
        assert card["checks"]["report"]["failed"] == ["unknown_tool_calls"]
    # A torn row of another action (a long llm_response cut mid-write, here with a
    # resumed attempt's row appended and a split UTF-8 character) cannot hide one:
    # skipped and counted in the detail.
    torn = json.dumps(_log_row("llm_response", response="中" * 40), ensure_ascii=False)
    _write_agent_log([_log_row("report_start")], raw_tail=torn[:-30] + appended)
    with open(po.ReportManager._get_agent_log_path(ts.REPORT_ID), "ab") as handle:
        handle.write(torn.encode("utf-8")[:-31] + b"\n")
    card = ts._score()
    record = ts._metric(card, "report", "unknown_tool_calls")
    assert (record["status"], record["value"]) == ("measured", 0)
    assert record["detail"] == "2 torn row(s) of other actions skipped"
    assert card["checks"]["report"]["passed"] is True

    # A report written before INFRA-5 logged tool_unknown rows has no tool_unknown /
    # tool_rejected row and no tool_dispatch counters: its zero is not evidence.
    telemetry = os.path.join(po.ReportManager._get_report_folder(ts.REPORT_ID), "telemetry.json")
    os.remove(telemetry)
    _write_agent_log([_log_row("report_start"), _log_row("tool_call"),
                      _log_row("report_complete", telemetry_totals={"tool_calls": 1})])
    card = ts._score()
    record = ts._metric(card, "report", "unknown_tool_calls")
    assert (record["status"], record["value"]) == ("not_instrumented", None)
    assert card["checks"]["report"] == {"passed": None, "failed": [],
                                        "unevaluable": ["unknown_tool_calls"]}
    assert "report_telemetry" not in card["artifacts"]
    # Any INFRA-5 marker in the log makes the zero evidence again.
    dispatch = dict.fromkeys(("dispatched", "rejected_parse", "rejected_params",
                              "rejected_unknown", "repaired"), 0)
    for marker in (_log_row("tool_rejected", tool_name="quick_search", reason="missing query"),
                   _log_row("report_complete", telemetry_totals={"tool_dispatch": dispatch})):
        _write_agent_log([_log_row("report_start"), marker])
        card = ts._score()
        assert ts._metric(card, "report", "unknown_tool_calls")["value"] == 0, marker["action"]
        assert card["checks"]["report"]["passed"] is True
    _write_agent_log([_log_row("report_start")])
    ts._write(telemetry, {"totals": {"tool_calls": 0, "tool_dispatch": dispatch}})
    card = ts._score()
    assert ts._metric(card, "report", "unknown_tool_calls")["status"] == "measured"
    assert "report_telemetry" in card["artifacts"]

    os.remove(po.ReportManager._get_agent_log_path(ts.REPORT_ID))
    card = ts._score()
    assert ts._metric(card, "report", "unknown_tool_calls")["status"] == "artifact_missing"
    assert "unknown_tool_calls" in card["checks"]["report"]["failed"]
    assert "agent_log" not in card["artifacts"]

    # Research: the v3 counters from meta.kiqs.
    ts._make_pipeline(meta=_kiqs(invalid_tool_calls=2, unknown_tool_calls=1))
    card = ts._score()
    assert ts._metric(card, "research", "invalid_tool_calls")["value"] == 2
    assert card["checks"]["research"]["failed"] == ["invalid_tool_calls", "unknown_tool_calls"]

    # A v3 meta written before EVAL-16 has no counters: unevaluable, never a pass.
    before = {k: v for k, v in ts.V3_META["kiqs"].items() if k not in lr.TOOL_CALL_COUNTERS}
    ts._make_pipeline(meta=dict(ts.V3_META, kiqs=before))
    card = ts._score()
    assert ts._metric(card, "research", "unknown_tool_calls")["status"] == "not_instrumented"
    assert card["checks"]["research"] == {"passed": None, "failed": [],
                                          "unevaluable": ["invalid_tool_calls", "unknown_tool_calls"]}

    # A counter that is not a count is unreadable (fails closed).
    ts._make_pipeline(meta=_kiqs(unknown_tool_calls=True, invalid_tool_calls="0"))
    card = ts._score()
    for name in ("invalid_tool_calls", "unknown_tool_calls"):
        assert ts._metric(card, "research", name)["status"] == "unreadable"
    assert card["checks"]["research"]["failed"] == ["invalid_tool_calls", "unknown_tool_calls"]

    # Research only for v3: another engine has no KIQ agents (not applicable, skipped).
    for meta in ({"research_engine": "legacy", "actors_count": 3},
                 {"actors_count": 19, "research_quality": {"score": 0.7}}):
        ts._make_pipeline(meta=meta, kiqs={})
        card = ts._score()
        for name in ("invalid_tool_calls", "unknown_tool_calls"):
            assert ts._metric(card, "research", name)["status"] == "not_applicable", (meta, name)
        assert not {"invalid_tool_calls", "unknown_tool_calls"} & set(
            card["checks"]["research"]["failed"] + card["checks"]["research"]["unevaluable"])
    # A v3 meta without a kiqs block is not instrumented; a missing meta fails closed.
    ts._make_pipeline(meta={"research_engine": "v3"}, kiqs={})
    assert ts._metric(ts._score(), "research", "unknown_tool_calls")["status"] == "not_instrumented"
    state = ts._make_pipeline()
    os.remove(os.path.join(state.handoff_dir, "meta.json"))
    card = ts._score()
    assert ts._metric(card, "research", "unknown_tool_calls")["status"] == "artifact_missing"
    assert {"invalid_tool_calls", "unknown_tool_calls"} <= set(card["checks"]["research"]["failed"])


def test_report_unknown_count_cross_checks_telemetry_and_odd_actions(roots):
    """INFRA-5's telemetry counts the unknown calls too: a lost tool_unknown row never
    reads as a measured 0.  A row whose action is not a string stays local to the log."""
    ts._make_pipeline()
    telemetry = os.path.join(po.ReportManager._get_report_folder(ts.REPORT_ID), "telemetry.json")

    def dispatch(rejected_unknown):
        return {"dispatched": 4, "rejected_parse": 0, "rejected_params": 0,
                "rejected_unknown": rejected_unknown, "repaired": 0}

    # ReportAgent swallows a failed log write: no row, but telemetry.json counts 2.
    ts._write(telemetry, {"totals": {"tool_calls": 4, "tool_dispatch": dispatch(2)}})
    _write_agent_log([_log_row("report_start"), _log_row("tool_call")])
    card = ts._score()
    record = ts._metric(card, "report", "unknown_tool_calls")
    assert (record["status"], record["value"]) == ("measured", 2)
    assert record["detail"] == ("telemetry totals.tool_dispatch.rejected_unknown counts 2 unknown "
                                "call(s) but the log holds 0 tool_unknown row(s): rows were lost, "
                                "the telemetry count is used")
    assert card["checks"]["report"]["failed"] == ["unknown_tool_calls"]
    # The largest total of any attempt (each report_complete row and telemetry.json) is
    # the floor; rows beyond it (earlier attempts, the dispatch fallback) still count.
    ts._write(telemetry, {"totals": {"tool_calls": 4, "tool_dispatch": dispatch(1)}})
    _write_agent_log([_log_row("tool_unknown", tool_name="a", path="react"),
                      _log_row("report_complete", telemetry_totals={"tool_dispatch": dispatch(3)})])
    assert ts._metric(ts._score(), "report", "unknown_tool_calls")["value"] == 3
    _write_agent_log([_log_row("tool_unknown", tool_name="a", path="react"),
                      _log_row("tool_unknown", tool_name="b", path="dispatch")])
    record = ts._metric(ts._score(), "report", "unknown_tool_calls")
    assert (record["value"], "detail" in record) == (2, False)
    # A total that is not a count fails closed.
    for bad in ("2", -1, True, None):
        ts._write(telemetry, {"totals": {"tool_dispatch": dispatch(bad)}})
        _write_agent_log([_log_row("report_start")])
        card = ts._score()
        record = ts._metric(card, "report", "unknown_tool_calls")
        assert (record["status"], record["detail"]) == (
            "unreadable", "telemetry totals.tool_dispatch.rejected_unknown is not a count"), bad
        assert card["checks"]["report"]["failed"] == ["unknown_tool_calls"]

    # A valid JSON row with an unhashable action (a hand-edited log) is no marker and no
    # row: only this metric reads the log, every other report metric is still measured.
    ts._write(telemetry, {"totals": {"tool_dispatch": dispatch(0)}})
    for rows, expected in (([], 0), ([_log_row("tool_unknown", tool_name="a", path="native")], 1)):
        _write_agent_log([dict(_log_row("report_start"), action=["tool_unknown"]),
                          dict(_log_row("tool_call"), action={"name": "tool_unknown"})] + rows)
        card = ts._score()
        record = ts._metric(card, "report", "unknown_tool_calls")
        assert (record["status"], record["value"]) == ("measured", expected)
        assert all(metric["status"] == "measured" for metric in card["stages"]["report"]["metrics"].values())
        assert card["checks"]["report"]["failed"] == ([] if expected == 0 else ["unknown_tool_calls"])
    os.remove(telemetry)
    _write_agent_log([dict(_log_row("tool_rejected"), action=["tool_rejected"])])
    assert ts._metric(ts._score(), "report", "unknown_tool_calls")["status"] == "not_instrumented"


def test_rate_metrics_cover_every_num_den_metric(roots):
    """RATE_METRICS names exactly the metrics the projection records as num/den rates."""
    ts._make_pipeline()
    card = ts._score()
    produced = {(stage, name) for stage in sc.STAGES
                for name, record in card["stages"][stage]["metrics"].items()
                if record.get("den") is not None}
    listed = {(stage, name) for stage, names in sc.RATE_METRICS.items() for name in names}
    assert produced == listed
    assert set(sc.RATE_METRICS) <= set(sc.STAGES)
    assert {better for names in sc.RATE_METRICS.values() for better in names.values()} == {
        sc.HIGHER_IS_BETTER, sc.LOWER_IS_BETTER}


# ================================================================ aggregate
@pytest.fixture
def base_card(roots):
    ts._make_pipeline()
    return ts._score()


RESEARCH = {"model": "glm-research"}


def _run(base, pid, day, *, sha="aaa", backbone="glm", verified=(8, 10), failures=(1, 20),
         passed=None):
    """A run built from the healthy scorecard: identity, two rates and stage verdicts overridden.

    ``backbone`` names the report provider (beside the shared RESEARCH model) or is
    the run's whole backbone (a dict, or None when run.json names no model).
    """
    card = copy.deepcopy(base)
    if isinstance(backbone, str):
        backbone = {"research": dict(RESEARCH),
                    "report": {"provider": backbone, "model_name": f"{backbone}-x"}}
    card["identity"].update(pipeline_id=pid, repo_git_sha=sha, backbone=backbone)
    metrics = card["stages"]["research"]["metrics"]
    for name, (num, den) in (("verified_share", verified), ("tool_failure_rate", failures)):
        metrics[name].update(num=num, den=den, value=round(num / den, 4))
    for stage, verdict in (passed or {}).items():
        card["checks"][stage] = {"passed": verdict,
                                 "failed": ["stage_status"] if verdict is False else [],
                                 "unevaluable": ["kiq_completion"] if verdict is None else []}
    created = dt.datetime(2026, 9, day, 12, tzinfo=UTC) if day else None
    return {"pipeline_id": pid, "created_at": created, "card": card}


def _flags(group):
    return [(flag["stage"], flag["measure"]) for flag in group["regressions"]]


def test_aggregate_grouping_wilson_min_runs_and_exit_codes(base_card):
    old = [_run(base_card, f"pipe_old{i}", 1 + i) for i in range(4)]  # verified 32/40 = 0.8

    # Grouped by sha and backbone; ordered by their newest run; the run is the unit.
    runs = old + [_run(base_card, "pipe_kimi", 6, backbone="kimi", verified=(7, 10)),
                  _run(base_card, "pipe_new0", 10, sha="bbb", verified=(2, 10)),
                  _run(base_card, "pipe_new1", 11, sha="bbb", verified=(1, 10))]
    result = cli.aggregate(runs)
    json.dumps(result, allow_nan=False)
    assert result["schema_version"] == "stage-scorecard-aggregate/v1"
    groups = result["groups"]
    assert [(g["repo_git_sha"], g["backbone"]["report"]["provider"], g["runs"]) for g in groups] == [
        ("aaa", "glm", 4), ("aaa", "kimi", 1), ("bbb", "glm", 2)]
    assert groups[0]["pipelines"] == [f"pipe_old{i}" for i in range(4)]
    assert groups[0]["first_created_at"].startswith("2026-09-01T12:00")
    # Compared with the same backbone at an earlier sha (aaa/glm), never with aaa/kimi.
    assert [g["compared_to"] for g in groups] == [None, None, 0] and result["latest_group"] == 2
    assert result["current"] == {"repo_git_sha": "bbb", "groups": [2], "unevaluable_share": 0.0}
    research = groups[0]["stages"]["research"]
    assert research["runs"] == 4
    assert research["contract"] == {"passed": 4, "failed": 0, "unevaluable": 0, "evaluable_runs": 4,
                                    "pass_rate": 1.0,
                                    "wilson": [round(x, 4) for x in wilson_interval(4, 4)]}
    share = research["rates"]["verified_share"]
    assert share["better"] == "higher" and share["runs"] == 4
    assert share["pooled"] == {"runs": 4, "num": 32, "den": 40, "value": 0.8,
                               "wilson": [round(x, 4) for x in wilson_interval(32, 40)]}
    assert share["per_run"] == {"median": 0.8, "min": 0.8, "max": 0.8}
    latest = groups[2]["stages"]["research"]["rates"]["verified_share"]
    assert latest["per_run"] == {"median": 0.15, "min": 0.1, "max": 0.2}
    # 3/20 pooled is far below 0.8, but two runs never raise a regression flag.
    assert wilson_interval(3, 20)[1] < 0.8
    assert groups[2]["regressions"] == [] and groups[1]["regressions"] == []
    assert (result["verdict"], result["exit_code"]) == ("clean", 0)

    # A third run of the same code and backbone: the pooled Wilson upper bound
    # (4/30) is below the aaa/glm point estimate (0.8) -> drift.
    runs.append(_run(base_card, "pipe_new2", 12, sha="bbb", verified=(1, 10), failures=(0, 20)))
    result = cli.aggregate(runs)
    latest = result["groups"][-1]
    assert _flags(latest) == [("research", "verified_share")]
    flag = latest["regressions"][0]
    assert flag["previous"] == 0.8 and flag["runs"] == 3 and flag["value"] == round(4 / 30, 4)
    assert flag["wilson"][1] < flag["previous"]
    # Lower-is-better: fewer tool failures (2/60 against 1/20) is never a regression.
    assert latest["stages"]["research"]["rates"]["tool_failure_rate"]["pooled"]["value"] == round(2 / 60, 4)
    assert (result["verdict"], result["exit_code"]) == ("drift", cli.EXIT_DRIFT)

    # ...while more failures is: the Wilson LOWER bound above the previous value.
    worse = [_run(base_card, f"pipe_bad{i}", 20 + i, sha="ccc", failures=(10, 20)) for i in range(3)]
    result = cli.aggregate(old + worse)
    assert _flags(result["groups"][-1]) == [("research", "tool_failure_rate")]
    assert result["groups"][-1]["regressions"][0]["better"] == "lower"

    # Contract failures of the current code win over drift (exit 1).
    failing = [_run(base_card, f"pipe_fail{i}", 20 + i, sha="ccc", verified=(1, 10),
                    passed={"report": False}) for i in range(3)]
    result = cli.aggregate(old + failing)
    latest = result["groups"][-1]
    assert ("report", "contract_pass_rate") in _flags(latest)
    assert ("research", "verified_share") in _flags(latest)
    assert latest["stages"]["report"]["contract"]["pass_rate"] == 0.0
    assert latest["contract_failures"][0] == {"pipeline_id": "pipe_fail0", "stage": "report",
                                              "failed": ["stage_status"]}
    assert (result["verdict"], result["exit_code"]) == ("contract_failures", 1)

    # A regression of an earlier sha is history: the current code decides (clean).
    recovered = [_run(base_card, f"pipe_ok{i}", 25 + i, sha="ddd") for i in range(3)]
    result = cli.aggregate(old + failing + recovered)
    assert _flags(result["groups"][1]) and result["groups"][2]["regressions"] == []
    assert result["exit_code"] == cli.EXIT_CLEAN

    # Inconclusive: more than 20% of the current code's scored stage verdicts are
    # unevaluable (2 of 6 stages in each run = 33%); exactly 1 of 6 is not.
    vague = [_run(base_card, f"pipe_vague{i}", 20 + i, sha="eee",
                  passed={"research": None, "report": None}) for i in range(3)]
    result = cli.aggregate(old + vague)
    assert result["groups"][-1]["unevaluable_share"] == round(6 / 18, 4)
    assert (result["verdict"], result["exit_code"]) == ("inconclusive", cli.EXIT_INCONCLUSIVE)
    assert result["groups"][-1]["stages"]["research"]["contract"]["unevaluable"] == 3
    result = cli.aggregate(old + [_run(base_card, "pipe_one", 20, sha="eee", passed={"research": None})])
    assert result["groups"][-1]["unevaluable_share"] == round(1 / 6, 4) and result["exit_code"] == 0
    # No run at all, or a pipeline that could not be scored, is never clean.
    assert cli.aggregate([])["exit_code"] == cli.EXIT_INCONCLUSIVE
    assert cli.aggregate([])["latest_group"] is None
    errors = [{"pipeline_id": "pipe_broken", "error": "ValueError: unreadable"}]
    assert cli.aggregate(old, errors=errors)["exit_code"] == cli.EXIT_INCONCLUSIVE
    # A run without created_at sorts as the oldest.
    result = cli.aggregate(old + [_run(base_card, "pipe_undated", None, sha="zzz")])
    assert result["groups"][0]["repo_git_sha"] == "zzz"
    assert result["groups"][0]["first_created_at"] is None


def _stopped_at_graph(base, pid, day, sha):
    """A run that failed at graph: only the research model is stamped, later stages not reached."""
    run = _run(base, pid, day, sha=sha, backbone={"research": dict(RESEARCH)}, passed={"graph": False})
    for stage in sc.STAGES[sc.STAGES.index("graph") + 1:]:
        run["card"]["stages"][stage]["status"] = sc.STAGE_NOT_REACHED
    return run


def test_aggregate_baseline_current_code_and_partial_backbones(base_card):
    """A regression compares the same backbone at another sha; the exit code judges every
    group of the newest run's sha; a run that stopped early joins the group it belongs to."""
    # A change of model alone never raises a flag: no earlier kimi group to compare with.
    glm = [_run(base_card, f"pipe_glm{i}", 1 + i, verified=(8, 10)) for i in range(5)]
    kimi = [_run(base_card, f"pipe_kimi{i}", 10 + i, backbone="kimi", verified=(1, 10)) for i in range(3)]
    result = cli.aggregate(glm + kimi)
    assert [g["compared_to"] for g in result["groups"]] == [None, None]
    assert result["groups"][1]["regressions"] == [] and result["exit_code"] == cli.EXIT_CLEAN
    # The same backbone at the next sha is compared with its own earlier group, not the
    # other model's: aaa/glm 0.8, aaa/kimi 0.3, bbb/glm pooled 105/300 = 0.35 -> drift.
    probe = glm + [_run(base_card, "pipe_kimi", 6, backbone="kimi", verified=(3, 10))]
    probe += [_run(base_card, f"pipe_b{i}", 20 + i, sha="bbb", verified=(35, 100)) for i in range(3)]
    result = cli.aggregate(probe)
    groups = result["groups"]
    assert [(g["repo_git_sha"], g["backbone"]["report"]["provider"]) for g in groups] == [
        ("aaa", "glm"), ("aaa", "kimi"), ("bbb", "glm")]
    assert groups[2]["compared_to"] == 0 and _flags(groups[2]) == [("research", "verified_share")]
    assert (groups[2]["regressions"][0]["previous"], groups[2]["regressions"][0]["value"]) == (0.8, 0.35)
    assert (result["verdict"], result["exit_code"]) == ("drift", cli.EXIT_DRIFT)
    # A group without a known backbone is never compared.
    unnamed = [_run(base_card, f"pipe_nobb{i}", 26 + i, sha="ccc", backbone=None, verified=(1, 10))
               for i in range(3)]
    result = cli.aggregate(probe + unnamed)
    assert (result["groups"][-1]["backbone"], result["groups"][-1]["compared_to"]) == (None, None)
    assert result["exit_code"] == cli.EXIT_CLEAN

    # Overlapping groups: (xxx, glm) ran on days 1 and 20 and its day-20 run fails a
    # contract; (xxx, kimi) ran once on day 2.  The group holding the newest run is the
    # latest, and every backbone of the newest run's sha is judged.
    overlap = [_run(base_card, "pipe_x_glm_1", 1, sha="xxx"),
               _run(base_card, "pipe_x_kimi", 2, sha="xxx", backbone="kimi"),
               _run(base_card, "pipe_x_glm_20", 20, sha="xxx", passed={"report": False})]
    result = cli.aggregate(overlap)
    assert [g["pipelines"] for g in result["groups"]] == [["pipe_x_kimi"], ["pipe_x_glm_1", "pipe_x_glm_20"]]
    assert result["latest_group"] == 1 and result["current"]["groups"] == [0, 1]
    assert (result["verdict"], result["exit_code"]) == ("contract_failures", 1)
    # A failure under another backbone of the current code counts; an older sha's never does.
    older = _run(base_card, "pipe_w_glm", 1, sha="www", passed={"report": False})
    clean = _run(base_card, "pipe_x_glm", 3, sha="xxx")
    result = cli.aggregate([older, _run(base_card, "pipe_x_kimi", 2, sha="xxx", backbone="kimi",
                                        passed={"report": False}), clean])
    assert result["current"] == {"repo_git_sha": "xxx", "groups": [1, 2], "unevaluable_share": 0.0}
    assert result["exit_code"] == cli.EXIT_CONTRACT_FAILURES
    assert cli.aggregate([older, clean])["exit_code"] == cli.EXIT_CLEAN

    # Partial backbone: a run that failed at graph on day 1 stamped only its research
    # model; it joins the group of its sha whose backbone agrees on every stamped stage.
    stopped = _stopped_at_graph(base_card, "pipe_graph_fail", 1, "xxx")
    done = [_run(base_card, f"pipe_done{i}", 5 + i, sha="xxx") for i in range(3)]
    result = cli.aggregate([stopped] + done)
    (group,) = result["groups"]
    assert group["pipelines"] == ["pipe_graph_fail", "pipe_done0", "pipe_done1", "pipe_done2"]
    assert group["partial_backbone_runs"] == ["pipe_graph_fail"] and group["ambiguous_backbone"] is False
    assert group["backbone"]["report"]["provider"] == "glm"
    assert group["stages"]["graph"]["contract"]["failed"] == 1 and group["stages"]["report"]["runs"] == 3
    assert (result["verdict"], result["exit_code"]) == ("contract_failures", 1)
    # A run whose run.json names no model joins its sha's only group as well.
    lone = _run(base_card, "pipe_unnamed", 2, sha="xxx", backbone=None)
    assert cli.aggregate(done + [lone])["groups"][0]["partial_backbone_runs"] == ["pipe_unnamed"]
    # When the stages it never reached are what tells two groups apart (glm and kimi
    # share the research model), it keeps a group of its own, still judged as current.
    result = cli.aggregate([stopped] + done + [_run(base_card, "pipe_kimi_done", 8, sha="xxx",
                                                    backbone="kimi")])
    assert [(g["pipelines"], g["ambiguous_backbone"]) for g in result["groups"]] == [
        (["pipe_graph_fail"], True), (["pipe_done0", "pipe_done1", "pipe_done2"], False),
        (["pipe_kimi_done"], False)]
    assert result["groups"][0]["backbone"] == {"research": RESEARCH}
    assert result["current"]["groups"] == [0, 1, 2]
    assert result["exit_code"] == cli.EXIT_CONTRACT_FAILURES


def _pipeline(pid, created, sha, *, status="completed", **pipeline):
    state = ts._make_pipeline(pid, status=status, **pipeline)
    state.created_at = created
    po.PipelineManager.save(state)
    ts._write(po.PipelineManager.manifest_path(pid), {
        "repo_git_sha": sha, "resolved": {"research": {"model": "glm"},
                                          "report": {"provider": "glm", "model_name": "glm-5.3"}}})


def test_aggregate_cli_groups_existing_runs_offline(roots, capsys, monkeypatch):
    def no_network(*_args, **_kwargs):
        raise AssertionError("the aggregate is offline")

    monkeypatch.setattr(socket, "create_connection", no_network)
    _pipeline("pipe_eval16a", "2026-09-01T08:00:00+00:00", "sha_old")
    _pipeline("pipe_eval16b", "2026-09-20T08:00:00+00:00", "sha_new")
    _pipeline("pipe_eval16c", "2026-09-21T09:30:00", "sha_new")  # naive: read as UTC
    _pipeline("pipe_eval16run", "2026-09-22T08:00:00+00:00", "sha_new", status="running")
    # A cancelled run was stopped by its user: skipped, never scored.
    _pipeline("pipe_eval16cancel", "2026-09-22T09:00:00+00:00", "sha_new", status="cancelled",
              stage_status={"report": "cancelled"})

    assert cli.main(["aggregate"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert [(g["repo_git_sha"], g["pipelines"]) for g in result["groups"]] == [
        ("sha_old", ["pipe_eval16a"]), ("sha_new", ["pipe_eval16b", "pipe_eval16c"])]
    assert result["groups"][1]["backbone"] == {"report": {"provider": "glm", "model_name": "glm-5.3"},
                                               "research": {"model": "glm"}}
    assert result["skipped"] == [{"pipeline_id": "pipe_eval16cancel", "reason": "cancelled"},
                                 {"pipeline_id": "pipe_eval16run", "reason": "status 'running'"}]
    assert result["groups"][1]["compared_to"] == 0 and result["verdict"] == "clean"
    assert result["groups"][1]["last_created_at"] == "2026-09-21T09:30:00+00:00"
    assert not os.path.exists(cli.aggregate_path())
    assert not os.path.exists(sc.sidecar_path("pipe_eval16a"))  # the aggregate writes no sidecar

    assert cli.main(["aggregate", "--since", "2026-09-20", "-o"]) == 0
    out = capsys.readouterr()
    result = json.loads(out.out)
    assert result["since"] == "2026-09-20" and result["count"] == 2
    assert [g["repo_git_sha"] for g in result["groups"]] == ["sha_new"]
    assert {"pipeline_id": "pipe_eval16a", "reason": "created before --since"} in result["skipped"]
    with open(cli.aggregate_path(), encoding="utf-8") as handle:
        assert json.load(handle) == result
    assert "wrote" in out.err

    # Exit 2 is the drift verdict, so an aggregate usage error exits 64 (EX_USAGE).
    for argv in (["aggregate", "--since", "last week"], ["aggregate", "--bogus"]):
        with pytest.raises(SystemExit) as excinfo:
            cli.main(argv)
        assert excinfo.value.code == cli.EXIT_AGGREGATE_USAGE == 64
        captured = capsys.readouterr()
        assert captured.out == "" and "usage:" in captured.err
    with pytest.raises(SystemExit) as excinfo:  # the score command keeps argparse's 2
        cli.main(["score", "--bogus"])
    assert excinfo.value.code == 2
    capsys.readouterr()

    # A failed -o write: the aggregate is still printed and the error goes to stderr;
    # a clean verdict exits 4, any other verdict keeps its own code.
    def no_disk(*_args, **_kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(cli, "write_json_atomic", no_disk)
    assert cli.main(["aggregate", "-o"]) == cli.EXIT_WRITE_FAILED
    out = capsys.readouterr()
    assert json.loads(out.out)["verdict"] == "clean" and "disk full" in out.err
    _pipeline("pipe_eval16fail", "2026-09-23T08:00:00+00:00", "sha_new", status="failed",
              stage_status={"report": "failed"})
    assert cli.main(["aggregate", "-o"]) == cli.EXIT_CONTRACT_FAILURES
    out = capsys.readouterr()
    assert json.loads(out.out)["verdict"] == "contract_failures" and "disk full" in out.err
