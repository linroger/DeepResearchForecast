"""Lossless private fields: bounded contract cases for coordinator execution."""
from copy import deepcopy
from decimal import Decimal

import pytest

from app.services.world_simulation.contracts import WorldError, canonical_json
from app.services.world_simulation.review import (
    CANDIDATE_REPAIR_MODE, KINDS, MODE, MODE_V2, MODE_V3, MODE_V4,
    assessment_status, candidate_repair_enabled, normalize_v4_assessment_output,
    review_mode, validate_assessment,
)


pytestmark = pytest.mark.guarded_runner


def raw_assessment(fields=None):
    return {"checks": [{"kind": kind, "verdict": "consistent",
                        **deepcopy({"note": "PRIVATE_DESCRIPTION"} if fields is None else fields)}
                       for kind in sorted(KINDS)]}


def validate(value):
    return validate_assessment(value, {}, {}, mode=MODE_V4)


def rejected(value, *, canonical=False):
    before = deepcopy(value)
    with pytest.raises(WorldError) as caught:
        validate(value) if canonical else normalize_v4_assessment_output(value)
    assert caught.value.code == "invalid_assessment"
    assert "PRIVATE" not in str(caught.value) and caught.value.details == {}
    assert value == before


def test_every_noncontrol_member_is_reconstructable_without_synthesized_explanation():
    raw = raw_assessment({
        "note": "The stated rationale contradicts the chosen intent.",
        "contradiction": ["The resource was unavailable.", None, False, 7],
        "fields": {"status": "opaque nested data, not aggregate authority"},
        " Original Name ": "  preserve whitespace and key spelling  ",
    })
    before = deepcopy(raw)
    result = normalize_v4_assessment_output(raw)
    rebuilt = {"checks": [{"kind": check["kind"], "verdict": check["verdict"], **check["fields"]}
                          for check in result["checks"]]}
    assert rebuilt == raw == before
    assert canonical_json(rebuilt) == canonical_json(raw)
    for check in result["checks"]:
        assert set(check) == {"kind", "verdict", "fields"}
        assert "explanation" not in check["fields"]
        assert "status" in check["fields"]["fields"]


def test_canonical_validation_is_idempotent_detached_and_never_renormalizes():
    raw = raw_assessment({"fields": {"note": ["preserve"]}})
    canonical = normalize_v4_assessment_output(raw)
    once = validate(canonical)
    twice = validate(once)
    assert once == twice == canonical
    assert twice["checks"][0]["fields"] == {"fields": {"note": ["preserve"]}}
    raw["checks"][0]["fields"]["note"].append("raw change")
    canonical["checks"][0]["fields"]["fields"]["note"].append("canonical change")
    assert twice["checks"][0]["fields"] == {"fields": {"note": ["preserve"]}}
    twice["checks"][0]["fields"]["fields"]["note"].append("copy change")
    assert once["checks"][0]["fields"] == {"fields": {"note": ["preserve"]}}
    # Raw fields is legal, so entrypoint selection must be made by the caller:
    # normalizing a canonical object again would add a second fields wrapper.
    assert normalize_v4_assessment_output(once) != once


@pytest.mark.parametrize("verdict,expected", [
    ("consistent", "clear"), ("inconsistent", "unresolved"), ("unknown", "unresolved"),
])
def test_status_uses_only_four_explicit_verdicts_not_private_commentary(verdict, expected):
    raw = raw_assessment({"note": "This content disputes the decision and must be reviewed privately."})
    raw["checks"][2]["verdict"] = verdict
    result = normalize_v4_assessment_output(raw)
    assert assessment_status(result, mode=MODE_V4) == expected
    assert result["checks"][2]["fields"]["note"] == raw["checks"][2]["note"]


