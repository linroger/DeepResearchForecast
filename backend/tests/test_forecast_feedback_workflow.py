"""Independent forecast feedback acceptance through production entry points.

External model/retrieval/provider replies are synthetic. Report generation,
normalization, final publication audit, monitor, durable ledger, scoring and
Flask consumers must remain production code. Execute only with the existing
main_offline_pytest runner in a frozen /private/tmp mirror.
"""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest

pytestmark = pytest.mark.guarded_runner


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _assert_public_consumers(client, report_id: str):
    """Read actual sealed artifacts through the customer-facing Flask routes."""
    from app.services.report_agent import ReportManager

    folder = Path(ReportManager._get_report_folder(report_id))
    audit = _read_json(folder / "final_audit.json")
    assert audit["hard_passed"], audit.get("hard_issues")
    assert audit["publish_gate"]["enabled"] is True
    assert audit["publish_gate"]["passed"] is True
    assert audit["markdown_sha256"] == _sha256(folder / "full_report.md")
    assert audit["forecast_sha256"] == _sha256(folder / "forecast.json")
    assert audit["structured_forecast"]["required"] is True
    assert audit["structured_forecast"]["valid"] is True

    detail = client.get(f"/api/report/{report_id}")
    assert detail.status_code == 200
    payload = detail.get_json()["data"]
    assert payload["publishable"] is True, payload.get("publication_issues")
    markdown = (folder / "full_report.md").read_text(encoding="utf-8")
    assert payload["markdown_content"] == markdown
    download = client.get(f"/api/report/{report_id}/download")
    assert download.status_code == 200
    assert download.get_data(as_text=True) == markdown
    forecast = client.get(f"/api/report/{report_id}/forecast")
    assert forecast.status_code == 200
    assert forecast.get_json()["data"]["forecast"] == _read_json(folder / "forecast.json")
    sdk_forecast = client.get(f"/api/v1/forecast/{report_id}")
    assert sdk_forecast.status_code == 200
    assert sdk_forecast.get_json()["data"]["forecast"] == _read_json(folder / "forecast.json")
    return {
        "report_id": report_id,
        "markdown_sha256": _sha256(folder / "full_report.md"),
        "forecast_sha256": _sha256(folder / "forecast.json"),
        "audit_sha256": _sha256(folder / "final_audit.json"),
    }


class ScriptedRetrieval:
    """Explicit synthetic graph-provider responses, with no graph/service client."""

    def get_simulation_context(self, **kwargs):
        return {"graph_statistics": {}, "total_entities": 0, "related_facts": []}

    def insight_forge(self, **kwargs):
        return ""

    def simulation_outcomes(self, *args, **kwargs):
        return ""

    def quick_search(self, **kwargs):
        return SimpleNamespace(to_text=lambda: "Synthetic source material: tighter policy could weigh on demand.")


class ScriptedModel:
    """Script external responses while leaving production report control flow real."""

    provider = "synthetic"
    model = "offline-fixture"

    def __init__(self, forecasts, outline, *, dual_anchor=False, near_anchor=False):
        self.forecasts = deepcopy(forecasts)
        self.outline = deepcopy(outline)
        self.dual_anchor = dual_anchor
        self.near_anchor = near_anchor
        self.calls = []

    def supports_native_tools(self):
        return False

    def chat_json(self, messages, **kwargs):
        self.calls.append({"kind": "chat_json", "messages": deepcopy(messages)})
        prompt = "\n".join(message["content"] for message in messages)
        if "[FORECASTS]" in prompt and "[MARKETS]" in prompt:
            pairs = [("F1", "synthetic-market-a"), ("F2", "synthetic-market-b")]
            if self.dual_anchor:
                pairs.append(("F3", "synthetic-market-c"))
            return {"matches": [
                {"forecast_id": fid, "market_id": mid,
                 "resolution_equivalence": "near" if self.near_anchor and fid == "F2" else "exact",
                 "confidence": 0.99}
                for fid, mid in pairs
            ]}
        if '"sections"' in prompt:
            return deepcopy(self.outline)
        if "binary_forecasts" in prompt:
            return {"binary_forecasts": deepcopy(self.forecasts["binary_forecasts"])}
        return deepcopy(self.forecasts)

    def chat(self, messages, **kwargs):
        self.calls.append({"kind": "chat", "messages": deepcopy(messages)})
        tool_turns = sum(
            message.get("role") == "assistant" and "<tool_call>" in message.get("content", "")
            for message in messages
        )
        if tool_turns < 4:
            return ('<tool_call>{"name":"quick_search",'
                    '"parameters":{"query":"policy and demand"}}</tool_call>')
        text = "\n".join(message["content"] for message in messages[:2])
        matches = [
            section for section in self.outline["sections"]
            if section["title"] in messages[1]["content"]
        ]
        if matches:
            section = max(matches, key=lambda row: messages[1]["content"].rfind(row["title"]))
            return "Final Answer: " + PROSE[section["title"]]
        raise AssertionError(f"Unscripted external prose request: {text[:200]}")


