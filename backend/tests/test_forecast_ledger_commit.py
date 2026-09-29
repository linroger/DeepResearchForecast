"""EVAL-1: publication-sealed, idempotent, self-contained forecast-ledger commits.

Offline: no LLM, no network. Reports are either synthetic sealed bundles written
to a per-test ReportManager.REPORTS_DIR, or bare ReportAgents whose LLM-facing
steps are stubbed so ``generate_report`` runs end-to-end on disk.
"""

import hashlib
import inspect
import json
import os
import threading
import time
from datetime import date, datetime, timezone

import pytest

from app.config import Config
from app.services import forecast_ledger as fl
from app.services import ledger_commit as lc
from app.services import pipeline_orchestrator as po
from app.services.report_agent import (
    Report, ReportAgent, ReportManager, ReportOutline, ReportSection, ReportStatus,
)
from app.utils.canonical_json import canonical_json_sha256
from app.utils.point_in_time import validate_as_of

NOW = datetime(2026, 9, 29, 12, 0, tzinfo=timezone.utc)
QUESTION = "Will the EU adopt a binding AI liability directive by 2030?"
MARKDOWN = (
    "# Forecast report\n\n"
    "This report forecasts whether the European Union adopts a binding directive. "
    "The analysis weighs legislative calendars, member-state positions and precedent.\n"
)
LEGACY_ROW_KEYS = {"report_id", "horizon", "resolution_date", "created_at", "scenarios",
                   "confidence", "resolved", "outcome", "schema_version"}


