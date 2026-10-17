"""Pure binding checks for an optional actor consistency revision.

These checks bind a model assessment to visible evidence and the final decision.
They do not prove that natural-language goals or explanations are correct.
"""
from .contracts import clone, require

MODE = "actor-consistency-v1"
MODE_V2 = "actor-consistency-v2"
MODE_V3 = "actor-consistency-v3"
MODE_V4 = "actor-consistency-v4"
REVIEW_MODES = frozenset({MODE, MODE_V2, MODE_V3, MODE_V4})
CANDIDATE_REPAIR_MODE = "known-output-error-v1"
CANDIDATE_OUTPUT_ERRORS = frozenset({
    "policy_invalid_response", "invalid_decision", "invalid_intent", "invalid_input", "invalid_quantity",
    "invalid_actor_update", "invalid_actor_provenance", "unauthorized_actor_update", "unauthorized_priority",
    "unavailable_offer", "closed_offer", "undelivered_offer", "stale_terms",
})
KINDS = frozenset({"goal_alignment", "conditional_timing", "quantity_consistency", "explanation_consistency"})
ROOTS = frozenset({"actor", "privateState", "world", "inbox", "ownOffers", "messages", "options",
                   "simulatedAt", "periodEnd", "phase", "round"})


def review_mode(spec):
    policy = spec.get("policy", {})
    require(isinstance(policy, dict), "invalid_policy_metadata", "Policy metadata must be an object")
    if "candidateRepair" in policy:
        require(policy.get("decisionReview") in (MODE_V3, MODE_V4)
                and policy["candidateRepair"] == CANDIDATE_REPAIR_MODE,
                "invalid_policy_metadata", "Candidate repair requires its explicit v3/v4 policy pin")
    if "decisionReview" not in policy:
        return None
    require(isinstance(policy["decisionReview"], str) and policy["decisionReview"] in REVIEW_MODES, "invalid_policy_metadata", "Unknown pinned decision review policy")
    require(type(spec.get("limits", {}).get("maxAttemptsPerSlot", 2)) is int
            and spec.get("limits", {}).get("maxAttemptsPerSlot", 2) == 2,
            "invalid_limit", "Consistency revision requires the existing two-call allowance")
    return policy["decisionReview"]


def candidate_repair_enabled(spec):
    return review_mode(spec) in (MODE_V3, MODE_V4) and spec["policy"].get("candidateRepair") == CANDIDATE_REPAIR_MODE


def candidate_error_context(observation, error_code):
    from .contracts import identifier

    require(isinstance(error_code, str) and error_code in CANDIDATE_OUTPUT_ERRORS,
            "invalid_review_input", "Candidate error must identify a supported output-validation failure")
    return {"schemaVersion": "actor-candidate-error/v1",
            "actorId": identifier(observation.get("actorId"), "actorId"),
            "observationId": identifier(observation.get("observationId"), "observationId"), "errorCode": error_code}


def validate_candidate_error_context(value, observation):
    require(isinstance(value, dict) and set(value) == {"schemaVersion", "actorId", "observationId", "errorCode"},
            "invalid_review_input", "Candidate error context has unsupported fields")
    require(value == candidate_error_context(observation, value["errorCode"]),
            "invalid_review_input", "Candidate error context belongs to another observation")
    return clone(value)


def _indices(value, size):
    require(isinstance(value, list) and all(type(index) is int and 0 <= index < size for index in value)
            and len(value) == len(set(value)), "invalid_assessment", "Assessment indexes must identify actual unique records")
    return set(value)


def _evidence(path, observation):
    require(isinstance(path, list) and 1 <= len(path) <= 12 and isinstance(path[0], str)
            and path[0] in ROOTS, "invalid_assessment", "Assessment evidence must refer to the original observation")
    value = observation
    for segment in path:
        if isinstance(value, dict):
            require(isinstance(segment, str) and segment in value,
                    "invalid_assessment", "Assessment evidence path is unavailable")
        elif isinstance(value, list):
            require(type(segment) is int and 0 <= segment < len(value),
                    "invalid_assessment", "Assessment evidence index is unavailable")
        else:
            require(False, "invalid_assessment", "Assessment evidence path does not resolve")
        value = value[segment]