QUESTION = "Forecast the US economic outlook through 2027-12-31 with ten independent binary forecasts."
AS_OF = "2028-01-15T00:00:00+00:00"
ORIGINAL = "report_feedback_original"
NEXT = "report_feedback_next"
OUTLINE = {
    "title": "US economic outlook",
    "summary": "Policy and household demand could shape the outlook.",
    "sections": [
        {"title": "Demand outlook", "description": "Household demand could weaken if financing becomes more costly."},
        {"title": "Policy channels", "description": "A more restrictive policy stance would constrain investment plans."},
        {"title": "Alternative paths", "description": "Supply improvements could support a continued expansion."},
        {"title": "Risks and decisions", "description": "A contraction would warrant reassessing the central outlook."},
    ],
}
PROSE = {
    "Demand outlook": (
        "Household demand could weaken if financing becomes more costly. A household facing "
        "a higher refinancing payment might defer a discretionary purchase while maintaining "
        "essential spending. That response would make the composition of demand relevant to "
        "the outlook: resilient necessities would not by themselves demonstrate strength in "
        "durable purchases. Businesses exposed to discretionary demand could respond by "
        "reducing orders, which might then affect hiring decisions.\n\n"
        "The expansion scenario would remain plausible if income growth supported spending "
        "despite these pressures. The contraction scenario would become more concerning if "
        "weakness spread from optional purchases into employment and incomes. A useful "
        "interpretation would consider those mechanisms together, while allowing for delays "
        "between financing conditions and spending choices. This conditional account does "
        "not establish that any of these changes has already occurred. Future official "
        "observations would be needed to adjudicate the stated forecast contracts."
    ),
    "Policy channels": (
        "A more restrictive policy stance would constrain investment plans through several "
        "possible channels. Firms could demand a higher expected return before committing "
        "capital, lenders could reconsider credit terms, and managers could retain cash "
        "while uncertainty remained high. Each channel would have a different transmission "
        "delay. A financing announcement would therefore provide less information than "
        "evidence that firms had actually changed the timing of planned projects.\n\n"
        "A tax change could also alter the distribution of incentives across businesses. "
        "The forecast of a corporate tax increase concerns an enacted statute and its "
        "specified deadline; political discussion alone would not satisfy that contract. "
        "A household rebate represents a distinct proposition with different recipients "
        "and a separate resolution rule. Either proposal could fail independently. The "
        "analysis would therefore preserve both uncertainties instead of inferring one "
        "policy outcome from the other or treating either policy as a complete economic "
        "scenario. Subsequent policy evidence would need to match each original question."
    ),
    "Alternative paths": (
        "Supply improvements could support a continued expansion even if demand became "
        "less vigorous. If firms encountered fewer production constraints, they could "
        "deliver existing orders with less disruption. Greater reliability might allow "
        "businesses to carry smaller precautionary inventories and redirect resources "
        "toward productive investment. These possibilities describe a conditional path "
        "and should not be interpreted as observations of current business conditions.\n\n"
        "The alternative contraction path would involve a broader deterioration that "
        "supply improvements could not offset. Its plausibility would depend on the "
        "interaction between employment, household incomes and investment plans. Those "
        "mechanisms could reinforce each other, but their relationship need not be "
        "immediate or uniform across industries. Scenario adjudication must consequently "
        "use the declared economy-wide outcome criterion. A single unemployment reading, "
        "a market settlement or an isolated policy event would not independently identify "
        "which complete scenario occurred. Each would remain evidence for its own "
        "bounded forecast question until a separate scenario outcome was supplied."
    ),
    "Risks and decisions": (
        "A contraction would warrant reassessing the central outlook. Decision makers "
        "could prepare contingent actions that depend on observable developments rather "
        "than a commitment to one narrative. For example, they might preserve flexibility "
        "in spending plans until the conditions relevant to their decision became clearer. "
        "A precaution of this kind would acknowledge uncertainty without asserting that "
        "the adverse scenario was inevitable or that its timing could be known precisely.\n\n"
        "Evaluation should retain the original forecast probabilities and resolution "
        "criteria. Changing a probability after learning the outcome would obscure what "
        "was actually predicted. Likewise, an ambiguous observation should remain "
        "unresolved until evidence satisfies the specified contract. A later report "
        "could use recorded outcomes to describe the forecasting record, provided it "
        "kept scenario and binary scores separate and disclosed outstanding questions. "
        "A small set of scored forecasts would not support a broad claim of calibrated "
        "performance. Reliable interpretation would depend on the quality of the "
        "retained evidence as well as the arithmetic of each score."
    ),
}


def _series(series="fred:UNRATE", *, future=False, unknown=False):
    unemployment = series == "fred:UNRATE"
    return {
        "series": series,
        "title": "US unemployment rate" if unemployment else "Effective federal funds rate",
        "units": "Percent", "frequency": "M",
        "source_url": f"https://fred.stlouisfed.org/series/{series.split(':')[1]}",
        "retrieved_at": AS_OF if future else "2026-10-01T00:00:00Z",
        "observations": [{
            "date": ("2027-06-01" if unemployment else "2027-12-01") if future else "2026-09-01",
            "value": 4.2 if unemployment else 3.5,
            "flag": "unknown" if unknown else "",
        }],
    }


