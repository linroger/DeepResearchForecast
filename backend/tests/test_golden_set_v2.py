"""Offline tests for the golden-set v2 data contract (EVAL-9, candidate P17).

Covers app/services/golden_set.py (forecaster view, structural leak lint,
validation, evidence recompute with a pre-registered tolerance, balance audit),
the schema v2 hooks in backend/scripts/golden_eval.py (validation on load, the
recompute mismatch exit 4, ambiguous-row exclusions, v1 byte-identity) and the
backend/scripts/golden_curate.py audit CLI. No LLM, no network.
"""

import hashlib
import json
import os
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))

import golden_curate as gc  # noqa: E402
import golden_eval as ge  # noqa: E402

from app.services import golden_set as gs  # noqa: E402
from app.services.forecast_ledger import read_ledger  # noqa: E402

VISIBLE = {"id", "question", "resolution_criteria", "as_of_date"}
V2_ONLY_KEYS = ("resolution_note", "resolve_time", "resolve_time_precision", "scoring_status",
                "verification", "resolution_evidence", "event_cluster", "shift_axis",
                "hindsight_framed", "reviewed_parentheticals")
# sha256 of the score-forecast-file report (canonical JSON, tmp paths replaced) and of
# its markdown that the pre-EVAL-9 golden_eval (feat/finharness-transplants@57d0e65)
# wrote for the v1 fixture of test_golden_eval._legacy_fixture.
PRE_EVAL9_V1_REPORT_SHA256 = "e27154d37d685b673f707ce14fd62f7545dcae9af1bca2539cacd7341f750c6d"
PRE_EVAL9_V1_MARKDOWN_SHA256 = "05893386c1bc6167dedd004d1080debd83852f1a06bcfee9760ef1a5bd481b21"


@pytest.fixture(autouse=True)
def _no_ledger_opt_in(tmp_path, monkeypatch):
    from app.config import Config

    monkeypatch.setattr(Config, "FORECAST_LEDGER_DIR", str(tmp_path / "_forecast_ledger"), raising=False)
    monkeypatch.setattr(Config, "GOLDEN_EVAL_LEDGER", False, raising=False)


def _committed():
    with open(ge.GOLDEN_PATH, encoding="utf-8") as f:
        return json.load(f)


def _by_id():
    return {q["id"]: q for q in _committed()["questions"]}


def _v1_copy(questions):
    """The pre-EVAL-9 rows: v2 keys dropped, the outcome prose put back into the criteria."""
    rows = []
    for q in questions:
        row = {k: v for k, v in q.items() if k not in V2_ONLY_KEYS}
        note = q.get("resolution_note")
        if note:
            criteria = q["resolution_criteria"]
            row["resolution_criteria"] = (criteria[:-1] + " " + note + ".") if note.startswith("(") \
                else criteria + " " + note
        rows.append(row)
    return rows


def _seat_evidence(seats, **rule):
    return {"kind": "count_threshold", "source_url": "https://example.org/results-2030",
            "archived_url": "https://web.archive.org/web/2030/https://example.org/results-2030",
            "raw_value": {"seats": seats},
            "rule": {"field": "seats", "comparator": ">=", "threshold": 51, **rule}}


def _market_evidence(price):
    return {"kind": "market_settlement", "source_url": "https://example.org/market/blue-2030",
            "archived_url": None, "raw_value": {"resolved_yes_price": price}}


def _v2_row(**over):
    row = {
        "id": "blue-senate-2030",
        "question": "Will the Blue party win a majority of seats in the Senate in the 2030 election?",
        "resolution_criteria": "YES if the Blue caucus holds >=51 Senate seats after the 2030 general election.",
        "as_of_date": "2030-10-01", "resolved_outcome": True, "resolution_note": "They won 53.",
        "resolution_date": "2030-11-06", "resolve_time": "2030-11-06T23:59:59Z",
        "resolve_time_precision": "day", "scoring_status": "scored", "verification": "verified",
        "resolution_evidence": _seat_evidence(53), "event_cluster": "senate-2030", "shift_axis": "none",
        "hindsight_framed": False, "reviewed_parentheticals": [], "category": "elections",
        "difficulty": "medium",
    }
    row.update(over)
    return row


def _write(path, obj):
    path.write_text(json.dumps(obj), encoding="utf-8")
    return str(path)


def _v2_file(path, rows):
    return _write(path, {"_meta": {"schema_version": 2}, "questions": rows})


def _codes(findings):
    return sorted({f["code"] for f in findings})


