"""Offline unit tests for the forecast-quality eval harness (EXECPLAN2 I-7-7).

All tests are offline: the pure scoring logic (clamp / normalize / aggregate /
baseline-gate / objective-signals / rubric+scenario parsing) is exercised with no
LLM, and the live judge path is driven by the FakeLLMClient fixture. Also asserts
the committed rubric/scenario/baseline fixtures are well-formed and point at real
demo reports — so `run` works out-of-the-box.
"""

import argparse
import json
import os
import sys
from types import SimpleNamespace

import pytest

# eval harness lives in backend/scripts/
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))

import eval_forecast_quality as ev  # noqa: E402

REPO_ROOT = ev.REPO_ROOT


# ----------------------------------------------------------------- clamp_score
def test_clamp_score_bounds_and_garbage():
    assert ev.clamp_score(3) == 3.0
    assert ev.clamp_score(9) == 5.0          # above max
    assert ev.clamp_score(-2) == 0.0         # below min
    assert ev.clamp_score(None) == 0.0       # missing → worst
    assert ev.clamp_score("nope") == 0.0     # non-numeric → worst
    assert ev.clamp_score(float("nan")) == 0.0
    assert ev.clamp_score(float("inf")) == 0.0
    assert ev.clamp_score("4.5") == 4.5      # numeric string ok


# -------------------------------------------------------- normalize_judge_scores
def test_normalize_flat_and_nested_and_missing():
    flat = ev.normalize_judge_scores({"groundedness": 4, "coverage": 5, "calibration": 3,
                                      "contradiction": 4, "citation_density": 2, "extra": 9})
    assert flat == {"groundedness": 4.0, "coverage": 5.0, "calibration": 3.0,
                    "contradiction": 4.0, "citation_density": 2.0}
    nested = ev.normalize_judge_scores({"scores": {"groundedness": 5}})
    assert nested["groundedness"] == 5.0 and nested["coverage"] == 0.0  # missing → 0
    assert ev.normalize_judge_scores("garbage") == {d: 0.0 for d in ev.RUBRIC_DIMENSIONS}


# ----------------------------------------------------------------- aggregate
def test_aggregate_mean_stdev_and_empty():
    samples = [
        {d: 4 for d in ev.RUBRIC_DIMENSIONS},
        {d: 2 for d in ev.RUBRIC_DIMENSIONS},
    ]
    agg = ev.aggregate_scores(samples)
    assert agg["groundedness"]["mean"] == 3.0
    assert agg["groundedness"]["min"] == 2.0 and agg["groundedness"]["max"] == 4.0
    assert agg["groundedness"]["n"] == 2
    assert agg["groundedness"]["stdev"] == 1.0
    empty = ev.aggregate_scores([])
    assert empty["coverage"] == {"mean": 0.0, "stdev": 0.0, "min": 0.0, "max": 0.0, "n": 0}


# ----------------------------------------------------------- compare_vs_baseline
def test_compare_pass_fail_and_missing():
    agg = {d: {"mean": 3.0} for d in ev.RUBRIC_DIMENSIONS}
    # baseline equal → pass (within tolerance)
    g = ev.compare_vs_baseline(agg, {d: 3.0 for d in ev.RUBRIC_DIMENSIONS}, default_tolerance=0.5)
    assert g["passed"] is True and g["missing_baseline"] is False
    # one dim regressed beyond tolerance → fail
    bad = {d: 3.0 for d in ev.RUBRIC_DIMENSIONS}
    bad["coverage"] = 4.0  # mean 3.0 < 4.0-0.5=3.5 → fail
    g2 = ev.compare_vs_baseline(agg, bad, default_tolerance=0.5)
    assert g2["passed"] is False
    assert g2["dimensions"]["coverage"]["passed"] is False
    assert g2["dimensions"]["coverage"]["delta"] == -1.0
    # within tolerance → pass
    near = {d: 3.4 for d in ev.RUBRIC_DIMENSIONS}
    assert ev.compare_vs_baseline(agg, near, default_tolerance=0.5)["passed"] is True
    # no baseline → passed None
    none_gate = ev.compare_vs_baseline(agg, None)
    assert none_gate["passed"] is None and none_gate["missing_baseline"] is True
    # per-baseline tolerance override
    tol_base = {d: 3.0 for d in ev.RUBRIC_DIMENSIONS}
    tol_base["coverage"] = 4.0
    tol_base["tolerance"] = 1.5  # 3.0 >= 4.0-1.5=2.5 → pass
    assert ev.compare_vs_baseline(agg, tol_base)["passed"] is True


