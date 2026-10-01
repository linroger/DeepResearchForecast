"""EVAL-5: market-relative skill scorer (Brier skill vs the price the forecast saw, divergence
hit rate vs a market-implied null) and its read-only monitor surface.

Covers the pure scorer (``backtest.market_skill_report`` / ``divergence_eligible``), the
read-time enrichment over the settlement fold (``resolution_monitor.enrich_market_rows``:
admissible() gate, proxy demotion, withheld reports, retracted / non-prospective /
conflicting settlements), the target lookup, ``expired_unresolved``, the monitor section
behind FORECAST_SKILL_SCORING (byte-identical when off) and the ``summary`` subcommand.

Offline: hand-built ledger rows and events, a fake market client, per-test ledger
directories (conftest), FakeLLMClient for the extractor's revision pass, no network.
"""

import ast
import copy
import hashlib
import json
import os
import re

import pytest

import scripts.resolution_monitor as mon
from app.config import Config
from app.services import backtest as bt
from app.services import forecast_ledger as fl
from app.services import forecast_resolution as fr
from app.services.forecast_extractor import _build_market_anchor, enforce_market_divergence
from app.utils.prediction_markets import _parse_resolution
from tests.conftest import FakeLLMClient

STATEMENT = "The EU AI liability directive is adopted by 2026-06-30."
CRITERIA = "Resolves YES if the Official Journal publishes the directive by 2026-06-30."
QUOTED_AT = "2026-04-30T10:00:00+00:00"
OBSERVED_AT = "2026-04-30T09:15:00+00:00"
CLOSED_AT = "2026-07-02T15:30:00+00:00"
PROCESSED = "2026-09-29T12:00:00+00:00"
META = {"as_of": "2026-05-01", "created_at": "2026-05-02T08:00:00+00:00", "commit_id": "c-r1",
        "production_primary": True}
RATIONALE = "Base rates and policy momentum favour adoption."
METRICS = ("mean_brier_model", "mean_brier_market", "brier_skill_vs_market",
           "mean_brier_delta", "brier_delta_ci95")
HIT_METRICS = ("hit_rate", "hit_rate_ci95", "null_hit_rate", "hit_rate_excess")


# ─────────────────────────────── helpers ─────────────────────────────────────
def _row(model_p, market_p, y, *, report_id=None, equivalence="exact", mc=0.9,
         publishable=True, basis="requote", gate=None, prior=None, cites=False, fid="F1"):
    """A normalized market_skill_report row."""
    return {"report_id": report_id or f"r-{model_p}-{market_p}-{y}", "forecast_id": fid,
            "y": y, "model_p": model_p, "market_p": market_p, "equivalence": equivalence,
            "match_confidence": mc, "publishable_at_issue": publishable,
            "rationale_cites_market": cites, "prior_probability": prior,
            "price_time_basis": basis, "gate_reason": gate}


def _binary(fid="F1", *, market_id="m-1", equivalence="exact", price=0.40, probability=0.30,
            quoted=True, mc=0.9, rationale=RATIONALE, end_date="2026-06-30T12:00:00Z",
            observed_at=None):
    """A binary whose anchor is built by the real producer (complete, byte-bound, dated)."""
    binary = {"id": fid, "proposition_id": f"prop-{fid}", "statement": STATEMENT,
              "probability": probability, "resolution_criteria": CRITERIA,
              "horizon_year": 2026, "adjustment_rationale": rationale}
    market = {"market_id": market_id,
              "question": "Will the EU adopt the AI liability directive by June 30, 2026?",
              "implied_yes_prob": price, "url": f"https://polymarket.com/event/{market_id}",
              "end_date": end_date}
    if quoted:
        market["quoted_at"] = QUOTED_AT
    if observed_at is not None:
        market["observed_at"] = observed_at
    binary["market_anchor"] = _build_market_anchor(
        probability, market, equivalence=equivalence, match_confidence=mc, binary=binary)
    return binary


def _commit_row(report_id, binaries, *, as_of="2026-05-01"):
    """A production primary schema_version 2 commit row as EVAL-1 writes it."""
    return {"schema_version": 2, "row_type": "commit", "commit_id": f"c-{report_id}",
            "target_key": f"k-{report_id}", "calibration_role": "primary",
            "record_class": "production", "report_id": report_id,
            "created_at": f"{as_of}T08:00:00+00:00", "as_of_date": as_of,
            "binary_forecasts": [fl.compact_binary(b) for b in binaries]}


def _event(fid="F1", *, report_id="r1", market_id="m-1", outcome="YES", eligible=True,
           prospective=True, status="settled", known_at=CLOSED_AT, basis="source",
           model_p=0.3, reason=None, source_kind="polymarket", **extra):
    """A schema_version 2 settlement event (EVAL-2/EVAL-4 row shape)."""
    row = {"report_id": report_id, "forecast_id": fid, "market_id": market_id,
           "resolved_outcome": outcome, "resolved_yes_price": None, "model_p": model_p,
           "market_p_at_research": 0.4, "brier_contribution": None, "resolved_at": PROCESSED,
           "schema_version": 2, "item_kind": "binary", "source_kind": source_kind,
           "outcome": outcome, "y": None if outcome not in ("YES", "NO") else int(outcome == "YES"),
           "outcome_known_at": known_at, "known_at_basis": basis, "processed_at": PROCESSED,
           "prospective": prospective, "scoring_eligible": eligible,
           "ineligible_reason": None if eligible else (reason or "not_prospective"),
           "resolution_status": status, "report_publishable_at_issue": True,
           "target_commit_id": None}
    row.update(extra)
    return row


def _manual(fid, outcome, *, report_id="r1", market_id="manual", supersedes=None,
            retract=False, eligible=True):
    """A manual binary attestation (EVAL-4 shape)."""
    return _event(fid, report_id=report_id, market_id=market_id,
                  outcome=None if retract else outcome, eligible=eligible and not retract,
                  status="retracted" if retract else "settled",
                  known_at=None if retract else "2026-07-05T00:00:00+00:00", basis="attested",
                  reason="retracted" if retract else None, source_kind="manual",
                  supersedes=supersedes, retracted=retract)