def _validate_v3(value):
    require(isinstance(value, dict) and set(value) == {"checks"},
            "invalid_assessment", "Per-check review requires checks without aggregate status")
    checks = value["checks"]
    require(isinstance(checks, list) and len(checks) == len(KINDS),
            "invalid_assessment", "Revision must assess all four consistency dimensions")
    seen = set()
    for check in checks:
        require(isinstance(check, dict) and set(check) == {"kind", "verdict", "explanation"},
                "invalid_assessment", "Unsupported assessment check fields")
        kind = check["kind"]
        require(isinstance(kind, str) and kind in KINDS and kind not in seen,
                "invalid_assessment", "Assessment kinds must be complete and unique")
        seen.add(kind)
        require(isinstance(check["verdict"], str) and check["verdict"] in {"consistent", "inconsistent", "unknown"},
                "invalid_assessment", "Each check requires an explicit consistency verdict")
        require(isinstance(check["explanation"], str) and bool(check["explanation"].strip())
                and len(check["explanation"]) <= 400,
                "invalid_assessment", "Each assessment needs a bounded explanation")
    return clone(value)


def assessment_status(value, *, mode):
    """Derive status from a validated assessment; v3 never trusts an aggregate flag.

    Callers still validate legacy evidence references against their observation.
    V3 is fully structural here and cannot clear missing or malformed checks.
    """
    require(isinstance(mode, str) and mode in REVIEW_MODES,
            "invalid_assessment", "Unsupported consistency assessment mode")
    if mode == MODE_V4:
        checks = _validate_v4(value)["checks"]
        return "clear" if all(check["verdict"] == "consistent" for check in checks) else "unresolved"
    if mode == MODE_V3:
        checks = _validate_v3(value)["checks"]
        return "clear" if all(check["verdict"] == "consistent" for check in checks) else "unresolved"
    require(isinstance(value, dict) and set(value) == {"status", "checks"}
            and isinstance(value["status"], str) and value["status"] in {"clear", "unresolved"}
            and isinstance(value["checks"], list) and len(value["checks"]) == len(KINDS)
            and all(isinstance(check, dict) and isinstance(check.get("kind"), str) for check in value["checks"])
            and {check["kind"] for check in value["checks"]} == KINDS,
            "invalid_assessment", "Revision requires a typed consistency assessment")
    return value["status"]


def validate_assessment(value, observation, decision, *, mode=MODE):
    require(isinstance(mode, str) and mode in REVIEW_MODES,
            "invalid_assessment", "Unsupported consistency assessment mode")
    if mode == MODE_V4:
        return _validate_v4(value)
    if mode == MODE_V3:
        return _validate_v3(value)
    require(isinstance(value, dict) and set(value) == {"status", "checks"}
            and isinstance(value["status"], str) and value["status"] in {"clear", "unresolved"},
            "invalid_assessment", "Revision requires a typed consistency assessment")
    checks = value["checks"]
    require(isinstance(checks, list) and len(checks) == len(KINDS),
            "invalid_assessment", "Revision must assess all four consistency dimensions")
    objectives = observation["actor"]["objectives"]
    intents = decision["intents"]
    seen = set()
    for check in checks:
        fields = {"kind", "explanation"} if mode == MODE_V2 else {
            "kind", "objectiveIndices", "intentIndices", "evidencePaths", "explanation"}
        require(isinstance(check, dict) and set(check) == fields,
                "invalid_assessment", "Unsupported assessment check fields")
        kind = check["kind"]
        require(isinstance(kind, str) and kind in KINDS and kind not in seen,
                "invalid_assessment", "Assessment kinds must be complete and unique")
        seen.add(kind)
        if mode == MODE:
            goals = _indices(check["objectiveIndices"], len(objectives))
            actions = _indices(check["intentIndices"], len(intents))
            require(kind != "goal_alignment" or goals == set(range(len(objectives))),
                    "invalid_assessment", "Goal review must reference every supplied objective")
            require(kind != "explanation_consistency" or actions == set(range(len(intents))),
                    "invalid_assessment", "Explanation review must reference every final intent")
        require(isinstance(check["explanation"], str) and bool(check["explanation"].strip())
                and len(check["explanation"]) <= 400,
                "invalid_assessment", "Each assessment needs a bounded explanation")
        if mode == MODE:
            paths = check["evidencePaths"]
            require(isinstance(paths, list) and 1 <= len(paths) <= 4,
                    "invalid_assessment", "Assessment needs bounded visible evidence references")
            for path in paths:
                _evidence(path, observation)
    return clone(value)


