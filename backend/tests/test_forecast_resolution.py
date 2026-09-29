"""EVAL-2: market settlement events v2.

Covers the sealed / publishable-at-issue gate, anchor eligibility, outcome_known_at
and its basis, the prospective lower-bound proof, pending reasons, grace terminals,
50/50 ambiguous settlements and the ledger settle sweep. Offline: Gamma rows are
fixtures parsed by ``_parse_resolution``, market clients are fakes, reports are
synthetic sealed bundles in a per-test REPORTS_DIR; no LLM, no network.
"""

import hashlib
import json
import math
import os

import pytest

import scripts.resolution_monitor as mon
from app.config import Config
from app.services import forecast_ledger as fl
from app.services import forecast_resolution as fr
from app.services.forecast_extractor import _build_market_anchor
from app.services.report_agent import FINAL_AUDIT_STALE_POLICY_REASON, ReportManager
from app.utils import prediction_markets as pm
from app.utils.point_in_time import parse_stamp_strict

PROCESSED = "2026-09-29T12:00:00+00:00"
CLOSED_AT = "2026-07-02T15:30:00+00:00"
STATEMENT = "The EU AI liability directive is adopted by 2026-06-30."
CRITERIA = "Resolves YES if the Official Journal publishes the directive by 2026-06-30."
QUESTION = "Will the EU adopt a binding AI liability directive by mid-2026?"
META = {"as_of": "2026-05-01", "created_at": "2026-05-02T08:00:00+00:00", "commit_id": "c-1"}
LEGACY_RESOLUTION_KEYS = ("market_id", "closed", "resolved", "resolved_outcome",
                          "resolved_yes_price", "uma_status")
V2_EVENT_KEYS = {"schema_version", "item_kind", "source_kind", "outcome", "y",
                 "outcome_known_at", "known_at_basis", "known_at_clamped", "processed_at",
                 "prospective", "scoring_eligible", "ineligible_reason", "resolution_status",
                 "report_publishable_at_issue", "target_commit_id", "evidence",
                 "terminal_reason"}