def _lookup(*binaries, report_id="r1"):
    by_key = {(report_id, b["id"]): b for b in binaries}
    return lambda rid, fid: by_key.get((rid, fid))


def _enrich(events, *binaries, publishable_fn=None, targets=None):
    return {row["forecast_id"]: row for row in mon.enrich_market_rows(
        events, target_lookup=_lookup(*binaries), publishable_fn=publishable_fn,
        targets=targets)}


def _strata(report):
    return report["strata"]


def _assert_no_metrics(stratum):
    for key in METRICS:
        assert stratum[key] is None, key
    for block in ("edge", "revised_toward_market", "retained_divergence"):
        for key in HIT_METRICS:
            assert stratum["divergence"][block][key] is None, (block, key)
        assert stratum["divergence"][block]["n"] == 0


# ─────────────────────────────── pure scorer ─────────────────────────────────
def test_known_values():
    report = bt.market_skill_report([_row(0.8, 0.6, 1, report_id="r1"),
                                     _row(0.3, 0.5, 0, report_id="r2")])
    assert report["schema"] == "market-skill/v1"
    head = _strata(report)["headline"]
    assert head["headline"] is True and head["n_scored"] == 2 and head["n_reports"] == 2
    assert head["mean_brier_model"] == 0.065
    assert head["mean_brier_market"] == 0.205
    assert head["brier_skill_vs_market"] == 0.6829
    assert head["mean_brier_delta"] == 0.14
    # Per-report deltas 0.12 and 0.16: mean 0.14, sd 0.0283, half-width 1.96*sd/sqrt(2) = 0.0392.
    assert head["brier_delta_ci95"] == [0.1008, 0.1792]
    assert head["price_time_basis"] == {"requote": 2, "observed": 0, "snapshot": 0, "none": 0}
    edge = head["divergence"]["edge"]
    # Both moved away from the market by 0.2 and the outcome landed on their side.
    assert edge["n"] == 2 and edge["hits"] == 2 and edge["hit_rate"] == 1.0
    assert edge["null_hit_rate"] == 0.55 and edge["hit_rate_excess"] == 0.45
    assert edge["hit_rate_ci95"] == [0.3424, 1.0]
    assert report["n_rows"] == 2 and report["unscored"] == {} and report["n_unscored"] == 0
    assert _strata(report)["all_produced"]["n_scored"] == 2
    assert _strata(report)["proxy"]["n_scored"] == 0


def test_deadband_boundary():
    # |d| exactly 0.10 (0.4 - 0.3 is 0.10000000000000003 in floats) claims no edge, but the
    # row still counts in the Brier skill; 0.11 claims one.
    rows = [_row(0.6, 0.5, 1), _row(0.4, 0.3, 0), _row(0.2, 0.3, 0), _row(0.61, 0.5, 1)]
    head = _strata(bt.market_skill_report(rows))["headline"]
    assert head["n_scored"] == 4
    assert head["divergence"]["n_no_edge_claimed"] == 3
    assert head["divergence"]["edge"]["n"] == 1
    assert head["mean_brier_model"] == round(
        sum((p - y) ** 2 for p, y in ((0.6, 1), (0.4, 0), (0.2, 0), (0.61, 1))) / 4, 4)
    assert bt.MARKET_DIVERGENCE_DEADBAND == 0.10
    assert bt.divergence_eligible(0.10, 0.9, 0.6) is False
    assert bt.divergence_eligible(-0.10, 0.9, 0.6) is False
    assert bt.divergence_eligible(0.1001, 0.9, 0.6) is True
    assert bt.divergence_eligible(-0.11, 0.9, 0.6) is True


def test_low_and_unknown_confidence_buckets():
    rows = [_row(0.8, 0.5, 1, mc=0.55), _row(0.8, 0.5, 1, mc=None),
            _row(0.8, 0.5, 1, mc=0.6), _row(0.2, 0.5, 1, mc="n/a")]
    div = _strata(bt.market_skill_report(rows))["headline"]["divergence"]
    assert div["min_match_confidence"] == 0.6
    assert div["n_ineligible_low_confidence"] == 1
    assert div["n_eligibility_unknown"] == 2
    assert div["edge"]["n"] == 1          # 0.6 sits on the floor: eligible (>=)
    # The configured floor moves the boundary: at 0.7 the 0.6 match is low confidence.
    div = _strata(bt.market_skill_report(rows, min_match_confidence=0.7))["headline"]["divergence"]
    assert div["n_ineligible_low_confidence"] == 2 and div["edge"]["n"] == 0
    assert bt.divergence_eligible(0.3, None, 0.6) is False
    assert bt.divergence_eligible(0.3, 0.59, 0.6) is False
    assert bt.divergence_eligible(0.3, 0.6, 0.6) is True


def test_withheld_counted_not_scored_and_all_produced_stratum():
    rows = [_row(0.8, 0.6, 1, report_id="r1"), _row(0.3, 0.5, 0, report_id="r2"),
            _row(0.9, 0.5, 0, report_id="r3", publishable=False),
            _row(0.9, 0.5, 0, report_id="r4", publishable=None),
            _row(0.7, 0.5, 1, report_id="r5", publishable=False, equivalence="near"),
            _row(0.7, 0.5, 1, report_id="r6", publishable=False, gate="conflict")]
    report = bt.market_skill_report(rows)
    head, proxy, produced = (_strata(report)[name] for name in bt.SKILL_STRATA)
    # Never in the headline (or proxy), always in unscored.withheld_report (fail closed).
    assert head["n_scored"] == 2 and proxy["n_scored"] == 0
    assert report["unscored"] == {"withheld_report": 4} and report["n_unscored"] == 4
    # all_produced re-scores the headline criteria with the withheld headline-grade rows.
    assert produced["headline"] is False and head["headline"] is True
    assert produced["n_scored"] == 4 and produced["n_withheld"] == 2
    assert produced["n_reports"] == 4
    assert produced["mean_brier_model"] == round((0.04 + 0.09 + 0.81 + 0.81) / 4, 4)
    # Every row lands in exactly one place.
    assert report["n_rows"] == head["n_scored"] + proxy["n_scored"] + report["n_unscored"] == 6