def _sha(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _file_sha(path):
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def _read_bytes(path):
    with open(path, "rb") as fh:
        return fh.read()


def _binary():
    statement = "The EU AI liability directive is adopted by 2030-06-30."
    criteria = "Resolves YES if the Official Journal publishes the directive by 2030-06-30."
    return {
        "id": "F1",
        "proposition_id": "eu-ai-liability",
        "statement": statement,
        "probability": 0.42,
        "resolution_criteria": criteria,
        "resolution_source": "EUR-Lex",
        "theme": "ai",
        "horizon_year": 2030,
        "base_rate_anchor": "x" * 500,
        "adjustment_rationale": "not copied into the ledger",
        "source": "research-prior",
        "criteria_sharp": True,
        "market_anchor": {
            "market_id": "m-1",
            "implied_yes_prob": 0.4,
            "forecast_contract_sha256": _sha(statement + "\n" + criteria),
        },
    }


def _forecast(confidence="low", horizon="2026-2030"):
    return {
        "horizon": horizon,
        "confidence": confidence,
        "scenarios": [
            {"name": "Adopted", "probability": 0.45, "resolution_criteria": "OJ publication",
             "base_rate_anchor": "dropped from the row"},
            {"name": "Stalled", "probability": 0.55, "resolution_criteria": "no publication"},
        ],
        "binary_forecasts": [_binary()],
    }


def _seal_bundle(report_id, markdown, forecast, *, hard_passed=True):
    """Write forecast.json + final_audit.json exactly as the final audit seals them."""
    folder = ReportManager._get_report_folder(report_id)
    os.makedirs(folder, exist_ok=True)
    forecast_text = json.dumps(forecast, ensure_ascii=False, indent=2, allow_nan=False)
    with open(os.path.join(folder, "forecast.json"), "w", encoding="utf-8") as fh:
        fh.write(forecast_text)
    audit = {
        "schema_version": 2,
        "policy_version": int(Config.REPORT_FINAL_AUDIT_POLICY_VERSION),
        "report_id": report_id,
        "markdown_sha256": _sha(markdown),
        "hard_issues": [] if hard_passed else ["dangling citation markers"],
        "hard_passed": hard_passed,
        "structured_forecast": {"required": True, "present": True, "valid": True},
        "scenario_contract": {"valid": True},
        "citation_artifacts": {"required": False},
        "publish_gate": {"enabled": False},
        "forecast_sha256": _sha(forecast_text),
    }
    with open(os.path.join(folder, "final_audit.json"), "w", encoding="utf-8") as fh:
        json.dump(audit, fh)
    return audit


def _write_report(report_id, forecast, *, markdown=MARKDOWN, hard_passed=True):
    folder = ReportManager._get_report_folder(report_id)
    os.makedirs(folder, exist_ok=True)
    with open(os.path.join(folder, "meta.json"), "w", encoding="utf-8") as fh:
        json.dump({"report_id": report_id, "simulation_id": "sim_1", "status": "completed",
                   "failed_sections": [], "partial": False}, fh)
    with open(os.path.join(folder, "full_report.md"), "w", encoding="utf-8") as fh:
        fh.write(markdown)
    return _seal_bundle(report_id, markdown, forecast, hard_passed=hard_passed)


@pytest.fixture
def reports_dir(monkeypatch, tmp_path):
    monkeypatch.setattr(Config, "UPLOAD_FOLDER", str(tmp_path), raising=False)
    monkeypatch.setattr(ReportManager, "REPORTS_DIR", str(tmp_path / "reports"), raising=False)
    monkeypatch.setattr(Config, "REPORT_FORECAST_LEDGER", True, raising=False)
    monkeypatch.setattr(Config, "FORECAST_LEDGER_COMMIT_MODE", "published", raising=False)
    monkeypatch.setattr(Config, "FORECAST_LEDGER_RECORD_UNPUBLISHED", True, raising=False)
    return tmp_path / "reports"


class _Agent:
    """The attributes run_post_publication reads from a ReportAgent."""

    def __init__(self, **over):
        self.simulation_id = "sim_1"
        self.simulation_requirement = QUESTION
        self.output_language = "English"
        self.actors = {"as_of_date": "2026-09-01"}
        self.scenario_label = ""
        self.ledger_context = None
        for key, value in over.items():
            setattr(self, key, value)


def _publish(agent, report_id, now=NOW):
    return lc.run_post_publication(
        agent, report_id, report_status="completed", error=None,
        publication_status_fn=ReportManager.publication_status,
        load_forecast_fn=ReportManager.load_structured_forecast, now=now)


def _ledger_path():
    return os.path.join(fl.ledger_dir(), "ledger.jsonl")


def _rows(row_type=None):
    return [r for r in fl.read_ledger() if row_type is None or r.get("row_type") == row_type]


def _commit(report_id, *, question=QUESTION, as_of="2026-09-01", record_class="production",
            provenance=None):
    """Commit a synthetic publication whose forecast fingerprint is derived from report_id."""
    return fl.commit_published_forecast(
        _forecast(), report_id=report_id, question=question, language="English",
        as_of_date=as_of, as_of_source="validated",
        publication={"authority": "final_audit", "policy_version": 3,
                     "markdown_sha256": _sha(MARKDOWN), "forecast_sha256": _sha(report_id)},
        record_class=record_class, provenance=provenance, committed_at=NOW.isoformat())


def _mark_resolved(path, outcome="Adopted"):
    rows = fl.read_ledger(os.path.dirname(path))
    with open(path, "w", encoding="utf-8") as fh:
        for row in rows:
            if row.get("row_type", "commit") == "commit":
                row["resolved"], row["outcome"] = True, outcome
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")


# ───────────────────────────── config ─────────────────────────────────────────
def test_config_defaults_and_env_example():
    """Defaults the ``reports_dir`` fixture pins explicitly, and their .env.example docs."""
    assert Config.FORECAST_LEDGER_COMMIT_MODE == "published"
    assert Config.FORECAST_LEDGER_RECORD_UNPUBLISHED is True
    assert Config.FORECAST_LEDGER_QUESTION_MAX_CHARS == 4000
    assert Config.REPORT_FORECAST_LEDGER is True
    env_example = os.path.join(os.path.dirname(__file__), "..", "..", ".env.example")
    with open(env_example, encoding="utf-8") as fh:
        text = fh.read()
    for line in ("# FORECAST_LEDGER_COMMIT_MODE=published",
                 "# FORECAST_LEDGER_RECORD_UNPUBLISHED=true",
                 "# FORECAST_LEDGER_QUESTION_MAX_CHARS=4000"):
        assert line in text


# ───────────────────────────── conftest isolation ─────────────────────────────
def test_conftest_isolates_ledger_dirs(tmp_path):
    assert "FORECAST_LEDGER_DIR" not in os.environ
    assert fl.ledger_dir() == str(tmp_path / "_forecast_ledger")
    assert fl.evaluation_ledger_dir() == str(tmp_path / "_evaluation_ledger")


# ───────────────────────────── unpublished terminals ──────────────────────────
def test_not_publishable_writes_unpublished_row_only(reports_dir):
    calls = {"publication": 0, "load": 0}

    def _status(rid):
        calls["publication"] += 1
        return {"publishable": False,
                "reasons": ["final audit did not hard-pass", "y" * 400]}

    def _load(rid):
        calls["load"] += 1
        return _forecast()

    receipt = lc.commit_report(
        report_id="r_unpub", report_status="completed", error=None, question=QUESTION,
        language="English", actors=None, scenario_label="", ledger_context={"pipeline_id": "p1"},
        publication_status_fn=_status, load_forecast_fn=_load, now=NOW)
    assert receipt["status"] == "unpublished" and receipt["unpublished_row"] == "recorded"
    assert receipt["commit_id"] is None
    assert calls == {"publication": 1, "load": 0}
    rows = _rows()
    assert len(rows) == 1
    row = rows[0]
    assert row["row_type"] == "unpublished_terminal" and row["schema_version"] == 2
    assert row["reasons"] == ["final audit did not hard-pass", "y" * 300]
    assert row["question_sha256"] == fl.question_sha256(QUESTION)
    assert row["run_ref"] == "p1" and row["record_class"] == "production"
    assert row["recorded_at"] == NOW.isoformat()
    assert "scenarios" not in row and "resolution_date" not in row
    # Idempotent on report_id.
    again = lc.commit_report(
        report_id="r_unpub", report_status="completed", error=None, question=QUESTION,
        language="English", actors=None, scenario_label="", ledger_context=None,
        publication_status_fn=_status, load_forecast_fn=_load, now=NOW)
    assert again["unpublished_row"] == "duplicate" and len(_rows()) == 1
    # Never scored, never due, never a production calibration row — even if tampered.
    tampered = dict(row, resolved=True, outcome="Adopted",
                    scenarios=[{"name": "Adopted", "probability": 0.5}])
    assert fl.is_production_calibration_row(row) is False
    assert fl.calibration_summary(entries=[tampered])["n_resolved"] == 0
    assert fl.calibration_summary()["n_resolved"] == 0
    assert fl.due_for_resolution("2099-12-31") == []


def test_record_unpublished_knob_off_writes_nothing(reports_dir, monkeypatch):
    monkeypatch.setattr(Config, "FORECAST_LEDGER_RECORD_UNPUBLISHED", False, raising=False)
    receipt = lc.commit_report(
        report_id="r_quiet", report_status="failed", error="boom", question=QUESTION,
        language=None, actors=None, scenario_label="", ledger_context=None,
        publication_status_fn=lambda rid: pytest.fail("not called for failed reports"),
        load_forecast_fn=lambda rid: None, now=NOW)
    assert receipt["status"] == "unpublished" and receipt["unpublished_row"] == "disabled"
    assert not os.path.exists(_ledger_path())


def test_completed_but_unpublishable_report_uses_gate_reasons(reports_dir):
    _write_report("r_gate", _forecast(), hard_passed=False)
    receipt = _publish(_Agent(), "r_gate")
    assert receipt["status"] == "unpublished"
    assert _rows("commit") == []
    (row,) = _rows("unpublished_terminal")
    assert "final audit did not hard-pass" in row["reasons"]
    assert "final audit contains hard issues" in row["reasons"]


# ───────────────────────────── sealed commits ─────────────────────────────────
def test_publishable_commit_uses_sealed_forecast(reports_dir):
    audit = _write_report("r_pub", _forecast(confidence="low"))
    agent = _Agent(
        _forecast_spine=_forecast(confidence="medium"),  # stale in-memory draft
        ledger_context={"pipeline_id": "pipe_1", "seed": 7, "run_kind": "pipeline",
                        "as_of_date": "2026-08-15", "unknown_key": "ignored"})
    receipt = _publish(agent, "r_pub")
    assert receipt["status"] == "committed" and receipt["record_class"] == "production"
    (row,) = _rows()
    assert row["schema_version"] == 2 and row["row_type"] == "commit"
    assert row["confidence"] == "low"
    assert row["publication"] == {
        "authority": "final_audit",
        "policy_version": int(Config.REPORT_FINAL_AUDIT_POLICY_VERSION),
        "markdown_sha256": audit["markdown_sha256"],
        "forecast_sha256": audit["forecast_sha256"],
    }
    assert row["publication"]["forecast_sha256"] == ReportManager.publication_status(
        "r_pub")["forecast_sha256"]
    assert row["commit_id"] == receipt["commit_id"] == _sha(
        "r_pub:" + audit["forecast_sha256"])
    assert row["target_key"] == canonical_json_sha256(
        {"v": 1, "q": fl.question_sha256(QUESTION), "as_of": "2026-08-15",
         "record_class": "production"})
    assert row["calibration_role"] == "primary" and row["revision_of"] is None
    assert row["question"] == QUESTION
    assert row["question_sha256"] == fl.question_sha256(QUESTION)
    assert (row["as_of_date"], row["as_of_source"]) == ("2026-08-15", "validated")
    assert row["language"] == "English"
    assert row["created_at"] == NOW.isoformat()
    assert row["horizon"] == "2026-2030" and row["resolution_date"] == "2030-12-31"
    assert row["scenarios"] == [
        {"name": "Adopted", "probability": 0.45, "resolution_criteria": "OJ publication"},
        {"name": "Stalled", "probability": 0.55, "resolution_criteria": "no publication"}]
    assert row["resolved"] is False and row["outcome"] is None
    assert (row["pipeline_id"], row["simulation_id"], row["seed"], row["run_kind"],
            row["run_ref"]) == ("pipe_1", "sim_1", 7, "pipeline", "pipe_1")
    assert "unknown_key" not in row and "eval_run_id" not in row
    (b,) = row["binary_forecasts"]
    sealed = _binary()
    assert b["statement"] == sealed["statement"]
    assert b["resolution_criteria"] == sealed["resolution_criteria"]
    assert b["market_anchor"] == sealed["market_anchor"]
    assert b["market_anchor"]["forecast_contract_sha256"] == _sha(
        b["statement"] + "\n" + b["resolution_criteria"])
    assert b["resolution_date"] == "2030-06-30"
    assert b["base_rate_anchor"] == "x" * 300
    assert "adjustment_rationale" not in b and "criteria_sharp" not in b
    assert agent.ledger_context.get("simulation_id") is None  # caller's dict not mutated


def test_api_path_defaults_to_production_with_sim_run_ref(reports_dir):
    _write_report("r_api", _forecast())
    receipt = _publish(_Agent(ledger_context=None, actors={"as_of_date": "2024-11"}), "r_api")
    assert receipt["status"] == "committed"
    (row,) = _rows()
    assert row["record_class"] == "production"
    assert row["run_ref"] == "sim:sim_1" and "pipeline_id" not in row and "seed" not in row
    assert (row["as_of_date"], row["as_of_source"]) == ("2026-09-29", "commit_date")


def test_recommit_same_publication_is_duplicate(reports_dir):
    _write_report("r_dup", _forecast())
    first = _publish(_Agent(), "r_dup")
    size = os.path.getsize(_ledger_path())
    second = _publish(_Agent(), "r_dup", now=datetime(2027, 1, 1, tzinfo=timezone.utc))
    assert first["status"] == "committed" and second["status"] == "duplicate"
    assert second["commit_id"] == first["commit_id"]
    assert os.path.getsize(_ledger_path()) == size


def test_concurrent_commits_one_primary(monkeypatch):
    real_read = fl.read_ledger

    def slow_read(d=None):
        rows = real_read(d)
        time.sleep(0.05)  # widen the read→write window so an unlocked race would show
        return rows

    monkeypatch.setattr(fl, "read_ledger", slow_read)
    start = threading.Barrier(8)
    results = []

    def worker(i):
        start.wait(timeout=5)
        results.append(_commit(f"r_conc_{i}"))

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=20)
    assert not any(t.is_alive() for t in threads)
    with open(_ledger_path(), encoding="utf-8") as fh:
        lines = [line for line in fh.read().splitlines() if line.strip()]
    rows = [json.loads(line) for line in lines]
    assert len(rows) == 8  # no lost or interleaved lines
    primaries = [r for r in rows if r["calibration_role"] == "primary"]
    revisions = [r for r in rows if r["calibration_role"] == "revision"]
    assert len(primaries) == 1 and len(revisions) == 7
    assert {r["revision_of"] for r in revisions} == {primaries[0]["commit_id"]}
    assert sorted(s for s, _ in results) == ["committed"] + ["revision"] * 7


