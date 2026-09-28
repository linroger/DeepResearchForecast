"""Deep-research engine v3 — bridge (deerflow_research.py) overhaul regressions.

Offline and deterministic: no network, no real LLM, no langchain (the backend
venv does not ship it).  Covers:

* engine resolution + routing (``RESEARCH_ENGINE=v3`` dispatch with ``bridge=``,
  legacy-only lane contracts, failure boundary, plog closed exactly once);
* env hygiene and credential preflight ordering (missing key → exit 3 before
  any engine dispatch) and safe integer env parsing;
* stage-1 messages never system-only (GLM 400 code 1214);
* cache-usage telemetry suffix that keeps the orchestrator ``[usage]`` regex;
* tool-free failover circuit (half-open primary probe, circuit only after the
  fallback actually served);
* provider-error extraction classification (no recovery against a dead
  provider, no 0-byte artifacts) and the extract-only contract modes;
* JSON repair (strict=False, string-aware trailing commas, truncation stack
  snapshot, stray-brace rescan), ``strip_think`` orphan closer;
* idempotent Prediction Market Signals section; ``ProgressLog`` after close.
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
import types
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]
_BRIDGE = str(_REPO / "deerflow_bridge")
if _BRIDGE not in sys.path:
    sys.path.insert(0, _BRIDGE)

import deerflow_research as dr  # noqa: E402

# The orchestrator's ``[usage]`` contract (pipeline_orchestrator._USAGE_RE).
USAGE_RE = re.compile(r"tokens in=(\d+|None)\s+out=(\d+|None)\s+total=(\d+|None)")


class _Log:
    """Minimal ProgressLog double recording (kind, message)."""

    def __init__(self):
        self.rows: list[tuple[str, str]] = []

    def write(self, kind, message):
        self.rows.append((kind, str(message)))

    def close(self):
        pass

    def text(self) -> str:
        return "\n".join(f"[{k}] {m}" for k, m in self.rows)


@pytest.fixture
def isolated_environ():
    """main() mutates os.environ (hygiene defaults, RESEARCH_EVIDENCE_ONLY); undo all of it."""
    saved = dict(os.environ)
    try:
        yield os.environ
    finally:
        os.environ.clear()
        os.environ.update(saved)


def _run_main(argv: list[str]) -> int:
    old_argv = sys.argv
    sys.argv = ["deerflow_research.py", *argv]
    try:
        return dr.main()
    finally:
        sys.argv = old_argv


def _read_meta(out_dir: Path) -> dict:
    return json.loads((out_dir / dr.META_FILENAME).read_text(encoding="utf-8"))


def _read_log(out_dir: Path) -> str:
    return (out_dir / dr.PROGRESS_FILENAME).read_text(encoding="utf-8")


def _install_fake_engine(monkeypatch, behaviour):
    """Register a stub ``linear_research`` module whose ``run`` delegates to ``behaviour``."""
    calls: list[dict] = []
    module = types.ModuleType("linear_research")

    def run(question, out_dir, args, meta, plog, write_meta, *, bridge=None):
        calls.append({
            "question": question, "out_dir": out_dir, "args": args,
            "meta": meta, "plog": plog, "bridge": bridge,
            "env_snapshot": dict(os.environ),
        })
        return behaviour(meta, plog, write_meta)

    module.run = run
    monkeypatch.setitem(sys.modules, "linear_research", module)
    return calls


# ---------------------------------------------------------------------------
# Engine resolution + routing
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("raw,expected", [
    (None, "legacy"),
    ("", "legacy"),
    ("  ", "legacy"),
    ("v3", "v3"),
    (" V3 ", "v3"),
    ("linear", "v3"),
    ("legacy", "legacy"),
    ("deerflow", "legacy"),
    ("Agentic", "legacy"),
])
def test_resolve_research_engine_known_values(monkeypatch, raw, expected):
    if raw is None:
        monkeypatch.delenv("RESEARCH_ENGINE", raising=False)
    else:
        monkeypatch.setenv("RESEARCH_ENGINE", raw)
    log = _Log()
    assert dr._resolve_research_engine(log) == expected
    assert log.rows == []


def test_resolve_research_engine_unknown_value_warns_and_uses_legacy(monkeypatch):
    monkeypatch.setenv("RESEARCH_ENGINE", "turbo")
    log = _Log()
    assert dr._resolve_research_engine(log) == "legacy"
    assert log.rows and log.rows[0][0] == "warn"
    assert "turbo" in log.rows[0][1]


def test_v3_dispatch_receives_bridge_after_hygiene_and_closes_plog(
        tmp_path, monkeypatch, isolated_environ):
    monkeypatch.setenv("RESEARCH_ENGINE", "v3")
    monkeypatch.setenv("MINIMAX_API_KEY", "test-key-not-used")
    for name in ("LLM_FALLBACK_API_KEY", "LLM_FALLBACK_BASE_URL",
                 "DASHSCOPE_API_KEY", "DEER_FLOW_CONFIG_PATH"):
        os.environ.pop(name, None)

    def behaviour(meta, plog, write_meta):
        meta.update(status="completed", research_engine="v3")
        write_meta()
        plog.write("done", "research complete (v3: stub)")
        return 0

    calls = _install_fake_engine(monkeypatch, behaviour)
    rc = _run_main(["--model", "minimax", "--depth", "deep",
                    "--out-dir", str(tmp_path), "--prompt", "Q-v3"])

    assert rc == 0
    assert len(calls) == 1
    call = calls[0]
    assert call["bridge"] is dr
    assert call["question"] == "Q-v3"
    assert call["out_dir"] == tmp_path.resolve()
    # Hygiene ran BEFORE dispatch: every $VAR of the adjacent config.yaml
    # (including the non-provider fallback stanza) exists in the child env.
    for name in ("LLM_FALLBACK_API_KEY", "LLM_FALLBACK_BASE_URL", "DASHSCOPE_API_KEY"):
        assert call["env_snapshot"].get(name) == ""
    assert call["plog"].closed is True
    meta = _read_meta(tmp_path)
    assert meta["status"] == "completed"
    assert meta["research_engine"] == "v3"
    assert meta["skill_activation"]["mode"] == "none"
    assert "deep_research_phases" not in meta
    log = _read_log(tmp_path)
    assert "[stage] research engine: v3" in log
    assert "research complete (v3: stub)" in log


def test_missing_provider_key_exits_3_before_v3_dispatch(
        tmp_path, monkeypatch, isolated_environ):
    monkeypatch.setenv("RESEARCH_ENGINE", "v3")
    monkeypatch.setenv("MINIMAX_API_KEY", "")
    calls = _install_fake_engine(
        monkeypatch, lambda *_a: pytest.fail("engine must not run without a key"))

    rc = _run_main(["--model", "minimax", "--out-dir", str(tmp_path), "--prompt", "Q"])

    assert rc == 3
    assert calls == []
    meta = _read_meta(tmp_path)
    assert meta["status"] == "failed"
    assert meta["error"] == "missing MINIMAX_API_KEY"


@pytest.mark.parametrize("extra_argv,flag", [
    (["--evidence-only"], "--evidence-only"),
    (["--synthesis-manifest", "manifest.json"], "--synthesis-manifest"),
    (["--extract-only"], "--extract-only"),
])
def test_v3_request_keeps_legacy_only_lane_contracts_on_legacy(
        tmp_path, monkeypatch, isolated_environ, extra_argv, flag):
    monkeypatch.setenv("RESEARCH_ENGINE", "v3")
    monkeypatch.setenv("MINIMAX_API_KEY", "")  # legacy path stops at the preflight
    calls = _install_fake_engine(
        monkeypatch, lambda *_a: pytest.fail("legacy-only mode routed to v3"))

    rc = _run_main(["--model", "minimax", "--out-dir", str(tmp_path),
                    "--prompt", "Q", *extra_argv])

    assert rc == 3
    assert calls == []
    assert _read_meta(tmp_path)["research_engine"] == "legacy"
    log = _read_log(tmp_path)
    assert f"v3 requested but {flag} is a legacy-engine lane contract" in log


def test_unknown_engine_value_routes_to_legacy_with_warning(
        tmp_path, monkeypatch, isolated_environ):
    monkeypatch.setenv("RESEARCH_ENGINE", "bogus-engine")
    monkeypatch.setenv("MINIMAX_API_KEY", "")
    calls = _install_fake_engine(
        monkeypatch, lambda *_a: pytest.fail("unknown value must not select v3"))

    assert _run_main(["--model", "minimax", "--out-dir", str(tmp_path),
                      "--prompt", "Q"]) == 3
    assert calls == []
    assert "[warn] RESEARCH_ENGINE='bogus-engine' is not recognized" in _read_log(tmp_path)


def test_v3_engine_exception_is_exit_2_with_terminal_meta(
        tmp_path, monkeypatch, isolated_environ):
    monkeypatch.setenv("RESEARCH_ENGINE", "linear")
    monkeypatch.setenv("MINIMAX_API_KEY", "k")

    def behaviour(_meta, _plog, _write_meta):
        raise RuntimeError("boom")

    calls = _install_fake_engine(monkeypatch, behaviour)
    rc = _run_main(["--model", "minimax", "--out-dir", str(tmp_path), "--prompt", "Q"])

    assert rc == 2
    assert calls[0]["plog"].closed is True
    meta = _read_meta(tmp_path)
    assert meta["status"] == "failed"
    assert meta["error"] == "v3 engine failed: RuntimeError: boom"
    assert "[error] v3 engine failed: RuntimeError: boom" in _read_log(tmp_path)


def test_v3_engine_interrupt_records_terminal_meta_and_propagates(
        tmp_path, monkeypatch, isolated_environ):
    monkeypatch.setenv("RESEARCH_ENGINE", "v3")
    monkeypatch.setenv("MINIMAX_API_KEY", "k")

    def behaviour(_meta, _plog, _write_meta):
        raise SystemExit(5)

    calls = _install_fake_engine(monkeypatch, behaviour)
    with pytest.raises(SystemExit):
        _run_main(["--model", "minimax", "--out-dir", str(tmp_path), "--prompt", "Q"])

    assert calls[0]["plog"].closed is True
    meta = _read_meta(tmp_path)
    assert meta["status"] == "failed"
    assert meta["error"] == "v3 engine interrupted: SystemExit"


@pytest.mark.parametrize("returned,expected_rc,expected_status", [
    (0, 0, "completed"),
    (2, 2, "failed"),
    (None, 2, "failed"),
])
def test_v3_engine_never_leaves_meta_running(
        tmp_path, monkeypatch, isolated_environ, returned, expected_rc, expected_status):
    monkeypatch.setenv("RESEARCH_ENGINE", "v3")
    monkeypatch.setenv("MINIMAX_API_KEY", "k")
    _install_fake_engine(monkeypatch, lambda *_a: returned)

    rc = _run_main(["--model", "minimax", "--out-dir", str(tmp_path), "--prompt", "Q"])

    assert rc == expected_rc
    meta = _read_meta(tmp_path)
    assert meta["status"] == expected_status
    assert meta.get("finished_at")


def test_invalid_opening_recursion_limit_falls_back_with_warning(
        tmp_path, monkeypatch, isolated_environ):
    monkeypatch.delenv("RESEARCH_ENGINE", raising=False)
    monkeypatch.setenv("DEERFLOW_DEEP_OPENING_RECURSION_LIMIT", "300s")
    monkeypatch.setenv("MINIMAX_API_KEY", "")

    rc = _run_main(["--model", "minimax", "--depth", "deep",
                    "--out-dir", str(tmp_path), "--prompt", "Q"])

    assert rc == 3  # reached the credential preflight instead of crashing (exit 1)
    meta = _read_meta(tmp_path)
    assert meta["research_engine"] == "legacy"
    assert meta["deep_research_phases"][0] == {
        "label": "deep-opening", "recursion_limit": 300}
    assert "DEERFLOW_DEEP_OPENING_RECURSION_LIMIT='300s' is not an integer" in _read_log(tmp_path)


@pytest.mark.parametrize("raw,expected,warns", [
    (None, 300, False),
    ("", 300, False),
    ("420", 420, False),
    (" 17 ", 17, False),
    ("abc", 300, True),
    ("0", 300, True),
    ("-5", 300, True),
])
def test_env_int_is_safe(monkeypatch, raw, expected, warns):
    if raw is None:
        monkeypatch.delenv("DRF_TEST_INT_KNOB", raising=False)
    else:
        monkeypatch.setenv("DRF_TEST_INT_KNOB", raw)
    log = _Log()
    assert dr._env_int("DRF_TEST_INT_KNOB", 300, minimum=1, plog=log) == expected
    assert bool(log.rows) is warns


# ---------------------------------------------------------------------------
# Env hygiene helpers
# ---------------------------------------------------------------------------


def test_config_env_references_skip_comments(tmp_path):
    config = tmp_path / "config.yaml"
    config.write_text(
        "# api_key: $COMMENTED_ONLY_KEY\n"
        "models:\n"
        "  - name: a\n"
        "    api_key: $ALPHA_KEY\n"
        "    base_url: ${BETA_URL}  # $INLINE_COMMENT_KEY\n"
        "    #  api_key: $INDENTED_COMMENT_KEY\n"
        "    header: \"prefix-$GAMMA_TOKEN\"\n"
        "    lower: $not_an_env_name\n",
        encoding="utf-8",
    )
    assert dr._config_env_references(config) == {"ALPHA_KEY", "BETA_URL", "GAMMA_TOKEN"}
    assert dr._config_env_references(tmp_path / "missing.yaml") == set()


def test_config_candidates_follow_harness_priority(tmp_path, monkeypatch):
    explicit = tmp_path / "explicit.yaml"
    env_path = tmp_path / "env.yaml"
    monkeypatch.setenv("DEER_FLOW_CONFIG_PATH", str(env_path))
    assert dr._deerflow_config_candidates(str(explicit)) == [explicit]
    assert dr._deerflow_config_candidates(None) == [env_path]

    monkeypatch.delenv("DEER_FLOW_CONFIG_PATH")
    monkeypatch.setenv("DEER_FLOW_PROJECT_ROOT", str(tmp_path))
    candidates = dr._deerflow_config_candidates(None)
    assert candidates[0] == tmp_path / "config.yaml"
    assert Path(dr.__file__).resolve().parent / "config.yaml" in candidates
    assert Path.cwd() / "config.yaml" in candidates


def test_preset_provider_env_defaults_never_overrides(tmp_path, isolated_environ):
    config = tmp_path / "config.yaml"
    config.write_text("a: $DRF_TEST_UNSET_KEY\nb: $DRF_TEST_SET_KEY\n", encoding="utf-8")
    os.environ.pop("DRF_TEST_UNSET_KEY", None)
    os.environ["DRF_TEST_SET_KEY"] = "real-value"
    os.environ.pop("KIMI_API_KEY", None)

    preset = dr._preset_provider_env_defaults(str(config))

    assert "DRF_TEST_UNSET_KEY" in preset and "KIMI_API_KEY" in preset
    assert "DRF_TEST_SET_KEY" not in preset
    assert os.environ["DRF_TEST_UNSET_KEY"] == ""
    assert os.environ["KIMI_API_KEY"] == ""
    assert os.environ["DRF_TEST_SET_KEY"] == "real-value"


# ---------------------------------------------------------------------------
# Stage-1 messages: never system-only
# ---------------------------------------------------------------------------


def test_stage1_messages_append_proceed_turn_when_evidence_empty():
    messages = dr._stage1_model_messages("GOVERNING", "model input", "")
    assert [m.__class__.__name__ for m in messages] == ["SystemMessage", "HumanMessage"]
    assert messages[0].content == "GOVERNING"
    assert messages[1].content == dr.STAGE1_PROCEED_INSTRUCTION
    assert dr.STAGE1_PROCEED_INSTRUCTION == "Follow the instructions above and respond now."


def test_stage1_messages_keep_evidence_block_as_user_turn():
    messages = dr._stage1_model_messages("GOVERNING", "fixture", "Revenue rose 12% in 2025.")
    assert [m.__class__.__name__ for m in messages] == ["SystemMessage", "HumanMessage"]
    assert messages[1].content.startswith("BEGIN UNTRUSTED EVIDENCE DATA — fixture")
    assert "Revenue rose 12% in 2025." in messages[1].content


def test_plain_string_bare_call_is_not_system_only(monkeypatch):
    captured = {}

    def fake_invoke(model_name, messages, **_kwargs):
        captured["messages"] = messages
        return types.SimpleNamespace(content='["query"]', response_metadata={},
                                     usage_metadata=None), model_name

    monkeypatch.setattr(dr, "_invoke_tool_free_model", fake_invoke)
    assert dr._bare_synth_invoke("glm", "Derive market queries.", None, "pm-queries") == '["query"]'
    kinds = [m.__class__.__name__ for m in captured["messages"]]
    assert kinds[-1] == "HumanMessage" and len(kinds) == 2


# ---------------------------------------------------------------------------
# Usage telemetry
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("response,expected", [
    (  # langchain_openai normalized shape (GLM path)
        types.SimpleNamespace(usage_metadata={
            "input_tokens": 1000, "output_tokens": 50, "total_tokens": 1050,
            "input_token_details": {"cache_read": 800},
            "output_token_details": {"reasoning": 30},
        }, response_metadata={}),
        {"cached": 800, "cache_write": 0, "reasoning": 30},
    ),
    (  # raw OpenAI-compatible token_usage
        types.SimpleNamespace(usage_metadata=None, response_metadata={"token_usage": {
            "prompt_tokens": 1000, "completion_tokens": 50, "total_tokens": 1050,
            "prompt_tokens_details": {"cached_tokens": 640, "cache_creation_input_tokens": 12},
            "completion_tokens_details": {"reasoning_tokens": 7},
        }}),
        {"cached": 640, "cache_write": 12, "reasoning": 7},
    ),
    (  # DeepSeek prefix cache; a zero sibling must not hide the real count
        types.SimpleNamespace(
            usage_metadata={"input_tokens": 10, "output_tokens": 1,
                            "input_token_details": {"cache_read": 0}},
            response_metadata={"usage": {"prompt_cache_hit_tokens": 9}}),
        {"cached": 9, "cache_write": 0, "reasoning": 0},
    ),
    (  # Anthropic raw usage block
        types.SimpleNamespace(usage_metadata=None, response_metadata={"usage": {
            "input_tokens": 10, "output_tokens": 5,
            "cache_read_input_tokens": 4000, "cache_creation_input_tokens": 1200,
        }}),
        {"cached": 4000, "cache_write": 1200, "reasoning": 0},
    ),
    (types.SimpleNamespace(), {"cached": 0, "cache_write": 0, "reasoning": 0}),
])
def test_model_response_cache_usage_shapes(response, expected):
    assert dr._model_response_cache_usage(response) == expected


def test_usage_line_appends_cache_fields_after_the_parsed_prefix():
    log = _Log()
    response = types.SimpleNamespace(usage_metadata={
        "input_tokens": 100, "output_tokens": 20, "total_tokens": 120,
        "input_token_details": {"cache_read": 80, "cache_creation": 3},
        "output_token_details": {"reasoning": 5},
    }, response_metadata={})

    dr._log_model_response_usage(log, "structured-extraction", response)

    kind, line = log.rows[0]
    assert kind == "usage"
    assert line == ("tokens in=100 out=20 total=120 phase=structured-extraction"
                    " cached=80 cache_write=3 reasoning=5")
    assert USAGE_RE.search(line).groups() == ("100", "20", "120")
    # The 3-tuple contract is unchanged.
    assert dr._model_response_usage(response) == (100, 20, 120)


def test_stream_end_usage_line_suffix_only_when_details_reported():
    plain = dr._stream_end_usage_line(
        {"input_tokens": 10, "output_tokens": 2, "total_tokens": 12})
    assert plain == "tokens in=10 out=2 total=12"
    assert dr._stream_end_usage_line({}) == "tokens in=None out=None total=None"
    assert USAGE_RE.search(dr._stream_end_usage_line({})).groups() == ("None", "None", "None")

    detailed = dr._stream_end_usage_line({
        "input_tokens": 10, "output_tokens": 2, "total_tokens": 12,
        "input_token_details": {"cache_read": 6},
    })
    assert detailed == "tokens in=10 out=2 total=12 cached=6 cache_write=0 reasoning=0"


# ---------------------------------------------------------------------------
# Tool-free failover circuit
# ---------------------------------------------------------------------------


@pytest.fixture
def failover(monkeypatch):
    """Fake deerflow.models + scripted _invoke_model; returns (behaviour, calls, key)."""
    monkeypatch.setenv("DEERFLOW_FALLBACK_MODEL", "antigravity")
    monkeypatch.setenv("DEERFLOW_FALLBACK_COOLDOWN_SECONDS", "900")
    monkeypatch.setattr(dr, "_MODEL_FAILOVER_UNTIL", {})

    class FakeModel:
        def __init__(self, name):
            self.name = name

        def bind(self, **_kwargs):
            return self

    models_module = types.ModuleType("deerflow.models")
    models_module.create_chat_model = lambda name, **_kwargs: FakeModel(name)
    deerflow_module = types.ModuleType("deerflow")
    deerflow_module.models = models_module
    monkeypatch.setitem(sys.modules, "deerflow", deerflow_module)
    monkeypatch.setitem(sys.modules, "deerflow.models", models_module)

    behaviour: dict[str, object] = {}
    calls: list[str] = []

    def invoke(model, _messages):
        calls.append(model.name)
        outcome = behaviour[model.name]
        if isinstance(outcome, BaseException):
            raise outcome
        return types.SimpleNamespace(content=outcome)

    monkeypatch.setattr(dr, "_invoke_model", invoke)
    return behaviour, calls, ("glm", "antigravity")


def _open_circuit(key):
    dr._MODEL_FAILOVER_UNTIL[key] = time.monotonic() + 900


def test_open_circuit_with_dead_fallback_probes_primary_half_open(failover):
    behaviour, calls, key = failover
    behaviour["antigravity"] = RuntimeError("Connection error.")
    behaviour["glm"] = "PRIMARY-OK"
    _open_circuit(key)
    log = _Log()

    response, served = dr._invoke_tool_free_model(
        "glm", ["m"], max_output_tokens=64, plog=log, label="extract")

    assert (response.content, served) == ("PRIMARY-OK", "glm")
    assert calls == ["antigravity", "glm"]
    assert key not in dr._MODEL_FAILOVER_UNTIL
    assert "half-open probe served the call" in log.text()


def test_fallback_failure_after_primary_failure_never_opens_circuit(failover):
    behaviour, calls, key = failover
    behaviour["glm"] = RuntimeError("APIConnectionError: Connection error")
    behaviour["antigravity"] = RuntimeError("Connection error.")

    with pytest.raises(dr.ModelProvidersUnavailable):
        dr._invoke_tool_free_model("glm", ["m"], max_output_tokens=64,
                                   plog=None, label="extract")

    assert calls == ["glm", "antigravity"]
    assert key not in dr._MODEL_FAILOVER_UNTIL

    # The next call therefore probes the (possibly recovered) primary first.
    behaviour["glm"] = "RECOVERED"
    response, served = dr._invoke_tool_free_model(
        "glm", ["m"], max_output_tokens=64, plog=None, label="extract")
    assert (response.content, served) == ("RECOVERED", "glm")


def test_open_circuit_with_both_models_down_raises_and_clears(failover):
    behaviour, calls, key = failover
    behaviour["antigravity"] = RuntimeError("Connection error.")
    behaviour["glm"] = RuntimeError("503 Service Unavailable")
    _open_circuit(key)

    with pytest.raises(dr.ModelProvidersUnavailable, match="half-open probe"):
        dr._invoke_tool_free_model("glm", ["m"], max_output_tokens=64,
                                   plog=None, label="extract")

    assert calls == ["antigravity", "glm"]
    assert key not in dr._MODEL_FAILOVER_UNTIL


def test_half_open_probe_does_not_mask_programming_errors(failover):
    behaviour, _calls, key = failover
    behaviour["antigravity"] = RuntimeError("Connection error.")
    behaviour["glm"] = ValueError("local prompt construction bug")
    _open_circuit(key)

    with pytest.raises(ValueError, match="prompt construction"):
        dr._invoke_tool_free_model("glm", ["m"], max_output_tokens=64,
                                   plog=None, label="extract")


def test_fallback_success_opens_then_extends_circuit(failover):
    behaviour, calls, key = failover
    behaviour["glm"] = RuntimeError("429 quota exhausted (2056)")
    behaviour["antigravity"] = "FALLBACK-OK"

    _resp, served = dr._invoke_tool_free_model(
        "glm", ["m"], max_output_tokens=64, plog=None, label="a")
    assert served == "antigravity"
    first_until = dr._MODEL_FAILOVER_UNTIL[key]

    dr._MODEL_FAILOVER_UNTIL[key] = time.monotonic() + 5  # nearly expired
    _resp, served = dr._invoke_tool_free_model(
        "glm", ["m"], max_output_tokens=64, plog=None, label="b")
    assert served == "antigravity"
    assert calls == ["glm", "antigravity", "antigravity"]
    assert dr._MODEL_FAILOVER_UNTIL[key] > time.monotonic() + 800
    assert first_until > time.monotonic() + 800


# ---------------------------------------------------------------------------
# Structured extraction: provider errors are not "unparseable JSON"
# ---------------------------------------------------------------------------


def test_extraction_provider_exception_is_classified(monkeypatch):
    def raising(*_args, **_kwargs):
        raise dr.ModelProvidersUnavailable("primary glm failed; fallback failed")

    monkeypatch.setattr(dr, "_invoke_tool_free_model", raising)
    for raw in (
        dr.extract_structured_tool_free("report", None, "glm", "standard", _Log()),
        dr.extract_structured_recovery_tool_free("report", None, "glm", _Log()),
    ):
        assert raw == ""
        assert raw.provider_error == "ModelProvidersUnavailable"
        assert "fallback failed" in raw.provider_error_message
        assert dr._structured_extraction_incomplete_reason(
            raw, dr.extract_json_object(raw)) == "provider_unavailable:ModelProvidersUnavailable"


def _provider_failure(exc_name="APIConnectionError"):
    return dr.StructuredExtractionText(
        "", provider_error=exc_name, provider_error_message="Connection error.")


def test_provider_failed_primary_retries_primary_not_recovery(monkeypatch):
    monkeypatch.setenv("RESEARCH_EXTRACTION_PROVIDER_RETRY_SECONDS", "3")
    primaries = iter([
        _provider_failure(),
        dr.StructuredExtractionText('{"actors":[{"name":"CATL"}]}', finish_reason="stop"),
    ])
    monkeypatch.setattr(dr, "extract_structured_tool_free",
                        lambda *_a, **_k: next(primaries))
    monkeypatch.setattr(dr, "extract_structured_recovery_tool_free",
                        lambda *_a, **_k: pytest.fail("recovery must not run"))
    sleeps: list[float] = []

    raw, obj, failed, used = dr.extract_complete_structured_tool_free(
        "report", None, "glm", "deep", _Log(), sleep=sleeps.append)

    assert sleeps == [3.0]
    assert obj["actors"][0]["name"] == "CATL"
    assert used is False
    assert [(phase, reason) for phase, _raw, reason in failed] == [
        ("primary", "provider_unavailable:APIConnectionError")]


def test_provider_down_twice_skips_compact_recovery(monkeypatch):
    monkeypatch.setenv("RESEARCH_EXTRACTION_PROVIDER_RETRY_SECONDS", "0")
    monkeypatch.setattr(dr, "extract_structured_tool_free",
                        lambda *_a, **_k: _provider_failure())
    monkeypatch.setattr(dr, "extract_structured_recovery_tool_free",
                        lambda *_a, **_k: pytest.fail("recovery must not run"))
    sleeps: list[float] = []

    _raw, obj, failed, used = dr.extract_complete_structured_tool_free(
        "report", None, "glm", "deep", _Log(), sleep=sleeps.append)

    assert obj is None and used is False
    assert sleeps == []  # zero backoff configured
    assert [phase for phase, _raw, _reason in failed] == ["primary", "primary_retry"]


def test_provider_recovered_but_malformed_then_uses_compact_recovery(monkeypatch):
    monkeypatch.setenv("RESEARCH_EXTRACTION_PROVIDER_RETRY_SECONDS", "0")
    primaries = iter([_provider_failure(), dr.StructuredExtractionText("not json")])
    monkeypatch.setattr(dr, "extract_structured_tool_free",
                        lambda *_a, **_k: next(primaries))
    monkeypatch.setattr(
        dr, "extract_structured_recovery_tool_free",
        lambda *_a, **_k: dr.StructuredExtractionText(
            '{"actors":[{"name":"Recovered"}]}', finish_reason="stop"))

    _raw, obj, failed, used = dr.extract_complete_structured_tool_free(
        "report", None, "glm", "deep", _Log(), sleep=lambda _s: None)

    assert used is True
    assert obj["actors"][0]["name"] == "Recovered"
    assert [reason for _p, _r, reason in failed] == [
        "provider_unavailable:APIConnectionError", "unparseable_json"]


def test_failure_persistence_writes_no_empty_artifacts(tmp_path):
    meta: dict = {}
    writes: list[bool] = []
    records = dr.persist_structured_extraction_failures(
        tmp_path,
        [
            ("primary", _provider_failure("ModelProvidersUnavailable"),
             "provider_unavailable:ModelProvidersUnavailable"),
            ("compact_recovery", dr.StructuredExtractionText("   \n"), "unparseable_json"),
            ("primary_retry", dr.StructuredExtractionText('{"actors": ['), "unparseable_json"),
        ],
        meta,
        lambda: writes.append(True),
    )

    assert writes == [True]
    assert records[0]["artifact"] is None
    assert records[0]["provider_error"] == "ModelProvidersUnavailable"
    assert records[0]["provider_error_message"] == "Connection error."
    assert records[1]["artifact"] is None
    assert "provider_error" not in records[1]
    assert (tmp_path / records[2]["artifact"]).read_text(encoding="utf-8") == '{"actors": ['
    written = sorted(p.name for p in tmp_path.glob("structured_extraction_unparseable_*"))
    assert written == [records[2]["artifact"]]
    assert meta["structured_extraction_failure"] == records[0]
    summary = dr._describe_extraction_failures(records)
    assert "primary=<no artifact: ModelProvidersUnavailable>" in summary
    assert "compact_recovery=<no artifact: empty output>" in summary


# ---------------------------------------------------------------------------
# Extract-only contract modes (salvage path)
# ---------------------------------------------------------------------------


def _extract_only_args(**overrides):
    base = {"no_actors": False, "target_language": "English", "model": "glm", "depth": "standard"}
    base.update(overrides)
    return types.SimpleNamespace(**base)


def test_extract_only_provider_outage_fails_closed_without_artifacts(tmp_path, monkeypatch):
    (tmp_path / dr.REPORT_FILENAME).write_text("# Report\n\n" + "evidence " * 100, encoding="utf-8")
    monkeypatch.setenv("RESEARCH_EXTRACTION_PROVIDER_RETRY_SECONDS", "0")
    monkeypatch.setattr(dr, "extract_structured_tool_free",
                        lambda *_a, **_k: _provider_failure())
    monkeypatch.setattr(dr, "extract_structured_recovery_tool_free",
                        lambda *_a, **_k: pytest.fail("recovery must not run"))
    monkeypatch.setattr(dr, "_collect_prediction_markets",
                        lambda *_a, **_k: pytest.fail("markets must not run after failure"))
    monkeypatch.setattr(dr, "_render_research_charts",
                        lambda *_a, **_k: pytest.fail("charts must not run after failure"))
    meta: dict = {}
    log = dr.ProgressLog(tmp_path / "extract.log")

    rc = dr.run_extract_only("Q", tmp_path, _extract_only_args(), meta, log, lambda: None)

    assert rc == 2
    assert meta["status"] == "failed"
    assert "provider_unavailable:APIConnectionError" in meta["error"]
    assert list(tmp_path.glob("structured_extraction_unparseable_*")) == []
    assert not (tmp_path / dr.ACTORS_FILENAME).exists()
    assert log.closed is True


def test_extract_only_report_only_cast_completes_without_dossier(tmp_path, monkeypatch):
    (tmp_path / dr.REPORT_FILENAME).write_text("# Report\n\n" + "evidence " * 100, encoding="utf-8")
    obj = {
        "actor_intelligence_contract": {"schema_version": "actor-intelligence/v1"},
        "actors": [{"name": "Acme", "type": "Organization",
                    "intelligence": {"schema_version": "actor-intelligence/v1"}}],
        "key_events": [{"date": "2026-01-01", "event": "Launch"}],
        "sources": [{"url": "https://example.com/a", "title": "A", "tier": "S2"}],
    }
    monkeypatch.setattr(dr, "extract_complete_structured_tool_free",
                        lambda *_a, **_k: ("{}", obj, [], False))
    monkeypatch.setattr(dr, "_collect_prediction_markets", lambda *_a, **_k: None)
    monkeypatch.setattr(dr, "_render_research_charts", lambda *_a, **_k: {})
    meta: dict = {}
    log = dr.ProgressLog(tmp_path / "extract.log")

    rc = dr.run_extract_only("Q", tmp_path, _extract_only_args(), meta, log, lambda: None)

    assert rc == 0
    assert meta["status"] == "completed"
    assert meta["actor_contract_mode"] == "report-only"
    actors = json.loads((tmp_path / dr.ACTORS_FILENAME).read_text(encoding="utf-8"))
    assert "actor_intelligence_contract" not in actors
    assert all("intelligence" not in row for row in actors["actors"])
    sources = json.loads((tmp_path / dr.SOURCES_FILENAME).read_text(encoding="utf-8"))
    assert [row["source_origin"] for row in sources] == ["cited"]


# ---------------------------------------------------------------------------
# JSON repair
# ---------------------------------------------------------------------------


def test_lenient_json_accepts_raw_newlines_in_strings():
    obj = dr.extract_json_object('{"actors": [{"name": "X", "description": "line1\nline2"}]}')
    assert obj == {"actors": [{"name": "X", "description": "line1\nline2"}]}


def test_trailing_comma_repair_is_string_aware():
    obj = dr.extract_json_object('{"a": "x, }", "b": [1,2,],}')
    assert obj == {"a": "x, }", "b": [1, 2]}
    assert dr._strip_trailing_commas('{"k": "a,]", "l": [1, ],\n}') == '{"k": "a,]", "l": [1 ]\n}'


@pytest.mark.parametrize("text,expected", [
    ('{"actors": [{"name": "X", "goals": ["a', {"actors": [{"name": "X"}]}),
    ('{"a": {"b": 1}, "c": {"d"', {"a": {"b": 1}}),
])
def test_truncation_repair_closes_with_boundary_stack(text, expected):
    assert dr.extract_json_object(text) == expected


def test_scanner_recovers_json_after_stray_prose_brace():
    text = ('Here is my analysis {of the situation.\n'
            '{"actors": [{"name": "X"}], "sources": []}')
    assert dr.extract_json_object(text) == {"actors": [{"name": "X"}], "sources": []}


def test_scanner_restarts_are_bounded():
    started = time.monotonic()
    assert list(dr._iter_balanced_json_objects("{" * 20000)) == []
    assert time.monotonic() - started < 5.0


# ---------------------------------------------------------------------------
# strip_think
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("raw,expected", [
    ("reasoning here...</think>\n# Report\nbody", "# Report\nbody"),
    ("a</THINK>b<think>c</think>d", "bd"),
    ("<think>x</think>kept", "kept"),
    ("answer<think>truncated reasoning", "answer"),
    ("r1</think>r2</think>final", "final"),
    ("plain text", "plain text"),
])
def test_strip_think_handles_orphan_closer(raw, expected):
    assert dr.strip_think(raw) == expected


# ---------------------------------------------------------------------------
# Prediction Market Signals section is upserted, never duplicated
# ---------------------------------------------------------------------------


def test_strip_markdown_h2_section_respects_boundaries_and_fences():
    report = (
        "# Title\n\nBody.\n\n"
        "## Prediction Market Signals\n\n> disclaimer\n\n"
        "### Prediction Market Signals (Polymarket)\n\n| # | q |\n\n"
        "## Visual Annex\n\n```\n## Prediction Market Signals\n```\n"
    )
    stripped = dr._strip_markdown_h2_section(report, "Prediction Market Signals")
    assert stripped == (
        "# Title\n\nBody.\n\n"
        "## Visual Annex\n\n```\n## Prediction Market Signals\n```\n"
    )


def test_prediction_market_section_append_is_idempotent(tmp_path, monkeypatch):
    market = {
        "market_id": "691340",
        "question": "AI bubble burst in 2026?",
        "implied_yes_prob": 0.1545,
        "volume": 2_310_000.0,
        "url": "https://polymarket.com/event/ai-bubble-burst-in-2026",
        "end_date": "2026-12-31T00:00:00Z",
    }
    (tmp_path / dr.PREDICTION_MARKET_CANDIDATES_FILENAME).write_text(
        json.dumps({"captured_at": "2026-07-11T00:00:00Z",
                    "queries": ["AI bubble 2026"], "markets": [market]}) + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(dr, "_PM_TRANSPORT_UNAVAILABLE", False)
    monkeypatch.setattr(dr, "_pm_resolve_queries", lambda *_a, **_k: [])
    monkeypatch.setattr(dr, "score_market_relevance", lambda *_a, **_k: {})
    monkeypatch.setenv("PREDICTION_MARKETS_ENABLED", "true")
    monkeypatch.setenv("PREDICTION_MARKETS_PRICE_HISTORY", "false")
    report_path = tmp_path / dr.REPORT_FILENAME
    report = ("# Report\n\nOur external calibration is Polymarket market 691340 "
              "at 15.45%.\n\n## Visual Annex\n\n![c](charts/c.png)\n")
    report_path.write_text(report, encoding="utf-8")

    for _attempt in range(2):
        dr._collect_prediction_markets(
            tmp_path, "Will the AI boom unwind in 2026?",
            report_path.read_text(encoding="utf-8"), {}, _Log(), model_name="test")

    final = report_path.read_text(encoding="utf-8")
    assert len(re.findall(r"^## Prediction Market Signals$", final, re.MULTILINE)) == 1
    assert len(re.findall(r"^### Prediction Market Signals \(Polymarket\)$",
                          final, re.MULTILINE)) == 1
    assert "## Visual Annex" in final and "691340" in final


# ---------------------------------------------------------------------------
# ProgressLog lifecycle
# ---------------------------------------------------------------------------


def test_progress_log_write_after_close_goes_to_stdout_only(tmp_path, capsys):
    path = tmp_path / "progress.log"
    log = dr.ProgressLog(path)
    log.write("stage", "before close")
    log.close()
    log.close()  # idempotent
    log.write("warn", "late worker line")

    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1 and lines[0].endswith("[stage] before close")
    out = capsys.readouterr().out
    assert "[warn] late worker line" in out
    assert log.closed is True


def test_progress_log_collapses_embedded_newlines(tmp_path):
    path = tmp_path / "progress.log"
    log = dr.ProgressLog(path)
    log.write("error", "Traceback (most recent call last):\n  File x\nValueError: bad\n")
    log.close()

    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    assert re.match(r"^\S+ \[error\] Traceback \(most recent call last\): \| File x \| ValueError: bad$",
                    lines[0])


def test_progress_log_survives_broken_stdout_pipe(tmp_path, monkeypatch):
    path = tmp_path / "progress.log"
    log = dr.ProgressLog(path)

    def broken_print(*_args, **_kwargs):
        raise BrokenPipeError(32, "Broken pipe")

    monkeypatch.setattr("builtins.print", broken_print)
    log.write("ok", "parent went away")
    log.close()
    log.write("ok", "and after close")

    assert path.read_text(encoding="utf-8").rstrip().endswith("[ok] parent went away")


# ---------------------------------------------------------------------------
# Extract-only salvage keeps the positional source ledger (round 3, C40)
# ---------------------------------------------------------------------------

_V3_SALVAGE_REPORT = (
    "# Report\n\n## Findings\n\nCapacity reached 100 GW [S1]. Analysts expect growth [S2]. "
    "Grid queues lengthen [S3].\n\n" + "Supporting evidence text. " * 40 + "\n\n## References\n\n"
    "- [S1] IEA capacity — https://iea.example.org/a (tier 1; fetched)\n"
    "- [S2] Blog snippet — https://blog.example.com/b (tier 3; search snippet)\n"
    "- [S3] Utility filing — https://ferc.example.gov/c (tier 1; fetched)\n")


def _v3_ledger_row(key, url, tier, origin):
    return {"source_id": key, "url": url, "title": key.upper(), "tier": tier, "date": None,
            "source_origin": origin, "reachable": True if origin == "fetched" else None,
            "supports": [], "independent": None}


@pytest.mark.parametrize("origins", [
    ("fetched", "cited", "fetched"),  # v3 mix: the snippet-only row sits between fetched rows
    ("cited", "cited", "cited"),      # no fetched row at all: never swapped for model rows
])
def test_extract_only_keeps_an_existing_positional_sources_json_verbatim(
        tmp_path, monkeypatch, origins):
    (tmp_path / dr.REPORT_FILENAME).write_text(_V3_SALVAGE_REPORT, encoding="utf-8")
    ledger = [
        _v3_ledger_row("a", "https://iea.example.org/a", "S1", origins[0]),
        _v3_ledger_row("b", "https://blog.example.com/b", "S3", origins[1]),
        _v3_ledger_row("c", "https://ferc.example.gov/c", "S1", origins[2]),
    ]
    ledger_bytes = json.dumps(ledger, ensure_ascii=False, indent=2).encode("utf-8") + b"\n"
    (tmp_path / dr.SOURCES_FILENAME).write_bytes(ledger_bytes)
    obj = {"actors": [{"name": "IEA", "type": "Organization"}],
           "key_events": [{"date": "2026-01-01", "event": "Survey published"}],
           "sources": [{"url": "https://model.example.net/x", "title": "M", "tier": "S2"}]}
    monkeypatch.setattr(dr, "extract_complete_structured_tool_free",
                        lambda *_a, **_k: ("{}", obj, [], False))
    monkeypatch.setattr(dr, "_collect_prediction_markets", lambda *_a, **_k: None)
    monkeypatch.setattr(dr, "_render_research_charts", lambda *_a, **_k: {})
    meta: dict = {}
    log = dr.ProgressLog(tmp_path / "extract.log")

    rc = dr.run_extract_only("Q", tmp_path, _extract_only_args(), meta, log, lambda: None)

    assert rc == 0 and meta["status"] == "completed"
    assert (tmp_path / dr.SOURCES_FILENAME).read_bytes() == ledger_bytes
    refs = re.findall(r"^- \[S(\d+)\] .*? — (\S+) \(", _V3_SALVAGE_REPORT, re.M)
    assert len(refs) == 3 and all(ledger[int(n) - 1]["url"] == url for n, url in refs)
    actors = json.loads((tmp_path / dr.ACTORS_FILENAME).read_text(encoding="utf-8"))
    assert [row["name"] for row in actors["actors"]] == ["IEA"] and "sources" not in actors
    assert json.loads((tmp_path / dr.TIMELINE_FILENAME).read_text(encoding="utf-8")) == obj["key_events"]
    assert meta["sources_count"] == 3 and meta["source_tiers"]["s1_count"] == 2


@pytest.mark.parametrize("raw", [None, "", "v3", "linear", " Linear ", "LINEAR", "legacy", "deerflow", "agentic",
                                 "linear-v2"])
def test_the_bridge_runs_the_engine_the_orchestrator_selected(raw, monkeypatch):
    """PR #2 intent (selectors must agree), under the v3 contract: the parent
    normalises RESEARCH_ENGINE (default v3, unknown -> v3) and passes the
    canonical value to the child, which must resolve it to the same engine."""
    from app.services import pipeline_orchestrator as po

    engine = po.resolve_research_engine(raw)
    monkeypatch.setenv("RESEARCH_ENGINE", engine)
    assert dr._resolve_research_engine() == engine