def test_malformed_judge_can_only_fail_gate():
    """A judge returning garbage → all-zero → must fail a non-trivial baseline."""
    agg = ev.aggregate_scores([ev.normalize_judge_scores("garbage")])
    gate = ev.compare_vs_baseline(agg, {d: 3.0 for d in ev.RUBRIC_DIMENSIONS}, default_tolerance=0.5)
    assert gate["passed"] is False


# ----------------------------------------------------------- objective_signals
def test_objective_signals_uses_citation_audit_and_forecast():
    report = "增长率为 35% [S1]\n石油出口下跌 80%\n# 标题 2030年"
    forecast = {"scenarios": [{"probability": 0.6}, {"probability": 0.4}]}
    sig = ev.objective_signals(report, forecast)
    assert sig["quantitative_claims"] >= 2
    assert 0.0 <= sig["citation_coverage"] <= 1.0
    assert sig["scenario_count"] == 2
    assert sig["probability_sum"] == 1.0
    assert sig["report_chars"] == len(report)
    # no forecast → no scenario fields, still returns citation signals
    sig2 = ev.objective_signals(report)
    assert "scenario_count" not in sig2 and "citation_coverage" in sig2


# ----------------------------------------------------------------- parse_rubric
def test_parse_rubric_committed_file_has_all_dims():
    text = open(ev.RUBRIC_PATH, encoding="utf-8").read()
    parsed = ev.parse_rubric(text)
    for dim in ev.RUBRIC_DIMENSIONS:
        assert dim in parsed and parsed[dim].strip(), f"rubric missing {dim}"


def test_parse_rubric_ignores_noncanonical_headings():
    md = "## 1. groundedness\nfoo\n## random\nbar\n## coverage\nbaz"
    parsed = ev.parse_rubric(md)
    assert set(parsed) == {"groundedness", "coverage"}
    assert parsed["groundedness"] == "foo"


# ----------------------------------------------------------------- load_scenario
def test_load_scenario_requires_name(tmp_path):
    p = tmp_path / "bad.json"
    p.write_text(json.dumps({"question": "x"}), encoding="utf-8")
    with pytest.raises(ValueError):
        ev.load_scenario(str(p))


# ------------------------------------------------------------- resolve_report_path
def test_resolve_report_path_relative_and_pipeline(tmp_path):
    s = {"name": "x", "report_path": "docs/demos/us-iran-2026/report.md"}
    rp = ev.resolve_report_path(s, REPO_ROOT)
    assert rp.endswith("docs/demos/us-iran-2026/report.md") and os.path.isabs(rp)
    # EVAL-10: a pipeline without a pipeline_state.json has no report to score; the stale
    # uploads/pipelines/<id>/report/report.md guess (a path no run writes) is gone.
    s2 = {"name": "y", "pipeline_id": "pipe_abc"}
    rp2 = ev.resolve_report_path(s2, REPO_ROOT, pipelines_dir=str(tmp_path / "pipelines"),
                                 reports_dir=str(tmp_path / "reports"))
    assert rp2 is None
    assert ev.resolve_report_path({"name": "z"}, REPO_ROOT) is None


def _write_pipeline_state(pipelines, pid, state):
    folder = pipelines / pid
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "pipeline_state.json").write_text(
        state if isinstance(state, str) else json.dumps(state), encoding="utf-8")


