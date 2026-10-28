"""Conservative, pure status consumer for already collected input artifacts.

No fetch, cache write or provider initialization occurs here. ``as_of`` describes
the input's retrieval/snapshot time, never a source publication date. Cached
content stays stale even if its snapshot is recent. Unknown provenance stays
unknown; a report-generation timestamp cannot make an undated input fresh.
"""
from __future__ import annotations

from datetime import datetime, timezone
import math
from typing import Literal, NotRequired, TypedDict


class InputHealth(TypedDict):
    status: Literal["fresh", "stale", "offline", "unknown", "empty", "disabled"]
    as_of: str | None
    attempted_at: NotRequired[str | None]
    rows: int
    reason: str


def _time(value):
    if not isinstance(value, str) or not value:
        return None
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return result.replace(tzinfo=timezone.utc) if result.tzinfo is None else result.astimezone(timezone.utc)
    except ValueError:
        return None


def _entry(payload, category, now, max_age_hours) -> InputHealth:
    if not isinstance(payload, dict):
        return {"status": "unknown", "as_of": None, "rows": 0, "reason": "missing_status_evidence"}
    status = payload.get("status")
    detail = status if isinstance(status, dict) else {}
    label = status if isinstance(status, str) else detail.get("status", detail.get("state"))
    # The sealed news carrier records per-query/provider states. Its top-level
    # as_of is a search cutoff, not a retrieval timestamp.
    native_news = category == "news" and isinstance(payload.get("providers"), dict)
    queries = payload.get("queries") if isinstance(payload.get("queries"), list) else []
    if native_news and label is None:
        states = [v.get("state") for v in payload["providers"].values() if isinstance(v, dict)]
        states += [q["status"].get("state") for q in queries
                   if isinstance(q, dict) and isinstance(q.get("status"), dict)]
        if any(s in ("unavailable", "forbidden", "timeout", "rate_limited", "error") for s in states):
            label = "offline"
        elif states and all(s == "disabled" for s in states):
            label = "disabled"
        elif states and all(s in ("ok", "verified_empty", "disabled") for s in states):
            label = "ok"
        elif states:
            label = "unknown"
    rows = None
    for key in {"markets": ("markets",), "news": ("articles", "items"),
                "official_data": ("series",), "provider": ()}[category]:
        if isinstance(payload.get(key), list):
            rows = payload[key]
            break
    count = len(rows) if rows is not None else payload.get("rows", 0)
    count = count if type(count) is int and count >= 0 else 0
    stamp = payload.get("retrieved_at") if native_news else payload.get("as_of") or payload.get("retrieved_at")
    if stamp is None and rows:
        stamps = [r.get("retrieved_at") if isinstance(r, dict) else None for r in rows]
        if all(_time(s) is not None for s in stamps):
            stamp = min(stamps, key=_time)
    if stamp is None and native_news and not rows and queries:
        stamps = [q.get("retrieved_at") if isinstance(q, dict) else None for q in queries]
        if all(_time(s) is not None for s in stamps):
            stamp = min(stamps, key=_time)
    timestamp = _time(stamp)
    result: InputHealth = {"status": "unknown", "as_of": stamp if timestamp else None,
                           "rows": count, "reason": "missing_status_evidence"}
    # A collector attempt dates availability evidence, not an absent price.
    # Keep this additive so older carriers and other inputs retain their shape.
    attempt_stamp = detail.get("attempted_at", payload.get("attempted_at"))
    attempt_time = _time(attempt_stamp)
    if "attempted_at" in detail or "attempted_at" in payload:
        result["attempted_at"] = (attempt_stamp if attempt_time is not None and attempt_time <= now else None)
    failures = detail.get("transport_failure_count")
    failed = (label in ("offline", "error", "failed", "transport_failure", "timeout")
              or (type(failures) is int and failures > 0)
              or detail.get("empty_reason") == "transport_failure"
              or bool(detail.get("transport_circuit_open"))
              or bool(detail.get("deadline_exhausted"))
              or bool(payload.get("transport_errors")))
    cached = (label == "stale" or payload.get("cached") is True
              or payload.get("from_cache") is True or payload.get("cache_status") == "hit"
              or (isinstance(payload.get("cache"), dict) and payload["cache"].get("hit") is True)
              or bool(rows and any(isinstance(r, dict) and (
                  r.get("requote_failed") is True or r.get("route") == "cache") for r in rows)))
    if (label == "disabled" or payload.get("enabled") is False
            or detail.get("empty_reason") == "disabled"):
        result.update(status="disabled", reason="input_disabled")
    elif failed:
        result.update(status="stale" if count and cached else "offline",
                      reason="cached_after_failure" if count and cached else "transport_failure")
    elif timestamp is not None and timestamp > now:
        result["reason"] = "future_snapshot_time"
    elif cached:
        result.update(status="stale", reason="cached_snapshot")
    elif timestamp is None and attempt_time is not None and attempt_time > now:
        result["reason"] = "future_attempt_time"
    elif count == 0 and (timestamp is not None or attempt_time is not None):
        successful = detail.get("successful_query_count")
        confirmed_empty = (label in ("empty", "ok", "fresh", "available")
                           or (type(successful) is int and successful > 0))
        checked_at = timestamp or attempt_time
        if confirmed_empty and (now - checked_at).total_seconds() > max_age_hours * 3600:
            result.update(status="stale", reason="status_age_exceeded")
        else:
            result.update(status="empty" if confirmed_empty else "unknown",
                          reason="no_rows" if confirmed_empty else "missing_status_evidence")
    elif timestamp is None:
        result["reason"] = "missing_snapshot_time"
    elif (now - timestamp).total_seconds() > max_age_hours * 3600:
        result.update(status="stale", reason="snapshot_age_exceeded")
    elif label in ("ok", "fresh", "available", "success") or (
            category != "provider" and rows is not None and label is None):
        result.update(status="fresh", reason="dated_snapshot")
    return result


def build_inputs_health(*, markets=None, news=None, official_data=None, provider=None,
                        as_of=None, max_age_hours=168):
    """Return forecast.json.inputs_health with explicit per-input status.

    Accepts saved market/news/official payloads or explicit status receipts with
    status/as_of/rows and optional attempted_at (also accepted inside status).
    Attempt time can date an empty status check but never a price snapshot.
    The optional as_of is the evaluation clock, not a default
    timestamp for inputs. No provider availability is inferred from configuration.
    """
    now = datetime.now(timezone.utc) if as_of is None else _time(as_of)
    if now is None:
        raise ValueError("invalid inputs-health as_of")
    if (type(max_age_hours) not in (float, int) or not math.isfinite(max_age_hours)
            or max_age_hours <= 0):
        raise ValueError("max_age_hours must be positive and finite")
    return {name: _entry(value, name, now, max_age_hours) for name, value in (
        ("markets", markets), ("news", news), ("official_data", official_data), ("provider", provider))}
