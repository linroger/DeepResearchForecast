"""EVAL-19 (P07 part 1/2): frozen evaluation bundle (app/services/eval_bundle.py), its
post-publication capture (ledger_commit.run_post_publication, EVAL_BUNDLE_CAPTURE) and
the backfill / verify CLI (backend/scripts/eval_bundle.py). Offline: no LLM, no network;
the pipeline store and the report store live under tmp_path."""

import hashlib
import json
import os
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from app.config import Config
from app.services import eval_bundle as eb
from app.services import forecast_ledger as fl
from app.services import ledger_commit
from app.services.report_agent import ReportManager
from app.utils import prediction_markets as pm

PID = "pipe_eval19"
NOW = datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc)
RESOLVED = {"report": {"provider": "fake", "model": "fake-report-1"},
            "research": {"provider": "fake", "model": "fake-research-1"}}
QUESTION = "Will grid demand exceed 230 GW?"
ACTORS = {"as_of_date": "2026-06-30", "central_question": QUESTION,
          "situation_brief": {"current_situation": "Demand is rising."},
          "actors": [{"name": "EIA", "type": "agency", "role": "publishes the data"}],
          "quantitative_facts": [{"metric": "US data-centre demand", "value": "150", "unit": "GW",
                                  "as_of_date": "2026-03-31", "source": "EIA", "tier": "S1"}],
          "forecast_inputs": {"base_rates": [{"reference_class": "grid build-outs", "outcome_frequency": "30%",
                                              "basis": "EIA history"}]}}
FORECAST = {
    "horizon": "2026-2030",
    "scenarios": [{"name": "Exceeds", "probability": 0.4, "resolution_criteria": "EIA > 230 GW"},
                  {"name": "Falls short", "probability": 0.6, "resolution_criteria": "EIA <= 230 GW"}],
    "binary_forecasts": [
        {"id": "F3", "statement": "s3", "probability": 0.3, "resolution_criteria": "c3", "horizon_year": 2030},
        {"id": "F1", "statement": "s1", "probability": 0.6, "resolution_criteria": "c1", "horizon_year": 2030,
         "market_anchor": {"market_id": "m1", "resolution_equivalence": "near", "price_at_research": 0.5}},
        {"id": "F2", "statement": "s2", "probability": 0.45, "resolution_criteria": "c2 by 2027-12-31",
         "market_anchor": {"market_id": "m2", "resolution_equivalence": "exact", "price_at_research": 0.4},
         "market_influence": {"prior_probability": 0.55}},
    ]}
MARKDOWN = "# Report\n\nGrid demand outlook.\n"


class _Zep:
    def __init__(self, facts=("EIA: demand 150 GW", "DOE: grid plan"), degraded=False):
        self.calls = []
        self.facts = list(facts)
        self.degraded = degraded

    def as_of_search(self, graph_id, query, as_of, limit=20):
        self.calls.append((graph_id, query, as_of, limit))
        return SimpleNamespace(facts=self.facts, degraded=self.degraded)


def _agent(health="ok", **over):
    agent = SimpleNamespace(
        actors=ACTORS, research_report="# Dossier\n\n" + "Body text. " * 50,
        _market_pack="| # | market |\n| 1 | Will X? |", _signal_pack="【内部情景推演】 signals",
        _run_summary_health=lambda: (health, False), simulation_requirement=QUESTION,
        graph_id="g1", simulation_id="sim1", zep_tools=_Zep(),
        ledger_context={"pipeline_id": PID, "as_of_date": "2026-06-30", "run_kind": "pipeline", "seed": 7})
    for key, value in over.items():
        setattr(agent, key, value)
    return agent


@pytest.fixture(autouse=True)
def pipelines(tmp_path, monkeypatch):
    """Hermetic pipeline store: owner lookups and run.json reads never see real runs. The
    ledger (isolated by conftest) commits in its default 'published' mode."""
    root = tmp_path / "pipelines"
    monkeypatch.setattr(Config, "PIPELINE_DATA_DIR", str(root), raising=False)
    monkeypatch.setattr(Config, "REPORT_FORECAST_LEDGER", True, raising=False)
    monkeypatch.setattr(Config, "FORECAST_LEDGER_COMMIT_MODE", "published", raising=False)
    return root


def _write_pipeline(root, pid=PID, *, resolved=RESOLVED, created_at="2026-09-30T00:00:00", **state):
    folder = root / pid
    folder.mkdir(parents=True, exist_ok=True)
    data = {"schema_version": 2, "pipeline_id": pid, "created_at": created_at, "options": {}}
    data.update(state)
    (folder / "pipeline_state.json").write_text(json.dumps(data), encoding="utf-8")
    if resolved is not None:
        (folder / "run.json").write_text(json.dumps({"schema": "run/v1", "resolved": resolved}), encoding="utf-8")
    return folder


