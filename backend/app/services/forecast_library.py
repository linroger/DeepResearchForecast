"""Small source-aware cross-case library; no acquisition or import-time I/O.

``root`` is the library directory (normally backend/uploads/_library), NOT a
case directory; its parent must exist before writing. Each kind has its own
directory of immutable content-ID JSON.
Both APIs raise LibraryError for invalid input, corruption or unverified proof;
I/O errors propagate. A missing library selects as []. Returned rows are detached
JSON with ``entryId`` added. No forecast, score or probability-policy ledger is
created. The coordinator must construct entries from validated case metadata.

Entry schema (unknown fields are rejected):
  schemaVersion: "forecast-library/v1" (may be omitted on write)
  kind: reference_class | mechanism | actor
  title: nonempty text; nodeTerms: nonempty list of matching labels
  asOf, evidenceDate, availableAt: ISO dates or timezone-aware timestamps
  sources: nonempty list of forecast-case/v1 source objects (all nine fields)
  provenance: {caseId, caseHash: SHA256, recordId,
               basis: observed | estimated | assumed | journal_outcome,
               journalProof?: {reportId, forecastId, publicationSha256,
                               eventSha256}}
  uncertainty: nonempty text; gaps: list of nonempty text
  content, by kind:
    reference_class: {series, units, comparator: {operator, threshold},
                      sampleSize, eventCount, windowStart, windowEnd}
    mechanism: {template, parameters: {name: scalar | vector | bounded prior},
                inputNodes?: list[node descriptor], outputNode?: node descriptor}
    actor: {name, actorClass, levers: list[text], record: text}

Reference-class counts require fetched primary sources and are descriptive
frequencies, never forecast probabilities. Mechanisms retain uncertain parameters;
this API does not claim hindcast validation. Actors describe real-world records,
never a simulation's self-rating. Assumed entries require explicit gaps.

Outcome-derived entries MUST use basis=journal_outcome and journalProof. The
configured production forecast journal is the sole outcome authority (resolved
through forecast_ledger.ledger_dir), independent of root or untrusted entry paths.
eventSha256 hashes the canonical {schema_version:1,type:"outcome",record:row}
event, NOT just the outcome row. The existing journal reader validates its full
hash chain and recomputes the outcome's publication/evidence binding on both write
and selection. Supported journal-derived learning is limited to a reference-class
entry bound to one exact official observation, including counts and comparator.
Current outcomes contain no independently admitted actor/behaviour or mechanism/
parameter claim binding: journal_outcome actor and mechanism entries, including
individual mechanism parameters, are rejected. Copying publisher/evidence text
cannot supply that binding. Source-backed manually observed actor records and
inherited mechanism assumptions remain supported without journal authority.
This proves journal integrity, not truth or prospective held-out forecasting lift;
library reuse NEVER authorizes changing estimator weights or probability policy.

Dates retain their original precision: a date-only value means end of that UTC
day for comparisons. Unknown publication dates require an explicit gap; retrieval
is not substituted for publication. availableAt must cover all source dates and
the outcome resolution date. Selection uses exact case-insensitive nodeTerms
overlap, then newest availableAt, then entryId; no hidden semantic/model search.
"""
from __future__ import annotations

from datetime import date, datetime, time, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat
import tempfile
from urllib.parse import urlsplit


SCHEMA = "forecast-library/v1"
KINDS = ("reference_class", "mechanism", "actor")
_MAX_BYTES = 262144
_HEX = re.compile(r"[0-9a-f]{64}\Z")
_ID = re.compile(r"fl1-[0-9a-f]{64}\Z")


class LibraryError(ValueError):
    """Closed library validation failure; filesystem errors propagate separately."""


def _require(condition, reason):
    if not condition:
        raise LibraryError(reason)


def _object(value, fields, optional=()):
    _require(type(value) is dict and set(fields) <= value.keys()
             and value.keys() <= set(fields) | set(optional), "invalid_object_fields")