def test_near_rows_in_proxy_not_headline():
    rows = [_row(0.8, 0.6, 1, report_id="r1"),
            _row(0.2, 0.6, 0, report_id="r2", equivalence="near"),
            _row(0.2, 0.6, 0, report_id="r3", equivalence="exact", gate="equivalence_near"),
            _row(0.2, 0.6, 0, report_id="r4", equivalence=None),
            _row(0.2, 0.6, 0, report_id="r5", basis=None),
            _row(0.2, 0.6, 0, report_id="r6", basis="bogus")]
    report = bt.market_skill_report(rows)
    head, proxy, produced = (_strata(report)[name] for name in bt.SKILL_STRATA)
    assert head["n_scored"] == 1 and head["mean_brier_model"] == 0.04
    assert head["mean_brier_market"] == 0.16 and head["brier_skill_vs_market"] == 0.75
    assert proxy["headline"] is False and proxy["n_scored"] == 5
    assert proxy["proxy_reasons"] == {"equivalence_missing": 1, "equivalence_near": 2,
                                      "no_price_time_basis": 2}
    assert proxy["price_time_basis"] == {"requote": 3, "observed": 0, "snapshot": 0, "none": 2}
    # Proxy rows are never pooled into all_produced either.
    assert produced["n_scored"] == 1
    assert report["unscored"] == {}


def test_null_hit_rate():
    # Two upward divergences on 0.2 markets: the market itself gives each a 0.2 chance of
    # landing on the forecast's side.
    rows = [_row(0.5, 0.2, 1, report_id="a"), _row(0.6, 0.2, 0, report_id="b")]
    edge = _strata(bt.market_skill_report(rows))["headline"]["divergence"]["edge"]
    assert edge["null_hit_rate"] == 0.2
    assert edge["hits"] == 1 and edge["hit_rate"] == 0.5 and edge["hit_rate_excess"] == 0.3
    # A downward divergence on a 0.2 market lands on its side with 1 - 0.2.
    down = _strata(bt.market_skill_report([_row(0.05, 0.2, 0)]))["headline"]["divergence"]
    assert down["edge"]["null_hit_rate"] == 0.8 and down["edge"]["hit_rate"] == 1.0


def test_degenerate_cases():
    # BS_market == 0: the market called both outcomes with certainty → no skill ratio.
    report = bt.market_skill_report([_row(0.8, 1.0, 1, report_id="r1"),
                                     _row(0.3, 0.0, 0, report_id="r2")])
    head = _strata(report)["headline"]
    assert head["mean_brier_market"] == 0.0 and head["brier_skill_vs_market"] is None
    assert head["mean_brier_delta"] == -0.065
    # One report → no interval; n_scored < min_n → insufficient_data.
    one = _strata(bt.market_skill_report([_row(0.8, 0.6, 1, report_id="r1"),
                                          _row(0.7, 0.6, 1, report_id="r1")], min_n=2))
    assert one["headline"]["n_reports"] == 1 and one["headline"]["brier_delta_ci95"] is None
    assert one["headline"]["insufficient_data"] is False
    assert _strata(bt.market_skill_report([_row(0.8, 0.6, 1)]))["headline"]["insufficient_data"]
    # Empty input: every metric None, every count 0, nothing raises.
    empty = bt.market_skill_report([])
    assert empty["n_rows"] == 0 and empty["unscored"] == {}
    for name in bt.SKILL_STRATA:
        assert _strata(empty)[name]["n_scored"] == 0
        _assert_no_metrics(_strata(empty)[name])
    assert bt.market_skill_report(None)["n_rows"] == 0
    # Unscoreable rows are bucketed, never dropped.
    bad = bt.market_skill_report([_row(0.8, 0.6, None), _row(0.8, 0.6, True),
                                  _row(float("nan"), 0.6, 1), _row(1.2, 0.6, 1),
                                  _row(0.8, None, 1), "not a row"])
    assert bad["unscored"] == {"invalid_row": 1, "missing_market_price": 1,
                               "missing_probability": 2, "unlabelled": 2}
    with pytest.raises(ValueError):
        bt.market_skill_report([], min_n=True)
    with pytest.raises(ValueError):
        bt.market_skill_report([], min_match_confidence=float("nan"))


def test_scorer_matches_enforce_market_divergence_candidates(monkeypatch):
    """Same dead-band and confidence boundary as the revision pass, on anchors whose rationale
    does not cite the market (the pass also skips a rationale that already cites it)."""
    cases = [(0.60, 0.50, 0.9), (0.40, 0.30, 0.9), (0.61, 0.50, 0.9), (0.39, 0.50, 0.9),
             (0.80, 0.50, 0.6), (0.80, 0.50, 0.59), (0.80, 0.50, None), (0.20, 0.50, 0.95),
             (0.55, 0.50, 0.9), (0.85, 0.50, 0.65)]

    def binaries():
        out = []
        for index, (p, ip, mc) in enumerate(cases):
            anchor = _build_market_anchor(p, {"market_id": f"m{index}", "question": "Will it?",
                                              "implied_yes_prob": ip}, equivalence="exact",
                                          match_confidence=mc)
            out.append({"id": f"F{index}", "statement": "It happens.", "probability": p,
                        "adjustment_rationale": RATIONALE, "market_anchor": anchor})
        return out

    for floor in (0.6, 0.7):
        monkeypatch.setattr(Config, "FORECAST_MARKET_DIVERGENCE_MIN_CONFIDENCE", floor)
        llm = FakeLLMClient(json_responses=[{"revisions": []}])
        assert enforce_market_divergence(binaries(), llm) == 0
        prompt = llm.calls[0]["messages"][0]["content"] if llm.calls else ""
        candidates = set(re.findall(r"^\[(F\d+)\] statement", prompt, re.MULTILINE))
        assert candidates  # the pass did consider some anchors
        assert mon.divergence_min_confidence() == floor
        for binary in binaries():
            anchor = binary["market_anchor"]
            assert not mon._extractor._rationale_cites_market(binary["adjustment_rationale"],
                                                              anchor)
            row = _row(binary["probability"], anchor["price_at_research"], 1,
                       mc=anchor.get("match_confidence"))
            div = _strata(bt.market_skill_report(
                [row], min_match_confidence=mon.divergence_min_confidence()))["headline"]["divergence"]
            expected = binary["id"] in candidates
            assert (div["edge"]["n"] == 1) is expected, (floor, binary["id"])
            assert bt.divergence_eligible(anchor["divergence"], anchor.get("match_confidence"),
                                          floor) is expected