def test_resolve_report_path_via_pipeline_state(tmp_path, monkeypatch):
    pipelines, reports = tmp_path / "pipelines", tmp_path / "reports"
    _write_pipeline_state(pipelines, "pipe_abc", {"pipeline_id": "pipe_abc", "report_id": "report_xyz"})
    report_dir = reports / "report_xyz"
    report_dir.mkdir(parents=True)
    (report_dir / "full_report.md").write_text("# Published report\n\nBody 35% [S1]", encoding="utf-8")
    (report_dir / "forecast.json").write_text(json.dumps({"scenarios": [{"probability": 1.0}]}),
                                              encoding="utf-8")
    dirs = {"pipelines_dir": str(pipelines), "reports_dir": str(reports)}

    rp = ev.resolve_report_path({"name": "y", "pipeline_id": "pipe_abc"}, REPO_ROOT, **dirs)
    assert rp == os.path.join(str(reports), "report_xyz", "full_report.md")
    report_md, forecast = ev._load_report_and_forecast(rp)  # the real report and its forecast
    assert report_md.startswith("# Published report") and forecast["scenarios"][0]["probability"] == 1.0

    # defaults come from Config.PIPELINE_DATA_DIR and Config.UPLOAD_FOLDER/reports
    from app.config import Config
    monkeypatch.setattr(Config, "PIPELINE_DATA_DIR", str(pipelines), raising=False)
    monkeypatch.setattr(Config, "UPLOAD_FOLDER", str(tmp_path), raising=False)
    assert ev.resolve_report_path({"name": "y", "pipeline_id": "pipe_abc"}, REPO_ROOT) == rp

    # None when the state is absent, unreadable, names no report, or an id is unsafe
    _write_pipeline_state(pipelines, "pipe_noreport", {"pipeline_id": "pipe_noreport"})
    _write_pipeline_state(pipelines, "pipe_garbled", "{not json")
    _write_pipeline_state(pipelines, "pipe_list", ["report_xyz"])
    _write_pipeline_state(pipelines, "pipe_escape", {"report_id": "../../etc"})
    for pid in ("pipe_missing", "pipe_noreport", "pipe_garbled", "pipe_list", "pipe_escape",
                "../pipelines/pipe_abc"):
        assert ev.resolve_report_path({"name": "n", "pipeline_id": pid}, REPO_ROOT, **dirs) is None, pid


# ------------------------------------------------------------- build_judge_messages
def test_build_judge_messages_deterministic_and_truncates():
    msgs = ev.build_judge_messages("RUBRIC", "x" * 60000, {"name": "n", "expected_outcome": {"a": 1}},
                                   {"citation_coverage": 0.5})
    assert msgs[0]["role"] == "system" and "RUBRIC" in msgs[0]["content"]
    assert "truncated" in msgs[1]["content"]
    assert "citation_coverage" in msgs[1]["content"]
    assert '"a": 1' in msgs[1]["content"]  # expected_outcome embedded
    # deterministic
    msgs2 = ev.build_judge_messages("RUBRIC", "x" * 60000, {"name": "n", "expected_outcome": {"a": 1}},
                                    {"citation_coverage": 0.5})
    assert msgs == msgs2


# ------------------------------------------------------- judge_report (fake LLM)
def test_judge_report_aggregates_k_passes(fake_llm):
    judge = fake_llm(json_responses=[
        {"groundedness": 4, "coverage": 4, "calibration": 4, "contradiction": 4, "citation_density": 2},
        {"groundedness": 2, "coverage": 4, "calibration": 4, "contradiction": 4, "citation_density": 2},
        {"groundedness": 3, "coverage": 4, "calibration": 4, "contradiction": 4, "citation_density": 2},
    ])
    result = ev.judge_report(judge, "report 35% [S1]", {"name": "t"}, "RUBRIC", k=3)
    assert result["k"] == 3
    assert result["aggregate"]["groundedness"]["mean"] == 3.0  # (4+2+3)/3
    assert result["aggregate"]["coverage"]["mean"] == 4.0
    assert len(judge.calls) == 3
    assert all(c["temperature"] == 0.0 for c in judge.calls)  # judge at temp 0


