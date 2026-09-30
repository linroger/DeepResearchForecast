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
import datetime as dt
import hashlib
import json
import os
import sys

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


# The cited re-check each verdict follows from (under the pin's undated policy, drop).
_CITED = {
    "date_verified": {"checked": 1, "admitted": 1, "same_day": 0, "unverifiable": 0, "late": 0},
    "date_verified_with_unverifiable": {"checked": 2, "admitted": 1, "same_day": 0, "unverifiable": 1, "late": 0},
    "violated": {"checked": 2, "admitted": 1, "same_day": 0, "unverifiable": 0, "late": 1},
}


def _audit_payload(status="date_verified", *, cited=None, **over):
    payload = {
        "schema": "drf-point-in-time/v1", "as_of": "2024-06-01", "same_day_policy": "exclude",
        "undated_policy": "drop",
        "streams": {"search": {"checked": 4, "admitted": 1, "same_day": 0, "unverifiable": 1, "late": 2},
                    "fetch": {"checked": 2, "admitted": 1, "same_day": 0, "unverifiable": 1, "late": 0},
                    "cited": dict(cited if cited is not None else _CITED.get(status, _CITED["date_verified"]))},
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


class _WarningRecorder:
    """Stands in for the orchestrator's logger (which does not propagate): keeps its warnings."""

    def __init__(self):
        self.warnings = []

    def warning(self, msg, *args):
        self.warnings.append(msg % args)

    def __getattr__(self, name):
        return lambda *args, **kwargs: None


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
    # An unhashable verdict (hand-edited or migrated) is no verdict, not a crash.
    json.dumps(dict(_audit_payload(), status=["x"])),
    json.dumps(dict(_audit_payload(), status={})),
    json.dumps(["not", "an", "audit"]),
    "{truncated",
    b"\xff\xfe not utf-8",
    # An audit of another pin's research (as-of or policies) vouches for nothing either.
    json.dumps(_audit_payload(as_of="2024-05-31")),
    json.dumps(_audit_payload(same_day_policy="include")),
    json.dumps(_audit_payload(undated_policy="flag")),
    json.dumps({key: value for key, value in _audit_payload().items() if key != "as_of"}),
    # A verdict its own cited counts do not imply (hand-edited) vouches for nothing.
    json.dumps(_audit_payload("date_verified", cited=_CITED["violated"])),
    json.dumps(_audit_payload("date_verified", cited=_CITED["date_verified_with_unverifiable"])),
    json.dumps(_audit_payload("violated", cited=_CITED["date_verified"])),
    json.dumps(_audit_payload(cited=dict(_CITED["date_verified"], checked=3))),
    json.dumps(_audit_payload(streams={})),
])
def test_an_unrecognised_audit_vouches_for_nothing(env, tmp_path, monkeypatch, content):
    state = _state("pipe_bad", PIN, tmp_path)
    os.makedirs(state.handoff_dir)
    mode = "wb" if isinstance(content, bytes) else "w"
    with open(os.path.join(state.handoff_dir, hp.POINT_IN_TIME_FILENAME), mode) as fh:
        fh.write(content)
    recorder = _WarningRecorder()
    monkeypatch.setattr(po, "logger", recorder)
    po.PipelineOrchestrator()._record_research_audit(state, state.handoff_dir)
    assert state.options[hp.HINDCAST_POLICY_OPTION] == PIN
    # A parseable audit is judged and rejected, never mistaken for an unreadable file.
    unreadable = content in ("{truncated", b"\xff\xfe not utf-8")
    [warning] = [message for message in recorder.warnings if hp.POINT_IN_TIME_FILENAME in message]
    assert ("unreadable" in warning) is unreadable
    assert ("not a recognised research audit" in warning) is not unreadable


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


