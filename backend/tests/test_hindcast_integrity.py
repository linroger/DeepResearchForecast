"""TIME-9: the hindcast integrity verdict, stamped from the research audit before the seal.

A gated hindcast's v3 research writes ``point_in_time.json``; after the research
contract is finalized the orchestrator records its verdict once per research
generation as the pin's ``research_audit`` (``{'status', 'sha256'}``; no other
pin field changes), refreshes run.json ``resolved.as_of_enforcement``
(``retrieval_clamped`` / ``audit_status``), and every report agent receives the
updated pin, so forecast.json's ``hindcast.integrity`` reflects the audit.
Without a (valid) audit, and for live runs, everything is as before TIME-9.

Offline: FakeLLMClient / stubs, per-test data directories.
"""

import copy
import hashlib
import json
import os

import pytest

from app.config import Config
from app.services import forecast_extractor as fe
from app.services import hindcast_policy as hp
from app.services import pipeline_orchestrator as po
from app.services.report_agent import ReportManager
from tests import test_hindcast_report_containment as containment

# Shared fixtures of the TIME-6 containment tests (data dirs, recorded market calls).
env = containment.env
market_calls = containment.market_calls

GATED = {"gates": True, "same_day": "exclude", "undated": "drop", "provider_bounds": True, "overfetch": 1}
PIN = dict(containment.PIN, pit=dict(GATED))
UNGATED_PIN = dict(containment.PIN, pit=dict(GATED, gates=False))
ENFORCEMENT = containment.ENFORCEMENT
BLOCK = containment.BLOCK


def _audit_payload(status="date_verified", **over):
    payload = {
        "schema": "drf-point-in-time/v1", "as_of": "2024-06-01", "same_day_policy": "exclude",
        "undated_policy": "drop",
        "streams": {"search": {"checked": 4, "admitted": 1, "same_day": 0, "unverifiable": 1, "late": 2},
                    "fetch": {"checked": 2, "admitted": 1, "same_day": 0, "unverifiable": 1, "late": 0},
                    "cited": {"checked": 1, "admitted": 1, "same_day": 0, "unverifiable": 0,
                              "late": 1 if status == "violated" else 0}},
        "wall": {"sids_withheld": 1, "digest_lines_dropped": 1, "digest_markers_stripped": 2},
        "parametric_suspects": {"timeline": 0, "quant": 0},
        "leak_guard": "source_publication_dates_only", "parametric_knowledge": "not_guarded",
        "live_page_text": "labelled_not_archived", "status": status,
    }
    payload.update(over)
    return payload


def _write_audit(handoff, payload):
    os.makedirs(handoff, exist_ok=True)
    raw = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
    with open(os.path.join(handoff, hp.POINT_IN_TIME_FILENAME), "wb") as fh:
        fh.write(raw)
    return hashlib.sha256(raw).hexdigest()


def _state(pid, pin, tmp_path):
    state = po.PipelineState(pipeline_id=pid, prompt=containment.QUESTION)
    if pin is not None:
        state.options[hp.HINDCAST_POLICY_OPTION] = copy.deepcopy(pin)
    state.handoff_dir = str(tmp_path / pid / "handoff")
    return state


def _run_json(pid):
    with open(po.PipelineManager.manifest_path(pid), encoding="utf-8") as fh:
        return json.load(fh)


@pytest.fixture
def manifest_env(env, monkeypatch):
    monkeypatch.setattr(po, "_repo_git_sha", lambda: "gitsha")
    monkeypatch.setattr(po, "_deerflow_ref", lambda: None)
    monkeypatch.setattr(Config, "RECORD_RUN_MANIFEST", True, raising=False)
    return env