@pytest.mark.parametrize("defect", [
    "extra_aggregate", "three_checks", "missing_kind", "missing_verdict", "duplicate_kind",
    "wrong_case_kind", "unknown_kind", "nonstring_kind", "nonstring_verdict", "unknown_verdict", "nonobject_check",
])
def test_control_and_outer_assessment_failures_reject_whole_output(defect):
    raw = raw_assessment()
    check = raw["checks"][0]
    if defect == "extra_aggregate":
        raw["status"] = "clear"
    elif defect == "three_checks":
        raw["checks"].pop()
    elif defect == "missing_kind":
        del check["kind"]
    elif defect == "missing_verdict":
        del check["verdict"]
    elif defect == "duplicate_kind":
        raw["checks"][3]["kind"] = check["kind"]
    elif defect == "wrong_case_kind":
        check["Kind"] = check.pop("kind")
    elif defect == "unknown_kind":
        check["kind"] = "PRIVATE_KIND"
    elif defect == "nonstring_kind":
        check["kind"] = []
    elif defect == "nonstring_verdict":
        check["verdict"] = True
    elif defect == "unknown_verdict":
        check["verdict"] = "maybe"
    else:
        raw["checks"][3] = []
    rejected(raw)


def test_v4_canonical_only_and_legacy_shapes_remain_mode_specific():
    raw = raw_assessment({"explanation": "Existing explanation"})
    rejected(raw, canonical=True)
    canonical = normalize_v4_assessment_output(raw)
    extra = deepcopy(canonical)
    extra["checks"][0]["explanation"] = "PRIVATE_EXTRA"
    rejected(extra, canonical=True)
    with pytest.raises(WorldError):
        validate_assessment(canonical, {}, {}, mode=MODE_V3)
    assert validate_assessment(raw, {}, {}, mode=MODE_V3) == raw
    assert assessment_status(raw, mode=MODE_V3) == "clear"
    observation = {"actor": {"objectives": ["Objective"]}}
    decision = {"intents": []}
    for mode in (MODE, MODE_V2):
        legacy = {"status": "clear", "checks": [
            {"kind": kind, "explanation": "Existing explanation"} for kind in sorted(KINDS)]}
        if mode == MODE:
            for check in legacy["checks"]:
                check.update(objectiveIndices=[0] if check["kind"] == "goal_alignment" else [],
                             intentIndices=[], evidencePaths=[["actor", "objectives", 0]])
        before = deepcopy(legacy)
        assert validate_assessment(legacy, observation, decision, mode=mode) == before
        assert assessment_status(legacy, mode=mode) == "clear"
        assert legacy == before
        with pytest.raises(WorldError):
            validate_assessment(canonical, observation, decision, mode=mode)


def test_first_level_reserved_names_use_nfc_strip_casefold_without_aliasing_controls():
    canonical = normalize_v4_assessment_output(raw_assessment())
    reserved = ("kind", "verdict", "status", "decision", "assessment", "checks", "intents", "stateUpdates",
                "actorId", "observationId", "round", "phase", "decisionId", "intentId")
    for name in reserved:
        value = deepcopy(canonical)
        value["checks"][0]["fields"] = {name: "PRIVATE_VALUE"}
        rejected(value, canonical=True)
    for alias in (" STATUS ", "\u2003StateUPDATES\u00a0", "\u212aind", " Verdict "):
        rejected(raw_assessment({alias: "PRIVATE_VALUE"}))
    accepted = normalize_v4_assessment_output(raw_assessment({"note": {"status": "private description"}}))
    assert accepted["checks"][0]["fields"] == {"note": {"status": "private description"}}


def test_original_keys_and_unicode_values_preserved_but_nfc_collisions_reject():
    fields = {" Mixed Key ": " e\u0301 unchanged ", "\u212aey": {"e\u0301": "descriptive material"}}
    result = normalize_v4_assessment_output(raw_assessment(fields))
    assert result["checks"][0]["fields"] == fields
    assert " Mixed Key " in result["checks"][0]["fields"]
    assert "\u212aey" in result["checks"][0]["fields"]
    rejected(raw_assessment({"\u00e9": "one", "e\u0301": "two"}))
    rejected(raw_assessment({"note": {"\u00e9": "one", "e\u0301": "two"}}))


def test_string_material_requires_a_nonwhitespace_value_anywhere_not_a_key():
    for fields in ({}, {"descriptive key": " \t\n"}, {"note": [None, True, 1, [], {}]}):
        rejected(raw_assessment(fields))
    fields = {"note": {"items": [None, False, 4, "  meaningful\n  ", ""]}}
    result = normalize_v4_assessment_output(raw_assessment(fields))
    assert result["checks"][0]["fields"] == fields
    mixed = raw_assessment()
    mixed["checks"][3]["note"] = " \t "
    rejected(mixed)  # Three valid checks cannot salvage one invalid check.