def test_judge_report_degrades_on_judge_exception():
    class Boom:
        def chat_json(self, **kw):
            raise RuntimeError("provider down")
    result = ev.judge_report(Boom(), "report", {"name": "t"}, "RUBRIC", k=2)
    # every pass failed → all-zero samples, no crash
    assert result["k"] == 2
    assert result["aggregate"]["groundedness"]["mean"] == 0.0
    assert result["judge_identity"] == {"provider": None, "model": None, "served_models": []}


# ------------------------------------------------------ EVAL-10: isolated judge
_JUDGE_REPLY = json.dumps({"groundedness": 4, "coverage": 3, "calibration": 4,
                           "contradiction": 5, "citation_density": 2})


class _CountingTransport:
    """Fake OpenAI client: every create() is one provider call; replies with a rubric JSON."""

    def __init__(self):
        self.calls = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        self.calls.append(kwargs)
        message = SimpleNamespace(content=_JUDGE_REPLY, tool_calls=[])
        return SimpleNamespace(choices=[SimpleNamespace(message=message, finish_reason="stop")],
                               usage=None, model=f"{kwargs['model']}-served")


@pytest.fixture
def judge_transport(monkeypatch):
    """A default-provider (minimax) setup with the process cache and tier routing ON."""
    from app.config import Config
    from app.utils import llm_client as lc
    from app.utils import telemetry as tel

    for name in ("LLM_FALLBACK_PROVIDER", "LLM_FALLBACK_MODEL", "LLM_FALLBACK_BASE_URL",
                 "LLM_FALLBACK_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    for attr, value in (("LLM_PROVIDER", "minimax"), ("LLM_MODEL_NAME", "MiniMax-M3"),
                        ("LLM_API_KEY", "sk-test"), ("LLM_BASE_URL", "http://127.0.0.1:1/v1"),
                        ("LLM_CACHE_ENABLED", True), ("LLM_TIERED_ROUTING", True),
                        ("LLM_STRONG_MODEL", "primary-strong-alias"),
                        ("LLM_RUN_BUDGET_TOKENS", 0), ("LLM_RUN_BUDGET_USD", 0.0)):
        monkeypatch.setattr(Config, attr, value, raising=False)
    monkeypatch.setattr(tel.LLMCache, "_store", {})
    monkeypatch.setattr(tel.LLMCache, "_order", [])
    transport = _CountingTransport()
    monkeypatch.setattr(lc.LLMClient, "_build_openai_client",
                        staticmethod(lambda provider, api_key, base_url: transport))
    return transport


def test_k_passes_are_real_calls(judge_transport):
    from app.utils.llm_client import LLMClient

    # what the unisolated client did: the k identical temperature-0 passes collapse into one call
    shared = LLMClient()
    for _ in range(3):
        ev.judge_once(shared, ev.build_judge_messages("RUBRIC", "report", {"name": "t"}, {}))
    assert len(judge_transport.calls) == 1

    judge = ev._build_judge_client(None, None)
    assert (judge.use_cache, judge._pinned) == (False, True)
    result = ev.judge_report(judge, "report", {"name": "t"}, "RUBRIC", k=3)
    assert len(judge_transport.calls) == 1 + 3  # k=3 → 3 provider calls
    assert result["k"] == 3 and result["aggregate"]["contradiction"]["mean"] == 5.0
    # pinned: the judge's own model is sent, never the primary's tier alias
    assert [c["model"] for c in judge_transport.calls[1:]] == ["MiniMax-M3"] * 3
    assert judge_transport.calls[0]["model"] == "primary-strong-alias"
    assert result["judge_identity"] == {"provider": "minimax", "model": "MiniMax-M3",
                                        "served_models": ["MiniMax-M3-served"]}


