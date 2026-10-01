"""EVAL-19 (P07 part 1/2): frozen evaluation bundle (app/services/eval_bundle.py), its
post-publication capture (ledger_commit.run_post_publication, EVAL_BUNDLE_CAPTURE) and
the backfill / verify CLI (backend/scripts/eval_bundle.py). Offline: no LLM, no network;
the pipeline store and the report store live under tmp_path."""

import hashlib
import json
import os
import shutil
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
    def __init__(self, facts=("EIA: demand 150 GW", "DOE: grid plan"), degraded=False, error=None):
        self.calls = []
        self.facts = list(facts)
        self.degraded = degraded
        self.error = error

    def as_of_search(self, graph_id, query, as_of, limit=20):
        self.calls.append((graph_id, query, as_of, limit))
        if self.error is not None:
            raise self.error
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


@pytest.mark.parametrize("status", ["failed", "", None])
def test_failed_report_is_never_bundled(report_dir, monkeypatch, status):
    """Gated like the ledger's scored row: a report that did not complete is never bundled,
    even when publication_status still reads publishable (meta.json from an earlier save)."""
    monkeypatch.setattr(Config, "EVAL_BUNDLE_CAPTURE", True, raising=False)
    receipt = ledger_commit.run_post_publication(
        _agent(), "r1", report_status=status, error="boom",
        publication_status_fn=lambda rid: {"publishable": True},
        load_forecast_fn=lambda rid: json.loads(json.dumps(FORECAST)), now=NOW)
    assert receipt["status"] == "unpublished"
    assert not os.path.exists(eb.bundle_dir_for(report_dir))


@pytest.mark.parametrize("publication", [{"publishable": "yes"}, {"publishable": 1}, None, ["publishable"]])
def test_only_a_true_publishable_flag_is_bundled(report_dir, monkeypatch, publication):
    monkeypatch.setattr(Config, "EVAL_BUNDLE_CAPTURE", True, raising=False)
    monkeypatch.setattr(Config, "REPORT_FORECAST_LEDGER", False, raising=False)
    ledger_commit.run_post_publication(
        _agent(), "r1", report_status="completed", error=None,
        publication_status_fn=lambda rid: publication,
        load_forecast_fn=lambda rid: json.loads(json.dumps(FORECAST)), now=NOW)
    assert not os.path.exists(eb.bundle_dir_for(report_dir))


@pytest.mark.parametrize("ledger_on, bundle_on, builds", [(True, True, 1), (False, True, 1),
                                                          (True, False, 1), (False, False, 0)])
def test_report_context_is_built_once_and_shared(report_dir, monkeypatch, ledger_on, bundle_on, builds):
    """One owner lookup per report: the bundle reads the very context the ledger committed
    with, and with both steps off none is built (flag-off behaviour unchanged)."""
    monkeypatch.setattr(Config, "REPORT_FORECAST_LEDGER", ledger_on, raising=False)
    monkeypatch.setattr(Config, "EVAL_BUNDLE_CAPTURE", bundle_on, raising=False)
    built, seen = [], {}
    real_context, real_commit, real_capture = (ledger_commit._report_context, ledger_commit.commit_report,
                                               eb.capture_from_agent)

    def _counting_context(agent):
        built.append(agent)
        return real_context(agent)

    def _commit(**kwargs):
        seen["ledger"] = kwargs["ledger_context"]
        return real_commit(**kwargs)

    def _capture(*args, **kwargs):
        seen["bundle"] = kwargs["context"]
        return real_capture(*args, **kwargs)
    monkeypatch.setattr(ledger_commit, "_report_context", _counting_context)
    monkeypatch.setattr(ledger_commit, "commit_report", _commit)
    monkeypatch.setattr(eb, "capture_from_agent", _capture)
    _post_publication(_agent(), now=NOW)
    assert len(built) == builds
    if ledger_on and bundle_on:
        assert seen["bundle"] == dict(seen["ledger"], record_class="production")
        assert "record_class" not in seen["ledger"]            # the bundle step works on a copy
    assert os.path.exists(eb.bundle_dir_for(report_dir)) is bundle_on


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