# Diagnostic-only schema. Never feed these receipts into decision admission,
# actor prompts, retry selection or scores. Keep all preexisting modes unchanged.
_REVISION_SHAPE_KEYS = tuple(sorted({
    "decision", "assessment", "intents", "stateUpdates", "rationale", "status",
    "actorId", "observationId", "checks", "kind", "verdict", "explanation",
    "objectiveIndices", "intentIndices", "evidencePaths", "round", "phase",
    "decisionId", "intentId",
}))
_REVISION_SHAPE_REQUIRED = {
    "root": ("assessment", "decision"),
    "decision": ("intents",),
    "assessment": ("checks",),
    "checks": (),
    "check0": ("explanation", "kind", "verdict"),
    "check1": ("explanation", "kind", "verdict"),
    "check2": ("explanation", "kind", "verdict"),
    "check3": ("explanation", "kind", "verdict"),
}
_REVISION_SHAPE_TYPES = frozenset({
    "missing", "null", "boolean", "number", "string", "array", "object",
})
_REVISION_SHAPE_NODE_FIELDS = frozenset({
    "type", "recognizedKeys", "missingRequiredKeys", "unknownKeyCount", "unknownKeyOverflow",
})


def build_revision_shape(raw):
    """Describe eight fixed locations without traversing arbitrary keys/values.

    Inputs are parsed JSON builtins. Only the declared child paths are read;
    object-key recognition uses fixed lookups plus len, never iteration over
    unknown keys. Nested values and check items beyond index three are untouched.
    """
    missing = object()

    def child(parent, key):
        return parent.get(key, missing) if type(parent) is dict else missing

    def describe(value, required):
        if value is missing:
            kind = "missing"
        elif value is None:
            kind = "null"
        else:
            kind = {bool: "boolean", int: "number", float: "number", str: "string",
                    list: "array", dict: "object"}.get(type(value))
        require(kind is not None, "invalid_review_shape", "Shape input must use parsed JSON types")
        keys = [key for key in _REVISION_SHAPE_KEYS if key in value] if kind == "object" else []
        unknown = len(value) - len(keys) if kind == "object" else 0
        return {
            "type": kind, "recognizedKeys": keys,
            "missingRequiredKeys": [key for key in required if key not in keys],
            "unknownKeyCount": min(unknown, 4), "unknownKeyOverflow": unknown > 4,
        }

    decision = child(raw, "decision")
    assessment = child(raw, "assessment")
    checks = child(assessment, "checks")
    count = min(len(checks), 5) if type(checks) is list else None
    values = {"root": raw, "decision": decision, "assessment": assessment, "checks": checks}
    for index in range(4):
        values[f"check{index}"] = checks[index] if count is not None and index < count else missing
    shape = {
        "schemaVersion": "actor-revision-shape/v1",
        "nodes": {name: describe(values[name], required)
                  for name, required in _REVISION_SHAPE_REQUIRED.items()},
        "checksItemCount": count,
    }
    return validate_revision_shape(shape)