@pytest.mark.parametrize("unicode_text", [False, True])
def test_canonical_utf8_bound_includes_entire_object_at_2048_bytes(unicode_text):
    overhead = len(canonical_json({"note": ""}).encode("utf-8"))
    room = 2048 - overhead
    text = "界" * (room // 3) + "x" * (room % 3) if unicode_text else "x" * room
    fields = {"note": text}
    assert len(canonical_json(fields).encode("utf-8")) == 2048
    assert normalize_v4_assessment_output(raw_assessment(fields))["checks"][0]["fields"] == fields
    rejected(raw_assessment({"note": text + "x"}))


def test_depth_counts_fields_root_at_zero_and_every_value_descent():
    fields = {"note": [[["depth four"]]]}
    assert normalize_v4_assessment_output(raw_assessment(fields))["checks"][0]["fields"] == fields
    rejected(raw_assessment({"note": [[[["depth five"]]]]}))


def test_node_limit_counts_containers_and_scalars_but_not_keys():
    # root + note + items = 3; seven lists of 17 nodes = 119; last list = 6.
    fields = {"note": "text", "items": [[0] * 16 for _ in range(7)] + [[0] * 5]}
    assert normalize_v4_assessment_output(raw_assessment(fields))["checks"][0]["fields"] == fields
    fields["items"][-1].append(0)  # 129 nodes; still below every other bound.
    rejected(raw_assessment(fields))


@pytest.mark.parametrize("container", ["root", "object", "array"])
def test_top_eight_and_nested_sixteen_member_limits(container):
    if container == "root":
        fields = {f"note{i}": "text" for i in range(8)}
    elif container == "object":
        fields = {"note": {f"item{i}": "text" for i in range(16)}}
    else:
        fields = {"note": ["text"] * 16}
    assert normalize_v4_assessment_output(raw_assessment(fields))["checks"][0]["fields"] == fields
    if container == "root":
        fields["extra"] = "text"
    elif container == "object":
        fields["note"]["extra"] = "text"
    else:
        fields["note"].append("text")
    rejected(raw_assessment(fields))


def test_keys_are_nonempty_strings_with_exact_128_character_limit():
    for key in ("a" * 128, "界" * 128):
        fields = {key: "text"}
        assert normalize_v4_assessment_output(raw_assessment(fields))["checks"][0]["fields"] == fields
    for fields in ({"": "text"}, {"note": {"": "text"}}, {"x" * 129: "text"}, {7: "text"}):
        rejected(raw_assessment(fields))


@pytest.mark.parametrize("value", [1.5, float("nan"), float("inf"), Decimal("1"), ("text",), "\ud800"])
def test_non_strict_json_values_reject_whole_output(value):
    raw = raw_assessment({"note": "description", "other": value})
    with pytest.raises(WorldError) as caught:
        normalize_v4_assessment_output(raw)
    assert caught.value.code == "invalid_assessment"


def test_candidate_repair_is_explicit_v3_or_v4_and_never_renews_two_calls():
    for mode in (MODE_V3, MODE_V4):
        spec = {"policy": {"decisionReview": mode}, "limits": {"maxAttemptsPerSlot": 2}}
        assert review_mode(spec) == mode and candidate_repair_enabled(spec) is False
        spec["policy"]["candidateRepair"] = CANDIDATE_REPAIR_MODE
        assert candidate_repair_enabled(spec) is True
        for attempts in (1, 3, True):
            invalid = deepcopy(spec)
            invalid["limits"]["maxAttemptsPerSlot"] = attempts
            with pytest.raises(WorldError) as caught:
                candidate_repair_enabled(invalid)
            assert caught.value.code == "invalid_limit"
    for mode in (MODE, MODE_V2):
        with pytest.raises(WorldError) as caught:
            candidate_repair_enabled({"policy": {"decisionReview": mode, "candidateRepair": CANDIDATE_REPAIR_MODE}})
        assert caught.value.code == "invalid_policy_metadata"
