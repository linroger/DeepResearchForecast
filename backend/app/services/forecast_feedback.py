"""Immutable publication facts and exact outcome joins; no acquisition or score cache.

The legacy ledgers remain observational inputs. Only a registered publication and
validated evidence can enter this journal. Every successful append is fsynced under
a mandatory interprocess lock, and every read validates the complete journal.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import date, datetime, time, timedelta, timezone
import calendar
import hashlib
import json
import math
import os
from pathlib import Path
import re
import threading


class ForecastFeedbackError(ValueError):
    """A closed validation failure with a stable code for callers."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


_LOCK = threading.RLock()
_FILE = "published_forecasts.jsonl"
_TRACKS = ("scenario", "market_binary", "official_data_binary", "unanchored_binary")
_METADATA = {
    "historical_calibration", "official_data_track_record", "track_record",
    "forecast_track_record", "audit", "quality", "binary_quality", "objective_signals",
}


def _require(condition, code):
    if not condition:
        raise ForecastFeedbackError(code)


def _json(value):
    try:
        return json.dumps(value, sort_keys=True, ensure_ascii=False,
                          separators=(",", ":"), allow_nan=False)
    except (ValueError, TypeError, OverflowError) as exc:
        raise ForecastFeedbackError("invalid_json_value") from exc


def _clone(value):
    return json.loads(_json(value))


def _digest(value):
    return hashlib.sha256(_json(value).encode("utf-8")).hexdigest()


def _identity(value):
    _require(isinstance(value, str) and bool(value.strip()) and value == value.strip(),
             "invalid_identity")
    return value


def _probability(value):
    _require(type(value) in (int, float) and math.isfinite(value) and 0 <= value <= 1,
             "invalid_probability")
    return float(value)


def _instant(value, *, date_end=False):
    _require(isinstance(value, str) and bool(value), "invalid_timestamp")
    try:
        if len(value) == 10:
            dt = datetime.combine(date.fromisoformat(value), time.max if date_end else time.min)
        else:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)
    except ValueError as exc:
        raise ForecastFeedbackError("invalid_timestamp") from exc


def _production(row):
    from .forecast_ledger import is_production_calibration_row
    return is_production_calibration_row(row)


def _snapshot(forecast):
    _require(isinstance(forecast, dict), "invalid_forecast")
    _require(_production(forecast), "evaluation_excluded")
    snapshot = _clone({
        key: value for key, value in forecast.items()
        if key not in _METADATA and not key.endswith(("_audit", "_quality", "_track_record"))
    })
    scenarios = snapshot.get("scenarios") or []
    binaries = snapshot.get("binary_forecasts") or []
    _require(isinstance(scenarios, list) and isinstance(binaries, list)
             and bool(scenarios or binaries), "empty_forecast")
    names, ids = set(), set()
    for row in scenarios:
        _require(isinstance(row, dict) and _production(row), "invalid_scenario")
        name = _identity(row.get("name"))
        _require(name not in names, "duplicate_scenario")
        names.add(name)
        row["probability"] = _probability(row.get("probability"))
    if scenarios:
        # Published producers round probabilities to four decimals. Up to five
        # scenarios can accumulate 0.00025 rounding error; allow 0.0005 without
        # renormalizing any issued probability or changing its score/digest.
        _require(math.isclose(sum(s["probability"] for s in scenarios), 1.0,
                              rel_tol=0, abs_tol=0.0005), "invalid_scenario_distribution")
    for row in binaries:
        _require(isinstance(row, dict) and _production(row), "invalid_binary")
        fid = _identity(row.get("id"))
        _require(fid not in ids, "duplicate_forecast_id")
        ids.add(fid)
        row["probability"] = _probability(row.get("probability"))
        for key in ("market_anchor", "data_anchor"):
            if key in row and row[key] is not None:
                _require(isinstance(row[key], dict), "invalid_anchor")
    return snapshot


