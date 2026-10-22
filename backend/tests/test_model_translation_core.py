"""Raw model translation contracts; no provider, saved data, or legacy masks."""
import copy
import json

import pytest

from app.services.model_translation import (
    translate_entries, translate_document, valid_receipt, valid_document_receipt,
    split_document, structure_issues,
)


class Translator:
    model = "controlled-translator-and-reviewer"

    def __init__(self, translations, rejected=()):
        self.translations = translations
        self.rejected = set(rejected)
        self.calls = []

    def chat(self, messages, **kwargs):
        payload = json.loads(messages[-1]["content"])
        self.calls.append(payload)
        assert "⟦" not in messages[-1]["content"], "model must see raw source facts"
        if "entries" in payload:
            values = {key: self.translations.get(source, source)
                      for key, source in payload["entries"].items()}
            return json.dumps({"translations": values}, ensure_ascii=False)
        return json.dumps({"reviews": {key: {
            "faithful": value["translation"] not in self.rejected,
            "complete": True, "target_language": True,
            "issues": ["changed meaning"] if value["translation"] in self.rejected else []}
            for key, value in payload["pairs"].items()}})


def test_direct_readable_numbers_dates_are_reviewed_not_lexically_rejected():
    source = "Revenue was $3.7 billion in December 2024; approval is not assured."
    target = "2024年12月营收为37亿美元；审批并无保证。"
    model = Translator({source: target})
    result = translate_entries(model, [("a", source)], "zh", context="outlook")
    assert result == {"a": target} and result.calls_used == 2
    assert model.calls[0]["entries"]["a"] == source
    assert model.calls[1]["pairs"]["a"] == {"source": source, "translation": target}
    assert valid_receipt(source, target, "zh", result.receipts["a"], context="outlook")


@pytest.mark.parametrize("bad", ["收入为3.7亿美元。", "装机容量为25 W。", "批准已获保证。"])
def test_semantic_rejection_never_becomes_accepted_via_structural_parity(bad):
    model = Translator({"Revenue $3.7 billion, capacity25 kW; approval not assured.": bad}, [bad])
    result = translate_entries(model, [("a", "Revenue $3.7 billion, capacity25 kW; approval not assured.")], "zh")
    assert not result and result.calls_used == 4 and "a" in result.issues


def test_repair_only_rejected_whole_entry_with_no_good_prefix_requeue():
    good, bad = "The plan is conditional.", "Capacity is 25 kW."
    model = Translator({good: "计划附带条件。", bad: "容量为25 W。"}, ["容量为25 W。"])
    original = model.chat

    def chat(messages, **kwargs):
        payload = json.loads(messages[-1]["content"])
        if payload.get("repair"):
            assert payload["entries"] == {"b": bad}
            model.translations[bad] = "容量为25 kW。"
        return original(messages, **kwargs)
    model.chat = chat
    results = []
    result = translate_entries(model, [("a", good), ("b", bad)], "zh", on_progress=results.append)
    assert result == {"a": "计划附带条件。", "b": "容量为25 kW。"}
    assert result.calls_used == 4 and set(results[-1].receipts) == {"a", "b"}


@pytest.mark.parametrize("changed", [
    "## 标题\n\n| A | B |\n|---|---|\n|甲|1|\n|乙|2|",
    "# 标题\n\n[来源](https://wrong.test) [S1]\n\n```json\n{\"x\":1}\n```",
    "# 标题\n\n[来源](https://example.test) [S2]\n\n```json\n{\"x\":1}\n```",
    "# 标题\n\n[来源](https://example.test) [S1]\n\n```json\n{\"x\":2}\n```",
])
def test_model_review_cannot_override_structural_or_immutable_carrier_failure(changed):
    source = '# Title\n\n[Source](https://example.test) [S1]\n\n```json\n{"x":1}\n```'
    model = Translator({source: changed})
    result = translate_entries(model, [("a", source)], "zh")
    assert not result and structure_issues(source, changed)
    assert not any("pairs" in call for call in model.calls)


def test_parsed_boundaries_ignore_fenced_heading_and_preserve_list_table_blocks():
    source = '# Title\n\n## First\n\n```text\n## not a section\n```\n\n## Next\n\n- one\n- two\n\n|A|B|\n|---|---|\n|x|1|\n'
    chunks = split_document(source)
    assert len(chunks) == 3 and "## not a section" in chunks[1]
    assert "- one\n- two" in chunks[2] and "|x|1|" in chunks[2]
    assert not structure_issues(source, source.replace("Title", "标题").replace("First", "第一"))


def test_natural_mandarin_can_start_with_an_unchanged_inline_identifier():
    source = "The `Q12027` forecast remains unchanged."
    target = "`Q12027`的预测保持不变。"
    model = Translator({source: target})
    result = translate_entries(model, [("a", source)], "zh")
    assert result == {"a": target} and result.calls_used == 2
    assert valid_receipt(source, target, "zh", result.receipts["a"])
    assert structure_issues(source, target.replace("Q12027", "Q12028"))


def test_budget_counts_review_and_never_accepts_unreviewed_output():
    model = Translator({"First": "第一", "Second": "第二"})
    assert not translate_entries(model, [("a", "First")], "zh", max_calls=1)
    assert not model.calls
    result = translate_entries(model, [("a", "First"), ("b", "Second")], "zh", max_calls=2)
    assert len(result) == 2 and result.calls_used == 2
    assert all(valid_receipt(source, result[key], "zh", result.receipts[key])
               for key, source in [("a", "First"), ("b", "Second")])


def test_duplicate_or_missing_json_keys_cannot_get_reviewed_as_complete():
    class Invalid:
        def chat(self, **kwargs):
            return '{"translations":{"a":"第一","a":"第二"}}'
    result = translate_entries(Invalid(), [("a", "First")], "zh")
    assert not result and result.calls_used == 2


def test_provider_failure_is_bounded_and_not_retried_as_content():
    class Offline:
        def chat(self, **kwargs):
            raise RuntimeError("private provider response must not be persisted")
    result = translate_entries(Offline(), [(str(i), "First") for i in range(60)], "zh")
    assert not result and result.calls_used == 1 and len(result.issues) == 60
    assert "private" not in str(result.issues)


def test_persisted_proof_binds_current_source_target_language_and_review():
    source, target = "# Outlook\n\nConditional approval.", "# 展望\n\n附条件批准。"
    model = Translator({"# Outlook": "# 展望", "# Outlook\n\nConditional approval.": target})
    translated, proof = translate_document(model, source, "zh")
    assert valid_document_receipt(source, translated, "zh", proof)
    assert not valid_document_receipt(source + " changed", translated, "zh", proof)
    assert not valid_document_receipt(source, translated + "改变", "zh", proof)
    assert not valid_document_receipt(source, translated, "en", proof)
    tampered = copy.deepcopy(proof)
    tampered["sections"][0]["receipt"]["review"]["faithful"] = False
    assert not valid_document_receipt(source, translated, "zh", tampered)
    assert not valid_document_receipt(source, translated, "zh", None)


@pytest.mark.parametrize("target", [None, {}, [], 25, True])
def test_malformed_receipt_target_fails_closed_without_read_time_exception(target):
    assert valid_receipt("source", target, "zh", {"engine": "model-translation/v1"}) is False


def test_oversized_atomic_block_reports_pending_without_truncation():
    source = "```text\n" + "a" * 25000 + "\n```"
    assert split_document(source) == [source]
    model = Translator({})
    target, proof = translate_document(model, source, "zh")
    assert source in target and not proof["complete"] and not model.calls
    assert not valid_document_receipt(source, target, "zh", proof)
