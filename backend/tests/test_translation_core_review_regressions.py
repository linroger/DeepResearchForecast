"""Durable review regressions over the real executor and synthetic transport."""

import json

import pytest

from app.config import Config
from app.services import model_translation as model
from app.services.translation.contracts import ScopedImport, canonical
from app.services.translation.engine import MAX_INPUT_TOKENS, _estimate
from app.services.translation.store import Store, database_path

IDENTITY = {"kind": "review-fixture", "ref_id": "report_a", "scope": {"view": "public"}}
PAIRS = [("a", "Value remains unchanged."), ("b", "Value remains unchanged.")]


class Model:
    model = "controlled-core-regression"

    def __init__(self, transform=None, timeout=False):
        self.calls = []
        self.messages = []
        self.transform = transform or (
            lambda text: text.replace("Value remains unchanged.", "数值保持不变。")
        )
        self.timeout = timeout

    def chat(self, messages, **kwargs):
        payload = json.loads(messages[-1]["content"])
        self.calls.append(payload)
        self.messages.append(messages)
        if self.timeout:
            raise TimeoutError("synthetic ambiguous remote outcome")
        if "entries" in payload:
            return json.dumps(
                {"translations": {k: self.transform(v) for k, v in payload["entries"].items()}}
            )
        return json.dumps(
            {
                "reviews": {
                    k: {"faithful": True, "complete": True, "target_language": True, "issues": []}
                    for k in payload["pairs"]
                }
            }
        )


@pytest.fixture(autouse=True)
def storage(tmp_path, monkeypatch):
    monkeypatch.setattr(Config, "UPLOAD_FOLDER", str(tmp_path / "uploads"))


class Crash(BaseException):
    """Terminate execution without entering the provider-error recovery path."""


def crash_after_stage(monkeypatch, stage):
    original = Store.checkpoint

    def checkpoint(store, job_id, fence, units, **kwargs):
        original(store, job_id, fence, units, **kwargs)
        if any(unit["stage"] == stage for unit in units.values()):
            raise Crash(stage)

    monkeypatch.setattr(Store, "checkpoint", checkpoint)
    return original


@pytest.mark.parametrize("stage", ["validate", "review_returned"])
def test_whole_returned_batch_survives_checkpoint_crash(monkeypatch, stage):
    original = crash_after_stage(monkeypatch, stage)
    first = Model()
    with pytest.raises(Crash):
        model.translate_entries(first, PAIRS, "zh", identity=IDENTITY)
    with Store(database_path()) as store:
        job_id = store.db.execute("SELECT id FROM jobs").fetchone()[0]
        assert {unit["stage"] for unit in store.units(job_id).values()} == {stage}
        assert (
            store.db.execute("SELECT COUNT(*) FROM attempts WHERE state='started'").fetchone()[0]
            == 0
        )
    monkeypatch.setattr(Store, "checkpoint", original)
    resumed = Model()
    result = model.translate_entries(resumed, PAIRS, "zh", identity=IDENTITY)
    assert len(result) == 2
    assert not any("entries" in call for call in resumed.calls)
    assert len(resumed.calls) == (1 if stage == "validate" else 0)


def test_interrupted_validation_preserves_single_repair_and_feedback(monkeypatch):
    original = crash_after_stage(monkeypatch, "validate")
    pairs = [("a", "Value remains unchanged. [S1]")]
    first = Model(transform=lambda text: "错误。")
    with pytest.raises(Crash):
        model.translate_entries(first, pairs, "zh", identity=IDENTITY)
    monkeypatch.setattr(Store, "checkpoint", original)
    second = Model(transform=lambda text: "错误。")
    result = model.translate_entries(second, pairs, "zh", identity=IDENTITY)
    assert not result and len(first.calls) + len(second.calls) == 2
    assert second.calls[0]["repair"] is True
    assert second.calls[0]["previous"] == {"a": "错误。"}
    assert second.calls[0]["structure_feedback"]["a"]["differences"]


def test_timeout_remains_unknown_and_consumes_budget():
    result = model.translate_entries(Model(timeout=True), PAIRS, "zh", identity=IDENTITY)
    with Store(database_path()) as store:
        row = dict(
            store.db.execute(
                "SELECT * FROM attempts WHERE job_id=?", (result.job["job_id"],)
            ).fetchone()
        )
    assert row["state"] == "unknown" and result.job["calls_used"] == 1
    assert json.loads(row["error"])["code"] == "provider_timeout"


@pytest.mark.parametrize("change", ["resource", "scope"])
def test_foreign_seed_is_not_admitted(change):
    private = {**IDENTITY, "scope": {"view": "actor", "actor_id": "synthetic"}}
    first = model.translate_entries(Model(), PAIRS, "zh", identity=private)
    seed = {
        k: {"source": text, "target": first[k], "receipt": first.receipts[k]} for k, text in PAIRS
    }
    other = {**private, "ref_id": "report_b"} if change == "resource" else IDENTITY
    transport = Model()
    result = model.translate_entries(transport, PAIRS, "zh", identity=other, seed=seed)
    assert len(result) == 2 and result.job["coverage"]["reused"] == 0
    assert len(transport.calls) == 2