def forecast_publication_digest(forecast):
    """Pure canonical substantive forecast hash, independent of report/timestamp."""
    return _digest(_snapshot(forecast))


def _path(d):
    if d is None:
        from .forecast_ledger import ledger_dir
        d = ledger_dir()
    return Path(d) / _FILE


@contextmanager
def _journal(d, *, write=False):
    # fcntl is mandatory: unsupported locking must fail, never degrade silently.
    import fcntl
    path = _path(d)
    with _LOCK:
        if write:
            path.parent.mkdir(parents=True, exist_ok=True)
        try:
            stream = path.open("a+b" if write else "rb")
        except FileNotFoundError:
            if write:
                raise
            yield None, []
            return
        with stream:
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX if write else fcntl.LOCK_SH)
            stream.seek(0)
            events = []
            for line in stream:
                _require(line.endswith(b"\n"), "journal_torn_tail")
                try:
                    record = json.loads(line)
                    event = record["event"]
                    _require(record["sha256"] == _digest(event), "journal_checksum")
                    _require(record["sequence"] == len(events) + 1, "journal_sequence")
                    _require(record["previous_sha256"] == (
                        _digest(events[-1]) if events else None), "journal_chain")
                    _require(event["schema_version"] == 1, "journal_schema")
                except (ValueError, KeyError, TypeError) as exc:
                    if isinstance(exc, ForecastFeedbackError):
                        raise
                    raise ForecastFeedbackError("journal_corrupt") from exc
                events.append(event)
            yield stream, events


def _append(stream, events, event):
    event = dict(event, schema_version=1)
    encoded = (_json({
        "sequence": len(events) + 1, "previous_sha256": _digest(events[-1]) if events else None,
        "sha256": _digest(event), "event": event,
    }) + "\n").encode("utf-8")
    stream.seek(0, os.SEEK_END)
    _require(stream.write(encoded) == len(encoded), "journal_short_write")
    _durable(stream)
    events.append(event)


