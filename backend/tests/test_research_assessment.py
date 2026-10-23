"""Post-gather decisions reach real writers, QA, persisted actors and resume."""
import copy
import json

import pytest

from tests import test_research_engine_v3 as base
bridge = base.bridge
_hermetic_env = base._hermetic_env

lr = base.lr
assessment = lr.assessment
DECISIVE = "The grid regulator revoked the expansion permit and suspended all pending connections."


class RevisedWorld(base.World):
    def __call__(self, call):
        if call["messages"][-1][1].startswith("POST-GATHER ASSESSMENT TASK"):
            text = call["messages"][1][1]
            payload = json.JSONDecoder().raw_decode(text[text.index("{"):])[0]
            assert len(payload["evidence"]) == 1  # mirrored identical assertions are not corroboration
            return base.ai(json.dumps({"scenarios": [
                {"scenario_id": row["scenario_id"], "weight": weight,
                 "reason": "The revoked permit makes the stalled path more likely; the initial planning prior is revised.",
                 "evidence_ids": [payload["evidence"][0]["evidence_id"]]}
                for row, weight in zip(payload["initial"]["scenarios"], (15, 15, 70), strict=True)]}))
        return super().__call__(call)

    def notes(self, tool_results):
        notes = super().notes(tool_results)
        sid = next(int(m.group(1)) for result in tool_results
                   for m in [base.re.match(r"\[S(\d+)\].*(?:excerpt|full page)", result)] if m)
        return notes.replace("## Conflicts", f"- {DECISIVE} [S{sid}] (VERIFIED)\n## Conflicts")


def fetched_page(url):
    return base.page_text(url) + "\n" + DECISIVE


def assessment_calls(model):
    return [c for c in model.calls if c["messages"][-1][1].startswith("POST-GATHER ASSESSMENT TASK")]


def test_real_gather_revises_writer_qa_and_forecast_handoff_and_reuses(tmp_path, bridge):
    rc, meta, _, model, out = base.run_engine(tmp_path, bridge, RevisedWorld(), fetch=fetched_page)
    assert rc == 0, meta.get("error")
    record = json.loads((out / "v3/assessment.json").read_text())
    assert [r["weight"] for r in record["initial"]["scenarios"]] == [50, 30, 20]
    assert [r["weight"] for r in record["final"]["scenarios"]] == [15, 15, 70]
    assert len(assessment_calls(model)) == 1
    assert record["initial"]["definition_sha256"] == record["final"]["definition_sha256"]
    assert all(r["prior_reason"] and r["final_reason"] and r["evidence_ids"] for r in record["changes"])
    writers = [c for c in model.calls if c["messages"][-1][1].startswith("SECTION WRITING TASK")]
    assert writers and all("Base case — 15%" in c["messages"][1][1] for c in writers)
    assert all("POST-GATHER ASSESSMENT" in c["messages"][2][1] for c in writers)
    actors = json.loads((out / "actors.json").read_text())
    assert [r["probability"] for r in actors["forecast_inputs"]["scenarios"]] == [.15, .15, .70]
    assert actors["forecast_inputs"]["assessment"] == record
    assert json.loads((out / "research_assessment.json").read_text()) == record
    assert meta["research_assessment"]["file_sha256"] == base.hashlib.sha256(
        (out / "research_assessment.json").read_bytes()).hexdigest()
    report = (out / "research_report.md").read_text()
    assert [(r["name"], r["probability"]) for r in base.forecast_inputs_from_report_markdown(report)["scenarios"]] == [
        ("Base case", .15), ("Accelerated build-out", .15), ("Stalled expansion", .70)]
    second = base.run_engine(tmp_path, bridge, RevisedWorld(), out_dir=out, fetch=fetched_page)
    assert second[0] == 0, second[1].get("error")
    assert not assessment_calls(second[3])
    assert json.loads((out / "v3/assessment.json").read_text()) == record