def test_same_question_as_of_second_report_is_revision():
    status, primary = _commit("r_first")
    assert status == "committed"
    # Cosmetic differences in the question do not escape pre-registration.
    status2, rev = _commit("r_second", question="  will the EU adopt a BINDING AI liability\n"
                                                "directive by 2030?  ")
    assert status2 == "revision"
    assert rev["target_key"] == primary["target_key"]
    assert rev["revision_of"] == primary["commit_id"]
    assert fl.is_production_calibration_row(primary) is True
    assert fl.is_production_calibration_row(rev) is False
    # With the primary (and even the revision) manually marked resolved, the target
    # is scored exactly once.
    _mark_resolved(_ledger_path())
    assert fl.calibration_summary()["n_resolved"] == 1
    # Other as_of dates / record classes are separate targets.
    assert _commit("r_other_asof", as_of="2026-09-02")[0] == "committed"
    assert _commit("r_member", record_class="ensemble_member")[0] == "committed"
    _mark_resolved(_ledger_path())
    assert fl.calibration_summary()["n_resolved"] == 2  # r_first + r_other_asof
    before = _read_bytes(_ledger_path())
    # A resolved primary still blocks: a later publication is a never-scored revision.
    status3, rev3 = _commit("r_after_resolution")
    assert status3 == "revision" and rev3["revision_of"] == primary["commit_id"]
    assert _read_bytes(_ledger_path()).startswith(before)
    assert fl.calibration_summary()["n_resolved"] == 2
    assert [r["report_id"] for r in fl.due_for_resolution("2099-12-31")] == []