# ───────────────────────────── the pin ───────────────────────────────────────
def test_research_audit_is_recorded_in_the_pin_once_per_research_generation(manifest_env, monkeypatch):
    state = _state("pipe_audit", PIN, manifest_env)
    digest = _write_audit(state.handoff_dir, _audit_payload())
    refreshes = []
    real_refresh = po.PipelineOrchestrator._refresh_as_of_enforcement
    monkeypatch.setattr(po.PipelineOrchestrator, "_refresh_as_of_enforcement",
                        lambda self, st: refreshes.append(st.pipeline_id) or real_refresh(self, st))
    orchestrator = po.PipelineOrchestrator()
    orchestrator._record_research_audit(state, state.handoff_dir)
    stored = state.options[hp.HINDCAST_POLICY_OPTION]
    assert stored["research_audit"] == {"status": "date_verified", "sha256": digest}
    # No other pin field changed.
    assert {key: value for key, value in stored.items() if key != "research_audit"} == PIN
    assert list(stored)[:-1] == list(PIN)
    # A resume that reuses the research finds the same bytes: nothing changes.
    orchestrator._record_research_audit(state, state.handoff_dir)
    assert refreshes == ["pipe_audit"]
    assert state.options[hp.HINDCAST_POLICY_OPTION]["research_audit"]["sha256"] == digest
    # A re-run research replaces the audit of the research it replaced.
    violated = _write_audit(state.handoff_dir, _audit_payload("violated"))
    orchestrator._record_research_audit(state, state.handoff_dir)
    assert state.options[hp.HINDCAST_POLICY_OPTION]["research_audit"] == {"status": "violated", "sha256": violated}
    # A research without an audit leaves none behind (fail closed: labelled).
    os.unlink(os.path.join(state.handoff_dir, hp.POINT_IN_TIME_FILENAME))
    orchestrator._record_research_audit(state, state.handoff_dir)
    assert state.options[hp.HINDCAST_POLICY_OPTION] == PIN
    assert refreshes == ["pipe_audit"] * 3


@pytest.mark.parametrize("content", [
    json.dumps(_audit_payload(schema="drf-point-in-time/v0")),
    json.dumps(_audit_payload(status="clean")),
    json.dumps(["not", "an", "audit"]),
    "{truncated",
    b"\xff\xfe not utf-8",
    # An audit of another pin's research (as-of or policies) vouches for nothing either.
    json.dumps(_audit_payload(as_of="2024-05-31")),
    json.dumps(_audit_payload(same_day_policy="include")),
    json.dumps(_audit_payload(undated_policy="flag")),
    json.dumps({key: value for key, value in _audit_payload().items() if key != "as_of"}),
])
def test_an_unrecognised_audit_vouches_for_nothing(env, tmp_path, content):
    state = _state("pipe_bad", PIN, tmp_path)
    os.makedirs(state.handoff_dir)
    mode = "wb" if isinstance(content, bytes) else "w"
    with open(os.path.join(state.handoff_dir, hp.POINT_IN_TIME_FILENAME), mode) as fh:
        fh.write(content)
    po.PipelineOrchestrator()._record_research_audit(state, state.handoff_dir)
    assert state.options[hp.HINDCAST_POLICY_OPTION] == PIN


@pytest.mark.parametrize("pin", [None, UNGATED_PIN, containment.LIVE_PIN, containment.PIN | {"pit": None}])
def test_no_audit_without_a_gated_hindcast_pin(env, tmp_path, pin):
    state = _state("pipe_none", pin, tmp_path)
    _write_audit(state.handoff_dir, _audit_payload())
    before = copy.deepcopy(state.options)
    po.PipelineOrchestrator()._record_research_audit(state, state.handoff_dir)
    assert state.options == before


def test_a_stale_audit_on_an_ungated_pin_is_dropped(env, tmp_path):
    state = _state("pipe_stale", dict(UNGATED_PIN, research_audit={"status": "date_verified", "sha256": "ab"}),
                   tmp_path)
    _write_audit(state.handoff_dir, _audit_payload())
    po.PipelineOrchestrator()._record_research_audit(state, state.handoff_dir)
    assert state.options[hp.HINDCAST_POLICY_OPTION] == UNGATED_PIN


# ───────────────────────────── run.json ──────────────────────────────────────
@pytest.mark.parametrize("status, clamped", [
    ("date_verified", True), ("date_verified_with_unverifiable", True), ("violated", False)])