@pytest.fixture
def report_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(ReportManager, "REPORTS_DIR", str(tmp_path / "reports"), raising=False)
    return _write_report("r1")


def _write_report(report_id, forecast_text=None):
    path = ReportManager._get_report_folder(report_id)
    os.makedirs(path, exist_ok=True)
    with open(os.path.join(path, "full_report.md"), "w", encoding="utf-8") as f:
        f.write(MARKDOWN)
    with open(os.path.join(path, "forecast.json"), "w", encoding="utf-8") as f:
        f.write(forecast_text if forecast_text is not None else json.dumps(FORECAST, indent=2))
    return path


def _seal(report_id):
    """meta.json + final_audit.json sealing the report's current Markdown and forecast.json
    bytes, exactly as the final audit does (real publication_status / load_structured_forecast)."""
    folder = ReportManager._get_report_folder(report_id)
    with open(os.path.join(folder, "meta.json"), "w", encoding="utf-8") as f:
        json.dump({"report_id": report_id, "status": "completed", "failed_sections": [], "partial": False,
                   "completed_at": "2026-09-30T10:00:00+00:00"}, f)
    audit = {"schema_version": 2, "policy_version": int(Config.REPORT_FINAL_AUDIT_POLICY_VERSION),
             "report_id": report_id, "hard_issues": [], "hard_passed": True,
             "markdown_sha256": _sha(os.path.join(folder, "full_report.md")),
             "structured_forecast": {"required": True, "present": True, "valid": True},
             "scenario_contract": {"valid": True}, "citation_artifacts": {"required": False},
             "publish_gate": {"enabled": False},
             "forecast_sha256": _sha(os.path.join(folder, "forecast.json"))}
    with open(os.path.join(folder, "final_audit.json"), "w", encoding="utf-8") as f:
        json.dump(audit, f)