def _forecast():
    binaries = [
        {"id": "F1", "statement": "The US enacts a corporate tax increase by 2027-12-31.",
         "resolution_criteria": "A signed federal statute raises the corporate tax rate by 2027-12-31.",
         "probability": 0.3},
        {"id": "F2", "statement": "The US enacts a household tax rebate by 2027-12-31.",
         "resolution_criteria": "A signed federal statute authorizes a household rebate by 2027-12-31.",
         "probability": 0.8},
        {"id": "F3", "statement": "US unemployment rate > 4% in June 2027.",
         "resolution_criteria": "fred:UNRATE > 4% in 2027-06.", "probability": 0.7,
         "data_anchor": {"series": "fred:UNRATE", "comparator": ">", "threshold": 4,
                         "observation": "2027-06", "units": "Percent", "transform": ""}},
        {"id": "F4", "statement": "The effective federal funds rate < 3% in December 2027.",
         "resolution_criteria": "fred:FEDFUNDS < 3% in 2027-12.", "probability": 0.4,
         "data_anchor": {"series": "fred:FEDFUNDS", "comparator": "<", "threshold": 3,
                         "observation": "2027-12", "units": "Percent", "transform": ""}},
    ]
    for number, (metric, probability) in enumerate([
        ("industrial output", 0.15), ("retail sales", 0.25), ("housing starts", 0.35),
        ("business investment", 0.65), ("real exports", 0.75), ("real imports", 0.85),
    ], 5):
        binaries.append({
            "id": f"F{number}", "statement": f"US {metric} growth exceeds 2% in 2027.",
            "resolution_criteria": f"The official annual {metric} growth exceeds 2% for 2027 by 2028-12-31.",
            "probability": probability,
        })
    for binary in binaries:
        binary.update(
            resolution_source="FRED" if binary.get("data_anchor") else "Official public record",
            theme="policy" if binary["id"] in {"F1", "F2"} else "macro",
            horizon_year=2027, source="research-prior",
            base_rate_anchor="Synthetic acceptance input; no empirical estimate.",
            adjustment_rationale="Synthetic external response for deterministic acceptance.",
            scenario_membership={"derivable": False, "yes_scenarios": []},
        )
    return {
        "headline": "Expansion remains the central scenario.",
        "horizon": "2027-12-31", "confidence": "medium",
        "scenarios": [
            {"name": "Baseline expansion", "probability": 0.7,
             "resolution_criteria": "NBER records no recession beginning before 2027-12-31."},
            {"name": "Contraction", "probability": 0.3,
             "resolution_criteria": "NBER records a recession beginning before 2027-12-31."},
        ],
        "binary_forecasts": binaries,
        # A model may invent an attractive record. The actual publisher must
        # use its own durable history, never promote this external assertion.
        "historical_calibration": {"forecast_track_record": {
            "schema_version": 1, "n_reports": 999, "source_digest": "a" * 64,
            "tracks": {kind: {"n_forecasts": 999, "n_resolved": 999,
                             "n_outstanding": 0, "mean_brier": 0.0, "coverage": 1.0}
                       for kind in ("scenario", "market_binary", "official_data_binary", "unanchored_binary")},
        }},
    }


def _markets(*, dual_anchor=False):
    return [
        {"market_id": mid, "question": binary["statement"],
         "implied_yes_prob": binary["probability"], "price_at_research": binary["probability"],
         "url": f"https://polymarket.com/event/{mid}", "end_date": "2027-12-31",
         "volume": 10000}
        for mid, binary in zip(
            ("synthetic-market-a", "synthetic-market-b", "synthetic-market-c") if dual_anchor
            else ("synthetic-market-a", "synthetic-market-b"), _forecast()["binary_forecasts"])
    ]


class ScriptedMarkets:
    """External market responses only; joins and Brier arithmetic stay native."""

    def __init__(self, *, conflict=False, wrong_identity=False, dual_anchor=False, settle_second=False):
        self.conflict = conflict
        self.wrong_identity = wrong_identity
        self.dual_anchor = dual_anchor
        self.settle_second = settle_second
        self.requested = []

    def requote_markets(self, rows):
        return deepcopy(rows)

    def fetch_resolutions(self, ids):
        self.requested.append(list(ids))
        return {
            mid: {"market_id": "unrelated-market" if self.wrong_identity else mid,
                  "resolved": (mid == "synthetic-market-a" or self.conflict
                               or (self.dual_anchor and mid == "synthetic-market-c")
                               or (self.settle_second and mid == "synthetic-market-b")),
                  "resolved_outcome": ("No" if self.conflict else "Yes") if mid == "synthetic-market-a" else "Yes",
                  "resolved_yes_price": 0.0 if self.conflict else (
                      1.0 if mid == "synthetic-market-a" or self.dual_anchor or self.settle_second else None)}
            for mid in ids
        }


class ScriptedData:
    def __init__(self, *, unemployment=4.2):
        self.requested = []
        self.unemployment = unemployment

    def get(self, series, **kwargs):
        self.requested.append((series, kwargs))
        row = _series(series, future=True, unknown=series == "fred:FEDFUNDS")
        if series == "fred:UNRATE":
            row["observations"][0]["value"] = self.unemployment
        return row