def _text(value):
    _require(type(value) is str and bool(value.strip()) and value == value.strip(), "invalid_text")
    return value


def _texts(value, *, empty=False):
    _require(type(value) is list and (empty or bool(value)), "invalid_text_list")
    for item in value:
        _text(item)
    _require(len(set(value)) == len(value), "duplicate_text")
    return value


def _instant(value):
    _text(value)
    try:
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
            return datetime.combine(date.fromisoformat(value), time.max, timezone.utc)
        _require("T" in value, "invalid_timestamp")
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
        _require(result.tzinfo is not None, "timestamp_requires_timezone")
        return result.astimezone(timezone.utc)
    except ValueError as exc:
        raise LibraryError("invalid_timestamp") from exc


def _not_future(value):
    moment = _instant(value)
    now = datetime.now(timezone.utc)
    _require(moment.date() <= now.date() if len(value) == 10 else moment <= now,
             "future_evidence")
    return moment


def _number(value):
    _require(type(value) in (int, float) and math.isfinite(value), "invalid_number")
    return value


def _sha(value):
    _require(type(value) is str and _HEX.fullmatch(value), "invalid_sha256")


def _encoded(value, *, bounded=True):
    # No coercion of tuple, integer keys, custom objects, NaN or infinity to JSON.
    def check(item):
        if type(item) is dict:
            _require(all(type(k) is str for k in item), "invalid_json_key")
            for child in item.values():
                check(child)
        elif type(item) is list:
            for child in item:
                check(child)
        elif type(item) is float:
            _require(math.isfinite(item), "invalid_json_number")
        else:
            _require(item is None or type(item) in (str, int, bool), "invalid_json_value")
    try:
        check(value)
        data = json.dumps(value, sort_keys=True, ensure_ascii=False,
                          separators=(",", ":"), allow_nan=False).encode("utf-8")
        _require(not bounded or len(data) <= _MAX_BYTES, "entry_too_large")
        return data
    except (TypeError, ValueError, OverflowError, RecursionError) as exc:
        raise LibraryError("invalid_json") from exc


def _digest(value):
    return hashlib.sha256(_encoded(value)).hexdigest()


def _parameter(value, entry):
    if type(value) is list:
        for item in value:
            _parameter(item, entry)
    elif type(value) is dict:
        _object(value, ("low", "high"), ("basis", "gap", "sourceIds"))
        _require(_number(value["low"]) <= _number(value["high"]), "invalid_parameter_range")
        basis = value.get("basis", entry["provenance"]["basis"])
        _require(basis != "journal_outcome", "unsupported_journal_mechanism_proof")
        _require(basis in ("observed", "estimated", "assumed"), "invalid_parameter_basis")
        if "gap" in value:
            _text(value["gap"])
        if basis == "assumed":
            _require(value.get("gap") or entry["gaps"], "assumption_gap_required")
        if "sourceIds" in value:
            _require(set(_texts(value["sourceIds"], empty=True)) <= {s["sourceId"] for s in entry["sources"]},
                     "unresolved_parameter_source")
    else:
        _number(value)


def _source(source):
    _object(source, ("sourceId", "url", "title", "publishedAt", "retrievedAt",
                     "originCluster", "tier", "fetched", "passage"))
    for name in ("sourceId", "url", "title", "originCluster"):
        _text(source[name])
    try:
        url = urlsplit(source["url"])
        _require(url.scheme in ("http", "https") and url.hostname and not url.username
                 and not url.password, "invalid_source_url")
    except ValueError as exc:
        raise LibraryError("invalid_source_url") from exc
    _require(source["tier"] in ("primary", "secondary", "social", "unknown"), "invalid_source_tier")
    _require(type(source["fetched"]) is bool and type(source["passage"]) is str,
             "invalid_source_evidence")
    if source["fetched"]:
        _text(source["passage"])
    retrieved = _not_future(source["retrievedAt"])
    if source["publishedAt"] is not None:
        _require(_not_future(source["publishedAt"]) <= retrieved, "publication_after_retrieval")
    return retrieved


