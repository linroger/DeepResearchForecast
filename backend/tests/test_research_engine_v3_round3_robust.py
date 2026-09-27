"""Review round 3 regressions of the deep-research engine v3: robustness,
degradation reporting and configuration (cluster "engine robust").

C3 a run no model call contributed to (the provider never answered) fails
resumably with ``provider_unavailable: no model output`` instead of publishing
a deterministic report; content-filter refusals of every call publish flagged,
and an empty actor list on an actor-enabled run is a degradation event.  C4 no
sourced evidence after gathering fails resumably (``evidence_unavailable``,
with the tool failure counts); partial tool failures are degradation events.
C5/C43 a template plan from a model outage, KIQs ended in deterministic notes
and KIQs or follow-ups never researched are degradation events.  C28 one
agent's exhausted provider ladder keeps what it read (retryable ``provider``
notes) and fails resumably while fewer than half of the planned KIQs have
notes their agent wrote.  C8 follow-ups a provider failure interrupted keep
the gap phase resumable and are researched on resume.  C9 SIGINT during a
fan-out starts no queued job and no new paid call; SIGTERM leaves
``meta.status`` terminal (``terminated``) and the progress log closed.  C7
the lease wait is bounded by the call's deadline and ends for the run after
the first capacity timeout.  C45 ``ACTOR_CAST_MAX`` follows the bridge
(0 = no cap, explicit values unclamped, invalid = default) and the cast is cut
by rank, not by emission order.  C46 every ``RESEARCH_LINEAR_*`` knob the
engine reads is documented in ``.env.example``.

Offline and deterministic: the fakes, fixtures and harness of
``test_research_engine_v3`` (scripted model, injected search/fetch, the real
bridge module with prediction markets and charts stubbed), injected clocks.
The two signal tests run the engine in a child process (a real signal must
not reach the pytest process) and use generous wall-clock bounds.
"""

from __future__ import annotations

import json
import os
import re
import signal
import subprocess
import sys
import textwrap
import threading
import types
from contextlib import contextmanager
from pathlib import Path

import pytest

import test_research_engine_v3 as v3

# The shared fixtures (hermetic env, real bridge with network steps stubbed).
_hermetic_env = v3._hermetic_env
bridge = v3.bridge
lr = v3.lr
rg = v3.rg
dr = v3.dr

QUESTION = "Will global data-centre capacity exceed 250 GW by the end of 2027?"
FILTERED = Exception("Error code: 400 - {'error': {'code': '1301', 'message': "
                     "'系统检测到输入或生成内容可能包含不安全或敏感内容'}}")


class APIConnectionError(Exception):
    """Same class name as openai.APIConnectionError (classified transient)."""


class BaseChatOpenAI:
    """Name-only marker: detect_profile binds a per-call timeout for it."""


class FakeTime:
    """One injected monotonic clock for the gateway (latency, backoff) and,
    through it, the run deadline."""

    def __init__(self) -> None:
        self.now = 0.0
        self._lock = threading.Lock()

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        with self._lock:
            self.now += float(seconds)


class HangingModel(v3.ScriptedModel, BaseChatOpenAI):
    """A provider that never answers: every call (primes included) waits out
    its deadline-clipped timeout and then times out."""

    def __init__(self, clock: FakeTime) -> None:
        super().__init__(lambda call: None)
        self.clock = clock

    def invoke(self, messages):
        self.clock.advance(self.bound.get("timeout") or 600)
        raise TimeoutError("Request timed out.")


class SlowModel(v3.ScriptedModel):
    """The scripted world, each call taking ``latency`` seconds of fake time."""

    def __init__(self, responder, clock: FakeTime, latency: float) -> None:
        super().__init__(responder)
        self.clock = clock
        self.latency = latency

    def invoke(self, messages):
        self.clock.advance(self.latency)
        return super().invoke(messages)


