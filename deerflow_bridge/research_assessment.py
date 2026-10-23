"""Bounded, source-linked assessment records. No I/O or model calls.

Exact quotation proves what a source asserted, not independent truth. Numeric
occurrence is only a diagnostic; typed support requires a complete source tuple.
"""
from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from datetime import date
from decimal import Decimal, InvalidOperation

VERSION = "post-gather-assessment/v1"
SUPPORT_VERSION = "numeric-claim-support/v1"
MAX_EVIDENCE = 48
FIELDS = ("entity", "metric", "value", "unit", "period_end", "value_type")


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def normalized(text):
    return " ".join(str(text or "").split())


def has_quantity(text):
    """Detect quantities including single digits, excluding dates/citation IDs.

    This is a conservative admission classifier, not a semantic verifier.
    """
    text = unicodedata.normalize("NFKC", str(text or ""))
    text = re.sub(r"\[S\d+\]|\b(?:19|20)\d{2}-\d{2}(?:-\d{2})?\b|\bFY\s*\d{4}\b", " ", text)
    text = re.sub(r"(?:19|20)\d{2}年(?:\d{1,2}月(?:\d{1,2}日)?)?", " ", text)
    text = re.sub(r"\b(?:January|February|March|April|May|June|July|August|September|October|November|December)"
                  r"\s+(?:\d{1,2},?\s+)?(?:19|20)\d{2}\b", " ", text, flags=re.I)
    text = re.sub(r"\b(?:in|by|through|during|since|until)\s+(?:19|20)\d{2}\b(?=\s*(?:[.,;:!?)]|$))", " ", text, flags=re.I)
    text = re.sub(r"\b(?:order|permit|article|section|license)\s+(?:no\.?\s*)?[A-Za-z]*\d+(?:[-/]\d+)*\b", " ", text, flags=re.I)
    return bool(re.search(r"(?<![A-Za-z_0-9])\d", text))


def typed_numeric_support(row, source, page):
    """Admit an exact typed source object, never scattered matching numbers.

    Prose without a typed source tuple remains explicitly unassessed. The
    official-data producer has its own deterministic series/observation proof.
    """
    support = {"schema_version": SUPPORT_VERSION, "status": "unassessed",
               "citation_resolved": bool(source), "numeric_occurrence": False,
               "semantic_support": False, "reason": "missing_typed_source"}
    if not source or not source.get("reachable") or not page:
        support["reason"] = "source_not_fetched"
        return support
    support.update(source_id=source.get("source_id"), source_url=source.get("url"),
                   content_sha256=hashlib.sha256(page.encode()).hexdigest())
    raw = row.get("value")
    try:
        if isinstance(raw, bool):
            raise ValueError()
        value = Decimal(str(raw))
        if not value.is_finite():
            raise ValueError()
    except (InvalidOperation, ValueError, TypeError):
        support["reason"] = "non_numeric_value"
        return support
    support["numeric_occurrence"] = str(raw) in page
    if any(row.get(k) in (None, "") for k in FIELDS):
        return support
    try:
        if (row["value_type"] not in {"actual", "estimate", "forecast", "target"}
                or date.fromisoformat(row["period_end"]).isoformat() != row["period_end"]
                or not all(isinstance(row[k], str) and row[k].strip() for k in ("entity", "metric", "unit"))):
            raise ValueError()
    except (TypeError, ValueError):
        support["reason"] = "invalid_typed_semantics"
        return support
    quote = row.get("supporting_quote")
    if not isinstance(quote, str) or not 12 <= len(quote) <= 4000 or quote not in page:
        support["reason"] = "quote_not_in_source"
        return support
    try:
        datum = json.loads(quote)
    except (TypeError, ValueError):
        support["reason"] = "prose_requires_semantic_review"
        return support
    if not isinstance(datum, dict):
        return support
    try:
        same_value = not isinstance(datum.get("value"), bool) and Decimal(str(datum.get("value"))) == value
    except InvalidOperation:
        same_value = False
    mismatch = [k for k in FIELDS if k != "value" and datum.get(k) != row.get(k)]
    if mismatch or not same_value:
        support.update(status="contradicted", reason="typed_tuple_mismatch",
                       mismatched_fields=mismatch + ([] if same_value else ["value"]))
        return support
    support.update(status="supported_source_assertion", semantic_support=True,
                   reason="exact_typed_source_tuple", quote=quote, quote_sha256=digest(quote),
                   assertion={key: row[key] for key in FIELDS},
                   independent=None)
    return support


