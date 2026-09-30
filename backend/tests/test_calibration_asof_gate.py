"""EVAL-3: settlement fold + the single point-in-time admissible() gate.

Covers ``forecast_resolution.admissible`` (strict stamps, same-day exclusion),
the per-item fold (precedence, conflict, legacy rows proven only through a v2
target), ``resolved_view``, the scoreability predicate, and their consumers:
``calibration_summary`` / ``recalibration_param`` (fold toggle, as_of cut,
exclusion counts), ``binary_calibration_summary`` (binary 0-1 scale), the
resolution monitor's running score and the report path, which stays
byte-identical while FORECAST_LEDGER_SETTLEMENT_FOLD is off.

Offline: hand-built ledger rows and events, fake market clients, per-test
ledger directories (conftest), no LLM, no network.
"""

import copy
import json
import os
from datetime import datetime, timezone

import pytest

import scripts.resolution_monitor as mon
from app.config import Config
from app.services import forecast_extractor as fe
from app.services import forecast_ledger as fl
from app.services import forecast_resolution as fr
from app.services.backtest import calibration_report
from app.services.forecast_extractor import _build_market_anchor
from app.services.report_agent import ReportAgent, ReportManager
from tests import test_evaluation_run as er

STATEMENT = "The EU AI liability directive is adopted by 2026-06-30."
CRITERIA = "Resolves YES if the Official Journal publishes the directive by 2026-06-30."
CLOSED_AT = "2026-07-02T15:30:00+00:00"
PROCESSED = "2026-09-29T12:00:00+00:00"
META = {"as_of": "2026-05-01", "created_at": "2026-05-02T08:00:00+00:00", "commit_id": "c-1"}
SCENARIOS = [{"name": "Adopted", "probability": 0.7, "resolution_criteria": "OJ"},
             {"name": "Stalled", "probability": 0.3, "resolution_criteria": "none"}]


def _binary(fid="F1", *, market_id="m-1", equivalence="exact", price=0.40, probability=0.30):
    """A binary whose anchor is built by the real producer (complete and byte-bound)."""
    binary = {"id": fid, "proposition_id": f"prop-{fid}", "statement": STATEMENT,
              "probability": probability, "resolution_criteria": CRITERIA,
              "horizon_year": 2026}
    market = {"market_id": market_id,
              "question": "Will the EU adopt the AI liability directive by June 30, 2026?",
              "implied_yes_prob": price, "url": f"https://polymarket.com/event/{market_id}",
              "end_date": "2026-06-30T12:00:00Z"}
    binary["market_anchor"] = _build_market_anchor(
        probability, market, equivalence=equivalence, match_confidence=0.9, binary=binary)
    return binary


def _commit_row(report_id="r1", *, commit_id="c-1", binaries=(), role="primary",
                record_class="production", as_of="2026-05-01"):
    """A schema_version 2 commit row as EVAL-1 writes it (never resolved on disk)."""
    return {"schema_version": 2, "row_type": "commit", "commit_id": commit_id,
            "target_key": f"k-{report_id}", "calibration_role": role,
            "record_class": record_class, "report_id": report_id,
            "created_at": "2026-05-02T08:00:00+00:00", "as_of_date": as_of,
            "scenarios": copy.deepcopy(SCENARIOS), "resolved": False, "outcome": None,
            "binary_forecasts": [fl.compact_binary(b) for b in binaries]}


def _event(fid="F1", *, report_id="r1", market_id="m-1", outcome="YES", eligible=True,
           prospective=True, status="settled", known_at=CLOSED_AT, basis="source",
           processed_at=PROCESSED, model_p=0.7, reason=None, item_kind="binary", **extra):
    """A schema_version 2 settlement event (the append_market_resolution row shape)."""
    row = {"report_id": report_id, "forecast_id": fid, "market_id": market_id,
           "resolved_outcome": None, "resolved_yes_price": None, "model_p": model_p,
           "market_p_at_research": 0.4, "brier_contribution": None,
           "resolved_at": processed_at, "schema_version": 2, "item_kind": item_kind,
           "source_kind": "polymarket", "outcome": outcome,
           "y": None if outcome not in ("YES", "NO") else int(outcome == "YES"),
           "outcome_known_at": known_at, "known_at_basis": basis, "processed_at": processed_at,
           "prospective": prospective, "scoring_eligible": eligible,
           "ineligible_reason": None if eligible else (reason or "not_prospective"),
           "resolution_status": status, "target_commit_id": None}
    row.update(extra)
    return row


def _terminal(fid, *, report_id="r1"):
    return _event(fid, report_id=report_id, market_id="terminal", outcome=None, eligible=False,
                  prospective=None, status="terminal", known_at=None, basis=None,
                  reason="unresolvable_after_grace", source_kind="terminal")


def _scenario_event(outcome="Adopted", *, report_id="r1", known_at="2026-03-01T00:00:00+00:00",
                    eligible=True, market_id="manual", **extra):
    """A scenario_set attestation in the shape EVAL-4's manual path appends."""
    return _event("__scenarios__", report_id=report_id, market_id=market_id, outcome=outcome,
                  eligible=eligible, known_at=known_at, basis="attested",
                  processed_at="2026-03-02T09:00:00+00:00", model_p=None,
                  item_kind="scenario_set", source_kind="manual", **extra)


def _legacy_row(fid="F1", *, report_id="r-leg", market_id="m-1", yes_price=1.0,
                resolved_at="2026-07-03T00:00:00+00:00"):
    """A schema_version 1 row of the pre-EVAL-2 monitor."""
    return {"report_id": report_id, "forecast_id": fid, "market_id": market_id,
            "resolved_outcome": "Yes", "resolved_yes_price": yes_price, "model_p": 0.3,
            "market_p_at_research": 0.4, "brier_contribution": 0.49,
            "resolved_at": resolved_at, "schema_version": 1}


