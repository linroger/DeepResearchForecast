"""EVAL-19 (P07 part 1/2): frozen evaluation bundle (app/services/eval_bundle.py), its
post-publication capture (ledger_commit.run_post_publication, EVAL_BUNDLE_CAPTURE) and
the backfill / verify CLI (backend/scripts/eval_bundle.py). Offline: no LLM, no network."""

import hashlib
import json
import os
from types import SimpleNamespace

import pytest

from app.config import Config
from app.services import eval_bundle as eb
from app.services import ledger_commit
from app.services.report_agent import ReportManager

ACTORS = {"as_of_date": "2026-06-30", "central_question": "Will grid demand exceed 230 GW?",
          "situation_brief": {"current_situation": "Demand is rising."},
          "actors": [{"name": "EIA", "type": "agency", "role": "publishes the data"}],
          "quantitative_facts": [{"metric": "US data-centre demand", "value": "150", "unit": "GW",
                                  "as_of_date": "2026-03-31", "source": "EIA", "tier": "S1"}],
          "forecast_inputs": {"base_rates": [{"reference_class": "grid build-outs", "outcome_frequency": "30%",
                                              "basis": "EIA history"}]}}
FORECAST = {"binary_forecasts": [
    {"id": "F3", "statement": "s3", "probability": 0.3, "resolution_criteria": "c3", "horizon_year": 2030},
    {"id": "F1", "statement": "s1", "probability": 0.6, "resolution_criteria": "c1", "horizon_year": 2030,
     "market_anchor": {"market_id": "m1", "resolution_equivalence": "near", "price_at_research": 0.5}},
    {"id": "F2", "statement": "s2", "probability": 0.45, "resolution_criteria": "c2 by 2027-12-31",
     "market_anchor": {"market_id": "m2", "resolution_equivalence": "exact", "price_at_research": 0.4},
     "market_influence": {"prior_probability": 0.55}},
]}


class _Zep:
    def __init__(self, facts=("EIA: demand 150 GW", "DOE: grid plan")):
        self.calls = []
        self.facts = list(facts)

    def as_of_search(self, graph_id, query, as_of, limit=20):
        self.calls.append((graph_id, query, as_of, limit))
        return SimpleNamespace(facts=self.facts)


def _agent(health="ok", **over):
    agent = SimpleNamespace(
        actors=ACTORS, research_report="# Dossier\n\n" + "Body text. " * 50,
        _market_pack="| # | market |\n| 1 | Will X? |", _signal_pack="【内部情景推演】 signals",
        _run_summary_health=lambda: (health, False), simulation_requirement="Will grid demand exceed 230 GW?",
        graph_id="g1", simulation_id="sim1", zep_tools=_Zep(),
        ledger_context={"pipeline_id": "pipe1", "as_of_date": "2026-06-30"})
    for key, value in over.items():
        setattr(agent, key, value)
    return agent


@pytest.fixture
def report_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(ReportManager, "REPORTS_DIR", str(tmp_path / "reports"), raising=False)
    path = ReportManager._get_report_folder("r1")
    os.makedirs(path, exist_ok=True)
    with open(os.path.join(path, "full_report.md"), "w", encoding="utf-8") as f:
        f.write("# Report\n")
    with open(os.path.join(path, "forecast.json"), "w", encoding="utf-8") as f:
        json.dump(FORECAST, f)
    return path