@pytest.mark.parametrize("mutation", ["missing", "changed"])
def test_consumed_assessment_cannot_be_replaced(tmp_path, bridge, mutation):
    rc, meta, _, _, out = base.run_engine(tmp_path, bridge, RevisedWorld(), fetch=fetched_page)
    assert rc == 0, meta.get("error")
    path = out / "v3/assessment.json"
    if mutation == "missing":
        path.unlink()
    else:
        data = json.loads(path.read_text())
        data["final"]["scenarios"][0]["weight"] = 99
        path.write_text(json.dumps(data))
    result = base.run_engine(tmp_path, bridge, RevisedWorld(), out_dir=out, fetch=fetched_page)
    assert result[0] == 2 and "research_assessment_" in result[1]["error"]
    assert not assessment_calls(result[3])


def test_saved_unversioned_policy_never_acquires_new_assessment(tmp_path, bridge, monkeypatch):
    original = lr._RunState.fresh.__func__

    def legacy(cls, *args):
        state = original(cls, *args)
        state._data.pop("assessment_policy")
        state.save()
        return state

    with monkeypatch.context() as m:
        m.setattr(lr._RunState, "fresh", classmethod(legacy))
        first = base.run_engine(tmp_path, bridge, RevisedWorld(), fetch=fetched_page)
    assert first[0] == 0, first[1].get("error")
    second = base.run_engine(tmp_path, bridge, RevisedWorld(), out_dir=first[4], fetch=fetched_page)
    assert second[0] == 0, second[1].get("error")
    assert not assessment_calls(first[3]) and not assessment_calls(second[3])
    assert not (first[4] / "v3/assessment.json").exists()


@pytest.mark.parametrize("target", ["handoff", "policy", "source"])
def test_reuse_binds_handoff_policy_and_actual_sources(tmp_path, bridge, target):
    first = base.run_engine(tmp_path, bridge, RevisedWorld(), fetch=fetched_page)
    assert first[0] == 0, first[1].get("error")
    out = first[4]
    if target == "handoff":
        (out / "research_assessment.json").unlink()
    elif target == "policy":
        path = out / "v3/state.json"
        data = json.loads(path.read_text())
        data.pop("assessment_policy")
        path.write_text(json.dumps(data))
    else:
        path = out / "v3/assessment.json"
        record = json.loads(path.read_text())
        record["evidence"][0]["content_sha256"] = "0" * 64
        record["sha256"] = assessment.digest({k: v for k, v in record.items() if k != "sha256"})
        path.write_text(json.dumps(record))
    second = base.run_engine(tmp_path, bridge, RevisedWorld(), out_dir=out, fetch=fetched_page)
    assert second[0] == 2 and "research_assessment_" in second[1]["error"]
    assert not assessment_calls(second[3])


def test_assessment_write_failure_cannot_mint_another_model_attempt(tmp_path, bridge, monkeypatch):
    original = lr._Engine.write_json

    def fail(self, path, obj, **kwargs):
        if path.name == "assessment.json":
            raise OSError("scripted durable write failure")
        return original(self, path, obj, **kwargs)

    with monkeypatch.context() as m:
        m.setattr(lr._Engine, "write_json", fail)
        first = base.run_engine(tmp_path, bridge, RevisedWorld(), fetch=fetched_page)
    assert first[0] == 2 and len(assessment_calls(first[3])) == 1
    second = base.run_engine(tmp_path, bridge, RevisedWorld(), out_dir=first[4], fetch=fetched_page)
    assert second[0] == 2 and "research_assessment_missing" in second[1]["error"]
    assert not assessment_calls(second[3])


