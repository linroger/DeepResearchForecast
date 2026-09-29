"""EVAL-13: evaluation-run honesty.

A pipeline started with ``PipelineOrchestrator.start(..., evaluation=...)`` is an
evaluation cell: its reports never read production calibration, never write the
production ledger and are never processed by the resolution monitor, and its
pinned target question is bound deterministically to one binary forecast.
Without an evaluation context everything stays byte-identical.

Offline: no LLM (FakeLLMClient / stubs), no network, per-test data directories.
"""

import hashlib
import json
import os
import time

import pytest

import scripts.resolution_monitor as mon
from app.config import Config
from app.services import forecast_extractor as fe
from app.services import forecast_ledger as fl
from app.services import ledger_commit as lc
from app.services import pipeline_orchestrator as po
from app.services.report_agent import ReportAgent, ReportManager
from tests.conftest import FakeLLMClient

QUESTION = "Will the EU adopt a binding AI liability directive by 2030?"
MARKDOWN = "# Forecast report\n\nThe analysis weighs legislative calendars and precedent.\n"
GOLDEN_ROW = {
    "id": "eu-ai-liability-2030",
    "question": QUESTION,
    "resolution_criteria": "YES if the Official Journal publishes the directive by 2030-12-31.",
    "as_of_date": "2026-09-01",
    # Grader-only fields: none of them may reach the pin, the prompts or the report.
    "resolved_outcome": False,
    "resolution_note": "The proposal was withdrawn by the Commission in 2025.",
    "resolution_date": "2030-12-31",
    "category": "policy",
    "difficulty": "hard",
}
QID = GOLDEN_ROW["id"]
EVALUATION = {"eval_run_id": "sweep-2026-09", "cell_id": "cell-001",
              "target": po.evaluation_target_from_golden(GOLDEN_ROW)}