def _sha(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def _report_bytes(report_dir):
    return {name: _sha(os.path.join(report_dir, name)) for name in sorted(os.listdir(report_dir))
            if os.path.isfile(os.path.join(report_dir, name))}


# ------------------------------------------------------------------ capture hook
def _post_publication(agent, *, publishable=True, now=None):
    return ledger_commit.run_post_publication(
        agent, "r1", report_status="completed", error=None,
        publication_status_fn=lambda rid: {"publishable": publishable},
        load_forecast_fn=lambda rid: json.loads(json.dumps(FORECAST)), now=now)


def _publish_for_real(agent):
    return ledger_commit.run_post_publication(
        agent, "r1", report_status="completed", error=None,
        publication_status_fn=ReportManager.publication_status,
        load_forecast_fn=ReportManager.load_structured_forecast, now=NOW)


def _ledger_row(report_id):
    rows = [r for r in fl.read_ledger() if r.get("report_id") == report_id]
    assert len(rows) == 1, rows
    return rows[0]


def test_flag_off_no_files_and_forecast_bytes_identical(report_dir, monkeypatch):
    monkeypatch.setattr(Config, "EVAL_BUNDLE_CAPTURE", False, raising=False)
    before = _report_bytes(report_dir)
    receipt = _post_publication(_agent())
    assert not os.path.exists(eb.bundle_dir_for(report_dir))
    assert _report_bytes(report_dir) == before
    assert "eval_bundle" not in receipt
    # on, but unpublishable: nothing either
    monkeypatch.setattr(Config, "EVAL_BUNDLE_CAPTURE", True, raising=False)
    _post_publication(_agent(), publishable=False)
    assert not os.path.exists(eb.bundle_dir_for(report_dir))


def test_capture_on_keeps_report_bytes_publishability_and_ledger_as_of(report_dir, pipelines, monkeypatch):
    """Real publication_status / load_structured_forecast: capture changes neither the
    report's bytes nor its publishability, and the bundle's as_of is the ledger row's."""
    monkeypatch.setattr(Config, "EVAL_BUNDLE_CAPTURE", True, raising=False)
    _write_pipeline(pipelines)
    _seal("r1")
    status_before = ReportManager.publication_status("r1")
    assert status_before["publishable"] is True
    before = _report_bytes(report_dir)
    receipt = _publish_for_real(_agent())
    assert receipt["status"] == "committed"
    manifest, texts = eb.load_bundle(eb.bundle_dir_for(report_dir))
    assert _report_bytes(report_dir) == before
    assert ReportManager.publication_status("r1") == status_before
    assert manifest["publication"] == {"markdown_sha256": before["full_report.md"],
                                       "forecast_sha256": before["forecast.json"]}
    assert manifest["capture"] == "in_pipeline" and manifest["upstream_models"] == RESOLVED
    assert manifest["run"] == {"record_class": "production", "run_kind": "pipeline", "seed": 7}
    row = _ledger_row("r1")
    assert (manifest["as_of"], manifest["as_of_source"]) == (row["as_of_date"], row["as_of_source"]) \
        == ("2026-06-30", "validated")
    assert [t["target_id"] for t in manifest["targets"]] == ["F2", "F1", "F3"]
    assert texts["market"] == "| # | market |\n| 1 | Will X? |"


def test_api_path_takes_the_owning_pipelines_identity(report_dir, pipelines, monkeypatch):
    """/api/report/generate (no ledger_context): the bundle is keyed like the ledger row,
    on the owning pipeline's validated anchor, never on the raw actors date."""
    monkeypatch.setattr(Config, "EVAL_BUNDLE_CAPTURE", True, raising=False)
    _write_pipeline(pipelines, simulation_id="sim1", options={"as_of_date_validated": "2026-06-15"})
    _seal("r1")
    agent = _agent(ledger_context=None, actors=dict(ACTORS, as_of_date="June 2026"))
    _publish_for_real(agent)
    manifest, _texts = eb.load_bundle(eb.bundle_dir_for(report_dir))
    row = _ledger_row("r1")
    assert manifest["ids"]["pipeline"] == PID and manifest["upstream_models"] == RESOLVED
    assert (manifest["as_of"], manifest["as_of_source"]) == (row["as_of_date"], row["as_of_source"]) \
        == ("2026-06-15", "validated")
    assert agent.zep_tools.calls == [("g1", QUESTION, "2026-06-15", 20)]


@pytest.mark.parametrize("actors_as_of", ["June 2026", "2027-03-31"])
def test_unvalidated_as_of_never_reaches_the_graph(report_dir, pipelines, monkeypatch, actors_as_of):
    """A non-canonical or future actors date is not an as-of: like the ledger row, the bundle
    falls back to the commit date, and no graph facts are frozen at that cut."""
    monkeypatch.setattr(Config, "EVAL_BUNDLE_CAPTURE", True, raising=False)
    _seal("r1")
    agent = _agent(ledger_context={"pipeline_id": PID, "as_of_date": None},
                   actors=dict(ACTORS, as_of_date=actors_as_of))
    _publish_for_real(agent)
    manifest, _texts = eb.load_bundle(eb.bundle_dir_for(report_dir))
    row = _ledger_row("r1")
    assert (manifest["as_of"], manifest["as_of_source"]) == (row["as_of_date"], row["as_of_source"]) \
        == ("2026-10-01", "commit_date")
    assert manifest["blocks"]["graph"]["status"] == "unavailable:no_validated_as_of"
    assert agent.zep_tools.calls == []


def test_capture_failure_never_breaks_the_report(report_dir, monkeypatch):
    monkeypatch.setattr(Config, "EVAL_BUNDLE_CAPTURE", True, raising=False)
    monkeypatch.setattr(eb, "capture_from_agent", lambda *a, **k: (_ for _ in ()).throw(OSError("disk full")))
    receipt = _post_publication(_agent())
    assert receipt["report_id"] == "r1"


# ------------------------------------------------------------------ manifest
def test_manifest_block_hashes_and_targets(report_dir, pipelines, monkeypatch):
    monkeypatch.setattr(Config, "EVAL_DOSSIER_CHARS", 200, raising=False)
    _write_pipeline(pipelines)
    agent = _agent()
    manifest = eb.capture_from_agent(agent, "r1", report_dir=report_dir, forecast=FORECAST, now=NOW)
    bundle = eb.bundle_dir_for(report_dir)
    assert manifest["schema"] == "drf-eval-bundle/v1" and manifest["capture"] == "in_pipeline"
    assert set(manifest["blocks"]) == set(eb.BLOCK_NAMES)
    assert sorted(os.listdir(os.path.join(bundle, "blocks"))) == sorted(f"{n}.txt" for n in eb.BLOCK_NAMES)
    for name, meta in manifest["blocks"].items():
        assert meta["status"] == "ok", name
        path = os.path.join(bundle, "blocks", f"{name}.txt")
        assert _sha(path) == meta["sha256"] and len(open(path, encoding="utf-8").read()) == meta["chars"]
    assert manifest["blocks"]["dossier"]["chars"] <= 200 + 50     # head + tail slice of the budget
    assert manifest["ids"] == {"pipeline": PID, "report": "r1", "simulation": "sim1", "graph": "g1"}
    assert manifest["created_at"] == NOW.isoformat()
    assert (manifest["as_of"], manifest["as_of_source"]) == ("2026-06-30", "validated")
    assert manifest["central_question"] == QUESTION
    assert manifest["upstream_models"] == RESOLVED
    assert manifest["run"] == {"record_class": None, "run_kind": "pipeline", "seed": 7}
    assert agent.zep_tools.calls == [("g1", QUESTION, "2026-06-30", 20)]
    assert [t["target_id"] for t in manifest["targets"]] == ["F2", "F1", "F3"]
    assert manifest["bundle_sha256"] == eb.bundle_sha256(manifest["blocks"], manifest["targets"])
    assert manifest["manifest_sha256"] == eb.manifest_sha256(manifest)
    assert "note" not in manifest["blocks"]["graph"]
    loaded, texts = eb.load_bundle(bundle)
    assert loaded == manifest and texts["sim"] == "【内部情景推演】 signals"
    assert texts["graph"] == "EIA: demand 150 GW\nDOE: grid plan"


def test_one_byte_tamper_fails_closed(report_dir, capsys):
    from scripts import eval_bundle as cli
    eb.capture_from_agent(_agent(), "r1", report_dir=report_dir, forecast=FORECAST)
    bundle = eb.bundle_dir_for(report_dir)
    assert cli.main(["verify", bundle]) == 0
    assert '"intact": true' in capsys.readouterr().out
    path = os.path.join(bundle, "blocks", "brief.txt")
    data = open(path, "rb").read()
    with open(path, "wb") as f:
        f.write(data[:-1] + bytes([data[-1] ^ 1]))
    with pytest.raises(eb.BundleIntegrityError, match="brief sha256 mismatch"):
        eb.load_bundle(bundle)
    assert cli.main(["verify", bundle]) == cli.EXIT_INTEGRITY
    assert '"intact": false' in capsys.readouterr().out
    # a deleted block fails too
    os.remove(path)
    with pytest.raises(eb.BundleIntegrityError, match="brief missing"):
        eb.load_bundle(bundle)
    assert cli.main(["verify", bundle]) == cli.EXIT_INTEGRITY
    # restored, the bundle verifies again
    with open(path, "wb") as f:
        f.write(data)
    eb.load_bundle(bundle)
    assert cli.main(["verify", bundle]) == 0
    # an edited target breaks the manifest seal; re-sealing it still breaks bundle_sha256
    manifest_path = os.path.join(bundle, eb.MANIFEST_NAME)
    manifest = json.load(open(manifest_path, encoding="utf-8"))
    manifest["targets"][0]["published_probability"] = 0.99
    json.dump(manifest, open(manifest_path, "w", encoding="utf-8"))
    with pytest.raises(eb.BundleIntegrityError, match="manifest_sha256 mismatch"):
        eb.load_bundle(bundle)
    manifest["manifest_sha256"] = eb.manifest_sha256(manifest)
    json.dump(manifest, open(manifest_path, "w", encoding="utf-8"))
    with pytest.raises(eb.BundleIntegrityError, match="bundle_sha256 mismatch"):
        eb.load_bundle(bundle)
    assert cli.main(["verify", bundle]) == cli.EXIT_INTEGRITY


def _flip_ok_block_and_delete_file(manifest, bundle):
    manifest["blocks"]["brief"]["status"] = "unavailable:x"        # sha256 and chars kept
    os.remove(os.path.join(bundle, "blocks", "brief.txt"))


def _flip_resealed(manifest, bundle):
    manifest["blocks"]["brief"] = {"sha256": None, "chars": 0, "status": "unavailable:x"}
    os.remove(os.path.join(bundle, "blocks", "brief.txt"))
    manifest["manifest_sha256"] = eb.manifest_sha256(manifest)    # bundle_sha256 still old


def _flip_resealed_hash_kept(manifest, bundle):
    # Seal and bundle hash both still match: only the entry-shape check catches it.
    _flip_ok_block_and_delete_file(manifest, bundle)
    manifest["manifest_sha256"] = eb.manifest_sha256(manifest)


def _extra_block_file(manifest, bundle):
    with open(os.path.join(bundle, "blocks", "evil.txt"), "w", encoding="utf-8") as f:
        f.write("injected")


MANIFEST_EDITS = {
    "as_of": lambda m, b: m.__setitem__("as_of", "2020-01-01"),
    "as_of_source": lambda m, b: m.__setitem__("as_of_source", "actors"),
    "central_question": lambda m, b: m.__setitem__("central_question", "A different question?"),
    "ids.report": lambda m, b: m["ids"].__setitem__("report", "other"),
    "publication.markdown_sha256": lambda m, b: m["publication"].__setitem__("markdown_sha256", "f" * 64),
    "upstream_models": lambda m, b: m.__setitem__("upstream_models", {"report": {"model": "other"}}),
    "run.seed": lambda m, b: m["run"].__setitem__("seed", 8),
    "capture": lambda m, b: m.__setitem__("capture", "backfill"),
    "block note": lambda m, b: m["blocks"]["market"].__setitem__("note", "fabricated"),
    "extra manifest key": lambda m, b: m.__setitem__("extra", 1),
    "seal removed": lambda m, b: m.pop("manifest_sha256"),
    "status flip + file deleted": _flip_ok_block_and_delete_file,
    "status flip resealed": _flip_resealed,
    "status flip resealed, hash kept": _flip_resealed_hash_kept,
    "extra block file": _extra_block_file,
}


@pytest.mark.parametrize("edit", sorted(MANIFEST_EDITS))
def test_any_manifest_edit_fails_closed(report_dir, pipelines, edit):
    from scripts import eval_bundle as cli
    _write_pipeline(pipelines)
    eb.capture_from_agent(_agent(), "r1", report_dir=report_dir, forecast=FORECAST)
    bundle = eb.bundle_dir_for(report_dir)
    assert cli.main(["verify", bundle]) == 0
    manifest_path = os.path.join(bundle, eb.MANIFEST_NAME)
    manifest = json.load(open(manifest_path, encoding="utf-8"))
    MANIFEST_EDITS[edit](manifest, bundle)
    json.dump(manifest, open(manifest_path, "w", encoding="utf-8"))
    with pytest.raises(eb.BundleIntegrityError):
        eb.load_bundle(bundle)
    assert cli.main(["verify", bundle]) == cli.EXIT_INTEGRITY


MALFORMED = {
    "block entry not an object": lambda m: m["blocks"].__setitem__("brief", "ok"),
    "NaN target": lambda m: m["targets"][0].__setitem__("published_probability", float("nan")),
    "targets not a list": lambda m: m.__setitem__("targets", {"F1": 0.4}),
    "unknown status": lambda m: m["blocks"]["sim"].__setitem__("status", "maybe"),
    "bare unavailable": lambda m: m["blocks"]["sim"].__setitem__("status", "unavailable:"),
    "ok without hash": lambda m: m["blocks"]["sim"].__setitem__("sha256", None),
    "ok with bool chars": lambda m: m["blocks"]["sim"].__setitem__("chars", True),
    "missing block": lambda m: m["blocks"].pop("graph"),
    "other schema": lambda m: m.__setitem__("schema", "drf-eval-bundle/v0"),
    "no schema": lambda m: m.pop("schema"),
}


@pytest.mark.parametrize("case", sorted(MALFORMED))
def test_malformed_manifest_raises_integrity_error_only(report_dir, case, capsys):
    from scripts import eval_bundle as cli
    eb.capture_from_agent(_agent(), "r1", report_dir=report_dir, forecast=FORECAST)
    bundle = eb.bundle_dir_for(report_dir)
    manifest_path = os.path.join(bundle, eb.MANIFEST_NAME)
    manifest = json.load(open(manifest_path, encoding="utf-8"))
    MALFORMED[case](manifest)
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f)                                       # allow_nan: writes NaN
    with pytest.raises(eb.BundleIntegrityError):
        eb.load_bundle(bundle)
    assert cli.main(["verify", bundle]) == cli.EXIT_INTEGRITY
    assert json.loads(capsys.readouterr().out.strip().splitlines()[-1])["intact"] is False
    with open(manifest_path, "w", encoding="utf-8") as f:
        f.write("{not json")
    assert cli.main(["verify", bundle]) == cli.EXIT_INTEGRITY