def test_record_classes_excluded():
    base = {"resolved": True, "outcome": "YES",
            "scenarios": [{"name": "YES", "probability": 0.9}, {"name": "NO", "probability": 0.1}]}
    legacy = dict(base, report_id="legacy")
    production = dict(base, report_id="prod", row_type="commit", record_class="production",
                      calibration_role="primary")
    excluded = [dict(base, report_id=rc, row_type="commit", record_class=rc,
                     calibration_role="primary")
                for rc in ("ensemble_member", "comparison", "conditional_scenario", "evaluation")]
    for row in excluded:
        assert fl.is_production_calibration_row(row) is False, row["record_class"]
    assert fl.is_production_calibration_row(legacy) is True
    assert fl.is_production_calibration_row(production) is True
    assert fl.calibration_summary(entries=[legacy, production, *excluded])["n_resolved"] == 2
    assert fl.recalibration_param(entries=[legacy, production, *excluded]) == \
        fl.recalibration_param(entries=[legacy, production])


def test_evaluation_rows_route_to_evaluation_ledger():
    status, row = _commit("r_eval", record_class="evaluation",
                          provenance={"eval_run_id": "ev1", "cell_id": "c1"})
    assert status == "committed" and (row["eval_run_id"], row["cell_id"]) == ("ev1", "c1")
    assert not os.path.exists(_ledger_path())
    eval_rows = fl.read_ledger(fl.evaluation_ledger_dir())
    assert [r["report_id"] for r in eval_rows] == ["r_eval"]
    # The idempotency check reads the same routed file.
    assert _commit("r_eval", record_class="evaluation")[0] == "duplicate"
    status_u, _ = fl.record_unpublished_terminal(
        report_id="r_eval_u", question_sha256="q", record_class="evaluation",
        run_ref="ev1", reasons=["gate"])
    assert status_u == "recorded" and not os.path.exists(_ledger_path())
    assert len(fl.read_ledger(fl.evaluation_ledger_dir())) == 2


def test_commit_rejects_invalid_input():
    assert fl.commit_published_forecast(
        {"scenarios": []}, report_id="r", question="q", language=None, as_of_date="2026-01-01",
        as_of_source="commit_date", publication={"forecast_sha256": "abc"}) == ("error", None)
    assert fl.commit_published_forecast(
        _forecast(), report_id="r", question="q", language=None, as_of_date="2026-01-01",
        as_of_source="commit_date", publication={}) == ("error", None)
    nan_forecast = _forecast()
    nan_forecast["scenarios"][0]["probability"] = float("nan")
    assert fl.commit_published_forecast(
        nan_forecast, report_id="r", question="q", language=None, as_of_date="2026-01-01",
        as_of_source="commit_date", publication={"forecast_sha256": "abc"}) == ("error", None)
    for bad_as_of in ("", "2024-11", "2024-6-1", "2024-02-30", None):
        assert fl.commit_published_forecast(
            _forecast(), report_id="r", question="q", language=None, as_of_date=bad_as_of,
            as_of_source="actors", publication={"forecast_sha256": "abc"}) == ("error", None)
    assert fl.commit_published_forecast(
        _forecast(), report_id="", question="q", language=None, as_of_date="2026-01-01",
        as_of_source="commit_date", publication={"forecast_sha256": "abc"}) == ("error", None)
    assert not os.path.exists(_ledger_path())


def test_question_is_capped_but_hashed_in_full(monkeypatch):
    monkeypatch.setattr(Config, "FORECAST_LEDGER_QUESTION_MAX_CHARS", 10, raising=False)
    long_q = "Q" * 50
    _status, row = _commit("r_cap", question=long_q)
    assert row["question"] == "Q" * 10
    assert row["question_sha256"] == fl.question_sha256(long_q) != fl.question_sha256("Q" * 10)


# ───────────────────────────── pure helpers ───────────────────────────────────
def test_resolution_date_for_horizon_ranges():
    assert fl.resolution_date_for_horizon("2026-2036") == "2036-12-31"
    assert fl.resolution_date_for_horizon("2026–2031") == "2031-12-31"
    assert fl.resolution_date_for_horizon("2026 to 2034") == "2034-12-31"
    assert fl.resolution_date_for_horizon("2026年至2030年") == "2030-12-31"
    assert fl.resolution_date_for_horizon("2026~2029") == "2029-12-31"
    assert fl.resolution_date_for_horizon("2026-01-01 to 2035-12-31") == "2035-12-31"
    assert fl.resolution_date_for_horizon("2035-12-31 — 2026-01-01") == "2035-12-31"
    assert fl.resolution_date_for_horizon("2030") == "2030-12-31"
    assert fl.resolution_date_for_horizon(None) is None
    # Non-range text and invalid dates delegate to _year_end, whose outputs are unchanged.
    for text in ("2030", "到2027年底", "mid-2027", "2030-06-30", "2026-13-01 to 2035-12-31"):
        assert fl.resolution_date_for_horizon(text) == fl._year_end(text)
    assert fl._year_end("2030") == "2030-12-31"
    assert fl._year_end("到2027年底") == "2027-12-31"
    assert fl._year_end("2026-01-01 to 2035-12-31") == "2026-01-01"  # the defect fixed above
    assert fl._year_end(None) is None


def test_question_sha256_normalization():
    assert fl.question_sha256("Ｗill  X\thappen?") == fl.question_sha256("will x happen?")
    assert fl.question_sha256("will x happen?") != fl.question_sha256("will y happen?")
    assert fl.question_sha256(None) == fl.question_sha256("")


def test_binary_resolution_date_moved_with_monitor_alias():
    import scripts.resolution_monitor as mon

    assert mon.binary_resolution_date is fl.binary_resolution_date
    assert fl.binary_resolution_date({"resolution_criteria": "by 2026-11-03"}) == "2026-11-03"
    assert fl.binary_resolution_date({"horizon_year": 2027}) == "2027-12-31"
    assert fl.binary_resolution_date({}) is None