def _configure(root, monkeypatch):
    from app.config import Config
    from app.services.report_agent import ReportManager
    from app.utils.prediction_markets import PolymarketClient

    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    flags = {
        "API_V1_ENABLED": True, "REPORT_FORECAST_LEDGER": True,
        "REPORT_STRUCTURED_FORECAST": True, "REPORT_FORECAST_SPINE_FIRST": True,
        "FORECAST_EMIT_BINARY": True, "DATA_SOURCES_ENABLED": True,
        "REPORT_PUBLISH_GATE": True, "REPORT_FINAL_READ_ONLY_AUDIT": True,
        "REPORT_EDITORIAL_LINT": True, "REPORT_CITATION_FINALIZER": True,
        "REPORT_FORECAST_SELF_CRITIQUE": False, "REPORT_REPAIR_PASSES": False,
        "REPORT_VISUALIZATIONS": False, "REPORT_BILINGUAL": False,
        "REPORT_LANGUAGE_PURITY": False, "REPORT_THREE_PART_SKELETON": False,
        "REPORT_SECTION_CONCURRENCY": 1, "REPORT_SECTION_REFLECTION": False,
        "REPORT_SPINE_SELFCONSISTENCY_K": 1, "FORECAST_ENSEMBLE_MODELS": "",
        "PREDICTION_MARKETS_ENABLED": True,
        "PIPELINE_DATA_DIR": str(root / "pipelines"),
        "OASIS_SIMULATION_DATA_DIR": str(root / "simulations"),
        "FORECAST_LEDGER_DIR": str(root / "ledger"),
    }
    for name, value in flags.items():
        monkeypatch.setattr(Config, name, value, raising=False)
    monkeypatch.setenv("REPORT_OUTPUT_LANGUAGE", "English")
    monkeypatch.setenv("PREDICTION_MARKETS_ENABLED", "true")
    monkeypatch.setattr(ReportManager, "REPORTS_DIR", str(root / "reports"))
    # These are the external market retrieval methods, not report/ledger logic.
    monkeypatch.setattr(PolymarketClient, "requote_markets", lambda self, rows: deepcopy(rows))
    monkeypatch.setattr(PolymarketClient, "snapshot_for_queries", lambda self, *a, **kw: _markets())
    return root


def _client():
    from app import create_app

    app = create_app()
    app.config["TESTING"] = True
    return app.test_client()


def _generate(root, report_id, *, dual_anchor=False, near_anchor=False):
    """Start the real public generation method from persisted synthetic inputs."""
    from app.config import Config
    from app.services.official_data import data_api, load_official_data
    from app.services.pipeline_orchestrator import PipelineManager, PipelineState
    from app.services.report_agent import ReportAgent, ReportStatus

    simulation_id = f"sim_{report_id}"
    pipeline_id = f"pipe_{report_id}"
    pipeline = Path(Config.PIPELINE_DATA_DIR) / pipeline_id
    handoff = pipeline / "handoff"
    handoff.mkdir(parents=True, exist_ok=True)
    PipelineManager.save(PipelineState(
        pipeline_id=pipeline_id, simulation_id=simulation_id, prompt=QUESTION,
        handoff_dir=str(handoff), created_at="2026-10-01T00:00:00Z"))
    (handoff / "prediction_markets.json").write_text(
        json.dumps({"markets": _markets(dual_anchor=dual_anchor)}), encoding="utf-8")
    api = data_api()
    api.write_dataset_files([api.Series.from_dict(_series(sid)) for sid in ("fred:UNRATE", "fred:FEDFUNDS")], handoff)
    carrier = load_official_data(handoff)
    assert carrier
    model = ScriptedModel(_forecast(), OUTLINE, dual_anchor=dual_anchor, near_anchor=near_anchor)
    agent = ReportAgent(
        "graph_feedback", simulation_id, QUESTION,
        llm_client=model, zep_tools=ScriptedRetrieval(), official_data=carrier,
        research_report="Policy could weigh on demand; all probabilities are synthetic acceptance inputs.",
    )
    report = agent.generate_report(report_id=report_id)
    assert report.status == ReportStatus.COMPLETED, report.error
    assert not report.failed_sections
    assert model.calls
    return report, agent


def _monitor(report_id, *, conflict=False):
    import scripts.resolution_monitor as monitor

    market, data = ScriptedMarkets(conflict=conflict), ScriptedData()
    # No forecast/report-folder/ledger override: discover the real published input.
    result = monitor.run_monitor(report_id, client=market, data_client=data, as_of=AS_OF)
    return result


def _tracks(*, scenario=0):
    from app.services import forecast_ledger

    summary = forecast_ledger.production_track_record()
    tracks = summary["tracks"]
    expected = {
        "scenario": (1, scenario, 0.18 if scenario else None),
        "market_binary": (2, 1, 0.49),
        "official_data_binary": (2, 1, 0.09),
        "unanchored_binary": (6, 0, None),
    }
    for kind, (total, resolved, brier) in expected.items():
        track = tracks[kind]
        assert track["n_forecasts"] == total, (kind, track)
        assert track["n_resolved"] == resolved, (kind, track)
        assert track["n_outstanding"] == total - resolved
        if brier is None:
            assert track["mean_brier"] is None
        else:
            assert track["mean_brier"] == pytest.approx(brier)
        assert track["coverage"] == pytest.approx(resolved / total)
    assert summary["n_reports"] == 1
    return summary


def _ledger_hash(root):
    return _sha256(Path(root) / "ledger" / "published_forecasts.jsonl")


