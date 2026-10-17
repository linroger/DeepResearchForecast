"""Pure binding checks for an optional actor consistency revision.

These checks bind a model assessment to visible evidence and the final decision.
They do not prove that natural-language goals or explanations are correct.
"""
from .contracts import clone, require

MODE = "actor-consistency-v1"
MODE_V2 = "actor-consistency-v2"
REVIEW_MODES = frozenset({MODE, MODE_V2})
KINDS = frozenset({"goal_alignment", "conditional_timing", "quantity_consistency", "explanation_consistency"})
ROOTS = frozenset({"actor", "privateState", "world", "inbox", "ownOffers", "messages", "options",
                   "simulatedAt", "periodEnd", "phase", "round"})


def review_mode(spec):
    policy = spec.get("policy", {})
    require(isinstance(policy, dict), "invalid_policy_metadata", "Policy metadata must be an object")
    if "decisionReview" not in policy:
        return None
    require(isinstance(policy["decisionReview"], str) and policy["decisionReview"] in REVIEW_MODES, "invalid_policy_metadata", "Unknown pinned decision review policy")
    require(type(spec.get("limits", {}).get("maxAttemptsPerSlot", 2)) is int
            and spec.get("limits", {}).get("maxAttemptsPerSlot", 2) == 2,
            "invalid_limit", "Consistency revision requires the existing two-call allowance")
    return policy["decisionReview"]


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


def validate_assessment(value, observation, decision, *, mode=MODE):
    require(isinstance(mode, str) and mode in REVIEW_MODES,
            "invalid_assessment", "Unsupported consistency assessment mode")
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