def validate_revision_shape(value):
    """Validate a closed structural receipt and copy only its bounded fields."""
    def check(condition):
        require(condition, "invalid_review_shape", "Invalid revision shape receipt")

    check(type(value) is dict and len(value) == 3
          and set(value) == {"schemaVersion", "nodes", "checksItemCount"})
    check(type(value["schemaVersion"]) is str and value["schemaVersion"] == "actor-revision-shape/v1")
    supplied = value["nodes"]
    check(type(supplied) is dict and len(supplied) == len(_REVISION_SHAPE_REQUIRED)
          and set(supplied) == set(_REVISION_SHAPE_REQUIRED))
    nodes = {}
    for name, required in _REVISION_SHAPE_REQUIRED.items():
        node = supplied[name]
        check(type(node) is dict and len(node) == len(_REVISION_SHAPE_NODE_FIELDS)
              and set(node) == _REVISION_SHAPE_NODE_FIELDS)
        kind = node["type"]
        check(type(kind) is str and kind in _REVISION_SHAPE_TYPES)
        keys = node["recognizedKeys"]
        check(type(keys) is list and len(keys) <= len(_REVISION_SHAPE_KEYS)
              and all(type(key) is str and key in _REVISION_SHAPE_KEYS for key in keys))
        check(keys == sorted(set(keys)))
        absent = node["missingRequiredKeys"]
        check(type(absent) is list and len(absent) <= len(required)
              and all(type(key) is str and key in required for key in absent))
        check(absent == [key for key in required if key not in keys])
        count, overflow = node["unknownKeyCount"], node["unknownKeyOverflow"]
        check(type(count) is int and 0 <= count <= 4 and type(overflow) is bool)
        check(not overflow or count == 4)
        check(kind == "object" or (keys == [] and count == 0 and overflow is False))
        nodes[name] = {
            "type": kind, "recognizedKeys": list(keys), "missingRequiredKeys": list(absent),
            "unknownKeyCount": count, "unknownKeyOverflow": overflow,
        }

    check(nodes["root"]["type"] != "missing")
    for parent, key, name in (("root", "decision", "decision"),
                              ("root", "assessment", "assessment"),
                              ("assessment", "checks", "checks")):
        present = nodes[parent]["type"] == "object" and key in nodes[parent]["recognizedKeys"]
        check((nodes[name]["type"] != "missing") == present)
    item_count = value["checksItemCount"]
    if nodes["checks"]["type"] == "array":
        check(type(item_count) is int and 0 <= item_count <= 5)
    else:
        check(item_count is None)
    for index in range(4):
        present = item_count is not None and index < item_count
        check((nodes[f"check{index}"]["type"] != "missing") == present)
    return {"schemaVersion": "actor-revision-shape/v1", "nodes": nodes, "checksItemCount": item_count}


# V4 private data is retained verbatim, never interpreted as action or authority.
_V4_RESERVED_FIELDS = frozenset(name.casefold() for name in (
    "kind", "verdict", "status", "decision", "assessment", "checks", "intents", "stateUpdates",
    "actorId", "observationId", "round", "phase", "decisionId", "intentId",
))


