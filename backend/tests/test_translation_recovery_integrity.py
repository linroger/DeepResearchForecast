"""Regression cases from independent review of the durable translation core."""
import json

import pytest

from app.config import Config
from app.services import model_translation as model
from app.services.translation.contracts import canonical
from app.services.translation.engine import MAX_INPUT_TOKENS, _estimate
from app.services.translation.store import Store, database_path
from tests.test_translation_job_v2 import Model, IDENTITY, PAIRS


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(Config, "UPLOAD_FOLDER", str(tmp_path / "uploads"))


class Transform(Model):
    def __init__(self, transform):
        super().__init__()
        self.transform = transform

    def chat(self, messages, **kwargs):
        payload = json.loads(messages[-1]["content"])
        if "entries" in payload:
            self.calls.append(payload)
            return json.dumps({"translations": {key: self.transform(text) for key, text in payload["entries"].items()}})
        return super().chat(messages, **kwargs)


def test_cross_section_reference_failure_is_repairable_and_never_complete():
    source = "## Outlook\n\nSee [policy][p].\n\n## References\n\n[p]: https://example.test/policy\n"
    bad = Transform(lambda text: text.replace("Outlook", "展望").replace("References", "参考来源").replace("See [policy][p].", "参见政策。"))
    target, proof = model.translate_document(bad, source, "zh", identity=IDENTITY)
    assert not proof["complete"] and not model.valid_document_receipt(source, target, "zh", proof)
    assert "[policy][p]" in target  # An unreviewed broken candidate is never shown.
    good = Transform(lambda text: text.replace("Outlook", "展望").replace("References", "参考来源").replace("See ", "参见 "))
    target, repaired = model.translate_document(good, source, "zh", identity=IDENTITY)
    assert repaired["complete"] and model.valid_document_receipt(source, target, "zh", repaired)
    assert list(good.calls[0]["entries"]) == ["section:0"]


@pytest.mark.parametrize("definition", ["[p]: https://example.test/policy", "[^p]: Value remains unchanged."])
def test_document_context_cannot_hide_removed_local_definition(definition):
    source = "## References\n\n" + definition
    _, state = model._parse(source)
    context = {key: state.env[key] for key in ("ref_links", "ref_footnotes") if state.env.get(key)}
    assert model.structure_issues(source, "## 参考来源", context)


def test_citation_at_start_is_not_a_new_reference_definition():
    assert not model.structure_issues("Source [S1].", "[S1]来源。")


@pytest.mark.parametrize("change", ["resource", "visibility"])
def test_seed_from_other_scope_is_not_admitted(change):
    private = {**IDENTITY, "scope": {"view": "actor", "actor_id": "one"}}
    first = model.translate_entries(Model(), PAIRS, "zh", identity=private)
    seed = {key: {"source": source, "target": first[key], "receipt": first.receipts[key]} for key, source in PAIRS}
    other = {**private, "ref_id": "other"} if change == "resource" else IDENTITY
    transport = Model()
    result = model.translate_entries(transport, PAIRS, "zh", identity=other, seed=seed)
    assert len(transport.calls) == 2 and result.job["coverage"]["reused"] == 0


class Interrupted(BaseException):
    pass


@pytest.mark.parametrize("stage", ["validate", "review_returned"])
def test_entire_returned_batch_survives_interruption(monkeypatch, stage):
    checkpoint = Store.checkpoint

    def interrupt(store, job_id, fence, units, **kwargs):
        checkpoint(store, job_id, fence, units, **kwargs)
        if any(unit["stage"] == stage for unit in units.values()):
            raise Interrupted()

    monkeypatch.setattr(Store, "checkpoint", interrupt)
    with pytest.raises(Interrupted):
        model.translate_entries(Model(), PAIRS, "zh", identity=IDENTITY)
    monkeypatch.setattr(Store, "checkpoint", checkpoint)
    transport = Model()
    result = model.translate_entries(transport, PAIRS, "zh", identity=IDENTITY)
    assert len(result) == 2
    assert not any("entries" in call for call in transport.calls)
    assert len(transport.calls) == (1 if stage == "validate" else 0)


def test_crash_does_not_grant_extra_content_repair(monkeypatch):
    checkpoint = Store.checkpoint

    def interrupt(store, job_id, fence, units, **kwargs):
        checkpoint(store, job_id, fence, units, **kwargs)
        if any(unit["stage"] == "validate" for unit in units.values()):
            raise Interrupted()

    first = Transform(lambda text: "错误。")
    monkeypatch.setattr(Store, "checkpoint", interrupt)
    with pytest.raises(Interrupted):
        model.translate_entries(first, [("a", "Value remains unchanged. [S1]")], "zh", identity=IDENTITY)
    monkeypatch.setattr(Store, "checkpoint", checkpoint)
    second = Transform(lambda text: "错误。")
    result = model.translate_entries(second, [("a", "Value remains unchanged. [S1]")], "zh", identity=IDENTITY)
    assert not result and len(first.calls) + len(second.calls) == 2
    assert second.calls[0]["repair"] is True and second.calls[0]["structure_feedback"]


def test_remote_timeout_keeps_unknown_outcome_and_consumed_budget():
    class Timeout(Model):
        def chat(self, **kwargs):
            raise TimeoutError("never-persist-this")
    result = model.translate_entries(Timeout(), PAIRS, "zh", identity=IDENTITY)
    with Store(database_path()) as store:
        attempt = store.db.execute("SELECT * FROM attempts WHERE job_id=?", (result.job["job_id"],)).fetchone()
        assert attempt["state"] == "unknown" and store.job(result.job["job_id"])["calls"] == 1
        assert "never-persist-this" not in attempt["error"]


@pytest.mark.parametrize("source,context", [("汉" * 9000, ""), ("Value remains unchanged.", "汉" * 8000)])
def test_first_entry_and_context_obey_hard_input_budget(source, context):
    transport = Model()
    result = model.translate_entries(transport, [("a", source)], "zh", context=context, identity=IDENTITY)
    assert not transport.calls and not result
    assert result.job["issues"][0]["code"] == "request_too_large"


def test_serialized_repair_payload_cannot_bypass_hard_budget():
    transport = Transform(lambda text: "# " + "汉" * 7900)
    result = model.translate_entries(transport, [("a", "Value remains unchanged.")], "zh", identity=IDENTITY)
    assert not result and len(transport.calls) == 1
    for call in transport.calls:
        assert _estimate(model._TRANSLATE) + _estimate(canonical(call)) <= MAX_INPUT_TOKENS


def test_cached_structure_is_immutable_and_receipts_keep_exact_signature():
    source = "## Outlook\n\nValue remains unchanged."
    before = model.markdown_structure(source)
    changed = model.markdown_structure(source)
    changed.append(["malicious"])
    assert model.markdown_structure(source) == before
    target, proof = model.translate_document(Model(), source, "zh")
    assert model.valid_document_receipt(source, target, "zh", proof)