def _eligible_item(**over):
    item = {"resolution_status": "settled", "scoring_eligible": True, "prospective": True,
            "outcome": "YES", "outcome_known_at": "2026-01-10T15:00:00Z",
            "known_at_basis": "source", "processed_at": "2026-01-12T00:00:00+00:00"}
    item.update(over)
    return item


# ─────────────────────────────── the gate ────────────────────────────────────
def test_admissible_strict_same_day():
    item = _eligible_item()
    assert fr.admissible(item, "2026-01-10") == (False, "known_on_or_after_as_of")
    assert fr.admissible(item, "2026-01-11") == (True, None)
    # An offset-aware as_of names the UTC day it falls on (2026-01-10 here).
    assert fr.admissible(item, "2026-01-11T03:00:00+05:00") == (False, "known_on_or_after_as_of")
    assert fr.admissible(item, datetime(2026, 1, 11, tzinfo=timezone.utc).date()) == (True, None)
    for as_of in ("2026-01", "Jan 11 2026", "2026-01-11T00:00:00"):
        assert fr.admissible(item, as_of) == (False, "unverifiable_as_of")
    # Naive, partial or missing known-at stamps are never guessed.
    for stamp in ("2026-01-10T15:00:00", "2026-01", "", None, "yesterday"):
        assert fr.admissible(_eligible_item(outcome_known_at=stamp), "2026-02-01") == \
            (False, "unverifiable_stamp")
    # The upper-bound basis reads processed_at, never outcome_known_at.
    upper = _eligible_item(known_at_basis="processing_upper_bound",
                           outcome_known_at="2026-01-01T00:00:00Z")
    assert fr.admissible(upper, "2026-01-12") == (False, "known_on_or_after_as_of")
    assert fr.admissible(upper, "2026-01-13") == (True, None)
    assert fr.admissible(dict(upper, processed_at=None), "2026-02-01") == \
        (False, "unverifiable_stamp")
    # A bare-date known-at counts at the end of its day: never admitted before that day is over.
    dated = _eligible_item(known_at_basis="attested", outcome_known_at="2026-01-10")
    assert fr.admissible(dated, "2026-01-10") == (False, "known_on_or_after_as_of")
    assert fr.admissible(dated, "2026-01-11") == (True, None)
    evening = datetime(2026, 1, 10, 20, 0, tzinfo=timezone.utc)
    assert fr.admissible(dated, now=evening) == (False, "known_after_now")
    assert fr.admissible(item, now=evening) == (True, None)
    assert fr.admissible(item, now=datetime(2026, 1, 10, 14, 0, tzinfo=timezone.utc)) == \
        (False, "known_after_now")
    assert fr.admissible(item) == (True, None)  # default clock: the real UTC now
    with pytest.raises(ValueError):
        fr.admissible(item, now=datetime(2026, 1, 11))
    # Eligibility, prospectivity and conflicts fail closed before any stamp is read.
    assert fr.admissible(_eligible_item(resolution_status="conflict"), "2026-02-01") == \
        (False, "conflict")
    assert fr.admissible(_eligible_item(scoring_eligible=False,
                                        ineligible_reason="ambiguous_settlement")) == \
        (False, "ambiguous_settlement")
    assert fr.admissible(_eligible_item(scoring_eligible="true")) == \
        (False, "not_scoring_eligible")
    assert fr.admissible(_eligible_item(prospective="unknown")) == (False, "not_prospective")
    assert fr.admissible(None) == (False, "not_an_item")


# ─────────────────────────────── the fold ────────────────────────────────────
def test_fold_precedence_and_conflict():
    events = [
        # F1: eligible settled beats an ineligible settlement and a terminal.
        _terminal("F1"),
        _event("F1", market_id="m-near", outcome="NO", eligible=False, reason="equivalence_near"),
        _event("F1"),
        # F2: ineligible settled beats a terminal.
        _event("F2", eligible=False, reason="not_prospective", prospective=False),
        _terminal("F2"),
        # F3: a terminal alone.
        _terminal("F3"),
        # F4: two eligible settlements disagree → conflict.
        _event("F4", market_id="m-a", outcome="YES"),
        _event("F4", market_id="m-b", outcome="NO"),
        # F5: two eligible settlements agree → the earliest known-at is the upper bound.
        _event("F5", market_id="m-late", known_at="2026-08-01T00:00:00+00:00"),
        _event("F5", market_id="m-early", known_at="2026-07-01T00:00:00+00:00"),
        # Not binary items: ignored by the binary fold.
        _scenario_event(),
        "not a row",
    ]
    before = copy.deepcopy(events)
    items = fr.fold_binary_items(events)
    assert events == before  # inputs never mutated
    assert set(items) == {("r1", f"F{n}") for n in range(1, 6)}
    f1 = items[("r1", "F1")]
    assert (f1["resolution_status"], f1["outcome"], f1["market_id"], f1["n_events"]) == \
        ("settled", "YES", "m-1", 3)
    assert fr.admissible(f1, "2026-07-03") == (True, None)
    f2 = items[("r1", "F2")]
    assert (f2["resolution_status"], f2["scoring_eligible"]) == ("settled", False)
    assert fr.admissible(f2) == (False, "not_prospective")
    assert items[("r1", "F3")]["resolution_status"] == "terminal"
    assert fr.admissible(items[("r1", "F3")]) == (False, "unresolvable_after_grace")
    f4 = items[("r1", "F4")]
    assert (f4["resolution_status"], f4["outcome"], f4["scoring_eligible"]) == \
        ("conflict", None, False)
    assert f4["conflicting_outcomes"] == ["NO", "YES"]
    assert fr.admissible(f4, "2026-12-31") == (False, "conflict")
    f5 = items[("r1", "F5")]
    assert (f5["market_id"], f5["outcome_known_at"]) == ("m-early", "2026-07-01T00:00:00+00:00")
    # The fold never depends on the order events were appended.
    assert fr.fold_binary_items(list(reversed(events))) == items
    # Even events tied on known-at, processed_at and market id fold to one fact.
    twins = [_event("F6", model_p=0.2), _event("F6", model_p=0.9)]
    assert fr.fold_binary_items(twins) == fr.fold_binary_items(twins[::-1])
    assert fr.fold_binary_items(twins)[("r1", "F6")]["model_p"] == 0.2