@pytest.mark.parametrize("trusted", [False, True])
def test_unscoped_legacy_seed_requires_explicit_validated_reader(trusted):
    first = model.translate_entries(Model(), PAIRS, "zh")
    seed = {
        k: {"source": text, "target": first[k], "receipt": first.receipts[k]} for k, text in PAIRS
    }
    if trusted:
        seed = ScopedImport(seed, IDENTITY)
    transport = Model()
    result = model.translate_entries(transport, PAIRS, "zh", identity=IDENTITY, seed=seed)
    assert len(result) == 2
    assert result.job["coverage"]["reused"] == (2 if trusted else 0)
    assert len(transport.calls) == (0 if trusted else 2)


@pytest.mark.parametrize("reference", ["link", "footnote"])
def test_invalid_cross_section_reference_stays_partial_and_normal_retry_repairs(reference):
    if reference == "link":
        prose, definition = "See [policy][p].", "[p]: https://example.test/policy"
    else:
        prose, definition = "Policy[^note].", "[^note]: Factual note."
    source = f"## Outlook\n\n{prose}\n\n## References\n\n{definition}\n"

    def good(text):
        return (
            text.replace("Outlook", "展望")
            .replace("References", "参考来源")
            .replace("See ", "参见 ")
            .replace("Policy", "政策")
            .replace("Factual note.", "事实说明。")
        )

    broken = Model(transform=lambda text: good(text.replace(prose, "错误的无引用译文。")))
    target, proof = model.translate_document(broken, source, "zh", identity=IDENTITY)
    assert not proof["complete"] and not model.valid_document_receipt(source, target, "zh", proof)
    assert "错误的无引用译文。" not in target
    assert prose in target  # Rejected prose is rendered from source, retaining the reference.
    assert not model.structure_issues(source, target)
    resumed = Model(transform=good)
    repaired, accepted = model.translate_document(resumed, source, "zh", identity=IDENTITY)
    assert accepted["complete"] and model.valid_document_receipt(source, repaired, "zh", accepted)
    assert [key for call in resumed.calls for key in call.get("entries", {})] == ["section:0"]


def actual_costs(transport):
    # Use the exact strings delivered to the transport, including JSON spacing.
    return [
        sum(_estimate(message["content"]) for message in messages)
        for messages in transport.messages
    ]


def test_large_english_section_is_allowed_within_hard_budget():
    transport = Model()
    result = model.translate_entries(
        transport, [("a", "Value remains unchanged. " * 300)], "zh", identity=IDENTITY
    )
    assert len(result) == 1 and len(transport.calls) == 2
    assert all(cost <= MAX_INPUT_TOKENS for cost in actual_costs(transport))


def test_oversized_first_cjk_entry_is_rejected_without_any_call():
    transport = Model()
    result = model.translate_entries(transport, [("a", "汉" * 9000)], "zh", identity=IDENTITY)
    assert not result and not transport.calls and result.job["calls_used"] == 0
    assert result.job["issues"][0]["code"] == "request_too_large"


def test_review_counts_source_and_candidate_plus_serialized_metadata():
    transport = Model()
    result = model.translate_entries(transport, [("a", "汉" * 4000)], "zh", identity=IDENTITY)
    assert not result and len(transport.calls) == 1 and "entries" in transport.calls[0]
    assert result.job["issues"][0]["stage"] == "reviewing"
    assert result.job["issues"][0]["code"] == "request_too_large"
    assert all(cost <= MAX_INPUT_TOKENS for cost in actual_costs(transport))


def test_repair_previous_candidate_is_inside_hard_budget():
    transport = Model(transform=lambda text: "汉" * 9000)
    result = model.translate_entries(
        transport, [("a", "Value remains unchanged. [S1]")], "zh", identity=IDENTITY
    )
    assert not result and len(transport.calls) == 1
    assert result.job["issues"][0]["code"] == "request_too_large"
    assert all(cost <= MAX_INPUT_TOKENS for cost in actual_costs(transport))


def test_hard_budget_counts_exact_serialization_at_boundary():
    # Construct an entry that fits compact canonical JSON but not the actual
    # JSON serialization used by the transport. This tests the declared input
    # policy without assuming the estimator equals a provider tokenizer.
    entry = None
    for size in range(9000, 7000, -1):
        text = "汉" * size
        payload = {"target_language": "zh", "context": "", "entries": {"a": text}}
        compact = _estimate(model._TRANSLATE) + _estimate(canonical(payload))
        actual = _estimate(model._TRANSLATE) + _estimate(json.dumps(payload, ensure_ascii=False))
        if compact <= MAX_INPUT_TOKENS < actual:
            entry = text
            break
    assert entry is not None, "fixture must reach the serialization boundary"
    transport = Model()
    model.translate_entries(transport, [("a", entry)], "zh", identity=IDENTITY)
    costs = actual_costs(transport)
    assert all(cost <= MAX_INPUT_TOKENS for cost in costs), (
        f"compact admission={compact}; actual dispatched costs={costs}; hard limit={MAX_INPUT_TOKENS}"
    )
