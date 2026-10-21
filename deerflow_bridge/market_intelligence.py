"""Bounded, source-aware market discovery for the shared context snapshot.

This module never writes the canonical Polymarket registry. All rows are research
context; title similarity establishes neither event equivalence nor arbitrage.
Provider documentation and compatibility limits are in market-implementation.md.
"""
from __future__ import annotations

import hashlib
import http.client
import importlib
import json
import math
import os
import re
import time
from datetime import datetime, timezone
from urllib.parse import quote, urlencode, urlsplit

KALSHI_BASE_URL = "https://external-api.kalshi.com/trade-api/v2"
METHOD = "market-context/v1"
MAX_BYTES = 1_000_000
MAX_PAGES = 2
PAGE_SIZE = 100
MAX_DETAILS = 2
MAX_ITEMS = 8
_ELIGIBILITY = {"context_only": True, "anchor": False, "resolution": False}


class _Failure(Exception):
    def __init__(self, state, reason):
        self.state, self.reason = state, reason
        super().__init__(reason)


def _bridge(name):
    return importlib.import_module(f"{__package__}.{name}" if __package__ else name)


def _now():
    return datetime.now(timezone.utc).isoformat()


def _text(value, limit=2000):
    if not isinstance(value, str):
        return None
    return re.sub(r"[\x00-\x1f\x7f]", " ", value).strip()[:limit] or None


def _number(value, *, maximum=None):
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        return None
    try:
        number = float(value)
    except (ValueError, TypeError, OverflowError):
        return None
    if not math.isfinite(number) or number < 0 or (maximum is not None and number > maximum):
        return None
    return number


def _timestamp(value):
    value = _text(value, 64)
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.astimezone(timezone.utc).isoformat() if parsed.tzinfo else None
    except ValueError:
        return None


def _enabled(name):
    return os.environ.get(name, "true").strip().lower() in {"1", "true", "yes", "on"}


def _limit(name, default, maximum):
    value = _number(os.environ.get(name, str(default)), maximum=None)
    return min(maximum, value) if value is not None else default


def _result(provider, query, state, *, attempted=False, reason=None, items=None, **metadata):
    status = {"state": state, "attempted": attempted}
    if reason:
        status["reason"] = reason
    return {"provider": provider, "query": query, "status": status,
            "items": items or [], "retrieved_at": _now(), "method": METHOD, **metadata}