def test_scorer_imports_no_llm_or_network():
    """The scorer is pure: its module imports only stdlib and its pure siblings."""
    base = os.path.join(os.path.dirname(__file__), "..", "app", "services")
    allowed = {"__future__", "math", "collections", "typing", "numbers", "random", "datetime",
               "config", "ensemble", "eval_stats"}
    for name in ("backtest.py", "eval_stats.py"):
        with open(os.path.join(base, name), encoding="utf-8") as handle:
            tree = ast.parse(handle.read())
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                imported.add((node.module or "").split(".")[0] or "<relative>")
        assert imported <= allowed, (name, imported - allowed)


# ─────────────────────────────── enrichment ──────────────────────────────────
def test_enrichment_rows_from_the_fold():
    exact = _binary("F1", probability=0.30)
    exact["market_influence"] = {"market_id": "m-1", "prior_probability": 0.45,
                                 "revised_probability": 0.30}
    near = _binary("F2", market_id="m-2", equivalence="near")
    snap = _binary("F3", market_id="m-3", quoted=False)
    restored = _binary("F4", market_id="m-4")
    restored["market_influence"] = {"market_id": "m-4", "prior_probability": 0.5,
                                    "probability_restored": True}
    cites = _binary("F5", market_id="m-5", rationale="The market prices this lower.")
    events = [_event("F1"),
              _event("F2", market_id="m-2", eligible=False, reason="equivalence_near"),
              _event("F3", market_id="m-3"), _event("F4", market_id="m-4"),
              _event("F5", market_id="m-5", outcome="NO")]
    rows = _enrich(events, exact, near, snap, restored, cites)
    f1 = rows["F1"]
    assert f1 == {"report_id": "r1", "forecast_id": "F1", "y": 1, "model_p": 0.3,
                  "market_p": 0.4, "equivalence": "exact", "match_confidence": 0.9,
                  "publishable_at_issue": True, "rationale_cites_market": False,
                  "prior_probability": 0.45, "price_time_basis": "requote", "gate_reason": None}
    assert rows["F2"]["gate_reason"] == "equivalence_near" and rows["F2"]["equivalence"] == "near"
    assert rows["F3"]["price_time_basis"] is None
    assert rows["F4"]["prior_probability"] is None
    assert rows["F5"]["rationale_cites_market"] is True and rows["F5"]["y"] == 0
    report = bt.market_skill_report(list(rows.values()))
    head, proxy = _strata(report)["headline"], _strata(report)["proxy"]
    assert head["n_scored"] == 3 and proxy["n_scored"] == 2
    assert proxy["proxy_reasons"] == {"equivalence_near": 1, "no_price_time_basis": 1}
    assert head["divergence"]["n_no_edge_claimed"] == 3
    assert report["unscored"] == {}


def test_price_time_bases_mirror_prediction_markets():
    """The scorer's dated bases are exactly prediction_markets' PRICE_TIME_BASIS_* values, in
    market_price_time's precedence, so a basis the producer adds can never fall to 'none'."""
    from app.utils import prediction_markets as pm
    declared = [value for name, value in vars(pm).items() if name.startswith("PRICE_TIME_BASIS_")]
    assert sorted(bt.PRICE_TIME_BASES) == sorted(declared)
    assert bt.PRICE_TIME_BASES == (pm.PRICE_TIME_BASIS_REQUOTE, pm.PRICE_TIME_BASIS_OBSERVED,
                                   pm.PRICE_TIME_BASIS_SNAPSHOT)


def test_observed_price_time_basis_lands_in_the_headline():
    """FU-11: an exact anchor the real producer dates by the row's observed_at is headline."""
    binary = _binary("F1", probability=0.30, quoted=False, observed_at=OBSERVED_AT)
    anchor = binary["market_anchor"]
    assert (anchor["price_time"], anchor["price_time_basis"]) == (OBSERVED_AT, "observed")
    rows = _enrich([_event("F1")], binary)
    assert rows["F1"]["price_time_basis"] == "observed" and rows["F1"]["gate_reason"] is None
    report = bt.market_skill_report(list(rows.values()))
    head, proxy = _strata(report)["headline"], _strata(report)["proxy"]
    assert head["n_scored"] == 1 and proxy["n_scored"] == 0 and report["unscored"] == {}
    assert head["price_time_basis"] == {"requote": 0, "observed": 1, "snapshot": 0, "none": 0}
    assert "no_price_time_basis" not in (proxy.get("proxy_reasons") or {})
    assert any("'observed'" in caveat for caveat in bt.MARKET_SKILL_CAVEATS)
    md = "\n".join(mon._render_market_skill(report))
    assert "| requote 0, observed 1, snapshot 0, none 0 |" in md
    assert "'observed' = the research bridge's fetch of that market row" in md