# ---------------------------------------------------------------- committed set
def test_committed_fixture_v2_clean():
    data = _committed()
    questions = data["questions"]
    assert gs.schema_version(data) == gs.SCHEMA_VERSION == 2
    assert len(questions) == 30 == data["_meta"]["count"]
    assert ge.load_golden_set() == questions                       # v2 validation passes on load
    for q in questions:
        assert gs.leak_findings(q) == [], q["id"]
        assert gs.validate_question(q) == [], q["id"]
        assert q["verification"] == "legacy_unverified" and q["resolution_evidence"] is None
        assert q["resolve_time"] == q["resolution_date"] + "T23:59:59Z"
        assert q["resolve_time_precision"] == "day" and q["shift_axis"] == "none"
        assert q["scoring_status"] == "scored" and isinstance(q["resolved_outcome"], bool)
        assert gs.recompute_label(q) == gs.LABEL_UNVERIFIABLE and gs.recompute_mismatch(q) is None
    assert sum(q["resolved_outcome"] for q in questions) == 24     # answer-bearing, outcome kept inline

    clusters = {q["event_cluster"] for q in questions}
    assert len(clusters) == 23
    members = {c: sorted(q["id"] for q in questions if q["event_cluster"] == c) for c in clusters}
    assert members["fomc-2024-25"] == ["fed-2024-09-cut", "fed-2024-11-cut", "fed-2024-12-cut", "fed-2025-01-cut"]
    assert members["us-pres-2024"] == ["us-pres-2024-harris", "us-pres-2024-trump"]
    assert members["us-senate-2024"] == ["us-senate-2024-dem-hold", "us-senate-2024-gop"]
    assert members["uk-ge-2024"] == ["uk-ge-2024-labour", "uk-ge-2024-tory"]
    assert members["in-ge-2024"] == ["in-ge-2024-bjp-alone", "in-ge-2024-nda-majority"]
    assert sum(len(ids) == 1 and ids[0] == c for c, ids in members.items()) == 18   # singles use their id

    assert [q["id"] for q in questions if q["hindsight_framed"]] == ["openai-gpt4o-2024"]

    rows = _by_id()
    # outcome prose moved verbatim into the grader-only note (25 rows), true clauses reviewed
    assert sum(1 for q in questions if q["resolution_note"]) == 25
    assert rows["us-senate-2024-gop"]["resolution_note"] == "(they won 53)"
    assert rows["us-senate-2024-dem-hold"]["resolution_note"] == "They lost the majority."
    assert rows["in-ge-2024-bjp-alone"]["resolution_note"] == "It won 240 and needed NDA allies for a majority."
    assert rows["us-senate-2024-dem-hold"]["resolution_criteria"] == (
        "YES if the Democratic caucus holds >=50 seats (with VP tiebreak) after the 2024 election.")
    reviewed = {q["id"]: q["reviewed_parentheticals"] for q in questions if q["reviewed_parentheticals"]}
    assert reviewed == {"us-senate-2024-dem-hold": ["(with VP tiebreak)"],
                        "fr-legis-2024-rn-majority": ["(RN)"],
                        "id-pres-2024-prabowo": ["(>50%)"],
                        "in-ge-2024-bjp-alone": ["(272+ seats)"],
                        "oscars-2024-oppenheimer": ["(96th)"]}
    meta = data["_meta"]
    assert "forecast origin" in meta["as_of_semantics"] and "not a model knowledge cutoff" in meta["as_of_semantics"]
    assert "point-in-time" in meta["as_of_semantics"]
    assert set(meta["schema"]["forecaster_visible"]) == VISIBLE
    assert set(meta["schema"]["grader_only"]) == set(gs.GRADER_ONLY_FIELDS)
    assert "23 clusters" in meta["event_cluster_rule"]

    # the v1 text this migration replaced is reproduced exactly by re-inserting the notes
    v1 = {q["id"]: q for q in _v1_copy(questions)}
    assert v1["us-senate-2024-gop"]["resolution_criteria"] == (
        "YES if the Republican caucus holds >=51 Senate seats after the 2024 general election (they won 53).")
    assert v1["fed-2025-01-cut"]["resolution_criteria"].endswith("2025 meeting. It held rates steady.")


def test_balance_audit_is_report_only_on_committed_set():
    audit = gs.balance_audit(_committed()["questions"])
    assert set(audit) == {"n", "yes_rate", "category_shares", "n_event_clusters",
                          "clusters_with_multiple_questions", "lead_buckets", "advisory_violations"}
    assert (audit["n"], audit["yes_rate"], audit["n_event_clusters"]) == (30, 0.8, 23)
    assert audit["category_shares"]["elections"] == 0.3667
    assert len(audit["clusters_with_multiple_questions"]) == 5
    assert audit["lead_buckets"] == {"le30": 16, "d31_180": 13, "gt180": 1, "unknown": 0}
    assert [v["code"] for v in audit["advisory_violations"]] == [
        "category_share", "yes_rate", "cluster_size", "hindsight_framed"]
    # an ambiguous row never counts toward the YES rate
    rows = [_v2_row(id="a"), _v2_row(id="b", resolved_outcome=False),
            _v2_row(id="c", scoring_status="ambiguous", resolved_outcome=None)]
    assert gs.balance_audit(rows)["yes_rate"] == 0.5


# ------------------------------------------------------------ forecaster view
def test_forecaster_view_keys_exact():
    for q in _committed()["questions"]:
        view = gs.forecaster_view(q)
        assert set(view) == VISIBLE
        assert view == {k: q[k] for k in VISIBLE}
        blob = json.dumps(view)
        assert "resolved_outcome" not in blob and "resolution_note" not in blob
        if q["resolution_note"]:
            assert q["resolution_note"] not in blob
    view = gs.forecaster_view({"id": "x", "resolved_outcome": True, "resolution_note": "It won."})
    assert view == {"id": "x", "question": None, "resolution_criteria": None, "as_of_date": None}
    assert gs.VISIBLE_FIELDS == ("id", "question", "resolution_criteria", "as_of_date")
    assert not set(gs.VISIBLE_FIELDS) & set(gs.GRADER_ONLY_FIELDS)