def run(tmp_path: Path, bridge, world=None, *, model=None, depth: str = "standard", out_dir: Path | None = None,
        gateway: dict | None = None, search=None, fetch=None):
    """``v3.run_engine`` with gateway options (clock, sleep, lease) and tools."""
    out_dir = out_dir or (tmp_path / "out")
    out_dir.mkdir(parents=True, exist_ok=True)
    model = model or v3.ScriptedModel(world)
    plog = v3.FakePlog()
    meta = {"status": "running", "question": QUESTION, "research_engine": "v3"}

    def write_meta():
        (out_dir / "meta.json").write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")

    def gateway_factory(args, plog_arg, bridge_arg, preset):
        options = {"sleep": lambda seconds: None, **(gateway or {})}
        return rg.ModelGateway(model, plog_arg, max_concurrency=preset.workers, budget_units=preset.budget_units,
                               reserve_share=lr.RESERVE_SHARE, **options)

    def tools_factory(ledger, pages_dir, bridge_arg, plog_arg, limits):
        return rg.ResearchTools(ledger, pages_dir, search_fn=search or v3.fake_search, fetch_fn=fetch or v3.page_text,
                                bridge=bridge_arg, plog=plog_arg, limits=limits)

    rc = lr.run(QUESTION, out_dir, v3.make_args(depth), meta, plog, write_meta, bridge=bridge,
                gateway_factory=gateway_factory, tools_factory=tools_factory)
    return rc, meta, plog, model, out_dir


def state_of(out: Path) -> dict:
    return json.loads((out / "v3" / "state.json").read_text(encoding="utf-8"))


def agent_kiqs(model) -> list[str]:
    return [re.search(r"Investigate (\S+):", c["messages"][2][1]).group(1) for c in v3.calls_of(model, "agent")]


def events_of(meta: dict) -> list[str]:
    return list((meta.get("research_quality") or {}).get("degradation") or [])


def fail_when(predicate, error):
    """A World ``fail`` hook raising ``error`` for the calls ``predicate`` picks."""
    def fail(call, role):
        return error if predicate(call, role) else None
    return fail


def agent_of(kid: str, *, after_reading: bool = False):
    def pick(call, role):
        if role != "agent" or f"Investigate {kid}:" not in call["messages"][2][1]:
            return False
        return not after_reading or any(kind == "tool" for kind, _ in call["messages"])
    return pick


# =============================================================== C3 no model output

def test_r3_a_provider_that_never_answers_fails_resumably_instead_of_publishing(tmp_path, bridge, monkeypatch):
    monkeypatch.setenv("DEERFLOW_RESEARCH_TIMEOUT", "900")
    monkeypatch.setenv("RESEARCH_LINEAR_WORKERS", "1")
    clock = FakeTime()
    out = tmp_path / "out"
    rc, meta, plog, _, _ = run(tmp_path, bridge, model=HangingModel(clock), depth="quick", out_dir=out,
                               gateway={"clock": clock, "sleep": clock.advance})
    assert rc == 2 and meta["status"] == "failed"
    assert meta["error"].startswith("provider_unavailable: no model output")
    assert not (out / "research_report.md").exists()
    assert clock.now <= 0.85 * 900 + rg.MIN_CALL_SECONDS          # well before the watchdog
    state = state_of(out)
    assert state["phases"]["finalize"]["status"] == "failed"
    assert not {"gather", "gap", "synthesize", "qa"} & set(state["phases"]) and state["kiqs"] == {}
    assert lr.PLAN_OUTAGE_KEY in meta["plan_fallback"]

    # The provider is back: the resumed attempt plans and researches again.
    rc, meta, plog, model, _ = run(tmp_path, bridge, v3.World(), depth="quick", out_dir=out)
    assert rc == 0, meta.get("error")
    assert meta["plan_fallback"] == [] and len(v3.calls_of(model, "PLANNING TASK")) == 1
    assert sorted(set(agent_kiqs(model))) == ["K1", "K2", "K3", "K4"]
    assert "planning again" in plog.text()


def test_r3_model_output_of_an_earlier_attempt_still_counts(tmp_path, bridge, monkeypatch):
    """The whole run, not one attempt: notes the agents wrote in an earlier
    attempt are model output, so a resumed attempt whose own calls all time
    out publishes (flagged) instead of failing again."""
    monkeypatch.setenv("DEERFLOW_RESEARCH_TIMEOUT", "900")
    monkeypatch.setenv("RESEARCH_LINEAR_WORKERS", "1")
    out = tmp_path / "out"
    quota = fail_when(lambda call, role: role in ("SECTION WRITING TASK", "EXECUTIVE SUMMARY TASK"),
                      Exception("Error code: 429 - {'error': {'code': '1113', 'message': '余额不足'}}"))
    rc, meta, _, _, _ = run(tmp_path, bridge, v3.World(fail=quota), depth="quick", out_dir=out)
    assert rc == 2 and meta["error"].startswith("provider_unavailable: synthesis failed")

    clock = FakeTime()
    rc, meta, _, _, _ = run(tmp_path, bridge, model=HangingModel(clock), depth="quick", out_dir=out,
                            gateway={"clock": clock, "sleep": clock.advance})
    assert rc == 0, meta.get("error")
    assert meta["research_quality"]["degraded"] is True
    assert any("written by the deterministic fallback" in event for event in events_of(meta))