def test_published_record_before_completion_recovers_without_reassessment(tmp_path, bridge, monkeypatch):
    original = lr._RunState.set_phase

    def fail(self, name, status, detail=""):
        if name == "assess" and status == "done":
            raise OSError("scripted completion failure")
        return original(self, name, status, detail)

    with monkeypatch.context() as m:
        m.setattr(lr._RunState, "set_phase", fail)
        first = base.run_engine(tmp_path, bridge, RevisedWorld(), fetch=fetched_page)
    assert first[0] == 2 and len(assessment_calls(first[3])) == 1
    second = base.run_engine(tmp_path, bridge, RevisedWorld(), out_dir=first[4], fetch=fetched_page)
    assert second[0] == 0, second[1].get("error")
    assert not assessment_calls(second[3])


@pytest.mark.parametrize("error,reason", [
    (base.rg.ContentFiltered, "content_filtered"), (base.rg.BudgetExhausted, "budget_exhausted"),
    (base.rg.DeadlineExceeded, "deadline_exceeded"), (base.rg.ContextTooLong, "context_limit"),
    (base.rg.BadRequest, "request_rejected"), (base.rg.ProviderUnavailable, "provider_unavailable")])
def test_optional_gateway_failure_records_honest_stop_and_retains_prior(tmp_path, bridge, monkeypatch, error, reason):
    original = base.rg.ModelGateway.json
    calls = []

    def refuse(self, builder, **kwargs):
        if kwargs.get("label") == "assess:final":
            calls.append(kwargs["label"])
            raise error("scripted refusal")
        return original(self, builder, **kwargs)

    monkeypatch.setattr(base.rg.ModelGateway, "json", refuse)
    first = base.run_engine(tmp_path, bridge, RevisedWorld(), fetch=fetched_page)
    assert first[0] == 0, first[1].get("error")
    record = json.loads((first[4] / "research_assessment.json").read_text())
    assert record["stopping_reason"] == reason
    assert [row["weight"] for row in record["final"]["scenarios"]] == [50, 30, 20]
    second = base.run_engine(tmp_path, bridge, RevisedWorld(), out_dir=first[4], fetch=fetched_page)
    assert second[0] == 0, second[1].get("error")
    assert len(calls) == 1


def test_dated_qualitative_evidence_can_revise_actual_assessment(tmp_path, bridge, monkeypatch):
    monkeypatch.setitem(globals(), "DECISIVE", "On 2026-10-22, the grid regulator revoked the expansion permit.")
    result = base.run_engine(tmp_path, bridge, RevisedWorld(), fetch=fetched_page)
    assert result[0] == 0, result[1].get("error")
    record = json.loads((result[4] / "research_assessment.json").read_text())
    assert record["stopping_reason"] == "assessed"
    assert [row["weight"] for row in record["final"]["scenarios"]] == [15, 15, 70]


@pytest.mark.parametrize("change", ["identity", "definition", "unknown_source", "sum", "reason"])
def test_reassessment_rejects_changed_event_or_unbound_revision(change):
    plan = type("Plan", (), {"question": "Will it open?", "as_of": "2026-10-23", "horizon": "2027",
                             "scenarios": [lr.Scenario("Open", 50, "Opens"), lr.Scenario("Closed", 50, "Stays closed")]})()
    initial = assessment.initial_frame(plan)
    evidence = [{"evidence_id": "e1", "numeric_semantics": "not_numeric"}]
    candidate = {"scenarios": [{"scenario_id": r["scenario_id"], "weight": w,
                                "reason": "The revoked permit changes the initial assessment.", "evidence_ids": ["e1"]}
                               for r, w in zip(initial["scenarios"], (20, 80), strict=True)]}
    candidate = copy.deepcopy(candidate)
    row = candidate["scenarios"][0]
    if change == "identity":
        row["scenario_id"] = "other-event"
    elif change == "definition":
        row["definition"] = "Announced, not opened"
    elif change == "unknown_source":
        row["evidence_ids"] = ["e99"]
    elif change == "sum":
        row["weight"] = 30
    else:
        row["reason"] = ""
    with pytest.raises(ValueError):
        assessment.finish(initial, evidence, candidate)