# ------------------------------------------------------------------ leak lint
def test_leak_findings_structural():
    committed = _by_id()
    v1 = {q["id"]: q for q in _v1_copy(committed.values())}

    gop = gs.leak_findings(v1["us-senate-2024-gop"])
    assert gop == [{"code": "unreviewed_parenthetical", "field": "resolution_criteria", "text": "(they won 53)"}]
    dem = gs.leak_findings(v1["us-senate-2024-dem-hold"])
    assert {(f["code"], f["text"]) for f in dem} == {("extra_sentence", "They lost the majority."),
                                                      ("unreviewed_parenthetical", "(with VP tiebreak)")}
    # '(with VP tiebreak)' is a true criteria clause: allowed only when reviewed, verbatim
    assert gs.leak_findings(committed["us-senate-2024-dem-hold"]) == []
    for listed in ([], ["(with vp tiebreak)"], ["with VP tiebreak"]):
        row = dict(committed["us-senate-2024-dem-hold"], reviewed_parentheticals=listed)
        assert _codes(gs.leak_findings(row)) == ["unreviewed_parenthetical"], listed
    # the parenthetical rule covers the question too
    assert _codes(gs.leak_findings(v1["oscars-2024-oppenheimer"])) == ["unreviewed_parenthetical"]
    assert gs.leak_findings(v1["oscars-2024-oppenheimer"])[0]["field"] == "question"

    # whitelisting a leaking parenthetical still trips the note check
    whitelisted = dict(committed["us-senate-2024-gop"],
                       resolution_criteria=v1["us-senate-2024-gop"]["resolution_criteria"],
                       reviewed_parentheticals=["(they won 53)"])
    assert gs.leak_findings(whitelisted) == [{"code": "outcome_in_visible_text", "field": "resolution_criteria",
                                              "text": "(they won 53)"}]
    # a note sentence folded into the criteria without parentheses or a full stop
    folded = dict(committed["fed-2025-01-cut"], resolution_criteria=(
        "YES if the FOMC lowers the federal funds target range at its January 28-29, 2025 meeting, "
        "though it held rates steady."))
    assert _codes(gs.leak_findings(folded)) == ["outcome_in_visible_text"]

    # an evidence raw value in the visible text leaks; the rule's own threshold does not
    raw_leak = _v2_row(resolution_note=None, resolution_criteria=(
        "YES if the Blue caucus, which ended with 53 seats, holds >=51 Senate seats after the election."))
    assert gs.leak_findings(raw_leak) == [{"code": "outcome_in_visible_text", "field": "resolution_criteria",
                                           "text": "53"}]
    assert gs.leak_findings(_v2_row()) == []
    twice = dict(raw_leak, resolution_evidence=dict(_seat_evidence(53), raw_value={"seats": 53, "final": 53}))
    assert gs.leak_findings(twice) == gs.leak_findings(raw_leak)          # one finding per phrase and field
    big = _v2_row(resolution_note=None, resolution_evidence=_seat_evidence(100000),
                  resolution_criteria="YES if the Blue caucus holds >=51 seats after 100,000 ballots are counted.")
    assert _codes(gs.leak_findings(big)) == ["outcome_in_visible_text"]
    # a market settlement price (0/0.5/1) is not prose: ">=1 count" is not a leak
    market = _v2_row(resolution_note=None, resolution_evidence=_market_evidence(1.0),
                     resolution_criteria="YES if the jury returns a guilty verdict on >=1 count in 2030.")
    assert gs.leak_findings(market) == []

    # no marker-word list: "cut" and "convicted" in criteria are legitimate
    for question, criteria in (
            ("Will the Federal Reserve cut its policy rate in March 2030?",
             "YES if the FOMC cuts the federal funds target range at its March 2030 meeting."),
            ("Will the defendant be convicted in 2030?",
             "YES if the defendant is convicted on any count in 2030."),
            ("Will the U.S. Senate confirm the nominee?",
             "YES if the U.S. Senate confirms Donald J. Trump's nominee by Dec. 31, 2030.")):
        assert gs.leak_findings(_v2_row(question=question, resolution_criteria=criteria,
                                        resolution_note=None)) == [], criteria

    assert _codes(gs.leak_findings(_v2_row(resolution_criteria="Resolves YES if the caucus holds 51 seats."))) == [
        "criteria_not_yes_if"]
    assert _codes(gs.leak_findings(_v2_row(resolution_criteria="YES if the caucus holds (51 seats."))) == [
        "unbalanced_parenthesis"]
    assert _codes(gs.leak_findings(_v2_row(resolution_criteria="YES if it holds. NO otherwise."))) == [
        "extra_sentence"]
    assert gs.split_sentences("YES if X costs $3.5T. They won.") == ["YES if X costs $3.5T.", "They won."]
    # "No." is an abbreviation only before a numeral; the word "no" still ends its sentence
    assert gs.split_sentences("YES if Proposition No. 5 passes.") == ["YES if Proposition No. 5 passes."]
    assert gs.split_sentences("YES if the Senate vote is not no. It passed.") == [
        "YES if the Senate vote is not no.", "It passed."]
    assert _codes(gs.leak_findings(_v2_row(resolution_criteria="YES if the referendum result is no. It was."))) \
        == ["extra_sentence"]