def normalize_kalshi_market(raw, query, *, retrieved_at=None, language=None):
    """Read documented dollar/fixed-point fields without guessing cent scales."""
    if not isinstance(raw, dict):
        return None
    ticker, title = _text(raw.get("ticker"), 200), _text(raw.get("title"), 500)
    if not ticker or not title:
        return None
    binary = raw.get("market_type") == "binary"
    prices = {key: _number(raw.get(key + "_dollars"), maximum=1)
              for key in ("yes_bid", "yes_ask", "no_bid", "no_ask", "last_price")}
    # Keep the quote basis explicit. A last trade has unknown age; never silently
    # replace a missing quote with zero, the opposite outcome, or a midpoint.
    probability = prices["last_price"] if binary else None
    row = {
        "id": f"kalshi:{ticker}", "native_id": ticker, "provider": "kalshi",
        "kind": "market_quote", "title": title,
        "url": KALSHI_BASE_URL + "/markets/" + quote(ticker, safe=""),
        "published_at": _timestamp(raw.get("created_time")),
        "retrieved_at": retrieved_at or _now(), "language": language,
        "query": query, "snippet": _text(raw.get("subtitle")),
        "eligibility": dict(_ELIGIBILITY), "market_type": _text(raw.get("market_type"), 40),
        "event_id": _text(raw.get("event_ticker"), 200),
        "outcome": "Yes" if binary else None,
        "yes_label": _text(raw.get("yes_sub_title"), 500),
        "no_label": _text(raw.get("no_sub_title"), 500),
        "probability": probability,
        "probability_basis": "last_price_dollars/1_USD_binary_payout" if probability is not None else None,
        "quote_basis": "provider_reported_dollars_per_contract",
        "price_unit": "USD_per_contract", "quote_at": None,
        # updated_time tracks metadata changes, not a last-trade timestamp.
        "metadata_updated_at": _timestamp(raw.get("updated_time")),
        "volume": _number(raw.get("volume_fp")), "volume_unit": "contracts",
        "volume_24h": _number(raw.get("volume_24h_fp")),
        "open_interest": _number(raw.get("open_interest_fp")),
        "notional_value": _number(raw.get("notional_value_dollars")),
        "rules_primary": _text(raw.get("rules_primary"), 6000),
        "rules_secondary": _text(raw.get("rules_secondary"), 3000),
        "end_date": _timestamp(raw.get("close_time")),
        "expiration_time": _timestamp(raw.get("expiration_time")),
        "strike_type": _text(raw.get("strike_type"), 80),
        "floor_strike": _finite_strike(raw.get("floor_strike")),
        "cap_strike": _finite_strike(raw.get("cap_strike")),
        "status": _text(raw.get("status"), 40),
    }
    row.update(prices)
    row["rules"] = "\n".join(part for part in (row["rules_primary"], row["rules_secondary"]) if part) or None
    row["volume_units"] = row["volume_unit"]
    row["units"] = row["price_unit"]
    row["price_basis"] = row["probability_basis"] or row["quote_basis"]
    row["contract_type"] = row["market_type"]
    row.update(bid=prices["yes_bid"], ask=prices["yes_ask"], last=prices["last_price"],
               quote_units="USD_per_contract")
    row["source_price_fields"] = {key + "_dollars": raw.get(key + "_dollars")
                                  if prices[key] is not None else None for key in prices}
    row["evidence_sha256"] = hashlib.sha256(json.dumps(
        row, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
        allow_nan=False).encode()).hexdigest()
    return row


def _finite_strike(value):
    # Strike thresholds can legitimately be negative.
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        return None
    try:
        number = float(value)
        return number if math.isfinite(number) else None
    except (ValueError, OverflowError):
        return None


class _Transport:
    def __init__(self, deadline, allowance, *, reserve_network):
        self.deadline, self.allowance, self.calls = deadline, allowance, 0
        self.reserve_network = reserve_network
        self.http_timeout = _limit("NEWS_CONTEXT_HTTP_TIMEOUT_SECONDS", 5, 5)

    def get(self, url, params=None):
        remaining = self.deadline - time.monotonic()
        if remaining <= 0 or self.http_timeout <= 0:
            raise _Failure("timeout", "deadline_exhausted")
        if self.calls >= self.allowance:
            raise _Failure("budget_exhausted", "market_request_limit")
        parts = urlsplit(url)
        valid = ((parts.netloc == "gamma-api.polymarket.com" and parts.path == "/public-search")
                 or (parts.netloc == "external-api.kalshi.com"
                     and (parts.path == "/trade-api/v2/markets"
                          or parts.path.startswith("/trade-api/v2/markets/"))))
        if parts.scheme != "https" or not valid or parts.query or parts.fragment:
            raise _Failure("unavailable", "endpoint_not_allowed")
        reservation = self.reserve_network()
        if not isinstance(reservation, dict) or reservation.get("allowed") is not True:
            state = reservation.get("state") if isinstance(reservation, dict) else None
            reason = reservation.get("reason") if isinstance(reservation, dict) else None
            if state not in {"timeout", "budget_exhausted", "unavailable"}:
                state = "unavailable"
            if not isinstance(reason, str) or not re.fullmatch(r"[a-zA-Z0-9_.:-]{1,100}", reason):
                reason = "market_reservation_denied"
            raise _Failure(state, reason)
        # The store has fsynced the reservation before this HTTP dispatch.
        self.calls += 1
        reserved_deadline = reservation.get("deadline")
        if isinstance(reserved_deadline, (int, float)) and math.isfinite(reserved_deadline):
            self.deadline = min(self.deadline, reserved_deadline)
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise _Failure("timeout", "deadline_exhausted")
        connection = http.client.HTTPSConnection(parts.netloc, timeout=min(self.http_timeout, remaining))
        try:
            path = parts.path + (("?" + urlencode(params)) if params else "")
            connection.request("GET", path, headers={"Accept": "application/json", "User-Agent": "DRF-market-context/1"})
            response = connection.getresponse()
            if response.status != 200:
                state = {401: "forbidden", 403: "forbidden", 429: "rate_limited"}.get(response.status, "unavailable")
                raise _Failure(state, f"http_{response.status}")
            body = bytearray()
            while True:
                remaining = self.deadline - time.monotonic()
                if remaining <= 0:
                    raise _Failure("timeout", "deadline_exhausted")
                read_socket = connection.sock or getattr(getattr(getattr(response, "fp", None), "raw", None), "_sock", None)
                if read_socket is not None:
                    read_socket.settimeout(min(self.http_timeout, remaining))
                block = response.read1(min(65536, MAX_BYTES + 1 - len(body)))
                if not block:
                    break
                body.extend(block)
                if len(body) > MAX_BYTES:
                    raise _Failure("unavailable", "response_too_large")
            try:
                return json.loads(body, parse_constant=lambda _: None)
            except (ValueError, UnicodeError):
                raise _Failure("unavailable", "invalid_json") from None
        except _Failure:
            raise
        except (TimeoutError, OSError) as exc:
            state = "timeout" if isinstance(exc, TimeoutError) else "unavailable"
            raise _Failure(state, "transport_failure") from None
        except Exception:
            raise _Failure("unavailable", "transport_failure") from None
        finally:
            connection.close()