def test_legacy_rows_need_v2_target_proof():
    binary = _binary("F1")
    target = _commit_row("r-leg", binaries=[binary])
    legacy = _legacy_row()
    # Without a v2 target nothing proves the market matched the binary: ineligible.
    (item,) = fr.fold_binary_items([legacy]).values()
    assert (item["scoring_eligible"], item["ineligible_reason"]) == (False, "no_v2_target")
    assert (item["known_at_basis"], item["processed_at"], item["legacy"]) == \
        ("processing_upper_bound", legacy["resolved_at"], True)
    # With the production primary target: exact anchor + research price inside (0.01, 0.99)
    # and a market end after the as-of date prove it.
    (item,) = fr.fold_binary_items([legacy], targets=[target]).values()
    assert (item["scoring_eligible"], item["prospective"], item["outcome"], item["y"]) == \
        (True, True, "YES", 1)
    assert fr.admissible(item, "2026-07-03") == (False, "known_on_or_after_as_of")
    assert fr.admissible(item, "2026-07-04") == (True, None)

    def reason(row, targets):
        (folded,) = fr.fold_binary_items([row], targets=targets).values()
        assert folded["scoring_eligible"] is False
        return folded["ineligible_reason"]

    assert reason(legacy, [_commit_row("r-leg", binaries=[_binary(equivalence="near")])]) == \
        "equivalence_near"
    assert reason(legacy, [_commit_row("r-leg", binaries=[_binary(price=0.995)])]) == \
        "prospective_unknown"
    assert reason(legacy, [_commit_row("r-leg", binaries=[_binary(market_id="m-2")])]) == \
        "market_mismatch"
    assert reason(legacy, [_commit_row("r-leg", binaries=[binary], role="revision")]) == \
        "no_v2_target"
    assert reason(legacy, [_commit_row("r-leg", binaries=[binary], record_class="ensemble_member")]) \
        == "no_v2_target"
    # Two primary rows registering the same item prove nothing.
    twin = _commit_row("r-leg", commit_id="c-2", binaries=[binary])
    assert reason(legacy, [target, twin]) == "no_v2_target"
    assert reason(_legacy_row(yes_price=0.6), [target]) == "not_converged"
    assert reason(dict(_legacy_row(yes_price=None), resolved_outcome=None), [target]) == \
        "no_yes_outcome"
    (no_price,) = fr.fold_binary_items([dict(_legacy_row(yes_price=None),
                                             resolved_outcome="No")], targets=[target]).values()
    assert (no_price["outcome"], no_price["scoring_eligible"]) == ("NO", True)
    # A naive legacy stamp stays unverifiable even when the target proves eligibility.
    (naive,) = fr.fold_binary_items([_legacy_row(resolved_at="2026-07-03T00:00:00")],
                                    targets=[target]).values()
    assert naive["scoring_eligible"] is True
    assert fr.admissible(naive, "2026-12-31") == (False, "unverifiable_stamp")


def test_resolved_view_fills_copies_and_never_mutates():
    primary = _commit_row("r1")
    other = _commit_row("r2", commit_id="c-2")
    revision = _commit_row("r1", commit_id="c-3", role="revision")
    legacy = {"report_id": "legacy", "resolved": True, "outcome": "Adopted",
              "scenarios": copy.deepcopy(SCENARIOS)}
    events = [_scenario_event(), _scenario_event(report_id="r2", target_commit_id="c-other"),
              _event("F1")]
    entries = [primary, other, revision, legacy]
    snapshot = copy.deepcopy((entries, events))
    view = fr.resolved_view(entries, events)
    assert (entries, events) == snapshot
    assert [row["commit_id"] for row in view] == ["c-1", "c-2"]
    filled, unbound = view
    assert (filled["resolved"], filled["outcome"], filled["known_at_basis"],
            filled["scoring_eligible"], filled["prospective"], filled["resolution_status"]) == \
        (True, "Adopted", "attested", True, True, "settled")
    assert filled["outcome_known_at"] == "2026-03-01T00:00:00+00:00"
    # An event naming another commit never labels this one; a hand-marked row never counts.
    assert (unbound["resolved"], unbound["outcome"]) == (False, None)
    marked = dict(primary, resolved=True, outcome="Adopted")
    (reset,) = fr.resolved_view([marked], [])
    assert (reset["resolved"], reset["outcome"], reset["scoring_eligible"]) == (False, None, False)
    # Disagreeing attestations make a conflict row.
    (conflict,) = fr.resolved_view([primary], [_scenario_event("Adopted"),
                                               _scenario_event("Stalled", market_id="m-x")])
    assert (conflict["resolved"], conflict["resolution_status"], conflict["outcome"]) == \
        (True, "conflict", None)
    # An attestation binds to exactly one production primary row, never scored twice.
    twin = _commit_row("r1", commit_id="c-9")
    for row in fr.resolved_view([primary, twin], [_scenario_event()]):
        assert (row["resolved"], row["outcome"], row["scoring_eligible"],
                row["ineligible_reason"]) == (True, None, False, "ambiguous_target")
        assert fr.admissible(row, "2026-12-31") == (False, "ambiguous_target")
    twins = fl.calibration_summary(entries=[primary, twin], events=[_scenario_event()],
                                   fold_settlements=True)
    assert (twins["n_resolved"], twins["excluded"]) == (0, {"ambiguous_target": 2})
    # Naming the commit resolves the ambiguity; the untargeted attestation still binds nowhere.
    named, bare = fr.resolved_view([primary, twin], [_scenario_event(target_commit_id="c-1"),
                                                     _scenario_event("Stalled", market_id="m-x")])
    assert (named["outcome"], named["scoring_eligible"], named["resolution_status"]) == \
        ("Adopted", True, "settled")
    assert (bare["outcome"], bare["ineligible_reason"]) == (None, "ambiguous_target")
    # A commit id two primary rows share is no target either.
    dup = fr.resolved_view([primary, copy.deepcopy(primary)],
                           [_scenario_event(target_commit_id="c-1")])
    assert [row["ineligible_reason"] for row in dup] == ["ambiguous_target"] * 2