def test_r3_every_call_refused_by_the_content_filter_publishes_flagged(tmp_path, bridge):
    class FilteredWorld(v3.World):
        def __call__(self, call):
            if v3.role_of(call) == "prime":
                return super().__call__(call)
            raise FILTERED

    rc, meta, _, model, out = run(tmp_path, bridge, FilteredWorld(), depth="quick")
    assert rc == 0, meta.get("error")                        # the provider answered: publish, flagged
    assert (out / "research_report.md").is_file()
    events = events_of(meta)
    assert meta["research_quality"]["degraded"] is True
    refused = [e for e in events if e.startswith("the provider's content filter refused every model call")]
    assert len(refused) == 1 and re.search(r"\((\d+) refused\)", refused[0])
    assert ("4 of 4 KIQ investigations ended in deterministic notes: K1 (content_filter), K2 (content_filter), "
            "K3 (content_filter), K4 (content_filter)") in events
    assert "actor extraction failed and the plan names no actors: the actor list is empty" in events
    assert json.loads((out / "actors.json").read_text(encoding="utf-8"))["actors"] == []


def test_r3_a_healthy_run_has_no_research_degradation_events(tmp_path, bridge):
    rc, meta, _, _, _ = run(tmp_path, bridge, v3.World(gap_followups=True))
    assert rc == 0 and "degraded" not in meta["research_quality"]


# =============================================================== C4 no sourced evidence

def _search_down(query, n):
    raise ConnectionError("tavily: connection refused")


def _fetch_down(url):
    raise ConnectionError("jina: connection refused")


def test_r3_no_sourced_evidence_fails_resumably_before_synthesis(tmp_path, bridge):
    out = tmp_path / "out"
    rc, meta, _, model, _ = run(tmp_path, bridge, v3.World(), depth="quick", out_dir=out,
                                search=_search_down, fetch=_fetch_down)
    assert rc == 2 and meta["status"] == "failed"
    match = re.fullmatch(r"evidence_unavailable: no sourced evidence after gathering "
                         r"\((\d+) of (\d+) searches and (\d+) of (\d+) fetches failed\)", meta["error"])
    assert match and int(match.group(1)) == int(match.group(2)) > 0
    assert not v3.calls_of(model, "SECTION WRITING TASK") and not (out / "research_report.md").exists()
    state = state_of(out)
    assert state["phases"]["gather"]["status"] == "failed" and state["kiqs"] == {}

    # Search is back: every KIQ is researched again, the plan is reused.
    rc, meta, _, model, _ = run(tmp_path, bridge, v3.World(), depth="quick", out_dir=out)
    assert rc == 0, meta.get("error")
    assert not v3.calls_of(model, "PLANNING TASK")
    assert sorted(set(agent_kiqs(model))) == ["K1", "K2", "K3", "K4"]
    assert meta["kiqs"]["facts"] > 0 and (out / "research_report.md").is_file()


def test_r3_partial_tool_failures_are_degradation_events(tmp_path, bridge):
    lock = threading.Lock()
    failed = {"searches": 0}

    def flaky_search(query, n):
        with lock:
            failed["searches"] += 1
            broken = failed["searches"] <= 2
        if broken:
            raise ConnectionError("search provider: HTTP 502")
        return v3.fake_search(query, n)

    rc, meta, _, _, _ = run(tmp_path, bridge, v3.World(), depth="quick", search=flaky_search, fetch=_fetch_down)
    assert rc == 0, meta.get("error")
    events = events_of(meta)
    searches, fetches = meta["tools"]["searches"], meta["tools"]["fetches"]
    assert f"2 of {searches} searches failed" in events
    assert fetches > 0 and f"{fetches} of {fetches} page fetches failed" in events


# =============================================================== C5 / C43 degradation events

def test_r3_a_template_plan_from_a_model_outage_is_flagged(tmp_path, bridge):
    down = fail_when(lambda call, role: role in ("SCOPE TASK", "PLANNING TASK"),
                     APIConnectionError("Connection error."))
    rc, meta, _, _, _ = run(tmp_path, bridge, v3.World(fail=down), depth="quick")
    assert rc == 0 and lr.PLAN_OUTAGE_KEY in meta["plan_fallback"]
    assert ("research plan built from the deterministic templates: the model was unavailable during planning"
            in events_of(meta))