def test_write_bundle_rejects_invalid_input_before_writing(tmp_path):
    bundle = str(tmp_path / "bundle")
    meta = {"capture": "in_pipeline"}
    with pytest.raises(ValueError, match="unknown bundle block"):
        eb.write_bundle(bundle, blocks={"extra": "x"}, statuses={}, targets=[], meta=meta)
    with pytest.raises(ValueError, match="invalid status"):
        eb.write_bundle(bundle, blocks={"brief": "x"}, statuses={"brief": "fine"}, targets=[], meta=meta)
    with pytest.raises(ValueError, match="capture"):
        eb.write_bundle(bundle, blocks={"brief": "x"}, statuses={}, targets=[], meta={})
    with pytest.raises(ValueError):
        eb.write_bundle(bundle, blocks={"brief": "x"}, statuses={},
                        targets=[{"target_id": "F1", "published_probability": float("nan")}], meta=meta)
    assert not os.path.exists(bundle)


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
    # no sealed forecast: its hash is not part of the publication
    assert manifest["publication"]["forecast_sha256"] is None
    # the owning pipeline has no run.json (and none at all without a pipeline id)
    assert manifest["ids"]["pipeline"] == PID and manifest["upstream_models"] is None
    assert eb.upstream_models(None) is None


def test_graph_block_question_unchanged_and_degraded_search_noted(report_dir):
    question = "Will grid demand exceed 230 GW " + "and stay there " * 40 + "by 2030?"
    zep = _Zep(degraded=True)
    manifest = eb.capture_from_agent(_agent(simulation_requirement=question, zep_tools=zep), "r1",
                                     report_dir=report_dir, forecast=FORECAST)
    assert len(question) > 350 and zep.calls == [("g1", question, "2026-06-30", 20)]
    assert manifest["blocks"]["graph"]["status"] == "ok"
    assert manifest["blocks"]["graph"]["note"] == "degraded_search"
    eb.load_bundle(eb.bundle_dir_for(report_dir))