def _v4_fields(value):
    """Copy a bounded strict-JSON tree without renaming keys or changing values."""
    import unicodedata
    from .contracts import WorldError, canonical_json

    require(type(value) is dict and 1 <= len(value) <= 8,
            "invalid_assessment", "V4 fields require one to eight private members")
    nodes = 0
    has_text = False

    def visit(item, depth):
        nonlocal nodes, has_text
        nodes += 1  # Every scalar/container, including fields at depth zero.
        require(nodes <= 128 and depth <= 4,
                "invalid_assessment", "V4 fields exceed the node or depth bound")
        kind = type(item)
        if item is None or kind in (bool, int):
            return item
        if kind is str:
            has_text = has_text or bool(item.strip())
            return item
        if kind is list:
            require(len(item) <= 16, "invalid_assessment", "V4 nested arrays exceed sixteen members")
            return [visit(child, depth + 1) for child in item]
        require(kind is dict, "invalid_assessment", "V4 fields require strict JSON types without floats")
        require(len(item) <= (8 if depth == 0 else 16),
                "invalid_assessment", "V4 object member bound exceeded")
        copied, normalized_keys = {}, set()
        for key, child in item.items():
            require(type(key) is str and 1 <= len(key) <= 128,
                    "invalid_assessment", "V4 field keys must be nonempty bounded strings")
            normalized = unicodedata.normalize("NFC", key)
            require(normalized not in normalized_keys,
                    "invalid_assessment", "V4 field keys collide under strict JSON normalization")
            normalized_keys.add(normalized)
            require(depth != 0 or normalized.strip().casefold() not in _V4_RESERVED_FIELDS,
                    "invalid_assessment", "V4 private fields cannot contain reserved control names")
            copied[key] = visit(child, depth + 1)
        return copied

    copied = visit(value, 0)
    require(has_text, "invalid_assessment", "V4 fields require a nonwhitespace string value")
    try:
        encoded = canonical_json(copied).encode("utf-8")
    except (TypeError, ValueError, UnicodeError, RecursionError, OverflowError):
        raise WorldError("invalid_assessment", "V4 fields must have a strict canonical JSON representation") from None
    require(len(encoded) <= 2048, "invalid_assessment", "V4 canonical fields exceed 2048 UTF-8 bytes")
    return copied


def _validate_v4(value):
    """Validate canonical v4 only; never reinterpret or normalize saved checks."""
    require(type(value) is dict and len(value) == 1 and "checks" in value,
            "invalid_assessment", "V4 assessment requires only checks")
    checks = value["checks"]
    require(type(checks) is list and len(checks) == len(KINDS),
            "invalid_assessment", "V4 assessment requires four checks")
    result, seen = [], set()
    for check in checks:
        require(type(check) is dict and len(check) == 3 and set(check) == {"kind", "verdict", "fields"},
                "invalid_assessment", "Canonical v4 checks require kind, verdict and fields")
        kind, verdict = check["kind"], check["verdict"]
        require(type(kind) is str and kind in KINDS and kind not in seen,
                "invalid_assessment", "V4 check kinds must be explicit, valid and unique")
        require(type(verdict) is str and verdict in {"consistent", "inconsistent", "unknown"},
                "invalid_assessment", "V4 check verdicts must be explicit and valid")
        seen.add(kind)
        result.append({"kind": kind, "verdict": verdict, "fields": _v4_fields(check["fields"])})
    return {"checks": result}


def normalize_v4_assessment_output(raw_assessment):
    """Losslessly pack fresh parsed v4 output; callers must not normalize replay.

    Raw ``fields`` is itself private data and remains under canonical
    ``fields.fields``. No alias, explanation or control value is manufactured.
    The outer decision/assessment envelope is validated by the HTTP policy.
    """
    require(type(raw_assessment) is dict and len(raw_assessment) == 1 and "checks" in raw_assessment,
            "invalid_assessment", "Raw v4 assessment requires only checks")
    checks = raw_assessment["checks"]
    require(type(checks) is list and len(checks) == len(KINDS),
            "invalid_assessment", "Raw v4 assessment requires four checks")
    packed = []
    for check in checks:
        require(type(check) is dict and 3 <= len(check) <= 10
                and all(type(key) is str for key in check) and "kind" in check and "verdict" in check,
                "invalid_assessment", "Raw v4 checks require exact controls and bounded private members")
        packed.append({
            "kind": check["kind"], "verdict": check["verdict"],
            "fields": {key: item for key, item in check.items() if key not in ("kind", "verdict")},
        })
    return _validate_v4({"checks": packed})