def test_r3_kiqs_ended_in_deterministic_notes_are_flagged_with_their_reasons(tmp_path, bridge):
    rc, meta, _, _, _ = run(tmp_path, bridge, v3.World(fail=fail_when(agent_of("K2"), FILTERED)))
    assert rc == 0
    assert "1 of 4 KIQ investigations ended in deterministic notes: K2 (content_filter)" in events_of(meta)


def test_r3_planned_kiqs_a_provider_failure_left_unresearched_are_flagged(tmp_path, bridge, monkeypatch):
    monkeypatch.setenv("RESEARCH_LINEAR_WORKERS", "1")
    down = fail_when(agent_of("K4"), APIConnectionError("Connection error."))
    rc, meta, _, _, _ = run(tmp_path, bridge, v3.World(fail=down))
    assert rc == 0, meta.get("error")
    assert meta["phases"]["gather"]["status"] == "partial" and meta["phases"]["gather"]["detail"] == "missing K4"
    assert "1 of 4 planned KIQs not researched: K4" in events_of(meta)


def test_r3_follow_ups_of_a_complete_verdict_are_not_counted_as_kiqs(tmp_path, bridge):
    class CompleteWithListWorld(v3.World):
        def gap(self, call):
            return v3.ai(json.dumps({"verdict": "complete", "follow_ups": [
                {"question": "How fast are interconnection approvals in Europe and Asia?", "queries": ["x"]}]}))

    rc, meta, _, model, _ = run(tmp_path, bridge, CompleteWithListWorld())
    assert rc == 0 and meta["kiqs"]["followups"] == 0 and "degraded" not in meta["research_quality"]
    assert not any(kid.startswith("G") for kid in agent_kiqs(model))


# =============================================================== C28 one agent's exhausted ladder

def test_r3_an_exhausted_ladder_keeps_the_reads_and_fails_resumably_below_half(tmp_path, bridge, monkeypatch):
    monkeypatch.setenv("RESEARCH_LINEAR_WORKERS", "1")          # K3, K4 are queued behind K2
    out = tmp_path / "out"
    down = fail_when(agent_of("K2", after_reading=True), APIConnectionError("Connection error."))
    rc, meta, _, model, _ = run(tmp_path, bridge, v3.World(fail=down), out_dir=out)
    assert rc == 2
    assert meta["error"].startswith("provider_unavailable: gather researched only 1 of 4 planned KIQs "
                                    "before a provider failure")
    assert sorted(set(agent_kiqs(model))) == ["K1", "K2"] and not v3.calls_of(model, "SECTION WRITING TASK")
    state = state_of(out)
    assert state["phases"]["gather"]["status"] == "failed"
    assert state["kiqs"]["K2"]["fallback"] == "provider" and "K3" not in state["kiqs"]
    k2 = json.loads((out / "v3" / "kiq" / "K2.json").read_text(encoding="utf-8"))
    assert k2["stats"]["fallback"] == "provider" and k2["stats"]["fetched"]
    assert k2["facts"] and {f["tag"] for f in k2["facts"]} == {"REPORTED"}

    rc, meta, _, model, _ = run(tmp_path, bridge, v3.World(), out_dir=out)
    assert rc == 0, meta.get("error")
    assert sorted(set(agent_kiqs(model))) == ["K2", "K3", "K4"]
    assert json.loads((out / "v3" / "kiq" / "K2.json").read_text(encoding="utf-8"))["stats"]["fallback"] is None
    assert meta["phases"]["gather"]["status"] == "done"


def test_r3_an_exhausted_ladder_with_half_the_kiqs_written_publishes_flagged(tmp_path, bridge, monkeypatch):
    monkeypatch.setenv("RESEARCH_LINEAR_WORKERS", "1")
    down = fail_when(agent_of("K4", after_reading=True), APIConnectionError("Connection error."))
    rc, meta, plog, _, out = run(tmp_path, bridge, v3.World(fail=down))
    assert rc == 0, meta.get("error")
    assert meta["phases"]["gather"]["status"] == "partial"
    assert meta["phases"]["gather"]["detail"] == "deterministic notes K4"
    assert "1 of 4 KIQ investigations ended in deterministic notes: K4 (provider)" in events_of(meta)
    assert "provider failure during gather" in plog.text()