@pytest.mark.parametrize("status", [["x"], {"a": 1}])
def test_run_json_survives_an_unhashable_audit_verdict(manifest_env, status):
    """A hand-edited or migrated state.json whose pin carries an unhashable verdict: run.json
    is still built, with the unaudited record."""
    state = _state("pipe_odd_verdict", dict(PIN, research_audit={"status": status, "sha256": "ab"}), manifest_env)
    assert po._build_run_manifest(state)["resolved"]["as_of_enforcement"] == ENFORCEMENT


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
    # Without the gates no audit vouches for the retrieval (as in forecast.json); an unknown
    # verdict is no audit.
    for pit in (dict(GATED, gates=False), dict(GATED, gates="true"), None):
        assert hp.as_of_enforcement_record(dict(audited, pit=pit)) == ENFORCEMENT
    for status in ("clean", ["x"], {"a": 1}):
        assert hp.as_of_enforcement_record(dict(PIN, research_audit={"status": status})) == ENFORCEMENT


def test_research_audit_record():
    assert hp.research_audit_record(_audit_payload(), "ab", pin=PIN) == {"status": "date_verified", "sha256": "ab"}
    assert hp.research_audit_record(_audit_payload("violated"), "cd", pin=PIN)["status"] == "violated"
    assert hp.research_audit_record(_audit_payload("date_verified_with_unverifiable"), "ef", pin=PIN) == {
        "status": "date_verified_with_unverifiable", "sha256": "ef"}
    for payload, digest in ((_audit_payload(), ""), (_audit_payload(), None), (_audit_payload(status=None), "ab"),
                            (dict(_audit_payload(), status=["x"]), "ab"),
                            (dict(_audit_payload(), status={"a": 1}), "ab"),
                            ({"status": "date_verified"}, "ab"), (None, "ab")):
        assert hp.research_audit_record(payload, digest, pin=PIN) is None
    # The verdict is re-derived from the audit's own cited counts; a disagreeing or
    # malformed count vouches for nothing.
    nothing_cited = dict(_CITED["date_verified"], checked=0, admitted=0)
    for status, cited in (("date_verified", _CITED["violated"]), ("date_verified", nothing_cited),
                          ("date_verified_with_unverifiable", _CITED["date_verified"]),
                          ("violated", _CITED["date_verified_with_unverifiable"]),
                          ("date_verified", dict(_CITED["date_verified"], admitted=True)),
                          ("date_verified", dict(_CITED["date_verified"], admitted=-1, same_day=2)),
                          ("date_verified", {"checked": 1, "admitted": 1})):
        assert hp.research_audit_record(_audit_payload(status, cited=cited), "ab", pin=PIN) is None
    assert hp.research_audit_record(_audit_payload("date_verified_with_unverifiable", cited=nothing_cited),
                                    "ab", pin=PIN)["status"] == "date_verified_with_unverifiable"
    # The audit must be of this pin: its as-of and the policies the research was launched with.
    flagged = dict(PIN, pit=dict(GATED, undated="flag", same_day="include"))
    assert hp.research_audit_record(_audit_payload(), "ab", pin=flagged) is None
    # Under the flag policy undated pages may back the report: never plain date_verified.
    assert hp.research_audit_record(_audit_payload(undated_policy="flag", same_day_policy="include"), "ab",
                                    pin=flagged) is None
    assert hp.research_audit_record(
        _audit_payload("date_verified_with_unverifiable", cited=_CITED["date_verified"], undated_policy="flag",
                       same_day_policy="include"), "ab", pin=flagged) == {
        "status": "date_verified_with_unverifiable", "sha256": "ab"}
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


@pytest.mark.parametrize("audit", [None, {}, {"status": "clean"}, {"verdict": "clean"}, "violated",
                                   {"status": ["x"], "sha256": "ab"}, {"status": {}, "sha256": "ab"}])
def test_forecast_block_without_an_audit_stays_labelled(audit):
    assert hp.hindcast_forecast_block(PIN, research_audit=audit) == BLOCK


@pytest.mark.parametrize("pin", [UNGATED_PIN, dict(PIN, pit=None), dict(PIN, pit=dict(GATED, gates="true")),
                                 {key: value for key, value in PIN.items() if key != "pit"}])