def test_proxy_demotion_rechecks_the_market_end_date():
    """The writer stops at equivalence_near, so the end-date check after it never ran: a near
    anchor joins the proxy stratum only when that check passes from the forecast origin."""
    matching = _binary("F1", equivalence="near")
    late = _binary("F2", market_id="m-2", equivalence="near", end_date="2026-12-31T12:00:00Z")
    near = [_event(fid, market_id=mid, eligible=False, reason="equivalence_near")
            for fid, mid in (("F1", "m-1"), ("F2", "m-2"))]
    rows = _enrich(near, matching, late)
    assert rows["F1"]["gate_reason"] == "equivalence_near"
    assert rows["F2"]["gate_reason"] == "end_date_mismatch"
    report = bt.market_skill_report(list(rows.values()))
    assert _strata(report)["proxy"]["n_scored"] == 1
    assert report["unscored"] == {"end_date_mismatch": 1}
    # The origin is the commit row's as-of date: issued after its own 2026-06-30 deadline, the
    # binary's end date cannot be verified (read with no origin, every named date counts).
    targets = [_commit_row("r1", [matching], as_of="2026-07-15")]
    assert _enrich(near[:1], matching, targets=targets)["F1"]["gate_reason"] == \
        "end_date_unverifiable"
    assert _enrich(near[:1], matching, targets=[_commit_row("r1", [matching])])["F1"][
        "gate_reason"] == "equivalence_near"


def test_an_admitted_attestation_still_needs_an_eligible_anchor():
    """Review round 1: the outcome label and the price it is scored against are separate facts,
    so a manual attestation (or one beside an ineligible market event) never scores against an
    anchor whose market ends after the deadline or whose binding no longer holds."""
    late = _binary("F1", end_date="2026-12-31T12:00:00Z")
    market_late = _event("F1", eligible=False, reason="end_date_mismatch")
    assert _enrich([market_late], late)["F1"]["gate_reason"] == "end_date_mismatch"
    for events in ([_manual("F1", "YES")], [market_late, _manual("F1", "YES")]):
        rows = _enrich(events, late)
        assert rows["F1"]["gate_reason"] == "end_date_mismatch"
        assert _strata(bt.market_skill_report(list(rows.values())))["headline"]["n_scored"] == 0
    rebound = _binary("F1")
    rebound["statement"] = "A different proposition entirely by 2026-06-30."
    assert _enrich([_manual("F1", "NO")], rebound)["F1"]["gate_reason"] == "binding_invalid"
    near_late = _binary("F2", market_id="m-2", equivalence="near", end_date="2026-12-31T12:00:00Z")
    rows = _enrich([_manual("F2", "YES")], near_late)
    assert rows["F2"]["gate_reason"] == "end_date_mismatch"
    assert _strata(bt.market_skill_report(list(rows.values())))["proxy"]["n_scored"] == 0
    # an eligible exact anchor with an attestation still scores in the headline
    rows = _enrich([_manual("F1", "YES")], _binary("F1"))
    assert rows["F1"]["gate_reason"] is None


def test_report_without_commit_row_uses_its_meta_origin():
    """Review round 1: a pre-EVAL-1 report's proxy end-date recheck uses the origin the writer
    used (meta.json created_at through origin_fn), not every date the binary names."""
    near = _binary("F1", equivalence="near")
    event = [_event("F1", eligible=False, reason="equivalence_near")]
    by_origin = {}
    for origin in ("2026-05-01", "2026-07-15"):
        by_origin[origin] = {row["forecast_id"]: row for row in mon.enrich_market_rows(
            event, target_lookup=_lookup(near), origin_fn=lambda rid, o=origin: o)}
    assert by_origin["2026-05-01"]["F1"]["gate_reason"] == "equivalence_near"
    assert by_origin["2026-07-15"]["F1"]["gate_reason"] == "end_date_unverifiable"
    calls = []
    mon.enrich_market_rows(event, target_lookup=_lookup(near), targets=[_commit_row("r1", [near])],
                           origin_fn=lambda rid: calls.append(rid))
    assert calls == []          # a committed report keeps its registered origin


def test_market_p_is_derived_as_the_writer_derives_it():
    binary = _binary("F1")
    binary["market_anchor"]["price_at_research"] = float("inf")
    row = _enrich([_event("F1")], binary)["F1"]
    assert row["market_p"] == fr._market_price_at_research(binary["market_anchor"])
    assert row["market_p"] == binary["market_anchor"]["implied_yes_prob"]


def test_admission_uses_the_monitor_clock():
    from datetime import datetime, timezone

    before = datetime(2026, 7, 1, tzinfo=timezone.utc)
    after = datetime(2026, 9, 29, tzinfo=timezone.utc)
    rows = {when: {r["forecast_id"]: r for r in mon.enrich_market_rows(
        [_event("F1")], target_lookup=_lookup(_binary("F1")), now=when)} for when in (before, after)}
    assert rows[before]["F1"]["gate_reason"] == "known_after_now"
    assert rows[after]["F1"]["gate_reason"] is None


def test_retracted_superseded_and_unanchored_attestations():
    binaries = [_binary("F1"), _binary("F2", market_id="m-2"),
                {"id": "F3", "statement": "Unanchored by 2026-06-30.", "probability": 0.5}]
    events = [
        # F1: an eligible attestation that was later retracted labels nothing.
        _manual("F1", "YES"), _manual("F1", None, market_id="manual:r1", supersedes="manual",
                                      retract=True),
        # F2: a correction replaces the attestation it supersedes.
        _manual("F2", "YES"), _manual("F2", "NO", market_id="manual:r1", supersedes="manual"),
        # F3: no market anchor, so nothing to score against.
        _manual("F3", "YES"),
    ]
    rows = _enrich(events, *binaries)
    assert "F1" not in rows
    assert rows["F2"]["y"] == 0 and rows["F2"]["gate_reason"] is None
    assert rows["F3"]["gate_reason"] == "no_market_anchor"
    report = bt.market_skill_report(list(rows.values()))
    assert _strata(report)["headline"]["n_scored"] == 1
    assert report["unscored"] == {"no_market_anchor": 1}