def test_judge_client_for_other_provider_is_isolated(judge_transport):
    judge = ev._build_judge_client("deepseek", "sk-ds")
    assert judge.provider == "deepseek" and (judge.use_cache, judge._pinned) == (False, True)
    assert judge.model != "primary-strong-alias"
    result = ev.judge_report(judge, "report", {"name": "t"}, "RUBRIC", k=2)
    assert [c["model"] for c in judge_transport.calls] == [judge.model, judge.model]
    assert result["judge_identity"] == {"provider": "deepseek", "model": judge.model,
                                        "served_models": [f"{judge.model}-served"]}


def _cli_run(captured, stdout):
    def fake_run(cmd, **kwargs):
        captured.append(cmd)
        return SimpleNamespace(returncode=0, stdout=stdout, stderr="")
    return fake_run


def test_cli_judge_identity_records_what_served(judge_transport, monkeypatch):
    """A CLI judge is recorded with the model it was asked for, or None, never LLM_MODEL_NAME."""
    from app.config import Config
    from app.utils import llm_client as lc

    envelope = json.dumps({"type": "result", "subtype": "success", "is_error": False,
                           "result": _JUDGE_REPLY,
                           "modelUsage": {"claude-opus-4-8": {"outputTokens": 7}}})
    captured = []
    monkeypatch.setattr(lc.subprocess, "run", _cli_run(captured, envelope))
    monkeypatch.setattr(Config, "LLM_PROVIDER", "claude-cli", raising=False)
    monkeypatch.setattr(Config, "LLM_MODEL_NAME", "gpt-4o-mini", raising=False)

    # the default claude-cli judge inherits a non-claude LLM_MODEL_NAME: no --model is passed,
    # so the CLI serves its account default and that is what the identity records
    judge = ev._build_judge_client(None, None)
    assert judge.provider == "claude-cli" and judge.model == Config.LLM_MODEL_NAME
    result = ev.judge_report(judge, "report", {"name": "t"}, "RUBRIC", k=2)
    assert len(captured) == 2 and not any("--model" in cmd for cmd in captured)
    assert result["aggregate"]["contradiction"]["mean"] == 5.0
    assert result["judge_identity"] == {"provider": "claude-cli", "model": None,
                                        "served_models": ["claude-opus-4-8"]}
    assert result["judge_identity"]["model"] != Config.LLM_MODEL_NAME

    # a claude model id is passed to the CLI, so it is the recorded requested model
    monkeypatch.setattr(Config, "LLM_MODEL_NAME", "claude-sonnet-4-5", raising=False)
    judge = ev._build_judge_client(None, None)
    result = ev.judge_report(judge, "report", {"name": "t"}, "RUBRIC", k=1)
    assert captured[-1][captured[-1].index("--model") + 1] == "claude-sonnet-4-5"
    assert result["judge_identity"] == {"provider": "claude-cli", "model": "claude-sonnet-4-5",
                                        "served_models": ["claude-opus-4-8"]}

    # codex exec is never given a model and reports none: a minimax primary's model is not it
    monkeypatch.setattr(Config, "LLM_PROVIDER", "minimax", raising=False)
    monkeypatch.setattr(Config, "LLM_MODEL_NAME", "MiniMax-M3", raising=False)
    monkeypatch.setattr(lc.subprocess, "run", _cli_run(captured, _JUDGE_REPLY))
    judge = ev._build_judge_client("codex-cli", None)
    result = ev.judge_report(judge, "report", {"name": "t"}, "RUBRIC", k=1)
    assert captured[-1][:2] == ["codex", "exec"] and "--model" not in captured[-1]
    assert result["judge_identity"] == {"provider": "codex-cli", "model": None, "served_models": []}
    assert judge_transport.calls == []  # no OpenAI-compatible transport was used


