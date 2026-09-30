"""Golden tests for LLM telemetry / cache / budget (EXECPLAN2 I-7-3, guards I-5-0/I-6-0/I-5-3)."""

import pytest

from app.utils import telemetry as T


def test_meter_accumulates_by_stage_and_model():
    T.LLMMeter.reset("r")
    T.LLMMeter.record("minimax", "MiniMax-M3", 1000, 500, 100.0, stage="RESEARCH", run_id="r")
    T.LLMMeter.record("minimax", "MiniMax-M3", 2000, 800, 50.0, stage="REPORT", run_id="r")
    T.LLMMeter.record("minimax", "MiniMax-M3", 0, 0, 0.0, cached=True, stage="REPORT", run_id="r")
    snap = T.LLMMeter.snapshot("r")
    assert snap["total"]["calls"] == 3
    assert snap["total"]["cached"] == 1
    assert snap["total"]["total_tokens"] == 4300
    assert set(snap["by_stage"]) == {"RESEARCH", "REPORT"}
    assert snap["total"]["cost_usd"] > 0


def test_cache_put_get_and_key_stability():
    k1 = T.LLMCache.key("p", "m", [{"role": "user", "content": "hi"}], 0.7, 100, None)
    k2 = T.LLMCache.key("p", "m", [{"role": "user", "content": "hi"}], 0.7, 100, None)
    assert k1 == k2
    T.LLMCache.put(k1, "resp")
    assert T.LLMCache.get(k1) == "resp"
    assert T.LLMCache.get("missing") is None


def test_budget_guard(monkeypatch):
    from app.config import Config
    T.LLMMeter.reset("b")
    T.LLMMeter.record("minimax", "MiniMax-M3", 100, 100, 1.0, run_id="b")
    monkeypatch.setattr(Config, "LLM_RUN_BUDGET_TOKENS", 50, raising=False)
    with pytest.raises(T.BudgetExceeded):
        T.check_budget("b")
    monkeypatch.setattr(Config, "LLM_RUN_BUDGET_TOKENS", 0, raising=False)
    T.check_budget("b")  # unlimited -> no raise


def test_context_roundtrip():
    T.set_run_context("rid", "STAGE")
    assert T.get_run_context() == ("rid", "STAGE")
    T.set_stage("OTHER")
    assert T.get_run_context() == ("rid", "OTHER")
    # FOG-TEL-1: set_run_context now also registers the run as process-active (for
    # single-active-run fallback attribution). Clean up so "rid" doesn't linger as a
    # stale sole-active run and silently absorb other tests' unattributed records.
    T.set_run_context(None, None)
    # Assert on "rid" specifically, not an empty registry: in a full-suite run
    # other tests may legitimately hold active registrations of their own.
    assert "rid" not in T.active_run_ids()


# ---------------------------------------------------------------- OBS-1 tests
def test_cost_is_estimated_flags_proxy_and_unknown():
    # Proxy/aggregator-fronted + unlisted providers are estimates; published ones aren't.
    assert T.cost_is_estimated("gemini") is True
    assert T.cost_is_estimated("proxy") is True
    assert T.cost_is_estimated("antigravity") is True
    assert T.cost_is_estimated("totally-unknown-provider") is True
    assert T.cost_is_estimated("openai") is False
    assert T.cost_is_estimated("minimax") is False
    assert T.cost_is_estimated("claude-cli") is False


def test_gemini_cost_entry_present_and_nonzero():
    # OBS-1: gemini gets an (estimated) non-zero per-1K rate so the USD line is plausible.
    cost = T.estimate_cost("gemini", 1000, 1000)
    assert cost > 0


def test_snapshot_cost_estimated_flag():
    # Authoritative provider -> not estimated.
    T.LLMMeter.reset("est-no")
    T.LLMMeter.record("minimax", "MiniMax-M3", 1000, 500, 10.0, run_id="est-no")
    assert T.LLMMeter.snapshot("est-no")["cost_estimated"] is False

    # Proxy/gemini provider with real token volume -> estimated.
    T.LLMMeter.reset("est-yes")
    T.LLMMeter.record("gemini", "gemini-3.5-flash", 1000, 500, 10.0, run_id="est-yes")
    assert T.LLMMeter.snapshot("est-yes")["cost_estimated"] is True

    # Empty run snapshot also carries the flag (False) without raising.
    assert T.LLMMeter.snapshot("never-seen")["cost_estimated"] is False