def _sha(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


# ------------------------------------------------------------------ capture hook
def _post_publication(agent, *, publishable=True):
    return ledger_commit.run_post_publication(
        agent, "r1", report_status="completed", error=None,
        publication_status_fn=lambda rid: {"publishable": publishable},
        load_forecast_fn=lambda rid: json.loads(json.dumps(FORECAST)))


def test_flag_off_no_files_and_forecast_bytes_identical(report_dir, monkeypatch):
    monkeypatch.setattr(Config, "EVAL_BUNDLE_CAPTURE", False, raising=False)
    before = {name: _sha(os.path.join(report_dir, name)) for name in ("full_report.md", "forecast.json")}
    receipt = _post_publication(_agent())
    assert not os.path.exists(eb.bundle_dir_for(report_dir))
    assert {name: _sha(os.path.join(report_dir, name)) for name in before} == before
    assert "eval_bundle" not in receipt
    # on, but unpublishable: nothing either
    monkeypatch.setattr(Config, "EVAL_BUNDLE_CAPTURE", True, raising=False)
    _post_publication(_agent(), publishable=False)
    assert not os.path.exists(eb.bundle_dir_for(report_dir))


def test_capture_on_writes_the_bundle_and_leaves_the_report_alone(report_dir, monkeypatch):
    monkeypatch.setattr(Config, "EVAL_BUNDLE_CAPTURE", True, raising=False)
    before = {name: _sha(os.path.join(report_dir, name)) for name in ("full_report.md", "forecast.json")}
    _post_publication(_agent())
    manifest, texts = eb.load_bundle(eb.bundle_dir_for(report_dir))
    assert {name: _sha(os.path.join(report_dir, name)) for name in before} == before
    assert manifest["publication"] == {"markdown_sha256": before["full_report.md"],
                                       "forecast_sha256": before["forecast.json"]}
    assert texts["market"] == "| # | market |\n| 1 | Will X? |"


def test_capture_failure_never_breaks_the_report(report_dir, monkeypatch):
    monkeypatch.setattr(Config, "EVAL_BUNDLE_CAPTURE", True, raising=False)
    monkeypatch.setattr(eb, "capture_from_agent", lambda *a, **k: (_ for _ in ()).throw(OSError("disk full")))
    receipt = _post_publication(_agent())
    assert receipt["report_id"] == "r1"


# ------------------------------------------------------------------ manifest
def test_manifest_block_hashes_and_targets(report_dir, monkeypatch):
    monkeypatch.setattr(Config, "EVAL_DOSSIER_CHARS", 200, raising=False)
    agent = _agent()
    manifest = eb.capture_from_agent(agent, "r1", report_dir=report_dir, forecast=FORECAST)
    bundle = eb.bundle_dir_for(report_dir)
    assert manifest["schema"] == "drf-eval-bundle/v1"
    assert set(manifest["blocks"]) == set(eb.BLOCK_NAMES)
    for name, meta in manifest["blocks"].items():
        assert meta["status"] == "ok", name
        path = os.path.join(bundle, "blocks", f"{name}.txt")
        assert _sha(path) == meta["sha256"] and len(open(path, encoding="utf-8").read()) == meta["chars"]
    assert manifest["blocks"]["dossier"]["chars"] <= 200 + 50     # head + tail slice of the budget
    assert manifest["ids"] == {"pipeline": "pipe1", "report": "r1", "simulation": "sim1", "graph": "g1"}
    assert manifest["as_of"] == "2026-06-30" and manifest["central_question"].startswith("Will grid")
    assert agent.zep_tools.calls == [("g1", "Will grid demand exceed 230 GW?", "2026-06-30", 20)]
    assert [t["target_id"] for t in manifest["targets"]] == ["F2", "F1", "F3"]
    assert manifest["bundle_sha256"] == eb.bundle_sha256(manifest["blocks"], manifest["targets"])
    loaded, texts = eb.load_bundle(bundle)
    assert loaded == manifest and texts["sim"] == "【内部情景推演】 signals"


def test_one_byte_tamper_fails_closed(report_dir, capsys):
    from scripts import eval_bundle as cli
    eb.capture_from_agent(_agent(), "r1", report_dir=report_dir, forecast=FORECAST)
    bundle = eb.bundle_dir_for(report_dir)
    assert cli.main(["verify", bundle]) == 0
    path = os.path.join(bundle, "blocks", "brief.txt")
    data = open(path, "rb").read()
    with open(path, "wb") as f:
        f.write(data[:-1] + bytes([data[-1] ^ 1]))
    with pytest.raises(eb.BundleIntegrityError, match="brief sha256 mismatch"):
        eb.load_bundle(bundle)
    assert cli.main(["verify", bundle]) == cli.EXIT_INTEGRITY
    assert '"intact": false' in capsys.readouterr().out
    # a deleted block and an edited target fail too
    with open(path, "wb") as f:
        f.write(data)
    eb.load_bundle(bundle)
    manifest_path = os.path.join(bundle, eb.MANIFEST_NAME)
    manifest = json.load(open(manifest_path, encoding="utf-8"))
    manifest["targets"][0]["published_probability"] = 0.99
    json.dump(manifest, open(manifest_path, "w", encoding="utf-8"))
    with pytest.raises(eb.BundleIntegrityError, match="bundle_sha256"):
        eb.load_bundle(bundle)


def test_hollow_sim_unavailable(report_dir):
    sim_file = os.path.join(eb.bundle_dir_for(report_dir), "blocks", "sim.txt")
    eb.capture_from_agent(_agent("ok"), "r1", report_dir=report_dir, forecast=FORECAST)
    assert os.path.exists(sim_file)
    for health in ("hollow", "errored", "truncated"):
        manifest = eb.capture_from_agent(_agent(health), "r1", report_dir=report_dir, forecast=FORECAST)
        assert manifest["blocks"]["sim"] == {"sha256": None, "chars": 0, "status": f"unavailable:{health}"}
        # a re-capture removes the earlier capture's block, so the bundle stays intact
        assert not os.path.exists(sim_file)
        eb.load_bundle(eb.bundle_dir_for(report_dir))


def test_missing_inputs_degrade_per_block(report_dir):
    agent = _agent(actors=None, _market_pack="", graph_id=None, research_report="")
    manifest = eb.capture_from_agent(agent, "r1", report_dir=report_dir, forecast=None)
    statuses = {name: meta["status"] for name, meta in manifest["blocks"].items()}
    assert statuses["brief"] == statuses["quant"] == statuses["forecast_inputs"] == "unavailable:no_actors"
    assert statuses["dossier"] == "unavailable:no_research_report"
    assert statuses["market"] == "unavailable:no_market_pack"
    assert statuses["graph"] == "unavailable:no_graph_context"
    assert manifest["targets"] == []


def test_select_targets_deterministic_prefers_exact():
    targets = eb.select_targets(FORECAST, 2)
    assert [t["target_id"] for t in targets] == ["F2", "F1"]
    assert targets[0]["pre_market_probability"] == 0.55 and targets[0]["published_probability"] == 0.45
    assert targets[0]["market_anchor"] == {"market_id": "m2", "equivalence": "exact", "price_at_research": 0.4}
    assert targets[0]["resolution_date"] == "2027-12-31"
    assert targets[1]["pre_market_probability"] == 0.6
    assert eb.select_targets(json.loads(json.dumps(FORECAST)), 2) == targets
    assert eb.select_targets({}, 5) == [] and eb.select_targets(None, 5) == []


# ------------------------------------------------------------------ backfill
def test_backfill_from_fixture_handoff(report_dir, tmp_path, monkeypatch, capsys):
    from app.services import pipeline_orchestrator as po
    from scripts import eval_bundle as cli
    handoff = tmp_path / "handoff"
    handoff.mkdir()
    (handoff / "actors.json").write_text(json.dumps(ACTORS), encoding="utf-8")
    (handoff / "research_report.md").write_text("# Dossier\n\nBody.", encoding="utf-8")
    (handoff / "prediction_markets.json").write_text(json.dumps({"markets": [
        {"market_id": "m1", "question": "Will X?", "implied_yes_prob": 0.4, "volume": 1000}]}), encoding="utf-8")
    state = {"pipeline_id": "pipe1", "report_id": "r1", "handoff_dir": str(handoff), "simulation_id": "sim1",
             "graph_id": "g1", "prompt": "Will grid demand exceed 230 GW?", "options": {}}
    monkeypatch.setattr(po.PipelineManager, "load", classmethod(lambda cls, pid: state if pid == "pipe1" else None))
    monkeypatch.setattr(ReportManager, "publication_status", classmethod(lambda cls, rid: {"publishable": True}))
    assert cli.main(["backfill", "--pipeline", "pipe1"]) == 0
    result = json.loads(capsys.readouterr().out)["results"][0]
    assert result["status"] == "written"
    manifest, texts = eb.load_bundle(eb.bundle_dir_for(report_dir))
    assert manifest["blocks"]["sim"]["status"] == manifest["blocks"]["graph"]["status"] == "unavailable:not_persisted"
    assert manifest["blocks"]["market"]["note"] == "backfill_research_snapshot" and "Will X?" in texts["market"]
    assert manifest["as_of"] == "2026-06-30" and manifest["central_question"].startswith("Will grid")
    # an existing bundle is kept unless --force; an unknown pipeline is skipped
    assert cli.main(["backfill", "--pipeline", "pipe1"]) == 0
    assert json.loads(capsys.readouterr().out)["results"][0]["reason"] == "bundle_exists"
    assert cli.main(["backfill", "--pipeline", "nope"]) == 0
    assert json.loads(capsys.readouterr().out)["results"][0]["reason"] == "pipeline_not_found"


def test_knobs_default_and_documented():
    assert Config.EVAL_BUNDLE_CAPTURE is False and Config.EVAL_DOSSIER_CHARS == 16000
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    text = open(os.path.join(root, ".env.example"), encoding="utf-8").read()
    assert "# EVAL_BUNDLE_CAPTURE=false" in text and "# EVAL_DOSSIER_CHARS=16000" in text
