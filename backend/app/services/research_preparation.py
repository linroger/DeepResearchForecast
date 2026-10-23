"""Deterministic research-to-PREPARE compiler; no filesystem discovery or models.

Integration API (all inputs are the caller's already admitted generation):
``compile_preparation_context(*, question, research_report, actors,
official_data=None, sources=None, actor_context_packs=None, source_binding=None,
as_of=None, report_artifacts=None) -> dict``. ``report_artifacts`` maps admitted
sidecar filenames (not paths to read) to decoded JSON, notably quantitative.json.
``as_of`` is an ISO cutoff or {as_of/cutoff, ...window metadata}; the complete
effective value is pinned in scope. No later meta.json lookup is performed.

Bundle research-preparation/v1:
* source: canonical JSON input hashes (report_sha256 hashes exact UTF-8 text),
  and the caller's source_binding; expected_sources is a subset of this mapping.
* scope: question, as_of (effective ISO cutoff), research_window, history_limit.
* quantitative: observations/guidance lists, PUBLIC ONLY. Rows carry id, entity,
  metric, series/provider, source_refs, value/unit (native, never rescaled),
  status, period, as_of, provenance, history, diagnostic_summary. Guidance never
  initializes state. Unknown/partial data remain guidance with their status.
* qualitative: public/modeler lists and actors keyed by canonical actor_id.
  Rows preserve conditions, status, evidence/source identities. Actor/modeler
  rows may contain permitted private quantities; never copy these into a seed.
* gaps: typed omissions with audience labels; no fabricated coefficients/bounds.
* content_sha256: actor_context.canonical_json_sha256 of every other field.

``validate_preparation_context(bundle, *, expected_sources=None)`` raises
ValueError on invalid proof/schema. ``render_preparation_context(bundle, *,
audience='public', actor_id=None, max_chars=12000)`` emits complete JSON rows and
an omission count, never slices values/units/conditions. ``write_preparation_context
(sim_dir, bundle)`` writes research_preparation.json then its completion manifest
research_preparation_manifest.json and returns the manifest. ``load_preparation_context
(sim_dir, expected_sha256=None, expected_sources=None)`` requires both artifacts;
expected_sha256 is the canonical content digest. Reuse MUST pass the original
digest and/or expected_sources, never recompile an old run against new inputs.

World seed integration: build_world_model_seed(..., preparation_context=bundle)
puts each public observed row in StateVariable.research_evidence, preserving full
identity/history; public guidance stays in quantitative_guidance. Invalid or
mismatched preparation raises rather than falling back to a mutable dossier.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
import re
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Mapping

from . import actor_context as ac
from .official_data import _contained_bytes, _snapshot_cutoff, data_api, resolution_instant
from ..utils.atomic import write_text_atomic

SCHEMA_VERSION = "research-preparation/v1"
PREPARATION_CONTEXT_VERSION = SCHEMA_VERSION
BUNDLE_FILE = "research_preparation.json"
MANIFEST_FILE = "research_preparation_manifest.json"
HISTORY_LIMIT = 60

__all__ = ["compile_preparation_context", "validate_preparation_context",
           "render_preparation_context", "write_preparation_context",
           "load_preparation_context"]

_OBSERVED = {"observed", "preliminary"}
_GUIDANCE = {"estimate", "target", "projection", "unknown", "partial"}
_PUBLIC = ac.PUBLIC_RELATIONSHIP_VISIBILITIES


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _token(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(value or "").casefold()).strip("_")


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _refs(row: Mapping) -> list[str]:
    refs = row.get("source_refs", row.get("source_ref", row.get("source_id", [])))
    if isinstance(refs, str):
        refs = [refs]
    return sorted(set(str(r).strip() for r in refs if str(r).strip())) if isinstance(refs, list) else []


def _public(row: Mapping, *, legacy=False) -> bool:
    qualifiers = row.get("qualifiers") if isinstance(row.get("qualifiers"), dict) else {}
    if row.get("actor_knows") is False or qualifiers.get("actor_knows") is False:
        return False
    vis = [_token(x.get("visibility")) for x in (row, qualifiers) if x.get("visibility")]
    if any(v not in _PUBLIC for v in vis):
        return False
    if any(_token(item.get("evidence_type")) in {"analyst_inference", "model_assumption", "hypothesis"}
           for item in (row, qualifiers)):
        return False
    return bool(vis) or legacy


def _native_quantity(value: Any, unit: Any) -> tuple[int | float, str]:
    """Read a complete native quantity. Never multiply or extract a numeric prefix."""
    unit = _text(unit)
    if type(value) in (int, float):
        number = value
    elif isinstance(value, str):
        match = re.fullmatch(
            r"\s*(US\$|USD|EUR|GBP|CNY|\$|€|£|¥)?\s*"
            r"([+-]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?(?:[eE][+-]?\d+)?)"
            r"\s*([^\d]*)\s*", value)
        if not match:
            raise ValueError("not a complete native quantity")
        raw = match[2].replace(",", "")
        number = int(raw) if re.fullmatch(r"[+-]?\d+", raw) else float(raw)
        inline = " ".join(x.strip() for x in (match[3], match[1] or "") if x.strip())

        def comparable(text):
            text = text.casefold().replace("us$", "usd").replace("$", "usd")
            for symbol, code in (("€", "eur"), ("£", "gbp"), ("¥", "yen")):
                text = text.replace(symbol, code)
            text = re.sub(r"\b(dollars?|us dollars?)\b", "usd", text)
            text = re.sub(r"\b(billions|millions|thousands)\b", lambda m: m[0][:-1], text)
            # Unicode unit symbols and Chinese scale words must survive. An
            # unknown unit is matched literally, never reduced to empty tokens.
            tokens = text.replace(" of ", " ").split()
            if (len(tokens) == 2 and set(tokens) & {"usd", "eur", "gbp", "cny", "yen"}
                    and set(tokens) & {"thousand", "million", "billion", "trillion"}):
                return sorted(tokens)  # the only supported harmless reordering
            return tokens

        if inline and unit and comparable(inline) != comparable(unit):
            raise ValueError("inline and explicit units disagree")
        unit = unit or inline
    else:
        raise ValueError("quantity must be a number, not a boolean")
    try:
        finite = math.isfinite(number)
    except OverflowError:
        finite = False
    if not finite or not unit:
        raise ValueError("quantity requires a finite value and native unit")
    return number, unit


def _status(row: Mapping) -> str:
    # Any guidance marker wins over a contradictory 'actual' marker.
    if "claim_support" in row:
        support = row["claim_support"]
        if (not isinstance(support, dict) or support.get("schema_version") != "numeric-claim-support/v1"
                or support.get("semantic_support") is not True
                or support.get("status") != "supported_source_assertion"):
            return "unknown"
    qualifiers = row.get("qualifiers") if isinstance(row.get("qualifiers"), dict) else {}
    tokens = {_token(obj.get(key)) for obj in (row, qualifiers) for key in ("status", "value_type", "value_kind")}
    for status, aliases in (("projection", {"projection", "forecast", "projected"}),
                            ("target", {"target", "goal", "planned", "guidance"}),
                            ("estimate", {"estimate", "estimated"}),
                            ("partial", {"partial", "incomplete"}),
                            ("unknown", {"unknown", "contested", "cancelled", "canceled", "superseded", "retracted", "denied"}),
                            ("preliminary", {"preliminary", "p"}),
                            ("observed", {"observed", "actual", "realized", "reported"})):
        if tokens & aliases:
            return status
    return "unknown"


def _check_availability(row: Mapping, cutoff: str) -> None:
    qualifiers = row.get("qualifiers") if isinstance(row.get("qualifiers"), dict) else {}
    for obj in (row, qualifiers):
        for key in ("as_of_date", "as_of", "release_date", "released_at", "available_at"):
            if obj.get(key) not in (None, ""):
                if not cutoff or resolution_instant(obj[key]) > resolution_instant(cutoff):
                    raise ValueError("evidence availability after cutoff")


def _period_end(period: str, frequency: str) -> str:
    start = date.fromisoformat(period)
    months = {"M": 1, "Q": 3, "A": 12}.get(frequency)
    if months:
        year, month = divmod(start.year * 12 + start.month - 1 + months, 12)
        return (date(year, month + 1, 1) - timedelta(days=1)).isoformat()
    return (start + timedelta(days=6 if frequency == "W" else 0)).isoformat()


def _identity(row: Mapping) -> str:
    # A metric label alone is never an identity: entity/series/source, unit and
    # transform/definition jointly identify the measurement, period is separate.
    keys = ("source_kind", "entity", "metric", "series", "provider", "source", "source_refs",
            "unit", "definition", "transform", "frequency", "seasonal_adjustment")
    # The dynamic world slug has a 64-character limit; keep an opaque 160-bit
    # identity while retaining full SHA-256 for all input and artifact seals.
    return "q_" + ac.canonical_json_sha256({key: row.get(key, "") for key in keys})[:40]


def _summarize(rows: list[dict]) -> dict:
    values = [r["value"] for r in rows]
    result = {"diagnostic_only": True, "count": len(rows), "min": min(values), "max": max(values),
              "first_period": rows[0]["period"], "last_period": rows[-1]["period"]}
    if len(rows) > 1:
        delta = values[-1] - values[0]
        if math.isfinite(delta):
            result["change_native_units"] = delta
    return result


def _group(rows: list[dict], gaps: list[dict]) -> list[dict]:
    grouped: dict[tuple, list] = {}
    for row in rows:
        grouped.setdefault((row["id"], "observations" if row["status"] in _OBSERVED else row["status"]), []).append(row)
    result = []
    for key in sorted(grouped):
        points: dict[str, dict] = {}
        conflicts = set()
        for row in grouped[key]:
            old = points.get(row["period"])
            if old and (old["value"], old["unit"], old["status"]) != (row["value"], row["unit"], row["status"]):
                conflicts.add(row["period"])
            points[row["period"]] = row
        for period in sorted(conflicts):
            gaps.append({"kind": "conflicting_values", "id": key[0], "period": period, "audience": "public"})
            del points[period]
        ordered = sorted(points.values(), key=lambda r: (r.get("period_end") or r["period"], r["period"]))
        if not ordered:
            continue
        bounded = ordered[-HISTORY_LIMIT:]
        latest = copy.deepcopy(bounded[-1])
        latest["history"] = [{k: r[k] for k in (
            "value", "period", "period_start", "period_end", "status", "as_of", "source_refs", "provenance")}
            for r in bounded]
        latest["diagnostic_summary"] = {**_summarize(bounded), "omitted_history": len(ordered) - len(bounded)}
        result.append(latest)
    return result


def _fact(row: Mapping, cutoff: str) -> dict:
    value, unit = _native_quantity(row.get("value"), row.get("unit", row.get("units")))
    metric = _text(row.get("metric"))
    refs = _refs(row)
    source = _text(row.get("source_url")) or _text(row.get("source"))
    if not metric or not (refs or source):
        raise ValueError("metric or source identity missing")
    period = _text(row.get("period")) or _text(row.get("period_end")) or _text(row.get("as_of_date"))
    availability = _text(row.get("as_of_date")) or _text(row.get("as_of"))
    end = _text(row.get("period_end"))
    if not end:
        frequency = _text(row.get("frequency"))
        if frequency in {"M", "Q", "A", "W"}:
            start = _text(row.get("period_start"))
            if not start:
                raise ValueError("aggregate period requires explicit start/end")
            end = _period_end(start, frequency)
        else:
            end = period
    status = _status(row)
    if not period or not availability or not cutoff:
        raise ValueError("period, availability or cutoff missing")
    if resolution_instant(availability) > resolution_instant(cutoff):
        raise ValueError("fact availability after cutoff")
    _check_availability(row, cutoff)
    # Guidance can describe a future period; observed state cannot.
    if status in _OBSERVED and resolution_instant(end) > resolution_instant(cutoff):
        raise ValueError("observed period after cutoff")
    result = {"source_kind": "research_fact", "entity": _text(row.get("entity")) or _text(row.get("geography")),
              "metric": metric, "series": _text(row.get("series")), "provider": _text(row.get("provider")),
              "source": source, "source_refs": refs, "value": value, "unit": unit, "period": period,
              "period_start": _text(row.get("period_start")), "period_end": end, "status": status,
              "as_of": availability, "cutoff": cutoff, "definition": _text(row.get("definition")),
              "transform": _text(row.get("transform")), "frequency": _text(row.get("frequency")),
              "seasonal_adjustment": _text(row.get("seasonal_adjustment")),
              "provenance": {key: copy.deepcopy(row[key]) for key in (
                  "source_origin", "dataset_file", "value_type", "value_kind", "status", "qualifiers", "conditions",
                  "dependencies", "evidence_type", "visibility", "actor_knows", "release_date", "released_at", "claim_support") if key in row}}
    result["id"] = _identity(result)
    return result


def _official_rows(official: Mapping, cutoff: str, gaps: list) -> list[dict]:
    output = []
    api = data_api()
    if api is None:
        raise ValueError("official status classifier unavailable")
    for raw in official.get("series", []):
        try:
            if not isinstance(raw, dict) or not _public(raw, legacy=True):
                continue
            # Reject bool before Series' numeric normalization can erase its type.
            if any(isinstance(o.get("value"), bool) for o in raw.get("observations", []) if isinstance(o, dict)):
                raise ValueError("boolean official observation")
            carrier = api.Series.from_dict(raw)
            if not cutoff or resolution_instant(carrier.retrieved_at) > resolution_instant(cutoff):
                raise ValueError("official retrieval missing or after cutoff")
            _check_availability(raw, cutoff)
            unit = _text(raw.get("units"))
            periods = carrier.provenance.get("periods", {})
            for obs in carrier.observations:
                if obs.value is None:
                    gaps.append({"kind": "missing_official_value", "series": carrier.series,
                                 "period": obs.date, "audience": "public"})
                    continue
                metadata = periods.get(obs.date, {}) if isinstance(periods, dict) else {}
                status = api.observation_kind(obs, carrier)
                end = metadata.get("end") or _period_end(obs.date, carrier.frequency)
                if status in _OBSERVED and resolution_instant(end) > resolution_instant(cutoff):
                    gaps.append({"kind": "period_after_cutoff", "series": carrier.series,
                                 "period": obs.date, "audience": "public"})
                    continue
                if carrier.provenance.get("resolution_safe") is False and status in _OBSERVED:
                    status = "unknown"
                # Use original native integer/float when available. Series normalizes
                # status and dates, never authorizes rescaling or dropping metadata.
                original = next((o for o in raw.get("observations", []) if o.get("date") == obs.date), {})
                value, unit = _native_quantity(original.get("value", obs.value), unit)
                provenance = {k: copy.deepcopy(v) for k, v in carrier.provenance.items() if k != "periods"}
                if metadata:
                    provenance["period"] = copy.deepcopy(metadata)
                provenance.update({k: copy.deepcopy(raw[k]) for k in (
                    "dataset_file", "sha256", "last_updated", "vintage", "release_date", "released_at") if k in raw})
                row = {"source_kind": "official_observation", "entity": carrier.geography,
                       "metric": _text(raw.get("title")) or carrier.series, "series": carrier.series,
                       "provider": carrier.provider, "source": carrier.source_url or carrier.provider_name or carrier.provider,
                       "source_refs": _refs(raw), "value": value, "unit": unit, "period": obs.date,
                       "period_start": metadata.get("start") or obs.date, "period_end": end,
                       "status": status, "as_of": carrier.retrieved_at, "cutoff": cutoff,
                       "definition": carrier.notes, "transform": carrier.transform, "frequency": carrier.frequency,
                       "seasonal_adjustment": carrier.seasonal_adjustment, "provenance": provenance}
                row["id"] = _identity(row)
                output.append(row)
        except (ValueError, TypeError, KeyError, OverflowError, AttributeError) as exc:
            gaps.append({"kind": "official_not_admitted", "series": _text(raw.get("series")) if isinstance(raw, dict) else "",
                         "reason": str(exc), "audience": "public"})
    return output


def compile_preparation_context(*, question, research_report, actors, official_data=None,
                                sources=None, actor_context_packs=None, source_binding=None,
                                as_of=None, report_artifacts=None) -> dict:
    """Compile supplied bound inputs only; strict hashes reject non-JSON/nonfinite inputs.

    report_artifacts is {filename: decoded JSON}. as_of accepts an ISO string or
    {as_of: ISO, research_window: {started_at, finished_at}}. A live research
    window uses the existing official snapshot cutoff recipe; the effective
    instant and original window are pinned. source_binding is copied verbatim.
    """
    if not isinstance(actors, dict) or not isinstance(question, str) or not isinstance(research_report, str):
        raise ValueError("question/report must be text and actors must be an object")
    packs, artifacts = actor_context_packs or {}, report_artifacts or {}
    if not isinstance(packs, dict) or not isinstance(artifacts, dict):
        raise ValueError("packs and report_artifacts must be objects")
    if source_binding is not None and not isinstance(source_binding, dict):
        raise ValueError("source_binding must be an object")
    if source_binding and source_binding.get("status") in {"invalid", "missing", "unbound"}:
        raise ValueError("preparation cannot adopt an unbound or invalid generation")
    source = {"question_sha256": ac.text_sha256(question), "report_sha256": ac.text_sha256(research_report),
              "actors_sha256": ac.canonical_json_sha256(actors), "sources_sha256": ac.canonical_json_sha256(sources),
              "official_data_sha256": ac.canonical_json_sha256(official_data),
              "actor_context_packs_sha256": ac.canonical_json_sha256(packs),
              "report_artifacts_sha256": ac.canonical_json_sha256(artifacts),
              "source_binding": copy.deepcopy(source_binding),
              "source_binding_sha256": ac.canonical_json_sha256(source_binding)}
    ac.canonical_json_sha256(source)  # strict input validation, including caller binding
    if official_data is not None and (not isinstance(official_data, dict) or not isinstance(official_data.get("series", []), list)):
        raise ValueError("official_data requires a series list")
    if not isinstance(actors.get("actors", []), list) or not isinstance(actors.get("quantitative_facts", []), list):
        raise ValueError("actors roster and quantitative_facts must be lists")
    ac._validate_actor_intelligence_contract(actors, research_report)
    for actor_id, pack in packs.items():
        if not isinstance(pack, dict) or pack.get("actor_id") != actor_id or any(
                pack.get("source", {}).get(k) != source[k] for k in ("actors_sha256", "report_sha256")):
            raise ValueError("actor pack differs from supplied research generation")
    window = copy.deepcopy(as_of.get("research_window", as_of.get("window"))) if isinstance(as_of, dict) else None
    requested = (as_of.get("as_of") or as_of.get("cutoff")) if isinstance(as_of, dict) else as_of
    requested = requested or actors.get("as_of_date")
    cutoff = _snapshot_cutoff(requested, window).isoformat() if requested else ""
    actor_ids = {ac.actor_id_for(a): str(a.get("name") or "") for a in actors.get("actors", []) if isinstance(a, dict)}
    if len(actor_ids) != len(actors.get("actors", [])):
        raise ValueError("duplicate or malformed preparation actor identity")
    scope = {"question": question, "as_of": cutoff, "requested_as_of": requested,
             "research_window": window, "history_limit": HISTORY_LIMIT, "actors": actor_ids}
    gaps, quantities = [], []
    qualitative = {"public": [], "modeler": [], "actors": {aid: [] for aid in sorted(actor_ids)}}
    canonical = bool(ac._actor_intelligence_contract(actors))
    selector = getattr(ac, "select_research_claims", None)
    if canonical and selector is not None:
        qualitative["public"] = copy.deepcopy(selector(actors, packs, audience="public"))
        qualitative["modeler"] = copy.deepcopy(selector(actors, packs, audience="modeler"))
        for aid in packs:
            qualitative["actors"][aid] = copy.deepcopy(selector(actors, packs, audience="actor", actor_id=aid))
    elif canonical:
        raise ValueError("canonical claim selector unavailable")
    admitted = [r for r in qualitative["public"] if r.get("dimension") == "quantitative_facts"]
    fact_rows = [(r, "actors.json") for r in (admitted if canonical else actors.get("quantitative_facts", [])) if isinstance(r, dict)]
    sidecar = artifacts.get("quantitative.json", [])
    if isinstance(sidecar, dict):
        sidecar = sidecar.get("quantitative_facts", sidecar.get("rows", []))
    if not isinstance(sidecar, list):
        raise ValueError("quantitative.json must contain a row list")
    for row in sidecar:
        if not isinstance(row, dict):
            continue
        if canonical:
            matched = next((r for r in admitted if all(r.get(k) == v for k, v in row.items())), None)
            if matched is None:
                continue
            # A subset is only a reference to the full admitted evidence, not
            # permission to shed its qualifiers/status/conditions.
            row = matched
        fact_rows.append((row, "quantitative.json"))
    official_rows = _official_rows(official_data or {}, cutoff, gaps) if official_data else []
    official_series = {r["series"] for r in official_rows}
    supplied_series = {r.get("series") for r in (official_data or {}).get("series", []) if isinstance(r, dict)}
    for raw, origin in fact_rows:
        # Stored official carriers are authoritative for status, dates and history;
        # sidecar restatements cannot bypass their availability/classification.
        if raw.get("source_origin") == "official_data" or raw.get("series") in supplied_series:
            if raw.get("series") not in official_series:
                gaps.append({"kind": "official_carrier_missing", "audience": "public"})
            continue
        if not canonical and not _public(raw, legacy=True):
            # Private payloads never appear in a shared omission message.
            local = {**copy.deepcopy(raw), "dimension": "quantitative_facts"}
            qualitative["modeler"].append(local)
            qualifiers = raw.get("qualifiers") if isinstance(raw.get("qualifiers"), dict) else {}
            aid = raw.get("actor_id")
            if (aid in qualitative["actors"] and raw.get("actor_knows") is not False
                    and qualifiers.get("actor_knows") is not False
                    and (raw.get("actor_knows") is True or qualifiers.get("actor_knows") is True)
                    and _token(raw.get("evidence_type")) != "analyst_inference"):
                qualitative["actors"][aid].append(local)
            continue
        try:
            row = _fact(raw, cutoff)
            row["provenance"]["artifact"] = origin
            quantities.append(row)
        except (ValueError, TypeError, OverflowError) as exc:
            gaps.append({"kind": "quantitative_not_admitted", "metric": _text(raw.get("metric")),
                         "reason": str(exc), "audience": "public"})
    quantities += official_rows
    quantitative = {"observations": _group([r for r in quantities if r["status"] in _OBSERVED], gaps),
                    "guidance": _group([r for r in quantities if r["status"] not in _OBSERVED], gaps)}
    # Every view obeys the same availability cutoff. Raw selected quantitative
    # claims must not bypass parsing, status, official-carrier or conflict checks
    # by travelling through a qualitative section. Public quantities are already
    # represented above. Private quantities retain their full permitted row and
    # a normalized native measurement in the owning actor/modeler view only.
    def clean_view(rows, audience):
        result = []
        for row in rows:
            try:
                _check_availability(row, cutoff)
                if row.get("dimension") == "quantitative_facts":
                    if audience == "public" or _public(row, legacy=not canonical):
                        continue
                    if row.get("source_origin") == "official_data" or row.get("series") in supplied_series:
                        continue
                    measurement = _fact(row, cutoff)
                    row = {**copy.deepcopy(row), "quantitative": measurement}
                result.append(row)
            except (ValueError, TypeError, OverflowError):
                gaps.append({"kind": "qualitative_not_admitted", "audience": audience})
        return result

    qualitative["public"] = clean_view(qualitative["public"], "public")
    qualitative["modeler"] = clean_view(qualitative["modeler"], "modeler")
    qualitative["actors"] = {aid: clean_view(rows, "actor") for aid, rows in qualitative["actors"].items()}
    bundle = {"schema_version": SCHEMA_VERSION, "source": source, "scope": scope,
              "quantitative": quantitative, "qualitative": qualitative, "gaps": gaps}
    bundle["content_sha256"] = ac.canonical_json_sha256(bundle)
    validate_preparation_context(bundle)
    return copy.deepcopy(bundle)


def validate_preparation_context(bundle, *, expected_sources=None) -> None:
    """Verify content, measurement semantics and optional expected source hash subset."""
    if not isinstance(bundle, dict) or bundle.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("unsupported preparation schema")
    digest = ac.canonical_json_sha256({k: v for k, v in bundle.items() if k != "content_sha256"})
    if bundle.get("content_sha256") != digest:
        raise ValueError("preparation content hash mismatch")
    for field in ("source", "scope", "quantitative", "qualitative"):
        if not isinstance(bundle.get(field), dict):
            raise ValueError("invalid preparation " + field)
    if (not isinstance(bundle["scope"].get("question"), str) or not isinstance(bundle["scope"].get("as_of"), str)
            or bundle["scope"].get("history_limit") != HISTORY_LIMIT):
        raise ValueError("invalid preparation scope")
    source = bundle["source"]
    for key in ("question_sha256", "report_sha256", "actors_sha256", "sources_sha256", "official_data_sha256",
                "actor_context_packs_sha256", "report_artifacts_sha256", "source_binding_sha256"):
        if not isinstance(source.get(key), str) or not re.fullmatch(r"[0-9a-f]{64}", source[key]):
            raise ValueError("invalid preparation source fingerprint: " + key)
    if source["source_binding_sha256"] != ac.canonical_json_sha256(source.get("source_binding")):
        raise ValueError("preparation binding mismatch")
    if expected_sources is not None:
        if not isinstance(expected_sources, dict) or any(k not in source or source[k] != v for k, v in expected_sources.items()):
            raise ValueError("preparation source generation mismatch")
    if ac.text_sha256(bundle["scope"].get("question", "")) != source["question_sha256"]:
        raise ValueError("preparation question mismatch")
    for category, statuses in (("observations", _OBSERVED), ("guidance", _GUIDANCE)):
        rows = bundle["quantitative"].get(category)
        if not isinstance(rows, list):
            raise ValueError("invalid quantitative section")
        for row in rows:
            if not isinstance(row, dict) or row.get("status") not in statuses or row.get("source_kind") not in {"research_fact", "official_observation"}:
                raise ValueError("invalid quantitative classification")
            if any(not isinstance(row.get(k), str) for k in ("id", "metric", "entity", "series", "provider", "source",
                                                            "unit", "period", "period_start", "period_end", "as_of", "cutoff")):
                raise ValueError("invalid quantitative identity")
            if type(row.get("value")) not in (int, float):
                raise ValueError("quantitative value must be a JSON number")
            _native_quantity(row["value"], row["unit"])
            if not isinstance(row.get("provenance"), dict) or not isinstance(row.get("source_refs"), list):
                raise ValueError("invalid quantitative provenance")
            if not _public(row["provenance"], legacy=True):
                raise ValueError("nonpublic quantitative evidence in shared section")
            if row["id"] != _identity(row) or not (row["source"] or _refs(row)):
                raise ValueError("invalid measurement identity")
            if not isinstance(row.get("history"), list) or not 0 < len(row["history"]) <= HISTORY_LIMIT:
                raise ValueError("invalid quantitative history")
            if row["cutoff"] != bundle["scope"].get("as_of"):
                raise ValueError("quantitative cutoff mismatch")
            if resolution_instant(row["as_of"]) > resolution_instant(row["cutoff"]):
                raise ValueError("quantitative availability after cutoff")
            for point in row["history"]:
                if not isinstance(point, dict) or type(point.get("value")) not in (int, float):
                    raise ValueError("invalid numeric history")
                _native_quantity(point.get("value"), row["unit"])
                provenance = point.get("provenance")
                if not isinstance(provenance, dict) or not _public(provenance, legacy=True):
                    raise ValueError("nonpublic or invalid history provenance")
                _check_availability(provenance, row["cutoff"])
                # Research facts retain their original modality. Official rows
                # use the provider classifier, which may infer status by policy.
                if row["source_kind"] == "research_fact" and _status(provenance) != point.get("status"):
                    raise ValueError("history contradicts source status")
                if point.get("status") not in statuses:
                    raise ValueError("history classification mismatch")
                if resolution_instant(point["as_of"]) > resolution_instant(row["cutoff"]):
                    raise ValueError("history availability after cutoff")
                if category == "observations" and resolution_instant(point["period_end"]) > resolution_instant(row["cutoff"]):
                    raise ValueError("observed history after cutoff")
            history_keys = [(point["period_end"] or point["period"], point["period"]) for point in row["history"]]
            if history_keys != sorted(set(history_keys)):
                raise ValueError("history periods must be unique and sorted")
            last = row["history"][-1]
            if any(last.get(k) != row.get(k) for k in (
                    "value", "period", "period_start", "period_end", "status", "as_of", "provenance", "source_refs")):
                raise ValueError("latest value differs from history")
            summary = row.get("diagnostic_summary")
            if not isinstance(summary, dict) or any(summary.get(k) != v for k, v in _summarize(row["history"]).items()):
                raise ValueError("invalid diagnostic summary")
    q = bundle["qualitative"]
    if not isinstance(q.get("public"), list) or not isinstance(q.get("modeler"), list) or not isinstance(q.get("actors"), dict):
        raise ValueError("invalid qualitative section")
    if any(not isinstance(rows, list) for rows in q["actors"].values()) or not isinstance(bundle.get("gaps"), list):
        raise ValueError("invalid qualitative rows or gaps")
    if any(not isinstance(g, dict) or g.get("audience") not in {"public", "modeler", "actor"} for g in bundle["gaps"]):
        raise ValueError("invalid preparation gap audience")
    if not isinstance(bundle["scope"].get("actors"), dict) or set(q["actors"]) != set(bundle["scope"]["actors"]):
        raise ValueError("qualitative actor roster mismatch")
    for rows in [q["public"], q["modeler"], *q["actors"].values()]:
        if any(not isinstance(r, dict) for r in rows):
            raise ValueError("qualitative evidence rows must be objects")
        for row in rows:
            _check_availability(row, bundle["scope"].get("as_of", ""))
            if row.get("dimension") == "quantitative_facts":
                measurement = _fact(row, bundle["scope"].get("as_of", ""))
                if row.get("quantitative") != measurement:
                    raise ValueError("unvalidated quantitative claim in qualitative section")
    if any(not _public(r) for r in q["public"]):
        raise ValueError("nonpublic qualitative evidence in shared section")
    for aid, rows in q["actors"].items():
        for row in rows:
            if _public(row):
                continue
            qualifiers = row.get("qualifiers") if isinstance(row.get("qualifiers"), dict) else {}
            if (row.get("actor_id") != aid or row.get("actor_knows") is False or qualifiers.get("actor_knows") is False
                    or any(_token(obj.get("evidence_type")) == "analyst_inference" for obj in (row, qualifiers))
                    or any(_token(obj.get("visibility")) in {"research_only", "analyst_only", "modeler_only", "not_known_to_actor"}
                           for obj in (row, qualifiers))
                    or not (row.get("actor_knows") is True or qualifiers.get("actor_knows") is True
                            or _token(row.get("visibility") or qualifiers.get("visibility")) in ac.ACTOR_KNOWN_VISIBILITIES)):
                raise ValueError("private qualitative evidence lacks owner permission")


_GAP_KINDS = {"conflicting_values", "missing_official_value", "period_after_cutoff", "official_not_admitted",
              "official_carrier_missing", "quantitative_not_admitted", "qualitative_not_admitted"}


def _gap_projection(gap: Mapping, audience: str) -> dict:
    """Public gaps never quote rejected evidence: denial aliases can occur in labels/errors."""
    if audience == "modeler":
        return dict(gap)
    result = {"kind": gap.get("kind") if gap.get("kind") in _GAP_KINDS else "evidence_not_admitted"}
    if type(gap.get("count")) is int and gap["count"] >= 0:
        result["count"] = gap["count"]
    return result


def _relevance_terms(text: str) -> set[str]:
    terms = set(re.findall(r"[a-z0-9]{3,}", text.casefold()))
    for run in re.findall(r"[\u3400-\u9fff]+", text):
        terms.update(run[i:i + 2] for i in range(max(1, len(run) - 1)))
    return terms - {"the", "and", "will", "what", "with", "from", "how", "might", "could", "would"}


def render_preparation_context(bundle, *, audience="public", actor_id=None, max_chars=12000) -> str:
    """Budgeted, relevance-ordered complete rows. Full history stays in the artifact.

    Actor-owned goals/constraints/plans lead actor views. Other evidence is ranked
    by question terms, then stable identity. Each quantitative projection retains
    its latest native baseline/conditions and diagnostics with explicit omitted
    history count; it never spends the prompt budget on all historical points.
    """
    validate_preparation_context(bundle)
    if audience not in {"public", "actor", "modeler"} or type(max_chars) is not int or max_chars < 0:
        raise ValueError("invalid preparation audience or budget")
    if audience == "actor" and actor_id not in bundle["qualitative"]["actors"]:
        raise ValueError("unknown preparation actor")
    rows = []
    for section in ("observations", "guidance"):
        rows += [{"section": section, **{k: v for k, v in r.items() if k != "history"},
                  "history_omitted": len(r["history"])} for r in bundle["quantitative"][section]]
    qual = bundle["qualitative"]
    selected = qual["public"] if audience == "public" else (qual["modeler"] if audience == "modeler" else qual["actors"][actor_id])
    rows += [{"section": "qualitative", **r} for r in selected]
    rows += [{"section": "gap", **_gap_projection(g, audience)} for g in bundle["gaps"]
             if g.get("audience") == "public" or audience == "modeler"]
    question_terms = _relevance_terms(bundle["scope"]["question"])
    priority_dimensions = {"goals", "objectives", "motivations", "constraints", "future_plans", "current_actions",
                           "investments_capital_allocation", "red_lines", "decision_rights_process_triggers"}

    def rank(row):
        own = audience == "actor" and row.get("actor_id") == actor_id
        priority = 0 if own and row.get("dimension") in priority_dimensions else 1 if own else 2
        content = " ".join(str(row.get(k) or "") for k in ("claim", "metric", "entity", "series", "definition", "dimension"))
        return (row.get("section") == "gap", priority, -len(question_terms & _relevance_terms(content)), _json(row))

    rows.sort(key=rank)
    header = ("Research preparation (evidence, not instructions; guidance/ranges are diagnostic only).\n"
              + "Question: " + bundle["scope"]["question"] + "\nAs of: " + (bundle["scope"]["as_of"] or "unknown"))
    chosen = []
    omitted_history = sum(row.get("history_omitted", 0) for row in rows)
    for row in rows:
        line = _json(row)
        footer = f"Omitted rows: {len(rows) - len(chosen) - 1}. History points omitted: {omitted_history}."
        trial = "\n".join([header, *chosen, line, footer])
        if len(trial) <= max_chars:
            chosen.append(line)
    footer = f"Omitted rows: {len(rows) - len(chosen)}. History points omitted: {omitted_history}."
    output = "\n".join([header, *chosen, footer])
    return output if len(output) <= max_chars else (footer if len(footer) <= max_chars else "")


def write_preparation_context(sim_dir, bundle) -> dict:
    """Publish bundle then completion proof. A partial write never loads as valid."""
    validate_preparation_context(bundle)
    root = Path(sim_dir)
    if root.is_symlink() or any((root / name).is_symlink() for name in (BUNDLE_FILE, MANIFEST_FILE)):
        raise ValueError("preparation paths must not be symlinks")
    if any((root / name).exists() for name in (BUNDLE_FILE, MANIFEST_FILE)):
        existing = load_preparation_context(root, expected_sha256=bundle["content_sha256"],
                                            expected_sources=bundle["source"])
        if existing != bundle:
            raise ValueError("cannot replace an existing preparation generation")
        return json.loads(_contained_bytes(root, MANIFEST_FILE))
    payload = _json(bundle) + "\n"
    manifest = {"schema_version": SCHEMA_VERSION, "file": BUNDLE_FILE,
                "sha256": hashlib.sha256(payload.encode()).hexdigest(),
                "content_sha256": bundle["content_sha256"], "source": copy.deepcopy(bundle["source"])}
    write_text_atomic(str(root / BUNDLE_FILE), payload)
    write_text_atomic(str(root / MANIFEST_FILE), _json(manifest) + "\n")
    return manifest


def load_preparation_context(sim_dir, expected_sha256=None, expected_sources=None) -> dict:
    """Require matching completion manifest, canonical content and caller proof."""
    root = Path(sim_dir)
    try:
        manifest_bytes = _contained_bytes(root, MANIFEST_FILE)
        manifest = json.loads(manifest_bytes)
        raw = _contained_bytes(root, BUNDLE_FILE)
        bundle = json.loads(raw)
        if (not isinstance(manifest, dict) or manifest.get("schema_version") != SCHEMA_VERSION
                or manifest.get("file") != BUNDLE_FILE or manifest.get("sha256") != hashlib.sha256(raw).hexdigest()):
            raise ValueError("invalid preparation manifest")
        validate_preparation_context(bundle, expected_sources=expected_sources)
        if manifest.get("content_sha256") != bundle["content_sha256"] or manifest.get("source") != bundle["source"]:
            raise ValueError("preparation manifest differs from bundle")
        if expected_sha256 is not None and expected_sha256 != bundle["content_sha256"]:
            raise ValueError("preparation expected hash mismatch")
        if manifest_bytes != _contained_bytes(root, MANIFEST_FILE) or raw != _contained_bytes(root, BUNDLE_FILE):
            raise ValueError("preparation changed during load")
        return bundle
    except (OSError, TypeError, KeyError, json.JSONDecodeError) as exc:
        raise ValueError("preparation artifacts missing or invalid") from exc