def test_status_snapshot_shape():
    T.LLMMeter.reset("st")
    T.LLMMeter.record("minimax", "MiniMax-M3", 100, 100, 5.0, stage="REPORT", run_id="st")
    s = T.LLMMeter.status_snapshot("st")
    assert set(s) == {"run_id", "total", "by_stage", "cost_estimated"}
    assert "by_model" not in s  # compact: per-model breakdown omitted
    assert s["by_stage"]["REPORT"]["calls"] == 1
    assert s["total"]["total_tokens"] == 200


# ---------------------------------------------------------------- ITEM-18 tests
def test_cost_override_from_env(monkeypatch):
    # LLM_COST_PER_MTOK ($/Mtok) overrides/extends the built-in per-1K table.
    from app.config import Config
    # 7.0 $/Mtok in, 21.0 $/Mtok out -> $/1K = 0.007 / 0.021.
    monkeypatch.setattr(
        Config, "LLM_COST_PER_MTOK",
        '{"openai": [7.0, 21.0], "myprov": [1.0, 2.0]}', raising=False)
    # Override wins over the built-in openai (5.0/15.0) rate.
    assert T.estimate_cost("openai", 1000, 1000) == pytest.approx(0.007 + 0.021)
    # New provider absent from built-ins is now priced from the override.
    assert T.estimate_cost("myprov", 1000, 0) == pytest.approx(0.001)


def test_cost_override_empty_falls_back_to_builtin(monkeypatch):
    from app.config import Config
    monkeypatch.setattr(Config, "LLM_COST_PER_MTOK", "", raising=False)
    # Built-in minimax rate stays authoritative; unknown provider -> 0 (tokens only).
    assert T.estimate_cost("minimax", 1000, 1000) == pytest.approx(0.0003 + 0.0011)
    assert T.estimate_cost("no-such-provider-xyz", 5000, 5000) == 0.0


def test_cost_override_malformed_is_ignored(monkeypatch):
    from app.config import Config
    monkeypatch.setattr(Config, "LLM_COST_PER_MTOK", "{not valid json", raising=False)
    # Parse failure -> no override, behaves exactly as built-in default (degrade-safe).
    assert T.estimate_cost("minimax", 1000, 1000) == pytest.approx(0.0003 + 0.0011)


def test_build_stage_telemetry_merges_tokens_cost_and_walls():
    T.LLMMeter.reset("stg")
    T.LLMMeter.record("openai", "gpt", 1000, 500, 120.0, stage="research", run_id="stg")
    T.LLMMeter.record("openai", "gpt", 2000, 800, 80.0, stage="report", run_id="stg")
    # graph stage has wall time but zero LLM calls; run stage has neither here.
    tel = T.build_stage_telemetry("stg", {"research": 42.0, "graph": 5.5, "report": 10.0})
    stages = tel["by_stage"]
    # union of meter stages and wall stages.
    assert set(stages) == {"research", "graph", "report"}
    assert stages["research"] == {
        "calls": 1, "input_tokens": 1000, "output_tokens": 500,
        "est_cost_usd": pytest.approx(0.0050 * 1 + 0.0150 * 0.5),
        "wall_seconds": 42.0,
    }
    # wall-only stage: zero token/call, wall preserved.
    assert stages["graph"]["calls"] == 0
    assert stages["graph"]["input_tokens"] == 0
    assert stages["graph"]["wall_seconds"] == 5.5
    # totals sum across stages.
    assert tel["total"]["calls"] == 2
    assert tel["total"]["input_tokens"] == 3000
    assert tel["total"]["output_tokens"] == 1300
    assert tel["total"]["wall_seconds"] == pytest.approx(57.5)
    assert tel["total"]["est_cost_usd"] == pytest.approx(
        sum(s["est_cost_usd"] for s in stages.values()))