def test_retracted_market_settlement_is_not_scored():
    # An ineligible market settlement plus a retracted attestation: the fold keeps only the
    # market event, which never enters a stratum.
    binary = _binary("F1")
    events = [_event("F1", eligible=False, reason="not_prospective", prospective=False),
              _manual("F1", "YES"),
              _manual("F1", None, market_id="manual:r1", supersedes="manual", retract=True)]
    report = bt.market_skill_report(list(_enrich(events, binary).values()))
    assert _strata(report)["headline"]["n_scored"] == 0
    assert _strata(report)["proxy"]["n_scored"] == 0
    assert report["unscored"] == {"not_prospective": 1}


def test_non_prospective_settlement_lands_in_not_prospective():
    exact, near = _binary("F1"), _binary("F2", market_id="m-2", equivalence="near")
    events = [_event("F1", eligible=False, prospective=False, reason="not_prospective"),
              # The writer stops at the equivalence check; lifting it still fails prospective.
              _event("F2", market_id="m-2", eligible=False, prospective=False,
                     reason="equivalence_near")]
    rows = _enrich(events, exact, near)
    assert rows["F1"]["gate_reason"] == "not_prospective"
    assert rows["F2"]["gate_reason"] == "not_prospective"
    report = bt.market_skill_report(list(rows.values()))
    assert report["unscored"] == {"not_prospective": 2}
    assert _strata(report)["proxy"]["n_scored"] == 0


def test_manual_vs_market_disagreement_lands_in_conflict():
    binary = _binary("F1")
    events = [_event("F1", outcome="YES"), _manual("F1", "NO")]
    report = bt.market_skill_report(list(_enrich(events, binary).values()))
    assert report["unscored"] == {"conflict": 1}
    assert _strata(report)["headline"]["n_scored"] == 0


def test_other_gate_reasons_never_scored():
    binaries = [_binary(f"F{i}", market_id=f"m-{i}") for i in range(1, 6)]
    events = [_event("F1", market_id="m-1", outcome=None, eligible=False, status="ambiguous",
                     reason="ambiguous_settlement"),
              _event("F2", market_id="terminal", outcome=None, eligible=False, prospective=None,
                     status="terminal", known_at=None, basis=None,
                     reason="unresolvable_after_grace", source_kind="terminal"),
              _event("F3", market_id="m-3", known_at="2026-07-02T15:30:00"),  # naive stamp
              _event("F4", market_id="m-other"),
              _event("F5", market_id="m-5", known_at="2099-01-01T00:00:00+00:00")]
    rows = _enrich(events, *binaries)
    assert {fid: row["gate_reason"] for fid, row in rows.items()} == {
        "F1": "ambiguous_settlement", "F2": "unresolvable_after_grace",
        "F3": "unverifiable_stamp", "F4": "market_mismatch", "F5": "known_after_now"}
    report = bt.market_skill_report(list(rows.values()))
    assert report["n_unscored"] == 5 and _strata(report)["headline"]["n_scored"] == 0


def test_publishability_from_event_stamps_else_publishable_fn():
    binary = _binary("F1")
    legacy = {"report_id": "r1", "forecast_id": "F1", "market_id": "m-1",
              "resolved_outcome": "Yes", "resolved_yes_price": 1.0, "model_p": 0.3,
              "market_p_at_research": 0.4, "brier_contribution": 0.49,
              "resolved_at": "2026-07-03T00:00:00+00:00", "schema_version": 1}
    targets = [_commit_row("r1", [binary])]
    calls = []

    def withheld(rid):
        calls.append(rid)
        return {"publishable": False, "reasons": ["final audit failed"]}

    rows = _enrich([legacy], binary, publishable_fn=withheld, targets=targets)
    assert calls == ["r1"] and rows["F1"]["publishable_at_issue"] is False
    assert rows["F1"]["gate_reason"] is None  # the legacy row is proven through its v2 target
    report = bt.market_skill_report(list(rows.values()))
    assert _strata(report)["headline"]["n_scored"] == 0
    assert report["unscored"] == {"withheld_report": 1}
    assert _strata(report)["all_produced"]["n_withheld"] == 1
    # A strict proof only: a dict saying publishable, or True itself.
    for verdict, expected in (({"publishable": True}, True), (True, True), ("yes", False),
                              ({}, False)):
        rows = _enrich([legacy], binary, publishable_fn=lambda rid, v=verdict: v,
                       targets=targets)
        assert rows["F1"]["publishable_at_issue"] is expected

    def broken(rid):
        raise OSError("unreadable")

    assert _enrich([legacy], binary, publishable_fn=broken,
                   targets=targets)["F1"]["publishable_at_issue"] is False

    # v2 events carry the stamp: the function is never consulted, and a False stamp withholds.
    def must_not_run(rid):
        raise AssertionError("stamped events never consult publishable_fn")

    assert _enrich([_event("F1")], binary, publishable_fn=must_not_run)["F1"][
        "publishable_at_issue"] is True
    stamped = _event("F1", report_publishable_at_issue=False)
    assert _enrich([stamped], binary, publishable_fn=must_not_run)["F1"][
        "publishable_at_issue"] is False


def test_enrichment_never_modifies_resolutions(tmp_path):
    led = str(tmp_path / "ledger")
    binary = _binary("F1")
    events = [_event("F1"), _manual("F1", "YES"),
              _event("F2", market_id="terminal", outcome=None, eligible=False, prospective=None,
                     status="terminal", known_at=None, basis=None,
                     reason="unresolvable_after_grace", source_kind="terminal")]
    for event in events:
        assert fl.append_settlement_event(event, d=led) is not None
    with open(os.path.join(led, "ledger.jsonl"), "w", encoding="utf-8") as handle:
        handle.write(json.dumps(_commit_row("r1", [binary, _binary("F2", market_id="m-2")]))
                     + "\n")
    path = os.path.join(led, "resolutions.jsonl")

    def digest():
        with open(path, "rb") as handle:
            return hashlib.sha256(handle.read()).hexdigest()

    before = digest()
    rows_on_disk = fl.read_market_resolutions(led)
    snapshot = copy.deepcopy(rows_on_disk)
    mon.enrich_market_rows(rows_on_disk, target_lookup=_lookup(binary),
                           targets=fl.read_ledger(led))
    assert rows_on_disk == snapshot
    skill = mon.market_skill_summary(led, as_of_day="2026-09-29",
                                     publishable_fn=lambda rid: True)
    assert skill["strata"]["headline"]["n_scored"] == 1
    assert skill["unscored"] == {"unresolvable_after_grace": 1}
    assert digest() == before and len(fl.read_market_resolutions(led)) == 3