def _sha(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@pytest.fixture
def env(monkeypatch, tmp_path):
    monkeypatch.setattr(Config, "UPLOAD_FOLDER", str(tmp_path), raising=False)
    monkeypatch.setattr(ReportManager, "REPORTS_DIR", str(tmp_path / "reports"), raising=False)
    monkeypatch.setattr(Config, "PIPELINE_DATA_DIR", str(tmp_path / "pipelines"), raising=False)
    monkeypatch.setattr(Config, "REPORT_FORECAST_LEDGER", True, raising=False)
    monkeypatch.setattr(Config, "FORECAST_LEDGER_COMMIT_MODE", "published", raising=False)
    monkeypatch.setattr(Config, "FORECAST_LEDGER_RECORD_UNPUBLISHED", True, raising=False)
    # Admission is what matters here; the background run is a no-op.
    monkeypatch.setattr(po.PipelineOrchestrator, "_run", classmethod(lambda cls, state: None))
    return tmp_path


def _settle(pipeline_id):
    thread = po.PipelineOrchestrator._threads.pop(pipeline_id, None)
    if thread is not None:
        thread.join(timeout=5)
    po.PipelineOrchestrator._cancel_events.pop(pipeline_id, None)


def _start(**kwargs):
    state = po.PipelineOrchestrator.start(QUESTION, mode="full", **kwargs)
    _settle(state.pipeline_id)
    return state


def _pin():
    return po.build_evaluation_pin(EVALUATION, pinned_at="2026-09-29T12:00:00+00:00")


def _without_volatile(value, pipeline_id):
    """Options with the pipeline id and admission timestamps neutralised (for comparisons)."""
    text = json.dumps(value, sort_keys=True).replace(pipeline_id, "<pid>")
    data = json.loads(text)

    def strip(node):
        if isinstance(node, dict):
            return {k: strip(v) for k, v in node.items() if k != "pinned_at"}
        return node
    return strip(data)


def _forecast(**extra):
    forecast = {
        "horizon": "2026-2030",
        "confidence": "low",
        "scenarios": [
            {"name": "Adopted", "probability": 0.35, "resolution_criteria": "OJ publication"},
            {"name": "Stalled", "probability": 0.65, "resolution_criteria": "no publication"},
        ],
        "binary_forecasts": [{"id": "F1", "statement": QUESTION, "probability": 0.35,
                              "resolution_criteria": GOLDEN_ROW["resolution_criteria"],
                              "target_question_id": QID, "target_bind": "verbatim"}],
    }
    forecast.update(extra)
    return forecast


def _write_report(report_id, forecast, *, created_at="2026-09-29T12:00:00", sealed=True,
                  simulation_id="sim_1"):
    """A completed report on disk; ``sealed`` adds the final-audit seal of its forecast.

    ``forecast=None`` leaves the report without a forecast.json (a failed finalize).
    """
    folder = ReportManager._get_report_folder(report_id)
    os.makedirs(folder, exist_ok=True)
    with open(os.path.join(folder, "meta.json"), "w", encoding="utf-8") as fh:
        json.dump({"report_id": report_id, "simulation_id": simulation_id, "graph_id": "g1",
                   "simulation_requirement": QUESTION, "status": "completed",
                   "created_at": created_at, "failed_sections": [], "partial": False}, fh)
    with open(os.path.join(folder, "full_report.md"), "w", encoding="utf-8") as fh:
        fh.write(MARKDOWN)
    if forecast is None:
        return folder
    forecast_text = json.dumps(forecast, ensure_ascii=False, indent=2)
    with open(os.path.join(folder, "forecast.json"), "w", encoding="utf-8") as fh:
        fh.write(forecast_text)
    if sealed:
        with open(os.path.join(folder, "final_audit.json"), "w", encoding="utf-8") as fh:
            json.dump({"schema_version": 2,
                       "policy_version": int(Config.REPORT_FINAL_AUDIT_POLICY_VERSION),
                       "report_id": report_id, "markdown_sha256": _sha(MARKDOWN),
                       "hard_issues": [], "hard_passed": True,
                       "structured_forecast": {"required": True, "present": True, "valid": True},
                       "scenario_contract": {"valid": True},
                       "citation_artifacts": {"required": False},
                       "publish_gate": {"enabled": False},
                       "forecast_sha256": _sha(forecast_text)}, fh)
    return folder


class _Agent:
    """The attributes run_post_publication reads from a ReportAgent."""

    def __init__(self, **over):
        self.simulation_id = "sim_1"
        self.simulation_requirement = QUESTION
        self.output_language = "English"
        self.actors = {"as_of_date": "2026-09-01"}
        self.scenario_label = ""
        self.ledger_context = None
        self.evaluation_context = None
        for key, value in over.items():
            setattr(self, key, value)


def _publish(agent, report_id, status="completed"):
    return lc.run_post_publication(
        agent, report_id, report_status=status, error=None if status == "completed" else "boom",
        publication_status_fn=ReportManager.publication_status,
        load_forecast_fn=ReportManager.load_structured_forecast)


def _production_ledger():
    return os.path.join(fl.ledger_dir(), "ledger.jsonl")


def _save_pipeline(pipeline_id, simulation_id, **options):
    state = po.PipelineState(pipeline_id=pipeline_id, prompt=QUESTION)
    state.simulation_id = simulation_id
    state.options.update(options)
    po.PipelineManager.save(state)
    return state


def _bare_agent(**over):
    a = ReportAgent.__new__(ReportAgent)
    for key, value in {
        "graph_id": "g1", "simulation_id": "sim_1", "simulation_requirement": QUESTION,
        "situation_brief": "", "actors": None, "sources": [], "research_report": "dossier",
        "output_language": "English", "scenario_label": "", "base_simulation_id": None,
        "_background_block": "", "_sources_index": "", "_signal_pack": "", "_market_pack": "",
        "_forecast_spine": _forecast(), "_forecast_spine_block": "", "_retrieval_query": None,
        "_outline_degraded": False, "_outline_summary": "", "_section_tool_calls": 0,
        "report_logger": None, "console_logger": None, "tools": {}, "llm": None,
        "_citation_index": None,
    }.items():
        setattr(a, key, value)
    for key, value in over.items():
        setattr(a, key, value)
    return a


def _finalize_env(monkeypatch, *, emit_binary):
    for name, value in (("FORECAST_EMIT_BINARY", emit_binary), ("REPORT_REPAIR_PASSES", False),
                        ("REPORT_FORECAST_SELF_CRITIQUE", False), ("FORECAST_SIM_SENSITIVITY", False),
                        ("FORECAST_BINARY_THEMES", "policy")):
        monkeypatch.setattr(Config, name, value, raising=False)


def _fake_extract(calls, *, target_binding=None):
    def fake(*args, **kwargs):
        calls.append(kwargs)
        out = {"binary_forecasts": [dict(b) for b in _forecast()["binary_forecasts"]],
               "binary_quality": {"count": 1, "issues": []}}
        if target_binding is not None:
            out["target_binding"] = target_binding
        return out
    return fake


def _read_forecast(report_id):
    path = os.path.join(ReportManager._get_report_folder(report_id), "forecast.json")
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


# ───────────────────────────── (A) admission ─────────────────────────────────
def test_config_default_and_env_example():
    assert Config.EVAL_TARGET_REPAIR_DRAW is True
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    with open(os.path.join(root, ".env.example"), encoding="utf-8") as fh:
        assert "# EVAL_TARGET_REPAIR_DRAW=true" in fh.read()


def test_start_without_evaluation_unchanged(env):
    omitted = _start()
    explicit = _start(evaluation=None)
    for state in (omitted, explicit):
        persisted = po.PipelineManager.load(state.pipeline_id)
        assert not [key for key in persisted["options"] if "evaluation" in key]
        assert po.EVALUATION_RUN_OPTION not in state.options
        # The handoff holds no admission marker (nothing at all at admission).
        assert os.listdir(po.PipelineManager.handoff_dir(state.pipeline_id)) == []
        assert po.PipelineOrchestrator._report_ledger_context(
            state, "sim_x", run_kind="pipeline", seed=0).get("record_class") is None
    assert (_without_volatile(po.PipelineManager.load(omitted.pipeline_id)["options"],
                              omitted.pipeline_id)
            == _without_volatile(po.PipelineManager.load(explicit.pipeline_id)["options"],
                                 explicit.pipeline_id))


@pytest.mark.parametrize("bad_id", ["../x", "a/b", "x\n", "", "_x", "a.b", "a" * 65, None, 7])
def test_invalid_eval_run_id_rejected_before_thread(env, monkeypatch, bad_id):
    class _NoTasks:
        def __init__(self):
            pytest.fail("a task was created for an invalid evaluation context")

    monkeypatch.setattr(po, "TaskManager", _NoTasks)
    threads_before = dict(po.PipelineOrchestrator._threads)
    with pytest.raises(ValueError):
        po.PipelineOrchestrator.start(QUESTION, evaluation={"eval_run_id": bad_id})
    # Validation runs before ensure_dirs / create_task / the thread: nothing is left behind.
    assert not os.path.exists(Config.PIPELINE_DATA_DIR)
    assert po.PipelineOrchestrator._threads == threads_before


@pytest.mark.parametrize("ctx", [
    "sweep-1",
    ["sweep-1"],
    {"cell_id": "c1"},                                                  # eval_run_id missing
    {"eval_run_id": "ok", "extra": 1},                                   # unknown key
    {"eval_run_id": "ok", "cell_id": "c" * 129},
    {"eval_run_id": "ok", "question_id": "q\n1"},
    {"eval_run_id": "ok", "cell_id": 5},
    {"eval_run_id": "ok", "target": {"question_id": "q1"}},              # statement missing
    {"eval_run_id": "ok", "target": {"question_id": "q1", "statement": "S", "extra": 1}},
    {"eval_run_id": "ok", "target": {"question_id": "q1", "statement": "S",
                                     "resolution_date": "2030-1-1"}},
    {"eval_run_id": "ok", "target": {"question_id": "q1", "statement": "S",
                                     "resolution_date": "2030-02-30"}},
    {"eval_run_id": "ok", "question_id": "q2",
     "target": {"question_id": "q1", "statement": "S"}},                 # ids disagree
    {"eval_run_id": "ok", "target": {"question_id": "q1", "statement": "x" * 1001}},
    # Line breaks and invisible format characters that pass a C0/DEL-only check.
    {"eval_run_id": "ok", "cell_id": "c\u20281"},                        # LINE SEPARATOR
    {"eval_run_id": "ok", "cell_id": "c\u20291"},                        # PARAGRAPH SEPARATOR
    {"eval_run_id": "ok", "question_id": "q\u00851"},                    # NEXT LINE (C1)
    {"eval_run_id": "ok", "question_id": "q\u202e1"},                    # RIGHT-TO-LEFT OVERRIDE
    {"eval_run_id": "ok", "target": {"question_id": "q1", "statement": "Will\u200bX happen?"}},
    {"eval_run_id": "ok", "target": {"question_id": "q1", "statement": "S",
                                     "resolution_criteria": "YES if X.\u2028Also Y."}},
])
def test_invalid_evaluation_context_rejected(env, ctx):
    with pytest.raises(ValueError):
        po.PipelineOrchestrator.start(QUESTION, evaluation=ctx)
    assert not os.path.exists(Config.PIPELINE_DATA_DIR)


def test_validate_evaluation_context_normalizes():
    assert po.validate_evaluation_context({"eval_run_id": "a" * 64}) == {
        "eval_run_id": "a" * 64, "cell_id": None, "question_id": None, "target": None}
    valid = po.validate_evaluation_context({
        "eval_run_id": "run_1-A", "cell_id": " c1 ",
        "target": {"question_id": "q1", "statement": " Will X happen? ",
                   "resolution_date": "2099-12-31"}})           # a future resolution date is fine
    assert valid == {"eval_run_id": "run_1-A", "cell_id": "c1", "question_id": "q1",
                     "target": {"question_id": "q1", "statement": "Will X happen?",
                                "resolution_criteria": None, "resolution_date": "2099-12-31"}}


def test_target_from_golden_is_outcome_free():
    target = po.evaluation_target_from_golden(GOLDEN_ROW)
    assert target == {"question_id": QID, "statement": QUESTION,
                      "resolution_criteria": GOLDEN_ROW["resolution_criteria"]}
    text = json.dumps(_pin())
    for grader_only in ("resolved_outcome", "resolution_note", GOLDEN_ROW["resolution_note"],
                        "difficulty", "category"):
        assert grader_only not in text


def test_pin_and_marker_written(env):
    plain = _start()
    plain_options = po.PipelineManager.load(plain.pipeline_id)["options"]
    state = _start(evaluation=EVALUATION)
    persisted = po.PipelineManager.load(state.pipeline_id)
    pin = persisted["options"][po.EVALUATION_RUN_OPTION]
    # The pin is the only admission difference from a production start.
    others = {k: v for k, v in persisted["options"].items() if k != po.EVALUATION_RUN_OPTION}
    assert set(persisted["options"]) == set(plain_options) | {po.EVALUATION_RUN_OPTION}
    assert (_without_volatile(others, state.pipeline_id)
            == _without_volatile(plain_options, plain.pipeline_id))
    assert list(pin) == ["version", "record_class", "characterization_only", "eval_run_id",
                         "cell_id", "question_id", "target", "pinned_at"]
    assert pin["version"] == "evaluation-run/v1"
    assert pin["record_class"] == "evaluation" and pin["characterization_only"] is True
    assert (pin["eval_run_id"], pin["cell_id"], pin["question_id"]) == (
        "sweep-2026-09", "cell-001", QID)
    assert pin["target"]["statement"] == QUESTION
    with open(os.path.join(po.PipelineManager.handoff_dir(state.pipeline_id),
                           po.EVALUATION_RUN_MARKER), encoding="utf-8") as fh:
        # The marker is the pin plus the admitting pipeline (handoff dirs can be shared).
        assert json.load(fh) == dict(pin, pipeline_id=state.pipeline_id)

    # Resume carries the pin unchanged (never re-captured).
    po.PipelineManager.mark_failed(state.pipeline_id, "boom")
    resumed = po.PipelineOrchestrator.resume(state.pipeline_id)
    _settle(state.pipeline_id)
    assert resumed.options[po.EVALUATION_RUN_OPTION] == pin
    assert po.PipelineManager.load(state.pipeline_id)["options"][po.EVALUATION_RUN_OPTION] == pin

    # A what-if fork of an evaluation run stays in the evaluation lane.
    base = po.PipelineState.from_dict(po.PipelineManager.load(state.pipeline_id))
    base.graph_id = "graph_1"
    po.PipelineManager.save(base)
    fork = po.PipelineOrchestrator.fork(state.pipeline_id, {"label": "Tariffs double"})
    _settle(fork.pipeline_id)
    assert po.PipelineManager.load(fork.pipeline_id)["options"][po.EVALUATION_RUN_OPTION] == pin
    ctx = po.PipelineOrchestrator._report_ledger_context(
        fork, "sim_fork", run_kind="pipeline", seed=0)
    assert ctx["record_class"] == "evaluation" and ctx["scenario_label"] == "Tariffs double"
    assert (ctx["eval_run_id"], ctx["cell_id"]) == ("sweep-2026-09", "cell-001")


# ───────────────────────────── (B) report + ledger ───────────────────────────
def test_report_under_evaluation_never_reads_production_calibration(env, monkeypatch):
    _finalize_env(monkeypatch, emit_binary=True)
    binding = {"bound": {QID: "F1"}, "missing": [], "method": "normalized_equality",
               "repair_draw": "not_needed"}
    calls = []
    monkeypatch.setattr(fe, "extract_binary_forecasts", _fake_extract(calls, target_binding=binding))
    monkeypatch.setattr(fl, "calibration_summary",
                        lambda *a, **k: pytest.fail("production calibration read in an evaluation run"))
    os.makedirs(ReportManager._get_report_folder("r_eval"), exist_ok=True)
    _bare_agent(evaluation_context=_pin())._finalize_structured_forecast("r_eval", MARKDOWN)
    forecast = _read_forecast("r_eval")
    assert "historical_calibration" not in forecast
    assert forecast["evaluation"] == {
        "record_class": "evaluation", "eval_run_id": "sweep-2026-09", "cell_id": "cell-001",
        "question_id": QID, "historical_calibration_suppressed": True, "target_binding": binding}
    # Only the pinned target reaches the extractor, as its target proposition.
    assert calls[0]["target_propositions"] == [{
        "question_id": QID, "statement": QUESTION,
        "resolution_criteria": GOLDEN_ROW["resolution_criteria"]}]
    assert forecast["binary_forecasts"][0]["target_question_id"] == QID


def test_evaluation_report_without_binaries_reports_missing_target(env, monkeypatch):
    _finalize_env(monkeypatch, emit_binary=False)
    monkeypatch.setattr(fl, "calibration_summary",
                        lambda *a, **k: pytest.fail("production calibration read in an evaluation run"))
    os.makedirs(ReportManager._get_report_folder("r_eval"), exist_ok=True)
    _bare_agent(evaluation_context=_pin())._finalize_structured_forecast("r_eval", MARKDOWN)
    assert _read_forecast("r_eval")["evaluation"]["target_binding"] == {
        "bound": {}, "missing": [QID], "method": "normalized_equality",
        "repair_draw": "not_attempted"}


def test_production_report_forecast_unchanged(env, monkeypatch):
    """No evaluation context: calibration is read, no target kwarg, no evaluation key."""
    _finalize_env(monkeypatch, emit_binary=True)
    _save_pipeline("pipe_prod", "sim_1")               # the owner is a production pipeline
    calls = []
    monkeypatch.setattr(fe, "extract_binary_forecasts", _fake_extract(calls))
    summary = {"n_resolved": 3, "mean_brier": 0.2, "calibration_error": 0.1}
    reads = []
    monkeypatch.setattr(fl, "calibration_summary", lambda *a, **k: reads.append(1) or summary)
    os.makedirs(ReportManager._get_report_folder("r_prod"), exist_ok=True)
    _bare_agent()._finalize_structured_forecast("r_prod", MARKDOWN)
    forecast = _read_forecast("r_prod")
    assert reads == [1] and forecast["historical_calibration"] == summary
    assert "evaluation" not in forecast
    assert "target_propositions" not in calls[0]
    # Byte-identical to the same agent with the evaluation machinery bypassed entirely.
    monkeypatch.setattr(ReportAgent, "_resolve_evaluation_context", lambda self: None)
    os.makedirs(ReportManager._get_report_folder("r_ref"), exist_ok=True)
    _bare_agent()._finalize_structured_forecast("r_ref", MARKDOWN)
    with open(os.path.join(ReportManager._get_report_folder("r_prod"), "forecast.json"), "rb") as a, \
            open(os.path.join(ReportManager._get_report_folder("r_ref"), "forecast.json"), "rb") as b:
        assert a.read() == b.read()


def test_commit_routes_to_evaluation_ledger(env):
    _write_report("r_eval", _forecast())
    receipt = _publish(_Agent(evaluation_context=_pin()), "r_eval")
    assert receipt["status"] == "committed" and receipt["record_class"] == "evaluation"
    assert not os.path.exists(_production_ledger())
    (row,) = fl.read_ledger(fl.evaluation_ledger_dir())
    assert row["record_class"] == "evaluation" and row["characterization_only"] is True
    assert (row["eval_run_id"], row["cell_id"]) == ("sweep-2026-09", "cell-001")
    assert row["target_variant"] == {"eval_run_id": "sweep-2026-09", "cell_id": "cell-001"}
    assert row["binary_forecasts"][0]["statement"] == QUESTION
    # The row ties its binary to the golden question without reopening forecast.json.
    assert (row["binary_forecasts"][0]["target_question_id"],
            row["binary_forecasts"][0]["target_bind"]) == (QID, "verbatim")
    assert fl.is_production_calibration_row(row) is False
    assert fl.calibration_summary()["n_resolved"] == 0

    # Another evaluation run of the same question is its own sample, not a revision.
    other = dict(_pin(), eval_run_id="sweep-2026-10")
    _write_report("r_eval2", _forecast(confidence="medium"))
    assert _publish(_Agent(evaluation_context=other), "r_eval2")["status"] == "committed"

    # A failed evaluation report's unpublished row lands in the evaluation ledger too.
    receipt = _publish(_Agent(evaluation_context=_pin()), "r_eval_failed", status="failed")
    assert receipt["status"] == "unpublished" and receipt["unpublished_row"] == "recorded"
    rows = fl.read_ledger(fl.evaluation_ledger_dir())
    assert [r.get("row_type") for r in rows] == ["commit", "commit", "unpublished_terminal"]
    assert rows[-1]["record_class"] == "evaluation"
    assert not os.path.exists(_production_ledger())


def test_apply_evaluation_context_keeps_member_identity():
    pin = _pin()
    assert lc.apply_evaluation_context({"pipeline_id": "p"}, None) == {"pipeline_id": "p"}
    member = lc.apply_evaluation_context({"record_class": "ensemble_member", "seed": 4}, pin)
    assert member == {"record_class": "evaluation", "evaluated_record_class": "ensemble_member",
                      "seed": 4, "eval_run_id": "sweep-2026-09", "cell_id": "cell-001"}
    assert lc.apply_evaluation_context(member, pin) == member          # idempotent
    compared = lc.apply_evaluation_context({"record_class": "comparison", "provider": "zai"}, pin)
    assert lc._target_variant("evaluation", compared, "") == {
        "eval_run_id": "sweep-2026-09", "cell_id": "cell-001", "provider": "zai"}
    assert lc._target_variant("evaluation", member, "") == {
        "eval_run_id": "sweep-2026-09", "cell_id": "cell-001", "seed": 4}


def test_reused_report_repair_routes_to_evaluation_ledger(env):
    state = po.PipelineState(pipeline_id="pipe_eval", prompt=QUESTION)
    state.options[po.EVALUATION_RUN_OPTION] = _pin()
    ctx = po.PipelineOrchestrator._report_ledger_context(
        state, "sim_eval", run_kind="pipeline", seed=0)
    assert ctx["record_class"] == "evaluation"
    _write_report("r_reused", _forecast())
    receipt = lc.recommit_reused_report(
        "r_reused", report_status="completed", question=QUESTION, language="English",
        actors=None, scenario_label="", ledger_context=ctx,
        publication_status_fn=ReportManager.publication_status,
        load_forecast_fn=ReportManager.load_structured_forecast)
    assert receipt["status"] == "committed" and receipt["repaired"] is True
    assert not os.path.exists(_production_ledger())
    assert fl.read_ledger(fl.evaluation_ledger_dir())[0]["report_id"] == "r_reused"
    # A second repair attempt sees the evaluation row and does nothing.
    assert lc.recommit_reused_report(
        "r_reused", report_status="completed", question=QUESTION, language="English",
        actors=None, scenario_label="", ledger_context=ctx,
        publication_status_fn=ReportManager.publication_status,
        load_forecast_fn=ReportManager.load_structured_forecast) is None


def test_legacy_mode_append_routes_to_evaluation_ledger(env, monkeypatch):
    _finalize_env(monkeypatch, emit_binary=False)
    monkeypatch.setattr(Config, "FORECAST_LEDGER_COMMIT_MODE", "legacy", raising=False)
    os.makedirs(ReportManager._get_report_folder("r_legacy"), exist_ok=True)
    _bare_agent(evaluation_context=_pin())._finalize_structured_forecast("r_legacy", MARKDOWN)
    assert not os.path.exists(_production_ledger())
    (row,) = fl.read_ledger(fl.evaluation_ledger_dir())
    assert row["report_id"] == "r_legacy" and row["schema_version"] == 1


def test_api_path_resolves_context_via_marker(env, monkeypatch):
    pin = _pin()
    _save_pipeline("pipe_eval", "sim_eval", **{po.EVALUATION_RUN_OPTION: pin,
                                               "ensemble_member_simulations": {"sim_member": 7}})
    _save_pipeline("pipe_prod", "sim_prod")
    # A state without the option still counts through its own handoff admission marker.
    marker_state = _save_pipeline("pipe_marker", "sim_marker")
    with open(os.path.join(po.PipelineManager.handoff_dir(marker_state.pipeline_id),
                           po.EVALUATION_RUN_MARKER), "w", encoding="utf-8") as fh:
        json.dump(dict(pin, pipeline_id="pipe_marker"), fh)
    # An unreadable marker fails closed: still an evaluation run.
    broken = _save_pipeline("pipe_broken", "sim_broken")
    with open(os.path.join(po.PipelineManager.handoff_dir(broken.pipeline_id),
                           po.EVALUATION_RUN_MARKER), "w", encoding="utf-8") as fh:
        fh.write("{not json")

    assert po.evaluation_context_for_simulation("sim_eval") == pin
    assert po.evaluation_context_for_simulation("sim_member") == pin
    assert po.evaluation_context_for_simulation("sim_marker") == pin
    assert po.evaluation_context_for_simulation("sim_broken")["record_class"] == "evaluation"
    assert po.evaluation_context_for_simulation("sim_broken")["marker_unreadable"] is True
    assert po.evaluation_context_for_simulation("sim_prod") is None
    assert po.evaluation_context_for_simulation("sim_unknown") is None
    assert po.evaluation_context_for_simulation(None) is None

    # /api/report/generate builds a ReportAgent without evaluation_context: it resolves
    # the run from the owning pipeline, once per agent.
    lookups = []
    real_lookup = po.evaluation_context_for_simulation
    monkeypatch.setattr(po, "evaluation_context_for_simulation",
                        lambda sid: lookups.append(sid) or real_lookup(sid))
    agent = _bare_agent(simulation_id="sim_eval")
    assert agent._resolve_evaluation_context() == pin
    assert agent._resolve_evaluation_context() == pin
    assert lookups == ["sim_eval"]
    assert _bare_agent(simulation_id="sim_prod")._resolve_evaluation_context() is None

    _write_report("r_api", _forecast())
    receipt = _publish(agent, "r_api")
    assert receipt["record_class"] == "evaluation" and receipt["status"] == "committed"
    assert not os.path.exists(_production_ledger())
    (row,) = fl.read_ledger(fl.evaluation_ledger_dir())
    assert row["pipeline_id"] == "pipe_eval" and row["eval_run_id"] == "sweep-2026-09"

    # A regenerated report on an ensemble member's simulation keeps its seed in its target.
    _write_report("r_member", _forecast(confidence="medium"))
    member = _bare_agent(simulation_id="sim_member")
    assert _publish(member, "r_member")["status"] == "committed"
    member_row = fl.read_ledger(fl.evaluation_ledger_dir())[-1]
    assert member_row["target_variant"] == {"eval_run_id": "sweep-2026-09",
                                            "cell_id": "cell-001", "seed": 7}


def test_marker_yields_pin_only_to_its_own_pipeline(env):
    """A batch child shares its evaluation base's handoff dir but answers another question."""
    import scripts.batch_runs as batch_runs

    base = _start(evaluation=EVALUATION)
    pin = po.PipelineManager.load(base.pipeline_id)["options"][po.EVALUATION_RUN_OPTION]
    loaded = po.PipelineState.from_dict(po.PipelineManager.load(base.pipeline_id))
    loaded.graph_id, loaded.simulation_id = "graph_1", "sim_base"
    po.PipelineManager.save(loaded)
    child = batch_runs.fork_question(base.pipeline_id, "Will the UK adopt one too?")
    _settle(child.pipeline_id)
    child_state = po.PipelineState.from_dict(po.PipelineManager.load(child.pipeline_id))
    assert child_state.handoff_dir == loaded.handoff_dir
    assert po.EVALUATION_RUN_OPTION not in child_state.options
    child_state.simulation_id = "sim_child"
    po.PipelineManager.save(child_state)

    # Every path agrees: the child stays out of production but claims no cell identity.
    expected = {"version": "evaluation-run/v1", "record_class": "evaluation",
                "characterization_only": True, "eval_run_id": None, "cell_id": None,
                "question_id": None, "target": None, "foreign_marker": True,
                "marker_pipeline_id": base.pipeline_id}
    assert po.PipelineOrchestrator._evaluation_pin(child_state) == expected
    assert po.evaluation_context_for_simulation("sim_child") == expected
    ctx = po.PipelineOrchestrator._report_ledger_context(
        child_state, "sim_child", run_kind="pipeline", seed=0)
    assert ctx["record_class"] == "evaluation"
    assert "eval_run_id" not in ctx and "cell_id" not in ctx
    agent = _bare_agent(simulation_id="sim_child")
    assert ReportAgent._evaluation_target_propositions(agent._resolve_evaluation_context()) is None
    # The base keeps its full pin through options and through its own marker alike.
    assert po.PipelineOrchestrator._evaluation_pin(loaded) == pin
    assert po.evaluation_context_for_simulation("sim_base") == pin
    options_less = po.PipelineManager.load(base.pipeline_id)
    del options_less["options"][po.EVALUATION_RUN_OPTION]
    assert po._evaluation_pin_of(base.pipeline_id, options_less) == pin

    # A marker that names no pipeline cannot be attributed: fail closed the same way.
    orphan = _save_pipeline("pipe_orphan", "sim_orphan")
    with open(os.path.join(po.PipelineManager.handoff_dir(orphan.pipeline_id),
                           po.EVALUATION_RUN_MARKER), "w", encoding="utf-8") as fh:
        json.dump(pin, fh)
    orphan_pin = po.evaluation_context_for_simulation("sim_orphan")
    assert orphan_pin["foreign_marker"] is True and orphan_pin["target"] is None
    # An id PipelineManager refuses owns no handoff dir, hence no marker (and no crash).
    assert po.PipelineOrchestrator._evaluation_pin(
        po.PipelineState(pipeline_id="../escape", prompt=QUESTION)) is None


def test_owner_lookup_failure_fails_closed(env, monkeypatch):
    def boom(simulation_id):
        raise OSError("pipeline store unreadable")

    monkeypatch.setattr(po, "_ledger_owner_of_simulation", boom)
    stub = po.evaluation_context_for_simulation("sim_any")
    assert stub["record_class"] == "evaluation" and stub["lookup_failed"] is True
    assert (stub["eval_run_id"], stub["cell_id"], stub["target"]) == (None, None, None)

    # An API-regenerated report whose owner cannot be determined never reaches production.
    agent = _bare_agent(simulation_id="sim_any")
    assert agent._resolve_evaluation_context()["lookup_failed"] is True
    _write_report("r_unknown_owner", _forecast())
    receipt = _publish(agent, "r_unknown_owner")
    assert receipt["record_class"] == "evaluation" and receipt["status"] == "committed"
    assert not os.path.exists(_production_ledger())
    (row,) = fl.read_ledger(fl.evaluation_ledger_dir())
    assert row["record_class"] == "evaluation" and "eval_run_id" not in row

    # Even the lookup itself raising inside the agent fails closed.
    def lookup_raises(simulation_id):
        raise RuntimeError("lookup unavailable")

    monkeypatch.setattr(po, "evaluation_context_for_simulation", lookup_raises)
    resolved = _bare_agent(simulation_id="sim_other")._resolve_evaluation_context()
    assert resolved["record_class"] == "evaluation" and resolved["lookup_failed"] is True


def test_early_spine_forecast_is_stamped(env, monkeypatch):
    """A report whose finalize never runs keeps a stamped (never monitored) forecast.json."""
    spine = {k: v for k, v in _forecast().items() if k != "binary_forecasts"}
    monkeypatch.setattr(fe, "derive_forecast_spine", lambda *a, **k: dict(spine))
    monkeypatch.setattr(fe, "render_forecast_spine_block", lambda s: "[spine]")
    monkeypatch.setattr(ReportAgent, "_temporal_horizon_date", lambda self: "")
    monkeypatch.setattr(Config, "REPORT_CRITIQUE_BEFORE_PROSE", False, raising=False)
    for rid in ("r_spine_eval", "r_spine_prod"):
        os.makedirs(ReportManager._get_report_folder(rid), exist_ok=True)
    _bare_agent(evaluation_context=_pin())._derive_and_pin_forecast_spine("r_spine_eval")
    early = _read_forecast("r_spine_eval")
    assert early["evaluation"] == {
        "record_class": "evaluation", "eval_run_id": "sweep-2026-09", "cell_id": "cell-001",
        "question_id": QID, "historical_calibration_suppressed": True,
        "target_binding": {"bound": {}, "missing": [QID], "method": "normalized_equality",
                           "repair_draw": "not_attempted"}}
    assert mon._is_evaluation_report("r_spine_eval") is True

    # Production: the early write is byte-identical to the unstamped spine.
    _save_pipeline("pipe_prod", "sim_1")
    agent = _bare_agent()
    agent._derive_and_pin_forecast_spine("r_spine_prod")
    with open(os.path.join(ReportManager._get_report_folder("r_spine_prod"), "forecast.json"),
              encoding="utf-8") as fh:
        assert fh.read() == json.dumps(spine, ensure_ascii=False, indent=2)
    assert "evaluation" not in agent._forecast_spine


def test_extraction_failure_is_distinguished_in_the_stamp(env, monkeypatch):
    _finalize_env(monkeypatch, emit_binary=True)

    def failing(*args, **kwargs):
        raise RuntimeError("provider down")

    monkeypatch.setattr(fe, "extract_binary_forecasts", failing)
    os.makedirs(ReportManager._get_report_folder("r_eval"), exist_ok=True)
    _bare_agent(evaluation_context=_pin())._finalize_structured_forecast("r_eval", MARKDOWN)
    assert _read_forecast("r_eval")["evaluation"]["target_binding"] == {
        "bound": {}, "missing": [QID], "method": "normalized_equality",
        "repair_draw": "extraction_failed"}


def test_seed_agent_receives_context(env, monkeypatch):
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
            self.evaluation_context = None

        def generate_report(self, report_id=None, **kw):
            captured["evaluation"] = self.evaluation_context
            captured["ctx"] = dict(self.ledger_context)

    monkeypatch.setattr(po, "SimulationManager", _SimManager)
    monkeypatch.setattr(po, "SimulationRunner", _Runner)
    monkeypatch.setattr(po, "ReportAgent", _FakeAgent)
    pin = _pin()
    state = po.PipelineState(pipeline_id="pipe_ens", prompt=QUESTION)
    state.options[po.EVALUATION_RUN_OPTION] = pin
    orch = po.PipelineOrchestrator()
    orch._run_one_seed(state, type("P", (), {"project_id": "proj"})(), "graph_1", None, {},
                       "report md", seed=11, max_rounds=None)
    assert captured["evaluation"] == pin
    assert captured["ctx"]["record_class"] == "evaluation"
    assert captured["ctx"]["evaluated_record_class"] == "ensemble_member"
    assert captured["ctx"]["seed"] == 11
    assert captured["ctx"]["eval_run_id"] == "sweep-2026-09"

    # The main report stage pins it too; a production run leaves the attribute untouched.
    main_agent = _FakeAgent()
    orch._generate_stage_report(state, main_agent, "sim_main", report_id="r_main",
                                progress_callback=lambda *a: None)
    assert captured["evaluation"] == pin and captured["ctx"]["record_class"] == "evaluation"
    production = po.PipelineState(pipeline_id="pipe_prod", prompt=QUESTION)
    production_agent = _FakeAgent()
    orch._generate_stage_report(production, production_agent, "sim_main", report_id="r_main2",
                                progress_callback=lambda *a: None)
    assert captured["evaluation"] is None and "record_class" not in captured["ctx"]
    # The run's own options/handoff decided "production": the report skips the owner scan.
    assert production_agent._evaluation_context_looked_up is True
    assert production_agent._evaluation_context_lookup is None


def test_production_agent_from_orchestrator_skips_owner_scan(env, monkeypatch):
    agent = _bare_agent()
    po.PipelineOrchestrator._assign_evaluation_context(
        agent, po.PipelineState(pipeline_id="pipe_prod", prompt=QUESTION))
    monkeypatch.setattr(po, "_ledger_owner_of_simulation",
                        lambda sid: pytest.fail("pipeline-state scan for an orchestrator agent"))
    assert agent._resolve_evaluation_context() is None


# ───────────────────────────── (C) resolution monitor ────────────────────────
def test_monitor_excludes_evaluation_reports(env, monkeypatch):
    monkeypatch.setattr(Config, "RESOLUTION_MONITOR_LOOKBACK_DAYS", 0, raising=False)
    stamp = {"record_class": "evaluation", "eval_run_id": "sweep-2026-09"}
    for i, rid in enumerate(("r_p1", "r_p2", "r_p3", "r_e1", "r_e2")):
        extra = {"evaluation": stamp} if rid.startswith("r_e") else {}
        # Evaluation reports are the newest: they would crowd production out of the window.
        _write_report(rid, _forecast(**extra), created_at=f"2026-09-2{i}T00:00:00",
                      sealed=rid != "r_e2")
    assert mon.recent_report_ids(3) == ["r_p3", "r_p2", "r_p1"]
    assert mon.recent_report_ids(2) == ["r_p3", "r_p2"]
    assert mon.recent_report_ids(3, exclude_evaluation=False) == ["r_e2", "r_e1", "r_p3"]

    class _NoMarkets:
        def __getattr__(self, name):
            pytest.fail(f"market client used for an evaluation report ({name})")

    folder = ReportManager._get_report_folder("r_e1")
    before = sorted(os.listdir(folder))
    led = str(env / "monitor_ledger")
    res = mon.run_monitor("r_e1", report_folder=folder, client=_NoMarkets(), ledger_dir=led,
                          as_of="2026-09-30T00:00:00")
    assert res["skipped"] == "evaluation_run"
    assert (res["anchored_count"], res["resolved_count"], res["newly_recorded_count"],
            res["needs_manual_count"]) == (0, 0, 0, 0)
    assert res["movers"] == [] and res["resolution_records"] == [] and res["needs_manual"] == []
    assert res["degraded"] is False and res["monitor_report_path"] is None
    assert sorted(os.listdir(folder)) == before          # zero writes
    assert not os.path.exists(led)
    # A production forecast still goes through the normal monitor (not skipped).
    prod = mon.run_monitor("r_p1", forecast=_forecast(), report_folder=str(env / "prod"),
                           client=_NoMarkets(), ledger_dir=led, dry_run=True,
                           as_of="2026-09-30T00:00:00")
    assert "skipped" not in prod


def test_monitor_excludes_unstamped_evaluation_reports_by_owner(env, monkeypatch):
    """Fail closed: a report of an evaluation run without the stamp (failed finalize, no
    forecast.json at all) is recognised through the pipeline that ran its simulation."""
    monkeypatch.setattr(Config, "RESOLUTION_MONITOR_LOOKBACK_DAYS", 0, raising=False)
    _save_pipeline("pipe_eval", "sim_eval", **{po.EVALUATION_RUN_OPTION: _pin()})
    _save_pipeline("pipe_prod", "sim_1")
    _write_report("r_p1", _forecast(), created_at="2026-09-20T00:00:00")
    _write_report("r_p2", _forecast(), created_at="2026-09-21T00:00:00")
    _write_report("r_e_unstamped", _forecast(), created_at="2026-09-22T00:00:00",
                  sealed=False, simulation_id="sim_eval")
    _write_report("r_e_noforecast", None, created_at="2026-09-23T00:00:00",
                  simulation_id="sim_eval")
    assert mon.recent_report_ids(2) == ["r_p2", "r_p1"]

    class _NoMarkets:
        def __getattr__(self, name):
            pytest.fail(f"market client used for an evaluation report ({name})")

    led = str(env / "monitor_ledger")
    for rid in ("r_e_unstamped", "r_e_noforecast"):
        folder = ReportManager._get_report_folder(rid)
        before = sorted(os.listdir(folder))
        res = mon.run_monitor(rid, client=_NoMarkets(), ledger_dir=led,
                              as_of="2026-09-30T00:00:00")
        assert res["skipped"] == "evaluation_run"
        assert sorted(os.listdir(folder)) == before and not os.path.exists(led)

    # An owner lookup that fails excludes the report too (never monitored as production).
    def boom(simulation_id):
        raise OSError("pipeline store unreadable")

    monkeypatch.setattr(po, "_ledger_owner_of_simulation", boom)
    assert mon.recent_report_ids(2) == []


# ───────────────────────────── (D) target binding ────────────────────────────
def _row(statement, probability, **extra):
    row = {"id": "F9", "statement": statement, "probability": probability,
           "resolution_criteria": "Resolves YES if the named outcome happens by 2030-12-31.",
           "theme": "policy", "horizon_year": 2030, "adjustment_rationale": "base rate"}
    row.update(extra)
    return row


OTHER_A = _row("AI capex exceeds $500B in 2027", 0.8)
OTHER_B = _row("The ECB cuts its deposit rate below 1% by 2027-12-31", 0.3)
TARGET = {"question_id": QID, "statement": QUESTION,
          "resolution_criteria": GOLDEN_ROW["resolution_criteria"]}


@pytest.fixture
def extract_env(monkeypatch):
    for name, value in (("FORECAST_BINARY_CONTRARIAN", False), ("FORECAST_ENSEMBLE_MODELS", ""),
                        ("EVAL_TARGET_REPAIR_DRAW", True)):
        monkeypatch.setattr(Config, name, value, raising=False)


def _prompt(fake, index):
    return fake.calls[index]["messages"][0]["content"]


def test_normalize_target_statement():
    norm = fe.normalize_target_statement
    assert norm("  Will  X\thappen ?? ") == norm("will x happen.") == "will x happen"
    assert norm("Will Ｘ happen？") == "will x happen"        # NFKC folds full-width forms
    assert norm("Will X happen, really?") != norm("Will X happen?")
    assert norm("Will X happen? . ?\u3000") == "will x happen"
    assert norm(None) == ""
    # Linear on degenerate model output: a long interior run of '?', '.' or spaces (a
    # backtracking trailing-strip regex took ~11 s at 64k characters here).
    started = time.perf_counter()
    long_run = "a" + "." * 200_000 + "b"
    assert norm(long_run) == long_run
    assert norm("x" + " ?." * 100_000) == "x"
    assert time.perf_counter() - started < 2.0


def test_target_binding_case_whitespace_drift(extract_env):
    drifted = "  will the eu   ADOPT a binding AI liability directive by 2030 "
    fake = FakeLLMClient(json_responses=[{"binary_forecasts": [OTHER_A, _row(drifted, 0.35)]}])
    out = fe.extract_binary_forecasts("dossier", fake, min_count=2, language="English",
                                      target_propositions=[TARGET])
    assert len(fake.calls) == 1                      # bound on the first draw: no repair draw
    first, second = out["binary_forecasts"]
    assert (first["id"], second["id"]) == ("F1", "F2")   # bound after the F-renumbering
    assert "target_question_id" not in first
    assert second["target_question_id"] == QID and second["target_bind"] == "normalized"
    assert out["target_binding"] == {"bound": {QID: "F2"}, "missing": [],
                                     "method": "normalized_equality", "repair_draw": "not_needed"}
    # The first draw asked for the statement verbatim, right before the dossier.
    prompt = _prompt(fake, 0)
    assert fe._TARGET_PROPOSITION_RULE in prompt
    assert prompt.index(f"- {QUESTION}") < prompt.index("[Research dossier]")
    assert f"Resolution criteria: {GOLDEN_ROW['resolution_criteria']}" in prompt

    exact = FakeLLMClient(json_responses=[{"binary_forecasts": [_row(QUESTION, 0.35), OTHER_A]}])
    out = fe.extract_binary_forecasts("dossier", exact, min_count=2, target_propositions=[TARGET])
    assert out["binary_forecasts"][0]["target_bind"] == "verbatim"
    assert out["target_binding"]["bound"] == {QID: "F1"}


def test_no_targets_prompts_byte_identical(extract_env):
    def run(**kwargs):
        fake = FakeLLMClient(json_responses=[{"binary_forecasts": [OTHER_A, OTHER_B]}])
        out = fe.extract_binary_forecasts("dossier text", fake, min_count=2, language="English",
                                          **kwargs)
        return [_prompt(fake, i) for i in range(len(fake.calls))], out

    base_prompts, base_out = run()
    for kwargs in ({"target_propositions": None}, {"target_propositions": []},
                   {"target_propositions": [{"question_id": "", "statement": "x"}, "junk"]}):
        prompts, out = run(**kwargs)
        assert prompts == base_prompts and out == base_out
    assert "target_binding" not in base_out
    assert "REQUIRED TARGET" not in base_prompts[0]
    assert all("target_question_id" not in b for b in base_out["binary_forecasts"])

    # With a target, the only prompt change is the addendum inserted before the dossier.
    prompts, _out = run(target_propositions=[TARGET])
    block = fe._target_proposition_block(fe._clean_target_propositions([TARGET]))
    assert prompts[0] == base_prompts[0].replace(
        "\n\n[Research dossier]\n", block + "\n\n[Research dossier]\n")


def test_missing_target_one_repair_draw_then_missing_no_fabrication(extract_env):
    near_miss = _row("The EU adopts some AI liability rules by 2030", 0.3)
    fake = FakeLLMClient(json_responses=[{"binary_forecasts": [OTHER_A, OTHER_B]},
                                         {"binary_forecasts": [near_miss, OTHER_A]}])
    out = fe.extract_binary_forecasts("dossier", fake, min_count=2, target_propositions=[TARGET])
    assert len(fake.calls) == 2                      # exactly one bounded repair draw
    repair = _prompt(fake, 1)
    assert fe._TARGET_REPAIR_RULE in repair and fe._TARGET_PROPOSITION_RULE not in repair
    assert f"- {QUESTION}" in repair
    assert f"- {OTHER_A['statement']}" in repair     # existing statements are excluded
    assert [b["statement"] for b in out["binary_forecasts"]] == [OTHER_A["statement"],
                                                                 OTHER_B["statement"]]
    assert all("target_question_id" not in b for b in out["binary_forecasts"])
    assert out["target_binding"] == {"bound": {}, "missing": [QID],
                                     "method": "normalized_equality", "repair_draw": "unmatched"}
    assert out["binary_quality"]["count"] == 2

    # A repair draw that does produce the statement is kept as the next F id.
    fake = FakeLLMClient(json_responses=[{"binary_forecasts": [OTHER_A, OTHER_B]},
                                         {"binary_forecasts": [_row(QUESTION.rstrip("?") + ".",
                                                                    0.3, id="F1")]}])
    out = fe.extract_binary_forecasts("dossier", fake, min_count=2, target_propositions=[TARGET])
    repaired = out["binary_forecasts"][-1]
    assert (repaired["id"], repaired["target_question_id"], repaired["target_bind"]) == (
        "F3", QID, "repair_draw")
    assert out["target_binding"] == {"bound": {QID: "F3"}, "missing": [],
                                     "method": "normalized_equality", "repair_draw": "bound"}


def _binary_keys(binaries):
    return [fe._binary_key(b["statement"]) for b in binaries]


FED_TARGET = {"question_id": "fed-below-3", "statement":
              "Will the Fed's policy rate be below 3% by 2027-12-31?"}


@pytest.mark.parametrize("target, drifted", [
    (TARGET, QUESTION.replace("AI liability", "AI-liability")),             # hyphen vs space
    (FED_TARGET, FED_TARGET["statement"].replace("'", "\u2019")),          # curly apostrophe
])
def test_near_duplicate_target_is_never_published_twice(extract_env, target, drifted):
    """Punctuation drift the binding key keeps apart but _binary_key folds: no repair draw,
    no second row for the proposition; the grader is pointed at the near-verbatim row."""
    assert fe.normalize_target_statement(drifted) != fe.normalize_target_statement(
        target["statement"])
    fake = FakeLLMClient(json_responses=[
        {"binary_forecasts": [OTHER_A, _row(drifted, 0.3)]},
        {"binary_forecasts": [_row(target["statement"], 0.6)]}])     # never requested
    out = fe.extract_binary_forecasts("dossier", fake, min_count=2, target_propositions=[target])
    assert len(fake.calls) == 1
    keys = _binary_keys(out["binary_forecasts"])
    assert len(keys) == len(set(keys)) == 2
    assert [b["probability"] for b in out["binary_forecasts"]] == [0.8, 0.3]
    assert all("target_question_id" not in b for b in out["binary_forecasts"])
    assert out["target_binding"] == {
        "bound": {}, "missing": [target["question_id"]], "method": "normalized_equality",
        "repair_draw": "near_duplicate", "near_match": {target["question_id"]: "F2"}}


def test_repair_row_colliding_with_an_existing_key_is_dropped(extract_env):
    """Defence in depth: a repair row that matches the target (NFKC folds a ligature) but
    shares an existing row's _binary_key is never appended."""
    target = {"question_id": "q-lig", "statement": "Will \ufb01nance grow?"}   # 'ﬁ' ligature
    existing = _row("Will finance-grow?", 0.3)
    fake = FakeLLMClient(json_responses=[{"binary_forecasts": [OTHER_A, existing]},
                                         {"binary_forecasts": [_row("Will finance grow?", 0.6)]}])
    out = fe.extract_binary_forecasts("dossier", fake, min_count=2, target_propositions=[target])
    assert len(fake.calls) == 2                      # the target itself was requested once
    keys = _binary_keys(out["binary_forecasts"])
    assert len(keys) == len(set(keys)) == 2
    assert out["target_binding"] == {
        "bound": {}, "missing": ["q-lig"], "method": "normalized_equality",
        "repair_draw": "unmatched", "near_match": {"q-lig": "F2"}}


def test_top_up_does_not_rerequest_a_near_duplicate_target(extract_env):
    drifted = QUESTION.replace("AI liability", "AI-liability")
    fake = FakeLLMClient(json_responses=[{"binary_forecasts": [OTHER_A, _row(drifted, 0.3)]},
                                         {"binary_forecasts": [OTHER_B]}])
    out = fe.extract_binary_forecasts("dossier", fake, min_count=3, target_propositions=[TARGET])
    assert len(fake.calls) == 2                      # first draw + top-up, no repair draw
    assert fe._TARGET_PROPOSITION_RULE in _prompt(fake, 0)
    assert "REQUIRED TARGET" not in _prompt(fake, 1)
    assert out["target_binding"]["repair_draw"] == "near_duplicate"
    assert len(set(_binary_keys(out["binary_forecasts"]))) == 3


def test_repair_draw_withheld_rows_count_only_for_the_target(extract_env):
    unreadable_extra = _row("An unrelated proposition the repair draw volunteered", None)
    fake = FakeLLMClient(json_responses=[{"binary_forecasts": [OTHER_A, OTHER_B]},
                                         {"binary_forecasts": [_row(QUESTION, 0.4),
                                                               unreadable_extra]}])
    out = fe.extract_binary_forecasts("dossier", fake, min_count=2, target_propositions=[TARGET])
    assert out["target_binding"]["repair_draw"] == "bound"
    assert "needs_review_count" not in out["binary_quality"]
    assert not any("withheld" in issue for issue in out["binary_quality"].get("issues", []))

    # The target's own unreadable probability is withheld, and counted.
    fake = FakeLLMClient(json_responses=[{"binary_forecasts": [OTHER_A, OTHER_B]},
                                         {"binary_forecasts": [_row(QUESTION, None),
                                                               unreadable_extra]}])
    out = fe.extract_binary_forecasts("dossier", fake, min_count=2, target_propositions=[TARGET])
    assert out["target_binding"]["repair_draw"] == "unmatched"
    assert out["binary_quality"]["needs_review_count"] == 1
    assert out["binary_quality"]["issues"][0] == fe._binary_withheld_issue(1)


def test_cell_forecast_scores_in_golden_eval_without_editing_ids(env, extract_env, monkeypatch):
    """End to end: finalize under the pin → forecast.json → golden_eval matches the cell."""
    import scripts.golden_eval as ge

    _finalize_env(monkeypatch, emit_binary=True)
    monkeypatch.setattr(Config, "BINARY_FORECASTS_MIN_COUNT", 2, raising=False)
    llm = FakeLLMClient(json_responses=[{"binary_forecasts": [
        OTHER_A, _row(QUESTION.upper().rstrip("?"), 0.35)]}])
    os.makedirs(ReportManager._get_report_folder("r_cell"), exist_ok=True)
    _bare_agent(evaluation_context=_pin(), llm=llm)._finalize_structured_forecast(
        "r_cell", MARKDOWN)
    forecast = _read_forecast("r_cell")
    bound = [b for b in forecast["binary_forecasts"] if b.get("target_question_id") == QID]
    assert [b["id"] for b in bound] == ["F2"]
    assert forecast["evaluation"]["target_binding"]["bound"] == {QID: "F2"}
    assert f"- {QUESTION}" in llm.calls[0]["messages"][0]["content"]
    golden = ge.index_golden([GOLDEN_ROW])
    res = ge.match_forecasts(ge.extract_binary_forecasts(forecast), golden)
    assert [(m["id"], m["forecast_id"], m["probability"]) for m in res["matched"]] == [
        (QID, "F2", 0.35)]
    assert res["unmatched_golden_ids"] == []


def test_repair_draw_disabled_or_failing_reports_missing(extract_env, monkeypatch):
    monkeypatch.setattr(Config, "EVAL_TARGET_REPAIR_DRAW", False, raising=False)
    fake = FakeLLMClient(json_responses=[{"binary_forecasts": [OTHER_A, OTHER_B]}])
    out = fe.extract_binary_forecasts("dossier", fake, min_count=2, target_propositions=[TARGET])
    assert len(fake.calls) == 1
    assert out["target_binding"]["missing"] == [QID]
    assert out["target_binding"]["repair_draw"] == "disabled"

    monkeypatch.setattr(Config, "EVAL_TARGET_REPAIR_DRAW", True, raising=False)

    class _FailingRepair(FakeLLMClient):
        def chat_json(self, messages, **kwargs):
            if self.calls:
                raise RuntimeError("provider down")
            return super().chat_json(messages, **kwargs)

    failing = _FailingRepair(json_responses=[{"binary_forecasts": [OTHER_A, OTHER_B]}])
    out = fe.extract_binary_forecasts("dossier", failing, min_count=2, target_propositions=[TARGET])
    assert len(out["binary_forecasts"]) == 2
    assert out["target_binding"] == {"bound": {}, "missing": [QID],
                                     "method": "normalized_equality", "repair_draw": "failed"}