def _content(entry):
    content, kind = entry["content"], entry["kind"]
    if kind == "reference_class":
        _object(content, ("series", "units", "comparator", "sampleSize", "eventCount",
                          "windowStart", "windowEnd"))
        _text(content["series"])
        _text(content["units"])
        comparator = content["comparator"]
        _object(comparator, ("operator", "threshold"))
        _require(comparator["operator"] in ("lt", "lte", "gt", "gte", "eq"), "invalid_comparator")
        _number(comparator["threshold"])
        n, hits = content["sampleSize"], content["eventCount"]
        _require(type(n) is int and n > 0 and type(hits) is int and 0 <= hits <= n, "invalid_counts")
        _require(_instant(content["windowStart"]) <= _instant(content["windowEnd"])
                 <= _instant(entry["evidenceDate"]), "invalid_reference_window")
        _require(entry["provenance"]["basis"] in ("observed", "journal_outcome"), "reference_requires_observations")
        _require(any(s["fetched"] and s["tier"] == "primary" for s in entry["sources"]),
                 "reference_requires_primary_source")
    elif kind == "mechanism":
        _object(content, ("template", "parameters"), ("inputNodes", "outputNode"))
        _require(content["template"] in ("growth", "sum", "product", "linear", "supply_demand",
                                         "adoption", "regulatory_milestone"), "invalid_template")
        parameters = content["parameters"]
        _require(type(parameters) is dict, "invalid_parameters")
        for name, value in parameters.items():
            _text(name)
            _parameter(value, entry)
        _require(("inputNodes" in content) == ("outputNode" in content), "incomplete_node_descriptors")
        if "inputNodes" in content:
            _require(type(content["inputNodes"]) is list, "invalid_node_descriptors")
            for node in [*content["inputNodes"], content["outputNode"]]:
                _object(node, ("nodeId", "label", "units", "vintage", "sourceIds"))
                for name in ("nodeId", "label", "units"):
                    _text(node[name])
                _require(set(_texts(node["sourceIds"], empty=True)) <= {s["sourceId"] for s in entry["sources"]},
                         "unresolved_node_source")
                if node["vintage"] is not None:
                    _require(_instant(node["vintage"]) <= _instant(entry["evidenceDate"]), "node_vintage_after_evidence")
    else:
        _object(content, ("name", "actorClass", "levers", "record"))
        for name in ("name", "actorClass", "record"):
            _text(content[name])
        _texts(content["levers"])
        _require(entry["provenance"]["basis"] in ("observed", "journal_outcome"),
                 "actor_requires_real_world_record")


def _validate(entry):
    entry = json.loads(_encoded(entry))
    _require(type(entry) is dict, "invalid_entry")
    entry.setdefault("schemaVersion", SCHEMA)
    _object(entry, ("schemaVersion", "kind", "title", "nodeTerms", "asOf", "evidenceDate",
                    "availableAt", "sources", "provenance", "uncertainty", "gaps", "content"))
    _require(entry["schemaVersion"] == SCHEMA and entry["kind"] in KINDS, "invalid_schema_or_kind")
    _text(entry["title"])
    _texts(entry["nodeTerms"])
    _text(entry["uncertainty"])
    _texts(entry["gaps"], empty=True)
    cutoff, available = _not_future(entry["asOf"]), _not_future(entry["availableAt"])
    _require(_not_future(entry["evidenceDate"]) <= available <= cutoff, "entry_cutoff")
    sources = entry["sources"]
    _require(type(sources) is list and bool(sources), "sources_required")
    for source in sources:
        _require(_source(source) <= available, "source_unavailable")
        _require(source["publishedAt"] is not None or bool(entry["gaps"]), "publication_gap_required")
    _require(len({s["sourceId"] for s in sources}) == len(sources), "duplicate_source_id")
    provenance = entry["provenance"]
    _object(provenance, ("caseId", "caseHash", "recordId", "basis"), ("journalProof",))
    for name in ("caseId", "recordId"):
        _text(provenance[name])
    _sha(provenance["caseHash"])
    basis = provenance["basis"]
    _require(basis in ("observed", "estimated", "assumed", "journal_outcome"), "invalid_basis")
    if basis == "assumed":
        _require(bool(entry["gaps"]), "assumption_gap_required")
    else:
        _require(any(s["fetched"] for s in sources), "fetched_evidence_required")
    _require((basis == "journal_outcome") == ("journalProof" in provenance), "journal_proof_required")
    if basis == "journal_outcome":
        proof = provenance["journalProof"]
        _object(proof, ("reportId", "forecastId", "publicationSha256", "eventSha256"))
        _text(proof["reportId"])
        _text(proof["forecastId"])
        _sha(proof["publicationSha256"])
        _sha(proof["eventSha256"])
        # Journal integrity is not an admitted actor/behaviour or parameter binding.
        # Validate on both writes and reads so old unsupported learning stays closed.
        _require(entry["kind"] == "reference_class",
                 "unsupported_journal_" + entry["kind"] + "_proof")
    _content(entry)
    return entry