# ─────────────────────────────── lookup / expired ────────────────────────────
def test_target_lookup_prefers_the_registered_binary(monkeypatch):
    registered = _binary("F1")
    entries = [_commit_row("r1", [registered])]
    reads = []

    def fake_sealed(rid):
        reads.append(rid)
        return None

    monkeypatch.setattr(mon, "_load_sealed_forecast", fake_sealed)
    # forecast.json's binary is byte for byte the registration: the full one (with its
    # rationale) is returned.
    lookup = mon.market_target_lookup(entries, forecasts={"r1": {"binary_forecasts": [registered]}})
    assert lookup("r1", "F1") is registered
    # A forecast.json binary that differs from the registration never stands in for it.
    changed = dict(registered, probability=0.9)
    lookup = mon.market_target_lookup(entries, forecasts={"r1": {"binary_forecasts": [changed]}})
    got = lookup("r1", "F1")
    assert got == entries[0]["binary_forecasts"][0] and "adjustment_rationale" not in got
    assert lookup("r1", "F9") is None
    # No commit row (pre-EVAL-1): the sealed forecast.json, read once per report.
    lookup = mon.market_target_lookup([])
    assert lookup("r2", "F1") is None and lookup("r2", "F2") is None and reads == ["r2"]
    lookup = mon.market_target_lookup([], forecasts={"r3": {"binary_forecasts": [changed]}})
    assert lookup("r3", "F1") is changed
    # Two binaries sharing an id name neither.
    dup = mon.market_target_lookup([], forecasts={"r4": {"binary_forecasts": [changed, changed]}})
    assert dup("r4", "F1") is None


def test_expired_unresolved_counts_anchored_items_without_any_fact():
    past, settled = _binary("F1"), _binary("F2", market_id="m-2")
    future = _binary("F3", market_id="m-3")
    future["resolution_criteria"] = "Resolves YES if adopted by 2027-06-30."
    future["statement"] = "Adopted by 2027-06-30."
    unanchored = {"id": "F4", "statement": "Unanchored by 2026-06-30.", "probability": 0.5,
                  "resolution_criteria": "by 2026-06-30"}
    entries = [_commit_row("r1", [past, settled, future, unanchored]),
               dict(_commit_row("r1", [past]), calibration_role="revision")]
    assert mon.expired_unresolved_count(entries, {("r1", "F2")}, "2026-09-29") == 1
    assert mon.expired_unresolved_count(entries, {("r1", "F1"), ("r1", "F2")}, "2026-09-29") == 0
    assert mon.expired_unresolved_count(entries, set(), "2026-06-01") == 0
    assert mon.expired_unresolved_count([], set(), "2026-09-29") == 0


def test_expired_unresolved_counts_reports_without_a_commit_row():
    """Review round 1: the monitor settles pre-EVAL-1 reports against the report itself, so
    their anchored, past-deadline, unsettled binaries count too (once per key)."""
    past = _binary("F1")
    assert mon.expired_unresolved_count([], set(), "2026-09-29",
                                        report_binaries={"r-legacy": [past]}) == 1
    assert mon.expired_unresolved_count([], {("r-legacy", "F1")}, "2026-09-29",
                                        report_binaries={"r-legacy": [past]}) == 0
    # a report with a commit row is read from that row only
    entries = [_commit_row("r1", [past])]
    assert mon.expired_unresolved_count(entries, set(), "2026-09-29",
                                        report_binaries={"r1": [past, _binary("F9", market_id="m-9")]}) == 1


# ─────────────────────────────── monitor surface ─────────────────────────────
class _Client:
    def __init__(self, resolutions):
        self._resolutions = resolutions

    def requote_markets(self, rows):
        return [dict(r, implied_yes_prob=r.get("price_at_research"), price_delta=0.0)
                for r in rows]

    def fetch_resolutions(self, ids):
        return {mid: self._resolutions[mid] for mid in ids if mid in self._resolutions}


def _gamma(market_id, yes):
    return _parse_resolution({
        "id": market_id, "question": "q", "outcomes": '["Yes","No"]',
        "outcomePrices": json.dumps([str(yes), str(round(1 - yes, 4))]), "closed": True,
        "umaResolutionStatus": "resolved", "endDate": "2026-06-30T12:00:00Z",
        "closedTime": "2026-07-02T15:30:00Z"})


def _monitor(tmp_path, tag):
    forecast = {"binary_forecasts": [_binary("F1", probability=0.30),
                                     _binary("F2", market_id="m-near", equivalence="near")]}
    client = _Client({"m-1": _gamma("m-1", 1.0), "m-near": _gamma("m-near", 0.0)})
    return mon.run_monitor("r1", forecast=forecast, report_folder=str(tmp_path / f"rep-{tag}"),
                           client=client, ledger_dir=str(tmp_path / f"led-{tag}"),
                           as_of=PROCESSED, publishable_fn=lambda rid: True, target_meta=META)