def test_build_stage_telemetry_empty_meter_wall_only_skeleton():
    T.LLMMeter.reset("stg-empty")
    tel = T.build_stage_telemetry("stg-empty", {"prepare": 3.0})
    assert tel["by_stage"]["prepare"] == {
        "calls": 0, "input_tokens": 0, "output_tokens": 0,
        "est_cost_usd": 0.0, "wall_seconds": 3.0,
    }
    assert tel["total"]["calls"] == 0
    # No stage_walls and empty meter -> empty by_stage (degrade-safe, no raise).
    tel2 = T.build_stage_telemetry("stg-empty", None)
    assert tel2["by_stage"] == {}
    assert tel2["total"]["wall_seconds"] == 0.0


def test_render_telemetry_appendix_deterministic_table():
    tel = {
        "by_stage": {
            "report": {"calls": 3, "input_tokens": 2000, "output_tokens": 800,
                       "est_cost_usd": 0.0221, "wall_seconds": 10.0},
            "research": {"calls": 1, "input_tokens": 1000, "output_tokens": 500,
                         "est_cost_usd": 0.0125, "wall_seconds": 42.0},
            "custom_stage": {"calls": 2, "input_tokens": 10, "output_tokens": 20,
                             "est_cost_usd": 0.0, "wall_seconds": 1.0},
        },
        "total": {"calls": 6, "input_tokens": 3010, "output_tokens": 1320,
                  "est_cost_usd": 0.0346, "wall_seconds": 53.0},
        "cost_estimated": False,
        "cost_basis": "api",
    }
    md = T.render_telemetry_appendix(tel)
    assert md.startswith("## Run Telemetry")
    lines = md.splitlines()
    # research (known order) precedes report (known order) precedes custom_stage (extra, appended).
    order = [i for i, ln in enumerate(lines)
             if ln.startswith("| research") or ln.startswith("| report")
             or ln.startswith("| custom_stage")]
    labels = [lines[i].split("|")[1].strip() for i in order]
    assert labels == ["research", "report", "custom_stage"]
    # thousands separators + TOTAL row present.
    assert "| 2,000 |" in md
    assert "**TOTAL**" in md
    assert "0.0346" in md


def test_render_telemetry_appendix_empty_returns_blank():
    assert T.render_telemetry_appendix(None) == ""
    assert T.render_telemetry_appendix({"by_stage": {}}) == ""


def test_render_telemetry_appendix_estimated_and_basis_footnote():
    tel = {
        "by_stage": {"run": {"calls": 1, "input_tokens": 5, "output_tokens": 5,
                             "est_cost_usd": 0.0, "wall_seconds": 2.0}},
        "total": {"calls": 1, "input_tokens": 5, "output_tokens": 5,
                  "est_cost_usd": 0.0, "wall_seconds": 2.0},
        "cost_estimated": True,
        "cost_basis": "subscription",
    }
    md = T.render_telemetry_appendix(tel)
    assert "rough estimate" in md
    assert "Cost basis: subscription" in md


# ---------------------------------------------------------------- R2-EXEC-6 tests
def test_http_client_disabled_by_default(monkeypatch):
    from app.config import Config
    from app.utils.llm_client import LLMClient
    # Unflagged / false -> None (keeps OpenAI SDK default client; degrade-safe).
    monkeypatch.setattr(Config, "LLM_HTTP2", False, raising=False)
    assert LLMClient._build_http_client() is None


def test_http_client_falls_back_to_http1_without_h2(monkeypatch):
    from app.config import Config
    from app.utils.llm_client import LLMClient
    monkeypatch.setattr(Config, "LLM_HTTP2", True, raising=False)
    monkeypatch.setattr(Config, "LLM_HTTP_KEEPALIVE", 128, raising=False)
    client = LLMClient._build_http_client()
    # With h2 absent, construction must still succeed (HTTP/1.1 fallback), not raise.
    assert client is not None
    try:
        # Generous read timeout so long generations aren't truncated at httpx's 5s default.
        assert client.timeout.read and client.timeout.read >= 120.0
    finally:
        client.close()