def _restart(root, prior_summary):
    """Run duplicate resolution and next generation in a fresh guarded interpreter."""
    guard = sys.modules["main_offline_guard"]
    script = Path(root) / "restart.py"
    script.write_text(
        "import json, os, runpy\n"
        "from pathlib import Path\n"
        "import pytest\n"
        f"ns = runpy.run_path({str(Path(__file__).resolve())!r})\n"
        f"root = Path({str(root)!r})\n"
        "with pytest.MonkeyPatch.context() as patch:\n"
        "    ns['_configure'](root, patch)\n"
        "    ns['_restart_workflow'](root)\n",
        encoding="utf-8",
    )
    guard.allow_python_script(script)
    process = subprocess.run(
        [sys.executable, str(script)], capture_output=True, text=True, timeout=90,
    )
    (Path(root) / "restart.stdout.txt").write_text(process.stdout, encoding="utf-8")
    (Path(root) / "restart.stderr.txt").write_text(process.stderr, encoding="utf-8")
    assert process.returncode == 0, process.stderr[-8000:] + process.stdout[-4000:]
    receipt = _read_json(Path(root) / "restart-receipt.json")
    assert receipt["pid"] != os.getpid()
    assert receipt["before"] == prior_summary
    child = _read_json(guard.root / f"process-{receipt['pid']}.json")
    assert child["exit_code"] == 0 and child["shutdown_complete"]
    assert child["identity_preserved"] and child["source_drift"] == []
    return receipt


def _restart_workflow(root):
    from app.services import forecast_ledger

    client = _client()
    before = _tracks(scenario=1)
    stored = forecast_ledger.read_published_forecast(ORIGINAL)
    _monitor(ORIGINAL)
    duplicate = client.post(f"/api/v1/resolve/{ORIGINAL}", json={"outcome": "Baseline expansion"})
    assert duplicate.status_code == 200, duplicate.get_json()
    assert _tracks(scenario=1) == before
    assert forecast_ledger.read_published_forecast(ORIGINAL) == stored
    _generate(root, NEXT)
    consumer = _assert_public_consumers(client, NEXT)
    folder = Path(root) / "reports" / NEXT
    later = _read_json(folder / "forecast.json")
    track = later["historical_calibration"]["forecast_track_record"]
    assert track == dict(before, excluded_report_id=NEXT)
    assert forecast_ledger.verify_production_track_record(track, exclude_report_id=NEXT)
    current = forecast_ledger.production_track_record(exclude_report_id=NEXT)
    prefix_keys = {"journal_length", "journal_sha256"}
    assert {k: v for k, v in track.items() if k not in prefix_keys} == {
        k: v for k, v in current.items() if k not in prefix_keys}
    markdown = (folder / "full_report.md").read_text(encoding="utf-8")
    for word in ("track record", "does not establish calibration", "separate denominators"):
        assert word in markdown.lower(), word
    for row in (
        "| Scenarios (multiclass) | 1 | 1 | 0 | 0.1800 |",
        "| Market binaries | 2 | 1 | 1 | 0.4900 |",
        "| Official-data binaries | 2 | 1 | 1 | 0.0900 |",
        "| Unanchored binaries | 6 | 0 | 6 | — |",
    ):
        assert row in markdown, row
    assert markdown.count("<!-- forecast-track-record:start -->") == 1
    assert _read_json(folder / "final_audit.json")["forecast_track_record"]["passed"]
    # Outcomes arriving after the next publication must not refresh its frozen
    # historical section or invalidate the provable prefix used by that report.
    import scripts.resolution_monitor as monitor
    monitor.run_monitor(
        ORIGINAL, client=ScriptedMarkets(settle_second=True),
        data_client=ScriptedData(), as_of="2028-02-01T00:00:00+00:00",
    )
    later_current = forecast_ledger.production_track_record(exclude_report_id=NEXT)
    assert later_current["tracks"]["market_binary"]["n_resolved"] == 2
    assert later_current["tracks"]["market_binary"]["mean_brier"] == pytest.approx(0.265)
    assert later_current["source_digest"] != track["source_digest"]
    assert forecast_ledger.verify_production_track_record(track, exclude_report_id=NEXT)
    assert _assert_public_consumers(client, NEXT) == consumer
    assert _read_json(folder / "forecast.json")["historical_calibration"]["forecast_track_record"] == track
    (Path(root) / "restart-receipt.json").write_text(json.dumps({
        "pid": os.getpid(), "before": before, "next_track_record": track,
        "consumer": consumer, "original": stored,
        "repaired_scenario_mirror": _read_json(Path(root) / "reports" / ORIGINAL / "resolved.json"),
    }, indent=2), encoding="utf-8")


