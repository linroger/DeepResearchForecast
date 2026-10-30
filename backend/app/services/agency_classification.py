"""Pure, source-declared agency classification for a PREPARE-owned cast.

This adapter does not infer facts from descriptions, roles or familiar names. Its
optional output is sealed by the caller and shared by config and world seeding.
"""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from typing import Any, Dict, Optional

from .agent_decision import AGENCY_CLASSES


_GENERIC_TYPES = frozenset({"", "entity", "actor", "actors", "agent", "unknown",
                            "organization", "organisation", "person", "other"})


def _get(value: Any, key: str, default: Any = None) -> Any:
    return value.get(key, default) if isinstance(value, dict) else getattr(value, key, default)


def _name(value: Any) -> str:
    # Case and whitespace only: punctuation, substrings and fuzzy similarity do
    # not establish identity. No role/description/summary text is consulted.
    return " ".join(value.split()).casefold() if isinstance(value, str) else ""


def _strings(value: Any) -> list[str]:
    return [v for v in value if isinstance(v, str) and _name(v)] if isinstance(value, list) else []


def _names(value: Any) -> set[str]:
    names = {_name(_get(value, "name")), *map(_name, _strings(_get(value, "aliases")))}
    attrs = _get(value, "attributes")
    if isinstance(attrs, dict):
        names.update(map(_name, _strings(attrs.get("aliases"))))
    return names - {""}


def _canonical(value: Any) -> bool:
    return isinstance(value, str) and value in AGENCY_CLASSES


def build_agency_classifications(entities: Any, actors: Any, ontology: Any) -> Dict[str, Dict[str, Any]]:
    """Return UUID-bound declarations, including explicit unresolved results.

    Priority: canonical dossier class; specific declared ontology type; specific
    exact named example; generic declared type/example. Invalid or conflicting
    metadata at a selected ontology tier cannot fall through to a broader class.
    The ontology hash covers canonical JSON of the complete supplied document.
    """
    ontology_sha256 = None
    type_rows = []
    if isinstance(ontology, dict):
        try:
            encoded = json.dumps(ontology, sort_keys=True, ensure_ascii=False,
                                 separators=(",", ":"), allow_nan=False).encode("utf-8")
            ontology_sha256 = hashlib.sha256(encoded).hexdigest()
            if isinstance(ontology.get("entity_types"), list):
                type_rows = [r for r in ontology["entity_types"]
                             if isinstance(r, dict) and _name(r.get("name"))]
        except (TypeError, ValueError, UnicodeError, RecursionError):
            pass
    actor_rows = actors.get("actors") if isinstance(actors, dict) else actors
    actor_rows = [a for a in actor_rows if isinstance(a, dict)] if isinstance(actor_rows, list) else []
    entity_rows = list(entities) if isinstance(entities, (list, tuple)) else []
    identities = []
    dossier_owners: Dict[int, set[str]] = {}
    prepared = []
    name_owners: Dict[str, set[str]] = {}
    for entity in entity_rows:
        uuid = _get(entity, "uuid")
        if not isinstance(uuid, str) or not uuid.strip():
            continue
        matches = [i for i, a in enumerate(actor_rows) if _names(entity) & _names(a)]
        identities.append((uuid, entity, matches))
        for index in matches:
            dossier_owners.setdefault(index, set()).add(uuid)
    # Require an unambiguous binding in both directions before importing any
    # dossier class, type or aliases into an entity's classification evidence.
    for uuid, entity, matches in identities:
        ambiguous = len(matches) > 1 or any(len(dossier_owners[i]) > 1 for i in matches)
        actor = actor_rows[matches[0]] if matches and not ambiguous else None
        names = _names(entity)
        if actor:
            names |= _names(actor)
        types = _strings(_get(entity, "labels"))
        types += [v for v in (_get(entity, "entity_type"), _get(entity, "type"),
                              (actor or {}).get("type")) if isinstance(v, str) and _name(v)]
        prepared.append((uuid, names, types, ambiguous, actor))
        for name in names:
            name_owners.setdefault(name, set()).add(uuid)

    out: Dict[str, Dict[str, Any]] = {}
    for uuid, names, types, ambiguous, actor in prepared:
        basis: Dict[str, Any] = {
            "entity_uuid": uuid, "source": "unresolved", "type_names": [],
            "ontology_sha256": ontology_sha256, "match_method": "none",
            "status": "unresolved", "reason": "no_declared_class", "declarations": [],
        }
        result = {"agency_class": None, "basis": basis}
        if uuid in out:
            out[uuid] = {"agency_class": None, "basis": {
                **basis, "reason": "duplicate_entity_uuid"}}
            continue
        out[uuid] = result
        if ambiguous:
            basis.update(reason="ambiguous_dossier_identity", match_method="exact_name_or_alias")
            continue
        if actor and _canonical(actor.get("agency_class")):
            klass = actor["agency_class"]
            basis.update(source="dossier", status="resolved", reason="declared_class",
                         match_method="exact_name_or_alias",
                         type_names=sorted(set([actor["type"]] if isinstance(actor.get("type"), str) else [])),
                         declarations=[{"agency_class": klass, "actor_name": actor.get("name")}])
            result["agency_class"] = klass
            continue

        normalized_types = {_name(t) for t in types}
        type_matches = [r for r in type_rows if _name(r["name"]) in normalized_types]
        example_matches = [r for r in type_rows if names & set(map(_name, _strings(r.get("examples"))))]
        tiers = (
            ("exact_type", [r for r in type_matches if _name(r["name"]) not in _GENERIC_TYPES]),
            ("exact_example_name_or_alias", [r for r in example_matches if _name(r["name"]) not in _GENERIC_TYPES]),
            ("exact_type", type_matches),
            ("exact_example_name_or_alias", example_matches),
        )
        for method, selected in tiers:
            if not selected:
                continue
            basis.update(source="ontology", match_method=method,
                         type_names=sorted({r["name"] for r in selected}))
            if method == "exact_example_name_or_alias":
                matched_names = names & {n for r in selected for n in map(_name, _strings(r.get("examples")))}
                if any(len(name_owners[n]) != 1 for n in matched_names):
                    basis["reason"] = "ambiguous_example_identity"
                    break
            if any(not _canonical(r.get("agency_class")) for r in selected):
                basis["reason"] = "invalid_declared_class"
                break
            declarations = [{"type_name": r["name"], "agency_class": r["agency_class"]}
                            for r in selected]
            # Stable ordering and deduplication, independent of ontology row order.
            basis["declarations"] = sorted(
                {json.dumps(d, sort_keys=True): d for d in declarations}.values(),
                key=lambda d: (d["type_name"], d["agency_class"]))
            classes = {r["agency_class"] for r in selected}
            if len(classes) != 1:
                basis["reason"] = "conflicting_declared_classes"
                break
            result["agency_class"] = next(iter(classes))
            basis.update(status="resolved", reason="declared_class")
            break
    return out