# ---------------------------------------------------------------- INFRA-2 tests
def test_cache_discard_removes_key_and_reports_missing():
    k1 = T.LLMCache.key("p", "m", [{"role": "user", "content": "discard"}], 0.0, 100, None)
    k2 = T.LLMCache.key("p", "m", [{"role": "user", "content": "keep"}], 0.0, 100, None)
    T.LLMCache.put(k1, "bad reply")
    T.LLMCache.put(k2, "good reply")

    assert T.LLMCache.discard(k1) is True
    assert T.LLMCache.get(k1) is None and k1 not in T.LLMCache._order
    assert T.LLMCache.get(k2) == "good reply" and k2 in T.LLMCache._order
    assert T.LLMCache.discard(k1) is False
    assert T.LLMCache.discard("never-cached") is False
    # A re-put after a discard is tracked once in the FIFO order again.
    T.LLMCache.put(k1, "fresh reply")
    assert T.LLMCache._order.count(k1) == 1 and T.LLMCache.get(k1) == "fresh reply"


def test_snapshot_has_no_structured_outputs_until_one_is_recorded():
    T.LLMMeter.reset("so")
    try:
        T.LLMMeter.record("minimax", "MiniMax-M3", 10, 5, 1.0, stage="graph", run_id="so")
        assert "structured_outputs" not in T.LLMMeter.snapshot("so")
        assert "structured_outputs_by_stage" not in T.LLMMeter.snapshot("so")
        assert "structured_outputs" not in T.LLMMeter.snapshot("so-never-seen")

        T.LLMMeter.record_structured("chat_json", "ok", stage="graph", run_id="so")
        T.LLMMeter.record_structured("chat_json", "repaired", json_truncation_repaired=True,
                                     stage="report", run_id="so")
        T.LLMMeter.record_structured("critique", "failed", stage="report", run_id="so")
        snap = T.LLMMeter.snapshot("so")
        # The spec shape: every value under a label is an integer counter.
        assert snap["structured_outputs"] == {
            "chat_json": {"ok": 1, "repaired": 1, "failed": 0, "truncation_repaired": 1},
            "critique": {"ok": 0, "repaired": 0, "failed": 1, "truncation_repaired": 0},
        }
        assert all(isinstance(n, int) for counts in snap["structured_outputs"].values()
                   for n in counts.values())
        # The per-stage breakdown lives in a sibling key.
        assert snap["structured_outputs_by_stage"] == {
            "chat_json": {
                "graph": {"ok": 1, "repaired": 0, "failed": 0, "truncation_repaired": 0},
                "report": {"ok": 0, "repaired": 1, "failed": 0, "truncation_repaired": 1},
            },
            "critique": {"report": {"ok": 0, "repaired": 0, "failed": 1, "truncation_repaired": 0}},
        }
        # record_structured never touches the call counters.
        assert snap["total"]["calls"] == 1
        T.LLMMeter.reset("so")
        after_reset = T.LLMMeter.snapshot("so")
        assert "structured_outputs" not in after_reset
        assert "structured_outputs_by_stage" not in after_reset
    finally:
        T.LLMMeter.reset("so")


def test_record_structured_attribution_matches_record():
    T.LLMMeter.reset("so-ctx")
    T.LLMMeter.reset("so-solo")
    try:
        T.set_run_context("so-ctx", "research")
        T.LLMMeter.record_structured("chat_json", "ok")
        T.set_run_context(None)
        assert T.LLMMeter.snapshot("so-ctx")["structured_outputs_by_stage"]["chat_json"] == {
            "research": {"ok": 1, "repaired": 0, "failed": 0, "truncation_repaired": 0}}

        # No run contextvar on the thread + exactly one active run -> fallback attribution.
        T.set_run_context("so-solo")
        token_ctx = T._current_run.set(None)
        try:
            T.LLMMeter.record_structured("chat_json", "failed")
        finally:
            T._current_run.reset(token_ctx)
        assert T.LLMMeter.snapshot("so-solo")["structured_outputs"]["chat_json"]["failed"] == 1
    finally:
        T.set_run_context(None)
        T.LLMMeter.reset("so-ctx")
        T.LLMMeter.reset("so-solo")


def test_record_structured_swallows_bad_outcomes():
    T.LLMMeter.reset("so-bad")
    try:
        T.LLMMeter.record_structured("chat_json", "exhausted", run_id="so-bad")
        assert "structured_outputs" not in T.LLMMeter.snapshot("so-bad")
    finally:
        T.LLMMeter.reset("so-bad")


# ---------------------------------------------------------------- EVAL-17 tests
_PRE_EVAL17_COUNTER_KEYS = ("calls", "cached", "prompt_tokens", "completion_tokens",
                            "total_tokens", "latency_ms", "cost_usd")