def test_dossier_budget_is_one_positive_value(monkeypatch):
    for value, expected in ((200, 200), (0, 16000), (-5, 16000), ("junk", 16000), (None, 16000)):
        monkeypatch.setattr(Config, "EVAL_DOSSIER_CHARS", value, raising=False)
        assert eb.dossier_chars() == expected, value


def test_select_targets_deterministic_prefers_exact():
    targets = eb.select_targets(FORECAST, 2)
    assert [t["target_id"] for t in targets] == ["F2", "F1"]
    assert targets[0]["pre_market_probability"] == 0.55 and targets[0]["published_probability"] == 0.45
    assert targets[0]["market_anchor"] == {"market_id": "m2", "equivalence": "exact", "price_at_research": 0.4}
    assert targets[0]["resolution_date"] == "2027-12-31"
    assert targets[1]["pre_market_probability"] == 0.6
    assert eb.select_targets(json.loads(json.dumps(FORECAST)), 2) == targets
    assert eb.select_targets({}, 5) == [] and eb.select_targets(None, 5) == []


def test_select_targets_natural_id_order_and_case_insensitive_exact():
    rows = [{"id": f"F{i}", "statement": f"s{i}", "probability": 0.5} for i in range(13, 0, -1)]
    assert [t["target_id"] for t in eb.select_targets({"binary_forecasts": rows}, 12)] \
        == [f"F{i}" for i in range(1, 13)]
    rows[0]["market_anchor"] = {"market_id": "m13", "resolution_equivalence": " EXACT "}
    assert [t["target_id"] for t in eb.select_targets({"binary_forecasts": rows}, 3)] == ["F13", "F1", "F2"]
    assert [t["target_id"] for t in eb.select_targets({"binary_forecasts": [
        {"id": "F10"}, {"id": "F2"}, {"id": "Q"}, {"id": "F1"}]})] == ["F1", "F2", "F10", "Q"]