# =============================================================== C8 gap follow-ups

class _GapWorld(v3.World):
    def __init__(self, *, follow_ups_down: bool = False, review_down: bool = False,
                 writers_down: bool = False) -> None:
        super().__init__(gap_followups=True)
        self.follow_ups_down, self.review_down, self.writers_down = follow_ups_down, review_down, writers_down

    def __call__(self, call):
        role = v3.role_of(call)
        if ((self.follow_ups_down and role == "agent" and "Investigate G1F" in call["messages"][2][1])
                or (self.review_down and role == "GAP REVIEW TASK")
                or (self.writers_down and role == "SECTION WRITING TASK")):
            raise APIConnectionError("Connection error.")
        return super().__call__(call)


def test_r3_follow_ups_a_provider_failure_interrupted_are_researched_on_resume(tmp_path, bridge):
    out = tmp_path / "out"
    rc, meta, _, _, _ = run(tmp_path, bridge, _GapWorld(follow_ups_down=True, writers_down=True), out_dir=out)
    assert rc == 2 and meta["error"].startswith("provider_unavailable: synthesis failed")
    gap = state_of(out)["phases"]["gap"]
    assert gap["status"] == "partial" and "provider failure" in gap["detail"]

    rc, meta, _, model, _ = run(tmp_path, bridge, _GapWorld(), out_dir=out)
    assert rc == 0, meta.get("error")
    assert "G1F1" in agent_kiqs(model) and not v3.calls_of(model, "GAP REVIEW TASK")  # review reused
    assert meta["kiqs"]["completed"] == 5 and state_of(out)["phases"]["gap"]["status"] == "done"


def test_r3_a_gap_review_a_provider_failure_stopped_runs_on_resume(tmp_path, bridge):
    out = tmp_path / "out"
    rc, _, _, _, _ = run(tmp_path, bridge, _GapWorld(review_down=True, writers_down=True), out_dir=out)
    assert rc == 2 and state_of(out)["phases"]["gap"]["status"] == "partial"

    rc, meta, _, model, _ = run(tmp_path, bridge, _GapWorld(), out_dir=out)
    assert rc == 0, meta.get("error")
    assert len(v3.calls_of(model, "GAP REVIEW TASK")) == 1 and "G1F1" in agent_kiqs(model)


def test_r3_a_gap_round_a_provider_failure_ended_is_flagged(tmp_path, bridge):
    rc, meta, _, _, _ = run(tmp_path, bridge, _GapWorld(follow_ups_down=True))
    assert rc == 0, meta.get("error")
    events = events_of(meta)
    assert "1 of 1 gap follow-up KIQs not researched: G1F1" in events
    assert "gap review ended early (stopped after round 1: provider failure (ProviderUnavailable))" in events


# =============================================================== C9 interrupts

_REPO = Path(__file__).resolve().parents[2]

_CHILD_PRELUDE = textwrap.dedent("""
    import json, os, re, signal, sys, time
    from pathlib import Path
    sys.path[:0] = [{backend!r}, {bridge!r}, {tests!r}]
    os.environ["DRF_TEST_PROCESS"] = "1"
    import test_research_engine_v3 as v3
    lr, rg, dr = v3.lr, v3.rg, v3.dr
    dr._collect_prediction_markets = lambda *args, **kwargs: None
    dr._render_research_charts = lambda *args, **kwargs: {{}}
    engines = []
    _init = lr._Engine.__init__

    def _record(self, *args, **kwargs):
        _init(self, *args, **kwargs)
        engines.append(self)

    lr._Engine.__init__ = _record
    seen = {{"agents": [], "after_stop": 0, "fired": False}}

    def stopped():
        return bool(engines) and getattr(engines[0], "cancelled", False)

    class World(v3.World):
        def plan(self, call):
            plan = json.loads(super().plan(call).content.split("```json\\n")[1].split("\\n```")[0])
            plan["kiqs"] = [{{"question": f"Question {{i}} about capacity topic {{i}}?",
                              "queries": [f"q{{i}} capacity"], "kind": "general"}} for i in range(1, 9)]
            return v3.ai("```json\\n" + json.dumps(plan) + "\\n```")

        def __call__(self, call):
            if stopped():
                seen["after_stop"] += 1
            if v3.role_of(call) == "agent":
                seen["agents"].append(re.search(r"Investigate (\\S+):", call["messages"][2][1]).group(1))
                if not seen["fired"]:
                    seen["fired"] = True
                    os.kill(os.getpid(), SIGNAL)   # while this call is in flight
                    limit = time.monotonic() + 20
                    while not stopped() and time.monotonic() < limit:
                        time.sleep(0.01)
            return super().__call__(call)

    os.environ.update(RESEARCH_LINEAR_WORKERS="1", RESEARCH_LINEAR_MAX_KIQS="8")
    out = Path(sys.argv[1])
""").format(backend=str(_REPO / "backend"), bridge=str(_REPO / "deerflow_bridge"),
            tests=str(_REPO / "backend" / "tests"))