# --------------------------------------------------------------- recompute
def test_recompute_label_kinds_and_pre_registered_tolerance():
    assert gs.recompute_label(_v2_row()) == "YES"                                     # 53 >= 51
    assert gs.recompute_label(_v2_row(resolution_evidence=_seat_evidence(50))) == "NO"
    numeric = dict(_seat_evidence(53), kind="numeric_threshold")
    assert gs.recompute_label(_v2_row(resolution_evidence=numeric)) == "YES"
    for price, label in ((1.0, "YES"), (0.0, "NO"), (0.5, "AMBIGUOUS"), (0.995, "YES"),
                         (0.7, "UNVERIFIABLE"), (1.5, "UNVERIFIABLE"), ("1.0", "UNVERIFIABLE")):
        assert gs.recompute_label(_v2_row(resolution_evidence=_market_evidence(price))) == label, price
    assert gs.recompute_label(_v2_row(resolution_evidence=None)) == "UNVERIFIABLE"
    assert gs.recompute_label(_v2_row(resolution_evidence={})) == "UNVERIFIABLE"
    assert gs.recompute_label(_v2_row(resolution_evidence=dict(_seat_evidence(53), raw_value={"votes": 9}))) \
        == "UNVERIFIABLE"

    def categorical(winner, comparator="==", threshold="Blue Party"):
        return _v2_row(resolution_evidence={
            "kind": "categorical", "source_url": "https://example.org/r", "raw_value": {"winner": winner},
            "rule": {"field": "winner", "comparator": comparator, "threshold": threshold}})
    assert gs.recompute_label(categorical("  blue   party ")) == "YES"
    assert gs.recompute_label(categorical("Red Party")) == "NO"
    assert gs.recompute_label(categorical("Red Party", "!=")) == "YES"
    assert gs.recompute_label(categorical("Red Party", "in", ["Red Party", "Green Party"])) == "YES"
    assert gs.recompute_label(categorical("Red Party", "not_in", ["Red Party"])) == "NO"
    assert gs.recompute_label(categorical(None)) == "UNVERIFIABLE"

    def occurrence(raw, **rule):
        return _v2_row(resolution_evidence={"kind": "event_occurrence", "source_url": "https://example.org/e",
                                            "raw_value": raw, "rule": rule or None})
    window = {"window_start": "2030-01-01", "window_end": "2030-12-31"}
    assert gs.recompute_label(occurrence({"occurred": True})) == "YES"
    assert gs.recompute_label(occurrence({"occurred": False})) == "NO"
    assert gs.recompute_label(occurrence({"occurred": True, "occurred_at": "2030-12-31T22:00:00Z"}, **window)) == "YES"
    assert gs.recompute_label(occurrence({"occurred": True, "occurred_at": "2031-01-01T00:00:01Z"}, **window)) == "NO"
    assert gs.recompute_label(occurrence({"occurred": True}, **window)) == "UNVERIFIABLE"

    # a numeric series reduced inside the window (touch question: max over 2030)
    series = [{"t": "2029-12-31", "v": 3.4}, {"t": "2030-06-05", "v": 3.01}, {"t": "2031-01-02", "v": 3.5}]

    def touched(threshold, aggregation="max"):
        return _v2_row(resolution_evidence={
            "kind": "numeric_threshold", "source_url": "https://example.org/cap", "raw_value": {"cap_tn": series},
            "rule": {"field": "cap_tn", "comparator": ">", "threshold": threshold, "aggregation": aggregation,
                     "window_start": "2030-01-01", "window_end": "2030-12-31"}})
    assert gs.recompute_label(touched(3.0)) == "YES"
    assert gs.recompute_label(touched(3.2)) == "NO"          # the 3.4 and 3.5 prints are outside the window
    assert gs.recompute_label(touched(0, "count")) == "YES"
    assert gs.recompute_label(touched(3.0, "value")) == "UNVERIFIABLE"   # a series needs an aggregation

    # dead band only from a pre-registered resolution_tolerance (inclusive, symmetric)
    near = _seat_evidence(51.4)
    assert gs.recompute_label(_v2_row(resolution_evidence=near)) == "YES"                 # default: no band
    band = {"epsilon_abs": 0.5, "basis": "provisional seat counts are revised by up to half a seat"}
    assert gs.recompute_label(_v2_row(resolution_evidence=near, resolution_tolerance=band)) == "AMBIGUOUS"
    assert gs.recompute_label(_v2_row(resolution_evidence=_seat_evidence(51.5),
                                      resolution_tolerance=band)) == "AMBIGUOUS"
    assert gs.recompute_label(_v2_row(resolution_evidence=_seat_evidence(51.6),
                                      resolution_tolerance=band)) == "YES"
    rel = {"epsilon_rel": 0.01, "basis": "1% revision band"}                              # eps = 0.51
    assert gs.recompute_label(_v2_row(resolution_evidence=_seat_evidence(50.5), resolution_tolerance=rel)) \
        == "AMBIGUOUS"
    # a band written next to the raw value is ignored by recompute and rejected by validation
    post_hoc = _v2_row(resolution_evidence=_seat_evidence(51.4, epsilon_abs=0.5))
    assert gs.recompute_label(post_hoc) == "YES"
    assert any("pre-registered" in e for e in gs.validate_question(post_hoc))
    both = {"epsilon_abs": 0.5, "epsilon_rel": 0.01, "basis": "x"}
    assert gs.recompute_label(_v2_row(resolution_evidence=near, resolution_tolerance=both)) == "UNVERIFIABLE"
    assert any("exactly one" in e for e in gs.validate_question(_v2_row(resolution_tolerance=both)))
    assert any("basis" in e for e in gs.validate_question(_v2_row(resolution_tolerance={"epsilon_abs": 0.5})))
    assert any("applies only" in e for e in gs.validate_question(
        _v2_row(resolution_evidence=_market_evidence(1.0), resolution_tolerance=band, resolution_note=None)))
    # registered before any evidence exists: allowed
    assert gs.validate_question(_v2_row(resolution_evidence=None, verification="unverified",
                                        resolution_tolerance=band)) == []

    # mismatch semantics: evidence that disagrees, or cannot recompute, is a data defect
    assert gs.recompute_mismatch(_v2_row()) is None
    assert "disagrees" in gs.recompute_mismatch(_v2_row(resolved_outcome=False))
    assert "UNVERIFIABLE" in gs.recompute_mismatch(_v2_row(resolution_evidence=_market_evidence(0.7)))
    void = _v2_row(scoring_status="ambiguous", resolved_outcome=None, resolution_evidence=_market_evidence(0.5))
    assert gs.recompute_mismatch(void) is None
    assert gs.recompute_mismatch(dict(void, resolution_evidence=_market_evidence(1.0))) is not None
    assert gs.recompute_mismatch(_v2_row(resolution_evidence=None)) is None

    from app.utils import prediction_markets as pm
    assert (gs.MARKET_SETTLED_YES, gs.MARKET_SETTLED_NO) == (pm._RESOLVED_PRICE_HI, pm._RESOLVED_PRICE_LO)