def test_validate_as_of_contract():
    today = date(2026, 9, 29)
    assert validate_as_of("2024-06-01", today_utc=today) == "2024-06-01"
    assert validate_as_of("2026-09-29", today_utc=datetime(2026, 9, 29, 1, tzinfo=timezone.utc))
    for bad in ("2024-6-1", "2024-06-01 00:00", "Sept 1", None, 20240601, "2024-02-30"):
        with pytest.raises(ValueError, match="canonical"):
            validate_as_of(bad, today_utc=today)
    with pytest.raises(ValueError, match="future"):
        validate_as_of("2026-09-30", today_utc=today)


def test_resolve_as_of_order():
    now = datetime(2026, 9, 29, 23, 30)  # naive → treated as UTC
    assert lc.resolve_as_of({"as_of_date": "2026-08-01"}, {"as_of_date": "2026-07-01"}, now) \
        == ("2026-08-01", "validated")
    assert lc.resolve_as_of({"as_of_date": "2026-8-1"}, {"as_of_date": "2026-07-01"}, now) \
        == ("2026-07-01", "actors")
    assert lc.resolve_as_of({"as_of_date": "2027-01-01"}, {"as_of_date": "2026-07-01"}, now) \
        == ("2026-07-01", "actors")
    assert lc.resolve_as_of(None, {"as_of_date": "2024-11"}, now) == ("2026-09-29", "commit_date")
    assert lc.resolve_as_of({}, {"as_of_date": "Nov 5, 2024"}, now) == ("2026-09-29", "commit_date")
    assert lc.resolve_as_of({}, None, datetime(2026, 9, 30, 1, tzinfo=timezone.utc)) \
        == ("2026-09-30", "commit_date")


def test_commit_mode_parsing(monkeypatch):
    for raw, expected in (("published", "published"), ("legacy", "legacy"), ("off", "off"),
                          ("LEGACY", "legacy"), ("bogus", "published"), ("", "published")):
        monkeypatch.setattr(Config, "FORECAST_LEDGER_COMMIT_MODE", raw, raising=False)
        assert lc.commit_mode() == expected


def test_ledger_append_only():
    fl.append_forecast(_forecast(), report_id="legacy_1", created_at="2026-01-01T00:00:00")
    _commit("r_a")
    fl.record_unpublished_terminal(report_id="r_u", question_sha256="q",
                                   record_class="production", run_ref="p", reasons=["x"])
    snapshot = _read_bytes(_ledger_path())
    _commit("r_a")                                   # duplicate
    _commit("r_b")                                   # revision
    _commit("r_c", as_of="2025-01-01")               # new primary
    fl.record_unpublished_terminal(report_id="r_u", question_sha256="q",
                                   record_class="production", run_ref="p", reasons=["x"])
    fl.record_unpublished_terminal(report_id="r_v", question_sha256="q",
                                   record_class="production", run_ref="p", reasons=["y"])
    after = _read_bytes(_ledger_path())
    assert after.startswith(snapshot) and len(after) > len(snapshot)
    assert len(fl.read_ledger()) == 6


def test_ledger_module_never_rewrites_ledger_file():
    src = inspect.getsource(fl)
    assert 'open(target, "w"' not in src and "os.replace" not in src and "truncate(" not in src
    assert "_ledger_file" not in inspect.getsource(lc)


# ───────────────────────────── generate_report integration ───────────────────
def _bare_report_agent(**over):
    a = ReportAgent.__new__(ReportAgent)
    for key, value in {
        "graph_id": "g1", "simulation_id": "sim_1", "simulation_requirement": QUESTION,
        "situation_brief": "", "actors": {"as_of_date": "2026-09-01"}, "sources": [],
        "research_report": "", "output_language": "English", "scenario_label": "",
        "base_simulation_id": None, "_background_block": "", "_sources_index": "",
        "_signal_pack": "", "_forecast_spine": None, "_forecast_spine_block": "",
        "_retrieval_query": None, "_outline_degraded": False, "_outline_summary": "",
        "_section_tool_calls": 0, "report_logger": None, "console_logger": None, "tools": {},
    }.items():
        setattr(a, key, value)
    outline = ReportOutline(title="Forecast", summary="Summary",
                            sections=[ReportSection(title="Analysis")])
    a.plan_outline = lambda progress_callback=None, forecast_spine_block="", \
        require_forecast_structure=False: outline
    a._generate_section = lambda section, outline, previous_sections, \
        progress_callback=None, section_index=0: "A long enough analytical body. " * 20
    for key, value in over.items():
        setattr(a, key, value)
    return a


@pytest.fixture
def report_env(reports_dir, monkeypatch):
    for name, value in (("REPORT_SECTION_CONCURRENCY", 1), ("REPORT_SECTION_RETRY_MAX", 0),
                        ("REPORT_STRUCTURED_FORECAST", False), ("REPORT_SIGNAL_PACK", False),
                        ("LLM_TELEMETRY_ENABLED", False), ("REPORT_EDITORIAL_LINT", False),
                        ("REPORT_CITATION_FINALIZER", False), ("REPORT_BILINGUAL", False),
                        ("REPORT_FINAL_READ_ONLY_AUDIT", True)):
        monkeypatch.setattr(Config, name, value, raising=False)
    return reports_dir


def _sealing_audit(forecast, calls=None):
    def _audit(report_id, report):
        if calls is not None:
            calls.append("final_audit")
        return _seal_bundle(report_id, report.markdown_content, forecast)
    return _audit