def _child(tmp_path: Path, body: str, out: Path) -> tuple[subprocess.CompletedProcess, dict]:
    script = tmp_path / "child.py"
    script.write_text(_CHILD_PRELUDE + textwrap.dedent(body), encoding="utf-8")
    proc = subprocess.run([sys.executable, str(script), str(out)], capture_output=True, text=True,
                          timeout=240, env=dict(os.environ), cwd=str(_REPO / "backend"))
    lines = [line for line in proc.stdout.splitlines() if line.startswith("RESULT ")]
    assert lines, proc.stdout[-2000:] + proc.stderr[-4000:]
    return proc, json.loads(lines[-1][len("RESULT "):])


def test_r3_sigint_during_a_fan_out_starts_no_queued_kiq_and_no_new_call(tmp_path):
    out = tmp_path / "run"
    proc, result = _child(tmp_path, """
        import atexit
        SIGNAL = signal.SIGINT
        result = {}

        def report():  # at exit: after every worker thread has finished
            result.update(seen, meta=json.loads((out / "out" / "meta.json").read_text()),
                          kiq_files=sorted(p.stem for p in (out / "out" / "v3" / "kiq").glob("*.json")))
            print("RESULT " + json.dumps(result), flush=True)

        atexit.register(report)
        try:
            v3.run_engine(out, dr, World(), depth="quick")
            result["raised"] = None
        except KeyboardInterrupt:
            result["raised"] = "KeyboardInterrupt"
        result["sigint_restored"] = signal.getsignal(signal.SIGINT) is signal.default_int_handler
    """, out)
    assert proc.returncode == 0, proc.stderr[-4000:]
    assert result["raised"] == "KeyboardInterrupt"
    assert result["agents"] == ["K1"] and result["after_stop"] == 0   # K2..K8 never started
    assert result["kiq_files"] == []                                    # nothing persisted after the stop
    assert result["meta"]["status"] == "failed"
    assert result["meta"]["error"] == "v3 engine interrupted: KeyboardInterrupt"
    assert result["sigint_restored"] is True


def test_r3_sigterm_leaves_a_terminal_status_and_a_closed_progress_log(tmp_path):
    out = tmp_path / "handoff"
    proc, result = _child(tmp_path, """
        SIGNAL = signal.SIGTERM
        os.environ.update(RESEARCH_ENGINE="v3", MINIMAX_API_KEY="test-key-not-used")
        model = v3.ScriptedModel(World())
        lr._default_gateway_factory = lambda args, plog, bridge, preset: rg.ModelGateway(
            model, plog, max_concurrency=preset.workers, budget_units=preset.budget_units,
            reserve_share=lr.RESERVE_SHARE, sleep=lambda seconds: None)
        lr._default_tools_factory = lambda ledger, pages, bridge, plog, limits: rg.ResearchTools(
            ledger, pages, search_fn=v3.fake_search, fetch_fn=v3.page_text, bridge=bridge, plog=plog,
            limits=limits)
        _close = dr.ProgressLog.close

        def close(self):
            _close(self)
            seen["plog_closed"] = self.closed

        dr.ProgressLog.close = close
        sys.argv = ["deerflow_research.py", "--model", "minimax", "--depth", "quick", "--out-dir", str(out),
                    "--prompt", "Will global data-centre capacity exceed 250 GW by the end of 2027?"]
        try:
            dr.main()
        finally:
            print("RESULT " + json.dumps(seen), flush=True)
    """, out)
    assert proc.returncode == 128 + signal.SIGTERM, proc.stderr[-4000:]
    meta = json.loads((out / dr.META_FILENAME).read_text(encoding="utf-8"))
    assert meta["status"] == "failed" and meta["error"] == "terminated" and meta["finished_at"]
    assert "[error] v3: terminated" in (out / dr.PROGRESS_FILENAME).read_text(encoding="utf-8")
    assert result["plog_closed"] is True
    assert result["agents"] == ["K1"] and result["after_stop"] == 0