def test_published_forecast_native_resolution_restart_and_next_report(tmp_path, monkeypatch):
    from app.services import forecast_ledger

    root = _configure(tmp_path, monkeypatch)
    client = _client()
    _generate(root, ORIGINAL)
    consumer = _assert_public_consumers(client, ORIGINAL)
    published = forecast_ledger.read_published_forecast(ORIGINAL)
    assert published is not None, "Audited save did not register the original forecast"
    assert published["forecast"]["scenarios"][0]["probability"] == 0.7
    assert published["forecast"]["binary_forecasts"][0]["probability"] == 0.3
    assert forecast_ledger.production_track_record()["tracks"]["scenario"]["n_resolved"] == 0
    history = _read_json(root / "reports" / ORIGINAL / "forecast.json")["historical_calibration"]["forecast_track_record"]
    assert history["n_reports"] == 0
    assert all(row["n_forecasts"] == 0 for row in history["tracks"].values())

    initial_hash = _ledger_hash(root)
    unknown = client.post(f"/api/v1/resolve/{ORIGINAL}", json={"outcome": "Unknown"})
    assert unknown.status_code in (400, 409), unknown.get_json()
    assert _ledger_hash(root) == initial_hash
    _monitor(ORIGINAL)
    before_scenario = _tracks()
    retained_outcomes = forecast_ledger.read_published_resolutions(ORIGINAL)
    assert len(retained_outcomes) == 2
    _monitor(ORIGINAL)
    assert _tracks() == before_scenario
    conflict_display = _monitor(ORIGINAL, conflict=True)
    assert _tracks() == before_scenario
    assert forecast_ledger.read_published_resolutions(ORIGINAL) == retained_outcomes
    shown_market = next(row for row in conflict_display["resolution_records"] if row["forecast_id"] == "F1")
    assert shown_market["resolved_outcome"] == "Yes"
    assert shown_market["model_p"] == 0.3
    assert shown_market["brier_contribution"] == pytest.approx(0.49)
    assert conflict_display["resolved_count"] == 2
    assert conflict_display["newly_recorded_count"] == 0
    expected_market_row = "| F1 | synthetic-market-a | Yes | 30% | 0.49 |"
    assert expected_market_row in conflict_display["monitor_report_md"]
    assert expected_market_row in Path(conflict_display["monitor_report_path"]).read_text(encoding="utf-8")

    resolved = client.post(f"/api/v1/resolve/{ORIGINAL}", json={"outcome": "Baseline expansion"})
    assert resolved.status_code == 200, resolved.get_json()
    score = resolved.get_json()["data"]["scoring"]
    assert score["brier"] == pytest.approx(0.18)
    assert score["realized_probability"] == 0.7
    after = _tracks(scenario=1)
    evaluation = forecast_ledger.append_golden_result(
        question_id="feedback-evaluation", probability=1.0, resolved_outcome=True,
        question="Synthetic historical answer known before evaluation",
        as_of_date="2020-01-01", resolution_date="2021-01-01",
        d=str(root / "ledger"),
    )
    assert evaluation["record_class"] == "evaluation"
    assert evaluation["ledger_redirected"] == "evaluation"
    assert _tracks(scenario=1) == after
    stored_hash = _ledger_hash(root)
    duplicate = client.post(f"/api/v1/resolve/{ORIGINAL}", json={"outcome": "Baseline expansion"})
    assert duplicate.status_code == 200
    assert duplicate.get_json()["data"]["scoring"] == score
    conflict = client.post(f"/api/v1/resolve/{ORIGINAL}", json={"outcome": "Contraction"})
    assert conflict.status_code == 409, conflict.get_json()
    assert _ledger_hash(root) == stored_hash
    assert _tracks(scenario=1) == after

    mirror = root / "reports" / ORIGINAL / "resolved.json"
    original_mirror = _read_json(mirror)
    # Model interruption after the durable outcome commit but before its derived
    # report-local mirror exists. Retry must rebuild it from the original fact.
    mirror.unlink()
    restarted = _restart(root, after)
    assert restarted["repaired_scenario_mirror"] == original_mirror
    (root / "acceptance-receipt.json").write_text(json.dumps({
        "scope": "synthetic external responses; production workflow and consumers",
        "original_consumer": consumer, "before_scenario": before_scenario,
        "after_scenario": after, "restart": restarted,
    }, indent=2), encoding="utf-8")


def test_publication_barrier_and_probability_tampering(tmp_path, monkeypatch):
    from app.services import forecast_ledger
    from app.services.report_agent import Report, ReportManager, ReportStatus

    root = _configure(tmp_path, monkeypatch)
    client = _client()
    draft = Report(
        report_id="report_feedback_draft", simulation_id="sim_feedback_draft",
        graph_id="graph_feedback", simulation_requirement=QUESTION,
        status=ReportStatus.COMPLETED, markdown_content="# Draft\n\nUnsealed forecast.\n",
    )
    folder = Path(ReportManager._get_report_folder(draft.report_id))
    folder.mkdir(parents=True)
    (folder / "forecast.json").write_text(json.dumps(_forecast()), encoding="utf-8")
    ReportManager.save_report(draft)
    assert forecast_ledger.read_published_forecast(draft.report_id) is None
    assert client.get(f"/api/report/{draft.report_id}/forecast").status_code == 409
    assert client.post(f"/api/v1/resolve/{draft.report_id}", json={"outcome": "Baseline expansion"}).status_code == 409

    _generate(root, ORIGINAL)
    published = forecast_ledger.read_published_forecast(ORIGINAL)
    forecast_path = Path(ReportManager._get_report_folder(ORIGINAL)) / "forecast.json"
    altered = _read_json(forecast_path)
    altered["binary_forecasts"][0]["probability"] = 0.99
    altered["scenarios"][0]["probability"] = 0.99
    altered["scenarios"][1]["probability"] = 0.01
    forecast_path.write_text(json.dumps(altered), encoding="utf-8")
    assert client.get(f"/api/report/{ORIGINAL}/forecast").status_code == 409
    assert client.get(f"/api/report/{ORIGINAL}/download").status_code == 409
    assert client.post(f"/api/v1/resolve/{ORIGINAL}", json={"outcome": "Baseline expansion"}).status_code == 409
    with pytest.raises(ValueError, match="unpublished|tracking"):
        _monitor(ORIGINAL)
    # Explicit injection is supported by the native monitor for callers. Even
    # there, the immutable registration must override the edited probabilities.
    import scripts.resolution_monitor as monitor
    monitor.run_monitor(
        ORIGINAL, forecast=altered, client=ScriptedMarkets(),
        data_client=ScriptedData(), as_of=AS_OF,
    )
    summary = forecast_ledger.production_track_record()
    market = summary["tracks"]["market_binary"]
    assert market["n_resolved"] == 1
    assert market["mean_brier"] == pytest.approx(0.49)
    assert summary["tracks"]["scenario"]["n_resolved"] == 0
    assert forecast_ledger.read_published_forecast(ORIGINAL) == published


