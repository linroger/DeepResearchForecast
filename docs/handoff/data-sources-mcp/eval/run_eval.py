"""Owner-approved live eval (2026-10-12 "Three-question eval"): quick-depth v3 research runs through the
real DeerFlowResearchRunner, then an evidence summary of how the agents used official data.

Run from backend/ with the backend venv (the backend Config loads the repo .env, data keys included):
  cd backend && .venv/bin/python ../docs/handoff/data-sources-mcp/eval/run_eval.py run <qid> <out_root>
  cd backend && .venv/bin/python ../docs/handoff/data-sources-mcp/eval/run_eval.py summarize <qid> <out_root>
qid: us_inflation | dc_power | cn_gdp. Run directories live under <out_root>/<qid>/handoff (keep them outside
the repo); summaries are printed and written to <out_root>/<qid>/summary.json.
"""
from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path

QUESTIONS = {
    "us_inflation": ("Will US CPI inflation fall below 2.5% year over year by December 2027, and how will "
                     "the Federal Reserve policy rate evolve through 2027?", None),
    "dc_power": ("How much will US data-center electricity consumption grow by 2030, and will grid and "
                 "power-price constraints slow the AI data-center buildout?", None),
    "cn_gdp": ("2027年中国实际GDP增速会低于4%吗？请结合官方统计数据、IMF与世界银行预测及主要驱动因素进行研判。", "Chinese"),
}


def _read(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def run(qid: str, root: Path) -> None:
    sys.path.insert(0, str(Path.cwd()))
    from app.services.pipeline_orchestrator import DeerFlowResearchRunner

    question, language = QUESTIONS[qid]
    handoff = root / qid / "handoff"
    handoff.mkdir(parents=True, exist_ok=True)
    with (root / qid / "progress.log").open("a", encoding="utf-8") as log:
        def on_progress(pct: int, message: str) -> None:
            line = f"{time.strftime('%H:%M:%S')} {pct:3d}% {message}"
            print(line, flush=True)
            log.write(line + "\n")
            log.flush()

        started = time.time()
        result = DeerFlowResearchRunner.run(question, str(handoff), on_progress=on_progress, depth="quick",
                                            language=language, research_engine="v3")
    summary = {k: v for k, v in (result or {}).items()
               if isinstance(v, (int, float, bool, type(None))) or isinstance(v, str) and len(v) <= 300}
    summary["wall_seconds"] = round(time.time() - started, 1)
    (root / qid / "runner_result.json").write_text(json.dumps(summary, indent=1, ensure_ascii=False))


def summarize(qid: str, root: Path) -> dict:
    handoff = root / qid / "handoff"
    v3 = handoff / "v3"
    plan = _read(v3 / "plan.json") or {}
    needs = {k.get("id"): k.get("data_needs") or [] for k in plan.get("kiqs", [])}
    ledger = _read(v3 / "sources_ledger.json")
    rows = ledger.get("rows", []) if isinstance(ledger, dict) else (ledger or [])
    dataset_sids = {r.get("sid") for r in rows if isinstance(r, dict) and r.get("via") == "data"}
    per_kiq = {}
    for path in sorted((v3 / "kiq").glob("*.json")):
        rec = _read(path)
        if not isinstance(rec, dict):
            continue
        facts = rec.get("facts") or []
        data_facts = [f for f in facts if set(f.get("sids") or []) & dataset_sids]
        per_kiq[path.stem] = {
            "question": (rec.get("question") or "")[:140],
            "kind": rec.get("kind"),
            "data_needs": needs.get(path.stem, []),
            "tools": (rec.get("stats") or {}).get("tools"),
            "facts": len(facts),
            "data_facts": len(data_facts),
            "data_facts_verified": sum(1 for f in data_facts if f.get("tag") == "VERIFIED"),
            "sample_data_fact": data_facts[0]["text"][:240] if data_facts else "",
        }
    report_path = handoff / "research_report.md"
    report = report_path.read_text(encoding="utf-8") if report_path.exists() else ""
    sources = _read(handoff / "sources.json") or []
    quant = _read(handoff / "quantitative.json") or []
    actors = _read(handoff / "actors.json") or {}
    charts = _read(handoff / "charts.json") or []
    datasets = _read(handoff / "data" / "datasets.json") or {}
    meta = _read(handoff / "meta.json") or {}
    qa = _read(v3 / "qa.json") or {}
    usage = _read(v3 / "usage.json") or {}
    chart_files = sorted(p.name for p in (handoff / "charts").glob("data_*.png")) if (handoff / "charts").is_dir() else []
    out = {
        "question": QUESTIONS[qid][0],
        "runner": {k: v for k, v in (_read(root / qid / "runner_result.json") or {}).items()
                   if not isinstance(v, str) or len(v) <= 300},
        "data_sources_meta": meta.get("data_sources"),
        "plan_kiqs_with_data_needs": sum(1 for v in needs.values() if v),
        "plan_data_needs_total": sum(len(v) for v in needs.values()),
        "datasets": [r.get("series") for r in datasets.get("series", [])],
        "per_kiq": per_kiq,
        "report_chars": len(report),
        "baseline_section": bool(re.search(r"^## (Official Data Baseline|官方数据基线)", report, re.M)),
        "figures_in_report": len(re.findall(r"\]\(charts/data_[^)]+\.png\)", report)),
        "data_chart_files": chart_files,
        "official_sources": sum(1 for s in sources if isinstance(s, dict) and s.get("source_origin") == "official_data"),
        "official_quant_rows": sum(1 for q in quant if isinstance(q, dict) and q.get("source_origin") == "official_data")
        if isinstance(quant, list) else None,
        "forecast_indicators": len(((actors.get("forecast_inputs") or {}).get("indicators") or [])
                                   if isinstance(actors, dict) else []),
        "data_charts_manifest": [c.get("id") for c in charts if isinstance(c, dict)
                                 and str(c.get("id", "")).startswith("data_")],
        "qa_passed": qa.get("passed"),
        "qa_failures": qa.get("failures"),
        "qa_data_checks": [{k: c.get(k) for k in ("name", "passed", "detail")}
                           for c in qa.get("checks", []) if "data" in str(c.get("name", ""))],
        "usage": usage.get("totals") or usage.get("total") or usage,
        "degradation": (meta.get("research_quality") or {}).get("degradation"),
    }
    (root / qid / "summary.json").write_text(json.dumps(out, indent=1, ensure_ascii=False))
    return out


if __name__ == "__main__":
    action, qid, out_root = sys.argv[1], sys.argv[2], Path(sys.argv[3]).resolve()
    if action == "run":
        run(qid, out_root)
    print(json.dumps(summarize(qid, out_root), indent=1, ensure_ascii=False)[:8000])