# ─────────────────────── scenario calibration consumers ──────────────────────
def test_calibration_summary_fold_toggle(monkeypatch, tmp_path):
    assert Config.FORECAST_LEDGER_SETTLEMENT_FOLD is False
    row = _commit_row("r1")
    event = _scenario_event()
    assert fl.calibration_summary(entries=[row], events=[event])["n_resolved"] == 0
    folded = fl.calibration_summary(entries=[row], events=[event], fold_settlements=True)
    assert folded["n_resolved"] == 1 and folded["excluded"] == {}
    expected = calibration_report([{"forecast": {"scenarios": SCENARIOS}, "outcome": "Adopted"}])
    assert folded["mean_brier"] == expected["mean_brier"]
    monkeypatch.setattr(Config, "FORECAST_LEDGER_SETTLEMENT_FOLD", True)
    assert fl.calibration_summary(entries=[row], events=[event])["n_resolved"] == 1
    # The evaluation lane never folds unless asked (its golden rows hold no events).
    golden = {"report_id": "golden:q1", "resolved": True, "outcome": "YES", "golden": True,
              "record_class": "evaluation", "characterization_only": True,
              "scenarios": [{"name": "YES", "probability": 0.8}, {"name": "NO", "probability": 0.2}]}
    assert fl.calibration_summary(entries=[golden], include_evaluation=True)["n_resolved"] == 1
    monkeypatch.setattr(Config, "FORECAST_LEDGER_SETTLEMENT_FOLD", False)
    # Explicit entries without events never read the resolutions file.
    read_resolutions = fl.read_market_resolutions
    monkeypatch.setattr(fl, "read_market_resolutions",
                        lambda *a, **k: pytest.fail("resolutions.jsonl read for explicit entries"))
    assert fl.calibration_summary(entries=[row], fold_settlements=True)["n_resolved"] == 0
    monkeypatch.setattr(fl, "read_market_resolutions", read_resolutions)
    # From disk: the ledger and resolutions.jsonl in one directory.
    d = str(tmp_path / "led")
    os.makedirs(d)
    with open(os.path.join(d, "ledger.jsonl"), "w", encoding="utf-8") as fh:
        fh.write(json.dumps(row) + "\n")
    extra = {k: v for k, v in event.items() if k not in (
        "report_id", "forecast_id", "market_id", "resolved_outcome", "resolved_yes_price",
        "model_p", "market_p_at_research", "brier_contribution", "resolved_at")}
    assert fl.append_market_resolution(
        report_id="r1", forecast_id="__scenarios__", market_id="manual", resolved_outcome=None,
        model_p=None, market_p_at_research=None, brier_contribution=None,
        resolved_at=event["resolved_at"], d=d, extra=extra) is not None
    assert fl.calibration_summary(d)["n_resolved"] == 0
    assert fl.calibration_summary(d, fold_settlements=True)["n_resolved"] == 1
    # The point-in-time cut: known 2026-03-01T00:00Z is inadmissible on that very day.
    assert fl.calibration_summary(d, fold_settlements=True, as_of="2026-03-01") == {
        "n_resolved": 0, "mean_brier": None, "calibration_error": None,
        "n_excluded_unscoreable": 0, "excluded": {"known_on_or_after_as_of": 1}}
    assert fl.calibration_summary(d, fold_settlements=True, as_of="2026-03-02")["n_resolved"] == 1
    # Under the fold, legacy resolved rows carry no settlement facts: excluded and counted.
    legacy = {"report_id": "legacy", "resolved": True, "outcome": "Adopted",
              "scenarios": copy.deepcopy(SCENARIOS)}
    out = fl.calibration_summary(entries=[row, legacy], events=[event], fold_settlements=True)
    assert out["n_resolved"] == 1 and out["excluded"] == {"not_production_primary": 1}
    # ... even one that declares settlement facts itself, and a commit row without a role:
    # rows outside the view are never read for eligibility or stamps.
    forged = dict(legacy, scoring_eligible=True, prospective=True, known_at_basis="attested",
                  outcome_known_at="2026-01-01T00:00:00Z", resolution_status="settled")
    roleless = dict(forged, row_type="commit", schema_version=2, commit_id="c-x",
                    record_class="production")
    for entries in ([forged], [roleless], [forged, roleless]):
        out = fl.calibration_summary(entries=entries, events=[event], fold_settlements=True)
        assert (out["n_resolved"], out["excluded"]) == \
            (0, {"not_production_primary": len(entries)})
    # A revision stays silent, exactly as before (record-class rule).
    revision = dict(forged, row_type="commit", calibration_role="revision")
    assert fl.calibration_summary(entries=[revision], events=[event],
                                  fold_settlements=True)["excluded"] == {}
    # An as_of alone applies the gate to the raw rows (fold off): the same exclusion.
    assert fl.calibration_summary(entries=[legacy], as_of="2026-03-02")["excluded"] == \
        {"not_scoring_eligible": 1}