# ------------------------------------------------------------------ backfill
def _handoff(tmp_path, *, markets_payload=None, name="handoff"):
    handoff = tmp_path / name
    handoff.mkdir()
    (handoff / "actors.json").write_text(json.dumps(ACTORS), encoding="utf-8")
    (handoff / "research_report.md").write_text("# Dossier\n\nBody.", encoding="utf-8")
    payload = markets_payload if markets_payload is not None else {
        "as_of": "2026-06-30T12:00:00Z",
        "markets": [{"market_id": "m1", "question": "Will X?", "implied_yes_prob": 0.4, "volume": 1000}]}
    (handoff / "prediction_markets.json").write_text(json.dumps(payload), encoding="utf-8")
    return handoff


def _backfill_pipeline(pipelines, handoff, pid=PID, report_id="r1", **state):
    return _write_pipeline(pipelines, pid, report_id=report_id, handoff_dir=str(handoff), simulation_id="sim1",
                           graph_id="g1", prompt=QUESTION, **state)


def _run_cli(capsys, *argv):
    from scripts import eval_bundle as cli
    code = cli.main(list(argv))
    return code, json.loads(capsys.readouterr().out)


def test_backfill_from_fixture_handoff(report_dir, pipelines, tmp_path, capsys):
    _backfill_pipeline(pipelines, _handoff(tmp_path))
    _seal("r1")
    code, out = _run_cli(capsys, "backfill", "--pipeline", PID)
    assert code == 0 and out["results"][0]["status"] == "written"
    manifest, texts = eb.load_bundle(eb.bundle_dir_for(report_dir))
    assert manifest["capture"] == "backfill"
    assert manifest["blocks"]["sim"]["status"] == manifest["blocks"]["graph"]["status"] == "unavailable:not_persisted"
    assert manifest["blocks"]["market"]["note"] == "backfill_research_snapshot" and "Will X?" in texts["market"]
    assert (manifest["as_of"], manifest["as_of_source"]) == ("2026-06-30", "actors")
    assert manifest["central_question"] == QUESTION and manifest["upstream_models"] == RESOLVED
    assert manifest["ids"] == {"pipeline": PID, "report": "r1", "simulation": "sim1", "graph": "g1"}
    assert manifest["run"] == {"record_class": None, "run_kind": "pipeline", "seed": None}
    # the audit-sealed forecast supplies the targets and the publication hash
    assert [t["target_id"] for t in manifest["targets"]] == ["F2", "F1", "F3"]
    assert manifest["publication"]["forecast_sha256"] == _sha(os.path.join(report_dir, "forecast.json"))
    # an existing bundle is kept unless --force; an unknown or invalid pipeline is skipped
    code, out = _run_cli(capsys, "backfill", "--pipeline", PID)
    assert code == 0 and out["results"][0]["reason"] == "bundle_exists"
    code, out = _run_cli(capsys, "backfill", "--pipeline", "pipe_nope")
    assert code == 0 and out["results"][0]["reason"] == "pipeline_not_found"
    code, out = _run_cli(capsys, "backfill", "--pipeline", "../escape")
    assert code == 0 and out["results"][0]["reason"] == "pipeline_not_found"