def _verify_outcome(entry):
    proof = entry["provenance"].get("journalProof")
    if proof is None:
        return
    from .forecast_feedback import ForecastFeedbackError, read_published_resolutions
    try:
        rows = read_published_resolutions(proof["reportId"])
    except ForecastFeedbackError as exc:
        raise LibraryError("invalid_outcome_journal") from exc
    row = next((r for r in rows if r["forecast_id"] == proof["forecastId"]), None)
    _require(row is not None and row["kind"] in ("official_data_binary", "named_source_event"),
             "verified_external_outcome_required")
    event_hash = hashlib.sha256(_encoded({"schema_version": 1, "type": "outcome", "record": row}, bounded=False)).hexdigest()
    _require(row["publication_sha256"] == proof["publicationSha256"]
             and event_hash == proof["eventSha256"],
             "outcome_proof_mismatch")
    _require(_instant(row["resolved_at"]) <= _instant(entry["availableAt"]), "outcome_after_availability")
    evidence = row["evidence"]
    source_url = evidence.get("source_url") if row["kind"] == "official_data_binary" else evidence.get("url")
    _require(source_url and any(s["url"] == source_url and s["fetched"] for s in entry["sources"]),
             "outcome_source_mismatch")
    for field in ("retrieved_at", "published_at"):
        if evidence.get(field):
            _require(_instant(evidence[field]) <= _instant(entry["availableAt"]),
                     "outcome_evidence_after_availability")
    if entry["kind"] == "reference_class":
        content = entry["content"]
        anchor, observation = evidence.get("data_anchor", {}), evidence.get("observation", {})
        operators = {"<": "lt", "<=": "lte", ">": "gt", ">=": "gte", "==": "eq", "=": "eq"}
        _require(evidence.get("series") == content["series"] and evidence.get("units") == content["units"]
                 and content["sampleSize"] == 1 and content["eventCount"] == int(row["outcome"])
                 and content["comparator"] == {"operator": operators.get(anchor.get("comparator")),
                                               "threshold": anchor.get("threshold")}
                 and content["windowStart"] == content["windowEnd"] == observation.get("date"),
                 "outcome_reference_mismatch")


def _directory(root, kind):
    root = Path(root)
    _require(not root.is_symlink(), "symlink_library")
    directory = root / kind
    _require(not directory.is_symlink(), "symlink_kind")
    return directory


def _read(path):
    _require(_ID.fullmatch(path.stem), "invalid_entry_filename")
    _require(not path.is_symlink(), "symlink_entry")
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as stream:
        _require(stat.S_ISREG(os.fstat(stream.fileno()).st_mode), "invalid_entry_file")
        raw = stream.read(_MAX_BYTES + 1)
    _require(len(raw) <= _MAX_BYTES, "entry_too_large")

    def pairs(items):
        result = {}
        for key, value in items:
            _require(key not in result, "duplicate_json_key")
            result[key] = value
        return result
    try:
        row = json.loads(raw, object_pairs_hook=pairs)
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise LibraryError("invalid_stored_json") from exc
    entry = _validate(row)
    _require(entry["kind"] == path.parent.name and path.stem == "fl1-" + _digest(entry),
             "entry_hash_mismatch")
    return entry