# ---------------------------------------------------------------- validation
def test_validate_rejects_as_of_equal_resolution():
    assert gs.validate_question(_v2_row()) == [] and gs.validate_question(_v2_row(), strict=True) == []
    same_day = _v2_row(as_of_date="2030-11-06")
    errors = gs.validate_question(same_day)
    assert any("strictly before resolution_date" in e for e in errors)
    assert any("after the end of the as_of day" in e for e in errors)
    assert any("strictly before" in e for e in gs.validate_question(_v2_row(as_of_date="2030-11-07")))

    for bad in ("2030-11-06T23:59:59+02:00", "2030-11-06T23:59:59", "2030-11-06", "soon"):
        assert any("resolve_time must be" in e for e in gs.validate_question(_v2_row(resolve_time=bad))), bad
    assert any("day-precision" in e for e in gs.validate_question(_v2_row(resolve_time="2030-11-06T12:00:00Z")))
    minute = _v2_row(resolve_time="2030-11-06T03:15:00Z", resolve_time_precision="minute")
    assert gs.validate_question(minute) == []
    early = _v2_row(as_of_date="2030-11-05", resolve_time="2030-11-05T23:59:59Z",
                    resolve_time_precision="minute")
    assert any("after the end of the as_of day" in e for e in gs.validate_question(early))

    missing = gs.validate_question({"id": "x", "resolved_outcome": True})
    for field in ("question", "resolution_criteria", "as_of_date", "resolve_time", "event_cluster"):
        assert f"missing required field {field!r}" in missing
    assert "resolved_outcome must be a boolean unless scoring_status is 'ambiguous'" in \
        gs.validate_question(_v2_row(resolved_outcome=None))
    assert gs.validate_question(_v2_row(scoring_status="ambiguous", resolved_outcome=None,
                                        resolution_evidence=_market_evidence(0.5), resolution_note=None)) == []
    assert gs.validate_question("row") == ["entry is not an object"]
    enum_errors = gs.validate_question(_v2_row(scoring_status="void", verification="checked",
                                               shift_axis="both", hindsight_framed="no"))
    assert len(enum_errors) == 4
    assert any("does not appear" in e for e in gs.validate_question(
        _v2_row(reviewed_parentheticals=["(stale clause)"])))
    assert any("source_url" in e for e in gs.validate_question(
        _v2_row(resolution_evidence=dict(_seat_evidence(53), source_url=""))))
    assert any("kind must be" in e for e in gs.validate_question(
        _v2_row(resolution_evidence=dict(_seat_evidence(53), kind="vibes"))))
    no_field = dict(_seat_evidence(53), rule={"comparator": ">=", "threshold": 51})
    assert any("rule.field must name" in e for e in gs.validate_question(_v2_row(resolution_evidence=no_field)))

    # strict: verified evidence required; every committed row is legacy_unverified
    for q in _committed()["questions"]:
        strict = gs.validate_question(q, strict=True)
        assert strict == ["strict: verification must be 'verified', got 'legacy_unverified'",
                          "strict: resolution_evidence is required"], q["id"]