def test_cache_read_tokens_accumulate_and_snapshot_additive():
    """record() without the kwarg keeps every existing key/value (the new key is 0);
    with it, cache reads accumulate into total/by_stage/by_model and never change cost."""
    T.LLMMeter.reset("eval17_plain")
    T.LLMMeter.record("minimax", "MiniMax-M3", 1000, 500, 100.0, stage="report",
                      run_id="eval17_plain")
    plain = T.LLMMeter.snapshot("eval17_plain")
    for counter in (plain["total"], plain["by_stage"]["report"],
                    plain["by_model"]["minimax:MiniMax-M3"]):
        assert list(counter)[:len(_PRE_EVAL17_COUNTER_KEYS)] == list(_PRE_EVAL17_COUNTER_KEYS)
        assert {k: counter[k] for k in _PRE_EVAL17_COUNTER_KEYS} == {
            "calls": 1, "cached": 0, "prompt_tokens": 1000, "completion_tokens": 500,
            "total_tokens": 1500, "latency_ms": 100.0,
            "cost_usd": round(T.estimate_cost("minimax", 1000, 500), 6)}
        assert counter["prompt_cache_read_tokens"] == 0
    assert set(plain["fallback_attributed"]) == set(_PRE_EVAL17_COUNTER_KEYS) | {
        "prompt_cache_read_tokens"}

    T.LLMMeter.reset("eval17_cache")
    T.LLMMeter.record("glm", "glm-5", 12000, 900, 10.0, stage="research", run_id="eval17_cache",
                      prompt_cache_read_tokens=8000)
    T.LLMMeter.record("glm", "glm-5", 4000, 100, 10.0, stage="research", run_id="eval17_cache",
                      prompt_cache_read_tokens=6500)
    T.LLMMeter.record("glm", "glm-5", 10, 1, 1.0, stage="report", run_id="eval17_cache",
                      prompt_cache_read_tokens=-5)              # clamped to 0
    T.LLMMeter.record("glm", "glm-5", 10, 1, 1.0, stage="report", run_id="eval17_cache",
                      prompt_cache_read_tokens="junk")          # unparseable → 0
    T.LLMMeter.record("glm", "glm-5", 10, 1, 1.0, stage="report", run_id="eval17_cache",
                      prompt_cache_read_tokens=float("inf"))    # OverflowError → 0
    snap = T.LLMMeter.snapshot("eval17_cache")
    assert snap["total"]["prompt_cache_read_tokens"] == 14500
    assert snap["by_stage"]["research"]["prompt_cache_read_tokens"] == 14500
    assert snap["by_stage"]["report"]["prompt_cache_read_tokens"] == 0
    assert snap["by_model"]["glm:glm-5"]["prompt_cache_read_tokens"] == 14500
    # Informational split only: prompt/total tokens and cost are what they were without it.
    assert snap["total"]["prompt_tokens"] == 16030
    assert snap["total"]["cost_usd"] == round(
        T.estimate_cost("glm", 16030, 1003), 6)
    assert T.LLMMeter.status_snapshot("eval17_cache")["total"]["prompt_cache_read_tokens"] == 14500
    T.LLMMeter.reset("eval17_plain")
    T.LLMMeter.reset("eval17_cache")


def test_cache_read_tokens_follow_fallback_attribution():
    """The fallback_attributed subset carries its share of cache reads too."""
    T._clear_active_runs()
    T.LLMMeter.reset("eval17_fb")
    T.set_run_context("eval17_fb")
    try:
        import threading

        def unattributed():  # a fresh thread has no run contextvar
            T.LLMMeter.record("glm", "glm-5", 100, 10, 1.0, prompt_cache_read_tokens=40)

        t = threading.Thread(target=unattributed)
        t.start()
        t.join()
        snap = T.LLMMeter.snapshot("eval17_fb")
        assert snap["fallback_attributed"]["prompt_cache_read_tokens"] == 40
        assert snap["total"]["prompt_cache_read_tokens"] == 40
    finally:
        T.set_run_context(None)
        T.LLMMeter.reset("eval17_fb")