def test_native_monitor_rejects_mismatched_provider_identity(tmp_path, monkeypatch):
    from app.services import forecast_ledger
    import scripts.resolution_monitor as monitor

    root = _configure(tmp_path, monkeypatch)
    _generate(root, ORIGINAL)
    result = monitor.run_monitor(
        ORIGINAL, client=ScriptedMarkets(wrong_identity=True),
        data_client=ScriptedData(), as_of=AS_OF,
    )
    summary = forecast_ledger.production_track_record()
    assert summary["tracks"]["market_binary"]["n_resolved"] == 0, result
    assert summary["tracks"]["scenario"]["n_resolved"] == 0
    assert summary["tracks"]["official_data_binary"]["n_resolved"] == 1


def test_dual_anchor_market_settlement_does_not_skip_official_observation(tmp_path, monkeypatch):
    from app.services import forecast_ledger
    import scripts.resolution_monitor as monitor

    root = _configure(tmp_path, monkeypatch)
    _generate(root, ORIGINAL, dual_anchor=True)
    published = forecast_ledger.read_published_forecast(ORIGINAL)
    dual = next(row for row in published["forecast"]["binary_forecasts"] if row["id"] == "F3")
    assert dual["market_anchor"]["market_id"] == "synthetic-market-c"
    assert dual["data_anchor"]["series"] == "fred:UNRATE"
    data = ScriptedData(unemployment=3.8)
    result = monitor.run_monitor(
        ORIGINAL, client=ScriptedMarkets(dual_anchor=True), data_client=data, as_of=AS_OF,
    )
    assert any(sid == "fred:UNRATE" for sid, kwargs in data.requested)
    official = next(row for row in result["data_resolution_records"] if row["forecast_id"] == "F3")
    assert official["resolved_outcome"] is False
    assert official["brier_contribution"] == pytest.approx(0.49)
    summary = forecast_ledger.production_track_record()
    assert summary["tracks"]["official_data_binary"]["n_forecasts"] == 2
    assert summary["tracks"]["official_data_binary"]["n_resolved"] == 1
    assert summary["tracks"]["official_data_binary"]["mean_brier"] == pytest.approx(0.49)
    assert summary["tracks"]["market_binary"]["n_forecasts"] == 2
    assert summary["tracks"]["market_binary"]["n_resolved"] == 1
    assert summary["tracks"]["scenario"]["n_resolved"] == 0


def test_monitor_aggregates_exclude_near_match_and_unknown_outcomes(tmp_path, monkeypatch):
    from app.services import forecast_ledger
    import scripts.resolution_monitor as monitor

    root = _configure(tmp_path, monkeypatch)
    _generate(root, ORIGINAL, near_anchor=True)
    published = forecast_ledger.read_published_forecast(ORIGINAL)
    near = next(row for row in published["forecast"]["binary_forecasts"] if row["id"] == "F2")
    assert near["market_anchor"]["resolution_equivalence"] == "near"
    result = monitor.run_monitor(
        ORIGINAL, client=ScriptedMarkets(settle_second=True),
        data_client=ScriptedData(), as_of=AS_OF,
    )
    assert result["resolved_count"] == 2
    assert result["newly_recorded_count"] == 2
    assert result["native_records_appended"] == 3
    assert result["market_brier"]["n_resolved"] == 1
    assert result["market_brier"]["mean_brier"] == pytest.approx(0.49)
    assert result["data_brier"]["n_resolved"] == 1
    assert result["data_brier"]["mean_brier"] == pytest.approx(0.09)
    assert result["calibration"]["n_resolved"] == 0
    assert result["calibration"]["mean_brier"] is None
    assert all(result[key]["source"] == "published_forecasts.jsonl"
               for key in ("market_brier", "data_brier", "calibration"))
    assert {row["forecast_id"] for row in result["resolution_records"]} == {"F1"}
    assert {row["forecast_id"] for row in result["data_resolution_records"]} == {"F3"}
    assert any(row["forecast_id"] == "F2" and row["reason"] == "market_not_exact"
               for row in result["forecast_feedback"]["rejected"])
    assert any(row["forecast_id"] == "F4" and row["status"] == "manual"
               for row in result["data_resolution_status"])
    markdown = result["monitor_report_md"]
    assert "Market-resolved binary forecasts: **1**; mean Brier: **0.49**" in markdown
    assert "Scenario forecasts resolved: **0**; mean Brier: **—**" in markdown
    assert "| F1 | synthetic-market-a | Yes | 30% | 0.49 |" in markdown
    assert "| F2 | synthetic-market-b | Yes |" not in markdown
    assert "| F4 | fred:FEDFUNDS | manual |" in markdown
    assert Path(result["monitor_report_path"]).read_text(encoding="utf-8") == markdown
    # The native legacy rows intentionally contain both market candidates;
    # only the admitted typed record may drive the public aggregate.
    assert forecast_ledger.market_brier_summary()["n_resolved"] == 2
    assert _tracks()["tracks"]["market_binary"]["n_resolved"] == 1