def test_output_records_judge_identity(fake_llm, tmp_path, monkeypatch):
    judge = fake_llm(json_responses=[dict.fromkeys(ev.RUBRIC_DIMENSIONS, 3)] * 2,
                     provider="kimi", model="kimi-judge")
    result = ev.judge_report(judge, "report", {"name": "t"}, "RUBRIC", k=1)
    assert result["judge_identity"] == {"provider": "kimi", "model": "kimi-judge", "served_models": []}

    # the `run` command records it for the whole run and for every scored scenario
    report = tmp_path / "report.md"
    report.write_text("# Report\n\nBody", encoding="utf-8")
    scenarios = tmp_path / "scenarios"
    scenarios.mkdir()
    (scenarios / "s.json").write_text(json.dumps({"name": "eval10-identity",
                                                  "report_path": str(report)}), encoding="utf-8")
    monkeypatch.setattr(ev, "_build_judge_client", lambda provider, api_key: judge)
    out = tmp_path / "eval_report.json"
    args = argparse.Namespace(live=True, scenarios_dir=str(scenarios), judge_provider=None,
                              api_key=None, k=1, tolerance=0.5, update_baseline=False, out=str(out))
    assert ev.cmd_run(args) == 0
    written = json.loads(out.read_text(encoding="utf-8"))
    identity = {"provider": "kimi", "model": "kimi-judge", "served_models": []}
    assert written["judge_identity"] == identity
    assert written["scenarios"]["eval10-identity"]["judge_identity"] == identity
    assert "judge_mismatch" not in written  # the baseline in use names no judge


def _run_args(scenarios, out, *, update_baseline=False):
    return argparse.Namespace(live=True, scenarios_dir=str(scenarios), judge_provider=None,
                              api_key=None, k=1, tolerance=0.5,
                              update_baseline=update_baseline, out=str(out))


def test_baseline_records_judge_and_flags_a_different_judge(fake_llm, tmp_path, monkeypatch, capsys):
    report = tmp_path / "report.md"
    report.write_text("# Report\n\nBody", encoding="utf-8")
    scenarios = tmp_path / "scenarios"
    scenarios.mkdir()
    (scenarios / "s.json").write_text(json.dumps({"name": "eval10-baseline",
                                                  "report_path": str(report)}), encoding="utf-8")
    baseline_path = tmp_path / "baseline_scores.json"
    baseline_path.write_text(json.dumps({"_comment": "floors"}), encoding="utf-8")
    monkeypatch.setattr(ev, "BASELINE_PATH", str(baseline_path))
    scores = dict.fromkeys(ev.RUBRIC_DIMENSIONS, 3)

    def judge_of(provider, model):
        judge = fake_llm(json_responses=[scores], provider=provider, model=model)
        monkeypatch.setattr(ev, "_build_judge_client", lambda provider, api_key: judge)

    # --update-baseline writes the judge next to the scores it produced
    judge_of("kimi", "kimi-judge")
    assert ev.cmd_run(_run_args(scenarios, tmp_path / "a.json", update_baseline=True)) == 0
    written = json.loads(baseline_path.read_text(encoding="utf-8"))
    assert written["_comment"] == "floors"
    assert written["eval10-baseline"]["judge_identity"] == {
        "provider": "kimi", "model": "kimi-judge", "served_models": []}

    # the same judge compares cleanly
    judge_of("kimi", "kimi-judge")
    assert ev.cmd_run(_run_args(scenarios, tmp_path / "b.json")) == 0
    same = json.loads((tmp_path / "b.json").read_text(encoding="utf-8"))
    assert same["judge_mismatch"] is False
    assert same["scenarios"]["eval10-baseline"]["judge_mismatch"] is False
    capsys.readouterr()

    # another judge is flagged and warned about; the dimension gate itself is unchanged
    judge_of("deepseek", "deepseek-chat")
    assert ev.cmd_run(_run_args(scenarios, tmp_path / "c.json")) == 0
    other = json.loads((tmp_path / "c.json").read_text(encoding="utf-8"))
    assert other["judge_mismatch"] is True
    assert other["scenarios"]["eval10-baseline"]["judge_mismatch"] is True
    assert other["scenarios"]["eval10-baseline"]["gate"]["passed"] is True
    assert "differs from the baseline's" in capsys.readouterr().err