@pytest.mark.parametrize("status", ["date_verified", "violated"])
def test_forecast_block_ignores_an_audit_on_an_ungated_pin(pin, status):
    """A hand-edited or migrated pin carrying an audit without gates: forecast.json and
    run.json agree that nothing was date-gated or verified."""
    audit = {"status": status, "sha256": "ab"}
    assert hp.hindcast_forecast_block(pin, research_audit=audit) == BLOCK
    assert hp.as_of_enforcement_record(dict(pin, research_audit=audit)) == ENFORCEMENT


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


# ───────────────────────────── the two processes' contract ───────────────────
def _child_engine():
    """The v3 child's ``linear_research``, imported as the v3 engine tests do (the parent
    and the child share no code, so this test pins their audit contract together)."""
    bridge_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                              "deerflow_bridge")
    if bridge_dir not in sys.path:
        sys.path.insert(0, bridge_dir)
    import linear_research

    return linear_research


_SOURCES = {
    "clean": [{"url": "https://a.example/x", "date": "2024-04-15"}],
    "undated": [{"url": "https://a.example/x", "date": "2024-04-15"}, {"url": "https://b.example/y"}],
    "same_day": [{"url": "https://a.example/x", "date": "2024-06-01"}],
    "late": [{"url": "https://a.example/2024/07/02/x", "date": "2024-04-15"}],
    "nothing": [],
}
_VERDICTS = {
    ("exclude", "drop"): {"clean": "date_verified", "undated": "date_verified_with_unverifiable",
                          "same_day": "violated", "late": "violated",
                          "nothing": "date_verified_with_unverifiable"},
    ("include", "flag"): {"clean": "date_verified_with_unverifiable",
                          "undated": "date_verified_with_unverifiable",
                          "same_day": "date_verified_with_unverifiable", "late": "violated",
                          "nothing": "date_verified_with_unverifiable"},
}


@pytest.mark.parametrize("same_day, undated", sorted(_VERDICTS))
def test_the_child_audit_is_what_the_parent_records(same_day, undated):
    """A real ``linear_research.point_in_time_payload``, written and read back as bytes, is
    recorded by ``research_audit_record`` with the child's own verdict, and maps to the
    matching forecast.json integrity and run.json attestation."""
    lr = _child_engine()
    assert (lr.POINT_IN_TIME_FILENAME, lr.POINT_IN_TIME_SCHEMA) == (hp.POINT_IN_TIME_FILENAME,
                                                                    hp.POINT_IN_TIME_SCHEMA)
    assert (lr.PIT_STATUS_VERIFIED, lr.PIT_STATUS_VERIFIED_UNVERIFIABLE, lr.PIT_STATUS_VIOLATED) == (
        hp.AUDIT_DATE_VERIFIED, hp.AUDIT_DATE_VERIFIED_WITH_UNVERIFIABLE, hp.AUDIT_VIOLATED)
    pin = dict(PIN, pit=dict(GATED, same_day=same_day, undated=undated))
    # The child's gates, parsed from the env the parent launches the research with.
    policy = lr._pit_policy({**hp.pit_research_env(pin["pit"]), "RESEARCH_AS_OF": pin["as_of"]})
    assert (policy.as_of, policy.same_day, policy.undated) == (dt.date(2024, 6, 1), same_day, undated)
    integrity = {"date_verified": "date_verified", "violated": "leak_suspected",
                 "date_verified_with_unverifiable": "date_verified_with_unverifiable"}
    for name, sources in _SOURCES.items():
        payload = lr.point_in_time_payload(policy, gate_counts={"fetch_admitted": 1}, sources=sources,
                                           suspects={"timeline": 0, "quant": 0}, wall={"sids_withheld": 0})
        status = _VERDICTS[(same_day, undated)][name]
        assert payload["status"] == status, name
        raw = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        digest = hashlib.sha256(raw).hexdigest()
        record = hp.research_audit_record(json.loads(raw.decode("utf-8")), digest, pin=pin)
        assert record == {"status": status, "sha256": digest}, name
        audited = dict(pin, research_audit=record)
        block = hp.hindcast_forecast_block(audited, research_audit=record)
        assert (block["retrieval"], block["integrity"]) == ("date_gated", integrity[status]), name
        assert hp.as_of_enforcement_record(audited) == dict(
            ENFORCEMENT, retrieval_clamped=status != "violated", audit_status=status), name