def _basis_for(run_id, providers):
    T.LLMMeter.reset(run_id)
    for prov in providers:
        T.LLMMeter.record(prov, "m", 100, 10, 1.0, run_id=run_id)
    basis = T.LLMMeter.snapshot(run_id)["cost_basis"]
    T.LLMMeter.reset(run_id)
    return basis


def test_subscription_providers_knob(monkeypatch):
    from app.config import Config
    # Default '' → the built-in classification, unchanged.
    monkeypatch.setattr(Config, "LLM_SUBSCRIPTION_PROVIDERS", "", raising=False)
    assert _basis_for("eval17_sub0", []) == "api"
    assert _basis_for("eval17_sub1", ["minimax"]) == "api"
    assert _basis_for("eval17_sub2", ["claude-cli"]) == "subscription"
    assert _basis_for("eval17_sub3", ["claude-cli", "codex-cli"]) == "subscription"
    assert _basis_for("eval17_sub4", ["claude-cli", "minimax"]) == "mixed"

    # Declared flat-rate plans (case-insensitive, whitespace tolerant) count as subscription.
    monkeypatch.setattr(Config, "LLM_SUBSCRIPTION_PROVIDERS", " MiniMax , glm,", raising=False)
    assert _basis_for("eval17_sub5", ["minimax"]) == "subscription"
    assert _basis_for("eval17_sub6", ["minimax", "glm", "claude-cli"]) == "subscription"
    assert _basis_for("eval17_sub7", ["minimax", "openai"]) == "mixed"
    assert _basis_for("eval17_sub8", ["openai"]) == "api"
    # cost_usd stays the API-rate equivalent (the knob only relabels the basis).
    T.LLMMeter.reset("eval17_sub9")
    T.LLMMeter.record("minimax", "m", 1000, 100, 1.0, run_id="eval17_sub9")
    snap = T.LLMMeter.snapshot("eval17_sub9")
    assert snap["cost_basis"] == "subscription"
    assert snap["total"]["cost_usd"] > 0
    assert snap["total"]["cost_usd"] == round(T.estimate_cost("minimax", 1000, 100), 6)
    T.LLMMeter.reset("eval17_sub9")
    # The stage telemetry / appendix inherit the relabelled basis.
    T.LLMMeter.record("minimax", "m", 1000, 100, 1.0, run_id="eval17_sub10", stage="report")
    assert T.build_stage_telemetry("eval17_sub10")["cost_basis"] == "subscription"
    T.LLMMeter.reset("eval17_sub10")


def test_subscription_providers_knob_default_is_empty_and_documented():
    import os
    backend = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with open(os.path.join(backend, "app", "config.py"), encoding="utf-8") as f:
        assert "os.environ.get('LLM_SUBSCRIPTION_PROVIDERS', '').strip()" in f.read()
    with open(os.path.join(os.path.dirname(backend), ".env.example"), encoding="utf-8") as f:
        assert "# LLM_SUBSCRIPTION_PROVIDERS=  " in f.read()


def test_add_counter_dicts_sums_cumulative_keys_and_tolerates_bad_rows():
    base = {"calls": 2, "cached": 1, "prompt_tokens": 100, "completion_tokens": 10,
            "total_tokens": 110, "latency_ms": 1.25, "cost_usd": 0.1}      # pre-EVAL-17 row
    cur = {"calls": 1, "cached": 0, "prompt_tokens": 50, "completion_tokens": 5,
           "total_tokens": 55, "latency_ms": 2.5, "cost_usd": 0.2,
           "prompt_cache_read_tokens": 30}
    out = T.add_counter_dicts(base, cur)
    assert out == {"calls": 3, "cached": 1, "prompt_tokens": 150, "completion_tokens": 15,
                   "total_tokens": 165, "latency_ms": 3.75,
                   "cost_usd": pytest.approx(0.3), "prompt_cache_read_tokens": 30}
    assert list(out) == list(T.CUMULATIVE_COUNTER_KEYS)
    assert T.add_counter_dicts(None, "junk")["calls"] == 0
    assert "calls" not in T.add_counter_dicts({"calls": "x"}, {"calls": 1})  # unaddable → skipped

    stages = T.add_stage_counter_dicts(
        {"research": base, "graph": {"calls": 4}},
        {"research": cur, "report": {"calls": 1}, "bad": None})
    assert list(stages) == ["research", "graph", "report", "bad"]
    assert stages["research"]["calls"] == 3
    assert stages["graph"]["calls"] == 4 and stages["report"]["calls"] == 1
    assert stages["bad"]["calls"] == 0
    assert T.add_stage_counter_dicts(None, ["x"]) == {}