def test_run_json_attests_the_audit(manifest_env, status, clamped):
    state = _state(f"pipe_run_{status}", PIN, manifest_env)
    orchestrator = po.PipelineOrchestrator()
    orchestrator._write_run_manifest(state)
    assert _run_json(state.pipeline_id)["resolved"]["as_of_enforcement"] == ENFORCEMENT
    _write_audit(state.handoff_dir, _audit_payload(status))
    orchestrator._record_research_audit(state, state.handoff_dir)
    expected = dict(ENFORCEMENT, retrieval_clamped=clamped, audit_status=status)
    assert _run_json(state.pipeline_id)["resolved"]["as_of_enforcement"] == expected
    # A later attempt's fresh run.json is built from the same pin.
    assert po._build_run_manifest(state)["resolved"]["as_of_enforcement"] == expected


def test_run_json_is_left_missing_when_absent(manifest_env):
    state = _state("pipe_no_run_json", PIN, manifest_env)
    _write_audit(state.handoff_dir, _audit_payload())
    po.PipelineOrchestrator()._record_research_audit(state, state.handoff_dir)
    assert state.options[hp.HINDCAST_POLICY_OPTION]["research_audit"]["status"] == "date_verified"
    assert not os.path.exists(po.PipelineManager.manifest_path(state.pipeline_id))


def test_enforcement_record_mapping():
    assert hp.as_of_enforcement_record(PIN) == ENFORCEMENT
    audited = dict(PIN, research_audit={"status": "date_verified", "sha256": "ab"})
    assert hp.as_of_enforcement_record(audited) == dict(ENFORCEMENT, retrieval_clamped=True,
                                                         audit_status="date_verified")
    # The gates must have run for retrieval to count as clamped; an unknown verdict is no audit.
    ungated = dict(audited, pit=dict(GATED, gates=False))
    assert hp.as_of_enforcement_record(ungated) == dict(ENFORCEMENT, audit_status="date_verified")
    assert hp.as_of_enforcement_record(dict(PIN, research_audit={"status": "clean"})) == ENFORCEMENT


def test_research_audit_record():
    assert hp.research_audit_record(_audit_payload(), "ab", pin=PIN) == {"status": "date_verified", "sha256": "ab"}
    assert hp.research_audit_record(_audit_payload("violated"), "cd", pin=PIN)["status"] == "violated"
    for payload, digest in ((_audit_payload(), ""), (_audit_payload(), None), (_audit_payload(status=None), "ab"),
                            ({"status": "date_verified"}, "ab"), (None, "ab")):
        assert hp.research_audit_record(payload, digest, pin=PIN) is None
    # The audit must be of this pin: its as-of and the policies the research was launched with.
    flagged = dict(PIN, pit=dict(GATED, undated="flag", same_day="include"))
    assert hp.research_audit_record(_audit_payload(), "ab", pin=flagged) is None
    assert hp.research_audit_record(_audit_payload(undated_policy="flag", same_day_policy="include"), "ab",
                                    pin=flagged) == {"status": "date_verified", "sha256": "ab"}
    # A hand-edited policy value reads strict, as it did for the research launch.
    odd = dict(PIN, pit=dict(GATED, undated="sometimes", same_day=None))
    assert hp.research_audit_record(_audit_payload(), "ab", pin=odd) == {"status": "date_verified", "sha256": "ab"}
    for pin in (UNGATED_PIN, dict(PIN, pit=None), dict(PIN, as_of=None), {}, None):
        assert hp.research_audit_record(_audit_payload(), "ab", pin=pin) is None


# ───────────────────────────── artifacts ─────────────────────────────────────
def test_point_in_time_json_is_a_research_artifact_and_sealed_when_present(tmp_path):
    state = po.PipelineState(pipeline_id="pipe_specs", prompt="q", handoff_dir=str(tmp_path))
    specs = dict(po.PipelineOrchestrator._stage_artifact_specs(state, po.STAGE_RESEARCH))
    assert specs["point_in_time"] == os.path.join(str(tmp_path), "point_in_time.json")
    assert "point_in_time.json" in po._RESEARCH_CONTRACT_FILES
    assert hp.POINT_IN_TIME_FILENAME == "point_in_time.json"


