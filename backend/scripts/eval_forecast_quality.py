#!/usr/bin/env python3
"""Forecast-quality regression scoring via a rubric LLM-judge (EXECPLAN2 I-7-7).

The system's whole purpose is forecast quality, yet nothing measures whether a
report is grounded, covers scenarios, or stays calibrated — so a prompt/model
change that quietly produces vaguer or hallucinated forecasts is invisible until
a human reads the output. This harness turns that into a number: it scores each
report on five rubric dimensions (0-5) with an LLM-judge, averages k passes at
temperature 0, and gates each dimension against a committed baseline within a
tolerance, emitting per-dimension deltas.

OPTIONAL-DEGRADE / strictly opt-in: the live judge needs a real LLM (API spend),
so it runs ONLY when Config.EVAL_ENABLED is true or --live is passed. It is a
standalone script — nothing in the running pipeline imports it — and must never
be wired into default CI. The *pure* scoring logic (rubric parse, normalization,
aggregation, baseline gating, objective signals) is side-effect-free and
offline-unit-tested with a fake judge (see backend/tests/test_eval_forecast_quality.py).

Examples:
    # score one report against the rubric (live judge)
    python backend/scripts/eval_forecast_quality.py score \
        --report docs/demos/us-iran-2026/report.md --judge-provider claude-cli --live

    # run the committed scenario set + gate vs baseline
    EVAL_ENABLED=true python backend/scripts/eval_forecast_quality.py run --judge-provider claude-cli

    # accept intentional improvements as the new baseline
    EVAL_ENABLED=true python backend/scripts/eval_forecast_quality.py run \
        --judge-provider claude-cli --update-baseline
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
EVAL_DIR = os.path.join(REPO_ROOT, "backend", "tests", "eval")
SCENARIOS_DIR = os.path.join(EVAL_DIR, "scenarios")
RUBRIC_PATH = os.path.join(EVAL_DIR, "rubric.md")
BASELINE_PATH = os.path.join(EVAL_DIR, "baseline_scores.json")

# The five scored dimensions (mirrored in rubric.md). Order is fixed so judge
# prompts and aggregation stay consistent.
RUBRIC_DIMENSIONS: Tuple[str, ...] = (
    "groundedness", "coverage", "calibration", "contradiction", "citation_density",
)
SCORE_MIN, SCORE_MAX = 0.0, 5.0
DEFAULT_TOLERANCE = 0.5   # how far below baseline a dimension may drift before failing
DEFAULT_K = 3             # judge passes averaged per report


# ============================================================ pure scoring logic
# Everything in this block is deterministic and side-effect-free (no LLM, no
# network, no disk writes) so it can be unit-tested offline with a fake judge.

def clamp_score(v: Any) -> float:
    """Coerce a judge sub-score to a float clamped to [SCORE_MIN, SCORE_MAX].

    NaN / non-numeric / missing → SCORE_MIN (treated as worst, so a malformed
    judge reply can only fail a regression gate, never spuriously pass it).
    """
    try:
        f = float(v)
    except (TypeError, ValueError):
        return SCORE_MIN
    if math.isnan(f) or math.isinf(f):
        return SCORE_MIN
    return max(SCORE_MIN, min(SCORE_MAX, f))


def normalize_judge_scores(raw: Any) -> Dict[str, float]:
    """Extract the 5 rubric dimensions from a judge reply, clamped to [0,5].

    Accepts either a flat dict ({"groundedness": 4, ...}) or one nested under a
    "scores" key. Unknown keys are ignored; missing dimensions default to 0.0.
    """
    if isinstance(raw, dict) and isinstance(raw.get("scores"), dict):
        raw = raw["scores"]
    if not isinstance(raw, dict):
        raw = {}
    return {dim: clamp_score(raw.get(dim)) for dim in RUBRIC_DIMENSIONS}


def aggregate_scores(samples: List[Dict[str, float]]) -> Dict[str, Dict[str, float]]:
    """Aggregate k judge samples into per-dimension {mean, stdev, min, max, n}."""
    out: Dict[str, Dict[str, float]] = {}
    for dim in RUBRIC_DIMENSIONS:
        vals = [clamp_score(s.get(dim)) for s in samples if isinstance(s, dict)]
        if not vals:
            out[dim] = {"mean": 0.0, "stdev": 0.0, "min": 0.0, "max": 0.0, "n": 0}
            continue
        mean = sum(vals) / len(vals)
        stdev = (sum((v - mean) ** 2 for v in vals) / len(vals)) ** 0.5
        out[dim] = {
            "mean": round(mean, 3),
            "stdev": round(stdev, 3),
            "min": round(min(vals), 3),
            "max": round(max(vals), 3),
            "n": len(vals),
        }
    return out


def compare_vs_baseline(agg: Dict[str, Dict[str, float]],
                        baseline: Optional[Dict[str, Any]],
                        default_tolerance: float = DEFAULT_TOLERANCE) -> Dict[str, Any]:
    """Gate aggregated scores against a committed baseline within a tolerance.

    A dimension passes when ``mean >= baseline - tolerance``. With no baseline
    (first run) the gate is reported as ``missing_baseline=True`` and ``passed``
    is None (neither pass nor fail — caller decides; typically --update-baseline).
    Per-dimension ``tolerance`` may override the default via baseline["tolerance"].
    """
    if not baseline:
        return {"passed": None, "missing_baseline": True, "dimensions": {}}
    tol = default_tolerance
    if isinstance(baseline.get("tolerance"), (int, float)):
        tol = float(baseline["tolerance"])
    dims: Dict[str, Any] = {}
    all_pass = True
    for dim in RUBRIC_DIMENSIONS:
        mean = float(agg.get(dim, {}).get("mean", 0.0))
        base = baseline.get(dim)
        if base is None:
            dims[dim] = {"mean": mean, "baseline": None, "delta": None,
                         "tolerance": tol, "passed": None}
            continue
        base = float(base)
        passed = mean >= (base - tol)
        all_pass = all_pass and passed
        dims[dim] = {
            "mean": round(mean, 3),
            "baseline": round(base, 3),
            "delta": round(mean - base, 3),
            "tolerance": tol,
            "passed": passed,
        }
    return {"passed": all_pass, "missing_baseline": False, "dimensions": dims}


def objective_signals(report_markdown: str, forecast: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Deterministic, non-LLM anchors handed to the judge (and recorded).

    Reuses the heuristic citation-grounding audit (forecast_extractor.I-3-1) plus
    structured-forecast shape signals so the judge has objective ground truth to
    anchor groundedness / calibration / citation_density against, rather than
    scoring from vibes alone.
    """
    from app.services.forecast_extractor import audit_citation_grounding
    audit = audit_citation_grounding(report_markdown or "")
    sig: Dict[str, Any] = {
        "citation_coverage": audit.get("coverage"),
        "quantitative_claims": audit.get("quantitative_claims"),
        "cited_claims": audit.get("cited"),
        "report_chars": len(report_markdown or ""),
    }
    if isinstance(forecast, dict):
        scenarios = forecast.get("scenarios") or []
        sig["scenario_count"] = len(scenarios) if isinstance(scenarios, list) else 0
        try:
            sig["probability_sum"] = round(
                sum(float(s.get("probability", 0) or 0) for s in scenarios
                    if isinstance(s, dict)), 3)
        except (TypeError, ValueError):
            sig["probability_sum"] = None
    return sig


