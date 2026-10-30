"""Bounded World Anchor evidence admission. Stdlib only; no import-time I/O.

External hashes authenticate provenance, not truth. Model review is an explicit,
qualified judgment of source support. The module never calls a provider or app.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import stat
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from types import MappingProxyType

VERSION = "world-anchor/v1"
ENGINES = ("oasis-legacy", "world-v1", "target-first-v1")
MAX_JSON = 8 * 1024 * 1024
MAX_PAGE = 16 * 1024 * 1024
MAX_TOTAL = 512 * 1024 * 1024
VALUE_KINDS = {
    "observed",
    "reported",
    "third_party_forecast",
    "analyst_inferred",
    "assumed",
    "simulated",
}
PRODUCERS = {
    "official_observation",
    "primary_statement",
    "secondary_report",
    "external_forecast",
    "research_analyst",
    "model_prior",
    "simulation",
}
NUMERIC_FIELDS = {
    "entity",
    "metric",
    "denominator",
    "geography",
    "unit",
    "reference_period",
    "value",
    "value_kind",
}
SUPPORT_FIELDS = NUMERIC_FIELDS | {
    "published_at",
    "available_at",
    "effective_at",
    "visible_at",
    "vintage",
    "cadence",
    "producer_class",
    "audience",
    "actor_basis",
    "authority",
}
_KEY = object()


class AnchorError(ValueError):
    def __init__(self, code, path="", requirement_id=None):
        self.code, self.path, self.requirement_id = code, path, requirement_id
        super().__init__(f"{code}: {path}")


def _need(ok, code="E_SCHEMA", path=""):
    if not ok:
        raise AnchorError(code, path)


def _object(value, fields, path=""):
    _need(type(value) is dict and set(value) == set(fields.split()), path=path)
    return value


def _list(value, maximum=20000):
    _need(type(value) is list, path="list")
    _need(len(value) <= maximum, "E_LIMIT", "list")
    return value


def _text(value, maximum=128):
    _need(type(value) is str and 0 < len(value) <= maximum, path="text")
    return value


def _hash(value):
    _need(
        type(value) is str and re.fullmatch(r"[0-9a-f]{64}", value), "E_HASH", "digest"
    )
    return value


def _integer(value, maximum=2**53 - 1):
    _need(type(value) is int and 0 <= value <= maximum, path="integer")
    return value


def _finite(value, depth=0, seen=None):
    _need(depth <= 32, "E_LIMIT", "depth")
    if value is None or type(value) is bool:
        return
    if type(value) is int:
        _need(abs(value) <= 2**53 - 1, "E_LIMIT", "integer")
    elif type(value) is float:
        _need(math.isfinite(value), "E_NONFINITE", "number")
    elif type(value) is str:
        _need(len(value) <= 262144, "E_LIMIT", "string")
        try:
            value.encode("utf-8")
        except UnicodeError:
            raise AnchorError("E_SCHEMA", "utf8") from None
    elif type(value) in (dict, list):
        seen = set() if seen is None else seen
        _need(id(value) not in seen, "E_SCHEMA", "cycle")
        seen.add(id(value))
        _need(len(value) <= 20000, "E_LIMIT", "collection")
        if type(value) is dict:
            for key, item in value.items():
                _need(type(key) is str, path="object_key")
                _finite(key, depth + 1, seen)
                _finite(item, depth + 1, seen)
        else:
            for item in value:
                _finite(item, depth + 1, seen)
        seen.remove(id(value))
    else:
        raise AnchorError("E_SCHEMA", "json_type")


def _bytes(value):
    _finite(value)
    result = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode()
    _need(len(result) <= MAX_JSON, "E_LIMIT", "json_bytes")
    return result


def anchor_hash(value):
    return hashlib.sha256(_bytes(value)).hexdigest()


def _copy(value):
    return json.loads(_bytes(value))


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        _need(key not in result, "E_DUPLICATE_KEY", "json")
        result[key] = value
    return result


def _load(data):
    _need(len(data) <= MAX_JSON, "E_LIMIT", "json_bytes")
    try:
        value = json.loads(
            data.decode("utf-8"),
            object_pairs_hook=_pairs,
            parse_constant=lambda _: (_ for _ in ()).throw(
                AnchorError("E_NONFINITE", "json")
            ),
        )
        _finite(value)
        return value
    except (ValueError, UnicodeError, RecursionError) as exc:
        if isinstance(exc, AnchorError):
            raise
        raise AnchorError("E_SCHEMA", "json") from None


def _id(prefix, *parts):
    return prefix + "_" + anchor_hash(["world-anchor-id/v1", *parts])


def _decimal(value):
    _need(
        type(value) is str
        and len(value) <= 60
        and re.fullmatch(r"-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?", value),
        path="decimal",
    )
    try:
        number = Decimal(value)
    except InvalidOperation:
        raise AnchorError("E_SCHEMA", "decimal") from None
    _need(
        number.is_finite()
        and len(number.as_tuple().digits) <= 38
        and number.as_tuple().exponent >= -18,
        path="decimal",
    )
    normalized = format(number, "f").rstrip("0").rstrip(".") if "." in value else value
    if number == 0:
        normalized = "0"
    _need(value == normalized, path="canonical_decimal")
    return number


def _numeric_tokens(text):
    """Plain complete numbers only; terminal punctuation is not a decimal part.

    Consume scientific tokens as a whole and exclude them, so their exponent
    cannot reappear as an apparently independent quantity. No partial dotted
    version, embedded word, leading-dot fraction or signed suffix is admitted.
    """
    pattern = r"(?<![\w.+-])(?P<number>[-+]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?)(?P<exponent>[eE][-+]?\d+)?(?!\w|\.[\w.])"
    return {
        Decimal(match.group("number").replace(",", ""))
        for match in re.finditer(pattern, text)
        if match.group("exponent") is None
    }


def _value(value):
    _need(type(value) is dict and "kind" in value, path="value")
    kind = value["kind"]
    if kind == "range":
        _object(value, "kind low high")
        _need(_decimal(value["low"]) <= _decimal(value["high"]), path="range")
    else:
        _object(value, "kind value")
        if kind == "number":
            _decimal(value["value"])
        elif kind == "boolean":
            _need(type(value["value"]) is bool, path="boolean")
        elif kind == "text":
            _text(value["value"], 8192)
        else:
            raise AnchorError("E_SCHEMA", "value_kind")
    return value


def _instant(value):
    _need(
        type(value) is str and re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", value),
        path="instant",
    )
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc
        )
    except ValueError:
        raise AnchorError("E_SCHEMA", "instant") from None


def _unknown_time():
    return {"value": None, "precision": "unknown", "basis_ref_ids": []}


def _time(value):
    _object(value, "value precision basis_ref_ids")
    _list(value["basis_ref_ids"], 64)
    if value["precision"] == "unknown":
        _need(value["value"] is None, path="unknown_time")
        return None
    _need(value["precision"] in {"day", "second"}, path="time_precision")
    result = _instant(value["value"])
    return (
        result.replace(hour=23, minute=59, second=59)
        if value["precision"] == "day"
        else result
    )


def _period(value):
    _object(value, "start end granularity")
    try:
        first, last = (
            date.fromisoformat(value["start"]),
            date.fromisoformat(value["end"]),
        )
    except (ValueError, TypeError):
        raise AnchorError("E_SCHEMA", "period") from None
    _need(
        first <= last
        and value["granularity"] in {"day", "month", "quarter", "year", "interval"},
        path="period",
    )


def _unit(value):
    _object(value, "id dimension scale currency price_basis base_period")
    _text(value["id"])
    _text(value["dimension"])
    _need(_decimal(value["scale"]) > 0, path="scale")
    _need(
        value["price_basis"] in {"nominal", "real", "not_applicable", "unknown"},
        path="price_basis",
    )
    if value["currency"] is not None:
        _text(value["currency"])
    if value["base_period"] is not None:
        _period(value["base_period"])


def _identity(value):
    _object(
        value, "entity_id metric_id denominator_id geography_id unit reference_period"
    )
    for key in ("entity_id", "metric_id"):
        _text(value[key])
    for key in ("denominator_id", "geography_id"):
        if value[key] is not None:
            _text(value[key])
    _unit(value["unit"])
    _period(value["reference_period"])


def _scope(value):
    _object(value, "run_id research_generation_id snapshot_id authority cutoff horizon")
    for key in ("run_id", "research_generation_id", "snapshot_id"):
        _text(value[key])
    _need(
        value["authority"] in {"legacy-kiq-v1", "target-first-v1"},
        "E_SCOPE",
        "authority",
    )
    _instant(value["cutoff"])
    _period(value["horizon"])


def _audience(value):
    _object(value, "kind actor_refs")
    _list(value["actor_refs"], 512)
    _need(value["kind"] in {"public", "actors", "analyst"}, "E_PRIVACY", "audience")
    _need(
        value["actor_refs"] == sorted(set(value["actor_refs"])),
        "E_PRIVACY",
        "audience_ids",
    )
    _need(
        bool(value["actor_refs"]) == (value["kind"] == "actors"),
        "E_PRIVACY",
        "audience_ids",
    )


def _path(value):
    _text(value, 512)
    _need(
        not value.startswith("/")
        and not any(c in value for c in ("\\", "\0", ":"))
        and all(part not in {"", ".", ".."} for part in value.split("/")),
        "E_PATH",
        "relative_path",
    )
    return value.split("/")


def _read(root, relative, limit):
    parts = _path(relative)
    fd = None
    try:
        fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        for part in parts[:-1]:
            child = os.open(
                part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd
            )
            os.close(fd)
            fd = child
        child = os.open(
            parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd
        )
        os.close(fd)
        fd = child
        info = os.fstat(fd)
        _need(stat.S_ISREG(info.st_mode), "E_PATH", "regular_file")
        _need(info.st_size <= limit, "E_LIMIT", "file_bytes")
        data = bytearray()
        while chunk := os.read(fd, min(65536, limit + 1 - len(data))):
            data.extend(chunk)
            _need(len(data) <= limit, "E_LIMIT", "file_bytes")
        return bytes(data)
    except OSError as exc:
        raise AnchorError(
            "E_FILE_MISSING" if exc.errno == 2 else "E_PATH", relative
        ) from None
    finally:
        if fd is not None:
            os.close(fd)


def _pointer(value, pointer):
    _need(
        type(pointer) is str and (pointer == "" or pointer.startswith("/")),
        "E_REFERENCE",
        "pointer",
    )
    try:
        for part in pointer.split("/")[1:]:
            _need(not re.search(r"~(?![01])", part), "E_REFERENCE", "pointer")
            part = part.replace("~1", "/").replace("~0", "~")
            if type(value) is list:
                _need(re.fullmatch(r"0|[1-9][0-9]*", part), "E_REFERENCE", "index")
                value = value[int(part)]
            else:
                value = value[part]
        return value
    except (KeyError, IndexError, TypeError):
        raise AnchorError("E_REFERENCE", "pointer") from None


def _gap(code, requirement_id=None, related=(), engines=()):
    return {
        "gap_id": _id("gap", requirement_id, code, sorted(related)),
        "requirement_id": requirement_id,
        "code": code,
        "related_ids": sorted(related),
        "blocking_engines": sorted(engines),
        "detail": code,
    }


TERM_FIELDS = "origin_pointer kind identity actor_ref value_type accepted_value_kinds accepted_evidence priority required consumers dependency_origins assumption_policy_id"
CONTRACT_FIELDS = "schema_version scope authority_artifact_id authority_artifact_hash authority_pointer authority_kind settlement aliases terms mechanisms identities actors calendar hazards indicators reference_classes"
SPEC_FIELDS = {
    "mechanisms": "mechanism_id template template_version input_node_ids output_node_id parameters lag_requirement_origin applicability_requirement_origins consumers",
    "identities": "identity_id lhs_node_id rhs_mechanism_id absolute_tolerance relative_tolerance scale_unit basis_requirement_origin",
    "actors": "actor_ref registry_artifact_id registry_pointer statements authority plans red_lines",
    "calendar": "event_id requirement_origin classification time_requirement_origin effect_requirement_origins",
    "hazards": "hazard_id trigger likelihood_requirement_origin effect_requirement_origins recurrence_requirement_origin consumers",
    "indicators": "indicator_id node_id requirement_origin consumer trigger",
    "reference_classes": "reference_class_id membership_requirement_origins observation_ids purpose",
}


RESEARCH_KINDS = frozenset(
    {
        "actor_objective",
        "actor_incentive",
        "actor_constraint",
        "actor_capability",
        "actor_information",
        "actor_decision_process",
        "actor_authority",
        "actor_belief",
        "red_line",
        "actor_plan",
        "actor_relationship",
        "actor_track_record",
        "actor_statement",
        "calendar_event",
        "event",
        "hazard",
        "indicator",
        "reference_class",
        "research_note",
    }
)


def _research_inventory_contract(contract):
    _need(
        contract["settlement"] is None
        and not contract["mechanisms"]
        and not contract["identities"],
        "E_CONTRACT",
        "research_inventory_no_execution",
    )
    origins = {r["origin_pointer"] for r in contract["terms"]}
    for term in contract["terms"]:
        _need(
            term["kind"] in RESEARCH_KINDS
            and term["identity"] is None
            and term["value_type"] == "text"
            and term["assumption_policy_id"] is None
            and all(c["role"] == "research_note" for c in term["consumers"]),
            "E_CONTRACT",
            "research_note",
        )
    for actor in contract["actors"]:
        _need(
            not actor["authority"]
            and not actor["plans"]
            and not actor["red_lines"]
            and set(actor["statements"]) <= origins,
            "E_CONTRACT",
            "research_actor",
        )
    for event in contract["calendar"]:
        _need(
            not event["effect_requirement_origins"]
            and event["requirement_origin"] in origins
            and event["time_requirement_origin"] in origins
            and event["classification"] in {"scheduled", "intention", "historical"},
            "E_CONTRACT",
            "research_calendar",
        )
    for hazard in contract["hazards"]:
        _need(
            hazard["trigger"] is None
            and not hazard["effect_requirement_origins"]
            and all(
                hazard[k] is None or hazard[k] in origins
                for k in (
                    "likelihood_requirement_origin",
                    "recurrence_requirement_origin",
                )
            )
            and all(c["role"] == "research_note" for c in hazard["consumers"]),
            "E_CONTRACT",
            "research_hazard",
        )
    for indicator in contract["indicators"]:
        _need(
            indicator["trigger"] is None
            and indicator["requirement_origin"] in origins
            and indicator["consumer"]["role"] == "research_note",
            "E_CONTRACT",
            "research_indicator",
        )
    for reference in contract["reference_classes"]:
        _need(
            reference["purpose"] == "diagnostic"
            and not reference["observation_ids"]
            and set(reference["membership_requirement_origins"]) <= origins,
            "E_CONTRACT",
            "research_reference_class",
        )


def requirements_from_contract(contract, *, scope):
    _scope(scope)
    result = {
        "schema_version": "world-anchor-requirements/v1",
        "scope": _copy(scope),
        "contract_hash": None,
        "contract": None,
        "requirements": [],
        "gaps": [],
    }
    if contract is None:
        result["gaps"] = [_gap("missing_contract", engines=ENGINES)]
        return result
    _finite(contract)
    _object(contract, CONTRACT_FIELDS)
    _need(contract["schema_version"] == "world-anchor-contract/v1", "E_VERSION")
    _need(contract["scope"] == scope, "E_SCOPE")
    _hash(contract["authority_artifact_hash"])
    _need(
        contract["authority_kind"]
        in {"admitted_contract", "reviewed_fixture", "research_inventory"},
        "E_CONTRACT",
    )
    inventory_only = contract["authority_kind"] == "research_inventory"
    if not inventory_only:
        _object(
            contract["settlement"],
            "target_node_id identity authority_artifact_id pointer",
        )
        _identity(contract["settlement"]["identity"])
    for rows, fields in SPEC_FIELDS.items():
        for row in _list(contract[rows], 512):
            _object(row, fields)
    for row in _list(contract["aliases"]):
        _object(row, "field canonical_id literal artifact_id artifact_hash pointer")
        _hash(row["artifact_hash"])
    digest, origins = anchor_hash(contract), {}
    for term in _list(contract["terms"], 1024):
        _need(type(term) is dict, "E_CONTRACT", "requirement")
        _object(term, TERM_FIELDS + (" cardinality" if "cardinality" in term else ""))
        cardinality = term.get("cardinality", "one")
        _need(
            type(cardinality) is str and cardinality in {"one", "many"},
            "E_CONTRACT",
            "cardinality",
        )
        _need(
            cardinality != "many" or term["value_type"] == "text",
            "E_CONTRACT",
            "collection_value_type",
        )
        _text(term["origin_pointer"], 512)
        _need(term["origin_pointer"] not in origins, "E_CONTRACT", "duplicate_origin")
        _need(
            type(term["required"]) is bool
            and type(term["priority"]) is int
            and term["priority"] in (0, 1, 2),
            "E_CONTRACT",
        )
        _need(
            term["value_type"] in {"number", "range", "text", "boolean"}, "E_CONTRACT"
        )
        _need(set(term["accepted_value_kinds"]) <= VALUE_KINDS, "E_CONTRACT")
        _need(term["consumers"], "E_CONTRACT", "consumer")
        for consumer in _list(term["consumers"]):
            _object(consumer, "engine role object_id field")
            _need(consumer["engine"] in ENGINES, "E_CONTRACT")
            _need(
                cardinality != "many"
                or consumer["role"] not in {"initial_state", "compiler_parameter"},
                "E_CONTRACT",
                "collection_scalar_consumer",
            )
        if term["identity"] is not None:
            _identity(term["identity"])
        elif term["value_type"] in {"number", "range"}:
            raise AnchorError("E_CONTRACT", "numeric_identity")
        rid = _id(
            "req",
            digest,
            term["origin_pointer"],
            term["kind"],
            term["identity"],
            term["consumers"],
        )
        origins[term["origin_pointer"]] = rid
    targets = [t for t in contract["terms"] if t["kind"] == "target_definition"]
    if inventory_only:
        _research_inventory_contract(contract)
        result["gaps"] = [_gap("missing_contract", engines=ENGINES)]
    else:
        _need(
            len(targets) == 1
            and targets[0]["identity"] == contract["settlement"]["identity"],
            "E_CONTRACT",
            "target",
        )
    for term in contract["terms"]:
        _need(
            all(p in origins for p in term["dependency_origins"]),
            "E_CONTRACT",
            "dependency",
        )
        result["requirements"].append(
            {
                **_copy(term),
                "requirement_id": origins[term["origin_pointer"]],
                "dependency_ids": sorted(
                    origins[p] for p in term["dependency_origins"]
                ),
            }
        )
    pending = {
        r["requirement_id"]: set(r["dependency_ids"]) for r in result["requirements"]
    }
    done = set()
    while pending:
        ready = {rid for rid, deps in pending.items() if deps <= done}
        _need(ready, "E_CONTRACT", "dependency_cycle")
        done.update(ready)
        pending = {rid: deps for rid, deps in pending.items() if rid not in ready}
    result.update(
        contract_hash=digest,
        contract=_copy(contract),
        requirements=sorted(result["requirements"], key=lambda r: r["requirement_id"]),
    )
    return result


def _policy(policy):
    _object(
        policy,
        "schema_version admission_version limits_version selection_version prior_rules conversions review_profile consumer_rules",
    )
    _need(
        policy["schema_version"] == "world-anchor-policy/v1"
        and policy["admission_version"] == "explicit-support/v1"
        and policy["limits_version"] == "world-anchor-limits/v1"
        and policy["selection_version"] == "exact-identity-lexical/v1",
        "E_VERSION",
    )
    _object(
        policy["review_profile"],
        "profile_id extraction_prompt_version review_prompt_version qualification_artifact_id qualification_artifact_hash",
    )
    for row in policy["consumer_rules"]:
        _object(row, "engine adapter_version role object_id field template_versions")
    for row in policy["conversions"]:
        _object(
            row,
            "conversion_id from_unit to_unit factor offset artifact_id artifact_hash pointer",
        )
        _unit(row["from_unit"])
        _unit(row["to_unit"])
        _decimal(row["factor"])
        _decimal(row["offset"])
        _need(
            all(
                row["from_unit"][k] == row["to_unit"][k]
                for k in ("dimension", "currency", "price_basis", "base_period")
            ),
            "E_CONTRACT",
            "conversion",
        )
    for row in policy["prior_rules"]:
        _object(
            row,
            "policy_id artifact_id artifact_hash pointer requirement_origins value identity rationale library_version",
        )
        _value(row["value"])
        _identity(row["identity"])
    _finite(policy)


class EvidenceIndex:
    """Issued only after explicit safe reads; views cannot mutate authentication."""

    __slots__ = ("_data", "_files", "_review_pins", "_producer_handles")

    def __init__(self, key, data, files, review_pins=None, producer_handles=None):
        _need(key is _KEY, "E_REFERENCE", "index_constructor")
        object.__setattr__(self, "_data", _bytes(data))
        object.__setattr__(self, "_files", MappingProxyType(dict(files)))
        object.__setattr__(
            self, "_review_pins", MappingProxyType(dict(review_pins or {}))
        )
        handles = dict(producer_handles or {})
        handles.update({h.manifest_hash: h for h in (review_pins or {}).values()})
        object.__setattr__(self, "_producer_handles", MappingProxyType(handles))

    def __setattr__(self, name, value):
        raise AnchorError("E_IMMUTABLE", "index")

    def snapshot(self):
        return _load(self._data)

    def artifact_bytes(self, artifact_id):
        _need(artifact_id in self._files, "E_REFERENCE", "artifact_id")
        return self._files[artifact_id]


def _context(index, requirements=None, policy=None):
    _need(type(index) is EvidenceIndex, "E_REFERENCE", "authenticated_index")
    data = index.snapshot()
    if requirements is not None:
        _need(
            data["requirements_hash"] == anchor_hash(requirements),
            "E_HASH",
            "requirements",
        )
    if policy is not None:
        _need(data["policy_hash"] == anchor_hash(policy), "E_HASH", "policy")
    return data


def _evidence_digest(data):
    return anchor_hash(
        {k: data[k] for k in ("input_hash", "requirements_hash", "policy_hash")}
        | {
            "proposal_hashes": sorted(
                anchor_hash(x) for x in data["evidence_proposals"]
            ),
            "review_receipt_hashes": sorted(
                anchor_hash(x) for x in data["review_receipts"]
            ),
            # Container inventory is sealed separately. Keep this legacy digest
            # slot empty so attaching accounting proof cannot change semantics.
            "producer_manifest_hashes": [],
        }
    )


def _source_tier(row):
    """Metadata uncertainty overrides legacy tiers without domain inference."""
    if (
        row.get("source_metadata_status") in {"conflict", "unknown"}
        or row.get("source_metadata_overflow") is True
    ):
        return "unknown"
    tier = row["evidence_tier"] if "evidence_tier" in row else row.get("tier")
    return tier if tier in {"primary", "secondary", "social"} else "unknown"


def index_snapshot(
    root, manifest, *, expected_manifest_hash, expected_scope, requirements, policy
):
    _scope(expected_scope)
    _policy(policy)
    _need(anchor_hash(manifest) == _hash(expected_manifest_hash), "E_HASH", "manifest")
    _object(
        manifest,
        "schema_version scope parent_manifest_hash artifacts tracks crosswalk omissions",
    )
    _need(manifest["schema_version"] == "world-anchor-input/v1", "E_VERSION")
    _need(manifest["scope"] == expected_scope == requirements["scope"], "E_SCOPE")
    _need(
        requirements
        == requirements_from_contract(requirements["contract"], scope=expected_scope),
        "E_CONTRACT",
    )
    files, artifacts, total = {}, {}, 0
    for item in _list(manifest["artifacts"], 4096):
        _object(item, "artifact_id track_id path sha256 bytes encoding role")
        aid = _text(item["artifact_id"])
        _need(aid not in files, "E_REFERENCE", "duplicate_artifact")
        _integer(item["bytes"], MAX_PAGE)
        total += item["bytes"]
        _need(total <= MAX_TOTAL, "E_LIMIT", "snapshot_bytes")
        data = _read(
            root, item["path"], MAX_PAGE if item["role"] == "page" else MAX_JSON
        )
        _need(
            len(data) == item["bytes"]
            and hashlib.sha256(data).hexdigest() == _hash(item["sha256"]),
            "E_HASH",
            aid,
        )
        if item["encoding"] == "utf8_json":
            _load(data)
        else:
            _need(item["encoding"] in {"utf8_text", "binary"}, "E_SCHEMA")
        files[aid], artifacts[aid] = data, item
    contract = requirements["contract"]
    if contract:
        aid = contract["authority_artifact_id"]
        _need(
            aid in files
            and artifacts[aid]["sha256"] == contract["authority_artifact_hash"],
            "E_CONTRACT",
            "authority",
        )
        authority = _pointer(_load(files[aid]), contract["authority_pointer"])
        _need(
            type(authority) is dict and authority.get("terms") == contract["terms"],
            "E_CONTRACT",
            "authority_terms",
        )
        _need(
            authority.get("settlement")
            == (
                None
                if contract["authority_kind"] == "research_inventory"
                else contract["settlement"]["identity"]
            ),
            "E_CONTRACT",
            "authority_settlement",
        )
        for section in (*SPEC_FIELDS, "aliases"):
            _need(
                authority.get(section, []) == contract[section],
                "E_CONTRACT",
                "authority_" + section,
            )
    result = {
        "schema_version": "world-anchor-index/v1",
        "scope": _copy(expected_scope),
        "input_hash": expected_manifest_hash,
        "requirements_hash": anchor_hash(requirements),
        "policy_hash": anchor_hash(policy),
        "evidence_hash": "",
        "evidence_proposals": [],
        "review_receipts": [],
        "producer_manifest_hashes": [],
        "manifest": _copy(manifest),
        "sources": [],
        "references": [],
        "inventory": [],
        "observations": [],
        "gaps": [],
    }
    track_ids = set()
    for track in _list(manifest["tracks"], 4096):
        _object(
            track,
            "track_id adapter ledger_artifact_id kiq_artifact_ids quantitative_artifact_id timeline_artifact_id actor_artifact_id case_artifact_id supporting_artifact_ids",
        )
        tid = _text(track["track_id"])
        for field in ("kiq_artifact_ids", "supporting_artifact_ids"):
            for aid in _list(track[field], 4096):
                _need(aid in files, "E_REFERENCE", "track_artifact")
        for field in (
            "quantitative_artifact_id",
            "timeline_artifact_id",
            "actor_artifact_id",
            "case_artifact_id",
        ):
            _need(
                track[field] is None or track[field] in files,
                "E_REFERENCE",
                "track_artifact",
            )
        _need(tid not in track_ids, "E_REFERENCE", "duplicate_track")
        track_ids.add(tid)
        _need(
            track["adapter"]
            == (
                "legacy-kiq/v1"
                if expected_scope["authority"] == "legacy-kiq-v1"
                else "target-case/v1"
            ),
            "E_SCOPE",
            "adapter",
        )
        lid = track["ledger_artifact_id"]
        _need(lid in files, "E_REFERENCE", "ledger")
        ledger = _load(files[lid])
        _list(ledger, 4096)
        sid_map = {}
        for i, row in enumerate(ledger):
            _need(
                type(row) is dict and type(row.get("sid")) is int and row["sid"] > 0,
                "E_SCHEMA",
                "ledger_sid",
            )
            _need(type(row.get("fetched", False)) is bool, "E_SCHEMA", "fetched")
            sid = str(row.get("sid", ""))
            _need(sid and sid not in sid_map, "E_REFERENCE", "ledger_sid")
            skey = _id("source", expected_scope, tid, lid, f"/{i}")
            sid_map[sid] = skey
            page = None
            if row.get("fetched") and row.get("page_path"):
                relative = "/".join(
                    artifacts[lid]["path"].split("/")[:-1] + _path(row["page_path"])
                )
                matches = [
                    a
                    for a in artifacts.values()
                    if a["path"] == relative and a["track_id"] == tid
                ]
                _need(len(matches) <= 1, "E_REFERENCE", "page_path")
                page = matches[0] if matches else None
                if page:
                    _need(
                        page["sha256"] == row.get("content_sha256"),
                        "E_HASH",
                        "ledger_page",
                    )
            source = {
                "source_key": skey,
                "track_id": tid,
                "ledger_artifact_id": lid,
                "ledger_pointer": f"/{i}",
                "local_source_id": sid,
                "url": row.get("url"),
                "title": row.get("title"),
                "content_artifact_id": page["artifact_id"] if page else None,
                "content_hash": page["sha256"] if page else None,
                "retention": "fetched_page"
                if page
                else "snippet_only"
                if row.get("snippet")
                else "missing",
                "tier": _source_tier(row),
                **{
                    k: _unknown_time()
                    for k in (
                        "published_at",
                        "available_at",
                        "retrieved_at",
                        "retained_at",
                    )
                },
                "capture": {
                    "kind": "content" if page else "unknown",
                    "retained_bytes_complete": bool(page),
                    "remote_document_complete": None,
                    "ends_mid_table": False,
                },
                "audience": _copy(
                    row.get("audience", {"kind": "public", "actor_refs": []})
                ),
            }
            _audience(source["audience"])
            if page and row.get("fetched_at"):
                try:
                    _instant(row["fetched_at"])
                    ref = _json_ref(
                        expected_scope,
                        source,
                        lid,
                        artifacts[lid]["sha256"],
                        f"/{i}/fetched_at",
                        row["fetched_at"],
                    )
                    result["references"].append(ref)
                    source["retrieved_at"] = {
                        "value": row["fetched_at"],
                        "precision": "second",
                        "basis_ref_ids": [ref["ref_id"]],
                    }
                except AnchorError:
                    result["gaps"].append(_gap("unknown_availability", related=[skey]))
            if page and re.search(
                rb"(?i)(?:<title>[^<]*404|404\s+(?:not found|error))",
                files[page["artifact_id"]],
            ):
                source["capture"]["kind"] = "error_page"
                result["gaps"].append(_gap("retrieval_error_page", related=[skey]))
            if not page:
                result["gaps"].append(_gap("missing_page", related=[skey]))
            result["sources"].append(source)

        def inventory(aid, rows, prefix, origin, kiq=None):
            _need(
                aid in files and artifacts[aid]["track_id"] == tid,
                "E_REFERENCE",
                "track_artifact",
            )
            for j, row in enumerate(_list(rows)):
                pointer = prefix + "/" + str(j)
                is_case = origin in {"case_claim", "case_node"}
                sids = (
                    row.get("sourceIds" if is_case else "sids", [])
                    if type(row) is dict
                    else []
                )
                valid_sids = type(sids) is list and all(
                    type(sid) is str and re.fullmatch(r"S[1-9][0-9]*", sid)
                    if is_case
                    else type(sid) is int and sid > 0
                    for sid in sids
                )
                if not valid_sids:
                    keys = []
                elif not is_case:
                    # KIQs retain integer ledger IDs even on a target-case track.
                    # Neither bools nor prefixed/string IDs acquire this join.
                    keys = (
                        sorted({sid_map[str(sid)] for sid in sids})
                        if all(str(sid) in sid_map for sid in sids)
                        else []
                    )
                else:
                    keys = []
                    for cross in manifest["crosswalk"]:
                        if (
                            cross.get("namespace") != "target_source_id"
                            or cross.get("track_id") != tid
                            or cross.get("external_id") not in sids
                        ):
                            continue
                        source = next(
                            (
                                s
                                for s in result["sources"]
                                if s["source_key"] == cross.get("source_key")
                                and s["track_id"] == tid
                            ),
                            None,
                        )
                        _need(
                            source is not None and cross["artifact_id"] in files,
                            "E_REFERENCE",
                            "target_crosswalk",
                        )
                        endpoint = _pointer(
                            _load(files[cross["artifact_id"]]), cross["pointer"]
                        )
                        if (
                            isinstance(endpoint, dict)
                            and endpoint.get("sourceId") == cross["external_id"]
                            and endpoint.get("url") == source["url"]
                            and source["content_hash"]
                            and endpoint.get("content_sha256") == source["content_hash"]
                        ):
                            keys.append(source["source_key"])
                        else:
                            result["gaps"].append(
                                _gap("ambiguous_source", related=[source["source_key"]])
                            )
                    keys = sorted(set(keys))
                cid = _id(
                    "claim", expected_scope, aid, artifacts[aid]["sha256"], pointer
                )
                result["inventory"].append(
                    {
                        "claim_id": cid,
                        "artifact_id": aid,
                        "pointer": pointer,
                        "raw_hash": anchor_hash(row),
                        "origin": origin,
                        "kiq_id": kiq,
                        "fact_index": j if kiq else None,
                        "upstream_claim_id": row.get("claimId")
                        if isinstance(row, dict)
                        else None,
                        "source_keys": keys,
                        "ref_ids": [],
                        "observation_ids": [],
                        "disposition": "indexed"
                        if keys
                        else "missing_provenance"
                        if valid_sids
                        else "unsupported",
                        "reason_code": None
                        if keys
                        else "missing_provenance"
                        if valid_sids
                        else "unsupported_shape",
                    }
                )

        for aid in track["kiq_artifact_ids"]:
            raw = _load(files[aid])
            _need(
                type(raw) is dict and type(raw.get("facts")) is list,
                "E_SCHEMA",
                "kiq_facts",
            )
            inventory(aid, raw["facts"], "/facts", "kiq_fact", raw.get("id", aid))
        if track["quantitative_artifact_id"]:
            aid = track["quantitative_artifact_id"]
            raw = _load(files[aid])
            _need(
                type(raw) is list
                or (type(raw) is dict and type(raw.get("quantitative_facts")) is list),
                "E_SCHEMA",
                "quantitative_shape",
            )
            inventory(
                aid,
                raw if isinstance(raw, list) else raw["quantitative_facts"],
                "" if isinstance(raw, list) else "/quantitative_facts",
                "legacy_quant" if track["adapter"] == "legacy-kiq/v1" else "case_node",
            )
        if track["timeline_artifact_id"]:
            aid = track["timeline_artifact_id"]
            raw = _load(files[aid])
            _need(
                type(raw) is list
                or (type(raw) is dict and type(raw.get("timeline")) is list),
                "E_SCHEMA",
                "timeline_shape",
            )
            inventory(
                aid,
                raw if isinstance(raw, list) else raw["timeline"],
                "" if isinstance(raw, list) else "/timeline",
                "legacy_timeline",
            )
        if track["actor_artifact_id"]:
            aid = track["actor_artifact_id"]
            raw = _load(files[aid])
            _need(
                isinstance(raw, dict) and isinstance(raw.get("actors"), list),
                "E_SCHEMA",
                "actor_wrapper",
            )
            inventory(aid, raw["actors"], "/actors", "actor_item")
        if track["case_artifact_id"]:
            aid = track["case_artifact_id"]
            raw = _load(files[aid])
            _need(raw.get("schemaVersion") == "forecast-case/v1", "E_VERSION", "case")
            inventory(aid, raw["claims"], "/claims", "case_claim")
    # Inventory official JSON without the permissive application loader. Every
    # manifest member must resolve, even rows that a legacy loader would omit.
    admitted_official = set()
    for mid, meta in artifacts.items():
        if meta["role"] != "official_manifest":
            continue
        official = _load(files[mid])
        _need(
            type(official) is dict
            and official.get("schema_version") == 1
            and type(official.get("series")) is list,
            "E_SCHEMA",
            "official_manifest",
        )
        for ordinal, entry in enumerate(official["series"]):
            _need(type(entry) is dict, "E_SCHEMA", "official_entry")
            members = {}
            for field, hash_field in (("file", "sha256"), ("csv", "csv_sha256")):
                _path(entry.get(field))
                matches = [
                    a
                    for a in artifacts.values()
                    if a["track_id"] == meta["track_id"]
                    and (
                        a["path"] == entry[field]
                        or a["path"].endswith("/" + entry[field])
                    )
                ]
                _need(
                    len(matches) == 1 and matches[0]["sha256"] == entry.get(hash_field),
                    "E_HASH",
                    "official_member",
                )
                members[field] = matches[0]
            artifact = members["file"]
            aid = artifact["artifact_id"]
            _need(
                aid not in admitted_official and artifact["role"] == "official_series",
                "E_REFERENCE",
                "official_series",
            )
            admitted_official.add(aid)
            raw = _load(files[aid])
            _need(
                type(raw) is dict and type(raw.get("observations")) is list,
                "E_SCHEMA",
                "official_observations",
            )
            for key in (
                "series",
                "provider",
                "units",
                "frequency",
                "seasonal_adjustment",
                "transform",
                "source_url",
                "api_url",
                "geography",
                "vintage",
                "projection_from",
            ):
                _need(
                    entry.get(key, "") == raw.get(key, ""),
                    "E_REFERENCE",
                    "official_metadata",
                )
            _text(artifact["track_id"])
            skey = _id(
                "source",
                expected_scope,
                artifact["track_id"],
                mid,
                f"/series/{ordinal}",
            )
            source = {
                "source_key": skey,
                "track_id": artifact["track_id"],
                "ledger_artifact_id": mid,
                "ledger_pointer": f"/series/{ordinal}",
                "local_source_id": raw["series"],
                "url": raw.get("source_url"),
                "title": raw.get("title"),
                "content_artifact_id": aid,
                "content_hash": artifact["sha256"],
                "retention": "official_row",
                "tier": "primary",
                **{
                    k: _unknown_time()
                    for k in (
                        "published_at",
                        "available_at",
                        "retrieved_at",
                        "retained_at",
                    )
                },
                "capture": {
                    "kind": "content",
                    "retained_bytes_complete": True,
                    "remote_document_complete": None,
                    "ends_mid_table": False,
                },
                "audience": {"kind": "public", "actor_refs": []},
            }
            if raw.get("retrieved_at"):
                try:
                    _instant(raw["retrieved_at"])
                    ref = _json_ref(
                        expected_scope,
                        source,
                        aid,
                        artifact["sha256"],
                        "/retrieved_at",
                        raw["retrieved_at"],
                    )
                    result["references"].append(ref)
                    source["retrieved_at"] = {
                        "value": raw["retrieved_at"],
                        "precision": "second",
                        "basis_ref_ids": [ref["ref_id"]],
                    }
                except AnchorError:
                    result["gaps"].append(_gap("unknown_availability", related=[skey]))
            result["sources"].append(source)
            seen_dates = set()
            for j, observation in enumerate(raw["observations"]):
                _object(observation, "date value flag")
                _need(
                    observation["date"] not in seen_dates,
                    "E_REFERENCE",
                    "duplicate_official_period",
                )
                seen_dates.add(observation["date"])
                pointer = f"/observations/{j}"
                cid = _id("claim", expected_scope, aid, artifact["sha256"], pointer)
                result["inventory"].append(
                    {
                        "claim_id": cid,
                        "artifact_id": aid,
                        "pointer": pointer,
                        "raw_hash": anchor_hash(observation),
                        "origin": "official_observation",
                        "kiq_id": None,
                        "fact_index": None,
                        "upstream_claim_id": None,
                        "source_keys": [skey],
                        "ref_ids": [],
                        "observation_ids": [],
                        "disposition": "indexed",
                        "reason_code": None,
                    }
                )
    _need(
        admitted_official
        == {aid for aid, a in artifacts.items() if a["role"] == "official_series"},
        "E_REFERENCE",
        "unmanifested_official_series",
    )
    for aid, meta in artifacts.items():
        if meta["role"] != "capture_metadata":
            continue
        capture_rows = _load(files[aid])
        _need(
            type(capture_rows) is dict and type(capture_rows.get("rows")) is list,
            "E_SCHEMA",
            "capture_metadata",
        )
        for row in capture_rows["rows"]:
            matches = [
                source
                for source in result["sources"]
                if source["track_id"] == row.get("track")
                and source["local_source_id"] == str(row.get("sid"))
            ]
            if not matches:
                continue
            source = matches[0]
            _need(
                row.get("sha256") == source["content_hash"],
                "E_HASH",
                "capture_metadata",
            )
            source["capture"]["ends_mid_table"] = row.get("ends_mid_table") is True
            source["capture"]["remote_document_complete"] = (
                row.get("complete_remote_document")
                if type(row.get("complete_remote_document")) is bool
                else None
            )
            if source["capture"]["ends_mid_table"]:
                result["gaps"].append(
                    _gap("partial_capture", related=[source["source_key"]])
                )
    _need(len(result["inventory"]) <= 20000, "E_LIMIT", "inventory")
    for omission in manifest["omissions"]:
        _object(omission, "artifact_id track_id pointer reason declared_count")
        result["gaps"].append(
            _gap(
                "inventory_omission",
                related=[omission["artifact_id"]] if omission["artifact_id"] else [],
            )
        )
    for cross in manifest["crosswalk"]:
        _object(
            cross,
            "crosswalk_id source_key namespace external_id track_id artifact_id pointer proof_ref_ids",
        )
        _need(
            any(
                s["source_key"] == cross["source_key"]
                and s["track_id"] == cross["track_id"]
                for s in result["sources"]
            ),
            "E_REFERENCE",
            "crosswalk",
        )
        _need(cross["artifact_id"] in files, "E_REFERENCE", "crosswalk_artifact")
        _pointer(_load(files[cross["artifact_id"]]), cross["pointer"])
    result["evidence_hash"] = _evidence_digest(result)
    return EvidenceIndex(_KEY, result, files)


def _json_ref(scope, source, aid, digest, pointer, value):
    locator = {
        "kind": "json_value",
        "pointer": pointer,
        "value_hash": anchor_hash(value),
    }
    return {
        "ref_id": _id("ref", source["source_key"], digest, locator),
        "source_key": source["source_key"],
        **{k: scope[k] for k in ("run_id", "research_generation_id", "snapshot_id")},
        "track_id": source["track_id"],
        "claim_id": None,
        "kiq_id": None,
        "fact_index": None,
        "artifact_id": aid,
        "content_hash": digest,
        "locator": locator,
    }


def _verify_ref(ref, data, index):
    _object(
        ref,
        "ref_id source_key run_id research_generation_id snapshot_id track_id claim_id kiq_id fact_index artifact_id content_hash locator",
    )
    _need(
        all(
            ref[k] == data["scope"][k]
            for k in ("run_id", "research_generation_id", "snapshot_id")
        ),
        "E_SCOPE",
        "reference",
    )
    sources = {s["source_key"]: s for s in data["sources"]}
    _need(
        ref["source_key"] in sources
        and sources[ref["source_key"]]["track_id"] == ref["track_id"],
        "E_REFERENCE",
        "source",
    )
    source = sources[ref["source_key"]]
    _need(
        ref["artifact_id"]
        in {source["ledger_artifact_id"], source["content_artifact_id"]},
        "E_REFERENCE",
        "source_artifact",
    )
    raw = index.artifact_bytes(ref["artifact_id"])
    _need(
        hashlib.sha256(raw).hexdigest() == ref["content_hash"],
        "E_HASH",
        "reference_content",
    )
    locator = ref["locator"]
    if ref["artifact_id"] == source["ledger_artifact_id"]:
        prefix = source["ledger_pointer"]
        _need(
            locator.get("kind") == "json_value"
            and (
                locator.get("pointer") == prefix
                or str(locator.get("pointer", "")).startswith(prefix + "/")
            ),
            "E_REFERENCE",
            "ledger_source_span",
        )
    if locator.get("kind") == "text_span":
        _object(locator, "kind start_byte end_byte quote")
        first, last = (
            _integer(locator["start_byte"], MAX_PAGE),
            _integer(locator["end_byte"], MAX_PAGE),
        )
        _need(0 <= first < last <= len(raw), "E_REFERENCE", "span")
        _need(last - first <= 8192, "E_LIMIT", "quote")
        try:
            actual = raw[first:last].decode("utf-8")
        except UnicodeError:
            raise AnchorError("E_REFERENCE", "utf8_span") from None
        _need(actual == locator["quote"], "E_REFERENCE", "quote")
    else:
        _object(locator, "kind pointer value_hash")
        _need(locator["kind"] == "json_value", "E_SCHEMA", "locator")
        actual = _pointer(_load(raw), locator["pointer"])
        _need(anchor_hash(actual) == locator["value_hash"], "E_HASH", "json_value")
    _need(
        ref["ref_id"] == _id("ref", ref["source_key"], ref["content_hash"], locator),
        "E_REFERENCE",
        "ref_id",
    )
    return actual


def availability_from_receipts(source, *, index, cutoff):
    data = _context(index)
    _need(source in data["sources"], "E_REFERENCE", "indexed_source")
    cutoff_value = _instant(cutoff)
    refs = {r["ref_id"]: r for r in data["references"]}
    dates = []
    for field, basis in (
        ("published_at", "published"),
        ("available_at", "available"),
        ("retrieved_at", "retrieved"),
        ("retained_at", "retained"),
    ):
        when = _time(source[field])
        if when is None or not source[field]["basis_ref_ids"]:
            continue
        valid = True
        for rid in source[field]["basis_ref_ids"]:
            ref = refs.get(rid)
            if ref is None or ref["source_key"] != source["source_key"]:
                valid = False
                break
            actual = _verify_ref(ref, data, index)
            if actual != source[field]["value"]:
                valid = False
                break
        if valid and source["content_hash"] is not None:
            dates.append((when, basis, source[field]))
    known = min(dates, key=lambda x: x[0]) if dates else None
    publication = _time(source["published_at"])
    captures = [v[0] for v in dates if v[1] in {"retrieved", "retained"}]
    conflict = publication is not None and captures and min(captures) < publication
    status = (
        "conflict"
        if conflict
        else "unknown"
        if known is None
        else "known_by_cutoff"
        if known[0] <= cutoff_value
        else "after_cutoff"
    )
    return {
        "published_at": _copy(source["published_at"]),
        "available_at": _copy(source["available_at"]),
        "known_by": _copy(known[2]) if known and not conflict else _unknown_time(),
        "cutoff_status": status,
        "basis": known[1] if known and not conflict else "unknown",
        "ref_ids": sorted({r for _, _, t in dates for r in t["basis_ref_ids"]}),
    }


class ProducerReceipts:
    """Authenticated transport artifacts; never constructed from model output."""

    __slots__ = ("_manifest", "_files", "manifest_hash")

    def __init__(self, key, manifest, files, digest):
        _need(key is _KEY, "E_REFERENCE", "receipt_constructor")
        object.__setattr__(self, "_manifest", _bytes(manifest))
        object.__setattr__(self, "_files", MappingProxyType(dict(files)))
        object.__setattr__(self, "manifest_hash", digest)

    def __setattr__(self, name, value):
        raise AnchorError("E_IMMUTABLE", "producer_receipts")

    @property
    def manifest(self):
        return _load(self._manifest)

    def artifact_bytes(self, artifact_id):
        _need(artifact_id in self._files, "E_REFERENCE", "producer_artifact")
        return self._files[artifact_id]


def producer_receipts(root, manifest, *, expected_manifest_hash, expected_scope):
    _scope(expected_scope)
    _object(manifest, "schema_version scope policy_hash files transport_artifact_ids")
    _need(
        manifest["schema_version"] == "world-anchor-producer-receipts/v1", "E_VERSION"
    )
    _need(manifest["scope"] == expected_scope, "E_SCOPE", "producer_scope")
    _need(
        anchor_hash(manifest) == _hash(expected_manifest_hash),
        "E_HASH",
        "producer_manifest",
    )
    _hash(manifest["policy_hash"])
    files = {}
    roles = {}
    total = 0
    for item in _list(manifest["files"], 256):
        _object(item, "artifact_id path sha256 bytes role")
        _need(
            item["role"] in {"raw_response", "transport_receipt", "metering_receipt"}
            and item["artifact_id"] not in files,
            "E_SCHEMA",
            "producer_file",
        )
        raw = _read(root, item["path"], MAX_JSON)
        total += len(raw)
        _need(total <= MAX_TOTAL, "E_LIMIT", "producer_bytes")
        _need(
            len(raw) == item["bytes"]
            and hashlib.sha256(raw).hexdigest() == _hash(item["sha256"]),
            "E_HASH",
            "producer_file",
        )
        _load(raw)
        files[item["artifact_id"]] = raw
        roles[item["artifact_id"]] = item["role"]
    _need(
        set(manifest["transport_artifact_ids"])
        == {aid for aid, role in roles.items() if role == "transport_receipt"}
        and len(set(manifest["transport_artifact_ids"]))
        == len(manifest["transport_artifact_ids"]),
        "E_REFERENCE",
        "transports",
    )
    attempts = set()
    for aid in manifest["transport_artifact_ids"]:
        receipt = _load(files[aid])
        _object(
            receipt,
            "schema_version attempt_id role mode anchor_budget_scope_id profile_id prompt_version input_hash requirements_hash proposal_hash request_hash response_artifact_id response_hash physical_attempts reserved_tokens outcome",
        )
        _need(
            receipt["schema_version"] == "world-anchor-transport/v1"
            and receipt["role"] in {"extraction", "semantic_review"},
            "E_VERSION",
        )
        _need(receipt["attempt_id"] not in attempts, "E_REFERENCE", "duplicate_attempt")
        attempts.add(receipt["attempt_id"])
        _need(receipt["outcome"] == "completed", "E_REFERENCE", "incomplete_review")
        rid = receipt["response_artifact_id"]
        _need(
            roles.get(rid) == "raw_response"
            and hashlib.sha256(files[rid]).hexdigest() == receipt["response_hash"],
            "E_HASH",
            "transport_response",
        )
        for key in ("input_hash", "requirements_hash", "request_hash", "response_hash"):
            _hash(receipt[key])
        _integer(receipt["physical_attempts"], 1)
        _integer(receipt["reserved_tokens"], 150000)
        if receipt["mode"] == "offline_scripted":
            _need(
                receipt["anchor_budget_scope_id"] is None
                and receipt["physical_attempts"] == receipt["reserved_tokens"] == 0,
                "E_BUDGET_RECEIPT",
            )
        else:
            _need(
                receipt["mode"] == "metered"
                and receipt["physical_attempts"] == 1
                and receipt["reserved_tokens"] > 0,
                "E_BUDGET_RECEIPT",
            )
            _text(receipt["anchor_budget_scope_id"])
    return ProducerReceipts(_KEY, manifest, files, expected_manifest_hash)


def _budget_receipt(value, data):
    _object(
        value,
        "schema authorization_sha256 pipeline_id scope_id session_id generation policy_sha256 source_sha256 routes_sha256 retained limits barrier_sha256",
    )
    _need(
        value["schema"] == "anchor-budget-receipt/v1",
        "E_BUDGET_RECEIPT",
        "budget_version",
    )
    _need(value["pipeline_id"] == data["scope"]["run_id"], "E_SCOPE", "budget_pipeline")
    for key in (
        "authorization_sha256",
        "policy_sha256",
        "source_sha256",
        "routes_sha256",
        "barrier_sha256",
    ):
        _hash(value[key])
    _text(value["scope_id"])
    _text(value["session_id"])
    _integer(value["generation"])
    limits = {
        "model_attempt_limit": 20,
        "token_envelope_limit": 150000,
        "catalog_attempt_limit": 8,
        "followup_attempt_limit": 12,
    }
    _object(value["limits"], " ".join(limits))
    for key, limit in limits.items():
        _integer(value["limits"][key], limit)
        _need(
            value["limits"][key] > 0
            if key in {"model_attempt_limit", "token_envelope_limit"}
            else True,
            "E_BUDGET_RECEIPT",
            "budget_limits",
        )
    _object(
        value["retained"],
        "model_attempts token_envelope_units catalog_attempts followup_attempts reserved_max_microusd",
    )
    for key, limit_key in (
        ("model_attempts", "model_attempt_limit"),
        ("token_envelope_units", "token_envelope_limit"),
        ("catalog_attempts", "catalog_attempt_limit"),
        ("followup_attempts", "followup_attempt_limit"),
    ):
        _integer(value["retained"][key], value["limits"][limit_key])
    _integer(value["retained"]["reserved_max_microusd"])
    return value


def _budget_summary(raw, handle, data):
    value = _load(raw)
    _object(
        value,
        "schema_version anchor_budget_scope_id physical_model_attempts reserved_tokens physical_catalog_attempts physical_followup_attempts budget_receipt_artifact_id budget_receipt_hash",
    )
    _need(
        value["schema_version"] == "world-anchor-metering/v1",
        "E_BUDGET_RECEIPT",
        "summary_version",
    )
    aid = value["budget_receipt_artifact_id"]
    _need(
        any(
            f["artifact_id"] == aid and f["role"] == "metering_receipt"
            for f in handle.manifest["files"]
        ),
        "E_BUDGET_RECEIPT",
        "budget_artifact",
    )
    budget_raw = handle.artifact_bytes(aid)
    _need(
        hashlib.sha256(budget_raw).hexdigest() == _hash(value["budget_receipt_hash"]),
        "E_HASH",
        "budget_receipt",
    )
    budget = _budget_receipt(_load(budget_raw), data)
    _need(
        value["anchor_budget_scope_id"] == budget["scope_id"],
        "E_BUDGET_RECEIPT",
        "summary_scope",
    )
    for target, source in (
        ("physical_model_attempts", "model_attempts"),
        ("reserved_tokens", "token_envelope_units"),
        ("physical_catalog_attempts", "catalog_attempts"),
        ("physical_followup_attempts", "followup_attempts"),
    ):
        _need(
            type(value[target]) is int and value[target] == budget["retained"][source],
            "E_BUDGET_RECEIPT",
            "summary_counters",
        )
    return value


def _retained_budget_maxima(handles, data):
    receipts = []
    seen = set()
    for handle in handles.values():
        for artifact in handle.manifest["files"]:
            if artifact["role"] != "metering_receipt" or artifact["sha256"] in seen:
                continue
            value = _load(handle.artifact_bytes(artifact["artifact_id"]))
            if (
                type(value) is dict
                and value.get("schema") == "anchor-budget-receipt/v1"
            ):
                receipts.append(_budget_receipt(value, data))
                seen.add(artifact["sha256"])
    if not receipts:
        return None
    immutable = (
        "authorization_sha256",
        "pipeline_id",
        "scope_id",
        "policy_sha256",
        "source_sha256",
        "routes_sha256",
        "limits",
    )
    first = receipts[0]
    fields = (
        "model_attempts",
        "token_envelope_units",
        "catalog_attempts",
        "followup_attempts",
        "reserved_max_microusd",
    )
    for i, receipt in enumerate(receipts):
        _need(
            all(receipt[k] == first[k] for k in immutable),
            "E_BUDGET_RECEIPT",
            "immutable_budget_authority",
        )
        for other in receipts[:i]:
            earlier = all(
                receipt["retained"][k] <= other["retained"][k] for k in fields
            )
            later = all(receipt["retained"][k] >= other["retained"][k] for k in fields)
            _need(earlier or later, "E_BUDGET_RECEIPT", "non_monotone_retained")
            if receipt["generation"] > other["generation"]:
                _need(later, "E_BUDGET_RECEIPT", "retained_generation_regression")
            elif receipt["generation"] < other["generation"]:
                _need(earlier, "E_BUDGET_RECEIPT", "retained_generation_regression")
    return {k: max(r["retained"][k] for r in receipts) for k in fields}


def attach_producer_receipts(index, *, receipts):
    """Attach externally authenticated accounting/transport proof without reviews.

    The attachment changes publication inventory, never the semantic evidence
    digest, candidate identity, source bytes or admitted observations.
    """
    data = _context(index)
    _need(type(receipts) in (list, tuple), "E_SCHEMA", "receipt_sequence")
    handles = dict(index._producer_handles)
    for handle in receipts:
        _need(type(handle) is ProducerReceipts, "E_REFERENCE", "producer_receipts")
        manifest = handle.manifest
        _need(
            manifest["scope"] == data["scope"]
            and manifest["policy_hash"] == data["policy_hash"],
            "E_SCOPE",
            "producer_receipts",
        )
        previous = handles.get(handle.manifest_hash)
        if previous is not None:
            _need(
                previous.manifest == manifest
                and dict(previous._files) == dict(handle._files),
                "E_HASH",
                "producer_collision",
            )
        handles[handle.manifest_hash] = handle
    budget_scopes = set()
    for handle in handles.values():
        for artifact in handle.manifest["files"]:
            if artifact["role"] != "metering_receipt":
                continue
            raw = handle.artifact_bytes(artifact["artifact_id"])
            value = _load(raw)
            if (
                type(value) is dict
                and value.get("schema") == "anchor-budget-receipt/v1"
            ):
                budget_scopes.add(_budget_receipt(value, data)["scope_id"])
            if (
                type(value) is dict
                and value.get("schema_version") == "world-anchor-metering/v1"
            ):
                budget_scopes.add(
                    _budget_summary(raw, handle, data)["anchor_budget_scope_id"]
                )
    _need(len(budget_scopes) <= 1, "E_BUDGET_RECEIPT", "mixed_budget_scope")
    _retained_budget_maxima(handles, data)
    data["producer_manifest_hashes"] = sorted(handles)
    attached = EvidenceIndex(_KEY, data, index._files, index._review_pins, handles)
    _, _, transport_scope = _receipt_totals(attached)
    _need(
        not budget_scopes
        or transport_scope is None
        or transport_scope in budget_scopes,
        "E_BUDGET_RECEIPT",
        "transport_budget_scope",
    )
    return attached


def _authenticate_review(proposal, review, policy, receipts):
    transports = {
        aid: _load(receipts.artifact_bytes(aid))
        for aid in receipts.manifest["transport_artifact_ids"]
    }
    extraction = [
        r
        for r in transports.values()
        if r["attempt_id"] == proposal["extraction_attempt_id"]
        and r["role"] == "extraction"
    ]
    _need(len(extraction) == 1, "E_REFERENCE", "extraction_transport")
    _need(
        review["transport_receipt_artifact_id"] in transports,
        "E_REFERENCE",
        "review_transport",
    )
    transport_raw = receipts.artifact_bytes(review["transport_receipt_artifact_id"])
    _need(
        hashlib.sha256(transport_raw).hexdigest() == review["transport_receipt_hash"],
        "E_HASH",
        "review_transport",
    )
    checked = transports[review["transport_receipt_artifact_id"]]
    _need(
        checked["attempt_id"] == review["review_attempt_id"]
        and checked["role"] == "semantic_review"
        and checked["proposal_hash"] == anchor_hash(proposal),
        "E_REFERENCE",
        "review_attempt",
    )
    profile = policy["review_profile"]
    for r, version in (
        (extraction[0], profile["extraction_prompt_version"]),
        (checked, profile["review_prompt_version"]),
    ):
        _need(
            r["input_hash"] == proposal["input_hash"]
            and r["requirements_hash"] == proposal["requirements_hash"]
            and r["profile_id"] == profile["profile_id"]
            and r["prompt_version"] == version,
            "E_REFERENCE",
            "qualified_review",
        )
    _need(
        extraction[0]["mode"] == checked["mode"]
        and extraction[0]["anchor_budget_scope_id"]
        == checked["anchor_budget_scope_id"],
        "E_BUDGET_RECEIPT",
        "review_scope",
    )
    _need(
        _load(receipts.artifact_bytes(extraction[0]["response_artifact_id"]))
        == {"references": proposal["references"], "rows": proposal["rows"]},
        "E_HASH",
        "extraction_response",
    )
    _need(
        review["raw_response_artifact_id"] == checked["response_artifact_id"]
        and review["raw_response_hash"] == checked["response_hash"],
        "E_HASH",
        "review_response",
    )
    _need(
        _load(receipts.artifact_bytes(checked["response_artifact_id"]))
        == {"decisions": review["decisions"]},
        "E_HASH",
        "review_decisions",
    )


OBS_FIELDS = "observation_id claim_id identity value value_kind producer_class subject_actor_ref owner_actor_ref audience actor_basis ref_ids support support_rule review_id conversion_id source_value published_at available_at known_by retrieved_at effective_at visible_at vintage cadence supersedes_observation_id"
EXTRACT_FIELDS = " ".join(
    sorted(
        (
            set(OBS_FIELDS.split())
            - {"observation_id", "support_rule", "review_id", "known_by"}
        )
        | {"proposal_id", "requirement_ids"}
    )
)
REVIEW_FIELDS = "schema_version review_id input_hash requirements_hash proposal_hash policy_hash profile_id review_prompt_version extraction_attempt_id review_attempt_id transport_receipt_artifact_id transport_receipt_hash raw_response_artifact_id raw_response_hash decisions"


def admit_reviewed_evidence(index, proposal, review, *, requirements, policy, receipts):
    data = _context(index, requirements, policy)
    _need(type(receipts) is ProducerReceipts, "E_REFERENCE", "producer_receipts")
    _need(
        receipts.manifest["scope"] == data["scope"]
        and receipts.manifest["policy_hash"] == data["policy_hash"],
        "E_SCOPE",
        "producer_receipts",
    )
    _object(
        proposal,
        "schema_version input_hash requirements_hash extraction_attempt_id references rows",
    )
    _object(review, REVIEW_FIELDS)
    _need(
        proposal["schema_version"] == "world-anchor-evidence-proposal/v1"
        and review["schema_version"] == "world-anchor-semantic-review/v1",
        "E_VERSION",
    )
    for key in ("input_hash", "requirements_hash"):
        _need(review[key] == proposal[key] == data[key], "E_HASH", key)
    _need(
        review["proposal_hash"] == anchor_hash(proposal)
        and review["policy_hash"] == data["policy_hash"],
        "E_HASH",
        "review_proposal",
    )
    profile = policy["review_profile"]
    qbytes = index.artifact_bytes(profile["qualification_artifact_id"])
    _need(
        hashlib.sha256(qbytes).hexdigest() == profile["qualification_artifact_hash"],
        "E_HASH",
        "review_qualification",
    )
    _need(
        review["profile_id"] == profile["profile_id"]
        and review["review_prompt_version"] == profile["review_prompt_version"],
        "E_REFERENCE",
        "review_profile",
    )
    _need(
        review["extraction_attempt_id"]
        == proposal["extraction_attempt_id"]
        != review["review_attempt_id"],
        "E_REFERENCE",
        "independent_review",
    )
    _text(review["review_attempt_id"])
    _text(review["extraction_attempt_id"])
    _hash(review["transport_receipt_hash"])
    _authenticate_review(proposal, review, policy, receipts)
    _need(
        review["review_id"] not in index._review_pins, "E_REFERENCE", "duplicate_review"
    )
    refs = {r["ref_id"]: r for r in data["references"]}
    for ref in _list(proposal["references"], 4096):
        _verify_ref(ref, data, index)
        _need(
            ref["ref_id"] not in refs or refs[ref["ref_id"]] == ref,
            "E_REFERENCE",
            "duplicate_ref",
        )
        refs[ref["ref_id"]] = ref
    claims = {r["claim_id"]: r for r in data["inventory"]}
    sources = {r["source_key"]: r for r in data["sources"]}
    requirements_by_id = {r["requirement_id"]: r for r in requirements["requirements"]}
    decisions = {}
    for decision in _list(review["decisions"], 1024):
        _object(decision, "proposal_id verdict checks")
        _need(
            decision["proposal_id"] not in decisions,
            "E_REFERENCE",
            "duplicate_decision",
        )
        _need(
            decision["verdict"] in {"explicit_support", "ambiguous", "unsupported"},
            "E_SCHEMA",
            "review_verdict",
        )
        decisions[decision["proposal_id"]] = decision
    _need(
        len({r["proposal_id"] for r in proposal["rows"]}) == len(proposal["rows"])
        and set(decisions) == {r["proposal_id"] for r in proposal["rows"]},
        "E_REFERENCE",
        "review_coverage",
    )
    for row in _list(proposal["rows"], 1024):
        _object(row, EXTRACT_FIELDS)
        _need(row["claim_id"] in claims, "E_REFERENCE", "claim")
        _need(
            set(row["requirement_ids"]) <= set(requirements_by_id),
            "E_REFERENCE",
            "nominated_requirement",
        )
        _value(row["value"])
        _value(row["source_value"])
        _need(
            row["value_kind"] in VALUE_KINDS and row["producer_class"] in PRODUCERS,
            "E_SCHEMA",
            "epistemic_kind",
        )
        _need(
            row["actor_basis"]
            in {"none", "self_statement", "mandate", "public_record"},
            "E_PRIVACY",
            "actor_basis",
        )
        _audience(row["audience"])
        if row["identity"] is not None:
            _identity(row["identity"])
        _need(
            row["identity"] is not None or row["value"]["kind"] in {"text", "boolean"},
            "E_SCHEMA",
            "numeric_identity",
        )
        _need(
            row["ref_ids"]
            and len(set(row["ref_ids"])) == len(row["ref_ids"])
            and set(row["ref_ids"]) <= refs.keys(),
            "E_REFERENCE",
            "row_refs",
        )
        claim = claims[row["claim_id"]]
        if (
            claim["origin"] in {"kiq_fact", "case_claim", "case_node"}
            and not claim["source_keys"]
        ):
            data["gaps"].append(_gap("missing_provenance", related=[row["claim_id"]]))
            continue
        # Lost provenance can be restored only by a scoped source reference and
        # independent review, never by a display label/cross-track SID join.
        for rid in row["ref_ids"]:
            ref = refs[rid]
            _need(
                ref["claim_id"] in {None, row["claim_id"]}, "E_REFERENCE", "claim_ref"
            )
            if ref["claim_id"] is not None:
                _need(
                    ref["kiq_id"] == claim["kiq_id"]
                    and ref["fact_index"] == claim["fact_index"],
                    "E_REFERENCE",
                    "fact_locator",
                )
            artifact = next(
                a
                for a in data["manifest"]["artifacts"]
                if a["artifact_id"] == claim["artifact_id"]
            )
            _need(ref["track_id"] == artifact["track_id"], "E_SCOPE", "claim_track")
            if claim["source_keys"]:
                _need(
                    ref["source_key"] in claim["source_keys"],
                    "E_REFERENCE",
                    "claim_source",
                )
        supports = {}
        for support in _list(row["support"], 64):
            _object(support, "field ref_id selector expected")
            field = support["field"]
            _need(
                field in SUPPORT_FIELDS
                and field not in supports
                and support["ref_id"] in row["ref_ids"],
                "E_REFERENCE",
                "support",
            )
            ref = refs[support["ref_id"]]
            outer, inner = ref["locator"], support["selector"]
            if field in NUMERIC_FIELDS:
                _need(
                    ref["artifact_id"]
                    == sources[ref["source_key"]]["content_artifact_id"],
                    "E_REFERENCE",
                    "source_content_support",
                )
            if outer["kind"] == "text_span":
                _need(
                    inner.get("kind") == "text_span"
                    and outer["start_byte"]
                    <= inner.get("start_byte", -1)
                    < inner.get("end_byte", -1)
                    <= outer["end_byte"],
                    "E_REFERENCE",
                    "support_span",
                )
            else:
                _need(
                    inner.get("kind") == "json_value"
                    and (
                        inner["pointer"] == outer["pointer"]
                        or inner["pointer"].startswith(outer["pointer"] + "/")
                    ),
                    "E_REFERENCE",
                    "support_pointer",
                )
            selected = {
                **ref,
                "locator": inner,
                "ref_id": _id("ref", ref["source_key"], ref["content_hash"], inner),
            }
            actual = _verify_ref(selected, data, index)
            _need(
                support["expected"]
                == (
                    actual
                    if isinstance(actual, str)
                    else json.dumps(
                        actual,
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    )
                ),
                "E_REFERENCE",
                "support_expected",
            )
            supports[field] = support
        required_fields = (
            {"value", "value_kind"} if row["identity"] is None else NUMERIC_FIELDS
        ) | {"producer_class", "audience", "actor_basis"}
        for field in ("effective_at", "visible_at", "vintage"):
            if _time(row[field]) is not None:
                required_fields.add(field)
        _object(
            row["cadence"],
            "kind interval_days release_lag_days uncertainty_days ref_ids",
        )
        _need(
            row["cadence"]["kind"]
            in {"unknown", "catalogued", "source_stated", "inferred"},
            path="cadence",
        )
        if row["cadence"]["kind"] != "unknown":
            required_fields.add("cadence")
        else:
            _need(
                all(
                    row["cadence"][k] is None
                    for k in ("interval_days", "release_lag_days", "uncertainty_days")
                ),
                path="unknown_cadence",
            )
        if row["actor_basis"] == "mandate":
            required_fields.add("authority")
        decision = decisions[row["proposal_id"]]
        checks = {}
        for check in decision["checks"]:
            _object(check, "field verdict ref_ids")
            _need(
                check["field"] not in checks and check["field"] in SUPPORT_FIELDS,
                "E_REFERENCE",
                "review_check",
            )
            _need(
                check["verdict"] in {"explicit_support", "ambiguous", "unsupported"},
                "E_SCHEMA",
                "review_check",
            )
            _need(
                set(check["ref_ids"]) <= set(row["ref_ids"]),
                "E_REFERENCE",
                "review_refs",
            )
            checks[check["field"]] = check
        supported = (
            required_fields <= supports.keys() and required_fields <= checks.keys()
        )
        supported = supported and all(
            checks[k]["verdict"] == "explicit_support"
            and supports[k]["ref_id"] in checks[k]["ref_ids"]
            for k in required_fields
        )
        if decision["verdict"] != "explicit_support" or not supported:
            data["gaps"].append(_gap("ambiguous_support", related=[row["claim_id"]]))
            continue
        if row["source_value"]["kind"] in {"number", "range"}:
            tokens = _numeric_tokens(supports["value"]["expected"])
            needed = (
                [row["source_value"]["value"]]
                if row["source_value"]["kind"] == "number"
                else [row["source_value"]["low"], row["source_value"]["high"]]
            )
            _need(
                all(_decimal(v) in tokens for v in needed),
                "E_REFERENCE",
                "numeric_support",
            )
        if row["conversion_id"] is None:
            _need(
                row["value"] == row["source_value"],
                "E_REFERENCE",
                "undeclared_conversion",
            )
        else:
            conversion = next(
                (
                    c
                    for c in policy["conversions"]
                    if c["conversion_id"] == row["conversion_id"]
                ),
                None,
            )
            _need(
                conversion is not None
                and row["value"]["kind"] == row["source_value"]["kind"] == "number",
                "E_REFERENCE",
                "conversion",
            )
            _need(
                row["identity"]["unit"] == conversion["to_unit"]
                and _decimal(row["value"]["value"])
                == _decimal(row["source_value"]["value"])
                * _decimal(conversion["factor"])
                + _decimal(conversion["offset"]),
                "E_REFERENCE",
                "conversion",
            )
        related_sources = [sources[refs[r]["source_key"]] for r in row["ref_ids"]]
        if any(
            s["audience"]["kind"] == "analyst"
            and row["audience"]["kind"] != "analyst"
            or s["audience"]["kind"] == "actors"
            and (
                row["audience"]["kind"] == "public"
                or row["audience"]["kind"] == "actors"
                and not set(row["audience"]["actor_refs"])
                <= set(s["audience"]["actor_refs"])
            )
            for s in related_sources
        ):
            data["gaps"].append(
                _gap("forbidden_actor_evidence", related=[row["claim_id"]])
            )
            continue
        if any(s["capture"]["kind"] == "error_page" for s in related_sources):
            data["gaps"].append(_gap("retrieval_error_page", related=[row["claim_id"]]))
            continue
        if any(
            s["retention"] not in {"fetched_page", "official_row"}
            for s in related_sources
        ):
            data["gaps"].append(_gap("missing_page", related=[row["claim_id"]]))
            continue
        availabilities = [
            availability_from_receipts(s, index=index, cutoff=data["scope"]["cutoff"])
            for s in related_sources
        ]
        # Every supporting source is checked, not a union blessed by one good ref.
        availability = max(
            availabilities, key=lambda a: a["known_by"]["value"] or "9999"
        )
        if any(a["cutoff_status"] != "known_by_cutoff" for a in availabilities):
            if any(
                a["cutoff_status"] in {"unknown", "conflict"} for a in availabilities
            ):
                availability = {**availability, "known_by": _unknown_time()}
        observation = {
            k: _copy(v)
            for k, v in row.items()
            if k not in {"proposal_id", "requirement_ids"}
        }
        observation.update(
            observation_id=_id("obs", row["claim_id"], row, review["review_id"]),
            support_rule="reviewed/v1",
            review_id=review["review_id"],
            published_at=availability["published_at"],
            available_at=availability["available_at"],
            known_by=availability["known_by"],
            retrieved_at=related_sources[0]["retrieved_at"],
        )
        data["observations"].append(observation)
        claim["observation_ids"].append(observation["observation_id"])
        claim["ref_ids"] = sorted(set(claim["ref_ids"]) | set(row["ref_ids"]))
        claim["disposition"], claim["reason_code"] = "indexed", None
    data["references"] = sorted(refs.values(), key=lambda r: r["ref_id"])
    data["evidence_proposals"].append(_copy(proposal))
    data["review_receipts"].append(_copy(review))
    data["producer_manifest_hashes"] = sorted(
        set(data["producer_manifest_hashes"]) | {receipts.manifest_hash}
    )
    data["evidence_hash"] = _evidence_digest(data)
    issued = EvidenceIndex(
        _KEY,
        data,
        index._files,
        {**index._review_pins, review["review_id"]: receipts},
        index._producer_handles,
    )
    _receipt_totals(issued)
    return issued


def _reviewed_requirement_ids(data):
    """Recover existing reviewed associations; no new evidence discovery."""
    admitted = {o["observation_id"] for o in data["observations"]}
    reviews = {}
    for review in data["review_receipts"]:
        reviews.setdefault(review["proposal_hash"], []).append(review["review_id"])
    result = {}
    for proposal in data["evidence_proposals"]:
        for review_id in reviews.get(anchor_hash(proposal), []):
            for row in proposal["rows"]:
                oid = _id("obs", row["claim_id"], row, review_id)
                if oid in admitted:
                    result[oid] = frozenset(row["requirement_ids"])
    return result


def _admitted_evidence_classes(data):
    refs = {r["ref_id"]: r for r in data["references"]}
    sources = {r["source_key"]: r for r in data["sources"]}
    claims = {r["claim_id"]: r for r in data["inventory"]}
    result = {}
    for obs in data["observations"]:
        eligible = {"page", "official_row", "typed_claim"}
        native = claims[obs["claim_id"]]["origin"] in {
            "case_claim",
            "case_node",
            "case_parameter",
        }
        for rid in obs["ref_ids"]:
            source = sources[refs[rid]["source_key"]]
            classes = (
                {"page"}
                if source["retention"] == "fetched_page"
                else {"official_row"}
                if source["retention"] == "official_row"
                else set()
            )
            if native and classes:
                classes.add("typed_claim")
            eligible &= classes
        result[obs["observation_id"]] = eligible if obs["ref_ids"] else set()
    return result


def _mismatch(req, obs, nominations, evidence_classes=None):
    if req["value_type"] in {"text", "boolean"}:
        if req["requirement_id"] not in nominations.get(obs["observation_id"], ()):
            return "missing_provenance"
        if req["actor_ref"] is not None and req["actor_ref"] not in {
            obs["subject_actor_ref"],
            obs["owner_actor_ref"],
        }:
            return "wrong_entity"
    if req["identity"] != obs["identity"]:
        if req["identity"] is None or obs["identity"] is None:
            return "missing_identity"
        for key, code in (
            ("entity_id", "wrong_entity"),
            ("metric_id", "wrong_metric"),
            ("unit", "wrong_unit"),
            ("denominator_id", "wrong_denominator"),
            ("geography_id", "wrong_geography"),
            ("reference_period", "wrong_period"),
        ):
            if req["identity"][key] != obs["identity"][key]:
                return code
    if obs["value_kind"] not in req["accepted_value_kinds"]:
        return "wrong_value_kind"
    if obs["value"]["kind"] != req["value_type"]:
        return "unsupported_semantics"
    if evidence_classes is not None and not (
        set(req["accepted_evidence"])
        & evidence_classes.get(obs["observation_id"], set())
    ):
        return "evidence_class_not_allowed"
    return None


def candidates_for_requirements(requirements, index):
    data = _context(index, requirements)
    result = {
        "schema_version": "world-anchor-candidates/v1",
        "requirements_hash": anchor_hash(requirements),
        "input_hash": data["input_hash"],
        "evidence_hash": data["evidence_hash"],
        "selection_version": "exact-identity-lexical/v1",
        "rows": [],
    }
    observations = {r["observation_id"]: r for r in data["observations"]}
    nominations = _reviewed_requirement_ids(data)
    evidence_classes = _admitted_evidence_classes(data)
    for req in requirements["requirements"]:
        possible, excluded = [], {}
        for claim in data["inventory"]:
            matches = [
                observations[oid]
                for oid in claim["observation_ids"]
                if _mismatch(req, observations[oid], nominations, evidence_classes)
                is None
            ]
            if matches:
                for obs in (
                    matches if req.get("cardinality", "one") == "many" else matches[:1]
                ):
                    possible.append(
                        {
                            "candidate_id": _id(
                                "candidate",
                                req["requirement_id"],
                                obs["observation_id"],
                            ),
                            "claim_id": claim["claim_id"],
                            "observation_id": obs["observation_id"],
                            "ref_ids": obs["ref_ids"],
                            "rank": 0,
                            "match": "exact",
                            "gap_codes": [],
                        }
                    )
            else:
                raw = _pointer(
                    _load(index.artifact_bytes(claim["artifact_id"])), claim["pointer"]
                )
                text = json.dumps(raw, ensure_ascii=False).casefold()
                ident = req["identity"]
                words = (
                    [
                        part
                        for k in ("entity_id", "metric_id")
                        for part in re.split(r"[_ -]+", ident[k].casefold())
                    ]
                    if ident
                    else []
                )
                if (
                    not claim["observation_ids"]
                    and words
                    and all(word in text for word in words)
                ):
                    possible.append(
                        {
                            "candidate_id": _id(
                                "candidate", req["requirement_id"], claim["claim_id"]
                            ),
                            "claim_id": claim["claim_id"],
                            "observation_id": None,
                            "ref_ids": [],
                            "rank": 0,
                            "match": "lexical",
                            "gap_codes": ["ambiguous_support"],
                        }
                    )
                else:
                    reason = (
                        "unproven"
                        if not claim["observation_ids"]
                        else "incompatible_identity"
                    )
                    excluded[reason] = excluded.get(reason, 0) + 1
        possible.sort(
            key=lambda r: (
                r["match"] != "exact",
                r["observation_id"] or "",
                r["claim_id"],
            )
        )
        if len(possible) > 6:
            excluded["candidate_limit"] = len(possible) - 6
        ranked = [{**row, "rank": i + 1} for i, row in enumerate(possible[:6])]
        result["rows"].append(
            {
                "requirement_id": req["requirement_id"],
                "ranked": ranked,
                "excluded_counts": [
                    {"reason": k, "count": v} for k, v in sorted(excluded.items())
                ],
            }
        )
    return result


def _receipt_totals(index):
    attempts = {}
    for handle in index._producer_handles.values():
        for aid in handle.manifest["transport_artifact_ids"]:
            receipt = _load(handle.artifact_bytes(aid))
            attempt_id = receipt["attempt_id"]
            _need(
                attempt_id not in attempts or attempts[attempt_id] == receipt,
                "E_REFERENCE",
                "attempt_collision",
            )
            attempts[attempt_id] = receipt
    metered = [r for r in attempts.values() if r["mode"] == "metered"]
    _need(
        len({r["anchor_budget_scope_id"] for r in metered}) <= 1,
        "E_BUDGET_RECEIPT",
        "mixed_scope",
    )
    models = sum(r["physical_attempts"] for r in attempts.values())
    tokens = sum(r["reserved_tokens"] for r in attempts.values())
    _need(models <= 20 and tokens <= 150000, "E_BUDGET_RECEIPT", "stage_limit")
    return models, tokens, metered[0]["anchor_budget_scope_id"] if metered else None


def _metering(value, index):
    fields = "anchor_budget_scope_id receipt_artifact_id receipt_hash mode physical_model_attempts reserved_tokens physical_catalog_attempts"
    _object(
        value,
        fields
        + (
            " physical_followup_attempts"
            if "physical_followup_attempts" in value
            else ""
        ),
    )
    for field, limit in (
        ("physical_model_attempts", 20),
        ("reserved_tokens", 150000),
        ("physical_catalog_attempts", 8),
    ):
        _integer(value[field], limit)
    _integer(value.get("physical_followup_attempts", 0), 12)
    models, tokens, transport_scope = _receipt_totals(index)
    _need(
        value["physical_model_attempts"] >= models
        and value["reserved_tokens"] >= tokens,
        "E_BUDGET_RECEIPT",
        "retained_floor",
    )
    summaries = []
    selected_budget_retained = []
    bound_budget = False
    data = _context(index)
    for handle in index._producer_handles.values():
        for artifact in handle.manifest["files"]:
            if artifact["role"] != "metering_receipt":
                continue
            raw = handle.artifact_bytes(artifact["artifact_id"])
            payload = _load(raw)
            if (
                type(payload) is dict
                and payload.get("schema") == "anchor-budget-receipt/v1"
            ):
                _budget_receipt(payload, data)
                bound_budget = True
            if (
                type(payload) is dict
                and payload.get("schema_version") == "world-anchor-metering/v1"
            ):
                bound_budget = True
                summary = _budget_summary(raw, handle, data)
                if (
                    artifact["artifact_id"] == value["receipt_artifact_id"]
                    and artifact["sha256"] == value["receipt_hash"]
                ):
                    summaries.append(summary)
                    selected_budget_retained.append(
                        _load(
                            handle.artifact_bytes(summary["budget_receipt_artifact_id"])
                        )["retained"]
                    )
    if value["mode"] == "offline_deterministic":
        _need(
            not bound_budget and transport_scope is None,
            "E_BUDGET_RECEIPT",
            "bound_scope_requires_metered",
        )
        _need(
            all(
                value[k] is None
                for k in (
                    "anchor_budget_scope_id",
                    "receipt_artifact_id",
                    "receipt_hash",
                )
            )
            and all(
                value[k] == 0
                for k in (
                    "physical_model_attempts",
                    "reserved_tokens",
                    "physical_catalog_attempts",
                )
            )
            and value.get("physical_followup_attempts", 0) == 0,
            "E_BUDGET_RECEIPT",
        )
        return
    _need(
        value["mode"] == "metered" and "physical_followup_attempts" in value,
        "E_BUDGET_RECEIPT",
        "metered_shape",
    )
    _need(
        summaries and all(s == summaries[0] for s in summaries),
        "E_BUDGET_RECEIPT",
        "metering_receipt",
    )
    summary = summaries[0]
    maximum = _retained_budget_maxima(index._producer_handles, data)
    _need(maximum is not None, "E_BUDGET_RECEIPT", "budget_authority")
    _need(
        selected_budget_retained
        and all(
            r["reserved_max_microusd"] >= maximum["reserved_max_microusd"]
            for r in selected_budget_retained
        ),
        "E_BUDGET_RECEIPT",
        "stale_metering",
    )
    for target, source in (
        ("physical_model_attempts", "model_attempts"),
        ("reserved_tokens", "token_envelope_units"),
        ("physical_catalog_attempts", "catalog_attempts"),
        ("physical_followup_attempts", "followup_attempts"),
    ):
        _need(summary[target] >= maximum[source], "E_BUDGET_RECEIPT", "stale_metering")
    _need(
        transport_scope is None or summary["anchor_budget_scope_id"] == transport_scope,
        "E_BUDGET_RECEIPT",
        "scope",
    )
    for field in (
        "anchor_budget_scope_id",
        "physical_model_attempts",
        "reserved_tokens",
        "physical_catalog_attempts",
        "physical_followup_attempts",
    ):
        _need(value[field] == summary[field], "E_BUDGET_RECEIPT", "metering_counters")


def _authenticate_prior(prior, index):
    raw = index.artifact_bytes(prior["artifact_id"])
    _need(
        hashlib.sha256(raw).hexdigest() == _hash(prior["artifact_hash"]),
        "E_HASH",
        "prior_basis",
    )
    value = _pointer(_load(raw), prior["pointer"])
    _need(
        type(value) is dict
        and value.get("value") == prior["value"]
        and value.get("library_version") == prior["library_version"],
        "E_REFERENCE",
        "prior_projection",
    )
    if "identity" in value:
        _need(value["identity"] == prior["identity"], "E_REFERENCE", "prior_identity")


def admit_bindings(
    requirements, index, candidates, proposal, *, policy, attempts, metering
):
    """Establish evidence/policy prerequisites, not installed adapter capability.

    A ready row still requires the real consumer's implemented-version, slot,
    unit, lag and applicability checks before executable preparation.
    """
    data = _context(index, requirements, policy)
    _metering(metering, index)
    _need(
        candidates == candidates_for_requirements(requirements, index),
        "E_HASH",
        "candidates",
    )
    _object(proposal, "schema_version requirements_hash input_hash candidate_hash rows")
    _need(proposal["schema_version"] == "world-anchor-proposal/v1", "E_VERSION")
    _need(
        proposal["requirements_hash"] == anchor_hash(requirements)
        and proposal["input_hash"] == data["input_hash"]
        and proposal["candidate_hash"] == anchor_hash(candidates),
        "E_PROPOSAL",
        "hashes",
    )
    reqs = {r["requirement_id"]: r for r in requirements["requirements"]}
    proposed = {}
    for row in _list(proposal["rows"], 1024):
        _object(row, "requirement_id decision candidate_ids prior_policy_id note")
        rid = row["requirement_id"]
        _need(
            rid in reqs
            and rid not in proposed
            and reqs[rid]["kind"] != "target_definition",
            "E_PROPOSAL",
            "requirement",
        )
        _need(
            row["decision"] in {"bind", "conflict", "gap", "assume"},
            "E_PROPOSAL",
            "decision",
        )
        proposed[rid] = row
    for attempt in attempts:
        _object(
            attempt,
            "attempt_id requirement_ids kind outcome receipt_artifact_id receipt_hash code",
        )
        _need(set(attempt["requirement_ids"]) <= reqs.keys(), "E_REFERENCE", "attempt")
    gaps = _copy(requirements["gaps"] + data["gaps"])
    observations = {r["observation_id"]: r for r in data["observations"]}
    nominations = _reviewed_requirement_ids(data)
    evidence_classes = _admitted_evidence_classes(data)
    selected = {
        r["requirement_id"]: {c["candidate_id"]: c for c in r["ranked"]}
        for r in candidates["rows"]
    }
    bindings = []
    for rid, req in reqs.items():
        row = proposed.get(rid)
        bound = {
            "binding_id": "",
            "requirement_id": rid,
            "status": "gap",
            "observation_ids": [],
            "assumption": None,
            "contract_ref": None,
            "rejected": [],
            "gap_ids": [],
        }
        code = None
        if req["kind"] == "target_definition":
            c = requirements["contract"]
            bound.update(
                status="bound",
                contract_ref={
                    "artifact_id": c["authority_artifact_id"],
                    "artifact_hash": c["authority_artifact_hash"],
                    "pointer": c["authority_pointer"],
                    "contract_hash": requirements["contract_hash"],
                },
            )
        elif row is None:
            code = "unproposed"
        elif row["decision"] == "assume":
            prior = next(
                (
                    p
                    for p in policy["prior_rules"]
                    if p["policy_id"]
                    == row["prior_policy_id"]
                    == req["assumption_policy_id"]
                ),
                None,
            )
            if (
                prior
                and req["kind"] == "mechanism_parameter"
                and req["origin_pointer"] in prior["requirement_origins"]
                and prior["identity"] == req["identity"]
                and prior["value"]["kind"] == req["value_type"]
                and "assumed" in req["accepted_value_kinds"]
            ):
                _authenticate_prior(prior, index)
                bound.update(
                    status="bound",
                    assumption={
                        "policy_id": prior["policy_id"],
                        "value": prior["value"],
                        "identity": prior["identity"],
                        "value_kind": "assumed",
                        "basis_artifact_id": prior["artifact_id"],
                        "basis_hash": prior["artifact_hash"],
                        "rationale": prior["rationale"],
                        "replaces_observation_ids": [],
                    },
                )
            else:
                code = "prior_not_allowed"
        else:
            _need(
                len(set(row["candidate_ids"])) == len(row["candidate_ids"])
                and set(row["candidate_ids"]) <= selected[rid].keys(),
                "E_PROPOSAL",
                "candidate_ids",
            )
            good = []
            for cid in row["candidate_ids"]:
                oid = selected[rid][cid]["observation_id"]
                if oid is None:
                    bound["rejected"].append(
                        {"candidate_id": cid, "code": "ambiguous_support"}
                    )
                    code = "ambiguous_support"
                    continue
                obs = observations[oid]
                why = _mismatch(req, obs, nominations, evidence_classes)
                if _time(obs["known_by"]) is None:
                    why = "unknown_availability"
                elif _time(obs["known_by"]) > _instant(data["scope"]["cutoff"]):
                    why = "after_cutoff"
                if (
                    obs["value_kind"] == "observed"
                    and obs["identity"]
                    and obs["identity"]["reference_period"]["end"]
                    > data["scope"]["cutoff"][:10]
                ):
                    why = "future_observation"
                if why:
                    bound["rejected"].append({"candidate_id": cid, "code": why})
                    code = why
                else:
                    good.append(obs)
            all_matches = [
                o
                for o in observations.values()
                if _mismatch(req, o, nominations, evidence_classes) is None
                and _time(o["known_by"]) is not None
                and _time(o["known_by"]) <= _instant(data["scope"]["cutoff"])
            ]
            collection = req.get("cardinality", "one") == "many"
            if (
                not collection
                and len({anchor_hash(o["value"]) for o in all_matches}) > 1
                or row["decision"] == "conflict"
                and good
            ):
                bound.update(
                    status="conflict",
                    observation_ids=sorted(o["observation_id"] for o in all_matches),
                )
                code = "conflicting_values"
            elif row["decision"] == "bind" and good and not bound["rejected"]:
                bound.update(
                    status="bound",
                    observation_ids=sorted(o["observation_id"] for o in good),
                )
                code = None
            else:
                if not code and any(
                    _mismatch(req, o, nominations, evidence_classes)
                    == "evidence_class_not_allowed"
                    for o in observations.values()
                ):
                    code = "evidence_class_not_allowed"
                code = code or "no_candidate"
        if code:
            gap = _gap(
                code,
                rid,
                engines=[c["engine"] for c in req["consumers"]]
                if req["required"]
                else [],
            )
            gaps.append(gap)
            bound["gap_ids"].append(gap["gap_id"])
        bound["binding_id"] = _id(
            "binding", rid, bound["observation_ids"], bound["assumption"]
        )
        bindings.append(bound)
    by_req = {b["requirement_id"]: b for b in bindings}
    for _ in range(len(bindings)):
        changed = False
        for rid, req in reqs.items():
            b = by_req[rid]
            if b["status"] == "bound" and any(
                by_req[d]["status"] != "bound" for d in req["dependency_ids"]
            ):
                b["status"] = "contested"
                gap = _gap(
                    "dependency_unready",
                    rid,
                    engines=[c["engine"] for c in req["consumers"]]
                    if req["required"]
                    else [],
                )
                gaps.append(gap)
                b["gap_ids"].append(gap["gap_id"])
                changed = True
        if not changed:
            break
    contract = requirements["contract"]
    for rid, req in reqs.items():
        for consumer in req["consumers"]:
            if not any(
                all(
                    rule[k] == consumer[k]
                    for k in ("engine", "role", "object_id", "field")
                )
                for rule in policy["consumer_rules"]
            ):
                gaps.append(
                    _gap(
                        "modeling_gap",
                        rid,
                        engines=[consumer["engine"]] if req["required"] else [],
                    )
                )
    if contract:
        templates = {
            "growth",
            "sum",
            "product",
            "linear",
            "supply_demand",
            "adoption",
            "regulatory_milestone",
        }
        outputs = set()
        for mechanism in contract["mechanisms"]:
            _need(
                mechanism["output_node_id"] not in outputs,
                "E_CONTRACT",
                "duplicate_mechanism_writer",
            )
            outputs.add(mechanism["output_node_id"])
            for slot in mechanism["parameters"]:
                _object(slot, "name requirement_origin unit")
                _unit(slot["unit"])
                _need(
                    slot["requirement_origin"]
                    in {r["origin_pointer"] for r in reqs.values()},
                    "E_CONTRACT",
                    "parameter_requirement",
                )
            for consumer in mechanism["consumers"]:
                policy_admitted = mechanism["template"] in templates and any(
                    all(
                        rule[k] == consumer[k]
                        for k in ("engine", "role", "object_id", "field")
                    )
                    and mechanism["template_version"] in rule["template_versions"]
                    for rule in policy["consumer_rules"]
                )
                if not policy_admitted:
                    gaps.append(
                        _gap(
                            "modeling_gap",
                            related=[mechanism["mechanism_id"]],
                            engines=[consumer["engine"]],
                        )
                    )
        pending = {
            m["output_node_id"]: set(m["input_node_ids"]) & outputs
            for m in contract["mechanisms"]
        }
        done = set()
        while pending:
            ready = {nid for nid, deps in pending.items() if deps <= done}
            _need(ready, "E_CONTRACT", "mechanism_cycle")
            done.update(ready)
            pending = {nid: deps for nid, deps in pending.items() if nid not in ready}
    executable_roles = {
        "initial_state",
        "compiler_parameter",
        "mechanism",
        "calendar",
        "observation",
    }
    for engine in ENGINES:
        policy_mapped = any(
            req["kind"] != "target_definition"
            and by_req[rid]["status"] == "bound"
            and (by_req[rid]["observation_ids"] or by_req[rid]["assumption"])
            and any(
                c["engine"] == engine
                and c["role"] in executable_roles
                and any(
                    all(
                        rule[k] == c[k]
                        for k in ("engine", "role", "object_id", "field")
                    )
                    for rule in policy["consumer_rules"]
                )
                for c in req["consumers"]
            )
            for rid, req in reqs.items()
        )
        if not policy_mapped:
            gaps.append(
                _gap(
                    "modeling_gap",
                    related=[engine, "no_executable_consumer"],
                    engines=[engine],
                )
            )
    gaps = sorted({g["gap_id"]: g for g in gaps}.values(), key=lambda g: g["gap_id"])

    variables = []
    if contract:
        outputs = {
            m["output_node_id"]: m["mechanism_id"] for m in contract["mechanisms"]
        }
        for rid, req in reqs.items():
            for consumer in req["consumers"]:
                if consumer["role"] == "initial_state" and req["identity"]:
                    nid = consumer["object_id"]
                    if not any(v["node_id"] == nid for v in variables):
                        variables.append(
                            {
                                "node_id": nid,
                                "identity": req["identity"],
                                "binding_id": by_req[rid]["binding_id"],
                                "history_observation_ids": [],
                                "revision_observation_ids": sorted(
                                    o["observation_id"]
                                    for o in observations.values()
                                    if o["identity"] == req["identity"]
                                    and o["value_kind"] == "third_party_forecast"
                                ),
                                "writable": nid not in outputs,
                                "producer_mechanism_id": outputs.get(nid),
                            }
                        )
    coverage = {
        "inventory_total": len(data["inventory"]),
        **{
            key: sum(r["disposition"] == key for r in data["inventory"])
            for key in ("indexed", "unsupported", "missing_provenance")
        },
        "admitted_observations": len(observations),
        **{
            key + "_requirements": sum(b["status"] == status for b in bindings)
            for key, status in (
                ("bound", "bound"),
                ("conflicted", "conflict"),
                ("contested", "contested"),
                ("gap", "gap"),
            )
        },
        "omissions": data["manifest"]["omissions"],
    }
    readiness = [
        {
            "engine": engine,
            "status": "blocked"
            if any(engine in g["blocking_engines"] for g in gaps)
            else "ready",
            "blocking_gap_ids": [
                g["gap_id"] for g in gaps if engine in g["blocking_engines"]
            ],
            "unmet_requirement_ids": sorted(
                {
                    g["requirement_id"]
                    for g in gaps
                    if engine in g["blocking_engines"] and g["requirement_id"]
                }
            ),
        }
        for engine in ENGINES
    ]
    pack = {
        "schema_version": VERSION,
        "scope": data["scope"],
        "contract_hash": requirements["contract_hash"],
        "input_hash": data["input_hash"],
        "requirements_hash": anchor_hash(requirements),
        "policy_hash": anchor_hash(policy),
        "evidence_hash": data["evidence_hash"],
        "evidence_proposals": data["evidence_proposals"],
        "review_receipts": data["review_receipts"],
        "producer_manifest_hashes": data["producer_manifest_hashes"],
        "requirements": requirements["requirements"],
        "candidates": candidates,
        "proposal": proposal,
        **{k: data[k] for k in ("inventory", "sources", "references", "observations")},
        "bindings": bindings,
        "variables": variables,
        **{
            ("actor_dossiers" if k == "actors" else k): contract[k] if contract else []
            for k in SPEC_FIELDS
        },
        "gaps": gaps,
        "resolution_attempts": attempts,
        "coverage": coverage,
        "readiness": readiness,
        "metering": metering,
    }
    if contract and (
        contract["authority_kind"] == "research_inventory"
        or any(
            c["role"] == "research_note" for r in reqs.values() for c in r["consumers"]
        )
    ):
        refs = {r["ref_id"]: r for r in pack["references"]}
        items = []
        for binding in bindings:
            req = reqs[binding["requirement_id"]]
            if binding["status"] != "bound" or not any(
                c["role"] == "research_note" for c in req["consumers"]
            ):
                continue
            for oid in binding["observation_ids"]:
                obs = observations[oid]
                support = next(s for s in obs["support"] if s["field"] == "value")
                selector = support["selector"]
                if selector["kind"] == "text_span":
                    quote = selector["quote"]
                else:
                    quote = _pointer(
                        _load(
                            index.artifact_bytes(refs[support["ref_id"]]["artifact_id"])
                        ),
                        selector["pointer"],
                    )
                    _need(type(quote) is str, "E_REFERENCE", "research_quote")
                items.append(
                    {
                        "research_item_id": _id(
                            "research_item", req["requirement_id"], oid
                        ),
                        "requirement_id": req["requirement_id"],
                        "observation_id": oid,
                        "kind": req["kind"],
                        "actor_ref": req["actor_ref"] or obs["subject_actor_ref"],
                        "quote": quote,
                        **{
                            k: obs[k]
                            for k in (
                                "value_kind",
                                "producer_class",
                                "audience",
                                "known_by",
                                "effective_at",
                                "visible_at",
                                "ref_ids",
                            )
                        },
                        "executable": False,
                    }
                )
        pack["research_items"] = sorted(
            items, key=lambda item: item["research_item_id"]
        )
    return _copy(pack)


def validate_pack(pack, *, requirements, index, policy):
    _finite(pack)
    _need(type(pack) is dict and pack.get("schema_version") == VERSION, "E_VERSION")
    try:
        expected = admit_bindings(
            requirements,
            index,
            pack["candidates"],
            pack["proposal"],
            policy=policy,
            attempts=pack["resolution_attempts"],
            metering=pack["metering"],
        )
    except KeyError:
        raise AnchorError("E_SCHEMA", "pack") from None
    _need(pack == expected, "E_HASH", "pack_admission")
    return expected


def _anchor_sheet(pack, *, index, requirements, policy):
    """Render the private analyst view solely from authenticated frozen inputs."""
    reqs = {r["requirement_id"]: r for r in pack["requirements"]}
    origins = {r["origin_pointer"]: r for r in pack["requirements"]}
    bindings = {b["requirement_id"]: b for b in pack["bindings"]}
    binding_ids = {b["binding_id"]: b for b in pack["bindings"]}
    observations = {o["observation_id"]: o for o in pack["observations"]}
    refs = {r["ref_id"]: r for r in pack["references"]}
    sources = {r["source_key"]: r for r in pack["sources"]}
    gaps = {g["gap_id"]: g for g in pack["gaps"]}
    artifacts = {a["artifact_id"]: a for a in index.snapshot()["manifest"]["artifacts"]}
    priors = {r["policy_id"]: r for r in policy["prior_rules"]}
    omitted, documents, aliases = set(), {}, {}
    lines = [
        "# World Anchor",
        "",
        "**Private analyst view.** These tables describe retained evidence and admission prerequisites. "
        "Installed-consumer checks and actor/public projections remain separate.",
        "",
        "Pack SHA256: " + anchor_hash(pack),
        "",
    ]

    def plain(value):
        if value is None:
            return "unknown"
        if type(value) is bool:
            return "true" if value else "false"
        if type(value) in (dict, list):
            return json.dumps(
                value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
            )
        return str(value)

    def cell(value):
        text = plain(value).replace("\n", " ").replace("\r", " ").replace("\t", " ")
        text = "".join(
            ch
            if ord(ch) >= 32
            and ord(ch) != 127
            and not (0x202A <= ord(ch) <= 0x202E or 0x2066 <= ord(ch) <= 0x2069)
            else "[U+" + format(ord(ch), "04X") + "]"
            for ch in text
        )
        text = (
            text.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;")
        )
        special = set(chr(96) + "\\*_{}[]()!#~|")
        return "".join(
            "&#" + str(ord(ch)) + ";" if ch in special else ch for ch in text
        )

    def table(title, headers, rows):
        rows = list(rows)
        lines.extend(
            [
                "",
                "## " + title,
                "",
                "| " + " | ".join(headers) + " |",
                "|" + "|".join("---" for _ in headers) + "|",
            ]
        )
        lines.extend("| " + " | ".join(cell(v) for v in row) + " |" for row in rows)
        if not rows:
            lines.extend(["", "No entries declared in this pack."])

    def missing(section, item, field, code, reference=""):
        omitted.add((section, str(item), field, code, str(reference)))
        return "[" + code + (": " + str(reference) if reference else "") + "]"

    def record(aid, pointer, section, item, expected_hash=None):
        try:
            raw = index.artifact_bytes(aid)
            if (
                expected_hash is not None
                and hashlib.sha256(raw).hexdigest() != expected_hash
            ):
                missing(section, item, "label", "label_hash_mismatch", aid)
                return None
            if aid not in documents:
                documents[aid] = _load(raw)
            return _pointer(documents[aid], pointer)
        except AnchorError as exc:
            missing(section, item, "record", "unavailable_input", aid + ":" + exc.code)
            return None

    contract = requirements["contract"]
    for alias in contract["aliases"] if contract else []:
        value = record(
            alias["artifact_id"],
            alias["pointer"],
            "Labels",
            alias["canonical_id"],
            alias["artifact_hash"],
        )
        if type(value) is str and value == alias["literal"]:
            aliases.setdefault((alias["field"], alias["canonical_id"]), set()).add(
                value
            )
        else:
            missing(
                "Labels",
                alias["canonical_id"],
                alias["field"],
                "unverified_label",
                alias["artifact_id"],
            )

    def label(field, identifier):
        if identifier is None:
            return "not applicable"
        names = sorted(aliases.get((field, identifier), ()))
        return " / ".join(names) + " [" + identifier + "]" if names else identifier

    def unit(value):
        return label("unit", value["id"]) if value else "not applicable"

    def period(value):
        return (
            value["start"] + " to " + value["end"] + " (" + value["granularity"] + ")"
            if value
            else "not applicable"
        )

    def time(value):
        return (
            value["value"] + " (" + value["precision"] + ")"
            if value and value["value"] is not None
            else "unknown"
        )

    def quantity(value):
        if value is None:
            return "unknown"
        return (
            value["low"] + " to " + value["high"]
            if value["kind"] == "range"
            else plain(value["value"])
        )

    def source_label(source):
        local = source["local_source_id"]
        return source["track_id"] + ":" + ("S" + local if local.isdigit() else local)

    def provenance(ref_ids, section, item):
        result = []
        for rid in ref_ids:
            ref = refs.get(rid)
            source = sources.get(ref["source_key"]) if ref else None
            result.append(
                source_label(source)
                if source
                else missing(section, item, "source", "missing_source_reference", rid)
            )
        return ", ".join(sorted(set(result))) or "[not_supplied]"

    def artifact_label(aid, pointer=""):
        artifact = artifacts.get(aid)
        return (
            aid + ":" + artifact["path"] + ("#" + pointer if pointer else "")
            if artifact
            else "[missing_artifact: " + aid + "]"
        )

    def info(origin, section, item, bound=None):
        req = reqs.get(bound["requirement_id"]) if bound else origins.get(origin)
        if req is None:
            status = (
                "[not_supplied]"
                if origin is None
                else missing(
                    section, item, "requirement", "missing_requirement", origin
                )
            )
            return {
                "req": None,
                "binding": None,
                "values": [],
                "status": status,
                "source": "[not_supplied]",
            }
        bound = bound or bindings.get(req["requirement_id"])
        if bound is None:
            return {
                "req": req,
                "binding": None,
                "values": [],
                "status": missing(
                    section, item, "binding", "missing_binding", req["requirement_id"]
                ),
                "source": "[not_supplied]",
            }
        values = []
        for oid in bound["observation_ids"]:
            if oid in observations:
                values.append(observations[oid])
            else:
                missing(section, item, "observation", "missing_observation", oid)
        if bound["assumption"]:
            values.append(bound["assumption"])
        codes = sorted(
            {gaps[g]["code"] if g in gaps else "missing_gap" for g in bound["gap_ids"]}
        )
        status = bound["status"] + (": " + ", ".join(codes) if codes else "")
        if req.get("cardinality", "one") == "many":
            status += " (collection; " + str(len(values)) + " selected)"
        source = provenance(
            [rid for value in values for rid in value.get("ref_ids", [])], section, item
        )
        if bound["assumption"]:
            a = bound["assumption"]
            source = artifact_label(a["basis_artifact_id"]) + " / " + a["basis_hash"]
        if bound["contract_ref"]:
            c = bound["contract_ref"]
            source = artifact_label(c["artifact_id"], c["pointer"])
        return {
            "req": req,
            "binding": bound,
            "values": values,
            "status": status,
            "source": source,
        }

    def value_text(data):
        if data["binding"] and data["binding"]["contract_ref"]:
            return "target definition only; no observed value"
        return "; ".join(quantity(v["value"]) for v in data["values"]) or "unknown"

    def basis(data):
        result = []
        for value in data["values"]:
            if value.get("value_kind") == "assumed":
                prior = priors.get(value["policy_id"], {})
                result.append(
                    "assumed; "
                    + value["policy_id"]
                    + "; "
                    + prior.get("library_version", "[not_supplied]")
                    + "; "
                    + value["rationale"]
                )
            else:
                result.append(value["value_kind"] + " / " + value["producer_class"])
        return "; ".join(sorted(set(result))) or "[not_supplied]"

    def consumers(rows):
        return (
            "; ".join(
                c["engine"] + ":" + c["role"] + ":" + c["object_id"] + "." + c["field"]
                for c in rows
            )
            or "[not_supplied]"
        )

    def summaries(origin_list, section, item):
        return [info(origin, section, item) for origin in origin_list]

    def statuses(items):
        return (
            "; ".join(sorted({d["status"] for d in items}))
            if items
            else "no requirements declared"
        )

    def evidence(items):
        return (
            "; ".join(sorted({d["source"] for d in items}))
            if items
            else "[not_supplied]"
        )

    scope = pack["scope"]
    table(
        "Scope",
        ["Run", "Input generation", "Snapshot", "Cutoff", "Horizon", "Authority"],
        [
            [
                scope["run_id"],
                scope["research_generation_id"],
                scope["snapshot_id"],
                scope["cutoff"],
                period(scope["horizon"]),
                contract["authority_kind"] if contract else "[missing_contract]",
            ]
        ],
    )
    rows = []
    for var in pack["variables"]:
        data = info(
            None, "Variables", var["node_id"], binding_ids.get(var["binding_id"])
        )
        ident = var["identity"]
        for value in data["values"] or [None]:
            rows.append(
                [
                    var["node_id"],
                    label("entity", ident["entity_id"])
                    + " / "
                    + label("metric", ident["metric_id"]),
                    quantity(value["value"]) if value else "unknown",
                    unit(ident["unit"]),
                    period(ident["reference_period"]),
                    time(value.get("vintage")) if value else "unknown",
                    value["value_kind"] if value else "[not_supplied]",
                    data["status"],
                    provenance(value["ref_ids"], "Variables", var["node_id"])
                    if value and value.get("ref_ids")
                    else data["source"],
                ]
            )
    table(
        "Variables",
        [
            "Node",
            "Entity / metric",
            "Value",
            "Unit",
            "Reference period",
            "Vintage",
            "Value kind",
            "Status",
            "Source",
        ],
        rows,
    )

    rows, parameters = [], []
    for mech in pack["mechanisms"]:
        entries = []
        for slot in mech["parameters"]:
            data = info(
                slot["requirement_origin"],
                "Parameter bases",
                mech["mechanism_id"] + ":" + slot["name"],
            )
            entries.append(data)
            ident = data["req"]["identity"] if data["req"] else None
            status = data["status"]
            if ident and ident["unit"] != slot["unit"]:
                status += " " + missing(
                    "Parameter bases",
                    mech["mechanism_id"],
                    slot["name"],
                    "unit_mismatch",
                    slot["requirement_origin"],
                )
            parameters.append(
                [
                    mech["mechanism_id"],
                    slot["name"],
                    value_text(data),
                    unit(slot["unit"]),
                    period(ident["reference_period"]) if ident else "not applicable",
                    basis(data),
                    status,
                    data["source"],
                ]
            )
        lag = info(mech["lag_requirement_origin"], "Mechanisms", mech["mechanism_id"])
        applicability = summaries(
            mech["applicability_requirement_origins"],
            "Mechanisms",
            mech["mechanism_id"],
        )
        rows.append(
            [
                mech["mechanism_id"],
                mech["template"] + "/" + mech["template_version"],
                ", ".join(mech["input_node_ids"]) + " -> " + mech["output_node_id"],
                ", ".join(p["name"] for p in mech["parameters"]) or "none declared",
                value_text(lag) if mech["lag_requirement_origin"] else "not supplied",
                "; ".join(value_text(d) for d in applicability) or "not supplied",
                statuses(entries),
                consumers(mech["consumers"]),
            ]
        )
    table(
        "Mechanisms",
        [
            "Mechanism",
            "Declared template",
            "Inputs / output",
            "Parameter slots",
            "Lag",
            "Applicability",
            "Admission basis",
            "Declared consumers",
        ],
        rows,
    )
    table(
        "Parameter bases",
        [
            "Mechanism",
            "Slot",
            "Value / range",
            "Declared unit",
            "Period",
            "Evidence / prior basis",
            "Status",
            "Source",
        ],
        parameters,
    )

    actor_specs = {a["actor_ref"]: a for a in pack["actor_dossiers"]}
    actor_cache = {}

    def actor_label(actor_ref):
        if actor_ref is None:
            return "not supplied", "[not_supplied]"
        if actor_ref in actor_cache:
            return actor_cache[actor_ref]
        spec = actor_specs.get(actor_ref)
        registry = (
            record(
                spec["registry_artifact_id"],
                spec["registry_pointer"],
                "Actor items",
                actor_ref,
            )
            if spec
            else None
        )
        if registry is None and contract:
            for alias in contract["aliases"]:
                if (
                    alias["field"] == "entity"
                    and alias["canonical_id"] == actor_ref
                    and alias["pointer"].endswith("/name")
                ):
                    literal = record(
                        alias["artifact_id"],
                        alias["pointer"],
                        "Actor items",
                        actor_ref,
                        alias["artifact_hash"],
                    )
                    if literal == alias["literal"]:
                        registry = record(
                            alias["artifact_id"],
                            alias["pointer"].rsplit("/", 1)[0],
                            "Actor items",
                            actor_ref,
                        )
                        break
        name = registry.get("name") if type(registry) is dict else None
        name = (
            name + " [" + actor_ref + "]"
            if type(name) is str and name
            else label("entity", actor_ref)
        )
        classes = [
            key + "=" + registry[key]
            for key in ("role_class", "agency_class")
            if type(registry) is dict
            and type(registry.get(key)) is str
            and registry[key]
        ]
        classification = "; ".join(classes) or missing(
            "Actor items", actor_ref, "class", "missing_registry_class"
        )
        actor_cache[actor_ref] = (name, classification)
        return name, classification

    rows, seen = [], set()

    def actor_item(actor_ref, kind, data, detail=""):
        name, classification = actor_label(actor_ref)
        for value in data["values"] or [None]:
            token = (
                actor_ref,
                kind,
                value.get(
                    "observation_id",
                    data["req"]["requirement_id"] if data["req"] else "",
                )
                if value
                else detail,
            )
            if token in seen:
                continue
            seen.add(token)
            rows.append(
                [
                    name,
                    kind,
                    quantity(value["value"]) if value else "unknown",
                    classification,
                    (
                        value["value_kind"]
                        + " / "
                        + value.get("producer_class", "model_prior")
                    )
                    if value
                    else "[not_supplied]",
                    plain(value.get("audience")) if value else "unknown",
                    time(value.get("known_by")) if value else "unknown",
                    data["status"],
                    detail or (data["req"]["origin_pointer"] if data["req"] else ""),
                    provenance(value["ref_ids"], "Actor items", actor_ref)
                    if value and value.get("ref_ids")
                    else data["source"],
                ]
            )

    for actor in pack["actor_dossiers"]:
        count = 0
        for group in ("statements", "plans"):
            for origin in actor[group]:
                data = info(origin, "Actor items", actor["actor_ref"])
                actor_item(
                    actor["actor_ref"],
                    data["req"]["kind"] if data["req"] else group,
                    data,
                )
                count += 1
        for authority in actor["authority"]:
            actor_item(
                actor["actor_ref"],
                "authority declaration",
                info(
                    authority["requirement_origin"], "Actor items", actor["actor_ref"]
                ),
                authority["lever_id"]
                + ": "
                + authority["mode"]
                + "; coholders="
                + ", ".join(authority["coholder_actor_refs"]),
            )
            count += 1
        for red_line in actor["red_lines"]:
            actor_item(
                actor["actor_ref"],
                "red_line",
                info(red_line["requirement_origin"], "Actor items", actor["actor_ref"]),
                "declared predicate=" + plain(red_line["predicate"]),
            )
            count += 1
        if not count:
            actor_item(
                actor["actor_ref"],
                "no items declared",
                info(None, "Actor items", actor["actor_ref"]),
            )
    for req in pack["requirements"]:
        if req["actor_ref"] is not None and (
            req["kind"].startswith("actor_") or req["kind"] == "red_line"
        ):
            actor_item(
                req["actor_ref"],
                req["kind"],
                info(req["origin_pointer"], "Actor items", req["actor_ref"]),
            )
    table(
        "Actor items",
        [
            "Actor",
            "Item kind",
            "Value / statement",
            "Registry class (declared, not cast validation)",
            "Epistemic / producer class",
            "Audience",
            "Known by",
            "Status",
            "Authority / predicate / origin",
            "Source",
        ],
        rows,
    )

    rows = []
    for event in pack["calendar"]:
        data = info(event["requirement_origin"], "Calendar", event["event_id"])
        when = info(event["time_requirement_origin"], "Calendar", event["event_id"])
        effects = summaries(
            event["effect_requirement_origins"], "Calendar", event["event_id"]
        )
        rows.append(
            [
                event["event_id"],
                event["classification"],
                value_text(data),
                value_text(when),
                "; ".join(value_text(d) for d in effects) or "none declared",
                statuses([data, when] + effects),
                evidence([data, when] + effects),
            ]
        )
    for item in pack.get("research_items", []):
        if item["kind"] in {"calendar_event", "event"}:
            rows.append(
                [
                    item["research_item_id"],
                    "research note; no scheduled effect",
                    item["quote"],
                    time(item["effective_at"]),
                    "none (non-executable)",
                    "source-supported research note",
                    provenance(item["ref_ids"], "Calendar", item["research_item_id"]),
                ]
            )
    represented = {i["requirement_id"] for i in pack.get("research_items", [])}
    for req in pack["requirements"]:
        if (
            req["kind"] in {"calendar_event", "event"}
            and req["requirement_id"] not in represented
            and any(c["role"] == "research_note" for c in req["consumers"])
        ):
            data = info(req["origin_pointer"], "Calendar", req["requirement_id"])
            rows.append(
                [
                    req["requirement_id"],
                    "research requirement; non-executable",
                    value_text(data),
                    "unknown",
                    "none",
                    data["status"],
                    data["source"],
                ]
            )
    table(
        "Calendar",
        [
            "Event",
            "Classification",
            "Evidence / description",
            "Effective date / time evidence",
            "Effects",
            "Status",
            "Source",
        ],
        rows,
    )

    rows = []
    for hazard in pack["hazards"]:
        likelihood = info(
            hazard["likelihood_requirement_origin"], "Hazards", hazard["hazard_id"]
        )
        recurrence = info(
            hazard["recurrence_requirement_origin"], "Hazards", hazard["hazard_id"]
        )
        effects = summaries(
            hazard["effect_requirement_origins"], "Hazards", hazard["hazard_id"]
        )
        rows.append(
            [
                hazard["hazard_id"],
                plain(hazard["trigger"]),
                value_text(likelihood),
                value_text(recurrence),
                "; ".join(value_text(d) for d in effects) or "not supplied",
                statuses([likelihood, recurrence] + effects),
                evidence([likelihood, recurrence] + effects),
            ]
        )
    for item in pack.get("research_items", []):
        if item["kind"] == "hazard":
            rows.append(
                [
                    item["research_item_id"],
                    "not an executable trigger",
                    item["quote"],
                    "not supplied",
                    "none (non-executable)",
                    "research note",
                    provenance(item["ref_ids"], "Hazards", item["research_item_id"]),
                ]
            )
    for req in pack["requirements"]:
        if (
            req["kind"] == "hazard"
            and req["requirement_id"] not in represented
            and any(c["role"] == "research_note" for c in req["consumers"])
        ):
            data = info(req["origin_pointer"], "Hazards", req["requirement_id"])
            rows.append(
                [
                    req["requirement_id"],
                    "not supplied",
                    value_text(data),
                    "unknown",
                    "none",
                    data["status"],
                    data["source"],
                ]
            )
    table(
        "Hazards",
        [
            "Hazard",
            "Declared trigger",
            "Likelihood / rate evidence",
            "Recurrence evidence",
            "Effect evidence",
            "Status",
            "Source",
        ],
        rows,
    )

    rows = []
    for indicator in pack["indicators"]:
        data = info(
            indicator["requirement_origin"], "Indicators", indicator["indicator_id"]
        )
        rows.append(
            [
                indicator["indicator_id"],
                indicator["node_id"],
                value_text(data),
                plain(indicator["trigger"]),
                consumers([indicator["consumer"]]),
                data["status"],
                data["source"],
            ]
        )
    for item in pack.get("research_items", []):
        if item["kind"] == "indicator":
            rows.append(
                [
                    item["research_item_id"],
                    "not supplied",
                    item["quote"],
                    "not supplied",
                    "research_note; non-executable",
                    "research note",
                    provenance(item["ref_ids"], "Indicators", item["research_item_id"]),
                ]
            )
    for req in pack["requirements"]:
        if (
            req["kind"] == "indicator"
            and req["requirement_id"] not in represented
            and any(c["role"] == "research_note" for c in req["consumers"])
        ):
            data = info(req["origin_pointer"], "Indicators", req["requirement_id"])
            rows.append(
                [
                    req["requirement_id"],
                    "not supplied",
                    value_text(data),
                    "not supplied",
                    "research_note; non-executable",
                    data["status"],
                    data["source"],
                ]
            )
    table(
        "Indicators",
        [
            "Indicator",
            "Node",
            "Evidence",
            "Declared predicate",
            "Consumer",
            "Status",
            "Source",
        ],
        rows,
    )

    rows = []
    for reference in pack["reference_classes"]:
        members = summaries(
            reference["membership_requirement_origins"],
            "Reference classes",
            reference["reference_class_id"],
        )
        ids = set(reference["observation_ids"])
        ids.update(
            v["observation_id"]
            for d in members
            for v in d["values"]
            if "observation_id" in v
        )
        values = [observations[oid] for oid in sorted(ids) if oid in observations]
        for oid in ids - observations.keys():
            missing(
                "Reference classes",
                reference["reference_class_id"],
                "member",
                "missing_observation",
                oid,
            )
        rows.append(
            [
                reference["reference_class_id"],
                reference["purpose"],
                "; ".join(
                    quantity(v["value"]) + " (" + v["value_kind"] + ")" for v in values
                )
                or "not supplied",
                statuses(members),
                provenance(
                    [rid for v in values for rid in v["ref_ids"]],
                    "Reference classes",
                    reference["reference_class_id"],
                ),
            ]
        )
    for item in pack.get("research_items", []):
        if item["kind"] == "reference_class":
            rows.append(
                [
                    item["research_item_id"],
                    "research note",
                    item["quote"],
                    "non-executable",
                    provenance(
                        item["ref_ids"], "Reference classes", item["research_item_id"]
                    ),
                ]
            )
    for req in pack["requirements"]:
        if (
            req["kind"] == "reference_class"
            and req["requirement_id"] not in represented
            and any(c["role"] == "research_note" for c in req["consumers"])
        ):
            data = info(
                req["origin_pointer"], "Reference classes", req["requirement_id"]
            )
            rows.append(
                [
                    req["requirement_id"],
                    "research requirement",
                    value_text(data),
                    data["status"],
                    data["source"],
                ]
            )
    table(
        "Reference classes",
        [
            "Class",
            "Purpose",
            "Members / evidence (no inferred base rate)",
            "Status",
            "Source",
        ],
        rows,
    )
    table(
        "Identities",
        [
            "Identity",
            "Left node",
            "Right mechanism",
            "Absolute tolerance",
            "Relative tolerance",
            "Scale unit",
            "Basis / evaluation",
            "Source",
        ],
        [
            [
                i["identity_id"],
                i["lhs_node_id"],
                i["rhs_mechanism_id"],
                i["absolute_tolerance"],
                i["relative_tolerance"],
                unit(i["scale_unit"]),
                info(i["basis_requirement_origin"], "Identities", i["identity_id"])[
                    "status"
                ]
                + "; residual not evaluated by this sheet",
                info(i["basis_requirement_origin"], "Identities", i["identity_id"])[
                    "source"
                ],
            ]
            for i in pack["identities"]
        ],
    )

    table(
        "Evidence inventory",
        [
            "Observation",
            "Value / statement",
            "Unit",
            "Reference period",
            "Vintage",
            "Value kind",
            "Known by",
            "Value source quotation",
            "Source",
        ],
        [
            [
                o["observation_id"],
                quantity(o["value"]),
                unit(o["identity"]["unit"]) if o["identity"] else "not applicable",
                period(o["identity"]["reference_period"])
                if o["identity"]
                else "not applicable",
                time(o["vintage"]),
                o["value_kind"],
                time(o["known_by"]),
                next(
                    (v["expected"] for v in o["support"] if v["field"] == "value"),
                    "[not_supplied]",
                ),
                provenance(o["ref_ids"], "Evidence inventory", o["observation_id"]),
            ]
            for o in sorted(pack["observations"], key=lambda v: v["observation_id"])
        ],
    )
    lines.extend(
        [
            "",
            "Same-reference-period forecasts remain revisions; this sheet never treats them as a growth series.",
        ]
    )
    table(
        "Research items",
        [
            "Item",
            "Kind",
            "Actor",
            "Exact supported quote",
            "Class",
            "Audience",
            "Known by",
            "Effective at",
            "Visible at",
            "Executable",
            "Source",
        ],
        [
            [
                r["research_item_id"],
                r["kind"],
                actor_label(r["actor_ref"])[0] if r["actor_ref"] else "not supplied",
                r["quote"],
                r["value_kind"] + " / " + r["producer_class"],
                plain(r["audience"]),
                time(r["known_by"]),
                time(r["effective_at"]),
                time(r["visible_at"]),
                "false",
                provenance(r["ref_ids"], "Research items", r["research_item_id"]),
            ]
            for r in pack.get("research_items", [])
        ],
    )
    table(
        "Sources",
        [
            "Scoped source ID",
            "Retained title",
            "URL",
            "Tier",
            "Retention",
            "Capture / completeness",
            "Published at",
            "Retrieved at",
            "Content SHA256",
        ],
        [
            [
                source_label(s),
                s["title"],
                s["url"],
                s["tier"],
                s["retention"],
                plain(s["capture"]),
                time(s["published_at"]),
                time(s["retrieved_at"]),
                s["content_hash"],
            ]
            for s in sorted(
                pack["sources"], key=lambda v: (v["track_id"], v["local_source_id"])
            )
        ],
    )
    table(
        "Requirements",
        [
            "Kind / origin",
            "Cardinality",
            "Admitted value / statement",
            "Status",
            "Source / basis",
            "Requirement ID",
        ],
        [
            [
                r["kind"] + " / " + r["origin_pointer"],
                r.get("cardinality", "one"),
                value_text(
                    info(r["origin_pointer"], "Requirements", r["requirement_id"])
                ),
                info(r["origin_pointer"], "Requirements", r["requirement_id"])[
                    "status"
                ],
                info(r["origin_pointer"], "Requirements", r["requirement_id"])[
                    "source"
                ],
                r["requirement_id"],
            ]
            for r in pack["requirements"]
        ],
    )
    table(
        "Gaps",
        ["Code", "Requirement", "Blocking engines", "Related IDs", "Detail"],
        [
            [
                g["code"],
                g["requirement_id"],
                ", ".join(g["blocking_engines"]) or "none",
                ", ".join(g["related_ids"]),
                g["detail"],
            ]
            for g in pack["gaps"]
        ],
    )
    table(
        "Coverage",
        ["Metric", "Count"],
        [[k, v] for k, v in sorted(pack["coverage"].items()) if k != "omissions"],
    )
    table(
        "Admission readiness",
        ["Engine", "Prerequisites", "Blocking gaps", "Unmet requirements"],
        [
            [
                r["engine"],
                r["status"],
                ", ".join(r["blocking_gap_ids"]) or "none",
                ", ".join(r["unmet_requirement_ids"]) or "none",
            ]
            for r in pack["readiness"]
        ],
    )
    table(
        "Input omissions",
        ["Artifact", "Track", "Pointer", "Reason", "Declared count"],
        [
            [
                o["artifact_id"],
                o["track_id"],
                o["pointer"],
                o["reason"],
                o["declared_count"],
            ]
            for o in pack["coverage"]["omissions"]
        ],
    )
    table(
        "Candidate selection",
        ["Requirement", "Retained shortlist", "Excluded counts"],
        [
            [r["requirement_id"], len(r["ranked"]), plain(r["excluded_counts"])]
            for r in pack["candidates"]["rows"]
        ],
    )
    table(
        "Resolution attempts",
        ["Attempt", "Kind", "Outcome", "Requirements", "Code", "Receipt"],
        [
            [
                r["attempt_id"],
                r["kind"],
                r["outcome"],
                ", ".join(r["requirement_ids"]),
                r["code"],
                r["receipt_artifact_id"],
            ]
            for r in pack["resolution_attempts"]
        ],
    )
    table("Metering", ["Field", "Recorded value"], sorted(pack["metering"].items()))
    table(
        "Rendering omissions",
        ["Section", "Item", "Field", "Code", "Reference"],
        sorted(omitted),
    )
    result = ("\n".join(lines) + "\n").encode("utf-8")
    _need(len(result) <= MAX_JSON, "E_LIMIT", "anchor_sheet")
    return result


def _render(pack, *, index, requirements, policy):
    digest = anchor_hash(pack)
    return {
        "world_anchor.json": _bytes(pack),
        "world_anchor.md": _anchor_sheet(
            pack, index=index, requirements=requirements, policy=policy
        ),
        "world_anchor_gaps.json": _bytes(
            {
                "schema_version": "world-anchor-gaps/v1",
                "pack_hash": digest,
                "gaps": pack["gaps"],
            }
        ),
        "world_anchor_coverage.json": _bytes(
            {
                "schema_version": "world-anchor-coverage/v1",
                "pack_hash": digest,
                "coverage": pack["coverage"],
                "readiness": pack["readiness"],
            }
        ),
    }


def emit_pack(directory, pack, *, requirements, index, policy):
    pack = validate_pack(pack, requirements=requirements, index=index, policy=policy)
    payloads = _render(pack, index=index, requirements=requirements, policy=policy)
    try:
        fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    except OSError:
        raise AnchorError("E_PATH", "output_directory") from None
    files = []
    try:
        for name, data in sorted(payloads.items()):
            try:
                existing = _read(directory, name, MAX_JSON)
            except AnchorError as exc:
                if exc.code != "E_FILE_MISSING":
                    raise
            else:
                _need(existing == data, "E_IMMUTABLE", name)
                files.append(
                    {
                        "path": name,
                        "sha256": hashlib.sha256(data).hexdigest(),
                        "bytes": len(data),
                    }
                )
                continue
            temp = ".anchor-" + os.urandom(12).hex()
            out = None
            try:
                out = os.open(
                    temp,
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                    0o600,
                    dir_fd=fd,
                )
                with os.fdopen(out, "wb") as stream:
                    out = None
                    stream.write(data)
                    stream.flush()
                    os.fsync(stream.fileno())
                try:
                    os.link(
                        temp, name, src_dir_fd=fd, dst_dir_fd=fd, follow_symlinks=False
                    )
                except FileExistsError:
                    _need(_read(directory, name, MAX_JSON) == data, "E_IMMUTABLE", name)
            finally:
                if out is not None:
                    os.close(out)
                os.unlink(temp, dir_fd=fd)
            files.append(
                {
                    "path": name,
                    "sha256": hashlib.sha256(data).hexdigest(),
                    "bytes": len(data),
                }
            )
        os.fsync(fd)
    finally:
        os.close(fd)
    return {
        "schema_version": "world-anchor-emission/v1",
        "scope": pack["scope"],
        "pack_hash": anchor_hash(pack),
        "contract_hash": pack["contract_hash"],
        "input_hash": pack["input_hash"],
        "policy_hash": pack["policy_hash"],
        "files": files,
    }


def read_pack(
    directory,
    receipt,
    *,
    expected_receipt_hash,
    expected_pack_hash,
    requirements,
    index,
    policy,
):
    _object(
        receipt,
        "schema_version scope pack_hash contract_hash input_hash policy_hash files",
    )
    _need(
        anchor_hash(receipt) == _hash(expected_receipt_hash)
        and receipt["pack_hash"] == _hash(expected_pack_hash),
        "E_HASH",
        "emission_receipt",
    )
    _need(receipt["schema_version"] == "world-anchor-emission/v1", "E_VERSION")
    names = {
        "world_anchor.json",
        "world_anchor.md",
        "world_anchor_gaps.json",
        "world_anchor_coverage.json",
    }
    _need(
        len(receipt["files"]) == 4 and {f["path"] for f in receipt["files"]} == names,
        "E_PUBLICATION",
        "files",
    )
    raw = {}
    for item in receipt["files"]:
        _object(item, "path sha256 bytes")
        data = _read(directory, item["path"], MAX_JSON)
        _need(
            len(data) == item["bytes"]
            and hashlib.sha256(data).hexdigest() == item["sha256"],
            "E_HASH",
            item["path"],
        )
        raw[item["path"]] = data
    pack = validate_pack(
        _load(raw["world_anchor.json"]),
        requirements=requirements,
        index=index,
        policy=policy,
    )
    _need(
        anchor_hash(pack) == expected_pack_hash
        and raw == _render(pack, index=index, requirements=requirements, policy=policy),
        "E_HASH",
        "pack",
    )
    _need(
        all(
            receipt[k] == pack[k]
            for k in ("scope", "contract_hash", "input_hash", "policy_hash")
        ),
        "E_SCOPE",
        "receipt",
    )
    return pack


def engine_projection(pack, *, requirements, index, policy, engine):
    """Project admitted data; the installed consumer owns executable admission.

    The policy hash authenticates declarations. It cannot establish that an
    adapter/version is installed or implements the projected semantics.
    """
    pack = validate_pack(pack, requirements=requirements, index=index, policy=policy)
    _need(engine in ENGINES, "E_SCHEMA", "engine")
    _need(
        next(r for r in pack["readiness"] if r["engine"] == engine)["status"]
        == "ready",
        "E_NOT_READY",
        engine,
    )
    reqs = {r["requirement_id"]: r for r in pack["requirements"]}

    def engine_consumer(consumer):
        return consumer["engine"] == engine and consumer["role"] != "research_note"

    research_only = {
        rid
        for rid, r in reqs.items()
        if all(c["role"] == "research_note" for c in r["consumers"])
    }
    req_ids = {
        rid
        for rid, r in reqs.items()
        if any(engine_consumer(c) for c in r["consumers"])
    }
    pending = list(req_ids)
    while pending:
        for dependency in reqs[pending.pop()]["dependency_ids"]:
            # Research notes remain in the analyst inventory. Traversing through
            # them would also grant execution to their otherwise unrelated bases.
            if dependency not in req_ids and dependency not in research_only:
                req_ids.add(dependency)
                pending.append(dependency)
    origins = {reqs[rid]["origin_pointer"] for rid in req_ids}

    def projected_origins(values):
        return all(value is None or value in origins for value in values)

    bindings = [
        b
        for b in pack["bindings"]
        if b["requirement_id"] in req_ids and b["status"] == "bound"
    ]
    oids = {oid for b in bindings for oid in b["observation_ids"]}
    observations = [o for o in pack["observations"] if o["observation_id"] in oids]
    refs = {rid for o in observations for rid in o["ref_ids"]}
    bids = {b["binding_id"] for b in bindings}
    mechanisms = [
        m
        for m in pack["mechanisms"]
        if any(engine_consumer(c) for c in m["consumers"])
        and projected_origins(
            [p["requirement_origin"] for p in m["parameters"]]
            + [m["lag_requirement_origin"]]
            + m["applicability_requirement_origins"]
        )
    ]
    mechanism_ids = {m["mechanism_id"] for m in mechanisms}
    return {
        "schema_version": "world-anchor-engine/v1",
        "engine": engine,
        "scope": pack["scope"],
        "pack_hash": anchor_hash(pack),
        "contract_hash": pack["contract_hash"],
        "input_hash": pack["input_hash"],
        "variables": [v for v in pack["variables"] if v["binding_id"] in bids],
        "observations": observations,
        "bindings": bindings,
        "references": [r for r in pack["references"] if r["ref_id"] in refs],
        "mechanisms": mechanisms,
        "identities": [
            i
            for i in pack["identities"]
            if i["rhs_mechanism_id"] in mechanism_ids
            and projected_origins([i["basis_requirement_origin"]])
        ],
        "calendar": [
            c
            for c in pack["calendar"]
            if c["requirement_origin"] in origins
            and projected_origins(
                [c["time_requirement_origin"]] + c["effect_requirement_origins"]
            )
        ],
        "hazards": [
            h
            for h in pack["hazards"]
            if any(engine_consumer(c) for c in h["consumers"])
            and projected_origins(
                [h["likelihood_requirement_origin"], h["recurrence_requirement_origin"]]
                + h["effect_requirement_origins"]
            )
        ],
        "indicators": [
            i
            for i in pack["indicators"]
            if engine_consumer(i["consumer"]) and i["requirement_origin"] in origins
        ],
        "gap_ids": [
            g["gap_id"]
            for g in pack["gaps"]
            if engine in g["blocking_engines"] or g["requirement_id"] in req_ids
        ],
    }


def actor_projection(pack, *, requirements, index, policy, actor_ref, at):
    pack = validate_pack(pack, requirements=requirements, index=index, policy=policy)
    instant = _instant(at)
    knowledge_limit = min(instant, _instant(pack["scope"]["cutoff"]))
    _text(actor_ref)
    research_only = {
        r["requirement_id"]
        for r in pack["requirements"]
        if all(c["role"] == "research_note" for c in r["consumers"])
    }
    allowed = {
        oid
        for b in pack["bindings"]
        if b["status"] == "bound" and b["requirement_id"] not in research_only
        for oid in b["observation_ids"]
    }
    items = []
    for obs in pack["observations"]:
        if (
            obs["observation_id"] not in allowed
            or obs["producer_class"]
            in {"research_analyst", "model_prior", "simulation"}
            or obs["value_kind"] in {"analyst_inferred", "assumed", "simulated"}
            or obs["actor_basis"] == "none"
        ):
            continue
        audience = obs["audience"]
        if audience["kind"] == "analyst" or (
            audience["kind"] == "actors" and actor_ref not in audience["actor_refs"]
        ):
            continue
        known, visible = _time(obs["known_by"]), _time(obs["visible_at"])
        if (
            known is None
            or visible is None
            # A visibility grant can delay release, never backdate knowledge.
            or known > knowledge_limit
            or visible > instant
        ):
            continue
        item = {
            "text": json.dumps(
                obs["value"], ensure_ascii=False, sort_keys=True, separators=(",", ":")
            ),
            "value": obs["value"],
            "value_kind": obs["value_kind"],
            "identity": obs["identity"],
            "public_source_url": None,
            "known_by": obs["known_by"]["value"],
            "effective_at": obs["effective_at"]["value"],
        }
        items.append({"item_id": _id("actor_item", item), **item})
    return {
        "schema_version": "world-anchor-actor/v1",
        "actor_ref": actor_ref,
        "at": at,
        "items": sorted(items, key=lambda r: r["item_id"]),
    }


def prepare_world_parameters(
    pack, requests, *, expected_pack_hash, requirements, index, policy
):
    _need(anchor_hash(pack) == _hash(expected_pack_hash), "E_HASH", "pack")
    engine_projection(
        pack, requirements=requirements, index=index, policy=policy, engine="world-v1"
    )
    reqs = {r["requirement_id"]: r for r in requirements["requirements"]}
    bindings = {b["binding_id"]: b for b in pack["bindings"]}
    observations = {o["observation_id"]: o for o in pack["observations"]}
    refs = {r["ref_id"]: r for r in pack["references"]}
    parameters = []
    targets = set()
    request_ids = set()
    pattern = r"/(?:initialState/(?:accounts/[^/]+/balance|(?:metrics|rules|relations)/[^/]+/value)|actionCatalog/(?:0|[1-9][0-9]*)/(?:parameters/[^/]+|inputs/[^/]+/(?:min|max))|scheduledEvents/(?:0|[1-9][0-9]*)/parameters/[^/]+|flows/(?:0|[1-9][0-9]*)/ratePerDay)"
    for request in _list(requests, 1024):
        _object(
            request,
            "request_id requirement_id binding_id observation_id field target target_object_id identity expected_value",
        )
        _need(
            request["target"] not in targets
            and request["request_id"] not in request_ids,
            "E_REFERENCE",
            "duplicate_parameter",
        )
        targets.add(request["target"])
        request_ids.add(request["request_id"])
        _need(
            re.fullmatch(pattern, request["target"])
            and request["field"] in {"value", "range.low", "range.high"},
            "E_REFERENCE",
            "parameter_path",
        )
        _need(
            request["requirement_id"] in reqs and request["binding_id"] in bindings,
            "E_REFERENCE",
            "parameter_binding",
        )
        req, binding = reqs[request["requirement_id"]], bindings[request["binding_id"]]
        _need(
            req.get("cardinality", "one") == "one",
            "E_REFERENCE",
            "collection_parameter",
        )
        _need(
            binding["requirement_id"] == req["requirement_id"]
            and binding["status"] == "bound"
            and req["identity"] == request["identity"],
            "E_REFERENCE",
            "parameter_identity",
        )
        _need(
            any(
                c["engine"] == "world-v1"
                and c["role"] == "compiler_parameter"
                and c["object_id"] == request["target_object_id"]
                and c["field"] == request["target"]
                for c in req["consumers"]
            ),
            "E_REFERENCE",
            "parameter_consumer",
        )
        if binding["assumption"]:
            _need(
                request["observation_id"] is None,
                "E_REFERENCE",
                "assumption_observation",
            )
            source = {
                "value": binding["assumption"]["value"],
                "value_kind": "assumed",
                "producer_class": "model_prior",
                "audience": {"kind": "analyst", "actor_refs": []},
                "ref_ids": [],
                **{
                    k: _unknown_time()
                    for k in ("available_at", "known_by", "effective_at", "visible_at")
                },
            }
        else:
            _need(
                request["observation_id"] in binding["observation_ids"],
                "E_REFERENCE",
                "parameter_observation",
            )
            source = observations[request["observation_id"]]
        value = source["value"]
        if request["field"] != "value":
            _need(
                value["kind"] == "range"
                and request["target"].endswith(
                    "/min" if request["field"] == "range.low" else "/max"
                ),
                "E_REFERENCE",
                "range_mapping",
            )
            value = {"kind": "number", "value": value[request["field"].split(".")[1]]}
        _need(value == request["expected_value"], "E_REFERENCE", "parameter_value")
        parameters.append(
            {
                k: request[k]
                for k in (
                    "request_id",
                    "requirement_id",
                    "binding_id",
                    "observation_id",
                    "field",
                    "target",
                    "target_object_id",
                    "identity",
                )
            }
            | {
                "value": value,
                **{
                    k: source[k]
                    for k in (
                        "value_kind",
                        "producer_class",
                        "audience",
                        "available_at",
                        "known_by",
                        "effective_at",
                        "visible_at",
                        "ref_ids",
                    )
                },
                "source_bindings": [refs[rid] for rid in source["ref_ids"]],
                "assumption": binding["assumption"],
            }
        )
    return {
        "schema_version": "prepared-typed-world/v1",
        "engine": "world-v1",
        "scope": pack["scope"],
        "pack_hash": expected_pack_hash,
        "contract_hash": pack["contract_hash"],
        "input_hash": pack["input_hash"],
        "parameters": parameters,
    }
