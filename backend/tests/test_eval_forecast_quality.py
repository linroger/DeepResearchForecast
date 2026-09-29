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
    assert result["judge_identity"] == {"provider": None, "model": None}


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
                               usage=None)


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


def test_judge_client_for_other_provider_is_isolated(judge_transport):
    judge = ev._build_judge_client("deepseek", "sk-ds")
    assert judge.provider == "deepseek" and (judge.use_cache, judge._pinned) == (False, True)
    assert judge.model != "primary-strong-alias"
    result = ev.judge_report(judge, "report", {"name": "t"}, "RUBRIC", k=2)
    assert [c["model"] for c in judge_transport.calls] == [judge.model, judge.model]
    assert result["judge_identity"] == {"provider": "deepseek", "model": judge.model}


def test_output_records_judge_identity(fake_llm, tmp_path, monkeypatch):
    judge = fake_llm(json_responses=[dict.fromkeys(ev.RUBRIC_DIMENSIONS, 3)] * 2,
                     provider="kimi", model="kimi-judge")
    result = ev.judge_report(judge, "report", {"name": "t"}, "RUBRIC", k=1)
    assert result["judge_identity"] == {"provider": "kimi", "model": "kimi-judge"}

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
    identity = {"provider": "kimi", "model": "kimi-judge"}
    assert written["judge_identity"] == identity
    assert written["scenarios"]["eval10-identity"]["judge_identity"] == identity


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