def record_entry(root, entry):
    """Validate and durably insert an immutable JSON row; return its content ID.

    Identical writes are idempotent; a changed field creates a new ID. Atomic
    no-replace linking prevents partial rows or concurrent overwrite. Existing
    corruption fails closed. No success is returned before file/directory fsync.
    """
    entry = _validate(entry)
    _verify_outcome(entry)
    identity = "fl1-" + _digest(entry)
    directory = _directory(root, entry["kind"])
    root = Path(root)
    _require(root.parent.is_dir(), "library_parent_missing")
    root.mkdir(exist_ok=True)
    directory.mkdir(exist_ok=True)
    # Repeat both syncs on retries, including after a previous fsync failure.
    _sync_directory(root.parent)
    _sync_directory(root)
    target = directory / (identity + ".json")
    fd, temporary = tempfile.mkstemp(prefix=".pending-", dir=directory)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(_encoded(entry))
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temporary, target)
        except FileExistsError:
            _require(_read(target) == entry, "immutable_entry_conflict")
        _sync_directory(directory)
    finally:
        os.unlink(temporary)
    return identity


def _sync_directory(directory):
    fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def publish_case_mechanisms(root, case):
    """Publish source-traceable templates from an admitted canonical case.

    Return {schemaVersion: forecast-library-publication/v1, caseId, caseHash,
    entries: [{mechanismId, entryId}], skips: [{mechanismId, reason}]}. Receipt
    persistence belongs to the coordinator. No base rates, actor performance,
    outcomes, numeric node forecasts or assessment weights are inferred. Case
    validation errors propagate before any write. Later persistence/integrity
    failures propagate; retry is safe because individual entries are immutable.

    Private nodes, absent fetched evidence and unknown evidence dates are
    explicit skips. Missing publication dates remain null
    with a gap. The original mechanism and parameter bases remain unchanged;
    input evidence is explicitly contextual and never validates the mechanism.
    """
    from .official_data import bridge_module
    contract = bridge_module("forecast_case")
    case = contract.validate_case(case)
    case_hash = contract.case_hash(case)
    _not_future(case["asOf"])
    receipt = {"schemaVersion": "forecast-library-publication/v1", "caseId": case["caseId"],
               "caseHash": case_hash, "entries": [], "skips": []}
    nodes = {n["nodeId"]: n for n in case["nodes"]}
    sources = {s["sourceId"]: s for s in case["sources"]}
    for mechanism in case["mechanisms"]:
        mid = mechanism["mechanismId"]

        def skip(reason):
            receipt["skips"].append({"mechanismId": mid, "reason": reason})

        related = [nodes[nid] for nid in mechanism["inputNodeIds"]]
        output = nodes[mechanism["outputNodeId"]]
        if any(n["visibility"] != "public" for n in [*related, output]):
            skip("private_node")
            continue
        source_ids = set(mechanism["sourceIds"])
        for node in related:
            source_ids.update(node["sourceIds"])
        if not source_ids or not any(sources[sid]["fetched"] for sid in source_ids):
            skip("no_fetched_source_evidence")
            continue
        # Eligibility comes from mechanism/input evidence above. Also preserve
        # all declared parameter/output provenance; it cannot create eligibility.
        def parameter_sources(value):
            if type(value) is dict:
                source_ids.update(value.get("sourceIds", []))
                for child in value.values():
                    parameter_sources(child)
            elif type(value) is list:
                for child in value:
                    parameter_sources(child)

        parameter_sources(mechanism["parameters"])
        source_ids.update(output["sourceIds"])
        retained = [sources[sid] for sid in sorted(source_ids)]
        dates = [n["vintage"] for n in related if n["vintage"] is not None]
        dates += [s["publishedAt"] for s in retained if s["publishedAt"] is not None]
        if not dates:
            skip("unknown_evidence_date")
            continue
        gaps = [mechanism["gap"]] if mechanism.get("gap") else []
        gaps.extend(n["gap"] for n in related if n.get("gap"))
        if not mechanism["sourceIds"]:
            gaps.append("Sources describe input nodes; they do not validate the mechanism or its parameters.")
        for source in retained:
            if source["publishedAt"] is None:
                gaps.append("Publication date unknown for " + source["sourceId"] + "; retrieval is not publication.")
            if not source["fetched"]:
                gaps.append("Source " + source["sourceId"] + " was not fetched; retained only as provenance.")

        def descriptor(node):
            return {k: node[k] for k in ("nodeId", "label", "units", "vintage")} | {
                "sourceIds": [sid for sid in node["sourceIds"] if sid in source_ids]}

        # Output vintage is retained too, although output values/ranges are not.
        if output["vintage"] is not None:
            dates.append(output["vintage"])
        evidence_date = max(dates, key=_instant)
        available = max([evidence_date, *[s["retrievedAt"] for s in retained]], key=_instant)
        terms = set()
        for node in [*related, output]:
            for text in (node["nodeId"], node["label"]):
                terms.add(text.casefold())
                terms.update(re.findall(r"[^\W_]+", text.casefold()))
        entry = {"kind": "mechanism", "title": mid + ": " + output["label"],
                 "nodeTerms": sorted(terms), "asOf": case["asOf"], "evidenceDate": evidence_date,
                 "availableAt": available, "sources": retained,
                 "provenance": {"caseId": case["caseId"], "caseHash": case_hash,
                                "recordId": mid, "basis": mechanism["basis"]},
                 "uncertainty": "Template and parameter bases are inherited from the case; no hindcast or outcome validation is asserted.",
                 "gaps": list(dict.fromkeys(gaps)),
                 "content": {"template": mechanism["kind"], "parameters": mechanism["parameters"],
                             "inputNodes": [descriptor(n) for n in related], "outputNode": descriptor(output)}}
        try:
            _validate(entry)
        except LibraryError as exc:
            skip(str(exc))
            continue
        identity = record_entry(root, entry)
        receipt["entries"].append({"mechanismId": mid, "entryId": identity})
    return receipt


