"""Bounded structural diagnostics only; run through the coordinator's guard."""
from copy import deepcopy
import json

import pytest

from app.services.world_simulation.contracts import WorldError
from app.services.world_simulation.review import build_revision_shape, validate_revision_shape


pytestmark = pytest.mark.guarded_runner


def revision():
    return {
        "decision": {"intents": [], "rationale": "PRIVATE_RATIONALE"},
        "assessment": {"checks": [
            {"kind": "goal_alignment", "verdict": "consistent", "explanation": "PRIVATE_EXPLANATION"},
        ]},
    }


def node(kind, keys=(), missing=(), unknown=0, overflow=False):
    return {"type": kind, "recognizedKeys": list(keys), "missingRequiredKeys": list(missing),
            "unknownKeyCount": unknown, "unknownKeyOverflow": overflow}


def invalid(value):
    with pytest.raises(WorldError) as caught:
        validate_revision_shape(value)
    assert caught.value.code == "invalid_review_shape"
    assert "PRIVATE" not in str(caught.value) and caught.value.details == {}


def test_exact_eight_node_contract():
    expected = {
        "schemaVersion": "actor-revision-shape/v1",
        "checksItemCount": 1,
        "nodes": {
            "root": node("object", ("assessment", "decision")),
            "decision": node("object", ("intents", "rationale")),
            "assessment": node("object", ("checks",)),
            "checks": node("array"),
            "check0": node("object", ("explanation", "kind", "verdict")),
            "check1": node("missing", missing=("explanation", "kind", "verdict")),
            "check2": node("missing", missing=("explanation", "kind", "verdict")),
            "check3": node("missing", missing=("explanation", "kind", "verdict")),
        },
    }
    assert build_revision_shape(revision()) == expected
    assert validate_revision_shape(expected) == expected


@pytest.mark.parametrize("raw,kind", [
    (None, "null"), (True, "boolean"), (7, "number"), (1.25, "number"),
    ("PRIVATE", "string"), ([], "array"), ({}, "object"),
])
def test_json_type_tags_keep_booleans_distinct(raw, kind):
    shape = build_revision_shape(raw)
    assert shape["nodes"]["root"] == node(kind, missing=("assessment", "decision"))
    assert all(value["type"] == "missing" for name, value in shape["nodes"].items() if name != "root")
    assert shape["checksItemCount"] is None


def test_absence_and_explicit_null_have_different_receipts():
    absent = build_revision_shape({})
    present = build_revision_shape({"decision": None, "assessment": {"checks": [None]}})
    assert absent["nodes"]["decision"] == node("missing", missing=("intents",))
    assert present["nodes"]["decision"] == node("null", missing=("intents",))
    assert absent["nodes"]["assessment"]["type"] == "missing"
    assert present["nodes"]["check0"] == node("null", missing=("explanation", "kind", "verdict"))
    assert present["nodes"]["check1"]["type"] == "missing"
    null_checks = build_revision_shape({"assessment": {"checks": None}})
    assert null_checks["nodes"]["checks"]["type"] == "null"
    assert null_checks["checksItemCount"] is None
    assert all(null_checks["nodes"][f"check{i}"]["type"] == "missing" for i in range(4))


@pytest.mark.parametrize("unknown", [0, 4, 5, 1000])
def test_global_key_allowlist_and_unknown_count_cap(unknown):
    raw = {"decision": None, "verdict": "PRIVATE_VALUE", "actorId": "PRIVATE_ACTOR"}
    raw.update({f"PRIVATE_KEY_{i}": object() for i in range(unknown)})
    shape = build_revision_shape(raw)
    assert shape["nodes"]["root"] == node(
        "object", ("actorId", "decision", "verdict"), ("assessment",), min(unknown, 4), unknown > 4,
    )
    assert "PRIVATE" not in json.dumps(shape)


def test_arbitrary_values_and_unknown_names_cannot_change_or_leak_into_shape():
    left = revision()
    left["PRIVATE_NAME_A"] = {"hidden": "PRIVATE_A"}
    left["decision"]["actorId"] = "PRIVATE_ACTOR_A"
    left["assessment"]["checks"][0]["PRIVATE_CHECK_A"] = "PRIVATE_TEXT"
    right = revision()
    right["PRIVATE_NAME_B"] = {"deeper": [[object()]]}
    right["decision"].update(actorId="PRIVATE_ACTOR_B", intents=object(), rationale=object())
    right["assessment"]["checks"][0] = {
        "kind": object(), "verdict": object(), "explanation": object(), "PRIVATE_CHECK_B": object(),
    }
    first, second = build_revision_shape(left), build_revision_shape(right)
    assert first == second
    text = json.dumps(first)
    assert "PRIVATE" not in text and "goal_alignment" not in text and "consistent" not in text


def test_deep_values_cycles_and_check_tail_are_not_traversed():
    class Opaque:
        def __deepcopy__(self, memo):
            raise AssertionError("Diagnostic copied an arbitrary value")

        def __repr__(self):
            raise AssertionError("Diagnostic represented an arbitrary value")

        def __iter__(self):
            raise AssertionError("Diagnostic traversed an arbitrary value")

    deep = []
    deep.append(deep)
    for _ in range(2000):
        deep = [deep]
    raw = {
        "decision": {"intents": deep, "rationale": Opaque(), "PRIVATE": Opaque()},
        "assessment": {"checks": [
            {}, None, deep, {"kind": Opaque(), "verdict": deep, "explanation": Opaque()}, Opaque(),
        ]},
    }
    shape = build_revision_shape(raw)
    assert shape["checksItemCount"] == 5
    assert shape["nodes"]["check2"]["type"] == "array"
    assert shape["nodes"]["check3"]["recognizedKeys"] == ["explanation", "kind", "verdict"]
    assert len(json.dumps(shape)) < 4000
    assert validate_revision_shape(shape) == shape