def test_generate_report_commit_order(report_env, monkeypatch):
    calls = []
    real_save, real_update = ReportManager.save_report, ReportManager.update_progress

    def save(report):
        calls.append("save_report")
        return real_save(report)

    def update(report_id, status, *args, **kwargs):
        if status == "completed":
            calls.append("update_progress(completed)")
        return real_update(report_id, status, *args, **kwargs)

    monkeypatch.setattr(ReportManager, "save_report", save)
    monkeypatch.setattr(ReportManager, "update_progress", update)
    monkeypatch.setattr(fl, "append_forecast",
                        lambda *a, **k: pytest.fail("no pre-audit append in published mode"))
    a = _bare_report_agent(_forecast_spine=_forecast(confidence="medium"))
    a._enforce_final_publish_audit = _sealing_audit(_forecast(confidence="low"), calls)
    real_commit = ReportAgent._commit_forecast_ledger.__get__(a)

    def commit(report_id, report, error=None):
        calls.append("commit_forecast_ledger")
        return real_commit(report_id, report, error=error)

    a._commit_forecast_ledger = commit
    report = a.generate_report(report_id="r_order")
    assert report.status == ReportStatus.COMPLETED
    i_audit = calls.index("final_audit")
    i_commit = calls.index("commit_forecast_ledger")
    i_update = calls.index("update_progress(completed)")
    last_save_before_commit = max(i for i, c in enumerate(calls[:i_commit]) if c == "save_report")
    assert i_audit < last_save_before_commit < i_update < i_commit
    assert calls.count("commit_forecast_ledger") == 1
    assert a.ledger_receipt["status"] == "committed"
    (row,) = _rows()
    assert row["confidence"] == "low" and row["report_id"] == "r_order"
    audit = json.loads(_read_bytes(os.path.join(report_env, "r_order", "final_audit.json")))
    assert row["publication"]["forecast_sha256"] == audit["forecast_sha256"]
    assert ReportManager.is_publishable("r_order") is True


def test_failed_audit_records_unpublished_only(report_env):
    """The real _enforce_final_publish_audit gate fails → one unpublished row with its reasons."""
    a = _bare_report_agent()
    a._audit_final_published_markdown = lambda report_id, report: {
        "hard_passed": False, "hard_issues": ["dangling citation markers [S9]"],
        "publish_gate": {"enabled": True, "passed": False}}
    report = a.generate_report(report_id="r_fail")
    assert report.status == ReportStatus.FAILED
    assert a.ledger_receipt["status"] == "unpublished"
    assert _rows("commit") == []
    (row,) = _rows()
    assert row["row_type"] == "unpublished_terminal" and row["report_id"] == "r_fail"
    assert row["reasons"][0].startswith("report_failed: ")
    assert "dangling citation markers [S9]" in row["reasons"][0]
    assert len(row["reasons"][0]) <= len("report_failed: ") + 200
    assert row["run_ref"] == "sim:sim_1"
    assert fl.calibration_summary()["n_resolved"] == 0
    assert fl.due_for_resolution("2099-12-31") == []


def test_real_final_audit_seal_is_what_gets_committed(reports_dir, monkeypatch):
    """No stubbed seal: the real read-only audit rewrites forecast.json (post-gate
    fields), and the committed row carries exactly those sealed bytes' fingerprint."""
    monkeypatch.setattr(Config, "REPORT_PUBLISH_GATE", True, raising=False)
    monkeypatch.setattr(Config, "REPORT_PUBLISH_GATE_MIN_COVERAGE", 0.5, raising=False)
    source = {"title": "Official outlook", "url": "https://example.gov/outlook",
              "date": "2026-06-30", "tier": "S1",
              "content": "Revenue could reach 65% by 2030 according to the official source."}
    report_id = "r_real_audit"
    markdown = "# Forecast\n\nRevenue could reach 65% by 2030 [S1].\n"
    draft = {
        "headline": "Base case leads", "horizon": "2030", "confidence": "high",
        "confidence_rationale": "Evidence is broad.",
        "scenarios": [
            {"name": "Base case", "probability": 0.6,
             "resolution_criteria": "The audited 2030 filing records the base-case outcome."},
            {"name": "Other / status quo", "probability": 0.4,
             "resolution_criteria": "Any other measurable outcome in the audited 2030 filing."}],
        "binary_forecasts": [{
            "id": "F1", "statement": "Revenue reaches 65% by 2030.", "probability": 0.65,
            "resolution_criteria": "The audited 2030 filing reports revenue at 65%."}],
        "quality": {},
    }
    _write_report(report_id, draft, markdown=markdown)
    os.remove(os.path.join(reports_dir, report_id, "final_audit.json"))
    a = _bare_report_agent(sources=[source], _citation_index={"S1": source},
                           research_report="Revenue evidence from the official source.",
                           _forecast_spine=_forecast(confidence="medium"))
    report = Report(report_id=report_id, simulation_id="sim_1", graph_id="g1",
                    simulation_requirement=QUESTION, status=ReportStatus.COMPLETED,
                    markdown_content=markdown)
    a._finalize_citations(report_id, report)  # the last sanctioned mutation (writes disk)
    forecast_path = os.path.join(reports_dir, report_id, "forecast.json")
    draft_bytes = _read_bytes(forecast_path)
    a._enforce_final_publish_audit(report_id, report)
    assert ReportManager.is_publishable(report_id) is True
    sealed_bytes = _read_bytes(forecast_path)
    assert sealed_bytes != draft_bytes  # the audit merged its post-gate fields
    audit = json.loads(_read_bytes(os.path.join(reports_dir, report_id, "final_audit.json")))

    receipt = a._commit_forecast_ledger(report_id, report)
    assert receipt["status"] == "committed" and a.ledger_receipt is receipt
    (row,) = _rows()
    assert row["publication"]["forecast_sha256"] == audit["forecast_sha256"] == _sha(
        sealed_bytes.decode("utf-8"))
    assert row["publication"]["markdown_sha256"] == audit["markdown_sha256"]
    assert row["confidence"] == json.loads(sealed_bytes)["confidence"]
    assert row["scenarios"] == [
        {"name": s["name"], "probability": s["probability"],
         "resolution_criteria": s["resolution_criteria"]}
        for s in json.loads(sealed_bytes)["scenarios"]]
    assert _read_bytes(forecast_path) == sealed_bytes
    assert ReportManager.is_publishable(report_id) is True