# ------------------------------------------------------------ golden_eval load
def test_load_golden_set_v1_compat_and_recompute_mismatch_raises(tmp_path, monkeypatch):
    v1_rows = _v1_copy(_committed()["questions"])
    v1_path = _write(tmp_path / "v1.json", v1_rows)                  # bare list, leaking criteria: v1 loads as before
    assert ge.load_golden_file(v1_path) == (1, v1_rows)
    assert ge.load_golden_set(_write(tmp_path / "v1_meta.json", {"_meta": {"schema_version": 1},
                                                                  "questions": v1_rows})) == v1_rows
    v1_void = _write(tmp_path / "v1_void.json", {"questions": [
        {"id": "a", "scoring_status": "ambiguous", "resolved_outcome": None}]})
    with pytest.raises(ValueError, match="needs boolean 'resolved_outcome'"):
        ge.load_golden_set(v1_void)                                  # v1 keeps today's check

    clean = _v2_file(tmp_path / "clean.json", [_v2_row()])
    assert ge.load_golden_file(clean)[0] == 2
    void = _v2_file(tmp_path / "void.json", [_v2_row(), _v2_row(
        id="void-2030", scoring_status="ambiguous", resolved_outcome=None, resolution_note=None,
        resolution_evidence=_market_evidence(0.5))])
    assert [q["id"] for q in ge.load_golden_set(void)] == ["blue-senate-2030", "void-2030"]

    leaking = _v2_file(tmp_path / "leak.json", [_v2_row(
        resolution_criteria="YES if the Blue caucus holds >=51 Senate seats after the 2030 general election. "
                            "They won 53.")])
    with pytest.raises(ValueError, match=r"'blue-senate-2030' breaks the schema v2 contract.*extra_sentence"):
        ge.load_golden_set(leaking)
    with pytest.raises(ValueError, match="strictly before"):
        ge.load_golden_set(_v2_file(tmp_path / "same_day.json", [_v2_row(as_of_date="2030-11-06")]))
    with pytest.raises(ValueError, match="unsupported golden _meta.schema_version 3"):
        ge.load_golden_set(_write(tmp_path / "v3.json", {"_meta": {"schema_version": 3}, "questions": v1_rows}))

    mismatch = _v2_file(tmp_path / "mismatch.json", [_v2_row(resolution_evidence=_seat_evidence(49))])
    with pytest.raises(gs.RecomputeMismatchError, match=r"'blue-senate-2030'.*recomputed label NO.*YES"):
        ge.load_golden_set(mismatch)
    assert issubclass(gs.RecomputeMismatchError, ValueError)
    v1_evidence = _write(tmp_path / "v1_evidence.json", {"questions": [
        {"id": "e1", "resolved_outcome": True, "resolution_evidence": _seat_evidence(49)}]})
    with pytest.raises(gs.RecomputeMismatchError, match="'e1'"):
        ge.load_golden_set(v1_evidence)                              # evidence is checked in any schema
    fpath = _write(tmp_path / "forecast.json", {"binary_forecasts": [{"id": "blue-senate-2030", "probability": 0.7}]})
    out = tmp_path / "never.json"
    monkeypatch.setattr(sys, "argv", ["golden_eval.py", "score-forecast-file", "--forecast", fpath,
                                      "--golden", mismatch, "-o", str(out)])
    assert ge.main() == ge.EXIT_RECOMPUTE_MISMATCH == 4              # fail loud, nothing written
    assert not out.exists()
    monkeypatch.setattr(sys, "argv", ["golden_eval.py", "score-forecast-file", "--forecast", fpath,
                                      "--golden", clean, "-o", str(out)])
    assert ge.main() == 0 and out.exists()