class InterruptedPublication(BaseException):
    """Simulate process loss after audited metadata save and before registration."""


def _interrupt_publication(root, monkeypatch, report_id):
    from app.services import forecast_ledger
    from app.services.report_agent import ReportManager

    original = forecast_ledger.record_published_forecast

    def failpoint(*args, **kwargs):
        if kwargs.get("report_id") == report_id:
            raise InterruptedPublication(report_id)
        return original(*args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(forecast_ledger, "record_published_forecast", failpoint)
        with pytest.raises(InterruptedPublication):
            _generate(root, report_id)
    folder = Path(ReportManager._get_report_folder(report_id))
    assert _read_json(folder / "meta.json")["status"] == "completed"
    assert _read_json(folder / "meta.json")["forecast_feedback_required"] is True
    assert _read_json(folder / "final_audit.json")["hard_passed"]
    assert forecast_ledger.read_published_forecast(report_id) is None
    return folder


def test_native_batch_recovers_pending_publication_despite_saturated_queue(tmp_path, monkeypatch, capsys):
    from app.services import forecast_ledger, official_data
    from app.utils.prediction_markets import PolymarketClient
    import scripts.resolution_monitor as monitor

    root = _configure(tmp_path, monkeypatch)
    _generate(root, "report_feedback_queue_a")
    broken = _interrupt_publication(root, monkeypatch, "report_feedback_queue_b")
    legacy = _interrupt_publication(root, monkeypatch, "report_feedback_queue_c")
    pending = _interrupt_publication(root, monkeypatch, "report_feedback_queue_z")
    # A broken candidate must not pin the bounded recovery cursor forever.
    with (broken / "full_report.md").open("a", encoding="utf-8") as stream:
        stream.write("\nUnaudited post-publication modification.\n")
    metadata = _read_json(legacy / "meta.json")
    metadata.pop("forecast_feedback_required")
    (legacy / "meta.json").write_text(json.dumps(metadata), encoding="utf-8")
    pending_hash = _sha256(pending / "forecast.json")

    # The clock and acquisition clients are external inputs. Batch selection,
    # recovery, audit, registration, queue rotation and monitor calls are real.
    monkeypatch.setattr(monitor, "_utcnow_iso", lambda: AS_OF)
    monkeypatch.setattr(PolymarketClient, "fetch_resolutions",
                        lambda self, ids: ScriptedMarkets().fetch_resolutions(ids))
    monkeypatch.setattr(official_data, "get_data_sources", lambda: ScriptedData())
    assert forecast_ledger.outstanding_published_report_ids(as_of=AS_OF, limit=1) == [
        "report_feedback_queue_a"]
    capsys.readouterr()
    for _ in range(3):
        assert monitor.main(["run", "--all-recent", "1"]) == 0
        if forecast_ledger.read_published_forecast("report_feedback_queue_z") is not None:
            break
    assert forecast_ledger.read_published_forecast("report_feedback_queue_z") is not None
    assert forecast_ledger.read_published_forecast("report_feedback_queue_b") is None
    assert forecast_ledger.read_published_forecast("report_feedback_queue_c") is None
    assert _sha256(pending / "forecast.json") == pending_hash
    assert (root / "ledger" / "publication_recovery_cursor.json").is_file()
    (root / "batch-recovery-output.txt").write_text(capsys.readouterr().out, encoding="utf-8")


def test_frozen_track_record_companion_tamper_is_rejected(tmp_path, monkeypatch):
    from app.services.report_agent import ReportManager

    root = _configure(tmp_path, monkeypatch)
    client = _client()
    report, agent = _generate(root, ORIGINAL)
    _assert_public_consumers(client, ORIGINAL)
    folder = Path(ReportManager._get_report_folder(ORIGINAL))
    companion = folder / "forecast_track_record.json"
    assert companion.is_file()
    tampered = _read_json(companion)
    tampered["n_reports"] = 999
    companion.write_text(json.dumps(tampered), encoding="utf-8")
    sealed = {name: _sha256(folder / name) for name in ("forecast.json", "full_report.md", "final_audit.json")}
    with pytest.raises(RuntimeError, match="track_record_mismatch"):
        agent._enforce_final_publish_audit(ORIGINAL, report)
    assert {name: _sha256(folder / name) for name in sealed} == sealed
    assert ReportManager.publication_status(ORIGINAL)["publishable"] is False
    assert client.get(f"/api/report/{ORIGINAL}/forecast").status_code == 409
    assert client.get(f"/api/report/{ORIGINAL}/download").status_code == 409