@pytest.mark.parametrize("forecast_state", ["unsealed", "tampered_after_audit"])
def test_backfill_targets_only_from_the_sealed_forecast(report_dir, pipelines, tmp_path, monkeypatch, capsys,
                                                       forecast_state):
    """A legacy publishable report (publication_status does not check forecast.json) whose
    sidecar is unsealed or changed after the audit contributes no targets."""
    monkeypatch.setattr(ReportManager, "publication_status", classmethod(lambda cls, rid: {"publishable": True}))
    _backfill_pipeline(pipelines, _handoff(tmp_path))
    if forecast_state == "tampered_after_audit":
        _seal("r1")
        tampered = dict(FORECAST, binary_forecasts=[dict(FORECAST["binary_forecasts"][0], probability=0.99)])
        _write_report("r1", json.dumps(tampered, indent=2))
    code, out = _run_cli(capsys, "backfill", "--pipeline", PID)
    assert code == 0 and out["results"][0]["status"] == "written"
    manifest, _texts = eb.load_bundle(eb.bundle_dir_for(report_dir))
    assert manifest["targets"] == [] and manifest["publication"]["forecast_sha256"] is None


def test_backfill_skips_unpublishable_reports(report_dir, pipelines, tmp_path, capsys):
    _backfill_pipeline(pipelines, _handoff(tmp_path))        # no meta.json / audit: not publishable
    code, out = _run_cli(capsys, "backfill", "--pipeline", PID)
    assert code == 0 and out["results"][0]["reason"] == "not_publishable"
    assert not os.path.exists(eb.bundle_dir_for(report_dir))


def test_backfill_market_block_is_pinned_to_the_snapshot_time(report_dir, pipelines, tmp_path, monkeypatch,
                                                            capsys):
    """The TIME-3 end-date gate is evaluated at the snapshot time, never at the backfill
    date: re-backfilling the same run gives the same bytes and the same bundle hash."""
    monkeypatch.setattr(Config, "PREDICTION_MARKETS_END_DATE_GATE", True, raising=False)
    markets = [{"market_id": "m1", "question": "Will X by August?", "implied_yes_prob": 0.4,
                "end_date": "2026-08-31"},                                   # ends after the snapshot
               {"market_id": "m2", "question": "Did Y by May?", "implied_yes_prob": 0.1,
                "end_date": "2026-05-31"}]                                   # ended before it
    _backfill_pipeline(pipelines, _handoff(tmp_path, markets_payload={"as_of": "2026-06-30T12:00:00Z",
                                                                      "markets": markets}))
    _seal("r1")
    rendered = []
    for clock, extra in ((datetime(2026, 6, 30, 13, tzinfo=timezone.utc), []),
                         (datetime(2026, 10, 1, tzinfo=timezone.utc), ["--force"])):
        monkeypatch.setattr(pm, "market_clock_now", lambda clock=clock: clock)
        code, out = _run_cli(capsys, "backfill", "--pipeline", PID, *extra)
        assert code == 0 and out["results"][0]["status"] == "written"
        manifest, texts = eb.load_bundle(eb.bundle_dir_for(report_dir))
        rendered.append((texts["market"], manifest["bundle_sha256"]))
    assert rendered[0] == rendered[1]
    market = rendered[0][0]
    assert "window ended 2026-05-31" in market and "window ended 2026-08-31" not in market
    # the wall-clock render of the same rows would differ on 2026-10-01
    assert "window ended 2026-08-31" in pm.render_markets_block(markets)