def evidence_rows(records, ledger_get, page_text):
    """Only exact fetched assertions enter revision evidence; duplicates collapse.

    Page/quote identity is retained. Different URLs are never asserted to be
    independent origins. Numeric prose is not promoted to a typed observation.
    """
    rows, seen = [], set()
    for kid in sorted(records):
        for fact in records[kid].get("facts", []):
            text = re.sub(r"\[S\d+\]", "", str(fact.get("text") or ""))
            quote = normalized(text).strip(" -")
            if not 20 <= len(quote) <= 2000 or fact.get("tag") == "UNVERIFIED":
                continue
            key = digest(quote)
            if key in seen:
                continue
            for sid in fact.get("sids", []):
                source = ledger_get(sid) or {}
                page = page_text(sid) if source.get("fetched") else None
                if not page or quote not in normalized(page):
                    continue
                semantics = "unassessed" if has_quantity(quote) else "not_numeric"
                support = fact.get("claim_support") or {}
                if support.get("semantic_support"):
                    checked = typed_numeric_support(
                        {**support.get("assertion", {}), "supporting_quote": support.get("quote")},
                        {**source, "reachable": True, "source_id": f"S{sid}"}, page)
                    if checked.get("semantic_support"):
                        semantics = "typed_source_tuple"
                rows.append({"evidence_id": "e_" + key[:20], "quote": quote, "sid": sid,
                             "source_url": source.get("url"),
                             "content_sha256": hashlib.sha256(page.encode()).hexdigest(),
                             "origin_id": source.get("origin_id") or source.get("canonical_url") or source.get("url"),
                             "independent": None, "support": "exact_source_assertion",
                             "numeric_semantics": semantics})
                seen.add(key)
                break
            if len(rows) >= MAX_EVIDENCE:
                return rows
    return rows


def official_observations(datasets, links, api, as_of):
    """Project hash-validated stored observations, without prose re-extraction.

    Callers must obtain datasets from strict load_datasets. Only complete
    observed points captured by the cutoff qualify; publisher projections,
    estimates, preliminary/partial/unknown points are not silently relabelled.
    """
    cutoff = api.resolution_instant(as_of)
    out = []
    for row in datasets:
        if row["series"] not in links:
            continue
        series = api.Series.from_dict(row)
        if not series.units or api.resolution_instant(series.retrieved_at) > cutoff:
            continue
        earliest_retrieval = api.resolution_instant(series.retrieved_at, date_end=False)
        observed = None
        for point in reversed(series.observations):
            if point.value is None or api.observation_kind(point, series) != "observed":
                continue
            period = series.provenance.get("periods", {}).get(point.date, {})
            end = (api.resolution_instant(period["end"]) if period.get("end") else
                   api._period_complete_at(point.date, series.frequency))
            if end <= cutoff and end <= earliest_retrieval:
                observed = point
                break
        if observed is None:
            continue
        observation = {"series": series.series, "entity": series.geography or None,
                       "metric": series.title, "value": observed.value, "unit": series.units,
                       "period": observed.date, "period_metadata": series.provenance.get("periods", {}).get(observed.date),
                       "frequency": series.frequency, "seasonal_adjustment": series.seasonal_adjustment,
                       "status": api.observation_kind(observed, series), "raw_flag": observed.flag,
                       "status_basis": series.provenance.get("status_basis"),
                       "native_unit": series.provenance.get("native_unit"),
                       "resolution_safe": series.provenance.get("resolution_safe"),
                       "retrieved_at": series.retrieved_at, "last_updated": series.last_updated,
                       "vintage": series.vintage, "transform": series.transform,
                       "information_cutoff": cutoff.isoformat()}
        binding = {"dataset_file": row["file"], "dataset_sha256": row["sha256"],
                   "source_url": series.source_url, "observation": observation}
        out.append({"evidence_id": "official_" + digest(binding)[:20], **binding,
                    "sid": links[series.series], "origin_id": series.series,
                    "independent": None, "support": "typed_official_observation",
                    "numeric_semantics": "typed_official_observation"})
        if len(out) >= MAX_EVIDENCE:
            break
    return out