@pytest.mark.parametrize("length", [0, 1, 4, 5, 1000])
def test_check_count_and_first_four_items_only(length):
    shape = build_revision_shape({"assessment": {"checks": [{} for _ in range(length)]}})
    assert shape["checksItemCount"] == min(length, 5)
    assert len(shape["nodes"]) == 8
    for index in range(4):
        assert shape["nodes"][f"check{index}"]["type"] == ("object" if index < length else "missing")


def test_builder_and_validator_return_detached_bounded_receipts():
    raw = revision()
    shape = build_revision_shape(raw)
    validated = validate_revision_shape(shape)
    raw.clear()
    shape["nodes"]["root"]["recognizedKeys"].clear()
    assert validated["nodes"]["root"]["recognizedKeys"] == ["assessment", "decision"]
    validated["nodes"]["check0"]["recognizedKeys"].clear()
    assert shape["nodes"]["check0"]["recognizedKeys"] == ["explanation", "kind", "verdict"]


@pytest.mark.parametrize("change", [
    "extra_field", "extra_node", "missing_node", "extra_node_field", "unknown_type",
    "unknown_key_name", "duplicate_key", "unsorted_keys", "wrong_missing", "boolean_count",
])
def test_validator_rejects_open_schema_and_untyped_or_noncanonical_fields(change):
    shape = build_revision_shape(revision())
    root = shape["nodes"]["root"]
    if change == "extra_field":
        shape["PRIVATE"] = "PRIVATE"
    elif change == "extra_node":
        shape["nodes"]["check4"] = deepcopy(shape["nodes"]["check0"])
    elif change == "missing_node":
        del shape["nodes"]["check3"]
    elif change == "extra_node_field":
        root["rawValue"] = "PRIVATE"
    elif change == "unknown_type":
        root["type"] = "PRIVATE"
    elif change == "unknown_key_name":
        root["recognizedKeys"] = ["PRIVATE"]
    elif change == "duplicate_key":
        root["recognizedKeys"].append("decision")
    elif change == "unsorted_keys":
        root["recognizedKeys"].reverse()
    elif change == "wrong_missing":
        root["missingRequiredKeys"] = ["decision"]
    elif change == "boolean_count":
        root["unknownKeyCount"] = True
    invalid(shape)


def test_validator_enforces_parent_presence_and_missing_versus_null():
    base = build_revision_shape({"decision": None, "assessment": {"checks": [None]}})
    cases = []
    changed = deepcopy(base)
    changed["nodes"]["root"] = node("object", ("assessment",), ("decision",))
    cases.append(changed)  # Absent key cannot have a present null child.
    changed = deepcopy(base)
    changed["nodes"]["decision"] = node("missing", missing=("intents",))
    cases.append(changed)  # Present key cannot have a missing child.
    changed = deepcopy(base)
    changed["nodes"]["assessment"] = node("null", missing=("checks",))
    cases.append(changed)  # Nonobject parent cannot have a checks child.
    changed = deepcopy(base)
    changed["nodes"]["root"] = node("null", missing=("assessment", "decision"))
    cases.append(changed)
    changed = build_revision_shape(None)
    changed["nodes"]["root"]["type"] = "missing"
    cases.append(changed)  # The supplied root always exists, including null.
    for value in cases:
        invalid(value)


def test_validator_enforces_array_counts_nonobject_metadata_and_overflow():
    base = build_revision_shape({"assessment": {"checks": [None]}})
    for count in (None, True, False, -1, 0, 2, 5, 6):
        changed = deepcopy(base)
        changed["checksItemCount"] = count
        invalid(changed)  # Exactly one present item; the others are missing.
    nonarray = build_revision_shape({"assessment": {"checks": None}})
    nonarray["checksItemCount"] = 0
    invalid(nonarray)
    for count, overflow in ((3, True), (0, 0), (5, False)):
        changed = deepcopy(base)
        changed["nodes"]["root"].update(unknownKeyCount=count, unknownKeyOverflow=overflow)
        invalid(changed)
    changed = deepcopy(base)
    changed["nodes"]["check0"]["unknownKeyCount"] = 1
    invalid(changed)  # Null cannot carry object metadata.
    changed = deepcopy(base)
    changed["nodes"]["check0"] = node("null", ("kind",), ("explanation", "verdict"))
    invalid(changed)


def test_unsupported_fixed_location_inputs_fail_typed_without_representation():
    class Private:
        def __repr__(self):
            raise AssertionError("PRIVATE object representation must not be inspected")

    for raw in (Private(), {"decision": Private()}, {"assessment": {"checks": [Private()]}}):
        with pytest.raises(WorldError) as caught:
            build_revision_shape(raw)
        assert caught.value.code == "invalid_review_shape"
        assert "PRIVATE" not in str(caught.value)
    for receipt in (None, [], {"schemaVersion": "PRIVATE"}):
        invalid(receipt)