# ───────────────────────────── forecast.json ─────────────────────────────────
@pytest.mark.parametrize("status, integrity", [
    ("date_verified", "date_verified"),
    ("date_verified_with_unverifiable", "date_verified_with_unverifiable"),
    ("violated", "leak_suspected"),
])
def test_forecast_block_maps_the_audit_to_integrity(status, integrity):
    block = hp.hindcast_forecast_block(PIN, research_audit={"status": status, "sha256": "ab"})
    assert block == dict(BLOCK, retrieval="date_gated", integrity=integrity)


@pytest.mark.parametrize("audit", [None, {}, {"status": "clean"}, {"verdict": "clean"}, "violated"])
def test_forecast_block_without_an_audit_stays_labelled(audit):
    assert hp.hindcast_forecast_block(PIN, research_audit=audit) == BLOCK


@pytest.mark.parametrize("audit, integrity", [
    (None, "labelled"), ({"status": "violated", "sha256": "ab"}, "leak_suspected"),
    ({"status": "date_verified", "sha256": "ab"}, "date_verified")])
def test_forecast_json_carries_the_integrity_verdict(env, market_calls, monkeypatch, audit, integrity):
    containment._finalize_env(monkeypatch)
    monkeypatch.setattr(fe, "extract_binary_forecasts", containment._fake_extract([]))
    pin = dict(PIN, research_audit=audit) if audit is not None else PIN
    os.makedirs(ReportManager._get_report_folder("r_integrity"), exist_ok=True)
    containment._bare_agent(hindcast=pin)._finalize_structured_forecast("r_integrity", containment.MARKDOWN)
    hindcast = containment._read_forecast("r_integrity")["hindcast"]
    assert hindcast["integrity"] == integrity
    assert hindcast["retrieval"] == ("live_labelled" if audit is None else "date_gated")
    assert market_calls == []


# ───────────────────────────── the state machine ─────────────────────────────
@pytest.mark.parametrize("status, clamped", [("date_verified", True), ("violated", False)])
def test_research_stage_stamps_the_pin_before_the_report_reads_it(monkeypatch, tmp_path, status, clamped):
    """The real _run state machine (every service faked): the research stage records the
    audit, the report agent receives the updated pin and run.json attests it."""
    from tests.test_orchestrator_research_wiring import _exercise_prepare_run_resume

    created = []
    written = {}

    class _Recording(po.ReportAgent):
        def __new__(cls, *args, **kwargs):
            agent = super().__new__(cls)
            created.append(agent)
            return agent

    real_record = po.PipelineOrchestrator._record_research_audit

    def research_with_audit(self, state, handoff_dir):
        # The gated v3 child wrote its audit into the handoff before this point.
        written["sha256"] = _write_audit(handoff_dir, _audit_payload(status))
        return real_record(self, state, handoff_dir)

    monkeypatch.setattr(po, "ReportAgent", _Recording)
    monkeypatch.setattr(po.PipelineOrchestrator, "_record_research_audit", research_with_audit)
    result = _exercise_prepare_run_resume(
        monkeypatch, tmp_path, rebuild_prepare=True, real_run_manifest=True,
        extra_options={hp.HINDCAST_POLICY_OPTION: copy.deepcopy(PIN)})
    assert result.report_generations, "the stage must build a fresh report"
    audit = {"status": status, "sha256": written["sha256"]}
    assert created[-1].kwargs["hindcast"] == dict(PIN, research_audit=audit)
    assert result.state.options[hp.HINDCAST_POLICY_OPTION] == dict(PIN, research_audit=audit)
    saved = po.PipelineManager.load(result.pid)
    assert saved["options"][hp.HINDCAST_POLICY_OPTION]["research_audit"] == audit
    resolved = _run_json(result.pid)["resolved"]
    assert resolved["as_of_enforcement"] == dict(ENFORCEMENT, retrieval_clamped=clamped, audit_status=status)