def test_unmatched_outcome_excluded_and_counted():
    def row(rid, outcome, probs=(0.7, 0.3), names=("Adopted", "Stalled"), **extra):
        base = {"report_id": rid, "resolved": True, "outcome": outcome,
                "scenarios": [{"name": n, "probability": p} for n, p in zip(names, probs, strict=True)]}
        base.update(extra)
        return base

    clean = [row("r1", "Adopted"), row("r2", " stalled. ", probs=(0.4, 0.6))]
    unmatched = row("r3", "Withdrawn")
    with_unmatched = clean[:1] + [unmatched] + clean[1:]
    out = fl.calibration_summary(entries=with_unmatched)
    ref = fl.calibration_summary(entries=clean)
    assert out["n_excluded_unscoreable"] == 1 and out["excluded"] == {"unmatched_outcome": 1}
    assert {k: out[k] for k in ("n_resolved", "mean_brier", "calibration_error")} == \
        {k: ref[k] for k in ("n_resolved", "mean_brier", "calibration_error")}
    assert ref["n_excluded_unscoreable"] == 0 and ref["excluded"] == {}
    # Before EVAL-3 the unmatched row was scored as an all-miss.
    legacy = calibration_report([{"forecast": {"scenarios": e["scenarios"]},
                                  "outcome": e["outcome"]} for e in with_unmatched])
    assert legacy["n"] == 3 and legacy["mean_brier"] != out["mean_brier"]
    # Ambiguous outcomes, unsettled statuses and outcome-less rows never score either.
    ambiguous = row("r4", "Adopted", names=("Adopted", "adopted."))
    unsettled = row("r5", "Adopted", resolution_status="ambiguous")
    blank = row("r6", "")
    mixed = fl.calibration_summary(entries=[*with_unmatched, ambiguous, unsettled, blank])
    assert mixed["n_resolved"] == 2 and mixed["n_excluded_unscoreable"] == 4
    assert mixed["excluded"] == {"ambiguous_outcome": 1, "no_outcome": 1, "not_settled": 1,
                                 "unmatched_outcome": 1}
    assert fr.is_scoreable_resolution(clean[1]) is True
    assert fr.is_scoreable_resolution(dict(clean[0], resolution_status="settled")) is True
    assert [fr.unscoreable_reason(e) for e in (unmatched, ambiguous, unsettled, blank)] == \
        ["unmatched_outcome", "ambiguous_outcome", "not_settled", "no_outcome"]
    assert fr.unscoreable_reason(dict(clean[0], resolved=False)) == "not_resolved"
    # Record-class exclusions stay silent, exactly as before.
    golden = row("golden:q1", "Adopted", golden=True)
    assert fl.calibration_summary(entries=[*clean, golden]) == ref


def test_recalibration_param_same_gate():
    assert Config.REPORT_RECALIBRATE_FROM_LEDGER is False
    row = _commit_row("r1")
    unmatched = {"report_id": "r9", "resolved": True, "outcome": "Withdrawn",
                 "scenarios": copy.deepcopy(SCENARIOS)}
    events = [_scenario_event()]
    base = fl.recalibration_param(entries=[row], events=events)
    assert (base["n"], base["enabled"], base["excluded"]) == (0, False, {})
    folded = fl.recalibration_param(entries=[row, unmatched], events=events,
                                    fold_settlements=True)
    # One admitted forecast with two scenarios → two (logit, hit) points; thin → identity.
    assert (folded["n"], folded["slope"], folded["fitted"]) == (2, 1.0, False)
    assert folded["excluded"] == {"not_production_primary": 1}
    same_day = fl.recalibration_param(entries=[row], events=events, fold_settlements=True,
                                      as_of="2026-03-01")
    assert (same_day["n"], same_day["excluded"]) == (0, {"known_on_or_after_as_of": 1})
    for as_of in (None, "2026-03-01", "2026-03-02"):
        summary = fl.calibration_summary(entries=[row, unmatched], events=events,
                                         fold_settlements=True, as_of=as_of)
        recal = fl.recalibration_param(entries=[row, unmatched], events=events,
                                       fold_settlements=True, as_of=as_of)
        assert recal["excluded"] == summary["excluded"]
        assert recal["n_excluded_unscoreable"] == summary["n_excluded_unscoreable"]
        assert recal["n"] == 2 * summary["n_resolved"]
    # The unfolded fit drops the unmatched row too (scoreability is unconditional).
    unfolded = fl.recalibration_param(entries=[unmatched])
    assert (unfolded["n"], unfolded["n_excluded_unscoreable"]) == (0, 1)


# ─────────────────────────── binary calibration ──────────────────────────────
def test_binary_calibration_summary_scale_and_exclusions():
    events = [
        _event("F1", outcome="YES", model_p=0.7),
        _event("F2", outcome="NO", model_p=0.2),
        _event("F3", eligible=False, prospective=False, reason="not_prospective"),
        _event("F4", eligible=False, reason="equivalence_near"),
        _event("F5", market_id="m-a", outcome="YES"),
        _event("F5", market_id="m-b", outcome="NO"),
        _event("F6", outcome=None, eligible=False, status="ambiguous",
               reason="ambiguous_settlement"),
        _terminal("F7"),
        _event("F8", model_p=None),
        _event("F9", known_at="2026-07-02T15:30:00"),  # naive: unverifiable
        _scenario_event(),
    ]
    out = fl.binary_calibration_summary(events=events, entries=[])
    assert out["scale"] == "binary" and out["as_of"] is None
    assert out["n_resolved"] == 2
    # Binary Brier: ((0.7 - 1)^2 + (0.2 - 0)^2) / 2 = 0.065 (half the multi-class sum).
    assert out["mean_brier"] == pytest.approx(0.065)
    assert out["excluded"] == {"ambiguous_settlement": 1, "conflict": 1, "equivalence_near": 1,
                               "invalid_model_probability": 1, "not_prospective": 1,
                               "unresolvable_after_grace": 1, "unverifiable_stamp": 1}
    pair = calibration_report([
        {"forecast": {"scenarios": [{"name": "YES", "probability": 0.7},
                                    {"name": "NO", "probability": 0.3}]}, "outcome": "YES"},
        {"forecast": {"scenarios": [{"name": "YES", "probability": 0.2},
                                    {"name": "NO", "probability": 0.8}]}, "outcome": "NO"}])
    assert pair["mean_brier"] == pytest.approx(2 * out["mean_brier"])
    assert out["calibration_error"] == pair["calibration_error"]
    # The as_of cut: known 2026-07-02T15:30Z is inadmissible for as_of 2026-07-02.
    cut = fl.binary_calibration_summary(events=events, entries=[], as_of="2026-07-02")
    assert cut["n_resolved"] == 0 and cut["as_of"] == "2026-07-02"
    assert cut["excluded"]["known_on_or_after_as_of"] == 3  # F1, F2 and F8
    assert fl.binary_calibration_summary(events=events, entries=[],
                                         as_of="2026-07-03")["n_resolved"] == 2
    # An eligible item whose status is not 'settled' is never scored.
    unknown = fl.binary_calibration_summary(events=[_event("F1", status="unknown")], entries=[])
    assert (unknown["n_resolved"], unknown["excluded"]) == (0, {"not_settled": 1})
    # From disk: resolutions.jsonl + ledger.jsonl of the default (per-test) ledger dir.
    empty = fl.binary_calibration_summary()
    assert (empty["n_resolved"], empty["mean_brier"], empty["excluded"]) == (0, None, {})