def parse_rubric(md_text: str) -> Dict[str, str]:
    """Parse rubric.md '## <dimension>' sections into {dimension: description}.

    Only the canonical RUBRIC_DIMENSIONS are returned; the section heading may be
    '## 1. groundedness' or '## groundedness'.
    """
    out: Dict[str, str] = {}
    current: Optional[str] = None
    buf: List[str] = []
    for line in (md_text or "").splitlines():
        if line.startswith("## "):
            if current:
                out[current] = "\n".join(buf).strip()
            heading = line[3:].strip().lstrip("0123456789. ").strip().lower()
            current = heading if heading in RUBRIC_DIMENSIONS else None
            buf = []
        elif current:
            buf.append(line)
    if current:
        out[current] = "\n".join(buf).strip()
    return out


def load_scenario(path: str) -> Dict[str, Any]:
    """Load + validate a scenario JSON. Requires 'name'; report_path/pipeline_id optional."""
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict) or not data.get("name"):
        raise ValueError(f"scenario {path} must be an object with a 'name'")
    return data


def discover_scenarios(scenarios_dir: str = SCENARIOS_DIR) -> List[str]:
    if not os.path.isdir(scenarios_dir):
        return []
    return sorted(
        os.path.join(scenarios_dir, fn)
        for fn in os.listdir(scenarios_dir)
        if fn.endswith(".json")
    )