def test_deeply_nested_manifest_raises_integrity_error_only(report_dir, capsys):
    from scripts import eval_bundle as cli
    eb.capture_from_agent(_agent(), "r1", report_dir=report_dir, forecast=FORECAST)
    bundle = eb.bundle_dir_for(report_dir)
    with open(os.path.join(bundle, eb.MANIFEST_NAME), "w", encoding="utf-8") as f:
        f.write("[" * 200000 + "]" * 200000)
    with pytest.raises(eb.BundleIntegrityError, match="manifest unreadable: RecursionError"):
        eb.load_bundle(bundle)
    assert cli.main(["verify", bundle]) == cli.EXIT_INTEGRITY
    assert json.loads(capsys.readouterr().out.strip().splitlines()[-1])["intact"] is False


def _stray_dir(blocks):
    os.makedirs(os.path.join(blocks, "junkdir", "nested"))
    open(os.path.join(blocks, "junkdir", "nested", "x.txt"), "w").close()


def _stray_ds_store(blocks):
    open(os.path.join(blocks, ".DS_Store"), "wb").close()


def _stray_symlinks(blocks):
    outside = os.path.join(os.path.dirname(os.path.dirname(blocks)), "outside")
    os.makedirs(outside, exist_ok=True)
    open(os.path.join(outside, "keep.txt"), "w").close()
    os.symlink(outside, os.path.join(blocks, "linkdir"))
    os.symlink(os.path.join(outside, "keep.txt"), os.path.join(blocks, "linkfile"))


@pytest.mark.parametrize("stray", [_stray_dir, _stray_ds_store, _stray_symlinks])
def test_recapture_repairs_any_stray_entry_in_blocks(report_dir, stray):
    """verify rejects anything in blocks/ the manifest does not own (directories and
    file-browser metadata included); a re-capture removes it without following links."""
    bundle = eb.bundle_dir_for(report_dir)
    eb.capture_from_agent(_agent(), "r1", report_dir=report_dir, forecast=FORECAST)
    stray(os.path.join(bundle, "blocks"))
    with pytest.raises(eb.BundleIntegrityError, match="unexpected file"):
        eb.load_bundle(bundle)
    eb.capture_from_agent(_agent(), "r1", report_dir=report_dir, forecast=FORECAST)
    eb.load_bundle(bundle)
    assert sorted(os.listdir(os.path.join(bundle, "blocks"))) == sorted(f"{n}.txt" for n in eb.BLOCK_NAMES)
    if stray is _stray_symlinks:
        assert os.path.exists(os.path.join(report_dir, "outside", "keep.txt"))   # unlinked, not followed


def test_recapture_repairs_a_directory_under_a_block_name_and_a_blocks_file(report_dir):
    bundle = eb.bundle_dir_for(report_dir)
    blocks = os.path.join(bundle, "blocks")
    eb.capture_from_agent(_agent(), "r1", report_dir=report_dir, forecast=FORECAST)
    os.remove(os.path.join(blocks, "brief.txt"))
    os.makedirs(os.path.join(blocks, "brief.txt", "inner"))
    with pytest.raises(eb.BundleIntegrityError, match="block brief missing"):
        eb.load_bundle(bundle)
    eb.capture_from_agent(_agent(), "r1", report_dir=report_dir, forecast=FORECAST)
    assert eb.load_bundle(bundle)[1]["brief"]
    shutil.rmtree(blocks)
    with open(blocks, "w", encoding="utf-8") as f:            # blocks/ is a plain file
        f.write("not a directory")
    with pytest.raises(eb.BundleIntegrityError, match="unreadable"):
        eb.load_bundle(bundle)
    eb.capture_from_agent(_agent(), "r1", report_dir=report_dir, forecast=FORECAST)
    assert os.path.isdir(blocks) and eb.load_bundle(bundle)[1]["brief"]


def test_symlinked_blocks_dir_is_replaced_not_followed(report_dir, tmp_path):
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (elsewhere / "precious.txt").write_text("keep me", encoding="utf-8")
    bundle = eb.bundle_dir_for(report_dir)
    os.makedirs(bundle)
    os.symlink(str(elsewhere), os.path.join(bundle, "blocks"))
    eb.capture_from_agent(_agent(), "r1", report_dir=report_dir, forecast=FORECAST)
    assert not os.path.islink(os.path.join(bundle, "blocks"))
    assert sorted(os.listdir(elsewhere)) == ["precious.txt"]
    eb.load_bundle(bundle)


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


def _graph_file(report_dir):
    return os.path.join(eb.bundle_dir_for(report_dir), "blocks", "graph.txt")