def _polymarket(query, transport, language):
    module = _bridge("market_tools")
    diagnostics, captured_raw = {}, {}
    def fetch(q, limit):
        payload = transport.get(module.POLYMARKET_BASE_URL + "/public-search",
                                {"q": q, "limit_per_type": limit, "events_status": "active"})
        if not isinstance(payload, dict) or not isinstance(payload.get("events"), list):
            raise _Failure("unavailable", "invalid_schema")
        events = []
        for event in payload["events"][:PAGE_SIZE]:
            if not isinstance(event, dict):
                continue
            bounded_event = dict(event)
            markets = event.get("markets")
            bounded_event["markets"] = markets[:PAGE_SIZE] if isinstance(markets, list) else []
            for raw in bounded_event["markets"]:
                if isinstance(raw, dict) and raw.get("id") is not None:
                    captured_raw[str(raw["id"])] = raw
            events.append(bounded_event)
        return events
    failure = []
    def bounded_fetch(q, limit):
        try:
            return fetch(q, limit)
        except _Failure as exc:
            failure.append(exc)
            # Existing owner logs this exception. Emit only a stable code.
            raise RuntimeError(exc.reason) from None
    records = module.snapshot_for_queries([query], per_query=MAX_ITEMS, max_total=MAX_ITEMS,
                                         fetch=bounded_fetch, diagnostics=diagnostics)
    items = []
    captured = _now()
    for record in records:
        raw = captured_raw.get(record["market_id"], {})
        names = module._as_list(raw.get("outcomes"))
        binary = len(names) == 2 and {str(n).strip().casefold() for n in names} == {"yes", "no"}
        prob = _number(record.get("implied_yes_prob"), maximum=1) if binary else None
        items.append({
            "id": "polymarket:" + record["market_id"], "native_id": record["market_id"],
            "provider": "polymarket", "kind": "market_quote", "title": record["question"],
            "url": record.get("url") or None, "query": query, "language": language,
            "published_at": _timestamp(raw.get("createdAt")), "retrieved_at": captured, "quote_at": None,
            "snippet": None, "eligibility": dict(_ELIGIBILITY), "outcome": "Yes" if binary else None,
            "probability": prob, "probability_basis": "Gamma_outcomePrices_literal_Yes" if prob is not None else None,
            "quote_basis": "Gamma_outcomePrices_literal_Yes", "price_unit": "USD_per_share",
            "price_basis": "Gamma_outcomePrices_literal_Yes", "units": "USD_per_share", "volume_units": "USD",
            "contract_type": "binary" if binary else None, "rules": _text(raw.get("description"), 6000),
            "volume": _number(raw.get("volume")), "volume_unit": "USD",
            "end_date": _timestamp(record.get("end_date")), "rules_primary": _text(raw.get("description"), 6000),
            "rules_secondary": None, "yes_bid": None, "yes_ask": None, "last_price": None,
            "bid": None, "ask": None, "last": None, "quote_units": "USD_per_share",
            "source_price_fields": {"outcomes": [_text(n, 80) for n in names[:8]],
                                    "outcomePrices": [_number(p, maximum=1) for p in module._as_list(raw.get("outcomePrices"))[:8]]},
        })
    if failure:
        exc = failure[0]
        return _result("polymarket", query, exc.state, attempted=transport.calls > 0, reason=exc.reason)
    return _result("polymarket", query, "ok" if items else "verified_empty", attempted=True,
                   items=items, recall_complete=False, recall_reason="existing_Polymarket_bounded_liquidity_filter")