def test_commit_error_never_changes_report_status(report_env, monkeypatch):
    def explode(*a, **k):
        raise OSError("disk full")

    monkeypatch.setattr(lc, "run_post_publication", explode)
    a = _bare_report_agent()
    a._enforce_final_publish_audit = _sealing_audit(_forecast())
    report = a.generate_report(report_id="r_err")
    assert report.status == ReportStatus.COMPLETED
    assert a.ledger_receipt["status"] == "error"
    assert ReportManager.is_publishable("r_err") is True


def test_late_failure_after_commit_adds_no_second_row(report_env):
    """A failure after the success-path commit leaves exactly the one commit row."""
    a = _bare_report_agent()
    a._enforce_final_publish_audit = _sealing_audit(_forecast())

    def progress(stage, progress_pct, message):
        if stage == "completed":
            raise RuntimeError("progress sink unavailable")

    report = a.generate_report(progress_callback=progress, report_id="r_late")
    assert report.status == ReportStatus.FAILED
    (row,) = _rows()
    assert row["row_type"] == "commit" and row["report_id"] == "r_late"
    assert a.ledger_receipt["status"] == "committed"


def _finalize_agent(monkeypatch, report_env):
    for name, value in (("FORECAST_EMIT_BINARY", False), ("REPORT_REPAIR_PASSES", False),
                        ("REPORT_FORECAST_SELF_CRITIQUE", False)):
        monkeypatch.setattr(Config, name, value, raising=False)
    a = _bare_report_agent(_forecast_spine=_forecast(confidence="medium"), actors=None,
                           llm=None, _citation_index=None)
    os.makedirs(os.path.join(report_env, "r_fin"), exist_ok=True)
    return a


def test_legacy_mode_byte_identical(report_env, monkeypatch):
    monkeypatch.setattr(Config, "FORECAST_LEDGER_COMMIT_MODE", "legacy", raising=False)
    real_append = fl.append_forecast
    calls = []

    def spy(forecast, **kwargs):
        calls.append(kwargs)
        return real_append(forecast, **kwargs)

    monkeypatch.setattr(fl, "append_forecast", spy)
    a = _finalize_agent(monkeypatch, report_env)
    a._finalize_structured_forecast("r_fin", MARKDOWN)
    assert len(calls) == 1 and set(calls[0]) == {"report_id", "horizon", "created_at"}
    (row,) = fl.read_ledger()
    assert set(row) == LEGACY_ROW_KEYS
    assert row["schema_version"] == 1 and row["report_id"] == "r_fin"
    assert row["confidence"] == "medium"  # legacy semantics: the pre-audit draft
    assert row["resolution_date"] == fl._year_end("2026-2030")
    datetime.fromisoformat(row["created_at"])
    # Byte-identical to today's append of the forecast _finalize just wrote.
    sealed = json.loads(_read_bytes(os.path.join(report_env, "r_fin", "forecast.json")))
    reference_dir = os.path.join(str(report_env), "_reference_ledger")
    real_append(sealed, report_id="r_fin", horizon=sealed.get("horizon"),
                created_at=row["created_at"], d=reference_dir)
    assert _read_bytes(_ledger_path()) == _read_bytes(os.path.join(reference_dir, "ledger.jsonl"))
    # The post-publication commit is disabled in legacy mode.
    _write_report("r_fin", _forecast(confidence="low"))
    assert _publish(_Agent(), "r_fin") == {"status": "disabled"}
    assert _rows("commit") == [] and len(fl.read_ledger()) == 1


def test_published_mode_finalize_appends_nothing(report_env, monkeypatch):
    """Default mode: _finalize_structured_forecast (pre-audit) never touches the ledger."""
    a = _finalize_agent(monkeypatch, report_env)
    a._finalize_structured_forecast("r_fin", MARKDOWN)
    assert os.path.exists(os.path.join(report_env, "r_fin", "forecast.json"))
    assert not os.path.exists(_ledger_path())


def test_off_mode_and_master_switch_write_nothing(report_env, monkeypatch):
    _write_report("r_off", _forecast())
    for mode, master in (("off", True), ("published", False), ("legacy", False)):
        monkeypatch.setattr(Config, "FORECAST_LEDGER_COMMIT_MODE", mode, raising=False)
        monkeypatch.setattr(Config, "REPORT_FORECAST_LEDGER", master, raising=False)
        a = _finalize_agent(monkeypatch, report_env)
        a._finalize_structured_forecast("r_fin", MARKDOWN)
        assert _publish(_Agent(), "r_off") == {"status": "disabled"}
        assert lc.run_post_publication(
            _Agent(), "r_off", report_status="failed", error="x",
            publication_status_fn=ReportManager.publication_status,
            load_forecast_fn=ReportManager.load_structured_forecast) == {"status": "disabled"}
    assert not os.path.exists(_ledger_path())


def test_commit_never_mutates_sealed_artifacts(reports_dir):
    _write_report("r_seal", _forecast())
    folder = reports_dir / "r_seal"
    names = ("full_report.md", "forecast.json", "final_audit.json", "meta.json")
    before = {n: _file_sha(folder / n) for n in names}
    assert _publish(_Agent(), "r_seal")["status"] == "committed"
    assert _publish(_Agent(), "r_seal")["status"] == "duplicate"
    assert {n: _file_sha(folder / n) for n in names} == before
    assert sorted(os.listdir(folder)) == sorted(names)
    assert ReportManager.is_publishable("r_seal") is True


def test_no_structured_forecast_is_logged_not_committed(reports_dir):
    _write_report("r_nofc", _forecast())
    receipt = lc.commit_report(
        report_id="r_nofc", report_status="completed", error=None, question=QUESTION,
        language=None, actors=None, scenario_label="", ledger_context=None,
        publication_status_fn=ReportManager.publication_status,
        load_forecast_fn=lambda rid: None, now=NOW)
    assert receipt["status"] == "no_structured_forecast"
    assert not os.path.exists(_ledger_path())