def test_previous_attempt_carry_qualifies_history_and_tolerates_junk():
    assert T.previous_attempt_carry(None) is None
    assert T.previous_attempt_carry(["junk"]) is None
    assert T.previous_attempt_carry({}) is None
    assert T.previous_attempt_carry({"total": {"calls": 0}}) is None   # no history at all
    # A zero-call attempt still carries the pipeline's history in its cumulative fields.
    carry = T.previous_attempt_carry({"total": {"calls": 0}, "cumulative_total": {"calls": 3},
                                      "cumulative_by_stage": {"graph": {"calls": 3}},
                                      "report_id": "r1", "status": "cancelled"})
    assert carry == {"previous_attempt": {"total": {"calls": 0}, "report_id": "r1",
                                          "status": "cancelled"},
                     "cumulative_total": {"calls": 3},
                     "cumulative_by_stage": {"graph": {"calls": 3}},
                     "partial": False}
    # A malformed total does not hide the cumulative history.
    assert T.previous_attempt_carry({"total": ["junk"], "cumulative_total": {"calls": 2}}
                                    )["cumulative_total"] == {"calls": 2}
    # Pre-EVAL-17 file spanning attempts: by_stage is the base and the split is partial.
    legacy = T.previous_attempt_carry({"total": {"calls": 1}, "cumulative_total": {"calls": 4},
                                       "by_stage": {"graph": {"calls": 1}}})
    assert legacy["cumulative_by_stage"] == {"graph": {"calls": 1}}
    assert legacy["partial"] is True
    data = {"total": {"calls": 1}, "by_stage": {"graph": {"calls": 1}}}
    T.apply_previous_attempt_carry(data, None)
    assert data == {"total": {"calls": 1}, "by_stage": {"graph": {"calls": 1}}}   # no-op
    T.apply_previous_attempt_carry(data, legacy)
    assert data["cumulative_total"]["calls"] == 5
    assert data["cumulative_by_stage"]["graph"]["calls"] == 2
    assert data["cumulative_by_stage_partial"] is True


def test_write_run_telemetry_uses_the_shared_merge_rule(tmp_path):
    """LLMMeter.write_run_telemetry merges like the pipeline flush: cumulative_total carries
    prompt_cache_read_tokens, cumulative_by_stage keeps the per-stage split, and a zero-call
    attempt no longer wipes the history (the old calls gate dropped it)."""
    import json

    rid = "eval17_write_rt"
    path = str(tmp_path / "run_telemetry.json")
    T.LLMMeter.reset(rid)
    T.LLMMeter.record("minimax", "m", 100, 10, 1.0, run_id=rid, stage="research",
                      prompt_cache_read_tokens=60)
    T.LLMMeter.write_run_telemetry(path, run_id=rid, extra={"report_id": "a"})
    with open(path, encoding="utf-8") as f:
        first = json.load(f)
    assert "cumulative_total" not in first and "cumulative_by_stage" not in first  # first write

    T.LLMMeter.reset(rid)                                     # attempt 2: zero calls
    T.LLMMeter.write_run_telemetry(path, run_id=rid, extra={"report_id": "b"})
    T.LLMMeter.reset(rid)                                     # attempt 3
    T.LLMMeter.record("minimax", "m", 50, 5, 1.0, run_id=rid, stage="report",
                      prompt_cache_read_tokens=20)
    T.LLMMeter.write_run_telemetry(path, run_id=rid, extra={"report_id": "c"})
    T.LLMMeter.reset(rid)
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    assert data["previous_attempt"]["report_id"] == "b"
    assert data["cumulative_total"]["calls"] == 2
    assert data["cumulative_total"]["prompt_tokens"] == 150
    assert data["cumulative_total"]["prompt_cache_read_tokens"] == 80
    assert data["cumulative_by_stage"]["research"]["prompt_cache_read_tokens"] == 60
    assert data["cumulative_by_stage"]["report"]["calls"] == 1
    assert "cumulative_by_stage_partial" not in data