# ─────────────────────────────── the monitor ─────────────────────────────────
class _Client:
    def __init__(self, resolutions):
        self._resolutions = resolutions

    def requote_markets(self, rows):
        return [dict(r, implied_yes_prob=r.get("price_at_research"), price_delta=0.0)
                for r in rows]

    def fetch_resolutions(self, ids):
        return {mid: self._resolutions[mid] for mid in ids if mid in self._resolutions}


def _gamma(market_id, yes):
    from app.utils import prediction_markets as pm
    return pm._parse_resolution({
        "id": market_id, "question": "q", "outcomes": '["Yes","No"]',
        "outcomePrices": json.dumps([str(yes), str(round(1 - yes, 4))]), "closed": True,
        "umaResolutionStatus": "resolved", "endDate": "2026-06-30T12:00:00Z",
        "closedTime": "2026-07-02T15:30:00Z"})


def test_monitor_folded_calibration_after_eligible_settlement(tmp_path, capsys):
    led = fl.ledger_dir()
    folder = str(tmp_path / "report")
    forecast = {"horizon": "2026", "scenarios": copy.deepcopy(SCENARIOS),
                "binary_forecasts": [_binary("F1", probability=0.3),
                                     _binary("F2", market_id="m-near", equivalence="near")]}
    client = _Client({"m-1": _gamma("m-1", 1.0), "m-near": _gamma("m-near", 0.0)})
    assert fl.binary_calibration_summary(led)["n_resolved"] == 0
    res = mon.run_monitor("r1", forecast=forecast, report_folder=folder, client=client,
                          ledger_dir=led, as_of=PROCESSED,
                          publishable_fn=lambda rid: True, target_meta=META)
    assert res["settlement"]["settled_eligible"] == 1
    # The unfolded scenario calibration can never see a market settlement ...
    assert fl.calibration_summary(led)["n_resolved"] == 0
    # ... the folded binary calibration does, point-in-time gated, scored on the 0-1 scale.
    binary = res["binary_calibration"]
    assert binary["n_resolved"] == 1 and binary["mean_brier"] == pytest.approx(0.49)
    assert binary["excluded"] == {"equivalence_near": 1}
    assert res["calibration"]["n_resolved"] == 0 and res["calibration"]["excluded"] == {}
    md = res["monitor_report_md"]
    assert ("- Market-resolved binary forecasts (all settlements, ungated; not calibration): "
            "**2**; mean Brier (binary, 0-1): **") in md
    assert "- Scenario forecasts resolved: **0**; mean Brier (multi-class sum, 0-2): **—**" in md
    assert ("- Binary forecasts scored (settlement fold, point-in-time gate): **1**; "
            "mean Brier (binary, 0-1): **0.49**") in md
    assert "- Binary forecasts excluded from calibration: equivalence_near 1" in md
    assert "- Scenario forecasts excluded from calibration: —" in md
    # `summary` prints the same folded numbers.
    assert mon.main(["summary"]) == 0
    out = capsys.readouterr().out
    printed = json.loads(out[out.index("{\n"):] if not out.startswith("{") else out)
    assert printed["binary_calibration"]["n_resolved"] == 1
    assert printed["scenario_calibration"]["n_resolved"] == 0


def test_monitor_primary_predicate_is_the_ledgers():
    rows = [_commit_row("r1"), _commit_row("r1", role="revision"),
            _commit_row("r1", record_class="ensemble_member"), dict(_commit_row("r1"), golden=True),
            {"report_id": "legacy", "resolved": True}, None, "row"]
    assert [mon._is_production_primary(r) for r in rows] == \
        [fl.is_production_primary_commit(r) for r in rows] == \
        [True, False, False, False, False, False, False]


def test_monitor_render_without_binary_block_keeps_legacy_lines():
    kwargs = {"report_id": "r1", "as_of": "2026-09-29", "movers": [], "resolution_records": [],
              "needs_manual": [], "calibration": {}, "market_brier": {}, "anchored_count": 0,
              "degraded": False}
    md = mon.render_monitor_md(**kwargs)
    assert "Binary forecasts scored" not in md and "excluded from calibration" not in md
    assert mon.render_monitor_md(**kwargs, binary_calibration=None) == md


# ─────────────────────────────── report path ─────────────────────────────────
def _legacy_block(forecast, cs):
    """The report path's calibration block before EVAL-3, verbatim, as the reference."""
    if cs.get("n_resolved"):
        forecast["historical_calibration"] = cs
        note = (f"历史校准：已解析 {cs['n_resolved']} 个预测，平均 Brier "
                f"{cs.get('mean_brier')}，校准误差 {cs.get('calibration_error')}")
        forecast["confidence_rationale"] = (
            (str(forecast.get("confidence_rationale") or "").strip()
             + " ｜" + note).strip(" ｜"))