def _sha(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _binary(fid="F1", *, market_id="m-1", equivalence="exact",
            end_date="2026-06-30T12:00:00Z", price=0.40, probability=0.30):
    """A binary with an anchor built by the real producer (complete and byte-bound)."""
    binary = {"id": fid, "proposition_id": f"prop-{fid}", "statement": STATEMENT,
              "probability": probability, "resolution_criteria": CRITERIA,
              "horizon_year": 2026}
    market = {"market_id": market_id,
              "question": "Will the EU adopt the AI liability directive by June 30, 2026?",
              "implied_yes_prob": price, "url": f"https://polymarket.com/event/{market_id}",
              "end_date": end_date}
    binary["market_anchor"] = _build_market_anchor(
        probability, market, equivalence=equivalence, match_confidence=0.9, binary=binary)
    return binary


def _gamma(market_id, yes, *, closed=True, uma="resolved", closed_time="2026-07-02T15:30:00Z"):
    """One Gamma /markets row (string prices, like the real API)."""
    raw = {"id": market_id, "question": "q", "outcomes": '["Yes","No"]',
           "outcomePrices": json.dumps([str(yes), str(round(1 - yes, 4))]),
           "closed": closed, "umaResolutionStatus": uma,
           "endDate": "2026-06-30T12:00:00Z"}
    if closed_time is not None:
        raw["closedTime"] = closed_time
    return raw


def _resolved(market_id, yes=1.0, **kwargs):
    return pm._parse_resolution(_gamma(market_id, yes, **kwargs))


def _json_out(capsys):
    """The JSON document the CLI printed (the app logger may share stdout)."""
    out = capsys.readouterr().out
    return json.loads(out[out.index("{\n"):] if not out.startswith("{") else out)


class _Client:
    """Offline market client: records every call; requote keeps research prices."""

    def __init__(self, resolutions=None):
        self._resolutions = resolutions or {}
        self.calls = []

    def requote_markets(self, rows):
        self.calls.append(("requote", [r.get("market_id") for r in rows]))
        return [dict(r, implied_yes_prob=r.get("price_at_research"), price_delta=0.0)
                for r in rows]

    def fetch_resolutions(self, ids):
        self.calls.append(("resolutions", list(ids)))
        return {mid: self._resolutions[mid] for mid in ids if mid in self._resolutions}


@pytest.fixture
def reports_dir(monkeypatch, tmp_path):
    monkeypatch.setattr(Config, "UPLOAD_FOLDER", str(tmp_path), raising=False)
    monkeypatch.setattr(ReportManager, "REPORTS_DIR", str(tmp_path / "reports"), raising=False)
    return tmp_path / "reports"


def _forecast(binaries):
    return {"horizon": "2026", "confidence": "low",
            "scenarios": [{"name": "Adopted", "probability": 0.3, "resolution_criteria": "OJ"},
                          {"name": "Stalled", "probability": 0.7, "resolution_criteria": "none"}],
            "binary_forecasts": binaries}


def _write_sealed_report(report_id, forecast, *, hard_passed=True):
    """meta.json + full_report.md + forecast.json + final_audit.json, sealed like the audit."""
    folder = ReportManager._get_report_folder(report_id)
    os.makedirs(folder, exist_ok=True)
    markdown = "# Forecast report\n\nBody.\n"
    with open(os.path.join(folder, "meta.json"), "w", encoding="utf-8") as fh:
        json.dump({"report_id": report_id, "status": "completed", "failed_sections": [],
                   "partial": False, "created_at": "2026-05-02T08:00:00+00:00"}, fh)
    with open(os.path.join(folder, "full_report.md"), "w", encoding="utf-8") as fh:
        fh.write(markdown)
    forecast_text = json.dumps(forecast, ensure_ascii=False, indent=2)
    with open(os.path.join(folder, "forecast.json"), "w", encoding="utf-8") as fh:
        fh.write(forecast_text)
    audit = {"schema_version": 2,
             "policy_version": int(Config.REPORT_FINAL_AUDIT_POLICY_VERSION),
             "report_id": report_id, "markdown_sha256": _sha(markdown),
             "hard_issues": [] if hard_passed else ["dangling citation markers"],
             "hard_passed": hard_passed,
             "structured_forecast": {"required": True, "present": True, "valid": True},
             "scenario_contract": {"valid": True}, "citation_artifacts": {"required": False},
             "publish_gate": {"enabled": False}, "forecast_sha256": _sha(forecast_text)}
    with open(os.path.join(folder, "final_audit.json"), "w", encoding="utf-8") as fh:
        json.dump(audit, fh)
    return folder


def _commit(forecast, report_id, *, d=None, record_class="production", target_variant=None,
            question=QUESTION, forecast_sha=None, committed_at="2026-05-02T08:00:00+00:00"):
    status, row = fl.commit_published_forecast(
        forecast, report_id=report_id, question=question, language="en",
        as_of_date="2026-05-01", as_of_source="validated",
        publication={"authority": "final_audit", "policy_version": 3,
                     "markdown_sha256": "md", "forecast_sha256": forecast_sha or _sha(report_id)},
        record_class=record_class, d=d, committed_at=committed_at,
        target_variant=target_variant)
    assert status in ("committed", "revision"), status
    return status, row


# ------------------------------------------------------------------ parsing / stamps

def test_parse_stamp_strict_contract():
    assert parse_stamp_strict("2026-07-02").isoformat() == "2026-07-02T00:00:00+00:00"
    assert parse_stamp_strict("2026-07-02T17:30:00+02:00").isoformat() == CLOSED_AT
    assert parse_stamp_strict("2026-07-02 15:30:00+00").isoformat() == CLOSED_AT
    assert parse_stamp_strict("2026-07-02T15:30:00Z").isoformat() == CLOSED_AT
    for bad in ("2026-07-02T15:30:00", "2026", "2026-07", "July 2026", " 2026-07-02",
                "2026-07-02\n", "20260702", "2026-W27-4", "2026-02-30", "\u0662\u0660\u0662\u0666-07-02",
                None, 20260702):
        assert parse_stamp_strict(bad) is None, bad
    assert parse_stamp_strict("2026-07-02", allow_date=False) is None


def test_parse_resolution_closed_time_and_status():
    settled = _resolved("mA", 1.0)
    assert settled["closed_time"] == CLOSED_AT
    assert settled["resolution_status"] == "settled"
    assert _resolved("mA", 1.0, closed_time="2026-07-02 15:30:00+00")["closed_time"] == CLOSED_AT
    # Missing, date-only, naive or free-text closedTime → None; endDate is never used.
    for bad in (None, "2026-07-02", "2026-07-02T15:30:00", "soon"):
        assert _resolved("mA", 1.0, closed_time=bad)["closed_time"] is None, bad
    # 0.5/0.5 with UMA resolved → ambiguous (final, but neither YES nor NO).
    ambiguous = _resolved("mA", 0.5)
    assert ambiguous["resolution_status"] == "ambiguous" and ambiguous["resolved"] is False
    assert _resolved("mA", 0.49)["resolution_status"] == "ambiguous"
    for kwargs in ({"uma": None}, {"uma": "proposed"}, {"uma": "unresolved"},
                   {"closed": False}):
        assert _resolved("mA", 0.5, **kwargs)["resolution_status"] == "unknown", kwargs
    assert _resolved("mA", 0.47)["resolution_status"] == "unknown"
    assert _resolved("mA", 0.6)["resolution_status"] == "unknown"
    # Legacy keys are unchanged.
    assert {k: settled[k] for k in LEGACY_RESOLUTION_KEYS} == {
        "market_id": "mA", "closed": True, "resolved": True, "resolved_outcome": "Yes",
        "resolved_yes_price": 1.0, "uma_status": "resolved"}
    no = _resolved("mB", 0.0)
    assert (no["resolved_outcome"], no["resolved_yes_price"], no["resolution_status"]) == (
        "No", 0.0, "settled")


def test_known_at_basis_and_clamp():
    assert fr.known_at({"closed_time": CLOSED_AT}, PROCESSED) == (CLOSED_AT, "source", False)
    # A close time after processing is impossible for an observed outcome: clamp to processing.
    assert fr.known_at({"closed_time": "2026-10-01T00:00:00+00:00"}, PROCESSED) == (
        PROCESSED, "processing_upper_bound", True)
    assert fr.known_at({"closed_time": None}, PROCESSED) == (
        PROCESSED, "processing_upper_bound", False)
    assert fr.known_at(None, PROCESSED) == (PROCESSED, "processing_upper_bound", False)
    # endDate is a scheduled end, never a known-at time.
    assert fr.known_at({"endDate": "2026-06-30T12:00:00Z"}, PROCESSED)[1] == (
        "processing_upper_bound")
    assert fr.known_at({}, "2026-09-29T14:00:00+02:00")[0] == PROCESSED
    with pytest.raises(ValueError):
        fr.known_at({"closed_time": CLOSED_AT}, "2026-09-29T12:00:00")


# ------------------------------------------------------------------ eligibility

def test_market_eligibility_rules():
    exact = _binary()
    assert fr.market_eligibility(exact, exact["market_anchor"], "exact") == (True, None)
    near = _binary(equivalence="near")
    assert fr.market_eligibility(near, near["market_anchor"], "exact") == (
        False, "equivalence_near")
    assert fr.market_eligibility(near, near["market_anchor"], "near") == (True, None)
    assert fr.market_eligibility(near, near["market_anchor"], "loose") == (True, None)
    # A loose (or missing) equivalence fails completeness first, whatever the floor: 'loose'
    # admits exactly what 'near' does.
    for level in ("loose", None):
        weak = dict(exact["market_anchor"], resolution_equivalence=level)
        assert fr.market_eligibility(exact, weak, "loose") == (False, "anchor_incomplete")
    # An unknown floor acts as the strictest one.
    assert fr.market_eligibility(near, near["market_anchor"], "bogus") == (
        False, "equivalence_near")
    incomplete = dict(exact["market_anchor"])
    incomplete.pop("url")
    assert fr.market_eligibility(exact, incomplete, "exact") == (False, "anchor_incomplete")
    assert fr.market_eligibility(exact, None, "exact") == (False, "anchor_incomplete")
    edited = dict(exact, statement=STATEMENT + " Revised.")
    assert fr.market_eligibility(edited, exact["market_anchor"], "exact") == (
        False, "binding_invalid")
    # Market end within a week of the binary's resolution date is fine; later is a mismatch.
    lag = _binary(end_date="2026-07-07T12:00:00Z")
    assert fr.market_eligibility(lag, lag["market_anchor"], "exact") == (True, None)
    late = _binary(end_date="2026-07-08T00:00:01Z")
    assert fr.market_eligibility(late, late["market_anchor"], "exact") == (
        False, "end_date_mismatch")
    garbled = dict(exact["market_anchor"], endDate="mid 2026")
    assert fr.market_eligibility(exact, garbled, "exact") == (False, "end_date_unverifiable")
    undated = dict(exact, resolution_criteria=CRITERIA.replace("2026-06-30", "mid-year"),
                   statement=STATEMENT.replace("2026-06-30", "mid-year"), horizon_year=None)
    undated["market_anchor"] = _build_market_anchor(
        0.3, {"market_id": "m-1", "question": "q?", "implied_yes_prob": 0.4,
              "url": "https://polymarket.com/event/m-1", "end_date": "2026-06-30T12:00:00Z"},
        equivalence="exact", match_confidence=0.9, binary=undated)
    assert fr.market_eligibility(undated, undated["market_anchor"], "exact") == (
        False, "end_date_unverifiable")

    # The end-date check fails closed: a later date in resolution_source (a publication
    # date) never loosens it, with or without a forecast origin.
    brent = {"id": "B1", "proposition_id": "prop-B1", "probability": 0.2, "horizon_year": 2026,
             "statement": "Brent closes above $100 by 2026-06-30.",
             "resolution_criteria": ("Resolves YES if Brent settles above $100 on any day "
                                     "by 2026-06-30."),
             "resolution_source": "EIA weekly report published 2027-01-10"}
    brent["market_anchor"] = _build_market_anchor(
        0.2, {"market_id": "m-brent", "question": "Brent above $100 in 2026?",
              "implied_yes_prob": 0.3, "url": "https://polymarket.com/event/m-brent",
              "end_date": "2026-12-31T23:59:59Z"},
        equivalence="exact", match_confidence=0.9, binary=brent)
    assert fr.settlement_resolution_date(brent) == "2027-01-10"  # grace waits for the latest
    for origin in (None, "2026-05-01"):
        assert fr.eligibility_deadline(brent, origin) == "2026-06-30"
        assert fr.market_eligibility(brent, brent["market_anchor"], "exact", origin=origin) == (
            False, "end_date_mismatch"), origin
    # 'on <deadline> ... published by <later date>': the deadline is the earliest date on or
    # after the origin, so a market ending near the publication date is a different window.
    cpi = {"id": "C1", "proposition_id": "prop-C1", "probability": 0.4, "horizon_year": 2027,
           "statement": "US CPI inflation is above 3% on 2027-12-31.",
           "resolution_criteria": ("Resolves YES if CPI YoY on 2027-12-31 exceeds 3%, as "
                                   "published by 2028-03-31.")}
    for market_end, expected in (("2028-04-07T00:00:00Z", (False, "end_date_mismatch")),
                                 ("2028-01-05T00:00:00Z", (True, None))):
        cpi["market_anchor"] = _build_market_anchor(
            0.4, {"market_id": "m-cpi", "question": "US CPI above 3% at end of 2027?",
                  "implied_yes_prob": 0.35, "url": "https://polymarket.com/event/m-cpi",
                  "end_date": market_end},
            equivalence="exact", match_confidence=0.9, binary=cpi)
        assert fr.market_eligibility(cpi, cpi["market_anchor"], "exact",
                                     origin="2026-05-01") == expected, market_end
    assert fr.eligibility_deadline(cpi, "2026-05-01") == "2027-12-31"
    assert fr.settlement_resolution_date(cpi) == "2028-03-31"


def test_eligibility_deadline_contract():
    baseline = {"statement": "GDP exceeds its 2024-12-31 level by 2027-06-30.",
                "resolution_source": "Eurostat release 2027-09-15", "horizon_year": 2027}
    # Dates before the origin day are baselines; the origin day itself can be the deadline.
    assert fr.eligibility_deadline(baseline, "2026-05-01") == "2027-06-30"
    assert fr.eligibility_deadline(baseline, "2026-05-02T08:00:00+00:00") == "2027-06-30"
    assert fr.eligibility_deadline(baseline, "2027-06-30") == "2027-06-30"
    # No readable origin: every named date counts, so the check is the strictest one.
    for origin in (None, "", "May 2026", "2026-05-01T08:00:00"):
        assert fr.eligibility_deadline(baseline, origin) == "2024-12-31", origin
    # Every named date before the origin → horizon_year's end; resolution_source is ignored.
    assert fr.eligibility_deadline(baseline, "2027-07-01") == "2027-12-31"
    assert fr.eligibility_deadline({"resolution_source": "release 2026-09-30",
                                    "horizon_year": 2026}) == "2026-12-31"
    assert fr.eligibility_deadline({"statement": "someday"}) is None
    assert fr.eligibility_deadline(None) is None
    # An unreadable horizon_year never raises (the sweep computes due items outside its try).
    assert fr.settlement_resolution_date({"statement": "someday", "horizon_year": "inf"}) is None
    assert fr.eligibility_deadline({"statement": "someday", "horizon_year": 1e400}) is None


def test_settlement_resolution_date_is_the_latest_named_date():
    """A baseline date named before the deadline never triggers a premature terminal or an
    end-date mismatch (both are append-only facts)."""
    baseline = {"id": "G1", "proposition_id": "prop-G1", "probability": 0.6,
                "statement": "Euro-area GDP exceeds its 2024-12-31 level by 2027-06-30.",
                "resolution_criteria": ("Resolves YES if Eurostat GDP exceeds the 2024-12-31 "
                                        "level by 2027-06-30."),
                "horizon_year": 2027}
    assert fl.binary_resolution_date(baseline) == "2024-12-31"  # first date: the baseline
    assert fr.settlement_resolution_date(baseline) == "2027-06-30"
    # Invalid calendar dates are ignored; no date at all falls back to horizon_year's end.
    assert fr.settlement_resolution_date(
        {"resolution_criteria": "by 2026-02-30", "horizon_year": 2027}) == "2027-12-31"
    assert fr.settlement_resolution_date(
        {"statement": "by 2026-03-01", "resolution_source": "2026-09-30 release"}) == "2026-09-30"
    assert fr.settlement_resolution_date({"statement": "someday"}) is None
    assert fr.settlement_resolution_date(None) is None

    # Unanchored: no terminal before 2027-06-30 + grace (processing day 2026-09-29 is far off).
    early = fr.settle_binaries("r1", [baseline], {}, processed_at=PROCESSED, grace_days=180)
    assert early["terminal"] == [] and early["pending_by_reason"] == {"no_market_anchor": 1}
    boundary = fr.settle_binaries("r1", [baseline], {}, processed_at="2027-12-27T12:00:00+00:00",
                                  grace_days=180)
    assert boundary["terminal"] == []
    late = fr.settle_binaries("r1", [baseline], {}, processed_at="2027-12-28T12:00:00+00:00",
                              grace_days=180)
    assert [t["evidence"]["resolution_date"] for t in late["terminal"]] == ["2027-06-30"]

    # Exact anchor whose market ends on the real deadline: eligible once the forecast origin
    # shows the first date is a baseline; without an origin the check fails closed.
    anchored = dict(baseline)
    anchored["market_anchor"] = _build_market_anchor(
        0.6, {"market_id": "m-gdp", "question": "Euro-area GDP above end-2024 by June 2027?",
              "implied_yes_prob": 0.55, "url": "https://polymarket.com/event/m-gdp",
              "end_date": "2027-06-30T12:00:00Z"},
        equivalence="exact", match_confidence=0.9, binary=anchored)
    assert fr.market_eligibility(anchored, anchored["market_anchor"], "exact",
                                 origin=META["as_of"]) == (True, None)
    assert fr.market_eligibility(anchored, anchored["market_anchor"], "exact") == (
        False, "end_date_mismatch")
    no_as_of = fr.settle_binaries(
        "r1", [anchored],
        {"m-gdp": _resolved("m-gdp", 1.0, closed_time="2027-07-01T09:00:00Z")},
        target_meta=dict(META, as_of=None), processed_at="2027-07-02T00:00:00+00:00")
    assert no_as_of["events"][0]["ineligible_reason"] is None  # created_at is the origin
    open_market = fr.settle_binaries(
        "r1", [anchored], {"m-gdp": _resolved("m-gdp", 0.55, closed=False, uma=None)},
        target_meta=META, processed_at=PROCESSED)
    assert open_market["terminal"] == [] and open_market["pending_by_reason"] == {
        "market_open": 1}
    settled = fr.settle_binaries(
        "r1", [anchored],
        {"m-gdp": _resolved("m-gdp", 1.0, closed_time="2027-07-01T09:00:00Z")},
        target_meta=META, processed_at="2027-07-02T00:00:00+00:00")["events"][0]
    assert (settled["scoring_eligible"], settled["ineligible_reason"]) == (True, None)


# ------------------------------------------------------------------ prospective proof

def test_prospective_requires_lower_bound_proof():
    anchor = _binary()["market_anchor"]  # price 0.40, market end 2026-06-30
    as_of, created = META["as_of"], META["created_at"]
    upper = "processing_upper_bound"
    assert fr.prospective_status(PROCESSED, upper, as_of, created, anchor) is True
    # A near-settled research price proves nothing about the lower side.
    assert fr.prospective_status(
        PROCESSED, upper, as_of, created, dict(anchor, price_at_research=0.995)) == "unknown"
    assert fr.prospective_status(
        PROCESSED, upper, as_of, created, dict(anchor, price_at_research=0.01)) == "unknown"
    assert fr.prospective_status(
        PROCESSED, upper, as_of, created, dict(anchor, endDate="2026-04-30T00:00:00Z")) == (
        "unknown")
    assert fr.prospective_status(PROCESSED, upper, as_of, created, None) == "unknown"
    assert fr.prospective_status(CLOSED_AT, "source", as_of, created, anchor) is True
    # Replay run after the outcome: as_of in the past, created after known_at → False.
    assert fr.prospective_status(CLOSED_AT, "source", "2026-03-01",
                                 "2026-09-01T00:00:00+00:00", anchor) is False
    # Same-day known-at is not prospective (the whole as-of day is the origin).
    assert fr.prospective_status("2026-05-01T23:00:00+00:00", "attested", "2026-05-01",
                                 None, anchor) is False
    assert fr.prospective_status("2026-05-02T00:00:00+00:00", "attested", "2026-05-01",
                                 None, anchor) is True
    # No origin at all, or an unreadable one, proves nothing.
    assert fr.prospective_status(CLOSED_AT, "source", None, None, anchor) == "unknown"
    assert fr.prospective_status(CLOSED_AT, "source", "May 2026", None, anchor) == "unknown"
    assert fr.prospective_status(CLOSED_AT, "source", as_of, "yesterday", anchor) == "unknown"
    # A stamp with no representable end of day is unreadable, never an OverflowError.
    assert fr.prospective_status(CLOSED_AT, "source", "9999-12-31", None, {}) == "unknown"
    assert fr.prospective_status(CLOSED_AT, "source", None, "9999-12-31", {}) == "unknown"
    far = fr.settle_binaries("r1", [_binary()], {"m-1": _resolved("m-1", 1.0)},
                             target_meta={"as_of": "9999-12-31"}, processed_at=PROCESSED)
    assert far["events"][0]["ineligible_reason"] == "prospective_unknown"

    # scoring_eligible only when prospective is True.
    resolutions = {"m-1": _resolved("m-1", 1.0)}

    def settle(meta):
        return fr.settle_binaries("r1", [_binary()], resolutions, target_meta=meta,
                                  processed_at=PROCESSED)["events"][0]

    ok = settle(META)
    assert (ok["prospective"], ok["scoring_eligible"], ok["ineligible_reason"]) == (
        True, True, None)
    replay = settle({"as_of": "2026-03-01", "created_at": "2026-09-01T00:00:00+00:00"})
    assert (replay["prospective"], replay["scoring_eligible"], replay["ineligible_reason"]) == (
        False, False, "not_prospective")
    blind = settle({})
    assert (blind["prospective"], blind["scoring_eligible"], blind["ineligible_reason"]) == (
        "unknown", False, "prospective_unknown")


# ------------------------------------------------------------------ settle_binaries

def test_settled_event_carries_every_v2_field():
    out = fr.settle_binaries("r1", [_binary()], {"m-1": _resolved("m-1", 1.0)},
                             target_meta=META, processed_at=PROCESSED)
    assert out["terminal"] == [] and out["pending_by_reason"] == {}
    event = out["events"][0]
    assert V2_EVENT_KEYS <= set(event)
    assert event["schema_version"] == 2 and event["item_kind"] == "binary"
    assert event["source_kind"] == "polymarket" and event["resolution_status"] == "settled"
    assert (event["outcome"], event["y"], event["resolved_outcome"]) == ("YES", 1, "Yes")
    assert event["brier_contribution"] == round((0.30 - 1) ** 2, 4)
    assert event["model_p"] == 0.30 and event["market_p_at_research"] == 0.40
    assert (event["outcome_known_at"], event["known_at_basis"], event["known_at_clamped"]) == (
        CLOSED_AT, "source", False)
    assert event["processed_at"] == PROCESSED and event["resolved_at"] == PROCESSED
    assert event["report_publishable_at_issue"] is True and event["target_commit_id"] == "c-1"
    assert event["evidence"] == {"market_url": "https://polymarket.com/event/m-1",
                                 "uma_status": "resolved", "closed_time": CLOSED_AT}
    assert event["terminal_reason"] is None
    json.dumps(event, allow_nan=False)
    no = fr.settle_binaries("r1", [_binary()], {"m-1": _resolved("m-1", 0.0)},
                            target_meta=META, processed_at=PROCESSED)["events"][0]
    assert (no["outcome"], no["y"], no["brier_contribution"]) == ("NO", 0, 0.09)
    with pytest.raises(ValueError):
        fr.settle_binaries("r1", [], {}, processed_at="2026-09-29")


def test_pending_reasons_and_grace_terminal():
    binaries = [
        _binary("F1", market_id="m-open"), _binary("F2", market_id="m-unconverged"),
        _binary("F3", market_id="m-proposed"), _binary("F4", market_id="m-disputed"),
        _binary("F5", market_id="m-missing"),
        {"id": "F6", "statement": "Unanchored event by 2025-01-01", "probability": 0.5,
         "resolution_criteria": "by 2025-01-01"},
        {"id": "F7", "statement": "Unanchored event, inside grace", "probability": 0.5,
         "resolution_criteria": "by 2026-06-01"},
        {"statement": "no id", "probability": 0.5},
    ]
    resolutions = {
        "m-open": _resolved("m-open", 0.4, closed=False, uma=None),
        "m-unconverged": _resolved("m-unconverged", 0.6, uma=None),
        "m-proposed": _resolved("m-proposed", 1.0, uma="proposed"),
        "m-disputed": _resolved("m-disputed", 0.0, uma="disputed"),
    }
    out = fr.settle_binaries("r1", binaries, resolutions, target_meta=META,
                             processed_at=PROCESSED, grace_days=180)
    assert out["events"] == []
    assert out["pending_by_reason"] == {
        "market_open": 1, "missing_forecast_id": 1, "no_market_anchor": 1,
        "no_resolution_data": 1, "not_converged": 1, "uma_pending": 2}
    # Only the unanchored F6 (2025-01-01 + 180 days < 2026-09-29) is past its grace period.
    assert len(out["terminal"]) == 1
    terminal = out["terminal"][0]
    assert (terminal["forecast_id"], terminal["market_id"], terminal["source_kind"]) == (
        "F6", "terminal", "terminal")
    assert terminal["terminal_reason"] == "unresolvable_after_grace"
    assert terminal["scoring_eligible"] is False and terminal["outcome_known_at"] is None
    assert terminal["evidence"]["resolution_date"] == "2025-01-01"
    assert V2_EVENT_KEYS <= set(terminal)

    # Grace boundary is strict: date + grace == processing day is still inside grace.
    boundary = fr.settle_binaries("r1", [binaries[5]], {}, processed_at="2025-06-30T12:00:00+00:00",
                                  grace_days=180)
    assert boundary["terminal"] == [] and boundary["pending_by_reason"] == {
        "no_market_anchor": 1}
    # Long after the markets' dates: anchored items with live data turn terminal too, but an
    # item with no data only when the source answered for ITS market (confirmed missing).
    late = "2027-12-31T00:00:00+00:00"
    after = fr.settle_binaries("r1", binaries[:5], resolutions, processed_at=late,
                               grace_days=180, answered_market_ids=[*resolutions, "m-missing"])
    assert sorted(t["forecast_id"] for t in after["terminal"]) == ["F1", "F2", "F3", "F4", "F5"]
    assert after["terminal"][0]["evidence"]["anchor_market_id"] == "m-open"
    # Its request batch failed (not answered), or no answered set at all: F5 stays pending
    # although the source answered for the other markets.
    for answered in (list(resolutions), None):
        failed = fr.settle_binaries("r1", binaries[:5], resolutions, processed_at=late,
                                    grace_days=180, answered_market_ids=answered)
        assert sorted(t["forecast_id"] for t in failed["terminal"]) == ["F1", "F2", "F3", "F4"]
        assert failed["pending_by_reason"] == {"no_resolution_data": 1}
    unreachable = fr.settle_binaries("r1", [binaries[4]], {}, processed_at=late,
                                     grace_days=180)
    assert unreachable["terminal"] == [] and unreachable["pending_by_reason"] == {
        "no_resolution_data": 1}
    # An item that already holds a market event never gets a terminal one.
    prior = [{"report_id": "r1", "forecast_id": "F1", "market_id": "m-open",
              "source_kind": "polymarket"},
             {"report_id": "r1", "forecast_id": "F2", "market_id": "terminal",
              "source_kind": "terminal"},
             {"report_id": "other", "forecast_id": "F3", "market_id": "m-proposed"}]
    kept = fr.settle_binaries("r1", binaries[:3], resolutions, processed_at=late,
                              grace_days=180, existing_events=prior)
    assert sorted(t["forecast_id"] for t in kept["terminal"]) == ["F2", "F3"]
    assert kept["pending_by_reason"] == {"market_open": 1}


def test_uma_status_history_uses_current_stage():
    """``umaResolutionStatuses`` is a history: its last entry is the current stage."""
    assert pm.current_uma_status('["proposed","resolved"]') == "resolved"
    assert pm.current_uma_status(["proposed", "Disputed"]) == "disputed"
    assert pm.current_uma_status("Proposed") == "proposed"
    assert pm.current_uma_status("[]") == "" and pm.current_uma_status(None) == ""
    assert pm.current_uma_status("[not json") == "[not json"

    def history(market_id, yes, stages):
        raw = _gamma(market_id, yes, uma=None)
        raw["umaResolutionStatuses"] = json.dumps(stages)
        return pm._parse_resolution(raw)

    resolved = history("m-1", 1.0, ["proposed", "resolved"])
    assert resolved["uma_status"] == '["proposed", "resolved"]'  # passthrough unchanged
    assert resolved["resolution_status"] == "settled"
    event = fr.settle_binaries("r1", [_binary()], {"m-1": resolved}, target_meta=META,
                               processed_at=PROCESSED)["events"]
    assert [(e["resolution_status"], e["scoring_eligible"]) for e in event] == [("settled", True)]
    # A proposal or dispute that is still the current stage keeps the item pending.
    for stages in (["proposed"], ["proposed", "resolved", "disputed"]):
        out = fr.settle_binaries("r1", [_binary()], {"m-1": history("m-1", 1.0, stages)},
                                 target_meta=META, processed_at=PROCESSED)
        assert out["events"] == [] and out["pending_by_reason"] == {"uma_pending": 1}, stages
    # A 50/50 settlement whose history ends 'resolved' is ambiguous; one still proposed is not.
    assert history("m-1", 0.5, ["proposed", "resolved"])["resolution_status"] == "ambiguous"
    assert history("m-1", 0.5, ["resolved", "proposed"])["resolution_status"] == "unknown"

    # A history Gamma sends as a real JSON array keeps its JSON form, never a Python repr
    # ("['proposed', 'resolved']" would read as a pending proposal until the grace terminal).
    def listed(yes, stages):
        raw = _gamma("m-1", yes, uma=None)
        raw["umaResolutionStatuses"] = stages
        return pm._parse_resolution(raw)

    for stages in (["proposed", "resolved"], ("proposed", "resolved")):
        parsed = listed(1.0, stages)
        assert parsed["uma_status"] == '["proposed", "resolved"]', stages
        assert pm.current_uma_status(parsed["uma_status"]) == "resolved"
        assert parsed["resolution_status"] == "settled"
        out = fr.settle_binaries("r1", [_binary()], {"m-1": parsed}, target_meta=META,
                                 processed_at=PROCESSED)
        assert [e["scoring_eligible"] for e in out["events"]] == [True], stages
    assert listed(0.5, ["proposed", "resolved"])["resolution_status"] == "ambiguous"
    assert listed(1.0, ["proposed"])["uma_status"] == '["proposed"]'
    assert listed(1.0, [])["uma_status"] == "[]"


def test_ambiguous_settlement_event_not_scored(tmp_path):
    out = fr.settle_binaries("r1", [_binary()], {"m-1": _resolved("m-1", 0.5)},
                             target_meta=META, processed_at=PROCESSED)
    event = out["events"][0]
    assert event["resolution_status"] == "ambiguous"
    assert (event["outcome"], event["y"], event["brier_contribution"],
            event["resolved_outcome"]) == (None, None, None, None)
    assert event["scoring_eligible"] is False
    assert event["ineligible_reason"] == "ambiguous_settlement"
    assert out["ineligible_by_reason"] == {"ambiguous_settlement": 1}
    assert out["terminal"] == [] and out["pending_by_reason"] == {}
    d = str(tmp_path)
    assert mon._append_event(event, d) is not None
    assert fl.market_brier_summary(d) == {"n_resolved": 0, "mean_brier": None}
    # A later run long after the grace period never adds a terminal on top of it.
    again = fr.settle_binaries("r1", [_binary()], {}, processed_at="2028-01-01T00:00:00+00:00",
                               existing_events=fl.read_market_resolutions(d))
    assert again["terminal"] == []


def test_near_anchor_and_uma_never_scoring_eligible():
    near = _binary(equivalence="near")
    out = fr.settle_binaries("r1", [near], {"m-1": _resolved("m-1", 1.0)},
                             target_meta=META, processed_at=PROCESSED,
                             min_equivalence="exact")
    assert out["events"][0]["scoring_eligible"] is False
    assert out["ineligible_by_reason"] == {"equivalence_near": 1}
    legacy = {"m-1": {"market_id": "m-1", "resolved": True, "resolved_outcome": "Yes",
                      "resolved_yes_price": 1.0}}
    # Legacy-shaped resolution dicts (no closed/resolution_status) still settle.
    assert fr.settle_binaries("r1", [_binary()], legacy, target_meta=META,
                              processed_at=PROCESSED)["events"][0]["resolution_status"] == (
        "settled")
    no_yes = {"m-1": pm._parse_resolution({"id": "m-1", "closed": True,
                                          "outcomes": '["Trump","Harris"]',
                                          "outcomePrices": '["1","0"]',
                                          "umaResolutionStatus": "resolved"})}
    assert fr.settle_binaries("r1", [_binary()], no_yes, target_meta=META,
                              processed_at=PROCESSED)["pending_by_reason"] == {
        "no_yes_outcome": 1}


# ------------------------------------------------------------------ ledger

def test_append_market_resolution_extra_is_additive(tmp_path):
    d = str(tmp_path)
    base = {"forecast_id": "F1", "resolved_outcome": "Yes", "model_p": 0.3,
            "market_p_at_research": 0.4, "brier_contribution": 0.49,
            "resolved_at": "2026-01-01T00:00:00", "resolved_yes_price": 1.0, "d": d}
    legacy = fl.append_market_resolution(report_id="r1", market_id="m1", **base)
    assert set(legacy) == {"report_id", "forecast_id", "market_id", "resolved_outcome",
                           "resolved_yes_price", "model_p", "market_p_at_research",
                           "brier_contribution", "resolved_at", "schema_version"}
    assert legacy["schema_version"] == 1
    assert fl.append_market_resolution(report_id="r1", market_id="m1", extra={},
                                       **base) is None  # same key: idempotent
    v2 = fl.append_market_resolution(
        report_id="r1", market_id="m2",
        extra={"report_id": "hijack", "schema_version": 7, "outcome": "YES"}, **base)
    assert v2["report_id"] == "r1" and v2["schema_version"] == 2 and v2["outcome"] == "YES"
    assert fl.append_market_resolution(report_id="r1", market_id="m3",
                                       extra={"y": math.nan}, **base) is None
    rows = fl.read_market_resolutions(d)
    assert [r["market_id"] for r in rows] == ["m1", "m2"]
    assert fl.append_market_resolution(report_id="r1", market_id="m2",
                                       extra={"outcome": "NO"}, **base) is None


def test_market_brier_summary_ignores_terminal_and_ambiguous(tmp_path):
    d = str(tmp_path)

    def add(market_id, brier, extra=None):
        fl.append_market_resolution(report_id="r", forecast_id=market_id, market_id=market_id,
                                    resolved_outcome=None, model_p=0.3,
                                    market_p_at_research=0.4, brier_contribution=brier,
                                    resolved_at="t", d=d, extra=extra)

    add("legacy", 0.49)
    add("settled", 0.04, {"source_kind": "polymarket", "resolution_status": "settled"})
    add("terminal", 0.25, {"source_kind": "terminal", "resolution_status": "terminal"})
    add("ambiguous", 0.25, {"source_kind": "polymarket", "resolution_status": "ambiguous"})
    add("manual", 0.25, {"source_kind": "manual", "resolution_status": "settled"})
    assert len(fl.read_market_resolutions(d)) == 5
    assert fl.market_brier_summary(d) == {"n_resolved": 2,
                                          "mean_brier": round((0.49 + 0.04) / 2, 4)}


# ------------------------------------------------------------------ publication gate

def test_publishable_at_issue_ignores_stale_policy(reports_dir, monkeypatch, tmp_path):
    forecast = _forecast([_binary()])
    _write_sealed_report("r-pub", forecast)
    assert ReportManager.publication_status("r-pub")["publishable"] is True
    at_issue = ReportManager.publishable_at_issue("r-pub")
    assert at_issue["publishable"] is True and at_issue["stale_policy_ignored"] is False

    monkeypatch.setattr(Config, "REPORT_FINAL_AUDIT_POLICY_VERSION",
                        int(Config.REPORT_FINAL_AUDIT_POLICY_VERSION) + 1)
    status = ReportManager.publication_status("r-pub")
    assert status["publishable"] is False
    assert status["reasons"] == [FINAL_AUDIT_STALE_POLICY_REASON]
    at_issue = ReportManager.publishable_at_issue("r-pub")
    assert at_issue["publishable"] is True and at_issue["stale_policy_ignored"] is True
    assert at_issue["reasons"] == []
    assert ReportManager.load_structured_forecast("r-pub") is None
    assert ReportManager.load_structured_forecast("r-pub", allow_stale_policy=True) == forecast

    # The settled history stays eligible after the bump (default gate, sealed forecast).
    led = str(tmp_path / "ledger")
    _, row = _commit(forecast, "r-pub", d=led)
    client = _Client({"m-1": _resolved("m-1", 1.0)})
    res = mon.run_monitor("r-pub", client=client, ledger_dir=led, as_of=PROCESSED)
    assert "skipped" not in res and res["resolved_count"] == 1
    event = fl.read_market_resolutions(led)[0]
    assert event["scoring_eligible"] is True and event["target_commit_id"] == row["commit_id"]

    # Any other reason still blocks.
    _write_sealed_report("r-bad", forecast, hard_passed=False)
    blocked = ReportManager.publishable_at_issue("r-bad")
    assert blocked["publishable"] is False and "final audit did not hard-pass" in blocked["reasons"]


def test_monitor_refuses_unpublishable_and_unsealed(reports_dir, tmp_path):
    led = str(tmp_path / "ledger")
    folder = str(tmp_path / "report")
    forecast = _forecast([_binary()])
    client = _Client({"m-1": _resolved("m-1", 1.0)})

    def assert_nothing_written(res, reason):
        assert res["skipped"] == reason
        assert res["resolved_count"] == 0 and res["newly_recorded_count"] == 0
        assert fl.read_market_resolutions(led) == []
        assert client.calls == []
        assert not os.path.exists(folder)

    assert_nothing_written(mon.run_monitor(
        "r1", forecast=forecast, report_folder=folder, client=client, ledger_dir=led,
        as_of=PROCESSED, publishable_fn=lambda rid: False), "not_publishable")

    def boom(rid):
        raise RuntimeError("status unavailable")

    assert_nothing_written(mon.run_monitor(
        "r1", forecast=forecast, report_folder=folder, client=client, ledger_dir=led,
        as_of=PROCESSED, publishable_fn=boom), "not_publishable")
    # Default gate: a report that is not on disk is not publishable.
    assert_nothing_written(mon.run_monitor(
        "r-missing", forecast=forecast, report_folder=folder, client=client, ledger_dir=led,
        as_of=PROCESSED), "not_publishable")
    # Publishable, but its forecast.json is not the audit-sealed one → not_sealed.
    sealed = _write_sealed_report("r-unsealed", forecast)
    with open(os.path.join(sealed, "forecast.json"), "a", encoding="utf-8") as fh:
        fh.write("\n")
    assert_nothing_written(mon.run_monitor(
        "r-unsealed", report_folder=folder, client=client, ledger_dir=led, as_of=PROCESSED,
        publishable_fn=lambda rid: True), "not_sealed")
    row = mon._summary_row(mon.run_monitor(
        "r1", forecast=forecast, report_folder=folder, client=client, ledger_dir=led,
        as_of=PROCESSED, publishable_fn=lambda rid: False))
    assert row == {"report_id": "r1", "skipped": "not_publishable"}


# ------------------------------------------------------------------ monitor run

def test_run_monitor_reports_settlement_counters(tmp_path):
    led = str(tmp_path / "ledger")
    folder = str(tmp_path / "report")
    forecast = _forecast([
        _binary("F1"),
        _binary("F2", market_id="m-near", equivalence="near"),
        _binary("F3", market_id="m-open"),
        {"id": "F4", "statement": "Unanchored by 2025-01-01", "probability": 0.5,
         "resolution_criteria": "by 2025-01-01"},
    ])
    client = _Client({"m-1": _resolved("m-1", 1.0), "m-near": _resolved("m-near", 0.0),
                      "m-open": _resolved("m-open", 0.4, closed=False, uma=None)})
    res = mon.run_monitor("r1", forecast=forecast, report_folder=folder, client=client,
                          ledger_dir=led, as_of="2026-09-29T12:00:00",
                          publishable_fn=lambda rid: True, target_meta=META)
    assert res["processed_at"] == PROCESSED
    assert res["resolved_count"] == 2 and res["newly_recorded_count"] == 2
    assert res["terminal_count"] == 1 and res["newly_terminal_count"] == 1
    assert res["settlement"] == {
        "settled": 2, "settled_eligible": 1, "ambiguous": 0, "terminal": 1,
        "pending_by_reason": {"market_open": 1},
        "ineligible_by_reason": {"equivalence_near": 1}, "appended": 3}
    assert {r["forecast_id"] for r in res["resolution_records"]} == {"F1", "F2"}
    rows = fl.read_market_resolutions(led)
    assert len(rows) == 3 and all(r["schema_version"] == 2 for r in rows)
    assert fl.market_brier_summary(led)["n_resolved"] == 2
    md = open(os.path.join(folder, "monitor_report.md"), encoding="utf-8").read()
    assert md == res["monitor_report_md"]
    assert "## Settlement" in md
    assert "- Pending by reason: market_open 1" in md
    assert "- Ineligible by reason: equivalence_near 1" in md
    assert "unresolvable_after_grace" in md and f"{CLOSED_AT} (source)" in md
    summary = mon._summary_row(res)
    assert summary["settled_eligible"] == 1 and summary["terminal"] == 1
    assert summary["pending_by_reason"] == {"market_open": 1}
    # Re-run: every event hits its idempotency key.
    again = mon.run_monitor("r1", forecast=forecast, report_folder=folder, client=client,
                            ledger_dir=led, as_of="2026-09-30T12:00:00+00:00",
                            publishable_fn=lambda rid: True, target_meta=META)
    assert again["newly_recorded_count"] == 0 and again["newly_terminal_count"] == 0
    assert again["settlement"]["appended"] == 0
    assert len(fl.read_market_resolutions(led)) == 3


def test_target_meta_from_commit_row_else_meta_json(tmp_path):
    led = str(tmp_path / "ledger")
    folder = tmp_path / "report"
    folder.mkdir()
    (folder / "meta.json").write_text(json.dumps({"created_at": "2026-05-02T10:00:00+02:00"}),
                                      encoding="utf-8")
    assert mon.target_meta_for("r1", ledger_dir=led, report_folder=str(folder)) == {
        "as_of": None, "created_at": "2026-05-02T08:00:00+00:00", "commit_id": None,
        "production_primary": None}
    assert mon.target_meta_for("r1", ledger_dir=led, report_folder=None) == {
        "as_of": None, "created_at": None, "commit_id": None, "production_primary": None}
    # A legacy schema_version 1 production row proves nothing: meta.json as before.
    assert fl.append_forecast(_forecast([_binary()]), report_id="r1", d=led) is not None
    assert mon.target_meta_for("r1", ledger_dir=led, report_folder=str(folder))[
        "production_primary"] is None
    _, row = _commit(_forecast([_binary()]), "r1", d=led)
    primary_meta = {"as_of": "2026-05-01", "created_at": "2026-05-02T08:00:00+00:00",
                    "commit_id": row["commit_id"], "production_primary": True}
    assert mon.target_meta_for("r1", ledger_dir=led, report_folder=str(folder)) == primary_meta
    # Given the binaries to settle, only the commit that pre-registered exactly them counts.
    assert mon.target_meta_for("r1", ledger_dir=led, report_folder=str(folder),
                               binaries=_forecast([_binary()])["binary_forecasts"]) == (
        primary_meta)
    for other in ([_binary(probability=0.45)], [_binary(), _binary("F2", market_id="m-2")], [],
                  [dict(_binary(), probability=float("nan"))]):
        assert mon.target_meta_for("r1", ledger_dir=led, report_folder=str(folder),
                                   binaries=other) == {
            "as_of": None, "created_at": None, "commit_id": None,
            "production_primary": False}, other
    assert mon._local_stamp_to_utc("not a date") is None
    assert mon._local_stamp_to_utc(None) is None


def test_non_production_targets_never_record_settlement(reports_dir):
    """Ensemble, revision and evaluation reports settle in memory but write nothing (I-21)."""
    client = _Client({mid: _resolved(mid, 1.0) for mid in ("m-1", "m-rev", "m-ens", "m-eval")})
    reports = {
        "r-prod": _forecast([_binary()]),
        "r-rev": _forecast([_binary(market_id="m-rev")]),
        "r-ens": _forecast([_binary(market_id="m-ens")]),
        "r-eval": _forecast([_binary(market_id="m-eval")]),
    }
    for rid, forecast in reports.items():
        _write_sealed_report(rid, forecast)
    _, primary = _commit(reports["r-prod"], "r-prod")
    status, revision = _commit(reports["r-rev"], "r-rev")  # same question + as-of → revision
    assert status == "revision"
    _, ensemble = _commit(reports["r-ens"], "r-ens", record_class="ensemble_member",
                          target_variant={"seed": 2})
    _, evaluation = _commit(reports["r-eval"], "r-eval", record_class="evaluation")
    # Ensemble members are primaries of their own target in the PRODUCTION ledger file;
    # evaluation commits are redirected to the evaluation ledger.
    assert ensemble["calibration_role"] == "primary"
    assert all(r.get("report_id") != "r-eval" for r in fl.read_ledger())
    assert [r["report_id"] for r in fl.read_ledger(fl.evaluation_ledger_dir())] == ["r-eval"]

    for rid, row in (("r-rev", revision), ("r-ens", ensemble), ("r-eval", evaluation)):
        meta = mon.target_meta_for(rid, report_folder=ReportManager._get_report_folder(rid))
        assert meta == {"as_of": "2026-05-01", "created_at": "2026-05-02T08:00:00+00:00",
                        "commit_id": row["commit_id"], "production_primary": False}, rid
        res = mon.run_monitor(rid, client=client, as_of=PROCESSED)
        assert "skipped" not in res, rid
        assert res["settlement"]["not_recorded"] == "not_production_primary"
        assert res["settlement"]["settled_eligible"] == 0 and res["settlement"]["appended"] == 0
        assert res["settlement"]["ineligible_by_reason"] == {"not_production_primary": 1}
        assert res["newly_recorded_count"] == 0 and res["newly_terminal_count"] == 0
        assert "- Not recorded in resolutions.jsonl: not_production_primary" in (
            res["monitor_report_md"])
        assert fl.read_market_resolutions() == [], rid
    # An unpublished-terminal row alone also marks the report as no production primary.
    assert fl.record_unpublished_terminal(report_id="r-unpub", question_sha256=None,
                                          record_class="production", run_ref=None,
                                          reasons=["audit failed"])[0] == "recorded"
    assert mon.target_meta_for("r-unpub")["production_primary"] is False

    # The production primary itself still records one scoring-eligible event, and the
    # running market Brier counts only it.
    res = mon.run_monitor("r-prod", client=client, as_of=PROCESSED)
    assert "not_recorded" not in res["settlement"] and res["newly_recorded_count"] == 1
    rows = fl.read_market_resolutions()
    assert [(r["report_id"], r["scoring_eligible"], r["target_commit_id"]) for r in rows] == [
        ("r-prod", True, primary["commit_id"])]
    assert fl.market_brier_summary()["n_resolved"] == 1
    # The pure decision marks every market event of a non-production target, even eligible ones.
    blocked = fr.settle_binaries("r-ens", [_binary()], {"m-1": _resolved("m-1", 1.0)},
                                 target_meta=dict(META, production_primary=False),
                                 processed_at=PROCESSED)["events"][0]
    assert (blocked["scoring_eligible"], blocked["ineligible_reason"]) == (
        False, "not_production_primary")


def test_run_monitor_settles_only_the_registered_binaries(reports_dir):
    """A later publication under the same report id is never scored under the primary's
    commit: run_monitor records nothing for it, while the sweep settles the primary's own
    pre-registered binaries."""
    registered = _forecast([_binary(probability=0.30)])
    _, primary = _commit(registered, "r-rep")
    _write_sealed_report("r-rep", _forecast([_binary(probability=0.45)]))
    client = _Client({"m-1": _resolved("m-1", 1.0)})
    res = mon.run_monitor("r-rep", client=client, as_of=PROCESSED)
    assert "skipped" not in res
    assert res["settlement"]["not_recorded"] == "not_production_primary"
    assert res["newly_recorded_count"] == 0 and fl.read_market_resolutions() == []
    assert mon.settle_ledger(client=client, as_of=PROCESSED)["appended"] == 1
    (event,) = fl.read_market_resolutions()
    assert (event["model_p"], event["target_commit_id"], event["scoring_eligible"]) == (
        0.30, primary["commit_id"], True)
    # With the registered bytes sealed on disk, run_monitor agrees with the sweep.
    _write_sealed_report("r-rep", registered)
    again = mon.run_monitor("r-rep", client=client, as_of=PROCESSED)
    assert "not_recorded" not in again["settlement"] and again["settlement"]["appended"] == 0
    assert [(r["model_p"], r["target_commit_id"]) for r in again["resolution_records"]] == [
        (0.30, primary["commit_id"])]


def test_normalize_processed_at():
    assert mon.normalize_processed_at("2026-07-07T00:00:00") == "2026-07-07T00:00:00+00:00"
    assert mon.normalize_processed_at("2026-07-07") == "2026-07-07T00:00:00+00:00"
    assert mon.normalize_processed_at("2026-07-07T02:00:00+02:00") == (
        "2026-07-07T00:00:00+00:00")
    for bad in ("yesterday", "2026", None):
        with pytest.raises(ValueError):
            mon.normalize_processed_at(bad)


# ------------------------------------------------------------------ settle sweep

def test_settle_sweep_over_v2_rows(monkeypatch, capsys, tmp_path):
    client = _Client({"m-1": _resolved("m-1", 1.0), "m-ens": _resolved("m-ens", 1.0),
                      "m-rev": _resolved("m-rev", 1.0), "m-eval": _resolved("m-eval", 1.0)})
    monkeypatch.setattr(pm, "PolymarketClient", lambda: client)
    monkeypatch.setattr(mon, "_utcnow_iso", lambda: PROCESSED)
    _, primary = _commit(_forecast([_binary()]), "r-prod")
    # A revision of the same target, an ensemble member and an evaluation row: never swept.
    status, _ = _commit(_forecast([_binary(market_id="m-rev")]), "r-rev")
    assert status == "revision"
    _commit(_forecast([_binary(market_id="m-ens")]), "r-ens", record_class="ensemble_member",
            target_variant={"seed": 2})
    _commit(_forecast([_binary(market_id="m-eval")]), "r-eval", record_class="evaluation")

    def run(*argv):
        assert mon.main(["settle", *argv]) == 0
        return _json_out(capsys)

    dry = run("--dry-run")
    assert dry["dry_run"] is True and dry["targets"] == 1
    assert dry["settled"] == 1 and dry["settled_eligible"] == 1 and dry["appended"] == 0
    assert fl.read_market_resolutions() == []
    assert client.calls == [("resolutions", ["m-1"])]

    first = run()
    assert first["targets"] == 1 and first["appended"] == 1
    assert {k: first[k] for k in ("settled_eligible", "terminal", "ambiguous",
                                  "pending_by_reason", "ineligible_by_reason")} == {
        "settled_eligible": 1, "terminal": 0, "ambiguous": 0, "pending_by_reason": {},
        "ineligible_by_reason": {}}
    rows = fl.read_market_resolutions()
    assert len(rows) == 1
    event = rows[0]
    assert event["schema_version"] == 2 and event["item_kind"] == "binary"
    assert event["report_id"] == "r-prod" and event["target_commit_id"] == primary["commit_id"]
    assert (event["outcome_known_at"], event["known_at_basis"]) == (CLOSED_AT, "source")
    assert event["prospective"] is True and event["scoring_eligible"] is True

    assert run()["appended"] == 0
    assert len(fl.read_market_resolutions()) == 1
    assert all("m-ens" not in ids and "m-rev" not in ids and "m-eval" not in ids
               for _, ids in client.calls)


def test_settle_sweep_newest_first_cap_and_degraded(tmp_path):
    led = str(tmp_path / "ledger")
    _commit(_forecast([_binary(market_id="m-old")]), "r-old", d=led, question="Old question?")
    _commit(_forecast([_binary(market_id="m-new")]), "r-new", d=led, question="New question?")
    client = _Client({"m-old": _resolved("m-old", 1.0), "m-new": _resolved("m-new", 1.0)})
    out = mon.settle_ledger(client=client, ledger_dir=led, as_of=PROCESSED, max_targets=1)
    assert out["targets"] == 1 and client.calls == [("resolutions", ["m-new"])]
    assert [r["report_id"] for r in fl.read_market_resolutions(led)] == ["r-new"]

    class Down:
        def fetch_resolutions(self, ids):
            raise ConnectionError("down")

    down = mon.settle_ledger(client=Down(), ledger_dir=str(tmp_path / "led2"), as_of=PROCESSED)
    assert down["targets"] == 0 and down["degraded"] is False
    _commit(_forecast([_binary(market_id="m-x")]), "r-x", d=str(tmp_path / "led2"))
    down = mon.settle_ledger(client=Down(), ledger_dir=str(tmp_path / "led2"), as_of=PROCESSED)
    assert down["degraded"] is True and down["pending_by_reason"] == {"no_resolution_data": 1}
    assert fl.read_market_resolutions(str(tmp_path / "led2")) == []


def test_settle_sweep_skips_finished_targets_before_the_cap(tmp_path):
    led = str(tmp_path / "ledger")
    _commit(_forecast([_binary(market_id="m-old")]), "r-old", d=led, question="Old question?")
    _commit(_forecast([_binary(market_id="m-new")]), "r-new", d=led, question="New question?")
    client = _Client({"m-old": _resolved("m-old", 1.0), "m-new": _resolved("m-new", 1.0)})
    first = mon.settle_ledger(client=client, ledger_dir=led, as_of=PROCESSED, max_targets=1)
    assert first["targets"] == 1 and first["appended"] == 1
    # The newer target is finished now, so it no longer uses up the cap: the older one is due.
    second = mon.settle_ledger(client=client, ledger_dir=led, as_of=PROCESSED, max_targets=1)
    assert second["targets"] == 1 and second["appended"] == 1
    assert client.calls == [("resolutions", ["m-new"]), ("resolutions", ["m-old"])]
    assert mon.settle_ledger(client=client, ledger_dir=led, as_of=PROCESSED)["targets"] == 0

    # due_binaries: an item is final once any resolutions row holds it (market, ambiguous,
    # terminal or legacy); an anchored item always needs a fetch; an unanchored one is due
    # only once its grace period has expired (an undated one never is).
    recorded = fr.recorded_items([{"report_id": "r", "forecast_id": "F1", "market_id": "terminal"},
                                  "junk"])
    assert recorded == {("r", "F1")}
    undated = {"id": "F2", "statement": "someday", "probability": 0.5}
    expired = {"id": "F3", "statement": "by 2025-01-01", "probability": 0.5}
    in_grace = {"id": "F4", "statement": "by 2026-06-30", "probability": 0.5}

    def due(report_id, binaries):
        return [b["id"] for b in fr.due_binaries(report_id, binaries, recorded,
                                                 processed_at=PROCESSED, grace_days=180)]

    assert due("r", [_binary("F1")]) == []
    assert due("r", [_binary("F1"), undated, in_grace, {"statement": "no id"}, "junk"]) == []
    assert due("r", [_binary("F1"), expired, _binary("F5", market_id="m-5")]) == ["F3", "F5"]
    assert due("other", [_binary("F1")]) == ["F1"]
    assert due("r", None) == []
    with pytest.raises(ValueError):
        fr.due_binaries("r", [expired], recorded, processed_at="2026-09-29T12:00:00")


def test_settle_sweep_cap_never_starves_grace_terminals(tmp_path):
    """I-20: a target whose only open items are unanchored and inside grace takes no cap slot,
    and the cap limits only targets that need a market fetch, so an older target whose grace
    has expired always gets its terminal."""
    def unanchored(fid, deadline):
        return {"id": fid, "statement": f"Event by {deadline}", "probability": 0.5,
                "resolution_criteria": f"Event by {deadline}"}

    led = str(tmp_path / "ledger")
    _commit(_forecast([unanchored("F1", "2024-01-01")]), "r-old", d=led, question="Old?")
    _commit(_forecast([unanchored("F1", "2029-01-01")]), "r-mid", d=led, question="Mid?")
    _commit(_forecast([unanchored("F1", "2030-01-01")]), "r-new", d=led, question="New?")
    client = _Client()
    first = mon.settle_ledger(client=client, ledger_dir=led, as_of=PROCESSED, max_targets=1)
    assert (first["targets"], first["terminal"], first["appended"]) == (1, 1, 1)
    assert first["pending_by_reason"] == {} and first["deferred_by_cap"] == 0
    assert mon.settle_ledger(client=client, ledger_dir=led, as_of=PROCESSED,
                             max_targets=1)["targets"] == 0
    assert [(r["report_id"], r["forecast_id"], r["market_id"])
            for r in fl.read_market_resolutions(led)] == [("r-old", "F1", "terminal")]
    assert client.calls == []  # a grace terminal needs no network

    # Newer anchored targets fill the cap; older grace terminals still land, and a deferred
    # target's anchored item is neither fetched nor ended.
    led2 = str(tmp_path / "ledger2")
    _commit(_forecast([unanchored("F1", "2024-01-01"), _binary("F2", market_id="m-mixed")]),
            "r-mixed", d=led2, question="Mixed?")
    _commit(_forecast([unanchored("F1", "2024-06-01")]), "r-local", d=led2, question="Local?")
    _commit(_forecast([_binary(market_id="m-a")]), "r-a", d=led2, question="A?")
    _commit(_forecast([_binary(market_id="m-b")]), "r-b", d=led2, question="B?")
    client = _Client({mid: _resolved(mid, 0.4, closed=False, uma=None)
                      for mid in ("m-a", "m-b", "m-mixed")})
    out = mon.settle_ledger(client=client, ledger_dir=led2, as_of=PROCESSED, max_targets=1)
    assert client.calls == [("resolutions", ["m-b"])]
    assert (out["targets"], out["deferred_by_cap"], out["terminal"]) == (3, 2, 2)
    assert out["pending_by_reason"] == {"market_open": 1}
    assert sorted((r["report_id"], r["forecast_id"], r["market_id"])
                  for r in fl.read_market_resolutions(led2)) == [
        ("r-local", "F1", "terminal"), ("r-mixed", "F1", "terminal")]


class _GammaResponse:
    """Minimal httpx response for PolymarketClient._request."""

    def __init__(self, payload, status_code=200):
        self.payload, self.status_code = payload, status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise pm.httpx.HTTPStatusError(f"HTTP {self.status_code}",
                                           request=None, response=None)

    def json(self):
        return self.payload


def test_failed_request_batch_never_ends_an_item(monkeypatch, tmp_path):
    """One failed Gamma chunk keeps its past-grace items pending; a chunk that answered
    without a market confirms it missing, so that item may turn terminal."""
    monkeypatch.setattr(Config, "PREDICTION_MARKETS_ENABLED", True, raising=False)
    monkeypatch.setattr(Config, "PREDICTION_MARKETS_REQUOTE_CHUNK", 1, raising=False)

    limits = []

    def fake_get(url, params=None, timeout=None, headers=None):
        (mid,) = params["id"]
        limits.append(params.get("limit"))
        if mid == "m-fail":
            return _GammaResponse(None, status_code=400)
        return _GammaResponse([_gamma(mid, 1.0)] if mid == "m-ok" else [])

    monkeypatch.setattr(pm.httpx, "get", fake_get)
    client = pm.PolymarketClient()
    resolutions, answered = client.fetch_resolutions_answered(["m-fail", "m-ok", "m-gone"])
    assert set(resolutions) == {"m-ok"} and answered == {"m-ok", "m-gone"}
    assert limits == [1, 1, 1]
    assert client.fetch_resolutions(["m-ok"]) == {"m-ok": resolutions["m-ok"]}
    monkeypatch.setattr(Config, "PREDICTION_MARKETS_ENABLED", False, raising=False)
    assert pm.PolymarketClient().fetch_resolutions_answered(["m-ok"]) == ({}, set())
    monkeypatch.setattr(Config, "PREDICTION_MARKETS_ENABLED", True, raising=False)

    led = str(tmp_path / "ledger")
    _commit(_forecast([_binary("F1", market_id="m-fail"), _binary("F2", market_id="m-ok"),
                       _binary("F3", market_id="m-gone")]), "r1", d=led)
    out = mon.settle_ledger(client=pm.PolymarketClient(), ledger_dir=led,
                            as_of="2027-12-31T00:00:00+00:00")
    assert out["settled"] == 1 and out["terminal"] == 1
    assert out["pending_by_reason"] == {"no_resolution_data": 1}
    rows = fl.read_market_resolutions(led)
    assert sorted((r["forecast_id"], r["market_id"]) for r in rows) == [
        ("F2", "m-ok"), ("F3", "terminal")]


def test_missing_market_needs_a_single_id_answer(monkeypatch):
    """A multi-id page may be truncated: an omitted id is confirmed missing only by a
    successful request for that id alone, and a page that ignores the id filter confirms
    nothing."""
    monkeypatch.setattr(Config, "PREDICTION_MARKETS_ENABLED", True, raising=False)
    monkeypatch.setattr(Config, "PREDICTION_MARKETS_REQUOTE_CHUNK", 3, raising=False)
    requests = []

    def truncating(url, params=None, timeout=None, headers=None):
        requests.append(dict(params))
        ids = params["id"]
        if len(ids) > 1:  # every multi-id page stops after its first row
            return _GammaResponse([_gamma(ids[0], 1.0)])
        (mid,) = ids
        if mid == "m-flaky":
            return _GammaResponse(None, status_code=400)
        return _GammaResponse([_gamma(mid, 1.0)] if mid == "m-late" else [])

    monkeypatch.setattr(pm.httpx, "get", truncating)
    resolutions, answered = pm.PolymarketClient().fetch_resolutions_answered(
        ["m-first", "m-late", "m-gone", "m-flaky"])
    assert set(resolutions) == {"m-first", "m-late"}
    assert answered == {"m-first", "m-late", "m-gone"}
    assert requests == [{"id": ["m-first", "m-late", "m-gone"], "limit": 3},
                        {"id": ["m-late"], "limit": 1}, {"id": ["m-gone"], "limit": 1},
                        {"id": ["m-flaky"], "limit": 1}]

    def unfiltered(url, params=None, timeout=None, headers=None):
        return _GammaResponse([_gamma("m-other", 1.0)])

    monkeypatch.setattr(pm.httpx, "get", unfiltered)
    for ids in (["m-x", "m-y"], ["m-x"]):
        assert pm.PolymarketClient().fetch_resolutions_answered(ids)[1] == set(), ids


def test_settle_sweep_skips_a_failing_row(monkeypatch, tmp_path):
    led = str(tmp_path / "ledger")
    _commit(_forecast([_binary(market_id="m-a")]), "r-a", d=led, question="Question A?")
    _commit(_forecast([_binary(market_id="m-b")]), "r-b", d=led, question="Question B?")
    real = fr.settle_binaries

    def flaky(report_id, *args, **kwargs):
        if report_id == "r-b":
            raise RuntimeError("malformed row")
        return real(report_id, *args, **kwargs)

    monkeypatch.setattr(mon._settlement, "settle_binaries", flaky)
    client = _Client({"m-a": _resolved("m-a", 1.0), "m-b": _resolved("m-b", 1.0)})
    out = mon.settle_ledger(client=client, ledger_dir=led, as_of=PROCESSED)
    assert out["targets"] == 2 and out["errors"] == 1 and out["appended"] == 1
    assert [r["report_id"] for r in fl.read_market_resolutions(led)] == ["r-a"]


def test_run_all_recent_runs_settle_sweep_behind_flag(monkeypatch, capsys):
    monkeypatch.setattr(mon, "recent_report_ids", lambda n, **kw: ["r1"])
    monkeypatch.setattr(mon, "run_monitor", lambda rid, **kw: {
        "report_id": rid, "skipped": "not_publishable"})
    sweeps = []

    def fake_sweep(**kw):
        sweeps.append(kw)
        return {"targets": 0}

    monkeypatch.setattr(mon, "settle_ledger", fake_sweep)
    assert Config.RESOLUTION_SETTLE_LEDGER is True
    assert mon.main(["run", "--all-recent", "--dry-run"]) == 0
    payload = _json_out(capsys)
    assert payload["settlement"] == {"targets": 0} and sweeps == [{"dry_run": True}]

    monkeypatch.setattr(Config, "RESOLUTION_SETTLE_LEDGER", False)
    assert mon.main(["run", "--all-recent"]) == 0
    payload = _json_out(capsys)
    assert payload == {"dry_run": False, "count": 1,
                       "reports": [{"report_id": "r1", "skipped": "not_publishable"}]}
    assert len(sweeps) == 1

    # A single-report run never sweeps; a failing sweep never breaks the run.
    monkeypatch.setattr(Config, "RESOLUTION_SETTLE_LEDGER", True)
    monkeypatch.setattr(mon, "resolve_report_id", lambda rid: rid)
    assert mon.main(["run", "r1"]) == 0
    assert "settlement" not in _json_out(capsys)

    def broken(**kw):
        raise OSError("disk")

    monkeypatch.setattr(mon, "settle_ledger", broken)
    assert mon.main(["run", "--all-recent"]) == 0
    assert _json_out(capsys)["settlement"] == {"error": "disk"}

    # No recent report folder: the self-contained ledger is still swept; flag off keeps exit 1.
    monkeypatch.setattr(mon, "settle_ledger", fake_sweep)
    monkeypatch.setattr(mon, "recent_report_ids", lambda n, **kw: [])
    assert mon.main(["run", "--all-recent"]) == 0
    assert _json_out(capsys) == {"dry_run": False, "count": 0, "reports": [],
                                 "settlement": {"targets": 0}}
    monkeypatch.setattr(Config, "RESOLUTION_SETTLE_LEDGER", False)
    assert mon.main(["run", "--all-recent"]) == 1
    assert capsys.readouterr().out == ""


def test_settlement_knob_defaults_are_documented():
    assert Config.RESOLUTION_SETTLE_LEDGER is True
    assert Config.RESOLUTION_MARKET_MIN_EQUIVALENCE == "exact"
    assert Config.RESOLUTION_PENDING_GRACE_DAYS == 180
    assert Config.RESOLUTION_SETTLE_MAX_TARGETS == 200
    env_example = os.path.join(os.path.dirname(__file__), "..", "..", ".env.example")
    text = open(env_example, encoding="utf-8").read()
    for line in ("RESOLUTION_SETTLE_LEDGER=true", "RESOLUTION_MARKET_MIN_EQUIVALENCE=exact",
                 "RESOLUTION_PENDING_GRACE_DAYS=180", "RESOLUTION_SETTLE_MAX_TARGETS=200"):
        assert f"# {line}" in text, line


def test_monitor_knob_readers_fail_closed(monkeypatch):
    monkeypatch.setattr(Config, "RESOLUTION_MARKET_MIN_EQUIVALENCE", "bogus")
    assert mon.market_min_equivalence() == "exact"
    monkeypatch.setattr(Config, "RESOLUTION_MARKET_MIN_EQUIVALENCE", "near")
    assert mon.market_min_equivalence() == "near"
    monkeypatch.setattr(Config, "RESOLUTION_PENDING_GRACE_DAYS", -5)
    assert mon.pending_grace_days() == 0
    monkeypatch.setattr(Config, "RESOLUTION_SETTLE_MAX_TARGETS", 0)
    assert mon.settle_max_targets() == 1


def test_render_monitor_md_unchanged_without_settlement():
    kwargs = {"report_id": "r1", "as_of": "2026-09-29", "movers": [], "resolution_records": [],
              "needs_manual": [], "calibration": {}, "market_brier": {}, "anchored_count": 0,
              "degraded": False}
    plain = mon.render_monitor_md(**kwargs)
    assert "## Settlement" not in plain
    assert mon.render_monitor_md(**kwargs, settlement=None, settlement_events=None) == plain
    with_counts = mon.render_monitor_md(**kwargs, settlement={"settled": 0}, settlement_events=[])
    assert "## Settlement" in with_counts and "- Pending by reason: —" in with_counts