def test_graph_block_question_unchanged_and_degraded_search_unavailable(report_dir):
    """A degraded search is zep_tools' keyword fallback over the whole graph, with no
    as-of cut: it is never frozen, and a re-capture drops the earlier capture's facts."""
    eb.capture_from_agent(_agent(), "r1", report_dir=report_dir, forecast=FORECAST)
    assert os.path.exists(_graph_file(report_dir))
    question = "Will grid demand exceed 230 GW " + "and stay there " * 40 + "by 2030?"
    zep = _Zep(degraded=True)
    manifest = eb.capture_from_agent(_agent(simulation_requirement=question, zep_tools=zep), "r1",
                                     report_dir=report_dir, forecast=FORECAST)
    assert len(question) > 350 and zep.calls == [("g1", question, "2026-06-30", 20)]
    assert manifest["blocks"]["graph"] == {"sha256": None, "chars": 0, "status": "unavailable:degraded_search"}
    assert not os.path.exists(_graph_file(report_dir))
    _manifest, texts = eb.load_bundle(eb.bundle_dir_for(report_dir))
    assert texts["graph"] is None and texts["brief"]


def test_graph_search_error_is_unavailable(report_dir):
    zep = _Zep(error=RuntimeError("graph backend down"))
    manifest = eb.capture_from_agent(_agent(zep_tools=zep), "r1", report_dir=report_dir, forecast=FORECAST)
    assert zep.calls == [("g1", QUESTION, "2026-06-30", 20)]
    assert manifest["blocks"]["graph"] == {"sha256": None, "chars": 0, "status": "unavailable:error:RuntimeError"}
    assert not os.path.exists(_graph_file(report_dir))
    assert manifest["blocks"]["brief"]["status"] == "ok"
    eb.load_bundle(eb.bundle_dir_for(report_dir))
    # no facts at all is unavailable too, never an empty 'ok' block
    manifest = eb.capture_from_agent(_agent(zep_tools=_Zep(facts=())), "r1", report_dir=report_dir,
                                     forecast=FORECAST)
    assert manifest["blocks"]["graph"]["status"] == "unavailable:no_graph_facts"


def test_graph_facts_are_one_per_line(report_dir):
    zep = _Zep(facts=["fact one\nwith  a\r\nbroken line", "   ", "\tfact two ", 3])
    manifest = eb.capture_from_agent(_agent(zep_tools=zep), "r1", report_dir=report_dir, forecast=FORECAST)
    _manifest, texts = eb.load_bundle(eb.bundle_dir_for(report_dir))
    assert texts["graph"] == "fact one with a broken line\nfact two\n3"
    assert texts["graph"].splitlines() == ["fact one with a broken line", "fact two", "3"]
    assert manifest["blocks"]["graph"]["chars"] == len(texts["graph"])


def test_sim_block_falls_back_to_the_built_signal_pack(report_dir):
    """No cached _signal_pack: the block is what _build_signal_pack (legacy_prompt's
    source) returns; a builder that raises or returns nothing is unavailable."""
    agent = _agent(_signal_pack="", _build_signal_pack=lambda: "built signals")
    manifest = eb.capture_from_agent(agent, "r1", report_dir=report_dir, forecast=FORECAST)
    assert eb.load_bundle(eb.bundle_dir_for(report_dir))[1]["sim"] == "built signals"
    assert manifest["blocks"]["sim"]["sha256"] == hashlib.sha256(b"built signals").hexdigest()
    agent = _agent(_signal_pack="cached", _build_signal_pack=lambda: "built signals")
    eb.capture_from_agent(agent, "r1", report_dir=report_dir, forecast=FORECAST)
    assert eb.load_bundle(eb.bundle_dir_for(report_dir))[1]["sim"] == "cached"

    def _boom():
        raise RuntimeError("no simulation data")
    for builder, status in ((_boom, "unavailable:error:RuntimeError"), (lambda: "  ", "unavailable:no_signal_pack")):
        manifest = eb.capture_from_agent(_agent(_signal_pack=None, _build_signal_pack=builder), "r1",
                                         report_dir=report_dir, forecast=FORECAST)
        assert manifest["blocks"]["sim"] == {"sha256": None, "chars": 0, "status": status}
        assert not os.path.exists(os.path.join(eb.bundle_dir_for(report_dir), "blocks", "sim.txt"))
        eb.load_bundle(eb.bundle_dir_for(report_dir))
    manifest = eb.capture_from_agent(_agent(_signal_pack=None), "r1", report_dir=report_dir, forecast=FORECAST)
    assert manifest["blocks"]["sim"]["status"] == "unavailable:no_signal_pack"