def test_research_market_block_snapshot_time_fallbacks(monkeypatch):
    monkeypatch.setattr(Config, "PREDICTION_MARKETS_END_DATE_GATE", True, raising=False)
    monkeypatch.setattr(pm, "market_clock_now", lambda: datetime(2026, 10, 1, tzinfo=timezone.utc))
    rows = [{"market_id": "m1", "question": "Will X?", "implied_yes_prob": 0.4, "end_date": "2026-08-31"}]
    text, status = eb.research_market_block({"markets": rows}, fallback_as_of="2026-06-30")
    assert status == "ok" and "window ended" not in text                 # end of the as-of day
    assert eb.research_market_block(rows, fallback_as_of=None) == (None, "unavailable:no_snapshot_time")
    assert eb.research_market_block({"markets": []}, fallback_as_of="2026-06-30") \
        == (None, "unavailable:no_research_snapshot")
    assert eb.research_market_block(None) == (None, "unavailable:no_research_snapshot")


def test_render_markets_block_default_clock_unchanged(monkeypatch):
    monkeypatch.setattr(Config, "PREDICTION_MARKETS_END_DATE_GATE", True, raising=False)
    clock = datetime(2026, 10, 1, tzinfo=timezone.utc)
    monkeypatch.setattr(pm, "market_clock_now", lambda: clock)
    rows = [{"market_id": "m1", "question": "Will X?", "implied_yes_prob": 0.4, "end_date": "2026-08-31"}]
    assert pm.render_markets_block(rows) == pm.render_markets_block(rows, now=clock)
    assert pm.render_markets_block(rows) != pm.render_markets_block(rows, now=datetime(2026, 7, 1, tzinfo=timezone.utc))


def test_backfill_force_keeps_an_in_pipeline_bundle(report_dir, pipelines, tmp_path, capsys):
    _backfill_pipeline(pipelines, _handoff(tmp_path))
    _seal("r1")
    eb.capture_from_agent(_agent(), "r1", report_dir=report_dir, forecast=FORECAST)
    code, out = _run_cli(capsys, "backfill", "--pipeline", PID, "--force")
    assert code == 0 and out["results"][0]["reason"] == "in_pipeline_bundle_exists"
    assert eb.load_bundle(eb.bundle_dir_for(report_dir))[0]["capture"] == "in_pipeline"
    code, out = _run_cli(capsys, "backfill", "--pipeline", PID, "--force", "--replace-in-pipeline")
    assert code == 0 and out["results"][0]["status"] == "written"
    manifest, texts = eb.load_bundle(eb.bundle_dir_for(report_dir))
    assert manifest["capture"] == "backfill" and texts["sim"] is None and texts["graph"] is None


def test_backfill_isolates_one_pipelines_failure(tmp_path, pipelines, monkeypatch, capsys):
    """A NaN probability in one sealed forecast aborts only that pipeline's row."""
    monkeypatch.setattr(ReportManager, "REPORTS_DIR", str(tmp_path / "reports"), raising=False)
    nan_forecast = dict(FORECAST, binary_forecasts=[dict(FORECAST["binary_forecasts"][0], probability=float("nan"))])
    _write_report("r_nan", json.dumps(nan_forecast, indent=2))
    _seal("r_nan")
    good_dir = _write_report("r_good")
    _seal("r_good")
    _backfill_pipeline(pipelines, _handoff(tmp_path, name="h_nan"), pid="pipe_nan", report_id="r_nan",
                       created_at="2026-09-30T02:00:00")
    _backfill_pipeline(pipelines, _handoff(tmp_path, name="h_good"), pid="pipe_good", report_id="r_good",
                       created_at="2026-09-30T01:00:00")
    code, out = _run_cli(capsys, "backfill", "--all-recent", "2")
    rows = {row["pipeline"]: row for row in out["results"]}
    assert code == 1 and [row["pipeline"] for row in out["results"]] == ["pipe_nan", "pipe_good"]
    assert rows["pipe_nan"]["status"] == "error" and rows["pipe_nan"]["reason"].startswith("ValueError")
    assert rows["pipe_good"]["status"] == "written"
    eb.load_bundle(eb.bundle_dir_for(good_dir))
    assert not os.path.exists(eb.bundle_dir_for(ReportManager._get_report_folder("r_nan")))


def test_knobs_default_and_documented():
    assert Config.EVAL_BUNDLE_CAPTURE is False and Config.EVAL_DOSSIER_CHARS == 16000
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    text = open(os.path.join(root, ".env.example"), encoding="utf-8").read()
    assert "# EVAL_BUNDLE_CAPTURE=false" in text and "# EVAL_DOSSIER_CHARS=16000" in text