def test_v1_score_report_byte_identical_to_pre_eval9(tmp_path):
    """A v1 golden file scores to exactly the bytes the pre-EVAL-9 code wrote (no new keys)."""
    golden = {"questions": [
        {"id": "q1", "question": "Q1?", "resolution_criteria": "x", "resolved_outcome": True,
         "resolution_date": "2024-11-06", "category": "elections", "difficulty": "easy", "as_of_date": "2024-11-01"},
        {"id": "q2", "question": "Q2?", "resolution_criteria": "x", "resolved_outcome": False,
         "resolution_date": "2024-11-06", "category": "elections", "difficulty": "easy", "as_of_date": "2024-11-01"},
        {"id": "q3", "question": "Q3?", "resolution_criteria": "x", "resolved_outcome": True,
         "resolution_date": "2024-12-05", "category": "markets", "difficulty": "hard", "as_of_date": "2024-01-01"},
        {"id": "q4", "question": "Q4?", "resolution_criteria": "x", "resolved_outcome": False,
         "resolution_date": "2024-08-01", "category": "markets", "difficulty": "medium", "as_of_date": "2024-06-01"},
        {"id": "q5", "question": "Q5?", "resolution_criteria": "x", "resolved_outcome": True,
         "resolution_date": "2024-06-01", "category": "sports", "difficulty": "medium", "as_of_date": "2024-05-01"},
    ]}
    fc = {"binary_forecasts": [
        {"id": "q1", "probability": 0.9}, {"id": "q2", "probability": 0.5}, {"id": "q3", "probability": 0.4},
        {"id": "q4", "probability": 0.75}, {"id": "q5", "probability": 0.62}, {"id": "zzz", "probability": 0.3}]}
    gpath, fpath = _write(tmp_path / "golden.json", golden), _write(tmp_path / "forecast.json", fc)
    out, md = tmp_path / "r.json", tmp_path / "r.md"
    assert ge.cmd_score_forecast_file(SimpleNamespace(forecast=fpath, golden=gpath, bins=10, out=str(out),
                                                      markdown=str(md), to_ledger=False, ledger_dir=None,
                                                      bootstrap=0)) == 0
    report = json.loads(out.read_text(encoding="utf-8"))
    assert "exclusions" not in report
    report["forecast_path"], report["golden_path"] = "<forecast>", "<golden>"
    canon = json.dumps(report, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    assert hashlib.sha256(canon.encode("utf-8")).hexdigest() == PRE_EVAL9_V1_REPORT_SHA256
    text = md.read_text(encoding="utf-8").replace(fpath, "<forecast>").replace(gpath, "<golden>")
    assert hashlib.sha256(text.encode("utf-8")).hexdigest() == PRE_EVAL9_V1_MARKDOWN_SHA256


# ---------------------------------------------------------------- exclusions
def test_ambiguous_rows_excluded_from_scoring(tmp_path):
    rows = [_v2_row(id="q-yes"),
            _v2_row(id="q-no", resolved_outcome=False, resolution_evidence=_seat_evidence(49),
                    resolution_note="They won 49."),
            _v2_row(id="q-void", scoring_status="ambiguous", resolved_outcome=None, resolution_note=None,
                    resolution_evidence=_market_evidence(0.5))]
    gpath = _v2_file(tmp_path / "golden.json", rows)
    index = ge.index_golden(ge.load_golden_set(gpath))
    match = ge.match_forecasts([{"id": "q-yes", "probability": 0.8}, {"id": "q-void", "probability": 0.9},
                                {"id": "q-no", "probability": 0.3}, {"id": "zzz", "probability": 0.5}], index)
    assert [r["id"] for r in match["matched"]] == ["q-yes", "q-no"]
    assert match["exclusions"] == {"ambiguous": ["q-void"]}
    assert match["unmatched_golden_ids"] == [] and match["unmatched_forecast_ids"] == ["zzz"]
    assert match["duplicate_forecast_ids"] == [] and match["invalid_probability_ids"] == []
    # listed even when no forecast names it; never an "unmatched" golden id
    only_yes = ge.match_forecasts([{"id": "q-yes", "probability": 0.8}], index)
    assert only_yes["exclusions"] == {"ambiguous": ["q-void"]} and only_yes["unmatched_golden_ids"] == ["q-no"]

    fpath = _write(tmp_path / "forecast.json", {"binary_forecasts": [
        {"id": "q-yes", "probability": 0.8}, {"id": "q-void", "probability": 0.9}, {"id": "q-no", "probability": 0.3}]})
    out, md, ledger = tmp_path / "r.json", tmp_path / "r.md", str(tmp_path / "eval_ledger")
    assert ge.cmd_score_forecast_file(SimpleNamespace(forecast=fpath, golden=gpath, bins=10, out=str(out),
                                                      markdown=str(md), to_ledger=True, ledger_dir=ledger,
                                                      bootstrap=0)) == 0
    report = json.loads(out.read_text(encoding="utf-8"))
    assert report["metrics"]["n"] == 2 and report["golden_count"] == 3
    assert report["exclusions"] == {"ambiguous": ["q-void"]}
    assert report["metrics"]["mean_brier"] == pytest.approx((0.04 + 0.09) / 2, abs=1e-4)
    assert "- excluded, ambiguous resolution (never scored): q-void" in md.read_text(encoding="utf-8")
    assert sorted(e["question_id"] for e in read_ledger(ledger)) == ["q-no", "q-yes"]   # never ledgered

    # a v2 set without ambiguous rows still reports an (empty) exclusions block
    const = _write(tmp_path / "const.json", {"binary_forecasts": [
        {"id": q["id"], "probability": 0.8} for q in _committed()["questions"]]})
    out2 = tmp_path / "committed.json"
    assert ge.cmd_score_forecast_file(SimpleNamespace(forecast=const, golden=ge.GOLDEN_PATH, bins=10, out=str(out2),
                                                      markdown=None, to_ledger=False, ledger_dir=None,
                                                      bootstrap=0)) == 0
    committed = json.loads(out2.read_text(encoding="utf-8"))
    assert committed["exclusions"] == {"ambiguous": []} and committed["metrics"]["n"] == 30
    assert committed["metrics"]["rigor"]["n_clusters"] == 23          # event clusters drive the bootstrap


# ------------------------------------------------------------------- audit CLI
def test_golden_curate_audit_exit_codes(tmp_path, capsys):
    out = tmp_path / "golden_audit.json"
    assert gc.main(["audit", "-o", str(out), "--markdown"]) == gc.EXIT_OK == 0
    report = json.loads(out.read_text(encoding="utf-8"))
    assert (report["schema_version"], report["n_questions"], report["strict"]) == (2, 30, False)
    assert report["n_violations"] == 0 and report["leaks"]["n_rows_with_findings"] == 0
    assert report["verification"] == {"legacy_unverified": 30}
    assert report["recompute"]["n_evidence_backed"] == 0
    assert report["balance"]["n_event_clusters"] == 23 and report["balance"]["yes_rate"] == 0.8
    md = (tmp_path / "golden_audit.md").read_text(encoding="utf-8")
    assert md.startswith("# Golden-set audit") and "mode: report-only" in md

    strict_out = tmp_path / "strict.json"
    assert gc.main(["audit", "--strict", "-o", str(strict_out)]) == gc.EXIT_STRICT_VIOLATIONS == 2
    strict = json.loads(strict_out.read_text(encoding="utf-8"))
    assert strict["n_violations"] == 30 and strict["leaks"]["n_rows_with_findings"] == 0
    assert all("strict: verification must be 'verified'" in errs[0]
               for errs in strict["validation"]["errors"].values())

    # a v1 copy: the leaking rows are reported; --strict exits 2
    questions = _committed()["questions"]
    v1_path = _write(tmp_path / "golden_v1.json", {"questions": _v1_copy(questions)})
    v1_out, v1_md = tmp_path / "v1_audit.json", tmp_path / "v1_audit.md"
    assert gc.main(["audit", "--golden", v1_path, "-o", str(v1_out), "--markdown", str(v1_md)]) == 0
    v1 = json.loads(v1_out.read_text(encoding="utf-8"))
    assert v1["schema_version"] == 1
    leaking = set(v1["leaks"]["findings"])
    assert {q["id"] for q in questions if q["resolution_note"]} <= leaking               # all 25 outcome rows
    assert leaking - {q["id"] for q in questions if q["resolution_note"]} == {
        "id-pres-2024-prabowo", "oscars-2024-oppenheimer"}                               # unreviewed clauses
    assert v1["leaks"]["findings"]["us-senate-2024-gop"][0]["text"] == "(they won 53)"
    assert "| us-senate-2024-dem-hold | extra_sentence | resolution_criteria | They lost the majority. |" in \
        v1_md.read_text(encoding="utf-8")
    assert gc.main(["audit", "--golden", v1_path, "--strict", "-o", str(v1_out)]) == 2

    # verified, evidence-backed, leak-free rows pass --strict; a recompute mismatch does not
    good = _v2_file(tmp_path / "good.json", [_v2_row(), _v2_row(
        id="void-2030", scoring_status="ambiguous", resolved_outcome=None, resolution_note=None,
        resolution_evidence=_market_evidence(0.5), event_cluster="void-2030")])
    good_out = tmp_path / "good_audit.json"
    assert gc.main(["audit", "--golden", good, "--strict", "-o", str(good_out)]) == 0
    good_report = json.loads(good_out.read_text(encoding="utf-8"))
    assert good_report["recompute"]["labels"] == {"blue-senate-2030": "YES", "void-2030": "AMBIGUOUS"}
    assert good_report["recompute"]["mismatches"] == {} and good_report["violation_ids"] == []
    bad = _v2_file(tmp_path / "bad.json", [_v2_row(resolution_evidence=_seat_evidence(49))])
    bad_out = tmp_path / "bad_audit.json"
    assert gc.main(["audit", "--golden", bad, "-o", str(bad_out)]) == 0                  # report-only
    assert "recomputed label NO" in json.loads(bad_out.read_text(encoding="utf-8"))["recompute"]["mismatches"][
        "blue-senate-2030"]
    assert gc.main(["audit", "--golden", bad, "--strict", "-o", str(bad_out)]) == 2
    dup = _v2_file(tmp_path / "dup.json", [_v2_row(), _v2_row()])
    assert gc.main(["audit", "--golden", dup, "--strict", "-o", str(bad_out)]) == 2
    assert json.loads(bad_out.read_text(encoding="utf-8"))["duplicate_ids"] == ["blue-senate-2030"]

    assert gc.main(["audit", "--golden", str(tmp_path / "missing.json")]) == gc.EXIT_UNREADABLE == 1
    assert gc.main(["audit", "--golden", _write(tmp_path / "v9.json", {"_meta": {"schema_version": 9},
                                                                       "questions": [_v2_row()]})]) == 1
    capsys.readouterr()
    assert gc.main(["audit", "--golden", good]) == 0                                     # no -o: JSON on stdout
    assert json.loads(capsys.readouterr().out)["mode"] == "golden-audit"