def resolve_report_path(scenario: Dict[str, Any], repo_root: str = REPO_ROOT, *,
                        pipelines_dir: Optional[str] = None,
                        reports_dir: Optional[str] = None) -> Optional[str]:
    """Resolve a scenario's report to score: explicit report_path (rel to repo
    root) wins; else the report a pipeline_id's run produced.

    A pipeline never writes a report under its own folder: its pipeline_state.json
    names the report_id, and the published report is <reports_dir>/<report_id>/
    full_report.md (forecast.json sits beside it). ``pipelines_dir`` defaults to
    Config.PIPELINE_DATA_DIR and ``reports_dir`` to Config.UPLOAD_FOLDER/reports.
    None when the state file is missing or unreadable, names no report_id, or an
    id is not a safe path component.
    """
    rp = scenario.get("report_path")
    if rp:
        cand = rp if os.path.isabs(rp) else os.path.join(repo_root, rp)
        return cand
    pid = scenario.get("pipeline_id")
    if not pid:
        return None
    from app.config import Config
    from app.utils.security import contained_child
    if pipelines_dir is None:
        pipelines_dir = Config.PIPELINE_DATA_DIR
    if reports_dir is None:
        reports_dir = os.path.join(Config.UPLOAD_FOLDER, "reports")
    try:
        state_path = os.path.join(contained_child(pipelines_dir, pid, "pipeline"),
                                  "pipeline_state.json")
        state = _load_json(state_path)
        report_id = state.get("report_id") if isinstance(state, dict) else None
        if not report_id:
            return None
        return os.path.join(contained_child(reports_dir, report_id, "report"), "full_report.md")
    except (OSError, ValueError):  # ValueError covers bad JSON and UnsafeIdError
        return None


def build_judge_messages(rubric_text: str, report_markdown: str,
                         scenario: Dict[str, Any], signals: Dict[str, Any]) -> List[Dict[str, str]]:
    """Construct the judge chat messages. Deterministic given inputs."""
    report = report_markdown or ""
    if len(report) > 48000:
        report = report[:48000] + "\n…(truncated)…"
    expected = scenario.get("expected_outcome")
    sys_prompt = (
        "你是预测质量评审专家。请严格按给定 rubric 给一份预测报告打分。"
        "对每个维度给 0-5 的整数分（0=缺失/不合格，5=优秀）。"
        "只输出 JSON：{\"groundedness\":int,\"coverage\":int,\"calibration\":int,"
        "\"contradiction\":int,\"citation_density\":int,\"notes\":\"简短说明\"}。"
        "不要输出任何解释或 markdown 代码块。\n\n[RUBRIC]\n" + (rubric_text or "")
    )
    parts = [
        "[客观信号]（已用确定性方法预先计算，请据此锚定 groundedness/calibration/citation_density）：",
        json.dumps(signals, ensure_ascii=False),
    ]
    if expected:
        parts += ["\n[该情景的参考结局/关键信号]：", json.dumps(expected, ensure_ascii=False)]
    parts += ["\n[预测报告]\n" + report]
    return [
        {"role": "system", "content": sys_prompt},
        {"role": "user", "content": "\n".join(parts)},
    ]


# ============================================================ live judge (gated)

def judge_once(llm, messages: List[Dict[str, str]]) -> Dict[str, float]:
    """One judge pass at temperature 0; returns normalized 0-5 sub-scores."""
    raw = llm.chat_json(messages=messages, temperature=0.0, max_tokens=512)
    return normalize_judge_scores(raw)