def _tokens(value):
    return set(re.findall(r"[^\W_]+", value.casefold(), flags=re.UNICODE))


def _kalshi(query, transport, language):
    start_calls = transport.calls
    candidates, seen, cursor, pages = [], set(), None, 0
    complete, failure = False, None
    # Reserve at least one detail call if there is a topical candidate.
    try:
        for _ in range(MAX_PAGES):
            params = {"status": "open", "limit": PAGE_SIZE, "mve_filter": "exclude"}
            if cursor:
                params["cursor"] = cursor
            payload = transport.get(KALSHI_BASE_URL + "/markets", params)
            pages += 1
            if not isinstance(payload, dict) or not isinstance(payload.get("markets"), list):
                raise _Failure("unavailable", "invalid_schema")
            for raw in payload["markets"][:PAGE_SIZE]:
                if not isinstance(raw, dict):
                    continue
                ticker = _text(raw.get("ticker"), 200)
                text = " ".join(str(raw.get(k) or "") for k in ("title", "subtitle", "yes_sub_title", "event_ticker", "ticker"))
                if ticker and ticker not in seen and _tokens(query) & _tokens(text):
                    candidates.append(raw)
                    seen.add(ticker)
            next_cursor = payload.get("cursor")
            if not isinstance(next_cursor, str) or len(next_cursor) > 2000:
                raise _Failure("unavailable", "invalid_cursor")
            if not next_cursor:
                complete = True
                break
            if next_cursor == cursor:
                raise _Failure("partial", "repeated_cursor")
            cursor = next_cursor
            if candidates and transport.allowance - transport.calls <= 1:
                break
    except _Failure as exc:
        failure = exc
    items, detail_attempts = [], 0
    details_stopped = failure is not None
    for raw in candidates[:MAX_ITEMS]:
        detail_obtained = False
        if detail_attempts < MAX_DETAILS and not details_stopped:
            detail_attempts += 1
            try:
                detail = transport.get(KALSHI_BASE_URL + "/markets/" + quote(raw["ticker"], safe=""))
                value = detail.get("market") if isinstance(detail, dict) else None
                if not isinstance(value, dict) or value.get("ticker") != raw["ticker"]:
                    raise _Failure("unavailable", "invalid_detail_schema")
                raw, detail_obtained = value, True
            except _Failure as exc:
                failure, details_stopped = exc, True
        row = normalize_kalshi_market(raw, query, language=language)
        if row:
            row["detail_obtained"] = detail_obtained
            items.append(row)
    recall_complete = complete and len(candidates) <= MAX_ITEMS
    state = "partial" if failure or not recall_complete else ("ok" if items else "verified_empty")
    if failure and not pages and not items:
        state = failure.state
    return _result("kalshi", query, state, attempted=transport.calls > start_calls,
                   reason=failure.reason if failure else (None if recall_complete else "bounded_catalog_scan"),
                   items=items, recall_complete=recall_complete, pages=pages,
                   candidate_count=len(candidates), search_method="bounded_catalog_token_overlap_candidates_only")