def select_entries(root, *, as_of, node_terms, kinds=None, limit=12):
    """Select relevant entries available at as_of; no I/O writes or external calls.

    All requested-kind files are schema/hash checked before filtering. Outcome
    proofs are rechecked only for cutoff-eligible relevant rows. Corruption is
    an error, never silently treated as an empty library. limit is an integer
    from 0 through 100. Empty node_terms or limit=0 yields no matches.
    """
    cutoff = _instant(as_of)
    terms = {term.casefold() for term in _texts(node_terms, empty=True)}
    _require(type(limit) is int and 0 <= limit <= 100, "invalid_limit")
    selected_kinds = list(KINDS) if kinds is None else _texts(kinds, empty=True)
    _require(all(kind in KINDS for kind in selected_kinds), "invalid_kind")
    if not terms or not limit:
        return []
    ranked = []
    for kind in selected_kinds:
        directory = _directory(root, kind)
        for path in sorted(directory.glob("*.json")):
            entry = _read(path)
            overlap = terms & {term.casefold() for term in entry["nodeTerms"]}
            if not overlap or _instant(entry["availableAt"]) > cutoff or _instant(entry["asOf"]) > cutoff:
                continue
            _verify_outcome(entry)
            ranked.append((len(overlap), _instant(entry["availableAt"]), path.stem, entry))
    ranked.sort(key=lambda item: (-item[0], -item[1].timestamp(), item[2]))
    return [dict(entry, entryId=identity) for _, _, identity, entry in ranked[:limit]]