# ───────────────────────────── entry points ───────────────────────────────────
def test_entry_points_set_record_class(reports_dir, monkeypatch):
    # Orchestrator main path: production (derived) + pipeline provenance.
    state = po.PipelineState(pipeline_id="pipe_main", prompt=QUESTION)
    state.options["as_of_date_validated"] = "2026-08-20"
    ctx = po.PipelineOrchestrator._report_ledger_context(
        state, "sim_main", run_kind="pipeline", seed=0)
    assert ctx == {"pipeline_id": "pipe_main", "simulation_id": "sim_main", "seed": 0,
                   "run_kind": "pipeline", "as_of_date": "2026-08-20"}
    _write_report("r_main", _forecast())
    receipt = _publish(_Agent(ledger_context=ctx), "r_main")
    assert receipt["record_class"] == "production" and receipt["status"] == "committed"
    row = _rows()[-1]
    assert (row["pipeline_id"], row["seed"], row["as_of_date"]) == ("pipe_main", 0, "2026-08-20")
    src = inspect.getsource(po.PipelineOrchestrator._run)
    i_ctx = src.find("agent.ledger_context = self._report_ledger_context(")
    i_gen = src.find("report = agent.generate_report(progress_callback=report_cb")
    i_receipt = src.find('state.options["forecast_ledger"] = dict(_ledger_receipt)')
    assert -1 < i_ctx < i_gen < i_receipt
    assert 'run_kind="pipeline"' in src[i_ctx:i_gen]

    # What-if fork: scenario_label → conditional_scenario, excluded from production.
    _write_report("r_whatif", _forecast())
    receipt = _publish(_Agent(ledger_context=ctx, scenario_label="Tariffs double"), "r_whatif")
    assert receipt["record_class"] == "conditional_scenario"
    assert fl.is_production_calibration_row(_rows()[-1]) is False


def test_seed_ensemble_member_record_class(monkeypatch, tmp_path):
    monkeypatch.setattr(Config, "PIPELINE_DATA_DIR", str(tmp_path / "pipelines"), raising=False)
    monkeypatch.setattr(Config, "SIM_GRAPH_FEEDBACK", False, raising=False)
    captured = {}

    class _Sim:
        simulation_id = "sim_seed"

    class _SimManager:
        def create_simulation(self, *a, **k):
            return _Sim()

        def prepare_simulation(self, **k):
            return None

    class _RunState:
        current_round = 1
        runner_status = po.RunnerStatus.COMPLETED

    class _Runner:
        start_simulation = staticmethod(lambda **k: None)
        get_run_state = staticmethod(lambda sim_id: _RunState())
        write_run_summary = staticmethod(lambda sim_id: None)

    class _FakeAgent:
        def __init__(self, **kwargs):
            self.ledger_context = None

        def generate_report(self, report_id=None, **kw):
            captured["ctx"] = dict(self.ledger_context)
            captured["report_id"] = report_id

    monkeypatch.setattr(po, "SimulationManager", _SimManager)
    monkeypatch.setattr(po, "SimulationRunner", _Runner)
    monkeypatch.setattr(po, "ReportAgent", _FakeAgent)
    state = po.PipelineState(pipeline_id="pipe_ens", prompt=QUESTION)
    state.options["as_of_date_validated"] = "2026-08-20"
    orch = po.PipelineOrchestrator()
    sim_id, rid, _fc = orch._run_one_seed(
        state, type("P", (), {"project_id": "proj"})(), "graph_1", None, {}, "report md",
        seed=11, max_rounds=None)
    assert sim_id == "sim_seed" and rid == captured["report_id"]
    assert captured["ctx"] == {"pipeline_id": "pipe_ens", "simulation_id": "sim_seed",
                               "seed": 11, "run_kind": "seed_ensemble",
                               "as_of_date": "2026-08-20", "record_class": "ensemble_member"}


def test_model_comparison_record_class(monkeypatch):
    import scripts.model_comparison as mc

    captured = {}

    class _FakeAgent:
        def __init__(self, **kwargs):
            self.ledger_context = None

        def generate_report(self, progress_callback=None, report_id=None):
            captured["ctx"] = dict(self.ledger_context)
            return type("R", (), {"status": ReportStatus.FAILED, "error": "stop here"})()

    monkeypatch.setattr(mc, "ReportAgent", _FakeAgent)
    monkeypatch.setattr(mc, "_build_client_for", lambda provider, api_key=None: object())
    result = mc._run_report_for_provider(
        {"base_pipeline_id": "pipe_base", "graph_id": "g", "simulation_id": "sim_base",
         "prompt": QUESTION}, "fake", None, self_critique=False)
    assert result["ok"] is False and result["error"] == "stop here"
    assert captured["ctx"] == {"pipeline_id": "pipe_base", "simulation_id": "sim_base",
                               "record_class": "comparison", "run_kind": "model_comparison"}


def test_graph_stage_sets_validated_as_of_outside_fallback():
    src = inspect.getsource(po.PipelineOrchestrator._run)
    markers = [
        "_as_of_validated = False",
        "as_of, _as_of_note = self._validate_as_of_date(",
        "_as_of_validated = True",
        "except Exception as _ae:",  # the raw-parse fallback never sets the flag
        'state.options.pop("as_of_date_validated", None)',
        "if _as_of_validated and as_of is not None:",
        'state.options["as_of_date_validated"] = _validate_as_of(',
        "seeded = _seed_research_actors(",
    ]
    pos = -1
    for marker in markers:
        nxt = src.find(marker, pos + 1)
        assert nxt > pos, marker
        pos = nxt


def test_health_failure_after_commit_does_not_retract(reports_dir, monkeypatch):
    _write_report("r_health", _forecast())
    assert _publish(_Agent(ledger_context={"pipeline_id": "pipe_h"}), "r_health")["status"] \
        == "committed"
    before = _read_bytes(_ledger_path())
    orch = po.PipelineOrchestrator()
    monkeypatch.setattr(orch, "_assess_report_health",
                        lambda report_id: ("failed", ["deliverable is broken"], {}))
    state = po.PipelineState(pipeline_id="pipe_h", prompt=QUESTION)
    state.report_id = "r_health"
    with pytest.raises(RuntimeError, match="deliverable is broken"):
        orch._enforce_pipeline_health(state)
    assert _read_bytes(_ledger_path()) == before
    (row,) = _rows()
    assert row["calibration_role"] == "primary" and fl.is_production_calibration_row(row)