def _agent(**over):
    agent = ReportAgent.__new__(ReportAgent)
    for key, value in over.items():
        setattr(agent, key, value)
    return agent


def _base_forecast():
    return {"question": "q", "scenarios": copy.deepcopy(SCENARIOS), "confidence": "medium",
            "confidence_rationale": "Evidence is mixed."}


def test_report_path_byte_identical_when_fold_off(monkeypatch):
    assert Config.FORECAST_LEDGER_SETTLEMENT_FOLD is False
    legacy_summary = {"n_resolved": 3, "mean_brier": 0.2, "calibration_error": 0.1}
    summary = dict(legacy_summary, n_excluded_unscoreable=1, excluded={"unmatched_outcome": 1})
    calls = []
    monkeypatch.setattr(fl, "calibration_summary",
                        lambda *a, **k: calls.append((a, k)) or dict(summary))
    monkeypatch.setattr(fl, "binary_calibration_summary",
                        lambda *a, **k: pytest.fail("binary calibration read with the fold off"))
    agent = _agent(ledger_context={"as_of_date": "2026-03-02"}, actors=None)
    forecast = _base_forecast()
    agent._attach_historical_calibration(forecast)
    assert calls == [((), {})]  # exactly today's call
    reference = _base_forecast()
    _legacy_block(reference, dict(legacy_summary))
    dump = lambda f: json.dumps(f, ensure_ascii=False, indent=2)  # noqa: E731
    assert dump(forecast) == dump(reference)
    assert forecast["confidence_rationale"] == \
        "Evidence is mixed. ｜历史校准：已解析 3 个预测，平均 Brier 0.2，校准误差 0.1"
    # Nothing resolved → forecast untouched, as before.
    monkeypatch.setattr(fl, "calibration_summary",
                        lambda *a, **k: {"n_resolved": 0, "mean_brier": None,
                                         "calibration_error": None,
                                         "n_excluded_unscoreable": 2, "excluded": {"x": 2}})
    untouched = _base_forecast()
    agent._attach_historical_calibration(untouched)
    assert untouched == _base_forecast()
    # A failing read is degrade-safe.
    monkeypatch.setattr(fl, "calibration_summary", lambda *a, **k: 1 / 0)
    failed = _base_forecast()
    agent._attach_historical_calibration(failed)
    assert failed == _base_forecast()


def test_report_path_fold_on_passes_as_of(monkeypatch):
    monkeypatch.setattr(Config, "FORECAST_LEDGER_SETTLEMENT_FOLD", True)
    calls, binary_calls = [], []
    scenario = {"n_resolved": 2, "mean_brier": 0.3, "calibration_error": 0.05,
                "n_excluded_unscoreable": 0, "excluded": {"not_prospective": 1}}
    binary = {"n_resolved": 4, "mean_brier": 0.12, "calibration_error": 0.02, "excluded": {},
              "as_of": "2026-03-02", "scale": "binary"}
    monkeypatch.setattr(fl, "calibration_summary",
                        lambda *a, **k: calls.append((a, k)) or dict(scenario))
    monkeypatch.setattr(fl, "binary_calibration_summary",
                        lambda *a, **k: binary_calls.append((a, k)) or dict(binary))
    forecast = _base_forecast()
    _agent(ledger_context={"as_of_date": "2026-03-02"},
           actors={"as_of_date": "2026-01-01"})._attach_historical_calibration(forecast)
    assert calls == [((), {"as_of": "2026-03-02"})]
    assert binary_calls == [((), {"as_of": "2026-03-02"})]
    block = forecast["historical_calibration"]
    assert block == dict(scenario, as_of="2026-03-02", scale="multiclass_sum", binary=binary)
    assert forecast["confidence_rationale"].endswith(
        "｜历史校准：已解析 2 个预测，平均 Brier 0.3，校准误差 0.05")
    # as_of source order: ledger context, else strict actors date, else None.
    for agent, expected in (
            (_agent(ledger_context={"as_of_date": "bad"}, actors={"as_of_date": "2026-01-01"}),
             "2026-01-01"),
            (_agent(ledger_context=None, actors={"as_of_date": "January 2026"}), None),
            (_agent(ledger_context={"as_of_date": "2999-01-01"}), None),
            (_agent(), None)):
        calls.clear()
        agent._attach_historical_calibration(_base_forecast())
        assert calls == [((), {"as_of": expected})]
    # Only binary settlements scored: the block is written, the rationale is unchanged.
    monkeypatch.setattr(fl, "calibration_summary",
                        lambda *a, **k: dict(scenario, n_resolved=0, mean_brier=None))
    binary_only = _base_forecast()
    _agent()._attach_historical_calibration(binary_only)
    assert binary_only["historical_calibration"]["binary"]["n_resolved"] == 4
    assert binary_only["confidence_rationale"] == "Evidence is mixed."


def test_report_path_fold_end_to_end(monkeypatch):
    """Real ledger files: a scenario attestation and an eligible market settlement."""
    led = fl.ledger_dir()
    os.makedirs(led, exist_ok=True)
    row = _commit_row("r1", binaries=[_binary("F1")])
    with open(os.path.join(led, "ledger.jsonl"), "w", encoding="utf-8") as fh:
        fh.write(json.dumps(row) + "\n")
    with open(os.path.join(led, "resolutions.jsonl"), "w", encoding="utf-8") as fh:
        for event in (_scenario_event(), _event("F1", model_p=0.3)):
            fh.write(json.dumps(event) + "\n")
    agent = _agent(ledger_context={"as_of_date": "2026-07-03"})
    off = _base_forecast()
    agent._attach_historical_calibration(off)
    assert off == _base_forecast()  # commit rows are never resolved on disk
    monkeypatch.setattr(Config, "FORECAST_LEDGER_SETTLEMENT_FOLD", True)
    on = _base_forecast()
    agent._attach_historical_calibration(on)
    block = on["historical_calibration"]
    assert (block["n_resolved"], block["as_of"], block["binary"]["n_resolved"]) == \
        (1, "2026-07-03", 1)
    assert block["binary"]["mean_brier"] == pytest.approx(0.49)
    # A report dated on the settlement day sees neither (same-day exclusion).
    same_day = _base_forecast()
    _agent(ledger_context={"as_of_date": "2026-03-01"})._attach_historical_calibration(same_day)
    assert same_day == _base_forecast()