def initial_frame(plan):
    definition = {"question": plan.question, "as_of": plan.as_of, "horizon": plan.horizon,
                  "scenarios": [{"name": s.name, "definition": s.thesis} for s in plan.scenarios]}
    identity = digest(definition)
    return {"version": 1, "definition_sha256": identity, **{k: definition[k] for k in ("question", "as_of", "horizon")},
            "scenarios": [{"scenario_id": "sc_" + digest([identity, i])[:20],
                           "name": s.name, "definition": s.thesis, "weight": s.weight,
                           "reason": s.thesis or "Initial planning assessment; no documented prior rationale."}
                          for i, s in enumerate(plan.scenarios)]}


def finish(initial, evidence, candidate=None, *, stopping_reason="insufficient_evidence"):
    final = json.loads(json.dumps(initial))
    final["version"] = 2
    changes = []
    if candidate is not None:
        if not isinstance(candidate, dict) or set(candidate) != {"scenarios"}:
            raise ValueError("assessment candidate must contain only scenarios")
        proposed = candidate["scenarios"]
        if not isinstance(proposed, list) or len(proposed) != len(initial["scenarios"]):
            raise ValueError("assessment scenario roster changed")
        eligible = {r["evidence_id"] for r in evidence if r["numeric_semantics"] != "unassessed"}
        total = 0
        for old, new, out in zip(initial["scenarios"], proposed, final["scenarios"]):
            if not isinstance(new, dict) or set(new) != {"scenario_id", "weight", "reason", "evidence_ids"}:
                raise ValueError("assessment scenario fields changed")
            if new["scenario_id"] != old["scenario_id"]:
                raise ValueError("assessment scenario identity changed")
            weight, reason, refs = new["weight"], new["reason"], new["evidence_ids"]
            if type(weight) is not int or not 1 <= weight <= 99:
                raise ValueError("assessment weight must be an integer in 1..99")
            if not isinstance(reason, str) or not 12 <= len(reason.strip()) <= 2000:
                raise ValueError("assessment requires a bounded final reason")
            if not isinstance(refs, list) or len(refs) > 12 or any(not isinstance(r, str) or r not in eligible for r in refs):
                raise ValueError("assessment evidence does not resolve to an admitted assertion")
            if weight != old["weight"] and not refs:
                raise ValueError("probability revision requires source-linked evidence")
            total += weight
            out.update(weight=weight, reason=reason, evidence_ids=list(dict.fromkeys(refs)))
            changes.append({"scenario_id": old["scenario_id"], "prior_weight": old["weight"],
                            "final_weight": weight, "prior_reason": old["reason"],
                            "final_reason": reason, "evidence_ids": out["evidence_ids"]})
        if total != 100:
            raise ValueError("assessment probabilities do not sum to 100")
        stopping_reason = "assessed"
    else:
        for row in final["scenarios"]:
            row.update(reason=f"Prior retained: {stopping_reason}.", evidence_ids=[])
        changes = [{"scenario_id": old["scenario_id"], "prior_weight": old["weight"],
                    "final_weight": old["weight"], "prior_reason": old["reason"],
                    "final_reason": new["reason"], "evidence_ids": []}
                   for old, new in zip(initial["scenarios"], final["scenarios"])]
    body = {"schema_version": VERSION, "initial": initial, "final": final, "changes": changes,
            "evidence": evidence, "inputs_sha256": digest([initial, evidence]),
            "stopping_reason": stopping_reason}
    return {**body, "sha256": digest(body)}


def validate_saved(record, initial, evidence):
    if not isinstance(record, dict) or record.get("schema_version") != VERSION:
        raise ValueError("assessment record missing or unsupported")
    if record.get("sha256") != digest({k: v for k, v in record.items() if k != "sha256"}):
        raise ValueError("assessment record changed")
    if record.get("inputs_sha256") != digest([initial, evidence]):
        raise ValueError("assessment inputs changed")
    candidate = None
    if record.get("stopping_reason") == "assessed":
        candidate = {"scenarios": [{k: r[k] for k in ("scenario_id", "weight", "reason", "evidence_ids")}
                                    for r in record["final"]["scenarios"]]}
    if finish(initial, evidence, candidate, stopping_reason=record["stopping_reason"]) != record:
        raise ValueError("assessment derivation changed")
    return record
