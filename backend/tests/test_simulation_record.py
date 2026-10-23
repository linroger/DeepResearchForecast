"""Simulation After-Action Record compiler (ADR 0003; design §3.1, §4; tests T5, T14, T15).

Fixtures: ``tests/fixtures/sim_record/reflexive3`` is the live reflexive-OASIS run
``sim_3ec25e64209e`` trimmed to its first three committed daily rounds; its
``world_actions.jsonl`` carries only the contract's public fields (``private_rationale``
was never copied).  ``tests/fixtures/sim_record/s2`` holds the dashboard slice's record
fixtures compiled from the same run.
"""
from __future__ import annotations

import ast
import builtins
import copy
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from app.config import Config
from app.services import sim_provenance as sp
from app.services import simulation_record as sr
from app.services import simulation_record_contract as rc
from app.services import simulation_record_gate as gate
from tests.conftest import FakeLLMClient

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "sim_record"
BACKEND = Path(__file__).resolve().parents[1]


def _copy_reflexive(tmp_path, name="sim_3ec25e64209e") -> str:
    target = tmp_path / name
    shutil.copytree(FIXTURES / "reflexive3", target)
    return str(target)


def _read_json(path):
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def _write_json(path, data):
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False)


def _rows(path):
    with open(path, "r", encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def _write_rows(path, rows):
    with open(path, "w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def _strip_generated_at(record):
    out = copy.deepcopy(record)
    out.pop("generated_at", None)
    return out


# ── the reflexive adapter on a live-derived run ─────────────────────────────────────────

def test_reflexive_record_is_valid_and_passes_the_gate(tmp_path):
    sim_dir = _copy_reflexive(tmp_path)
    record = sr.build_record(sim_dir, language="English", synthesis=False)
    assert rc.validate_shape(record) == []
    assert record["engine"] == "oasis-reflexive" and record["language"] == "en"
    assert record["rounds_committed"] == 3 and record["rounds_planned"] == 3
    assert record["banner"] == sp.SIM_BANNER_EN
    assert record["health"] == {"simulation_health": "ok", "validity": "valid", "arbiter_failed_rounds": 0,
                                "seed_gaps": 10, "organic_actions": 629}
    # one section per committed round, narrative verbatim, moves through the public allowlist only
    history = {r["round"]: r for r in _rows(os.path.join(sim_dir, "world_state_history.jsonl"))}
    for period in record["periods"]:
        assert period["narrative"] == history[period["round"]]["narrative"]
        assert "shares" not in period and "scenario_shares" not in period
        assert period["refs"][0]["file"] == "world_state_history.jsonl"
        for move in period["moves"]:
            assert set(move) <= {"actor", "option", "kind", "targets", "magnitude", "public_statement", "terms",
                                 "commitment", "ref"}
            assert move["ref"]["file"] == "world_actions.jsonl"
    assert any(p["facts_changed"] for p in record["periods"])
    fact = next(f for p in record["periods"] for f in p["facts_changed"])
    assert {"variable", "from", "to", "unit", "cause", "ref"} <= set(fact)
    # overall: shares only here, labelled; track records; fixed-rule turning points; limits
    shares = record["overall"]["shares"]
    assert shares["epistemic_status"] == rc.EPISTEMIC_STATUS and shares["paths"]["k"] == 1
    assert set(shares["final"]) == set(record["setup"]["scenarios"])
    assert record["overall"]["turning_points"] and len(record["overall"]["turning_points"]) <= sr.TURNING_POINT_CAP
    assert record["limits"]["behaviour_note"] == sr._LABELS["en"]["behaviour_note"]
    assert record["limits"]["arbiter_failed_rounds"] == 0 and len(record["limits"]["seed_gaps"]) == 10
    # entities: cast + aliases + variables + scenarios + period labels
    declared = set(record["entities_declared"])
    assert {"Government of Iran", "Zelensky", "Brent ICE futures", "Stalemate with fragile talks", "2026-10-23"} <= declared
    assert record["overall"]["synthesis"]["generator"] == "deterministic"
    assert record["limits"]["synthesis_dropped"] == "disabled by SIM_RECORD_SYNTHESIS"
    paths = sr.write_record(sim_dir, record)
    audit = gate.audit_record(sim_dir, record)
    assert audit["publication_status"] == "passed" and audit["hard_issues"] == [], audit["hard_issues"]
    assert rc.is_published(sim_dir)
    assert set(os.listdir(sim_dir)) >= {rc.RECORD_JSON, rc.RECORD_MD, rc.RECORD_MD_ZH, rc.RECORD_AUDIT_JSON}
    md = Path(paths["md"]).read_text(encoding="utf-8")
    zh = Path(paths["md_zh"]).read_text(encoding="utf-8")
    # outside the banner and the shares caption (both deny probability status), the word never appears
    body_en = md.replace(sp.SIM_BANNER_EN, "").replace(sr._LABELS["en"]["shares_caption"], "")
    body_zh = zh.replace(sp.SIM_BANNER_ZH, "").replace(sr._LABELS["zh"]["shares_caption"], "")
    assert sp.SIM_BANNER_EN in md and "### Arbiter narrative" in md and "probabilit" not in body_en.lower()
    assert sp.SIM_BANNER_ZH in zh and "### 仲裁叙事" in zh and "概率" not in body_zh
    assert f"| {sr._LABELS['en']['scenario']} | {sr._LABELS['en']['final_share']} |" in md
    # the narrative is quoted verbatim in both renderings; the Chinese rendering is not a translation
    assert history[1]["narrative"][:60] in md and history[1]["narrative"][:60] in zh


def test_private_rationale_is_excluded_by_allowlist_at_load(tmp_path):
    sim_dir = _copy_reflexive(tmp_path)
    path = os.path.join(sim_dir, "world_actions.jsonl")
    rows = _rows(path)
    secret = "SECRET-RATIONALE the minister privately expects the talks to collapse by Thursday"
    for row in rows:
        row["private_rationale"] = secret
    _write_rows(path, rows)
    art = sr._Artifacts(sim_dir)
    assert art.actions and all("private_rationale" not in row for row in art.actions)
    assert set().union(*(row.keys() for row in art.actions)) <= rc.ACTION_PUBLIC_FIELDS
    record = sr.build_record(sim_dir, language="en", synthesis=False)
    assert secret not in json.dumps(record, ensure_ascii=False)
    assert secret not in sr.render_markdown(record, "en") and secret not in sr.render_markdown(record, "zh")


# ── T5: health stubs and mechanical-only rounds ─────────────────────────────────────────

class _NeverCalled(FakeLLMClient):
    def chat(self, *args, **kwargs):  # noqa: D401
        raise AssertionError("the LLM must not be called for this run")


@pytest.mark.parametrize("health", sorted(rc.HEALTH_STUB_VALUES))
def test_unusable_health_yields_a_stub_with_zero_llm_calls(tmp_path, health):
    sim_dir = _copy_reflexive(tmp_path)
    summary_path = os.path.join(sim_dir, "run_summary.json")
    summary = _read_json(summary_path)
    summary["simulation_health"] = health
    _write_json(summary_path, summary)
    llm = _NeverCalled()
    record = sr.build_record(sim_dir, language="en", llm=llm, synthesis=True)
    assert llm.calls == []
    assert record["limits"]["stub"] is True and record["health"]["simulation_health"] == health
    assert rc.validate_shape(record) == []
    # committed-period stubs: one per committed round, no narrative, no moves, no shares
    assert [p["round"] for p in record["periods"]] == [1, 2, 3]
    for period in record["periods"]:
        assert period["stub"] is True and period["narrative"] == "" and period["moves"] == []
        assert period["facts_changed"] == [] and period["events"] == []
    assert record["overall"]["shares"] == {} and record["overall"]["turning_points"] == []
    synthesis = record["overall"]["synthesis"]
    assert synthesis["generator"] == "deterministic" and health in synthesis["text"]
    assert record["limits"]["synthesis_dropped"].startswith("health stub")
    md = sr.render_markdown(record, "en")
    assert sr._LABELS["en"]["stub_period"] in md and "### Arbiter narrative" not in md
    assert gate.audit_record(sim_dir, record, write=False)["publication_status"] == "passed"


def test_invalid_decision_channel_yields_a_stub(tmp_path):
    sim_dir = _copy_reflexive(tmp_path)
    path = os.path.join(sim_dir, "world_state_trajectory.json")
    trajectory = _read_json(path)
    trajectory["validity"] = "inconclusive"
    _write_json(path, trajectory)
    llm = _NeverCalled()
    record = sr.build_record(sim_dir, language="en", llm=llm)
    assert llm.calls == [] and record["limits"]["stub"] is True
    assert record["health"]["validity"] == "inconclusive"
    assert all(p["narrative"] == "" for p in record["periods"])
    assert gate.audit_record(sim_dir, record, write=False)["publication_status"] == "passed"


def test_validity_is_derived_from_round_accounting_when_not_explicit():
    assert sr.decision_channel_validity({}) == "unknown"
    assert sr.decision_channel_validity({"validity": "valid"}) == "valid"
    accounting = {"valid_transitions": 3, "failed_rounds": 0, "valid_coverage": 1.0}
    assert sr.decision_channel_validity({"outcome": {"round_accounting": accounting}}) == "valid"
    assert sr.decision_channel_validity({"outcome": {"round_accounting": dict(accounting, failed_rounds=1)}}) == "inconclusive"
    assert sr.decision_channel_validity({"outcome": {"round_accounting": dict(accounting, valid_transitions=0)}}) == "invalid"


def test_failed_arbiter_round_is_marked_mechanical_only(tmp_path):
    sim_dir = _copy_reflexive(tmp_path)
    path = os.path.join(sim_dir, "world_state_history.jsonl")
    rows = _rows(path)
    rows[1]["arbiter_status"] = "failed"
    rows[1]["arbiter_problems"] = ["llm error: BadRequestError"]
    _write_rows(path, rows)
    record = sr.build_record(sim_dir, language="en", synthesis=False)
    flags = [(p["round"], p["arbiter_status"], p["mechanical_only"]) for p in record["periods"]]
    assert flags == [(1, "applied", False), (2, "failed", True), (3, "applied", False)]
    assert record["limits"]["mechanical_only_rounds"] == [2]
    assert record["health"]["arbiter_failed_rounds"] == 1 == record["limits"]["arbiter_failed_rounds"]
    md = sr.render_markdown(record, "en")
    assert sr._LABELS["en"]["mechanical_only"] in md
    assert "llm error: BadRequestError" in md
    audit = gate.audit_record(sim_dir, record, write=False)
    assert audit["publication_status"] == "passed", audit["hard_issues"]


def test_llm_degraded_run_keeps_the_skeleton_without_a_synthesis_call(tmp_path):
    sim_dir = _copy_reflexive(tmp_path)
    summary_path = os.path.join(sim_dir, "run_summary.json")
    summary = _read_json(summary_path)
    summary["simulation_health"] = "llm_degraded"
    _write_json(summary_path, summary)
    llm = _NeverCalled()
    record = sr.build_record(sim_dir, language="en", llm=llm, synthesis=True)
    assert llm.calls == [] and record["limits"]["stub"] is False
    assert record["periods"][0]["narrative"]  # the skeleton is complete
    assert record["overall"]["synthesis"]["generator"] == "deterministic"
    assert record["limits"]["synthesis_dropped"].startswith("llm_degraded")


# ── T14: determinism and synthesis fallback ─────────────────────────────────────────────

def test_same_artifacts_give_byte_identical_json_except_generated_at(tmp_path):
    a = _copy_reflexive(tmp_path / "a")
    b = _copy_reflexive(tmp_path / "b")
    ra = sr.build_record(a, language="en", synthesis=False)
    rb = sr.build_record(b, language="en", synthesis=False)
    assert _strip_generated_at(ra) == _strip_generated_at(rb)
    assert sr.render_markdown(ra, "en") == sr.render_markdown(rb, "en")
    assert sr.render_markdown(ra, "zh") == sr.render_markdown(rb, "zh")
    sr.write_record(a, ra)
    sr.write_record(b, rb)
    json_a = Path(a, rc.RECORD_JSON).read_bytes().replace(ra["generated_at"].encode(), b"T")
    json_b = Path(b, rc.RECORD_JSON).read_bytes().replace(rb["generated_at"].encode(), b"T")
    assert json_a == json_b
    assert Path(a, rc.RECORD_MD).read_bytes() == Path(b, rc.RECORD_MD).read_bytes()
    # the audit's sha256 is the sha256 of the written file
    import hashlib
    audit = gate.audit_record(a, ra)
    assert audit["sha256"] == hashlib.sha256(Path(a, rc.RECORD_JSON).read_bytes()).hexdigest()


def test_synthesis_failure_falls_back_to_the_skeleton_with_a_reason(tmp_path):
    sim_dir = _copy_reflexive(tmp_path)

    class Boom(FakeLLMClient):
        def chat(self, *args, **kwargs):
            self.calls.append({"kind": "chat"})
            raise RuntimeError("provider 1301")

    llm = Boom()
    record = sr.build_record(sim_dir, language="en", llm=llm, synthesis=True)
    assert len(llm.calls) == 1
    assert record["overall"]["synthesis"]["generator"] == "deterministic"
    assert record["overall"]["synthesis"]["text"]
    assert record["limits"]["synthesis_dropped"].startswith("llm error: RuntimeError")
    assert rc.validate_shape(record) == []
    assert gate.audit_record(sim_dir, record, write=False)["publication_status"] == "passed"


def test_synthesis_is_dropped_when_it_adds_a_gate_issue_and_kept_when_clean(tmp_path):
    sim_dir = _copy_reflexive(tmp_path)
    # a number that traces to no artifact row (G2) → dropped, skeleton kept, reason recorded
    invented = FakeLLMClient(responses=["Talks stalled on sequencing and output rose 37.5% (2026-10-23).\n\n"
                                        "Nothing lapsed (2026-10-25)."])
    record = sr.build_record(sim_dir, language="en", llm=invented, synthesis=True)
    assert record["overall"]["synthesis"]["generator"] == "deterministic"
    assert record["limits"]["synthesis_dropped"].startswith("gate: G2")
    # no period label → cannot be grounded → dropped
    unlabelled = FakeLLMClient(responses=["Talks stalled on sequencing."])
    record = sr.build_record(sim_dir, language="en", llm=unlabelled, synthesis=True)
    assert record["limits"]["synthesis_dropped"] == "paragraph 1 names no period label"
    # the synthesis sees the deterministic skeleton and nothing else: the user turn is the
    # instruction plus _skeleton_for_prompt(record), the rules forbid markers and probability words
    messages = unlabelled.calls[0]["messages"]
    assert [m["role"] for m in messages] == ["system", "user"]
    assert "[S1]" in messages[0]["content"] and "probability" in messages[0]["content"]
    skeleton = sr._skeleton_for_prompt(record)
    assert skeleton in messages[1]["content"] and "2026-10-23" in skeleton
    assert "private_rationale" not in skeleton and set(json.loads(skeleton)) == {
        "periods", "final_variables", "shares", "turning_points", "track_records"}
    assert unlabelled.calls[0]["temperature"] == 0.2
    # a clean synthesis is kept, labelled llm, with one claim per paragraph
    clean = FakeLLMClient(responses=["All parties confirmed attendance at the talks while the gaps widened "
                                     "(2026-10-23; 2026-10-24).\n\nNo offer lapsed and no red line was crossed "
                                     "(2026-10-25)."])
    record = sr.build_record(sim_dir, language="en", llm=clean, synthesis=True)
    assert record["overall"]["synthesis"]["generator"] == "llm"
    assert record["limits"]["synthesis_dropped"] is None
    assert [c["paragraph"] for c in record["overall"]["synthesis"]["claims"]] == [0, 1]
    assert len(record["overall"]["synthesis"]["claims"][0]["refs"]) == 2
    sr.write_record(sim_dir, record)
    audit = gate.audit_record(sim_dir, record)
    assert audit["publication_status"] == "passed", audit["hard_issues"]


def test_synthesis_is_disabled_by_config(tmp_path, monkeypatch):
    sim_dir = _copy_reflexive(tmp_path)
    monkeypatch.setattr(Config, "SIM_RECORD_SYNTHESIS", False)
    llm = _NeverCalled()
    record = sr.build_record(sim_dir, language="en", llm=llm)
    assert llm.calls == [] and record["limits"]["synthesis_dropped"] == "disabled by SIM_RECORD_SYNTHESIS"


# ── T15: input contract ─────────────────────────────────────────────────────────────────

FORBIDDEN_IMPORTS = ("report_agent", "forecast_extractor", "zep_tools", "exec_brief", "report_visualizer",
                     "deep_research", "research_", "news_market_context", "official_data", "prediction_market",
                     "market_", "dossier")


def _imports_of(path: Path):
    tree = ast.parse(path.read_text(encoding="utf-8"), str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield alias.name
        elif isinstance(node, ast.ImportFrom):
            yield node.module or ""
            for alias in node.names:
                yield f"{node.module or ''}.{alias.name}"


def test_compiler_imports_nothing_from_the_report_or_research_planes(tmp_path):
    names = list(_imports_of(BACKEND / "app" / "services" / "simulation_record.py"))
    assert names
    for name in names:
        assert not any(bad in name for bad in FORBIDDEN_IMPORTS), name
    # the gate may use the lint's language scan (G9) but nothing else from those planes
    gate_names = [n for n in _imports_of(BACKEND / "app" / "services" / "simulation_record_gate.py")
                  if "report_lint" not in n]
    for name in gate_names:
        assert not any(bad in name for bad in FORBIDDEN_IMPORTS), name
    # a fresh interpreter: importing the compiler loads none of those modules
    code = ("import sys\n"
            "sys.path.insert(0, %r)\n" % str(BACKEND) +
            "import app.services.simulation_record, app.services.simulation_record_gate\n"
            "bad = sorted(m for m in sys.modules if m.startswith('app.') and any(k in m for k in %r))\n"
            "print('|'.join(bad))" % (FORBIDDEN_IMPORTS,))
    env = dict(os.environ, DRF_TEST_PROCESS="1")
    script = tmp_path / "record_import_probe.py"
    script.write_text(code, encoding="utf-8")
    guard = sys.modules.get("main_offline_guard")
    if guard is not None:
        guard.allow_python_script(script)
    out = subprocess.run([sys.executable, str(script)], cwd=str(tmp_path), env=env,
                         capture_output=True, text=True, timeout=120)
    assert out.returncode == 0, out.stderr[-2000:]
    assert out.stdout.strip() == "", out.stdout


def test_compiler_opens_no_file_outside_the_simulation_directory(tmp_path, monkeypatch):
    sim_dir = _copy_reflexive(tmp_path)
    # a decoy next to the simulation directory must never be opened
    (tmp_path / "sources.json").write_text("{}", encoding="utf-8")
    (tmp_path / "forecast.json").write_text("{}", encoding="utf-8")
    opened = []
    real_open = builtins.open

    def spy(file, *args, **kwargs):
        if isinstance(file, (str, bytes, os.PathLike)):
            opened.append(os.path.realpath(os.fspath(file)))
        return real_open(file, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", spy)
    record = sr.build_record(sim_dir, language="en", synthesis=False)
    sr.write_record(sim_dir, record)
    gate.audit_record(sim_dir, record)
    root = os.path.realpath(sim_dir)
    assert opened, "nothing was opened"
    outside = [p for p in opened if os.path.commonpath([p, root]) != root]
    assert outside == [], outside
    basenames = {os.path.basename(p) for p in opened}
    assert basenames <= {"world_state.json", "world_state_history.jsonl", "world_digest.jsonl", "world_actions.jsonl",
                         "decisions.jsonl", "world_state_trajectory.json", "world_paths.json", "run_summary.json",
                         "simulation_config.json", "simulation_config_manifest.json", "state.json",
                         "actor_cast_manifest.json", "world_result.json", "world_spec.json",
                         rc.RECORD_JSON, rc.RECORD_MD, rc.RECORD_MD_ZH, rc.RECORD_AUDIT_JSON} | {
        n for n in basenames if ".tmp-" in n}


def test_artifact_reader_refuses_symlinks_and_escapes(tmp_path):
    sim_dir = _copy_reflexive(tmp_path)
    outside = tmp_path / "outside.json"
    outside.write_text(json.dumps({"simulation_health": "hollow"}), encoding="utf-8")
    os.unlink(os.path.join(sim_dir, "run_summary.json"))
    os.symlink(outside, os.path.join(sim_dir, "run_summary.json"))
    art = sr._Artifacts(sim_dir)
    assert art.run_summary == {}            # the symlink is refused, so the run is "unknown", not hollow
    assert art.path("../outside.json") is None
    with pytest.raises(sr.RecordBuildError):
        sr._Artifacts(str(tmp_path / "missing"))


# ── engine adapters ─────────────────────────────────────────────────────────────────────

def _write_world_v1(sim_dir: Path) -> None:
    sim_dir.mkdir(parents=True, exist_ok=True)
    spec = {"schemaVersion": "simulation-world-spec/v1", "engine": "world-v1", "simulationId": "sim_w1",
            "periods": [{"start": "2030-01-01T00:00:00Z", "end": "2030-01-02T00:00:00Z"},
                        {"start": "2030-01-02T00:00:00Z", "end": "2030-01-03T00:00:00Z"}],
            "actors": [{"actorId": "producer", "name": "Producer"}, {"actorId": "buyer", "name": "Buyer"}]}
    metric = lambda v: {"value": v, "unit": "goods_per_day", "visibility": {"kind": "public"}}  # noqa: E731
    result = {"schemaVersion": "world-result/v1", "engine": "world-v1", "simulationId": "sim_w1", "completed": True,
              "committedRound": 2, "totalRounds": 2, "asOf": "2030-01-01T00:00:00Z", "horizon": "2030-01-03T00:00:00Z",
              "forecastEffect": "diagnostic_only", "view": "public", "round": 2,
              "world": {"metrics": {"capacity": metric("7")}, "rules": {"permit": {"value": True}},
                        "interactions": {"i1": {"proposerId": "buyer", "recipientIds": ["producer"], "templateId": "purchase",
                                                "status": "accepted", "createdRound": 1, "terms": {"quantity": "2", "price": "5"}}},
                        "commitments": {"c1": {"actorId": "producer", "kind": "delivery", "status": "fulfilled",
                                               "createdAt": "2030-01-02T00:00:00Z"}}},
              "trajectory": [{"round": 0, "simulatedAt": "2030-01-01T00:00:00Z", "metrics": {"capacity": metric("4")}, "rules": {"permit": {"value": True}}},
                             {"round": 1, "simulatedAt": "2030-01-02T00:00:00Z", "metrics": {"capacity": metric("4")}, "rules": {"permit": {"value": True}}},
                             {"round": 2, "simulatedAt": "2030-01-03T00:00:00Z", "metrics": {"capacity": metric("7")}, "rules": {"permit": {"value": True}}}],
              "events": [{"round": 1, "eventId": "e1", "kind": "offer", "actorId": "buyer", "description": "Buyer offered a purchase",
                          "details": {"quantity": "2"}},
                         {"round": 2, "eventId": "e2", "kind": "investment", "actorId": "producer", "description": "Capacity expanded",
                          "details": {"delta": "3"}}]}
    _write_json(sim_dir / "world_spec.json", spec)
    for snapshot in [result["world"], *result["trajectory"]]:
        for bucket in ("rules", "interactions", "commitments"):
            for row in snapshot.get(bucket, {}).values():
                row["visibility"] = {"kind": "public"}
    for event in result["events"]:
        event["visibility"] = {"kind": "public"}
    for row in result["trajectory"][1:]:
        row["interactions"] = json.loads(json.dumps(result["world"]["interactions"]))
        row["commitments"] = json.loads(json.dumps(result["world"]["commitments"]))
    _write_json(sim_dir / "world_result.json", result)
    _write_json(sim_dir / "state.json", {"simulation_id": "sim_w1", "simulation_engine": "world-v1"})
    _write_json(sim_dir / "run_summary.json", {"simulation_id": "sim_w1", "simulation_health": "ok"})


def test_world_v1_adapter_builds_tables_and_states_that_no_narrative_exists(tmp_path):
    sim_dir = tmp_path / "sim_w1"
    _write_world_v1(sim_dir)
    llm = _NeverCalled()
    record = sr.build_record(str(sim_dir), language="en", llm=llm, synthesis=True)
    assert llm.calls == []                      # no arbiter narrative to synthesise from
    assert record["engine"] == "world-v1" and rc.validate_shape(record) == []
    assert record["rounds_committed"] == 2 and record["health"]["validity"] == "valid"
    assert [p["label"] for p in record["periods"]] == ["2030-01-02", "2030-01-03"]
    assert all(p["narrative"] == "" and p["arbiter_status"] == "not_applicable" for p in record["periods"])
    assert sr._LABELS["en"]["world_v1_no_narrative"] in record["limits"]["notes"]
    assert record["periods"][1]["facts_changed"] == [{"variable": "capacity", "from": "4", "to": "7", "unit": "goods_per_day",
                                                      "cause": "kernel", "ref": {"file": "world_result.json", "round": 2, "id": "metrics:capacity"}}]
    assert record["periods"][0]["offers"][0]["from_actor"] == "Buyer" and record["periods"][0]["offers"][0]["to_actor"] == "Producer"
    assert record["overall"]["track_records"] == [{"actor": "Producer", "kept": 1, "lapsed": 0, "broken": 0, "released": 0, "open": 0, "resolved": 1}]
    assert record["overall"]["shares"] == {} and {"Producer", "Buyer", "capacity"} <= set(record["entities_declared"])
    md = sr.render_markdown(record, "en")
    assert sr._LABELS["en"]["world_v1_no_narrative"] in md and "### Arbiter narrative" not in md
    audit = gate.audit_record(str(sim_dir), record)
    assert audit["publication_status"] == "passed", audit["hard_issues"]


def test_thin_adapter_states_that_no_world_model_ran(tmp_path):
    # legacy in-band calendar mode: the decision channel ran (trajectory), no world model (no history)
    sim_dir = tmp_path / "sim_thin"
    sim_dir.mkdir()
    for name in ("world_digest.jsonl", "world_state_trajectory.json", "run_summary.json",
                 "simulation_config.json", "state.json"):
        shutil.copy(FIXTURES / "reflexive3" / name, sim_dir / name)
    llm = _NeverCalled()
    record = sr.build_record(str(sim_dir), language="en", llm=llm, synthesis=True)
    assert llm.calls == [] and record["engine"] == "oasis-inband"
    assert rc.validate_shape(record) == [] and record["rounds_committed"] == 3
    assert record["limits"]["stub"] is False and record["health"]["validity"] == "valid"
    assert record["limits"]["notes"] == [sr._LABELS["en"]["no_world_model"].format(engine="oasis-inband")]
    assert record["limits"]["synthesis_dropped"] == "engine oasis-inband has no arbiter narrative to synthesise"
    for period in record["periods"]:
        assert period["narrative"] == "" and period["events"][0]["kind"] == "digest"
        assert period["refs"][0]["file"] == "world_digest.jsonl"
    assert record["setup"]["cast"]                      # top agents from run_summary
    assert record["overall"]["shares"]["final"] and record["overall"]["final_variables"] == []
    assert sr._LABELS["en"]["no_world_model"].format(engine="oasis-inband") in sr.render_markdown(record, "en")
    audit = gate.audit_record(str(sim_dir), record)
    assert audit["publication_status"] == "passed", audit["hard_issues"]
    # without a decision channel the validity is unknown: committed-period stubs, nothing padded
    no_channel = tmp_path / "sim_nochannel"
    no_channel.mkdir()
    for name in ("world_digest.jsonl", "run_summary.json", "simulation_config.json"):
        shutil.copy(FIXTURES / "reflexive3" / name, no_channel / name)
    record = sr.build_record(str(no_channel), language="en", llm=llm, synthesis=True)
    assert llm.calls == [] and record["limits"]["stub"] is True and record["health"]["validity"] == "unknown"
    assert [p["round"] for p in record["periods"]] == [1, 2, 3] and all(p["events"] == [] for p in record["periods"])
    assert gate.audit_record(str(no_channel), record, write=False)["publication_status"] == "passed"
    # hours mode (no temporal config, no digest) is the other thin engine
    hours = tmp_path / "sim_hours"
    hours.mkdir()
    shutil.copy(FIXTURES / "reflexive3" / "run_summary.json", hours / "run_summary.json")
    record = sr.build_record(str(hours), language="en", synthesis=False)
    assert record["engine"] == "oasis-hours" and record["periods"] == [] and rc.validate_shape(record) == []


def test_engine_hint_and_language_resolution(tmp_path):
    sim_dir = _copy_reflexive(tmp_path)
    art = sr._Artifacts(sim_dir)
    assert sr.resolve_engine(art, None) == "oasis-reflexive"
    assert sr.resolve_engine(art, "oasis-inband") == "oasis-inband"
    assert sr.resolve_language(art, None) == "en"             # the sealed config says English
    assert sr.resolve_language(art, "中文") == "zh" and sr.resolve_language(art, "Chinese") == "zh"
    assert sr.resolve_language(art, "English") == "en"
    record = sr.build_record(sim_dir, language="zh", synthesis=False)
    assert record["language"] == "zh" and record["banner"] == sp.SIM_BANNER_ZH
    assert record["limits"]["behaviour_note"] == sr._LABELS["zh"]["behaviour_note"]
    paths = sr.write_record(sim_dir, record)
    assert Path(paths["md"]).read_bytes() == Path(paths["md_zh"]).read_bytes()


# ── the dashboard slice's fixtures ──────────────────────────────────────────────────────

@pytest.mark.parametrize("name", ["en", "zh", "hollow", "paths"])
def test_s2_fixture_records_satisfy_the_shape_contract(name):
    record = _read_json(FIXTURES / "s2" / f"simulation_record.{name}.json")
    assert rc.validate_shape(record) == []
    assert "private_rationale" not in json.dumps(record)


def test_illustrative_s2_fixture_is_not_a_faithful_compilation(tmp_path):
    """The hand-authored dashboard example is not a publishable source projection."""
    sim_dir = _copy_reflexive(tmp_path)
    record = _read_json(FIXTURES / "s2" / "simulation_record.en.json")
    audit = gate.audit_record(sim_dir, record, write=False)
    assert audit["publication_status"] == "failed"
    assert any("differs from the artifact projection" in h for h in audit["hard_issues"])
    # the Chinese twin replaces the arbiter narratives with short Chinese ones, so it is a
    # shape fixture for the Chinese interface, not a record of this run: the gate says so
    zh = _read_json(FIXTURES / "s2" / "simulation_record.zh.json")
    zh_audit = gate.audit_record(sim_dir, zh, write=False)
    assert zh_audit["publication_status"] == "failed"
    assert any(h.startswith("G4") and "narrative" in h for h in zh_audit["hard_issues"])


# ── orchestrator wiring (S1.3, S1.4) ────────────────────────────────────────────────────

def _orchestrator_env(monkeypatch, tmp_path):
    from app.services import pipeline_orchestrator as po
    run_root = tmp_path / "run-state"
    run_root.mkdir()
    monkeypatch.setattr(po.SimulationRunner, "RUN_STATE_DIR", str(run_root), raising=False)
    monkeypatch.setattr(po.PipelineManager, "save", classmethod(lambda cls, state: None))
    manifest = {}
    monkeypatch.setattr(po.PipelineManager, "load_artifact_manifest", classmethod(lambda cls, pid: dict(manifest)))
    monkeypatch.setattr(po.PipelineManager, "write_artifact_manifest",
                        classmethod(lambda cls, pid, value: manifest.update(value)))
    return po, run_root, manifest


def test_orchestrator_publishes_the_record_after_run_summary(monkeypatch, tmp_path):
    po, run_root, manifest = _orchestrator_env(monkeypatch, tmp_path)
    sim_dir = _copy_reflexive(run_root, "sim_rec")
    state = po.PipelineState(pipeline_id="pipe_rec", prompt="q", mode="full", status="running")
    state.simulation_id = "sim_rec"
    state.options["research_language"] = "English"
    monkeypatch.setattr(Config, "SIM_RECORD_SYNTHESIS", False)
    assert po.PipelineOrchestrator()._publish_simulation_record(state, "sim_rec", regenerate=True) is True
    record_path = os.path.join(sim_dir, rc.RECORD_JSON)
    assert state.artifacts["simulation_record"] == record_path
    assert manifest["simulation_record"]["path"] == record_path and manifest["simulation_record"]["schema_ok"]
    assert rc.is_published(sim_dir)
    before = Path(record_path).read_bytes()
    # a reused run keeps its audited bytes
    assert po.PipelineOrchestrator()._publish_simulation_record(state, "sim_rec", regenerate=False) is True
    assert Path(record_path).read_bytes() == before
    # regenerate rewrites (generated_at moves); the audit follows
    assert po.PipelineOrchestrator()._publish_simulation_record(state, "sim_rec", regenerate=True) is True
    assert rc.is_published(sim_dir)
    # the run_summary path publishes the record too (S1.3: both call paths)
    state2 = po.PipelineState(pipeline_id="pipe_rec2", prompt="q", mode="full", status="running")
    state2.simulation_id = "sim_rec"
    monkeypatch.setattr(po.SimulationRunner, "write_run_summary",
                        classmethod(lambda cls, *args, **kwargs: None))
    assert po.PipelineOrchestrator()._publish_run_summary(state2, "sim_rec", communities=None, regenerate=False) is True
    assert state2.artifacts["run_summary"].endswith("run_summary.json")
    assert state2.artifacts["simulation_record"] == record_path


def test_orchestrator_record_degrades_safely(monkeypatch, tmp_path):
    po, run_root, manifest = _orchestrator_env(monkeypatch, tmp_path)
    sim_dir = _copy_reflexive(run_root, "sim_rec")
    state = po.PipelineState(pipeline_id="pipe_rec", prompt="q", mode="full", status="running")
    state.simulation_id = "sim_rec"
    # disabled → nothing written, nothing registered
    monkeypatch.setattr(Config, "SIM_RECORD_ENABLED", False)
    assert po.PipelineOrchestrator()._publish_simulation_record(state, "sim_rec", regenerate=True) is False
    assert not os.path.exists(os.path.join(sim_dir, rc.RECORD_JSON)) and "simulation_record" not in state.artifacts
    monkeypatch.setattr(Config, "SIM_RECORD_ENABLED", True)
    # a compiler crash is logged and swallowed; the stage goes on
    import app.services.simulation_record as compiler

    def boom(*args, **kwargs):
        raise RuntimeError("boom")

    with pytest.MonkeyPatch.context() as crash:
        crash.setattr(compiler, "build_record", boom)
        assert po.PipelineOrchestrator()._publish_simulation_record(state, "sim_rec", regenerate=True) is False
    assert "simulation_record" not in state.artifacts
    # a missing simulation directory likewise
    assert po.PipelineOrchestrator()._publish_simulation_record(state, "sim_missing", regenerate=True) is False
    # the seed path registers nothing but still writes the files
    seed_dir = _copy_reflexive(run_root, "sim_seed")
    monkeypatch.setattr(Config, "SIM_RECORD_SYNTHESIS", False)
    seed_state = po.PipelineState(pipeline_id="pipe_seed", prompt="q", mode="full", status="running")
    assert po.PipelineOrchestrator()._publish_simulation_record(seed_state, "sim_seed", regenerate=True, register=False) is True
    assert os.path.exists(os.path.join(seed_dir, rc.RECORD_AUDIT_JSON)) and "simulation_record" not in seed_state.artifacts


def test_stage_run_specs_register_the_record_beside_run_summary(monkeypatch, tmp_path):
    from app.services import pipeline_orchestrator as po
    monkeypatch.setattr(po.SimulationRunner, "RUN_STATE_DIR", str(tmp_path), raising=False)
    state = po.PipelineState(pipeline_id="pipe_specs", prompt="q", mode="full", status="running")
    state.simulation_id = "sim_specs"
    names = [name for name, _ in po.PipelineOrchestrator._stage_artifact_specs(state, po.STAGE_RUN)]
    assert names == ["run_summary", "simulation_record"]
    paths = dict(po.PipelineOrchestrator._stage_artifact_specs(state, po.STAGE_RUN))
    assert paths["simulation_record"] == os.path.join(str(tmp_path), "sim_specs", rc.RECORD_JSON)
    # world-v1 keeps its strict spec set (every spec there is a required artifact); the optional
    # record is registered for it by _publish_simulation_record instead
    state.options["simulation_engine"] = "world-v1"
    assert [name for name, _ in po.PipelineOrchestrator._stage_artifact_specs(state, po.STAGE_RUN)] == [
        "world_result", "world_result_manifest"]


def test_run_rotation_list_carries_the_record_files():
    from app.services.simulation_runner import SimulationRunner
    stale = set(SimulationRunner._STALE_DERIVED_ARTIFACTS)
    assert {rc.RECORD_JSON, rc.RECORD_MD, rc.RECORD_MD_ZH, rc.RECORD_AUDIT_JSON} <= stale
    assert "world_state_history.jsonl" in stale


def test_config_defaults_and_env_example_document_the_record_knobs():
    assert Config.SIM_RECORD_ENABLED is True and Config.SIM_RECORD_SYNTHESIS is True
    env_example = (BACKEND.parent / ".env.example").read_text(encoding="utf-8")
    assert "# SIM_RECORD_ENABLED=true" in env_example and "# SIM_RECORD_SYNTHESIS=true" in env_example


def test_source_module_docstrings_and_labels_carry_no_literal_banner_copies():
    """The banner and bridge strings have one source (T9); the record modules must import them."""
    for name in ("simulation_record.py", "simulation_record_gate.py"):
        src = (BACKEND / "app" / "services" / name).read_text(encoding="utf-8")
        assert sp.SIM_BANNER_EN not in src and sp.SIM_BANNER_ZH not in src, name
        assert sp.BRIDGE_TITLE_EN not in src and sp.CHART_OUTCOME_SHARES_EN not in src, name