def test_r3_stop_on_signals_is_a_no_op_off_the_main_thread():
    engine = types.SimpleNamespace(cancelled=False, cancel=lambda: None)
    box: dict = {}
    worker = threading.Thread(target=lambda: box.update(restore=lr._stop_on_signals(engine)))
    worker.start()
    worker.join()
    before = signal.getsignal(signal.SIGTERM)
    box["restore"]()
    assert signal.getsignal(signal.SIGTERM) is before


# =============================================================== C7 lease wait

@pytest.mark.parametrize("remaining, expected", [
    (None, 300), (1000.0, 300), (330.0, 300), (329.0, 270), (91.8, 60), (60.0, 30), (59.0, 1), (5.0, 1),
])
def test_r3_lease_wait_is_bounded_by_the_call_deadline(remaining, expected):
    deadline = None if remaining is None else rg.Deadline(remaining, lambda: 0.0)
    assert lr._lease_wait(300, deadline) == expected


def test_r3_a_saturated_envelope_costs_one_bounded_wait_and_the_run_ends_before_the_watchdog(
        tmp_path, bridge, monkeypatch):
    monkeypatch.setenv("DEERFLOW_RESEARCH_TIMEOUT", "900")
    monkeypatch.setenv("RESEARCH_LINEAR_WORKERS", "1")
    clock = FakeTime()
    env: dict[str, str] = {}
    waits: list[int] = []

    @contextmanager
    def saturated(weight=1):
        wait = int(env[lr.LEASE_WAIT_ENV])      # research_budget reads it as each wait begins
        waits.append(wait)
        clock.advance(wait)
        raise TimeoutError(f"timed out waiting {wait}s for research model capacity (1 requested, 4 global)")
        yield  # pragma: no cover

    plog = v3.FakePlog()
    lease = lr._bridge_lease(types.SimpleNamespace(_model_call_lease=saturated), lr._Reporter(plog), env)
    model = SlowModel(v3.World(), clock, latency=5.0)
    rc, meta, _, _, out = run(tmp_path, bridge, model=model, depth="quick",
                              gateway={"clock": clock, "sleep": clock.advance, "lease": lease})
    assert rc == 0, meta.get("error")
    plan_share = lr.PHASE_TIME_SHARE["plan"] * 0.85 * 900
    assert waits == [int((plan_share - rg.MIN_CALL_SECONDS) // lr.LEASE_WAIT_STEP_S) * lr.LEASE_WAIT_STEP_S]
    assert clock.now < 0.85 * 900 + rg.MIN_CALL_SECONDS < 900
    assert v3.calls_of(model, "SCOPE TASK") and v3.calls_of(model, "SECTION WRITING TASK")
    assert meta["plan_fallback"] == [] and (out / "research_report.md").is_file()
    assert len([m for m in plog.of("warn") if "for the rest of the run" in m]) == 1


def test_r3_the_lease_accepts_the_gateway_deadline_hook():
    lease = lr._bridge_lease(types.SimpleNamespace(_model_call_lease=lambda weight=1: _nothing()),
                             lr._Reporter(None), {})
    assert rg._accepts_keyword(lease, "deadline")


@contextmanager
def _nothing():
    yield


# =============================================================== C45 ACTOR_CAST_MAX

@pytest.mark.parametrize("raw", [None, "", "  ", "0", "-3", "20", " 15 ", "+7", "80", "200", "inf", "nan",
                                 "20.5", "1e3", "soon", "5000 nines"])
def test_r3_actor_cast_max_is_read_exactly_as_the_bridge_reads_it(raw, monkeypatch):
    raw = "9" * 5000 if raw == "5000 nines" else raw        # past int()'s digit limit: invalid
    env = {} if raw is None else {"ACTOR_CAST_MAX": raw}
    if raw is None:
        monkeypatch.delenv("ACTOR_CAST_MAX", raising=False)
    else:
        monkeypatch.setenv("ACTOR_CAST_MAX", raw)
    assert lr.actor_cast_max(env) == dr._actor_cast_max()


class CastWorld(v3.World):
    """25 extracted actors; the five principal (tier 1) actors come last."""

    def actors(self, call):
        payload = json.loads(super().actors(call).content)
        payload["actors"] = (
            [{"name": f"Stakeholder {i}", "type": "Organization", "influence": "low", "simulation_tier": 3}
             for i in range(20)]
            + [{"name": f"Principal {i}", "type": "Government", "influence": "high", "simulation_tier": 1}
               for i in range(5)])
        payload["relationships"] = [{"source": "Principal 0", "target": "Stakeholder 0", "type": "OPPOSES"}]
        return v3.ai(json.dumps(payload))


def _task(model, role: str) -> str:
    return v3.calls_of(model, role)[0]["messages"][-1][1]


def test_r3_actor_cast_max_zero_keeps_every_actor(tmp_path, bridge, monkeypatch):
    monkeypatch.setenv("ACTOR_CAST_MAX", "0")
    rc, meta, _, model, out = run(tmp_path, bridge, CastWorld(), depth="quick")
    assert rc == 0, meta.get("error")
    actors = json.loads((out / "actors.json").read_text(encoding="utf-8"))["actors"]
    assert len(actors) == 25 and "actors_truncated_from" not in meta
    assert f"At most {lr.ACTOR_PROMPT_CEILING} actors" in _task(model, "ACTOR EXTRACTION TASK")
    assert f"up to {lr.ACTOR_PROMPT_CEILING} actors" in _task(model, "PLANNING TASK")


def test_r3_the_cast_is_cut_by_rank_not_by_emission_order(tmp_path, bridge):
    rc, meta, _, model, out = run(tmp_path, bridge, CastWorld(), depth="quick")
    assert rc == 0, meta.get("error")
    obj = json.loads((out / "actors.json").read_text(encoding="utf-8"))
    names = {a["name"] for a in obj["actors"]}
    assert len(names) == lr.DEFAULT_ACTOR_CAST and {f"Principal {i}" for i in range(5)} <= names
    assert meta["actors_truncated_from"] == 25 and len(obj["context_entities"]) == 5
    assert obj["relationships"] == [] or all(r["source"] in names and r["target"] in names
                                              for r in obj["relationships"])
    assert f"At most {lr.DEFAULT_ACTOR_CAST} actors" in _task(model, "ACTOR EXTRACTION TASK")


@pytest.mark.parametrize("raw, prompt_cap", [("80", 80), ("inf", lr.DEFAULT_ACTOR_CAST)])
def test_r3_explicit_or_invalid_caps_reach_the_prompts_unclamped(tmp_path, bridge, monkeypatch, raw, prompt_cap):
    monkeypatch.setenv("ACTOR_CAST_MAX", raw)
    rc, meta, _, model, _ = run(tmp_path, bridge, v3.World(), depth="quick")
    assert rc == 0, meta.get("error")
    assert f"At most {prompt_cap} actors" in _task(model, "ACTOR EXTRACTION TASK")
    assert f"up to {prompt_cap} actors" in _task(model, "PLANNING TASK")


def test_r3_plan_and_extraction_rows_follow_the_cap():
    rows = [{"name": f"Actor {i}", "type": "Organization"} for i in range(25)]
    assert len(lr.normalize_actor_rows(rows, 0)) == 25 and len(lr.normalize_actor_rows(rows, 7)) == 7
    assert len(lr._normalize_plan_actors(rows, 0)) == 25 and len(lr._normalize_plan_actors(rows, 7)) == 7


# =============================================================== C46 engine knobs documented

class _RecordingEnv(dict):
    """An empty environment that records every name read from it."""

    def __init__(self) -> None:
        super().__init__()
        self.read: set[str] = set()

    def get(self, key, default=None):
        self.read.add(key)
        return super().get(key, default)

    def __getitem__(self, key):
        self.read.add(key)
        return super().__getitem__(key)

    def __contains__(self, key):
        self.read.add(key)
        return super().__contains__(key)


def test_r3_every_engine_knob_is_documented_in_env_example():
    env = _RecordingEnv()
    lr.resolve_preset("deep", env)
    glm = types.SimpleNamespace(model_name="glm-5.3")
    rg.detect_profile(glm, env=env)
    knobs = {name for name in env.read if name.startswith("RESEARCH_LINEAR_")}
    assert {"RESEARCH_LINEAR_DIGEST_CAP", "RESEARCH_LINEAR_TIMEOUT_WRITE", "RESEARCH_LINEAR_GLM_EFFORT_AGENT",
            "RESEARCH_LINEAR_MAX_KIQS"} <= knobs
    documented = set(re.findall(r"^#?\s*([A-Z][A-Z0-9_]+)=", (_REPO / ".env.example").read_text(encoding="utf-8"),
                                re.M))
    assert sorted(knobs - documented) == []