def test_judge_mismatch_rules():
    base = {"provider": "claude-cli", "model": None, "served_models": ["claude-opus-4-8"]}
    assert ev.judge_mismatch(base, dict(base)) is False
    assert ev.judge_mismatch(base, {**base, "provider": "codex-cli"}) is True
    assert ev.judge_mismatch(base, {**base, "model": "claude-sonnet-4-5"}) is True
    # the CLI account default changed under an unchanged request
    assert ev.judge_mismatch(base, {**base, "served_models": ["claude-sonnet-4-5"]}) is True
    # unknown served models on either side are not evidence of a different judge
    assert ev.judge_mismatch(base, {**base, "served_models": []}) is False
    assert ev.judge_mismatch({"provider": "claude-cli", "model": None}, base) is False


def test_skipped_pipeline_scenario_names_the_pipeline(fake_llm, tmp_path, monkeypatch, capsys):
    from app.config import Config
    monkeypatch.setattr(Config, "PIPELINE_DATA_DIR", str(tmp_path / "pipelines"), raising=False)
    monkeypatch.setattr(Config, "UPLOAD_FOLDER", str(tmp_path), raising=False)
    _write_pipeline_state(tmp_path / "pipelines", "pipe_done", {"report_id": "report_gone"})
    scenarios = tmp_path / "scenarios"
    scenarios.mkdir()
    for name, body in (("no-state", {"pipeline_id": "pipe_nostate"}),
                       ("no-file", {"pipeline_id": "pipe_done"}),
                       ("nothing", {})):
        (scenarios / f"{name}.json").write_text(json.dumps({"name": name, **body}), encoding="utf-8")
    judge = fake_llm(provider="kimi", model="kimi-judge")
    monkeypatch.setattr(ev, "_build_judge_client", lambda provider, api_key: judge)
    out = tmp_path / "eval_report.json"
    assert ev.cmd_run(_run_args(scenarios, out)) == 0
    assert judge.calls == []
    skipped = json.loads(out.read_text(encoding="utf-8"))["scenarios"]

    assert skipped["no-state"]["pipeline_id"] == "pipe_nostate"
    assert skipped["no-state"]["report_path"] is None and skipped["no-state"]["skipped"] is True
    assert "pipeline pipe_nostate has no resolvable report" in skipped["no-state"]["reason"]
    # the state names a report whose full_report.md does not exist: the path is reported
    missing = os.path.join(str(tmp_path), "reports", "report_gone", "full_report.md")
    assert skipped["no-file"] == {"skipped": True, "report_path": missing, "pipeline_id": "pipe_done",
                                  "reason": f"report not found at {missing}"}
    assert skipped["nothing"]["reason"] == "scenario names neither a report_path nor a pipeline_id"
    printed = capsys.readouterr().out
    assert "[skip] no-state: pipeline pipe_nostate has no resolvable report" in printed


# ------------------------------------------------------ committed fixtures wiring
def test_committed_scenarios_load_and_point_to_real_reports():
    paths = ev.discover_scenarios(ev.SCENARIOS_DIR)
    assert len(paths) >= 2, "expected committed eval scenarios"
    for p in paths:
        sc = ev.load_scenario(p)
        rp = ev.resolve_report_path(sc, REPO_ROOT)
        assert rp and os.path.exists(rp), f"{sc['name']} report missing: {rp}"


def test_committed_baseline_covers_every_scenario():
    baseline = json.load(open(ev.BASELINE_PATH, encoding="utf-8"))
    for p in ev.discover_scenarios(ev.SCENARIOS_DIR):
        name = ev.load_scenario(p)["name"]
        assert name in baseline, f"baseline missing scenario {name}"
        for dim in ev.RUBRIC_DIMENSIONS:
            assert dim in baseline[name], f"baseline[{name}] missing {dim}"