def test_unencodable_block_text_is_unavailable_alone(report_dir):
    """A lone surrogate (decoded from a JSON escape) cannot be written as UTF-8: only that
    block is unavailable, the other blocks are still frozen and the bundle verifies."""
    agent = _agent(research_report="dossier \ud800 text", _market_pack="market \udc80",
                   _signal_pack="", _build_signal_pack=lambda: "sim \ud83d",
                   zep_tools=_Zep(facts=["fact \ud800"]))
    manifest = eb.capture_from_agent(agent, "r1", report_dir=report_dir, forecast=FORECAST)
    statuses = {name: meta["status"] for name, meta in manifest["blocks"].items()}
    for name in ("dossier", "market", "sim", "graph"):
        assert statuses[name] == "unavailable:error:UnicodeEncodeError", name
    assert statuses["brief"] == statuses["quant"] == statuses["forecast_inputs"] == "ok"
    _manifest, texts = eb.load_bundle(eb.bundle_dir_for(report_dir))
    assert texts["dossier"] is None and texts["brief"]


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
def _handoff(pipelines, pid=PID, *, markets_payload=None):
    """A stored handoff at the pipeline's own path (under PIPELINE_DATA_DIR)."""
    handoff = pipelines / pid / "handoff"
    handoff.mkdir(parents=True)
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


def test_backfill_from_fixture_handoff(report_dir, pipelines, capsys):
    _backfill_pipeline(pipelines, _handoff(pipelines))
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
    assert manifest["run"] == {"record_class": "production", "run_kind": "pipeline", "seed": None}
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


def test_backfill_reads_only_a_contained_handoff(report_dir, pipelines, tmp_path, capsys):
    """A state whose handoff_dir escapes PIPELINE_DATA_DIR is not followed: the backfill
    reads the pipeline's own handoff (PipelineManager.resolve_handoff_dir), never the files
    the edited state points at."""
    outside = tmp_path / "outside_handoff"
    outside.mkdir()
    (outside / "actors.json").write_text(json.dumps(ACTORS), encoding="utf-8")
    (outside / "research_report.md").write_text("# OUTSIDE dossier", encoding="utf-8")
    _backfill_pipeline(pipelines, outside)
    _seal("r1")
    code, out = _run_cli(capsys, "backfill", "--pipeline", PID)
    assert code == 0 and out["results"][0]["status"] == "written"
    manifest, _texts = eb.load_bundle(eb.bundle_dir_for(report_dir))
    statuses = {name: meta["status"] for name, meta in manifest["blocks"].items()}
    assert statuses["brief"] == "unavailable:no_actors" and statuses["dossier"] == "unavailable:no_research_report"
    _handoff(pipelines)                                      # the pipeline's own (static) handoff
    code, out = _run_cli(capsys, "backfill", "--pipeline", PID, "--force")
    assert code == 0 and out["results"][0]["status"] == "written"
    _manifest, texts = eb.load_bundle(eb.bundle_dir_for(report_dir))
    assert texts["brief"] and "OUTSIDE" not in texts["dossier"] and "Body." in texts["dossier"]


def test_backfill_fork_reads_its_base_handoff_and_class(report_dir, pipelines, capsys):
    """A what-if fork shares its base's handoff and validated anchor, and is recorded as the
    ledger records it: a conditional scenario."""
    base_handoff = _handoff(pipelines, "pipe_base")
    _write_pipeline(pipelines, "pipe_base", options={"as_of_date_validated": "2026-06-15"})
    _backfill_pipeline(pipelines, base_handoff, pid="pipe_fork",
                       options={"scenario_label": "What if rates fall", "base_pipeline_id": "pipe_base"})
    _seal("r1")
    code, out = _run_cli(capsys, "backfill", "--pipeline", "pipe_fork")
    assert code == 0 and out["results"][0]["status"] == "written"
    manifest, texts = eb.load_bundle(eb.bundle_dir_for(report_dir))
    assert manifest["run"]["record_class"] == "conditional_scenario"
    assert (manifest["as_of"], manifest["as_of_source"]) == ("2026-06-15", "validated")
    assert texts["brief"] and "Body." in texts["dossier"]