def agency_classification_for(agency_classifications: Any, entity_uuid: Any) -> Optional[Dict[str, Any]]:
    """Validate an optional sealed-map entry without mutating the caller's map.

    This is structural/identity validation, not signature authentication; the
    parent owns the source-bound manifest seal. Invalid entries grant no class.
    """
    if not isinstance(agency_classifications, dict) or not isinstance(entity_uuid, str):
        return None
    entry = agency_classifications.get(entity_uuid)
    if not isinstance(entry, dict) or "agency_class" not in entry or not isinstance(entry.get("basis"), dict):
        return None
    try:
        json.dumps(entry, allow_nan=False)
    except (TypeError, ValueError, RecursionError):
        return None
    basis = entry["basis"]
    if basis.get("entity_uuid") != entity_uuid or basis.get("status") not in ("resolved", "unresolved"):
        return None
    if not isinstance(basis.get("type_names"), list) or any(not isinstance(t, str) for t in basis["type_names"]):
        return None
    if basis.get("source") not in ("dossier", "ontology", "unresolved"):
        return None
    if basis.get("match_method") not in ("none", "exact_name_or_alias", "exact_type", "exact_example_name_or_alias"):
        return None
    if basis["status"] == "unresolved":
        return deepcopy(entry) if entry.get("agency_class") is None else None
    klass = entry.get("agency_class")
    declarations = basis.get("declarations")
    if not _canonical(klass) or not isinstance(declarations, list) or not declarations:
        return None
    if any(not isinstance(d, dict) or d.get("agency_class") != klass for d in declarations):
        return None
    if basis["source"] == "ontology":
        digest = basis.get("ontology_sha256")
        if (not isinstance(digest, str) or len(digest) != 64
                or any(c not in "0123456789abcdef" for c in digest)
                or not basis["type_names"]
                or any(d.get("type_name") not in basis["type_names"] for d in declarations)
                or basis["match_method"] not in {"exact_type", "exact_example_name_or_alias"}):
            return None
    elif basis["source"] != "dossier" or basis["match_method"] != "exact_name_or_alias":
        return None
    return deepcopy(entry)