def _historical_cutoff(as_of):
    """Normal v3 runs use today's UTC date, which permits a present capture.

    An explicit earlier instant is different from a date-only run label. These
    feeds do not prove historical point-in-time availability at that instant.
    """
    if as_of is None or as_of == "":
        return False
    if not isinstance(as_of, str):
        return True
    try:
        now = datetime.now(timezone.utc)
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", as_of):
            return datetime.fromisoformat(as_of).date() < now.date()
        cutoff = datetime.fromisoformat(as_of.replace("Z", "+00:00"))
        return cutoff.tzinfo is None or cutoff < now
    except ValueError:
        return True


def compare_markets(client, query, *, deadline=None):
    """Discover context candidates, persist once, replay sealed captures unchanged."""
    query = " ".join(str(query or "").split())[:500]
    if not query:
        return _result("market_compare", query, "unsupported", reason="empty_query")
    if not _enabled("NEWS_CONTEXT_ENABLED") or not _enabled("MARKET_INTELLIGENCE_ENABLED"):
        return _result("market_compare", query, "disabled", reason="market_intelligence_disabled")
    end = time.monotonic() + _limit("NEWS_CONTEXT_DEADLINE_SECONDS", 10, 10)
    if deadline is not None:
        try:
            supplied = time.monotonic() + deadline.remaining() if hasattr(deadline, "remaining") else float(deadline)
            end = min(end, supplied) if math.isfinite(supplied) else time.monotonic()
        except (TypeError, ValueError, OverflowError):
            return _result("market_compare", query, "unsupported", reason="invalid_deadline")
    snapshot = client.snapshot()
    snapshot.setdefault("as_of", getattr(client, "as_of", None))
    snapshot.setdefault("language", getattr(client, "language", None))
    if hasattr(client, "artifact_dir") and client.artifact_dir is None:
        return _result("market_compare", query, "unavailable", reason="artifact_dir_required")
    capture = getattr(client, "capture_market", None)
    if not callable(capture):
        return _result("market_compare", query, "unavailable", reason="atomic_market_capture_unavailable")
    results = []
    for provider in ("polymarket", "kalshi", "metaculus"):
        if provider == "metaculus":
            result = client.record_result(provider, query, _result(
                provider, query, "unsupported",
                reason="authenticated_community_forecast_access_not_established",
                kind="community_forecast", network_requests=0))
        elif _historical_cutoff(snapshot.get("as_of")):
            result = client.record_result(provider, query, _result(
                provider, query, "unsupported", reason="historical_quote_availability_not_established",
                network_requests=0))
        else:
            def acquire(reserve_network, selected=provider):
                # Durable request admission and cross-process exclusion belong
                # solely to ContextClient. This local bound only narrows a call.
                transport = _Transport(end, 4, reserve_network=reserve_network)
                try:
                    result = (_polymarket if selected == "polymarket" else _kalshi)(
                        query, transport, snapshot.get("language"))
                except _Failure as exc:
                    result = _result(selected, query, exc.state, attempted=transport.calls > 0, reason=exc.reason)
                result["network_requests"] = transport.calls
                if "recall_complete" in result:
                    result["incomplete_recall"] = not result["recall_complete"]
                    result["coverage"] = "bounded_catalog_scan" if selected == "kalshi" else "existing_liquidity_filtered_search"
                return result
            result = capture(provider, query, acquire, deadline=end)
        results.append(result)
    items = [row for result in results for row in result.get("items", [])]
    states = {result["status"]["state"] for result in results}
    state = "partial" if states - {"ok", "verified_empty"} else ("ok" if items else "verified_empty")
    return _result("market_compare", query, state,
                   attempted=any(result["status"].get("attempted") for result in results),
                   items=items, providers=results,
                   retrieved_at=max((r["retrieved_at"] for r in results if r.get("retrieved_at")), default=None),
                   comparison_basis="topic_candidates_only",
                   equivalence_established=False,
                   limitations="Distinct contracts; verify entities, thresholds, horizons, rules and outcome polarity. Prices are indicative context; no executable arbitrage or automatic anchoring.")