def _legacy_calibration_summary(entries):
    """The pre-EVAL-3 calibration_summary selection, verbatim, as the reference."""
    resolved = [
        {"forecast": {"scenarios": e.get("scenarios")}, "outcome": e.get("outcome")}
        for e in entries
        if e.get("resolved") and e.get("outcome") and e.get("scenarios")
        and fl.is_production_calibration_row(e)
    ]
    if not resolved:
        return {"n_resolved": 0, "mean_brier": None, "calibration_error": None}
    rep = calibration_report(resolved)
    return {"n_resolved": len(resolved), "mean_brier": rep.get("mean_brier"),
            "calibration_error": rep.get("calibration_error")}


@pytest.fixture
def report_env(monkeypatch, tmp_path):
    monkeypatch.setattr(Config, "UPLOAD_FOLDER", str(tmp_path), raising=False)
    monkeypatch.setattr(ReportManager, "REPORTS_DIR", str(tmp_path / "reports"), raising=False)
    monkeypatch.setattr(Config, "PIPELINE_DATA_DIR", str(tmp_path / "pipelines"), raising=False)
    monkeypatch.setattr(Config, "REPORT_FORECAST_LEDGER", True, raising=False)
    monkeypatch.setattr(Config, "FORECAST_LEDGER_COMMIT_MODE", "published", raising=False)
    er._finalize_env(monkeypatch, emit_binary=True)
    return tmp_path


def _finalize(report_id, agent):
    os.makedirs(ReportManager._get_report_folder(report_id), exist_ok=True)
    agent._finalize_structured_forecast(report_id, er.MARKDOWN)
    with open(os.path.join(ReportManager._get_report_folder(report_id), "forecast.json"),
              "rb") as fh:
        return fh.read()


def test_finalize_forecast_json_byte_identical_when_fold_off(report_env, monkeypatch):
    """forecast.json through the real finalize path equals the pre-EVAL-3 block's output
    when every resolved outcome matches a scenario; settlement events change nothing."""
    led = fl.ledger_dir()
    os.makedirs(led, exist_ok=True)
    resolved = [{"report_id": rid, "resolved": True, "outcome": outcome, "schema_version": 1,
                 "scenarios": copy.deepcopy(SCENARIOS)}
                for rid, outcome in (("old-1", "Adopted"), ("old-2", "stalled"))]
    with open(os.path.join(led, "ledger.jsonl"), "w", encoding="utf-8") as fh:
        for row in (*resolved, _commit_row("r1", binaries=[_binary("F1")])):
            fh.write(json.dumps(row) + "\n")
    with open(os.path.join(led, "resolutions.jsonl"), "w", encoding="utf-8") as fh:
        for event in (_scenario_event(), _event("F1", model_p=0.3)):
            fh.write(json.dumps(event) + "\n")
    monkeypatch.setattr(ReportAgent, "_resolve_evaluation_context", lambda self: None)
    monkeypatch.setattr(fe, "extract_binary_forecasts", er._fake_extract([]))
    agent_kwargs = {"ledger_context": {"as_of_date": "2026-07-03"}}
    new = _finalize("r_new", er._bare_agent(**agent_kwargs))
    forecast = json.loads(new)
    assert forecast["historical_calibration"] == _legacy_calibration_summary(resolved)
    assert forecast["historical_calibration"]["n_resolved"] == 2
    assert "历史校准：已解析 2 个预测" in forecast["confidence_rationale"]
    monkeypatch.setattr(
        ReportAgent, "_attach_historical_calibration",
        lambda self, fc: _legacy_block(fc, _legacy_calibration_summary(fl.read_ledger())))
    assert _finalize("r_ref", er._bare_agent(**agent_kwargs)) == new


def test_finalize_fold_on_evaluation_run_never_reads_calibration(report_env, monkeypatch):
    """EVAL-13 suppression wraps the fold: an evaluation run reads no calibration at all."""
    monkeypatch.setattr(Config, "FORECAST_LEDGER_SETTLEMENT_FOLD", True)
    binding = {"bound": {er.QID: "F1"}, "missing": [], "method": "normalized_equality",
               "repair_draw": "not_needed"}
    monkeypatch.setattr(fe, "extract_binary_forecasts",
                        er._fake_extract([], target_binding=binding))
    for name in ("calibration_summary", "binary_calibration_summary"):
        monkeypatch.setattr(fl, name, lambda *a, **k: pytest.fail(
            "production calibration read in an evaluation run"))
    forecast = json.loads(_finalize("r_eval", er._bare_agent(evaluation_context=er._pin())))
    assert "historical_calibration" not in forecast
    assert forecast["evaluation"]["historical_calibration_suppressed"] is True


def test_config_defaults_and_env_example():
    assert Config.FORECAST_LEDGER_SETTLEMENT_FOLD is False
    assert Config.REPORT_RECALIBRATE_FROM_LEDGER is False
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    with open(os.path.join(root, ".env.example"), encoding="utf-8") as fh:
        text = fh.read()
    assert "# FORECAST_LEDGER_SETTLEMENT_FOLD=false" in text
    assert "# REPORT_RECALIBRATE_FROM_LEDGER=false" in text