@pytest.mark.parametrize("options, marker, expected", [
    ({}, None, "production"),
    ({"evaluation_run_v1": {"eval_run_id": "e1", "cell_id": "c1"}}, None, "evaluation"),
    ({"evaluation_run_v1": "corrupted"}, None, "evaluation"),             # fails closed
    ({}, {"pipeline_id": PID, "eval_run_id": "e1", "cell_id": "c1"}, "evaluation"),
    ({}, {"pipeline_id": "pipe_other", "eval_run_id": "e1"}, "evaluation"),  # foreign marker
])
def test_backfill_records_the_ledger_record_class(report_dir, pipelines, capsys, options, marker, expected):
    """An evaluation run's report is told apart from production exactly as the ledger tells
    it (EVAL-13: the options pin, else the handoff marker)."""
    handoff = _handoff(pipelines)
    if marker is not None:
        (handoff / "evaluation_run.json").write_text(json.dumps(marker), encoding="utf-8")
    _backfill_pipeline(pipelines, handoff, options=options)
    _seal("r1")
    code, out = _run_cli(capsys, "backfill", "--pipeline", PID)
    assert code == 0 and out["results"][0]["status"] == "written"
    assert eb.load_bundle(eb.bundle_dir_for(report_dir))[0]["run"]["record_class"] == expected


@pytest.mark.parametrize("forecast_state", ["unsealed", "tampered_after_audit"])
def test_backfill_targets_only_from_the_sealed_forecast(report_dir, pipelines, monkeypatch, capsys, forecast_state):
    """A legacy publishable report (publication_status does not check forecast.json) whose
    sidecar is unsealed or changed after the audit contributes no targets."""
    monkeypatch.setattr(ReportManager, "publication_status", classmethod(lambda cls, rid: {"publishable": True}))
    _backfill_pipeline(pipelines, _handoff(pipelines))
    if forecast_state == "tampered_after_audit":
        _seal("r1")
        tampered = dict(FORECAST, binary_forecasts=[dict(FORECAST["binary_forecasts"][0], probability=0.99)])
        _write_report("r1", json.dumps(tampered, indent=2))
    code, out = _run_cli(capsys, "backfill", "--pipeline", PID)
    assert code == 0 and out["results"][0]["status"] == "written"
    manifest, _texts = eb.load_bundle(eb.bundle_dir_for(report_dir))
    assert manifest["targets"] == [] and manifest["publication"]["forecast_sha256"] is None


def test_backfill_skips_unpublishable_reports(report_dir, pipelines, capsys):
    _backfill_pipeline(pipelines, _handoff(pipelines))        # no meta.json / audit: not publishable
    code, out = _run_cli(capsys, "backfill", "--pipeline", PID)
    assert code == 0 and out["results"][0]["reason"] == "not_publishable"
    assert not os.path.exists(eb.bundle_dir_for(report_dir))


def test_backfill_market_block_is_pinned_to_the_snapshot_time(report_dir, pipelines, monkeypatch, capsys):
    """The TIME-3 end-date gate is evaluated at the snapshot time, never at the backfill
    date: re-backfilling the same run gives the same bytes and the same bundle hash."""
    monkeypatch.setattr(Config, "PREDICTION_MARKETS_END_DATE_GATE", True, raising=False)
    markets = [{"market_id": "m1", "question": "Will X by August?", "implied_yes_prob": 0.4,
                "end_date": "2026-08-31"},                                   # ends after the snapshot
               {"market_id": "m2", "question": "Did Y by May?", "implied_yes_prob": 0.1,
                "end_date": "2026-05-31"}]                                   # ended before it
    _backfill_pipeline(pipelines, _handoff(pipelines, markets_payload={"as_of": "2026-06-30T12:00:00Z",
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


def test_backfill_force_keeps_an_in_pipeline_bundle(report_dir, pipelines, capsys):
    _backfill_pipeline(pipelines, _handoff(pipelines))
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
    _backfill_pipeline(pipelines, _handoff(pipelines, "pipe_nan"), pid="pipe_nan", report_id="r_nan",
                       created_at="2026-09-30T02:00:00")
    _backfill_pipeline(pipelines, _handoff(pipelines, "pipe_good"), pid="pipe_good", report_id="r_good",
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