def judge_report(llm, report_markdown: str, scenario: Dict[str, Any], rubric_text: str,
                 k: int = DEFAULT_K, forecast: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Score one report: k judge passes → aggregate + objective signals.

    Best-effort per pass — a judge call that raises or returns garbage degrades to
    an all-zero sample (which can only lower the score, never spuriously pass).
    """
    signals = objective_signals(report_markdown, forecast)
    messages = build_judge_messages(rubric_text, report_markdown, scenario, signals)
    samples: List[Dict[str, float]] = []
    for _ in range(max(1, k)):
        try:
            samples.append(judge_once(llm, messages))
        except Exception as e:  # noqa: BLE001 - degrade-safe: one bad pass != crash
            samples.append({dim: 0.0 for dim in RUBRIC_DIMENSIONS})
            print(f"  [warn] judge pass failed: {e}", file=sys.stderr)
    return {
        "scenario": scenario.get("name"),
        "aggregate": aggregate_scores(samples),
        "samples": samples,
        "signals": signals,
        "k": len(samples),
        "judge_identity": judge_identity(llm),
    }


def judge_identity(llm) -> Dict[str, Any]:
    """The judge's {provider, model}, recorded with every score so each score is
    attributable to the backbone that produced it (scores from different judges
    are not one series)."""
    return {"provider": getattr(llm, "provider", None), "model": getattr(llm, "model", None)}


def _load_json(path: str) -> Any:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _load_report_and_forecast(report_path: str) -> Tuple[str, Optional[Dict[str, Any]]]:
    with open(report_path, encoding="utf-8") as f:
        report_md = f.read()
    forecast = None
    fc_path = os.path.join(os.path.dirname(report_path), "forecast.json")
    if os.path.exists(fc_path):
        try:
            forecast = _load_json(fc_path)
        except Exception:  # noqa: BLE001
            forecast = None
    return report_md, forecast


def _build_judge_client(provider: Optional[str], api_key: Optional[str]):
    """Construct a per-instance LLMClient for the judge (never touches global Config).

    EVAL-10: the judge is isolated. pinned=True keeps its provider and model (no
    tier re-route, no silent failover to another backbone) and use_cache=False
    makes each of the k passes a real call; with the process-wide LLMCache on, the
    k identical temperature-0 requests collapsed into one call, and a malformed
    cached reply zeroed every sample (chat_json's re-ask hit the same entry).
    """
    from app.utils.llm_client import LLMClient
    from app.config import Config
    isolation: Dict[str, Any] = {"pinned": True, "use_cache": False}
    if not provider or provider == Config.LLM_PROVIDER:
        return LLMClient(**isolation)  # default global provider
    # mirror model_comparison._build_client_for for non-default providers
    meta = Config.PROVIDER_META.get(provider, {})
    kwargs: Dict[str, Any] = {"provider": provider}
    if meta.get("openai_compat"):
        key = (api_key or "").strip()
        if not key:
            key_env = meta.get("key_env")
            if key_env:
                key = os.environ.get(key_env, "").strip()
        if key:
            kwargs["api_key"] = key
        if meta.get("default_base"):
            kwargs["base_url"] = meta["default_base"]
        if meta.get("default_model"):
            kwargs["model"] = meta["default_model"]
    return LLMClient(**kwargs, **isolation)


def _eval_allowed(args) -> bool:
    """Live judging is opt-in: requires Config.EVAL_ENABLED or --live (cost guard)."""
    from app.config import Config
    return bool(getattr(Config, "EVAL_ENABLED", False) or getattr(args, "live", False))


# ============================================================ CLI commands

def cmd_score(args) -> int:
    if not _eval_allowed(args):
        print("eval is opt-in: set EVAL_ENABLED=true or pass --live (the judge "
              "calls a real LLM = API spend; never enable in default CI).")
        return 0
    rubric_text = open(RUBRIC_PATH, encoding="utf-8").read()
    report_md, forecast = _load_report_and_forecast(args.report)
    scenario = {"name": os.path.basename(args.report)}
    if args.scenario:
        scenario = load_scenario(args.scenario)
    llm = _build_judge_client(args.judge_provider, args.api_key)
    result = judge_report(llm, report_md, scenario, rubric_text, k=args.k, forecast=forecast)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def cmd_run(args) -> int:
    if not _eval_allowed(args):
        print("eval is opt-in: set EVAL_ENABLED=true or pass --live (the judge "
              "calls a real LLM = API spend; never enable in default CI).")
        return 0
    rubric_text = open(RUBRIC_PATH, encoding="utf-8").read()
    baseline = _load_json(BASELINE_PATH) if os.path.exists(BASELINE_PATH) else {}
    scenario_paths = discover_scenarios(args.scenarios_dir)
    if not scenario_paths:
        print(f"no scenarios in {args.scenarios_dir}", file=sys.stderr)
        return 2
    llm = _build_judge_client(args.judge_provider, args.api_key)

    report: Dict[str, Any] = {"scenarios": {}, "overall_passed": True,
                              "judge_identity": judge_identity(llm)}
    new_baseline: Dict[str, Any] = dict(baseline) if isinstance(baseline, dict) else {}
    for sp in scenario_paths:
        scenario = load_scenario(sp)
        name = scenario["name"]
        report_path = resolve_report_path(scenario)
        if not report_path or not os.path.exists(report_path):
            print(f"  [skip] {name}: report not found at {report_path}")
            report["scenarios"][name] = {"skipped": True, "report_path": report_path}
            continue
        report_md, forecast = _load_report_and_forecast(report_path)
        scored = judge_report(llm, report_md, scenario, rubric_text, k=args.k, forecast=forecast)
        gate = compare_vs_baseline(scored["aggregate"],
                                   baseline.get(name) if isinstance(baseline, dict) else None,
                                   default_tolerance=args.tolerance)
        scored["gate"] = gate
        report["scenarios"][name] = scored
        if gate.get("passed") is False:
            report["overall_passed"] = False
        # update-baseline records the mean per dimension
        new_baseline[name] = {dim: scored["aggregate"][dim]["mean"] for dim in RUBRIC_DIMENSIONS}
        new_baseline[name]["tolerance"] = args.tolerance

    out = json.dumps(report, ensure_ascii=False, indent=2)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(out)
        print(f"wrote {args.out}")
    else:
        print(out)

    if args.update_baseline:
        with open(BASELINE_PATH, "w", encoding="utf-8") as f:
            json.dump(new_baseline, f, ensure_ascii=False, indent=2)
        print(f"updated baseline → {BASELINE_PATH}")
        return 0
    # regression gate: non-zero exit on a real failure so CI/opt-in callers can branch
    return 0 if report["overall_passed"] else 1


def main() -> int:
    ap = argparse.ArgumentParser(description="forecast-quality regression scoring (LLM-judge)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("score", help="judge a single report")
    s.add_argument("--report", required=True, help="path to report.md to score")
    s.add_argument("--scenario", default=None, help="optional scenario JSON (expected_outcome)")
    s.add_argument("--judge-provider", default=None, help="LLM provider for the judge (default: global)")
    s.add_argument("--api-key", default=None, help="API key for the judge provider")
    s.add_argument("--k", type=int, default=DEFAULT_K, help="judge passes to average")
    s.add_argument("--live", action="store_true", help="allow live judge even if EVAL_ENABLED unset")
    s.set_defaults(func=cmd_score)

    r = sub.add_parser("run", help="judge the committed scenario set + gate vs baseline")
    r.add_argument("--scenarios-dir", default=SCENARIOS_DIR)
    r.add_argument("--judge-provider", default=None)
    r.add_argument("--api-key", default=None)
    r.add_argument("--k", type=int, default=DEFAULT_K)
    r.add_argument("--tolerance", type=float, default=DEFAULT_TOLERANCE)
    r.add_argument("--update-baseline", action="store_true", help="accept current scores as the new baseline")
    r.add_argument("-o", "--out", default=None, help="write eval_report.json (default: stdout)")
    r.add_argument("--live", action="store_true", help="allow live judge even if EVAL_ENABLED unset")
    r.set_defaults(func=cmd_run)

    args = ap.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