def _durable(stream):
    """Also used on retries: a previous complete write may have failed its fsync."""
    stream.flush()
    os.fsync(stream.fileno())
    # Persist a newly created journal's directory entry before acknowledging it.
    fd = os.open(Path(stream.name).parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _state(events):
    publications, outcomes, checked = {}, {}, {}
    for sequence, event in enumerate(events, 1):
        try:
            kind, row = event["type"], event["record"]
            rid = _identity(row["report_id"])
            if kind == "publication":
                _require(rid not in publications, "journal_duplicate_publication")
                _require(row["record_class"] == "production", "journal_record_class")
                _require(forecast_publication_digest(row["forecast"]) == row["publication_sha256"],
                         "journal_publication_digest")
                _instant(row["created_at"])
                publications[rid] = row
            elif kind == "outcome":
                _require(rid in publications, "journal_unpublished_outcome")
                publication = publications[rid]
                _require(row["publication_sha256"] == publication["publication_sha256"],
                         "journal_outcome_binding")
                if row["kind"] == "scenario":
                    expected = _scenario_record(publication, row["outcome"], row["evidence"],
                                                row["resolved_at"])
                else:
                    expected = _binary_record(publication, row["kind"], row["evidence"])
                _require(row == expected, "journal_outcome_mismatch")
                key = (rid, row["forecast_id"])
                _require(key not in outcomes, "journal_duplicate_outcome")
                outcomes[key] = row
            elif kind == "checked":
                _require(rid in publications, "journal_unpublished_visit")
                _instant(row["checked_at"])
                checked[rid] = {"sequence": sequence,
                                "visits": checked.get(rid, {}).get("visits", 0) + 1}
            else:
                raise ForecastFeedbackError("journal_event_type")
        except (KeyError, TypeError) as exc:
            raise ForecastFeedbackError("journal_corrupt") from exc
    return publications, outcomes, checked


def record_published_forecast(forecast, *, report_id, created_at, d=None):
    """Register final audited output; conflict and persistence failures propagate."""
    rid = _identity(report_id)
    snapshot = _snapshot(forecast)
    _instant(created_at)
    row = dict(report_id=rid, created_at=created_at, forecast=snapshot,
               publication_sha256=_digest(snapshot), record_class="production")
    with _journal(d, write=True) as (stream, events):
        publications, _, _ = _state(events)
        if rid in publications:
            original = publications[rid]
            _require(original["publication_sha256"] == row["publication_sha256"],
                     "publication_conflict")
            _durable(stream)
            return _clone(original)
        _append(stream, events, {"type": "publication", "record": row})
    return _clone(row)


def read_published_forecast(report_id, *, d=None):
    with _journal(d) as (_, events):
        publications, _, _ = _state(events)
        return _clone(publications.get(_identity(report_id)))


def read_published_resolutions(report_id, d=None):
    """Read committed typed outcomes with original evidence and derived scores.

    Returns detached rows sorted by kind/forecast ID. Missing or unresolved reports
    return an empty list; native candidates never enter this read. The complete
    journal and all outcome bindings are validated without creating or writing files.
    """
    rid = _identity(report_id)
    with _journal(d) as (_, events):
        _, outcomes, _ = _state(events)
        rows = [row for (stored_rid, _), row in outcomes.items() if stored_rid == rid]
        return _clone(sorted(rows, key=lambda row: (row["kind"], row["forecast_id"] or "")))


def list_published_report_ids(d=None):
    """Read registered report identities in one validated journal load."""
    with _journal(d) as (_, events):
        publications, _, _ = _state(events)
        return sorted(publications)


def verify_published_forecast(forecast, *, report_id, d=None):
    """Read-only publication check; absent is None, mismatch is a closed error."""
    original = read_published_forecast(report_id, d=d)
    digest = forecast_publication_digest(forecast)
    if original is not None:
        _require(original["publication_sha256"] == digest, "publication_conflict")
    return original


def _lane(binary):
    if binary.get("data_anchor"):
        return "official_data_binary"
    if binary.get("market_anchor"):
        return "market_binary"
    return "unanchored_binary"


def _score(scenarios, outcome):
    matches = [s for s in scenarios if s["name"] == outcome]
    _require(isinstance(outcome, str) and len(matches) == 1, "scenario_not_exact")
    probability = matches[0]["probability"]
    return {
        "brier": round(sum((s["probability"] - float(s["name"] == outcome)) ** 2
                           for s in scenarios), 4),
        "realized_probability": probability,
        "log_loss": round(-math.log(max(1e-9, probability)), 4),
        "n_scenarios": len(scenarios), "outcome_matched_a_scenario": True,
    }


def _scenario_record(publication, outcome, evidence, resolved_at):
    _require(_instant(resolved_at, date_end=True) >= _instant(publication["created_at"]),
             "outcome_before_publication")
    _require(evidence is None or isinstance(evidence, dict), "invalid_evidence")
    _require(evidence is None or _production(evidence), "evaluation_excluded")
    score = _score(publication["forecast"].get("scenarios") or [], outcome)
    return dict(report_id=publication["report_id"], forecast_id=None, kind="scenario",
                outcome=outcome, evidence=_clone(evidence), resolved_at=resolved_at,
                publication_sha256=publication["publication_sha256"], score=score)


def _persist_outcome(stream, events, outcomes, row):
    key = (row["report_id"], row["forecast_id"])
    if key in outcomes:
        original = outcomes[key]
        _require(original["kind"] == row["kind"] and original["outcome"] == row["outcome"],
                 "outcome_conflict")
        _durable(stream)
        return original, False
    _append(stream, events, {"type": "outcome", "record": row})
    outcomes[key] = row
    return row, True


def resolve_published_scenario(report_id, outcome, *, evidence=None, resolved_at, d=None):
    with _journal(d, write=True) as (stream, events):
        publications, outcomes, _ = _state(events)
        _require(report_id in publications, "unpublished_report")
        row = _scenario_record(publications[report_id], outcome, evidence, resolved_at)
        original, _ = _persist_outcome(stream, events, outcomes, row)
        return _clone(original)


def _binary_record(publication, kind, evidence):
    _require(isinstance(evidence, dict) and _production(evidence), "evaluation_excluded")
    _require(evidence.get("report_id") == publication["report_id"], "report_mismatch")
    fid = _identity(evidence.get("forecast_id"))
    binaries = publication["forecast"].get("binary_forecasts") or []
    binary = next((b for b in binaries if b["id"] == fid), None)
    _require(binary is not None, "unknown_forecast")
    _require(kind == _lane(binary) and kind != "unanchored_binary", "resolution_kind_mismatch")
    probability = binary["probability"]
    _require(_probability(evidence.get("model_p")) == probability, "probability_mismatch")
    resolved_at = evidence.get("resolved_at")
    _require(_instant(resolved_at, date_end=True) >= _instant(publication["created_at"]),
             "outcome_before_publication")
    outcome = evidence.get("resolved_outcome")
    if kind == "market_binary":
        anchor = binary["market_anchor"]
        _require(evidence.get("market_id") == _identity(anchor.get("market_id")),
                 "market_identity_mismatch")
        _require(anchor.get("resolution_equivalence") == "exact", "market_not_exact")
        # Bind supplied richer evidence when available; original anchor always survives.
        if "market_anchor" in evidence:
            _require(evidence["market_anchor"] == anchor, "market_contract_mismatch")
        if anchor.get("forecast_contract_sha256"):
            contract = str(binary.get("statement") or "").strip() + "\n" + str(
                binary.get("resolution_criteria") or "").strip()
            _require(anchor["forecast_contract_sha256"] == hashlib.sha256(
                contract.encode("utf-8")).hexdigest(), "market_contract_mismatch")
        if type(outcome) is str:
            _require(outcome in ("Yes", "No"), "invalid_outcome")
            outcome = outcome == "Yes"
        _require(type(outcome) is bool, "invalid_outcome")
        price = _probability(evidence.get("resolved_yes_price"))
        _require(price >= 0.99 if outcome else price <= 0.01, "market_not_terminal")
    else:
        from . import official_data
        anchor = binary["data_anchor"]
        _require(evidence.get("series") == _identity(anchor.get("series")), "series_mismatch")
        _require(type(outcome) is bool, "invalid_outcome")
        dataset = evidence.get("dataset_snapshot")
        _require(isinstance(dataset, dict) and _production(dataset), "invalid_dataset")
        _require(_digest(dataset) == evidence.get("dataset_sha256"), "dataset_hash_mismatch")
        # The canonical validator enriches anchors FROM the incoming dataset.
        # Check frozen period-defining metadata first so normalization cannot
        # turn a published quarterly question into a completed monthly one.
        for field in ("frequency", "geography"):
            if anchor.get(field):
                _require(dataset.get(field) == anchor[field], "data_contract_mismatch")
        carrier = {"series": [dataset]}
        original = official_data.validate_data_anchor(anchor, carrier)
        supplied = official_data.validate_data_anchor(evidence.get("data_anchor"), carrier)
        keys = ("series", "comparator", "threshold", "period", "transform", "units")
        _require(bool(original) and bool(supplied) and all(
            original.get(k) == supplied.get(k) for k in keys), "data_contract_mismatch")
        for field in ("units", "transform", "source_url", "retrieved_at", "vintage"):
            _require(evidence.get(field, "") == dataset.get(field, ""),
                     "data_provenance_mismatch")
        decision = official_data.resolve_data_anchor(anchor, dataset, as_of=resolved_at)
        _require(decision.get("status") == "resolved"
                 and type(decision.get("outcome")) is bool and decision["outcome"] == outcome
                 and decision.get("observation") == evidence.get("observation"),
                 "data_outcome_mismatch")
    return dict(report_id=publication["report_id"], forecast_id=fid, kind=kind, outcome=outcome,
                resolved_at=resolved_at, evidence=_clone(evidence),
                publication_sha256=publication["publication_sha256"],
                score={"brier": round((probability - float(outcome)) ** 2, 4),
                       "probability": probability})


def _native_rows(d, filename):
    """Strict source read: never skip a corrupted native row to select evidence."""
    import fcntl
    try:
        stream = (_path(d).parent / filename).open("rb")
    except FileNotFoundError:
        return []
    with stream:
        fcntl.flock(stream.fileno(), fcntl.LOCK_SH)
        rows = []
        for line in stream:
            _require(line.endswith(b"\n"), "native_torn_tail")
            try:
                row = json.loads(line)
            except ValueError as exc:
                raise ForecastFeedbackError("native_corrupt") from exc
            _require(isinstance(row, dict), "native_corrupt")
            rows.append(row)
        return rows


def reconcile_published_resolutions(report_id, *, market_rows=None, data_rows=None, d=None):
    """Join native rows to the original contract; never admit an unregistered report."""
    result = {"accepted": 0, "duplicates": 0, "rejected": []}
    with _journal(d, write=True) as (stream, events):
        publications, outcomes, _ = _state(events)
        _require(report_id in publications, "unpublished_report")
        sources = (
            ("market_binary", _native_rows(d, "resolutions.jsonl") if market_rows is None else market_rows),
            ("official_data_binary", _native_rows(d, "data_resolutions.jsonl") if data_rows is None else data_rows),
        )
        for kind, rows in sources:
            _require(isinstance(rows, list), "invalid_resolution_rows")
            for evidence in rows:
                if isinstance(evidence, dict) and evidence.get("report_id") != report_id:
                    continue
                try:
                    row = _binary_record(publications[report_id], kind, evidence)
                    _, added = _persist_outcome(stream, events, outcomes, row)
                    result["accepted" if added else "duplicates"] += 1
                except ForecastFeedbackError as exc:
                    result["rejected"].append({
                        "kind": kind, "forecast_id": evidence.get("forecast_id") if isinstance(evidence, dict) else None,
                        "reason": exc.code,
                    })
    return result


def _due(binary, forecast):
    anchor = binary.get("data_anchor") or binary.get("market_anchor") or {}
    if binary.get("data_anchor"):
        # Use the official observation period, not the report's broader horizon.
        frequency = str(anchor.get("frequency") or "").upper()
        canonical = str(anchor.get("period") or "")
        period = canonical if frequency and re.fullmatch(r"\d{4}-\d{2}-\d{2}", canonical) else str(
            anchor.get("observation") or canonical)
        try:
            if re.fullmatch(r"\d{4}", period):
                return date(int(period), 12, 31).isoformat()
            quarter = re.fullmatch(r"(\d{4})-Q([1-4])", period)
            if quarter:
                year, month = int(quarter[1]), 3 * int(quarter[2])
                return date(year, month, calendar.monthrange(year, month)[1]).isoformat()
            if re.fullmatch(r"\d{4}-\d{2}", period):
                year, month = map(int, period.split("-"))
                return date(year, month, calendar.monthrange(year, month)[1]).isoformat()
            if re.fullmatch(r"\d{4}-\d{2}-\d{2}", period):
                start = date.fromisoformat(period)
                if frequency in ("M", "Q", "A"):
                    months = start.month - 1 + {"M": 1, "Q": 3, "A": 12}[frequency]
                    return (date(start.year + months // 12, months % 12 + 1, 1)
                            - timedelta(days=1)).isoformat()
                return (start + timedelta(days=6 if frequency == "W" else 0)).isoformat()
        except ValueError:
            return None  # A malformed contract stays visible for manual review.
        return None  # Unrecognized official period must not inherit a distant horizon.
    for candidate in (binary.get("resolution_date"), anchor.get("endDate")):
        if candidate:
            try:
                return _instant(candidate).date().isoformat()
            except ForecastFeedbackError:
                pass
    for key in ("resolution_criteria", "resolution_source", "statement"):
        match = re.search(r"\b\d{4}-\d{2}-\d{2}\b", str(binary.get(key) or ""))
        if match:
            try:
                return date.fromisoformat(match[0]).isoformat()
            except ValueError:
                pass
    from .forecast_ledger import _year_end
    return _year_end(str(binary.get("horizon_year") or forecast.get("horizon") or ""))


def _outstanding(publications, outcomes, checked, as_of):
    cutoff = _instant(as_of, date_end=True).date().isoformat() if as_of else None
    grouped = {}
    for rid, publication in publications.items():
        for binary in publication["forecast"].get("binary_forecasts") or []:
            if (rid, binary["id"]) in outcomes:
                continue
            due = _due(binary, publication["forecast"])
            if cutoff and due and due > cutoff:
                continue
            grouped.setdefault(rid, []).append(dict(
                report_id=rid, forecast_id=binary["id"], kind=_lane(binary),
                probability=binary["probability"], resolution_date=due,
                created_at=publication["created_at"],
                publication_sha256=publication["publication_sha256"], binary=binary,
                selection_token=checked.get(rid, {}).get("sequence", 0)))
    report_ids = sorted(grouped, key=lambda rid: (
        checked.get(rid, {}).get("sequence", 0),
        min(row["resolution_date"] or "9999-12-31" for row in grouped[rid]),
        _instant(publications[rid]["created_at"]), rid))
    for rid, rows in grouped.items():
        # A report can exceed the question limit. Rotate its eligible prefix on
        # every durable visit so a manual question cannot starve later questions.
        offset = checked.get(rid, {}).get("visits", 0) % len(rows)
        grouped[rid] = rows[offset:] + rows[:offset]
    return report_ids, grouped


def _limit(limit):
    _require(type(limit) is int and limit >= 0, "invalid_limit")
    return limit


def list_outstanding_published_questions(*, as_of=None, limit=100, d=None):
    with _journal(d) as (_, events):
        ids, grouped = _outstanding(*_state(events), as_of)
        # Round-robin across reports so one large report cannot consume the batch.
        rows = []
        index = 0
        while len(rows) < _limit(limit) and any(index < len(grouped[rid]) for rid in ids):
            for rid in ids:
                if index < len(grouped[rid]) and len(rows) < limit:
                    rows.append(grouped[rid][index])
            index += 1
        return _clone(rows)


def outstanding_published_report_ids(*, as_of=None, limit=20, d=None):
    with _journal(d) as (_, events):
        ids, _ = _outstanding(*_state(events), as_of)
        return ids[:_limit(limit)]


def mark_published_report_checked(report_id, *, checked_at, selection_token=None, d=None):
    """Rotate a completed report attempt; limited batches must pass their token."""
    _instant(checked_at)
    with _journal(d, write=True) as (stream, events):
        publications, _, checked = _state(events)
        _require(report_id in publications, "unpublished_report")
        if selection_token is not None:
            sequence = checked.get(report_id, {}).get("sequence", 0)
            _require(type(selection_token) is int and 0 <= selection_token <= sequence,
                     "invalid_selection_token")
            if selection_token != sequence:
                # Another poller already advanced this exact selected generation.
                _durable(stream)
                return _clone(events[sequence - 1]["record"])
        row = dict(report_id=report_id, checked_at=checked_at)
        _append(stream, events, {"type": "checked", "record": row})
    return row


def _legacy_summary(d, excluded):
    from .forecast_ledger import read_ledger
    unique, conflicts = {}, set()
    for row in read_ledger(d):
        if (not isinstance(row, dict) or not _production(row) or row.get("resolved") is not True
                or row.get("report_id") in excluded):
            continue
        try:
            rid = _identity(row.get("report_id"))
            snapshot = _snapshot({"scenarios": row.get("scenarios")})
            score = _score(snapshot["scenarios"], row.get("outcome"))["brier"]
            identity = _digest({"forecast": snapshot, "outcome": row.get("outcome")})
            if rid in unique and unique[rid][0] != identity:
                conflicts.add(rid)
            unique[rid] = (identity, score)
        except ForecastFeedbackError:
            continue
    scores = [score for rid, (_, score) in unique.items() if rid not in conflicts]
    return dict(source="ledger.jsonl", n_resolved=len(scores),
                mean_brier=round(sum(scores) / len(scores), 4) if scores else None)


def _typed_track_record(events, exclude_report_id):
    publications, outcomes, _ = _state(events)
    included = {rid: row for rid, row in publications.items() if rid != exclude_report_id}
    tracks = {kind: dict(n_forecasts=0, n_resolved=0, n_outstanding=0,
                         mean_brier=None, coverage=0.0) for kind in _TRACKS}
    for publication in included.values():
        forecast = publication["forecast"]
        tracks["scenario"]["n_forecasts"] += bool(forecast.get("scenarios"))
        for binary in forecast.get("binary_forecasts") or []:
            tracks[_lane(binary)]["n_forecasts"] += 1
    scored = [row for (rid, _), row in outcomes.items() if rid in included]
    scored.sort(key=lambda row: (row["report_id"], row["kind"], row["forecast_id"] or ""))
    for kind, track in tracks.items():
        values = [row["score"]["brier"] for row in scored if row["kind"] == kind]
        track["n_resolved"] = len(values)
        track["n_outstanding"] = track["n_forecasts"] - len(values)
        track["mean_brier"] = round(sum(values) / len(values), 4) if values else None
        track["coverage"] = len(values) / track["n_forecasts"] if track["n_forecasts"] else 0.0
    facts = {"publications": [included[rid] for rid in sorted(included)],
             "outcomes": scored}
    return dict(schema_version=1, source=_FILE, source_digest=_digest(facts),
                journal_length=len(events), journal_sha256=_digest(events),
                excluded_report_id=exclude_report_id,
                n_reports=len(included), tracks=tracks,
                scored_identities=[{key: row[key] for key in ("report_id", "forecast_id", "kind")}
                                   for row in scored])


def production_track_record(*, d=None, exclude_report_id=None):
    with _journal(d) as (_, events):
        result = _typed_track_record(events, exclude_report_id)
        registered = {event["record"]["report_id"] for event in events if event["type"] == "publication"}
    result["legacy_scenario"] = _legacy_summary(d, registered | {exclude_report_id})
    return result


def verify_production_track_record(summary, *, exclude_report_id=None, d=None):
    """Verify frozen typed history from its journal prefix without refreshing it.

    Legacy scenario rows are mutable and deliberately outside this proof. Callers
    must never describe legacy_scenario as verified immutable publication history.
    """
    _require(isinstance(summary, dict), "track_record_mismatch")
    length = summary.get("journal_length")
    _require(type(length) is int and length >= 0, "track_record_prefix_mismatch")
    with _journal(d) as (_, events):
        _state(events)  # Corruption after the prefix must still fail closed.
        _require(length <= len(events) and _digest(events[:length]) == summary.get("journal_sha256"),
                 "track_record_prefix_mismatch")
        expected = _typed_track_record(events[:length], exclude_report_id)
    actual = {key: value for key, value in summary.items() if key != "legacy_scenario"}
    # Canonical JSON comparison rejects Python's True == 1 and related coercions.
    _require(_json(actual) == _json(expected), "track_record_mismatch")
    return True