def test_monitor_section_flagged(tmp_path, monkeypatch):
    assert Config.FORECAST_SKILL_SCORING is True
    on = _monitor(tmp_path, "on")
    skill = on["market_skill"]
    assert skill["schema"] == "market-skill/v1" and skill["as_of"] == "2026-09-29"
    head, proxy = skill["strata"]["headline"], skill["strata"]["proxy"]
    assert head["n_scored"] == 1 and head["mean_brier_model"] == 0.49
    assert head["mean_brier_market"] == 0.36 and head["insufficient_data"] is True
    assert proxy["n_scored"] == 1 and proxy["proxy_reasons"] == {"equivalence_near": 1}
    assert skill["expired_unresolved"] == 0
    md = on["monitor_report_md"]
    assert "## Skill vs the market it saw" in md
    assert "| headline (indicative) | 1 (1) | 0.4900 | 0.3600 | -0.3611 |" in md
    assert "- Unscored by reason: —" in md
    assert md.index("## Running score") < md.index("## Skill vs the market it saw") < \
        md.index("## Newly resolved markets")
    with open(on["monitor_report_path"], encoding="utf-8") as handle:
        assert handle.read() == md

    monkeypatch.setattr(Config, "FORECAST_SKILL_SCORING", False)
    off = _monitor(tmp_path, "off")
    assert "market_skill" not in off
    section = "\n" + "\n".join(mon._render_market_skill(skill))
    assert md.count(section) == 1
    assert off["monitor_report_md"] == md.replace(section, "")
    assert "Skill vs the market" not in off["monitor_report_md"]
    assert set(on) - set(off) == {"market_skill"}
    # The renderer itself is unchanged without a market_skill block.
    kwargs = {"report_id": "r1", "as_of": "2026-09-29", "movers": [], "resolution_records": [],
              "needs_manual": [], "calibration": {}, "market_brier": {}, "anchored_count": 0,
              "degraded": False}
    assert mon.render_monitor_md(**kwargs, market_skill=None) == mon.render_monitor_md(**kwargs)


def test_monitor_counts_an_expired_binary_of_a_report_without_commit_row(tmp_path):
    forecast = {"binary_forecasts": [_binary("F1", probability=0.30)]}
    res = mon.run_monitor("r-legacy", forecast=forecast, report_folder=str(tmp_path / "rep"),
                          client=_Client({}), ledger_dir=str(tmp_path / "led"), as_of=PROCESSED,
                          publishable_fn=lambda rid: True,
                          target_meta={"as_of": None, "created_at": "2026-05-02T08:00:00+00:00",
                                       "commit_id": None, "production_primary": None})
    assert [(n["forecast_id"], n["has_anchor"]) for n in res["needs_manual"]] == [("F1", True)]
    assert res["market_skill"]["expired_unresolved"] == 1
    assert "Expired unresolved (anchored, past resolution date, no settlement yet): **1**" in \
        res["monitor_report_md"]


def test_batch_reads_each_report_once(monkeypatch):
    reads, calls = mon.MarketSkillReads(), []
    monkeypatch.setattr(mon, "_sealed_forecast_or_none", lambda rid: calls.append(rid) or None)
    monkeypatch.setattr(mon, "_report_meta_origin", lambda rid: calls.append(("origin", rid)) or None)
    for _ in range(3):
        reads.sealed_forecast("r1")
        reads.report_origin("r1")
    assert calls == ["r1", ("origin", "r1")]


def test_market_skill_failure_degrades_safely(tmp_path, monkeypatch, capsys):
    def boom(**kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(mon, "market_skill_summary", boom)
    res = _monitor(tmp_path, "err")
    assert res["market_skill"] == {"schema": "market-skill/v1", "error": "boom"}
    assert "_Market skill unavailable this run: boom._" in res["monitor_report_md"]
    assert res["settlement"]["settled_eligible"] == 1
    assert mon.main(["summary"]) == 0
    printed = json.loads(capsys.readouterr().out)
    assert printed["market_skill"] == {"schema": "market-skill/v1", "error": "boom"}


def test_summary_prints_market_skill_on_an_empty_ledger(capsys, monkeypatch):
    assert fl.read_market_resolutions(fl.ledger_dir()) == []
    assert mon.main(["summary"]) == 0
    printed = json.loads(capsys.readouterr().out)
    skill = printed["market_skill"]
    assert skill["schema"] == "market-skill/v1"
    assert set(skill["strata"]) == {"headline", "proxy", "all_produced"}
    for name in bt.SKILL_STRATA:
        assert skill["strata"][name]["n_scored"] == 0
        _assert_no_metrics(skill["strata"][name])
    assert skill["n_rows"] == 0 and skill["unscored"] == {} and skill["expired_unresolved"] == 0
    assert skill["min_n"] == Config.FORECAST_SKILL_MIN_N == 10
    assert skill["min_match_confidence"] == Config.FORECAST_MARKET_DIVERGENCE_MIN_CONFIDENCE
    assert skill["caveats"] == list(bt.MARKET_SKILL_CAVEATS)
    # Flag off: the summary is exactly the pre-EVAL-5 payload.
    monkeypatch.setattr(Config, "FORECAST_SKILL_SCORING", False)
    assert mon.main(["summary"]) == 0
    assert set(json.loads(capsys.readouterr().out)) == {
        "market_brier", "scenario_calibration", "binary_calibration"}


def test_skill_knobs_are_documented_and_read_fail_safe(monkeypatch):
    assert Config.FORECAST_SKILL_SCORING is True and Config.FORECAST_SKILL_MIN_N == 10
    env_example = os.path.join(os.path.dirname(__file__), "..", "..", ".env.example")
    with open(env_example, encoding="utf-8") as handle:
        text = handle.read()
    for line in ("FORECAST_SKILL_SCORING=true", "FORECAST_SKILL_MIN_N=10"):
        assert f"# {line}" in text, line
    monkeypatch.setattr(Config, "FORECAST_SKILL_MIN_N", 0)
    assert mon.skill_min_n() == 1
    monkeypatch.setattr(Config, "FORECAST_SKILL_MIN_N", "bogus")
    assert mon.skill_min_n() == 10
    monkeypatch.setattr(Config, "FORECAST_MARKET_DIVERGENCE_MIN_CONFIDENCE", float("nan"))
    assert mon.divergence_min_confidence() == 0.6
